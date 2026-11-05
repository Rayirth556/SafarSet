"""Read-side queries for the four UI surfaces. Pure functions over a connection (no HTTP types)."""
import json
import math

from ..domain import state as dstate
from ..events.reducers import batch_is_stale
from ..scoring import stub
from ..scoring.interface import ScoreContext

STATES = ["UNAFFECTED", "UNRESOLVED", "TENTATIVE", "CONFIRMED", "BOARDED"]


def _one(conn, sql, *a):
    return conn.execute(sql, a).fetchone()


def _all(conn, sql, *a):
    return conn.execute(sql, a).fetchall()


def hhmm(m):
    return None if m is None else f"{m // 60:02d}:{m % 60:02d}"


def place_names(conn):
    return {r["place_id"]: r["name"] for r in _all(conn, "SELECT place_id, name FROM places")}


# ------------------------------------------------------------------------------------------------ KPIs and banner
def kpis(conn):
    out = {s: {"groups": 0, "heads": 0} for s in STATES}
    for r in _all(conn, "SELECT state, COUNT(*) n, SUM(size) heads FROM v_group_state GROUP BY state"):
        out[r["state"]] = {"groups": r["n"], "heads": r["heads"] or 0}
    affected = {"groups": sum(v["groups"] for k, v in out.items() if k != "UNAFFECTED"),
                "heads": sum(v["heads"] for k, v in out.items() if k != "UNAFFECTED")}
    displaced = dstate.load_displaced(conn)
    held = dstate.load_held(conn)
    sizes = {r["group_id"]: r["size"] for r in _all(conn, "SELECT group_id, size FROM groups")}
    comp = _one(conn, """SELECT COALESCE(SUM(CASE WHEN reserved = 1 THEN size END), 0) pnr,
                                COALESCE(SUM(CASE WHEN reserved = 0 THEN size END), 0) unres FROM groups WHERE affected = 1""")
    est = _one(conn, "SELECT value FROM settings WHERE key = 'unreserved_estimate'")
    # three disjoint populations: known PNR holders, ticketed unreserved (UTS) passengers, and an ESTIMATE of unregistered walk-ons
    composition = {"pnr_heads": comp["pnr"], "ticketed_unreserved_heads": comp["unres"],
                   "unreserved_estimate": {"heads": json.loads(est["value"]).get("heads", 0) if est else 0, "estimated": True}}
    return {"composition": composition,"affected": affected, "tentative": out["TENTATIVE"], "confirmed": out["CONFIRMED"], "boarded": out["BOARDED"],
            "unresolved": out["UNRESOLVED"],
            "displaced_awaiting_replacement": {"groups": len(displaced), "heads": sum(sizes[g] for g in displaced)},
            "held_by_operator": {"groups": len(held), "heads": sum(h["size"] for h in held.values())}}


def banner(conn, clock):
    if not _one(conn, "SELECT 1 FROM vehicles LIMIT 1"):
        return {"active": False, "title": "No scenario loaded", "items": [], "clock": hhmm(clock)}
    items = []
    names = {r["vehicle_id"]: (r["name"] or r["vehicle_id"]) for r in _all(conn, "SELECT vehicle_id, name FROM vehicles")}
    for d in _all(conn, "SELECT * FROM disruptions ORDER BY seq"):
        detail = json.loads(d["detail"])
        if d["kind"] == "TRAIN_CANCELLED":
            items.append({"seq": d["seq"], "kind": d["kind"], "vehicle_id": d["vehicle_id"],
                          "text": f"Train cancelled: {d['vehicle_id']} ({names.get(d['vehicle_id'])})" + (f" - {detail['reason']}" if detail.get("reason") else "")})
        elif d["kind"] == "TRAIN_DELAYED":
            items.append({"seq": d["seq"], "kind": d["kind"], "vehicle_id": d["vehicle_id"], "text": f"Delay: {d['vehicle_id']} +{detail['delay_min']} min"})
        else:
            items.append({"seq": d["seq"], "kind": d["kind"], "route_id": d["route_id"], "text": f"Road closure: {detail['description']}" + (f" (route {d['route_id']})" if d["route_id"] else "")})
    meta = json.loads(_one(conn, "SELECT value FROM settings WHERE key = 'scenario_meta'")["value"])
    return {"active": bool(items), "title": items[0]["text"] if items else "No disruption", "items": items, "clock": hhmm(clock),
            "label": meta["label"], "cancelled_vehicle_id": meta["cancelled_vehicle_id"]}


# ------------------------------------------------------------------------------------------------ capacity
def capacity(conn, role="ALLOCATION"):
    marks = {r["pool_id"]: dict(r) for r in _all(conn, "SELECT * FROM field_reports")}
    stops = {}
    for s in _all(conn, "SELECT vehicle_id, seq, stop_name, stop_id FROM vehicle_stops ORDER BY vehicle_id, seq"):
        stops.setdefault(s["vehicle_id"], []).append(s["stop_name"] or s["stop_id"])
    loads = {}
    for r in _all(conn, "SELECT * FROM v_segment_load ORDER BY pool_id, seg_idx"):
        loads.setdefault(r["pool_id"], []).append(r)
    committed = {}
    for r in _all(conn, "SELECT pool_id, seg_idx, committed_other FROM segment_capacity"):
        committed.setdefault(r["pool_id"], {})[r["seg_idx"]] = r["committed_other"]
    vehicles = []
    q = "SELECT * FROM vehicles" + ("" if role == "all" else " WHERE role = ?") + " ORDER BY depart_min, vehicle_id"
    for v in _all(conn, q, *([] if role == "all" else [role])):
        pools = []
        for p in _all(conn, "SELECT * FROM pools WHERE vehicle_id = ? ORDER BY pool_id", v["vehicle_id"]):
            segs = [{"seg_idx": r["seg_idx"], "from_stop": stops[v["vehicle_id"]][r["seg_idx"]], "to_stop": stops[v["vehicle_id"]][r["seg_idx"] + 1],
                     "cap": r["cap"], "confirmed": r["confirmed"], "boarded": r["boarded"], "tentative": r["tentative"], "free": r["free"]}
                    for r in loads.get(p["pool_id"], [])]
            report = marks.get(p["pool_id"])
            pools.append({"pool_id": p["pool_id"], "kind": p["kind"], "class": p["class"], "coaches": p["coaches"], "nominal": p["nominal"],
                          "capacity_label": p["capacity_label"], "buffer_mode": p["buffer_mode"], "buffer_pct": p["buffer_pct"],
                          "formula": _formula(p, max(committed.get(p["pool_id"], {0: 0}).values()), report),
                          "walkon_expected": p["walkon_expected"],
                          "field_report": ({"level": report["level"], "count": report["count"], "seq": report["reported_seq"]} if report else None),
                          "segments": segs})
        boarding = json.loads(v["boarding"])
        vehicles.append({"vehicle_id": v["vehicle_id"], "mode": v["mode"], "role": v["role"], "label": v["label"], "name": v["name"],
                         "train_no": v["train_no"], "route_id": v["route_id"], "status": v["status"], "delay_min": v["delay_min"],
                         "depart_min": v["depart_min"] + v["delay_min"], "depart": hhmm(v["depart_min"] + v["delay_min"]),
                         "boarding_note": boarding.get("note"), "wheelchair_accessible": json.loads(v["attrs"]).get("wheelchair_accessible"),
                         "stops": stops[v["vehicle_id"]], "pools": pools})
    return vehicles


def _formula(p, committed, report):
    if p["kind"] == "RESERVED":
        return "exact vacancy from the reservation chart (no buffer)"
    base = math.floor(p["nominal"] * p["buffer_pct"] + 1e-9)
    text = f"{p['nominal']} × {round(p['buffer_pct'] * 100)}% = {base}"
    if committed:
        text += f" − {committed} already aboard = {max(0, base - committed)}"
    if report and report["level"] in ("FULL", "OVERCROWDED"):
        text += f" (frozen: field report {report['level'].lower()})"
    return text


# ------------------------------------------------------------------------------------------------ passengers
def _group_rows(conn):
    out = []
    for g in _all(conn, "SELECT g.*, s.state FROM groups g JOIN v_group_state s USING (group_id) ORDER BY g.group_id"):
        d = dict(g)
        d["requirements"], d["attrs"] = json.loads(g["requirements"]), json.loads(g["attrs"])
        d["reserved"] = bool(g["reserved"])
        out.append(d)
    return out


def scores(conn, groups, now_min):
    """Fresh score and rank (allocator order) for every affected group: gid -> (result, rank)."""
    ctx = ScoreContext(now_min=now_min, weights=dstate.current_weights(conn))
    scored = [(g, stub.score(g, ctx)) for g in groups if g["affected"]]
    scored.sort(key=lambda x: (-x[1]["total"], x[0]["booking_time"], x[0]["pnr"] is None, x[0]["pnr"] or "", x[0]["group_id"]))
    return {g["group_id"]: ({"total": r["total"], "breakdown": [list(b) for b in r["breakdown"]]}, i) for i, (g, r) in enumerate(scored, 1)}


def _live(conn):
    return {r["group_id"]: dict(r) for r in _all(conn, "SELECT * FROM allocations WHERE status IN ('TENTATIVE','CONFIRMED','BOARDED')")}


def _alloc_view(a, vehicle_of):
    if not a:
        return None
    reason = json.loads(a["reason"])
    ch = reason.get("chosen") or {}
    return {"id": a["id"], "status": a["status"], "pool_id": a["pool_id"], "vehicle_id": vehicle_of[a["pool_id"]],
            "board_idx": a["board_idx"], "alight_idx": a["alight_idx"], "depart_min": ch.get("depart_min"), "arrive_min": ch.get("arrive_min"),
            "depart": hhmm(ch.get("depart_min")), "arrive": hhmm(ch.get("arrive_min")), "class_step": ch.get("class_step"),
            "class_flagged": ch.get("class_flagged"), "boarding_note": ch.get("boarding_note"), "score": a["score"]}


def passengers(conn, now_min, *, status=None, dest=None, q=None, limit=500, offset=0):
    groups = _group_rows(conn)
    sc = scores(conn, groups, now_min)
    live = _live(conn)
    vehicle_of = {r["pool_id"]: r["vehicle_id"] for r in _all(conn, "SELECT pool_id, vehicle_id FROM pools")}
    displaced, held = dstate.load_displaced(conn), dstate.load_held(conn)
    names = place_names(conn)
    rows = []
    for g in groups:
        if status and g["state"] != status.upper():
            continue
        if dest and g["dest_place"] != dest.upper():
            continue
        if q and q.lower() not in f"{g['group_id']} {g['pnr'] or ''}".lower():
            continue
        s, rank = sc.get(g["group_id"], (None, None))
        a = g["attrs"]
        rows.append({"group_id": g["group_id"], "pnr": g["pnr"], "size": g["size"], "class": g["class"], "reserved": g["reserved"],
                     "known": bool(g["known"]), "dest_place": g["dest_place"], "dest_name": names.get(g["dest_place"]), "state": g["state"],
                     "score": s["total"] if s else None, "rank": rank, "score_breakdown": s["breakdown"] if s else None,
                     "flags": {"senior": a["has_senior"], "child": a["has_child_under_12"], "pregnant": a["pregnant"],
                               "disability": a["disability"], "wheelchair": g["requirements"].get("wheelchair", False),
                               "deadline": hhmm(a["deadline_min"])},
                     "language": a.get("language"), "waiting_since": g["waiting_since"],
                     "allocation": _alloc_view(live.get(g["group_id"]), vehicle_of),
                     "displaced": g["group_id"] in displaced, "held_by_operator": g["group_id"] in held,
                     "boarded_on_own": g["self_boarded_vehicle"]})
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["group_id"]))
    return {"total": len(rows), "items": rows[offset:offset + limit]}


def why(conn, now_min, group_id):
    g = next((x for x in _group_rows(conn) if x["group_id"] == group_id), None)
    if g is None:
        return None
    groups = _group_rows(conn)
    sc = scores(conn, groups, now_min)
    s, rank = sc.get(group_id, (None, None))
    vehicle_of = {r["pool_id"]: r["vehicle_id"] for r in _all(conn, "SELECT pool_id, vehicle_id FROM pools")}
    history = [dict(r) for r in _all(conn, "SELECT id, pool_id, board_idx, alight_idx, status, batch_id, score, created_seq, status_seq, status_reason FROM allocations WHERE group_id = ? ORDER BY id", group_id)]
    for h in history:
        h["status_reason"] = json.loads(h["status_reason"]) if h["status_reason"] else None
        h["vehicle_id"] = vehicle_of[h["pool_id"]]
    live = _live(conn).get(group_id)
    reason = json.loads(live["reason"]) if live else None
    unresolved = None
    if g["state"] == "UNRESOLVED":
        item = _one(conn, """SELECT i.detail, i.batch_id FROM batch_items i JOIN plan_batches b USING (batch_id)
                              WHERE i.group_id = ? AND i.kind = 'UNRESOLVED' ORDER BY b.proposed_seq DESC LIMIT 1""", group_id)
        if item:
            unresolved = dict(json.loads(item["detail"]), batch_id=item["batch_id"])
    held = dstate.load_held(conn).get(group_id)
    names = place_names(conn)
    decision = (reason or {}).get("text") or ((unresolved or {}).get("reason") or {}).get("text") or \
               (f"Held out of automatic planning by the operator: {held['why']}" if held else "Not affected by the disruption." if g["state"] == "UNAFFECTED" else "No decision yet.")
    return {"group": {"group_id": group_id, "pnr": g["pnr"], "size": g["size"], "class": g["class"], "reserved": g["reserved"], "known": bool(g["known"]),
                      "dest_place": g["dest_place"], "dest_name": names.get(g["dest_place"]), "requirements": g["requirements"], "attrs": g["attrs"]},
            "state": g["state"], "score": s, "rank": rank, "of": len(sc),
            "stored_score_at_allocation": live["score"] if live else None, "allocation": _alloc_view(live, vehicle_of),
            "reason": reason, "decision_text": decision, "unresolved": unresolved, "held_by_operator": held,
            "displaced": group_id in dstate.load_displaced(conn), "boarded_on_own": g["self_boarded_vehicle"], "history": history}


# ------------------------------------------------------------------------------------------------ unresolved demand
def unresolved(conn, now_min):
    groups = {g["group_id"]: g for g in _group_rows(conn)}
    sc = scores(conn, list(groups.values()), now_min)
    names = place_names(conn)
    latest = {}
    for r in _all(conn, """SELECT i.group_id, i.detail, i.batch_id FROM batch_items i JOIN plan_batches b USING (batch_id)
                           WHERE i.kind = 'UNRESOLVED' ORDER BY b.proposed_seq"""):
        latest[r["group_id"]] = r
    displaced = dstate.load_displaced(conn)
    by_dest = {}
    for g in groups.values():
        if g["state"] != "UNRESOLVED":
            continue
        item = latest.get(g["group_id"])
        detail = json.loads(item["detail"]) if item else {}
        row = {"group_id": g["group_id"], "pnr": g["pnr"], "size": g["size"], "class": g["class"], "rank": sc.get(g["group_id"], (None, None))[1],
               "score": (sc.get(g["group_id"], (None, None))[0] or {}).get("total"), "reason": detail.get("reason"),
               "alternatives": detail.get("alternatives", []), "displaced": g["group_id"] in displaced,
               "blocking_groups": detail.get("blocking_groups"), "blocking_why": detail.get("blocking_why"), "planned_in_batch": item["batch_id"] if item else None}
        by_dest.setdefault(g["dest_place"], []).append(row)
    out = []
    for dest in sorted(by_dest):
        rows = sorted(by_dest[dest], key=lambda r: (r["rank"] or 10 ** 9, r["group_id"]))
        out.append({"dest_place": dest, "dest_name": names.get(dest), "groups": len(rows), "heads": sum(r["size"] for r in rows), "items": rows})
    return out


# ------------------------------------------------------------------------------------------------ batches
def _batch_row(conn, batch_id):
    return _one(conn, "SELECT * FROM plan_batches WHERE batch_id = ?", batch_id)


def batch(conn, batch_id, *, with_items=True):
    b = _batch_row(conn, batch_id)
    if b is None:
        return None
    summary = json.loads(b["summary"])
    out = {"batch_id": b["batch_id"], "status": b["status"], "cause": b["cause"], "base_seq": b["base_seq"], "proposed_seq": b["proposed_seq"],
           "approved_seq": b["approved_seq"], "stale": batch_is_stale(conn, batch_id) if b["status"] == "PROPOSED" else False,
           # the operator edited the weights after this plan was made and has not re-run: the plan reflects the OLD weights
           "weights_out_of_date": b["status"] == "PROPOSED" and summary.get("weights") is not None and summary["weights"] != dstate.current_weights(conn),
           "diff": summary.get("diff"), "summary": {k: v for k, v in summary.items() if k not in ("diff", "reshuffle_moves")},
           "reshuffle_moves": summary.get("reshuffle_moves", [])}
    tent = _one(conn, "SELECT COUNT(*) n, COALESCE(SUM(size), 0) h FROM allocations WHERE batch_id = ? AND status = 'TENTATIVE'", batch_id)
    conf = _one(conn, "SELECT COUNT(*) n, COALESCE(SUM(size), 0) h FROM allocations WHERE batch_id = ? AND status IN ('CONFIRMED','BOARDED')", batch_id)
    out["allocations"] = {"tentative": {"groups": tent["n"], "heads": tent["h"]}, "confirmed": {"groups": conf["n"], "heads": conf["h"]}}
    if with_items:
        info = {g["group_id"]: g for g in _group_rows(conn)}
        names = place_names(conn)
        cats = {}
        for it in _all(conn, "SELECT * FROM batch_items WHERE batch_id = ? ORDER BY item_idx", batch_id):
            g = info[it["group_id"]]
            cats.setdefault(it["kind"], []).append({"group_id": it["group_id"], "pnr": g["pnr"], "size": g["size"], "class": g["class"],
                                                    "dest_place": g["dest_place"], "dest_name": names.get(g["dest_place"]),
                                                    "detail": json.loads(it["detail"])})
        out["items"] = cats
    return out


def pending_batch(conn):
    bid = dstate.pending_batch_id(conn)
    return batch(conn, bid) if bid else None


def batches(conn):
    return [{"batch_id": r["batch_id"], "status": r["status"], "cause": r["cause"], "proposed_seq": r["proposed_seq"], "approved_seq": r["approved_seq"]}
            for r in _all(conn, "SELECT * FROM plan_batches ORDER BY proposed_seq")]


# ------------------------------------------------------------------------------------------------ rules
def rules(conn):
    buffers = json.loads(_one(conn, "SELECT value FROM settings WHERE key = 'buffers'")["value"])
    modes = {}
    for r in _all(conn, "SELECT buffer_mode, MIN(nominal) nominal FROM pools WHERE buffer_mode IS NOT NULL GROUP BY buffer_mode"):
        modes[r["buffer_mode"]] = {"buffer_pct": buffers.get(r["buffer_mode"]), "example": f"{r['nominal']} × {round(buffers.get(r['buffer_mode'], 0) * 100)}% = {math.floor(r['nominal'] * buffers.get(r['buffer_mode'], 0) + 1e-9)}"}
    row = _one(conn, "SELECT value, version FROM settings WHERE key = 'scoring_weights'")
    return {"weights": dstate.current_weights(conn), "weights_version": row["version"] if row else 0, "weights_source": "operator" if row else "config/scoring_weights.json",
            "buffers": modes, "class_rank": json.loads(_one(conn, "SELECT value FROM settings WHERE key = 'class_rank'")["value"]),
            "config": dstate.load_config(), "editable": {"weights": True, "buffers": True, "config": False},
            "note": "Weights are PLACEHOLDERS for the stub scorer; buffers apply to unreserved coaches and buses only (reserved coaches use exact vacancy)."}


# ------------------------------------------------------------------------------------------------ field view
def field_vehicles(conn):
    return [{"vehicle_id": v["vehicle_id"], "mode": v["mode"], "label": v["label"], "name": v["name"], "train_no": v["train_no"],
             "route_id": v["route_id"], "status": v["status"], "depart": v["depart"], "delay_min": v["delay_min"], "boarding_note": v["boarding_note"],
             "pools": [{"pool_id": p["pool_id"], "kind": p["kind"], "class": p["class"], "nominal": p["nominal"], "field_report": p["field_report"]} for p in v["pools"]]}
            for v in capacity(conn, "ALLOCATION")]


def manifest(conn, vehicle_id):
    v = _one(conn, "SELECT * FROM vehicles WHERE vehicle_id = ?", vehicle_id)
    if v is None:
        return None
    names = place_names(conn)
    rows = []
    for a in _all(conn, """SELECT a.*, g.pnr, g.dest_place, g.class gclass, g.requirements, g.attrs FROM allocations a JOIN pools p USING (pool_id)
                           JOIN groups g USING (group_id) WHERE p.vehicle_id = ? AND a.status IN ('TENTATIVE','CONFIRMED','BOARDED')
                           ORDER BY CASE a.status WHEN 'BOARDED' THEN 0 WHEN 'CONFIRMED' THEN 1 ELSE 2 END, a.id""", vehicle_id):
        rows.append({"allocation_id": a["id"], "group_id": a["group_id"], "pnr": a["pnr"], "size": a["size"], "class": a["gclass"], "pool_id": a["pool_id"],
                     "status": a["status"], "dest_place": a["dest_place"], "dest_name": names.get(a["dest_place"]),
                     "wheelchair": json.loads(a["requirements"]).get("wheelchair", False), "can_board": a["status"] == "CONFIRMED",
                     "note": "tentative: not yet approved, do not board" if a["status"] == "TENTATIVE" else None})
    boarded = sum(r["size"] for r in rows if r["status"] == "BOARDED")
    expected = sum(r["size"] for r in rows if r["status"] in ("CONFIRMED", "BOARDED"))
    return {"vehicle_id": vehicle_id, "status": v["status"], "depart": hhmm(v["depart_min"] + v["delay_min"]), "expected_heads": expected, "boarded_heads": boarded,
            "passengers": rows}


# ------------------------------------------------------------------------------------------------ phone
def phone_messages(conn, key):
    g = _one(conn, "SELECT group_id, pnr FROM groups WHERE pnr = ? OR group_id = ?", key, key)
    if g is None:
        return None
    rows = _all(conn, "SELECT n.*, e.ts_sim FROM notifications n JOIN events e ON e.seq = n.sent_seq "
                      "WHERE n.group_id = ? AND n.channel = 'PHONE_MOCK' ORDER BY n.id", g["group_id"])
    out = []
    for r in rows:
        detail = json.loads(r["detail"]) if r["detail"] else None
        out.append({"id": r["id"], "channel": r["channel"], "lang": r["lang"], "message": r["message"], "reason": r["reason"],
                    "detail": detail, "sent_seq": r["sent_seq"],
                    # simulation clock when it was sent, and what kind of message it is (NEW / CHANGED / DISPLACED_UNPLACED; null for old logs)
                    "sent_at_min": r["ts_sim"], "sent_at": hhmm(r["ts_sim"]), "kind": (detail or {}).get("kind")})
    return {"group_id": g["group_id"], "pnr": g["pnr"], "messages": out}


def pending_batch_summary(conn):
    bid = dstate.pending_batch_id(conn)
    if not bid:
        return None
    b = batch(conn, bid, with_items=False)
    return {"batch_id": b["batch_id"], "cause": b["cause"], "stale": b["stale"], "weights_out_of_date": b["weights_out_of_date"],
            "diff": b["diff"], "allocations": b["allocations"]}
