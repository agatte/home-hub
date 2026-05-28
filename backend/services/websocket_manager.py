"""
WebSocket connection manager — broadcasts state changes to all connected clients.
"""
import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import WebSocket

logger = logging.getLogger("home_hub.websocket")

# Per-client send timeout. A stalled client (mobile on bad wifi, paused tab)
# used to hold the whole broadcast loop on its TCP send. Beyond this budget
# we drop the client rather than starve everyone else.
SEND_TIMEOUT_SECONDS = 2.0


class WebSocketManager:
    """Manages WebSocket connections and broadcasts messages to all clients."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self._connections.add(websocket)
        logger.info(f"Client connected. Total connections: {len(self._connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        self._connections.discard(websocket)
        logger.info(f"Client disconnected. Total connections: {len(self._connections)}")

    async def broadcast(self, message_type: str, data: Any) -> None:
        """
        Broadcast a message to all connected clients in parallel.

        A slow client only stalls its own send (bounded by SEND_TIMEOUT_SECONDS);
        all other clients receive the message without head-of-line blocking.

        Args:
            message_type: Event type (e.g., "light_update", "sonos_update").
            data: Payload to send.
        """
        if not self._connections:
            return

        payload = json.dumps({"type": message_type, "data": data})
        targets = list(self._connections)

        async def _send_one(ws: WebSocket) -> Optional[WebSocket]:
            try:
                await asyncio.wait_for(ws.send_text(payload), timeout=SEND_TIMEOUT_SECONDS)
                return None
            except Exception:
                return ws

        # return_exceptions=True forward-safety: _send_one already catches
        # everything internally and returns either None (ok) or the failing
        # WebSocket. If a future change introduces an unhandled raise inside
        # _send_one, return_exceptions=False would short-circuit the whole
        # gather and drop the broadcast for every other still-pending client.
        # The True variant lets every other client finish; we treat any
        # leaked exception as a failed send and disconnect that client.
        results = await asyncio.gather(
            *(_send_one(ws) for ws in targets), return_exceptions=True
        )
        for ws, result in zip(targets, results):
            if isinstance(result, BaseException) or result is not None:
                failed = result if isinstance(result, WebSocket) else ws
                self.disconnect(failed)

    @property
    def connection_count(self) -> int:
        """Number of active connections."""
        return len(self._connections)
