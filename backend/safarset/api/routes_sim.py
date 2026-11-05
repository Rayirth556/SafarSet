"""Demo controls. NOT part of the product: every endpoint lives under /sim and drives the platform only through the same
events a real feed would produce (cancellation, delay, closure, ETM load reports, second-chart vacancies from the TTE hand-held terminal)."""
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


def _timeline_step(st, type_):
    """The scripted step of this event type (the demo controls default to what the script does)."""
    return next(s for s in st.scenario["timeline"]["steps"] if s["type"] == type_)


@router.post("/inject-overcrowd")
async def inject_overcrowd(request: Request, body: models.InjectOvercrowdBody | None = None):
    """A conductor's ETM reports a bus overcrowded before boarding (defaults to the scripted step-4 vehicle and count)."""
    st = _st(request)
    body = body or models.InjectOvercrowdBody()
    scripted = _timeline_step(st, "LOAD_REPORT")["payload"]
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


@router.post("/deploy-bus")
async def deploy_bus(request: Request):
    """The depot sends an extra special on the overcrowded bus's route: the scripted step-4 vehicle, with its scripted timing."""
    st = _st(request)
    step = _timeline_step(st, "VEHICLE_DEPLOYED")
    return _serialise(await st.mutate(lambda: st.engine.handle("VEHICLE_DEPLOYED", "sim", step["payload"], st.clock)))


@router.post("/inject-vacancies")
@router.post("/inject-noshows", deprecated=True)
async def inject_vacancies(request: Request, body: models.InjectVacanciesBody | None = None):
    """Second-chart vacancies: the railway's final chart (prepared about 30 min before departure) shows berths that are now
    vacant, reported through the TTE hand-held terminal. Defaults to the scripted step-5 train, pool and count.
    (`/inject-noshows` is the old name of this endpoint. The event type stays NOSHOWS_REPORTED.)"""
    st = _st(request)
    body = body or models.InjectVacanciesBody()
    scripted = _timeline_step(st, "NOSHOWS_REPORTED")["payload"]
    vid = body.vehicle_id or scripted["vehicle_id"]
    pool = body.pool_id or (scripted["pool_id"] if vid == scripted["vehicle_id"] else None)
    if pool is None:
        r = st.conn.execute("SELECT pool_id FROM pools WHERE vehicle_id = ? AND kind = 'RESERVED' ORDER BY nominal DESC, pool_id LIMIT 1", (vid,)).fetchone()
        if r is None:
            raise HTTPException(422, detail={"error": f"{vid} has no reserved pool", "kind": "InvalidRequest"})
        pool = r["pool_id"]
    nseg = st.conn.execute("SELECT COUNT(*) FROM segment_capacity WHERE pool_id = ?", (pool,)).fetchone()[0]
    seats = body.seats or (scripted["seats_freed"] if pool == scripted["pool_id"] else 4)
    payload = {"vehicle_id": vid, "pool_id": pool, "seats_freed": seats, "from_seg": 0, "to_seg": nseg, "reported_by": "SIMULATED second chart (TTE hand-held terminal)"}
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
    """Move the demo clock. Logged as a CLOCK_SET event so replay and restarts see the same clock."""
    st = _st(request)
    await st.mutate(lambda: st.engine.handle("CLOCK_SET", "sim", {"to_min": body.to_min}, body.to_min))
    return {"clock": views.hhmm(body.to_min), "clock_min": body.to_min}


def _compliant(seed, group_id, rate):
    u = int(hashlib.sha256(f"{seed}:{group_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return u < rate


@router.post("/depart/{vehicle_id}")
async def depart(request: Request, vehicle_id: str):
    """Close the loop (plan -> observe -> re-plan) for one vehicle at departure, using the compliance and walk-on sliders.

    1. Ignorers (confirmed groups, deterministic per seed, that do not follow their allocation) board the EARLIEST-departing
       vehicle toward their destination that has not left yet. When that is this vehicle they RUSH it.
    2. Rushers and walk-ons (walk-on rate x nominal) are already in the vehicle; allocated passengers then board in priority
       order while there is physical room. Whoever does not fit is refused at the door.
    3. The conductor's load report counts everyone present (aboard before + rushers + walk-ons + all allocated heads). When
       it exceeds the seats the report is OVERCROWDED and the refused groups are DISPLACED and re-planned.
    Rushers are not lost: they become BOARDED (on this vehicle, no seat recorded) and their old allocation is released."""
    st = _st(request)
    row = st.conn.execute("SELECT * FROM vehicles WHERE vehicle_id = ?", (vehicle_id,)).fetchone()
    if row is None:
        raise HTTPException(404, detail={"error": f"unknown vehicle {vehicle_id}", "kind": "NotFound"})
    seed = st.scenario["meta"]["params"]["seed"]

    def fn():
        e, c = st.engine, st.conn
        pool = c.execute("SELECT * FROM pools WHERE vehicle_id = ? AND kind = 'UNRESERVED' ORDER BY pool_id LIMIT 1", (vehicle_id,)).fetchone()
        mine = c.execute("""SELECT a.id, a.group_id, a.size FROM allocations a JOIN pools p USING (pool_id)
                            WHERE p.vehicle_id = ? AND a.status = 'CONFIRMED' ORDER BY a.score DESC, a.id""", (vehicle_id,)).fetchall()
        rushers = []
        if pool is not None and row["status"] == "SCHEDULED":
            served = {pl for r in c.execute("SELECT serves_places FROM vehicle_stops WHERE vehicle_id = ? AND seq > 0", (vehicle_id,))
                      for pl in json.loads(r["serves_places"])}
            depart_eff = row["depart_min"] + row["delay_min"]
            for g in c.execute("""SELECT a.group_id, a.size, g.dest_place FROM allocations a JOIN pools p USING (pool_id)
                                  JOIN vehicles v ON v.vehicle_id = p.vehicle_id JOIN groups g USING (group_id)
                                  WHERE a.status = 'CONFIRMED' AND p.vehicle_id <> ? AND v.depart_min + v.delay_min >= ?
                                  ORDER BY a.id""", (vehicle_id, depart_eff)):
                if g["dest_place"] in served and not _compliant(seed, g["group_id"], st.sim_params["compliance_rate"]):
                    rushers.append(g)
        committed = (c.execute("SELECT MAX(committed_other) FROM segment_capacity WHERE pool_id = ?", (pool["pool_id"],)).fetchone()[0] or 0) if pool else 0
        walk_ons = round(st.sim_params["walkon_rate"] * pool["nominal"]) if pool else 0
        rush_heads = sum(g["size"] for g in rushers)
        room = max(0, pool["nominal"] - (committed + rush_heads + walk_ons)) if pool else 10 ** 9
        boarded, refused = [], []
        for a in mine:
            if a["size"] <= room:
                e.handle("PASSENGER_BOARDED", "field", {"allocation_id": a["id"]}, st.clock)
                room -= a["size"]
                boarded.append(a["group_id"])
            else:
                refused.append(a["group_id"])
        for g in rushers:
            e.handle("GROUP_SELF_BOARDED", "field", {"group_id": g["group_id"], "vehicle_id": vehicle_id,
                                                      "reason": "ignored the plan and boarded the earliest vehicle toward the destination"}, st.clock)
        report, batch = None, None
        if pool:
            present = committed + rush_heads + walk_ons + sum(a["size"] for a in mine)
            level = "OVERCROWDED" if present > pool["nominal"] else "FULL" if present == pool["nominal"] else "NORMAL"
            report = {"pool_id": pool["pool_id"], "level": level, "count": present, "nominal": pool["nominal"], "committed": committed,
                      "walk_ons": walk_ons, "rushers_heads": rush_heads, "allocated_heads": sum(a["size"] for a in mine)}
            batch = e.handle("LOAD_REPORT", "field", {"vehicle_id": vehicle_id, "pool_id": pool["pool_id"], "level": level, "count": present,
                                                       "reported_by": "SIMULATED conductor ETM (from sliders)"}, st.clock).batch_id
        return {"vehicle_id": vehicle_id, "boarded_groups": boarded, "refused_groups": refused, "rusher_groups": [g["group_id"] for g in rushers],
                "load_report": report, "batch_id": batch, "params": dict(st.sim_params)}
    return await st.mutate(fn)


@router.get("/timeline")
async def timeline(request: Request):
    st = _st(request)
    steps = st.scenario["timeline"]["steps"]
    return {"label": "SIMULATED", "next_step": st.timeline_idx, "total": len(steps),
            "steps": [{k: s[k] for k in ("step", "label", "at", "at_min", "kind", "type", "payload", "expect")} for s in steps]}


@router.post("/timeline/next")
async def timeline_next(request: Request):
    st = _st(request)
    steps = st.scenario["timeline"]["steps"]
    if st.timeline_idx >= len(steps):
        raise HTTPException(409, detail={"error": "the scripted timeline is finished; POST /sim/timeline/reset to replay", "kind": "TimelineDone"})
    step = steps[st.timeline_idx]

    def run():
        if st.engine.clock != step["at_min"]:
            st.engine.handle("CLOCK_SET", "sim", {"to_min": step["at_min"]}, step["at_min"])
        return play_step(st.engine, step)
    res = await st.mutate(run)
    st.timeline_idx += 1
    return {"played": {k: step[k] for k in ("step", "label", "at", "kind", "type")}, "result": _serialise(res), "next_step": st.timeline_idx}


@router.post("/timeline/reset")
async def timeline_reset(request: Request):
    st = _st(request)
    async with st.lock:
        st.reset(st.scenario)
        await _announce_reset(st)
    return {"next_step": 0}
