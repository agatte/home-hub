"""
Home Hub — FastAPI application.

Single backend that controls Hue lights, Sonos speaker, runs automation engine,
and serves the React frontend.
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes.automation import router as automation_router
from backend.api.routes.health import router as health_router
from backend.api.routes.lights import router as lights_router
from backend.api.routes.music import router as music_router
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
from backend.services.library_import_service import LibraryImportService
from backend.services.morning_routine import MorningRoutineService
from backend.services.recommendation_service import RecommendationService
from backend.services.event_logger import EventLogger
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

    # Automation engine — load persisted schedule + brightness config
    from backend.api.routes.routines import load_setting
    from backend.api.routes.automation import (
        SCHEDULE_CONFIG_KEY, BRIGHTNESS_CONFIG_KEY, _dict_to_schedule_config,
    )
    from backend.services.automation_engine import ScheduleConfig

    saved_schedule = await load_setting(SCHEDULE_CONFIG_KEY)
    schedule_config = (
        _dict_to_schedule_config(saved_schedule)
        if saved_schedule
        else ScheduleConfig()
    )
    saved_brightness = await load_setting(BRIGHTNESS_CONFIG_KEY)

    # Event logger — captures mode transitions, light adjustments, Sonos events
    event_logger = EventLogger()
    app.state.event_logger = event_logger

    automation = AutomationEngine(
        hue=hue, hue_v2=hue_v2, ws_manager=ws_manager,
        schedule_config=schedule_config,
        mode_brightness=saved_brightness or None,
        event_logger=event_logger,
    )
    automation.screen_sync = screen_sync
    app.state.automation = automation

    # Music mapper (DB-backed mode-to-playlist mapping with smart auto-play)
    music_mapper = MusicMapper(
        sonos_service=sonos, ws_manager=ws_manager, event_logger=event_logger
    )
    await music_mapper.load_from_db()
    automation.register_on_mode_change(music_mapper.on_mode_change_wrapper)
    app.state.music_mapper = music_mapper

    # Library import service (Apple Music XML → taste profile)
    library_import = LibraryImportService()
    app.state.library_import = library_import

    # Recommendation service (Last.fm + iTunes Search API)
    rec_service = RecommendationService(
        lastfm_api_key=settings.LASTFM_API_KEY,
    )
    app.state.recommendation_service = rec_service

    # Morning routine — load persisted config from DB, fall back to .env defaults
    from backend.api.routes.routines import load_morning_config
    saved_config = await load_morning_config()

    morning = MorningRoutineService(
        tts_service=tts,
        automation_engine=automation,
        openweather_key=settings.OPENWEATHER_API_KEY,
        google_maps_key=settings.GOOGLE_MAPS_API_KEY,
        home_address=settings.HOME_ADDRESS,
        work_address=settings.WORK_ADDRESS,
        morning_volume=saved_config.get("volume", settings.MORNING_VOLUME),
    )
    app.state.morning_routine = morning

    # Scheduler
    scheduler = AsyncScheduler()
    scheduler.add_task(ScheduledTask(
        name="morning_routine",
        hour=saved_config.get("hour", settings.MORNING_ROUTINE_HOUR),
        minute=saved_config.get("minute", settings.MORNING_ROUTINE_MINUTE),
        weekdays=[0, 1, 2, 3, 4],  # Monday-Friday
        callback=morning.execute,
        enabled=saved_config.get("enabled", bool(settings.OPENWEATHER_API_KEY)),
    ))

    # Evening wind-down routine
    from backend.api.routes.routines import WINDDOWN_CONFIG_KEY
    from backend.services.winddown_routine import WinddownRoutineService

    winddown_config = await load_setting(WINDDOWN_CONFIG_KEY)
    winddown = WinddownRoutineService(
        automation_engine=automation,
        sonos_service=sonos,
        tts_service=tts,
        volume=winddown_config.get("volume", 20),
        activate_candlelight=winddown_config.get("activate_candlelight", True),
        weekdays_only=winddown_config.get("weekdays_only", False),
    )
    app.state.winddown_routine = winddown

    winddown_weekdays = (
        [0, 1, 2, 3, 4]
        if winddown_config.get("weekdays_only", False)
        else [0, 1, 2, 3, 4, 5, 6]
    )
    scheduler.add_task(ScheduledTask(
        name="winddown_routine",
        hour=winddown_config.get("hour", 21),
        minute=winddown_config.get("minute", 0),
        weekdays=winddown_weekdays,
        callback=winddown.execute,
        enabled=winddown_config.get("enabled", False),
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
    await rec_service.close()


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
app.include_router(music_router)
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

    # Capture current brightness before the change for event logging
    bri_before = None
    if "bri" in state:
        current = await hue.get_light(light_id)
        if current:
            bri_before = current.get("bri")

    await hue.set_light(light_id, state)

    # Broadcast updated state to all clients
    updated = await hue.get_light(light_id)
    if updated:
        await ws_manager.broadcast("light_update", updated)

    # Log the manual adjustment
    if "bri" in state:
        event_logger = getattr(app.state, "event_logger", None)
        automation = getattr(app.state, "automation", None)
        if event_logger:
            mode = automation.current_mode if automation else None
            await event_logger.log_light_adjustment(
                light_id=str(light_id),
                light_name=updated.get("name") if updated else None,
                bri_before=bri_before,
                bri_after=state["bri"],
                mode_at_time=mode,
            )


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
