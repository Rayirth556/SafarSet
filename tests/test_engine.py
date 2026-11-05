"""Event loop on the generated scenario: re-plan on events, stability, bounded reshuffle, displacement, diff categories,
operator overrides, weight re-runs, and approval-only behaviour. The scripted demo timeline is played end to end.
Tests assert rules and structure, not how large the (tuned) shortage is."""
import json

import pytest

from safarset.db.conn import new_db
from safarset.db.invariants import check_invariants
from safarset.domain.loop import Engine
from safarset.events.apply import apply_event
from safarset.events.reducers import Rejected, StaleBatch, batch_is_stale
from safarset.sim.generator import generate
from safarset.sim.runner import play_timeline


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, group, allocation, kind, ctx=None):
        self.calls.append((group["group_id"], kind, allocation["id"] if allocation else None))
        return {"channel": "PHONE_MOCK", "lang": group["attrs"]["language"], "message": f"{kind} {group['group_id']}",
                "reason": allocation["reason"]["text"] if allocation else None}


@pytest.fixture(scope="module")
def scenario():
    return generate(42)


def make(scenario, **kw):
    c = new_db()
    apply_event(c, "SCENARIO_LOADED", "sim", {"scenario": scenario})
    notifier = FakeNotifier()
    return Engine(c, notifier=notifier, **kw), c, notifier


@pytest.fixture()
def world(scenario):
    return make(scenario)


@pytest.fixture()
def started(world):
    e, c, n = world
    e.handle("TRAIN_CANCELLED", "sim", {"vehicle_id": "TRAIN-SIM-CXL"}, 840)
    return e, c, n


def rows(c, sql, *a):
    return c.execute(sql, a).fetchall()


def scalar(c, sql, *a):
    return c.execute(sql, a).fetchone()[0]


def tentative(c):
    return {r["group_id"]: (r["pool_id"], r["board_idx"], r["alight_idx"]) for r in rows(c, "SELECT * FROM allocations WHERE status='TENTATIVE'")}


def confirmed(c):
    return {r["group_id"] for r in rows(c, "SELECT group_id FROM allocations WHERE status='CONFIRMED'")}


def diff_counts(c, batch_id):
    return {k: v["groups"] for k, v in json.loads(scalar(c, "SELECT summary FROM plan_batches WHERE batch_id = ?", batch_id))["diff"].items()}


def items(c, batch_id, kind):
    return {r["group_id"]: json.loads(r["detail"]) for r in rows(c, "SELECT * FROM batch_items WHERE batch_id = ? AND kind = ?", batch_id, kind)}


def dest_stop(c, vehicle_id, place):
    for r in rows(c, "SELECT seq, serves_places FROM vehicle_stops WHERE vehicle_id = ? AND seq > 0 ORDER BY seq", vehicle_id):
        if place in json.loads(r["serves_places"]):
            return r["seq"]


def find_room(c, group_id):
    """(pool_id, board, alight) of some allocatable pool serving the group's destination with room for the whole group."""
    g = rows(c, "SELECT size, dest_place FROM groups WHERE group_id = ?", group_id)[0]
    for v in rows(c, "SELECT vehicle_id FROM vehicles WHERE role = 'ALLOCATION' AND status = 'SCHEDULED' ORDER BY vehicle_id"):
        j = dest_stop(c, v["vehicle_id"], g["dest_place"])
        if j is None:
            continue
        for p in rows(c, "SELECT pool_id FROM pools WHERE vehicle_id = ? ORDER BY pool_id", v["vehicle_id"]):
            free = rows(c, "SELECT MIN(cap - used) m FROM segment_capacity WHERE pool_id = ? AND seg_idx < ?", p["pool_id"], j)[0]["m"]
            if free is not None and free >= g["size"] and p["pool_id"].endswith(":UR") and v["vehicle_id"].startswith("BUS-SPL"):
                return p["pool_id"], 0, j
    return None


# ================================================================================================ the demo timeline
def test_scripted_demo_timeline_plays_against_the_event_loop(world, scenario):
    e, c, notifier = world
    log = {}

    def snapshot(name):
        log[name] = {"confirmed": confirmed(c), "tentative": tentative(c), "notified": len(notifier.calls),
                     "sms_rows": scalar(c, "SELECT COUNT(*) FROM notifications")}

    def check(step, res):
        n = step["step"]
        assert check_invariants(c) == [], f"step {n}"
        if n == 1:                                                   # cancellation: a plan is proposed, nothing is sent
            pend = e.pending_batch()
            assert pend["status"] == "PROPOSED" and res.batch_id == pend["batch_id"]
            affected = {r["group_id"] for r in rows(c, "SELECT group_id FROM groups WHERE affected = 1")}
            assert affected == {r["group_id"] for r in rows(c, "SELECT group_id FROM groups")}
            assert set(tentative(c)) | set(items(c, pend["batch_id"], "UNRESOLVED")) == affected
            assert notifier.calls == [] and scalar(c, "SELECT COUNT(*) FROM notifications") == 0
            snapshot("after_plan")
        elif n == 2:
            assert res == e.pending_batch()["batch_id"]          # the plan from step 1 is still the fresh pending batch
        elif n == 3:                                                 # approval: confirmed + SMS to exactly those groups
            assert set(res.confirmed_groups) == set(log["after_plan"]["tentative"])
            assert {g for g, _, _ in notifier.calls} == set(res.confirmed_groups)
            assert confirmed(c) == set(res.confirmed_groups) and tentative(c) == {}
            assert scalar(c, "SELECT COUNT(*) FROM notifications") == len(res.confirmed_groups)
            snapshot("after_approval")
        elif n == 4:                                                 # conductor reports the first bus overcrowded
            vid = step["payload"]["vehicle_id"]
            assert rows(c, "SELECT level FROM field_reports WHERE pool_id = ?", step["payload"]["pool_id"])[0]["level"] == "OVERCROWDED"
            displaced = {r["group_id"] for r in rows(c, "SELECT group_id FROM allocations WHERE status='DISPLACED'")}
            assert displaced <= log["after_approval"]["confirmed"]
            for r in rows(c, "SELECT status_reason FROM allocations WHERE status='DISPLACED'"):
                assert json.loads(r["status_reason"])["cause"] == "LOAD_REPORT"
            assert scalar(c, "SELECT COUNT(*) FROM notifications") == log["after_approval"]["sms_rows"]     # still nothing sent
            assert res.batch_id and set(items(c, res.batch_id, "DISPLACED")) == displaced
            assert confirmed(c) == log["after_approval"]["confirmed"] - displaced                           # confirmed are frozen
            snapshot("after_overcrowd")
        elif n == 5:                                                 # second-chart vacancies: seats appear
            p = step["payload"]
            caps = [r["cap"] for r in rows(c, "SELECT cap FROM segment_capacity WHERE pool_id = ? ORDER BY seg_idx", p["pool_id"])]
            nominal = scalar(c, "SELECT nominal FROM pools WHERE pool_id = ?", p["pool_id"])
            assert all(cap <= nominal for cap in caps)
            assert scalar(c, "SELECT COUNT(*) FROM notifications") == log["after_approval"]["sms_rows"]
            snapshot("after_vacancies")
        elif n == 6:                                                 # re-plan pending, fresh, confirmed still frozen
            pend = e.pending_batch()
            assert pend and not batch_is_stale(c, pend["batch_id"])
            assert confirmed(c) == log["after_overcrowd"]["confirmed"]
            counts = diff_counts(c, pend["batch_id"])
            assert counts["DISPLACED"] > 0 or counts["NEWLY_PLACED"] > 0 or counts["RESHUFFLED"] > 0
        elif n == 7:                                                 # second approval: only changed groups are notified
            before = log["after_vacancies"]
            assert set(res.confirmed_groups) == set(before["tentative"])
            assert confirmed(c) == before["confirmed"] | set(res.confirmed_groups)
            assert tentative(c) == {} and e.pending_batch() is None
            new_calls = notifier.calls[log["after_approval"]["notified"]:]
            assert {g for g, _, _ in new_calls} >= set(res.confirmed_groups)
            assert not ({g for g, _, _ in new_calls} & log["after_overcrowd"]["confirmed"])   # frozen groups were not re-notified

    play_timeline(e, scenario, check)
    # every displaced group is either re-confirmed on a new seat or still unresolved; never double-booked
    assert scalar(c, "SELECT COUNT(*) FROM (SELECT group_id FROM allocations WHERE status IN ('TENTATIVE','CONFIRMED','BOARDED') "
                     "GROUP BY group_id HAVING COUNT(*) > 1)") == 0
    kinds = {r["kind"] for r in rows(c, "SELECT DISTINCT kind FROM batch_items")}
    assert {"NEWLY_PLACED", "UNRESOLVED"} <= kinds


# ================================================================================================ approval only
def test_nothing_is_sent_until_approval_and_stale_batches_can_only_be_replanned(world):
    e, c, notifier = world
    e.auto_replan = False
    e.handle("TRAIN_CANCELLED", "sim", {"vehicle_id": "TRAIN-SIM-CXL"}, 840)
    b1 = e.replan(845)
    assert notifier.calls == [] and scalar(c, "SELECT COUNT(*) FROM notifications") == 0
    pool = rows(c, "SELECT pool_id, MIN(seg_lo) lo, MAX(seg_hi) hi FROM batch_footprint WHERE batch_id = ? AND pool_id IN "
                   "(SELECT pool_id FROM pools WHERE kind = 'RESERVED') GROUP BY pool_id LIMIT 1", b1)[0]
    veh = scalar(c, "SELECT vehicle_id FROM pools WHERE pool_id = ?", pool["pool_id"])
    e.handle("NOSHOWS_REPORTED", "field", {"vehicle_id": veh, "pool_id": pool["pool_id"], "seats_freed": 1, "from_seg": pool["lo"], "to_seg": pool["lo"] + 1}, 850)
    with pytest.raises(StaleBatch):
        e.approve(b1, 851)
    assert notifier.calls == [] and scalar(c, "SELECT COUNT(*) FROM allocations WHERE status='CONFIRMED'") == 0
    b2 = e.replan(852, force=True)
    assert b2 != b1 and scalar(c, "SELECT status FROM plan_batches WHERE batch_id = ?", b1) == "SUPERSEDED"
    e.approve(b2, 853)
    assert len(notifier.calls) == scalar(c, "SELECT COUNT(*) FROM allocations WHERE status='CONFIRMED'") > 0
    with pytest.raises(Rejected, match="no pending batch"):
        e.approve(None, 854)


# ================================================================================================ stability + diff
def test_unrelated_event_produces_no_new_batch_and_a_small_event_a_small_diff(started):
    e, c, notifier = started
    b1 = e.pending_batch()["batch_id"]
    before = tentative(c)
    # events that only touch non-allocatable regular services cannot change anyone's plan
    r = e.handle("ROAD_CLOSED", "sim", {"route_id": "MTC-23213", "description": "waterlogging on the Koyambedu leg"}, 841)   # one minute later: no departure becomes un-boardable
    assert r.batch_id is None and e.pending_batch()["batch_id"] == b1 and tentative(c) == before
    reg = scalar(c, "SELECT pool_id FROM pools WHERE pool_id LIKE 'BUS-REG-%' LIMIT 1")
    r = e.handle("LOAD_REPORT", "field", {"vehicle_id": reg.split(":")[0], "pool_id": reg, "level": "FULL", "count": 40}, 842)
    assert r.batch_id is None and tentative(c) == before
    # a small related event: two seats appear on one train pool
    pool = rows(c, "SELECT pool_id, vehicle_id FROM pools WHERE kind = 'RESERVED' AND vehicle_id = 'TRAIN-SIM-ALT-3' ORDER BY nominal DESC")[0]
    r = e.handle("NOSHOWS_REPORTED", "field", {"vehicle_id": pool["vehicle_id"], "pool_id": pool["pool_id"], "seats_freed": 2, "from_seg": 0, "to_seg": 4}, 843)
    after = tentative(c)
    counts = diff_counts(c, r.batch_id) if r.batch_id else None
    assert all(after.get(g) == v for g, v in before.items()), "an unrelated/small event must not move existing placements"
    if counts:
        assert counts["RESHUFFLED"] == 0 and counts["DISPLACED"] == 0
        assert counts["NEWLY_PLACED"] <= 2                          # at most two heads' worth of newly placed groups
    assert check_invariants(c) == []


def test_capacity_loss_forces_moves_that_are_reported_as_forced_reshuffles(started):
    e, c, _ = started
    b1 = e.pending_batch()["batch_id"]
    pool = rows(c, """SELECT a.pool_id, p.vehicle_id, COUNT(*) n FROM allocations a JOIN pools p USING (pool_id)
                      WHERE a.status = 'TENTATIVE' AND p.kind = 'RESERVED' GROUP BY a.pool_id ORDER BY n DESC LIMIT 1""")[0]
    held = {r["group_id"] for r in rows(c, "SELECT group_id FROM allocations WHERE status='TENTATIVE' AND pool_id = ?", pool["pool_id"])}
    r = e.handle("VACANCY_UPDATE", "field", {"pool_id": pool["pool_id"], "from_seg": 0, "to_seg": scalar(c, "SELECT COUNT(*) FROM segment_capacity WHERE pool_id = ?", pool["pool_id"]), "vacancy": 0}, 850)
    assert r.batch_id and r.batch_id != b1
    resh = items(c, r.batch_id, "RESHUFFLED")
    unres = items(c, r.batch_id, "UNRESOLVED")
    assert set(resh) | set(unres) >= held and all(d["forced"] is True for d in resh.values())
    assert diff_counts(c, r.batch_id)["RESHUFFLED"] == len(resh)
    others = [g for g in tentative(c) if g not in held]
    assert others, "groups on other pools stay where they were"


def test_diff_categories_and_counts_after_displacement(started):
    e, c, _ = started
    e.approve(None, 850)
    victims = [r["id"] for r in rows(c, "SELECT a.id FROM allocations a WHERE a.status='CONFIRMED' ORDER BY a.id LIMIT 3")]
    vg = {r["group_id"] for r in rows(c, "SELECT group_id FROM allocations WHERE id IN (%s)" % ",".join(map(str, victims)))}
    for aid in victims:
        e.handle("PASSENGER_DISPLACED", "field", {"allocation_id": aid, "reason": "could not board: crowd at the stop"}, 855)
    bid = e.pending_batch()["batch_id"]
    displaced = items(c, bid, "DISPLACED")
    assert set(displaced) == vg
    counts = diff_counts(c, bid)
    assert counts["DISPLACED"] == len(vg)
    assert all(d["replaced"] in (True, False) for d in displaced.values())
    # counts match the stored items exactly, per category
    for kind, n in counts.items():
        assert n == scalar(c, "SELECT COUNT(*) FROM batch_items WHERE batch_id = ? AND kind = ?", bid, kind)
    heads = json.loads(scalar(c, "SELECT summary FROM plan_batches WHERE batch_id = ?", bid))["diff"]["DISPLACED"]["heads"]
    assert heads == scalar(c, "SELECT SUM(size) FROM groups WHERE group_id IN (%s)" % ",".join("'%s'" % g for g in vg))
    assert confirmed(c).isdisjoint(vg)                                          # displaced groups are out until re-confirmed


# ================================================================================================ operator override
def test_override_requires_a_reason_and_is_logged(started):
    e, c, _ = started
    g = next(iter(tentative(c)))
    with pytest.raises(Rejected, match="requires a reason"):
        e.override(g, "UNASSIGN", " ", ts_sim=850)
    e.override(g, "UNASSIGN", "family asked to wait for the next train", ts_sim=851)
    ev = rows(c, "SELECT payload FROM events WHERE type = 'OPERATOR_OVERRIDE' ORDER BY seq DESC LIMIT 1")[0]["payload"]
    assert "family asked to wait" in ev


def test_unassign_holds_a_group_out_of_planning_until_resumed(started):
    e, c, _ = started
    g = next(iter(tentative(c)))
    r = e.override(g, "UNASSIGN", "passenger asked to be excluded", ts_sim=850)
    assert g not in tentative(c) and scalar(c, "SELECT COUNT(*) FROM group_holds WHERE group_id = ?", g) == 1
    e.replan(851, force=True)
    bid = e.pending_batch()["batch_id"]
    assert items(c, bid, "UNRESOLVED")[g]["reason"]["primary_cause"] == "OPERATOR_HOLD" and g not in tentative(c)
    e.override(g, "RESUME_AUTO", "passenger changed their mind", ts_sim=852)
    assert scalar(c, "SELECT COUNT(*) FROM group_holds") == 0


def test_assign_override_is_pinned_logged_and_needs_approval(started):
    e, c, notifier = started
    row = rows(c, "SELECT group_id, pool_id, board_idx, alight_idx FROM allocations WHERE status='TENTATIVE' AND pool_id LIKE 'BUS-SPL-%' ORDER BY id")[0]
    g, pool_id, lo, hi = row["group_id"], row["pool_id"], row["board_idx"], row["alight_idx"]
    e.auto_replan = False                                       # keep the freed seat free (a re-plan would hand it to someone else)
    e.override(g, "UNASSIGN", "free the seat, then assign it deliberately", ts_sim=850)
    assert g not in tentative(c)
    e.override(g, "ASSIGN", "operator moved the family to the earlier bus", pool_id=pool_id, board_idx=lo, alight_idx=hi, ts_sim=860)
    alloc = rows(c, "SELECT * FROM allocations WHERE group_id = ? AND status = 'TENTATIVE'", g)[0]
    reason = json.loads(alloc["reason"])
    assert reason["operator_override"]["reason"] == "operator moved the family to the earlier bus" and alloc["pool_id"] == pool_id
    e.auto_replan = True
    # kept through a normal re-plan AND through "adjust weights and re-run"
    e.replan(861, force=True)
    assert tentative(c)[g] == (pool_id, lo, hi)
    e.adjust_weights_and_rerun({"medical_disability": 40, "senior_60_plus": 25, "child_or_pregnant": 30, "hard_deadline": 20,
                                "reserved_pnr": 10, "ageing_per_hour": 6}, 862)
    assert tentative(c)[g] == (pool_id, lo, hi)
    bid = e.pending_batch()["batch_id"]
    item = rows(c, "SELECT kind, detail FROM batch_items WHERE batch_id = ? AND group_id = ?", bid, g)[0]
    assert json.loads(item["detail"])["operator_override"] is True
    assert notifier.calls == []                                         # approval only
    e.approve(None, 870)
    assert g in confirmed(c) and any(call[0] == g for call in notifier.calls)


def test_assign_rejections_leave_state_untouched(started):
    e, c, _ = started
    g = rows(c, "SELECT group_id FROM groups WHERE dest_place = 'POONAMALLEE' LIMIT 1")[0]["group_id"]
    before = (tentative(c), scalar(c, "SELECT COUNT(*) FROM allocations"))
    with pytest.raises(Rejected, match="does not stop at POONAMALLEE"):         # BUS-SPL-02 is an Avadi route
        e.override(g, "ASSIGN", "wrong bus on purpose", pool_id="BUS-SPL-02:UR", board_idx=0, alight_idx=3, ts_sim=850)
    with pytest.raises(Rejected, match="needs pool_id"):
        e.override(g, "ASSIGN", "missing target", ts_sim=850)
    assert (tentative(c), scalar(c, "SELECT COUNT(*) FROM allocations")) == before


def test_assign_into_a_full_pool_is_refused_by_the_database(started):
    e, c, _ = started
    j = dest_stop(c, "BUS-SPL-02", "AVADI")
    pool = "BUS-SPL-02:UR"
    with pytest.raises(Rejected, match="database rejected"):
        for g in [r["group_id"] for r in rows(c, "SELECT group_id FROM groups WHERE dest_place = 'AVADI' ORDER BY group_id")] * 1:
            e.override(g, "ASSIGN", "force everyone onto one bus", pool_id=pool, board_idx=0, alight_idx=j, ts_sim=850)
    assert max(r["used"] - r["cap"] for r in rows(c, "SELECT used, cap FROM segment_capacity")) <= 0
    assert check_invariants(c) == []


def test_override_of_a_confirmed_group_displaces_the_old_seat_and_needs_approval(started):
    e, c, notifier = started
    e.approve(None, 850)
    n0 = len(notifier.calls)
    g, old = next((r["group_id"], r["id"]) for r in rows(c, "SELECT group_id, id FROM allocations WHERE status = 'CONFIRMED' ORDER BY id"))
    e.override(g, "UNASSIGN", "operator removed the group from this vehicle", ts_sim=860)
    assert scalar(c, "SELECT status FROM allocations WHERE id = ?", old) == "DISPLACED"
    bid = e.pending_batch()["batch_id"]
    assert g in items(c, bid, "DISPLACED") and len(notifier.calls) == n0


# ================================================================================================ weights re-run
def test_adjust_weights_and_rerun_creates_a_new_pending_batch_from_scratch(started):
    e, c, _ = started
    b1 = e.pending_batch()["batch_id"]
    weights = {"medical_disability": 40, "senior_60_plus": 5000, "child_or_pregnant": 30, "hard_deadline": 20,
               "reserved_pnr": 10, "ageing_per_hour": 6}
    b2 = e.adjust_weights_and_rerun(weights, 860)
    assert b2 != b1 and e.pending_batch()["batch_id"] == b2
    assert scalar(c, "SELECT status FROM plan_batches WHERE batch_id = ?", b1) == "SUPERSEDED"
    assert json.loads(scalar(c, "SELECT value FROM settings WHERE key = 'scoring_weights'")) == weights
    assert scalar(c, "SELECT COUNT(*) FROM events WHERE type = 'WEIGHTS_CHANGED'") == 1
    seniors = {r["group_id"] for r in rows(c, "SELECT group_id, attrs FROM groups") if json.loads(r["attrs"])["has_senior"]}
    top = json.loads(scalar(c, "SELECT summary FROM plan_batches WHERE batch_id = ?", b2))["weights"]
    assert top["senior_60_plus"] == 5000
    ranks = {r["group_id"]: json.loads(r["reason"])["rank"] for r in rows(c, "SELECT group_id, reason FROM allocations WHERE status = 'TENTATIVE'")}
    assert max(ranks[g] for g in seniors if g in ranks) <= len(seniors)           # seniors take the first ranks
    assert check_invariants(c) == []


def test_adjust_weights_leaves_confirmed_groups_alone(started):
    e, c, _ = started
    e.approve(None, 850)
    frozen = confirmed(c)
    e.adjust_weights_and_rerun({"medical_disability": 1, "senior_60_plus": 1, "child_or_pregnant": 1, "hard_deadline": 1,
                                "reserved_pnr": 1, "ageing_per_hour": 99}, 860)
    assert confirmed(c) == frozen and check_invariants(c) == []


# ================================================================================================ disruptions
def test_road_closure_cancels_buses_displaces_confirmed_and_replans(started):
    e, c, _ = started
    e.approve(None, 850)
    on_route = {r["group_id"] for r in rows(c, """SELECT a.group_id FROM allocations a JOIN pools p USING (pool_id) JOIN vehicles v USING (vehicle_id)
                                                  WHERE a.status = 'CONFIRMED' AND v.route_id = 'MTC-22836'""")}
    r = e.handle("ROAD_CLOSED", "sim", {"route_id": "MTC-22836", "description": "flooding on Poonamallee High Road"}, 860)
    assert scalar(c, "SELECT COUNT(*) FROM vehicles WHERE route_id = 'MTC-22836' AND status = 'SCHEDULED'") == 0
    displaced = {x["group_id"] for x in rows(c, "SELECT group_id FROM allocations WHERE status = 'DISPLACED'")}
    assert displaced == on_route
    if on_route:
        assert set(items(c, r.batch_id, "DISPLACED")) == on_route
    for a in rows(c, "SELECT a.pool_id FROM allocations a WHERE a.status IN ('TENTATIVE','CONFIRMED')"):
        assert not a["pool_id"].startswith(tuple(v["vehicle_id"] for v in rows(c, "SELECT vehicle_id FROM vehicles WHERE route_id='MTC-22836'")))
    assert check_invariants(c) == []


def test_delay_keeps_confirmed_and_revalidates_tentative_deadlines(started):
    e, c, _ = started
    frozen_before = confirmed(c)
    e.approve(None, 850)
    frozen = confirmed(c)
    r = e.handle("TRAIN_DELAYED", "sim", {"vehicle_id": "TRAIN-SIM-ALT-1", "delay_min": 120}, 860)
    assert confirmed(c) == frozen and frozen_before == set()
    if r.batch_id:
        summary = json.loads(scalar(c, "SELECT summary FROM plan_batches WHERE batch_id = ?", r.batch_id))
        assert all(code in ("MISSES_DEADLINE", "TOO_LATE_TO_BOARD", "ROUTE_CHANGED", "NO_CAPACITY", "POOL_GONE", "VEHICLE_CANCELLED", "CLASS_NOT_ALLOWED", "WHEELCHAIR_NOT_ACCESSIBLE")
                   for code in summary["unpinned"].values())
        for a in rows(c, "SELECT reason FROM allocations WHERE status = 'TENTATIVE'"):
            ch = json.loads(a["reason"])["chosen"]
            if ch["vehicle_id"] == "TRAIN-SIM-ALT-1":
                sched = scalar(c, "SELECT arr_min FROM vehicle_stops WHERE vehicle_id = 'TRAIN-SIM-ALT-1' AND seq = ?", ch["alight_idx"])
                assert ch["arrive_min"] == sched + 120
    assert check_invariants(c) == []


# ================================================================================================ batch causes and plan-item flags
def test_batches_carry_the_cause_that_created_them(started):
    e, c, _ = started
    causes = lambda: {r["batch_id"]: r["cause"] for r in rows(c, "SELECT batch_id, cause FROM plan_batches")}
    assert causes()["B1"] == "TRAIN_CANCELLED"                                       # triggered by the cancellation event
    b2 = e.adjust_weights_and_rerun({"medical_disability": 40, "senior_60_plus": 25, "child_or_pregnant": 30, "hard_deadline": 20,
                                     "reserved_pnr": 10, "ageing_per_hour": 6}, 860)
    assert causes()[b2] == "WEIGHTS_RERUN"
    b3 = e.replan(861, force=True)
    assert causes()[b3] == "MANUAL_REPLAN"
    r = e.handle("LOAD_REPORT", "field", {"vehicle_id": "BUS-SPL-01", "pool_id": "BUS-SPL-01:UR", "level": "FULL", "count": 40}, 862)
    if r.batch_id:
        assert causes()[r.batch_id] == "LOAD_REPORT"


def test_overriding_a_confirmed_group_flags_that_the_old_sms_is_still_held(started):
    e, c, notifier = started
    e.approve(None, 850)
    g = next(r["group_id"] for r in rows(c, "SELECT group_id FROM allocations WHERE status = 'CONFIRMED' ORDER BY id"))
    e.override(g, "UNASSIGN", "operator removed the group from this vehicle", ts_sim=860)
    bid = e.pending_batch()["batch_id"]
    for item in rows(c, "SELECT kind, detail FROM batch_items WHERE batch_id = ? AND group_id = ?", bid, g):
        assert json.loads(item["detail"])["old_sms_still_held"] is True
    d = items(c, bid, "DISPLACED")[g]
    assert d["old_sms_still_held"] is True and d["cause"] == "OPERATOR_OVERRIDE"
    # the same flag applies to any displaced confirmed group (e.g. crowd at the stop), because the SMS is already out
    victim = next(r["id"] for r in rows(c, "SELECT id FROM allocations WHERE status = 'CONFIRMED' ORDER BY id"))
    e.handle("PASSENGER_DISPLACED", "field", {"allocation_id": victim, "reason": "could not board: crowd at the stop"}, 865)
    bid2 = e.pending_batch()["batch_id"]
    assert all(v["old_sms_still_held"] is True for v in items(c, bid2, "DISPLACED").values())
