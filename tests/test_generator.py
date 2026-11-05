import json
import math
from pathlib import Path

import pytest

from safarset.sim.generator import dumps, generate
from scenario_check import crude_unplaced

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def sc():
    return generate(42)


def test_same_seed_is_byte_identical():
    assert dumps(generate(7)) == dumps(generate(7))


def test_different_seeds_differ():
    assert dumps(generate(1)) != dumps(generate(2))


def test_json_round_trip_is_lossless(sc):
    assert json.loads(dumps(sc)) == json.loads(json.dumps(sc))


def test_params_change_output_but_only_where_expected():
    a, b = generate(5, pct_senior=0.05), generate(5, pct_senior=0.40)
    assert a["vehicles"] == b["vehicles"]  # senior share must not touch vehicles (independent random streams)
    assert sum(g["attrs"]["has_senior"] for g in a["groups"]) < sum(g["attrs"]["has_senior"] for g in b["groups"])


@pytest.mark.parametrize("n", [1, 50, 300, 1000])
def test_head_count_is_exact(n):
    assert sum(g["size"] for g in generate(3, n_passengers=n)["groups"]) == n


def test_senior_and_group_shares_are_exact(sc):
    n = 300
    heads = sum(g["size"] for g in sc["groups"])
    seniors = sum(1 for g in sc["groups"] for a in g["attrs"]["ages"] if a >= 60)
    assert seniors == round(n * 0.12)
    in_groups = sum(g["size"] for g in sc["groups"] if g["size"] > 1)
    assert abs(in_groups - round(n * 0.35)) <= 1 and heads == n


def test_groups_are_well_formed(sc):
    ids = [g["group_id"] for g in sc["groups"]]
    assert len(set(ids)) == len(ids)
    pnrs = [g["pnr"] for g in sc["groups"] if g["pnr"]]
    assert len(set(pnrs)) == len(pnrs) and all(p.startswith("SIM") for p in pnrs)
    for g in sc["groups"]:
        assert len(g["attrs"]["ages"]) == g["size"] >= 1
        assert g["reserved"] == (g["pnr"] is not None) == (g["class"] != "UR")
        assert g["dest_place"] in sc["places"] and g["dest_place"] != "CENTRAL"
        if g["attrs"]["has_child_under_12"]:
            assert any(a >= 18 for a in g["attrs"]["ages"]), "child must travel with an adult"
        if g["attrs"]["deadline_min"] is not None:
            assert g["attrs"]["deadline_min"] > sc["meta"]["cancel_min"]
        assert g["waiting_since"] <= sc["meta"]["cancel_min"]
        assert g["attrs"]["phone"].startswith("+91000")  # obviously fake


def test_capacity_invariants_and_buffer_formula(sc):
    for v in sc["vehicles"]:
        nseg = len(v["stops"]) - 1
        assert v["label"] and v["role"]
        for p in v["pools"]:
            assert len(p["segments"]) == nseg
            for s in p["segments"]:
                assert isinstance(s["cap"], int) and s["cap"] >= 0
                if p["kind"] == "RESERVED":
                    assert s["cap"] == s["vacancy"] <= p["nominal"] and p["buffer_pct"] is None
                else:
                    expect = max(0, math.floor(p["nominal"] * p["buffer_pct"] + 1e-9) - s["committed_other"])
                    assert s["cap"] == expect


def test_nominals_follow_decisions(sc):
    caps = json.loads((ROOT / "data/real/capacities.json").read_text(encoding="utf-8"))
    mtc = [p for v in sc["vehicles"] if v["vehicle_id"].startswith("BUS-SPL") for p in v["pools"]]
    ic = [p for v in sc["vehicles"] if v["vehicle_id"].startswith("IC-SPL") for p in v["pools"]]
    assert {p["nominal"] for p in mtc} == {40} and {p["nominal"] for p in ic} == {50}
    assert all(p["capacity_label"] == "SIMULATED" for p in ic)
    sl = caps["rail_per_coach"]["SL"]["capacity"]
    assert all(p["nominal"] % sl == 0 for v in sc["vehicles"] for p in v["pools"] if p["class"] == "SL")


def test_stops_are_time_ordered_and_serve_destinations(sc):
    for v in sc["vehicles"]:
        deps = [s["dep_min"] for s in v["stops"]]
        assert deps == sorted(deps)
        assert v["boarding"]["stop_seq"] == 0
    served = {pl for v in sc["vehicles"] if v["role"] == "ALLOCATION" for s in v["stops"] for pl in s["serves_places"]}
    assert {g["dest_place"] for g in sc["groups"]} <= served


def test_avadi_boards_at_nearest_stop_on_pattern_and_says_straight_line(sc):
    avadi = [v for v in sc["vehicles"] if v["role"] == "ALLOCATION" and v["mode"] == "BUS" and v.get("route_id") in ("MTC-22758", "MTC-22244")]
    assert avadi
    for v in avadi:
        assert v["boarding"]["stop_name"] == "Nurse Quarters" and v["boarding"]["walk_m"] == 260
        assert "straight-line" in v["boarding"]["note"]
    assert all("straight-line" in v["boarding"]["note"] for v in sc["vehicles"]
               if v["role"] == "ALLOCATION" and v["mode"] == "BUS" and v["boarding"]["walk_m"])


def test_unverified_trains_are_labelled_and_incomplete_ones_skipped(sc):
    real = [v for v in sc["vehicles"] if v["mode"] == "TRAIN" and v["label"].startswith("REAL")]
    assert [v["vehicle_id"] for v in real] == ["TRAIN-12607"] and real[0]["label"] == "REAL_DRAFT_UNVERIFIED"
    assert any("12639" in w for w in sc["meta"]["warnings"])
    for f in ("data/real/trains.json", "data/simulated/sim_trains.json"):
        data = json.loads((ROOT / f).read_text(encoding="utf-8"))
        assert all("verified" in t and "simulated" in t for t in data["trains"])
    assert "SIMULATED" in json.loads((ROOT / "data/simulated/sim_trains.json").read_text(encoding="utf-8"))["_kind"]


def test_wheelchair_groups_have_an_accessible_vehicle(sc):
    assert any(g["requirements"]["wheelchair"] for g in generate(11, n_passengers=600)["groups"])
    assert any(v["attrs"]["wheelchair_accessible"] for v in sc["vehicles"] if v["mode"] == "TRAIN")


def test_timeline(sc):
    steps = sc["timeline"]["steps"]
    assert [s["type"] for s in steps] == ["TRAIN_CANCELLED", "APPROVE_BATCH", "LOAD_REPORT", "VEHICLE_DEPLOYED",
                                          "APPROVE_BATCH", "NOSHOWS_REPORTED", "APPROVE_BATCH"]
    assert [s["at_min"] for s in steps] == sorted(s["at_min"] for s in steps)
    vehicles = {v["vehicle_id"]: v for v in sc["vehicles"]}
    over, deploy, noshow = steps[2]["payload"], steps[3]["payload"]["vehicle"], steps[5]["payload"]
    assert over["level"] == "OVERCROWDED" and over["count"] > vehicles[over["vehicle_id"]]["pools"][0]["nominal"]
    assert vehicles[over["vehicle_id"]]["depart_min"] > steps[2]["at_min"]            # reported before boarding
    # the depot's extra special: a new id, the same route and stops as the overcrowded bus, and enough lead time to be boarded
    bus = vehicles[over["vehicle_id"]]
    assert deploy["vehicle_id"] not in vehicles and deploy["route_id"] == bus["route_id"] and deploy["role"] == "ALLOCATION"
    assert [s["stop_id"] for s in deploy["stops"]] == [s["stop_id"] for s in bus["stops"]] and deploy["boarding"] == bus["boarding"]
    assert deploy["depart_min"] >= steps[3]["at_min"] + 30                            # the bus check-in lead
    assert deploy["pools"][0]["pool_id"].startswith(deploy["vehicle_id"] + ":") and deploy["name"] == bus["name"]
    assert steps[4]["at_min"] < deploy["depart_min"] - 30                             # approved while it can still be boarded
    assert vehicles[noshow["vehicle_id"]]["depart_min"] > steps[5]["at_min"]          # train has not left yet
    assert noshow["to_seg"] == len(vehicles[noshow["vehicle_id"]]["stops"]) - 1
    pool = next(p for p in vehicles[noshow["vehicle_id"]]["pools"] if p["pool_id"] == noshow["pool_id"])
    assert 6 <= noshow["seats_freed"] <= 12 or not any(g["reserved"] for g in sc["groups"])     # a handful: half the waiting reserved demand, 6 to 12
    assert noshow["seats_freed"] <= pool["nominal"]
    assert steps[0]["expect"]["affected_heads"] == 300


@pytest.mark.parametrize("seed", [1, 2, 3, 42, 99])
def test_default_scenario_has_a_realistic_shortfall(seed):
    placed, unplaced = crude_unplaced(generate(seed))
    total = placed + sum(unplaced.values())
    assert total == 300 and 0 < sum(unplaced.values()) < 0.5 * total


@pytest.mark.parametrize("kw", [{"pct_senior": 1.5}, {"compliance_rate": -0.1}, {"n_passengers": 0}])
def test_bad_parameters_rejected(kw):
    with pytest.raises(ValueError):
        generate(1, **kw)


def test_shortage_does_not_depend_on_unverified_12607():
    sc = generate(42, exclude_trains=("12607",))
    assert "TRAIN-12607" not in {v["vehicle_id"] for v in sc["vehicles"]}
    for seed in (1, 2, 3, 42, 99):
        placed, unplaced = crude_unplaced(generate(seed, exclude_trains=("12607",)))
        assert sum(unplaced.values()) > 0 and placed + sum(unplaced.values()) == 300


def test_unreserved_populations_are_disjoint(sc):
    est = sc["unreserved_estimate"]
    ticketed = sum(g["size"] for g in sc["groups"] if not g["reserved"])
    assert est["population"] == "UNREGISTERED_WALKONS" and est["ticketed_unreserved_heads_in_groups"] == ticketed
    # the estimate is a separate crowd: the passenger list already adds up to exactly n_passengers without it
    assert sum(g["size"] for g in sc["groups"]) == 300 and est["heads"] > 0
    assert "groups" not in est and "group_ids" not in est
    assert all(g["known"] == g["reserved"] for g in sc["groups"])
    assert est["heads"] < ticketed       # walk-on estimate is derived from, but does not include, the ticketed heads


def test_cancel_time_must_precede_cancelled_departure(sc):
    cxl = next(v for v in sc["vehicles"] if v["role"] == "TO_BE_CANCELLED")
    assert cxl["depart_min"] == 16 * 60 and sc["meta"]["cancel_min"] == 14 * 60   # 2 h notice, per owner
    with pytest.raises(ValueError):
        generate(1, cancel_time="16:00")


def test_class_rank_comes_from_config(sc):
    rank = json.loads((ROOT / "config/class_rank.json").read_text(encoding="utf-8"))["class_rank"]
    assert rank == ["UR", "2S", "SL", "CC", "3A", "2A", "1A"] and sc["class_rank"] == rank
    classes = {p["class"] for v in sc["vehicles"] for p in v["pools"]} | {g["class"] for g in sc["groups"]}
    assert classes <= set(rank)


def test_every_allocatable_bus_serves_a_destination_and_buses_cover_avadi_and_poonamallee(sc):
    """Regression: Avadi routes once ended at a GTFS stop id that was not mapped to AVADI, so no bus served Avadi."""
    buses = [v for v in sc["vehicles"] if v["role"] == "ALLOCATION" and v["mode"] == "BUS"]
    for v in buses:
        served = {pl for s in v["stops"][1:] for pl in s["serves_places"]}
        assert served, f"{v['vehicle_id']} ({v.get('route_id')}) serves no destination"
    served_by_bus = {pl for v in buses for s in v["stops"][1:] for pl in s["serves_places"]}
    assert {"AVADI", "POONAMALLEE"} <= served_by_bus


def test_second_chart_vacancies_fall_in_irs_final_chart_window_and_seats_stay_usable(sc):
    from safarset.domain import compat
    steps = sc["timeline"]["steps"]
    chart = steps[5]
    assert chart["label"] == "Second-chart vacancies reported on a train" and "second chart" in chart["payload"]["reported_by"]
    train = next(v for v in sc["vehicles"] if v["vehicle_id"] == chart["payload"]["vehicle_id"])
    lead = train["depart_min"] - chart["at_min"]
    assert 5 <= lead <= 30, f"second-chart vacancies reported {lead} min before departure; IR's final chart is prepared 30-5 min before"
    ctx = {"now_min": steps[6]["at_min"], "min_checkin_min": {"TRAIN": 10, "BUS": 30}, "walk_m_per_min": 80}
    g = {"size": 1, "reserved": True, "class": "2S", "board_place": "CENTRAL", "dest_place": "ARAKKONAM", "requirements": {}, "attrs": {}}
    veh = dict(train, status="SCHEDULED", delay_min=0)
    assert train["depart_min"] >= steps[6]["at_min"] + 10                     # even the final approval leaves time to board
    opt, rej = compat.vehicle_option(g, veh, ctx)
    assert rej is None or rej["code"] != "TOO_LATE_TO_BOARD"
