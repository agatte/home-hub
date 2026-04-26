"""
Home Hub — FastAPI application.

Single backend that controls Hue lights, Sonos speaker, runs automation engine,
and serves the React frontend.

Startup / shutdown logic lives in ``backend.bootstrap`` — this module
focuses on app construction, middleware, and routing only.
"""
import json
import logging
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.api.routes.automation import router as automation_router
from backend.api.routes.health import router as health_router
from backend.api.routes.lights import router as lights_router
from backend.api.routes.music import router as music_router
from backend.api.routes.routines import router as routines_router
from backend.api.routes.scenes import router as scenes_router
from backend.api.routes.sonos import router as sonos_router
from backend.api.routes.plants import router as plants_router
from backend.api.routes.bar import router as bar_router
from backend.api.routes.events import router as events_router
from backend.api.routes.rules import router as rules_router
from backend.api.routes.pihole import router as pihole_router
from backend.api.routes.weather import router as weather_router
from backend.api.routes.ambient import router as ambient_router
from backend.api.routes.learning import router as learning_router
from backend.api.routes.camera import router as camera_router
from backend.api.routes.debug import router as debug_router
from backend.api.routes.pihole_proxy import router as pihole_proxy_router
from backend.bootstrap import lifespan
from backend.config import PROJECT_ROOT, STATIC_DIR, TTS_DIR, settings

FRONTEND_DIST = PROJECT_ROOT / settings.FRONTEND_BUILD
from backend.schemas.ws import (
    LightCommand,
    LightCommandData,
    SonosCommand,
    SonosCommandData,
    WSCommand,
)
from backend.services.hue_service import HueService
from backend.services.sonos_service import SonosService
from backend.services.tracing import (
    coerce_inbound_id,
    new_request_id,
    request_id_var,
)
from backend.services.websocket_manager import WebSocketManager

app_logger = logging.getLogger("home_hub.main")

# Pre-built adapter for the discriminated WS-command union — caching the
# TypeAdapter avoids rebuilding validation machinery on every frame.
_WS_COMMAND_ADAPTER: TypeAdapter[WSCommand] = TypeAdapter(WSCommand)


# Rate limiter — prevents abuse from rogue LAN clients
from backend.rate_limit import limiter  # noqa: E402 — after route imports to avoid circular

app = FastAPI(
    title="Home Hub",
    description="Unified home automation dashboard — Hue lights, Sonos, smart automation.",
    version="2.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow frontend dev server, kiosk, and local network clients
_CORS_ORIGINS = [
    "http://localhost:8000",
    "http://localhost:3001",
    "http://127.0.0.1:8000",
    "http://192.168.1.210:8000",   # Latitude kiosk (production)
    "http://192.168.1.30:8000",    # Windows dev machine
    "http://192.168.1.30:3001",    # Vite dev server
    "http://192.168.1.209:8000",   # Android tablet
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request, call_next):
    """
    Stamp every HTTP request with a correlation ID.

    Trusts an inbound X-Request-ID if it looks sane (printable, no
    whitespace, ≤64 chars); otherwise generates a fresh one. The ID
    rides into a ContextVar that the logging filter reads, and back
    out as a response header so callers can correlate end-to-end.
    """
    rid = coerce_inbound_id(request.headers.get("X-Request-ID"))
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        request_id_var.reset(token)


# Mount static files (TTS audio, ambient sounds, frontend build)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TTS_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "ambient").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Routes
app.include_router(health_router)
app.include_router(lights_router)
app.include_router(scenes_router)
app.include_router(sonos_router)
app.include_router(automation_router)
app.include_router(music_router)
app.include_router(weather_router)
app.include_router(pihole_router)
app.include_router(plants_router)
app.include_router(bar_router)
app.include_router(routines_router)
app.include_router(events_router)
app.include_router(rules_router)
app.include_router(ambient_router)
app.include_router(learning_router)
app.include_router(camera_router)
app.include_router(debug_router)

# Pi-hole reverse proxy — must come AFTER all API routers so our own
# /api/* routes match first.  Only unmatched /api/* paths (Pi-hole's
# own endpoints) and /admin/* fall through to this proxy.
app.include_router(pihole_proxy_router)

# Serve the SvelteKit static build (must come after API routes).
# Path is controlled by settings.FRONTEND_BUILD (default frontend-svelte/build).
if FRONTEND_DIST.exists():
    app.mount("/_app", StaticFiles(directory=str(FRONTEND_DIST / "_app")), name="frontend-app")

    @app.get("/{path:path}")
    async def serve_frontend(path: str) -> FileResponse:
        """Serve the SvelteKit SPA — non-API routes fall through to index.html."""
        file_path = FRONTEND_DIST / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIST / "index.html"))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time state sync.

    Clients receive light_update, sonos_update, connection_status,
    mode_update events. Clients can send light_command, sonos_command messages.
    """
    ws_manager: WebSocketManager = websocket.app.state.ws_manager

    # Connection-scoped correlation ID — frames belong to one ongoing
    # session, so a single ID per connection is the right granularity.
    # The client gets it via connection_status so it can echo it on
    # support tickets; logs across this connection share the tag.
    rid = new_request_id()
    rid_token = request_id_var.set(rid)

    await ws_manager.connect(websocket)

    # Send initial connection status
    hue = websocket.app.state.hue
    sonos = websocket.app.state.sonos
    automation = websocket.app.state.automation
    await websocket.send_text(json.dumps({
        "type": "connection_status",
        "data": {
            "hue": hue.connected,
            "sonos": sonos.connected,
            "build_id": websocket.app.state.build_id,
            "request_id": rid,
        },
    }))

    # Send current automation mode
    await websocket.send_text(json.dumps({
        "type": "mode_update",
        "data": {
            "mode": automation.current_mode,
            "source": automation.mode_source,
            "manual_override": automation.manual_override,
        },
    }))

    # Send current ambient sound state
    ambient = getattr(websocket.app.state, "ambient_sound", None)
    if ambient:
        await websocket.send_text(json.dumps({
            "type": "ambient_update",
            "data": ambient.get_state(),
        }))

    # Send current presence state
    presence = getattr(websocket.app.state, "presence", None)
    if presence:
        await websocket.send_text(json.dumps({
            "type": "presence_update",
            "data": presence.get_status(),
        }))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                app_logger.warning("Malformed WebSocket JSON, ignoring")
                continue

            try:
                command = _WS_COMMAND_ADAPTER.validate_python(message)
            except ValidationError as e:
                # include_context=False drops `ctx['error']` which holds a
                # ValueError that json.dumps can't serialize.
                details = e.errors(include_url=False, include_context=False)
                app_logger.warning("WebSocket validation failed: %s", details)
                try:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "data": {"reason": "validation", "details": details},
                    }))
                except Exception:
                    pass
                continue

            if isinstance(command, LightCommand):
                await _handle_light_command(websocket.app, command.data, ws_manager)
            elif isinstance(command, SonosCommand):
                await _handle_sonos_command(websocket.app, command.data)

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        app_logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)
    finally:
        request_id_var.reset(rid_token)


async def _handle_light_command(
    app, data: LightCommandData, ws_manager: WebSocketManager,
) -> None:
    """Process a validated light control command from a WebSocket client."""
    hue: HueService = app.state.hue
    if not hue.connected:
        return

    light_id = data.light_id

    # Build the bridge payload from only the fields the client actually set.
    state = data.model_dump(exclude={"light_id"}, exclude_none=True)
    if not state:
        return

    # Capture full before-state for event logging (bri, hue, sat, ct)
    before = await hue.get_light(light_id) if any(
        k in state for k in ("bri", "hue", "sat", "ct")
    ) else None

    await hue.set_light(light_id, state)

    # Mark this light as manually overridden so automation skips it
    automation = getattr(app.state, "automation", None)
    if automation:
        automation.mark_light_manual(str(light_id))

    # Broadcast updated state to all clients
    updated = await hue.get_light(light_id)
    if updated:
        await ws_manager.broadcast("light_update", updated)

    # Log the manual adjustment (covers bri/hue/sat/ct changes)
    event_logger = getattr(app.state, "event_logger", None)
    if event_logger and before is not None:
        mode = automation.current_mode if automation else None
        await event_logger.log_light_adjustment(
            light_id=str(light_id),
            light_name=(updated or before).get("name"),
            bri_before=before.get("bri") if "bri" in state else None,
            bri_after=state.get("bri"),
            hue_before=before.get("hue") if "hue" in state else None,
            hue_after=state.get("hue"),
            sat_before=before.get("sat") if "sat" in state else None,
            sat_after=state.get("sat"),
            ct_before=before.get("ct") if "ct" in state else None,
            ct_after=state.get("ct"),
            mode_at_time=mode,
            trigger="ws",
        )


async def _handle_sonos_command(app, data: SonosCommandData) -> None:
    """Process a validated Sonos control command from a WebSocket client."""
    sonos: SonosService = app.state.sonos
    if not sonos.connected:
        return

    action = data.action
    success = False
    event_type: Optional[str] = None
    if action == "play":
        success = await sonos.play()
        event_type = "play"
    elif action == "pause":
        success = await sonos.pause()
        event_type = "pause"
    elif action == "volume":
        # Validator guarantees data.volume is set when action == "volume".
        success = await sonos.set_volume(data.volume)
        event_type = "volume"
    elif action == "next":
        success = await sonos.next_track()
        event_type = "skip"
    elif action == "previous":
        success = await sonos.previous_track()
        event_type = "skip"

    # Log the manual playback event
    if success and event_type is not None:
        event_logger = getattr(app.state, "event_logger", None)
        automation = getattr(app.state, "automation", None)
        if event_logger:
            mode = automation.current_mode if automation else None
            await event_logger.log_sonos_event(
                event_type=event_type,
                favorite_title=None,
                mode_at_time=mode,
                volume=data.volume,
                triggered_by="manual",
            )
