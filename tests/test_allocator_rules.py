"""Allocator and compatibility rules on small hand-built worlds (no database): every owner rule has its own test."""
import copy

import pytest

from safarset.domain import compat
from safarset.domain.allocator import allocate

RANK = {c: i for i, c in enumerate(["UR", "2S", "SL", "CC", "3A", "2A", "1A"])}
CFG = {"min_checkin_min": 0, "walk_m_per_min": 80, "arrival_tolerance_min": 15, "reshuffle_max_moves": 2, "reshuffle_candidates": 8}


def vehicle(vid, mode="BUS", dep=100, stops=None, pools=(), role="ALLOCATION", wheelchair=True, walk_m=0, route=None, delay=0):
    """stops: [(places, arr, dep), ...]; stop 0 is the boarding stop."""
    stops = stops or [(["CENTRAL"], dep, dep), (["MID"], dep + 20, dep + 20), (["DEST"], dep + 60, dep + 60)]
    return {"vehicle_id": vid, "mode": mode, "role": role, "label": "SIMULATED", "status": "SCHEDULED", "delay_min": delay,
            "depart_min": dep, "route_id": route, "train_no": vid, "name": vid,
            "boarding": {"stop_seq": 0, "walk_m": walk_m, "note": "Boards at X"}, "attrs": {"wheelchair_accessible": wheelchair},
            "stops": [{"seq": i, "serves_places": p, "arr_min": a, "dep_min": d, "stop_id": f"s{i}"} for i, (p, a, d) in enumerate(stops)],
            "pools": list(pools)}


def pool(pid, kind="UNRESERVED", cls="UR"):
    return {"pool_id": pid, "kind": kind, "class": cls, "nominal": 50, "buffer_mode": None, "buffer_pct": None}


def grp(gid, size=1, cls="UR", reserved=False, dest="DEST", prio=0, booking=0, pnr=None, **attrs):
    return {"group_id": gid, "size": size, "class": cls, "reserved": reserved, "board_place": "CENTRAL", "dest_place": dest,
            "requirements": {"wheelchair": attrs.pop("wheelchair", False)}, "booking_time": booking, "pnr": pnr, "waiting_since": 0,
            "attrs": {"prio": prio, "deadline_min": attrs.pop("deadline", None), **attrs}}


def prio_scorer(g, ctx):
    return {"total": g["attrs"]["prio"], "breakdown": [("prio", g["attrs"]["prio"])]}


def run(groups, vehicles, free, connections=(), now=0, scorer=prio_scorer):
    vs = {v["vehicle_id"]: v for v in vehicles}
    return allocate(groups, vs, free, scorer=scorer, weights={}, rank_map=RANK, connections=list(connections), now_min=now, config=CFG)


def placed(plan):
    return {a["group_id"]: (a["reason"]["chosen"]["vehicle_id"], a["pool_id"]) for a in plan.placements}


def unresolved(plan):
    return {u["group_id"]: u for u in plan.unresolved}


# ------------------------------------------------------------------ compat
def test_class_steps():
    r = RANK
    sl = {"reserved": True, "class": "SL"}
    assert compat.class_step(sl, pool("a", "RESERVED", "SL"), r)[:2] == (0, "SAME_CLASS")
    assert compat.class_step(sl, pool("a", "RESERVED", "3A"), r)[:2] == (1, "UPGRADE")
    assert compat.class_step(sl, pool("a", "RESERVED", "2S"), r)[:2] == (2, "LOWER_CLASS_FLAGGED")
    assert compat.class_step(sl, pool("a"), r)[:2] == (3, "UNRESERVED_LAST_RESORT")
    ur = {"reserved": False, "class": "UR"}
    assert compat.class_step(ur, pool("a"), r) is not None and compat.class_step(ur, pool("a", "RESERVED", "SL"), r) is None


def test_vehicle_option_rejection_codes():
    ctx = {"now_min": 0, "min_checkin_min": 30, "walk_m_per_min": 80}
    g = grp("g")
    assert compat.vehicle_option(g, vehicle("v", dep=100), ctx)[0]["arrive"] == 160
    assert compat.vehicle_option(g, vehicle("v", dep=20), ctx)[1]["code"] == "TOO_LATE_TO_BOARD"
    assert compat.vehicle_option(g, vehicle("v", dep=100, walk_m=800), ctx)[0]["walk_min"] == 10
    assert compat.vehicle_option(g, vehicle("v", dep=35, walk_m=800), ctx)[1]["code"] == "TOO_LATE_TO_BOARD"
    assert compat.vehicle_option(grp("g", dest="NOWHERE"), vehicle("v"), ctx)[1]["code"] == "NO_DESTINATION"
    assert compat.vehicle_option(grp("g", wheelchair=True), vehicle("v", wheelchair=False), ctx)[1]["code"] == "WHEELCHAIR_NOT_ACCESSIBLE"
    assert compat.vehicle_option(grp("g", deadline=150), vehicle("v", dep=100), ctx)[1]["late_by_min"] == 10
    assert compat.vehicle_option(g, vehicle("v", role="TRANSFER_LEG"), ctx)[1]["code"] == "NOT_ALLOCATABLE"
    assert compat.vehicle_option(g, vehicle("v", dep=100, delay=15), ctx)[0]["arrive"] == 175       # delay shifts arrival
    v = vehicle("v"); v["status"] = "CANCELLED"
    assert compat.vehicle_option(g, v, ctx)[1]["code"] == "VEHICLE_CANCELLED"


# ------------------------------------------------------------------ choice rules
def test_earliest_arrival_beats_mode_tier():
    """A bus arriving earlier beats a slower train (owner rule 6)."""
    bus = vehicle("bus", "BUS", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], 150, 150)], pools=[pool("bus:UR")])
    train = vehicle("train", "TRAIN", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], 190, 190)], pools=[pool("train:UR")])
    p = run([grp("g")], [train, bus], {"bus:UR": [5], "train:UR": [5]})
    assert placed(p)["g"][0] == "bus" and p.placements[0]["reason"]["why_chosen"]["decided_by"] == "EARLIEST_ARRIVAL"


def test_mode_tier_only_breaks_ties():
    s = [(["CENTRAL"], 100, 100), (["DEST"], 150, 150)]
    bus, train = vehicle("a_bus", "BUS", stops=s, pools=[pool("a_bus:UR")]), vehicle("z_train", "TRAIN", stops=s, pools=[pool("z_train:UR")])
    p = run([grp("g")], [bus, train], {"a_bus:UR": [5], "z_train:UR": [5]})
    assert placed(p)["g"][0] == "z_train" and p.placements[0]["reason"]["why_chosen"]["decided_by"] == "MODE_TIER"


def test_class_rule_prefers_same_then_upgrade_then_lower_then_unreserved():
    def pick(pools):
        v = vehicle("v", "TRAIN", pools=pools)
        return run([grp("g", cls="SL", reserved=True)], [v], {p["pool_id"]: [5, 5] for p in pools})
    sl, a3, s2, ur = pool("v:SL", "RESERVED", "SL"), pool("v:3A", "RESERVED", "3A"), pool("v:2S", "RESERVED", "2S"), pool("v:UR")
    for pools, expect_pool, step in (([s2, a3, sl, ur], "v:SL", "SAME_CLASS"), ([s2, a3, ur], "v:3A", "UPGRADE"),
                                     ([s2, ur], "v:2S", "LOWER_CLASS_FLAGGED"), ([ur], "v:UR", "UNRESERVED_LAST_RESORT")):
        p = pick(pools)
        ch = p.placements[0]["reason"]["chosen"]
        assert (ch["pool_id"], ch["class_step"]) == (expect_pool, step)
        assert ch["class_flagged"] == (step == "LOWER_CLASS_FLAGGED")
        assert step.split("_")[0].lower() in p.placements[0]["reason"]["text"].lower() or step == "SAME_CLASS"


def test_nearest_upgrade_is_preferred():
    v = vehicle("v", "TRAIN", pools=[pool("v:3A", "RESERVED", "3A"), pool("v:CC", "RESERVED", "CC")])
    p = run([grp("g", cls="SL", reserved=True)], [v], {"v:3A": [5, 5], "v:CC": [5, 5]})
    assert placed(p)["g"][1] == "v:CC"


def test_class_step_ranks_below_arrival():
    """Earliest arrival is the first criterion even when it costs a class step."""
    train = vehicle("train", "TRAIN", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], 200, 200)], pools=[pool("train:SL", "RESERVED", "SL")])
    bus = vehicle("bus", "BUS", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], 150, 150)], pools=[pool("bus:UR")])
    p = run([grp("g", cls="SL", reserved=True)], [train, bus], {"train:SL": [5], "bus:UR": [5]})
    assert placed(p)["g"][0] == "bus" and p.placements[0]["reason"]["chosen"]["class_step"] == "UNRESERVED_LAST_RESORT"


# ------------------------------------------------------------------ capacity and priority
def test_capacity_is_per_segment_and_a_group_is_never_split():
    v = vehicle("v", pools=[pool("v:UR")],
                stops=[(["CENTRAL"], 100, 100), (["MID"], 120, 120), (["DEST"], 160, 160), (["FAR"], 200, 200)])
    free = {"v:UR": [3, 0, 3]}                              # the middle segment is full
    p = run([grp("y", size=3, dest="MID"), grp("z", size=1, dest="DEST", prio=5), grp("w", size=3, dest="FAR")], [v], free)
    got, un = placed(p), unresolved(p)
    assert set(got) == {"y"}                                # y rides only segment 0, so segment 1 being full does not matter
    assert un["z"]["reason"]["binding"]["segment"] == 1 and un["z"]["reason"]["binding"]["free"] == 0
    assert un["w"]["reason"]["primary_cause"] == "CAPACITY"
    # a group larger than any segment is never split across vehicles or seats
    big = run([grp("big", size=4, dest="MID")], [v], {"v:UR": [3, 3, 3]})
    assert unresolved(big)["big"]["reason"]["binding"]["needed"] == 4 and not big.placements


def test_segment_reuse_allows_two_groups_on_the_same_seats():
    v = vehicle("v", pools=[pool("v:UR")], stops=[(["CENTRAL"], 100, 100), (["MID"], 120, 120), (["DEST"], 160, 160)])
    p = run([grp("a", size=2, dest="MID"), grp("b", size=2, dest="DEST")], [v], {"v:UR": [2, 2]})
    assert set(placed(p)) == {"a", "b"} or set(placed(p)) == {"a"}
    # a uses seg 0 only; b needs seg 0 AND 1: with 2 free on seg 0 only one of them fits, never both
    assert len(p.placements) == 1 and len(p.unresolved) == 1


def test_higher_priority_wins_the_last_seat_regardless_of_booking_order():
    v = vehicle("v", pools=[pool("v:UR")])
    p = run([grp("early", prio=1, booking=1), grp("urgent", prio=50, booking=999)], [v], {"v:UR": [1, 1]})
    assert set(placed(p)) == {"urgent"} and p.order == ["urgent", "early"]
    assert unresolved(p)["early"]["reason"]["rank"] == 2


def test_ties_break_by_booking_time_then_pnr_then_group_id():
    v = vehicle("v", pools=[pool("v:UR")])
    gs = [grp("g3", booking=5, pnr="P3"), grp("g1", booking=5, pnr="P1"), grp("g2", booking=1, pnr="P9"), grp("g0", booking=5, pnr=None)]
    assert run(gs, [v], {"v:UR": [9, 9]}).order == ["g2", "g1", "g3", "g0"]


def test_input_order_does_not_change_the_plan():
    v = vehicle("v", pools=[pool("v:UR")])
    gs = [grp(f"g{i}", size=1 + i % 3, prio=i % 4, booking=i, pnr=f"P{i}") for i in range(30)]
    a = run(gs, [v], {"v:UR": [12, 12]})
    b = run(list(reversed(gs)), [v], {"v:UR": [12, 12]})
    assert placed(a) == placed(b) and a.order == b.order


def test_allocator_never_oversells_and_does_not_mutate_inputs():
    v = vehicle("v", pools=[pool("v:UR")])
    free = {"v:UR": [7, 7]}
    snapshot = copy.deepcopy(free)
    gs = [grp(f"g{i}", size=1 + i % 3, prio=i, booking=i) for i in range(20)]
    p = run(gs, [v], free)
    assert free == snapshot
    sizes = {g["group_id"]: g["size"] for g in gs}
    assert sum(sizes[a["group_id"]] for a in p.placements) <= 7


def test_ageing_lets_a_long_waiter_overtake():
    from safarset.scoring.stub import default_weights, score
    w = default_weights()
    v = vehicle("v", dep=1000, pools=[pool("v:UR")])
    def mk(gid, since, **a):
        return {**grp(gid), "waiting_since": since, "reserved": False, "attrs": {"ages": [30], "deadline_min": None, **a}}
    medical = mk("medical", 700, disability=True)
    def winner(waiter_since):
        p = allocate([mk("waiter", waiter_since), medical], {"v": v}, {"v:UR": [1, 1]}, scorer=score, weights=w,
                     rank_map=RANK, connections=[], now_min=720, config=CFG)
        return set(placed(p))
    assert winner(700 - 60) == {"medical"}           # 1 h longer wait is worth only a few points
    assert winner(700 - 12 * 60) == {"waiter"}       # 12 h longer: nobody is starved


# ------------------------------------------------------------------ unresolved causes and alternatives
def test_wheelchair_and_deadline_causes_and_late_arrival_alternative():
    v = vehicle("v", dep=100, pools=[pool("v:UR")], wheelchair=False)
    p = run([grp("w", wheelchair=True), grp("d", deadline=120)], [v], {"v:UR": [5, 5]})
    un = unresolved(p)
    assert un["w"]["reason"]["primary_cause"] == "ACCESSIBILITY" and un["d"]["reason"]["primary_cause"] == "DEADLINE"
    alts = un["d"]["alternatives"]
    assert alts[0]["type"] == "LATE_ARRIVAL" and alts[0]["late_by_min"] == 40 and alts[-1]["type"] == "WAITLIST"
    assert [a["rank"] for a in alts] == [1, 2]


def test_waitlist_positions_follow_priority_per_destination():
    v = vehicle("v", pools=[pool("v:UR")])
    gs = [grp("a", prio=9), grp("b", prio=5), grp("c", prio=7), grp("d", prio=1)]
    p = run(gs, [v], {"v:UR": [1, 1]})
    pos = {u["group_id"]: u["alternatives"][-1]["position"] for u in p.unresolved}
    assert set(placed(p)) == {"a"} and pos == {"c": 1, "b": 2, "d": 3}


def test_multi_leg_alternative_when_no_direct_vehicle_has_space():
    direct = vehicle("direct", pools=[pool("direct:UR")])
    leg1 = vehicle("leg1", role="TRANSFER_LEG", route="R1", dep=100, stops=[(["CENTRAL"], 100, 100), (["HUB"], 130, 130)], pools=[pool("leg1:UR")])
    leg2 = vehicle("leg2", role="TRANSFER_LEG", route="R2", dep=170, stops=[(["HUB"], 170, 170), (["DEST"], 260, 260)], pools=[pool("leg2:UR")])
    too_soon = vehicle("leg2_early", role="TRANSFER_LEG", route="R2", dep=140, stops=[(["HUB"], 140, 140), (["DEST"], 200, 200)], pools=[pool("leg2_early:UR")])
    conn = {"id": "CONN-T", "from_place": "CENTRAL", "via_place": "HUB", "leg1_route": "R1", "leg2_route": "R2", "to_places": ["DEST"], "min_connection_min": 20}
    free = {"direct:UR": [0, 0], "leg1:UR": [9], "leg2:UR": [9], "leg2_early:UR": [9]}
    p = run([grp("g")], [direct, leg1, leg2, too_soon], free, connections=[conn])
    alt = unresolved(p)["g"]["alternatives"][0]
    assert alt["type"] == "MULTI_LEG" and alt["arrive_min"] == 260 and [l["vehicle_id"] for l in alt["legs"]] == ["leg1", "leg2"]
    # wheelchair users are not offered legs on inaccessible regular services
    leg1["attrs"]["wheelchair_accessible"] = False
    p = run([grp("g", wheelchair=True)], [direct, leg1, leg2], free, connections=[conn])
    assert all(a["type"] != "MULTI_LEG" for a in unresolved(p)["g"]["alternatives"])


# ------------------------------------------------------------------ machine-readable reasons
def test_reason_is_machine_readable_and_explains_the_choice():
    full = vehicle("a_full", dep=90, stops=[(["CENTRAL"], 90, 90), (["DEST"], 120, 120)], pools=[pool("a_full:UR")])
    ok = vehicle("b_ok", dep=100, pools=[pool("b_ok:UR")], walk_m=260)
    p = run([grp("g", prio=12, booking=3)], [full, ok], {"a_full:UR": [0], "b_ok:UR": [4, 4]})
    r = p.placements[0]["reason"]
    assert r["algorithm"] == "greedy-priority-v2" and (r["rank"], r["of"]) == (1, 1)
    assert r["score"] == {"total": 12, "breakdown": [["prio", 12]]}
    assert r["chosen"]["vehicle_id"] == "b_ok" and r["chosen"]["boarding_note"] == "Boards at X"
    assert r["binding_constraints"][0] == {"code": "CAPACITY", "vehicle_id": "a_full", "pool_id": "a_full:UR", "segment": 0,
                                           "free": 0, "needed": 1, "arrive": 120}
    assert "a_full" in r["text"] and "segment 0" in r["text"]
    import json
    json.dumps(r)                                              # fully JSON-serialisable


# ------------------------------------------------------------------ arrival tolerance (+15 min counts as equal)
def _two_trains(arrive_a, arrive_b, pools_a, pools_b):
    a = vehicle("a", "TRAIN", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], arrive_a, arrive_a)], pools=pools_a)
    b = vehicle("b", "TRAIN", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], arrive_b, arrive_b)], pools=pools_b)
    return a, b


def test_lower_class_vehicle_arriving_5_min_earlier_loses_to_same_class():
    a, b = _two_trains(150, 155, [pool("a:2S", "RESERVED", "2S")], [pool("b:SL", "RESERVED", "SL")])
    p = run([grp("g", cls="SL", reserved=True)], [a, b], {"a:2S": [5], "b:SL": [5]})
    r = p.placements[0]["reason"]
    assert placed(p)["g"][0] == "b" and r["chosen"]["class_step"] == "SAME_CLASS"
    assert r["why_chosen"]["decided_by"] == "CLASS_STEP" and "within 15 min count as equal" in r["text"]


def test_tolerance_boundary_is_inclusive_at_15_minutes_and_exclusive_beyond():
    for gap, expect in ((15, "b"), (16, "a")):
        a, b = _two_trains(150, 150 + gap, [pool("a:2S", "RESERVED", "2S")], [pool("b:SL", "RESERVED", "SL")])
        p = run([grp("g", cls="SL", reserved=True)], [a, b], {"a:2S": [5], "b:SL": [5]})
        assert placed(p)["g"][0] == expect, gap
    # beyond the tolerance the earlier arrival wins even at a worse class
    assert p.placements[0]["reason"]["why_chosen"]["decided_by"] == "EARLIEST_ARRIVAL"


def test_within_tolerance_order_is_class_then_upgrade_then_best_fit_then_arrival_then_mode_tier():
    s = lambda arr: [(["CENTRAL"], 100, 100), (["DEST"], arr, arr)]
    def pick(vs, free, g=None):
        return placed(run([g or grp("g")], vs, free))["g"][0]
    # best fit: same class and arrival, the tighter vehicle wins
    tight, roomy = vehicle("z_tight", stops=s(150), pools=[pool("z_tight:UR")]), vehicle("a_roomy", stops=s(150), pools=[pool("a_roomy:UR")])
    assert pick([roomy, tight], {"z_tight:UR": [1], "a_roomy:UR": [9]}) == "z_tight"
    # equal class and fit: earlier arrival (inside the tolerance) wins before mode tier
    bus, train = vehicle("bus", "BUS", stops=s(150), pools=[pool("bus:UR")]), vehicle("train", "TRAIN", stops=s(160), pools=[pool("train:UR")])
    assert pick([bus, train], {"bus:UR": [3], "train:UR": [3]}) == "bus"
    # fully equal: mode tier breaks the tie (train)
    train2 = vehicle("train2", "TRAIN", stops=s(150), pools=[pool("train2:UR")])
    assert pick([bus, train2], {"bus:UR": [3], "train2:UR": [3]}) == "train2"


# ------------------------------------------------------------------ stability rule and bounded reshuffle
def _pin(gid, pool_id, b, j, **extra):
    return {gid: {"pool_id": pool_id, "board_idx": b, "alight_idx": j, "override": extra.pop("override", False),
                  "reason": {"algorithm": "greedy-priority-v2", "chosen": {"class_step": extra.pop("step", "UNRESERVED_TICKET")}, "text": "old"}}}


def two_buses(arr_b=165, wheel_b=True, pool_b=None, cap_a=2, cap_b=1):
    a = vehicle("a", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], 150, 150)], pools=[pool("a:UR")])
    b = vehicle("b", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], arr_b, arr_b)], pools=[pool_b or pool("b:UR")], wheelchair=wheel_b)
    return [a, b], {"a:UR": [cap_a], (pool_b or pool("b:UR"))["pool_id"]: [cap_b]}


def run_pinned(groups, vehicles, free, pinned, cfg=None):
    return allocate(groups, {v["vehicle_id"]: v for v in vehicles}, free, scorer=prio_scorer, weights={}, rank_map=RANK,
                    connections=[], now_min=0, config=cfg or CFG, pinned=pinned)


def test_existing_tentative_placements_are_kept():
    vs, free = two_buses(cap_a=3, cap_b=5)
    gs = [grp("low", prio=1), grp("mid", prio=5), grp("new", prio=9)]
    p = run_pinned(gs, vs, free, {**_pin("low", "a:UR", 0, 1), **_pin("mid", "a:UR", 0, 1)})
    pl = placed(p)
    assert pl["low"][0] == "a" and pl["mid"][0] == "a"          # kept exactly where they were
    assert "new" in pl and not p.reshuffles and p.summary["kept_groups"] == 2
    kept = {x["group_id"]: x["reason"] for x in p.placements}
    assert kept["low"]["stability"]["kept"] is True and kept["low"]["rank"] == 3


def reshuffle_case(arr_b=165, low_prio=1, override=False, low_group=None, vehicles=None, free=None, cfg=None, pins=None):
    vs, fr = (vehicles, free) if vehicles else two_buses(arr_b=arr_b)
    low = low_group or grp("low", prio=low_prio)
    urgent = grp("urgent", size=2, prio=9)
    return run_pinned([low, urgent], vs, fr, pins or _pin("low", "a:UR", 0, 1, override=override), cfg)


def test_bounded_reshuffle_moves_a_lower_priority_tentative_group_so_a_higher_priority_one_is_placed():
    p = reshuffle_case(165)                                       # b arrives +15 after a: exactly on the tolerance
    assert placed(p) == {"urgent": ("a", "a:UR"), "low": ("b", "b:UR")}
    rec = p.reshuffles[0]
    assert rec["beneficiary"] == "urgent" and (rec["heads_placed"], rec["heads_moved"], rec["net_heads_placed"]) == (2, 1, 1)
    assert rec["moves"] == [{"group_id": "low", "from": {"pool_id": "a:UR", "arrive_min": 150},
                             "to": {"pool_id": "b:UR", "arrive_min": 165}, "arrival_change_min": 15}]
    assert p.summary["heads_placed"] == 3 and p.summary["heads_unresolved"] == 0
    reasons = {x["group_id"]: x["reason"] for x in p.placements}
    assert reasons["low"]["reshuffled_from"]["pool_id"] == "a:UR" and "MOVED by bounded reshuffle" in reasons["low"]["text"]
    assert "Made room" in reasons["urgent"]["text"]


def test_reshuffle_never_moves_a_group_beyond_the_arrival_tolerance():
    p = reshuffle_case(166)                                       # +16 min: worse off by more than the tolerance
    assert placed(p) == {"low": ("a", "a:UR")} and not p.reshuffles
    u = {x["group_id"]: x for x in p.unresolved}["urgent"]
    assert u["reason"]["stability"]["blocked_by"] == ["low"] and "stability rule" in u["reason"]["text"]


def test_reshuffle_never_moves_a_higher_priority_group_or_an_operator_override():
    assert not reshuffle_case(160, low_prio=20).reshuffles                       # low outranks urgent: protected
    p = reshuffle_case(160, override=True)                                       # operator-pinned: never moved
    assert not p.reshuffles and "low" in placed(p) and placed(p)["low"][0] == "a" and "urgent" not in placed(p)


def test_reshuffle_requires_no_worse_class_and_requirements_met():
    sl_a = vehicle("a", "TRAIN", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], 150, 150)], pools=[pool("a:SL", "RESERVED", "SL")])
    # worse class: low (SL ticket) would drop to unreserved on b -> refused
    b_ur = vehicle("b", "BUS", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], 155, 155)], pools=[pool("b:UR")])
    low = grp("low", cls="SL", reserved=True, prio=1)
    pins = _pin("low", "a:SL", 0, 1, step="SAME_CLASS")
    urgent_group = grp("urgent", size=2, cls="SL", reserved=True, prio=9)
    def go(vs, free, low_g=low):
        return run_pinned([low_g, urgent_group], vs, free, pins)
    assert not go([sl_a, b_ur], {"a:SL": [2], "b:UR": [1]}).reshuffles
    # an UPGRADE counts as no worse off: b offers a 3A berth
    b_3a = vehicle("b", "TRAIN", dep=100, stops=[(["CENTRAL"], 100, 100), (["DEST"], 155, 155)], pools=[pool("b:3A", "RESERVED", "3A")])
    assert go([sl_a, b_3a], {"a:SL": [2], "b:3A": [1]}).reshuffles
    # requirements: wheelchair user cannot be moved to an inaccessible vehicle; hard deadline cannot be broken
    wheel = grp("low", prio=1, wheelchair=True)
    vs, free = two_buses(160, wheel_b=False)
    assert not reshuffle_case(vehicles=vs, free=free, low_group=wheel).reshuffles
    late = grp("low", prio=1, deadline=155)
    vs, free = two_buses(160)
    assert not reshuffle_case(vehicles=vs, free=free, low_group=late).reshuffles


def test_reshuffle_moves_at_most_the_configured_number_of_groups_and_never_unplaces_anyone():
    vs, free = two_buses(arr_b=155, cap_a=3, cap_b=2)
    gs = [grp("low1", prio=1), grp("low2", prio=2), grp("urgent", size=3, prio=9, deadline=152)]   # only bus a is in time for urgent
    pins = {**_pin("low1", "a:UR", 0, 1), **_pin("low2", "a:UR", 0, 1)}
    no = run_pinned(gs, vs, free, pins, dict(CFG, reshuffle_max_moves=1))
    assert not no.reshuffles and "urgent" not in placed(no)
    yes = run_pinned(gs, vs, free, pins, dict(CFG, reshuffle_max_moves=2))
    assert len(yes.reshuffles[0]["moves"]) == 2 and set(placed(yes)) == {"low1", "low2", "urgent"}
    # never fewer people placed than before the reshuffle: every pinned group is still placed
    assert yes.summary["heads_unresolved"] == 0


def test_net_positive_counts_heads_not_groups():
    from safarset.domain.allocator import net_positive
    assert not net_positive(moved_heads=2, placed_heads=1)      # moving two single travellers to place one: NOT allowed
    assert not net_positive(1, 1)                               # equal is not "strictly more"
    assert not net_positive(2, 2)
    assert net_positive(1, 2) and net_positive(2, 3)


def test_moving_as_many_people_as_would_be_placed_is_refused_even_if_group_counts_look_better():
    vs, free = two_buses(arr_b=155, cap_a=2, cap_b=2)
    pins = {**_pin("low1", "a:UR", 0, 1), **_pin("low2", "a:UR", 0, 1)}
    # one traveller placed by moving one single traveller: 1 head placed vs 1 head moved -> refused
    one = run_pinned([grp("low1", prio=1), grp("low2", prio=2), grp("urgent", size=1, prio=9, deadline=152)], vs, free, pins)
    assert not one.reshuffles and "urgent" not in placed(one)
    stab = {u["group_id"]: u for u in one.unresolved}["urgent"]["reason"]["stability"]
    assert stab["why"] == "MOVES_AS_MANY_HEADS_AS_PLACED" and (stab["moved_heads"], stab["placed_heads"]) == (1, 1)
    # a pair placed by moving two single travellers (2 heads vs 2 heads): refused, although 1 group is placed for 2 moved
    two = run_pinned([grp("low1", prio=1), grp("low2", prio=2), grp("urgent", size=2, prio=9, deadline=152)], vs, free, pins)
    assert not two.reshuffles and "urgent" not in placed(two)
    # moving one single traveller to place a pair of two is fine
    ok = run_pinned([grp("low1", prio=1), grp("urgent", size=2, prio=9, deadline=152)], vs, {"a:UR": [2], "b:UR": [2]}, _pin("low1", "a:UR", 0, 1))
    assert ok.reshuffles and ok.reshuffles[0]["heads_moved"] == 1 and ok.reshuffles[0]["heads_placed"] == 2


def test_the_smallest_set_of_movers_is_chosen():
    """Moving low1 and then pair would move 3 heads (not allowed: 3 is not fewer than the 3 placed); moving only `pair`
    (2 heads) is enough and allowed. The allocator must find the smaller set instead of taking the lowest priority first."""
    vs, free = two_buses(arr_b=155, cap_a=4, cap_b=3)
    gs = [grp("low1", prio=1), grp("pair", size=2, prio=3), grp("urgent", size=3, prio=9, deadline=152)]
    pins = {**_pin("low1", "a:UR", 0, 1), **_pin("pair", "a:UR", 0, 1)}
    p = run_pinned(gs, vs, free, pins)
    assert p.reshuffles and [m["group_id"] for m in p.reshuffles[0]["moves"]] == ["pair"]
    assert (p.reshuffles[0]["heads_moved"], p.reshuffles[0]["heads_placed"]) == (2, 3)
    assert set(placed(p)) == {"low1", "pair", "urgent"} and placed(p)["low1"][0] == "a"


def test_per_mode_checkin_lead_trains_shorter_than_buses():
    cfg = dict(CFG, min_checkin_min={"TRAIN": 10, "BUS": 30})
    train = vehicle("train", "TRAIN", dep=115, stops=[(["CENTRAL"], 115, 115), (["DEST"], 200, 200)], pools=[pool("train:UR")])
    bus = vehicle("bus", "BUS", dep=115, stops=[(["CENTRAL"], 115, 115), (["DEST"], 200, 200)], pools=[pool("bus:UR")])
    p = allocate([grp("g")], {"train": train, "bus": bus}, {"train:UR": [3], "bus:UR": [3]}, scorer=prio_scorer, weights={}, rank_map=RANK,
                 connections=[], now_min=100, config=cfg)
    assert placed(p)["g"][0] == "train"                            # 15 min before departure: boardable by train (10), not by bus (30)
    ctx = {"now_min": 100, "min_checkin_min": {"TRAIN": 10, "BUS": 30}, "walk_m_per_min": 80}
    assert compat.vehicle_option(grp("g"), bus, ctx)[1]["code"] == "TOO_LATE_TO_BOARD" and compat.vehicle_option(grp("g"), train, ctx)[0]


def test_invalid_pins_are_dropped_not_kept():
    vs, free = two_buses(cap_a=3, cap_b=3)
    vs[0]["status"] = "CANCELLED"
    p = run_pinned([grp("g", prio=1)], vs, free, _pin("g", "a:UR", 0, 1))
    assert p.unpinned == {"g": "VEHICLE_CANCELLED"} and placed(p)["g"][0] == "b"
    vs, free = two_buses(cap_a=3, cap_b=3)
    p = allocate([grp("g", prio=1)], {v["vehicle_id"]: v for v in vs}, free, scorer=prio_scorer, weights={}, rank_map=RANK,
                 connections=[], now_min=90, config=dict(CFG, min_checkin_min=30), pinned=_pin("g", "a:UR", 0, 1))
    assert p.unpinned == {"g": "TOO_LATE_TO_BOARD"} and not p.placements


def test_held_groups_are_excluded_and_reported_with_their_cause():
    vs, free = two_buses(cap_a=3, cap_b=3)
    p = allocate([grp("h", prio=99), grp("g", prio=1)], {v["vehicle_id"]: v for v in vs}, free, scorer=prio_scorer, weights={}, rank_map=RANK,
                 connections=[], now_min=0, config=CFG, held={"h": {"why": "medical escort", "size": 1, "dest_place": "DEST"}})
    assert set(placed(p)) == {"g"} and p.order == ["g"]
    assert p.unresolved[0]["reason"]["primary_cause"] == "OPERATOR_HOLD" and "medical escort" in p.unresolved[0]["reason"]["text"]


def test_plan_item_exposes_the_blocking_groups_and_why():
    from safarset.db.conn import new_db
    from safarset.domain.diff import build_diff
    vs, free = two_buses(arr_b=166)                              # +16 min: the blocker cannot move, so urgent stays unresolved
    p = run_pinned([grp("low", prio=1), grp("urgent", size=2, prio=9)], vs, free, _pin("low", "a:UR", 0, 1))
    build_diff(new_db(), p)
    item = next(i for i in p.items if i["kind"] == "UNRESOLVED" and i["group_id"] == "urgent")["detail"]
    assert item["blocking_groups"] == ["low"] and item["blocking_why"] == "NO_ALTERNATIVE_WITHIN_TOLERANCE"
    assert (item["blocking_moved_heads"], item["blocking_placed_heads"]) == (1, 2)
    vs, free = two_buses(arr_b=155, cap_a=2, cap_b=2)
    p = run_pinned([grp("low1", prio=1), grp("urgent", size=1, prio=9, deadline=152)], vs, {"a:UR": [1], "b:UR": [2]}, _pin("low1", "a:UR", 0, 1))
    build_diff(new_db(), p)
    item = next(i for i in p.items if i["kind"] == "UNRESOLVED")["detail"]
    assert item["blocking_why"] == "MOVES_AS_MANY_HEADS_AS_PLACED" and item["blocking_groups"] == ["low1"]
