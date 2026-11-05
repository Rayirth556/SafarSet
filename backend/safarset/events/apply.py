"""Single entry point for every state change: validate -> append event -> reduce, all in one transaction."""
import json
import sqlite3
from datetime import datetime, timezone

from pydantic import ValidationError

from ..db.conn import transaction
from .reducers import REDUCERS, Rejected
from .types import EVENT_MODELS


def _validate(type_, payload):
    model = EVENT_MODELS.get(type_)
    if model is None:
        raise Rejected(f"unknown event type {type_}")
    try:
        return model.model_validate(payload)
    except ValidationError as e:
        raise Rejected("invalid " + type_ + ": " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))


def _append(conn, seq, type_, actor, ts_sim, causation_seq, model, ts_wall=None):
    payload = json.dumps(model.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    ts_wall = ts_wall or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    cur = conn.execute("INSERT INTO events (seq, ts_sim, ts_wall, type, actor, payload, causation_seq) VALUES (?,?,?,?,?,?,?)",
                       (seq, ts_sim, ts_wall, type_, actor, payload, causation_seq))
    conn.execute("UPDATE ctx SET current_seq = ?", (cur.lastrowid,))
    return cur.lastrowid


def _run(conn, type_, actor, payload, ts_sim, causation_seq):
    model = _validate(type_, payload)
    with transaction(conn):
        seq = _append(conn, None, type_, actor, ts_sim, causation_seq, model)
        try:
            REDUCERS[type_](conn, seq, model)
        except sqlite3.IntegrityError as e:              # the DATABASE refused the write (CHECK / trigger)
            raise Rejected(f"database rejected the change: {e}") from e
    return seq


def apply_event(conn, type_, actor, payload, ts_sim=None, causation_seq=None):
    """Apply one event. Returns its seq. On refusal raises Rejected, writes no state and no event, and records a
    COMMAND_REJECTED audit event (so the operator's refused attempt is still visible in the log)."""
    try:
        return _run(conn, type_, actor, payload, ts_sim, causation_seq)
    except Rejected as e:
        if type_ != "COMMAND_REJECTED":
            _run(conn, "COMMAND_REJECTED", "system", {"command_type": type_, "error": str(e)}, ts_sim, None)
        raise


def replay(src, dst):
    """Rebuild state in an empty DB by re-running the reducers over src's event log (same seq and timestamps)."""
    for row in src.execute("SELECT * FROM events ORDER BY seq").fetchall():
        model = _validate(row["type"], json.loads(row["payload"]))
        with transaction(dst):
            _append(dst, row["seq"], row["type"], row["actor"], row["ts_sim"], row["causation_seq"], model, row["ts_wall"])
            REDUCERS[row["type"]](dst, row["seq"], model)
