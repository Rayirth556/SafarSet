"""Re-plan diff: turn a Plan into batch items with the operator's categories and counts.

Baseline = what the operator last saw (the pending batch) plus what the world already holds:
  DISPLACED     the group lost a CONFIRMED seat (could not board / operator override) and has not been re-confirmed.
                detail.replaced says whether this plan gives it a new seat; detail.old_sms_still_held is always True
                (the passenger still holds the old confirmation until a new batch is approved), so the UI can warn.
  RESHUFFLED    the group had a TENTATIVE placement and now has a different one. detail.forced tells whether that was
                imposed by a capacity change (True) or chosen by the bounded reshuffle (False).
  NEWLY_PLACED  placed now, had no live placement and was not displaced.
  PLACED        unchanged from the pending batch.
  UNRESOLVED    still unplaced (a displaced group that stays unplaced is listed under both DISPLACED and UNRESOLVED).
"""
import json

from . import state

CATEGORIES = ["DISPLACED", "NEWLY_PLACED", "RESHUFFLED", "PLACED", "UNRESOLVED"]


def _cause(row):
    r = row.get("status_reason")
    return json.loads(r).get("cause") if r else None


def _same(prev, a):
    return (prev["pool_id"], prev["board_idx"], prev["alight_idx"]) == (a["pool_id"], a["board_idx"], a["alight_idx"])


def build_diff(conn, plan):
    prev, displaced = state.load_previous_proposed(conn), state.load_displaced(conn)
    voluntary = {m["group_id"] for r in plan.reshuffles for m in r["moves"]}
    items = []

    def detail_of(a):
        ch = a["reason"]["chosen"]
        return {"vehicle_id": ch["vehicle_id"], "pool_id": a["pool_id"], "arrive_min": ch["arrive_min"], "class_step": ch["class_step"]}

    for a in plan.placements:
        gid, d = a["group_id"], detail_of(a)
        if gid in displaced:
            d.update(replaced=True, displaced_from=displaced[gid]["pool_id"], cause=_cause(displaced[gid]), old_sms_still_held=True)
            kind = "DISPLACED"
        elif gid in prev and not _same(prev[gid], a):
            d.update(forced=gid not in voluntary, moved_from=prev[gid]["pool_id"])
            kind = "RESHUFFLED"
        elif gid in prev:
            kind = "PLACED"
        else:
            kind = "NEWLY_PLACED"
        if a["reason"].get("stability", {}).get("override"):
            d["operator_override"] = True
        items.append({"kind": kind, "group_id": gid, "detail": d})
    for u in plan.unresolved:
        gid = u["group_id"]
        if gid in displaced:
            items.append({"kind": "DISPLACED", "group_id": gid, "detail": {"replaced": False, "displaced_from": displaced[gid]["pool_id"],
                                                                           "cause": _cause(displaced[gid]), "old_sms_still_held": True}})
        d = {"reason": u["reason"], "alternatives": u["alternatives"]}
        stab = u["reason"].get("stability")
        if stab:                                                   # shown by the UI: who blocks this group and why
            d.update(blocking_groups=stab["blocked_by"], blocking_why=stab["why"], blocking_moved_heads=stab["moved_heads"],
                     blocking_placed_heads=stab["placed_heads"])
        if gid in displaced:
            d["old_sms_still_held"] = True
        if gid in prev and prev[gid]["status"] == "TENTATIVE":
            d["was_placed"] = True
        items.append({"kind": "UNRESOLVED", "group_id": gid, "detail": d})
    sizes = dict(plan.sizes)
    sizes.update({u["group_id"]: u["size"] for u in plan.unresolved if u["size"]})
    counts = {c: {"groups": 0, "heads": 0} for c in CATEGORIES}
    for it in items:
        c = counts[it["kind"]]
        c["groups"] += 1
        c["heads"] += sizes.get(it["group_id"]) or 0
    plan.items = items
    plan.summary["diff"] = counts
    plan.summary["reshuffle_moves"] = [m for r in plan.reshuffles for m in r["moves"]]
    return counts
