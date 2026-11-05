"""Field view endpoints (conductor / TTE on a phone). These stand in for the ETM and HHT feeds."""
from fastapi import APIRouter, HTTPException, Request

from . import models, views

router = APIRouter(prefix="/api/field", tags=["field"])


def _st(request: Request):
    return request.app.state.safar.require()


def _vehicle(st, vehicle_id):
    if st.conn.execute("SELECT 1 FROM vehicles WHERE vehicle_id = ?", (vehicle_id,)).fetchone() is None:
        raise HTTPException(404, detail={"error": f"unknown vehicle {vehicle_id}", "kind": "NotFound"})


@router.get("/vehicles")
async def vehicles(request: Request):
    return views.field_vehicles(_st(request).conn)


@router.get("/vehicles/{vehicle_id}/manifest")
async def manifest(request: Request, vehicle_id: str):
    st = _st(request)
    _vehicle(st, vehicle_id)
    return views.manifest(st.conn, vehicle_id)


@router.post("/vehicles/{vehicle_id}/board")
async def board(request: Request, vehicle_id: str, body: models.BoardBody):
    st = _st(request)
    _vehicle(st, vehicle_id)
    aid = body.allocation_id
    if aid is None and body.group_id:
        r = st.conn.execute("""SELECT a.id FROM allocations a JOIN pools p USING (pool_id) WHERE p.vehicle_id = ? AND a.group_id = ?
                               AND a.status IN ('TENTATIVE','CONFIRMED','BOARDED')""", (vehicle_id, body.group_id)).fetchone()
        aid = r["id"] if r else None
    if aid is None:
        raise HTTPException(422, detail={"error": "give allocation_id, or a group_id that has a seat on this vehicle", "kind": "InvalidRequest"})
    ts = body.ts_sim if body.ts_sim is not None else st.clock
    res = await st.mutate(lambda: st.engine.handle("PASSENGER_BOARDED", "field", {"allocation_id": aid}, ts))
    return {"seq": res.seq, "allocation_id": aid}


@router.post("/vehicles/{vehicle_id}/load-report")
async def load_report(request: Request, vehicle_id: str, body: models.LoadReportBody):
    st = _st(request)
    _vehicle(st, vehicle_id)
    pool = body.pool_id
    if pool is None:
        r = st.conn.execute("SELECT pool_id FROM pools WHERE vehicle_id = ? AND kind = 'UNRESERVED' ORDER BY pool_id LIMIT 1", (vehicle_id,)).fetchone()
        if r is None:
            raise HTTPException(422, detail={"error": "this vehicle has no unreserved pool; pass pool_id", "kind": "InvalidRequest"})
        pool = r["pool_id"]
    ts = body.ts_sim if body.ts_sim is not None else st.clock
    payload = {"vehicle_id": vehicle_id, "pool_id": pool, "level": body.level, "count": body.count, "reported_by": "field view"}
    res = await st.mutate(lambda: st.engine.handle("LOAD_REPORT", "field", payload, ts))
    return {"seq": res.seq, "pool_id": pool, "batch_id": res.batch_id}


@router.post("/vehicles/{vehicle_id}/vacancy")
async def vacancy(request: Request, vehicle_id: str, body: models.VacancyBody):
    st = _st(request)
    _vehicle(st, vehicle_id)
    ts = body.ts_sim if body.ts_sim is not None else st.clock
    payload = {"pool_id": body.pool_id, "from_seg": body.from_seg, "to_seg": body.to_seg, "vacancy": body.vacancy, "reported_by": "field view (HHT)"}
    res = await st.mutate(lambda: st.engine.handle("VACANCY_UPDATE", "field", payload, ts))
    return {"seq": res.seq, "batch_id": res.batch_id}
