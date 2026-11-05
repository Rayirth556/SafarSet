"""Allocator end-to-end on the generated scenario, through the database. Every placement is re-verified by code that
does not share the allocator's logic. These tests assert structure and rule compliance, not how large the shortfall is
(the scenario shortage is tuned, so it is not a result)."""
import json
import math

import pytest

from safarset.db.conn import new_db
from safarset.db.invariants import check_invariants
from safarset.domain.planner import propose_plan, submit_plan
from safarset.events.apply import apply_event
from safarset.events.queries import list_events
from safarset.sim.generator import generate

NOW = 845          # 14:05, five minutes after the cancellation
CHECKIN = {"TRAIN": 10, "BUS": 30}      # per-mode check-in lead (config/allocator.json)


@pytest.fixture(scope="module")
def scenario():
    return generate(42)


@pytest.fixture()
def db(scenario):
    c = new_db()
    apply_event(c, "SCENARIO_LOADED", "sim", {"scenario": scenario})
    apply_event(c, "TRAIN_CANCELLED", "sim", {"vehicle_id": "TRAIN-SIM-CXL"}, ts_sim=840)
    return c


def rows(c, sql, *a):
    return c.execute(sql, a).fetchall()


def plan_and_submit(c, batch="B1", now=NOW):
    plan = propose_plan(c, now)
    submit_plan(c, plan, batch, ts_sim=now)
    return plan


def test_plan_partitions_every_group_and_the_database_accepts_it(db):
    plan = plan_and_submit(db)
    placed = {a["group_id"] for a in plan.placements}
    unresolved = {u["group_id"] for u in plan.unresolved}
    assert not placed & unresolved
    assert placed | unresolved == {r["group_id"] for r in rows(db, "SELECT group_id FROM groups WHERE affected = 1")}
    assert len(plan.order) == len(placed) + len(unresolved)
    assert plan.summary["heads_placed"] + plan.summary["heads_unresolved"] == 300
    assert check_invariants(db) == []
    assert rows(db, "SELECT COUNT(*) n FROM allocations WHERE status='TENTATIVE'")[0]["n"] == len(placed)
    assert rows(db, "SELECT COUNT(*) n FROM batch_items WHERE kind='UNRESOLVED'")[0]["n"] == len(unresolved)


def test_every_placement_is_independently_rule_compliant(db, scenario):
    plan_and_submit(db)
    rank = {c: i for i, c in enumerate(scenario["class_rank"])}
    vehicles = {v["vehicle_id"]: v for v in scenario["vehicles"]}
    pools = {p["pool_id"]: (v, p) for v in scenario["vehicles"] for p in v["pools"]}
    for a in rows(db, "SELECT a.*, g.dest_place, g.class gclass, g.reserved, g.requirements, g.attrs FROM allocations a JOIN groups g USING (group_id)"):
        v, p = pools[a["pool_id"]]
        stops = v["stops"]
        assert v["role"] == "ALLOCATION" and 0 <= a["board_idx"] < a["alight_idx"] < len(stops)
        assert a["dest_place"] in stops[a["alight_idx"]]["serves_places"]
        assert not any(a["dest_place"] in s["serves_places"] for s in stops[a["board_idx"] + 1:a["alight_idx"]]), "must alight at the first matching stop"
        assert "CENTRAL" in stops[a["board_idx"]]["serves_places"]
        assert stops[a["board_idx"]]["dep_min"] >= NOW + CHECKIN[v["mode"]]
        if json.loads(a["requirements"])["wheelchair"]:
            assert v["attrs"]["wheelchair_accessible"]
        deadline = json.loads(a["attrs"])["deadline_min"]
        if deadline is not None:
            assert stops[a["alight_idx"]]["arr_min"] <= deadline
        if not a["reserved"]:
            assert p["kind"] == "UNRESERVED", "a ticketed-unreserved group must never take a reserved berth"
        elif p["kind"] == "RESERVED":
            assert p["class"] in rank
        reason = json.loads(a["reason"])
        assert reason["chosen"]["pool_id"] == a["pool_id"] and reason["text"] and reason["score"]["breakdown"]
        step = reason["chosen"]["class_step"]
        if a["reserved"] and p["kind"] == "RESERVED":
            expect = "SAME_CLASS" if p["class"] == a["gclass"] else ("UPGRADE" if rank[p["class"]] > rank[a["gclass"]] else "LOWER_CLASS_FLAGGED")
            assert step == expect
            assert reason["chosen"]["class_flagged"] == (expect == "LOWER_CLASS_FLAGGED")
        elif a["reserved"]:
            assert step == "UNRESERVED_LAST_RESORT"


def test_no_over_allocation_and_buffers_are_respected_per_mode(db, scenario):
    plan_and_submit(db)
    for r in rows(db, "SELECT s.pool_id, s.seg_idx, s.cap, s.used, s.committed_other, p.kind, p.nominal, p.buffer_pct FROM segment_capacity s JOIN pools p USING (pool_id)"):
        assert 0 <= r["used"] <= r["cap"]
        if r["kind"] == "UNRESERVED":      # buffered: never more than floor(nominal x buffer%) minus people already aboard
            assert r["used"] <= max(0, math.floor(r["nominal"] * r["buffer_pct"] + 1e-9) - r["committed_other"])
        else:                              # reserved train coaches: exact vacancy, no buffer
            assert r["buffer_pct"] is None and r["used"] <= r["cap"]


def test_lowering_a_buffer_shrinks_what_the_plan_may_use(db):
    apply_event(db, "BUFFER_CHANGED", "operator", {"mode": "MTC_BUS", "buffer_pct": 0.25})
    plan_and_submit(db)
    for r in rows(db, "SELECT used FROM segment_capacity WHERE pool_id LIKE 'BUS-SPL-%'"):
        assert r["used"] <= 10                                  # floor(40 x 25%)
    assert check_invariants(db) == []


def test_replan_is_idempotent_and_deterministic(db):
    first = propose_plan(db, NOW)
    again = propose_plan(db, NOW)
    assert json.dumps(first.placements, sort_keys=True) == json.dumps(again.placements, sort_keys=True)
    assert json.dumps(first.unresolved, sort_keys=True) == json.dumps(again.unresolved, sort_keys=True)
    submit_plan(db, first, "B1", ts_sim=NOW)
    # tentative seats count as free, so re-planning an unchanged world reproduces the same plan
    replan = propose_plan(db, NOW)
    assert {(a["group_id"], a["pool_id"], a["board_idx"], a["alight_idx"]) for a in replan.placements} == \
           {(a["group_id"], a["pool_id"], a["board_idx"], a["alight_idx"]) for a in first.placements}
    submit_plan(db, replan, "B2", ts_sim=NOW)
    assert check_invariants(db) == []


def test_confirmed_seats_stay_fixed_in_the_next_plan(db):
    p1 = plan_and_submit(db)
    apply_event(db, "BATCH_APPROVED", "operator", {"batch_id": "B1"})
    confirmed = {r["group_id"] for r in rows(db, "SELECT group_id FROM allocations WHERE status='CONFIRMED'")}
    p2 = propose_plan(db, NOW + 10)
    assert not confirmed & ({a["group_id"] for a in p2.placements} | {u["group_id"] for u in p2.unresolved})
    submit_plan(db, p2, "B2", ts_sim=NOW + 10)
    assert {r["group_id"] for r in rows(db, "SELECT group_id FROM allocations WHERE status='CONFIRMED'")} == confirmed
    assert check_invariants(db) == []


def test_cancelled_or_delayed_vehicles_are_handled(db, scenario):
    apply_event(db, "TRAIN_CANCELLED", "sim", {"vehicle_id": "TRAIN-SIM-ALT-1"})
    apply_event(db, "TRAIN_DELAYED", "sim", {"vehicle_id": "TRAIN-SIM-ALT-2", "delay_min": 90})
    plan = plan_and_submit(db)
    assert all(a["pool_id"].split(":")[0] != "TRAIN-SIM-ALT-1" for a in plan.placements)
    alt2 = {v["vehicle_id"]: v for v in scenario["vehicles"]}["TRAIN-SIM-ALT-2"]
    for a in plan.placements:
        ch = a["reason"]["chosen"]
        if ch["vehicle_id"] == "TRAIN-SIM-ALT-2":
            assert ch["arrive_min"] == alt2["stops"][ch["alight_idx"]]["arr_min"] + 90
            assert ch["depart_min"] == alt2["stops"][ch["board_idx"]]["dep_min"] + 90


def test_operator_weights_change_the_order(db):
    base = propose_plan(db, NOW)
    apply_event(db, "WEIGHTS_CHANGED", "operator", {"weights": {"medical_disability": 40, "senior_60_plus": 5000, "child_or_pregnant": 30,
                                                                 "hard_deadline": 20, "reserved_pnr": 10, "ageing_per_hour": 6}})
    heavy = propose_plan(db, NOW)
    seniors = {r["group_id"] for r in rows(db, "SELECT group_id, attrs FROM groups") if json.loads(r["attrs"])["has_senior"]}
    assert seniors and set(heavy.order[:len(seniors)]) == seniors and base.order != heavy.order
    assert heavy.summary["weights"]["senior_60_plus"] == 5000


def test_unresolved_groups_carry_cause_and_ranked_alternatives(db):
    plan = propose_plan(db, NOW)
    for u in plan.unresolved:
        assert u["reason"]["unresolved"] and u["reason"]["primary_cause"] and u["reason"]["text"]
        alts = u["alternatives"]
        assert alts and alts[-1]["type"] == "WAITLIST" and [a["rank"] for a in alts] == list(range(1, len(alts) + 1))
        assert all(a["type"] in ("LATE_ARRIVAL", "MULTI_LEG", "WAITLIST") for a in alts)
        times = [a["arrive_min"] for a in alts[:-1]]
        assert times == sorted(times)
        json.dumps(u)
    by_dest = {}
    for u in plan.unresolved:                           # waitlist positions are 1..n per destination, in priority order
        by_dest.setdefault(u["dest_place"], []).append(u["alternatives"][-1]["position"])
    assert all(p == list(range(1, len(p) + 1)) for p in by_dest.values())


def test_rejected_events_are_hidden_by_default_in_the_event_list(db):
    with pytest.raises(Exception):
        apply_event(db, "BATCH_APPROVED", "operator", {"batch_id": "NOPE"})
    assert "COMMAND_REJECTED" not in {e["type"] for e in list_events(db)}
    assert "COMMAND_REJECTED" in {e["type"] for e in list_events(db, hide_rejected=False)}
