"""
Home Hub — FastAPI application.

Single backend that controls Hue lights, Sonos speaker, runs automation engine,
and serves the React frontend.
"""
import asyncio
import json
import logging
import subprocess
import uuid
from contextlib import asynccontextmanager
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
from backend.config import PROJECT_ROOT, STATIC_DIR, TTS_DIR, settings

FRONTEND_DIST = PROJECT_ROOT / settings.FRONTEND_BUILD
from backend.database import init_db
from backend.schemas.ws import (
    LightCommand,
    LightCommandData,
    SonosCommand,
    SonosCommandData,
    WSCommand,
)
from backend.services.automation_engine import AutomationEngine
from backend.services.screen_sync import LaptopLoopbackCapture, ScreenSyncService
from backend.services.hue_service import HueService
from backend.services.hue_v2_service import HueV2Service
from backend.services.library_import_service import LibraryImportService
from backend.services.morning_routine import MorningRoutineService
from backend.services.recommendation_service import RecommendationService
from backend.services.event_logger import EventLogger
from backend.services.fauxmo_service import FauxmoService
from backend.services.music_mapper import MusicMapper
from backend.services.scheduler import AsyncScheduler, ScheduledTask
from backend.services.presence_service import PresenceService
from backend.services.sonos_service import SonosService
from backend.services.tracing import (
    coerce_inbound_id,
    new_request_id,
    request_id_var,
)
from backend.services.tts_service import TTSService
from backend.services.websocket_manager import WebSocketManager
from backend.utils.logger import logger  # noqa: F401 — triggers logging setup

app_logger = logging.getLogger("home_hub.main")

# Pre-built adapter for the discriminated WS-command union — caching the
# TypeAdapter avoids rebuilding validation machinery on every frame.
_WS_COMMAND_ADAPTER: TypeAdapter[WSCommand] = TypeAdapter(WSCommand)


async def _safe_shutdown(name: str, factory) -> None:
    """
    Run a teardown step and log+continue on failure.

    `factory` is a zero-arg callable that returns the awaitable — that way
    an AttributeError while building the coroutine (e.g. attribute missing
    on app.state) is caught too, not just exceptions raised during execution.
    """
    try:
        await factory()
    except Exception as e:
        app_logger.error("shutdown step %r failed: %s", name, e, exc_info=True)


def _compute_build_id() -> str:
    """
    Identifier for the running code, used by the frontend to detect deploys
    over the WebSocket and auto-reload the kiosk dashboard. Prefers the short
    git SHA so a benign restart on the same commit doesn't trigger a reload;
    falls back to a per-process UUID if git is unavailable.

    Note: scripts/deploy.sh only restarts home-hub.service when files under
    backend/ or run.py actually changed in the pulled diff, so empty commits
    or pure-frontend deploys won't bump this value mid-flight. That's by
    design — skipping unnecessary backend restarts is what keeps the
    dashboard responsive during routine deploys.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        sha = result.stdout.strip()
        if sha:
            return sha
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return uuid.uuid4().hex[:8]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the application."""
    app_logger.info("Starting Home Hub...")

    app.state.build_id = _compute_build_id()
    app_logger.info(f"Build ID: {app.state.build_id}")

    # Initialize database
    await init_db()
    app_logger.info("Database initialized")

    # WebSocket manager
    ws_manager = WebSocketManager()
    app.state.ws_manager = ws_manager

    # Heartbeat registry — long-running tasks call .tick(name) once per
    # iteration; /health flags any whose age > 2x expected interval. Has
    # to live before service construction so each service can be wired
    # via set_heartbeat_registry().
    from backend.services.heartbeat import HeartbeatRegistry
    heartbeats = HeartbeatRegistry()
    app.state.heartbeats = heartbeats

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

    # Screen sync service — receiver for RGB colors posted by the desktop
    # pc_agent (or laptop loopback). Holds smoothing state and applies the
    # final color to the bedroom lamp. The capture loop lives elsewhere.
    screen_sync = ScreenSyncService(hue_service=hue, target_light_id="2")
    app.state.screen_sync = screen_sync

    # Laptop loopback — opt-in screen capture that runs in-process on the
    # laptop and POSTs to localhost (TV-on-laptop escape hatch). Default off.
    laptop_loopback = LaptopLoopbackCapture()
    app.state.laptop_loopback = laptop_loopback

    # Automation engine — load persisted schedule + brightness config
    from backend.api.routes.routines import load_setting
    from backend.api.routes.automation import (
        SCHEDULE_CONFIG_KEY, BRIGHTNESS_CONFIG_KEY, SCREEN_SYNC_LAPTOP_KEY,
        WATCHING_POSTURE_KEY, WATCHING_POSTURE_DEFAULTS,
        _dict_to_schedule_config,
    )
    from backend.services.automation_engine import ScheduleConfig

    saved_schedule = await load_setting(SCHEDULE_CONFIG_KEY)
    schedule_config = (
        _dict_to_schedule_config(saved_schedule)
        if saved_schedule
        else ScheduleConfig()
    )
    saved_brightness = await load_setting(BRIGHTNESS_CONFIG_KEY)
    saved_watching_posture = await load_setting(WATCHING_POSTURE_KEY)

    # Event logger — captures mode transitions, light adjustments, Sonos events
    event_logger = EventLogger()
    app.state.event_logger = event_logger
    # Background retry loop for transient DB errors (SQLite WAL locks).
    # Registered to tasks below so the existing cancel-and-wait path tears it down.
    event_logger_retry_task = await event_logger.start()

    # Event query service — read-only aggregation over event tables
    from backend.services.event_query_service import EventQueryService
    app.state.event_query_service = EventQueryService()

    # Weather service (NWS API — no key required, free alerts). Constructed
    # before AutomationEngine so it flows in via the constructor; previously
    # this lived after automation and was back-filled, which is the
    # late-binding pattern this section now avoids.
    from backend.services.weather_service import WeatherService
    weather_service = WeatherService()
    app.state.weather_service = weather_service
    logger.info("Weather service initialized (NWS API)")

    # ML services — model manager + learners + fusion. All built before
    # AutomationEngine so engine takes them via constructor kwargs (no
    # post-construction `automation._x = y` back-fills).
    from backend.services.ml.model_manager import ModelManager
    from backend.services.ml.lighting_learner import LightingPreferenceLearner
    from backend.services.ml.ml_logger import MLDecisionLogger
    from backend.services.ml.confidence_fusion import ConfidenceFusion

    model_manager = ModelManager()
    await model_manager.load_all()
    app.state.model_manager = model_manager

    lighting_learner = LightingPreferenceLearner(model_manager)
    model_manager.register_learner(lighting_learner)
    app.state.lighting_learner = lighting_learner

    ml_logger = MLDecisionLogger(ws_manager=ws_manager)
    app.state.ml_logger = ml_logger

    # Behavioral predictor — graceful degradation if lightgbm missing.
    behavioral_predictor = None
    try:
        from backend.services.ml.behavioral_predictor import BehavioralPredictor
        behavioral_predictor = BehavioralPredictor(model_manager)
        model_manager.register_learner(behavioral_predictor)
        app_logger.info(
            "Behavioral predictor initialized (status=%s)",
            behavioral_predictor._status,
        )
    except ImportError:
        app_logger.warning(
            "lightgbm not installed — behavioral predictor disabled"
        )
    app.state.behavioral_predictor = behavioral_predictor

    confidence_fusion = ConfidenceFusion()
    app.state.confidence_fusion = confidence_fusion
    app_logger.info("Confidence fusion initialized")

    # Music bandit — Thompson sampling playlist selection. Built before
    # MusicMapper so it can be passed via constructor.
    from backend.services.ml.music_bandit import MusicBandit
    music_bandit = MusicBandit(model_manager)
    model_manager.register_learner(music_bandit)
    app.state.music_bandit = music_bandit
    app_logger.info("Music bandit initialized (%d arms)", len(music_bandit._arms))

    app_logger.info("ML services initialized")

    # Rule engine — learns time-based mode patterns, nudges user.
    # Takes confidence_fusion via constructor (was previously back-filled).
    from backend.services.rule_engine_service import RuleEngineService
    rule_engine = RuleEngineService(
        ws_manager=ws_manager,
        confidence_fusion=confidence_fusion,
    )
    app.state.rule_engine = rule_engine

    # Music mapper — takes music_bandit via constructor (was back-filled).
    music_mapper = MusicMapper(
        sonos_service=sonos,
        ws_manager=ws_manager,
        event_logger=event_logger,
        music_bandit=music_bandit,
    )
    await music_mapper.load_from_db()
    app.state.music_mapper = music_mapper

    # Ambient sound service — takes weather_service via constructor for real
    # this time (was previously passed as a getattr that returned None, then
    # back-filled).
    from backend.services.ambient_sound_service import AmbientSoundService
    ambient_sound = AmbientSoundService(
        ws_manager=ws_manager,
        weather_service=weather_service,
    )
    await ambient_sound.load_from_db()
    ambient_sound.scan_sounds()
    app.state.ambient_sound = ambient_sound

    # Automation engine — every collaborator now flows in via the
    # constructor. Replaces the previous shape that took 4 args and
    # back-filled 8 more attributes after construction.
    automation = AutomationEngine(
        hue=hue, hue_v2=hue_v2, ws_manager=ws_manager,
        schedule_config=schedule_config,
        mode_brightness=saved_brightness or None,
        event_logger=event_logger,
        weather_service=weather_service,
        sonos=sonos,
        screen_sync=screen_sync,
        music_mapper=music_mapper,
        rule_engine=rule_engine,
        lighting_learner=lighting_learner,
        ml_logger=ml_logger,
        behavioral_predictor=behavioral_predictor,
        confidence_fusion=confidence_fusion,
    )
    app.state.automation = automation
    await automation.load_scene_overrides()

    # Mode-change callbacks — runtime event subscriptions, separate from
    # dependency injection. Registered after automation exists.
    automation.register_on_mode_change(music_mapper.on_mode_change_wrapper)
    automation.register_on_mode_change(ambient_sound.on_mode_change_wrapper)
    automation.register_on_mode_change(ml_logger.on_mode_change)

    # Apply persisted watching-posture tuning (settings-page sliders for the
    # projector-safe caps + reclined L1 night ambient).
    posture_cfg = {**WATCHING_POSTURE_DEFAULTS, **(saved_watching_posture or {})}
    screen_sync.set_cap_override(
        "watching", "bed", "reclined", posture_cfg["reclined_sync_cap"]
    )
    screen_sync.set_cap_override(
        "watching", "bed", "upright", posture_cfg["upright_sync_cap"]
    )
    automation.set_bed_reclined_l1_night(posture_cfg["reclined_l1_night"])

    # Restore laptop loopback state from persisted setting (default off)
    saved_loopback = await load_setting(SCREEN_SYNC_LAPTOP_KEY)
    if saved_loopback.get("enabled", False):
        await laptop_loopback.start()
        app_logger.info("Laptop screen sync loopback resumed from saved state")

    # Library import service (Apple Music XML → taste profile)
    library_import = LibraryImportService()
    app.state.library_import = library_import

    # Recommendation service (Last.fm + iTunes Search API)
    rec_service = RecommendationService(
        lastfm_api_key=settings.LASTFM_API_KEY,
    )
    app.state.recommendation_service = rec_service

    # Plant app integration (external app, cached 10 min). The service
    # refuses to construct against http:// without the explicit
    # PLANT_APP_ALLOW_INSECURE escape hatch — catch and skip rather
    # than crashing the lifespan.
    if settings.PLANT_APP_API_URL and settings.PLANT_APP_EMAIL:
        from backend.services.plant_app_service import PlantAppService
        try:
            plant_service = PlantAppService(
                api_url=settings.PLANT_APP_API_URL,
                email=settings.PLANT_APP_EMAIL,
                password=settings.PLANT_APP_PASSWORD or "",
                allow_insecure=settings.PLANT_APP_ALLOW_INSECURE,
            )
            app.state.plant_service = plant_service
            logger.info("Plant app service initialized")
        except ValueError as e:
            logger.error("Plant app disabled — %s", e)

    # Bar app integration (Home Bar on LAN, cached 10 min)
    if settings.BAR_APP_URL:
        from backend.services.bar_app_service import BarAppService
        bar_service = BarAppService(api_url=settings.BAR_APP_URL)
        app.state.bar_service = bar_service

        # When Home Hub enters "social" mode, auto-activate bar party mode
        async def _bar_mode_callback(new_mode: str, **kwargs) -> None:
            if new_mode == "social":
                await bar_service.notify_party_mode(True)
            elif new_mode != "social":
                # Only deactivate if we previously activated
                pass  # Don't auto-deactivate — let the host control this

        automation.register_on_mode_change(_bar_mode_callback)
        logger.info("Bar app service initialized (%s)", settings.BAR_APP_URL)

    # Presence detection — replaces Alexa geofence. Now receives the real
    # confidence_fusion via constructor (previously was back-filled because
    # fusion didn't exist yet at presence-construction time).
    presence_config = await load_setting("presence_config")
    presence = PresenceService(
        hue=hue,
        hue_v2=hue_v2,
        sonos=sonos,
        tts=tts,
        weather_service=weather_service,
        automation_engine=automation,
        music_mapper=music_mapper,
        ws_manager=ws_manager,
        event_logger=event_logger,
        config=presence_config or {},
        # Presence is a voter in ConfidenceFusion — "phone on home WiFi"
        # is the most reliable "user is (not) home" signal the system has.
        fusion=confidence_fusion,
    )
    app.state.presence = presence
    logger.info(
        "Presence detection initialized (phone=%s)", presence.config.phone_ip
    )

    # Pi-hole DNS stats (optional)
    if settings.PIHOLE_API_URL and settings.PIHOLE_API_KEY:
        from backend.services.pihole_service import PiholeService
        pihole_service = PiholeService(
            api_url=settings.PIHOLE_API_URL,
            api_key=settings.PIHOLE_API_KEY,
        )
        app.state.pihole_service = pihole_service
        logger.info("Pi-hole service initialized")

    # Fauxmo Alexa integration (Phase 3 voice control)
    fauxmo = FauxmoService(
        local_ip=settings.LOCAL_IP,
        api_port=8000,
        enabled=settings.FAUXMO_ENABLED,
    )
    await fauxmo.start()
    app.state.fauxmo = fauxmo

    # Morning routine — load persisted config from DB, fall back to .env defaults
    from backend.api.routes.routines import load_morning_config
    saved_config = await load_morning_config()

    morning = MorningRoutineService(
        tts_service=tts,
        automation_engine=automation,
        weather_service=getattr(app.state, "weather_service", None),
        google_maps_key=settings.GOOGLE_MAPS_API_KEY,
        home_address=settings.HOME_ADDRESS,
        work_address=settings.WORK_ADDRESS,
        morning_volume=saved_config.get("volume", settings.MORNING_VOLUME),
    )
    app.state.morning_routine = morning

    # Scheduler
    scheduler = AsyncScheduler()

    morning_hour = saved_config.get("hour", settings.MORNING_ROUTINE_HOUR)
    morning_minute = saved_config.get("minute", settings.MORNING_ROUTINE_MINUTE)
    morning_enabled = saved_config.get("enabled", True)

    # Sunrise ramp — 30 minutes before morning routine
    ramp_total = morning_hour * 60 + morning_minute - 30
    if ramp_total < 0:
        ramp_total += 1440  # Wrap past midnight
    ramp_hour, ramp_minute = divmod(ramp_total, 60)

    scheduler.add_task(ScheduledTask(
        name="sunrise_ramp",
        hour=ramp_hour,
        minute=ramp_minute,
        weekdays=[0, 1, 2, 3, 4],
        callback=morning.sunrise_ramp,
        enabled=morning_enabled,
    ))

    scheduler.add_task(ScheduledTask(
        name="morning_routine",
        hour=morning_hour,
        minute=morning_minute,
        weekdays=[0, 1, 2, 3, 4],  # Monday-Friday
        callback=morning.execute,
        enabled=morning_enabled,
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
        skip_if_active=winddown_config.get("skip_if_active", True),
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

    # Nightly ML retrain at 4:00 AM
    scheduler.add_task(ScheduledTask(
        name="ml_nightly_training",
        hour=4,
        minute=0,
        weekdays=[0, 1, 2, 3, 4, 5, 6],
        callback=model_manager.retrain_all,
        enabled=True,
    ))

    # Nightly fusion weight tuning at 3:30 AM — runs 30 min before the model
    # retrain so yesterday's fusion decisions (which carry per-source signal
    # details in `factors`) feed into the weight update before the newly
    # trained models start producing tomorrow's decisions.
    async def fusion_weight_tuning() -> None:
        acc = await ml_logger.compute_accuracy_by_source(days=14)
        if acc:
            confidence_fusion.update_weights_from_accuracy(acc)
            app_logger.info(
                "fusion_weight_tuning: updated weights from %d sources", len(acc),
            )
        else:
            app_logger.info(
                "fusion_weight_tuning: no usable per-source accuracy data yet — weights unchanged",
            )

    scheduler.add_task(ScheduledTask(
        name="fusion_weight_tuning",
        hour=3,
        minute=30,
        weekdays=[0, 1, 2, 3, 4, 5, 6],
        callback=fusion_weight_tuning,
        enabled=True,
    ))

    app.state.scheduler = scheduler

    # Background tasks
    tasks: list[asyncio.Task] = []

    # Wire heartbeat registry into every service that runs a polling
    # loop. Each service publishes liveness via .tick(name) once per
    # iteration; /health reads heartbeats.snapshot() to flag stale tasks.
    event_logger.set_heartbeat_registry(heartbeats)
    hue.set_heartbeat_registry(heartbeats)
    sonos.set_heartbeat_registry(heartbeats)
    automation.set_heartbeat_registry(heartbeats)
    scheduler.set_heartbeat_registry(heartbeats)
    rule_engine.set_heartbeat_registry(heartbeats)
    presence.set_heartbeat_registry(heartbeats)

    # Register expected polling cadences. Camera self-registers on enable
    # and deregisters on disable / pause (handled in CameraService) so
    # legitimate downtime isn't flagged stale.
    heartbeats.register("event_logger_retry", 30.0)
    if hue.connected:
        heartbeats.register("hue", 1.0)
    if sonos.connected:
        heartbeats.register("sonos", 2.0)
    heartbeats.register("automation", 60.0)
    heartbeats.register("scheduler", 30.0)
    heartbeats.register("rule_engine", 6 * 3600.0)
    heartbeats.register("presence", float(presence.config.probe_interval))
    heartbeats.register("transit_lighting", 2.0)

    # Event logger retry task was started above — register for teardown here.
    tasks.append(event_logger_retry_task)

    if hue.connected:
        tasks.append(asyncio.create_task(hue.poll_state_loop(ws_manager)))

    if sonos.connected:
        tasks.append(asyncio.create_task(sonos.poll_state_loop(ws_manager)))

    tasks.append(asyncio.create_task(automation.run_loop()))
    tasks.append(asyncio.create_task(scheduler.run_loop()))
    tasks.append(asyncio.create_task(rule_engine.run_generation_loop()))
    tasks.append(asyncio.create_task(presence.run_loop()))

    # Camera presence detection (opt-in, runs on Latitude webcam)
    camera_enabled_setting = await load_setting("camera_enabled")
    if camera_enabled_setting and camera_enabled_setting.get("enabled", False):
        try:
            from backend.services.camera_service import CameraService
            camera_service = CameraService(ws_manager, automation, ml_logger)
            camera_service.set_heartbeat_registry(heartbeats)
            await camera_service.start()
            if camera_service.enabled:
                app.state.camera_service = camera_service
                automation.register_on_mode_change(camera_service.on_mode_change)
                automation.set_camera_service(camera_service)
                presence.set_camera_service(camera_service)
                tasks.append(asyncio.create_task(camera_service.poll_loop()))
                app_logger.info("Camera presence detection started")
            else:
                app_logger.warning("Camera service failed to start (webcam unavailable?)")
        except ImportError:
            app_logger.warning("mediapipe/opencv not installed — camera service disabled")
    else:
        app_logger.info("Camera service disabled (camera_enabled=false)")

    # Transit lighting — brighten kitchen/living-room when Anthony steps out
    # of the bedroom with his phone still on Wi-Fi. Depends on camera presence
    # + WiFi presence, so only makes sense once those are both running.
    from backend.services.transit_lighting_service import TransitLightingService
    transit_lighting = TransitLightingService(
        automation_engine=automation,
        camera_service=getattr(app.state, "camera_service", None),
        presence_service=presence,
    )
    transit_lighting.set_heartbeat_registry(heartbeats)
    app.state.transit_lighting = transit_lighting
    tasks.append(asyncio.create_task(transit_lighting.poll_loop()))
    app_logger.info("Transit lighting service started")

    app_logger.info("Home Hub is ready")

    yield

    # Shutdown
    app_logger.info("Shutting down Home Hub...")

    # 1. Stop producers that feed the background loops. If any one raises, the
    #    others still run because _safe_shutdown swallows per-step errors.
    await _safe_shutdown("laptop_loopback", laptop_loopback.stop)
    await _safe_shutdown("fauxmo", fauxmo.stop)
    ambient_sound = getattr(app.state, "ambient_sound", None)
    if ambient_sound is not None:
        await _safe_shutdown("ambient_sound", ambient_sound.stop)

    # 2. Cancel background tasks, then bounded-wait for them to finish. A hung
    #    task can't block shutdown forever.
    for task in tasks:
        task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        still_running = [
            getattr(t.get_coro(), "__qualname__", "?")
            for t in tasks
            if not t.done()
        ]
        app_logger.error(
            "shutdown: %d tasks still running after 5s timeout: %s",
            len(still_running), still_running,
        )

    # 3. Close long-lived HTTP clients last — poll loops that used them are
    #    already cancelled, so there's no race.
    await _safe_shutdown("hue_v2", hue_v2.close)
    await _safe_shutdown("rec_service", rec_service.close)
    camera = getattr(app.state, "camera_service", None)
    if camera is not None:
        await _safe_shutdown("camera", camera.close)
    transit = getattr(app.state, "transit_lighting", None)
    if transit is not None:
        await _safe_shutdown("transit_lighting", transit.close)


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
