"""Scenario sanity checks, including a regression for the Phase 2 Avadi bug."""
import pytest

from safarset.sim import world
from safarset.sim.generator import generate
from safarset.sim.validate import validate_scenario


def test_default_scenarios_have_no_errors():
    for seed in (1, 2, 3, 42, 99):
        assert validate_scenario(generate(seed))[0] == []


def test_avadi_bug_regression_unmapped_terminal_stop_is_caught(monkeypatch):
    """Phase 2 bug: Avadi routes ended at an unmapped GTFS stop, so no bus served Avadi (trains still did, so a pure
    per-destination check would have passed). The route-level check must catch it."""
    broken = {k: v for k, v in world.BUS_STOP_PLACES.items() if k != "MTC-10430"}
    monkeypatch.setattr(world, "BUS_STOP_PLACES", broken)
    with pytest.raises(ValueError, match=r"route MTC-22758\) never reaches AVADI"):
        generate(42)


def test_destination_without_any_compatible_vehicle_is_an_error():
    # no MTC specials: Poonamallee has no rail stop, so nothing can carry anyone there
    with pytest.raises(ValueError, match="destination POONAMALLEE: no compatible allocatable vehicle"):
        generate(42, n_mtc_specials=0)


def test_every_destination_is_checked_for_both_ticket_types():
    sc = generate(42)
    for v in sc["vehicles"]:
        if v["mode"] == "TRAIN":                           # drop the unreserved pools: reserved-only trains
            v["pools"] = [p for p in v["pools"] if p["kind"] == "RESERVED"]
        elif v["role"] == "ALLOCATION" and v.get("route_id") in ("MTC-22758", "MTC-22244"):
            v["pools"] = []                                # and Avadi buses with no pool at all
    errors, _ = validate_scenario(sc)
    assert any("AVADI" in e and "unreserved" in e for e in errors)


def test_individually_impossible_groups_are_flagged_as_warnings_not_errors():
    sc = generate(42)
    for g in sc["groups"][:1]:
        g["attrs"]["deadline_min"] = sc["meta"]["cancel_min"] + 6      # nobody can arrive that soon
    errors, warnings = validate_scenario(sc)
    assert errors == [] and any("no structurally compatible vehicle" in w for w in warnings)
