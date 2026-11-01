"""WebSocket broadcast hub: pushes pipeline events to the floating UI."""
from __future__ import annotations

import logging

from fastapi import WebSocket

log = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, event: dict) -> None:
        for ws in list(self._clients):
            try:
                await ws.send_json(event)
            except Exception:
                log.debug("Dropping dead websocket client")
                self._clients.discard(ws)
