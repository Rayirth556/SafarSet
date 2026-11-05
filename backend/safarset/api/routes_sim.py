"""Demo controls. NOT part of the product: every endpoint lives under /sim and drives the platform only through the same
events a real feed would produce (cancellation, delay, closure, ETM load reports, HHT no-shows)."""
import hashlib
import json

from fastapi import APIRouter, HTTPException, Request

from ..domain.loop import Approval, Handled
from ..sim.generator import generate
from ..sim.runner import play_step
from . import models, views

router = APIRouter(prefix="/sim", tags=["demo controls (not part of the product)"])


def _st(request: Request):
    return request.app.state.safar.require()


def _serialise(res):
    if isinstance(res, Handled):
        return {"seq": res.seq, "batch_id": res.batch_id}
    if isinstance(res, Approval):
        return {"batch_id": res.batch_id, "seq": res.seq, "confirmed_groups": len(res.confirmed_groups), "notified_groups": len(res.notified)}
    return {"batch_id": res}


async def _announce_reset(st):
    st.last_sent = st.conn.execute("SELECT MAX(seq) FROM events").fetchone()[0]
    await st.hub.broadcast(st.snapshot() | {"type": "reset"})


@router.post("/load-scenario")
async def load_scenario(request: Request, body: models.LoadScenarioBody):
    st = request.app.state.safar
    try:
        scenario = generate(body.seed, n_passengers=body.n_passengers, pct_senior=body.pct_senior, pct_groups=body.pct_groups,
                            compliance_rate=body.compliance_rate, walkon_rate=body.walkon_rate, pct_unreserved=body.pct_unreserved,
                            n_mtc_specials=body.n_mtc_specials, n_intercity_specials=body.n_intercity_specials,
                            cancel_time=body.cancel_time, exclude_trains=tuple(body.exclude_trains))
    except ValueError as e:
        raise HTTPException(422, detail={"error": str(e), "kind": "InvalidScenario"}) from e
    async with st.lock:
        st.reset(scenario)
        await _announce_reset(st)
    meta = scenario["meta"]
    return {"label": meta["label"], "params": meta["params"], "warnings": meta["warnings"], "cancelled_vehicle_id": meta["cancelled_vehicle_id"],
            "clock": views.hhmm(st.clock), "groups": len(scenario["groups"]), "heads": scenario["summary"]["heads"],
            "vehicles": len(scenario["vehicles"]), "timeline_steps": len(scenario["timeline"]["steps"])}


@router.post("/cancel-train")
async def cancel_train(request: Request, body: models.CancelBody | None = None):
    st = _st(request)
    body = body or models.CancelBody()
    vid = body.vehicle_id or st.scenario["meta"]["cancelled_vehicle_id"]
    res = await st.mutate(lambda: st.engine.handle("TRAIN_CANCELLED", "sim", {"vehicle_id": vid, "reason": body.reason}, st.clock))
    return _serialise(res)


@router.post("/delay-train")
async def delay_train(request: Request, body: models.DelayBody):
    st = _st(request)
    res = await st.mutate(lambda: st.engine.handle("TRAIN_DELAYED", "sim", {"vehicle_id": body.vehicle_id, "delay_min": body.delay_min}, st.clock))
    return _serialise(res)


@router.post("/close-road")
async def close_road(request: Request, body: models.CloseRoadBody):
    st = _st(request)
    res = await st.mutate(lambda: st.engine.handle("ROAD_CLOSED", "sim", {"route_id": body.route_id, "description": body.description}, st.clock))
    return _serialise(res)


def _timeline_step(st, n):
    return st.scenario["timeline"]["steps"][n]


@router.post("/inject-overcrowd")
async def inject_overcrowd(request: Request, body: models.InjectOvercrowdBody | None = None):
    """A conductor's ETM reports a bus overcrowded before boarding (defaults to the scripted step-4 vehicle and count)."""
    st = _st(request)
    body = body or models.InjectOvercrowdBody()
    scripted = _timeline_step(st, 3)["payload"]
    vid = body.vehicle_id or scripted["vehicle_id"]
    pool = scripted["pool_id"] if vid == scripted["vehicle_id"] else None
    if pool is None:
        r = st.conn.execute("SELECT pool_id FROM pools WHERE vehicle_id = ? AND kind = 'UNRESERVED' LIMIT 1", (vid,)).fetchone()
        if r is None:
            raise HTTPException(422, detail={"error": f"{vid} has no unreserved pool", "kind": "InvalidRequest"})
        pool = r["pool_id"]
    count = body.count if body.count is not None else (scripted["count"] if vid == scripted["vehicle_id"] else None)
    payload = {"vehicle_id": vid, "pool_id": pool, "level": "OVERCROWDED", "count": count, "reported_by": "SIMULATED conductor ETM"}
    return _serialise(await st.mutate(lambda: st.engine.handle("LOAD_REPORT", "field", payload, st.clock)))


@router.post("/inject-noshows")
async def inject_noshows(request: Request, body: models.InjectNoshowsBody | None = None):
    """A TTE's hand-held terminal reports no-shows: berths free up (defaults to the scripted step-5 train, pool and count)."""
    st = _st(request)
    body = body or models.InjectNoshowsBody()
    scripted = _timeline_step(st, 4)["payload"]
    vid = body.vehicle_id or scripted["vehicle_id"]
    pool = body.pool_id or (scripted["pool_id"] if vid == scripted["vehicle_id"] else None)
    if pool is None:
        r = st.conn.execute("SELECT pool_id FROM pools WHERE vehicle_id = ? AND kind = 'RESERVED' ORDER BY nominal DESC, pool_id LIMIT 1", (vid,)).fetchone()
        if r is None:
            raise HTTPException(422, detail={"error": f"{vid} has no reserved pool", "kind": "InvalidRequest"})
        pool = r["pool_id"]
    nseg = st.conn.execute("SELECT COUNT(*) FROM segment_capacity WHERE pool_id = ?", (pool,)).fetchone()[0]
    seats = body.seats or (scripted["seats_freed"] if pool == scripted["pool_id"] else 4)
    payload = {"vehicle_id": vid, "pool_id": pool, "seats_freed": seats, "from_seg": 0, "to_seg": nseg, "reported_by": "SIMULATED TTE HHT"}
    return _serialise(await st.mutate(lambda: st.engine.handle("NOSHOWS_REPORTED", "field", payload, st.clock)))


@router.get("/params")
async def get_params(request: Request):
    return _st(request).sim_params


@router.put("/params")
async def put_params(request: Request, body: models.SimParamsBody):
    st = _st(request)
    params = dict(st.sim_params, **{k: v for k, v in body.model_dump().items() if v is not None})

    def fn():
        res = st.engine.handle("SIM_PARAMS_CHANGED", "sim", {"params": params}, st.clock)
        st.sim_params = params
        return res
    await st.mutate(fn)
    return st.sim_params


@router.post("/clock")
async def set_clock(request: Request, body: models.ClockBody):
    st = _st(request)
    st.engine.clock = body.to_min
    await st.hub.broadcast({"type": "clock", "clock": views.hhmm(body.to_min), "clock_min": body.to_min})
    return {"clock": views.hhmm(body.to_min), "clock_min": body.to_min}


def _compliant(seed, group_id, rate):
    u = int(hashlib.sha256(f"{seed}:{group_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return u < rate


@router.post("/depart/{vehicle_id}")
async def depart(request: Request, vehicle_id: str):
    """Close the loop (plan -> observe -> re-plan) for one vehicle at departure, using the compliance and walk-on sliders.

    Confirmed groups that comply board; the rest ignored their allocation and are treated as no-shows (DISPLACED, so they
    are re-planned). Then the conductor's load report is derived: people already aboard + boarded heads + walk-ons
    (walk-on rate x nominal). SIMPLIFICATION: the ignorers are not modelled as boarding another vehicle."""
    st = _st(request)
    if st.conn.execute("SELECT 1 FROM vehicles WHERE vehicle_id = ?", (vehicle_id,)).fetchone() is None:
        raise HTTPException(404, detail={"error": f"unknown vehicle {vehicle_id}", "kind": "NotFound"})
    seed = st.scenario["meta"]["params"]["seed"]

    def fn():
        e, c = st.engine, st.conn
        boarded, ignored = [], []
        for a in c.execute("""SELECT a.id, a.group_id, a.size FROM allocations a JOIN pools p USING (pool_id)
                              WHERE p.vehicle_id = ? AND a.status = 'CONFIRMED' ORDER BY a.id""", (vehicle_id,)).fetchall():
            if _compliant(seed, a["group_id"], st.sim_params["compliance_rate"]):
                e.handle("PASSENGER_BOARDED", "field", {"allocation_id": a["id"]}, st.clock)
                boarded.append(a["group_id"])
            else:
                ignored.append(a)
        report = None
        pool = c.execute("SELECT * FROM pools WHERE vehicle_id = ? AND kind = 'UNRESERVED' ORDER BY pool_id LIMIT 1", (vehicle_id,)).fetchone()
        if pool:
            aboard = c.execute("SELECT COALESCE(SUM(a.size), 0) FROM allocations a WHERE a.pool_id = ? AND a.status = 'BOARDED'", (pool["pool_id"],)).fetchone()[0]
            committed = c.execute("SELECT MAX(committed_other) FROM segment_capacity WHERE pool_id = ?", (pool["pool_id"],)).fetchone()[0] or 0
            walkons = round(st.sim_params["walkon_rate"] * pool["nominal"])
            count = committed + aboard + walkons
            level = "OVERCROWDED" if count > pool["nominal"] else "FULL" if count == pool["nominal"] else "NORMAL"
            report = {"pool_id": pool["pool_id"], "level": level, "count": count, "walk_ons": walkons}
        for a in ignored:
            e.handle("PASSENGER_DISPLACED", "field", {"allocation_id": a["id"], "reason": "ignored the plan and did not board this vehicle"}, st.clock)
        batch = None
        if report:
            batch = e.handle("LOAD_REPORT", "field", {"vehicle_id": vehicle_id, "pool_id": report["pool_id"], "level": report["level"],
                                                       "count": report["count"], "reported_by": "SIMULATED conductor ETM (from sliders)"}, st.clock).batch_id
        return {"vehicle_id": vehicle_id, "boarded_groups": boarded, "ignored_plan_groups": [a["group_id"] for a in ignored],
                "load_report": report, "batch_id": batch, "params": dict(st.sim_params)}
    return await st.mutate(fn)


@router.get("/timeline")
async def timeline(request: Request):
    st = _st(request)
    steps = st.scenario["timeline"]["steps"]
    return {"label": "SIMULATED", "next_step": st.timeline_idx, "total": len(steps),
            "steps": [{k: s[k] for k in ("step", "at", "at_min", "kind", "type", "payload", "expect")} for s in steps]}


@router.post("/timeline/next")
async def timeline_next(request: Request):
    st = _st(request)
    steps = st.scenario["timeline"]["steps"]
    if st.timeline_idx >= len(steps):
        raise HTTPException(409, detail={"error": "the scripted timeline is finished; POST /sim/timeline/reset to replay", "kind": "TimelineDone"})
    step = steps[st.timeline_idx]
    st.engine.clock = step["at_min"]
    res = await st.mutate(lambda: play_step(st.engine, step))
    st.timeline_idx += 1
    return {"played": {k: step[k] for k in ("step", "at", "kind", "type")}, "result": _serialise(res), "next_step": st.timeline_idx}


@router.post("/timeline/reset")
async def timeline_reset(request: Request):
    st = _st(request)
    async with st.lock:
        st.reset(st.scenario)
        await _announce_reset(st)
    return {"next_step": 0}
