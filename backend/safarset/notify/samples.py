"""Fixed sample inputs used for the message review document (docs/messages.md) and the golden tests."""

PLACES = {"CENTRAL": "Chennai Central", "AVADI": "Avadi", "POONAMALLEE": "Poonamallee", "ARAKKONAM": "Arakkonam", "KATPADI": "Katpadi"}


def _group(lang, dest, size=3):
    return {"group_id": "G0001", "size": size, "dest_place": dest, "attrs": {"language": lang, "phone": "+91000000000"}}


def _alloc(vehicle_id, depart, arrive, step="SAME_CLASS", decided="EARLIEST_ARRIVAL", **extra):
    reason = {"algorithm": "greedy-priority-v2", "chosen": {"vehicle_id": vehicle_id, "depart_min": depart, "arrive_min": arrive, "class_step": step},
              "why_chosen": {"decided_by": decided}, "binding_constraints": []}
    reason.update(extra)
    return {"reason": reason}


def _ctx(vehicle, dest_name, stop, walk_m, cause=None):
    ctx = {"vehicle": vehicle, "boarding": {"stop_name": stop, "walk_m": walk_m}, "dest_name": dest_name, "places": PLACES}
    if cause:
        ctx["change_cause"] = cause
    return ctx


BUS = {"vehicle_id": "BUS-SPL-02", "mode": "BUS", "name": "MTC 120 R1", "train_no": None}
TRAIN = {"vehicle_id": "TRAIN-12607", "mode": "TRAIN", "name": "Lalbagh Express", "train_no": "12607"}


def samples():
    """[(title, group, allocation, kind, ctx)] covering every message kind and the main reason shapes."""
    out = []
    for lang in ("en", "ta"):
        out += [
            (f"{lang}: new journey by bus, earliest arrival, Avadi boarding with a walk", _group(lang, "AVADI"),
             _alloc("BUS-SPL-02", 890, 957), "NEW", _ctx(BUS, "Avadi", "Nurse Quarters", 260)),
            (f"{lang}: new journey by train, same class, an earlier option was full", _group(lang, "ARAKKONAM", 1),
             _alloc("TRAIN-12607", 930, 995, decided="CLASS_STEP", **{"binding_constraints": [{"code": "CAPACITY", "vehicle_id": "BUS-SPL-01"}]}),
             "NEW", _ctx(TRAIN, "Arakkonam", None, 0)),
            (f"{lang}: new journey with a class upgrade", _group(lang, "KATPADI", 2),
             _alloc("TRAIN-12607", 930, 1055, step="UPGRADE", decided="ONLY_FEASIBLE_OPTION"), "NEW", _ctx(TRAIN, "Katpadi", None, 0)),
            (f"{lang}: new journey in a lower class (flagged)", _group(lang, "KATPADI", 2),
             _alloc("TRAIN-12607", 930, 1055, step="LOWER_CLASS_FLAGGED"), "NEW", _ctx(TRAIN, "Katpadi", None, 0)),
            (f"{lang}: journey changed after the first bus was too crowded", _group(lang, "POONAMALLEE", 2),
             _alloc("BUS-SPL-03", 922, 981), "CHANGED", _ctx(BUS | {"name": "MTC 101CT", "vehicle_id": "BUS-SPL-03"}, "Poonamallee", "Mgr Central", 100, "LOAD_REPORT")),
            (f"{lang}: journey changed by the control room", _group(lang, "AVADI", 1),
             {"reason": {"algorithm": "operator-override", "chosen": {"vehicle_id": "BUS-SPL-02", "depart_min": 890, "arrive_min": 957, "class_step": "OPERATOR_ASSIGNED"}}},
             "CHANGED", _ctx(BUS, "Avadi", "Nurse Quarters", 260, "OPERATOR_OVERRIDE")),
            (f"{lang}: seat lost, no replacement yet (road closed)", _group(lang, "AVADI", 1), None, "DISPLACED_UNPLACED",
             {"change_cause": "ROAD_CLOSED", "places": PLACES, "dest_name": "Avadi"}),
        ]
    return out
