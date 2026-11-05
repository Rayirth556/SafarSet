"""Event log + state projection on the real generated scenario (seed 42): lifecycle, rules from the owner's
review (rule 7 buffer protection, rule 8 staleness), displacement, and replay equivalence."""
import json

import pytest

from safarset.db.conn import new_db
from safarset.db.invariants import check_invariants, state_dump
from safarset.events.apply import apply_event, replay
from safarset.events.reducers import BufferRejected, Rejected, StaleBatch, batch_is_stale
from safarset.sim.generator import generate


@pytest.fixture(scope="module")
def scenario():
    return generate(42)


@pytest.fixture()
def db(scenario):
    c = new_db()
    apply_event(c, "SCENARIO_LOADED", "sim", {"scenario": scenario})
    return c


@pytest.fixture()
def cancelled(db):
    apply_event(db, "TRAIN_CANCELLED", "sim", {"vehicle_id": "TRAIN-SIM-CXL"}, ts_sim=840)
    return db


def q(c, sql, *a):
    return c.execute(sql, a).fetchall()


def one(c, sql, *a):
    return c.execute(sql, a).fetchone()[0]


def dest_range(c, vehicle_id, place):
    """(board_idx, alight_idx) of the first stop after boarding that serves `place`."""
    for r in q(c, "SELECT seq, serves_places FROM vehicle_stops WHERE vehicle_id = ? AND seq > 0 ORDER BY seq", vehicle_id):
        if place in json.loads(r["serves_places"]):
            return 0, r["seq"]
    raise AssertionError(f"{vehicle_id} does not serve {place}")


def groups_for(c, place, n=None, max_total=None):
    out, total = [], 0
    for g in q(c, "SELECT group_id, size FROM groups WHERE dest_place = ? AND affected = 1 AND wheelchair_free = 1 ORDER BY group_id", place) \
            if False else q(c, "SELECT group_id, size FROM groups WHERE dest_place = ? AND affected = 1 ORDER BY group_id", place):
        if max_total is not None and total + g["size"] > max_total:
            continue
        out.append(g["group_id"])
        total += g["size"]
        if n and len(out) >= n:
            break
    return out


def plan(c, batch_id, pool_id, vehicle_id, place, group_ids, scores=None, **extra):
    lo, hi = dest_range(c, vehicle_id, place)
    base = one(c, "SELECT MAX(seq) FROM events")
    allocs = [{"group_id": g, "pool_id": pool_id, "board_idx": lo, "alight_idx": hi,
               "score": (scores or {}).get(g, 1.0), "reason": {"why": "test", "pool": pool_id}} for g in group_ids]
    return apply_event(c, "PLAN_PROPOSED", "system", {"batch_id": batch_id, "base_seq": base, "allocations": allocs,
                                                      "items": [{"kind": "PLACED", "group_id": g} for g in group_ids], **extra})


def states(c):
    return {r["state"]: r["n"] for r in q(c, "SELECT state, COUNT(*) n FROM v_group_state GROUP BY state")}


BUS, BUS_POOL = "BUS-SPL-02", "BUS-SPL-02:UR"      # Avadi special, nominal 40 x 75% = 30 seats


# ------------------------------------------------------------------------------------------------- loading
def test_scenario_loads_with_caps_and_clean_invariants(db, scenario):
    assert one(db, "SELECT COUNT(*) FROM groups") == len(scenario["groups"])
    assert one(db, "SELECT SUM(size) FROM groups") == 300
    for v in scenario["vehicles"]:
        for p in v["pools"]:
            got = [r["cap"] for r in q(db, "SELECT cap FROM segment_capacity WHERE pool_id = ? ORDER BY seg_idx", p["pool_id"])]
            assert got == [s["cap"] for s in p["segments"]]
    assert check_invariants(db) == []
    assert states(db) == {"UNAFFECTED": len(scenario["groups"])}
    with pytest.raises(Rejected):
        apply_event(db, "SCENARIO_LOADED", "sim", {"scenario": scenario})


def test_cancellation_marks_every_stranded_group_unresolved(cancelled):
    assert states(cancelled) == {"UNRESOLVED": one(cancelled, "SELECT COUNT(*) FROM groups")}
    assert one(cancelled, "SELECT status FROM vehicles WHERE vehicle_id = 'TRAIN-SIM-CXL'") == "CANCELLED"


# ------------------------------------------------------------------------------------------------- plan lifecycle
def test_plan_then_approval_moves_states_and_keeps_invariants(cancelled):
    gs = groups_for(cancelled, "AVADI", max_total=20)
    plan(cancelled, "B1", BUS_POOL, BUS, "AVADI", gs)
    assert states(cancelled)["TENTATIVE"] == len(gs)
    assert check_invariants(cancelled) == []
    apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    assert states(cancelled)["CONFIRMED"] == len(gs) and "TENTATIVE" not in states(cancelled)
    assert one(cancelled, "SELECT status FROM plan_batches WHERE batch_id='B1'") == "APPROVED"
    assert check_invariants(cancelled) == []
    # reasons are stored machine-readable with each allocation
    assert json.loads(one(cancelled, "SELECT reason FROM allocations LIMIT 1"))["why"] == "test"


def test_overselling_plan_is_rejected_by_the_database_with_no_partial_state(cancelled):
    gs = groups_for(cancelled, "AVADI")                         # more heads than the bus's 30 buffered seats
    assert sum(one(cancelled, "SELECT size FROM groups WHERE group_id = ?", g) for g in gs) > 30
    before = (state_dump(cancelled), one(cancelled, "SELECT COUNT(*) FROM events"))
    with pytest.raises(Rejected, match="database rejected"):
        plan(cancelled, "BIG", BUS_POOL, BUS, "AVADI", gs)
    after = state_dump(cancelled)
    assert after["allocations"] == before[0]["allocations"] and after["segment_capacity"] == before[0]["segment_capacity"]
    assert after["plan_batches"] == []
    last = q(cancelled, "SELECT type, payload FROM events ORDER BY seq DESC LIMIT 2")
    assert last[0]["type"] == "COMMAND_REJECTED" and "PLAN_PROPOSED" in last[0]["payload"]
    assert last[1]["type"] != "PLAN_PROPOSED"                   # the refused plan itself was not logged
    assert check_invariants(cancelled) == []


def test_new_plan_supersedes_pending_batch_and_never_moves_confirmed(cancelled):
    g1, g2 = groups_for(cancelled, "AVADI", n=2)
    plan(cancelled, "B1", BUS_POOL, BUS, "AVADI", [g1])
    plan(cancelled, "B2", BUS_POOL, BUS, "AVADI", [g1, g2])
    assert one(cancelled, "SELECT status FROM plan_batches WHERE batch_id='B1'") == "SUPERSEDED"
    assert one(cancelled, "SELECT COUNT(*) FROM allocations WHERE status='TENTATIVE'") == 2
    assert one(cancelled, "SELECT COUNT(*) FROM allocations WHERE status='RELEASED'") == 1
    apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B2"})
    confirmed = one(cancelled, "SELECT id FROM allocations WHERE status='CONFIRMED' LIMIT 1")
    with pytest.raises(Rejected, match="never moves CONFIRMED"):
        plan(cancelled, "B3", BUS_POOL, BUS, "AVADI", [], release=[confirmed])
    with pytest.raises(Rejected, match="not pending"):
        apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B1"})


def test_unaffected_groups_cannot_be_planned(db):
    g = one(db, "SELECT group_id FROM groups LIMIT 1")
    with pytest.raises(Rejected, match="not affected"):
        plan(db, "B1", BUS_POOL, BUS, "AVADI", [g])


# ------------------------------------------------------------------------------------------------- rule 8: staleness
def test_staleness_only_when_an_event_touches_the_batch_footprint(cancelled):
    train = "TRAIN-SIM-ALT-1"
    pools = {r["class"]: r["pool_id"] for r in q(cancelled, "SELECT pool_id, class FROM pools WHERE vehicle_id = ?", train)}
    gs = groups_for(cancelled, "ARAKKONAM", max_total=2)
    sl = pools["SL"]
    lo, hi = dest_range(cancelled, train, "ARAKKONAM")                      # footprint: SL segments [0, hi)
    plan(cancelled, "B1", sl, train, "ARAKKONAM", gs)
    # unrelated: another vehicle's capacity, a field flag, a delay of another vehicle, a settings change elsewhere
    apply_event(cancelled, "NOSHOWS_REPORTED", "field", {"vehicle_id": "TRAIN-SIM-ALT-2", "pool_id": "TRAIN-SIM-ALT-2:SL",
                                                          "seats_freed": 2, "from_seg": 0, "to_seg": 2})
    apply_event(cancelled, "LOAD_REPORT", "field", {"vehicle_id": BUS, "pool_id": BUS_POOL, "level": "FULL", "count": 40})
    apply_event(cancelled, "BUFFER_CHANGED", "operator", {"mode": "MTC_BUS", "buffer_pct": 0.8})
    # same pool, but segments OUTSIDE the footprint
    nseg = one(cancelled, "SELECT COUNT(*) FROM segment_capacity WHERE pool_id = ?", sl)
    assert hi < nseg
    apply_event(cancelled, "NOSHOWS_REPORTED", "field", {"vehicle_id": train, "pool_id": sl, "seats_freed": 1,
                                                          "from_seg": hi, "to_seg": nseg})
    assert not batch_is_stale(cancelled, "B1")
    # now an event inside the footprint
    apply_event(cancelled, "NOSHOWS_REPORTED", "field", {"vehicle_id": train, "pool_id": sl, "seats_freed": 1,
                                                          "from_seg": 0, "to_seg": 1})
    assert batch_is_stale(cancelled, "B1")
    with pytest.raises(StaleBatch, match="Re-plan"):
        apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    assert one(cancelled, "SELECT status FROM plan_batches WHERE batch_id='B1'") == "PROPOSED"   # still pending
    # re-planning gives a fresh, approvable batch
    plan(cancelled, "B2", sl, train, "ARAKKONAM", gs)
    apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B2"})
    assert check_invariants(cancelled) == []


# ------------------------------------------------------------------------------------------------- rule 7: buffers
def _fill_bus(c, confirm_total, tentative_total):
    gs = groups_for(c, "AVADI", max_total=confirm_total)
    plan(c, "B1", BUS_POOL, BUS, "AVADI", gs)
    apply_event(c, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    gt = [g for g in groups_for(c, "AVADI", max_total=confirm_total + tentative_total) if g not in gs]
    t_total = 0
    chosen = []
    for g in gt:
        size = one(c, "SELECT size FROM groups WHERE group_id=?", g)
        if t_total + size <= tentative_total:
            chosen.append(g)
            t_total += size
    plan(c, "B2", BUS_POOL, BUS, "AVADI", chosen)
    return gs, chosen


def test_buffer_cannot_drop_below_confirmed_plus_boarded(cancelled):
    gs, _ = _fill_bus(cancelled, 24, 0)
    firm = sum(one(cancelled, "SELECT size FROM groups WHERE group_id=?", g) for g in gs)
    before = state_dump(cancelled)
    # 40 seats x 50% = 20 < firm (>=20?) -> make sure it is really below
    pct = (firm - 1) / 40
    with pytest.raises(BufferRejected, match="never displaced by a settings change"):
        apply_event(cancelled, "BUFFER_CHANGED", "operator", {"mode": "MTC_BUS", "buffer_pct": pct})
    after = state_dump(cancelled)
    assert after["allocations"] == before["allocations"] and after["segment_capacity"] == before["segment_capacity"]
    assert after["settings"] == before["settings"]
    assert check_invariants(cancelled) == []


def test_buffer_lowering_releases_tentative_but_never_confirmed(cancelled):
    gs, tent = _fill_bus(cancelled, 14, 14)
    firm = sum(one(cancelled, "SELECT size FROM groups WHERE group_id=?", g) for g in gs)
    assert tent
    apply_event(cancelled, "BUFFER_CHANGED", "operator", {"mode": "MTC_BUS", "buffer_pct": firm / 40})
    assert one(cancelled, "SELECT COUNT(*) FROM allocations WHERE status='CONFIRMED'") == len(gs)
    assert one(cancelled, "SELECT COUNT(*) FROM allocations WHERE status='TENTATIVE'") == 0
    assert one(cancelled, "SELECT COUNT(*) FROM allocations WHERE status='RELEASED'") == len(tent)
    assert one(cancelled, "SELECT value FROM settings WHERE key='buffers'").count("MTC_BUS") == 1
    assert json.loads(one(cancelled, "SELECT value FROM settings WHERE key='buffers'"))["MTC_BUS"] == firm / 40
    assert check_invariants(cancelled) == []


def test_buffer_raise_grows_capacity(cancelled):
    before = one(cancelled, "SELECT MAX(cap) FROM segment_capacity WHERE pool_id = ?", BUS_POOL)
    apply_event(cancelled, "BUFFER_CHANGED", "operator", {"mode": "MTC_BUS", "buffer_pct": 0.9})
    assert before == 30 and one(cancelled, "SELECT MAX(cap) FROM segment_capacity WHERE pool_id = ?", BUS_POOL) == 36
    with pytest.raises(Rejected):
        apply_event(cancelled, "BUFFER_CHANGED", "operator", {"mode": "NO_SUCH_MODE", "buffer_pct": 0.5})
    with pytest.raises(Rejected):
        apply_event(cancelled, "BUFFER_CHANGED", "operator", {"mode": "MTC_BUS", "buffer_pct": 1.5})


# ------------------------------------------------------------------------------------------------- field feeds, displacement
def _reserved_pool_with_two_groups(c):
    train = "TRAIN-SIM-ALT-1"
    pool = f"{train}:SL"
    gs = groups_for(c, "ARAKKONAM", max_total=6)
    return train, pool, gs


def test_vacancy_cut_releases_tentative_before_displacing_confirmed(cancelled):
    train, pool, gs = _reserved_pool_with_two_groups(cancelled)
    assert len(gs) >= 3
    lo, hi = dest_range(cancelled, train, "ARAKKONAM")
    plan(cancelled, "B1", pool, train, "ARAKKONAM", gs[:2], scores={gs[0]: 9.0, gs[1]: 1.0})
    apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    plan(cancelled, "B2", pool, train, "ARAKKONAM", [gs[2]], scores={gs[2]: 5.0})
    held = sum(one(cancelled, "SELECT size FROM groups WHERE group_id=?", g) for g in gs[:3])
    confirmed_heads = sum(one(cancelled, "SELECT size FROM groups WHERE group_id=?", g) for g in gs[:2])
    # TTE: only `confirmed_heads` berths are really vacant -> tentative goes first, confirmed stay
    apply_event(cancelled, "VACANCY_UPDATE", "field", {"pool_id": pool, "from_seg": 0, "to_seg": hi, "vacancy": confirmed_heads})
    st = {r["group_id"]: r["status"] for r in q(cancelled, "SELECT group_id, status FROM allocations")}
    assert st[gs[2]] == "RELEASED" and st[gs[0]] == st[gs[1]] == "CONFIRMED"
    # a further cut displaces the LOWER-scored confirmed group first
    smaller = one(cancelled, "SELECT size FROM groups WHERE group_id=?", gs[0])
    apply_event(cancelled, "VACANCY_UPDATE", "field", {"pool_id": pool, "from_seg": 0, "to_seg": hi, "vacancy": smaller})
    st = {r["group_id"]: r["status"] for r in q(cancelled, "SELECT group_id, status FROM allocations")}
    assert st[gs[1]] == "DISPLACED" and st[gs[0]] == "CONFIRMED"
    assert one(cancelled, "SELECT state FROM v_group_state WHERE group_id=?", gs[1]) == "UNRESOLVED"   # back in the pool
    assert held > confirmed_heads > 0
    assert check_invariants(cancelled) == []


def test_boarded_passengers_are_never_shed(cancelled):
    train, pool, gs = _reserved_pool_with_two_groups(cancelled)
    lo, hi = dest_range(cancelled, train, "ARAKKONAM")
    plan(cancelled, "B1", pool, train, "ARAKKONAM", gs[:1])
    apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    aid = one(cancelled, "SELECT id FROM allocations")
    with pytest.raises(Rejected, match="unknown allocation"):
        apply_event(cancelled, "PASSENGER_BOARDED", "field", {"allocation_id": 9999})
    apply_event(cancelled, "PASSENGER_BOARDED", "field", {"allocation_id": aid})
    with pytest.raises(Rejected):
        apply_event(cancelled, "VACANCY_UPDATE", "field", {"pool_id": pool, "from_seg": 0, "to_seg": hi, "vacancy": 0})
    with pytest.raises(Rejected, match="only CONFIRMED"):
        apply_event(cancelled, "PASSENGER_DISPLACED", "field", {"allocation_id": aid, "reason": "overcrowded"})
    assert one(cancelled, "SELECT status FROM allocations") == "BOARDED"
    assert check_invariants(cancelled) == []


def test_displacing_a_confirmed_passenger_frees_seats_and_needs_a_reason(cancelled):
    gs = groups_for(cancelled, "AVADI", max_total=10)
    plan(cancelled, "B1", BUS_POOL, BUS, "AVADI", gs)
    apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    aid = one(cancelled, "SELECT id FROM allocations ORDER BY id LIMIT 1")
    used_before = one(cancelled, "SELECT MAX(used) FROM segment_capacity WHERE pool_id = ?", BUS_POOL)
    with pytest.raises(Rejected):
        apply_event(cancelled, "PASSENGER_DISPLACED", "field", {"allocation_id": aid, "reason": ""})
    apply_event(cancelled, "PASSENGER_DISPLACED", "field", {"allocation_id": aid, "reason": "bus overcrowded before boarding"})
    assert one(cancelled, "SELECT MAX(used) FROM segment_capacity WHERE pool_id = ?", BUS_POOL) < used_before
    assert one(cancelled, "SELECT status FROM allocations WHERE id=?", aid) == "DISPLACED"


def test_cancelling_an_alternate_train_sheds_its_holders(cancelled):
    train, pool, gs = _reserved_pool_with_two_groups(cancelled)
    plan(cancelled, "B1", pool, train, "ARAKKONAM", gs[:2])
    apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    apply_event(cancelled, "TRAIN_CANCELLED", "sim", {"vehicle_id": train})
    assert one(cancelled, "SELECT COUNT(*) FROM allocations WHERE status = 'DISPLACED'") == 2
    assert one(cancelled, "SELECT MAX(cap) FROM segment_capacity WHERE pool_id LIKE ?", train + ":%") == 0
    assert check_invariants(cancelled) == []


def test_load_report_flags_freezes_and_restores_capacity(cancelled):
    caps = lambda: [r["cap"] for r in q(cancelled, "SELECT cap FROM segment_capacity WHERE pool_id = ? ORDER BY seg_idx", BUS_POOL)]
    assert max(caps()) == 30
    apply_event(cancelled, "LOAD_REPORT", "field", {"vehicle_id": BUS, "pool_id": BUS_POOL, "level": "OVERCROWDED", "count": 52})
    assert tuple(one_row(cancelled, "SELECT level, count FROM field_reports")) == ("OVERCROWDED", 52)
    assert max(caps()) == 0                                   # nobody confirmed or boarded: nothing more can be accepted
    apply_event(cancelled, "BUFFER_CHANGED", "operator", {"mode": "MTC_BUS", "buffer_pct": 0.9})
    assert max(caps()) == 0                                   # a settings change does not lift a field freeze
    apply_event(cancelled, "LOAD_REPORT", "field", {"vehicle_id": BUS, "pool_id": BUS_POOL, "level": "NORMAL", "count": 20})
    assert max(caps()) == 36                                  # freeze lifted; the new 90% buffer applies (floor(40 x 0.9))
    assert check_invariants(cancelled) == []


def test_overcrowded_report_displaces_confirmed_groups_without_physical_room(cancelled):
    gs = groups_for(cancelled, "AVADI", max_total=12)
    plan(cancelled, "B1", BUS_POOL, BUS, "AVADI", gs, scores={g: float(i) for i, g in enumerate(gs, 1)})
    apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    aid = {r["group_id"]: r["id"] for r in q(cancelled, "SELECT id, group_id FROM allocations")}
    # a conductor sees 40 people for 40 seats: no physical room for any confirmed (unboarded) group
    apply_event(cancelled, "LOAD_REPORT", "field", {"vehicle_id": BUS, "pool_id": BUS_POOL, "level": "OVERCROWDED", "count": 40})
    assert {r["status"] for r in q(cancelled, "SELECT status FROM allocations")} == {"DISPLACED"}
    assert one(cancelled, "SELECT MAX(used) FROM segment_capacity WHERE pool_id = ?", BUS_POOL) == 0
    assert all(json.loads(r["status_reason"])["cause"] == "LOAD_REPORT" for r in q(cancelled, "SELECT status_reason FROM allocations"))
    assert len(aid) == len(gs) and check_invariants(cancelled) == []


def test_partial_room_displaces_only_the_lowest_priority_groups(cancelled):
    gs = groups_for(cancelled, "AVADI", max_total=12)
    scores = {g: float(i) for i, g in enumerate(gs, 1)}       # later = higher priority
    plan(cancelled, "B1", BUS_POOL, BUS, "AVADI", gs, scores=scores)
    apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    sizes = {g: one(cancelled, "SELECT size FROM groups WHERE group_id=?", g) for g in gs}
    room = sizes[gs[-1]]                                      # exactly enough room for the highest-priority group
    apply_event(cancelled, "LOAD_REPORT", "field", {"vehicle_id": BUS, "pool_id": BUS_POOL, "level": "OVERCROWDED", "count": 40 - room})
    kept = [r["group_id"] for r in q(cancelled, "SELECT group_id FROM allocations WHERE status='CONFIRMED'")]
    assert kept == [gs[-1]] and sum(sizes[g] for g in kept) <= room
    assert check_invariants(cancelled) == []


def one_row(c, sql):
    return c.execute(sql).fetchone()


# ------------------------------------------------------------------------------------------------- audit rules
def test_operator_override_requires_a_reason_and_refusals_are_logged(cancelled):
    g = one(cancelled, "SELECT group_id FROM groups LIMIT 1")
    with pytest.raises(Rejected, match="requires a reason"):
        apply_event(cancelled, "OPERATOR_OVERRIDE", "operator", {"group_id": g, "action": "UNASSIGN", "reason": "  "})
    assert one(cancelled, "SELECT type FROM events ORDER BY seq DESC LIMIT 1") == "COMMAND_REJECTED"
    apply_event(cancelled, "OPERATOR_OVERRIDE", "operator", {"group_id": g, "action": "UNASSIGN", "reason": "medical escort request"})
    assert "medical escort request" in one(cancelled, "SELECT payload FROM events ORDER BY seq DESC LIMIT 1")


def test_unknown_and_malformed_events_are_rejected(db):
    with pytest.raises(Rejected, match="unknown event type"):
        apply_event(db, "MAKE_IT_RAIN", "operator", {})
    with pytest.raises(Rejected, match="invalid"):
        apply_event(db, "TRAIN_DELAYED", "sim", {"vehicle_id": "TRAIN-12607", "delay_min": -5})
    with pytest.raises(Rejected, match="invalid"):
        apply_event(db, "TRAIN_DELAYED", "sim", {"vehicle_id": "TRAIN-12607", "delay_min": 5, "surprise": 1})


def test_settings_events_are_versioned(db):
    apply_event(db, "WEIGHTS_CHANGED", "operator", {"weights": {"senior": 10}})
    apply_event(db, "WEIGHTS_CHANGED", "operator", {"weights": {"senior": 12}})
    r = one_row(db, "SELECT value, version FROM settings WHERE key='scoring_weights'")
    assert json.loads(r["value"]) == {"senior": 12} and r["version"] == 2


def test_delay_and_road_closure_are_recorded(db):
    apply_event(db, "TRAIN_DELAYED", "sim", {"vehicle_id": "TRAIN-12607", "delay_min": 45})
    apply_event(db, "ROAD_CLOSED", "sim", {"route_id": "MTC-22836", "description": "flooding at Poonamallee High Road"})
    assert one(db, "SELECT delay_min FROM vehicles WHERE vehicle_id='TRAIN-12607'") == 45
    assert one(db, "SELECT COUNT(*) FROM disruptions") == 2


# ------------------------------------------------------------------------------------------------- replay
def test_replaying_the_log_rebuilds_identical_state(cancelled, scenario):
    c = cancelled
    train, pool, gs = _reserved_pool_with_two_groups(c)
    plan(c, "B1", pool, train, "ARAKKONAM", gs[:2], scores={gs[0]: 3.0, gs[1]: 2.0})
    apply_event(c, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    a_gs = groups_for(c, "AVADI", max_total=20)
    plan(c, "B2", BUS_POOL, BUS, "AVADI", a_gs)
    apply_event(c, "LOAD_REPORT", "field", {"vehicle_id": BUS, "pool_id": BUS_POOL, "level": "OVERCROWDED", "count": 52})
    apply_event(c, "BUFFER_CHANGED", "operator", {"mode": "MTC_BUS", "buffer_pct": 0.6})
    with pytest.raises(Rejected):
        apply_event(c, "BUFFER_CHANGED", "operator", {"mode": "TRAIN_UNRESERVED", "buffer_pct": 9})
    apply_event(c, "NOSHOWS_REPORTED", "field", {"vehicle_id": train, "pool_id": pool, "seats_freed": 2, "from_seg": 0, "to_seg": 2})
    apply_event(c, "VACANCY_UPDATE", "field", {"pool_id": pool, "from_seg": 0, "to_seg": 2, "vacancy": 1})
    apply_event(c, "TRAIN_DELAYED", "sim", {"vehicle_id": "TRAIN-12607", "delay_min": 30})
    apply_event(c, "SMS_SENT", "system", {"group_id": gs[0], "channel": "PHONE_MOCK", "lang": "en", "message": "hello", "reason": "r"})
    assert one(c, "SELECT COUNT(*) FROM events WHERE type='COMMAND_REJECTED'") >= 1
    assert one(c, "SELECT COUNT(*) FROM allocations WHERE status='DISPLACED'") + one(c, "SELECT COUNT(*) FROM allocations WHERE status='RELEASED'") > 0

    fresh = new_db()
    replay(c, fresh)
    assert state_dump(fresh) == state_dump(c)
    assert [tuple(r) for r in fresh.execute("SELECT * FROM events ORDER BY seq")] == \
           [tuple(r) for r in c.execute("SELECT * FROM events ORDER BY seq")]
    assert check_invariants(fresh) == []


def test_overcrowded_report_without_a_count_is_treated_as_exactly_full(cancelled):
    gs = groups_for(cancelled, "AVADI", max_total=12)
    plan(cancelled, "B1", BUS_POOL, BUS, "AVADI", gs, scores={g: float(i) for i, g in enumerate(gs, 1)})
    apply_event(cancelled, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    apply_event(cancelled, "LOAD_REPORT", "field", {"vehicle_id": BUS, "pool_id": BUS_POOL, "level": "OVERCROWDED"})   # no count
    # count defaults to the nominal (40): zero physical room, so every unboarded confirmed group is displaced
    assert {r["status"] for r in q(cancelled, "SELECT status FROM allocations")} == {"DISPLACED"}
    assert one_row(cancelled, "SELECT level, count FROM field_reports")["count"] is None          # the report is stored as sent
    assert max(r["cap"] for r in q(cancelled, "SELECT cap FROM segment_capacity WHERE pool_id = ?", BUS_POOL)) == 0
    assert check_invariants(cancelled) == []


def test_overcrowded_without_count_equals_overcrowded_with_count_nominal(scenario):
    outcomes = []
    for payload in ({"level": "OVERCROWDED"}, {"level": "OVERCROWDED", "count": 40}):
        c = new_db()
        apply_event(c, "SCENARIO_LOADED", "sim", {"scenario": scenario})
        apply_event(c, "TRAIN_CANCELLED", "sim", {"vehicle_id": "TRAIN-SIM-CXL"})
        gs = groups_for(c, "AVADI", max_total=12)
        plan(c, "B1", BUS_POOL, BUS, "AVADI", gs, scores={g: float(i) for i, g in enumerate(gs, 1)})
        apply_event(c, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
        apply_event(c, "LOAD_REPORT", "field", {"vehicle_id": BUS, "pool_id": BUS_POOL, **payload})
        outcomes.append([(r["group_id"], r["status"]) for r in q(c, "SELECT group_id, status FROM allocations ORDER BY id")])
    assert outcomes[0] == outcomes[1]
