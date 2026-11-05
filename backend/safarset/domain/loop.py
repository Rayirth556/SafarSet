"""The event loop: apply an event, and when it can change what is possible, propose a new plan for approval.

Nothing is ever sent without approval: a re-plan only creates a pending batch of TENTATIVE changes. `approve` turns
the batch into CONFIRMED and then (and only then) asks the notifier to tell the people whose journey changed.
"""
import json
from dataclasses import dataclass, field

from ..events.apply import apply_event
from ..events.reducers import Rejected
from . import state
from .diff import build_diff
from .planner import propose_plan, submit_plan

# Events after which the set of feasible placements may have changed.
REPLAN_ON = {"TRAIN_CANCELLED", "TRAIN_DELAYED", "ROAD_CLOSED", "VACANCY_UPDATE", "NOSHOWS_REPORTED", "LOAD_REPORT", "VEHICLE_DEPLOYED",
             "BUFFER_CHANGED", "PASSENGER_DISPLACED", "OPERATOR_OVERRIDE", "GROUP_SELF_BOARDED"}


@dataclass
class Handled:
    seq: int
    batch_id: str | None = None


@dataclass
class Approval:
    batch_id: str
    seq: int
    confirmed_groups: list = field(default_factory=list)
    notified: list = field(default_factory=list)


class Engine:
    """notifier: optional object with notify(group: dict, allocation: dict | None, kind: str) -> dict | None, where the
    result (channel, lang, message, reason) is logged as an SMS_SENT event. kind: NEW | CHANGED | DISPLACED_UNPLACED."""

    def __init__(self, conn, *, notifier=None, scorer=None, config=None, auto_replan=True):
        self.conn, self.notifier, self.scorer, self.config, self.auto_replan = conn, notifier, scorer, config, auto_replan
        self.clock = None

    @classmethod
    def restore(cls, conn, **kw):
        """Rebuild an engine around an existing (e.g. replayed) database. Every clock change is logged with an event
        (CLOCK_SET, or the scenario time on the event it accompanies), so the clock is the scenario time of the last event."""
        e = cls(conn, **kw)
        row = conn.execute("SELECT ts_sim FROM events WHERE ts_sim IS NOT NULL ORDER BY seq DESC LIMIT 1").fetchone()
        e.clock = row["ts_sim"] if row else None
        return e

    # ------------------------------------------------------------------ helpers
    def _now(self, ts_sim):
        if ts_sim is not None:
            self.clock = ts_sim
        if self.clock is None:
            raise ValueError("no scenario clock yet: pass ts_sim")
        return self.clock

    def _scalar(self, sql, *a):
        return self.conn.execute(sql, a).fetchone()[0]

    def pending_batch(self):
        bid = state.pending_batch_id(self.conn)
        return dict(self.conn.execute("SELECT * FROM plan_batches WHERE batch_id = ?", (bid,)).fetchone()) if bid else None

    def _next_batch_id(self):
        n = [int(r[0][1:]) for r in self.conn.execute("SELECT batch_id FROM plan_batches WHERE batch_id GLOB 'B[0-9]*'")]
        return f"B{max(n, default=0) + 1}"

    def _disruption_active(self):
        return bool(self._scalar("SELECT COUNT(*) FROM groups WHERE affected = 1"))

    # ------------------------------------------------------------------ events
    def handle(self, type_, actor, payload, ts_sim=None):
        """Apply one event; if it can change feasibility, propose a fresh plan (pending, needs approval)."""
        now = self._now(ts_sim)
        seq = apply_event(self.conn, type_, actor, payload, ts_sim=now)
        batch = self.replan(now, cause=type_) if (self.auto_replan and type_ in REPLAN_ON and self._disruption_active()) else None
        return Handled(seq, batch)

    def replan(self, ts_sim=None, *, fresh=False, force=False, cause="MANUAL_REPLAN"):
        """Propose a new pending batch (batch.cause records why). Returns its id, or None when nothing would change (unless force)."""
        now = self._now(ts_sim)
        plan = propose_plan(self.conn, now, scorer=self.scorer, config=self.config, fresh=fresh)
        build_diff(self.conn, plan)
        if not force and self._same_as_pending(plan):
            return None
        bid = self._next_batch_id()
        submit_plan(self.conn, plan, bid, ts_sim=now, cause=cause)
        return bid

    def _same_as_pending(self, plan):
        pend = state.pending_batch_id(self.conn)
        new_place = {(a["group_id"], a["pool_id"], a["board_idx"], a["alight_idx"]) for a in plan.placements}
        new_unres = {u["group_id"] for u in plan.unresolved}
        if pend is None:
            if plan.placements:
                return False
            last = self.conn.execute("SELECT batch_id FROM plan_batches ORDER BY proposed_seq DESC LIMIT 1").fetchone()
            seen = {r["group_id"] for r in self.conn.execute("SELECT group_id FROM batch_items WHERE batch_id = ? AND kind = 'UNRESOLVED'",
                                                             (last["batch_id"],))} if last else None
            return seen is not None and seen == new_unres
        cur = {(r["group_id"], r["pool_id"], r["board_idx"], r["alight_idx"]) for r in self.conn.execute(
            "SELECT group_id, pool_id, board_idx, alight_idx FROM allocations WHERE batch_id = ? AND status = 'TENTATIVE'", (pend,))}
        cur_unres = {r["group_id"] for r in self.conn.execute("SELECT group_id FROM batch_items WHERE batch_id = ? AND kind = 'UNRESOLVED'", (pend,))}
        return cur == new_place and cur_unres == new_unres

    def ensure_plan(self, ts_sim=None):
        """A pending batch that is not stale, creating one if needed."""
        from ..events.reducers import batch_is_stale
        pend = self.pending_batch()
        if pend and not batch_is_stale(self.conn, pend["batch_id"]):
            if ts_sim is not None and ts_sim != self.clock:          # no event follows, so log the clock move explicitly
                self.handle("CLOCK_SET", "sim", {"to_min": ts_sim}, ts_sim)
            return pend["batch_id"]
        return self.replan(ts_sim, force=True)

    def adjust_weights_and_rerun(self, weights, ts_sim=None):
        """Operator edits the weights and re-runs: WEIGHTS_CHANGED, then a from-scratch plan as a NEW pending batch."""
        now = self._now(ts_sim)
        apply_event(self.conn, "WEIGHTS_CHANGED", "operator", {"weights": weights}, ts_sim=now)
        return self.replan(now, fresh=True, force=True, cause="WEIGHTS_RERUN")

    def override(self, group_id, action, reason, *, pool_id=None, board_idx=None, alight_idx=None, ts_sim=None):
        payload = {"group_id": group_id, "action": action, "reason": reason}
        if action == "ASSIGN":
            payload.update(pool_id=pool_id, board_idx=board_idx, alight_idx=alight_idx)
        return self.handle("OPERATOR_OVERRIDE", "operator", payload, ts_sim)

    # ------------------------------------------------------------------ approval (approval only)
    def approve(self, batch_id=None, ts_sim=None):
        now = self._now(ts_sim)
        batch_id = batch_id or state.pending_batch_id(self.conn)
        if batch_id is None:
            raise Rejected("there is no pending batch to approve")
        tentative = self.conn.execute("SELECT id, group_id FROM allocations WHERE batch_id = ? AND status = 'TENTATIVE'", (batch_id,)).fetchall()
        was_displaced = {r["group_id"] for r in self.conn.execute(
            "SELECT DISTINCT group_id FROM allocations WHERE status = 'DISPLACED'")}
        unplaced_displaced = [r["group_id"] for r in self.conn.execute(
            "SELECT group_id FROM batch_items WHERE batch_id = ? AND kind = 'DISPLACED' AND json_extract(detail, '$.replaced') = 0", (batch_id,))]
        seq = apply_event(self.conn, "BATCH_APPROVED", "operator", {"batch_id": batch_id}, ts_sim=now)   # raises Rejected if stale
        result = Approval(batch_id, seq, [t["group_id"] for t in tentative])
        if self.notifier:
            for t in tentative:
                self._notify(t["group_id"], t["id"], "CHANGED" if t["group_id"] in was_displaced else "NEW", now, result)
            for gid in unplaced_displaced:
                self._notify(gid, None, "DISPLACED_UNPLACED", now, result)
        return result

    def _notify(self, gid, alloc_id, kind, now, result):
        g = dict(self.conn.execute("SELECT * FROM groups WHERE group_id = ?", (gid,)).fetchone())
        g["requirements"], g["attrs"] = json.loads(g["requirements"]), json.loads(g["attrs"])
        alloc = None
        if alloc_id is not None:
            alloc = dict(self.conn.execute("SELECT * FROM allocations WHERE id = ?", (alloc_id,)).fetchone())
            alloc["reason"] = json.loads(alloc["reason"])
        msgs = self.notifier.notify(g, alloc, kind, self._notify_ctx(gid, alloc, kind, now))
        msgs = [] if not msgs else [msgs] if isinstance(msgs, dict) else list(msgs)
        for msg in msgs:
            apply_event(self.conn, "SMS_SENT", "system",
                        {"group_id": gid, "channel": msg["channel"], "lang": msg["lang"], "message": msg["message"], "reason": msg.get("reason"),
                         "status": msg.get("status", "SENT"), "detail": {**(msg.get("detail") or {}), "kind": kind}}, ts_sim=now)
        if msgs:
            result.notified.append(gid)

    def _notify_ctx(self, gid, alloc, kind, now):
        """Facts a notifier needs to word the message (names, stop, walk, why the journey changed). No wording here."""
        c = self.conn
        places = {r["place_id"]: r["name"] for r in c.execute("SELECT place_id, name FROM places")}
        g = c.execute("SELECT dest_place FROM groups WHERE group_id = ?", (gid,)).fetchone()
        ctx = {"now_min": now, "places": places, "dest_name": places.get(g["dest_place"], g["dest_place"])}
        d = c.execute("SELECT status_reason FROM allocations WHERE group_id = ? AND status = 'DISPLACED' ORDER BY id DESC LIMIT 1", (gid,)).fetchone()
        if d and d["status_reason"]:
            ctx["change_cause"] = json.loads(d["status_reason"]).get("cause")
        if alloc:
            v = c.execute("SELECT v.* FROM vehicles v JOIN pools p USING (vehicle_id) WHERE p.pool_id = ?", (alloc["pool_id"],)).fetchone()
            stop = c.execute("SELECT stop_name FROM vehicle_stops WHERE vehicle_id = ? AND seq = ?", (v["vehicle_id"], alloc["board_idx"])).fetchone()
            boarding = json.loads(v["boarding"])
            ctx["vehicle"] = {"vehicle_id": v["vehicle_id"], "mode": v["mode"], "name": v["name"], "train_no": v["train_no"], "route_id": v["route_id"]}
            ctx["boarding"] = {"stop_name": stop["stop_name"], "walk_m": boarding.get("walk_m"), "note": boarding.get("note")}
        return ctx
