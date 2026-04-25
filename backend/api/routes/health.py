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
    event_logger_overflow: dict = {}
    event_logger_queue_depth = 0
    if hasattr(app.state, "event_logger"):
        el = app.state.event_logger
        event_logger_drops = el.get_drop_counts()
        event_logger_overflow = el.get_overflow_counts()
        event_logger_queue_depth = el.get_queue_depth()

    # Background-task heartbeats. Each long-running poll loop publishes
    # last_tick via HeartbeatRegistry; a task is "stale" if its age
    # exceeds 2x its expected interval. /health stays HTTP 200 even when
    # degraded so external probes (Uptime Kuma) keep working — the
    # status field is the signal to act on.
    tasks: list[dict] = []
    tasks_stale: list[str] = []
    status = "healthy"
    if hasattr(app.state, "heartbeats"):
        tasks = app.state.heartbeats.snapshot()
        tasks_stale = [t["name"] for t in tasks if t["stale"]]
        if tasks_stale:
            status = "degraded"

    # Circuit breakers protecting calls into Hue / Sonos. When a breaker
    # is open, calls fail fast (raising CircuitBreakerOpen) instead of
    # wedging on a slow bridge — the heartbeat surface above tells you
    # the loop is still ticking, this surface tells you why it's failing.
    circuit_breakers: dict = {}
    if hasattr(app.state, "hue") and hasattr(app.state.hue, "breaker"):
        circuit_breakers["hue"] = app.state.hue.breaker.snapshot()
    if hasattr(app.state, "sonos") and hasattr(app.state.sonos, "breaker"):
        circuit_breakers["sonos"] = app.state.sonos.breaker.snapshot()
    if any(b.get("state") == "open" for b in circuit_breakers.values()):
        status = "degraded"

    return {
        "status": status,
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
        "event_logger_overflow": event_logger_overflow,
        "event_logger_queue_depth": event_logger_queue_depth,
        "tasks": tasks,
        "tasks_stale": tasks_stale,
        "circuit_breakers": circuit_breakers,
    }
