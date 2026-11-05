"""Read helpers over the event log."""
import json


def list_events(conn, *, after_seq=0, limit=200, hide_rejected=True, tail=False):
    """Events in seq order. COMMAND_REJECTED audit rows are hidden by default (the UI can pass hide_rejected=False).
    tail=True returns the LAST `limit` events instead of the first (what a scrolling log wants)."""
    where = "SELECT * FROM events WHERE seq > ?" + (" AND type <> 'COMMAND_REJECTED'" if hide_rejected else "")
    sql = f"SELECT * FROM ({where} ORDER BY seq DESC LIMIT ?) ORDER BY seq" if tail else where + " ORDER BY seq LIMIT ?"
    return [{"seq": r["seq"], "ts_sim": r["ts_sim"], "ts_wall": r["ts_wall"], "type": r["type"], "actor": r["actor"],
             "payload": json.loads(r["payload"]), "causation_seq": r["causation_seq"]}
            for r in conn.execute(sql, (after_seq, limit))]
