"""Scripted demo timeline (SIMULATED) built from a generated scenario.

Steps are data, not code: the Phase 8 demo runner plays them against the API and checks `expect`.
kind: sim_event (injected via /sim/*), system (the platform reacts by itself), operator_action (a human clicks).
`expect` values are targets for the demo and are validated against the real allocator in Phase 8; they are
deliberately loose (minimums, not exact counts).
"""


def _fmt(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"


def build_timeline(sc):
    cancel = sc["meta"]["cancel_min"]
    alloc_buses = sorted((v for v in sc["vehicles"] if v["mode"] == "BUS" and v["role"] == "ALLOCATION"),
                         key=lambda v: (v["depart_min"], v["vehicle_id"]))
    alt_trains = sorted((v for v in sc["vehicles"] if v["mode"] == "TRAIN" and v["role"] == "ALLOCATION"
                         and any(p["kind"] == "RESERVED" for p in v["pools"])),
                        key=lambda v: (v["depart_min"], v["vehicle_id"]))
    walkon_rate = sc["behaviour"]["walkon_rate"]

    # Step 4: the earliest special (the one people rush) is reported overcrowded shortly before it leaves.
    bus = alloc_buses[0]
    pool = bus["pools"][0]
    count = round(pool["nominal"] * (1 + walkon_rate))
    t_over = bus["depart_min"] - 5

    # Step 5: a TTE reports no-shows on the first alternate train that has not yet left at that time.
    train = next(t for t in alt_trains if t["depart_min"] > t_over + 30)
    res = max((p for p in train["pools"] if p["kind"] == "RESERVED"), key=lambda p: (p["nominal"], p["pool_id"]))
    nseg = len(res["segments"])
    mean_vacancy = sum(s["vacancy"] for s in res["segments"]) / nseg
    seats = max(4, round(0.25 * mean_vacancy))      # a realistic handful of no-shows, relative to what is free now
    t_noshow = train["depart_min"] - 20      # IR prepares its second chart 30-5 min before departure; seats stay usable (train check-in lead is 10 min)

    steps = [
        {"step": 1, "at_min": cancel, "kind": "sim_event", "type": "TRAIN_CANCELLED",
         "payload": {"vehicle_id": sc["meta"]["cancelled_vehicle_id"], "reason": "SIMULATED cancellation at origin"},
         "expect": {"affected_heads": sc["summary"]["heads"]}},
        {"step": 2, "at_min": cancel + 5, "kind": "system", "type": "PLAN_PROPOSED", "payload": {},
         "expect": {"batch_status": "PROPOSED", "over_allocated_segments": 0, "unresolved_heads_min": 1}},
        {"step": 3, "at_min": cancel + 10, "kind": "operator_action", "type": "APPROVE_BATCH",
         "payload": {"batch": "latest"},
         "expect": {"confirmed_heads_min": 1, "tentative_heads": 0, "sms_sent_for_every_confirmed_group": True}},
        {"step": 4, "at_min": t_over, "kind": "sim_event", "type": "LOAD_REPORT",
         "payload": {"vehicle_id": bus["vehicle_id"], "pool_id": pool["pool_id"], "level": "OVERCROWDED",
                     "count": count, "reported_by": "SIMULATED conductor ETM"},
         "expect": {"vehicle_flag": "overcrowded", "event_logged": True}},
        {"step": 5, "at_min": t_noshow, "kind": "sim_event", "type": "NOSHOWS_REPORTED",
         "payload": {"vehicle_id": train["vehicle_id"], "pool_id": res["pool_id"], "seats_freed": seats,
                     "from_seg": 0, "to_seg": nseg, "reported_by": "SIMULATED TTE HHT"},
         "expect": {"vacancy_increase_seats": seats, "event_logged": True}},
        {"step": 6, "at_min": t_noshow + 1, "kind": "system", "type": "PLAN_PROPOSED", "payload": {"replan": True},
         "expect": {"batch_status": "PROPOSED", "over_allocated_segments": 0, "confirmed_frozen_except_displaced": True,
                    "diff_has_any_of": ["DISPLACED", "NEWLY_PLACED", "RESHUFFLED"]}},
        {"step": 7, "at_min": t_noshow + 6, "kind": "operator_action", "type": "APPROVE_BATCH",
         "payload": {"batch": "latest"}, "expect": {"tentative_heads": 0, "sms_sent_for_every_changed_group": True}},
    ]
    for s in steps:
        s["at"] = _fmt(s["at_min"])
    assert all(a["at_min"] <= b["at_min"] for a, b in zip(steps, steps[1:])), "timeline must be time-ordered"
    return {"label": "SIMULATED", "steps": steps}
