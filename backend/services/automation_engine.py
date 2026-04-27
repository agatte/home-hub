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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.config import settings

logger = logging.getLogger("home_hub.automation")

# Indianapolis timezone (Indiana doesn't follow standard Eastern DST rules)
TZ = ZoneInfo("America/Indiana/Indianapolis")

# Modes during which screen sync colors should be applied. The receiver
# endpoint at POST /api/automation/screen-color drops colors silently when
# the current mode isn't in this set.
SCREEN_SYNC_MODES = frozenset(("gaming", "watching"))

# Effect lifecycle (Hue v2 dynamic effects + weather-effect mapping +
# WEATHER_SKIP_MODES) lives in effect_manager.py. Re-exported below at
# module scope for back-compat with callers that import them from this
# module.

# Zone+posture → relax rule — first mode-changing sensor actuation. Auto-
# applies the "relax" manual override when the camera sees bed+reclined for
# a sustained window. Ships in shadow mode (settings.ZONE_POSTURE_RULE_APPLY
# defaults False) so the firing pattern can be observed via ml_decisions
# before flipping to live actuation. Full spec in docs/PROJECT_SPEC.md.
#
# Design notes:
# - Dwell (5 min) filters brief lean-backs and phone-checks.
# - Projector-from-bed carves itself out: sitting up against the headboard
#   keeps posture=upright, so the (bed, reclined) gate never trips.
# - Re-fire suppression reuses `_override_timeout_hours` so shadow and live
#   cadence match: once the rule logs/fires, it won't re-fire for 4h.
# - Eligible modes exclude everything except idle/away/working — we never
#   stomp explicit modes like gaming / watching / social / cooking /
#   sleeping / relax.
# - Time gate: evening always; weekend afternoons (≥13:00) also eligible.
ZONE_POSTURE_RULE_DWELL_SECONDS = 120
ZONE_POSTURE_RULE_WEEKEND_AFTERNOON_HOUR = 13
ZONE_POSTURE_RULE_ELIGIBLE_MODES = frozenset(("idle", "away", "working"))


# ---------------------------------------------------------------------------
# Configurable schedule dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DaySchedule:
    """Time-based lighting schedule for one day type (weekday or weekend)."""

    wake_hour: int = 5
    wake_brightness: int = 40
    ramp_start_hour: int = 6
    ramp_duration_minutes: int = 60
    evening_start_hour: int = 18
    winddown_start_hour: int = 21
    # Late-night period (relax-only override). From this hour until wake_hour
    # the relax palette switches to "Moss & Ember" — deeper, mossier, cave/den.
    # Modes that don't define a late_night state fall back to their night state.
    late_night_start_hour: int = 23


@dataclass
class ScheduleConfig:
    """Combined weekday + weekend schedule configuration."""

    weekday: DaySchedule = field(default_factory=DaySchedule)
    weekend: DaySchedule = field(default_factory=lambda: DaySchedule(
        wake_hour=8,
        ramp_start_hour=8,
        ramp_duration_minutes=120,
    ))


# Lighting tunables + the per-light state lookup table live in
# light_state_calculator.py. Re-exported below at module scope for
# back-compat with callers that imported them from this module.
from backend.services.light_state_calculator import (  # noqa: E402
    ACTIVITY_LIGHT_STATES,
    BED_RECLINED_L1_NIGHT_DEFAULT,
    BED_RECLINED_L1_RATIO,
    BED_RECLINED_L2_WATCHING_BRI,
    DEFAULT_MODE_BRIGHTNESS,
    EFFECT_AUTO_MAP,
    LUX_CURVE,
    LUX_MODES,
    LUX_MULT_EPSILON,
    LUX_STALE_SECONDS,
    MODE_TRANSITION_TIME,
    WINDDOWN_RAMP_MINUTES,
    ZONE_POSTURE_FRESHNESS_SECONDS,
    adjust_single_light as _adjust_single_light_pure,
    apply_brightness_multiplier as _calc_apply_brightness_multiplier,
    apply_lux_multiplier as _calc_apply_lux_multiplier,
    apply_weather_adjust as _calc_apply_weather_adjust,
    apply_zone_overlay as _calc_apply_zone_overlay,
    classify_weather as _classify_weather_pure,
    get_time_period as _calc_get_time_period,
    get_time_period_static as _get_time_period_static,
    lerp_light_state as _lerp_light_state,
    lux_to_multiplier,
    morning_ramp as _morning_ramp,
    resolve_activity_state as _resolve_activity_state,
)
from backend.services.effect_manager import (  # noqa: E402
    EffectManager,
    WEATHER_EFFECT_MAP,
    WEATHER_SKIP_MODES,
)


# Light ID → room mapping for readability
LIGHT_IDS = {
    "living_room": "1",
    "bedroom": "2",
    "kitchen_front": "3",
    "kitchen_back": "4",
}

# Mode priority — higher index wins when multiple sources report.
# Enforced universally by the priority guard in report_activity().
MODE_PRIORITY = {
    "sleeping": 0,
    "away": 0,
    "idle": 1,
    "working": 2,
    "watching": 3,
    "cooking": 3,
    "social": 4,
    "gaming": 5,
}

# Source-staleness cutoff for the priority guard. A current-mode source that
# hasn't reported in this many seconds is considered dead, and a lower-priority
# report from a different source may take over. Prevents an abandoned
# high-priority signal (e.g. stale social) from permanently locking out fresh
# lower-priority reports. 300s matches the confidence-fusion stale window.
SOURCE_STALE_SECONDS = 300


# ---------------------------------------------------------------------------
# Time-based rules — weekday vs weekend
# ---------------------------------------------------------------------------

WEEKDAY_TIME_RULES = [
    # (start_hour, end_hour, light_state_or_ramp)
    (0, 5, {"on": False}),                                          # Overnight — off
    (5, 6, {"on": True, "bri": 40, "hue": 6000, "sat": 200}),     # Early sniping — very dim warm
    (6, 7, ("morning_ramp", 6, 60)),                                # Getting ready (60 min ramp)
    (7, 18, {"on": False}),                                         # At work — off
    (18, 21, {"on": True, "bri": 180, "hue": 8000, "sat": 160}),  # Warm evening
    (21, 24, {"on": True, "bri": 60, "hue": 5500, "sat": 220}),   # Dim wind-down
]

WEEKEND_TIME_RULES = [
    (0, 8, {"on": False}),                                          # Sleeping in — off
    (8, 10, ("morning_ramp", 8, 120)),                              # Gentle weekend ramp (120 min)
    (10, 18, {"on": True, "bri": 220, "hue": 20000, "sat": 80}),  # Daytime neutral bright
    (18, 21, {"on": True, "bri": 180, "hue": 8000, "sat": 160}),  # Warm evening
    (21, 24, {"on": True, "bri": 60, "hue": 5500, "sat": 220}),   # Dim wind-down
]


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
        self._effect_manager = effect_manager or EffectManager(
            hue_v2=hue_v2, weather_service=weather_service,
        )

        # Weather condition tracking for music suggestions
        self._last_weather_condition: Optional[str] = None

        # Current state
        self._current_mode: str = "idle"
        self._mode_source: str = "time"
        self._manual_override: bool = False
        self._override_mode: Optional[str] = None
        self._override_time: Optional[datetime] = None
        self._last_activity: Optional[str] = None
        self._last_activity_change: Optional[datetime] = None
        # Per-source liveness for the priority guard (source → last report time).
        self._last_mode_source_report_at: dict[str, datetime] = {}

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
        # Last applied lux multiplier — if the new multiplier is within
        # LUX_MULT_EPSILON of this, we keep using the old value so the final
        # state dict is identical and the per-light dedupe at _apply_state
        # naturally skips the bridge write.
        self._last_lux_multiplier: float = 1.0

        # Screen sync — passed via constructor; reconciliation skips lights
        # that screen sync owns so we don't fight it on watching/gaming.
        self._screen_sync = screen_sync

        # Decision pipeline — real-time snapshot of all inputs → output
        self._pipeline_history: list[dict] = []
        self._last_pipeline_broadcast: Optional[datetime] = None

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
        return self._override_mode if self._manual_override else self._current_mode

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
        self._last_applied_per_light = {}  # Force re-apply
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
        self._last_applied_per_light = {}  # Force re-apply
        logger.info(f"Mode brightness updated: {brightness}")

    def _get_time_period(self) -> str:
        """Resolve the current time period via the calculator (shim)."""
        return _calc_get_time_period(self._schedule_config, datetime.now(tz=TZ))

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

        Away detection is handled by the PC activity detector, not the
        schedule — so time-based rules always provide sensible lighting
        for when the user is home (ramp → daytime → evening → wind-down).
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
        """
        ema, baseline = self._read_fresh_camera_lux()
        new_state, new_mult = _calc_apply_lux_multiplier(
            state, mode, ema, self._last_lux_multiplier, baseline,
        )
        self._last_lux_multiplier = new_mult
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
        """True iff the camera is enabled with a fresh ``zone == 'desk'`` reading.

        Used by autonomous mode-setters (late-night rescue, behavioral
        predictor, fusion override, winddown routine) to defer to active
        desk presence. If the camera sees Anthony at the desk, the system
        should not push him into ``relax`` against his apparent activity.
        """
        camera = self._camera_service
        if camera is None or not getattr(camera, "enabled", False):
            return False
        zone = self._fresh_camera_attr(camera, "zone", "zone_committed_at")
        return zone == "desk"

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
        """
        self._bed_reclined_l1_night = max(1, min(100, int(value)))

    def register_on_mode_change(self, callback) -> None:
        """
        Register a callback to be invoked when the active mode changes.

        Args:
            callback: Async callable accepting a single mode string argument.
        """
        self._on_mode_change_callbacks.append(callback)

    async def _fire_mode_change_callbacks(self, mode: str) -> None:
        """Invoke all registered mode-change callbacks with timeout protection."""
        for callback in self._on_mode_change_callbacks:
            try:
                await asyncio.wait_for(callback(mode), timeout=8.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "Mode change callback %s timed out after 8s for mode '%s'",
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
            mode: Detected mode (gaming, watching, working, social, idle, away).
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

        # Record this source's last-seen time regardless of whether the report
        # caused a mode change. Source freshness tracks liveness, not edges.
        self._last_mode_source_report_at[source] = now

        old_mode = self._current_mode

        # Accept the new detected mode (tracks what the PC is actually doing)
        self._current_mode = mode
        self._mode_source = source
        self._last_activity = mode
        self._last_activity_change = now

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
        if mode not in ("idle", "away"):
            self._external_off_detected = False

        # Apply the appropriate light state. force_resend=True because this
        # branch only runs when the resolved mode actually changed — bridge
        # state may have drifted (effects, external writes, prior overrides)
        # and the cache should be invalidated.
        await self._apply_mode(mode, force_resend=True)

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
                ``api:<remote_ip>``; internal triggers (winddown,
                late_night_rescue, fusion, zone_posture_rule, etc.) pass
                their own short label so journalctl shows who flipped the
                override and from where.
        """
        # Capture the effective mode (override if active, else detected) so that
        # event logging and callback gating see the real "previous" mode, not
        # the stale private _current_mode which only reflects PC agent state.
        old_mode = self.current_mode
        was_overridden = self._manual_override
        prior_override = self._override_mode
        self._manual_override = True
        self._override_mode = mode
        self._override_time = datetime.now(tz=TZ)
        self._last_activity_change = self._override_time

        self._clear_per_light_overrides()
        logger.info(
            "Manual override set: %s (source=%s, prior=%s, was_overridden=%s)",
            mode, source, prior_override, was_overridden,
        )
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
                source="manual",
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
        old_effective = self._override_mode
        was_overridden = self._manual_override
        self._manual_override = False
        self._override_mode = None
        self._override_time = None

        self._clear_per_light_overrides()
        logger.info(
            "Manual override cleared — returning to auto "
            "(source=%s, prior_override=%s, was_overridden=%s)",
            source, old_effective, was_overridden,
        )

        if old_effective == "sleeping":
            # User is (probably) still asleep or just waking — they'll pick a
            # new mode on the dashboard. Leave lights off.
            await self._broadcast_mode()
            return

        # Re-apply current detected mode or time-based. force_resend=True
        # because we've just released the override and per-light overrides;
        # the cache may not reflect what's actually on the bridge.
        if self._current_mode in ("idle", "away"):
            await self._apply_time_based()
        else:
            await self._apply_mode(self._current_mode, force_resend=True)

        await self._broadcast_mode()
        # Only fire callbacks if the effective mode actually changed
        if old_effective != self._current_mode:
            await self._fire_mode_change_callbacks(self._current_mode)

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
    ) -> None:
        """Apply temporary per-light brightness for transit-navigation lighting.

        Writes the given per-light states directly to the bridge and protects
        those lights from mode-driven automation until ``clear_transit_override``
        is called or the deadline elapses. Used by ``TransitLightingService``
        when the camera loses Anthony while his phone is still on Wi-Fi — the
        apartment briefly brightens along his likely walking path without
        changing the current mode.

        Args:
            states: light_id → state dict (``{"on": True, "bri": ..., "ct": ...}``)
            duration_seconds: max protection window before auto-expiry (default 10 min)
            transition_time: deciseconds for the Hue transition (20 = 2s)
        """
        if not self._hue or not self._hue.connected:
            return
        deadline = datetime.now(tz=TZ) + timedelta(seconds=duration_seconds)
        tasks = []
        for light_id, state in states.items():
            cmd = {**state, "transitiontime": transition_time}
            tasks.append(self._hue.set_light(light_id, cmd))
            self._transit_light_overrides[light_id] = deadline
            # Seed dedup so a concurrent reconcile cycle doesn't re-send the
            # previous mode state for these lights before the skip filter runs.
            self._last_applied_per_light[light_id] = {k: v for k, v in state.items() if k != "transitiontime"}
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(
            "Transit override applied to lights %s (expires %s)",
            list(states.keys()),
            deadline.strftime("%H:%M:%S"),
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
            self._last_applied_per_light.pop(lid, None)
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
            self._last_applied_per_light = {}

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
            self._last_applied_per_light = {}
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

        if mode in ACTIVITY_LIGHT_STATES:
            mode_states = ACTIVITY_LIGHT_STATES[mode]
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
                    evening_state = _resolve_activity_state(mode, "evening")
                    night_state = _resolve_activity_state(mode, "night")
                    state = _lerp_light_state(evening_state, night_state, progress)
                else:
                    state = _resolve_activity_state(mode, period)
            else:
                state = _resolve_activity_state(mode, period)

            # Apply learned lighting preferences as overlay (ML Phase 1).
            # Learned values replace hardcoded defaults per-light, per-property.
            lighting_learner = getattr(self, "_lighting_learner", None)
            if lighting_learner:
                overlay = lighting_learner.get_overlay(mode, period)
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
                self._last_applied_per_light = {}
                await self._apply_state(
                    {"on": True, "bri": 1, "hue": 5000, "sat": 254},
                    transitiontime=200,  # 20s
                )
                await asyncio.sleep(22)
                self._last_applied_per_light = {}
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
                self._last_applied_per_light = {}
                await self._apply_state(state)
                logger.info(f"Sleep fade step {i}/{steps}: bri={new_bri}")

            await asyncio.sleep(step_interval)
            self._last_applied_per_light = {}
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
        ) and any(k in ("1", "2", "3", "4") for k in state.keys())

        if is_per_light:
            await self._apply_per_light(state, transitiontime)
        else:
            await self._apply_uniform(state, transitiontime)

    async def _apply_uniform(
        self, state: dict[str, Any], transitiontime: int | None = None,
    ) -> None:
        """Apply the same state to all lights (backward-compatible path)."""
        # Prune expired transit overrides before consulting them.
        self._prune_expired_transit_overrides()

        # If any lights have manual or transit overrides, fall through to the
        # per-light path so the filter can skip the protected lights.
        if self._manual_light_overrides or self._transit_light_overrides:
            per_light = {lid: state for lid in ("1", "2", "3", "4")}
            await self._apply_per_light(per_light, transitiontime)
            return

        # Convert to per-light for dedup tracking
        per_light = {lid: state for lid in ("1", "2", "3", "4")}
        if per_light == self._last_applied_per_light:
            return

        prev_snapshot = {lid: (self._last_applied_per_light.get(lid) or {}).copy() for lid in ("1", "2", "3", "4")}
        self._last_applied_per_light = {lid: state.copy() for lid in ("1", "2", "3", "4")}
        cmd = {**state}
        if transitiontime is not None:
            cmd["transitiontime"] = transitiontime
        await self._hue.set_all_lights(cmd)
        logger.info(f"Applied uniform state: bri={state.get('bri')}, hue={state.get('hue')}")
        if self._event_logger:
            for lid in ("1", "2", "3", "4"):
                prev = prev_snapshot.get(lid, {})
                await self._event_logger.log_light_adjustment(
                    light_id=lid,
                    bri_before=prev.get("bri"), bri_after=state.get("bri"),
                    hue_before=prev.get("hue"), hue_after=state.get("hue"),
                    sat_before=prev.get("sat"), sat_after=state.get("sat"),
                    ct_before=prev.get("ct"), ct_after=state.get("ct"),
                    mode_at_time=self._current_mode,
                    trigger="automation",
                )

    async def _apply_per_light(
        self, states: dict[str, dict], transitiontime: int | None = None,
    ) -> None:
        """Apply individual states to each light (parallel when possible)."""
        # Drop any transit overrides whose deadline has passed before we check.
        self._prune_expired_transit_overrides()

        # Filter out lights with active manual or transit overrides.
        # Both dicts freeze their lights against mode-driven automation.
        protected = set(self._manual_light_overrides) | set(self._transit_light_overrides)
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
                        mode_at_time=self._current_mode,
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
        # randomly unequal. Social has its own sub-style cycling; sleeping/idle/
        # away are handled by other paths.
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
        base = _resolve_activity_state(mode, self._get_time_period())
        if not base:
            return

        drifted: dict[str, dict] = {}
        for lid in ("1", "2", "3", "4"):
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
        if mode not in WEATHER_SKIP_MODES:
            drifted = self._weather_adjust(drifted)
        self._last_applied_per_light = {}  # Force apply
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
                    minutes_since_start = (hour - ramp_start_hour) * 60 + minute
                    state = _morning_ramp(minutes_since_start, ramp_duration)
                else:
                    state = rule
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

        while True:
            try:
                if self._heartbeat is not None:
                    self._heartbeat.tick("automation")
                if not self._enabled:
                    await asyncio.sleep(60)
                    continue

                now = datetime.now(tz=TZ)

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
                # Complements winddown (which expires at 4h) and handles the
                # 02:00+ edge when someone's still at the desk. Guarded so real
                # gaming/watching/social/sleeping are respected, music playback
                # counts as intentional activity, and a fresh camera 'at desk'
                # reading means the user is actively present and shouldn't be
                # pushed into relax.
                if (
                    not self._manual_override
                    and not self.is_at_desk_fresh()
                    and self._get_time_period() == "late_night"
                    and self._current_mode in ("working", "idle")
                    and not await self._sonos_is_playing()
                ):
                    logger.info(
                        "Late-night rescue: switching to relax from %s",
                        self._current_mode,
                    )
                    await self.set_manual_override("relax", source="late_night_rescue")

                # If no activity override and no manual override, apply time-based
                if (
                    not self._manual_override
                    and self._current_mode in ("idle", "away")
                ):
                    await self._apply_time_based()
                elif (
                    not self._manual_override
                    and self._current_mode not in ("idle", "away", "social")
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
                    prediction = await predictor.predict(
                        current_mode=self._current_mode,
                    )
                if (
                    prediction
                    and not self._manual_override
                    and self._current_mode in ("idle", "away")
                ):
                    if not prediction.get("shadow"):
                        confidence = prediction["confidence"]
                        if confidence >= 0.95:
                            # Auto-apply at high confidence — unless camera
                            # sees Anthony at the desk, in which case defer
                            # to active presence and log the veto for audit.
                            if self.is_at_desk_fresh():
                                logger.debug(
                                    "Predictor suppressed (camera at desk): "
                                    "%s @ %.2f",
                                    prediction["predicted_mode"], confidence,
                                )
                                if ml_logger:
                                    factors = dict(prediction.get("factors") or {})
                                    factors["vetoed_by"] = "camera_at_desk"
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
                            # Suggest via WebSocket toast
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
                # fresh; check_rules() internally only nudges the user when
                # current_mode is idle/away.
                rule_engine = getattr(self, "_rule_engine", None)
                if rule_engine and not self._manual_override:
                    await rule_engine.check_rules(self._current_mode)

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
                            and self._current_mode not in ("idle", "away")
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
                            and self._current_mode in ("idle", "away")
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

        # Gate 1: any active manual override (user or rule) takes precedence.
        if self._manual_override:
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

        # Gate 3: the core condition — committed zone + posture.
        zone = camera.zone
        posture = camera.posture
        if zone != "bed" or posture != "reclined":
            self._zone_posture_reclined_since = None
            return

        # Gate 4: eligible current mode. Explicit activity modes (gaming,
        # watching, social, cooking, sleeping) and relax itself are excluded.
        if self._current_mode not in ZONE_POSTURE_RULE_ELIGIBLE_MODES:
            self._zone_posture_reclined_since = None
            return

        # Gate 5: time-of-day — evening always; weekends also allow afternoon.
        is_weekend = now.weekday() >= 5
        schedule = (
            self._schedule_config.weekend if is_weekend
            else self._schedule_config.weekday
        )
        afternoon_ok = (
            is_weekend and now.hour >= ZONE_POSTURE_RULE_WEEKEND_AFTERNOON_HOUR
        )
        evening_ok = now.hour >= schedule.evening_start_hour
        if not (afternoon_ok or evening_ok):
            self._zone_posture_reclined_since = None
            return

        # All gates pass — start / continue the dwell timer.
        if self._zone_posture_reclined_since is None:
            self._zone_posture_reclined_since = now
            return

        elapsed = (now - self._zone_posture_reclined_since).total_seconds()
        if elapsed < ZONE_POSTURE_RULE_DWELL_SECONDS:
            return

        # Dwell met — fire (live) or shadow-log.
        should_apply = bool(settings.ZONE_POSTURE_RULE_APPLY)
        trigger_reason = "evening" if evening_ok else "weekend_afternoon"
        factors = {
            "zone": zone,
            "posture": posture,
            "current_mode": self._current_mode,
            "dwell_seconds": int(elapsed),
            "is_weekend": is_weekend,
            "hour": now.hour,
            "trigger": trigger_reason,
        }

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

        # Record fire time; reset dwell so next eligible window needs fresh
        # accumulation (not just surviving override expiry instantly).
        self._zone_posture_last_fired_at = now
        self._zone_posture_reclined_since = None

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
            "active": self._current_mode not in ("idle", "away")
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
            "applies": mode in ("idle", "away")
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
        elif self._current_mode not in ("idle", "away"):
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

    async def _broadcast_pipeline(self) -> None:
        """Broadcast pipeline state to all WebSocket clients (throttled)."""
        now = datetime.now(tz=TZ)
        if (
            self._last_pipeline_broadcast
            and (now - self._last_pipeline_broadcast).total_seconds() < 1.0
        ):
            return
        self._last_pipeline_broadcast = now

        state = self._build_pipeline_state()
        self._pipeline_history.append(state)
        if len(self._pipeline_history) > 30:
            self._pipeline_history.pop(0)

        await self._ws_manager.broadcast("pipeline_state", state)

    async def _broadcast_mode(self) -> None:
        """Broadcast the current mode to all WebSocket clients."""
        await self._ws_manager.broadcast("mode_update", {
            "mode": self.current_mode,
            "source": self.mode_source,
            "manual_override": self._manual_override,
        })
        await self._broadcast_pipeline()
