"""Reducers: the state projection. Each takes (conn, seq, payload_model) and runs inside the transaction that
appended the event. Reducers are deterministic (no clock, no randomness) so replaying the log rebuilds identical state.

Rejections raise Rejected; the transaction rolls back and nothing (neither event nor state) is written.
"""
import json
import math
import sqlite3

from ..db.loader import load_scenario, load_vehicle

HOLDING = ("TENTATIVE", "CONFIRMED", "BOARDED")


class Rejected(ValueError):
    """The command is refused; carries a human-readable message for the UI."""


class StaleBatch(Rejected):
    pass


class BufferRejected(Rejected):
    pass


class CapacityRejected(Rejected):
    """An allocation would oversell a segment. The message names the pool and segment; `detail` says the database constraint stopped it."""
    detail = "blocked by database capacity constraint"


def _capacity_refusal(conn, pool_id, board_idx, alight_idx, size):
    """Plain-language reason for a refused allocation: which vehicle, coach and segment is full. Called after the failed statement
    (SQLite undoes that statement only), so the segment numbers are the ones that refused it."""
    pool = _one(conn, "SELECT p.class, v.vehicle_id, v.name FROM pools p JOIN vehicles v USING (vehicle_id) WHERE p.pool_id = ?", (pool_id,))
    stops = {r["seq"]: (r["stop_name"] or r["stop_id"]) for r in conn.execute(
        "SELECT seq, stop_name, stop_id FROM vehicle_stops WHERE vehicle_id = ?", (pool["vehicle_id"],))}
    full = [r for r in conn.execute("SELECT seg_idx, cap - used AS free FROM segment_capacity WHERE pool_id = ? AND seg_idx >= ? AND seg_idx < ? "
                                    "AND cap - used < ? ORDER BY seg_idx", (pool_id, board_idx, alight_idx, size))]
    who = f"{pool['name'] or pool['vehicle_id']} ({pool['vehicle_id']}), {pool['class']}"
    if not full:
        return CapacityRejected(f"No room on {who}: the seats for stops {board_idx} to {alight_idx} are not available.")
    first = full[0]
    free = max(0, first["free"])
    text = (f"No room on {who}: {stops.get(first['seg_idx'], first['seg_idx'])} to {stops.get(first['seg_idx'] + 1, first['seg_idx'] + 1)} "
            f"has {free} free seat{'' if free == 1 else 's'} and this group needs {size}.")
    if len(full) > 1:
        text += f" {len(full)} segments of the journey are full."
    return CapacityRejected(text)


def _insert_allocation(conn, sql, args, pool_id, board_idx, alight_idx, size):
    try:
        conn.execute(sql, args)
    except sqlite3.IntegrityError as e:
        if "used <= cap" in str(e):
            raise _capacity_refusal(conn, pool_id, board_idx, alight_idx, size) from e
        raise


def g_size(conn, group_id):
    return _one(conn, "SELECT size FROM groups WHERE group_id = ?", (group_id,))["size"]


def _j(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def _one(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()


def _floor_pct(n, pct):
    return int(math.floor(n * pct + 1e-9))


# ------------------------------------------------------------------ shared: change capacity, shedding if needed
def _set_status(conn, seq, alloc_id, status, cause):
    conn.execute("UPDATE allocations SET status = ?, status_seq = ?, status_reason = ? WHERE id = ?",
                 (status, seq, _j(cause), alloc_id))


def _fit_capacity(conn, seq, pool_id, new_caps, cause, allow_displace, buffer_rule=False):
    """Apply new_caps {seg_idx: cap} to a pool.

    1. buffer_rule: reject if confirmed+boarded on any segment exceeds the new cap (settings changes may never
       push out CONFIRMED passengers).
    2. If used > new cap, shed holders: TENTATIVE first (lowest score, newest first), then - only when
       allow_displace - CONFIRMED (physically cannot be carried) -> DISPLACED. BOARDED is never shed.
    3. Write the new caps (the DB CHECK is the final judge).
    Shed order uses the score STORED on each allocation, not a recomputed one (see docs/scoring_interface.md, "Shed order").
    Returns (released_ids, displaced_ids)."""
    if buffer_rule:
        for seg, cap in sorted(new_caps.items()):
            r = _one(conn, "SELECT confirmed + boarded AS firm FROM v_segment_load WHERE pool_id = ? AND seg_idx = ?",
                     (pool_id, seg))
            if r["firm"] > cap:
                raise BufferRejected(
                    f"Refused: this setting would leave capacity {cap} on {pool_id} segment {seg}, below the "
                    f"{r['firm']} seats already confirmed or boarded. Confirmed passengers are never displaced by a "
                    f"settings change; nothing was changed.")
    released, displaced = [], []
    while True:
        over = [seg for seg, cap in new_caps.items()
                if _one(conn, "SELECT used FROM segment_capacity WHERE pool_id = ? AND seg_idx = ?", (pool_id, seg))["used"] > cap]
        if not over:
            break
        covers = " OR ".join("(board_idx <= ? AND alight_idx > ?)" for _ in over)   # must cover an overloaded segment
        cargs = [x for seg in over for x in (seg, seg)]
        for status in ("TENTATIVE", "CONFIRMED") if allow_displace else ("TENTATIVE",):
            victim = _one(conn, f"SELECT id FROM allocations WHERE pool_id = ? AND status = ? AND ({covers})"
                                " ORDER BY COALESCE(json_extract(reason, '$.score.tier'), json_extract(reason, '$.tier'), 2) DESC, score ASC, id DESC LIMIT 1",
                          (pool_id, status, *cargs))
            if victim:
                break
        else:
            victim = None
        if victim is None:
            raise Rejected(f"Cannot reduce capacity of {pool_id}: the remaining holders cannot be moved "
                           f"(boarded passengers, or confirmed passengers on a settings change).")
        if status == "TENTATIVE":
            _set_status(conn, seq, victim["id"], "RELEASED", cause)
            released.append(victim["id"])
        else:
            _set_status(conn, seq, victim["id"], "DISPLACED", cause)
            displaced.append(victim["id"])
    for seg, cap in new_caps.items():
        conn.execute("UPDATE segment_capacity SET cap = ? WHERE pool_id = ? AND seg_idx = ?", (cap, pool_id, seg))
    return released, displaced


def _pool(conn, pool_id):
    p = _one(conn, "SELECT * FROM pools WHERE pool_id = ?", (pool_id,))
    if p is None:
        raise Rejected(f"unknown pool {pool_id}")
    return p


def _nseg(conn, pool_id):
    return _one(conn, "SELECT COUNT(*) AS n FROM segment_capacity WHERE pool_id = ?", (pool_id,))["n"]


# ------------------------------------------------------------------ reducers
def scenario_loaded(conn, seq, p):
    if _one(conn, "SELECT 1 FROM vehicles LIMIT 1"):
        raise Rejected("a scenario is already loaded")
    load_scenario(conn, seq, p.scenario)


def train_cancelled(conn, seq, p):
    v = _one(conn, "SELECT * FROM vehicles WHERE vehicle_id = ?", (p.vehicle_id,))
    if v is None:
        raise Rejected(f"unknown vehicle {p.vehicle_id}")
    if v["mode"] != "TRAIN" or v["status"] == "CANCELLED":
        raise Rejected(f"{p.vehicle_id} is not a running train")
    conn.execute("UPDATE vehicles SET status = 'CANCELLED' WHERE vehicle_id = ?", (p.vehicle_id,))
    conn.execute("UPDATE groups SET affected = 1 WHERE on_vehicle_id = ?", (p.vehicle_id,))
    conn.execute("INSERT INTO disruptions VALUES (?,?,?,?,?)",
                 (seq, "TRAIN_CANCELLED", p.vehicle_id, None, _j({"reason": p.reason})))
    # Seats on the cancelled train disappear: shed whoever held them.
    _cancel_vehicle_pools(conn, seq, p.vehicle_id, {"cause": "TRAIN_CANCELLED", "seq": seq})


def train_delayed(conn, seq, p):
    if _one(conn, "SELECT 1 FROM vehicles WHERE vehicle_id = ?", (p.vehicle_id,)) is None:
        raise Rejected(f"unknown vehicle {p.vehicle_id}")
    conn.execute("UPDATE vehicles SET delay_min = ? WHERE vehicle_id = ?", (p.delay_min, p.vehicle_id))
    conn.execute("INSERT INTO disruptions VALUES (?,?,?,?,?)",
                 (seq, "TRAIN_DELAYED", p.vehicle_id, None, _j({"delay_min": p.delay_min})))


def _cancel_vehicle_pools(conn, seq, vehicle_id, cause):
    for pool in conn.execute("SELECT pool_id FROM pools WHERE vehicle_id = ?", (vehicle_id,)).fetchall():
        caps = {s: 0 for s in range(_nseg(conn, pool["pool_id"]))}
        _fit_capacity(conn, seq, pool["pool_id"], caps, cause, allow_displace=True)


def road_closed(conn, seq, p):
    """Buses on a closed route stop running (unless passengers are already aboard: those are underway)."""
    conn.execute("INSERT INTO disruptions VALUES (?,?,?,?,?)",
                 (seq, "ROAD_CLOSED", None, p.route_id, _j({"description": p.description})))
    if p.route_id is None:
        return
    for v in conn.execute("SELECT vehicle_id FROM vehicles WHERE route_id = ? AND status = 'SCHEDULED' ORDER BY vehicle_id", (p.route_id,)).fetchall():
        aboard = _one(conn, "SELECT 1 FROM allocations a JOIN pools p USING (pool_id) WHERE p.vehicle_id = ? AND a.status = 'BOARDED'", (v["vehicle_id"],))
        if aboard:
            continue
        conn.execute("UPDATE vehicles SET status = 'CANCELLED' WHERE vehicle_id = ?", (v["vehicle_id"],))
        _cancel_vehicle_pools(conn, seq, v["vehicle_id"], {"cause": "ROAD_CLOSED", "seq": seq, "route_id": p.route_id})


def _store_claim(conn, seq, pool_id, seg, value, observed_at, source):
    conn.execute("INSERT OR REPLACE INTO vacancy_claims VALUES (?,?,?,?,?,?)", (pool_id, seg, value, observed_at, source, seq))


def _record_conflict(conn, seq, pool_id, seg, outcome, kept, other):
    """kept and other are (value, source, observed_at) tuples."""
    conn.execute("INSERT INTO field_conflicts (seq, pool_id, seg_idx, outcome, kept_value, kept_source, kept_observed_at,"
                 " other_value, other_source, other_observed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (seq, pool_id, seg, outcome, *kept, *other))


def _resolve_vacancy_claim(conn, seq, p, seg):
    """Two field sources can disagree about one segment. Arrival order is not evidence, so the reducer decides by observation time:
      - no claim held yet                  -> accept
      - newer observation than the one held -> accept (the held claim is superseded)
      - older observation than the one held -> refuse, keep the held value, record STALE_IGNORED
      - same observation time, different value -> keep the LOWER (safer: fewer seats to sell), record CONFLICT for the operator
      - undated claim vs a dated one        -> refuse, record UNDATED_IGNORED
      - undated vs undated                  -> the last arrival wins (events from before observation times existed)
    Returns the value to apply to the segment, or None to leave the segment's capacity as it is."""
    held = _one(conn, "SELECT * FROM vacancy_claims WHERE pool_id = ? AND seg_idx = ?", (p.pool_id, seg))
    source = p.reported_by or "unknown"
    if held is None:
        _store_claim(conn, seq, p.pool_id, seg, p.vacancy, p.observed_at, source)
        return p.vacancy
    held_claim = (held["value"], held["source"], held["observed_at"])
    new_claim = (p.vacancy, source, p.observed_at)
    if p.observed_at is None and held["observed_at"] is None:
        _store_claim(conn, seq, p.pool_id, seg, p.vacancy, None, source)
        return p.vacancy
    if p.observed_at is None:
        if p.vacancy != held["value"]:
            _record_conflict(conn, seq, p.pool_id, seg, "UNDATED_IGNORED", held_claim, new_claim)
        return None
    if held["observed_at"] is None or p.observed_at > held["observed_at"]:
        _store_claim(conn, seq, p.pool_id, seg, p.vacancy, p.observed_at, source)
        return p.vacancy
    if p.observed_at < held["observed_at"]:
        if p.vacancy != held["value"]:
            _record_conflict(conn, seq, p.pool_id, seg, "STALE_IGNORED", held_claim, new_claim)
        return None
    if p.vacancy == held["value"]:
        return None
    safer = min(p.vacancy, held["value"])
    _store_claim(conn, seq, p.pool_id, seg, safer, p.observed_at, "conflict")
    _record_conflict(conn, seq, p.pool_id, seg, "CONFLICT", (safer, "conflict", p.observed_at), new_claim)
    return safer


def conflict_resolved(conn, seq, p):
    c = _one(conn, "SELECT resolved FROM field_conflicts WHERE id = ?", (p.conflict_id,))
    if c is None:
        raise Rejected(f"unknown field conflict {p.conflict_id}")
    if c["resolved"]:
        raise Rejected(f"field conflict {p.conflict_id} is already reviewed")
    conn.execute("UPDATE field_conflicts SET resolved = 1, resolved_seq = ?, resolved_note = ? WHERE id = ?", (seq, p.note, p.conflict_id))


def vacancy_update(conn, seq, p):
    pool = _pool(conn, p.pool_id)
    if pool["kind"] != "RESERVED":
        raise Rejected(f"{p.pool_id} is unreserved; vacancy updates apply to reserved coaches only")
    if p.to_seg > _nseg(conn, p.pool_id) or p.from_seg >= p.to_seg:
        raise Rejected("segment range outside the pool")
    if p.vacancy > pool["nominal"]:
        raise Rejected(f"vacancy {p.vacancy} exceeds the pool's nominal {pool['nominal']}")
    caps = {}
    for s in range(p.from_seg, p.to_seg):
        value = _resolve_vacancy_claim(conn, seq, p, s)
        if value is None:
            value = _one(conn, "SELECT cap FROM segment_capacity WHERE pool_id = ? AND seg_idx = ?", (p.pool_id, s))["cap"]
        caps[s] = value
    _fit_capacity(conn, seq, p.pool_id, caps, {"cause": "VACANCY_UPDATE", "seq": seq}, allow_displace=True)


def noshows_reported(conn, seq, p):
    pool = _pool(conn, p.pool_id)
    if pool["vehicle_id"] != p.vehicle_id or pool["kind"] != "RESERVED":
        raise Rejected("second-chart vacancies apply to a reserved pool of the stated vehicle")
    if p.to_seg > _nseg(conn, p.pool_id) or p.from_seg >= p.to_seg:
        raise Rejected("segment range outside the pool")
    caps = {}
    for s in range(p.from_seg, p.to_seg):
        cap = _one(conn, "SELECT cap FROM segment_capacity WHERE pool_id = ? AND seg_idx = ?", (p.pool_id, s))["cap"]
        caps[s] = min(pool["nominal"], cap + p.seats_freed)
    _fit_capacity(conn, seq, p.pool_id, caps, {"cause": "NOSHOWS_REPORTED", "seq": seq}, allow_displace=False)


def _is_frozen(conn, pool_id):
    r = _one(conn, "SELECT level FROM field_reports WHERE pool_id = ?", (pool_id,))
    return bool(r) and r["level"] in ("FULL", "OVERCROWDED")


def _formula_caps(conn, pool, pct):
    """Allocatable seats per segment for an unreserved pool: floor(nominal x buffer) minus people already aboard.
    A pool reported FULL/OVERCROWDED stays frozen at what is already confirmed or boarded."""
    frozen = _is_frozen(conn, pool["pool_id"])
    caps = {}
    for s in conn.execute("SELECT s.seg_idx, s.committed_other, v.confirmed + v.boarded AS firm FROM segment_capacity s "
                          "JOIN v_segment_load v USING (pool_id, seg_idx) WHERE s.pool_id = ?", (pool["pool_id"],)):
        cap = max(0, _floor_pct(pool["nominal"], pct) - s["committed_other"])
        caps[s["seg_idx"]] = min(cap, s["firm"]) if frozen else cap
    return caps


def load_report(conn, seq, p):
    """ETM/conductor feed. FULL/OVERCROWDED on an unreserved pool means no more people can board: confirmed groups that
    no longer have physical room (nominal seats minus the count reported) are DISPLACED, lowest score first, and the
    pool is frozen at what is already confirmed or boarded. NORMAL lifts the freeze. Reserved pools: logged only."""
    pool = _pool(conn, p.pool_id)
    if pool["vehicle_id"] != p.vehicle_id:
        raise Rejected("pool does not belong to that vehicle")
    conn.execute("INSERT INTO field_reports VALUES (?,?,?,?,?) ON CONFLICT(pool_id) DO UPDATE SET level = excluded.level,"
                 " count = excluded.count, reported_seq = excluded.reported_seq",
                 (p.pool_id, p.vehicle_id, p.level, p.count, seq))
    if pool["kind"] != "UNRESERVED":
        return
    cause = {"cause": "LOAD_REPORT", "seq": seq, "level": p.level, "count": p.count}
    if p.level == "NORMAL":
        _fit_capacity(conn, seq, p.pool_id, _formula_caps(conn, pool, pool["buffer_pct"]), cause, allow_displace=False)
        return
    count = p.count if p.count is not None else pool["nominal"]      # no count reported: treat the vehicle as exactly full
    room = max(0, pool["nominal"] - count)
    confirmed = conn.execute("SELECT id, size FROM allocations WHERE pool_id = ? AND status = 'CONFIRMED' "
                             "ORDER BY COALESCE(json_extract(reason, '$.score.tier'), json_extract(reason, '$.tier'), 2) DESC, score ASC, id DESC",
                             (p.pool_id,)).fetchall()
    heads = sum(a["size"] for a in confirmed)
    for a in confirmed:
        if heads <= room:
            break
        _set_status(conn, seq, a["id"], "DISPLACED", dict(cause, reason=f"{p.level.lower()} before boarding: {count} aboard, {pool['nominal']} seats"))
        heads -= a["size"]
    _fit_capacity(conn, seq, p.pool_id, _formula_caps(conn, pool, pool["buffer_pct"]), cause, allow_displace=False)


def buffer_changed(conn, seq, p):
    pools = conn.execute("SELECT * FROM pools WHERE buffer_mode = ? ORDER BY pool_id", (p.mode,)).fetchall()
    if not pools:
        raise Rejected(f"unknown buffer mode {p.mode}")
    plans = []
    for pool in pools:                                   # rule check for every pool before touching any
        caps = _formula_caps(conn, pool, p.buffer_pct)
        plans.append((pool["pool_id"], caps))
        for seg, cap in caps.items():
            r = _one(conn, "SELECT confirmed + boarded AS firm FROM v_segment_load WHERE pool_id = ? AND seg_idx = ?",
                     (pool["pool_id"], seg))
            if r["firm"] > cap:
                raise BufferRejected(
                    f"Refused: a {round(p.buffer_pct * 100)}% buffer for {p.mode} would leave capacity {cap} on "
                    f"{pool['pool_id']} segment {seg}, below the {r['firm']} seats already confirmed or boarded. "
                    f"Confirmed passengers are never displaced by a settings change; nothing was changed.")
    for pool_id, caps in plans:
        _fit_capacity(conn, seq, pool_id, caps, {"cause": "BUFFER_CHANGED", "seq": seq}, allow_displace=False, buffer_rule=True)
        conn.execute("UPDATE pools SET buffer_pct = ? WHERE pool_id = ?", (p.buffer_pct, pool_id))
    row = _one(conn, "SELECT value, version FROM settings WHERE key = 'buffers'")
    buffers = json.loads(row["value"]) if row else {}
    buffers[p.mode] = p.buffer_pct
    _upsert_setting(conn, seq, "buffers", buffers)


def _upsert_setting(conn, seq, key, value):
    conn.execute("INSERT INTO settings (key, value, version, updated_seq) VALUES (?,?,1,?) ON CONFLICT(key) DO UPDATE SET"
                 " value = excluded.value, version = version + 1, updated_seq = excluded.updated_seq", (key, _j(value), seq))


def weights_changed(conn, seq, p):
    _upsert_setting(conn, seq, "scoring_weights", p.weights)


def sim_params_changed(conn, seq, p):
    _upsert_setting(conn, seq, "sim_params", p.params)


def passenger_boarded(conn, seq, p):
    a = _one(conn, "SELECT status FROM allocations WHERE id = ?", (p.allocation_id,))
    if a is None:
        raise Rejected(f"unknown allocation {p.allocation_id}")
    if a["status"] != "CONFIRMED":
        raise Rejected(f"only CONFIRMED allocations can board (this one is {a['status']})")
    _set_status(conn, seq, p.allocation_id, "BOARDED", {"cause": "PASSENGER_BOARDED", "seq": seq})


def passenger_displaced(conn, seq, p):
    a = _one(conn, "SELECT status FROM allocations WHERE id = ?", (p.allocation_id,))
    if a is None:
        raise Rejected(f"unknown allocation {p.allocation_id}")
    if a["status"] != "CONFIRMED":
        raise Rejected(f"only CONFIRMED allocations can be displaced (this one is {a['status']})")
    _set_status(conn, seq, p.allocation_id, "DISPLACED", {"cause": "PASSENGER_DISPLACED", "seq": seq, "reason": p.reason})


def plan_proposed(conn, seq, p):
    if _one(conn, "SELECT 1 FROM plan_batches WHERE batch_id = ?", (p.batch_id,)):
        raise Rejected(f"batch {p.batch_id} already exists")
    cause = {"cause": "PLAN_PROPOSED", "seq": seq, "batch_id": p.batch_id}
    footprint = {}
    # 1. supersede the pending batch: its tentative rows go back to the pool
    old = _one(conn, "SELECT batch_id FROM plan_batches WHERE status = 'PROPOSED'")
    if old:
        for a in conn.execute("SELECT id, pool_id, board_idx, alight_idx FROM allocations WHERE batch_id = ? AND status = 'TENTATIVE'",
                              (old["batch_id"],)).fetchall():
            _set_status(conn, seq, a["id"], "RELEASED", dict(cause, superseded=old["batch_id"]))
            footprint[(a["pool_id"], a["board_idx"], a["alight_idx"])] = 1
        conn.execute("UPDATE plan_batches SET status = 'SUPERSEDED' WHERE batch_id = ?", (old["batch_id"],))
    # 2. explicit releases (moves of tentative rows only)
    for aid in p.release:
        a = _one(conn, "SELECT status, pool_id, board_idx, alight_idx FROM allocations WHERE id = ?", (aid,))
        if a is None or a["status"] != "TENTATIVE":
            raise Rejected(f"allocation {aid} is not TENTATIVE; a plan never moves CONFIRMED or BOARDED passengers")
        _set_status(conn, seq, aid, "RELEASED", cause)
        footprint[(a["pool_id"], a["board_idx"], a["alight_idx"])] = 1
    conn.execute("INSERT INTO plan_batches (batch_id, status, cause, base_seq, proposed_seq, summary) VALUES (?,?,?,?,?,?)",
                 (p.batch_id, "PROPOSED", p.cause, p.base_seq, seq, _j(p.summary)))
    # 3. the new tentative set; the DB rejects any over-allocation (all segments or none)
    for a in p.allocations:
        g = _one(conn, "SELECT affected FROM groups WHERE group_id = ?", (a.group_id,))
        if g is None or not g["affected"]:
            raise Rejected(f"group {a.group_id} is unknown or not affected by a disruption")
        _insert_allocation(conn, "INSERT INTO allocations (group_id, pool_id, board_idx, alight_idx, size, status, batch_id, score, reason,"
                           " created_seq, status_seq) VALUES (?,?,?,?,(SELECT size FROM groups WHERE group_id = ?),'TENTATIVE',?,?,?,?,?)",
                           (a.group_id, a.pool_id, a.board_idx, a.alight_idx, a.group_id, p.batch_id, a.score, _j(a.reason), seq, seq),
                           a.pool_id, a.board_idx, a.alight_idx, g_size(conn, a.group_id))
        footprint[(a.pool_id, a.board_idx, a.alight_idx)] = 1
    for (pool_id, lo, hi) in sorted(footprint):
        conn.execute("INSERT INTO batch_footprint VALUES (?,?,?,?)", (p.batch_id, pool_id, lo, hi))
    for i, item in enumerate(p.items):
        if _one(conn, "SELECT 1 FROM groups WHERE group_id = ?", (item.group_id,)) is None:
            raise Rejected(f"unknown group {item.group_id} in plan items")
        conn.execute("INSERT INTO batch_items VALUES (?,?,?,?,?)", (p.batch_id, i, item.kind, item.group_id, _j(item.detail)))


def batch_is_stale(conn, batch_id):
    """Stale only if an event after the batch's base touched a pool/segment the batch uses (its own proposal excluded)."""
    return _one(conn, """
        SELECT 1 FROM plan_batches b
          JOIN batch_footprint f ON f.batch_id = b.batch_id
          JOIN capacity_touches t ON t.pool_id = f.pool_id AND t.seg_idx >= f.seg_lo AND t.seg_idx < f.seg_hi
         WHERE b.batch_id = ? AND t.seq > b.base_seq AND t.seq <> b.proposed_seq LIMIT 1""", (batch_id,)) is not None


def batch_approved(conn, seq, p):
    b = _one(conn, "SELECT status FROM plan_batches WHERE batch_id = ?", (p.batch_id,))
    if b is None:
        raise Rejected(f"unknown batch {p.batch_id}")
    if b["status"] != "PROPOSED":
        raise Rejected(f"batch {p.batch_id} is {b['status']}, not pending")
    if batch_is_stale(conn, p.batch_id):
        raise StaleBatch(f"batch {p.batch_id} is stale: capacity it relies on changed after it was planned. Re-plan.")
    conn.execute("UPDATE allocations SET status = 'CONFIRMED', status_seq = ?, status_reason = ? WHERE batch_id = ? AND status = 'TENTATIVE'",
                 (seq, _j({"cause": "BATCH_APPROVED", "seq": seq}), p.batch_id))
    conn.execute("UPDATE plan_batches SET status = 'APPROVED', approved_seq = ? WHERE batch_id = ?", (seq, p.batch_id))


def vehicle_deployed(conn, seq, p):
    """An extra vehicle becomes allocatable. Only dispatched (ALLOCATION) vehicles can be deployed, and only new ids."""
    v = p.vehicle
    missing = [k for k in ("vehicle_id", "mode", "role", "label", "depart_min", "boarding", "attrs", "stops", "pools") if k not in v]
    if missing:
        raise Rejected(f"vehicle spec is missing {', '.join(missing)}")
    if v["role"] != "ALLOCATION":
        raise Rejected("only an allocatable (dispatched) vehicle can be deployed")
    if _one(conn, "SELECT 1 FROM vehicles WHERE vehicle_id = ?", (v["vehicle_id"],)):
        raise Rejected(f"vehicle {v['vehicle_id']} already exists")
    if not v["stops"] or not v["pools"]:
        raise Rejected("a deployed vehicle needs stops and at least one pool")
    load_vehicle(conn, v)


def sms_sent(conn, seq, p):
    if _one(conn, "SELECT 1 FROM groups WHERE group_id = ?", (p.group_id,)) is None:
        raise Rejected(f"unknown group {p.group_id}")
    conn.execute("INSERT INTO notifications (group_id, channel, lang, message, reason, status, detail, sent_seq) VALUES (?,?,?,?,?,?,?,?)",
                 (p.group_id, p.channel, p.lang, p.message, p.reason, p.status, _j(p.detail) if p.detail is not None else None, seq))


def operator_override(conn, seq, p):
    """Human override (reason mandatory, logged). It changes state but never sends anything: an ASSIGN lands as a
    TENTATIVE seat in the pending batch and needs approval like any other change."""
    g = _one(conn, "SELECT * FROM groups WHERE group_id = ?", (p.group_id,))
    if g is None:
        raise Rejected(f"unknown group {p.group_id}")
    if not g["affected"]:
        raise Rejected(f"group {p.group_id} is not affected by a disruption")
    cause = {"cause": "OPERATOR_OVERRIDE", "seq": seq, "reason": p.reason}
    if p.action == "RESUME_AUTO":
        conn.execute("DELETE FROM group_holds WHERE group_id = ?", (p.group_id,))
        return
    live = _one(conn, "SELECT id, status FROM allocations WHERE group_id = ? AND status IN ('TENTATIVE','CONFIRMED','BOARDED')", (p.group_id,))
    if live:
        if live["status"] == "BOARDED":
            raise Rejected("this group has already boarded; an override cannot move it")
        _set_status(conn, seq, live["id"], "RELEASED" if live["status"] == "TENTATIVE" else "DISPLACED", cause)
    if p.action == "UNASSIGN":
        conn.execute("INSERT OR REPLACE INTO group_holds VALUES (?,?,?)", (p.group_id, p.reason, seq))
        return
    if p.pool_id is None or p.board_idx is None or p.alight_idx is None:
        raise Rejected("ASSIGN needs pool_id, board_idx and alight_idx")
    pool = _pool(conn, p.pool_id)
    veh = _one(conn, "SELECT * FROM vehicles WHERE vehicle_id = ?", (pool["vehicle_id"],))
    if veh["status"] != "SCHEDULED":
        raise Rejected(f"{veh['vehicle_id']} is not running")
    stops = {r["seq"]: r for r in conn.execute("SELECT * FROM vehicle_stops WHERE vehicle_id = ?", (veh["vehicle_id"],))}
    if p.board_idx not in stops or p.alight_idx not in stops:
        raise Rejected("segment range outside the vehicle's route")
    if g["dest_place"] not in json.loads(stops[p.alight_idx]["serves_places"]):
        raise Rejected(f"{veh['vehicle_id']} does not stop at {g['dest_place']} at stop {p.alight_idx}")
    arrive = stops[p.alight_idx]["arr_min"] + veh["delay_min"]
    warnings = []
    if json.loads(g["requirements"]).get("wheelchair") and not json.loads(veh["attrs"]).get("wheelchair_accessible"):
        warnings.append("vehicle is not wheelchair accessible")
    deadline = json.loads(g["attrs"]).get("deadline_min")
    if deadline is not None and arrive > deadline:
        warnings.append(f"arrives {arrive - deadline} min after the group's hard deadline")
    conn.execute("DELETE FROM group_holds WHERE group_id = ?", (p.group_id,))
    batch = _one(conn, "SELECT batch_id FROM plan_batches WHERE status = 'PROPOSED'")
    if batch is None:
        bid = f"OV{seq}"
        conn.execute("INSERT INTO plan_batches (batch_id, status, cause, base_seq, proposed_seq, summary) VALUES (?,?,?,?,?,?)",
                     (bid, "PROPOSED", "OPERATOR_OVERRIDE", seq - 1, seq, _j({"operator_override": True})))
    else:
        bid = batch["batch_id"]
    reason = {"algorithm": "operator-override", "operator_override": {"reason": p.reason, "seq": seq, "warnings": warnings},
              "chosen": {"vehicle_id": veh["vehicle_id"], "pool_id": p.pool_id, "mode": veh["mode"], "board_idx": p.board_idx,
                         "alight_idx": p.alight_idx, "depart_min": stops[p.board_idx]["dep_min"] + veh["delay_min"], "arrive_min": arrive,
                         "class_step": "OPERATOR_ASSIGNED", "class_flagged": False},
              "text": f"Assigned by the operator: {p.reason}." + (" Warnings: " + "; ".join(warnings) + "." if warnings else "")}
    _insert_allocation(conn, "INSERT INTO allocations (group_id, pool_id, board_idx, alight_idx, size, status, batch_id, score, reason, created_seq, status_seq)"
                       " VALUES (?,?,?,?,?,'TENTATIVE',?,?,?,?,?)",
                       (p.group_id, p.pool_id, p.board_idx, p.alight_idx, g["size"], bid, 1e6, _j(reason), seq, seq),
                       p.pool_id, p.board_idx, p.alight_idx, g["size"])
    conn.execute("INSERT INTO batch_footprint VALUES (?,?,?,?)", (bid, p.pool_id, p.board_idx, p.alight_idx))
    idx = _one(conn, "SELECT COALESCE(MAX(item_idx), -1) + 1 AS n FROM batch_items WHERE batch_id = ?", (bid,))["n"]
    conn.execute("INSERT INTO batch_items VALUES (?,?,?,?,?)",
                 (bid, idx, "DISPLACED" if live and live["status"] == "CONFIRMED" else "NEWLY_PLACED", p.group_id,
                  _j({"operator_override": True, "reason": p.reason,
                      "old_sms_still_held": bool(live and live["status"] == "CONFIRMED")})))


def clock_set(conn, seq, p):
    _upsert_setting(conn, seq, "clock", {"min": p.to_min})


def group_self_boarded(conn, seq, p):
    g = _one(conn, "SELECT * FROM groups WHERE group_id = ?", (p.group_id,))
    if g is None or not g["affected"]:
        raise Rejected(f"group {p.group_id} is unknown or not affected by a disruption")
    if g["self_boarded_vehicle"]:
        raise Rejected(f"group {p.group_id} has already boarded {g['self_boarded_vehicle']} on its own")
    if _one(conn, "SELECT 1 FROM vehicles WHERE vehicle_id = ?", (p.vehicle_id,)) is None:
        raise Rejected(f"unknown vehicle {p.vehicle_id}")
    live = _one(conn, "SELECT id, status FROM allocations WHERE group_id = ? AND status IN ('TENTATIVE','CONFIRMED','BOARDED')", (p.group_id,))
    if live:
        if live["status"] == "BOARDED":
            raise Rejected("this group is already boarded on its allocated vehicle")
        _set_status(conn, seq, live["id"], "RELEASED", {"cause": "SELF_BOARDED", "seq": seq, "vehicle_id": p.vehicle_id, "reason": p.reason})
    conn.execute("UPDATE groups SET self_boarded_vehicle = ? WHERE group_id = ?", (p.vehicle_id, p.group_id))
    conn.execute("DELETE FROM group_holds WHERE group_id = ?", (p.group_id,))


def passenger_escalated(conn, seq, p):
    """Auditable wait escalation: Tier 2 passenger promoted to Tier 1 after exceeding maximum wait threshold."""
    row = _one(conn, "SELECT attrs FROM groups WHERE group_id = ?", (p.group_id,))
    if row is None:
        raise Rejected(f"unknown group {p.group_id}")
    attrs = json.loads(row["attrs"])
    attrs["escalated"] = True
    attrs["escalated_seq"] = seq
    attrs["escalated_from_tier"] = p.from_tier
    attrs["escalated_to_tier"] = p.to_tier
    attrs["escalated_wait_min"] = p.wait_min
    attrs["escalation_reason"] = p.reason
    conn.execute("UPDATE groups SET attrs = ? WHERE group_id = ?", (_j(attrs), p.group_id))


def _noop(conn, seq, p):
    pass


REDUCERS = {
    "SCENARIO_LOADED": scenario_loaded, "TRAIN_CANCELLED": train_cancelled, "TRAIN_DELAYED": train_delayed,
    "ROAD_CLOSED": road_closed, "VACANCY_UPDATE": vacancy_update, "NOSHOWS_REPORTED": noshows_reported,
    "LOAD_REPORT": load_report, "PASSENGER_BOARDED": passenger_boarded, "PASSENGER_DISPLACED": passenger_displaced,
    "PLAN_PROPOSED": plan_proposed, "BATCH_APPROVED": batch_approved, "SMS_SENT": sms_sent, "VEHICLE_DEPLOYED": vehicle_deployed,
    "OPERATOR_OVERRIDE": operator_override, "WEIGHTS_CHANGED": weights_changed, "BUFFER_CHANGED": buffer_changed,
    "SIM_PARAMS_CHANGED": sim_params_changed, "COMMAND_REJECTED": _noop, "CLOCK_SET": clock_set,
    "GROUP_SELF_BOARDED": group_self_boarded, "PASSENGER_ESCALATED": passenger_escalated, "CONFLICT_RESOLVED": conflict_resolved,
}
