"""Scenario sanity checks. These catch generator/data mistakes that would silently starve a destination (e.g. the
Avadi buses once ended at an unmapped GTFS stop, so no bus served Avadi even though trains did).

validate_scenario returns (errors, warnings). Errors make `generate` raise; warnings are recorded in meta.warnings.
"""
from ..domain import compat
from ..domain.state import load_config
from . import world


def _as_vehicle(v):
    return dict(v, status=v.get("status", "SCHEDULED"), delay_min=v.get("delay_min", 0))


def validate_scenario(sc, config=None):
    cfg = config or load_config()
    ctx = {"now_min": sc["meta"]["cancel_min"] + 5, "min_checkin_min": cfg["min_checkin_min"], "walk_m_per_min": cfg["walk_m_per_min"]}
    rank = {c: i for i, c in enumerate(sc["class_rank"])}
    vehicles = [_as_vehicle(v) for v in sc["vehicles"] if v["role"] == "ALLOCATION"]
    errors, warnings = [], []

    # 1. every allocatable vehicle reaches at least one destination, and routes reach the place they were chosen for
    for v in vehicles:
        served = {pl for s in v["stops"][v["boarding"]["stop_seq"] + 1:] for pl in s["serves_places"]}
        if not served:
            errors.append(f"{v['vehicle_id']} serves no destination after its boarding stop")
        expected = world.ROUTE_EXPECTED_PLACE.get(v.get("route_id"))
        if expected and expected not in served:
            errors.append(f"{v['vehicle_id']} (route {v['route_id']}) never reaches {expected}")

    # 2. every demanded destination has a compatible allocatable vehicle, for both reserved and unreserved tickets
    probes = {"reserved": {"reserved": True, "class": "SL"}, "unreserved": {"reserved": False, "class": "UR"}}
    for place in sorted({g["dest_place"] for g in sc["groups"]}):
        for label, p in probes.items():
            g = {"size": 1, **p, "board_place": "CENTRAL", "dest_place": place, "requirements": {}, "attrs": {"deadline_min": None}}
            if not any(compat.structurally_compatible(g, v, ctx, rank) for v in vehicles):
                errors.append(f"destination {place}: no compatible allocatable vehicle for a {label} ticket")

    # 3. individual groups that no vehicle can ever take (wheelchair, deadline): legitimate but worth flagging
    impossible = [g["group_id"] for g in sc["groups"]
                  if not any(compat.structurally_compatible(g, v, ctx, rank) for v in vehicles)]
    if impossible:
        warnings.append(f"{len(impossible)} group(s) have no structurally compatible vehicle: {impossible[:10]}")
    return errors, warnings
