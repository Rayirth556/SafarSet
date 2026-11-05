"""Compatibility rules, as pure functions over plain dicts (used by the allocator and by scenario validation).

Vehicle dict: {vehicle_id, mode, role, status, delay_min, depart_min, boarding{stop_seq, walk_m}, attrs, stops[], pools[]}
Group dict:   {size, class, reserved, board_place, dest_place, requirements{}, attrs{deadline_min}}
A stop is {seq, serves_places[], arr_min, dep_min}; times are scenario minutes (delay is added here, not stored).
"""
import math

STEP_SAME, STEP_UPGRADE, STEP_LOWER, STEP_UNRESERVED = 0, 1, 2, 3
STEP_NAMES = {STEP_SAME: "SAME_CLASS", STEP_UPGRADE: "UPGRADE", STEP_LOWER: "LOWER_CLASS_FLAGGED",
              STEP_UNRESERVED: "UNRESERVED_LAST_RESORT"}
TICKETED_UNRESERVED = "UNRESERVED_TICKET"


def class_step(group, pool, rank):
    """(step, name, detail) or None if the group may not use this pool.

    Reserved group: same class -> upgrade (higher class) -> lower class (flagged) -> unreserved as last resort.
    Ticketed-unreserved group: unreserved pools only (buses, general coaches)."""
    if not group["reserved"]:
        return (STEP_SAME, TICKETED_UNRESERVED, 0) if pool["kind"] == "UNRESERVED" else None
    if pool["kind"] == "UNRESERVED":
        return STEP_UNRESERVED, STEP_NAMES[STEP_UNRESERVED], 0
    gr, pr = rank.get(group["class"]), rank.get(pool["class"])
    if gr is None or pr is None:
        return None
    if pool["class"] == group["class"]:
        return STEP_SAME, STEP_NAMES[STEP_SAME], 0
    if pr > gr:
        return STEP_UPGRADE, STEP_NAMES[STEP_UPGRADE], pr - gr
    return STEP_LOWER, STEP_NAMES[STEP_LOWER], gr - pr


def checkin_min(ctx, mode):
    """Check-in lead for a mode: ctx["min_checkin_min"] is {"TRAIN": n, "BUS": n} (a plain number applies to every mode)."""
    c = ctx["min_checkin_min"]
    return c[mode] if isinstance(c, dict) else c


def vehicle_option(group, vehicle, ctx):
    """Resolve boarding/destination stops and timing for a group on a vehicle (capacity and class not yet considered).

    Returns ({"b","j","depart","arrive","walk_min"}, None) if feasible, else (None, {"code", ...}).
    ctx: now_min, min_checkin_min (per mode), walk_m_per_min."""
    if vehicle["status"] != "SCHEDULED":
        return None, {"code": "VEHICLE_CANCELLED"}
    if vehicle["role"] != "ALLOCATION":
        return None, {"code": "NOT_ALLOCATABLE"}
    stops, b = vehicle["stops"], vehicle["boarding"]["stop_seq"]
    if group["board_place"] not in stops[b]["serves_places"]:
        return None, {"code": "NO_BOARDING_STOP"}
    j = next((s["seq"] for s in stops[b + 1:] if group["dest_place"] in s["serves_places"]), None)
    if j is None:
        return None, {"code": "NO_DESTINATION"}
    delay = vehicle.get("delay_min", 0)
    depart, arrive = stops[b]["dep_min"] + delay, stops[j]["arr_min"] + delay
    walk_min = int(math.ceil((vehicle["boarding"].get("walk_m") or 0) / ctx["walk_m_per_min"]))
    needed_by = ctx["now_min"] + checkin_min(ctx, vehicle["mode"]) + walk_min
    if depart < needed_by:
        return None, {"code": "TOO_LATE_TO_BOARD", "depart": depart, "needed_by": needed_by}
    if group["requirements"].get("wheelchair") and not vehicle["attrs"].get("wheelchair_accessible"):
        return None, {"code": "WHEELCHAIR_NOT_ACCESSIBLE", "arrive": arrive}
    deadline = group["attrs"].get("deadline_min")
    if deadline is not None and arrive > deadline:
        return None, {"code": "MISSES_DEADLINE", "arrive": arrive, "deadline": deadline, "late_by_min": arrive - deadline}
    return {"b": b, "j": j, "depart": depart, "arrive": arrive, "walk_min": walk_min}, None


def structurally_compatible(group, vehicle, ctx, rank):
    """Capacity-free compatibility: some pool of this vehicle may carry the group, and the vehicle can reach the
    destination in time. Used by scenario validation."""
    opt, _ = vehicle_option(group, vehicle, ctx)
    return opt is not None and any(class_step(group, p, rank) is not None for p in vehicle["pools"])
