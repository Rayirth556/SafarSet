"""Operator dashboard endpoints (control room)."""
from fastapi import APIRouter, HTTPException, Query, Request

from ..domain import state as dstate
from ..events.queries import list_events
from . import models, views

router = APIRouter(prefix="/api", tags=["operator"])


def _st(request: Request):
    return request.app.state.safar.require()


def _ts(st, ts):
    return ts if ts is not None else st.clock


@router.get("/state")
async def get_state(request: Request):
    st = _st(request)
    return st.snapshot() | {"type": "state"}


@router.get("/notifier")
async def get_notifier(request: Request):
    """Which notification backends are live: the phone mock always; real SMS only when enabled by the environment flag."""
    return request.app.state.safar.notifier.status() if hasattr(request.app.state.safar.notifier, "status") else {"phone_mock": True}


@router.get("/kpis")
async def get_kpis(request: Request):
    return views.kpis(_st(request).conn)


@router.get("/capacity")
async def get_capacity(request: Request, role: str = Query("ALLOCATION", pattern="^(ALLOCATION|TRANSFER_LEG|all)$")):
    return views.capacity(_st(request).conn, role)


@router.get("/passengers")
async def get_passengers(request: Request, status: str | None = None, dest: str | None = None, q: str | None = None,
                         limit: int = Query(500, ge=1, le=5000), offset: int = Query(0, ge=0)):
    st = _st(request)
    return views.passengers(st.conn, st.clock, status=status, dest=dest, q=q, limit=limit, offset=offset)


@router.get("/passengers/{group_id}/why")
async def get_why(request: Request, group_id: str):
    st = _st(request)
    out = views.why(st.conn, st.clock, group_id)
    if out is None:
        raise HTTPException(404, detail={"error": f"unknown group {group_id}", "kind": "NotFound"})
    return out


@router.get("/unresolved")
async def get_unresolved(request: Request):
    st = _st(request)
    return views.unresolved(st.conn, st.clock)


@router.get("/batches")
async def get_batches(request: Request):
    return views.batches(_st(request).conn)


@router.get("/batches/pending")
async def get_pending(request: Request):
    return views.pending_batch(_st(request).conn)


@router.get("/batches/{batch_id}")
async def get_batch(request: Request, batch_id: str):
    out = views.batch(_st(request).conn, batch_id)
    if out is None:
        raise HTTPException(404, detail={"error": f"unknown batch {batch_id}", "kind": "NotFound"})
    return out


@router.get("/batches/{batch_id}/preview")
async def preview_batch(request: Request, batch_id: str, kind: str | None = Query(None, pattern="^(NEW|CHANGED|DISPLACED_UNPLACED)$"),
                        lang: str | None = Query(None, pattern="^(en|ta)$"), vehicle_id: str | None = None):
    """What approving this batch would send (counts, and the real text for one example, optionally for one vehicle), without sending anything."""
    st = _st(request)
    if views.batch(st.conn, batch_id, with_items=False) is None:
        raise HTTPException(404, detail={"error": f"unknown batch {batch_id}", "kind": "NotFound"})
    return st.engine.preview_messages(batch_id, kind, lang, vehicle_id)


@router.post("/batches/{batch_id}/approve")
async def approve(request: Request, batch_id: str, body: models.ApproveBody | None = None):
    st = _st(request)
    res = await st.mutate(lambda: st.engine.approve(batch_id, _ts(st, body.ts_sim if body else None)))
    return {"batch_id": res.batch_id, "seq": res.seq, "confirmed_groups": len(res.confirmed_groups), "notified_groups": len(res.notified)}


@router.post("/replan")
async def replan(request: Request, body: models.ReplanBody | None = None):
    body = body or models.ReplanBody()
    st = _st(request)
    ts = _ts(st, body.ts_sim)
    if body.weights is not None:
        current = dstate.current_weights(st.conn)
        unknown = set(body.weights) - set(current)
        if unknown or set(current) - set(body.weights):
            raise HTTPException(422, detail={"error": f"weights must have exactly these keys: {sorted(current)}", "kind": "InvalidWeights"})
        bid = await st.mutate(lambda: st.engine.adjust_weights_and_rerun(body.weights, ts))
    else:
        bid = await st.mutate(lambda: st.engine.replan(ts, fresh=body.fresh, force=True, cause="MANUAL_REPLAN"))
    return {"batch_id": bid, "cause": "WEIGHTS_RERUN" if body.weights is not None else "MANUAL_REPLAN"}


@router.get("/rules")
async def get_rules(request: Request):
    return views.rules(_st(request).conn)


@router.get("/priority-policy")
async def get_priority_policy(request: Request):
    from ..scoring.policy import load_priority_policy
    return load_priority_policy().model_dump()


@router.put("/priority-policy")
async def put_priority_policy(request: Request, body: dict):
    from ..scoring.policy import PriorityPolicy, get_default_policy_path, load_priority_policy
    st = _st(request)
    ts = _ts(st, body.get("ts_sim"))
    try:
        policy_data = body.get("policy", body)
        updated_policy = PriorityPolicy.model_validate(policy_data)
    except Exception as e:
        raise HTTPException(422, detail={"error": str(e), "kind": "InvalidPolicy"}) from e

    path = get_default_policy_path()
    path.write_text(json.dumps(updated_policy.model_dump(), indent=2), encoding="utf-8")
    load_priority_policy(reload=True)

    bid = await st.mutate(lambda: st.engine.replan(ts, fresh=True, force=True, cause="POLICY_SIMULATION"))
    return {"status": "ok", "batch_id": bid, "policy": updated_policy.model_dump()}


@router.put("/rules")
async def put_rules(request: Request, body: models.RulesBody):
    st = _st(request)
    ts = _ts(st, body.ts_sim)
    if body.weights is not None:
        current = dstate.current_weights(st.conn)
        if set(body.weights) != set(current):
            raise HTTPException(422, detail={"error": f"weights must have exactly these keys: {sorted(current)}", "kind": "InvalidWeights"})
        await st.mutate(lambda: st.engine.handle("WEIGHTS_CHANGED", "operator", {"weights": body.weights}, ts))
    for mode, pct in (body.buffers or {}).items():
        await st.mutate(lambda m=mode, p=pct: st.engine.handle("BUFFER_CHANGED", "operator", {"mode": m, "buffer_pct": p}, ts))
    return views.rules(st.conn)


@router.get("/events")
async def get_events(request: Request, after: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=2000), hide_rejected: bool = True,
                     tail: bool = False):
    from .state import public_event
    st = _st(request)
    rows = list_events(st.conn, after_seq=after, limit=limit, hide_rejected=hide_rejected, tail=tail)
    out = []
    for e in rows:
        r = st.conn.execute("SELECT * FROM events WHERE seq = ?", (e["seq"],)).fetchone()
        out.append(public_event(r))
    return {"hide_rejected": hide_rejected, "last_seq": st.last_sent, "events": out}


@router.post("/groups/{group_id}/override")
async def override(request: Request, group_id: str, body: models.OverrideBody):
    st = _st(request)
    ts = _ts(st, body.ts_sim)
    res = await st.mutate(lambda: st.engine.override(group_id, body.action, body.reason, pool_id=body.pool_id, board_idx=body.board_idx,
                                                    alight_idx=body.alight_idx, ts_sim=ts))
    return {"seq": res.seq, "batch_id": res.batch_id}


@router.post("/groups/{group_id}/verify")
async def verify_group(request: Request, group_id: str, body: models.VerifyGroupBody):
    st = _st(request)
    ts = _ts(st, body.ts_sim)

    def fn():
        g = st.conn.execute("SELECT attrs FROM groups WHERE group_id = ?", (group_id,)).fetchone()
        if not g:
            raise HTTPException(404, detail={"error": f"group {group_id} not found", "kind": "NotFound"})
        attrs = json.loads(g["attrs"])
        if body.verification_type == "CRITICAL_EMERGENCY":
            attrs["medical_emergency"] = body.verified
            attrs["verified_critical"] = body.verified
            attrs["critical_verification_reason"] = body.reason
        elif body.verification_type == "COMPANIONS":
            attrs["companion_verified"] = body.verified
            attrs["companion_verification_reason"] = body.reason
        st.conn.execute("UPDATE groups SET attrs = ? WHERE group_id = ?", (json.dumps(attrs, sort_keys=True, ensure_ascii=False), group_id))
        bid = st.engine.replan(ts, fresh=True, force=True, cause="OPERATOR_OVERRIDE")
        return {"group_id": group_id, "verified": body.verified, "batch_id": bid}

    return await st.mutate(fn)
