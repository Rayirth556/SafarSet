"""Passenger phone mock: the messages the notifier has sent to one group (keyed by PNR, or by group id for unreserved)."""
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from . import views

router = APIRouter(tags=["phone"])


@router.get("/api/phone/{key}/messages")
async def messages(request: Request, key: str):
    st = request.app.state.safar.require()
    out = views.phone_messages(st.conn, key)
    if out is None:
        raise HTTPException(404, detail={"error": f"no passenger with PNR or group id {key}", "kind": "NotFound"})
    return out


@router.websocket("/ws/phone/{key}")
async def phone_ws(ws: WebSocket, key: str):
    st = ws.app.state.safar
    await st.hub.connect_phone(key, ws)
    try:
        out = views.phone_messages(st.conn, key) if st.loaded else None
        await ws.send_json({"type": "history", "found": out is not None, **(out or {"messages": []})})
        while True:
            await ws.receive_text()          # phones only listen; this keeps the socket open and notices disconnects
    except WebSocketDisconnect:
        st.hub.disconnect_phone(key, ws)
