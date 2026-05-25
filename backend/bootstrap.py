"""
Application bootstrap — startup and shutdown lifecycle.

Hosts the FastAPI ``lifespan`` context manager that wires every
service in dependency order, kicks off polling tasks, and tears
everything down cleanly. Lives in its own module so ``main.py``
can stay focused on app construction, middleware, and routing.

Construction order is intentional and dependency-respecting (see
``docs/Audit_Summary.txt`` → "Backend DI cleanup"). Dependencies
flow in via constructor kwargs; no post-construction
``service._attr = dep`` back-fills.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.config import PROJECT_ROOT, STATIC_DIR, TTS_DIR, settings
from backend.database import init_db
from backend.services.automation_engine import AutomationEngine
from backend.services.event_logger import EventLogger
from backend.services.fauxmo_service import FauxmoService
from backend.services.hue_service import HueService
from backend.services.hue_v2_service import HueV2Service
from backend.services.library_import_service import LibraryImportService
from backend.services.mode_volume_service import ModeVolumeService
from backend.services.morning_routine import MorningRoutineService
from backend.services.music_mapper import MusicMapper
from backend.services.recommendation_service import RecommendationService
from backend.services.scheduler import AsyncScheduler, ScheduledTask
from backend.services.lol_champion_service import LoLChampionService
from backend.services.screen_sync import LaptopLoopbackCapture, ScreenSyncService
from backend.services.sonos_service import SonosService
from backend.services.tts_service import TTSService
from backend.services.websocket_manager import WebSocketManager
from backend.utils.logger import logger  # noqa: F401 — triggers logging setup

# Logger name kept as "home_hub.main" intentionally — these lifecycle
# messages predate this module, and existing log-tail / alert tooling
# (if any) keys on the historical name. A future commit can rename it
# alongside whatever consumes these lines.
app_logger = logging.getLogger("home_hub.main")


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
    # pc_agent (or laptop loopback). Holds per-light smoothing state and
    # applies colors to the two bedroom lamps. L2 ← left half, L5 ← right
    # half (dual-region sync). The capture loop lives elsewhere.
    screen_sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
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
    # Wire weather into the event logger so log_light_adjustment captures
    # weather_class for the LightingLearner weather-aware retrain (Layer 3).
    event_logger.set_weather_service(weather_service)
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
    # One-shot recalc on boot. Cheap (DB scan + EMA over ≤14d of user-trigger
    # rows, typically <2s). Ensures the persisted lighting_prefs.json reflects
    # the *current* learning logic — important when the collapse / EMA rules
    # change between deploys and the nightly recalc at 04:00 hasn't run yet.
    try:
        await lighting_learner.recalculate()
    except Exception:
        logger.exception("Boot-time lighting_learner.recalculate() failed")

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

    # Presence fusion — multi-source attendance / zone / posture merger.
    # No dependencies; sources register against it after they're built
    # (Latitude camera_service callback below, desktop pc_agent via
    # /api/camera/observation POST endpoint). Constructed unconditionally
    # so the merged surface is always available — when no source has
    # reported yet, it degrades to "not at desk, no posture committed",
    # matching the no-camera baseline.
    from backend.services.presence_fusion import PresenceFusion
    presence = PresenceFusion()
    app.state.presence = presence
    app_logger.info("Presence fusion initialized")

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
        ml_logger=ml_logger,
    )
    app.state.rule_engine = rule_engine

    # Music mapper — takes music_bandit via constructor (was back-filled).
    # Phase B (2026-05-12): weather_service threaded in so the bandit picks
    # context-aware playlists per (mode, period, weather_class, title) arm key.
    music_mapper = MusicMapper(
        sonos_service=sonos,
        ws_manager=ws_manager,
        event_logger=event_logger,
        music_bandit=music_bandit,
        weather_service=weather_service,
        # GAMEDAY_SPEC §10.3 — pregameday→gameday transition handler needs
        # TTS access for the stakes-tier announcement at T-30.
        tts_service=tts,
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
        sonos=sonos,
    )
    await ambient_sound.load_from_db()
    ambient_sound.scan_sounds()
    app.state.ambient_sound = ambient_sound

    # Effect manager — owns Hue v2 dynamic-effect lifecycle (stop/start
    # ordering, same-effect skip, weather-effect fallback). Constructed
    # before AutomationEngine so it can be passed in via DI.
    from backend.services.effect_manager import EffectManager
    effect_manager = EffectManager(
        hue_v2=hue_v2, weather_service=weather_service,
    )
    app.state.effect_manager = effect_manager

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
        effect_manager=effect_manager,
        presence_fusion=presence,
    )
    app.state.automation = automation
    # Off-dashboard skip emitter — wire after both event_logger and
    # automation exist so poll_state_loop can label skips with the
    # current mode. Pre-2026-05-25, only dashboard ws skips emitted
    # event_type="skip" rows; physical/Alexa/Sonos-app skips were
    # invisible to the music bandit's reward signal.
    sonos.attach_event_logger(event_logger, automation)
    await automation.load_scene_overrides()
    await automation.load_dnd_state()
    await automation.load_override_state()
    # Rehydrate the latest pending rule-suggestion across restarts. Without
    # this, a deploy mid-suggestion would drop the in-memory pointer and
    # the kiosk would lose the Home banner on WS reconnect. Mirrors the
    # load_override_state() pattern above.
    await rule_engine.restore_pending_on_boot()

    # Music mapper consults automation.is_dnd_active() to suppress auto-play
    # / weather suggestions during a DND window — wired post-construction
    # because both services need to exist before the link is established.
    music_mapper.set_automation(automation)
    ambient_sound.set_automation(automation)

    # Away mode shelved 2026-05-21 — three pivots (Hue REST polling,
    # Hue v2 SSE behavior_instance events, ARP-based LAN presence) all
    # failed against either Signify's third-party API gating or iOS sleep
    # behavior on this apartment's router topology. The Hue iOS app's
    # native Home & Away automations (which turn entire-home lights on/off
    # via bridge recipes) integrate cleanly with the existing
    # `_check_external_off` mechanism in automation_engine.run_loop —
    # autonomous setters skip while the apartment is dark. See memory
    # entry `project_away_mode_shelved.md` before attempting another
    # presence-detection design.

    # Mode-change callbacks — runtime event subscriptions, separate from
    # dependency injection. Registered after automation exists.
    #
    # GameDayService (Phase B slice A) does NOT register a mode-change
    # callback — it sets modes (T-30 pre-kickoff, T+30 post-game clear),
    # it doesn't listen. Its instantiation lives further down with the
    # other late-stage services (~line 620). Music for `gameday` comes via
    # mode_playlists + MusicMapper's existing on_mode_change auto-play —
    # no callback ordering surgery needed. See docs/GAMEDAY_SPEC.md §3.2.
    automation.register_on_mode_change(music_mapper.on_mode_change_wrapper)
    automation.register_on_mode_change(ambient_sound.on_mode_change_wrapper)
    automation.register_on_mode_change(ml_logger.on_mode_change)

    # League champion → bedroom-lamp color override. Service is gaming-mode-
    # gated internally; the mode-change callback clears its state when the
    # engine leaves gaming so screen-sync resumes on the bedroom lamps.
    lol_champion = LoLChampionService(hue_service=hue, automation_engine=automation)
    app.state.lol_champion_service = lol_champion
    automation.register_on_mode_change(lol_champion.on_mode_change)

    # Per-mode Sonos volume curves (GH#17). Fades the speaker to a mode-shaped
    # target on transition. Pure-policy split: see mode_volume_policy.py.
    # ambient_sound passed in so the service can skip its fade when ambient is
    # mirroring (ambient has its own per-mode volume policy, see
    # ambient_sound_service._sync_sonos_volume).
    mode_volume = ModeVolumeService(
        sonos, automation, tts_service=tts, ambient_sound_service=ambient_sound,
    )
    automation.register_on_mode_change(mode_volume.on_mode_change)
    app.state.mode_volume = mode_volume

    # "Good night" TTS on entry into sleeping mode. Suppressed when the
    # watching_sleep_guard fires (Anthony's already asleep — speaking
    # "Good night" at 03:00 would wake him up). The callback fan-out
    # only passes `mode`, so we read the source off the engine itself —
    # set_manual_override stamps `_override_source` BEFORE firing
    # callbacks, so `automation.override_source` is current.
    async def _sleeping_tts(new_mode: str, **_kwargs) -> None:
        if new_mode != "sleeping":
            return
        if automation.override_source == "watching_sleep_guard":
            return
        asyncio.create_task(tts.speak("Good night.", volume=10))

    automation.register_on_mode_change(_sleeping_tts)

    # Pregameday → gameday audio dispatch (GAMEDAY_SPEC §10.3). Fires at the
    # T-30 flip when the engine transitions from pregameday into gameday.
    # Closure-tracks the previous mode since callback fan-out only passes
    # the new mode. Reads playoff stakes from app_settings (populated by
    # the Tuesday playoff_state_refresh ScheduledTask in Phase 4) and
    # dispatches TTS + (conditionally) Sonos hype via music_mapper.
    _pregame_state = {"prev_mode": None}

    async def _pregame_audio_dispatch(new_mode: str, **_kwargs) -> None:
        prev = _pregame_state["prev_mode"]
        _pregame_state["prev_mode"] = new_mode
        if not (prev == "pregameday" and new_mode == "gameday"):
            return
        try:
            from backend.services.pregame_audio_policy import compute_pregame_audio
        except ImportError:
            app_logger.exception("pregame_audio_policy import failed")
            return

        # Pull stakes + game context. Defensive: missing/stale state falls
        # back to "standard" tier, which announces the kickoff but skips hype.
        playoff_state = await load_setting("gameday_playoff_state") or {}
        try:
            game = app.state.gameday.current_state()
        except Exception:
            game = None
        opponent = (game and game.opponent) or "the opponent"

        # Apartment-context suppressions read off the engine in real time
        # (sleeping mode + DND silence audio even for a fully-committed game).
        decision = compute_pregame_audio(
            opponent=opponent,
            season_week=int(playoff_state.get("season_week") or 1),
            is_preseason=bool(playoff_state.get("is_preseason") or False),
            playoff_probability=playoff_state.get("playoff_probability"),
            is_eliminated=bool(playoff_state.get("is_eliminated") or False),
            division_gap_games=playoff_state.get("division_gap_games"),
            sleeping_mode=(automation.current_mode == "sleeping"),
            dnd_active=automation.is_dnd_active(),
            line_index=int(playoff_state.get("season_week") or 0),
        )
        app_logger.info(
            "pregame audio: tier=%s tts=%s sonos_hype=%s opponent=%s",
            decision.tier, bool(decision.tts_line),
            decision.sonos_hype_play, opponent,
        )
        asyncio.create_task(music_mapper.dispatch_pregame_audio(decision))

    automation.register_on_mode_change(_pregame_audio_dispatch)

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

    # Nightly ML retrain at 4:00 AM
    scheduler.add_task(ScheduledTask(
        name="ml_nightly_training",
        hour=4,
        minute=0,
        weekdays=[0, 1, 2, 3, 4, 5, 6],
        callback=model_manager.retrain_all,
        enabled=True,
    ))

    # Apartment Logbook — nightly narrative journal at 2:00 AM.
    # Reads yesterday's events from activity_events / light_adjustments /
    # sonos_playback_events / scene_activations and writes a Markdown file
    # to data/journal/YYYY-MM-DD.md. Pure read; no actuation.
    from backend.services.journal_service import JournalService
    journal_dir = PROJECT_ROOT / "data" / "journal"
    journal_service = JournalService(journal_dir=journal_dir)
    app.state.journal_service = journal_service

    scheduler.add_task(ScheduledTask(
        name="journal_nightly",
        hour=2,
        minute=0,
        weekdays=[0, 1, 2, 3, 4, 5, 6],
        callback=journal_service.run_nightly,
        enabled=True,
    ))

    # Nightly fusion weight tuning at 3:30 AM — runs 30 min before the model
    # retrain so yesterday's fusion decisions (which carry per-source signal
    # details in `factors`) feed into the weight update before the newly
    # trained models start producing tomorrow's decisions.
    async def fusion_weight_tuning() -> None:
        metrics = await ml_logger.compute_per_source_metrics(days=14)
        if metrics:
            acc = {src: r["accuracy"] for src, r in metrics.items()}
            confidence_fusion.update_weights_from_accuracy(acc)
            persisted = await ml_logger.persist_accuracy_metrics(
                metrics, window_days=14,
            )
            app_logger.info(
                "fusion_weight_tuning: updated %d weights, persisted %d ml_metrics rows",
                len(acc), persisted,
            )
        else:
            app_logger.info(
                "fusion_weight_tuning: no usable per-source accuracy data yet — weights unchanged, no rows persisted",
            )

    scheduler.add_task(ScheduledTask(
        name="fusion_weight_tuning",
        hour=3,
        minute=30,
        weekdays=[0, 1, 2, 3, 4, 5, 6],
        callback=fusion_weight_tuning,
        enabled=True,
    ))

    # Predictor auto-demote at 3:45 AM — counterpart to the diversity gate
    # on /predictor/promote. If a promoted predictor's recent shadow
    # outputs collapse (single-class / near-single-class over 7d), flip
    # back to shadow automatically so the apartment doesn't get driven by
    # a degenerate model. Anti-flap baked into check_and_demote_if_degenerate
    # (only confirmed-collapse reasons trigger; insufficient_samples /
    # no_predictions are treated as "don't know yet"). Runs after weight
    # tuning (3:30) and before the 4:00 retrain so the upcoming retrain
    # has a chance to fix the underlying issue.
    async def predictor_auto_demote_check() -> None:
        if behavioral_predictor is None:
            return
        result = await behavioral_predictor.check_and_demote_if_degenerate(ml_logger)
        app_logger.info("predictor_auto_demote_check: %s", result)

    scheduler.add_task(ScheduledTask(
        name="predictor_auto_demote_check",
        hour=3,
        minute=45,
        weekdays=[0, 1, 2, 3, 4, 5, 6],
        callback=predictor_auto_demote_check,
        enabled=True,
    ))

    # 90-day event-table retention sweep. CLAUDE.md documents the policy
    # but nothing was deleting old rows — activity_events, light_adjustments,
    # sonos_playback_events, scene_activations, and ml_decisions all grew
    # unbounded. Weekly aggregation into summaries (per spec) is deferred;
    # this task just keeps the rolling window honest. Runs at 03:00 — after
    # the journal (02:00) has read yesterday's events and before the fusion
    # weight tuning (03:30) reads its 14-day window.
    async def retention_sweep() -> None:
        from sqlalchemy import text as _sql_text
        from backend.database import async_session
        cutoff_sql = "datetime('now', '-90 days')"
        targets = (
            ("activity_events", "timestamp"),
            ("light_adjustments", "timestamp"),
            ("sonos_playback_events", "timestamp"),
            ("scene_activations", "timestamp"),
            ("ml_decisions", "timestamp"),
        )
        deleted_total = 0
        async with async_session() as session:
            for table, ts_col in targets:
                try:
                    result = await session.execute(
                        _sql_text(
                            f"DELETE FROM {table} WHERE {ts_col} < {cutoff_sql}"
                        )
                    )
                    deleted_total += result.rowcount or 0
                except Exception as exc:
                    app_logger.warning(
                        "retention_sweep: failed to prune %s: %s", table, exc,
                    )
            await session.commit()
        app_logger.info(
            "retention_sweep: pruned %d rows older than 90 days", deleted_total,
        )

    scheduler.add_task(ScheduledTask(
        name="retention_sweep",
        hour=3,
        minute=0,
        weekdays=[0, 1, 2, 3, 4, 5, 6],
        callback=retention_sweep,
        enabled=True,
    ))

    # Playoff-state refresh (GAMEDAY_SPEC §10.5) — Tuesday 06:00 ET. Pulls
    # ESPN team schedule, derives record + season_week, persists to
    # app_settings["gameday_playoff_state"] so the pregameday audio handler
    # has real stakes inputs. Phase 4 ships with playoff_probability=None
    # (graceful fallback to standard tier); future iteration backfills it
    # from ESPN's predictor endpoint.
    from backend.services.playoff_state_refresh import (
        refresh_playoff_state,
        REFRESH_HOUR_ET,
        REFRESH_MINUTE_ET,
        REFRESH_WEEKDAY,
    )

    async def playoff_state_refresh() -> None:
        # routines.save_setting handles the DB write — passed as a callable
        # so playoff_state_refresh stays DB-layer-agnostic for testing.
        from backend.api.routes.routines import save_setting
        await refresh_playoff_state(save_setting)

    scheduler.add_task(ScheduledTask(
        name="playoff_state_refresh",
        hour=REFRESH_HOUR_ET,
        minute=REFRESH_MINUTE_ET,
        weekdays=[REFRESH_WEEKDAY],
        callback=playoff_state_refresh,
        enabled=True,
    ))

    app.state.scheduler = scheduler

    # Persist scheduler task status across restarts so /health.scheduler_tasks
    # survives deploys (without this, last_run resets to None on every boot
    # and overnight runs look like "never fired" from the dashboard).
    from backend.api.routes.routines import load_setting, save_setting
    scheduler.set_persistence(save_setting)
    await scheduler.load_state(load_setting)

    # Game Day service (Phase B slice A) — ESPN polling + Colts game state
    # + auto-flip to gameday mode at T-30 / auto-clear at T+30. Subscribers
    # for play events / state transitions register here in later slices
    # (Slice B: CelebrationOrchestrator). Public read-only via /api/gameday/*.
    from backend.services.gameday_service import GameDayService
    gameday = GameDayService(
        automation_engine=automation,
        ws_manager=ws_manager,
    )
    await gameday.connect()
    app.state.gameday = gameday
    app_logger.info("GameDayService initialized")

    # CelebrationOrchestrator (Phase B Slice B) — subscribes to GameDayService
    # play + state-transition events and runs light + TTS celebration sequences.
    # Cooldown enforced internally (8s between any two sequences). Light
    # sequence values are placeholders; iterate with lighting-curator subagent
    # before preseason 2026-08-13 (regular season opens Sunday 2026-09-13).
    from backend.services.celebration_orchestrator import CelebrationOrchestrator
    celebration = CelebrationOrchestrator(
        hue_service=hue,
        tts_service=tts,
        ws_manager=ws_manager,
        gameday_service=gameday,
        automation_engine=automation,
        # camera_service late-bound below — opt-in service is constructed
        # later in this lifespan; we call set_camera_service() once it's
        # available.
        camera_service=None,
        # event_logger mirrors every set_light from a celebration sequence
        # into the `light_adjustments` table (trigger="celebration:<key>"),
        # so gameday choreography shows up in get_state_history / the
        # nightly journal / DB analytics. Without this, those writes only
        # land in journalctl.
        event_logger=event_logger,
    )
    gameday.register_on_play_event(celebration.on_play_event)
    gameday.register_on_state_transition(celebration.on_state_transition)
    app.state.celebration_orchestrator = celebration
    app_logger.info("CelebrationOrchestrator subscribed to GameDayService")

    # NotifierService — pushes "what just changed and why" to the user's
    # desktop (custom toast widget over WS) and phone (ntfy.sh push).
    # Watches mode flips + effective brightness shifts on the engine and
    # surfaces top-3 fusion factors as the "why." Suppression: DND,
    # 10s coalesce, 30s boot delay, and user-initiated mode flips
    # (api:* / manual / alexa:* / guest:*) — Anthony pressed it, no toast.
    from backend.services.notifier_service import NotifierService
    notifier = NotifierService(
        ws_manager=ws_manager,
        automation_engine=automation,
        ntfy_topic=settings.NTFY_TOPIC,
        ntfy_server=settings.NTFY_SERVER,
    )
    await notifier.start()
    app.state.notifier = notifier
    automation.register_on_mode_change(notifier.on_mode_change)

    # Late-bind brightness-suggestion collaborators on rule_engine. Built
    # in this order because rule_engine is constructed early (line ~274)
    # but the notifier comes online here. Public base url defaults to the
    # Latitude's LAN address — ntfy.sh action buttons hit it directly from
    # the iPhone on Wi-Fi (no auth needed via require_api_key's RFC1918
    # bypass) and the `X-API-Key` header travels for cellular round-trips.
    rule_engine.set_brightness_suggestion_deps(
        lighting_learner=lighting_learner,
        notifier_service=notifier,
        api_key=settings.HOME_HUB_API_KEY,
        public_base_url=(
            f"http://{settings.LOCAL_IP}:8000"
            if getattr(settings, "LOCAL_IP", None)
            else "http://192.168.1.210:8000"
        ),
    )

    # Background tasks
    tasks: list[asyncio.Task] = []

    # Wire heartbeat registry into every service that runs a polling
    # loop. Each service publishes liveness via .tick(name) once per
    # iteration; /health reads heartbeats.snapshot() to flag stale tasks.
    event_logger.set_heartbeat_registry(heartbeats)
    hue.set_heartbeat_registry(heartbeats)
    hue_v2.set_heartbeat_registry(heartbeats)
    sonos.set_heartbeat_registry(heartbeats)
    automation.set_heartbeat_registry(heartbeats)
    scheduler.set_heartbeat_registry(heartbeats)
    rule_engine.set_heartbeat_registry(heartbeats)

    # Register expected polling cadences. Camera self-registers on enable
    # and deregisters on disable / pause (handled in CameraService) so
    # legitimate downtime isn't flagged stale.
    heartbeats.register("event_logger_retry", 30.0)
    if hue.connected:
        heartbeats.register("hue", 0.5)
    if hue_v2.connected and hue_v2._v2_to_v1:
        # SSE delivers events on physical light changes (sub-second cadence
        # during a slider drag, otherwise minutes-quiet). Stale window
        # budgets the full silence→reconnect cycle: 90s silence timeout
        # (_STREAM_SILENT_RECONNECT_SECONDS) + 1s backoff sleep + up to
        # ~10s for TCP+TLS handshake against the bridge's self-signed
        # cert under load. /health only goes degraded if the reconnect
        # cycle itself can't establish a working stream in time.
        heartbeats.register("hue_v2_stream", 100.0)
    if sonos.connected:
        heartbeats.register("sonos", 2.0)
    heartbeats.register("automation", 60.0)
    heartbeats.register("scheduler", 30.0)
    heartbeats.register("rule_engine", 6 * 3600.0)
    heartbeats.register("transit_lighting", 2.0)
    heartbeats.register("desk_exit_kitchen", 2.0)

    # Event logger retry task was started above — register for teardown here.
    tasks.append(event_logger_retry_task)

    if hue.connected:
        tasks.append(asyncio.create_task(hue.poll_state_loop(ws_manager)))

    # v2 EventStream — pushes external light changes (Hue app, wall dimmer)
    # at ~150ms latency instead of waiting for the next 0.5s v1 poll. The
    # stream loop is fail-soft: if the bridge SSE drops, v1 polling
    # automatically returns to 0.5s cadence (via set_v2_stream_active).
    if hue_v2.connected and hue_v2._v2_to_v1:
        tasks.append(asyncio.create_task(
            hue_v2.event_stream_loop(ws_manager, hue)
        ))
    else:
        app_logger.info(
            "v2 EventStream not spawned (hue_v2.connected=%s, mapped=%d)",
            hue_v2.connected, len(hue_v2._v2_to_v1),
        )

    if sonos.connected:
        tasks.append(asyncio.create_task(sonos.poll_state_loop(ws_manager)))

    tasks.append(asyncio.create_task(automation.run_loop()))
    tasks.append(asyncio.create_task(scheduler.run_loop()))
    tasks.append(asyncio.create_task(rule_engine.run_generation_loop()))
    # Hourly scan for weather-aware brightness-suggestion candidates.
    # See LightingPreferenceLearner.scan_for_suggestions + RuleEngineService
    # .scan_and_emit_brightness_suggestions for the full pipeline.
    tasks.append(asyncio.create_task(rule_engine.brightness_scan_loop()))
    tasks.append(asyncio.create_task(gameday.poll_state_loop()))
    tasks.append(asyncio.create_task(notifier.poll_loop()))
    # Re-evaluate ambient sound whenever the cached weather class changes
    # (rain ↔ clear, etc.). Same loop seeds the first _evaluate ~5s after
    # startup, which re-arms playback when load_from_db rehydrates
    # last_playing=True across a deploy.
    tasks.append(asyncio.create_task(ambient_sound.weather_watch_loop()))

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
                event_logger.set_camera_service(camera_service)
                ambient_sound.set_camera_service(camera_service)
                # Feed PresenceFusion the Latitude lane. Desktop lane is
                # POST-driven via /api/camera/observation.
                camera_service.register_observation_callback(presence.on_observation)
                # Store the poll task on the service so close()/respawn
                # can cancel + await it cleanly. Also append to the
                # lifespan tasks list so shutdown waits on it.
                camera_service._poll_task = asyncio.create_task(camera_service.poll_loop())
                tasks.append(camera_service._poll_task)
                app_logger.info("Camera presence detection started")
            else:
                app_logger.warning("Camera service failed to start (webcam unavailable?)")
        except ImportError:
            app_logger.warning("mediapipe/opencv not installed — camera service disabled")
    else:
        app_logger.info("Camera service disabled (camera_enabled=false)")

    # Camera watchdog — supervises the poll_loop and respawns the service
    # when the lane goes silent (V4L2 wedge after suspend/resume, failed
    # boot start with camera_enabled=true, etc.). Always running; reads
    # camera_enabled live, so a user enabling the camera later still gets
    # supervision without a restart. Inert when disabled.
    try:
        from backend.services.camera_service import camera_watchdog_loop
        tasks.append(asyncio.create_task(camera_watchdog_loop(app)))
        app_logger.info("Camera watchdog started")
    except ImportError:
        # camera_service import only fails when mediapipe/opencv are
        # missing — same condition that disables the service above.
        pass

    # Late-bind camera into the celebration orchestrator. Used by the
    # volume policy to dial TTS down when no one is home (camera absent
    # ≥5 minutes). When camera is disabled / unavailable, the policy
    # treats the apartment as occupied (no penalty).
    celebration.set_camera_service(getattr(app.state, "camera_service", None))

    # Transit lighting — brighten kitchen/living-room when Anthony steps out
    # of the bedroom (camera detects absence). 10-min hard timeout protects
    # against runaway if the camera mis-fires.
    from backend.services.transit_lighting_service import TransitLightingService
    transit_lighting = TransitLightingService(
        automation_engine=automation,
        camera_service=getattr(app.state, "camera_service", None),
        presence_fusion=presence,
    )
    transit_lighting.set_heartbeat_registry(heartbeats)
    app.state.transit_lighting = transit_lighting
    tasks.append(asyncio.create_task(transit_lighting.poll_loop()))
    app_logger.info("Transit lighting service started")

    # Desk-exit kitchen — when Anthony leaves the desk in productive evening/
    # night, brighten the kitchen pair (L3 + L4) and hold until he returns.
    # Distinct from transit (kitchen-only, time-of-day scaled, hold-until-
    # return instead of 10-min auto-fade). Transit cedes the kitchen pair
    # during the same window so the two don't fight.
    from backend.services.desk_exit_kitchen_service import DeskExitKitchenService
    desk_exit_kitchen = DeskExitKitchenService(
        automation_engine=automation,
        camera_service=getattr(app.state, "camera_service", None),
        presence_fusion=presence,
    )
    desk_exit_kitchen.set_heartbeat_registry(heartbeats)
    app.state.desk_exit_kitchen = desk_exit_kitchen
    tasks.append(asyncio.create_task(desk_exit_kitchen.poll_loop()))
    app_logger.info("Desk-exit kitchen service started")

    # AI Personality Layer (Phase A — shadow-log only).
    # EmotionService consumes face blendshapes from camera_service when
    # emotion_enabled and persists the derived mood vector to mood_samples.
    # No actuation in Phase A; gated by personality_enabled + emotion_enabled
    # settings (both default false). Mood-ring light + vibe intent + toast
    # suggestions layer on in later phases.
    try:
        from backend.database import async_session as personality_session_factory
        from backend.services.personality.emotion_service import EmotionService
        emotion_service = EmotionService(
            ws_manager=ws_manager,
            automation_engine=automation,
            camera_service=getattr(app.state, "camera_service", None),
            session_factory=personality_session_factory,
        )
        # Compose the two opt-in toggles: personality_enabled is the master
        # kill switch; emotion_enabled is the sub-toggle for the camera-
        # driven half. Both must be true for EmotionService to actually run.
        personality_setting = await load_setting("personality_enabled")
        emotion_setting = await load_setting("emotion_enabled")
        emotion_on = (
            (personality_setting or {}).get("enabled", False)
            and (emotion_setting or {}).get("enabled", False)
        )
        await emotion_service.start(emotion_enabled=emotion_on)
        app.state.emotion_service = emotion_service
        app_logger.info(
            "EmotionService initialized (enabled=%s)", emotion_on,
        )
    except Exception:
        app_logger.exception("EmotionService failed to initialize — personality disabled")

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
    await _safe_shutdown("gameday", gameday.close)
    notifier_inst = getattr(app.state, "notifier", None)
    if notifier_inst is not None:
        await _safe_shutdown("notifier", notifier_inst.close)
    camera = getattr(app.state, "camera_service", None)
    if camera is not None:
        await _safe_shutdown("camera", camera.close)
    transit = getattr(app.state, "transit_lighting", None)
    if transit is not None:
        await _safe_shutdown("transit_lighting", transit.close)
    desk_exit = getattr(app.state, "desk_exit_kitchen", None)
    if desk_exit is not None:
        await _safe_shutdown("desk_exit_kitchen", desk_exit.close)
    emotion = getattr(app.state, "emotion_service", None)
    if emotion is not None:
        await _safe_shutdown("emotion_service", emotion.close)
