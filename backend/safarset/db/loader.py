"""Load a generated scenario into the state tables (called by the SCENARIO_LOADED reducer)."""
import json


def _j(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def load_scenario(conn, seq, sc):
    meta = sc["meta"]
    for pid, pl in sc["places"].items():
        conn.execute("INSERT INTO places VALUES (?,?,?,?)",
                     (pid, pl["name"], _j(pl["rail"]), int(bool(pl.get("transfer_only")))))
    for v in sc["vehicles"]:
        conn.execute("INSERT INTO vehicles (vehicle_id, mode, role, label, depart_min, route_id, train_no, name, boarding, attrs)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (v["vehicle_id"], v["mode"], v["role"], v["label"], v["depart_min"], v.get("route_id"),
                      v.get("train_no"), v.get("name"), _j(v["boarding"]), _j(v["attrs"])))
        for s in v["stops"]:
            conn.execute("INSERT INTO vehicle_stops VALUES (?,?,?,?,?,?,?)",
                         (v["vehicle_id"], s["seq"], s["stop_id"], s.get("stop_name"), _j(s["serves_places"]),
                          s["arr_min"], s["dep_min"]))
        for p in v["pools"]:
            conn.execute("INSERT INTO pools VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (p["pool_id"], v["vehicle_id"], p["kind"], p["class"], p["coaches"], p["nominal"],
                          p["capacity_label"], p["buffer_mode"], p["buffer_pct"], p["walkon_expected"]))
            for s in p["segments"]:
                conn.execute("INSERT INTO segment_capacity (pool_id, seg_idx, cap, used, committed_other) VALUES (?,?,?,0,?)",
                             (p["pool_id"], s["seg_idx"], s["cap"], s.get("committed_other", 0)))
    for g in sc["groups"]:
        conn.execute("INSERT INTO groups (group_id, pnr, size, reserved, known, class, board_place, dest_place, on_vehicle_id,"
                     " booking_time, waiting_since, requirements, attrs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (g["group_id"], g["pnr"], g["size"], int(g["reserved"]), int(g["known"]), g["class"],
                      g["board_place"], g["dest_place"], meta["cancelled_vehicle_id"], g["booking_time"],
                      g["waiting_since"], _j(g["requirements"]), _j(g["attrs"])))
    for key, val in (("buffers", sc["buffers"]), ("class_rank", sc["class_rank"]),
                     ("scenario_meta", {"params": meta["params"], "cancel_min": meta["cancel_min"],
                                        "cancelled_vehicle_id": meta["cancelled_vehicle_id"], "label": meta["label"]}),
                     ("behaviour", sc["behaviour"]), ("connections", sc["connections"])):
        conn.execute("INSERT INTO settings (key, value, version, updated_seq) VALUES (?,?,1,?)", (key, _j(val), seq))
