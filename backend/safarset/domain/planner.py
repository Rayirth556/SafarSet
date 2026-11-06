"""Glue between the database and the pure allocator."""
import json

from ..events.apply import apply_event
from ..scoring import priority, stub
from . import state
from .allocator import allocate


def propose_plan(conn, now_min, *, scorer=None, config=None, weights=None, fresh=False):
    """Compute (not apply) a plan for every affected group that holds no CONFIRMED/BOARDED seat.

    Default (event-triggered re-plan): existing TENTATIVE placements are kept unless invalid or moved by the bounded
    reshuffle (stability rule). fresh=True ("adjust weights and re-run"): ignore tentative placements and plan from
    scratch; operator overrides are still kept."""
    vehicles, free = state.load_vehicles(conn)
    rank = json.loads(conn.execute("SELECT value FROM settings WHERE key = 'class_rank'").fetchone()["value"])
    pins = state.load_pins(conn)
    if fresh:
        pins = {g: p for g, p in pins.items() if p["override"]}
    cur_weights = weights or state.current_weights(conn)
    active_scorer = scorer
    if active_scorer is None:
        if cur_weights and any(k in cur_weights for k in ("senior_60_plus", "medical_disability")):
            active_scorer = stub.score
        else:
            active_scorer = priority.score
    plan = allocate(state.load_pending_groups(conn), vehicles, free,
                    scorer=active_scorer, weights=cur_weights,
                    rank_map={c: i for i, c in enumerate(rank)}, connections=state.load_connections(conn),
                    now_min=now_min, config=config or state.load_config(), pinned=pins, held=state.load_held(conn))
    return plan


def submit_plan(conn, plan, batch_id, *, ts_sim=None, actor="system", cause="REPLAN"):
    """Turn a plan into a PLAN_PROPOSED event (the DB re-validates every seat)."""
    if hasattr(plan, "escalations") and plan.escalations:
        for esc in plan.escalations:
            row = conn.execute("SELECT attrs FROM groups WHERE group_id = ?", (esc["group_id"],)).fetchone()
            if row:
                attrs = json.loads(row["attrs"])
                if not attrs.get("escalated"):
                    apply_event(conn, "PASSENGER_ESCALATED", actor, esc, ts_sim=ts_sim)
    base = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]
    return apply_event(conn, "PLAN_PROPOSED", actor, plan.to_payload(batch_id, base, cause), ts_sim=ts_sim)
