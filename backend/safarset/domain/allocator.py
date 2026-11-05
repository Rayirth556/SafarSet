"""Priority-ordered greedy allocator with a stability rule and bounded reshuffle. Pure: takes plain dicts, returns a
Plan; the caller turns it into a PLAN_PROPOSED event. Same input => same output.

Rules (owner-approved):
  * groups are ordered by score (descending), ties by (booking_time, pnr, group_id); a group is never split;
  * candidate = (vehicle, pool). Arrivals within `arrival_tolerance_min` (+15) of the earliest feasible arrival are
    treated as EQUAL; among those: class step (same -> upgrade -> lower, flagged -> unreserved last resort), upgrade
    distance, best fit, then earlier arrival, then mode tier (train before bus), then ids. A candidate arriving more
    than the tolerance after the earliest never beats it;
  * capacity is per segment: min(free[b..j-1]) >= group size; buffers are already inside `free`;
  * CONFIRMED/BOARDED seats are fixed (not in `free`). Stability: existing TENTATIVE placements are kept ("pinned")
    unless they became invalid, or the BOUNDED RESHUFFLE applies: an unplaced group may cause a strictly
    lower-priority pinned group to move only if that group is no worse off (same destination, arrival within
    +tolerance, class step not worse, requirements met), at most `reshuffle_max_moves` groups move, and the move
    places strictly more people (the unplaced group); nobody is ever unplaced by a reshuffle;
  * operator overrides are pinned and never moved.
"""
from collections import Counter
from itertools import combinations
from dataclasses import dataclass, field

from ..scoring.interface import ScoreContext
from . import compat

ALGORITHM = "greedy-priority-v2"
_TIER = {"TRAIN": 0, "BUS": 1}
_KEY_NAMES = ["CLASS_STEP", "UPGRADE_DISTANCE", "BEST_FIT", "ARRIVAL", "MODE_TIER", "VEHICLE_ID", "POOL_ID"]
_QUALITY = {compat.STEP_SAME: 0, compat.STEP_UPGRADE: 0, compat.STEP_LOWER: 2, compat.STEP_UNRESERVED: 3}


def net_positive(moved_heads, placed_heads):
    """A reshuffle must place strictly more PEOPLE than it moves (heads, not groups)."""
    return placed_heads > moved_heads


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


@dataclass
class Plan:
    placements: list = field(default_factory=list)     # PlanAllocation-shaped dicts, priority order
    unresolved: list = field(default_factory=list)     # {group_id, size, dest_place, reason, alternatives}
    order: list = field(default_factory=list)          # group_ids in priority order
    reshuffles: list = field(default_factory=list)     # voluntary bounded-reshuffle records
    unpinned: dict = field(default_factory=dict)       # group_id -> why an existing tentative placement was dropped
    summary: dict = field(default_factory=dict)
    sizes: dict = field(default_factory=dict)          # group_id -> heads
    items: list = None                                 # set by the diff builder

    def default_items(self):
        items = [{"kind": "PLACED", "group_id": a["group_id"],
                  "detail": {"vehicle_id": a["reason"]["chosen"]["vehicle_id"], "pool_id": a["pool_id"],
                             "arrive_min": a["reason"]["chosen"]["arrive_min"], "class_step": a["reason"]["chosen"]["class_step"]}}
                 for a in self.placements]
        items += [{"kind": "UNRESOLVED", "group_id": u["group_id"],
                   "detail": {"reason": u["reason"], "alternatives": u["alternatives"]}} for u in self.unresolved]
        return items

    def to_payload(self, batch_id, base_seq, cause="REPLAN"):
        return {"batch_id": batch_id, "base_seq": base_seq, "cause": cause, "allocations": self.placements, "release": [],
                "items": self.items if self.items is not None else self.default_items(), "summary": self.summary}


def _vehicle_name(v):
    return f"train {v['train_no']}" if v["mode"] == "TRAIN" else f"bus {v['vehicle_id']}"


def _reject_noise(code):
    return code in ("NO_BOARDING_STOP", "NO_DESTINATION", "NOT_ALLOWED", "NOT_ALLOCATABLE", "VEHICLE_CANCELLED")


def _kf(c):
    """Order key among candidates whose arrivals count as equal."""
    return (c["step"], c["dist"], c["slack"], c["arrive"], c["tier"], c["vehicle"]["vehicle_id"], c["pool"]["pool_id"])


def _ordered(cands, tol):
    """Candidates within tol of the earliest arrival, ordered by _kf; then the rest by (arrival, _kf)."""
    if not cands:
        return []
    earliest = min(c["arrive"] for c in cands)
    near = sorted((c for c in cands if c["arrive"] <= earliest + tol), key=_kf)
    far = sorted((c for c in cands if c["arrive"] > earliest + tol), key=lambda c: (c["arrive"], *_kf(c)))
    return near + far


def _candidates(g, vehicles, free, ctx, rank_map):
    """-> (feasible, blocked, rejects, counts). feasible fit now; blocked pass every rule except capacity."""
    feasible, blocked, rejects, counts = [], [], [], Counter()
    for v in vehicles:
        opt, rej = compat.vehicle_option(g, v, ctx)
        if rej:
            counts[rej["code"]] += 1
            if not _reject_noise(rej["code"]):
                rejects.append({"vehicle_id": v["vehicle_id"], "pool_id": None, **rej})
            continue
        b, j = opt["b"], opt["j"]
        best_reject, any_pool = None, False
        for p in v["pools"]:
            cs = compat.class_step(g, p, rank_map)
            if cs is None:
                continue
            any_pool = True
            seg = free[p["pool_id"]][b:j]
            step, step_name, dist = cs
            cand = {"vehicle": v, "pool": p, "opt": opt, "step": step, "step_name": step_name, "dist": dist,
                    "slack": min(seg) - g["size"], "tier": _TIER[v["mode"]], "arrive": opt["arrive"]}
            if min(seg) < g["size"]:
                bad = next(i for i, f in enumerate(seg) if f < g["size"])
                best_reject = {"code": "CAPACITY", "vehicle_id": v["vehicle_id"], "pool_id": p["pool_id"], "segment": b + bad,
                               "free": seg[bad], "needed": g["size"], "arrive": opt["arrive"]}
                blocked.append(cand)
                continue
            feasible.append(cand)
        if best_reject:
            counts["CAPACITY"] += 1
            rejects.append(best_reject)
        elif not any_pool:
            counts["CLASS_NOT_ALLOWED"] += 1
    return feasible, blocked, rejects, counts


def _decided_by(ordered, tol):
    if len(ordered) < 2:
        return "ONLY_FEASIBLE_OPTION"
    a, b = ordered[0], ordered[1]
    if b["arrive"] > min(c["arrive"] for c in ordered) + tol:
        return "EARLIEST_ARRIVAL"
    for name, x, y in zip(_KEY_NAMES, _kf(a), _kf(b)):
        if x != y:
            return name
    return "IDENTICAL"


def _chosen_dict(c):
    v, p, o = c["vehicle"], c["pool"], c["opt"]
    return {"vehicle_id": v["vehicle_id"], "pool_id": p["pool_id"], "mode": v["mode"], "board_idx": o["b"], "alight_idx": o["j"],
            "depart_min": o["depart"], "arrive_min": o["arrive"], "class_step": c["step_name"],
            "class_flagged": c["step"] == compat.STEP_LOWER, "boarding_note": v["boarding"].get("note")}


def _reason_text(rank, n, sc, ch, why, preferred, tol, vehicles):
    v = vehicles[ch["vehicle_id"]]
    why_text = {"EARLIEST_ARRIVAL": f"Chosen because it arrives more than {tol} min earlier than the next option.",
                "ONLY_FEASIBLE_OPTION": "It was the only feasible option.",
                "CLASS_STEP": f"Arrivals within {tol} min count as equal; this option needs a smaller class change.",
                "UPGRADE_DISTANCE": f"Arrivals within {tol} min count as equal; this option needs the smaller upgrade.",
                "BEST_FIT": f"Arrivals within {tol} min count as equal and class is equal; this option leaves the least spare capacity.",
                "ARRIVAL": "Equal on class and fit; this option arrives earlier.",
                "MODE_TIER": "Equal on everything else; trains are preferred over buses on a tie."}.get(why, "Chosen by a deterministic tie-break.")
    parts = [f"Priority rank {rank} of {n} (score {sc['total']:g}).",
             f"Placed on {_vehicle_name(v)}, departing {hhmm(ch['depart_min'])}, arriving {hhmm(ch['arrive_min'])}.", why_text]
    if ch["class_step"] == "UPGRADE":
        parts.append("Seat is in a higher class than the ticket (upgrade).")
    elif ch["class_flagged"]:
        parts.append("FLAGGED: seat is in a lower class than the ticket.")
    elif ch["class_step"] == "UNRESERVED_LAST_RESORT":
        parts.append("No reserved seat was available in time; unreserved space on this vehicle.")
    if preferred:
        p0 = preferred[0]
        parts.append(f"Earlier option {p0['vehicle_id']} was not available: {p0['code']}"
                     + (f" (segment {p0['segment']} has {p0['free']} free, needs {p0['needed']})" if p0["code"] == "CAPACITY" else "") + ".")
    if ch.get("boarding_note"):
        parts.append(ch["boarding_note"] + ".")
    return " ".join(parts)


def _unresolved_reason(rank, n, sc, rejects, counts, stability=None):
    cap = sorted((r for r in rejects if r["code"] == "CAPACITY"), key=lambda r: (r["arrive"], r["vehicle_id"], r["pool_id"]))
    if cap:
        cause, binding = "CAPACITY", cap[0]
    elif counts["MISSES_DEADLINE"]:
        cause, binding = "DEADLINE", min((r for r in rejects if r["code"] == "MISSES_DEADLINE"), key=lambda r: r["arrive"])
    elif counts["WHEELCHAIR_NOT_ACCESSIBLE"]:
        cause, binding = "ACCESSIBILITY", None
    elif counts["TOO_LATE_TO_BOARD"]:
        cause, binding = "NO_DEPARTURE_LEFT", None
    else:
        cause, binding = "NO_VEHICLE_SERVES_DESTINATION", None
    text = {"CAPACITY": "No seats: every vehicle reaching the destination is full" + (
                f" (best near-miss {binding['vehicle_id']}: segment {binding['segment']} has {binding['free']} free, needs {binding['needed']})" if cause == "CAPACITY" else ""),
            "DEADLINE": "Every vehicle with space arrives after the group's hard deadline",
            "ACCESSIBILITY": "No wheelchair-accessible vehicle reaches the destination in time",
            "NO_DEPARTURE_LEFT": "No suitable vehicle departs late enough to board",
            "NO_VEHICLE_SERVES_DESTINATION": "No vehicle serves this destination"}[cause] + "."
    if stability:
        if stability["why"] == "MOVES_AS_MANY_HEADS_AS_PLACED":
            text += (f" Fitting it would mean moving {stability['moved_heads']} traveller(s) ({', '.join(stability['blocked_by'])}) to place "
                     f"{stability['placed_heads']}; a reshuffle must place strictly more people than it moves (stability rule).")
        else:
            text += (f" It would fit if lower-priority tentative group(s) {', '.join(stability['blocked_by'])} moved, but none could move "
                     "without being worse off (stability rule). 'Adjust weights and re-run' re-plans from scratch.")
    return {"algorithm": ALGORITHM, "unresolved": True, "rank": rank, "of": n, "score": sc, "primary_cause": cause,
            "binding": binding, "rejections_by_code": dict(sorted(counts.items())),
            "stability": stability or None, "text": f"Priority rank {rank} of {n}. " + text}


# ----------------------------------------------------------------------------------- alternatives for unplaced groups
def _leg(v, from_place, to_place, earliest_depart, ctx):
    stops = v["stops"]
    b = next((s["seq"] for s in stops if from_place in s["serves_places"]), None)
    if b is None:
        return None
    j = next((s["seq"] for s in stops[b + 1:] if to_place in s["serves_places"]), None)
    if j is None:
        return None
    delay = v.get("delay_min", 0)
    walk = int(-(-(v["boarding"].get("walk_m") or 0) // ctx["walk_m_per_min"])) if b == v["boarding"]["stop_seq"] else 0
    depart, arrive = stops[b]["dep_min"] + delay, stops[j]["arr_min"] + delay
    if v["status"] != "SCHEDULED" or depart < earliest_depart + walk:
        return None
    return {"b": b, "j": j, "depart": depart, "arrive": arrive}


def _leg_pool(v, leg, free, size):
    for p in v["pools"]:
        if p["kind"] == "UNRESERVED" and min(free[p["pool_id"]][leg["b"]:leg["j"]]) >= size:
            return p
    return None


def _multi_leg(g, vehicles, free, connections, ctx):
    wheel = g["requirements"].get("wheelchair")
    best = None
    for cn in connections:
        if g["dest_place"] not in cn["to_places"] or g["board_place"] != cn["from_place"]:
            continue
        routes1 = set(cn.get("leg1_routes") or [cn["leg1_route"]])
        for v1 in vehicles:
            if v1["route_id"] not in routes1 or v1["role"] not in ("TRANSFER_LEG", "ALLOCATION") or (wheel and not v1["attrs"].get("wheelchair_accessible")):
                continue
            start = ctx["now_min"] + compat.checkin_min(ctx, v1["mode"])
            l1 = _leg(v1, cn["from_place"], cn["via_place"], start, ctx)
            p1 = _leg_pool(v1, l1, free, g["size"]) if l1 else None
            if not p1:
                continue
            for v2 in vehicles:
                if v2["route_id"] != cn["leg2_route"] or v2["role"] != "TRANSFER_LEG" or (wheel and not v2["attrs"].get("wheelchair_accessible")):
                    continue
                l2 = _leg(v2, cn["via_place"], g["dest_place"], l1["arrive"] + cn["min_connection_min"], ctx)
                p2 = _leg_pool(v2, l2, free, g["size"]) if l2 else None
                if not p2:
                    continue
                key = (l2["arrive"], l1["depart"], v1["vehicle_id"], v2["vehicle_id"])
                if best is None or key < best[0]:
                    best = (key, cn, v1, p1, l1, v2, p2, l2)
    if best is None:
        return None
    _, cn, v1, p1, l1, v2, p2, l2 = best
    return {"type": "MULTI_LEG", "connection": cn["id"], "depart_min": l1["depart"], "arrive_min": l2["arrive"],
            "legs": [{"vehicle_id": v1["vehicle_id"], "pool_id": p1["pool_id"], "from": cn["from_place"], "to": cn["via_place"],
                      "depart_min": l1["depart"], "arrive_min": l1["arrive"]},
                     {"vehicle_id": v2["vehicle_id"], "pool_id": p2["pool_id"], "from": cn["via_place"], "to": g["dest_place"],
                      "depart_min": l2["depart"], "arrive_min": l2["arrive"]}],
            "note": "Suggestion only: seats are not held for this option; it uses regular services."}


def _late_arrival(g, vehicles, free, ctx, rank_map, tol):
    if g["attrs"].get("deadline_min") is None:
        return None
    relaxed = dict(g, attrs=dict(g["attrs"], deadline_min=None))
    feasible, _, _, _ = _candidates(relaxed, vehicles, free, ctx, rank_map)
    if not feasible:
        return None
    ch = _chosen_dict(_ordered(feasible, tol)[0])
    return {"type": "LATE_ARRIVAL", "vehicle_id": ch["vehicle_id"], "pool_id": ch["pool_id"], "depart_min": ch["depart_min"],
            "arrive_min": ch["arrive_min"], "late_by_min": ch["arrive_min"] - g["attrs"]["deadline_min"], "class_step": ch["class_step"],
            "note": "Misses the hard deadline; seats exist if the operator accepts that."}


def _alternatives(g, wait_pos, vehicles, free, connections, ctx, rank_map, tol):
    alts = [a for a in (_late_arrival(g, vehicles, free, ctx, rank_map, tol), _multi_leg(g, vehicles, free, connections, ctx)) if a]
    alts.sort(key=lambda a: (a["arrive_min"], a["type"]))
    alts.append({"type": "WAITLIST", "position": wait_pos, "destination": g["dest_place"],
                 "note": "Re-planned automatically when capacity frees up (second-chart vacancies, extra vehicles)."})
    for i, a in enumerate(alts, 1):
        a["rank"] = i
    return alts


# ----------------------------------------------------------------------------------- the allocator
class _Run:
    """One allocation run: mutable working state kept together so helper steps stay short."""

    def __init__(self, groups, vehicles, free, scorer, weights, rank_map, connections, now_min, config, pinned, held):
        self.cfg = config
        self.tol = config.get("arrival_tolerance_min", 15)
        self.ctx = {"now_min": now_min, "min_checkin_min": config["min_checkin_min"], "walk_m_per_min": config["walk_m_per_min"]}
        self.rank_map, self.connections, self.now_min, self.weights = rank_map, connections, now_min, weights
        self.vehicles = vehicles
        self.vlist = [vehicles[k] for k in sorted(vehicles)]
        self.pool_vehicle = {p["pool_id"]: v for v in self.vlist for p in v["pools"]}
        self.work = {k: list(v) for k, v in free.items()}
        self.held = held
        sctx = ScoreContext(now_min=now_min, weights=weights)
        scored = [(g, scorer(g, sctx)) for g in groups if g["group_id"] not in held]
        scored.sort(key=lambda x: (-x[1]["total"], x[0]["booking_time"], x[0]["pnr"] is None, x[0]["pnr"] or "", x[0]["group_id"]))
        self.n = len(scored)
        self.g = {g["group_id"]: g for g, _ in scored}
        self.sc = {g["group_id"]: {"total": s["total"], "breakdown": [list(x) for x in s["breakdown"]]} for g, s in scored}
        self.rank = {g["group_id"]: i for i, (g, _) in enumerate(scored, 1)}
        self.order = [g["group_id"] for g, _ in scored]
        self.pinned = pinned
        self.place = {}                  # gid -> placement record
        self.unpinned, self.reshuffles = {}, []
        self.stability_note = {}

    # -- seats
    def take(self, pool_id, b, j, size):
        for i in range(b, j):
            self.work[pool_id][i] -= size

    def give(self, pool_id, b, j, size):
        for i in range(b, j):
            self.work[pool_id][i] += size

    # -- pins
    def apply_pins(self):
        for gid in self.order:
            pin = self.pinned.get(gid)
            if not pin:
                continue
            g, v = self.g[gid], self.pool_vehicle.get(pin["pool_id"])
            pool = next((p for p in v["pools"] if p["pool_id"] == pin["pool_id"]), None) if v else None
            code = None
            if v is None:
                code = "POOL_GONE"
            elif pin.get("override"):
                opt = {"b": pin["board_idx"], "j": pin["alight_idx"], "depart": v["stops"][pin["board_idx"]]["dep_min"] + v["delay_min"],
                       "arrive": v["stops"][pin["alight_idx"]]["arr_min"] + v["delay_min"]}
                if v["status"] != "SCHEDULED":
                    code = "VEHICLE_CANCELLED"
                cs = compat.class_step(g, pool, self.rank_map) or (compat.STEP_SAME, "OPERATOR_ASSIGNED", 0)
            else:
                opt, rej = compat.vehicle_option(g, v, self.ctx)
                cs = compat.class_step(g, pool, self.rank_map)
                if rej:
                    code = rej["code"]
                elif (opt["b"], opt["j"]) != (pin["board_idx"], pin["alight_idx"]):
                    code = "ROUTE_CHANGED"
                elif cs is None:
                    code = "CLASS_NOT_ALLOWED"
            if code is None and min(self.work[pin["pool_id"]][opt["b"]:opt["j"]]) < g["size"]:
                code = "NO_CAPACITY"
            if code:
                self.unpinned[gid] = code
                continue
            self.take(pin["pool_id"], opt["b"], opt["j"], g["size"])
            ch = dict(pin["reason"].get("chosen") or {})
            ch.update({"vehicle_id": v["vehicle_id"], "pool_id": pin["pool_id"], "board_idx": opt["b"], "alight_idx": opt["j"],
                       "depart_min": opt["depart"], "arrive_min": opt["arrive"]})
            ch.setdefault("class_step", cs[1])
            ch.setdefault("class_flagged", cs[0] == compat.STEP_LOWER)
            ch.setdefault("mode", v["mode"])
            reason = dict(pin["reason"], rank=self.rank[gid], of=self.n, score=self.sc[gid], chosen=ch,
                          stability={"kept": True, "override": bool(pin.get("override"))})
            self.place[gid] = {"gid": gid, "pool_id": pin["pool_id"], "b": opt["b"], "j": opt["j"], "size": g["size"], "arrive": opt["arrive"],
                               "step": cs[0], "origin": "override" if pin.get("override") else "pinned", "reason": reason,
                               "vehicle": v}

    # -- greedy
    def place_group(self, gid, cand, ordered, rejects, reshuffle=None):
        g, ch = self.g[gid], _chosen_dict(cand)
        self.take(ch["pool_id"], ch["board_idx"], ch["alight_idx"], g["size"])
        why = _decided_by(ordered, self.tol) if ordered else "ONLY_FEASIBLE_OPTION"
        preferred = sorted((r for r in rejects if r.get("arrive") is not None and r["arrive"] < ch["arrive_min"] and r["code"] == "CAPACITY"),
                           key=lambda r: (r["arrive"], r["vehicle_id"]))[:3]
        runner = ordered[1] if ordered and len(ordered) > 1 else None
        reason = {"algorithm": ALGORITHM, "rank": self.rank[gid], "of": self.n, "score": self.sc[gid], "chosen": ch,
                  "why_chosen": {"decided_by": why, "runner_up": None if runner is None else
                                 {"vehicle_id": runner["vehicle"]["vehicle_id"], "pool_id": runner["pool"]["pool_id"],
                                  "arrive_min": runner["arrive"], "class_step": runner["step_name"]}},
                  "binding_constraints": preferred,
                  "text": _reason_text(self.rank[gid], self.n, self.sc[gid], ch, why, preferred, self.tol, self.vehicles)}
        if reshuffle:
            reason["reshuffle"] = reshuffle
            reason["text"] += (f" Made room by moving {reshuffle['heads_moved']} traveller(s) in {len(reshuffle['moves'])} lower-priority "
                               f"tentative group(s) who are no worse off, to place {reshuffle['heads_placed']}.")
        self.place[gid] = {"gid": gid, "pool_id": ch["pool_id"], "b": ch["board_idx"], "j": ch["alight_idx"], "size": g["size"],
                           "arrive": ch["arrive_min"], "step": cand["step"], "origin": "new", "reason": reason, "vehicle": cand["vehicle"]}

    def greedy(self):
        failed = []
        for gid in self.order:
            if gid in self.place:
                continue
            feasible, blocked, rejects, counts = _candidates(self.g[gid], self.vlist, self.work, self.ctx, self.rank_map)
            ordered = _ordered(feasible, self.tol)
            if not ordered:
                failed.append((gid, rejects, counts))
                continue
            self.place_group(gid, ordered[0], ordered, rejects)
        return failed

    # -- bounded reshuffle
    def _move_candidates(self, m, sim, old):
        feasible, _, _, _ = _candidates(self.g[m["gid"]], self.vlist, sim, self.ctx, self.rank_map)
        ok = [c for c in _ordered(feasible, self.tol)
              if c["pool"]["pool_id"] != old["pool_id"] and c["arrive"] <= old["arrive"] + self.tol
              and _QUALITY[c["step"]] <= _QUALITY[old["step"]]]
        return ok

    def _mover_sets(self, gid, pid, need, max_moves):
        """Smallest sets (by heads moved, then lowest priority) of strictly lower-priority pinned groups in pool `pid`
        whose seats cover every deficit segment. At most max_moves groups; operator overrides are never movers."""
        movers = sorted((p for p in self.place.values() if p["origin"] == "pinned" and p["pool_id"] == pid
                         and self.rank[p["gid"]] > self.rank[gid] and any(p["b"] <= s < p["j"] for s in need)),
                        key=lambda p: (-self.rank[p["gid"]], p["gid"]))[:8]
        found = []
        for k in range(1, max_moves + 1):
            for combo in combinations(movers, k):
                left = dict(need)
                for m in combo:
                    for s in range(m["b"], m["j"]):
                        if s in left:
                            left[s] -= m["size"]
                            if left[s] <= 0:
                                del left[s]
                if not left:
                    found.append(combo)
        found.sort(key=lambda c: (sum(m["size"] for m in c), len(c), -sum(self.rank[m["gid"]] for m in c), [m["gid"] for m in c]))
        return found

    def reshuffle(self, failed):
        still = []
        max_moves = self.cfg.get("reshuffle_max_moves", 2)
        for gid, rejects, counts in failed:
            g = self.g[gid]
            feasible, blocked, rejects, counts = _candidates(g, self.vlist, self.work, self.ctx, self.rank_map)
            if feasible:                                  # earlier reshuffles freed room
                self.place_group(gid, _ordered(feasible, self.tol)[0], _ordered(feasible, self.tol), rejects)
                continue
            done, first_block = False, None
            for cand in _ordered(blocked, self.tol)[: self.cfg.get("reshuffle_candidates", 8)]:
                pid, o = cand["pool"]["pool_id"], cand["opt"]
                need = {s: g["size"] - self.work[pid][s] for s in range(o["b"], o["j"]) if self.work[pid][s] < g["size"]}
                for chosen in self._mover_sets(gid, pid, need, max_moves):
                    moved_heads = sum(m["size"] for m in chosen)
                    blk = {"blocked_by": [m["gid"] for m in chosen], "moved_heads": moved_heads, "placed_heads": g["size"]}
                    if not net_positive(moved_heads, g["size"]):      # heads, not groups: must place strictly more than it moves
                        first_block = first_block or dict(blk, why="MOVES_AS_MANY_HEADS_AS_PLACED")
                        continue
                    sim = {k: list(v) for k, v in self.work.items()}
                    for m in chosen:
                        for i in range(m["b"], m["j"]):
                            sim[m["pool_id"]][i] += m["size"]
                    if min(sim[pid][o["b"]:o["j"]]) < g["size"]:
                        continue
                    for i in range(o["b"], o["j"]):
                        sim[pid][i] -= g["size"]
                    moves, ok = [], True
                    for m in sorted(chosen, key=lambda p: self.rank[p["gid"]]):
                        alts = self._move_candidates(m, sim, m)
                        if not alts:
                            ok = False
                            break
                        a = alts[0]
                        for i in range(a["opt"]["b"], a["opt"]["j"]):
                            sim[a["pool"]["pool_id"]][i] -= m["size"]
                        moves.append((m, a))
                    if not ok:
                        first_block = first_block or dict(blk, why="NO_ALTERNATIVE_WITHIN_TOLERANCE")
                        continue
                    self.work = sim
                    for m, a in moves:
                        self._commit_move(m, a)
                    rec = {"beneficiary": gid, "net_heads_placed": g["size"] - moved_heads, "heads_placed": g["size"], "heads_moved": moved_heads,
                           "moves": [{"group_id": m["gid"], "from": {"pool_id": m["pool_id"], "arrive_min": m["arrive"]},
                                      "to": {"pool_id": a["pool"]["pool_id"], "arrive_min": a["arrive"]},
                                      "arrival_change_min": a["arrive"] - m["arrive"]} for m, a in moves]}
                    self.reshuffles.append(rec)
                    self.give(pid, o["b"], o["j"], g["size"])          # seats were already taken in `sim`; place_group takes them
                    self.place_group(gid, cand, [cand], rejects, reshuffle=rec)
                    done = True
                    break
                if done:
                    break
            if not done:
                self.stability_note[gid] = first_block
                still.append((gid, rejects, counts))
        return still

    def _commit_move(self, m, a):
        gid, ch = m["gid"], _chosen_dict(a)
        old = m["reason"]
        reason = dict(old, chosen=ch, stability={"kept": False, "moved": True},
                      reshuffled_from={"pool_id": m["pool_id"], "arrive_min": m["arrive"]})
        reason["text"] = (old.get("text", "") + f" MOVED by bounded reshuffle to {ch['vehicle_id']} (arrival "
                          f"{'+' if a['arrive'] >= m['arrive'] else ''}{a['arrive'] - m['arrive']} min, no worse off).").strip()
        self.place[gid] = {"gid": gid, "pool_id": ch["pool_id"], "b": ch["board_idx"], "j": ch["alight_idx"], "size": m["size"],
                           "arrive": ch["arrive_min"], "step": a["step"], "origin": "moved", "reason": reason, "vehicle": a["vehicle"]}

    # -- results
    def finish(self, failed):
        plan = Plan(order=list(self.order), reshuffles=self.reshuffles, unpinned=self.unpinned,
                    sizes={gid: g['size'] for gid, g in self.g.items()})
        for gid in self.order:
            p = self.place.get(gid)
            if p:
                plan.placements.append({"group_id": gid, "pool_id": p["pool_id"], "board_idx": p["b"], "alight_idx": p["j"],
                                        "score": self.sc[gid]["total"], "reason": p["reason"]})
        by_dest = Counter()
        for gid, rejects, counts in failed:
            g = self.g[gid]
            by_dest[g["dest_place"]] += 1
            reason = _unresolved_reason(self.rank[gid], self.n, self.sc[gid], rejects, counts, self.stability_note.get(gid))
            plan.unresolved.append({"group_id": gid, "size": g["size"], "dest_place": g["dest_place"], "reason": reason,
                                    "alternatives": _alternatives(g, by_dest[g["dest_place"]], self.vlist, self.work, self.connections,
                                                                  self.ctx, self.rank_map, self.tol)})
        for gid, h in sorted(self.held.items()):
            plan.unresolved.append({"group_id": gid, "size": h["size"], "dest_place": h["dest_place"], "alternatives": [],
                                    "reason": {"algorithm": ALGORITHM, "unresolved": True, "primary_cause": "OPERATOR_HOLD",
                                               "text": f"Held out of automatic planning by the operator: {h['why']}"}})
        placed_heads = sum(self.g[a["group_id"]]["size"] for a in plan.placements)
        total_heads = sum(g["size"] for g in self.g.values())
        plan.summary = {"algorithm": ALGORITHM, "now_min": self.now_min, "weights": dict(self.weights), "groups": self.n,
                        "heads": total_heads, "heads_placed": placed_heads, "heads_unresolved": total_heads - placed_heads,
                        "kept_groups": sum(1 for p in self.place.values() if p["origin"] in ("pinned", "override")),
                        "reshuffles": len(self.reshuffles), "unpinned": dict(sorted(self.unpinned.items())),
                        "placed_by_class_step": dict(sorted(Counter(a["reason"]["chosen"]["class_step"] for a in plan.placements).items()))}
        return plan


def allocate(groups, vehicles, free, *, scorer, weights, rank_map, connections, now_min, config, pinned=None, held=None):
    """vehicles: id -> vehicle (see compat); free: pool_id -> [free seats per segment] (copied, not mutated).
    pinned: group_id -> {pool_id, board_idx, alight_idx, reason, override} for existing TENTATIVE placements to keep.
    held: group_id -> {why, size, dest_place} for groups the operator removed from automatic planning."""
    run = _Run(groups, vehicles, free, scorer, weights, rank_map, connections, now_min, config, pinned or {}, held or {})
    run.apply_pins()
    failed = run.greedy()
    if run.pinned and failed:
        failed = run.reshuffle(failed)
    return run.finish(failed)
