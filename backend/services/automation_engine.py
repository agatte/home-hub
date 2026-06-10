"""
Autonomous light engine — time-based + activity-driven light automation.

Combines time-of-day rules with PC activity detection and ambient noise
monitoring to automatically set the optimal lighting. Manual overrides from
the dashboard take priority and persist until the next activity change or
a 4-hour timeout.

Supports per-light control for modes that need different lights doing
different things (e.g., watching mode: bedroom lamp syncs to screen,
others off; fire-and-ice party: warm/cool split across rooms).
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.config import settings

# Mode priority, autonomous-source sets, schedule dataclasses, time rules, and
# tuning constants live in automation_constants.py (step 1 of the GH#86
# decomposition). Imported with explicit `X as X` re-export aliases so existing
# `from backend.services.automation_engine import X` callers (tests, routes)
# keep working and ruff's unused-import fix leaves them alone.
from backend.services.automation_constants import (
    ASLEEP_STAMP_FAILSAFE_HOURS as ASLEEP_STAMP_FAILSAFE_HOURS,
    AUTONOMOUS_PUSH_SOURCES as AUTONOMOUS_PUSH_SOURCES,
    DND_STATE_KEY as DND_STATE_KEY,
    IDLE_AMBIENT_RELAX_DWELL_SECONDS as IDLE_AMBIENT_RELAX_DWELL_SECONDS,
    MODE_PRIORITY as MODE_PRIORITY,
    PRESERVE_PER_LIGHT_OVERRIDE_SOURCES as PRESERVE_PER_LIGHT_OVERRIDE_SOURCES,
    RECENT_PROCESS_WORKING_SECONDS as RECENT_PROCESS_WORKING_SECONDS,
    RESCUE_OVERRIDE_SOURCES as RESCUE_OVERRIDE_SOURCES,
    SCREEN_SYNC_FRESH_SECONDS as SCREEN_SYNC_FRESH_SECONDS,
    SCREEN_SYNC_MODES as SCREEN_SYNC_MODES,
    SOURCE_STALE_SECONDS as SOURCE_STALE_SECONDS,
    TZ as TZ,
    USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS as USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS,
    WATCHING_SLEEP_GUARD_DWELL_SECONDS as WATCHING_SLEEP_GUARD_DWELL_SECONDS,
    WATCHING_SLEEP_GUARD_OVERRIDE_MIN_AGE_SECONDS as WATCHING_SLEEP_GUARD_OVERRIDE_MIN_AGE_SECONDS,
    WEEKDAY_TIME_RULES as WEEKDAY_TIME_RULES,
    WEEKEND_TIME_RULES as WEEKEND_TIME_RULES,
    ZONE_POSTURE_RULE_DWELL_SECONDS as ZONE_POSTURE_RULE_DWELL_SECONDS,
    ZONE_POSTURE_RULE_DWELL_SOCIAL_SECONDS as ZONE_POSTURE_RULE_DWELL_SOCIAL_SECONDS,
    ZONE_POSTURE_RULE_ELIGIBLE_MODES as ZONE_POSTURE_RULE_ELIGIBLE_MODES,
    ZONE_POSTURE_RULE_SOCIAL_MIN_AGE_SECONDS as ZONE_POSTURE_RULE_SOCIAL_MIN_AGE_SECONDS,
    ZONE_POSTURE_RULE_WEEKEND_AFTERNOON_HOUR as ZONE_POSTURE_RULE_WEEKEND_AFTERNOON_HOUR,
    DaySchedule as DaySchedule,
    ScheduleConfig as ScheduleConfig,
)
from backend.services.dnd_manager import DndManager
from backend.services.pipeline_broadcaster import PipelineBroadcaster

logger = logging.getLogger("home_hub.automation")

# Effect lifecycle (Hue v2 dynamic effects + weather-effect mapping +
# WEATHER_SKIP_MODES) lives in effect_manager.py. Re-exported below at
# module scope for back-compat with callers that import them from this
# module.

# Lighting tunables + the per-light state lookup table live in
# light_state_calculator.py. Re-exported below at module scope for
# back-compat with callers that imported them from this module.
from backend.services.light_state_calculator import (  # noqa: E402
    ACTIVITY_LIGHT_STATES,
    ALL_LIGHT_IDS,
    BED_RECLINED_L1_NIGHT_DEFAULT,
    BED_RECLINED_L1_RATIO,
    BED_RECLINED_L2_WATCHING_BRI,
    DEFAULT_MODE_BRIGHTNESS,
    EFFECT_AUTO_MAP,
    LUX_STALE_SECONDS,
    MODE_TRANSITION_TIME,
    WINDDOWN_RAMP_MINUTES,
    ZONE_POSTURE_FRESHNESS_SECONDS,
    adjust_single_light as _adjust_single_light_pure,
    apply_brightness_multiplier as _calc_apply_brightness_multiplier,
    apply_functional_weather_brightness as _calc_apply_functional_weather_brightness,
    apply_lux_multiplier as _calc_apply_lux_multiplier,
    apply_weather_adjust as _calc_apply_weather_adjust,
    apply_zone_overlay as _calc_apply_zone_overlay,
    classify_weather as _classify_weather_pure,
    get_mode_state_table as _get_mode_state_table,
    get_time_period as _calc_get_time_period,
    lerp_light_state as _lerp_light_state,
    lux_to_multiplier,
    morning_ramp as _morning_ramp,
    resolve_activity_state as _resolve_activity_state,
)
from backend.services.effect_manager import (  # noqa: E402
    EffectManager,
    WEATHER_SKIP_MODES,
)


def _extract_game_factor(factors: Optional[list[dict]]) -> Optional[str]:
    """Pull the ``game`` factor's value off an activity report's factor list.

    The PC-agent emits ``{"key": "game", "value": "<slug>", ...}`` when a game
    with a dedicated lighting profile is active (see
    ``pc_agent.activity_detector._resolve_active_game``). Returns the stripped
    slug, or None when no game factor is present. Mirrors ``lol_champion_service.
    _extract_champion``.
    """
    if not factors:
        return None
    for f in factors:
        if not isinstance(f, dict) or f.get("key") != "game":
            continue
        val = f.get("value") or f.get("display")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


class AutomationEngine:
    """
    Combines time-of-day rules and activity reports to control lights.

    The engine runs a background loop that checks every 60 seconds whether
    the time-based state needs updating. Activity reports from the PC agent
    and ambient monitor override time-based rules. Manual overrides from
    the dashboard take highest priority.
    """

    def __init__(
        self,
        hue,
        hue_v2,
        ws_manager,
        schedule_config: Optional[ScheduleConfig] = None,
        mode_brightness: Optional[dict[str, float]] = None,
        event_logger=None,
        weather_service=None,
        # Cross-service collaborators — main.py constructs these in
        # dependency order and passes them in. All default None so
        # tests can build an engine with just the hardware deps.
        sonos=None,
        screen_sync=None,
        music_mapper=None,
        rule_engine=None,
        lighting_learner=None,
        ml_logger=None,
        behavioral_predictor=None,
        confidence_fusion=None,
        effect_manager=None,
        presence_fusion=None,
    ) -> None:
        self._hue = hue
        self._hue_v2 = hue_v2
        self._ws_manager = ws_manager
        self._event_logger = event_logger
        self._weather_service = weather_service
        self._sonos = sonos
        self._music_mapper = music_mapper
        self._rule_engine = rule_engine
        self._lighting_learner = lighting_learner
        self._ml_logger = ml_logger
        self._behavioral_predictor = behavioral_predictor
        self._presence_fusion = presence_fusion
        self._effect_manager = effect_manager or EffectManager(
            hue_v2=hue_v2, weather_service=weather_service,
        )

        # Weather condition tracking for music suggestions
        self._last_weather_condition: Optional[str] = None

        # Current state
        self._current_mode: str = "idle"
        # Active game slug (from the PC-agent's `game` factor) when a game with
        # a dedicated lighting profile is running in gaming mode; None otherwise.
        # Drives GAME_LIGHT_PROFILES (e.g. Rust "Rusted Ember"). Kept in lockstep
        # with _current_mode — set/cleared alongside it in report_activity.
        self._current_game: Optional[str] = None
        self._mode_source: str = "time"
        self._manual_override: bool = False
        self._override_mode: Optional[str] = None
        self._override_source: Optional[str] = None
        self._override_time: Optional[datetime] = None
        self._last_activity: Optional[str] = None
        self._last_activity_change: Optional[datetime] = None
        # Per-source liveness for the priority guard (source → last report time).
        self._last_mode_source_report_at: dict[str, datetime] = {}

        # Last time the PC agent reported mode=working. Independent of camera
        # signal — used by late-night rescue as a parallel veto so a transient
        # camera blip doesn't strand the user in relax while they're actively
        # at the keyboard. See RECENT_PROCESS_WORKING_SECONDS.
        self._last_process_working_at: Optional[datetime] = None

        # Timestamp of the most recent transition INTO `idle`. Cleared on any
        # exit from idle. Used by the ambient_relax setter to require a
        # continuous idle window (IDLE_AMBIENT_RELAX_DWELL_SECONDS) before
        # pushing to relax. Set/cleared in report_activity below.
        self._idle_entered_at: Optional[datetime] = None

        # Per-light state tracking for deduplication
        self._last_applied_per_light: dict[str, dict] = {}

        # Per-light manual overrides — maps light_id → timestamp
        # Lights in this dict are protected from automation until next mode change
        self._manual_light_overrides: dict[str, datetime] = {}

        # Per-light transit-lighting overrides — maps light_id → expiration deadline.
        # Set by TransitLightingService when Anthony steps out of the bedroom while
        # kitchen/living-room are dim. Cleared by the service when the camera sees
        # him again, or auto-expired at the deadline. Reconciliation skips these
        # lights the same way _manual_light_overrides does.
        self._transit_light_overrides: dict[str, datetime] = {}

        # Track if lights were turned off externally (Alexa geofence)
        self._external_off_detected: bool = False

        # Sleep fade task (gradual dim → off)
        self._sleep_fade_task: Optional[asyncio.Task] = None

        # Mode change callbacks (e.g., music mapper auto-play)
        self._on_mode_change_callbacks: list = []

        # Config
        self._enabled: bool = True
        self._override_timeout_hours: int = 4
        self._gaming_effect: Optional[str] = None
        # Active-effect tracking lives on self._effect_manager; expose it via
        # delegating properties so legacy reads (sleep-mode branch, pipeline
        # broadcast, etc.) keep working unchanged.

        # Configurable schedule and mode brightness
        self._schedule_config = schedule_config or ScheduleConfig()
        self._mode_brightness = {**DEFAULT_MODE_BRIGHTNESS, **(mode_brightness or {})}

        # Scene drift — subtle variation over time to prevent staleness
        self._scene_drift_enabled: bool = True
        self._last_drift_time: Optional[datetime] = None
        self._drift_interval_minutes: int = 30

        # Mode → scene overrides cache (loaded from DB)
        self._scene_overrides: dict[str, dict[str, str]] = {}  # {mode: {period: scene_id}}
        self._scene_override_sources: dict[str, dict[str, str]] = {}  # {mode: {period: source}}

        # Confidence fusion — passed via constructor; ensemble of process
        # / camera / audio / behavioral / rule_engine + presence voter.
        self._confidence_fusion = confidence_fusion
        self._last_fusion_result: Optional[dict] = None

        # Camera service (set when camera is enabled via /api/camera/enable
        # or by main.py boot if camera_enabled setting is true). Used by
        # _apply_lux_multiplier to read the smoothed ambient lux reading.
        self._camera_service = None
        # Zone+posture → relax rule state. `_reclined_since` tracks the
        # dwell timer (set on first poll with bed+reclined, cleared when
        # conditions or gates break). `_last_fired_at` is the re-fire
        # suppression stamp — matches live override_timeout_hours so
        # shadow cadence tracks what live cadence would look like.
        self._zone_posture_reclined_since: Optional[datetime] = None
        self._zone_posture_last_fired_at: Optional[datetime] = None
        # Watching-sleep guard rule state. Same dwell+stamp shape as the
        # zone+posture rule above. `_watching_sleep_dwell_since` is the
        # entry timestamp into (watching ∧ bed ∧ reclined ∧ late_night);
        # cleared whenever any of those four conditions break.
        self._watching_sleep_dwell_since: Optional[datetime] = None
        self._watching_sleep_guard_last_fired_at: Optional[datetime] = None
        # "User is likely still asleep" stamp — set on any tick where the
        # watching_sleep_guard sees a confident bed+reclined observation
        # during watching mode. Consumed by `_is_likely_still_asleep`,
        # which gates the morning brightness ramp (idle's curve climbing
        # 80→196 between 06:00–07:00) and the watching-mode late_night→day
        # period transition (the L2/L5 jump from bri≈20 to bri=91 at
        # 06:00:06 on 2026-05-15). Reference incident: 2026-05-14 →
        # 2026-05-15, watching held all night, both brightness paths
        # combined to wake the user at ~06:30. Released by either
        # attendance signal (camera zone=desk fresh, PC working recent)
        # or the 12h failsafe.
        self._last_bed_reclined_during_watching_at: Optional[datetime] = None
        # User-respect cooldown stamp — set when the user clears an override
        # via api:* (dashboard "auto" button). While within the cooldown,
        # set_manual_override blocks autonomous-source pushes (rescue, rule,
        # fusion, predictor) so the user's "auto" press actually sticks.
        self._user_cleared_override_at: Optional[datetime] = None
        # Last applied lux multiplier — if the new multiplier is within
        # LUX_MULT_EPSILON of this, we keep using the old value so the final
        # state dict is identical and the per-light dedupe at _apply_state
        # naturally skips the bridge write.
        self._last_lux_multiplier: float = 1.0
        # Last weather class the multiplier was computed against. A change
        # between ticks bypasses the LUX_MULT_EPSILON dead-band in
        # apply_lux_multiplier so weather-onset shifts (clouds→rain Δmult
        # ~0.06) aren't suppressed under the 0.08 epsilon.
        self._last_weather_class: Optional[str] = None

        # Do Not Disturb — locks autonomous state changes for a finite window.
        # User-initiated mode picks (source starts with "api:") still pass;
        # everything else (process/camera/audio reports, late-night rescue,
        # fusion, behavioral predictor, zone+posture rule, routines, music
        # auto-play, weather suggestions) gates on `is_dnd_active()`. State
        # persists to app_settings["dnd_state"] so it survives a restart.
        # State machine lives in dnd_manager.py (GH#86 step 2); the engine
        # keeps thin delegates below. WS manager is read through a getter
        # because it's assigned after construction.
        self._dnd = DndManager(ws_manager_getter=lambda: self._ws_manager)

        # Screen sync — passed via constructor; reconciliation skips lights
        # that screen sync owns so we don't fight it on watching/gaming.
        self._screen_sync = screen_sync

        # Decision pipeline — real-time snapshot of all inputs → output.
        # Ring + throttle + WS emit live in pipeline_broadcaster.py (GH#86
        # step 3); _build_pipeline_state stays on the engine (reads live
        # engine state). Getters defer to call time — WS manager is
        # assigned post-construction.
        self._pipeline = PipelineBroadcaster(
            ws_manager_getter=lambda: self._ws_manager,
            state_builder=self._build_pipeline_state,
        )

        # Heartbeat registry — set via set_heartbeat_registry from lifespan
        # so /health can flag a stalled run_loop.
        self._heartbeat = None

    def set_heartbeat_registry(self, registry) -> None:
        """Inject the heartbeat registry (called from lifespan)."""
        self._heartbeat = registry

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_mode(self) -> str:
        if self._manual_override:
            return self._override_mode or self._current_mode
        return self._current_mode

    @property
    def current_game(self) -> Optional[str]:
        """Active game slug driving GAME_LIGHT_PROFILES, or None.

        Read by the screen-color route to switch L2 into the Rust luma
        brightness-sync path. Only set in gaming mode.
        """
        return self._current_game

    @property
    def mode_source(self) -> str:
        return "manual" if self._manual_override else self._mode_source

    @property
    def manual_override(self) -> bool:
        return self._manual_override

    @property
    def override_mode(self) -> Optional[str]:
        return self._override_mode

    @property
    def override_source(self) -> Optional[str]:
        """Caller label of the active override (e.g. ``api:1.2.3.4``,
        ``gameday:auto``). None when no override is active. Used by
        GameDayService's post-game auto-clear to skip if the user
        manually overrode the gameday flip mid/post-game."""
        return self._override_source if self._manual_override else None

    @property
    def last_activity_change(self) -> Optional[datetime]:
        return self._last_activity_change

    @property
    def manual_light_overrides(self) -> dict[str, datetime]:
        """Light IDs with active per-light manual overrides."""
        return self._manual_light_overrides

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def override_timeout_hours(self) -> int:
        return self._override_timeout_hours

    @override_timeout_hours.setter
    def override_timeout_hours(self, value: int) -> None:
        self._override_timeout_hours = max(1, value)

    @property
    def gaming_effect(self) -> Optional[str]:
        return self._gaming_effect

    @gaming_effect.setter
    def gaming_effect(self, value: Optional[str]) -> None:
        self._gaming_effect = value

    # ------------------------------------------------------------------
    # Schedule + brightness config
    # ------------------------------------------------------------------

    @property
    def schedule_config(self) -> ScheduleConfig:
        return self._schedule_config

    @property
    def mode_brightness(self) -> dict[str, float]:
        return self._mode_brightness.copy()

    def update_schedule_config(self, config: ScheduleConfig) -> None:
        """Hot-reload the time schedule config. Takes effect on next loop cycle."""
        self._schedule_config = config
        self._invalidate_dedup_cache()  # Force re-apply
        logger.info("Schedule config updated")

    async def load_scene_overrides(self) -> None:
        """Load mode → scene overrides from the database into memory."""
        try:
            from backend.database import async_session
            from backend.models import ModeSceneOverride
            from sqlalchemy import select

            async with async_session() as session:
                result = await session.execute(select(ModeSceneOverride))
                overrides = result.scalars().all()

            self._scene_overrides = {}
            self._scene_override_sources = {}
            for o in overrides:
                self._scene_overrides.setdefault(o.mode, {})[o.time_period] = o.scene_id
                self._scene_override_sources.setdefault(o.mode, {})[o.time_period] = o.scene_source
            logger.info("Loaded %d mode-scene overrides", len(overrides))
        except Exception as e:
            logger.error("Failed to load scene overrides: %s", e, exc_info=True)

    def update_mode_brightness(self, brightness: dict[str, float]) -> None:
        """Hot-reload per-mode brightness multipliers."""
        self._mode_brightness = {**DEFAULT_MODE_BRIGHTNESS, **brightness}
        self._invalidate_dedup_cache()  # Force re-apply
        logger.info(f"Mode brightness updated: {brightness}")

    def _get_time_period(self) -> str:
        """Resolve the current time period via the calculator (shim)."""
        return _calc_get_time_period(self._schedule_config, datetime.now(tz=TZ))

    def get_time_period(self) -> str:
        """Public accessor for the current time period.

        Surfaced for consumers that need to mirror the engine's day/evening/
        night/late_night logic without reaching into the private shim — the
        monitor_brightness pc_agent and the /api/automation/status route.
        """
        return self._get_time_period()

    async def _sonos_is_playing(self) -> bool:
        """Check if Sonos is actively playing. Used by the late-night rescue
        so intentional late listening isn't interrupted by an auto-relax flip.
        """
        if not self._sonos:
            return False
        try:
            status = await self._sonos.get_status()
            return status.get("state") == "PLAYING"
        except Exception:
            return False

    def _build_time_rules(self, schedule: DaySchedule) -> list:
        """
        Build time rule tuples dynamically from a DaySchedule config.

        Returns the same format as the old WEEKDAY_TIME_RULES / WEEKEND_TIME_RULES
        constants: list of (start_hour, end_hour, state_or_ramp).

        Idle detection is handled by the PC activity detector, not the
        schedule — so time-based rules always provide sensible lighting
        across the day (ramp → daytime → evening → wind-down).
        """
        rules = []

        # Overnight → off (midnight to wake)
        if schedule.wake_hour > 0:
            rules.append((0, schedule.wake_hour, {"on": False}))

        # Wake → ramp start: dim warm
        if schedule.ramp_start_hour > schedule.wake_hour:
            rules.append((
                schedule.wake_hour,
                schedule.ramp_start_hour,
                {"on": True, "bri": schedule.wake_brightness, "hue": 6000, "sat": 200},
            ))

        # Morning ramp
        ramp_end_hour = schedule.ramp_start_hour + max(
            1, schedule.ramp_duration_minutes // 60
        )
        ramp_end = min(ramp_end_hour, schedule.evening_start_hour)
        rules.append((
            schedule.ramp_start_hour,
            ramp_end,
            ("morning_ramp", schedule.ramp_start_hour, schedule.ramp_duration_minutes),
        ))

        # Daytime bright neutral
        if ramp_end < schedule.evening_start_hour:
            rules.append((
                ramp_end,
                schedule.evening_start_hour,
                {"on": True, "bri": 220, "hue": 20000, "sat": 80},
            ))

        # Evening warm
        rules.append((
            schedule.evening_start_hour,
            schedule.winddown_start_hour,
            {"on": True, "bri": 180, "hue": 8000, "sat": 160},
        ))

        # Wind-down dim
        rules.append((
            schedule.winddown_start_hour,
            24,
            {"on": True, "bri": 60, "hue": 5500, "sat": 220},
        ))

        return rules

    def _apply_brightness_multiplier(
        self, state: dict[str, Any], mode: str
    ) -> dict[str, Any]:
        """Apply per-mode brightness multiplier (shim → calculator)."""
        return _calc_apply_brightness_multiplier(
            state, mode, self._mode_brightness
        )

    def set_camera_service(self, camera) -> None:
        """Wire the camera service so ambient lux can modulate brightness.

        Called by main.py at boot (if the camera is already enabled) and by
        the /api/camera/enable route when the camera is toggled on.
        """
        self._camera_service = camera

    # Backwards-compat for tests / callers referencing the classmethod form
    _lux_to_multiplier = staticmethod(lux_to_multiplier)

    def _read_fresh_camera_lux(self) -> tuple[Optional[float], Optional[float]]:
        """Return ``(ema_lux, baseline_lux)`` if the camera reading is fresh.

        Both values are ``None`` when the camera isn't wired up, is
        disabled or paused, hasn't been calibrated, or the last reading
        is older than ``LUX_STALE_SECONDS``. Engine state stays here
        rather than in the calculator so the calculator can remain
        agnostic of the camera service object.
        """
        camera = self._camera_service
        if camera is None or not getattr(camera, "enabled", False):
            return None, None
        if getattr(camera, "_paused", False):
            return None, None
        ema = getattr(camera, "ema_lux", None)
        if ema is None:
            return None, None
        last_update = getattr(camera, "last_lux_update", None)
        if last_update is None:
            return None, None
        age = (datetime.now(timezone.utc) - last_update).total_seconds()
        if age > LUX_STALE_SECONDS:
            return None, None
        return float(ema), getattr(camera, "baseline_lux", None)

    def _apply_lux_multiplier(
        self, state: dict[str, Any], mode: str
    ) -> dict[str, Any]:
        """Adjust per-light brightness by ambient lux (shim → calculator).

        Reads the fresh camera lux off ``self`` (gated on staleness +
        camera enabled/paused/calibrated). Hysteresis state lives here:
        the calculator returns the new last-multiplier value, which we
        store back on ``self._last_lux_multiplier``.

        Weather class is threaded in so the calculator can shift the
        effective baseline — storms drop the baseline so the same lux
        reading lands deeper in the curve's lift region (Layer 2 of the
        weather-aware brightness work).
        """
        ema, baseline = self._read_fresh_camera_lux()
        weather = self._get_current_weather_condition()
        new_state, new_mult, new_class = _calc_apply_lux_multiplier(
            state, mode, ema, self._last_lux_multiplier, baseline,
            weather_class=weather,
            last_weather_class=self._last_weather_class,
        )
        self._last_lux_multiplier = new_mult
        self._last_weather_class = new_class
        return new_state

    # Class-level aliases kept for back-compat with tests that read these
    # off the engine class. The canonical home for these constants is
    # backend.services.light_state_calculator.
    _BED_RECLINED_L1_NIGHT_DEFAULT = BED_RECLINED_L1_NIGHT_DEFAULT
    _BED_RECLINED_L2_WATCHING_BRI = BED_RECLINED_L2_WATCHING_BRI
    _BED_RECLINED_L1_RATIO = BED_RECLINED_L1_RATIO
    _ZONE_POSTURE_FRESHNESS_SECONDS = ZONE_POSTURE_FRESHNESS_SECONDS

    def _fresh_camera_attr(
        self, camera: Any, value_attr: str, ts_attr: str,
    ) -> Optional[str]:
        """Read ``camera.{value_attr}`` only if its commit timestamp is fresh.

        Returns ``None`` if camera is missing, the value is missing, or the
        commit timestamp is older than ``ZONE_POSTURE_FRESHNESS_SECONDS``.
        Cameras that don't expose the timestamp attribute (older fakes /
        stubs) bypass the freshness gate so existing tests continue to work.
        """
        if camera is None:
            return None
        value = getattr(camera, value_attr, None)
        if value is None:
            return None
        # Tests use plain stubs without the *_committed_at attribute — only
        # apply the freshness gate when the timestamp surface exists.
        if not hasattr(camera, ts_attr):
            return value
        committed_at = getattr(camera, ts_attr, None)
        if committed_at is None:
            return None
        age = (datetime.now(timezone.utc) - committed_at).total_seconds()
        if age > ZONE_POSTURE_FRESHNESS_SECONDS:
            return None
        return value

    def is_at_desk_fresh(self) -> bool:
        """True iff a fresh at-desk confirmation exists from any presence source.

        Used by autonomous mode-setters (late-night rescue, behavioral
        predictor, fusion override) to defer to active desk presence. The
        signal is multi-source: PresenceFusion combines the Latitude
        camera (zone=desk) with the desktop pc_agent (face_present), so a
        weak-face Latitude chair-back FP no longer hides Anthony when the
        desktop sees him head-on.
        """
        # Prefer PresenceFusion when wired — it's the source-aware path.
        # Fall back to direct camera reading for boot-time / test paths
        # where the fusion layer isn't built yet.
        presence = self._presence_fusion
        if presence is not None:
            return presence.is_at_desk_fresh(ZONE_POSTURE_FRESHNESS_SECONDS)
        camera = self._camera_service
        if camera is None or not getattr(camera, "enabled", False):
            return False
        zone = self._fresh_camera_attr(camera, "zone", "zone_committed_at")
        return zone == "desk"

    def is_present_in_room(self) -> bool:
        """True iff a presence source shows the user is visibly here right now.

        Zone-independent — answers "is someone here?" rather than "at the
        desk?". The ``ambient_relax`` soft-default consults this so it no
        longer treats "present but not at the desk" (e.g. on the couch — the
        Latitude's living-room view since the 2026-05-27 relocation) as
        "nobody home" and force-flip to relax.

        Strong presence (pose / face≥0.70) OR a fresh committed zone. The
        committed-zone arm matters at night: couch detection is often
        weak-face-only (conf ~0.3-0.45, never strong — measured 2026-05-27),
        but the committed couch zone survives the 15s hysteresis + face-anchor
        gating, so it's a reliable "someone is here" signal that strong
        presence alone misses. An empty couch does not commit a zone. Returns
        False when PresenceFusion isn't wired (boot / tests).
        """
        presence = self._presence_fusion
        if presence is None:
            return False
        return presence.is_strongly_present_any() or presence.latest_zone() is not None

    async def signal_presence(self, source: str) -> None:
        """Signal that a human is physically present in the apartment.

        Clears `_external_off_detected` if set, releasing the run_loop
        suppression that the `_check_external_off` mechanism armed when
        the Hue iOS app's "Leaving home" automation turned all lights off.
        Without this hook, the flag only clears when `report_activity`
        fires with a non-idle mode — which can't happen if the user
        walks in but doesn't touch the PC.

        Camera service calls this on absent→present transitions (today's
        only caller). A future Latitude-mic audio classifier could call
        it on high-confidence human-sound events. Idempotent: no-op when
        the flag is already clear.

        Args:
            source: Caller identifier for telemetry ("camera" today;
                "audio" if/when the parked Latitude-mic path ships).
        """
        if not self._external_off_detected:
            return
        self._external_off_detected = False
        logger.info(
            "Presence signal from %s — clearing external-off suppression "
            "so automation can resume",
            source,
        )

    def is_recent_process_working(
        self, window_seconds: int = RECENT_PROCESS_WORKING_SECONDS,
    ) -> bool:
        """True iff the PC agent reported ``mode=working`` within the window.

        Camera zone is the primary attendance signal but is brittle in dark
        rooms / pose-only conditions. The PC agent (psutil-driven, reports
        every 5s when active) is an independent attendance signal — used as
        a parallel veto by autonomous relax pushes (late-night rescue).
        10-minute default tolerates idle thinking gaps while staying
        conservative against "user left for the night."
        """
        if self._last_process_working_at is None:
            return False
        age = (
            datetime.now(tz=TZ) - self._last_process_working_at
        ).total_seconds()
        return age < window_seconds

    def _attach_presence_attribution(
        self,
        factors: dict,
        zone: Optional[str] = None,
        posture: Optional[str] = None,
    ) -> None:
        """Stamp ``zone_source`` / ``posture_source`` onto a factors dict.

        Reads ``PresenceFusion.get_sources()`` and records the first source
        whose fresh reading carries the matching ``zone`` / ``posture``
        value. Tagging makes ml_decisions audit-friendly: the
        ``fusion-lane-auditor`` can confirm both presence sources are
        contributing to actual decisions (not just heartbeating into the
        camera lane). Mutates ``factors`` in place; silently no-ops when
        PresenceFusion isn't wired or anything raises (rule fires must
        never abort on telemetry — they already burned their refractory
        stamp by the time this runs).
        """
        presence_fusion = getattr(self, "_presence_fusion", None)
        if presence_fusion is None:
            return
        try:
            sources = presence_fusion.get_sources()
            if zone is not None:
                factors["zone_source"] = next(
                    (
                        s for s, st in sources.items()
                        if st.get("zone") == zone and st.get("fresh")
                    ),
                    None,
                )
            if posture is not None:
                factors["posture_source"] = next(
                    (
                        s for s, st in sources.items()
                        if st.get("posture") == posture and st.get("fresh")
                    ),
                    None,
                )
        except Exception:
            return

    def _is_likely_still_asleep(self, now: datetime) -> bool:
        """True while the user appears to be asleep in bed.

        Stamped by `_evaluate_watching_sleep_guard` on every tick that
        observes a confident bed+reclined lock during watching mode.
        Released by any attendance signal that the user is up (camera
        sees them at the desk, or the PC agent says they're working) or
        the 12h failsafe.

        Consumed by `_apply_time_based` (morning_ramp suppression) and
        `_apply_mode` (watching late_night→day suppression). Catches the
        2026-05-15 wake-up: watching held all night, the dark-room guard
        fix should have fired sleeping but defense-in-depth wants the
        ramp itself to know "the user might still be asleep" too.
        """
        if self._last_bed_reclined_during_watching_at is None:
            return False
        age = (
            now - self._last_bed_reclined_during_watching_at
        ).total_seconds()
        if age > ASLEEP_STAMP_FAILSAFE_HOURS * 3600:
            return False
        # Any attendance signal releases the gate. Both helpers already
        # used as autonomous-push vetoes — same semantics here.
        if self.is_at_desk_fresh():
            return False
        if self.is_recent_process_working():
            return False
        return True

    def _apply_zone_overlay(
        self, state: dict[str, Any], mode: str, period: str,
    ) -> dict[str, Any]:
        """Zone/posture overlay (shim → calculator).

        Resolves fresh zone + posture off the camera service (with the
        freshness gate handled by ``_fresh_camera_attr``), then hands
        primitives to the pure calculator function.
        """
        camera = self._camera_service
        zone = self._fresh_camera_attr(camera, "zone", "zone_committed_at")
        posture = self._fresh_camera_attr(
            camera, "posture", "posture_committed_at"
        )
        l1_night = (
            getattr(self, "_bed_reclined_l1_night", None)
            or BED_RECLINED_L1_NIGHT_DEFAULT
        )
        return _calc_apply_zone_overlay(
            state, mode, period, zone, posture, l1_night,
        )

    def set_bed_reclined_l1_night(self, value: int) -> None:
        """Runtime override for the L1 night brightness when watching reclined.

        Evening and late_night L1 scale proportionally so a single slider
        tunes the whole reclined profile coherently. Accepts 1..100 and
        clamps; the settings page does its own range validation too.

        DORMANT since 2026-05-27 (Latitude→living-room move retired the
        bed-zone source the consuming overlay branch depends on). Setter
        still accepts writes so the stored value survives for revival.
        """
        self._bed_reclined_l1_night = max(1, min(100, int(value)))

    def register_on_mode_change(self, callback) -> None:
        """
        Register a callback to be invoked when the active mode changes.

        Args:
            callback: Async callable accepting a single mode string argument.
        """
        self._on_mode_change_callbacks.append(callback)

    def deregister_on_mode_change(self, callback) -> None:
        """Remove a previously-registered mode-change callback.

        Used when a subscriber is being replaced (e.g. CameraService
        respawn) so we don't accumulate dead references that would still
        get invoked on each mode change. No-op for callbacks that were
        never registered — keeps callers from raising during partial
        teardown.
        """
        try:
            self._on_mode_change_callbacks.remove(callback)
        except ValueError:
            pass

    async def notify_camera_commit(self) -> None:
        """Re-apply lighting after the camera commits a new zone or posture.

        Called by ``camera_service.poll_loop`` on actual transitions
        (zone or posture committing to a new non-None value), not on
        steady-state refreshes. Forces a fresh light apply with
        ``force_resend=True`` so the overlay's now-fresh zone/posture
        values flow into ``apply_zone_overlay`` and the dedup cache
        doesn't suppress the new computed state.

        Why this exists: ``_apply_mode`` only runs on mode transitions,
        and the 60s periodic re-apply in ``run_loop`` skips entirely
        when ``_manual_override`` is active. So a zone/posture commit
        that happens AFTER lights have settled (common post-restart,
        when hysteresis takes 60-120s to re-commit) would otherwise
        leave lights at the no-overlay baseline until the next mode
        change.
        """
        mode = self.current_mode
        if not mode:
            return
        logger.debug(
            "Camera commit → re-apply mode=%s with overlay-aware overlay",
            mode,
        )
        await self._apply_mode(mode, force_resend=True)

    async def _fire_mode_change_callbacks(self, mode: str) -> None:
        """Invoke all registered mode-change callbacks with timeout protection."""
        # 15s budget per callback. CameraService.start() reopens V4L2 on
        # resume-from-sleeping, which can take 5-8s under contention; the
        # earlier 8s ceiling clipped legitimate restarts and orphaned the
        # camera silent.
        for callback in self._on_mode_change_callbacks:
            try:
                await asyncio.wait_for(callback(mode), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "Mode change callback %s timed out after 15s for mode '%s'",
                    getattr(callback, "__qualname__", callback),
                    mode,
                )
            except Exception as e:
                logger.error(f"Mode change callback error: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Activity reporting
    # ------------------------------------------------------------------

    async def report_activity(
        self,
        mode: str,
        source: str,
        factors: Optional[list[dict]] = None,
    ) -> None:
        """
        Process an activity report from the PC agent, ambient monitor, or camera.

        Args:
            mode: Detected mode (gaming, watching, working, social, idle).
            source: Detection source ("process", "ambient", "audio_ml", or "camera").
            factors: Optional sub-factor list surfaced to the analytics
                constellation (foreground app / idle bucket / YAMNet classes /
                etc). Passed through to the confidence fusion without affecting
                fusion math.
        """
        if not self._enabled:
            return

        # Report to confidence fusion BEFORE mode-change guards — fusion is a
        # voting system, every signal should be heard even when it loses the
        # mode-change vote. "ambient" (RMS) aliases to the audio_ml lane.
        fusion = getattr(self, "_confidence_fusion", None)
        if fusion:
            if source == "process":
                fusion.report_signal("process", mode, 1.0, factors=factors)
            elif source == "ambient":
                fusion.report_signal("audio_ml", mode, 0.7, factors=factors)
            else:
                fusion.report_signal(source, mode, 0.8, factors=factors)

        # Persist a per-lane row in ml_decisions so per-source accuracy and
        # the analytics dashboard see the process voter directly. Shadow row
        # (applied=False) — process is a voter, not an actuator. Mirrors the
        # rule_engine wiring shipped 2026-04-28.
        if source == "process" and self._ml_logger is not None:
            await self._ml_logger.log_decision(
                predicted_mode=mode,
                confidence=1.0,
                decision_source="process",
                factors={
                    "engine_priority": MODE_PRIORITY.get(mode, 0),
                    "agent_factors": factors or [],
                },
                applied=False,
                broadcast=False,
            )

        # DND blocks autonomous mode changes after fusion has logged its
        # signal — fusion weights still tune normally so the lane stays
        # warm for when DND clears. report_activity has no user-source
        # path (PC agent / ambient / camera only), so this exits early
        # without a source check.
        if self.is_dnd_active():
            logger.debug("DND active — ignoring %s report (mode=%s)", source, mode)
            return

        # Priority guard — a lower-priority mode can't displace a higher-priority
        # current mode unless the report comes from the source that owns it
        # (sources can always update themselves) or the owning source has gone
        # stale. Enforces MODE_PRIORITY universally so every signal is subject
        # to the same rule.
        now = datetime.now(tz=TZ)
        current_priority = MODE_PRIORITY.get(self._current_mode, 0)
        new_priority = MODE_PRIORITY.get(mode, 0)
        if new_priority < current_priority and source != self._mode_source:
            last_report = self._last_mode_source_report_at.get(self._mode_source)
            if last_report is not None:
                age = (now - last_report).total_seconds()
                if age < SOURCE_STALE_SECONDS:
                    logger.debug(
                        "Priority guard: ignored %s %s (p=%d) — %s %s (p=%d) "
                        "still fresh (age %.0fs)",
                        source, mode, new_priority,
                        self._mode_source, self._current_mode,
                        current_priority, age,
                    )
                    # Still update liveness for the reporting source so a fresh
                    # source doesn't age out while being guarded against.
                    self._last_mode_source_report_at[source] = now
                    return

        # Sleeping floor — sleeping carries MODE_PRIORITY=0 (the global floor),
        # so the priority guard above can never protect it: `new_priority < 0`
        # is never true, and any idle sensor report (audio_ml/camera, p=1) walks
        # straight through and breaks sleep. A *manual* sleeping override is
        # protected downstream (the AUTONOMOUS_PUSH_SOURCES displacement gate +
        # the manual-override early-return), but once that override lapses and
        # sleeping survives only as a *detected* `_current_mode` — re-asserted by
        # the PC sleep-watcher via source=process — nothing guarded it. This bit
        # twice on 2026-06-03: audio_ml `idle` displaced a non-override sleeping
        # at 08:20 and again at 12:28 UTC (flag b064a0). Mirror the
        # RESCUE_OVERRIDE_SOURCES floor: while sleeping is held without a manual
        # override, only a foreground *process* report of a real activity mode
        # (anything above idle — working / watching / gaming) may wake the
        # apartment. Idle/sleeping reports and non-process sources (audio_ml,
        # camera, ambient) cannot. User actions take the set_manual_override /
        # clear_override paths and are unaffected. Deliberately NOT subject to
        # SOURCE_STALE_SECONDS — sleep must persist even if the owning process
        # source goes quiet (e.g. the PC itself suspends).
        if (
            self._current_mode == "sleeping"
            and not self._manual_override
            and not (source == "process" and new_priority > MODE_PRIORITY["idle"])
        ):
            logger.debug(
                "Sleeping floor: ignored %s %s (p=%d) — non-override sleeping "
                "only wakes on a foreground process activity report",
                source, mode, new_priority,
            )
            self._last_mode_source_report_at[source] = now
            return

        # Record this source's last-seen time regardless of whether the report
        # caused a mode change. Source freshness tracks liveness, not edges.
        self._last_mode_source_report_at[source] = now

        # Stamp process-working liveness for the late-night rescue veto.
        # Updated on every confirming report, not just on mode edges, so a
        # steady stream of process-working heartbeats keeps the veto alive
        # even when the engine has demoted current_mode to idle.
        if source == "process" and mode == "working":
            self._last_process_working_at = now

        old_mode = self._current_mode
        old_game = self._current_game

        # Accept the new detected mode (tracks what the PC is actually doing)
        self._current_mode = mode
        # Track the active game (drives GAME_LIGHT_PROFILES). Only meaningful in
        # gaming mode; any other mode clears it so a stale profile can't linger.
        # Set in lockstep with _current_mode so the next _apply_mode resolves the
        # right palette on the same report that first carries the `game` factor.
        self._current_game = _extract_game_factor(factors) if mode == "gaming" else None
        self._mode_source = source
        self._last_activity = mode
        self._last_activity_change = now

        # Track continuous-idle dwell for the ambient_relax setter. Stamp on
        # entry only — re-stamping every confirming idle report would defeat
        # the dwell. A presence blip to any non-idle mode clears the stamp so
        # the timer restarts on the next idle entry.
        if mode == "idle" and old_mode != "idle":
            self._idle_entered_at = now
        elif mode != "idle":
            self._idle_entered_at = None

        # Priority-bypass for autonomous overrides: when an autonomous setter
        # (fusion_auto_apply, late_night_rescue, behavioral_predictor, …)
        # locked a low-priority mode and an organic detector now reports a
        # higher-priority one, let the new signal displace the override
        # instead of being silently consumed. Bug surfaced 2026-05-12: a
        # fusion_auto_apply idle@1 lock swallowed 7 organic gaming@5 /
        # working@2 / watching@3 reports across 116min until the user manually
        # tapped "Auto". User-set overrides (manual / api:* / guest / alexa:* /
        # rule_suggestion_accept:*) are NEVER auto-displaced — explicit user
        # intent always wins.
        #
        # 2026-05-16: added RESCUE_OVERRIDE_SOURCES floor. Rescue sources
        # (late_night_rescue, zone_posture_rule, watching_sleep_guard) push
        # manual-only modes (relax/sleeping) whose default priority is 0;
        # without a floor, an `idle` sensor report (p=1) silently undoes the
        # rescue. Floor at idle prevents that while still allowing real
        # activity signals (working+) to displace. Worked example: rescue
        # sets relax (p=0) → effective p=1 → ambient idle (p=1) cannot
        # displace (`1 > 1` False); foreground gaming (p=5) still does.
        override_priority = MODE_PRIORITY.get(self._override_mode, 0)
        if self._override_source in RESCUE_OVERRIDE_SOURCES:
            override_priority = max(override_priority, MODE_PRIORITY["idle"])

        if (
            self._manual_override
            and self._override_source in AUTONOMOUS_PUSH_SOURCES
            and new_priority > override_priority
        ):
            logger.info(
                "Autonomous override displaced by priority: %s (p=%d, "
                "source=%s) → %s (p=%d, source=%s)",
                self._override_mode,
                override_priority,
                self._override_source,
                mode, new_priority, source,
            )
            self._manual_override = False
            self._override_mode = None
            self._override_source = None
            self._override_time = None
            await self._persist_override_state()
            # Fall through to normal mode-application path below — per-light
            # overrides are preserved (no _clear_per_light_overrides) because
            # this displacement is autonomous, mirroring clear_override's gate.

        # If manual override is active, update detected mode silently but
        # never clear the override — only the user or the 4h timeout should.
        if self._manual_override:
            if old_mode != mode:
                logger.info(
                    f"Activity changed ({old_mode} → {mode}) — "
                    f"manual override active, keeping {self._override_mode}"
                )
                if self._event_logger:
                    await self._event_logger.log_mode_change(
                        mode=mode,
                        previous_mode=old_mode,
                        source=source,
                    )
            await self._broadcast_mode()
            return

        # Clear external off detection on any activity
        if mode not in ("idle",):
            self._external_off_detected = False

        # Apply the appropriate light state. force_resend=True only on a
        # real mode change — invalidates the per-light dedup cache so any
        # bridge drift from effects / external writes / prior overrides
        # gets re-corrected. Same-mode heartbeats (PC agent fires every
        # 5s in steady state) ride the cache so identical-state writes
        # are suppressed; lux multiplier updates still propagate because
        # _apply_mode runs the full state pipeline either way. The 2026-
        # 05-06 audit found this branch was unconditionally clearing the
        # cache on every report, producing ~3.5 no-op bridge writes per
        # minute on L2 with bri_before=null in the log timeline.
        # force_resend on a game change too (e.g. launching/quitting Rust while
        # staying in gaming mode) so the GAME_LIGHT_PROFILES swap repaints
        # immediately instead of riding the per-light dedup cache.
        await self._apply_mode(
            mode,
            force_resend=(old_mode != mode or old_game != self._current_game),
        )

        # Fire mode change callbacks (e.g., music auto-play)
        if old_mode != mode:
            await self._fire_mode_change_callbacks(mode)
            if self._event_logger:
                await self._event_logger.log_mode_change(
                    mode=mode,
                    previous_mode=old_mode,
                    source=source,
                )

        # Broadcast mode change
        await self._broadcast_mode()

    async def set_manual_override(self, mode: str, source: str = "internal") -> None:
        """Set a manual mode override from the dashboard.

        Args:
            mode: Target activity mode.
            source: Caller identifier for telemetry. API route passes
                ``api:<remote_ip>``; internal triggers (late_night_rescue,
                fusion, zone_posture_rule, etc.) pass their own short label
                so journalctl shows who flipped the override and from where.
        """
        # DND blocks autonomous override pushes (late_night_rescue, fusion,
        # behavioral_predictor, zone_posture_rule, internal). User-initiated
        # overrides from the API route ("api:<ip>") still pass — the user
        # can change mode while DND is on; we just suppress automation noise.
        if self.is_dnd_active() and not source.startswith("api:"):
            logger.info(
                "DND active — blocking autonomous override %s (source=%s)",
                mode, source,
            )
            return

        # User-respect cooldown — if the user just cleared an override via
        # the dashboard, block autonomous-source pushes for the cooldown
        # window so "auto" actually means auto. User-initiated actions
        # (api:*, rule_suggestion_accept:*) bypass — they aren't sensor
        # reactivity.
        if (
            source in AUTONOMOUS_PUSH_SOURCES
            and self._user_cleared_override_at is not None
        ):
            elapsed = (
                datetime.now(tz=TZ) - self._user_cleared_override_at
            ).total_seconds()
            if elapsed < USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS:
                logger.info(
                    "Autonomous override blocked by user-clear cooldown: "
                    "mode=%s source=%s elapsed=%.0fs / %ds",
                    mode, source, elapsed,
                    USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS,
                )
                return

        # Capture the effective mode (override if active, else detected) so that
        # event logging and callback gating see the real "previous" mode, not
        # the stale private _current_mode which only reflects PC agent state.
        old_mode = self.current_mode
        was_overridden = self._manual_override
        prior_override = self._override_mode
        self._manual_override = True
        self._override_mode = mode
        self._override_source = source
        self._override_time = datetime.now(tz=TZ)
        self._last_activity_change = self._override_time

        # Only wipe per-light manual brightness/color when the user picked
        # this mode. Autonomous sources (late-night rescue, fusion,
        # predictor, zone+posture rule) preserve them — see
        # PRESERVE_PER_LIGHT_OVERRIDE_SOURCES.
        if source not in PRESERVE_PER_LIGHT_OVERRIDE_SOURCES:
            self._clear_per_light_overrides()
        logger.info(
            "Manual override set: %s (source=%s, prior=%s, was_overridden=%s)",
            mode, source, prior_override, was_overridden,
        )
        await self._persist_override_state()
        # Broadcast first so the UI updates immediately, then apply lights.
        # force_resend=True so any lights that were behind a per-light override
        # (now released) get a fresh write to the new mode's state.
        await self._broadcast_mode()
        await self._apply_mode(mode, force_resend=True)
        # Fire mode change callbacks only if the mode actually changed
        if old_mode != mode:
            await self._fire_mode_change_callbacks(mode)
        if self._event_logger and old_mode != mode:
            await self._event_logger.log_mode_change(
                mode=mode,
                previous_mode=old_mode,
                source=source,
            )

    async def clear_override(self, source: str = "internal") -> None:
        """Clear the manual override and return to automatic mode.

        Special case: if we were sleeping, don't re-apply anything. The fade
        already finished hours ago and lights are off. Re-applying a detected
        mode (working/idle with its time-based night rule, etc.) would blast
        bright lights on while the user is still asleep — exactly the
        "lights turn back on" bug.

        Args:
            source: Caller identifier for telemetry — see set_manual_override.
                Useful for diagnosing surprise clear events (e.g. an API
                client posting ``mode=auto`` mid-evening).
        """
        # DND blocks autonomous override clears (4h timeout, fusion, etc.) so
        # the locked state survives the DND window. User-initiated clears via
        # the API route still pass.
        if self.is_dnd_active() and not source.startswith("api:"):
            logger.info(
                "DND active — blocking autonomous override clear (source=%s)",
                source,
            )
            return

        # Stamp the user-respect cooldown when this clear came from the
        # dashboard "auto" button. Subsequent autonomous mode pushes get
        # suppressed for USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS so the user's
        # explicit "auto" choice isn't immediately undone by a sensor lane.
        if source.startswith("api:"):
            self._user_cleared_override_at = datetime.now(tz=TZ)

        old_effective = self._override_mode
        was_overridden = self._manual_override
        self._manual_override = False
        self._override_mode = None
        self._override_source = None
        self._override_time = None

        # Same gate as set_manual_override — autonomous clears (4h timeout,
        # etc.) preserve per-light overrides; user-initiated "auto" presses
        # wipe them so the dashboard's "auto" feels like a clean slate.
        if source not in PRESERVE_PER_LIGHT_OVERRIDE_SOURCES:
            self._clear_per_light_overrides()
        logger.info(
            "Manual override cleared — returning to auto "
            "(source=%s, prior_override=%s, was_overridden=%s)",
            source, old_effective, was_overridden,
        )
        await self._persist_override_state()

        if old_effective == "sleeping":
            # User is (probably) still asleep or just waking — they'll pick a
            # new mode on the dashboard. Leave lights off, but DO fire mode
            # change callbacks so subscribers (camera unpause, ambient sound,
            # ML logger) sync to the new effective mode. The 2026-05-05 bug:
            # camera stayed paused all day after each morning's "Auto" tap
            # because this branch skipped callbacks entirely. MusicMapper has
            # its own auto-play gates (idle has no playlist) so waking to
            # idle won't trigger music.
            await self._broadcast_mode()
            if old_effective != self._current_mode:
                await self._fire_mode_change_callbacks(self._current_mode)
            return

        # Re-apply current detected mode or time-based. force_resend=True
        # because we've just released the override and per-light overrides;
        # the cache may not reflect what's actually on the bridge.
        if self._current_mode in ("idle",):
            await self._apply_time_based()
        else:
            await self._apply_mode(self._current_mode, force_resend=True)

        await self._broadcast_mode()
        # Only fire callbacks if the effective mode actually changed
        if old_effective != self._current_mode:
            await self._fire_mode_change_callbacks(self._current_mode)

    # ------------------------------------------------------------------
    # Do Not Disturb
    # ------------------------------------------------------------------

    def is_dnd_active(self) -> bool:
        """True iff DND is enabled and the expiry is still in the future.

        Delegates to :class:`DndManager` — kept as an engine method so the
        many gating callers (routes, notifier, celebrations, run_loop) are
        untouched by the extraction.
        """
        return self._dnd.is_active()

    def dnd_status(self) -> dict:
        """Return DND state as a JSON-serializable dict for API responses."""
        return self._dnd.status()

    async def enable_dnd(
        self, duration_minutes: int = 120, source: str = "internal",
    ) -> dict:
        """Activate DND for ``duration_minutes`` (clamped to [1, 720])."""
        return await self._dnd.enable(duration_minutes, source=source)

    async def clear_dnd(self, source: str = "internal") -> dict:
        """Clear DND immediately."""
        return await self._dnd.clear(source=source)

    async def _persist_override_state(self) -> None:
        """Write current manual-override state to app_settings.

        Persists `_manual_override`, `_override_mode`, `_override_time`,
        and both autonomous-rule refractory stamps
        (`_zone_posture_last_fired_at`, `_watching_sleep_guard_last_fired_at`)
        so a backend restart (deploys, crashes) doesn't drop the user's
        active mode and re-derive it from raw sensors. Without this,
        deploying while in `relax` would briefly flip to whatever the PC
        agent is reporting until the rule re-fires after its dwell, and
        a deploy mid-watching-sleep window would risk a double-fire on
        the same night.
        """
        from backend.api.routes.automation import OVERRIDE_STATE_KEY
        from backend.api.routes.routines import save_setting

        payload: dict[str, Any] = {
            "manual_override": self._manual_override,
            "override_mode": self._override_mode,
            "override_source": self._override_source,
            "override_time_utc": (
                self._override_time.astimezone(timezone.utc).isoformat()
                if self._override_time is not None else None
            ),
            "zone_posture_last_fired_utc": (
                self._zone_posture_last_fired_at.astimezone(timezone.utc).isoformat()
                if self._zone_posture_last_fired_at is not None else None
            ),
            "watching_sleep_guard_last_fired_utc": (
                self._watching_sleep_guard_last_fired_at
                .astimezone(timezone.utc).isoformat()
                if self._watching_sleep_guard_last_fired_at is not None else None
            ),
            "user_cleared_override_at_utc": (
                self._user_cleared_override_at.astimezone(timezone.utc).isoformat()
                if self._user_cleared_override_at is not None else None
            ),
            "last_bed_reclined_during_watching_utc": (
                self._last_bed_reclined_during_watching_at
                .astimezone(timezone.utc).isoformat()
                if self._last_bed_reclined_during_watching_at is not None else None
            ),
        }
        try:
            await save_setting(OVERRIDE_STATE_KEY, payload)
        except Exception as e:
            logger.error("Failed to persist override state: %s", e, exc_info=True)

    async def load_override_state(self) -> None:
        """Restore manual-override state from app_settings on startup.

        Drops the override if it would have already timed out (older than
        `_override_timeout_hours`); `sleeping` is exempt because it has no
        timeout by design. Always restores the zone+posture rule stamp so
        gate 2's post-expiry refractory survives a restart.
        """
        from backend.api.routes.automation import OVERRIDE_STATE_KEY
        from backend.api.routes.routines import load_setting

        try:
            saved = await load_setting(OVERRIDE_STATE_KEY)
        except Exception as e:
            logger.error("Failed to load override state: %s", e, exc_info=True)
            return
        if not saved:
            return

        # Restore zone+posture stamp first — independent of the override
        # itself, and needed even when the override has expired so the
        # gate 2 refractory window is honored across restarts.
        stamp_str = saved.get("zone_posture_last_fired_utc")
        if stamp_str:
            try:
                self._zone_posture_last_fired_at = (
                    datetime.fromisoformat(stamp_str).astimezone(TZ)
                )
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid zone_posture stamp on load: %r", stamp_str,
                )

        # Same restore for the watching-sleep guard refractory stamp so a
        # deploy mid-window doesn't double-fire.
        wsg_str = saved.get("watching_sleep_guard_last_fired_utc")
        if wsg_str:
            try:
                self._watching_sleep_guard_last_fired_at = (
                    datetime.fromisoformat(wsg_str).astimezone(TZ)
                )
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid watching_sleep_guard stamp on load: %r", wsg_str,
                )

        # Restore user-clear cooldown stamp so a deploy/restart mid-cooldown
        # doesn't drop the suppression window.
        clear_str = saved.get("user_cleared_override_at_utc")
        if clear_str:
            try:
                self._user_cleared_override_at = (
                    datetime.fromisoformat(clear_str).astimezone(TZ)
                )
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid user_cleared_override stamp on load: %r", clear_str,
                )

        # Restore the asleep-stamp so a deploy mid-night doesn't drop
        # morning-ramp suppression. The 12h failsafe inside
        # `_is_likely_still_asleep` self-clears stale stamps regardless.
        asleep_str = saved.get("last_bed_reclined_during_watching_utc")
        if asleep_str:
            try:
                self._last_bed_reclined_during_watching_at = (
                    datetime.fromisoformat(asleep_str).astimezone(TZ)
                )
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid asleep stamp on load: %r", asleep_str,
                )

        if not saved.get("manual_override"):
            return
        mode = saved.get("override_mode")
        if not mode:
            return
        time_str = saved.get("override_time_utc")
        if not time_str:
            return
        try:
            override_time = datetime.fromisoformat(time_str).astimezone(TZ)
        except (TypeError, ValueError):
            logger.warning("Invalid override_time on load: %r", time_str)
            return

        # Sleeping has no timeout by design (CLAUDE.md: "Persistent override").
        # Every other mode: drop if it would have already expired.
        if mode != "sleeping":
            elapsed = datetime.now(tz=TZ) - override_time
            if elapsed > timedelta(hours=self._override_timeout_hours):
                logger.info(
                    "Override (%s) age %.0fmin exceeds %dh timeout — "
                    "treating as expired",
                    mode, elapsed.total_seconds() / 60,
                    self._override_timeout_hours,
                )
                # Re-persist the cleared state so the dashboard sees no override.
                await self._persist_override_state()
                return

        self._manual_override = True
        self._override_source = saved.get("override_source")
        self._override_mode = mode
        self._override_time = override_time
        self._last_activity_change = override_time
        age_min = int(
            (datetime.now(tz=TZ) - override_time).total_seconds() // 60
        )
        logger.info(
            "Override restored from app_settings: mode=%s set %dmin ago",
            mode, age_min,
        )

    async def load_dnd_state(self) -> None:
        """Restore DND state from app_settings on startup.

        Delegates to :class:`DndManager.load_state` (bootstrap calls this).
        """
        await self._dnd.load_state()

    def mark_light_manual(self, light_id: str) -> None:
        """Mark a light as manually adjusted — protects it from automation.

        Per-light overrides are cleared on the next explicit mode change
        (manual override set/cleared) so automation resumes naturally.
        """
        self._manual_light_overrides[light_id] = datetime.now(tz=TZ)
        logger.info(f"Light {light_id} marked as manually overridden")

    def _clear_per_light_overrides(self) -> None:
        """Clear all per-light manual overrides."""
        if self._manual_light_overrides:
            logger.info(
                f"Clearing per-light overrides: {list(self._manual_light_overrides)}"
            )
            self._manual_light_overrides.clear()

    def _invalidate_dedup_cache(self) -> None:
        """Drop the per-light dedup cache so the next ``_apply_state`` re-sends
        to every light instead of being suppressed as a no-op.

        Single owner for the "force re-apply" discipline. Call wherever the
        bridge may have diverged from ``_last_applied_per_light`` (mode
        transitions across a colorspace switch, effect stop/start, config
        hot-reloads, sleep-fade steps, scene drift). Centralized so a new code
        path can't silently reintroduce the stale-cache dedup-skip behind the
        kitchen-pair drift of 2026-05-09 (project_transit_lighting_cache_pop_churn).
        """
        self._last_applied_per_light = {}

    def _forget_dedup_light(self, light_id: str) -> None:
        """Drop one light from the dedup cache so the next reconcile re-sends
        the mode's state to it. Used when a transit override is cleared/expired
        and the cache would otherwise retain the stale transit value and
        dedup-skip the revert.
        """
        self._last_applied_per_light.pop(light_id, None)

    def _prune_expired_transit_overrides(self) -> None:
        """Remove transit overrides whose deadline has passed.

        Called before the skip filter consults the dict so expired entries
        don't stale-lock automation from reasserting a light.
        """
        if not self._transit_light_overrides:
            return
        now = datetime.now(tz=TZ)
        expired = [
            lid for lid, deadline in self._transit_light_overrides.items()
            if deadline <= now
        ]
        for lid in expired:
            del self._transit_light_overrides[lid]
            # Mirrors clear_transit_override's pop. Without it, the dedup
            # cache retains transit values after deadline expiry and the
            # next reconcile dedup-skips on stale data (kitchen-pair drift
            # 2026-05-09; memory project_transit_lighting_cache_pop_churn).
            self._forget_dedup_light(lid)
        if expired:
            logger.info(
                "Transit overrides auto-expired for lights %s",
                expired,
            )

    async def apply_transit_override(
        self,
        states: dict[str, dict],
        duration_seconds: int = 600,
        transition_time: int = 20,
        trigger: str = "transit",
    ) -> None:
        """Apply temporary per-light brightness, protected from mode reconcile.

        Writes the given per-light states directly to the bridge and protects
        those lights from mode-driven automation until ``clear_transit_override``
        is called or the deadline elapses. Used by ``TransitLightingService``
        (gentle navigation lift) and ``DeskExitKitchenService`` (kitchen
        brighten on desk exit) — both share the same protection slot
        (``_transit_light_overrides``) but distinguish themselves via the
        ``trigger`` label written to ``light_adjustments``.

        Args:
            states: light_id → state dict (``{"on": True, "bri": ..., "ct": ...}``)
            duration_seconds: max protection window before auto-expiry
            transition_time: deciseconds for the Hue transition (20 = 2s)
            trigger: label written to light_adjustments.trigger — defaults to
                ``"transit"`` for back-compat; ``DeskExitKitchenService`` passes
                ``"desk_exit_kitchen"`` so analytics can distinguish the two
                paths.
        """
        if not self._hue or not self._hue.connected:
            return

        # Kitchen-pair atomicity: L3 + L4 must move as a unit in functional
        # modes. If the user has manually set one (e.g., L4 at bri=114),
        # transit-overriding only the unstamped one splits the pendants —
        # writes go to L3 directly here, but the next _apply_per_light cycle
        # re-protects L4 (manual stamp) and not L3, leaving them mismatched.
        # Skip the pair entirely when either is manual; L1 still applies.
        # Symptom that motivated this guard: 21 solo-L3 writes / 11 min split
        # on 2026-05-09. Memory: project_transit_lighting_cache_pop_churn.md.
        if "3" in states and "4" in states:
            kitchen_manual = (
                "3" in self._manual_light_overrides
                or "4" in self._manual_light_overrides
            )
            if kitchen_manual:
                stamped = next(
                    lid for lid in ("3", "4")
                    if lid in self._manual_light_overrides
                )
                logger.info(
                    "%s skipped kitchen pair (L3/L4) — manual override on light %s",
                    trigger, stamped,
                )
                states = {
                    lid: s for lid, s in states.items() if lid not in ("3", "4")
                }
                if not states:
                    return

        deadline = datetime.now(tz=TZ) + timedelta(seconds=duration_seconds)
        tasks = []
        # Capture before-state for event logging — same pattern as
        # _apply_per_light. Without this, transit writes were invisible to
        # light_adjustments queries (2026-05-12 incident: 107 transit cycles
        # in 30 min produced zero rows in the analytics surface).
        pre_values: dict[str, dict] = {}
        for light_id, state in states.items():
            pre_values[light_id] = (
                self._last_applied_per_light.get(light_id) or {}
            ).copy()
            cmd = {**state, "transitiontime": transition_time}
            tasks.append(self._hue.set_light(light_id, cmd))
            self._transit_light_overrides[light_id] = deadline
            # Seed dedup so a concurrent reconcile cycle doesn't re-send the
            # previous mode state for these lights before the skip filter runs.
            self._last_applied_per_light[light_id] = {k: v for k, v in state.items() if k != "transitiontime"}
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(
            "%s override applied to lights %s (expires %s)",
            trigger, list(states.keys()),
            deadline.strftime("%H:%M:%S"),
        )
        if self._event_logger:
            for light_id, state in states.items():
                prev = pre_values.get(light_id, {})
                await self._event_logger.log_light_adjustment(
                    light_id=light_id,
                    bri_before=prev.get("bri"), bri_after=state.get("bri"),
                    hue_before=prev.get("hue"), hue_after=state.get("hue"),
                    sat_before=prev.get("sat"), sat_after=state.get("sat"),
                    ct_before=prev.get("ct"), ct_after=state.get("ct"),
                    mode_at_time=self.current_mode,
                    trigger=trigger,
                )

    async def apply_desk_exit_override(
        self,
        states: dict[str, dict],
        duration_seconds: int = 4 * 3600,
        transition_time: int = 5,
    ) -> None:
        """Brighten the kitchen pair when Anthony leaves the desk.

        Thin wrapper around ``apply_transit_override`` with the
        ``trigger="desk_exit_kitchen"`` label so light_adjustments rows are
        distinguishable from generic transit pulses. Default ``duration_seconds``
        is 4h (vs transit's 10min) because this override holds until
        ``DeskExitKitchenService`` sees Anthony back at the desk; the deadline
        is only a wedged-camera failsafe.
        """
        await self.apply_transit_override(
            states,
            duration_seconds=duration_seconds,
            transition_time=transition_time,
            trigger="desk_exit_kitchen",
        )

    async def clear_desk_exit_override(self, transition_time: int = 20) -> None:
        """Revert the kitchen pair back to the current mode's state.

        Thin alias for ``clear_transit_override`` scoped to the kitchen pair
        only — the desk-exit service never touches L1, so a service-wide
        clear could safely call the generic method, but this keeps the call
        sites symmetric with the apply method.
        """
        await self.clear_transit_override(
            light_ids=["3", "4"], transition_time=transition_time,
        )

    async def apply_corridor_override(
        self,
        states: dict[str, dict],
        duration_seconds: int = 600,
        transition_time: int = 15,
    ) -> None:
        """Late-night corridor brighten — L1 + kitchen pair as a path-light unit.

        Sibling to ``apply_desk_exit_override``. Drives L1 (living-room
        floor lamp) plus L3/L4 (kitchen pendants) under a single override
        stamp with ``trigger="corridor"``. Called by
        ``DeskExitKitchenService`` when the period is ``late_night`` — at
        that hour the user might be heading to the kitchen OR the bathroom,
        and since neither camera sees the hallway we can't disambiguate.
        L1 spills warm light into the hallway from the living-room end;
        L3/L4 spill from the kitchen end. Together they cover both
        destinations.

        Default ``duration_seconds`` is 10min (vs desk_exit's 4h) because
        the corridor override is short-lived by design — Anthony either
        returns to the desk or the failsafe trips before then. ``states``
        is expected to include L1 plus optionally L3/L4 (the staged
        ramp-up calls this twice: once with L1 alone, once with the
        kitchen pair 2s later).
        """
        await self.apply_transit_override(
            states,
            duration_seconds=duration_seconds,
            transition_time=transition_time,
            trigger="corridor",
        )

    async def clear_corridor_override(
        self,
        light_ids: Optional[list[str]] = None,
        transition_time: int = 30,
    ) -> None:
        """Revert corridor-overridden lights back to current mode state.

        Wraps ``clear_transit_override`` for the L1+kitchen set. Default
        scope is ``["1", "3", "4"]`` (whole corridor) — the service passes
        a subset for the sequenced wind-down (kitchen first at t=0, L1
        after a 10s linger).

        Note on ``transition_time``: ``clear_transit_override`` discards
        this parameter (API-compat shim) and lets ``_apply_mode`` use the
        mode-default transition speed for the revert. The kwarg is kept
        here for call-site symmetry with the apply path; the actual fade
        speed is driven by ``MODE_TRANSITION_TIME[current_mode]``
        (working=2s, relax=4s, etc.). At late_night this is typically a
        2–4s fade — close enough to the original 3s design intent that
        no caller-side override is needed.
        """
        _ = transition_time  # See docstring — passed for symmetry only.
        if light_ids is None:
            light_ids = ["1", "3", "4"]
        await self.clear_transit_override(
            light_ids=light_ids, transition_time=transition_time,
        )

    async def clear_transit_override(
        self,
        light_ids: Optional[list[str]] = None,
        transition_time: int = 30,
    ) -> None:
        """Remove transit overrides and revert the affected lights to the current mode.

        Args:
            light_ids: lights to clear. If None, clears all active transit overrides.
            transition_time: deciseconds for the revert (30 = 3s — fast-but-not-jarring).
        """
        _ = transition_time  # API-compat shim — revert uses mode-default transition speed
        if not self._transit_light_overrides:
            return
        if light_ids is None:
            light_ids = list(self._transit_light_overrides.keys())
        cleared = []
        for lid in light_ids:
            if lid in self._transit_light_overrides:
                del self._transit_light_overrides[lid]
                cleared.append(lid)
        if not cleared:
            return
        # Drop dedup cache for reverted lights so _apply_mode will actually
        # re-send the mode's state to them.
        for lid in cleared:
            self._forget_dedup_light(lid)
        # Reapply against the EFFECTIVE (override-aware) mode. Using the raw
        # `_current_mode` field here discards an active manual override and
        # snaps lights to whatever the PC activity detector last reported —
        # the bug where a brief camera flicker in a dim bedroom rendered
        # working late_night brightness right over a relax override.
        effective_mode = self.current_mode
        logger.info(
            "Transit override cleared for lights %s — reverting to mode %s",
            cleared, effective_mode,
        )
        # Re-apply the current mode's full light state. Dedup cache will no-op
        # on any lights that weren't in the transit set, so only the cleared
        # lights receive new Hue commands.
        await self._apply_mode(effective_mode)

    # ------------------------------------------------------------------
    # Light state application
    # ------------------------------------------------------------------

    async def _reconcile_effect(
        self, desired: Optional[str | dict[str, Any]],
    ) -> None:
        """Transition active Hue v2 effect (shim → effect_manager)."""
        await self._effect_manager.reconcile(desired)

    async def _apply_mode(self, mode: str, *, force_resend: bool = False) -> None:
        """Apply light state for a given mode.

        Args:
            mode: The mode whose lighting to apply.
            force_resend: When True, clear the per-light dedup cache so every
                light gets re-written to the bridge. Set this on actual mode
                transitions (the previous mode may have used HSB while the new
                one uses CT, an effect was running, manual overrides were
                released, etc. — any of which can leave the bridge state out
                of sync with the cache). Leave False on periodic reapply
                ticks so dedup can no-op when nothing changed.
        """
        # Cancel any in-progress sleep fade if switching to an active mode
        if mode != "sleeping" and self._sleep_fade_task and not self._sleep_fade_task.done():
            self._sleep_fade_task.cancel()
            self._sleep_fade_task = None
            logger.info("Sleep fade cancelled — activity resumed")

        # Screen sync no longer has a start/stop loop — colors arrive via
        # POST /api/automation/screen-color and are gated by SCREEN_SYNC_MODES
        # at the route handler. No engine-side action needed when modes change.

        # Determine what effect should be active for this mode+period.
        # IMPORTANT: don't stop the current effect yet. Stopping an active
        # effect before the new brightness target is on the bridge causes the
        # bridge to reset brightness to 100%, producing the visible "pop" on
        # mode change. We reconcile effects at the END of this function, after
        # _apply_state (or scene activation) has established the new target.
        desired_effect = self._get_desired_effect(mode)

        # On a true mode transition, the previous mode may have used HSB
        # while this one uses CT, an effect may have been running and changed
        # bridge state, or manual overrides may have just been released —
        # any of which can leave the cache stale. Periodic reapply ticks
        # don't have those concerns and rely on dedup to no-op cleanly.
        if force_resend:
            self._invalidate_dedup_cache()

        # Sleep mode: dim the bridge FIRST, then stop the effect, then fade to off.
        # Stopping an active effect before setting a brightness target pops the
        # bridge to 100% (same root cause as the mode-change flash documented
        # in _reconcile_effect). Apply a very low target first so the bridge
        # holds it when the effect releases.
        if mode == "sleeping":
            if self._sleep_fade_task and not self._sleep_fade_task.done():
                return  # Fade already in progress

            # Apply dim initial target — deep ember at bri=20. 1s snap so the
            # first thing Anthony sees (already in bed) is sleep-friendly.
            initial_state = {"on": True, "bri": 20, "hue": 5000, "sat": 254}
            self._invalidate_dedup_cache()
            await self._apply_state(initial_state, transitiontime=10)
            await asyncio.sleep(1.2)  # Let the bridge settle the target

            # Now stop the effect — bridge holds bri=20 instead of popping to 100%
            await self._effect_manager.stop_all()

            self._sleep_fade_task = asyncio.create_task(self._sleep_fade())
            return

        # Social mode: route through party sub-mode system (handles own effects)
        if mode == "social":
            await self._apply_social_style()
            return

        # Check for scene override (user-mapped Hue scene for this mode+time)
        period = self._get_time_period()
        # Asleep-in-bed gate for watching mode: hold the night state past
        # wake_hour when the user appears to still be asleep. The 2026-05-15
        # incident saw watching mode's late_night→day transition jump L2/L5
        # from bri≈20 to bri=91 at 06:00:06 while the user was still in bed.
        # Scoped to watching only — no other mode has the "user fell asleep
        # with this mode active" pathology that needs this guard.
        # `_resolve_activity_state` for watching has no late_night key, so
        # "night" is the explicit dim-but-not-late-night state we want.
        if (
            mode == "watching"
            and period == "day"
            and self._is_likely_still_asleep(datetime.now(tz=TZ))
        ):
            logger.info(
                "Watching mode holding night state past wake_hour — "
                "user likely still asleep (bed+reclined observed at %s)",
                self._last_bed_reclined_during_watching_at,
            )
            period = "night"
        override_scene = self._scene_overrides.get(mode, {}).get(period)
        if override_scene and self._hue_v2 and self._hue_v2.connected:
            source = self._scene_override_sources.get(mode, {}).get(period, "bridge")
            override_applied = False
            failure_reason: str | None = None
            try:
                if source == "bridge":
                    await self._hue_v2.activate_scene(override_scene)
                    logger.info(
                        "Applied scene override for %s/%s: %s",
                        mode, period, override_scene,
                    )
                    override_applied = True
                elif source == "preset":
                    # Preset scenes are handled via the scenes route — activate by name
                    from backend.api.routes.scenes import SCENE_PRESETS, _activate_per_light
                    preset = SCENE_PRESETS.get(override_scene)
                    if preset:
                        await _activate_per_light(preset["lights"], self._hue)
                        override_applied = True
                    else:
                        failure_reason = f"preset '{override_scene}' not in SCENE_PRESETS"
            except Exception as e:
                failure_reason = f"{type(e).__name__}: {e}"
                logger.error(
                    "Scene override failed for %s/%s (%s): %s",
                    mode, period, override_scene, e,
                    exc_info=True,
                )

            if override_applied:
                # Reconcile effect AFTER scene activation so the bridge has a
                # brightness target set before we stop any old effect.
                await self._reconcile_effect(desired_effect)
                return

            # Both paths failed — notify the frontend and fall through to the
            # hardcoded ACTIVITY_LIGHT_STATES path below so lights don't stay
            # in their prior state silently.
            await self._ws_manager.broadcast("scene_failed", {
                "mode": mode,
                "time_period": period,
                "scene_id": override_scene,
                "source": source,
                "reason": failure_reason or "unknown",
            })
            logger.warning(
                "Falling back to ACTIVITY_LIGHT_STATES for %s/%s after scene override failure",
                mode, period,
            )

        # A per-game profile (GAME_LIGHT_PROFILES, e.g. Rust) overrides the
        # generic gaming palette when self._current_game is set — resolved
        # through the same table helper the resolver uses, so the lerp /
        # overlay / multiplier pipeline below is identical.
        game = self._current_game
        mode_states = _get_mode_state_table(mode, game)
        if mode_states is not None:
            if "day" in mode_states:
                # Time-aware mode: blend evening → night during the 30-min ramp window
                now = datetime.now(tz=TZ)
                schedule = (
                    self._schedule_config.weekday
                    if now.weekday() < 5
                    else self._schedule_config.weekend
                )
                winddown_total = schedule.winddown_start_hour * 60
                current_total = now.hour * 60 + now.minute
                minutes_until_winddown = winddown_total - current_total

                if 0 < minutes_until_winddown <= WINDDOWN_RAMP_MINUTES:
                    progress = (WINDDOWN_RAMP_MINUTES - minutes_until_winddown) / WINDDOWN_RAMP_MINUTES
                    evening_state = _resolve_activity_state(mode, "evening", game)
                    night_state = _resolve_activity_state(mode, "night", game)
                    state = _lerp_light_state(evening_state, night_state, progress)
                else:
                    state = _resolve_activity_state(mode, period, game)
            else:
                state = _resolve_activity_state(mode, period, game)

            # Apply learned lighting preferences as overlay (ML Phase 1).
            # Learned values replace hardcoded defaults per-light, per-property.
            # Weather class threaded in (Layer 4) so the overlay picks the
            # weather-specific bucket when one exists, otherwise falls back
            # to the "any" baseline.
            lighting_learner = getattr(self, "_lighting_learner", None)
            if lighting_learner:
                weather_for_overlay = (
                    self._get_current_weather_condition() or "any"
                )
                overlay = lighting_learner.get_overlay(
                    mode, period, weather_for_overlay,
                )
                if overlay:
                    deltas: dict[str, dict] = {}
                    for light_id, prefs in overlay.items():
                        if light_id in state:
                            pre = state[light_id]
                            # Only fields the overlay actually changed (pre
                            # value differs from the overlay value) count —
                            # avoids logging no-op merges.
                            light_deltas = {
                                k: {"before": pre.get(k), "after": v}
                                for k, v in prefs.items()
                                if pre.get(k) != v
                            }
                            if light_deltas:
                                deltas[light_id] = light_deltas
                            state[light_id] = {**pre, **prefs}
                    ml_logger_ref = getattr(self, "_ml_logger", None)
                    if deltas and ml_logger_ref:
                        await ml_logger_ref.log_decision(
                            predicted_mode=mode,
                            confidence=None,
                            decision_source="lighting_learner",
                            factors={
                                "period": period,
                                "deltas": deltas,
                            },
                            applied=True,
                        )

            state = self._apply_brightness_multiplier(state, mode)
            state = self._apply_lux_multiplier(state, mode)
            state = self._functional_weather_brightness(state, mode, period)
            state = self._apply_zone_overlay(state, mode, period)
            if mode not in WEATHER_SKIP_MODES:
                state = self._weather_adjust(state)
            tt = MODE_TRANSITION_TIME.get(mode)
            await self._apply_state(state, transitiontime=tt)

            # Reconcile effect AFTER the state is on the bridge — this
            # avoids the brightness pop that happens when an effect is
            # stopped before the target brightness is known to the bridge.
            await self._reconcile_effect(desired_effect)
        else:
            # Unknown mode — fall back to time-based
            await self._apply_time_based()

    async def _apply_social_style(self) -> None:
        """Apply the Velvet Speakeasy social palette — static, no effect.

        Single-palette replacement for the old sub-style system (color_cycle/
        club/rave/fire_and_ice). The dusty-rose + cognac + burnt-orange
        combination is intentionally static: warm deep saturation flatters
        skin and drinks without cycling that reads as "RGB gamer strip".
        """
        await self._apply_state(
            ACTIVITY_LIGHT_STATES["social"],
            transitiontime=MODE_TRANSITION_TIME["social"],
        )
        await self._reconcile_effect(None)

    async def _sleep_fade(self) -> None:
        """
        Dim lights then turn off.

        Manual trigger: quick ~24s fade from the bri=20 initial set by
            _apply_mode's sleeping branch down to off. Anthony is already
            in bed when he triggers this — he doesn't want to wait.
        Auto-detected: slow 10-minute stepwise fade from the current
            brightness (drifted off naturally, let him down gently).

        Runs as a background task so it doesn't block the automation loop.
        Cancellable if the user wakes up (activity detector fires).
        """
        try:
            if self._manual_override:
                # Manual: _apply_mode already set bri=20 deep ember. Brief hold
                # so the dim start is visible, then smooth 20s slide to near-off,
                # then off.
                await asyncio.sleep(2.0)
                self._invalidate_dedup_cache()
                await self._apply_state(
                    {"on": True, "bri": 1, "hue": 5000, "sat": 254},
                    transitiontime=200,  # 20s
                )
                await asyncio.sleep(22)
                self._invalidate_dedup_cache()
                await self._apply_state({"on": False})
                logger.info("Sleep fade complete (manual, ~24s)")
                return

            # Auto-detected: 10-minute gradual stepwise fade from the current
            # bridge brightness. Use a conservative default if the bridge read
            # fails so the fade still lands.
            lights = await self._hue.get_all_lights()
            current_bri = lights[0].get("bri", 80) if lights else 80
            steps = 6
            step_interval = 100  # 6 × 100s ≈ 10 min
            bri_step = current_bri / steps

            logger.info(
                f"Sleep fade started: {current_bri} → off over ~10 minutes (auto)"
            )

            for i in range(1, steps + 1):
                await asyncio.sleep(step_interval)
                new_bri = max(1, int(current_bri - bri_step * i))
                state = {"on": True, "bri": new_bri, "hue": 6000, "sat": 200}
                self._invalidate_dedup_cache()
                await self._apply_state(state)
                logger.info(f"Sleep fade step {i}/{steps}: bri={new_bri}")

            await asyncio.sleep(step_interval)
            self._invalidate_dedup_cache()
            await self._apply_state({"on": False})
            logger.info("Sleep fade complete — lights off")

        except asyncio.CancelledError:
            logger.info("Sleep fade cancelled")
            raise
        except Exception as e:
            logger.error(f"Sleep fade error: {e}", exc_info=True)

    async def _apply_state(
        self, state: dict[str, Any], transitiontime: int | None = None,
    ) -> None:
        """
        Apply a light state — supports both uniform and per-light formats.

        Args:
            state: Either a flat dict (applied to all lights) or a dict keyed
                   by light ID with individual states per light.
            transitiontime: Transition duration in deciseconds (10 = 1s).
                            Injected into each light command if provided.
        """
        if not self._hue or not self._hue.connected:
            return

        # Detect format: per-light dicts have string keys like "1", "2"
        is_per_light = all(
            isinstance(v, dict) for v in state.values()
        ) and any(k in ALL_LIGHT_IDS for k in state.keys())

        if is_per_light:
            await self._apply_per_light(state, transitiontime)
        else:
            await self._apply_uniform(state, transitiontime)

    def _protected_light_ids(self) -> set[str]:
        """Light ids the mode-apply pipeline must NOT write this tick.

        Always includes manual + transit per-light overrides. Additionally
        includes the screen-sync target lamps (L2/L5) while sync is actively
        owning them — current mode is a SCREEN_SYNC_MODE and a color was
        pushed within ``SCREEN_SYNC_FRESH_SECONDS``. Screen sync writes those
        lamps directly to the bridge (bypassing the per-light dedup cache),
        so without this guard the periodic mode-reapply — and every
        ``notify_camera_commit`` force-resend — re-writes them to their
        static state, fighting sync and producing the visible L2/L5 flicker
        (audit 2026-05-30, syncfight-1). When sync goes quiet the freshness
        gate lapses and the engine reclaims the lamps on the next tick.
        """
        protected = set(self._manual_light_overrides) | set(self._transit_light_overrides)
        sync = self._screen_sync
        if sync is not None and self.current_mode in SCREEN_SYNC_MODES:
            last = sync.last_color_at
            if last is not None:
                age = (datetime.now(timezone.utc) - last).total_seconds()
                if age < SCREEN_SYNC_FRESH_SECONDS:
                    protected |= set(sync.target_lights)
        return protected

    async def _apply_uniform(
        self, state: dict[str, Any], transitiontime: int | None = None,
    ) -> None:
        """Apply the same state to all lights (backward-compatible path)."""
        # Prune expired transit overrides before consulting them.
        self._prune_expired_transit_overrides()

        # If any lights are protected (manual / transit overrides, or sync-
        # owned L2/L5), fall through to the per-light path so the filter can
        # skip them instead of stomping them via set_all_lights.
        if self._protected_light_ids():
            per_light = {lid: state for lid in ALL_LIGHT_IDS}
            await self._apply_per_light(per_light, transitiontime)
            return

        # Convert to per-light for dedup tracking
        per_light = {lid: state for lid in ALL_LIGHT_IDS}
        if per_light == self._last_applied_per_light:
            return

        prev_snapshot = {lid: (self._last_applied_per_light.get(lid) or {}).copy() for lid in ALL_LIGHT_IDS}
        self._last_applied_per_light = {lid: state.copy() for lid in ALL_LIGHT_IDS}
        cmd = {**state}
        if transitiontime is not None:
            cmd["transitiontime"] = transitiontime
        await self._hue.set_all_lights(cmd)
        logger.info(f"Applied uniform state: bri={state.get('bri')}, hue={state.get('hue')}")
        if self._event_logger:
            for lid in ALL_LIGHT_IDS:
                prev = prev_snapshot.get(lid, {})
                await self._event_logger.log_light_adjustment(
                    light_id=lid,
                    bri_before=prev.get("bri"), bri_after=state.get("bri"),
                    hue_before=prev.get("hue"), hue_after=state.get("hue"),
                    sat_before=prev.get("sat"), sat_after=state.get("sat"),
                    ct_before=prev.get("ct"), ct_after=state.get("ct"),
                    mode_at_time=self.current_mode,
                    trigger="automation",
                )

    async def _apply_per_light(
        self, states: dict[str, dict], transitiontime: int | None = None,
    ) -> None:
        """Apply individual states to each light (parallel when possible)."""
        # Drop any transit overrides whose deadline has passed before we check.
        self._prune_expired_transit_overrides()

        # Filter out protected lights: manual + transit per-light overrides,
        # plus screen-sync-owned L2/L5 while sync is fresh (see
        # _protected_light_ids — stops the static-vs-sync flicker).
        protected = self._protected_light_ids()
        if protected:
            skipped = [lid for lid in states if lid in protected]
            if skipped:
                states = {
                    lid: s for lid, s in states.items() if lid not in protected
                }
                logger.debug(f"Skipping overridden lights: {skipped}")
                if not states:
                    return

        # Optimization: if all lights get the same state, use the uniform path
        unique_states = list(states.values())
        if not protected and all(
            s == unique_states[0] for s in unique_states
        ):
            await self._apply_uniform(unique_states[0], transitiontime)
            return

        # Build list of lights that actually changed
        tasks = []
        changed_ids = []
        # Keep the pre-change value per light so we can log accurate before/after pairs
        pre_values: dict[str, dict] = {}
        for light_id, state in states.items():
            last = self._last_applied_per_light.get(light_id)
            if state != last:
                pre_values[light_id] = (last or {}).copy()
                cmd = {**state}
                if transitiontime is not None:
                    cmd["transitiontime"] = transitiontime
                tasks.append(self._hue.set_light(light_id, cmd))
                self._last_applied_per_light[light_id] = state.copy()
                changed_ids.append(light_id)

        if tasks:
            await asyncio.gather(*tasks)
            on_ids = [lid for lid in changed_ids if states[lid].get("on", True)]
            off_ids = [lid for lid in changed_ids if not states[lid].get("on", True)]
            logger.info(f"Applied per-light state: on={on_ids}, off={off_ids}")
            if self._event_logger:
                for lid in changed_ids:
                    new = states[lid]
                    prev = pre_values.get(lid, {})
                    await self._event_logger.log_light_adjustment(
                        light_id=lid,
                        bri_before=prev.get("bri"), bri_after=new.get("bri"),
                        hue_before=prev.get("hue"), hue_after=new.get("hue"),
                        sat_before=prev.get("sat"), sat_after=new.get("sat"),
                        ct_before=prev.get("ct"), ct_after=new.get("ct"),
                        mode_at_time=self.current_mode,
                        trigger="automation",
                    )

    async def _maybe_drift(self) -> None:
        """
        Apply subtle random perturbation to current light state if the mode
        has been unchanged for drift_interval_minutes. Prevents the "nothing
        ever changes" feeling during long sessions.
        """
        if not self._scene_drift_enabled:
            return
        # Drift is aesthetic variation — it only belongs in relax. Functional
        # modes (working/gaming/watching/cooking) need stable, predictable light
        # values; independent per-light deltas there make paired lights look
        # randomly unequal. Social has its own sub-style cycling; sleeping/idle
        # are handled by other paths.
        mode = self.current_mode
        if mode != "relax":
            return

        now = datetime.now(tz=TZ)

        # Need a stable mode for at least drift_interval minutes
        if self._last_activity_change:
            minutes_in_mode = (now - self._last_activity_change).total_seconds() / 60
            if minutes_in_mode < self._drift_interval_minutes:
                return

        # Throttle drift frequency
        if self._last_drift_time:
            since_drift = (now - self._last_drift_time).total_seconds() / 60
            if since_drift < self._drift_interval_minutes:
                return

        self._last_drift_time = now

        # Get the base state and apply small random deltas
        period = self._get_time_period()
        base = _resolve_activity_state(mode, period)
        if not base:
            return

        drifted: dict[str, dict] = {}
        for lid in ALL_LIGHT_IDS:
            ls = base.get(lid, {})
            if not ls or not ls.get("on", True):
                drifted[lid] = ls
                continue
            d = {**ls}
            if "bri" in d:
                d["bri"] = max(1, min(254, d["bri"] + random.randint(-15, 15)))
            if "hue" in d:
                d["hue"] = max(0, min(65535, d["hue"] + random.randint(-1500, 1500)))
            if "sat" in d:
                d["sat"] = max(0, min(254, d["sat"] + random.randint(-20, 20)))
            if "ct" in d:
                d["ct"] = max(153, min(500, d["ct"] + random.randint(-15, 15)))
            drifted[lid] = d

        drifted = self._apply_brightness_multiplier(drifted, mode)
        drifted = self._apply_lux_multiplier(drifted, mode)
        drifted = self._functional_weather_brightness(drifted, mode, period)
        if mode not in WEATHER_SKIP_MODES:
            drifted = self._weather_adjust(drifted)
        self._invalidate_dedup_cache()  # Force apply
        await self._apply_state(drifted, transitiontime=100)  # 10s imperceptible
        logger.info("Scene drift applied for mode '%s'", mode)

    def _weather_adjust(self, state: dict[str, Any]) -> dict[str, Any]:
        """Apply subtle weather-based adjustments (shim → calculator).

        Reads weather off the wired service, classifies it, and hands
        off to the pure calculator function. ``None`` condition (no
        match or no weather data) is a no-op.
        """
        condition = self._get_current_weather_condition()
        if condition is not None:
            logger.debug("Weather adjustment: %s", condition)
        return _calc_apply_weather_adjust(state, condition)

    def _classify_weather(
        self, desc: str, weather: dict[str, Any],
    ) -> str | None:
        """Map weather description to a condition category (shim → calculator)."""
        return _classify_weather_pure(desc, weather)

    def _functional_weather_brightness(
        self, state: dict[str, Any], mode: str, period: str,
    ) -> dict[str, Any]:
        """Brighten functional-mode lights on dim weather (shim → calculator).

        Resolves the set of light_ids the LightingLearner has already
        learned a weather-specific preference for; those lights skip the
        heuristic boost (Layer 5 fade-out gate) so the user's accepted
        preference isn't double-applied on top of the heuristic.
        """
        condition = self._get_current_weather_condition()
        learner = getattr(self, "_lighting_learner", None)
        learned: set[str] = set()
        if learner and condition:
            try:
                learned = learner.has_weather_pref(mode, period, condition)
            except Exception:
                learned = set()
        return _calc_apply_functional_weather_brightness(
            state, mode, period, condition,
            learner_has_learned=learned,
        )

    def _get_desired_effect(
        self, mode: str,
    ) -> Optional[str | dict[str, Any]]:
        """Determine the dynamic effect target for a mode (shim → effect_manager)."""
        return self._effect_manager.get_desired_effect(mode, self._get_time_period())

    def _get_weather_effect(self) -> str | None:
        """Weather-condition effect override (shim → effect_manager)."""
        return self._effect_manager.get_weather_effect()

    @property
    def _active_effect_name(self) -> Optional[str]:
        """Currently-active effect name (delegates to effect_manager)."""
        return self._effect_manager.active_name

    @property
    def _active_effect_lights(self) -> Optional[list[str]]:
        """Light scope of the currently-active effect (delegates to effect_manager)."""
        return self._effect_manager.active_lights

    def _get_current_weather_condition(self) -> str | None:
        """Return the classified weather condition string, or None."""
        if not self._weather_service:
            return None
        try:
            weather = self._weather_service.get_cached()
            if not weather:
                return None
        except Exception:
            return None
        desc = weather.get("description", "").lower()
        return self._classify_weather(desc, weather)

    # _adjust_single_light is kept as a static-method shim so any
    # external caller / test that grabs `engine._adjust_single_light`
    # keeps working. Implementation lives in light_state_calculator.
    _adjust_single_light = staticmethod(_adjust_single_light_pure)

    async def _apply_time_based(self) -> None:
        """Apply the time-appropriate light state (weekday/weekend aware)."""
        now = datetime.now(tz=TZ)
        hour = now.hour
        minute = now.minute

        # Select schedule config based on day of week
        schedule = (
            self._schedule_config.weekday
            if now.weekday() < 5
            else self._schedule_config.weekend
        )
        rules = self._build_time_rules(schedule)

        # Evening → wind-down fade: interpolate over the 30 min before winddown_start_hour
        winddown_total_minute = schedule.winddown_start_hour * 60
        current_total_minute = hour * 60 + minute
        minutes_until_winddown = winddown_total_minute - current_total_minute

        if 0 < minutes_until_winddown <= WINDDOWN_RAMP_MINUTES:
            progress = (WINDDOWN_RAMP_MINUTES - minutes_until_winddown) / WINDDOWN_RAMP_MINUTES
            evening_state: dict[str, Any] = {"on": True, "bri": 180, "hue": 8000, "sat": 160}
            winddown_state: dict[str, Any] = {"on": True, "bri": 60, "hue": 5500, "sat": 220}
            state = _lerp_light_state(evening_state, winddown_state, progress)
            state = self._weather_adjust(state)
            await self._apply_state(state)
            return

        for start, end, rule in rules:
            if start <= hour < end:
                if isinstance(rule, tuple) and rule[0] == "morning_ramp":
                    _, ramp_start_hour, ramp_duration = rule
                    # Suppress the ramp if the user is likely still asleep.
                    # Reference incident 2026-05-15: watching held all night,
                    # PC went idle at 06:05, this ramp climbed bri 80→196
                    # over 36min and woke the user. Hold the pre-ramp dim
                    # state (same shape as the wake_hour → ramp_start_hour
                    # rule from `_build_time_rules`) until attendance lands.
                    if self._is_likely_still_asleep(now):
                        state = {
                            "on": True,
                            "bri": schedule.wake_brightness,
                            "hue": 6000,
                            "sat": 200,
                        }
                        logger.info(
                            "Morning ramp suppressed — user likely still asleep "
                            "(bed+reclined observed at %s)",
                            self._last_bed_reclined_during_watching_at,
                        )
                    else:
                        minutes_since_start = (hour - ramp_start_hour) * 60 + minute
                        state = _morning_ramp(minutes_since_start, ramp_duration)
                elif isinstance(rule, dict):
                    state = rule
                else:
                    logger.warning("Unknown rule shape in time-based rules: %r", rule)
                    return
                state = self._weather_adjust(state)
                await self._apply_state(state)
                return

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def run_loop(self) -> None:
        """
        Background task — checks every 60 seconds if lights need updating.

        Handles:
        - Time-based transitions (gradual morning ramp, evening dimming)
        - Manual override timeout (auto-clears after N hours)
        - External off detection (Alexa geofence — don't override)
        """
        logger.info("Automation engine started")

        # Seed _last_process_working_at from DB so the late-night rescue and
        # ambient-relax attendance vetoes are live immediately after a restart.
        # Without this, there's a window (up to RECENT_PROCESS_WORKING_SECONDS)
        # where a fresh process=working report can't defend against a rescue
        # that evaluates on the first tick post-restart. Confirmed incident:
        # 2026-06-02 03:13 UTC rescue fired 46s after a working POST.
        try:
            from backend.database import async_session
            from backend.models import ActivityEvent
            from sqlalchemy import select

            async with async_session() as _seed_db:
                _seed_row = (await _seed_db.execute(
                    select(ActivityEvent.timestamp)
                    .where(ActivityEvent.source == "process")
                    .where(ActivityEvent.mode == "working")
                    .order_by(ActivityEvent.timestamp.desc())
                    .limit(1)
                )).fetchone()
                if _seed_row:
                    _seed_ts = _seed_row[0]
                    if _seed_ts.tzinfo is None:
                        _seed_ts = _seed_ts.replace(tzinfo=timezone.utc)
                    _seed_age = (datetime.now(tz=TZ) - _seed_ts).total_seconds()
                    if _seed_age < RECENT_PROCESS_WORKING_SECONDS:
                        self._last_process_working_at = _seed_ts
                        logger.info(
                            "Seeded _last_process_working_at from DB (age=%.0fs)",
                            _seed_age,
                        )
        except Exception:
            logger.warning(
                "Could not seed _last_process_working_at from DB", exc_info=True,
            )

        while True:
            try:
                if self._heartbeat is not None:
                    self._heartbeat.tick("automation")
                if not self._enabled:
                    await asyncio.sleep(60)
                    continue

                now = datetime.now(tz=TZ)

                # DND auto-expiry — once-per-tick lazy clear. is_dnd_active()
                # itself is side-effect free; we run the persist + WS broadcast
                # here so the dashboard learns about expiry within ~60s.
                if self._dnd.should_expire(now):
                    logger.info("DND auto-expired at %s", now.isoformat())
                    await self.clear_dnd(source="auto_expiry")

                # Check manual override timeout. Sleeping is persistent:
                # a 4-hour timeout at ~3am would hand control back to the
                # detected-mode path, which can turn lights on while the
                # user is still asleep. Anthony clears sleeping manually
                # when he wakes up.
                if (
                    self._manual_override
                    and self._override_time
                    and self._override_mode != "sleeping"
                ):
                    elapsed = now - self._override_time
                    if elapsed > timedelta(hours=self._override_timeout_hours):
                        logger.info(
                            f"Manual override timed out after "
                            f"{self._override_timeout_hours}h"
                        )
                        await self.clear_override(source="timeout_4h")

                # Expire stale per-light overrides (same 4h window as the
                # mode-level override, tracked per-entry via the datetime
                # stamped in mark_light_manual).
                if self._manual_light_overrides:
                    cutoff = timedelta(hours=self._override_timeout_hours)
                    expired = [
                        lid for lid, ts in self._manual_light_overrides.items()
                        if now - ts > cutoff
                    ]
                    for lid in expired:
                        del self._manual_light_overrides[lid]
                        logger.info(
                            f"Per-light override on light {lid} expired "
                            f"after {self._override_timeout_hours}h"
                        )

                # Check for external off (Alexa geofence)
                if await self._check_external_off():
                    await asyncio.sleep(60)
                    continue

                # Late-night rescue — after late_night_start_hour, prefer relax
                # over "still working" or idle when no Sonos media is playing.
                # Catches the 02:00+ edge when someone's still at the desk.
                # Guarded so real gaming/watching/social/sleeping are respected,
                # and music playback counts as intentional activity. Attendance
                # vetoes (camera at desk / recent process working) are checked
                # inside the block so suppressed rescues are logged to
                # ml_decisions for observability — mirrors the predictor path.
                if (
                    not self._manual_override
                    and not self.is_dnd_active()
                    and self._get_time_period() == "late_night"
                    and self._current_mode in ("working", "idle")
                    and not await self._sonos_is_playing()
                ):
                    _rescue_veto: str | None = None
                    if self.is_at_desk_fresh():
                        _rescue_veto = "camera_at_desk"
                    elif self.is_recent_process_working():
                        _rescue_veto = "process_working_recent"

                    if _rescue_veto is None:
                        logger.info(
                            "Late-night rescue: switching to relax from %s",
                            self._current_mode,
                        )
                        await self.set_manual_override("relax", source="late_night_rescue")
                    else:
                        logger.debug(
                            "Late-night rescue suppressed (%s)", _rescue_veto,
                        )
                        _rescue_ml = getattr(self, "_ml_logger", None)
                        if _rescue_ml:
                            await _rescue_ml.log_decision(
                                predicted_mode="relax",
                                confidence=1.0,
                                decision_source="late_night_rescue",
                                factors={"vetoed_by": _rescue_veto},
                                applied=False,
                                broadcast=False,
                            )

                # Ambient relax — soft default when nothing's happening. Idle
                # held for IDLE_AMBIENT_RELAX_DWELL_SECONDS without any
                # attendance signal, no Sonos → push to relax. Day-agnostic;
                # the late_night branch above handles the post-23:00 case where
                # mode is still "working" (vs idle) at the desk.
                #
                # is_present_in_room() stays in the outer elif (camera sees
                # someone on the couch → just not our trigger, not a veto).
                # Attendance vetoes (at-desk / recent-process-working) move
                # inside for the same ml_decisions observability as the rescue.
                elif (
                    not self._manual_override
                    and not self.is_dnd_active()
                    and not self.is_present_in_room()
                    and self._current_mode == "idle"
                    and self._idle_entered_at is not None
                    and (now - self._idle_entered_at).total_seconds()
                        >= IDLE_AMBIENT_RELAX_DWELL_SECONDS
                    and not await self._sonos_is_playing()
                ):
                    _relax_veto: str | None = None
                    if self.is_at_desk_fresh():
                        _relax_veto = "camera_at_desk"
                    elif self.is_recent_process_working():
                        _relax_veto = "process_working_recent"

                    if _relax_veto is None:
                        logger.info(
                            "Ambient relax: idle held %.0fs without presence "
                            "— switching to relax",
                            (now - self._idle_entered_at).total_seconds(),
                        )
                        await self.set_manual_override("relax", source="ambient_relax")
                    else:
                        logger.debug(
                            "Ambient relax suppressed (%s)", _relax_veto,
                        )
                        _relax_ml = getattr(self, "_ml_logger", None)
                        if _relax_ml:
                            await _relax_ml.log_decision(
                                predicted_mode="relax",
                                confidence=1.0,
                                decision_source="ambient_relax",
                                factors={"vetoed_by": _relax_veto},
                                applied=False,
                                broadcast=False,
                            )

                # If no activity override and no manual override, apply time-based
                if (
                    not self._manual_override
                    and self._current_mode in ("idle",)
                ):
                    await self._apply_time_based()
                elif (
                    not self._manual_override
                    and self._current_mode not in ("idle", "social")
                ):
                    # Re-apply activity mode to pick up day→evening→night transitions.
                    # force_resend=False so dedup in _last_applied_per_light makes
                    # this a true no-op when nothing changed (the common case).
                    await self._apply_mode(self._current_mode)

                # Scene drift — subtle variety during long sessions
                if not self._manual_override:
                    await self._maybe_drift()

                # Weather-driven music suggestions
                weather_condition = self._get_current_weather_condition()
                if weather_condition != self._last_weather_condition:
                    self._last_weather_condition = weather_condition
                    if weather_condition and self._music_mapper:
                        await self._music_mapper.on_weather_change(
                            weather_condition, self._current_mode,
                        )

                # ML behavioral predictor — runs every cycle for shadow-mode
                # telemetry only. The fusion lane was removed 2026-04-27 after
                # the model collapsed to a single output class (see
                # `project_path_a_checkbacks.md`); shadow logging continues so
                # we can verify a future retrain breaks the degeneracy before
                # rewiring it back into fusion.
                predictor = getattr(self, "_behavioral_predictor", None)
                ml_logger = getattr(self, "_ml_logger", None)
                prediction = None
                if predictor and not self._manual_override:
                    # Pass the same camera + audio context EventLogger
                    # captures at training time so inference sees the
                    # feature shape the model was trained on. Camera
                    # values use the freshness-gated read so a stale
                    # committed value (e.g. user left an hour ago)
                    # doesn't poison the prediction.
                    from backend.services.ml.feature_builder import (
                        latest_audio_class,
                    )
                    camera = self._camera_service
                    prediction = await predictor.predict(
                        current_mode=self._current_mode,
                        zone=(
                            self._fresh_camera_attr(
                                camera, "zone", "zone_committed_at",
                            ) if camera else None
                        ),
                        posture=(
                            self._fresh_camera_attr(
                                camera, "posture", "posture_committed_at",
                            ) if camera else None
                        ),
                        audio_class=await latest_audio_class(),
                        lux=getattr(camera, "ema_lux", None) if camera else None,
                    )
                if (
                    prediction
                    and not self._manual_override
                    and self._current_mode in ("idle",)
                ):
                    if not prediction.get("shadow"):
                        confidence = prediction["confidence"]
                        if confidence >= 0.95:
                            # Auto-apply at high confidence — unless the user
                            # is demonstrably present (camera at desk OR PC
                            # agent reported working within the last 10min),
                            # in which case defer to active presence and log
                            # the veto for audit. Parallel-veto pattern mirrors
                            # late_night_rescue (commit 0dcb245).
                            veto_reason: str | None = None
                            if self.is_at_desk_fresh():
                                veto_reason = "camera_at_desk"
                            elif self.is_recent_process_working():
                                veto_reason = "process_working_recent"

                            if veto_reason is not None:
                                logger.debug(
                                    "Predictor suppressed (%s): %s @ %.2f",
                                    veto_reason,
                                    prediction["predicted_mode"], confidence,
                                )
                                if ml_logger:
                                    factors = dict(prediction.get("factors") or {})
                                    factors["vetoed_by"] = veto_reason
                                    await ml_logger.log_decision(
                                        predicted_mode=prediction["predicted_mode"],
                                        confidence=confidence,
                                        decision_source="ml",
                                        factors=factors,
                                        applied=False,
                                    )
                            else:
                                await self.set_manual_override(
                                    prediction["predicted_mode"],
                                    source="behavioral_predictor",
                                )
                                if ml_logger:
                                    await ml_logger.log_decision(
                                        predicted_mode=prediction["predicted_mode"],
                                        confidence=confidence,
                                        decision_source="ml",
                                        factors=prediction.get("factors"),
                                        applied=True,
                                    )
                        elif confidence >= 0.70:
                            # Suggest via WebSocket toast (suppressed during DND
                            # — prediction toasts feel like automation noise to
                            # someone who explicitly asked for quiet)
                            if not self.is_dnd_active():
                                await self._ws_manager.broadcast(
                                    "ml_prediction", prediction
                                )
                            if ml_logger:
                                await ml_logger.log_decision(
                                    predicted_mode=prediction["predicted_mode"],
                                    confidence=confidence,
                                    decision_source="ml",
                                    factors=prediction.get("factors"),
                                    applied=False,
                                )
                    elif prediction and prediction.get("shadow") and ml_logger:
                        # Shadow mode: log but don't act
                        await ml_logger.log_decision(
                            predicted_mode=prediction["predicted_mode"],
                            confidence=prediction["confidence"],
                            decision_source="ml",
                            factors=prediction.get("factors"),
                            applied=False,
                        )

                # Rule engine — runs every cycle to keep its fusion vote
                # fresh, even under a manual override. check_rules()
                # internally gates the user-nudge path on current_mode == idle.
                rule_engine = getattr(self, "_rule_engine", None)
                if rule_engine:
                    await rule_engine.check_rules(self._current_mode)
                    # Auto-expire pending rule_suggestions older than 60min so
                    # the Home banner doesn't outlive its usefulness. No-op
                    # when nothing to expire (single indexed query per tick).
                    await rule_engine.expire_stale_pending()

                # Confidence fusion — compute and optionally act
                fusion = getattr(self, "_confidence_fusion", None)
                if fusion:
                    fusion_result = fusion.compute_fusion()
                    if fusion_result:
                        self._last_fusion_result = fusion_result
                        fc = fusion_result["fused_confidence"]
                        fm = fusion_result["fused_mode"]
                        acted = False

                        # Can override stale process detection at 92%+
                        # with 80%+ agreement — unless camera sees Anthony
                        # at the desk, in which case fusion's vote loses
                        # to direct physical presence and the decision is
                        # logged as vetoed instead of actuated.
                        if (
                            fusion_result.get("can_override")
                            and not self._manual_override
                            and self._current_mode not in ("idle",)
                            and fm != self._current_mode
                        ):
                            if self.is_at_desk_fresh():
                                logger.debug(
                                    "Fusion override suppressed (camera at "
                                    "desk): %s -> %s @ %.2f",
                                    self._current_mode, fm, fc,
                                )
                                if ml_logger:
                                    await ml_logger.log_decision(
                                        predicted_mode=fm,
                                        confidence=fc,
                                        decision_source="fusion",
                                        factors={
                                            "agreement": fusion_result["agreement"],
                                            "signal_details": fusion_result["signals"],
                                            "action": "override",
                                            "vetoed_by": "camera_at_desk",
                                        },
                                        applied=False,
                                    )
                                acted = True  # don't double-log as shadow below
                            else:
                                logger.info(
                                    "Fusion override: %s -> %s "
                                    "(%.0f%% confidence, %.0f%% agreement)",
                                    self._current_mode, fm, fc * 100,
                                    fusion_result["agreement"] * 100,
                                )
                                await self.set_manual_override(fm, source="fusion_can_override")
                                acted = True
                                if ml_logger:
                                    await ml_logger.log_decision(
                                        predicted_mode=fm,
                                        confidence=fc,
                                        decision_source="fusion",
                                        factors={
                                            "agreement": fusion_result["agreement"],
                                            "active_signals": len([
                                                s for s in
                                                fusion_result["signals"].values()
                                                if not s["stale"]
                                            ]),
                                            "signal_details": fusion_result["signals"],
                                            "action": "override",
                                        },
                                        applied=True,
                                    )
                        elif (
                            fc >= 0.95
                            and not self._manual_override
                            and self._current_mode in ("idle",)
                            and fm != self._current_mode
                            and not self.is_at_desk_fresh()
                            and not self.is_recent_process_working()
                        ):
                            logger.info(
                                "Fusion auto-apply: %s (%.0f%% confidence)",
                                fm, fc * 100,
                            )
                            await self.set_manual_override(fm, source="fusion_auto_apply")
                            acted = True
                            if ml_logger:
                                await ml_logger.log_decision(
                                    predicted_mode=fm,
                                    confidence=fc,
                                    decision_source="fusion",
                                    factors={
                                        "agreement":
                                            fusion_result["agreement"],
                                        "signal_details":
                                            fusion_result["signals"],
                                        "action": "auto_apply",
                                    },
                                    applied=True,
                                )

                        # Shadow-log every silent fusion tick so
                        # compute_accuracy_by_source has per-signal data
                        # to tune weights against. broadcast=False to
                        # avoid flooding the pipeline WebSocket at 1/min.
                        if not acted and ml_logger:
                            await ml_logger.log_decision(
                                predicted_mode=fm,
                                confidence=fc,
                                decision_source="fusion",
                                factors={
                                    "agreement": fusion_result["agreement"],
                                    "signal_details": fusion_result["signals"],
                                    "current_mode": self._current_mode,
                                    "action": "shadow",
                                },
                                applied=False,
                                broadcast=False,
                            )

                # Zone+posture → relax actuation (shadow-mode by default).
                # Safe to run late in the loop: uses committed camera state
                # that doesn't mutate during this tick, and only acts via
                # set_manual_override which will be respected by the next
                # tick's own manual_override gates.
                await self._evaluate_zone_posture_rule(now)

                # Watching → sleeping guard. Catches "fell asleep with
                # YouTube on the projector" — the case late_night_rescue
                # can't reach because watching ≠ working/idle. Same
                # camera-state safety as zone+posture above.
                await self._evaluate_watching_sleep_guard(now)

                # Periodic pipeline broadcast — keeps the pipeline view fresh
                # even when no mode changes occur (e.g., time period transitions)
                await self._broadcast_pipeline()

                await asyncio.sleep(60)

            except asyncio.CancelledError:
                logger.info("Automation engine stopped")
                break
            except Exception as e:
                logger.error(f"Automation engine error: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _evaluate_zone_posture_rule(self, now: datetime) -> None:
        """Zone+posture → relax actuation rule.

        DORMANT since the 2026-05-27 Latitude→living-room move: no camera
        produces ``zone="bed"`` anymore, so the bed+reclined gate can never
        pass and this rule no-ops every tick. Kept (not deleted) pending a
        possible light-touch desktop bed-detection path; remove this and the
        ``ZONE_POSTURE_RULE_APPLY`` env gate if bed coverage is abandoned.

        First mode-changing sensor actuation — fires when the camera
        observes bed+reclined sustained for ``ZONE_POSTURE_RULE_DWELL_SECONDS``,
        subject to mode / override / time-of-day / refractory gates. Logs
        ml_decisions with ``decision_source="zone_posture_rule"`` on every
        fire or shadow-would-fire so the pattern is visible.

        Shadow vs live is controlled by ``settings.ZONE_POSTURE_RULE_APPLY``:
        shadow mode logs applied=False and does not call set_manual_override;
        live mode logs applied=True and applies the override. Both paths use
        the same gates, so shadow data is a faithful preview of live
        behavior.
        """
        camera = self._camera_service
        if camera is None:
            return

        # Gate 0: DND suppresses the dwell timer entirely so we don't
        # accumulate a "would have fired" stamp during a quiet window.
        # set_manual_override would block the actuation anyway, but
        # resetting the dwell here keeps shadow logs honest.
        if self.is_dnd_active():
            self._zone_posture_reclined_since = None
            return

        # Gate 1: any active manual override takes precedence — EXCEPT
        # `social`, which we allow the rule to supersede when it's been
        # in place ≥SOCIAL_MIN_AGE. Social tends to outlive its context
        # (guest left, host stayed in social then went to bed); the
        # min-age gate protects an actively-set social from instant override.
        if self._manual_override:
            if self._override_mode != "social":
                self._zone_posture_reclined_since = None
                return
            override_age = (
                (now - self._override_time).total_seconds()
                if self._override_time else 0
            )
            if override_age < ZONE_POSTURE_RULE_SOCIAL_MIN_AGE_SECONDS:
                self._zone_posture_reclined_since = None
                return

        # Gate 2: recent fire suppression — parallels override_timeout_hours
        # so shadow logging cadence matches what live firing would produce.
        # Once a live fire sets an override, gate 1 handles suppression for
        # the full override window; when the override expires this gate lets
        # a fresh dwell accumulate for the next legitimate trigger.
        if self._zone_posture_last_fired_at and (
            (now - self._zone_posture_last_fired_at).total_seconds()
            < self._override_timeout_hours * 3600
        ):
            self._zone_posture_reclined_since = None
            return

        # Gate 2.5: user-clear cooldown. When the user just cleared an
        # override via the dashboard, set_manual_override silently rejects
        # autonomous-source pushes for USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS.
        # Without this gate the rule would still meet dwell, log applied=1,
        # and burn its 4h refractory on a fire that set_manual_override
        # threw away — locking the rule out for the rest of the night even
        # after the cooldown expired (2026-05-05 incident). Reset the dwell
        # so a fresh 120s of bed+reclined is required after the cooldown.
        if self._user_cleared_override_at is not None:
            elapsed = (
                (now - self._user_cleared_override_at).total_seconds()
            )
            if elapsed < USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS:
                self._zone_posture_reclined_since = None
                return

        # Gate 3: the core condition — committed zone + posture.
        zone = camera.zone
        posture = camera.posture
        if zone != "bed" or posture != "reclined":
            self._zone_posture_reclined_since = None
            return

        # Gate 4: eligible mode. Use override mode when override is active
        # (only social reaches here per gate 1), else current detected mode.
        # Explicit modes other than social (gaming/watching/cooking/sleeping)
        # and relax itself are excluded.
        effective_mode = (
            self._override_mode if self._manual_override else self._current_mode
        )
        if effective_mode not in ZONE_POSTURE_RULE_ELIGIBLE_MODES:
            self._zone_posture_reclined_since = None
            return

        # Gate 5: time-of-day — evening through pre-wake (wraps midnight);
        # weekends also allow afternoon. Without the midnight wrap the rule
        # would silently disengage exactly when it's most needed (the
        # 2026-05-05 incident: bed+reclined at 04:30 ET kept the lights
        # bright because hour=4 failed `hour >= evening_start_hour`).
        is_weekend = now.weekday() >= 5
        schedule = (
            self._schedule_config.weekend if is_weekend
            else self._schedule_config.weekday
        )
        afternoon_ok = (
            is_weekend and now.hour >= ZONE_POSTURE_RULE_WEEKEND_AFTERNOON_HOUR
        )
        evening_ok = (
            now.hour >= schedule.evening_start_hour
            or now.hour < schedule.wake_hour
        )
        if not (afternoon_ok or evening_ok):
            self._zone_posture_reclined_since = None
            return

        # All gates pass — start / continue the dwell timer.
        if self._zone_posture_reclined_since is None:
            self._zone_posture_reclined_since = now
            return

        elapsed = (now - self._zone_posture_reclined_since).total_seconds()
        dwell_required = (
            ZONE_POSTURE_RULE_DWELL_SOCIAL_SECONDS
            if effective_mode == "social"
            else ZONE_POSTURE_RULE_DWELL_SECONDS
        )
        if elapsed < dwell_required:
            return

        # Gate 6: attendance vetoes — even with dwell met, fresh camera-at-desk
        # OR a recent process=working report means the user isn't actually
        # settling in (they're lying back on the bed momentarily while still
        # on the PC). Reset the dwell so a fresh 120s of bed+reclined-with-no-
        # other-activity is required after attendance clears. Same pair of
        # vetoes that gate late_night_rescue + winddown_push since 2026-05-07
        # (commit 0dcb245). Checked here BEFORE the refractory stamp burn —
        # per feedback_rule_refractory_burn_pattern.md, silent-rejection
        # conditions must run before the stamp or the rule locks itself out
        # for 4h on a no-op.
        at_desk = self.is_at_desk_fresh()
        process_working = self.is_recent_process_working()
        if at_desk or process_working:
            logger.debug(
                "Zone+posture rule vetoed at fire-time: at_desk_fresh=%s "
                "recent_process_working=%s — dwell reset",
                at_desk, process_working,
            )
            self._zone_posture_reclined_since = None
            return

        # Dwell met — fire (live) or shadow-log.
        should_apply = bool(settings.ZONE_POSTURE_RULE_APPLY)
        trigger_reason = "evening" if evening_ok else "weekend_afternoon"
        factors = {
            "zone": zone,
            "posture": posture,
            "current_mode": self._current_mode,
            "effective_mode": effective_mode,
            "dwell_seconds": int(elapsed),
            "dwell_required": int(dwell_required),
            "is_weekend": is_weekend,
            "hour": now.hour,
            "trigger": trigger_reason,
        }

        # Commit the refractory stamp BEFORE any risky await. If
        # set_manual_override raises (transient Hue error, broadcast
        # failure, callback exception), the stamp is already in-memory
        # and persisted, so gate 2 still suppresses for the next 4h
        # instead of letting the rule re-fire on every dwell window.
        self._zone_posture_last_fired_at = now
        self._zone_posture_reclined_since = None
        await self._persist_override_state()

        # Source attribution (Commit 3 of multi-camera fusion). Stamped
        # AFTER the refractory commit on purpose — the helper is the only
        # remaining thing between the stamp and the ml_logger row, and
        # `feedback_rule_refractory_burn_pattern.md` mandates "stamp
        # first, telemetry second" so a helper exception can't dodge the
        # refractory. Records which presence source's fresh reading
        # carries the zone/posture the rule fired on, so the
        # fusion-lane-auditor can confirm both cameras are contributing
        # to actual decisions rather than just showing up in
        # /api/camera/status diagnostics.
        self._attach_presence_attribution(factors, zone=zone, posture=posture)

        if should_apply:
            logger.info(
                "Zone+posture rule firing: %s + %s held %.0fs → relax",
                zone, posture, elapsed,
            )
            await self.set_manual_override("relax", source="zone_posture_rule")
        else:
            logger.info(
                "Zone+posture rule would fire (shadow): %s + %s held %.0fs",
                zone, posture, elapsed,
            )

        ml_logger = getattr(self, "_ml_logger", None)
        if ml_logger:
            await ml_logger.log_decision(
                predicted_mode="relax",
                confidence=1.0,
                decision_source="zone_posture_rule",
                factors=factors,
                applied=should_apply,
            )

    async def _evaluate_watching_sleep_guard(self, now: datetime) -> None:
        """Watching → sleeping guard rule.

        DORMANT since the 2026-05-27 Latitude→living-room move: needs
        ``zone="bed"`` + ``posture="reclined"`` to start its dwell, neither of
        which any camera produces now, so it never fires (it had also fired 0×
        in production before the move). Kept pending possible desktop
        bed-detection; safe to remove if bed coverage is abandoned for good.

        Catches the "fell asleep with YouTube on the projector" case the
        existing late_night_rescue can't reach (rescue is gated to
        working/idle and skips while a video player is foregrounded).
        Fires when ``mode == watching`` AND the camera observes
        ``zone == bed`` AND ``posture == reclined`` for
        ``WATCHING_SLEEP_GUARD_DWELL_SECONDS`` continuously inside the
        ``late_night`` time period. Always live (no shadow gate) — this
        is a comfort/safety rule, not an experimental classifier.

        Gate ordering follows the same silent-rejection-before-stamp-burn
        pattern as ``_evaluate_zone_posture_rule`` (per
        ``feedback_rule_refractory_burn_pattern.md``): every condition
        that can suppress a fire is checked before the refractory stamp
        is committed, so a no-op tick can never lock the rule out for 4h.
        """
        camera = self._camera_service
        if camera is None:
            return

        # Gate 0: DND suppresses the dwell timer. set_manual_override would
        # block the actuation anyway, but resetting the dwell here keeps the
        # "fresh dwell required after DND" semantic.
        if self.is_dnd_active():
            self._watching_sleep_dwell_since = None
            return

        # Gate 1: refractory — if we already fired within the override
        # timeout, suppress. Reset the dwell so a fresh window is required
        # after expiry. Mirrors zone_posture gate 2.
        if self._watching_sleep_guard_last_fired_at and (
            (now - self._watching_sleep_guard_last_fired_at).total_seconds()
            < self._override_timeout_hours * 3600
        ):
            self._watching_sleep_dwell_since = None
            return

        # Gate 2: user-clear cooldown. set_manual_override silently rejects
        # autonomous sources during this window; without an early reset here
        # the rule would burn its 4h refractory on a fire that was thrown
        # away (the 2026-05-05 zone_posture incident pattern). Drop the
        # dwell so a fresh window is required after the cooldown.
        if self._user_cleared_override_at is not None:
            elapsed = (
                (now - self._user_cleared_override_at).total_seconds()
            )
            if elapsed < USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS:
                self._watching_sleep_dwell_since = None
                return

        # Gate 3: time-of-day. Only fire inside the late_night period
        # (23:00–wake_hour, weekday/weekend-aware). Outside the window,
        # reset dwell — falling asleep at 21:00 watching a movie isn't
        # the case we're trying to catch.
        if self._get_time_period() != "late_night":
            self._watching_sleep_dwell_since = None
            return

        # Gate 4: effective mode must be watching. With manual_override
        # active that means override_mode; otherwise the detected current
        # mode. Anything else resets dwell.
        effective_mode = (
            self._override_mode if self._manual_override else self._current_mode
        )
        if effective_mode != "watching":
            self._watching_sleep_dwell_since = None
            return

        # Gate 5: stale-override supersedure. If the user just tapped
        # watching from the dashboard, give them at least the dwell window
        # before we override. Beyond that the override is presumed to be
        # "they fell asleep with it set." Mirrors the
        # ZONE_POSTURE_RULE_SOCIAL_MIN_AGE_SECONDS pattern.
        if self._manual_override and self._override_time is not None:
            override_age = (now - self._override_time).total_seconds()
            if override_age < WATCHING_SLEEP_GUARD_OVERRIDE_MIN_AGE_SECONDS:
                self._watching_sleep_dwell_since = None
                return

        # Gate 6: core condition — committed zone + posture, with
        # dark-room continuation tolerance.
        #
        # Starting the dwell still requires a confident lock: zone="bed"
        # AND posture="reclined." That's the only way to be sure the user
        # is actually in bed and not at the desk reclined in their chair.
        #
        # But once dwell has started, darkness should not break it.
        # 2026-05-14 incident: camera locked bed+reclined at 23:00, then
        # lost pose detection as the room darkened past the projector's
        # ambient light. After ABSENT_THRESHOLD frames of no commits,
        # camera.zone / camera.posture cleared to None. The old strict
        # check ("zone != 'bed' or posture != 'reclined'") then reset
        # the dwell on every tick for the rest of the night, and the
        # guard never fired — yet this is exactly the case it exists
        # for. RGB pose detection is not IR-aware; sleeping people make
        # rooms dark; the rule has to tolerate that without firing on
        # someone who actually moved away.
        #
        # Continuation policy (only after dwell has started):
        #   - zone None    (cleared by darkness)         → tolerated
        #   - zone "bed"                                 → tolerated
        #   - zone anything else (e.g. "desk")           → reset
        #   - posture None (cleared by darkness)         → tolerated
        #   - posture "reclined"                         → tolerated
        #   - posture "upright"                          → reset
        zone = camera.zone
        posture = camera.posture
        dwell_started = self._watching_sleep_dwell_since is not None

        if dwell_started:
            # Reset only on active contradiction, not on staleness.
            if (
                (zone is not None and zone != "bed")
                or (posture is not None and posture != "reclined")
            ):
                self._watching_sleep_dwell_since = None
                return
        else:
            # Strict lock required to start the dwell.
            if zone != "bed" or posture != "reclined":
                return

        # Stamp the "user is likely still asleep" marker on any tick that
        # observes a confident bed+reclined (not on dark-room continuation
        # ticks where zone/posture are None — those tolerate staleness but
        # don't constitute a fresh observation). Consumed by
        # `_is_likely_still_asleep` to gate the morning brightness ramp
        # and watching mode's late_night→day transition.
        if zone == "bed" and posture == "reclined":
            self._last_bed_reclined_during_watching_at = now

        # All gates pass — accumulate dwell.
        if self._watching_sleep_dwell_since is None:
            self._watching_sleep_dwell_since = now
            return
        elapsed = (now - self._watching_sleep_dwell_since).total_seconds()
        if elapsed < WATCHING_SLEEP_GUARD_DWELL_SECONDS:
            return

        # Dwell met — commit refractory stamp BEFORE the await on
        # set_manual_override, same reasoning as the zone+posture rule:
        # if the override raises, the stamp prevents re-fire on every tick.
        self._watching_sleep_guard_last_fired_at = now
        self._watching_sleep_dwell_since = None
        await self._persist_override_state()

        factors = {
            "zone": zone,
            "posture": posture,
            "ambient_lux": getattr(camera, "ema_lux", None),
            "current_mode": self._current_mode,
            "effective_mode": effective_mode,
            "dwell_seconds": int(elapsed),
            "dwell_required": WATCHING_SLEEP_GUARD_DWELL_SECONDS,
            "hour": now.hour,
        }
        # Source attribution (Commit 3 of multi-camera fusion). For this
        # rule both will resolve to "latitude" today (zone=bed and
        # posture=reclined are Latitude-only); tagging makes that explicit
        # in ml_decisions and future-proofs the row if a bedroom-facing
        # source ever joins the fusion.
        self._attach_presence_attribution(factors, zone=zone, posture=posture)

        logger.info(
            "Watching-sleep guard firing: bed+reclined held %.0fmin "
            "in late_night while watching → sleeping",
            elapsed / 60,
        )
        await self.set_manual_override(
            "sleeping", source="watching_sleep_guard",
        )

        ml_logger = getattr(self, "_ml_logger", None)
        if ml_logger:
            await ml_logger.log_decision(
                predicted_mode="sleeping",
                confidence=1.0,
                decision_source="watching_sleep_guard",
                factors=factors,
                applied=True,
            )

    async def _check_external_off(self) -> bool:
        """
        Check if all lights were turned off externally (e.g., Alexa geofence).

        If detected, suppress automation to avoid fighting with Alexa.
        Returns True if we should skip this cycle.
        """
        if not self._hue or not self._hue.connected:
            return False

        lights = await self._hue.get_all_lights()
        all_off = all(not light.get("on", False) for light in lights)

        if all_off and not self._external_off_detected:
            self._external_off_detected = True
            logger.info("All lights off (external) — suppressing auto-control")
            return True

        return self._external_off_detected

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Decision pipeline snapshot
    # ------------------------------------------------------------------

    def _build_pipeline_state(self) -> dict[str, Any]:
        """Snapshot all active inputs, priority resolution, and final output."""
        now = datetime.now(tz=TZ)
        mode = self.current_mode
        period = self._get_time_period()

        # --- Inputs ---
        manual_input = {
            "active": self._manual_override,
            "mode": self._override_mode,
            "set_at": (
                self._override_time.isoformat()
                if self._override_time else None
            ),
        }

        activity_priority = MODE_PRIORITY.get(self._current_mode, 0)
        activity_input = {
            "active": self._current_mode not in ("idle",)
            or self._mode_source == "process",
            "mode": self._current_mode,
            "source": self._mode_source,
            "priority": activity_priority,
            "last_change": (
                self._last_activity_change.isoformat()
                if self._last_activity_change else None
            ),
        }

        ambient_input = {
            "active": self._current_mode == "social"
            and self._mode_source == "ambient",
            "mode": "social" if (
                self._current_mode == "social"
                and self._mode_source == "ambient"
            ) else None,
        }

        # Screen sync state from the service reference
        sync = self._screen_sync
        screen_active = (
            mode in SCREEN_SYNC_MODES
            and sync is not None
            and sync.last_color_at is not None
        )
        screen_input = {
            "active": screen_active,
            "target_light": sync._target_light if sync else "2",
            "last_color_at": (
                sync.last_color_at.isoformat()
                if sync and sync.last_color_at else None
            ),
            "source": sync.last_source if sync else None,
        }

        time_input = {
            "period": period,
            "schedule_type": "weekday" if now.weekday() < 5 else "weekend",
            "applies": mode in ("idle",)
            and not self._manual_override,
        }

        weather_condition = self._get_current_weather_condition()
        weather_effect = self._get_weather_effect()
        weather_input = {
            "condition": weather_condition,
            "effect_override": weather_effect if (
                weather_effect and not EFFECT_AUTO_MAP.get(mode, {}).get(period)
            ) else None,
            "applies": mode not in WEATHER_SKIP_MODES,
        }

        brightness_mult = self._mode_brightness.get(mode, 1.0)
        brightness_input = {
            "multiplier": brightness_mult,
            "applies": brightness_mult != 1.0,
        }

        override_scene = self._scene_overrides.get(mode, {}).get(period)
        scene_input = {
            "active": override_scene is not None,
            "scene_id": override_scene,
            "source": self._scene_override_sources.get(
                mode, {},
            ).get(period),
        }

        inputs = {
            "manual_override": manual_input,
            "activity": activity_input,
            "ambient": ambient_input,
            "screen_sync": screen_input,
            "time_of_day": time_input,
            "weather": weather_input,
            "brightness": brightness_input,
            "scene_override": scene_input,
        }

        # --- Resolution ---
        if self._manual_override:
            winning = "manual_override"
            reason = (
                f"Manual override to {self._override_mode}"
                f" (set {self._format_ago(self._override_time)})"
            )
        elif self._current_mode not in ("idle",):
            winning = "activity"
            reason = (
                f"{self._current_mode.title()} detected via "
                f"{self._mode_source} (priority {activity_priority})"
            )
        else:
            winning = "time_of_day"
            reason = f"No activity — using {period} time rules"

        resolution = {
            "winning_input": winning,
            "reason": reason,
            "effective_mode": mode,
            "effective_source": self.mode_source,
        }

        # --- Output ---
        output = {
            "mode": mode,
            "time_period": period,
            "effect": self._active_effect_name,
            "brightness_multiplier": brightness_mult,
            "lights": dict(self._last_applied_per_light),
        }

        # Add fusion state
        fusion_data = getattr(self, "_last_fusion_result", None)

        return {
            "timestamp": now.isoformat(),
            "inputs": inputs,
            "resolution": resolution,
            "output": output,
            "fusion": fusion_data,
        }

    @staticmethod
    def _format_ago(dt: Optional[datetime]) -> str:
        """Format a datetime as a human-readable 'X ago' string."""
        if not dt:
            return "unknown"
        delta = datetime.now(tz=TZ) - dt
        minutes = int(delta.total_seconds() / 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        return f"{hours}h {minutes % 60}m ago"

    @property
    def pipeline_history(self) -> list[dict]:
        """Pipeline snapshot ring for the /api/automation/pipeline view."""
        return self._pipeline.history

    async def _broadcast_pipeline(self) -> None:
        """Broadcast pipeline state to all WebSocket clients (throttled)."""
        await self._pipeline.broadcast()

    async def _broadcast_mode(self) -> None:
        """Broadcast the current mode to all WebSocket clients."""
        await self._ws_manager.broadcast("mode_update", {
            "mode": self.current_mode,
            "source": self.mode_source,
            "manual_override": self._manual_override,
            "time_period": self._get_time_period(),
        })
        await self._broadcast_pipeline()
