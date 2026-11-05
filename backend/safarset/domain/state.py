"""Read the planning inputs out of the database as plain dicts (the allocator never touches SQL)."""
import json
from pathlib import Path

from ..scoring.stub import default_weights


def load_config(config_dir=None):
    d = Path(config_dir) if config_dir else Path(__file__).resolve().parents[3] / "config"
    return json.loads((d / "allocator.json").read_text(encoding="utf-8"))


def _setting(conn, key):
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(r["value"]) if r else None


def current_weights(conn):
    return _setting(conn, "scoring_weights") or default_weights()


def load_vehicles(conn):
    """All vehicles with stops and pools. free[pool_id] = cap minus CONFIRMED and BOARDED seats per segment
    (TENTATIVE seats count as free: a re-plan may move them)."""
    vehicles = {}
    for v in conn.execute("SELECT * FROM vehicles ORDER BY vehicle_id"):
        vehicles[v["vehicle_id"]] = {
            "vehicle_id": v["vehicle_id"], "mode": v["mode"], "role": v["role"], "label": v["label"],
            "status": v["status"], "delay_min": v["delay_min"], "depart_min": v["depart_min"],
            "route_id": v["route_id"], "train_no": v["train_no"], "name": v["name"],
            "boarding": json.loads(v["boarding"]), "attrs": json.loads(v["attrs"]), "stops": [], "pools": []}
    for s in conn.execute("SELECT * FROM vehicle_stops ORDER BY vehicle_id, seq"):
        vehicles[s["vehicle_id"]]["stops"].append({
            "seq": s["seq"], "stop_id": s["stop_id"], "stop_name": s["stop_name"],
            "serves_places": json.loads(s["serves_places"]), "arr_min": s["arr_min"], "dep_min": s["dep_min"]})
    for p in conn.execute("SELECT * FROM pools ORDER BY pool_id"):
        vehicles[p["vehicle_id"]]["pools"].append({
            "pool_id": p["pool_id"], "kind": p["kind"], "class": p["class"], "nominal": p["nominal"],
            "buffer_mode": p["buffer_mode"], "buffer_pct": p["buffer_pct"]})
    free = {}
    for r in conn.execute("SELECT pool_id, seg_idx, cap - confirmed - boarded AS free FROM v_segment_load ORDER BY pool_id, seg_idx"):
        free.setdefault(r["pool_id"], []).append(r["free"])
    return vehicles, free


def load_pending_groups(conn):
    """Affected groups that hold no CONFIRMED/BOARDED seat: UNRESOLVED or TENTATIVE (both may be re-planned)."""
    rows = conn.execute("""SELECT g.* FROM groups g JOIN v_group_state s USING (group_id)
                            WHERE s.state IN ('UNRESOLVED','TENTATIVE') ORDER BY g.group_id""").fetchall()
    out = []
    for g in rows:
        d = dict(g)
        d["requirements"], d["attrs"] = json.loads(g["requirements"]), json.loads(g["attrs"])
        d["reserved"] = bool(g["reserved"])
        out.append(d)
    return out


def load_connections(conn):
    r = conn.execute("SELECT value FROM settings WHERE key = 'connections'").fetchone()
    return json.loads(r["value"]) if r else []


def load_held(conn):
    """Groups the operator removed from automatic planning: gid -> {why, size, dest_place}."""
    return {r["group_id"]: {"why": r["reason"], "size": r["size"], "dest_place": r["dest_place"]}
            for r in conn.execute("SELECT h.group_id, h.reason, g.size, g.dest_place FROM group_holds h JOIN groups g USING (group_id)")}


def load_pins(conn):
    """Existing TENTATIVE placements of the pending batch: gid -> pin (kept by the stability rule)."""
    pins = {}
    for r in conn.execute("""SELECT a.group_id, a.pool_id, a.board_idx, a.alight_idx, a.reason FROM allocations a
                              JOIN plan_batches b USING (batch_id) WHERE a.status = 'TENTATIVE' AND b.status = 'PROPOSED'"""):
        reason = json.loads(r["reason"])
        pins[r["group_id"]] = {"pool_id": r["pool_id"], "board_idx": r["board_idx"], "alight_idx": r["alight_idx"],
                               "reason": reason, "override": reason.get("algorithm") == "operator-override"}
    return pins


def pending_batch_id(conn):
    r = conn.execute("SELECT batch_id FROM plan_batches WHERE status = 'PROPOSED'").fetchone()
    return r["batch_id"] if r else None


def load_previous_proposed(conn):
    """The operator's last view: each group's latest allocation row in the pending batch (any status), gid -> row dict."""
    bid = pending_batch_id(conn)
    if bid is None:
        return {}
    out = {}
    for r in conn.execute("SELECT * FROM allocations WHERE batch_id = ? ORDER BY id", (bid,)):
        out[r["group_id"]] = dict(r)
    return out


def load_displaced(conn):
    """Groups whose CONFIRMED seat was displaced and who have not been re-confirmed since: gid -> displaced row."""
    out = {}
    for r in conn.execute("""SELECT d.* FROM allocations d WHERE d.status = 'DISPLACED' AND d.id = (
                                  SELECT MAX(x.id) FROM allocations x WHERE x.group_id = d.group_id AND x.status = 'DISPLACED')
                              AND NOT EXISTS (SELECT 1 FROM allocations y WHERE y.group_id = d.group_id AND y.id > d.id
                                              AND y.status IN ('CONFIRMED','BOARDED'))
                              AND NOT EXISTS (SELECT 1 FROM allocations z WHERE z.group_id = d.group_id AND z.status IN ('CONFIRMED','BOARDED'))"""):
        out[r["group_id"]] = dict(r)
    return out
