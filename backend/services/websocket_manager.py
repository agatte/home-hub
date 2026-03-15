"""
WebSocket connection manager — broadcasts state changes to all connected clients.
"""
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("home_hub.websocket")


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
        Broadcast a message to all connected clients.

        Args:
            message_type: Event type (e.g., "light_update", "sonos_update").
            data: Payload to send.
        """
        if not self._connections:
            return

        payload = json.dumps({"type": message_type, "data": data})
        disconnected: list[WebSocket] = []

        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        """Number of active connections."""
        return len(self._connections)
