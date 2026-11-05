"""WebSocket fan-out. All UIs share one stream (`/ws`); each phone mock has its own (`/ws/phone/{key}`)."""
from fastapi import WebSocket


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.phones: dict[str, set[WebSocket]] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, msg):
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:
                self.clients.discard(ws)

    async def connect_phone(self, key: str, ws: WebSocket):
        await ws.accept()
        self.phones.setdefault(key, set()).add(ws)

    def disconnect_phone(self, key: str, ws: WebSocket):
        self.phones.get(key, set()).discard(ws)

    async def send_phone(self, keys, msg):
        for key in keys:
            for ws in list(self.phones.get(key, ())):
                try:
                    await ws.send_json(msg)
                except Exception:
                    self.phones[key].discard(ws)
