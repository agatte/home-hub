"""
Home Hub — FastAPI application.

Single backend that controls Hue lights, Sonos speaker, runs automation engine,
and serves the React frontend.
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes.automation import router as automation_router
from backend.api.routes.health import router as health_router
from backend.api.routes.lights import router as lights_router
from backend.api.routes.routines import router as routines_router
from backend.api.routes.scenes import router as scenes_router
from backend.api.routes.sonos import router as sonos_router
from backend.config import PROJECT_ROOT, STATIC_DIR, TTS_DIR, settings

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
from backend.database import init_db
from backend.services.automation_engine import AutomationEngine
from backend.services.screen_sync import ScreenSyncService
from backend.services.hue_service import HueService
from backend.services.hue_v2_service import HueV2Service
from backend.services.morning_routine import MorningRoutineService
from backend.services.music_mapper import MusicMapper
from backend.services.scheduler import AsyncScheduler, ScheduledTask
from backend.services.sonos_service import SonosService
from backend.services.tts_service import TTSService
from backend.services.websocket_manager import WebSocketManager
from backend.utils.logger import logger  # noqa: F401 — triggers logging setup

app_logger = logging.getLogger("home_hub.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the application."""
    app_logger.info("Starting Home Hub...")

    # Initialize database
    await init_db()
    app_logger.info("Database initialized")

    # WebSocket manager
    ws_manager = WebSocketManager()
    app.state.ws_manager = ws_manager

    # Hue Bridge (v1 — basic light control)
    hue = HueService(
        bridge_ip=settings.HUE_BRIDGE_IP,
        username=settings.HUE_USERNAME,
    )
    await hue.connect()
    app.state.hue = hue
    app_logger.info(f"Hue bridge: {'connected' if hue.connected else 'NOT connected'}")

    # Hue v2 API (native scenes + dynamic effects)
    hue_v2 = HueV2Service(
        bridge_ip=settings.HUE_BRIDGE_IP,
        username=settings.HUE_USERNAME,
    )
    if hue.connected:
        await hue_v2.connect()
    app.state.hue_v2 = hue_v2
    app_logger.info(
        f"Hue v2 API: {'connected' if hue_v2.connected else 'NOT connected'}"
    )

    # Sonos speaker
    sonos = SonosService(sonos_ip=settings.SONOS_IP)
    await sonos.discover()
    app.state.sonos = sonos
    app_logger.info(f"Sonos: {'connected' if sonos.connected else 'NOT connected'}")

    # TTS service
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    tts = TTSService(
        sonos_service=sonos,
        static_dir=STATIC_DIR,
        local_ip=settings.LOCAL_IP,
        voice=settings.TTS_VOICE,
        default_volume=settings.TTS_VOLUME,
    )
    app.state.tts = tts

    # Screen sync service (syncs dominant screen color to bedroom lamp)
    screen_sync = ScreenSyncService(hue_service=hue, target_light_id="2")
    app.state.screen_sync = screen_sync

    # Automation engine
    automation = AutomationEngine(hue=hue, hue_v2=hue_v2, ws_manager=ws_manager)
    automation.screen_sync = screen_sync
    app.state.automation = automation

    # Music mapper
    music_mapper = MusicMapper(sonos_service=sonos)
    app.state.music_mapper = music_mapper

    # Morning routine
    morning = MorningRoutineService(
        tts_service=tts,
        automation_engine=automation,
        openweather_key=settings.OPENWEATHER_API_KEY,
        google_maps_key=settings.GOOGLE_MAPS_API_KEY,
        home_address=settings.HOME_ADDRESS,
        work_address=settings.WORK_ADDRESS,
        morning_volume=settings.MORNING_VOLUME,
    )
    app.state.morning_routine = morning

    # Scheduler
    scheduler = AsyncScheduler()
    scheduler.add_task(ScheduledTask(
        name="morning_routine",
        hour=settings.MORNING_ROUTINE_HOUR,
        minute=settings.MORNING_ROUTINE_MINUTE,
        weekdays=[0, 1, 2, 3, 4],  # Monday-Friday
        callback=morning.execute,
        enabled=bool(settings.OPENWEATHER_API_KEY),  # Only if API key is set
    ))
    app.state.scheduler = scheduler

    # Background tasks
    tasks: list[asyncio.Task] = []

    if hue.connected:
        tasks.append(asyncio.create_task(hue.poll_state_loop(ws_manager)))

    if sonos.connected:
        tasks.append(asyncio.create_task(sonos.poll_state_loop(ws_manager)))

    tasks.append(asyncio.create_task(automation.run_loop()))
    tasks.append(asyncio.create_task(scheduler.run_loop()))

    app_logger.info("Home Hub is ready")

    yield

    # Shutdown
    app_logger.info("Shutting down Home Hub...")
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await hue_v2.close()


app = FastAPI(
    title="Home Hub",
    description="Unified home automation dashboard — Hue lights, Sonos, smart automation.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server and tablet
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (TTS audio, frontend build)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Routes
app.include_router(health_router)
app.include_router(lights_router)
app.include_router(scenes_router)
app.include_router(sonos_router)
app.include_router(automation_router)
app.include_router(routines_router)

# Serve React frontend build (must come after API routes)
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend-assets")

    @app.get("/{path:path}")
    async def serve_frontend(path: str) -> FileResponse:
        """Serve the React SPA — all non-API routes fall through to index.html."""
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

    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            msg_type = message.get("type")
            data = message.get("data", {})

            if msg_type == "light_command":
                await _handle_light_command(websocket.app, data, ws_manager)
            elif msg_type == "sonos_command":
                await _handle_sonos_command(websocket.app, data)
            else:
                app_logger.warning(f"Unknown WebSocket message type: {msg_type}")

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        app_logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


async def _handle_light_command(app, data: dict, ws_manager: WebSocketManager) -> None:
    """Process a light control command from a WebSocket client."""
    hue: HueService = app.state.hue
    if not hue.connected:
        return

    light_id = data.get("light_id")
    if not light_id:
        return

    state = {k: v for k, v in data.items() if k != "light_id"}
    await hue.set_light(light_id, state)

    # Broadcast updated state to all clients
    updated = await hue.get_light(light_id)
    if updated:
        await ws_manager.broadcast("light_update", updated)


async def _handle_sonos_command(app, data: dict) -> None:
    """Process a Sonos control command from a WebSocket client."""
    sonos: SonosService = app.state.sonos
    if not sonos.connected:
        return

    action = data.get("action")
    if action == "play":
        await sonos.play()
    elif action == "pause":
        await sonos.pause()
    elif action == "volume":
        volume = data.get("volume")
        if volume is not None:
            await sonos.set_volume(int(volume))
    elif action == "next":
        await sonos.next_track()
    elif action == "previous":
        await sonos.previous_track()
