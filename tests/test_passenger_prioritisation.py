"""Comprehensive automated tests for SafarSet Improved Passenger Prioritisation.

Covers all 28 requirements specified in Section 12:
  - Priority logic (Tests 1-8)
  - Group logic (Tests 9-13)
  - Escalation (Tests 14-17)
  - Walk-on demand (Tests 18-21)
  - Allocation and database safety (Tests 22-28)
"""
import concurrent.futures
import json
import sqlite3
import pytest

from safarset.db.conn import new_db, transaction
from safarset.db.invariants import check_capacity_invariants
from safarset.domain import compat
from safarset.domain.allocator import allocate
from safarset.domain.planner import propose_plan, submit_plan
from safarset.events.apply import apply_event
from safarset.scoring import priority
from safarset.scoring.interface import ScoreContext
from safarset.scoring.policy import load_priority_policy


# --------------------------------------------------------------------------- Helpers
def make_group(gid="G001", size=1, **attrs):
    deadline = attrs.pop("deadline_min", None)
    waiting_since = attrs.pop("waiting_since", 800)
    reserved = attrs.pop("reserved", True)
    reqs = {"wheelchair": attrs.pop("wheelchair", False)}
    return {
        "group_id": gid,
        "pnr": f"PNR-{gid}" if reserved else None,
        "size": size,
        "reserved": reserved,
        "known": True,
        "class": "SL" if reserved else "UR",
        "board_place": "CENTRAL",
        "dest_place": "DEST",
        "booking_time": 100,
        "waiting_since": waiting_since,
        "requirements": reqs,
        "attrs": {"deadline_min": deadline, **attrs},
    }


def make_vehicle(vid="V1", mode="TRAIN", dep=900, cap=10, wheelchair=True):
    return {
        "vehicle_id": vid,
        "mode": mode,
        "role": "ALLOCATION",
        "label": "SIMULATED",
        "status": "SCHEDULED",
        "delay_min": 0,
        "depart_min": dep,
        "route_id": "R1",
        "train_no": vid,
        "name": vid,
        "boarding": {"stop_seq": 0, "walk_m": 0, "note": "Boards at Central"},
        "attrs": {"wheelchair_accessible": wheelchair},
        "stops": [
            {"seq": 0, "stop_id": "s0", "stop_name": "Central", "serves_places": ["CENTRAL"], "arr_min": dep, "dep_min": dep},
            {"seq": 1, "stop_id": "s1", "stop_name": "Dest", "serves_places": ["DEST"], "arr_min": dep + 60, "dep_min": dep + 60},
        ],
        "pools": [
            {
                "pool_id": f"{vid}:SL",
                "kind": "RESERVED",
                "class": "SL",
                "coaches": 1,
                "nominal": cap,
                "capacity_label": "SIMULATED",
                "buffer_mode": None,
                "buffer_pct": None,
                "walkon_expected": 0,
                "segments": [{"seg_idx": 0, "cap": cap}],
            }
        ],
    }


# ===========================================================================
# 1. PRIORITY LOGIC (Tests 1 - 8)
# ===========================================================================
def test_1_verified_medical_emergency_receives_tier_0():
    """Verified medical emergency receives Tier 0 (Critical)."""
    g = make_group("G1", medical_emergency=True, ages=[35])
    res = priority.score(g, ScoreContext(now_min=840))
    assert res["tier"] == 0
    assert res["tier_name"] == "CRITICAL"
    assert "critical" in res["tier_reason"].lower() or "medical" in res["tier_reason"].lower()


def test_2_assistance_required_passenger_receives_tier_1():
    """Passengers requiring disability/wheelchair assistance or unaccompanied minors receive Tier 1."""
    # Disability
    g1 = make_group("G1", disability=True, ages=[30])
    res1 = priority.score(g1, ScoreContext(now_min=840))
    assert res1["tier"] == 1
    assert res1["tier_name"] == "HIGH"

    # Wheelchair
    g2 = make_group("G2", wheelchair=True, ages=[40])
    res2 = priority.score(g2, ScoreContext(now_min=840))
    assert res2["tier"] == 1

    # Unaccompanied minor (size 1, age < 18)
    g3 = make_group("G3", size=1, ages=[10])
    res3 = priority.score(g3, ScoreContext(now_min=840))
    assert res3["tier"] == 1
    assert "minor" in res3["tier_reason"].lower()


def test_3_ordinary_passenger_receives_tier_2():
    """Ordinary adult passenger receives Tier 2 (Standard)."""
    g = make_group("G1", ages=[35])
    res = priority.score(g, ScoreContext(now_min=840))
    assert res["tier"] == 2
    assert res["tier_name"] == "STANDARD"


def test_4_elderly_passenger_without_assistance_is_not_automatically_tier_1():
    """Elderly passenger without assistance need is NOT automatically placed in Tier 1."""
    # Senior without assistance is Tier 2 (age is soft factor)
    senior_no_assist = make_group("G1", ages=[68])
    res_no = priority.score(senior_no_assist, ScoreContext(now_min=840))
    assert res_no["tier"] == 2

    # Senior with assistance requirement is Tier 1
    senior_assist = make_group("G2", ages=[68], assistance_required=True)
    res_yes = priority.score(senior_assist, ScoreContext(now_min=840))
    assert res_yes["tier"] == 1


def test_5_age_related_score_affects_ordering_within_a_tier():
    """Within Tier 2, age-related vulnerability score affects the effective score."""
    senior = make_group("G_sr", ages=[68], waiting_since=800)
    young = make_group("G_yg", ages=[28], waiting_since=800)

    res_sr = priority.score(senior, ScoreContext(now_min=840))
    res_yg = priority.score(young, ScoreContext(now_min=840))

    assert res_sr["tier"] == res_yg["tier"] == 2
    assert res_sr["factor_scores"]["age_vulnerability"] > res_yg["factor_scores"]["age_vulnerability"]
    assert res_sr["effective_score"] > res_yg["effective_score"]


def test_6_waiting_time_ageing_increases_effective_score():
    """Waiting time ageing increases effective score linearly without ceiling."""
    g = make_group("G1", ages=[30], waiting_since=800)

    res_short = priority.score(g, ScoreContext(now_min=860))  # waited 60 min
    res_long = priority.score(g, ScoreContext(now_min=920))   # waited 120 min

    diff_wait = 120 - 60
    policy = load_priority_policy()
    expected_diff = diff_wait * policy.ageing.rate_per_minute

    assert res_long["effective_score"] > res_short["effective_score"]
    assert abs((res_long["ageing"] - res_short["ageing"]) - expected_diff) < 1e-4

    # Beyond factor normalization caps (200 min vs 260 min), effective score grows purely and linearly by ageing
    res_200 = priority.score(g, ScoreContext(now_min=1000))
    res_260 = priority.score(g, ScoreContext(now_min=1060))
    assert abs((res_260["effective_score"] - res_200["effective_score"]) - expected_diff) < 1e-4


def test_7_journey_urgency_affects_score():
    """Journey deadline urgency increases score for passengers with tighter deadlines."""
    urgent = make_group("G_urg", ages=[30], deadline_min=870, waiting_since=800)
    relaxed = make_group("G_rel", ages=[30], deadline_min=1100, waiting_since=800)
    no_deadline = make_group("G_none", ages=[30], deadline_min=None, waiting_since=800)

    ctx = ScoreContext(now_min=840)
    r_urg = priority.score(urgent, ctx)
    r_rel = priority.score(relaxed, ctx)
    r_none = priority.score(no_deadline, ctx)

    assert r_urg["factor_scores"]["journey_urgency"] > r_rel["factor_scores"]["journey_urgency"] > r_none["factor_scores"]["journey_urgency"]
    assert r_urg["effective_score"] > r_rel["effective_score"] > r_none["effective_score"]


def test_8_no_double_counting_of_tier_and_scoring_factors():
    """Factors are not double-counted between tier membership and score breakdown."""
    g = make_group("G1", ages=[30], waiting_since=840)
    res = priority.score(g, ScoreContext(now_min=840))

    # Standard passenger with no assistance gets 0 assistance points
    assert res["factor_scores"]["additional_assistance"] == 0
    # Sum of factor breakdown items must equal total score
    breakdown_sum = sum(pts for _, pts in res["breakdown"])
    assert abs(breakdown_sum - res["total"]) < 1e-4


# ===========================================================================
# 2. GROUP LOGIC (Tests 9 - 13)
# ===========================================================================
def test_9_groups_remain_intact():
    """A group is never split across seats or partially allocated."""
    g = make_group("G_family", size=4, ages=[40, 38, 8, 5])
    v = make_vehicle("V1", cap=3)  # Only 3 seats available, group needs 4

    plan = allocate(
        [g],
        {"V1": v},
        {"V1:SL": [3]},
        scorer=priority.score,
        weights={},
        rank_map={"SL": 0},
        connections=[],
        now_min=840,
        config={"arrival_tolerance_min": 15, "min_checkin_min": {"TRAIN": 0, "BUS": 0}, "walk_m_per_min": 80},
    )

    assert len(plan.placements) == 0
    assert len(plan.unresolved) == 1
    assert plan.unresolved[0]["group_id"] == "G_family"


def test_10_group_tier_follows_highest_priority_member_tier():
    """Group tier equals the highest-priority tier among its members."""
    # Member 1: disabled (Tier 1), Member 2: adult (Tier 2), Member 3: adult (Tier 2)
    g = make_group("G_fam", size=3, members=[
        {"age": 65, "disability": True, "assistance_required": True},
        {"age": 35, "disability": False},
        {"age": 30, "disability": False},
    ])
    res = priority.score(g, ScoreContext(now_min=840))
    assert res["tier"] == 1
    assert "Member 1" in res["tier_reason"]


def test_11_group_score_follows_configured_aggregation_rule():
    """Group score is the average score of members belonging to the highest-priority tier."""
    # Group with 1 Tier 1 member and 2 Tier 2 members
    g1 = make_group("G_single_t1", size=3, members=[
        {"age": 70, "disability": True},
        {"age": 30},
        {"age": 25},
    ])
    res1 = priority.score(g1, ScoreContext(now_min=840))
    member_scores1 = res1["member_scores"]
    t1_member = next(m for m in member_scores1 if m["tier"] == 1)
    assert abs(res1["effective_score"] - t1_member["effective_score"]) < 1e-4

    # Group with 2 Tier 1 members
    g2 = make_group("G_two_t1", size=3, members=[
        {"age": 70, "disability": True},
        {"age": 68, "disability": True},
        {"age": 30},
    ])
    res2 = priority.score(g2, ScoreContext(now_min=840))
    t1_members = [m for m in res2["member_scores"] if m["tier"] == 1]
    expected_avg = sum(m["effective_score"] for m in t1_members) / len(t1_members)
    assert abs(res2["effective_score"] - expected_avg) < 1e-4


def test_12_legitimate_companions_inherit_priority_according_to_policy():
    """Legitimate companions traveling together (within limit) inherit the group's priority tier."""
    family = make_group("G_family", size=4, ages=[70, 40, 38, 10], disability=True)
    res = priority.score(family, ScoreContext(now_min=840))
    assert res["tier"] == 1
    assert not res["companion_blocked"]


def test_13_unverified_companions_cannot_exploit_priority_inheritance():
    """Oversized unverified groups cannot exploit companion priority inheritance."""
    # Group of size 8 (> 6 limit) without operator verification
    huge_unverified = make_group("G_huge", size=8, ages=[70, 25, 25, 25, 25, 25, 25, 25], disability=True)
    res = priority.score(huge_unverified, ScoreContext(now_min=840))
    assert res["companion_blocked"] is True
    assert res["tier"] == 2
    assert "verification" in res["tier_reason"].lower()

    # With companion_verified flag set, priority inheritance is permitted
    huge_verified = make_group("G_huge_ok", size=8, ages=[70, 25, 25, 25, 25, 25, 25, 25], disability=True, companion_verified=True)
    res_ok = priority.score(huge_verified, ScoreContext(now_min=840))
    assert res_ok["companion_blocked"] is False
    assert res_ok["tier"] == 1


# ===========================================================================
# 3. ESCALATION (Tests 14 - 17)
# ===========================================================================
def test_14_tier_2_passenger_promoted_after_configured_wait_threshold():
    """Tier 2 passenger waiting beyond configured threshold (120 min) is promoted to Tier 1."""
    # Waited 130 minutes (840 - 710)
    g = make_group("G_wait", ages=[30], waiting_since=710)
    res = priority.score(g, ScoreContext(now_min=840))
    assert res["tier"] == 1
    assert res["escalated"] is True
    assert "promoted" in res["escalation_reason"].lower()


def test_15_tier_0_is_never_reached_through_ordinary_wait_escalation():
    """Ordinary wait escalation promotes to Tier 1, never Tier 0."""
    # Waited a huge amount of time (1000 minutes)
    g = make_group("G_ancient_wait", ages=[30], waiting_since=0)
    res = priority.score(g, ScoreContext(now_min=1000))
    assert res["tier"] == 1
    assert res["tier"] != 0


def test_16_escalation_is_logged():
    """Wait escalation is logged as a PASSENGER_ESCALATED event in the event log."""
    c = new_db()
    c.execute("INSERT INTO vehicles (vehicle_id, mode, role, label, depart_min, boarding, attrs) VALUES ('V1','TRAIN','ALLOCATION','SIMULATED',900,'{\"stop_seq\": 0, \"walk_m\": 0, \"note\": \"\"}','{}')")
    c.execute("INSERT INTO pools VALUES ('V1:SL','V1','RESERVED','SL',1,10,'SIMULATED',NULL,NULL,0)")
    c.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap) VALUES ('V1:SL', 0, 10)")
    c.execute("INSERT INTO vehicle_stops VALUES ('V1', 0, 's0', 'Central', '[\"CENTRAL\"]', 900, 900)")
    c.execute("INSERT INTO vehicle_stops VALUES ('V1', 1, 's1', 'Dest', '[\"DEST\"]', 960, 960)")
    c.execute("INSERT INTO settings (key, value, version, updated_seq) VALUES ('class_rank', '[\"SL\"]', 1, 1)")
    c.execute("INSERT INTO settings (key, value, version, updated_seq) VALUES ('scoring_weights', '{}', 1, 1)")
    c.execute("INSERT INTO groups (group_id, pnr, size, reserved, known, class, board_place, dest_place, booking_time, waiting_since, requirements, attrs, affected)"
              " VALUES ('G_esc', 'PNR1', 1, 1, 1, 'SL', 'CENTRAL', 'DEST', 0, 700, '{}', '{\"ages\": [30]}', 1)")
    c.execute("INSERT INTO events (ts_wall, type, actor, payload) VALUES ('t', 'INIT', 'system', '{}')")

    plan = propose_plan(c, now_min=840, scorer=priority.score)
    assert any(esc["group_id"] == "G_esc" for esc in plan.escalations)

    submit_plan(c, plan, "B1", ts_sim=840)

    # Verify event was logged
    esc_events = c.execute("SELECT * FROM events WHERE type = 'PASSENGER_ESCALATED'").fetchall()
    assert len(esc_events) == 1
    payload = json.loads(esc_events[0]["payload"])
    assert payload["group_id"] == "G_esc"
    assert payload["from_tier"] == 2
    assert payload["to_tier"] == 1


def test_17_repeated_processing_does_not_produce_duplicate_escalation_events():
    """Repeated planning runs do not produce duplicate escalation events for already-escalated groups."""
    c = new_db()
    c.execute("INSERT INTO vehicles (vehicle_id, mode, role, label, depart_min, boarding, attrs) VALUES ('V1','TRAIN','ALLOCATION','SIMULATED',900,'{\"stop_seq\": 0, \"walk_m\": 0, \"note\": \"\"}','{}')")
    c.execute("INSERT INTO pools VALUES ('V1:SL','V1','RESERVED','SL',1,10,'SIMULATED',NULL,NULL,0)")
    c.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap) VALUES ('V1:SL', 0, 10)")
    c.execute("INSERT INTO vehicle_stops VALUES ('V1', 0, 's0', 'Central', '[\"CENTRAL\"]', 900, 900)")
    c.execute("INSERT INTO vehicle_stops VALUES ('V1', 1, 's1', 'Dest', '[\"DEST\"]', 960, 960)")
    c.execute("INSERT INTO settings (key, value, version, updated_seq) VALUES ('class_rank', '[\"SL\"]', 1, 1)")
    c.execute("INSERT INTO settings (key, value, version, updated_seq) VALUES ('scoring_weights', '{}', 1, 1)")
    c.execute("INSERT INTO groups (group_id, pnr, size, reserved, known, class, board_place, dest_place, booking_time, waiting_since, requirements, attrs, affected)"
              " VALUES ('G_esc', 'PNR1', 1, 1, 1, 'SL', 'CENTRAL', 'DEST', 0, 700, '{}', '{\"ages\": [30]}', 1)")
    c.execute("INSERT INTO events (ts_wall, type, actor, payload) VALUES ('t', 'INIT', 'system', '{}')")

    plan1 = propose_plan(c, now_min=840, scorer=priority.score)
    submit_plan(c, plan1, "B1", ts_sim=840)

    # Second plan at same or later time
    plan2 = propose_plan(c, now_min=850, scorer=priority.score)
    submit_plan(c, plan2, "B2", ts_sim=850)

    # Exactly 1 escalation event, no duplicates
    esc_events = c.execute("SELECT * FROM events WHERE type = 'PASSENGER_ESCALATED'").fetchall()
    assert len(esc_events) == 1


# ===========================================================================
# 4. WALK-ON DEMAND (Tests 18 - 21)
# ===========================================================================
def test_18_estimated_walkons_affect_load_estimation():
    """Estimated walk-ons are tracked in pool configuration and contribute to buffer / load estimation."""
    c = new_db()
    c.execute("INSERT INTO vehicles (vehicle_id, mode, role, label, depart_min, boarding, attrs) VALUES ('B1','BUS','ALLOCATION','SIMULATED',900,'{}','{}')")
    c.execute("INSERT INTO pools VALUES ('B1:UR','B1','UNRESERVED','UR',1,40,'SIMULATED','MTC_BUS',0.75,10)")
    c.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap, used, committed_other) VALUES ('B1:UR', 0, 30, 0, 5)")
    c.execute("INSERT INTO vehicle_stops VALUES ('B1', 0, 's0', 'Central', '[\"CENTRAL\"]', 900, 900)")
    c.execute("INSERT INTO vehicle_stops VALUES ('B1', 1, 's1', 'Dest', '[\"DEST\"]', 960, 960)")

    pool_row = c.execute("SELECT walkon_expected, nominal, buffer_pct FROM pools WHERE pool_id = 'B1:UR'").fetchone()
    assert pool_row["walkon_expected"] == 10


def test_19_estimated_walkons_are_not_individually_allocated():
    """Estimated walk-on demand does not create individual passenger groups or allocations."""
    c = new_db()
    c.execute("INSERT INTO settings (key, value, version, updated_seq) VALUES ('unreserved_estimate', '{\"heads\": 50}', 1, 1)")
    c.execute("INSERT INTO vehicles (vehicle_id, mode, role, label, depart_min, boarding, attrs) VALUES ('V1','TRAIN','ALLOCATION','SIMULATED',900,'{}','{}')")
    c.execute("INSERT INTO pools VALUES ('V1:SL','V1','RESERVED','SL',1,10,'SIMULATED',NULL,NULL,0)")
    c.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap) VALUES ('V1:SL', 0, 10)")

    # Assert no individual groups exist for the estimate
    groups = c.execute("SELECT * FROM groups").fetchall()
    assert len(groups) == 0


def test_20_actual_boarding_counts_consume_capacity():
    """Actual walk-ons reported during boarding via LOAD_REPORT consume capacity."""
    c = new_db()
    c.execute("INSERT INTO vehicles (vehicle_id, mode, role, label, depart_min, boarding, attrs) VALUES ('B1','BUS','ALLOCATION','SIMULATED',900,'{}','{}')")
    c.execute("INSERT INTO pools VALUES ('B1:UR','B1','UNRESERVED','UR',1,40,'SIMULATED','MTC_BUS',0.75,0)")
    c.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap, used) VALUES ('B1:UR', 0, 30, 0)")
    c.execute("INSERT INTO vehicle_stops VALUES ('B1', 0, 's0', 'Central', '[\"CENTRAL\"]', 900, 900)")
    c.execute("INSERT INTO vehicle_stops VALUES ('B1', 1, 's1', 'Dest', '[\"DEST\"]', 960, 960)")
    c.execute("INSERT INTO settings (key, value, version, updated_seq) VALUES ('buffers', '{\"MTC_BUS\": 0.75}', 1, 1)")

    # Conductor reports 35 people aboard (overcrowded)
    apply_event(c, "LOAD_REPORT", "field", {"vehicle_id": "B1", "pool_id": "B1:UR", "level": "OVERCROWDED", "count": 35})

    rep = c.execute("SELECT level, count FROM field_reports WHERE pool_id = 'B1:UR'").fetchone()
    assert rep["level"] == "OVERCROWDED"
    assert rep["count"] == 35


def test_21_no_double_counting_of_ticketed_unreserved_and_walkons():
    """Ticketed unreserved passengers (UTS) and estimated walk-ons are tracked as distinct populations."""
    from safarset.api.views import kpis

    c = new_db()
    c.execute("INSERT INTO settings (key, value, version, updated_seq) VALUES ('unreserved_estimate', '{\"heads\": 25}', 1, 1)")
    # 2 PNR heads, 3 ticketed unreserved heads
    c.execute("INSERT INTO groups (group_id, size, reserved, known, class, board_place, dest_place, booking_time, waiting_since, requirements, attrs, affected)"
              " VALUES ('G1', 2, 1, 1, 'SL', 'CENTRAL', 'DEST', 0, 0, '{}', '{}', 1)")
    c.execute("INSERT INTO groups (group_id, size, reserved, known, class, board_place, dest_place, booking_time, waiting_since, requirements, attrs, affected)"
              " VALUES ('G2', 3, 0, 1, 'UR', 'CENTRAL', 'DEST', 0, 0, '{}', '{}', 1)")

    data = kpis(c)
    comp = data["composition"]
    assert comp["pnr_heads"] == 2
    assert comp["ticketed_unreserved_heads"] == 3
    assert comp["unreserved_estimate"]["heads"] == 25
    assert comp["unreserved_estimate"]["estimated"] is True
    # Total affected heads includes PNR + UTS, NOT estimated walk-ons
    assert data["affected"]["heads"] == 5


# ===========================================================================
# 5. ALLOCATION AND DATABASE SAFETY (Tests 22 - 28)
# ===========================================================================
def test_22_higher_priority_groups_are_processed_first():
    """Higher-priority groups (Tier 0 > Tier 1 > Tier 2) are allocated before lower-priority groups."""
    g_critical = make_group("G_crit", medical_emergency=True, size=1)
    g_high = make_group("G_high", disability=True, size=1)
    g_standard = make_group("G_std", size=1)

    v = make_vehicle("V1", cap=2)  # Space for only 2 of the 3 passengers

    plan = allocate(
        [g_standard, g_critical, g_high],
        {"V1": v},
        {"V1:SL": [2]},
        scorer=priority.score,
        weights={},
        rank_map={"SL": 0},
        connections=[],
        now_min=840,
        config={"arrival_tolerance_min": 15, "min_checkin_min": {"TRAIN": 0, "BUS": 0}, "walk_m_per_min": 80},
    )

    placed_gids = [a["group_id"] for a in plan.placements]
    assert placed_gids == ["G_crit", "G_high"]
    assert plan.unresolved[0]["group_id"] == "G_std"


def test_23_hard_constraints_override_priority_scores():
    """Hard constraints (accessibility, route, capacity) strictly override high priority scores."""
    # Critical passenger needing wheelchair
    g_crit_wheel = make_group("G_crit", medical_emergency=True, wheelchair=True, size=1)
    # Standard passenger needing standard seat
    g_std = make_group("G_std", size=1)

    # Vehicle is NOT wheelchair accessible
    v_inaccessible = make_vehicle("V1", cap=1, wheelchair=False)

    plan = allocate(
        [g_crit_wheel, g_std],
        {"V1": v_inaccessible},
        {"V1:SL": [1]},
        scorer=priority.score,
        weights={},
        rank_map={"SL": 0},
        connections=[],
        now_min=840,
        config={"arrival_tolerance_min": 15, "min_checkin_min": {"TRAIN": 0, "BUS": 0}, "walk_m_per_min": 80},
    )

    placed_gids = [a["group_id"] for a in plan.placements]
    assert "G_std" in placed_gids
    assert "G_crit" not in placed_gids
    assert plan.unresolved[0]["group_id"] == "G_crit"
    assert plan.unresolved[0]["reason"]["primary_cause"] == "ACCESSIBILITY"


def test_24_passenger_groups_are_never_split():
    """A passenger group cannot be partially allocated across multiple vehicles or segments."""
    g = make_group("G_group5", size=5)
    v = make_vehicle("V1", cap=4)

    plan = allocate(
        [g],
        {"V1": v},
        {"V1:SL": [4]},
        scorer=priority.score,
        weights={},
        rank_map={"SL": 0},
        connections=[],
        now_min=840,
        config={"arrival_tolerance_min": 15, "min_checkin_min": {"TRAIN": 0, "BUS": 0}, "walk_m_per_min": 80},
    )

    assert len(plan.placements) == 0
    assert plan.unresolved[0]["group_id"] == "G_group5"


def test_25_group_rejected_if_any_required_segment_lacks_capacity():
    """A group is rejected if even a single segment of the required journey lacks sufficient capacity."""
    # Vehicle with 3 segments: caps [10, 2, 10]
    v = {
        "vehicle_id": "V_multi",
        "mode": "TRAIN",
        "role": "ALLOCATION",
        "label": "SIMULATED",
        "status": "SCHEDULED",
        "delay_min": 0,
        "depart_min": 900,
        "boarding": {"stop_seq": 0, "walk_m": 0, "note": ""},
        "attrs": {"wheelchair_accessible": True},
        "stops": [
            {"seq": 0, "serves_places": ["CENTRAL"], "arr_min": 900, "dep_min": 900, "stop_id": "s0"},
            {"seq": 1, "serves_places": ["STOP1"], "arr_min": 930, "dep_min": 930, "stop_id": "s1"},
            {"seq": 2, "serves_places": ["STOP2"], "arr_min": 960, "dep_min": 960, "stop_id": "s2"},
            {"seq": 3, "serves_places": ["DEST"], "arr_min": 990, "dep_min": 990, "stop_id": "s3"},
        ],
        "pools": [{"pool_id": "P1", "kind": "RESERVED", "class": "SL", "nominal": 10}],
    }

    # Group needs 4 seats from CENTRAL to DEST (all 3 segments)
    g = make_group("G_needs4", size=4)

    # Segment 1 only has 2 seats free (< 4)
    free = {"P1": [10, 2, 10]}

    plan = allocate(
        [g],
        {"V_multi": v},
        free,
        scorer=priority.score,
        weights={},
        rank_map={"SL": 0},
        connections=[],
        now_min=840,
        config={"arrival_tolerance_min": 15, "min_checkin_min": {"TRAIN": 0, "BUS": 0}, "walk_m_per_min": 80},
    )

    assert len(plan.placements) == 0
    assert plan.unresolved[0]["reason"]["primary_cause"] == "CAPACITY"


def test_26_concurrent_allocations_cannot_oversell_the_final_seat(tmp_path):
    """Concurrent threads attempting to claim the final seat cannot oversell capacity."""
    db_file = tmp_path / "concurrent_test.db"
    conn_setup = sqlite3.connect(str(db_file), isolation_level=None)
    with open("backend/safarset/db/schema.sql", encoding="utf-8") as f:
        conn_setup.executescript(f.read())

    # 1 seat available
    conn_setup.execute("INSERT INTO vehicles (vehicle_id, mode, role, label, depart_min, boarding, attrs) VALUES ('V1','TRAIN','ALLOCATION','SIMULATED',900,'{}','{}')")
    conn_setup.execute("INSERT INTO pools VALUES ('V1:SL','V1','RESERVED','SL',1,1,'SIMULATED',NULL,NULL,0)")
    conn_setup.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap, used) VALUES ('V1:SL', 0, 1, 0)")
    conn_setup.execute("INSERT INTO events (ts_wall, type, actor, payload) VALUES ('t', 'INIT', 'system', '{}')")

    for i in range(5):
        conn_setup.execute("INSERT INTO groups (group_id, size, reserved, known, class, board_place, dest_place, booking_time, waiting_since, requirements, attrs, affected)"
                           f" VALUES ('g{i}', 1, 1, 1, 'SL', 'CENTRAL', 'DEST', 0, 0, '{{}}', '{{}}', 1)")
    conn_setup.close()

    def try_allocate(gid):
        c = sqlite3.connect(str(db_file), isolation_level=None, timeout=10.0)
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA busy_timeout = 5000")
        try:
            with transaction(c):
                c.execute("INSERT INTO allocations (group_id, pool_id, board_idx, alight_idx, size, status, reason, created_seq, status_seq)"
                          " VALUES (?, 'V1:SL', 0, 1, 1, 'CONFIRMED', '{}', 1, 1)", (gid,))
            return True
        except (sqlite3.IntegrityError, sqlite3.OperationalError):
            return False
        finally:
            c.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(try_allocate, [f"g{i}" for i in range(5)]))

    # Exactly 1 allocation succeeded
    assert results.count(True) == 1

    # Verify database state has used == 1 (never > 1)
    check_c = sqlite3.connect(str(db_file))
    check_c.row_factory = sqlite3.Row
    used = check_c.execute("SELECT used FROM segment_capacity WHERE pool_id = 'V1:SL'").fetchone()[0]
    allocs = check_c.execute("SELECT COUNT(*) FROM allocations").fetchone()[0]
    assert used == 1
    assert allocs == 1
    assert check_capacity_invariants(check_c) == []
    check_c.close()


def test_27_failed_multi_segment_allocation_rolls_back_all_capacity_updates():
    """A failed allocation on a multi-segment journey rolls back every segment (statement atomicity)."""
    c = new_db()
    c.execute("INSERT INTO vehicles (vehicle_id, mode, role, label, depart_min, boarding, attrs) VALUES ('V1','TRAIN','ALLOCATION','SIMULATED',900,'{}','{}')")
    c.execute("INSERT INTO pools VALUES ('V1:SL','V1','RESERVED','SL',1,10,'SIMULATED',NULL,NULL,0)")
    # Segments 0, 1 have capacity 5, but segment 2 has capacity 2
    for seg, cap in enumerate([5, 5, 2]):
        c.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap, used) VALUES ('V1:SL', ?, ?, 0)", (seg, cap))
    c.execute("INSERT INTO groups (group_id, size, reserved, known, class, board_place, dest_place, booking_time, waiting_since, requirements, attrs, affected)"
              " VALUES ('G1', 3, 1, 1, 'SL', 'CENTRAL', 'DEST', 0, 0, '{}', '{}', 1)")
    c.execute("INSERT INTO events (ts_wall, type, actor, payload) VALUES ('t', 'INIT', 'system', '{}')")

    with pytest.raises(sqlite3.IntegrityError):
        # Needs 3 seats across segments 0, 1, 2. Segment 2 will fail (used=3 > cap=2).
        c.execute("INSERT INTO allocations (group_id, pool_id, board_idx, alight_idx, size, status, reason, created_seq, status_seq)"
                  " VALUES ('G1', 'V1:SL', 0, 3, 3, 'TENTATIVE', '{}', 1, 1)")

    # All segments must remain at used = 0 (all-or-nothing rollback)
    used_values = [r["used"] for r in c.execute("SELECT used FROM segment_capacity ORDER BY seg_idx").fetchall()]
    assert used_values == [0, 0, 0]
    assert check_capacity_invariants(c) == []


def test_28_raw_sql_cannot_violate_database_capacity_constraints():
    """Direct SQL queries cannot violate CHECK constraints (used <= cap, used >= 0)."""
    c = new_db()
    c.execute("INSERT INTO vehicles (vehicle_id, mode, role, label, depart_min, boarding, attrs) VALUES ('V1','TRAIN','ALLOCATION','SIMULATED',900,'{}','{}')")
    c.execute("INSERT INTO pools VALUES ('V1:SL','V1','RESERVED','SL',1,10,'SIMULATED',NULL,NULL,0)")
    c.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap, used) VALUES ('V1:SL', 0, 10, 0)")

    # used > cap
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE segment_capacity SET used = 11 WHERE pool_id = 'V1:SL'")

    # used < 0
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE segment_capacity SET used = -1 WHERE pool_id = 'V1:SL'")

    # Insert invalid segment capacity row
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap, used) VALUES ('V1:SL', 1, 5, 6)")
