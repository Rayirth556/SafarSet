"""Scripted demo timeline (SIMULATED) built from a generated scenario.

Steps are data, not code: the demo runner plays them against the API and checks `expect`.
kind: sim_event (injected via /sim/*), system (the platform reacts by itself), operator_action (a human clicks).
`expect` values are targets for the demo and are validated against the real allocator by the demo runner and the tests; they are
deliberately loose (minimums, not exact counts).

Every step changes something the operator can see:
  1 cancel          banner, KPIs, a plan proposed for approval (the platform proposes it by itself; there is no separate step)
  2 approve         tentative -> confirmed, messages sent
  3 overcrowded     the bus's confirmed groups are displaced; a re-plan shows them with no replacement yet
  4 extra bus       the depot deploys another special on the same route; the re-plan places the displaced groups on it
  5 approve         the displaced passengers are confirmed on the extra bus and told ("moved to ...")
  6 second chart    vacancies appear on a train; the re-plan places more people who were still waiting
  7 approve         that re-plan is confirmed; only the newly placed groups are messaged
The approval at step 5 has to come before the second chart: the extra bus leaves soon, and a plan that is not approved in time is
dropped by the planner (a bus inside its check-in lead cannot be boarded any more).
"""
import copy

from ..domain import compat


def _fmt(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"


# the depot needs this long to turn a bus out: passengers must be told, walk to the stop, and the allocator's bus check-in lead is 30 min
DEPLOY_TO_DEPARTURE_MIN = 35
DEPLOY_AFTER_REPORT_MIN = 8
APPROVE_AFTER_DEPLOY_MIN = 3


def deployed_clone(sc, bus, depart_min):
    """The extra special the depot sends: same route, same stops and pattern as `bus`, a new id, leaving at `depart_min`."""
    n = max(int(v["vehicle_id"].rsplit("-", 1)[1]) for v in sc["vehicles"] if v["vehicle_id"].startswith("BUS-SPL-")) + 1
    new_id = f"BUS-SPL-{n:02d}"
    v = copy.deepcopy(bus)
    delta = depart_min - bus["depart_min"]
    v["vehicle_id"], v["depart_min"] = new_id, depart_min
    for s in v["stops"]:
        for k in ("arr_min", "dep_min"):
            if s.get(k) is not None:
                s[k] += delta
    for p in v["pools"]:
        p["pool_id"] = f"{new_id}:{p['class']}"
    return v


def build_timeline(sc):
    cancel = sc["meta"]["cancel_min"]
    alloc_buses = sorted((v for v in sc["vehicles"] if v["mode"] == "BUS" and v["role"] == "ALLOCATION"),
                         key=lambda v: (v["depart_min"], v["vehicle_id"]))
    alt_trains = sorted((v for v in sc["vehicles"] if v["mode"] == "TRAIN" and v["role"] == "ALLOCATION"
                         and any(p["kind"] == "RESERVED" for p in v["pools"])),
                        key=lambda v: (v["depart_min"], v["vehicle_id"]))
    walkon_rate = sc["behaviour"]["walkon_rate"]

    # Step 3: the earliest special (the one people rush) is reported overcrowded shortly before it leaves.
    bus = alloc_buses[0]
    pool = bus["pools"][0]
    count = round(pool["nominal"] * (1 + walkon_rate))
    t_over = bus["depart_min"] - 5

    # Step 4: the depot sends another special on the same route.
    t_deploy = t_over + DEPLOY_AFTER_REPORT_MIN
    extra = deployed_clone(sc, bus, t_deploy + DEPLOY_TO_DEPARTURE_MIN)

    # Step 5: second-chart vacancies on a train that has not left yet. IR prepares its final (second) chart about 30 min before
    # departure and it shows berths now vacant; true no-shows are only known around departure.
    train, res, seats = choose_second_chart(sc, alt_trains, t_deploy)
    nseg = len(res["segments"])
    t_chart = train["depart_min"] - 20      # IR prepares its second chart 30-5 min before departure; seats stay usable (train check-in lead is 10 min)

    steps = [
        {"step": 1, "at_min": cancel, "kind": "sim_event", "type": "TRAIN_CANCELLED",
         "payload": {"vehicle_id": sc["meta"]["cancelled_vehicle_id"], "reason": "SIMULATED cancellation at origin"},
         "expect": {"affected_heads": sc["summary"]["heads"], "batch_status": "PROPOSED", "over_allocated_segments": 0, "unresolved_heads_min": 1}},
        {"step": 2, "at_min": cancel + 10, "kind": "operator_action", "type": "APPROVE_BATCH",
         "payload": {"batch": "latest"},
         "expect": {"confirmed_heads_min": 1, "tentative_heads": 0, "sms_sent_for_every_confirmed_group": True}},
        {"step": 3, "at_min": t_over, "kind": "sim_event", "type": "LOAD_REPORT",
         "payload": {"vehicle_id": bus["vehicle_id"], "pool_id": pool["pool_id"], "level": "OVERCROWDED",
                     "count": count, "reported_by": "SIMULATED conductor ETM"},
         "expect": {"vehicle_flag": "overcrowded", "event_logged": True, "displaced_groups_min": 1}},
        {"step": 4, "at_min": t_deploy, "kind": "sim_event", "type": "VEHICLE_DEPLOYED",
         "payload": {"vehicle": extra, "reported_by": "SIMULATED depot control"},
         "expect": {"deployed_vehicle": extra["vehicle_id"], "event_logged": True, "displaced_replaced_share_min": 0.5}},
        {"step": 5, "at_min": t_deploy + APPROVE_AFTER_DEPLOY_MIN, "kind": "operator_action", "type": "APPROVE_BATCH",
         "payload": {"batch": "latest"},
         "expect": {"tentative_heads": 0, "sms_sent_for_every_changed_group": True, "displaced_told_where_they_moved": True}},
        {"step": 6, "at_min": t_chart, "kind": "sim_event", "type": "NOSHOWS_REPORTED",
         "payload": {"vehicle_id": train["vehicle_id"], "pool_id": res["pool_id"], "seats_freed": seats,
                     "from_seg": 0, "to_seg": nseg, "reported_by": "SIMULATED second chart (TTE hand-held terminal)"},
         "expect": {"vacancy_increase_seats": seats, "event_logged": True, "newly_placed_groups_min": 1,
                    "confirmed_frozen_except_displaced": True}},
        {"step": 7, "at_min": t_chart + 5, "kind": "operator_action", "type": "APPROVE_BATCH",
         "payload": {"batch": "latest"}, "expect": {"tentative_heads": 0, "sms_sent_for_every_changed_group": True}},
    ]
    labels = {1: "Train cancelled; plan proposed for approval", 2: "Operator approves the plan",
              3: "Conductor reports a bus overcrowded", 4: f"Depot deploys an extra {bus['name'] or 'special'} bus",
              5: "Operator approves the re-plan", 6: "Second-chart vacancies reported on a train", 7: "Operator approves the second re-plan"}
    for s in steps:
        s["at"] = _fmt(s["at_min"])
        s["label"] = labels[s["step"]]
    assert all(a["at_min"] <= b["at_min"] for a, b in zip(steps, steps[1:])), "timeline must be time-ordered"
    return {"label": "SIMULATED", "steps": steps}


def choose_second_chart(sc, alt_trains, t_deploy):
    """The train, reserved coach (pool) and number of seats for the second-chart report.

    Second-chart vacancies are reserved berths, so they can only help passengers who hold reserved tickets (an unreserved ticket cannot use
    a reserved coach). The demo should therefore show them on a train that reaches destinations where such passengers are likely to be
    waiting: places no direct bus serves (here Tiruvallur and Jolarpettai), because everywhere else a reserved passenger can fall back on a
    bus. The coach is the one whose class matches most of that demand (same class needs no downgrade). Chosen from the scenario's own
    passenger list, so it follows the seed and the parameters."""
    rank = {c: i for i, c in enumerate(sc["class_rank"])}
    bus_places = {pl for v in sc["vehicles"] if v["role"] == "ALLOCATION" and v["mode"] == "BUS" for s in v["stops"][1:] for pl in s["serves_places"]}
    reserved = [g for g in sc["groups"] if g["reserved"]]
    best, best_key = None, None
    for t in alt_trains:
        if t["depart_min"] <= t_deploy + 30:
            continue
        served = {pl for s in t["stops"][t["boarding"]["stop_seq"] + 1:] for pl in s["serves_places"]}
        wanted = [g for g in reserved if g["dest_place"] in served and g["dest_place"] not in bus_places]
        for p in t["pools"]:
            if p["kind"] != "RESERVED":
                continue
            fits = [g for g in wanted if compat.class_step(g, p, rank) is not None]
            same = sum(g["size"] for g in fits if g["class"] == p["class"])
            key = (sum(g["size"] for g in fits), same, p["nominal"], -t["depart_min"])
            if best_key is None or key > best_key:
                best, best_key = (t, p, key[0]), key
    if best is None or best_key[0] == 0:             # no such demand: any train that has not left, its biggest coach
        train = next(t for t in alt_trains if t["depart_min"] > t_deploy + 30)
        res = max((p for p in train["pools"] if p["kind"] == "RESERVED"), key=lambda p: (p["nominal"], p["pool_id"]))
        mean_vacancy = sum(s["vacancy"] for s in res["segments"]) / len(res["segments"])
        return train, res, max(4, round(0.25 * mean_vacancy))
    train, res, demand = best
    return train, res, max(6, min(12, round(0.5 * demand)))     # a realistic handful of newly vacant berths: half the waiting demand, 6 to 12
