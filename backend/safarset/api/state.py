"""Application state shared by all routes: the database, the engine, the WebSocket hub and the demo cursor."""
import asyncio
import json

from fastapi import HTTPException

from ..db.conn import new_db
from ..domain.loop import Engine
from ..events.apply import apply_event
from ..events.reducers import Rejected
from . import views
from .hub import Hub
from ..notify.notifier import Notifier

# which UI data a given event type invalidates (the UIs refetch these topics over REST)
TOPICS = {
    "SCENARIO_LOADED": ["all"],
    "TRAIN_CANCELLED": ["banner", "capacity", "passengers", "unresolved", "batch", "kpis"],
    "TRAIN_DELAYED": ["banner", "capacity", "passengers", "batch"],
    "ROAD_CLOSED": ["banner", "capacity", "passengers", "unresolved", "batch", "kpis"],
    "VEHICLE_DEPLOYED": ["capacity", "field", "passengers", "unresolved", "batch", "kpis"],
    "VACANCY_UPDATE": ["capacity", "passengers", "unresolved", "batch", "kpis"],
    "NOSHOWS_REPORTED": ["capacity", "passengers", "unresolved", "batch", "kpis"],
    "LOAD_REPORT": ["capacity", "field", "passengers", "unresolved", "batch", "kpis"],
    "PASSENGER_BOARDED": ["field", "passengers", "kpis", "capacity"],
    "PASSENGER_DISPLACED": ["capacity", "field", "passengers", "unresolved", "batch", "kpis"],
    "PLAN_PROPOSED": ["batch", "capacity", "passengers", "unresolved", "kpis"],
    "BATCH_APPROVED": ["batch", "capacity", "passengers", "unresolved", "kpis", "field"],
    "SMS_SENT": ["phone"],
    "OPERATOR_OVERRIDE": ["capacity", "passengers", "unresolved", "batch", "kpis"],
    "WEIGHTS_CHANGED": ["rules", "batch"],
    "BUFFER_CHANGED": ["rules", "capacity", "passengers", "batch", "kpis"],
    "SIM_PARAMS_CHANGED": ["sim"],
    "COMMAND_REJECTED": [],
    "CLOCK_SET": ["sim"],
    "GROUP_SELF_BOARDED": ["field", "capacity", "passengers", "unresolved", "batch", "kpis"],
    "PASSENGER_ESCALATED": ["passengers", "batch", "kpis"],
}


def public_event(row):
    payload = json.loads(row["payload"])
    if row["type"] == "SCENARIO_LOADED":                         # the full scenario is ~1 MB: send a summary
        meta = payload["scenario"]["meta"]
        payload = {"scenario": {"label": meta["label"], "params": meta["params"], "groups": len(payload["scenario"]["groups"]),
                                "vehicles": len(payload["scenario"]["vehicles"])}}
    return {"seq": row["seq"], "ts_sim": row["ts_sim"], "ts_wall": row["ts_wall"], "type": row["type"], "actor": row["actor"],
            "payload": payload, "causation_seq": row["causation_seq"], "rejected": row["type"] == "COMMAND_REJECTED"}


class AppState:
    def __init__(self, notifier=None):
        self.hub = Hub()
        self.lock = asyncio.Lock()
        self.notifier = notifier or Notifier.from_env()          # phone mock always; real SMS only if SAFARSET_SMS_* enables it
        self.conn = self.engine = self.scenario = None
        self.sim_params = {}
        self.timeline_idx = 0
        self.last_sent = 0

    @property
    def loaded(self):
        return self.engine is not None

    def require(self):
        if not self.loaded:
            raise HTTPException(409, detail={"error": "no scenario loaded: POST /sim/load-scenario first", "kind": "NoScenario"})
        return self

    @property
    def clock(self):
        return self.engine.clock if self.engine else None

    def reset(self, scenario):
        self.conn = new_db(check_same_thread=False)
        apply_event(self.conn, "SCENARIO_LOADED", "sim", {"scenario": scenario})
        self.engine = Engine(self.conn, notifier=self.notifier)
        self.engine.clock = scenario["meta"]["cancel_min"]
        self.scenario = scenario
        self.sim_params = {"compliance_rate": scenario["behaviour"]["compliance_rate"], "walkon_rate": scenario["behaviour"]["walkon_rate"]}
        self.timeline_idx = 0
        self.last_sent = self.conn.execute("SELECT MAX(seq) FROM events").fetchone()[0]

    # ------------------------------------------------------------------ snapshot + publishing
    def snapshot(self):
        if not self.loaded:
            return {"type": "snapshot", "loaded": False, "last_seq": 0}
        return {"type": "snapshot", "loaded": True, "last_seq": self.last_sent, "clock": views.hhmm(self.clock), "clock_min": self.clock,
                "banner": views.banner(self.conn, self.clock), "kpis": views.kpis(self.conn), "pending_batch": views.pending_batch_summary(self.conn),
                "sim_params": self.sim_params}

    async def publish(self):
        """After a mutation: push every new event, then KPIs, then an invalidate hint, and deliver SMS to phone mocks."""
        if not self.loaded:
            return
        rows = self.conn.execute("SELECT * FROM events WHERE seq > ? ORDER BY seq", (self.last_sent,)).fetchall()
        if not rows:
            return
        topics = []
        for r in rows:
            ev = public_event(r)
            await self.hub.broadcast({"type": "event", "seq": ev["seq"], "event": ev})
            for t in TOPICS.get(r["type"], []):
                if t not in topics:
                    topics.append(t)
            if r["type"] == "SMS_SENT" and ev["payload"]["channel"] == "PHONE_MOCK":
                p = ev["payload"]
                g = self.conn.execute("SELECT pnr FROM groups WHERE group_id = ?", (p["group_id"],)).fetchone()
                keys = [k for k in (p["group_id"], g["pnr"]) if k]
                await self.hub.send_phone(keys, {"type": "sms", "seq": ev["seq"], "group_id": p["group_id"], "channel": p["channel"],
                                                 "lang": p["lang"], "message": p["message"], "reason": p["reason"],
                                                 "detail": p.get("detail"), "kind": (p.get("detail") or {}).get("kind"),
                                                 "sent_at_min": ev["ts_sim"], "sent_at": views.hhmm(ev["ts_sim"])})
        self.last_sent = rows[-1]["seq"]
        if topics:
            await self.hub.broadcast({"type": "kpis", "kpis": views.kpis(self.conn), "clock": views.hhmm(self.clock), "clock_min": self.clock,
                                      "last_seq": self.last_sent})
            await self.hub.broadcast({"type": "invalidate", "topics": topics, "last_seq": self.last_sent})

    async def mutate(self, fn):
        """Run a state-changing function under the lock, publish what changed, and map refusals to HTTP 409."""
        self.require()
        async with self.lock:
            try:
                result = fn()
            except Rejected as e:
                await self.publish()
                body = {"error": str(e), "kind": type(e).__name__}
                if getattr(e, "detail", None):
                    body["detail"] = e.detail            # e.g. "blocked by database capacity constraint"
                raise HTTPException(409, detail=body) from e
            await self.publish()
            return result
