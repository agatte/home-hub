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
from backend.api.routes.analytics import router as analytics_router
from backend.api.routes.events import router as events_router
from backend.api.routes.gameday import router as gameday_router
from backend.api.routes.guest import router as guest_router
from backend.api.routes.journal import router as journal_router
from backend.api.routes.rules import router as rules_router
from backend.api.routes.pihole import router as pihole_router
from backend.api.routes.vitals import router as vitals_router
from backend.api.routes.weather import router as weather_router
from backend.api.routes.ambient import router as ambient_router
from backend.api.routes.learning import router as learning_router
from backend.api.routes.camera import router as camera_router
from backend.api.routes.debug import router as debug_router
from backend.api.routes.notification import router as notification_router
from backend.api.routes.personality import router as personality_router
from backend.api.routes.pihole_proxy import router as pihole_proxy_router
from backend.bootstrap import lifespan
from backend.config import DATA_DIR, PROJECT_ROOT, STATIC_DIR, TTS_DIR, settings

# Sentry init runs before app construction so the FastAPI auto-integration
# patches request handling. dsn=None disables ingestion silently — safe in
# dev where SENTRY_DSN is unset.
#
# Gate ingestion on APP_ENV == "production" so dev pytest runs (which
# intentionally raise RuntimeError("speaker offline") in TTS tests, etc.)
# don't burn the 10k/month free-tier quota with test-mock noise that looks
# like real prod issues in the dashboard. If the dev .env happens to have
# SENTRY_DSN set (config drift), this guard still silences it.
import sentry_sdk  # noqa: E402

sentry_sdk.init(
    dsn=settings.SENTRY_DSN if settings.APP_ENV == "production" else None,
    environment=settings.APP_ENV,
    traces_sample_rate=0.0,
    send_default_pii=False,
)

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


# --- Per-connection WebSocket rate limit -------------------------------------
#
# slowapi only binds to HTTP handlers; WebSockets need their own bucket.
# Today the WS is LAN-only (the tunnel proxy doesn't declare WS upgrade
# methods, so it's not publicly reachable). But the kiosk drags a slider
# faster than the bridge can ack, and a future remote-app feature might
# expose the WS through a tunneled path — either way, a small in-memory
# token bucket per client is cheap insurance.
#
# Implementation: track timestamps of the last N commands per WS object.
# 30 commands per 10 seconds is generous enough for slider drags (which
# emit ~20/s during a fast sweep) without leaving the door open to
# unlimited abuse.
import time  # noqa: E402
from collections import deque  # noqa: E402

_WS_RATE_LIMIT_WINDOW = 10.0  # seconds
_WS_RATE_LIMIT_MAX = 30       # commands per window


def _ws_rate_limit_check(bucket: deque[float]) -> bool:
    """Slide the window, return True if the command should be ALLOWED.

    Mutates `bucket` in place — call once per inbound command. The deque
    is bounded by the time window, not by maxlen; max-window-size is
    `_WS_RATE_LIMIT_MAX` items so it stays small.
    """
    now = time.monotonic()
    cutoff = now - _WS_RATE_LIMIT_WINDOW
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= _WS_RATE_LIMIT_MAX:
        return False
    bucket.append(now)
    return True


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


# Conservative CSP for the kiosk. Tighten over time:
#   - `'unsafe-inline'` on style-src is needed for Svelte component-scoped
#     inline styles + style="..." attributes in templates. SvelteKit 2 can
#     run without it if every component is refactored — out of scope here.
#   - `'unsafe-inline'` on script-src is needed because adapter-static
#     emits the SvelteKit hydration bootstrap as a literal inline <script>
#     block in build/index.html (the `__sveltekit_*` IIFE that fires
#     kit.start). Without it, every browser refuses to hydrate the page
#     and the kiosk goes black — happened once 2026-05-17. Phase-2 fix is
#     `kit.csp` in svelte.config.js (mode: 'hash') feeding hashes to this
#     middleware; not done yet because adapter-static's fallback-index
#     emit path needs verification first.
#   - `'self' blob:` on worker-src is for Threlte/three.js on /gameday.
#   - connect-src includes ws: for the in-page WebSocket (same-origin
#     covered by 'self' on modern browsers, but ws: makes it explicit).
#   - object-src 'none' + base-uri 'self' + form-action 'self' +
#     frame-ancestors 'none' close the legacy holes browsers leave open.
# When a console violation appears in production, copy the directive that
# fired and adjust here; don't blanket-allow 'unsafe-eval' or '*' sources.
_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self' ws: wss:; "
    "font-src 'self' data:; "
    "media-src 'self'; "
    "worker-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    """
    Apply defense-in-depth response headers to every response.

    These are belt-and-suspenders on top of the LAN/tunnel auth model:
    they harden the browser side so an attacker who somehow gets a
    response served back can't pivot it into XSS, clickjacking, MIME
    sniffing, or referrer leakage. HSTS is only sent on tunnel-origin
    responses — over plain-HTTP LAN it's a no-op (browsers ignore HSTS
    on non-HTTPS) and sending it on LAN would just be confusing
    in dev tools.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Referrer-Policy", "strict-origin-when-cross-origin"
    )
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    response.headers.setdefault("Content-Security-Policy", _CSP)
    is_tunnel = (
        request.headers.get("X-Tunnel-Origin", "").strip().lower()
        == "cloudflare"
    )
    if is_tunnel:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


# Mount static files (TTS audio, ambient sounds, frontend build)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TTS_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "ambient").mkdir(parents=True, exist_ok=True)
# Long-form user-curated ambient MP3s live in data/ambient/ (gitignored).
# Mount under a distinct URL so the service can resolve files to the right
# prefix without filename collisions on the wire. check_dir=False makes the
# mount idempotent when the dir doesn't yet exist (fresh checkout).
(DATA_DIR / "ambient").mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/ambient-long",
    StaticFiles(directory=str(DATA_DIR / "ambient"), check_dir=False),
    name="ambient-long",
)
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
app.include_router(analytics_router)
app.include_router(gameday_router)
app.include_router(guest_router)
app.include_router(journal_router)
app.include_router(rules_router)
app.include_router(ambient_router)
app.include_router(learning_router)
app.include_router(camera_router)
app.include_router(vitals_router)
app.include_router(debug_router)
app.include_router(notification_router)
app.include_router(personality_router)

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

    # Per-connection rate-limit bucket (see _ws_rate_limit_check).
    ws_bucket: deque[float] = deque()

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
            "time_period": automation.get_time_period(),
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

            # Rate-limit BEFORE parsing — a flood of garbage JSON shouldn't
            # cost us the validator allocations either.
            if not _ws_rate_limit_check(ws_bucket):
                try:
                    await websocket.send_text(json.dumps({
                        "type": "rate_limit",
                        "data": {
                            "max": _WS_RATE_LIMIT_MAX,
                            "window_s": _WS_RATE_LIMIT_WINDOW,
                        },
                    }))
                except Exception:
                    pass
                continue

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

    # No post-write broadcast: the bridge is mid-transition right now and a
    # fresh get_light read returns an intermediate value that the slider
    # would snap to on drag-release. The polling loop already broadcasts
    # state and honors the in-flight window (hue_service.poll_state_loop),
    # and the frontend optimistically patched the local store before this
    # command was sent.

    # Log the manual adjustment (covers bri/hue/sat/ct changes)
    event_logger = getattr(app.state, "event_logger", None)
    if event_logger and before is not None:
        mode = automation.current_mode if automation else None
        await event_logger.log_light_adjustment(
            light_id=str(light_id),
            light_name=before.get("name"),
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
