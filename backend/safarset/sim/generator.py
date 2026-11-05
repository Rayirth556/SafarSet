"""Seeded, deterministic SafarSet scenario generator.

generate(seed, n_passengers, pct_senior, pct_groups, compliance_rate, walkon_rate, ...) -> dict

Same arguments (and same input data files) => identical output. Each part of the scenario draws from its own
random stream (seed + part name) so changing one parameter does not reshuffle unrelated parts.

Everything produced here is SIMULATED, except where a field is explicitly labelled REAL (bus route patterns and
stop ids from data/real, and the unverified Lalbagh 12607 draft). The scenario carries `label` fields so that the
UI and tests can tell real from simulated.
"""
from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path

from . import world
from .timeline import build_timeline
from .validate import validate_scenario

SCHEMA_VERSION = 1
LABEL_SIM = "SIMULATED"

# Minutes after the cancelled train's departure at which it would have reached each place. SIMULATED for
# Poonamallee and Vellore (no rail stop), taken from the SIM-CXL stop times otherwise.
_REF_ARRIVAL_OFFSET = {"AVADI": 27, "POONAMALLEE": 55, "TIRUVALLUR": 44, "ARAKKONAM": 64,
                       "KATPADI": 124, "VELLORE": 150, "JOLARPETTAI": 204}


def _rng(seed, part):
    return random.Random(f"safarset:{seed}:{part}")  # string seeds are hashed, stable across runs


def _hhmm(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _fmt_min(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _floor_pct(n, pct):
    return int(math.floor(n * pct + 1e-9))


def _haversine_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    x = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(x))


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------------------------------- data loading
def _load_world(data_dir):
    d = Path(data_dir)
    ref = d / "real" / "reference"
    stops = {r["stop_id"]: r for r in _read_csv(ref / "bus_stops.csv")}
    routes = {r["route_id"]: r for r in _read_csv(ref / "bus_routes.csv")}
    route_stops = {}
    for r in _read_csv(ref / "bus_route_stops.csv"):
        route_stops.setdefault(r["route_id"], []).append(r)
    for rows in route_stops.values():
        rows.sort(key=lambda r: int(r["seq"]))
    trips = {}
    for r in _read_csv(ref / "bus_trips.csv"):
        trips.setdefault(r["route_id"], []).append(r)
    return {
        "stops": stops, "routes": routes, "route_stops": route_stops, "trips": trips,
        "caps": _load_json(d / "real" / "capacities.json"),
        "real_trains": _load_json(d / "real" / "trains.json"),
        "sim_trains": _load_json(d / "simulated" / "sim_trains.json"),
        "stations": _load_json(ref / "stations.json")["stations"],
    }


def _load_buffers(config_dir):
    return _load_json(Path(config_dir) / "buffers.json")["buffer_pct"]


# ----------------------------------------------------------------------------------------------- passengers
def _make_groups(seed, n, p, cxl, cancel_min):
    rng = _rng(seed, "passengers")
    # 1. group sizes. Multi-person groups carry (about) pct_groups of all heads; the rest travel alone.
    remaining = round(n * p["pct_groups"])
    sizes = []
    while remaining >= 2:
        s = min(rng.choices([2, 3, 4, 5], [0.45, 0.30, 0.15, 0.10])[0], remaining)
        if s < 2:
            break
        sizes.append(s)
        remaining -= s
    sizes += [1] * (n - sum(sizes))
    rng.shuffle(sizes)

    # 2. members. idx 0 of every group is the lead adult; only other members of multi-person groups can be children.
    members = [{"g": gi, "idx": k, "age": rng.randint(18, 59), "flags": set()}
               for gi, s in enumerate(sizes) for k in range(s)]

    def pick(pool, count):
        chosen = rng.sample(pool, min(count, len(pool)))
        return chosen

    free = list(range(len(members)))
    for i in pick(free, round(n * p["pct_senior"])):
        members[i]["age"] = rng.randint(60, 85)
        members[i]["flags"].add("senior")
    kid_pool = [i for i in free if members[i]["idx"] > 0 and "senior" not in members[i]["flags"]]
    for i in pick(kid_pool, round(n * p["pct_children"])):
        members[i]["age"] = rng.randint(1, 11)
        members[i]["flags"].add("child")
    adult_pool = [i for i in free if "child" not in members[i]["flags"]]
    for i in pick([i for i in adult_pool if "senior" not in members[i]["flags"]], round(n * p["pct_pregnant"])):
        members[i]["flags"].add("pregnant")
    dis = pick(adult_pool, round(n * p["pct_disabled"]))
    for j, i in enumerate(dis):
        members[i]["flags"].add("disability")
        if rng.random() < 0.3:
            members[i]["flags"].add("wheelchair")

    by_group = {}
    for m in members:
        by_group.setdefault(m["g"], []).append(m)

    # 3. unreserved vs reserved (heads-based target)
    order = list(range(len(sizes)))
    rng.shuffle(order)
    unres, heads = set(), 0
    for gi in order:
        if heads >= round(n * p["pct_unreserved"]):
            break
        unres.add(gi)
        heads += sizes[gi]

    comp = cxl["coaches"]
    per = {c: v["capacity"] for c, v in p["caps"]["rail_per_coach"].items()}
    class_w = {c: comp.get(c, 0) * per[c] for c in world.RESERVED_CLASSES if comp.get(c, 0)}

    dests = list(world.DEST_WEIGHTS)
    weights = [world.DEST_WEIGHTS[x] for x in dests]
    used_pnr, groups = set(), []
    for gi, size in enumerate(sizes):
        ms = by_group[gi]
        reserved = gi not in unres
        pnr = None
        if reserved:
            while True:
                pnr = f"SIM{rng.randint(0, 9999999):07d}"
                if pnr not in used_pnr:
                    used_pnr.add(pnr)
                    break
        dest = rng.choices(dests, weights)[0]
        flags = set().union(*(m["flags"] for m in ms))
        ages = [m["age"] for m in ms]
        deadline = None
        if rng.random() < p["pct_deadline"]:
            deadline = cancel_min + 60 + _REF_ARRIVAL_OFFSET[dest] + rng.choice([45, 90, 120, 180, 240])
        groups.append({
            "group_id": f"G{gi + 1:04d}",
            "pnr": pnr,
            "size": size,
            "reserved": reserved,
            "known": reserved,          # unreserved heads are counted at the station, not exact
            "class": rng.choices(list(class_w), list(class_w.values()))[0] if reserved else "UR",
            "board_place": "CENTRAL",
            "dest_place": dest,
            "booking_time": (-(rng.randint(1, 60) * 1440) + rng.randint(0, 1439)) if reserved
                            else cancel_min - rng.randint(1, 45),
            "waiting_since": cancel_min - rng.randint(0, 45),
            "requirements": {"wheelchair": "wheelchair" in flags},
            "attrs": {
                "ages": ages, "max_age": max(ages),
                "has_senior": "senior" in flags, "has_child_under_12": "child" in flags,
                "pregnant": "pregnant" in flags, "disability": "disability" in flags,
                "medical_need": "disability" in flags or "pregnant" in flags,
                "deadline_min": deadline,
                "language": "ta" if rng.random() < 0.55 else "en",
                "phone": f"+91000{rng.randint(0, 9999999):07d}",   # obviously fake, not a valid Indian mobile
            },
        })
    return groups


# ----------------------------------------------------------------------------------------------- vehicles
def _stop_places_rail(code):
    return [pid for pid, pl in world.PLACES.items() if code in pl["rail"]]


def _seg_series_reserved(rng, nominal, nseg):
    base = nominal * rng.uniform(0.01, 0.035)
    out = []
    for i in range(nseg):
        grow = 1 + 0.25 * (i / max(nseg - 1, 1))      # more seats free further down the line as people alight
        out.append(max(0, round(base * grow) + rng.randint(-2, 2)))
    return out


def _pool(vid, cls, kind, coaches, nominal, label, segs_vals, buffer_mode=None, buffer_pct=None, walkon=0):
    segments = []
    for i, v in enumerate(segs_vals):
        if kind == "RESERVED":
            segments.append({"seg_idx": i, "vacancy": v, "cap": v})
        else:
            cap = max(0, _floor_pct(nominal, buffer_pct) - v)
            segments.append({"seg_idx": i, "committed_other": v, "cap": cap})
    return {"pool_id": f"{vid}:{cls}", "kind": kind, "class": cls, "coaches": coaches, "nominal": nominal,
            "capacity_label": label, "buffer_mode": buffer_mode, "buffer_pct": buffer_pct,
            "walkon_expected": walkon, "segments": segments}


def _train_vehicle(seed, tr, role, w, buffers, walkon_rate, label):
    stops = []
    for k, s in enumerate(tr["stops"]):
        stops.append({"seq": k, "stop_id": s["station"], "serves_places": _stop_places_rail(s["station"]),
                      "arr_min": _hhmm(s["arr"]) if s["arr"] else None, "dep_min": _hhmm(s["dep"])})
    vid = f"TRAIN-{tr['train_no']}"
    nseg = len(stops) - 1
    pools = []
    if role == "ALLOCATION":
        rng = _rng(seed, f"vehicle:{vid}")
        per = w["caps"]["rail_per_coach"]
        for cls, count in tr["coaches"].items():
            nominal = count * per[cls]["capacity"]
            if cls in world.RESERVED_CLASSES:
                pools.append(_pool(vid, cls, "RESERVED", count, nominal, per[cls]["label"],
                                   _seg_series_reserved(rng, nominal, nseg)))
            else:  # GS
                committed = round(nominal * rng.uniform(0.60, 0.72))
                pools.append(_pool(vid, "UR", "UNRESERVED", count, nominal, per[cls]["label"],
                                   [committed] * nseg, "TRAIN_UNRESERVED", buffers["TRAIN_UNRESERVED"],
                                   round(walkon_rate * nominal)))
    return {"vehicle_id": vid, "mode": "TRAIN", "role": role, "label": label, "train_no": tr["train_no"],
            "name": tr["name"], "verified": tr.get("verified", False), "depart_min": stops[0]["dep_min"],
            "boarding": {"stop_seq": 0, "stop_id": "MAS", "walk_m": 0, "note": "Boards at Chennai Central"},
            "attrs": {"wheelchair_accessible": True, "wheelchair_label": LABEL_SIM},
            "stops": stops, "pools": pools}


def _bus_vehicle(vid, role, label, route_id, stops, boarding, nominal, nominal_label, buffer_mode, buffers,
                 committed, walkon, wheelchair, depart_min):
    nseg = len(stops) - 1
    pool = _pool(vid, "UR", "UNRESERVED", 1, nominal, nominal_label, [committed] * nseg, buffer_mode,
                 buffers[buffer_mode], walkon)
    return {"vehicle_id": vid, "mode": "BUS", "role": role, "label": label, "route_id": route_id,
            "depart_min": depart_min, "boarding": boarding,
            "attrs": {"wheelchair_accessible": wheelchair, "wheelchair_label": LABEL_SIM},
            "stops": stops, "pools": [pool]}


def _mtc_stops_from(w, route_id, board_seq, board_dep_min):
    rs = w["route_stops"][route_id]
    off_b = int(rs[board_seq - 1]["dep_offset_s"])
    out = []
    for r in rs[board_seq - 1:]:
        sid = r["stop_id"]
        out.append({"seq": len(out), "stop_id": sid, "stop_name": w["stops"][sid]["stop_name"],
                    "serves_places": list(world.BUS_STOP_PLACES.get(sid, [])),
                    "arr_min": board_dep_min + round((int(r["arr_offset_s"]) - off_b) / 60),
                    "dep_min": board_dep_min + round((int(r["dep_offset_s"]) - off_b) / 60)})
    out[0]["serves_places"] = sorted(set(out[0]["serves_places"]) | {"CENTRAL"})
    return out


def _nearest_board_seq(w, route_id):
    mas = w["stations"]["MAS"]
    best = None
    for r in w["route_stops"][route_id]:
        s = w["stops"][r["stop_id"]]
        d = _haversine_km((float(s["lat"]), float(s["lon"])), (mas["lat"], mas["lon"]))
        if best is None or d < best[0]:
            best = (d, int(r["seq"]), s["stop_name"])
    return best


def _boarding_info(w, route_id):
    d_km, seq, name = _nearest_board_seq(w, route_id)
    walk_m = int(round(d_km * 100) * 10)  # nearest 10 m, straight-line
    return seq, {"stop_seq": 0, "stop_id": w["route_stops"][route_id][seq - 1]["stop_id"], "stop_name": name,
                 "walk_m": walk_m, "note": f"Boards at {name}, about {walk_m} m (straight-line) from Chennai Central"}


def _build_vehicles(seed, w, p, buffers, cancel_min, exclude_trains=()):
    vehicles, warnings = [], []
    cap = w["caps"]
    mtc_nom = cap["bus_nominal_seated"]["MTC_ordinary"]
    ic_nom = cap["bus_nominal_seated"]["INTERCITY_SPECIAL"]

    # --- trains: real draft + simulated; skip any train with incomplete times or no coach mix
    cancelled = None
    for src in (w["real_trains"], w["sim_trains"]):
        for tr in src["trains"]:
            if tr.get("simulated"):
                label = LABEL_SIM
            else:
                label = "REAL" if tr.get("verified") else "REAL_DRAFT_UNVERIFIED"
            incomplete = any((s["dep"] is None) or (k > 0 and s["arr"] is None) for k, s in enumerate(tr["stops"]))
            if incomplete:
                warnings.append(f"train {tr['train_no']} skipped: incomplete timings")
                continue
            role = tr.get("role", "ALTERNATE")
            if tr["train_no"] in exclude_trains:
                warnings.append(f"train {tr['train_no']} excluded by parameter")
                continue
            if role == "ALTERNATE" and "coaches" not in tr:
                warnings.append(f"train {tr['train_no']} skipped: no coach composition")
                continue
            if role == "ALTERNATE" and _hhmm(tr["stops"][0]["dep"]) < cancel_min + 30:
                warnings.append(f"train {tr['train_no']} skipped: departs less than 30 min after cancellation")
                continue
            v = _train_vehicle(seed, tr, "TO_BE_CANCELLED" if role == "CANCELLED" else "ALLOCATION", w, buffers,
                               p["walkon_rate"], label)
            if role == "CANCELLED":
                cancelled = (tr, v)
            vehicles.append(v)
    if cancelled is None:
        raise ValueError("no cancelled train defined (role=CANCELLED) in sim_trains.json")

    # --- MTC specials on real route patterns (deployable, SIMULATED dispatch)
    rng = _rng(seed, "mtc_specials")
    template = ["MTC-22836", "MTC-22758", "MTC-22798", "MTC-22758", "MTC-23210", "MTC-22244", "MTC-22836", "MTC-22758"]
    t = cancel_min + 40
    for k in range(p["n_mtc_specials"]):
        rid = template[k % len(template)]
        seq, boarding = _boarding_info(w, rid)
        stops = _mtc_stops_from(w, rid, seq, t)
        vid = f"BUS-SPL-{k + 1:02d}"
        vehicles.append(_bus_vehicle(vid, "ALLOCATION", "REAL_ROUTE_SIMULATED_DISPATCH", rid, stops, boarding,
                                     mtc_nom["capacity"], mtc_nom["label"], "MTC_BUS", buffers, 0,
                                     round(p["walkon_rate"] * mtc_nom["capacity"]), rng.random() < 0.25, t))
        t += rng.randint(10, 25)

    # --- intercity specials from Central (SIMULATED)
    rng = _rng(seed, "intercity_specials")
    ic = world.INTERCITY_ROUTES["SIM-IC-CENTRAL"]
    for k in range(p["n_intercity_specials"]):
        dep = cancel_min + 150 + 60 * k
        stops = [{"seq": i, "stop_id": f"{'SIM-IC-CENTRAL'}-{i}", "stop_name": nm, "serves_places": list(pl),
                  "arr_min": dep + off, "dep_min": dep + off} for i, (nm, pl, off) in enumerate(ic["stops"])]
        board = {"stop_seq": 0, "stop_id": stops[0]["stop_id"], "stop_name": "Chennai Central",
                 "walk_m": 0, "note": "SIMULATED special departs from Chennai Central"}
        vehicles.append(_bus_vehicle(f"IC-SPL-{k + 1:02d}", "ALLOCATION", LABEL_SIM, "SIM-IC-CENTRAL", stops, board,
                                     ic_nom["capacity"], ic_nom["label"], "INTERCITY_BUS", buffers, 0,
                                     round(p["walkon_rate"] * ic_nom["capacity"]), False, dep))

    # --- regular services used only as legs of multi-leg alternatives (role TRANSFER_LEG)
    rng = _rng(seed, "regular")
    lo, hi = cancel_min + 60, 21 * 60
    for place, rid in world.MTC_TRANSFER_ROUTES.items():
        rs = w["route_stops"][rid]
        if place != "TIRUVALLUR":
            seq, boarding = _boarding_info(w, rid)
        else:  # Tiruvallur leg boards at Poonamallee Bus Terminus (first stop)
            seq, boarding = 1, {"stop_seq": 0, "stop_id": rs[0]["stop_id"], "stop_name": w["stops"][rs[0]["stop_id"]]["stop_name"],
                                "walk_m": None, "note": "Second leg: boards at Poonamallee Bus Terminus"}
        off_b = int(rs[seq - 1]["dep_offset_s"])
        for tr in w["trips"][rid]:
            dep = _hhmm(tr["start_time"][:5]) + round(off_b / 60)
            if not lo <= dep <= hi:
                continue
            stops = _mtc_stops_from(w, rid, seq, dep)
            committed = round(mtc_nom["capacity"] * rng.uniform(0.2, 0.5))
            vehicles.append(_bus_vehicle(f"BUS-REG-{rid[4:]}-{tr['trip_id'][4:]}", "TRANSFER_LEG", "REAL_SCHEDULE_SIMULATED_LOAD",
                                         rid, stops, boarding, mtc_nom["capacity"], mtc_nom["label"], "MTC_BUS",
                                         buffers, committed, 0, False, dep))
    kic = world.INTERCITY_ROUTES["SIM-IC-KOY"]
    for k in range(7):
        dep = 15 * 60 + 30 + 40 * k
        stops = [{"seq": i, "stop_id": f"SIM-IC-KOY-{i}", "stop_name": nm, "serves_places": list(pl),
                  "arr_min": dep + off, "dep_min": dep + off} for i, (nm, pl, off) in enumerate(kic["stops"])]
        board = {"stop_seq": 0, "stop_id": stops[0]["stop_id"], "stop_name": "Koyambedu CMBT", "walk_m": None,
                 "note": "Second leg: boards at Koyambedu CMBT"}
        committed = round(ic_nom["capacity"] * rng.uniform(0.35, 0.65))
        vehicles.append(_bus_vehicle(f"IC-REG-KOY-{k + 1:02d}", "TRANSFER_LEG", LABEL_SIM, "SIM-IC-KOY", stops, board,
                                     ic_nom["capacity"], ic_nom["label"], "INTERCITY_BUS", buffers, committed, 0,
                                     False, dep))
    for v in vehicles:                                     # passenger-facing names (used in SMS): MTC route numbers, labelled intercity buses
        if v["mode"] == "BUS":
            rid = v.get("route_id", "")
            v["name"] = (f"MTC {w['routes'][rid]['short_name']}" if rid in w["routes"]
                         else "Special intercity bus (SIMULATED)" if v["vehicle_id"].startswith("IC-SPL") else "Intercity bus (SIMULATED)")
    return vehicles, cancelled[1], warnings


def _pool_capacity_to(vehicle, pool, place):
    """Upper bound of heads this pool could carry Central->place: min cap over the segments between boarding and the
    first stop serving the place. 0 if the vehicle does not serve it. Ignores class rules and group sizes."""
    stops = vehicle["stops"]
    b = vehicle["boarding"]["stop_seq"]
    for j in range(b + 1, len(stops)):
        if place in stops[j]["serves_places"]:
            return min(s["cap"] for s in pool["segments"][b:j])
    return 0


def _summary(groups, vehicles):
    demand = {}
    for g in groups:
        demand[g["dest_place"]] = demand.get(g["dest_place"], 0) + g["size"]
    cap = {pl: 0 for pl in demand}
    for v in vehicles:
        if v["role"] != "ALLOCATION":
            continue
        for pool in v["pools"]:
            for pl in cap:
                cap[pl] += _pool_capacity_to(v, pool, pl)
    return {"heads": sum(g["size"] for g in groups), "groups": len(groups),
            "demand_heads_by_place": dict(sorted(demand.items())),
            "capacity_upper_bound_by_place": dict(sorted(cap.items())),
            "note": "TUNED scenario: shortage is deliberately shaped for the demo and is NOT a result. capacity_upper_bound ignores class rules, group sizes and shared segments; generator sanity check only"}


# ----------------------------------------------------------------------------------------------- public API
def generate(seed, n_passengers=300, pct_senior=0.12, pct_groups=0.35, compliance_rate=0.8, walkon_rate=0.3, *,
             pct_unreserved=0.25, pct_disabled=0.04, pct_children=0.06, pct_pregnant=0.02, pct_deadline=0.10,
             n_mtc_specials=4, n_intercity_specials=2, cancel_time="14:00", exclude_trains=(),
             data_dir=None, config_dir=None):
    """Generate one scenario. See module docstring. Raises ValueError on out-of-range parameters."""
    for name, val in (("pct_senior", pct_senior), ("pct_groups", pct_groups), ("compliance_rate", compliance_rate),
                      ("walkon_rate", walkon_rate), ("pct_unreserved", pct_unreserved)):
        if not 0 <= val <= 1:
            raise ValueError(f"{name} must be within [0, 1], got {val}")
    if n_passengers < 1:
        raise ValueError("n_passengers must be >= 1")
    root = Path(__file__).resolve().parents[3]
    data_dir = Path(data_dir) if data_dir else root / "data"
    config_dir = Path(config_dir) if config_dir else root / "config"
    cancel_min = _hhmm(cancel_time)

    params = {"seed": seed, "n_passengers": n_passengers, "pct_senior": pct_senior, "pct_groups": pct_groups,
              "compliance_rate": compliance_rate, "walkon_rate": walkon_rate, "pct_unreserved": pct_unreserved,
              "pct_disabled": pct_disabled, "pct_children": pct_children, "pct_pregnant": pct_pregnant,
              "pct_deadline": pct_deadline, "n_mtc_specials": n_mtc_specials,
              "n_intercity_specials": n_intercity_specials, "cancel_time": cancel_time,
              "exclude_trains": sorted(exclude_trains)}
    w = _load_world(data_dir)
    buffers = _load_buffers(config_dir)
    p = dict(params, caps=w["caps"])

    vehicles, cancelled, warnings = _build_vehicles(seed, w, p, buffers, cancel_min, tuple(exclude_trains))
    if cancel_min >= cancelled["depart_min"]:
        raise ValueError(f"cancel_time {cancel_time} must be before the cancelled train departs ({_fmt_min(cancelled['depart_min'])})")
    cxl_spec = next(t for t in w["sim_trains"]["trains"] if t.get("role") == "CANCELLED")
    groups = _make_groups(seed, n_passengers, p, cxl_spec, cancel_min)

    ticketed_unreserved = sum(g["size"] for g in groups if not g["reserved"])
    est_rng = _rng(seed, "unregistered_walkons")
    scenario = {
        "meta": {
            "label": LABEL_SIM, "schema_version": SCHEMA_VERSION, "params": params,
            "time_unit": "minutes from 00:00 of the scenario day; booking_time may be negative (earlier days)",
            "cancel_min": cancel_min, "cancelled_vehicle_id": cancelled["vehicle_id"],
            "labels": {
                "SIMULATED": "invented by the generator",
                "REAL": "real train with owner-verified timings",
                "REAL_DRAFT_UNVERIFIED": "real train, timings from a single unverified public source",
                "REAL_ROUTE_SIMULATED_DISPATCH": "real MTC route pattern and stop ids; the dispatched special is simulated",
                "REAL_SCHEDULE_SIMULATED_LOAD": "real GTFS trip time; passenger load is simulated",
                "REAL-secondary": "figure from secondary public sources", "ESTIMATE": "rough estimate",
            },
            "warnings": warnings,
            "assumptions": [
                "Cancelled train is SIMULATED (SIM-CXL); Poonamallee has no rail stop, so those passengers are modelled as road-continuing travellers.",
                "Only dispatched specials and alternate trains are allocatable; regular services are transfer legs for alternatives only.",
                "groups with known=false are ticketed unreserved passengers; unreserved_estimate is a separate, disjoint crowd of unregistered walk-ons.",
            ],
        },
        "places": world.PLACES,
        "buffers": buffers,
        "class_rank": _load_json(config_dir / "class_rank.json")["class_rank"],
        "vehicles": vehicles,
        "groups": groups,
        # DISJOINT populations: `groups` with known=false are ticketed unreserved passengers (they hold UTS tickets
        # and are in the passenger list). `unregistered_walkon_estimate` are people with NO ticket on the cancelled
        # train who may rush the same vehicles; they are never in `groups`.
        "unreserved_estimate": {
            "population": "UNREGISTERED_WALKONS",
            "heads": round(ticketed_unreserved * est_rng.uniform(0.15, 0.35)),
            "ticketed_unreserved_heads_in_groups": ticketed_unreserved,
            "label": LABEL_SIM,
        },
        "walkon": {"walkon_rate": walkon_rate,
                   "expected_by_pool": {pl["pool_id"]: pl["walkon_expected"] for v in vehicles for pl in v["pools"]
                                        if pl["walkon_expected"]},
                   "label": LABEL_SIM},
        "behaviour": {"compliance_rate": compliance_rate, "walkon_rate": walkon_rate,
                      "note": "consumed by /sim endpoints: (1 - compliance_rate) of allocated groups board the first vehicle"},
        "connections": [
            {"id": "CONN-KOY", "from_place": "CENTRAL", "via_place": "KOYAMBEDU", "leg1_route": "MTC-23213",
             "leg2_route": "SIM-IC-KOY", "to_places": ["KATPADI", "VELLORE"], "min_connection_min": world.MIN_CONNECTION_MIN,
             "label": "leg1 REAL route, leg2 SIMULATED"},
            {"id": "CONN-TRL", "from_place": "CENTRAL", "via_place": "POONAMALLEE",
             "leg1_routes": ["MTC-22836", "MTC-22798", "MTC-23210"], "leg2_route": "MTC-22780",
             "to_places": ["TIRUVALLUR"], "min_connection_min": world.MIN_CONNECTION_MIN,
             "label": "both legs REAL routes, loads SIMULATED"},
        ],
        "summary": _summary(groups, vehicles),
    }
    errors, group_warnings = validate_scenario(scenario)
    if errors:
        raise ValueError("invalid scenario: " + "; ".join(errors))
    scenario["meta"]["warnings"].extend(group_warnings)
    scenario["timeline"] = build_timeline(scenario)
    return scenario


def dumps(scenario):
    """Canonical JSON text (stable key order) so identical scenarios serialise byte-identically."""
    return json.dumps(scenario, indent=1, sort_keys=True, ensure_ascii=False)
