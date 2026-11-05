"""FastAPI application. Run:  uvicorn safarset.api.app:app --reload   (from the backend/ directory)

Surfaces: /api/*  operator dashboard + field view + phone mock;  /sim/*  demo controls (not part of the product);
/ws  live stream for every UI;  /ws/phone/{pnr}  one phone's messages.  OpenAPI docs at /docs.
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import routes_field, routes_operator, routes_phone, routes_sim
from .state import AppState


def create_app(notifier=None):
    app = FastAPI(title="SafarSet", version="0.6.0",
                  description="Dynamic travel recovery and passenger coordination. All data in the demo is SIMULATED unless a field says REAL.")
    app.state.safar = AppState(notifier)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ValueError)
    async def value_error(_, exc):
        return JSONResponse(status_code=422, content={"detail": {"error": str(exc), "kind": "InvalidRequest"}})

    @app.exception_handler(RequestValidationError)
    async def bad_request(_, exc):
        fields = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
        text = "; ".join(f"{f['field']}: {f['message']}" for f in fields)
        return JSONResponse(status_code=422, content={"detail": {"error": text, "kind": "InvalidRequest", "fields": fields}})

    @app.get("/health", tags=["meta"])
    async def health():
        st = app.state.safar
        return {"ok": True, "scenario_loaded": st.loaded, "clients": len(st.hub.clients)}

    @app.websocket("/ws")
    async def stream(ws: WebSocket):
        st = ws.app.state.safar
        await st.hub.connect(ws)
        try:
            await ws.send_json(st.snapshot())
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong", "last_seq": st.last_sent})
                elif msg.get("type") == "snapshot":
                    await ws.send_json(st.snapshot())
        except WebSocketDisconnect:
            st.hub.disconnect(ws)

    for r in (routes_operator.router, routes_field.router, routes_phone.router, routes_sim.router):
        app.include_router(r)
    return app


app = create_app()
