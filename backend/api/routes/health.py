"""
Health check endpoint.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health_check(request: Request) -> dict:
    """
    Returns service status for all connected devices.

    Useful for monitoring and debugging connectivity issues.
    """
    app = request.app

    hue_connected = False
    sonos_connected = False

    if hasattr(app.state, "hue"):
        hue_connected = app.state.hue.connected

    if hasattr(app.state, "sonos"):
        sonos_connected = app.state.sonos.connected

    pihole_connected = False
    if hasattr(app.state, "pihole_service"):
        pihole_connected = app.state.pihole_service.connected

    fauxmo_connected = False
    if hasattr(app.state, "fauxmo"):
        fauxmo_connected = app.state.fauxmo.connected

    ws_count = 0
    if hasattr(app.state, "ws_manager"):
        ws_count = app.state.ws_manager.connection_count

    event_logger_drops: dict = {}
    if hasattr(app.state, "event_logger"):
        event_logger_drops = app.state.event_logger.get_drop_counts()

    return {
        "status": "healthy",
        "service": "Home Hub",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "devices": {
            "hue_bridge": hue_connected,
            "sonos": sonos_connected,
            "pihole": pihole_connected,
            "fauxmo": fauxmo_connected,
        },
        "websocket_clients": ws_count,
        "event_logger_drops": event_logger_drops,
    }
