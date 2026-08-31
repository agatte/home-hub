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
from dataclasses import dataclass
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
    RECENT_DESK_ATTENDANCE_SECONDS as RECENT_DESK_ATTENDANCE_SECONDS,
    MODE_PRIORITY as MODE_PRIORITY,
    PHYSICAL_CONTEXT_DESK_ABSENCE_SECONDS as PHYSICAL_CONTEXT_DESK_ABSENCE_SECONDS,
    PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS as PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS,
    PHYSICAL_CONTEXT_PRESENCE_LOSS_SECONDS as PHYSICAL_CONTEXT_PRESENCE_LOSS_SECONDS,
    PHYSICAL_CONTEXT_PROCESS_DEVICE_LIMIT as PHYSICAL_CONTEXT_PROCESS_DEVICE_LIMIT,
    PHYSICAL_CONTEXT_PROCESS_VETO_SECONDS as PHYSICAL_CONTEXT_PROCESS_VETO_SECONDS,
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
from backend.services.engine_state import EngineState
from backend.services.light_applicator import LightApplicator, LightApplyResult
from backend.services.lighting_transition_boundary import LightingTransitionBoundary
from backend.services.light_override_manager import LightOverrideManager
from backend.services.living_room_atmosphere import (
    ATMOSPHERE_TRANSITION_TIME,
    LIVING_ROOM_ATMOSPHERE_LIGHT_IDS,
    AtmospherePlan,
    LivingRoomAtmosphereCurator,
    bound_living_room_atmosphere_brightness,
    merge_living_room_atmosphere,
    preserve_atmosphere_effect_scope,
)
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
    LEGACY_TIME_BASED_LIGHT_IDS,
    MODE_TRANSITION_TIME,
    GamingContext,
    GamingResolution,
    RELAX_DRIFT_LIGHT_IDS,
    WINDDOWN_RAMP_MINUTES,
    ZONE_POSTURE_FRESHNESS_SECONDS,
    adjust_single_light as _adjust_single_light_pure,
    apply_brightness_multiplier as _calc_apply_brightness_multiplier,
    apply_functional_weather_brightness as _calc_apply_functional_weather_brightness,
    apply_gaming_day_surround_brightness as _calc_apply_gaming_day_surround_brightness,
    apply_lux_multiplier as _calc_apply_lux_multiplier,
    apply_weather_adjust as _calc_apply_weather_adjust,
    apply_zone_overlay as _calc_apply_zone_overlay,
    classify_weather as _classify_weather_pure,
    get_mode_state_table as _get_mode_state_table,
    get_time_period as _calc_get_time_period,
    interpolate_gaming_state,
    lerp_light_state as _lerp_light_state,
    lux_to_multiplier,
    morning_ramp as _morning_ramp,
    resolve_activity_state as _resolve_activity_state,
    resolve_gaming_lighting,
)
from backend.services.effect_manager import (  # noqa: E402
    EffectManager,
    WEATHER_SKIP_MODES,
)


# Gaming changes are semantic compositions, not a single short mode snap.
# Values are Hue deciseconds. Scheduled evolution stays slower than
# entry/profile changes; the existing 30-minute evening ramp supplies the
# small intermediate targets.
GAMING_TRANSITION_TIME: dict[str, int | None] = {
    "activity_entry": 20,
    "profile_acquire": 20,
    "game_switch": 25,
    "profile_release": 20,
    "scheduled_evolution": 100,
    "context_adjustment": 15,
    "scene_release": 20,
    "steady": None,
}

# A color-space handoff must leave useful room light established.  L1 plus the
# paired kitchen pendants are the functional anchor; L2/L5/L6 can change while
# that group remains visible.  The kitchen is deliberately never split.
_GAMING_HANDOFF_GROUPS: tuple[tuple[str, ...], ...] = (
    ("2", "5", "6"),
    ("1", "3", "4"),
)


@dataclass(frozen=True)
class _GamingPlanSnapshot:
    """Detached stable Gaming resolution retained for comparison/diagnostics."""

    requested_game: Optional[str]
    selected_profile: Optional[str]
    schedule_type: Optional[str]
    period: Optional[str]
    selected_variant: Optional[tuple[Optional[str], str]]
    fallback_reason: Optional[str]
    legacy_daytime_exception: bool
    state: dict[str, dict[str, Any]]

    @classmethod
    def from_resolution(cls, resolution: GamingResolution) -> "_GamingPlanSnapshot":
        return cls(
            requested_game=resolution.context.game_slug,
            selected_profile=resolution.selected_profile.game_slug,
            schedule_type=resolution.context.schedule_type,
            period=resolution.context.period,
            selected_variant=tuple(resolution.selected_variant),
            fallback_reason=resolution.fallback_reason,
            legacy_daytime_exception=resolution.legacy_daytime_exception,
            state={light_id: light.copy() for light_id, light in resolution.state.items()},
        )

    def diagnostics(self, transition_reason: Optional[str]) -> dict[str, Any]:
        return {
            "requested_game": self.requested_game,
            "selected_profile": self.selected_profile,
            "schedule_type": self.schedule_type,
            "period": self.period,
            "selected_variant": (
                {
                    "schedule_type": self.selected_variant[0],
                    "period": self.selected_variant[1],
                }
                if self.selected_variant is not None
                else None
            ),
            "fallback_reason": self.fallback_reason,
            "legacy_daytime_exception": self.legacy_daytime_exception,
            "transition_reason": transition_reason,
        }


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



def _factor_value(factors: Optional[list[dict]], key: str) -> object:
    """Return a factor value by key, tolerating older/partial factor rows."""
    if not factors:
        return None
    for factor in factors:
        if isinstance(factor, dict) and factor.get("key") == key:
            return factor.get("value")
    return None


def _string_factor(factors: Optional[list[dict]], key: str) -> Optional[str]:
    value = _factor_value(factors, key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _number_factor(factors: Optional[list[dict]], key: str) -> Optional[float]:
    value = _factor_value(factors, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _activity_device(factors: Optional[list[dict]]) -> Optional[str]:
    """Best-effort device role for a process report, e.g. desktop/latitude."""
    value = _factor_value(factors, "device")
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _activity_source_key(source: str, factors: Optional[list[dict]]) -> str:
    """Device-qualified source key for freshness/ownership bookkeeping."""
    device = _activity_device(factors)
    if source == "process" and device:
        return f"{source}:{device}"
    return source


@dataclass(frozen=True)
class ProcessObservation:
    """Latest raw process-classifier observation for one device."""

    observed_mode: str
    candidate_mode: Optional[str]
    candidate_reason: Optional[str]
    idle_seconds: Optional[float]
    pending_mode: Optional[str]
    pending_dwell_age: Optional[float]
    gaming_qualification: Optional[str]
    source: str
    device: str
    received_at: datetime

    @property
    def committed_mode(self) -> str:
        """Compatibility alias for physical-context consumers."""
        return self.observed_mode

    def as_context(self, now: datetime) -> dict[str, Any]:
        return {
            "observed_mode": self.observed_mode,
            "candidate_mode": self.candidate_mode,
            "candidate_reason": self.candidate_reason,
            "idle_seconds": self.idle_seconds,
            "pending_mode": self.pending_mode,
            "pending_dwell_age": self.pending_dwell_age,
            "gaming_qualification": self.gaming_qualification,
            "source": self.source,
            "device": self.device,
            "received_at": self.received_at.isoformat(),
            "age_seconds": (now - self.received_at).total_seconds(),
        }


@dataclass(frozen=True)
class ProcessSemanticEvidence:
    """Accepted process semantic evidence for one device."""

    committed_mode: str
    candidate_mode: Optional[str]
    candidate_reason: Optional[str]
    idle_seconds: Optional[float]
    pending_mode: Optional[str]
    pending_dwell_age: Optional[float]
    gaming_qualification: Optional[str]
    source: str
    device: str
    received_at: datetime

    def as_context(self, now: datetime) -> dict[str, Any]:
        return {
            "committed_mode": self.committed_mode,
            "candidate_mode": self.candidate_mode,
            "candidate_reason": self.candidate_reason,
            "idle_seconds": self.idle_seconds,
            "pending_mode": self.pending_mode,
            "pending_dwell_age": self.pending_dwell_age,
            "gaming_qualification": self.gaming_qualification,
            "source": self.source,
            "device": self.device,
            "received_at": self.received_at.isoformat(),
            "age_seconds": (now - self.received_at).total_seconds(),
        }


@dataclass(frozen=True)
class PhysicalContextProcessArbitration:
    """One source-qualified process vote for couch authority."""

    state: str
    reason: str
    evidence: Optional[ProcessObservation | ProcessSemanticEvidence] = None

    def as_context(self, now: datetime) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": self.state,
            "reason": self.reason,
        }
        if self.evidence is not None:
            result.update(self.evidence.as_context(now))
            if isinstance(self.evidence, ProcessObservation):
                # Arbitration remains backward-compatible for diagnostics while
                # the raw observation layer names its detector value honestly.
                result["committed_mode"] = self.evidence.observed_mode
        return result


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
        if effect_manager is None:
            transition_boundary = LightingTransitionBoundary(hue)
            self._effect_manager = EffectManager(
                hue_v2=hue_v2,
                weather_service=weather_service,
                transition_boundary=transition_boundary,
            )
        else:
            self._effect_manager = effect_manager
        self._transition_boundary = self._effect_manager.transition_boundary

        # Weather condition tracking for music suggestions
        self._last_weather_condition: Optional[str] = None

        # Current state
        self._current_mode: str = "idle"
        # Active game slug (from the PC-agent's `game` factor) when a game with
        # a dedicated lighting profile is running in gaming mode; None otherwise.
        # Drives GAME_LIGHT_PROFILES (e.g. Rust "Rusted Ember"). Kept in lockstep
        # with _current_mode — set/cleared alongside it in report_activity.
        self._current_game: Optional[str] = None
        # Gaming resolver state is deliberately detached from the mutable
        # per-light working state. It is both the semantic comparison baseline
        # and the compact diagnostics surface for the active Gaming session.
        self._current_gaming_resolution: Optional[_GamingPlanSnapshot] = None
        self._last_gaming_resolution: Optional[_GamingPlanSnapshot] = None
        self._last_gaming_target: Optional[dict[str, dict[str, Any]]] = None
        # A failed CT↔HSB masking write must retain its trusted old-space
        # baseline even when a force resend deliberately clears normal dedup.
        self._gaming_handoff_retry_baseline: dict[str, dict[str, Any]] = {}
        self._last_gaming_transition_reason: Optional[str] = None
        self._gaming_plan_changed: bool = False
        self._gaming_scene_override: Optional[dict[str, Any]] = None
        # Blocks direct Gaming writers during explicit-scene authority transfer.
        self._gaming_scene_transition_pending: bool = False
        self._mode_source: str = "time"
        self._mode_source_key: str = "time"
        self._manual_override: bool = False
        self._override_mode: Optional[str] = None
        self._override_source: Optional[str] = None
        self._override_time: Optional[datetime] = None
        self._override_expiry_deferred: bool = False
        self._last_activity: Optional[str] = None
        self._last_activity_change: Optional[datetime] = None
        # Per-source liveness for the priority guard (source → last report time).
        self._last_mode_source_report_at: dict[str, datetime] = {}

        # Last time the PC agent reported mode=working. Independent of camera
        # signal — used by late-night rescue as a parallel veto so a transient
        # camera blip doesn't strand the user in relax while they're actively
        # at the keyboard. See RECENT_PROCESS_WORKING_SECONDS.
        self._last_process_working_at: Optional[datetime] = None
        # Raw observations remain per-device for physical-context consumers.
        self._last_process_observation_by_device: dict[
            str, ProcessObservation
        ] = {}
        # Accepted semantics are intentionally distinct from raw observations.
        # Only a single derived voter from this layer enters fusion.
        self._last_process_semantic_by_device: dict[
            str, ProcessSemanticEvidence
        ] = {}

        # Central physical-context relax release state.
        self._physical_context_last_qualifying_at: Optional[datetime] = None
        self._physical_context_presence_lost_at: Optional[datetime] = None
        self._physical_context_last_decision: Optional[str] = None

        # Sleeping clears retain the normal autonomous cooldown for every
        # source except physical_context_relax after a new post-resume commit.
        self._user_clear_allows_physical_context_relax: bool = False

        # Timestamp of the most recent transition INTO `idle`. Cleared on any
        # exit from idle. Used by the ambient_relax setter to require a
        # continuous idle window (IDLE_AMBIENT_RELAX_DWELL_SECONDS) before
        # pushing to relax. Set/cleared in report_activity below.
        self._idle_entered_at: Optional[datetime] = None

        # Shared per-light state: dedup cache + manual/transit override
        # stamps. Grouped on EngineState (GH#87 step 4a) so the step-4/5
        # extractions can share one owner object. The original attribute
        # names (_last_applied_per_light, _manual_light_overrides,
        # _transit_light_overrides) remain available as property facades
        # below — every existing call site, test rebind, and the
        # notifier's getattr reach-through work unchanged.
        #
        # _transit_light_overrides semantics: set by TransitLightingService
        # when Anthony steps out of the bedroom while kitchen/living-room
        # are dim (DeskExitKitchenService shares the dict). Cleared by the
        # service when the camera sees him again, or auto-expired at the
        # deadline. Reconciliation skips these lights the same way
        # _manual_light_overrides does.
        self._state = EngineState()
        self._external_light_owners: list[Any] = []
        self._suspended_external_owner_ids: set[int] = set()

        # Per-light override verbs (manual stamps, dedup discipline,
        # transit/desk-exit/corridor lifecycle) — GH#87 step 4. Getters
        # defer to call time: hue/event_logger can be (re)wired after
        # construction, current_mode must be the override-aware property,
        # and _apply_mode is the revert path for transit clears.
        self._overrides = LightOverrideManager(
            state=self._state,
            hue_getter=lambda: self._hue,
            event_logger_getter=lambda: self._event_logger,
            current_mode_getter=lambda: self.current_mode,
            # Late-bound through self so a rebound _apply_mode (tests spy on
            # it; future wrappers may decorate it) is honored at call time —
            # a bound method captured here would go stale.
            reapply_mode=lambda mode: self._apply_mode(mode),
            suppressed_getter=lambda: self._external_off_detected,
            transition_boundary=self._transition_boundary,
        )

        # Bridge-write layer (away-gate, dedup compare/record, protected-light
        # skip filter, uniform/per-light fan-out + event logging) — GH#87
        # step 5. Operates on the SAME EngineState dicts as the override
        # manager (critic #4: direct O(1) dict access on the 0.5s hot path),
        # and consults the override manager for transit-prune. Getters defer
        # to call time so hue/event_logger/screen_sync can be (re)wired after
        # construction and current_mode stays the override-aware property.
        # _apply_mode stays on the engine as the policy coordinator and calls
        # into here via apply_state; the engine keeps thin _apply_* delegates
        # below so existing callers + test spies are honored.
        self._applicator = LightApplicator(
            state=self._state,
            overrides=self._overrides,
            hue_getter=lambda: self._hue,
            event_logger_getter=lambda: self._event_logger,
            # Actuation/audit boundary uses the user-facing projection so
            # occupied-awake fallback writes are recorded as General, not the
            # detector's internal Idle evidence.
            current_mode_getter=lambda: self.effective_mode,
            screen_sync_getter=lambda: self._screen_sync,
            external_owners_getter=self._active_external_light_owners,
            suppressed_getter=lambda: self._external_off_detected,
            # Cross-dispatch routes back through the engine's _apply_* delegates
            # so spies that patch engine._apply_per_light / _apply_uniform are
            # honored from inside the apply chain (step-4 reapply_mode pattern).
            dispatch_per_light=lambda s, t=None: self._apply_per_light(s, t),
            dispatch_uniform=lambda s, t=None: self._apply_uniform(s, t),
            transition_boundary=self._transition_boundary,
        )

        # Track if lights were turned off externally (Alexa geofence)
        self._external_off_detected: bool = False
        # Hard hold on the suppression above — armed ONLY by a geofence
        # LEAVE (AwayManager). While held, residual PC process reports
        # (the foreground process lingers up to ~10 min after walking
        # out, until the Win32 idle threshold trips) can NOT clear the
        # suppression — only signal_presence (camera sees a person /
        # geofence arrive) releases it. The soft path (_check_external_off
        # detecting the Hue app's all-off) never sets this, preserving
        # its original "any non-idle activity resumes" semantics.
        self._away_hold: bool = False
        # Compatibility latch for the decided Home + General model. False at
        # boot so stale/initial idle remains conservative overnight. Explicit
        # Sleeping → Auto confirms a human wake and sets this until a real
        # lifecycle transition (Sleeping/Away) clears it. While set, detector
        # idle renders an awake General baseline instead of the legacy overnight
        # off rule, and weak process ``sleeping`` cannot reclaim house authority.
        self._home_awake_confirmed: bool = False

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
        self._living_room_decision_gate = None
        self._living_room_atmosphere_curator: Optional[
            LivingRoomAtmosphereCurator
        ] = None

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
    def house_state(self) -> str:
        """Project the legacy mode engine onto the decided house-state model.

        Away is owned by the hard away hold, not by detector ``idle``/``away``
        vocabulary. Sleeping remains represented by the effective legacy mode
        until the broader house-state migration lands. Winding Down is not
        inferred from the clock; it becomes a real state only when GH#138 does.
        """
        if self._away_hold:
            return "away"
        if self.current_mode == "sleeping":
            return "sleeping"
        return "home"

    @property
    def activity(self) -> Optional[str]:
        """Return the decided user-facing activity projected from legacy mode.

        ``idle`` is detector/internal evidence. While Home, it projects to the
        General activity baseline. Away and Sleeping intentionally expose no
        awake activity.
        """
        if self.house_state != "home":
            return None
        mode = self.current_mode
        if mode in {"idle", "away"}:
            return "general"
        if mode == "sleeping":
            return None
        return mode

    @property
    def effective_mode(self) -> str:
        """Return the user-facing effective lifecycle/activity label.

        ``idle`` is detector evidence, not an occupied-awake activity.  Keep
        the raw value in ``_current_mode`` / activity-context diagnostics, but
        project Home + idle to General at API, pipeline, and actuation-audit
        boundaries.
        """
        if self.house_state == "away":
            return "away"
        if self.house_state == "sleeping":
            return "sleeping"
        return self.activity or self.current_mode

    @property
    def effective_source(self) -> str:
        """Return the owner of the projected effective mode.

        Home + General is the time-of-day fallback rendered from internal idle
        evidence; the detector source remains available separately.
        """
        if (
            self.house_state == "home"
            and not self._manual_override
            and self._current_mode == "idle"
        ):
            return "time_of_day"
        return self.mode_source

    @property
    def last_weather_class(self) -> Optional[str]:
        """Most recent weather class applied to the lux-multiplier curve.

        Exposed on /health so the stateful Check K verifier can tell a
        within-epsilon steady state apart from a never-fired transition.
        """
        return self._last_weather_class

    @property
    def last_lux_multiplier(self) -> float:
        """Most recent lux brightness multiplier the engine settled on."""
        return self._last_lux_multiplier

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

    def set_living_room_decision_gate(self, gate: Any) -> None:
        """Attach the read-only shadow gate after bootstrap composition."""
        self._living_room_decision_gate = gate

    def set_living_room_atmosphere_curator(
        self, curator: LivingRoomAtmosphereCurator,
    ) -> None:
        """Attach the downstream selector; the decision gate stays writer-free."""
        self._living_room_atmosphere_curator = curator

    def get_living_room_atmosphere_status(self) -> Optional[dict[str, Any]]:
        curator = self._living_room_atmosphere_curator
        return curator.current_status() if curator is not None else None

    async def get_living_room_atmosphere_history(
        self, limit: int,
    ) -> list[dict[str, Any]]:
        curator = self._living_room_atmosphere_curator
        return await curator.history(limit) if curator is not None else []

    def get_activity_context(self) -> dict[str, Any]:
        """Return held activity/effective-mode state without recomputation."""
        now = datetime.now(tz=TZ)
        report_at = self._last_mode_source_report_at.get(
            self._mode_source_key,
            self._last_mode_source_report_at.get(self._mode_source),
        )
        report_age = (
            (now - report_at).total_seconds()
            if report_at is not None else None
        )
        process_arbitration = self._physical_context_process_arbitration(now)
        return {
            "house_state": self.house_state,
            "activity": self.activity,
            "current_activity": self._current_mode,
            "current_activity_source": self._mode_source,
            "current_activity_source_key": self._mode_source_key,
            "current_activity_reported_at": (
                report_at.isoformat() if report_at is not None else None
            ),
            "current_activity_age_seconds": report_age,
            "current_activity_fresh": (
                report_age is not None and report_age <= SOURCE_STALE_SECONDS
            ),
            "effective_mode": self.effective_mode,
            "effective_source": self.effective_source,
            "last_activity_change": (
                self._last_activity_change.isoformat()
                if self._last_activity_change is not None else None
            ),
            "process_evidence_by_device": {
                device: evidence.as_context(now)
                for device, evidence in sorted(
                    self._last_process_semantic_by_device.items()
                )
            },
            "process_observations_by_device": {
                device: observation.as_context(now)
                for device, observation in sorted(
                    self._last_process_observation_by_device.items()
                )
            },
            "physical_context_process_arbitration": (
                process_arbitration.as_context(now)
            ),
            "gaming": self.get_gaming_diagnostics(),
        }

    def get_light_ownership_context(self) -> dict[str, Any]:
        """Return existing ownership state without changing protection."""
        sync = self._screen_sync
        now = datetime.now(timezone.utc)
        sync_age = (
            (now - sync.last_color_at).total_seconds()
            if sync is not None and sync.last_color_at is not None
            else None
        )
        source_stamps = (
            getattr(sync, "last_color_at_by_source", {})
            if sync is not None else {}
        )
        screen_sources = {
            source: {
                "last_color_at": stamp.isoformat(),
                "age_seconds": (now - stamp).total_seconds(),
            }
            for source, stamp in source_stamps.items()
        }
        external_owners = []
        for owner in self._external_light_owners:
            targets = getattr(owner, "owned_light_targets", lambda: {})()
            external_owners.append({
                "name": getattr(owner, "owner_name", type(owner).__name__),
                "light_ids": sorted(targets),
            })
        return {
            "manual": {
                "light_ids": sorted(self._manual_light_overrides),
                "set_at_by_light": {
                    light_id: stamp.isoformat()
                    for light_id, stamp in self._manual_light_overrides.items()
                },
            },
            "screen_sync": {
                "source": sync.last_source if sync is not None else None,
                "last_color_at": (
                    sync.last_color_at.isoformat()
                    if sync is not None and sync.last_color_at is not None
                    else None
                ),
                "age_seconds": sync_age,
                "available_light_ids": (
                    sorted(sync.target_lights) if sync is not None else []
                ),
                "sources": screen_sources,
            },
            "protected_light_ids": sorted(self._protected_light_ids()),
            "transit_light_ids": sorted(self._transit_light_overrides),
            "external_owners": external_owners,
        }

    def get_pipeline_status(self) -> dict[str, Any]:
        """Return held pipeline liveness for the shadow capability snapshot."""
        return {
            "enabled": self._enabled,
            "history_size": len(self._pipeline.history),
        }

    async def evaluate_living_room_context(
        self, *, trigger: str = "normal",
    ) -> Optional[dict[str, Any]]:
        """Run the attached shadow gate without affecting engine state."""
        gate = self._living_room_decision_gate
        if gate is None:
            return None
        try:
            await gate.evaluate(trigger=trigger)
        except Exception:
            logger.error(
                "Living-room shadow evaluation escaped gate boundary",
                exc_info=True,
            )
        return gate.current_envelope()

    async def _plan_living_room_atmosphere(
        self,
        *,
        period: str,
        scene_override_active: bool,
    ) -> Optional[AtmospherePlan]:
        curator = self._living_room_atmosphere_curator
        if curator is None:
            return None
        try:
            envelope = await self.evaluate_living_room_context(
                trigger="atmosphere_plan",
            )
            provenance = (
                self._override_source
                if self._manual_override
                else self._mode_source
            )
            return curator.decide(
                envelope,
                period=period,
                provenance=provenance,
                session_started_at=(
                    self._override_time
                    if provenance == "physical_context_relax"
                    else None
                ),
                scene_override_active=scene_override_active,
            )
        except Exception:
            curator.reset_session("selector_failure")
            logger.error(
                "Living-room atmosphere selector failed; using ordinary Relax",
                exc_info=True,
            )
            return None

    # ── EngineState facades (GH#87 step 4a) ────────────────────────────
    # The dicts live on self._state so the step-4/5 extractions can share
    # one owner object. These keep the original attribute names working —
    # internal call sites, tests that rebind the dicts wholesale, and
    # notifier_service's getattr(engine, "_last_applied_per_light", ...)
    # reach-through are all unchanged. Property access is attribute-speed;
    # the hot-path dict operations themselves stay direct O(1) (critic #4).

    @property
    def _last_applied_per_light(self) -> dict[str, dict]:
        return self._state.last_applied_per_light

    @_last_applied_per_light.setter
    def _last_applied_per_light(self, value: dict[str, dict]) -> None:
        self._state.last_applied_per_light = value

    @property
    def _manual_light_overrides(self) -> dict[str, datetime]:
        return self._state.manual_light_overrides

    @_manual_light_overrides.setter
    def _manual_light_overrides(self, value: dict[str, datetime]) -> None:
        self._state.manual_light_overrides = value

    @property
    def _transit_light_overrides(self) -> dict[str, datetime]:
        return self._state.transit_light_overrides

    @_transit_light_overrides.setter
    def _transit_light_overrides(self, value: dict[str, datetime]) -> None:
        self._state.transit_light_overrides = value

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

    def _now(self) -> datetime:
        """Return local wall time for deterministic automation decisions."""
        return datetime.now(tz=TZ)

    def _get_time_period(self, now: Optional[datetime] = None) -> str:
        """Resolve the current time period via the calculator (shim)."""
        return _calc_get_time_period(self._schedule_config, now or self._now())

    def get_time_period(self) -> str:
        """Public accessor for the current time period.

        Surfaced for consumers that need to mirror the engine's day/evening/
        night/late_night logic without reaching into the private shim — the
        monitor_brightness pc_agent and the /api/automation/status route.
        """
        return self._get_time_period()

    @staticmethod
    def _gaming_schedule_type(now: datetime) -> str:
        return "weekday" if now.weekday() < 5 else "weekend"

    def get_gaming_diagnostics(self) -> dict[str, Any]:
        """Return a detached summary of the effective, accepted Gaming plan."""
        active = self.current_mode == "gaming"
        if active and self._gaming_scene_override is not None:
            return {"active": True, **self._gaming_scene_override.copy()}
        plan = self._current_gaming_resolution if active else None
        if plan is None:
            return {
                "active": active,
                "requested_game": None,
                "selected_profile": None,
                "schedule_type": None,
                "period": None,
                "selected_variant": None,
                "fallback_reason": None,
                "legacy_daytime_exception": False,
                "transition_reason": (
                    self._last_gaming_transition_reason if active else None
                ),
                "current_plan_differs_from_previous": False,
            }
        result = plan.diagnostics(self._last_gaming_transition_reason)
        result["active"] = True
        result["current_plan_differs_from_previous"] = self._gaming_plan_changed
        return result

    @staticmethod
    def _gaming_color_space(light: dict[str, Any]) -> str:
        if "ct" in light:
            return "ct"
        if "hue" in light and "sat" in light:
            return "hsb"
        return "none"

    def _classify_gaming_transition(
        self,
        next_plan: _GamingPlanSnapshot,
        target_state: dict[str, dict[str, Any]],
        *,
        scheduled_interpolation: bool,
        scene_released: bool = False,
    ) -> str:
        previous = self._current_gaming_resolution
        if scene_released:
            return "scene_release"
        if previous is None:
            return "activity_entry"
        if previous.selected_profile is None and next_plan.selected_profile is not None:
            return "profile_acquire"
        if previous.selected_profile is not None and next_plan.selected_profile is None:
            return "profile_release"
        if (
            previous.selected_profile is not None
            and next_plan.selected_profile is not None
            and previous.selected_profile != next_plan.selected_profile
        ):
            return "game_switch"
        if (
            previous.selected_variant != next_plan.selected_variant
            or previous.period != next_plan.period
        ):
            return "scheduled_evolution"
        if (
            previous.schedule_type != next_plan.schedule_type
            and previous.state != next_plan.state
        ):
            return "scheduled_evolution"
        if scheduled_interpolation and target_state != self._last_gaming_target:
            return "scheduled_evolution"
        if target_state != self._last_gaming_target:
            return "context_adjustment"
        return "steady"

    @staticmethod
    def _merge_light_apply_results(*results: LightApplyResult) -> LightApplyResult:
        """Combine a staged write outcome without losing retry information."""
        merged = LightApplyResult()
        for result in results:
            merged.successful.update(result.successful)
            merged.failed.update(result.failed)
            merged.skipped.update(result.skipped)
            merged.deduplicated.update(result.deduplicated)
        return merged

    def _gaming_crossing_light_ids(
        self,
        target_state: dict[str, dict[str, Any]],
        previous_states: dict[str, dict[str, Any]],
    ) -> set[str]:
        return {
            light_id
            for light_id, target in target_state.items()
            if (previous := previous_states.get(light_id)) is not None
            and self._gaming_color_space(previous) != "none"
            and self._gaming_color_space(target) != "none"
            and self._gaming_color_space(previous) != self._gaming_color_space(target)
        }

    @staticmethod
    def _gaming_mask_state(previous: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
        """Retain the old color space at a conservative masking brightness."""
        old_color = {
            key: value for key, value in previous.items()
            if key in {"ct", "hue", "sat"}
        }
        return {
            "on": True,
            "bri": max(
                1,
                min(int(previous.get("bri", 1)), int(target.get("bri", 1)), 20),
            ),
            **old_color,
        }

    async def _apply_gaming_color_space_handoff(
        self,
        target_state: dict[str, dict[str, Any]],
        transitiontime: int,
        previous_states: dict[str, dict[str, Any]],
    ) -> LightApplyResult:
        """Apply a role-staged CT↔HSB handoff under one shared boundary.

        The bedroom/accent group changes first while L1/L3/L4 remain useful;
        then the functional group changes while the first group is established.
        A failed masking write never receives its incompatible final recolor.
        """
        crossings = self._gaming_crossing_light_ids(target_state, previous_states)
        if not crossings:
            return await self._apply_state(target_state, transitiontime=transitiontime)

        async with self._transition_boundary.serialized():
            outcomes: list[LightApplyResult] = []
            non_crossing = {
                light_id: target
                for light_id, target in target_state.items()
                if light_id not in crossings
            }
            if non_crossing:
                outcomes.append(
                    await self._apply_state(non_crossing, transitiontime=transitiontime)
                )

            for group in _GAMING_HANDOFF_GROUPS:
                group_crossings = [light_id for light_id in group if light_id in crossings]
                if not group_crossings:
                    continue
                masking = {
                    light_id: self._gaming_mask_state(
                        previous_states[light_id], target_state[light_id],
                    )
                    for light_id in group_crossings
                }
                masked = await self._apply_state(masking, transitiontime=10)
                outcomes.append(masked)
                await self._transition_boundary.wait_for_settle(masked.successful)
                for light_id in masked.failed:
                    self._gaming_handoff_retry_baseline[light_id] = (
                        previous_states[light_id].copy()
                    )

                # A protected light is deliberately passed through the normal
                # final apply, where ownership skips it. A failed masking light
                # is excluded so it cannot jump directly across color spaces.
                final_group = {
                    light_id: target_state[light_id]
                    for light_id in group_crossings
                    if light_id not in masked.failed
                }
                if final_group:
                    final = await self._apply_state(
                        final_group, transitiontime=transitiontime,
                    )
                    outcomes.append(final)
                    await self._transition_boundary.wait_for_settle(final.successful)
                    for light_id in final.successful:
                        self._gaming_handoff_retry_baseline.pop(light_id, None)
            return self._merge_light_apply_results(*outcomes)

    async def _establish_gaming_handoff_effect_safety(
        self,
        target_state: dict[str, dict[str, Any]],
        previous_states: dict[str, dict[str, Any]],
        transitiontime: int,
        release_light_ids: set[str],
    ) -> LightApplyResult:
        """Establish role-staged static Gaming targets inside effect release."""
        if not self._transition_boundary.held_by_current_task:
            raise RuntimeError("Gaming effect safety requires the transition boundary")

        crossings = self._gaming_crossing_light_ids(target_state, previous_states)
        if not crossings:
            return await self.establish_effect_release(
                target_state, transitiontime, release_light_ids,
            )

        # All released lights need a safe static command at every effect stage.
        # Cross-space fixtures not yet due to move retain their observed old
        # color-space state; protected lights remain owned by the applicator.
        working = {
            light_id: target_state.get(light_id, previous_states.get(light_id, {})).copy()
            for light_id in release_light_ids
        }
        for light_id in crossings:
            if light_id in working:
                working[light_id] = previous_states[light_id].copy()

        outcomes: list[LightApplyResult] = []
        for group in _GAMING_HANDOFF_GROUPS:
            group_crossings = [light_id for light_id in group if light_id in crossings]
            if not group_crossings:
                continue
            for light_id in group_crossings:
                working[light_id] = self._gaming_mask_state(
                    previous_states[light_id], target_state[light_id],
                )
            masked = await self.establish_effect_release(
                working, 10, release_light_ids,
            )
            outcomes.append(masked)
            await self._transition_boundary.wait_for_settle(masked.successful)
            if masked.failed:
                for light_id in masked.failed & crossings:
                    self._gaming_handoff_retry_baseline[light_id] = (
                        previous_states[light_id].copy()
                    )
                return self._merge_light_apply_results(*outcomes)

            for light_id in group_crossings:
                working[light_id] = target_state[light_id].copy()
            final = await self.establish_effect_release(
                working, transitiontime, release_light_ids,
            )
            outcomes.append(final)
            await self._transition_boundary.wait_for_settle(final.successful)
            if final.failed:
                for light_id in final.failed & crossings:
                    self._gaming_handoff_retry_baseline[light_id] = (
                        working[light_id].copy()
                    )
                return self._merge_light_apply_results(*outcomes)
            for light_id in group_crossings:
                self._gaming_handoff_retry_baseline.pop(light_id, None)
        return self._merge_light_apply_results(*outcomes)

    async def _reconcile_gaming_effect_handoff(
        self,
        desired: Optional[str | dict[str, Any]],
        target_state: dict[str, dict[str, Any]],
        previous_states: dict[str, dict[str, Any]],
        transitiontime: int,
    ) -> bool:
        """Keep the Gaming handoff inside EffectManager's existing boundary."""
        async def establish_safety(release_light_ids: set[str]) -> LightApplyResult | bool:
            result = await self._establish_gaming_handoff_effect_safety(
                target_state,
                previous_states,
                transitiontime,
                release_light_ids,
            )
            return result if not result.failed else False

        async def staged_static_ready() -> bool:
            return True

        return await self._effect_manager.replace_with_action(
            staged_static_ready,
            establish_safety=establish_safety,
            desired=desired,
        )

    async def _read_scene_release_baseline(self) -> dict[str, dict[str, Any]]:
        """Read Hue once when native scene ownership returns to composition."""
        if self._hue is None or not self._hue.connected:
            return {}
        try:
            lights = await self._hue.get_all_lights()
        except Exception:
            logger.warning("Could not read Hue baseline for Gaming scene release", exc_info=True)
            return {}

        baseline: dict[str, dict[str, Any]] = {}
        for light in lights:
            light_id = light.get("light_id", light.get("id"))
            if light_id is None:
                continue
            state: dict[str, Any] = {
                "on": bool(light.get("on", True)),
                "bri": int(light.get("bri", 1)),
            }
            if light.get("colormode") == "ct" and light.get("ct") is not None:
                state["ct"] = int(light["ct"])
            elif light.get("hue") is not None and light.get("sat") is not None:
                state["hue"] = int(light["hue"])
                state["sat"] = int(light["sat"])
            baseline[str(light_id)] = state
        return baseline

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

        # Daytime neutral white — functional idle uses CT, never tinted HSB.
        if ramp_end < schedule.evening_start_hour:
            rules.append((
                ramp_end,
                schedule.evening_start_hour,
                {"on": True, "bri": 220, "ct": 250},
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
        # Prefer PresenceFusion when wired — it is the source-aware path.
        # Fall back to direct camera reading for boot-time / test paths
        # where the fusion layer is not built yet.
        presence = self._presence_fusion
        if presence is not None:
            return presence.is_at_desk_fresh(ZONE_POSTURE_FRESHNESS_SECONDS)
        zone, _ = self._current_zone_posture()
        return zone == "desk"


    def is_recently_at_desk(
        self, window_seconds: int = RECENT_DESK_ATTENDANCE_SECONDS,
    ) -> bool:
        """True iff the desk was confirmed recently enough to veto automation.

        PresenceFusion keeps a high-water mark that survives a non-confirming
        desktop frame, which is the important distinction from
        ``is_at_desk_fresh``. Use this for autonomous idle/relax pushes that
        should not fire while Anthony is still plausibly at the desk.
        """
        presence = self._presence_fusion
        if presence is not None:
            try:
                seconds_since = presence.seconds_since_at_desk()
                if seconds_since is not None:
                    return seconds_since <= window_seconds
                return presence.is_at_desk_fresh(window_seconds)
            except Exception:
                logger.debug(
                    "PresenceFusion recent-desk check failed", exc_info=True,
                )
        return self.is_at_desk_fresh()

    def _attendance_veto_reason(self) -> Optional[str]:
        """Reason an autonomous mode push should defer to active attendance."""
        if self.is_recently_at_desk():
            return "recent_desk_attendance"
        if self.is_recent_process_working():
            return "process_working_recent"
        return None

    def _has_fresh_mode_replacement(self, now: datetime) -> bool:
        """Whether a fresh semantic source can safely replace user intent."""
        if self._current_mode == "idle":
            return False
        last_report = self._last_mode_source_report_at.get(
            self._mode_source_key,
            self._last_mode_source_report_at.get(self._mode_source),
        )
        return bool(
            last_report
            and (now - last_report).total_seconds() < SOURCE_STALE_SECONDS
        )

    def _override_is_user_owned(self) -> bool:
        """Return whether the active override represents explicit user intent."""
        return bool(
            self._manual_override
            and self._override_source not in AUTONOMOUS_PUSH_SOURCES
        )

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

        Camera absent→present and the geofence arrive both route here —
        physical presence is the ONLY thing that releases a hard
        (geofence-armed) hold; residual process reports are not it.
        Idempotent: no-op when nothing is armed.

        Args:
            source: Caller identifier for telemetry ("camera",
                "geofence:<src>"; "audio" if/when the parked
                Latitude-mic path ships).
        """
        if not self._external_off_detected and not self._away_hold:
            return
        self._away_hold = False
        self._external_off_detected = False
        logger.info(
            "Presence signal from %s — clearing external-off suppression "
            "so automation can resume",
            source,
        )

    def arm_away_suppression(self, source: str) -> None:
        """Arm the external-off run_loop suppression with a HARD hold.

        Same flag `_check_external_off` sets when it detects an
        externally-darkened apartment — but armed proactively by the
        AwayManager on a geofence LEAVE (no 60s detection race), and
        with `_away_hold` set so residual PC process reports can't
        clear it (see report_activity). Released ONLY by
        `signal_presence` (geofence arrive, camera absent→present).

        Also invalidates the per-light dedup cache: the apartment is
        being forced dark, so the cache no longer reflects the bridge.
        Without this, a camera-walk-in release (phone left in the car,
        geofence missed) would dedup-skip the re-light and leave the
        user standing in a dark, unsuppressed apartment.

        Idempotent; upgrades a soft (Hue-app-detected) suppression to a
        hard one when both fire on the same departure.
        """
        already_armed = self._external_off_detected
        self._external_off_detected = True
        self._away_hold = True
        self._home_awake_confirmed = False
        self._invalidate_dedup_cache()
        self._invalidate_external_light_owners("away")
        if not already_armed:
            logger.info(
                "Away suppression armed by %s (hard hold) — run_loop will "
                "skip autonomous setters until presence returns",
                source,
            )
        else:
            logger.info(
                "Away suppression upgraded to hard hold by %s",
                source,
            )

    async def reapply_current_mode(self, *, force_resend: bool = True) -> None:
        """Re-apply the current effective mode's lighting on demand.

        Public surface for the AwayManager's welcome-home sequence (and
        any future caller that needs a deterministic re-light): after an
        away window the bridge is dark but the dedup cache still holds
        pre-departure values, so the default apply would dedup-skip.
        Uses the override-aware ``current_mode`` property — never the raw
        ``_current_mode`` field (see feedback_current_mode_field_footgun).
        """
        await self._apply_mode(self.current_mode, force_resend=force_resend)

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

    def is_recent_desktop_interaction(
        self,
        *,
        max_idle_seconds: float,
        max_report_age_seconds: float,
    ) -> bool:
        """Whether fresh desktop process evidence proves recent real input.

        This is deliberately narrower than the activity detector's Gaming hold:
        callers choose a short idle bound suitable for physical-presence
        arbitration. A stale/missing desktop agent, missing idle factor, clock
        skew, or an idle value at/above the bound all fail open so physical
        navigation can proceed.
        """
        evidence = self._last_process_observation_by_device.get("desktop")
        if evidence is None or evidence.idle_seconds is None:
            return False
        age = (datetime.now(tz=TZ) - evidence.received_at).total_seconds()
        return bool(
            -2.0 <= age <= max_report_age_seconds
            and 0.0 <= evidence.idle_seconds < max_idle_seconds
        )

    def _record_process_observation(
        self,
        mode: str,
        factors: Optional[list[dict]],
        now: datetime,
    ) -> ProcessObservation:
        """Store the latest raw process/classifier observation for one device."""
        device = _activity_device(factors) or "unknown"
        observation = ProcessObservation(
            observed_mode=mode,
            candidate_mode=_string_factor(factors, "candidate_mode"),
            candidate_reason=_string_factor(factors, "candidate_reason"),
            idle_seconds=_number_factor(factors, "idle"),
            pending_mode=_string_factor(factors, "pending_mode"),
            pending_dwell_age=_number_factor(factors, "pending_dwell_age"),
            gaming_qualification=_string_factor(
                factors, "gaming_qualification",
            ),
            source="process",
            device=device,
            received_at=now,
        )
        self._last_process_observation_by_device[device] = observation
        if (
            len(self._last_process_observation_by_device)
            > PHYSICAL_CONTEXT_PROCESS_DEVICE_LIMIT
        ):
            oldest_device = min(
                self._last_process_observation_by_device,
                key=lambda key: (
                    self._last_process_observation_by_device[key].received_at
                ),
            )
            self._last_process_observation_by_device.pop(oldest_device, None)
        return observation

    def _record_process_semantic(
        self,
        observation: ProcessObservation | str,
        factors: Optional[list[dict]] = None,
        now: Optional[datetime] = None,
    ) -> None:
        """Commit one already-arbitrated process observation as a semantic.

        The string/factors form is retained for existing physical-context
        fixtures and callers. Runtime reporting always passes a raw observation
        that was captured before arbitration.
        """
        if isinstance(observation, str):
            observation = self._record_process_observation(
                observation, factors, now or datetime.now(tz=TZ),
            )
        self._last_process_semantic_by_device[observation.device] = (
            ProcessSemanticEvidence(
                committed_mode=observation.observed_mode,
                candidate_mode=observation.candidate_mode,
                candidate_reason=observation.candidate_reason,
                idle_seconds=observation.idle_seconds,
                pending_mode=observation.pending_mode,
                pending_dwell_age=observation.pending_dwell_age,
                gaming_qualification=observation.gaming_qualification,
                source=observation.source,
                device=observation.device,
                received_at=observation.received_at,
            )
        )
        if (
            len(self._last_process_semantic_by_device)
            > PHYSICAL_CONTEXT_PROCESS_DEVICE_LIMIT
        ):
            oldest_device = min(
                self._last_process_semantic_by_device,
                key=lambda key: (
                    self._last_process_semantic_by_device[key].received_at
                ),
            )
            self._last_process_semantic_by_device.pop(oldest_device, None)

    def _derived_process_semantic(self) -> Optional[ProcessSemanticEvidence]:
        """Return the freshest accepted process voter for fusion.

        Fusion freshness is an eligibility condition, not a tiebreaker.  A
        stale higher-priority semantic must not suppress a fresh lower-priority
        semantic from another device; once eligible, the established mode
        priority and then recency choose the single non-double-counting voter.
        """
        now = datetime.now(tz=TZ)
        fresh_semantics = [
            evidence
            for evidence in self._last_process_semantic_by_device.values()
            if (now - evidence.received_at).total_seconds()
            <= SOURCE_STALE_SECONDS
        ]
        if not fresh_semantics:
            return None
        return max(
            fresh_semantics,
            key=lambda evidence: (
                MODE_PRIORITY.get(evidence.committed_mode, 0),
                evidence.received_at,
            ),
        )

    def _sync_process_fusion(self) -> tuple[Optional[str], bool]:
        """Replace fusion's process lane from accepted semantics only."""
        fusion = getattr(self, "_confidence_fusion", None)
        semantic = self._derived_process_semantic()
        if fusion is None:
            return (semantic.committed_mode if semantic else None, False)
        clear_signal = getattr(fusion, "clear_signal", None)
        if callable(clear_signal):
            clear_signal("process")
        if semantic is None:
            return None, False
        fusion.report_signal(
            "process",
            semantic.committed_mode,
            1.0,
            factors=[
                {"key": "device", "label": "Device", "value": semantic.device,
                 "display": semantic.device, "impact": 1.0},
                {"key": "semantic_mode", "label": "Accepted semantic",
                 "value": semantic.committed_mode,
                 "display": semantic.committed_mode, "impact": 1.0},
            ],
            timestamp=semantic.received_at,
        )
        return semantic.committed_mode, True

    async def _finalize_process_report(
        self,
        *,
        observation: ProcessObservation,
        disposition: str,
        reason: str,
        agent_factors: Optional[list[dict]],
    ) -> dict[str, Any]:
        """Log a truthful process observation and update the semantic voter."""
        included_in_fusion = False
        if disposition == "accepted":
            self._record_process_semantic(observation)
            semantic_mode, included_in_fusion = self._sync_process_fusion()
        elif disposition == "retracted":
            self._last_process_semantic_by_device.pop(observation.device, None)
            semantic_mode, included_in_fusion = self._sync_process_fusion()
        else:
            semantic = self._derived_process_semantic()
            semantic_mode = semantic.committed_mode if semantic else None

        result = {
            "reported_mode": observation.observed_mode,
            "observed_source": f"process:{observation.device}",
            "semantic_disposition": disposition,
            "reason": reason,
            "semantic_mode": semantic_mode,
            "authoritative_mode": self.current_mode,
            "included_in_fusion": included_in_fusion,
        }
        if self._ml_logger is not None:
            await self._ml_logger.log_decision(
                predicted_mode=observation.observed_mode,
                confidence=1.0,
                decision_source="process",
                factors={
                    "engine_priority": MODE_PRIORITY.get(
                        observation.observed_mode, 0,
                    ),
                    "agent_factors": agent_factors or [],
                    **result,
                },
                applied=False,
                broadcast=False,
            )
        return result

    def _physical_context_desk_absence_qualified(self, now: datetime) -> bool:
        """Whether fresh explicit desktop absence has held for 30 seconds."""
        reading = self._physical_context_source_reading("desktop")
        age = self._physical_context_reading_age(reading, now)
        if not (
            reading is not None
            and -2.0 <= age <= PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
            and reading.face_present is False
        ):
            return False
        presence = self._presence_fusion
        if presence is None:
            return False
        try:
            seconds_since = presence.seconds_since_at_desk()
        except Exception:
            logger.debug(
                "PresenceFusion desk-absence check failed", exc_info=True,
            )
            return False
        return bool(
            seconds_since is not None
            and seconds_since >= PHYSICAL_CONTEXT_DESK_ABSENCE_SECONDS
        )

    def _physical_context_strong_contradiction(self, now: datetime) -> bool:
        """Strong source-qualified proof that desktop intent was abandoned."""
        camera_ready, _ = self._physical_context_camera_ready()
        return bool(
            camera_ready
            and self._physical_context_couch_qualified(now)
            and self._physical_context_desk_absence_qualified(now)
        )

    def _physical_context_process_discount_supported(self, now: datetime) -> bool:
        """Current or lifecycle-debounced couch authority supports discounting."""
        if self._physical_context_strong_contradiction(now):
            return True
        active = bool(
            self._manual_override
            and self._override_source == "physical_context_relax"
        )
        last_qualified = self._physical_context_last_qualifying_at
        if not active or last_qualified is None:
            return False
        authority_age = (now - last_qualified).total_seconds()
        return bool(
            self._physical_context_desk_absence_qualified(now)
            and 0 <= authority_age <= (
                PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
                + PHYSICAL_CONTEXT_PRESENCE_LOSS_SECONDS
            )
        )

    def _physical_context_process_arbitration(
        self, now: datetime,
    ) -> PhysicalContextProcessArbitration:
        """Resolve fresh process intent against strong physical couch authority."""
        meaningful: list[tuple[float, ProcessObservation]] = []
        for evidence in self._last_process_observation_by_device.values():
            age = (now - evidence.received_at).total_seconds()
            if (
                evidence.committed_mode in {"gaming", "watching", "working"}
                and 0 <= age <= PHYSICAL_CONTEXT_PROCESS_VETO_SECONDS
            ):
                meaningful.append((age, evidence))
        if not meaningful:
            return PhysicalContextProcessArbitration(
                state="none",
                reason="no_fresh_process_intent",
            )

        discount_supported = self._physical_context_process_discount_supported(now)
        vetoes: list[tuple[float, ProcessObservation]] = []
        discounted: list[tuple[float, ProcessObservation]] = []
        for age, evidence in meaningful:
            if (
                evidence.device == "desktop"
                and evidence.committed_mode in {"gaming", "working"}
                and discount_supported
            ):
                discounted.append((age, evidence))
            else:
                vetoes.append((age, evidence))

        if vetoes:
            _, evidence = min(vetoes, key=lambda row: row[0])
            reason = (
                "desktop_process_intent_active"
                if evidence.device == "desktop"
                else "process_intent_active"
            )
            return PhysicalContextProcessArbitration(
                state="veto",
                reason=reason,
                evidence=evidence,
            )

        _, evidence = min(discounted, key=lambda row: row[0])
        return PhysicalContextProcessArbitration(
            state="discounted",
            reason="stale_desktop_process_discounted",
            evidence=evidence,
        )

    def _physical_context_source_reading(self, source: str) -> Any:
        presence = self._presence_fusion
        if presence is None:
            return None
        getter = getattr(presence, "get_source_reading", None)
        if getter is None:
            return None
        return getter(source)

    def _physical_context_camera_ready(self) -> tuple[bool, str]:
        camera = self._camera_service
        if camera is None or not getattr(camera, "enabled", False):
            return False, "latitude_disabled"
        if getattr(camera, "_paused", False):
            return False, "latitude_paused"
        if hasattr(camera, "healthy") and not camera.healthy:
            return False, "latitude_unhealthy"
        if (
            hasattr(camera, "presence_authority_ready")
            and not camera.presence_authority_ready
        ):
            return False, "latitude_presence_authority_unknown"
        if (
            not hasattr(camera, "healthy")
            and hasattr(camera, "_cap")
            and camera._cap is None
        ):
            return False, "latitude_unhealthy"
        if getattr(camera, "last_detection_at", None) is None:
            return False, "latitude_post_start_observation_missing"
        return True, "ready"

    @staticmethod
    def _physical_context_reading_age(reading: Any, now: datetime) -> float:
        if reading is None or getattr(reading, "captured_at", None) is None:
            return float("inf")
        return (now - reading.captured_at).total_seconds()

    def _physical_context_couch_qualified(self, now: datetime) -> bool:
        reading = self._physical_context_source_reading("latitude")
        age = self._physical_context_reading_age(reading, now)
        return bool(
            reading is not None
            and -2.0 <= age <= PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
            and reading.zone == "couch"
            and reading.face_present is True
        )

    def _physical_context_desktop_conflict(self, now: datetime) -> bool:
        reading = self._physical_context_source_reading("desktop")
        age = self._physical_context_reading_age(reading, now)
        return bool(
            reading is not None
            and -2.0 <= age <= PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
            and reading.face_present is True
        )

    def _physical_context_cooldown_blocked(self, now: datetime) -> bool:
        if self._user_cleared_override_at is None:
            return False
        elapsed = (now - self._user_cleared_override_at).total_seconds()
        return bool(
            elapsed < USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS
            and not self._user_clear_allows_physical_context_relax
        )

    def _log_physical_context_decision(
        self, decision: str, detail: str, trigger: str,
    ) -> None:
        if decision == self._physical_context_last_decision:
            return
        self._physical_context_last_decision = decision
        logger.info(
            "Physical-context relax %s: %s (trigger=%s)",
            decision,
            detail,
            trigger,
        )

    async def notify_presence_observation(self, reading: Any) -> None:
        """Evaluate source-qualified physical context after an observation edge."""
        source = getattr(reading, "source", "unknown")
        await self._evaluate_physical_context_relax(
            trigger=f"presence:{source}",
        )

    async def _evaluate_physical_context_relax(
        self,
        *,
        now: Optional[datetime] = None,
        trigger: str,
    ) -> None:
        """Own entry, preemption, and loss debounce for couch-driven relax."""
        now = now or datetime.now(tz=TZ)
        active = bool(
            self._manual_override
            and self._override_source == "physical_context_relax"
        )
        camera_ready, camera_reason = self._physical_context_camera_ready()
        couch_qualified = camera_ready and self._physical_context_couch_qualified(now)
        desktop_conflict = self._physical_context_desktop_conflict(now)
        process_arbitration = self._physical_context_process_arbitration(now)
        process_evidence = process_arbitration.evidence

        if couch_qualified:
            reading = self._physical_context_source_reading("latitude")
            self._physical_context_last_qualifying_at = reading.captured_at
            self._physical_context_presence_lost_at = None

        if active:
            if self.is_dnd_active():
                self._log_physical_context_decision(
                    "blocked_dnd", "active override held by existing DND semantics", trigger,
                )
                return
            if self._external_off_detected or self._away_hold:
                self._log_physical_context_decision(
                    "released_away", "away/external-off became active", trigger,
                )
                await self.clear_override(source="physical_context_relax")
                return
            # A real semantic process intent can preempt couch Relax immediately.
            # Keep this ahead of the physical-conflict hysteresis below so a
            # genuine desk return to Working/Gaming/Watching does not wait for
            # the couch-loss timer.
            if process_arbitration.state == "veto" and process_evidence is not None:
                age = (now - process_evidence.received_at).total_seconds()
                self._log_physical_context_decision(
                    "preempted_process",
                    f"{process_evidence.device} "
                    f"{process_evidence.committed_mode} age={age:.1f}s",
                    trigger,
                )
                await self.clear_override(source="physical_context_relax")
                return

            # PresenceFusion's desktop face signal is intentionally raw and can
            # flicker on a single frame.  When the Latitude still has fresh,
            # committed couch authority, contradictory desktop-only evidence is
            # not enough to tear down the incumbent Relax state.  Holding here
            # prevents Relax -> idle -> Relax repaint loops while preserving
            # immediate semantic-process preemption above.
            if couch_qualified:
                return

            if desktop_conflict:
                self._log_physical_context_decision(
                    "released_desktop_conflict",
                    "fresh desktop face restored desk authority after couch loss",
                    trigger,
                )
                await self.clear_override(source="physical_context_relax")
                return
            if not camera_ready:
                self._physical_context_presence_lost_at = None
                self._log_physical_context_decision(
                    "held_camera_unknown",
                    f"{camera_reason}; waiting for authoritative physical evidence",
                    trigger,
                )
                return
            lost_at = self._physical_context_presence_lost_at
            if lost_at is None:
                reading = self._physical_context_source_reading("latitude")
                reading_age = self._physical_context_reading_age(reading, now)
                if (
                    reading is not None
                    and -2.0
                    <= reading_age
                    <= PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
                ):
                    lost_at = reading.captured_at
                else:
                    lost_at = now
                self._physical_context_presence_lost_at = lost_at
            loss_age = (now - lost_at).total_seconds()
            if loss_age >= PHYSICAL_CONTEXT_PRESENCE_LOSS_SECONDS:
                self._log_physical_context_decision(
                    "released_presence_loss",
                    f"{camera_reason}; loss={loss_age:.1f}s",
                    trigger,
                )
                await self.clear_override(source="physical_context_relax")
            return

        if not self._enabled:
            return
        if self._manual_override:
            self._log_physical_context_decision(
                "blocked_manual", f"override={self._override_source}", trigger,
            )
            return
        if self._external_off_detected or self._away_hold:
            self._log_physical_context_decision(
                "blocked_away", "away/external-off active", trigger,
            )
            return
        if self.is_dnd_active():
            self._log_physical_context_decision("blocked_dnd", "DND active", trigger)
            return
        entry_mode_eligible = bool(
            self._current_mode == "idle"
            or (
                self._current_mode in {"gaming", "working"}
                and process_arbitration.state == "discounted"
            )
        )
        if not entry_mode_eligible or not camera_ready or not couch_qualified:
            return
        if desktop_conflict:
            self._log_physical_context_decision(
                "blocked_desktop_conflict", "simultaneous fresh couch and desk", trigger,
            )
            return
        if process_arbitration.state == "veto" and process_evidence is not None:
            age = (now - process_evidence.received_at).total_seconds()
            self._log_physical_context_decision(
                "blocked_process",
                f"{process_evidence.device} "
                f"{process_evidence.committed_mode} age={age:.1f}s",
                trigger,
            )
            return
        if self._physical_context_cooldown_blocked(now):
            self._log_physical_context_decision(
                "blocked_cooldown", "non-sleeping user clear cooldown", trigger,
            )
            return

        await self.set_manual_override("relax", source="physical_context_relax")
        if self._manual_override and self._override_source == "physical_context_relax":
            self._log_physical_context_decision(
                "entered", "fresh committed Latitude couch face", trigger,
            )

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
        if self.is_recently_at_desk():
            return False
        if self.is_recent_process_working():
            return False
        return True

    def _current_zone_posture(self) -> tuple[Optional[str], Optional[str]]:
        """Return the freshest fused zone/posture, falling back to camera state."""
        presence = self._presence_fusion
        if presence is not None:
            try:
                return presence.latest_zone(), presence.latest_posture()
            except Exception:
                pass
        camera = self._camera_service
        zone = self._fresh_camera_attr(camera, "zone", "zone_committed_at")
        posture = self._fresh_camera_attr(
            camera, "posture", "posture_committed_at"
        )
        return zone, posture


    def _apply_zone_overlay(
        self, state: dict[str, Any], mode: str, period: str,
    ) -> dict[str, Any]:
        """Zone/posture overlay (shim → calculator).

        Resolves fresh zone + posture off the camera service (with the
        freshness gate handled by ``_fresh_camera_attr``), then hands
        primitives to the pure calculator function.
        """
        zone, posture = self._current_zone_posture()
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
        # The observation edge already applied the physical-context entry.
        # Avoid a second force-resend of the same relax palette.
        if self._override_source == "physical_context_relax":
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
    ) -> dict[str, Any]:
        """
        Process an activity report from the PC agent, ambient monitor, or camera.

        Args:
            mode: Detected mode (gaming, watching, working, social, idle).
            source: Detection source ("process", "ambient", "audio_ml", or "camera").
            factors: Optional sub-factor list surfaced to the analytics
                constellation (foreground app / idle bucket / YAMNet classes /
                etc). Process factors remain attached to the raw observation;
                only accepted process semantics are eligible for fusion.
        """
        source_key = _activity_source_key(source, factors)
        report_now = datetime.now(tz=TZ)
        observation: Optional[ProcessObservation] = None
        if source == "process":
            observation = self._record_process_observation(
                mode, factors, report_now,
            )

        # Raw process diagnostics intentionally remain observable while
        # automation is disabled.  They abstain before physical arbitration,
        # accepted semantics, fusion, authority, or ActivityEvent handling.
        if not self._enabled:
            if observation is not None:
                return await self._finalize_process_report(
                    observation=observation,
                    disposition="abstaining",
                    reason="automation_disabled",
                    agent_factors=factors,
                )
            return {
                "reported_mode": mode,
                "semantic_disposition": "abstaining",
                "reason": "automation_disabled",
                "semantic_mode": None,
                "authoritative_mode": self.current_mode,
                "included_in_fusion": False,
            }

        if observation is not None:
            await self._evaluate_physical_context_relax(
                now=report_now, trigger="process_report",
            )

        # Non-process sources own their own lanes. Process takes the separate
        # accepted-semantic path below; raw device reports never vote directly.
        fusion = getattr(self, "_confidence_fusion", None)
        if fusion:
            if source == "ambient":
                fusion.report_signal("audio_ml", mode, 0.7, factors=factors)
            elif source != "process":
                fusion.report_signal(source, mode, 0.8, factors=factors)

        # Latitude's idle heartbeat is a media-intent retraction. It removes
        # that device's accepted semantic but is never global idle evidence.
        if source == "process" and observation is not None and (
            observation.device == "latitude" and mode == "idle"
        ):
            return await self._finalize_process_report(
                observation=observation,
                disposition="retracted",
                reason="latitude_media_intent_retracted",
                agent_factors=factors,
            )

        # DND blocks autonomous mode changes after fusion has logged its
        # signal — fusion weights still tune normally so the lane stays
        # warm for when DND clears. report_activity has no user-source
        # path (PC agent / ambient / camera only), so this exits early
        # without a source check.
        if self.is_dnd_active():
            logger.debug("DND active — ignoring %s report (mode=%s)", source, mode)
            if observation is not None:
                return await self._finalize_process_report(
                    observation=observation,
                    disposition="rejected",
                    reason="dnd_active",
                    agent_factors=factors,
                )
            return {
                "reported_mode": mode, "semantic_disposition": "rejected",
                "reason": "dnd_active", "semantic_mode": None,
                "authoritative_mode": self.current_mode,
                "included_in_fusion": False,
            }

        # Priority guard — a lower-priority mode can't displace a higher-priority
        # current mode unless the report comes from the source that owns it
        # (sources can always update themselves) or the owning source has gone
        # stale. Enforces MODE_PRIORITY universally so every signal is subject
        # to the same rule.
        now = report_now
        current_priority = MODE_PRIORITY.get(self._current_mode, 0)
        new_priority = MODE_PRIORITY.get(mode, 0)
        if new_priority < current_priority and source_key != self._mode_source_key:
            last_report = self._last_mode_source_report_at.get(
                self._mode_source_key,
                self._last_mode_source_report_at.get(self._mode_source),
            )
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
                    self._last_mode_source_report_at[source_key] = now
                    self._last_mode_source_report_at[source] = now
                    if observation is not None:
                        return await self._finalize_process_report(
                            observation=observation,
                            disposition="rejected",
                            reason="source_priority",
                            agent_factors=factors,
                        )
                    return {
                        "reported_mode": mode,
                        "semantic_disposition": "rejected",
                        "reason": "source_priority",
                        "semantic_mode": None,
                        "authoritative_mode": self.current_mode,
                        "included_in_fusion": False,
                    }

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
            self._last_mode_source_report_at[source_key] = now
            self._last_mode_source_report_at[source] = now
            if observation is not None:
                return await self._finalize_process_report(
                    observation=observation,
                    disposition="rejected",
                    reason="sleeping_floor",
                    agent_factors=factors,
                )
            return {
                "reported_mode": mode, "semantic_disposition": "rejected",
                "reason": "sleeping_floor", "semantic_mode": None,
                "authoritative_mode": self.current_mode,
                "included_in_fusion": False,
            }

        # Record this source's last-seen time regardless of whether the report
        # caused a mode change. Source freshness tracks liveness, not edges.
        self._last_mode_source_report_at[source_key] = now
        self._last_mode_source_report_at[source] = now

        # Explicit Sleeping → Auto establishes Home as human authority. A PC
        # sleep-watcher report is device lifecycle evidence, not proof that the
        # human went back to sleep, so it cannot reclaim Sleeping while that
        # awake-home latch is active. A later explicit/trusted Sleeping override
        # clears the latch in set_manual_override().
        if (
            self._home_awake_confirmed
            and source == "process"
            and mode == "sleeping"
        ):
            logger.debug(
                "Confirmed Home: ignored process sleeping report after "
                "explicit wake"
            )
            if observation is not None:
                return await self._finalize_process_report(
                    observation=observation,
                    disposition="rejected",
                    reason="home_awake_confirmed",
                    agent_factors=factors,
                )
            return {
                "reported_mode": mode, "semantic_disposition": "rejected",
                "reason": "home_awake_confirmed", "semantic_mode": None,
                "authoritative_mode": self.current_mode,
                "included_in_fusion": False,
            }

        # Fresh desk presence is stronger evidence than a passive idle detector
        # for active desk work. Windows input can sit idle while Anthony is
        # visibly at the desk reading or thinking. Watching already has process-
        # detector hysteresis, so a committed idle report must release it even
        # while desk presence remains fresh. Physical location alone is not
        # media intent. Gaming likewise releases when its process lane goes idle.
        if (
            mode == "idle"
            and self._current_mode == "working"
            and self.is_recently_at_desk()
        ):
            logger.info(
                "Desk-presence veto: ignored %s idle while %s is at desk",
                source,
                self._current_mode,
            )
            if observation is not None:
                return await self._finalize_process_report(
                    observation=observation,
                    disposition="rejected",
                    reason="recent_desk_presence",
                    agent_factors=factors,
                )
            return {
                "reported_mode": mode, "semantic_disposition": "rejected",
                "reason": "recent_desk_presence", "semantic_mode": None,
                "authoritative_mode": self.current_mode,
                "included_in_fusion": False,
            }

        # Stamp process-working liveness for the late-night rescue veto.
        # Updated on every confirming report, not just on mode edges, so a
        # steady stream of process-working heartbeats keeps the veto alive
        # even when the engine has demoted current_mode to idle.
        if source == "process" and mode == "working":
            self._last_process_working_at = now

        old_mode = self._current_mode

        # Accept the new detected mode (tracks what the PC is actually doing)
        self._current_mode = mode
        # Track the active game (drives GAME_LIGHT_PROFILES). Only meaningful in
        # gaming mode; any other mode clears it so a stale profile can't linger.
        # Set in lockstep with _current_mode so the next _apply_mode resolves the
        # right palette on the same report that first carries the `game` factor.
        self._current_game = _extract_game_factor(factors) if mode == "gaming" else None
        if mode != "gaming":
            self._current_gaming_resolution = None
            self._last_gaming_target = None
            self._gaming_handoff_retry_baseline.clear()
            self._gaming_scene_override = None
        self._mode_source = source
        self._mode_source_key = source_key
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
        process_arbitration = self._physical_context_process_arbitration(now)

        if (
            self._manual_override
            and self._override_source in AUTONOMOUS_PUSH_SOURCES
            and new_priority > override_priority
            and (
                self._override_source != "physical_context_relax"
                or (
                    source == "process"
                    and process_arbitration.state == "veto"
                )
            )
        ):
            if self._override_source == "physical_context_relax":
                process_evidence = process_arbitration.evidence
                self._log_physical_context_decision(
                    "preempted_process",
                    (
                        f"{process_evidence.device} "
                        f"{process_evidence.committed_mode} age=0.0s"
                        if process_evidence is not None
                        else f"{source_key} {mode} age=0.0s"
                    ),
                    "activity_report",
                )
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
            if observation is not None:
                return await self._finalize_process_report(
                    observation=observation,
                    disposition="accepted",
                    reason="manual_override_held",
                    agent_factors=factors,
                )
            return {
                "reported_mode": mode, "semantic_disposition": "accepted",
                "reason": "manual_override_held", "semantic_mode": mode,
                "authoritative_mode": self.current_mode,
                "included_in_fusion": False,
            }

        # Clear external off detection on any activity — UNLESS the
        # suppression is hard-held by a geofence LEAVE. The PC's
        # foreground process lingers up to ~10 min after walking out
        # (until the Win32 idle threshold), so post-departure `working`
        # heartbeats are residue, not presence. Only signal_presence
        # (camera sees a person / geofence arrive) releases a hard hold.
        if mode not in ("idle",) and not self._away_hold:
            self._external_off_detected = False

        # While suppressed (away hard-hold, or the soft Hue-app all-off
        # that an idle report doesn't clear): keep the mode bookkeeping
        # above + the event log + WS broadcast, but do NOT actuate
        # lights or fire mode-change callbacks — a working→idle
        # transition 10 min after a departure would otherwise re-light
        # an empty apartment via the evening time rules (force_resend
        # bypasses the dedup cache on transitions) and auto-play music
        # to nobody. Found live 2026-06-10 during D2/D6 testing.
        if self._external_off_detected:
            if old_mode != mode:
                logger.info(
                    "Mode %s → %s while away/external-off suppressed — "
                    "tracked, not actuated",
                    old_mode, mode,
                )
                if self._event_logger:
                    await self._event_logger.log_mode_change(
                        mode=mode,
                        previous_mode=old_mode,
                        source=source,
                    )
            await self._broadcast_mode()
            if observation is not None:
                return await self._finalize_process_report(
                    observation=observation,
                    disposition="accepted",
                    reason="external_off_suppressed",
                    agent_factors=factors,
                )
            return {
                "reported_mode": mode, "semantic_disposition": "accepted",
                "reason": "external_off_suppressed", "semantic_mode": mode,
                "authoritative_mode": self.current_mode,
                "included_in_fusion": False,
            }

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
        # Gaming plan changes are classified inside _apply_mode from the
        # previous/next resolved plans. A raw game-factor change does not by
        # itself invalidate the cache: two unknown games can share the exact
        # generic target, while real plan deltas naturally reach the applicator.
        await self._apply_mode(
            mode,
            force_resend=(old_mode != mode),
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
        if observation is not None:
            return await self._finalize_process_report(
                observation=observation,
                disposition="accepted",
                reason="accepted",
                agent_factors=factors,
            )
        return {
            "reported_mode": mode,
            "semantic_disposition": "accepted",
            "reason": "accepted",
            "semantic_mode": mode,
            "authoritative_mode": self.current_mode,
            "included_in_fusion": False,
        }

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

        # Away/external-off interplay. An explicit USER mode pick while the
        # apartment is suppressed is deliberate remote actuation ("light the
        # place for the dog-sitter" via Alexa/dashboard) — release the
        # suppression so the pick renders past the _apply_mode chokepoint.
        # Autonomous sources must NOT pierce it: they are exactly what
        # away-suppression silences (run_loop is gated; this guards direct
        # callers).
        if self._external_off_detected:
            if source in AUTONOMOUS_PUSH_SOURCES:
                logger.info(
                    "Away/external-off suppressed — blocking autonomous "
                    "override %s (source=%s)",
                    mode, source,
                )
                return
            await self.signal_presence(f"override:{source}")

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
            physical_context_exempt = bool(
                source == "physical_context_relax"
                and self._user_clear_allows_physical_context_relax
            )
            if elapsed < USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS and not physical_context_exempt:
                logger.info(
                    "Autonomous override blocked by user-clear cooldown: "
                    "mode=%s source=%s elapsed=%.0fs / %ds",
                    mode, source, elapsed,
                    USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS,
                )
                return

        # A committed Sleeping lifecycle transition ends any previously
        # confirmed awake-home session. Do this only after all override gates
        # above pass so a blocked autonomous sleep push cannot clear wake state.
        if mode == "sleeping":
            self._home_awake_confirmed = False

        # Capture the effective mode (override if active, else detected) so that
        # event logging and callback gating see the real "previous" mode, not
        # the stale private _current_mode which only reflects PC agent state.
        old_mode = self.current_mode
        was_overridden = self._manual_override
        prior_override = self._override_mode
        prior_override_source = self._override_source
        self._manual_override = True
        self._override_mode = mode
        self._override_source = source
        self._override_time = datetime.now(tz=TZ)
        self._override_expiry_deferred = False
        self._last_activity_change = self._override_time
        if (
            prior_override_source == "physical_context_relax"
            and source != "physical_context_relax"
            and self._living_room_atmosphere_curator is not None
        ):
            self._living_room_atmosphere_curator.reset_session(
                f"authority_replaced:{source}",
            )

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

    async def clear_override(
        self,
        source: str = "internal",
        *,
        user_requested_auto: bool = False,
    ) -> None:
        """Clear the manual override and return to automatic mode.

        Ordinary/internal clears preserve the historical Sleeping safety rule:
        clearing a Sleeping override must not blindly relight the apartment.
        The explicit Auto control is different. When the user deliberately
        selects Auto while Sleeping, that action is authoritative wake intent
        and transitions the compatibility runtime to Home + General immediately.

        Args:
            source: Caller identifier for telemetry — see set_manual_override.
                Useful for diagnosing surprise clear events (e.g. an API
                client posting ``mode=auto`` mid-evening).
            user_requested_auto: True only for the explicit user Auto action.
                Internal timeout/recovery callers must leave this False.
        """
        # DND blocks autonomous override clears (4h timeout, fusion, etc.) so
        # the locked state survives the DND window. User-initiated clears via
        # the API route still pass.
        if (
            self.is_dnd_active()
            and not source.startswith("api:")
            and not user_requested_auto
        ):
            logger.info(
                "DND active — blocking autonomous override clear (source=%s)",
                source,
            )
            return

        # Stamp the user-respect cooldown when this clear came from the
        # dashboard "auto" button. Subsequent autonomous mode pushes get
        # suppressed for USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS so the user's
        # explicit "auto" choice isn't immediately undone by a sensor lane.
        old_effective = self._override_mode
        # Sleeping can also be held directly in `_current_mode` by the PC
        # sleep watcher with no manual override. Explicit Auto must still see
        # that as a Sleeping → Home wake boundary.
        if user_requested_auto and self.current_mode == "sleeping":
            old_effective = "sleeping"
        old_source = self._override_source
        if source.startswith("api:") or user_requested_auto:
            self._user_cleared_override_at = datetime.now(tz=TZ)
            self._user_clear_allows_physical_context_relax = (
                old_effective == "sleeping"
            )

        was_overridden = self._manual_override
        self._manual_override = False
        self._override_mode = None
        self._override_source = None
        self._override_time = None
        self._override_expiry_deferred = False
        if (
            old_source == "physical_context_relax"
            and self._living_room_atmosphere_curator is not None
        ):
            self._living_room_atmosphere_curator.reset_session(
                f"authority_released:{source}",
            )
        if self._current_mode == "idle":
            self._idle_entered_at = datetime.now(tz=TZ)

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
            if user_requested_auto:
                # Explicit Sleeping → Auto is a strong human wake signal. Do
                # not resurrect whatever detector mode happened to accumulate
                # underneath the Sleeping override; establish the compatibility
                # representation of Home + General first. Fresh semantic
                # activity may refine it normally on the next report.
                now = datetime.now(tz=TZ)
                self._current_mode = "idle"
                self._current_game = None
                self._mode_source = "user_auto"
                self._mode_source_key = "user_auto"
                self._last_activity = "idle"
                self._last_activity_change = now
                self._idle_entered_at = now
                self._last_mode_source_report_at["user_auto"] = now

                # Cancel any still-running sleep fade even when Away prevents
                # the lighting apply below.
                if (
                    self._sleep_fade_task
                    and not self._sleep_fade_task.done()
                ):
                    self._sleep_fade_task.cancel()
                    self._sleep_fade_task = None
                    logger.info(
                        "Sleep fade cancelled — explicit Auto wake requested"
                    )

                if self._away_hold:
                    # Hard Away/geofence authority outranks the wake control.
                    # Keep both suppression bits intact and expose the new raw
                    # activity only for later reacquisition.
                    logger.info(
                        "Sleeping→Auto wake held by hard Away suppression "
                        "(source=%s)",
                        source,
                    )
                    # Match the engine's normal Away contract: expose raw
                    # state, but do not fire downstream mode callbacks that may
                    # actuate Sonos or other integrations while nobody is home.
                    await self._broadcast_mode()
                    return

                self._home_awake_confirmed = True

                if self._external_off_detected:
                    # Sleeping/off can leave the soft all-lights-off latch set.
                    # Explicit wake intent may release that soft latch, but this
                    # path never clears the hard Away hold above.
                    self._external_off_detected = False
                    self._invalidate_dedup_cache()
                    logger.info(
                        "Sleeping→Auto wake released soft external-off "
                        "suppression (source=%s)",
                        source,
                    )

                logger.info(
                    "Sleeping→Auto wake: house=home activity=general "
                    "(source=%s)",
                    source,
                )
                await self._apply_mode("idle", force_resend=True)
                await self._broadcast_mode()
                await self._fire_mode_change_callbacks(self._current_mode)
                return

            # Non-explicit clears keep the historical safety contract: the
            # user may still be asleep, so leave lights off but wake lifecycle
            # subscribers (camera, ambient, ML logger) to the exposed mode.
            await self._broadcast_mode()
            if old_effective != self._current_mode:
                await self._fire_mode_change_callbacks(self._current_mode)
            return

        # Clearing an autonomous override while away must expose raw state
        # without re-lighting or firing downstream mode callbacks.
        if self._external_off_detected or self._away_hold:
            await self._broadcast_mode()
            logger.info(
                "Override clear tracked but not actuated while away/external-off"
            )
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
            "user_clear_allows_physical_context_relax": (
                self._user_clear_allows_physical_context_relax
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

        Expired autonomous overrides are dropped. Expired user-owned
        overrides are restored until a fresh semantic mode can safely replace
        them; `sleeping` remains exempt because it has no timeout by design.
        Always restores the zone+posture rule stamp so gate 2's post-expiry
        refractory survives a restart.
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

        self._user_clear_allows_physical_context_relax = bool(
            saved.get("user_clear_allows_physical_context_relax", False)
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

        source = saved.get("override_source")

        # Physical evidence is process-local and must be re-established after
        # restart. Never restore this override from pre-start camera state;
        # the next fresh 15-second couch commit will enter through the evaluator.
        if source == "physical_context_relax":
            logger.info("Physical-context override awaits post-start couch evidence")
            await self._persist_override_state()
            return

        # Sleeping has no timeout by design (CLAUDE.md: "Persistent override").
        # An expired autonomous push is safe to drop at startup. An explicit
        # user choice is not: sources are not yet reporting, so restoring it
        # prevents booting into a stale idle/color state. The run loop releases
        # it once a fresh non-idle semantic replacement arrives.
        if mode != "sleeping":
            elapsed = datetime.now(tz=TZ) - override_time
            if elapsed > timedelta(hours=self._override_timeout_hours):
                if source in AUTONOMOUS_PUSH_SOURCES:
                    logger.info(
                        "Autonomous override (%s, source=%s) age %.0fmin "
                        "exceeds %dh timeout — treating as expired",
                        mode, source, elapsed.total_seconds() / 60,
                        self._override_timeout_hours,
                    )
                    await self._persist_override_state()
                    return
                self._override_expiry_deferred = True
                logger.info(
                    "User override (%s, source=%s) age %.0fmin exceeds %dh "
                    "timeout — restoring until a fresh mode replaces it",
                    mode, source, elapsed.total_seconds() / 60,
                    self._override_timeout_hours,
                )

        self._manual_override = True
        self._override_source = source
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

    # ── Per-light override verbs ────────────────────────────────────────
    # Implementations live in light_override_manager.py (GH#87 step 4).
    # These delegates keep the original method names for external callers
    # (TransitLightingService, DeskExitKitchenService, WS handler, tests).

    def mark_light_manual(
        self, light_id: str, target: Optional[dict] = None,
    ) -> None:
        """Mark a light as manually adjusted — protects it from automation.

        Per-light overrides are cleared on the next explicit mode change
        (manual override set/cleared) so automation resumes naturally.
        """
        self._overrides.mark_manual(light_id, target)

    def _clear_per_light_overrides(self) -> None:
        """Clear all per-light manual overrides."""
        self._overrides.clear_manual_stamps()

    def _invalidate_dedup_cache(self) -> None:
        """Drop the per-light dedup cache so the next ``_apply_state`` re-sends
        to every light. See LightOverrideManager.invalidate_dedup_cache for
        the full force-re-apply discipline rationale.
        """
        self._overrides.invalidate_dedup_cache()

    def _forget_dedup_light(self, light_id: str) -> None:
        """Drop one light from the dedup cache so the next reconcile re-sends
        the mode's state to it.
        """
        self._overrides.forget_dedup_light(light_id)

    def _prune_expired_transit_overrides(self) -> None:
        """Remove transit overrides whose deadline has passed."""
        self._overrides.prune_expired_transit()

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
        await self._overrides.apply_transit_override(
            states,
            duration_seconds=duration_seconds,
            transition_time=transition_time,
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
        await self._overrides.clear_transit_override(
            light_ids=light_ids, transition_time=transition_time,
        )

    # ------------------------------------------------------------------
    # Light state application
    # ------------------------------------------------------------------

    async def _reconcile_effect(
        self,
        desired: Optional[str | dict[str, Any]],
        intended_states: Optional[dict[str, dict]] = None,
        transitiontime: int | None = None,
    ) -> bool:
        """Safely establish targets, settle, then reconcile Hue effects."""
        return await self._effect_manager.reconcile(
            desired,
            establish_safety=lambda release_ids: (
                self._applicator.establish_effect_release(
                    intended_states,
                    transitiontime,
                    release_ids,
                )
            ),
        )

    async def establish_effect_release(
        self,
        intended_states: Optional[dict[str, dict]],
        transitiontime: int | None,
        release_light_ids: set[str],
    ) -> LightApplyResult:
        """Establish effect-release targets while the shared boundary is held."""
        return await self._applicator.establish_effect_release(
            intended_states,
            transitiontime,
            release_light_ids,
        )

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
        if mode != "gaming" and self._screen_sync is not None:
            clear_gaming = getattr(
                self._screen_sync, "clear_accepted_gaming_state", None,
            )
            if callable(clear_gaming):
                clear_gaming()

        # Away/external-off CHOKEPOINT: while the apartment is suppressed,
        # NO path may actuate lights — not just run_loop (gated upstream)
        # but the side doors live testing found 2026-06-10: the transit/
        # desk-exit clear-revert (reapply_mode), scheduled routines, and
        # any future caller. Paths that legitimately re-light clear the
        # flag FIRST (signal_presence on arrive/camera; user override in
        # set_manual_override).
        if self._external_off_detected:
            logger.debug(
                "_apply_mode(%s) skipped — away/external-off suppressed", mode,
            )
            return

        # Cancel any in-progress sleep fade if switching to an active mode
        if mode != "sleeping" and self._sleep_fade_task and not self._sleep_fade_task.done():
            self._sleep_fade_task.cancel()
            self._sleep_fade_task = None
            logger.info("Sleep fade cancelled — activity resumed")

        # Screen sync no longer has a start/stop loop — colors arrive via
        # POST /api/automation/screen-color and are gated by SCREEN_SYNC_MODES
        # at the route handler. No engine-side action needed when modes change.

        # Capture one local timestamp for every clock-dependent decision in
        # this mode application. Period/effect selection, the watching-asleep
        # guard, and wind-down interpolation must not observe different clocks.
        now = self._now()
        period = self._get_time_period(now)

        # Determine what effect should be active for this mode+period.
        # IMPORTANT: don't stop the current effect yet. Stopping an active
        # effect before the new brightness target is on the bridge causes the
        # bridge to reset brightness to 100%, producing the visible "pop" on
        # mode change. We reconcile effects at the END of this function, after
        # _apply_state (or scene activation) has established the new target.
        desired_effect = self._get_desired_effect(mode, period)
        pre_transition_targets = {
            light_id: target.copy()
            for light_id, target in self._last_applied_per_light.items()
        }

        # On a true mode transition, the previous mode may have used HSB
        # while this one uses CT, an effect may have been running and changed
        # bridge state, or manual overrides may have just been released —
        # any of which can leave the cache stale. Periodic reapply ticks
        # don't have those concerns and rely on dedup to no-op cleanly.
        if force_resend:
            self._invalidate_dedup_cache()

        # Sleep mode: establish the dim target and release any active effect as
        # one serialized transition, then continue the existing fade to off.
        # Stopping an active effect before setting a brightness target pops the
        # bridge to 100% (same root cause as the mode-change flash documented
        # in _reconcile_effect).
        if mode == "sleeping":
            if self._sleep_fade_task and not self._sleep_fade_task.done():
                return  # Fade already in progress

            # Apply dim initial target — deep ember at bri=20. 1s snap so the
            # first thing Anthony sees (already in bed) is sleep-friendly.
            initial_state = {"on": True, "bri": 20, "hue": 5000, "sat": 254}
            self._invalidate_dedup_cache()
            if self._effect_manager.needs_reconcile(desired_effect):
                release_targets = {
                    light_id: initial_state.copy()
                    for light_id in self._effect_manager.release_light_ids()
                }
                released = await self._reconcile_effect(
                    desired_effect,
                    intended_states=release_targets,
                    transitiontime=10,
                )
                if not released:
                    logger.warning(
                        "Sleep transition aborted: effect release safety failed",
                    )
                    return
            else:
                # No effect release is needed, but preserve the prior visible
                # dim step using its acknowledged Hue transition deadline.
                applied = await self._apply_state(initial_state, transitiontime=10)
                await self._transition_boundary.wait_for_settle(applied.successful)

            self._sleep_fade_task = asyncio.create_task(self._sleep_fade())
            return

        # Social mode: route through party sub-mode system (handles own effects)
        if mode == "social":
            await self._apply_social_style()
            return

        # Check for scene override (user-mapped Hue scene for this mode+time)
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
            and self._is_likely_still_asleep(now)
        ):
            logger.info(
                "Watching mode holding night state past wake_hour — "
                "user likely still asleep (bed+reclined observed at %s)",
                self._last_bed_reclined_during_watching_at,
            )
            period = "night"
        override_scene = self._scene_overrides.get(mode, {}).get(period)
        atmosphere_plan = (
            await self._plan_living_room_atmosphere(
                period=period,
                scene_override_active=override_scene is not None,
            )
            if mode == "relax"
            else None
        )
        if atmosphere_plan is not None and atmosphere_plan.should_apply:
            desired_effect = preserve_atmosphere_effect_scope(desired_effect)
        if override_scene and self._hue_v2 and self._hue_v2.connected:
            source = self._scene_override_sources.get(mode, {}).get(period, "bridge")
            override_applied = False
            failure_reason: str | None = None
            if mode == "gaming":
                self._gaming_scene_transition_pending = True
            try:
                owners_released = (
                    mode != "gaming"
                    or await self._release_external_owners_for_scene()
                )
            except asyncio.CancelledError:
                if mode == "gaming":
                    self._gaming_scene_transition_pending = False
                raise
            except Exception:
                if mode == "gaming":
                    self._gaming_scene_transition_pending = False
                raise
            if not owners_released:
                self._gaming_scene_transition_pending = False
                logger.warning(
                    "Gaming scene activation deferred: external owner release failed",
                )
                return
            try:
                if source == "bridge":
                    async def activate_native_override() -> bool:
                        return await self._hue_v2.activate_scene(override_scene)

                    override_applied = await self._effect_manager.replace_with_action(
                        activate_native_override,
                        establish_safety=lambda release_ids: (
                            self.establish_effect_release(
                                pre_transition_targets or None,
                                MODE_TRANSITION_TIME.get(mode),
                                release_ids,
                            )
                        ),
                        desired=desired_effect,
                    )
                    logger.info(
                        "Applied scene override for %s/%s: %s",
                        mode, period, override_scene,
                    )
                elif source == "preset":
                    from backend.api.routes.scenes import SCENE_PRESETS
                    preset = SCENE_PRESETS.get(override_scene)
                    if preset:
                        normalized = {
                            str(light_id): light_state.copy()
                            for light_id, light_state in preset["lights"].items()
                        }

                        async def preset_ready() -> bool:
                            return True

                        override_applied = (
                            await self._effect_manager.replace_with_action(
                                preset_ready,
                                establish_safety=lambda release_ids: (
                                    self.establish_effect_release(
                                        normalized,
                                        MODE_TRANSITION_TIME.get(mode),
                                        release_ids,
                                    )
                                ),
                                desired=desired_effect,
                            )
                        )
                    else:
                        failure_reason = f"preset '{override_scene}' not in SCENE_PRESETS"
            except asyncio.CancelledError:
                if mode == "gaming":
                    self._gaming_scene_transition_pending = False
                raise
            except Exception as e:
                failure_reason = f"{type(e).__name__}: {e}"
                logger.error(
                    "Scene override failed for %s/%s (%s): %s",
                    mode, period, override_scene, e,
                    exc_info=True,
                )

            # No await occurs between clearing this latch and recording a
            # successful scene marker below, so another coroutine cannot enter
            # the release -> accepted-scene gap.  Failures intentionally reopen
            # ordinary Gaming ownership before the fallback composition awaits.
            if mode == "gaming":
                self._gaming_scene_transition_pending = False

            if override_applied:
                if mode == "gaming":
                    if self._screen_sync is not None:
                        supersede = getattr(
                            self._screen_sync, "supersede_light", None,
                        )
                        if callable(supersede):
                            for light_id in self._screen_sync.target_lights:
                                supersede(light_id)
                        clear_gaming = getattr(
                            self._screen_sync, "clear_accepted_gaming_state", None,
                        )
                        if callable(clear_gaming):
                            clear_gaming()
                    self._current_gaming_resolution = None
                    self._gaming_plan_changed = False
                    self._last_gaming_transition_reason = "scene_override"
                    self._gaming_scene_override = {
                        "requested_game": self._current_game,
                        "selected_profile": None,
                        "schedule_type": self._gaming_schedule_type(now),
                        "period": period,
                        "selected_variant": None,
                        "fallback_reason": "explicit_scene_override",
                        "legacy_daytime_exception": False,
                        "transition_reason": "scene_override",
                        "current_plan_differs_from_previous": False,
                    }
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

        # A native scene changes bridge state without making the ordinary
        # per-light cache authoritative.  When its mapping disappears, take
        # one bounded bridge snapshot for a safe composed release, then force
        # a real reconcile rather than deduplicating against pre-scene state.
        gaming_scene_released = bool(
            mode == "gaming"
            and override_scene is None
            and self._gaming_scene_override is not None
        )
        scene_release_baseline: dict[str, dict[str, Any]] = {}
        if gaming_scene_released:
            scene_release_baseline = await self._read_scene_release_baseline()
            self._invalidate_dedup_cache()

        # Gaming has one production composition path. The pure resolver owns
        # generic/profile selection; the established engine pipeline below
        # still owns context overlays, protected lights, effects and dedup.
        gaming_resolution: Optional[GamingResolution] = None
        gaming_scheduled_interpolation = False
        game = self._current_game
        mode_states = {"day": {}} if mode == "gaming" else _get_mode_state_table(mode, game)
        if mode_states is not None:
            if mode == "gaming":
                gaming_context = GamingContext(
                    game_slug=game,
                    schedule_type=self._gaming_schedule_type(now),
                    period=period,
                )
                gaming_resolution = resolve_gaming_lighting(gaming_context)
                state = {
                    light_id: light.copy()
                    for light_id, light in gaming_resolution.state.items()
                }
                # Preserve the existing gradual evening→night evolution. The
                # helper refuses CT↔HSB intermediate targets, so a future
                # incompatible profile simply takes the explicit phased path
                # below rather than issuing an invalid mixed-color command.
                schedule = (
                    self._schedule_config.weekday
                    if now.weekday() < 5
                    else self._schedule_config.weekend
                )
                winddown_total = schedule.winddown_start_hour * 60
                current_total = now.hour * 60 + now.minute
                minutes_until_winddown = winddown_total - current_total
                if (
                    period == "evening"
                    and 0 < minutes_until_winddown <= WINDDOWN_RAMP_MINUTES
                ):
                    progress = (
                        WINDDOWN_RAMP_MINUTES - minutes_until_winddown
                    ) / WINDDOWN_RAMP_MINUTES
                    night_resolution = resolve_gaming_lighting(
                        GamingContext(
                            game_slug=game,
                            schedule_type=gaming_context.schedule_type,
                            period="night",
                        )
                    )
                    if gaming_resolution.legacy_daytime_exception:
                        # Rust remains exact legacy output in this commit,
                        # including its established after-dark ramp.
                        state = _lerp_light_state(
                            state, night_resolution.state, progress,
                        )
                        gaming_scheduled_interpolation = True
                    else:
                        try:
                            state = interpolate_gaming_state(
                                state, night_resolution.state, progress,
                            )
                            gaming_scheduled_interpolation = True
                        except ValueError:
                            # The phase handler below performs color-space
                            # changes only after an acknowledged dim/settle
                            # boundary.
                            pass
            elif "day" in mode_states:
                # Time-aware mode: blend evening → night during the 30-min ramp window
                schedule = (
                    self._schedule_config.weekday
                    if now.weekday() < 5
                    else self._schedule_config.weekend
                )
                winddown_total = schedule.winddown_start_hour * 60
                current_total = now.hour * 60 + now.minute
                minutes_until_winddown = winddown_total - current_total

                if (
                    period == "evening"
                    and 0 < minutes_until_winddown <= WINDDOWN_RAMP_MINUTES
                ):
                    progress = (WINDDOWN_RAMP_MINUTES - minutes_until_winddown) / WINDDOWN_RAMP_MINUTES
                    evening_state = _resolve_activity_state(mode, "evening", game)
                    night_state = _resolve_activity_state(mode, "night", game)
                    state = _lerp_light_state(evening_state, night_state, progress)
                else:
                    state = _resolve_activity_state(mode, period, game)
            else:
                state = _resolve_activity_state(mode, period, game)

            atmosphere_active = bool(
                atmosphere_plan is not None and atmosphere_plan.should_apply
            )
            # The curator owns only its bounded L1/L3/L4/L6 overlay. The ordinary
            # pipeline still owns global brightness, environmental processing,
            # protected-light gates, dedup, and Hue application.
            if atmosphere_active:
                state = merge_living_room_atmosphere(
                    state,
                    atmosphere_plan.palette,
                )

            # Apply learned lighting preferences as overlay (ML Phase 1).
            # Learned values replace hardcoded defaults per-light, per-property.
            # Weather class threaded in (Layer 4) so the overlay picks the
            # weather-specific bucket when one exists, otherwise falls back
            # to the "any" baseline.
            lighting_learner = getattr(self, "_lighting_learner", None)
            if lighting_learner and mode != "gaming":
                weather_for_overlay = (
                    self._get_current_weather_condition() or "any"
                )
                zone_for_overlay, _ = self._current_zone_posture()
                overlay = lighting_learner.get_overlay(
                    mode, period, weather_for_overlay, zone=zone_for_overlay,
                )
                if overlay:
                    deltas: dict[str, dict] = {}
                    for light_id, prefs in overlay.items():
                        if light_id in state:
                            # Per-light Relax learning describes the ordinary
                            # palette. Do not let it replace curator-owned
                            # atmosphere identity; L2/L5 remain learner-owned.
                            if (
                                atmosphere_active
                                and light_id in LIVING_ROOM_ATMOSPHERE_LIGHT_IDS
                            ):
                                continue
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
            atmosphere_brightness_basis = (
                {
                    light_id: state[light_id].copy()
                    for light_id in LIVING_ROOM_ATMOSPHERE_LIGHT_IDS
                    if light_id in state
                }
                if atmosphere_active
                else None
            )
            state = self._apply_lux_multiplier(state, mode)
            state = self._functional_weather_brightness(state, mode, period)
            state = self._gaming_day_surround_brightness(state, mode, period)
            state = self._apply_zone_overlay(state, mode, period)
            if mode not in WEATHER_SKIP_MODES:
                state = self._weather_adjust(state)
            if atmosphere_brightness_basis is not None:
                state = bound_living_room_atmosphere_brightness(
                    state,
                    atmosphere_brightness_basis,
                    period,
                )
            if self._screen_sync is not None:
                prime = getattr(self._screen_sync, "prime_from_mode_state", None)
                if prime is not None:
                    prime(mode, period, state)
            gaming_plan: Optional[_GamingPlanSnapshot] = None
            gaming_transition_reason: Optional[str] = None
            accepted_plan_changed = False
            handoff_baseline = {
                **pre_transition_targets,
                **self._gaming_handoff_retry_baseline,
                **scene_release_baseline,
            }
            if gaming_resolution is not None:
                gaming_plan = _GamingPlanSnapshot.from_resolution(gaming_resolution)
                gaming_transition_reason = self._classify_gaming_transition(
                    gaming_plan,
                    state,
                    scheduled_interpolation=gaming_scheduled_interpolation,
                    scene_released=gaming_scene_released,
                )
                accepted_plan_changed = (
                    self._last_gaming_target is None
                    or state != self._last_gaming_target
                )
            tt = (
                GAMING_TRANSITION_TIME[gaming_transition_reason]
                if gaming_transition_reason is not None
                else ATMOSPHERE_TRANSITION_TIME
                if atmosphere_plan is not None
                and atmosphere_plan.should_apply
                else MODE_TRANSITION_TIME.get(mode)
            )
            crosses_color_space = bool(
                gaming_transition_reason is not None
                and self._gaming_crossing_light_ids(state, handoff_baseline)
            )
            if self._effect_manager.needs_reconcile(desired_effect):
                # One serialized sequence: force safe targets (including
                # protected held targets), wait the commanded transition,
                # then release/start the effect.
                if crosses_color_space and tt is not None:
                    applied = await self._reconcile_gaming_effect_handoff(
                        desired_effect,
                        state,
                        handoff_baseline,
                        tt,
                    )
                else:
                    applied = await self._reconcile_effect(
                        desired_effect,
                        intended_states=state,
                        transitiontime=tt,
                    )
            else:
                # Steady plans ride the normal dedup path. CT↔HSB target
                # changes use the small acknowledged two-phase handoff instead
                # of asking Hue to interpolate incompatible command spaces.
                if crosses_color_space and tt is not None:
                    applied = await self._apply_gaming_color_space_handoff(
                        state,
                        tt,
                        handoff_baseline,
                    )
                else:
                    applied = await self._apply_state(state, transitiontime=tt)
            if gaming_plan is not None and (
                applied is True
                or isinstance(applied, LightApplyResult) and not applied.failed
            ):
                # A scene release becomes authoritative only after its
                # composed replacement is accepted.  Until then the native
                # scene marker remains both the retry trigger and the only
                # honest diagnostics authority.
                if gaming_scene_released:
                    self._gaming_scene_override = None
                self._current_gaming_resolution = gaming_plan
                self._last_gaming_resolution = gaming_plan
                self._last_gaming_target = {
                    light_id: light.copy() for light_id, light in state.items()
                }
                if self._screen_sync is not None:
                    publish = getattr(
                        self._screen_sync, "publish_accepted_gaming_state", None,
                    )
                    if callable(publish):
                        publish(state)
                self._last_gaming_transition_reason = gaming_transition_reason
                self._gaming_plan_changed = accepted_plan_changed
            if atmosphere_plan is not None and atmosphere_plan.should_apply:
                await self._living_room_atmosphere_curator.observe_application(
                    atmosphere_plan,
                    applied,
                )
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
        state = ACTIVITY_LIGHT_STATES["social"]
        transitiontime = MODE_TRANSITION_TIME["social"]
        if self._effect_manager.needs_reconcile(None):
            await self._reconcile_effect(
                None,
                intended_states=state,
                transitiontime=transitiontime,
            )
        else:
            await self._apply_state(state, transitiontime=transitiontime)

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
    ) -> LightApplyResult:
        """Apply a light state (uniform or per-light) — GH#87 step-5 delegate
        to :class:`LightApplicator`. Kept as a method (not just an attribute)
        so callers (``_apply_mode``, ``_apply_time_based``, ``_sleep_fade``,
        ``_maybe_drift``) and test spies that patch ``engine._apply_state``
        are honored unchanged.
        """
        return await self._applicator.apply_state(state, transitiontime)

    def _protected_light_ids(self) -> set[str]:
        """Light ids the mode-apply pipeline must NOT write this tick — GH#87
        step-5 delegate to :class:`LightApplicator`. (manual + transit
        overrides, plus fresh screen-sync-owned lights while sync is fresh.)
        """
        return self._applicator.protected_light_ids()

    def register_external_light_owner(self, owner: Any) -> None:
        """Register a direct bridge writer for final-apply protection."""
        if owner not in self._external_light_owners:
            self._external_light_owners.append(owner)

    def _active_external_light_owners(self) -> list[Any]:
        return [
            owner for owner in self._external_light_owners
            if id(owner) not in self._suspended_external_owner_ids
        ]

    def _invalidate_external_light_owners(self, reason: str) -> None:
        """Drop direct-writer stamps after authoritative dark/suppressed state."""
        for owner in self._external_light_owners:
            invalidate = getattr(owner, "invalidate_ownership", None)
            if callable(invalidate):
                invalidate(reason)

    async def _release_external_owners_for_scene(self) -> bool:
        """Reclaim direct-writer lamps before an explicit Gaming scene."""
        for owner in self._external_light_owners:
            release = getattr(owner, "release_for_scene", None)
            if callable(release) and await release() is not True:
                return False
        return True

    async def reclaim_external_light_release(
        self, owner: Any, light_ids: set[str],
    ) -> LightApplyResult:
        """Synchronously replace one writer with the accepted Gaming plan."""
        targets = {
            light_id: self._last_gaming_target[light_id].copy()
            for light_id in light_ids
            if self._last_gaming_target is not None
            and light_id in self._last_gaming_target
        }
        unresolved = set(light_ids) - set(targets)
        if unresolved or self.current_mode != "gaming" or self._gaming_scene_override:
            return LightApplyResult(failed=set(light_ids))
        if self._external_off_detected:
            return LightApplyResult(skipped=set(light_ids))

        async with self._transition_boundary.serialized():
            sync = self._screen_sync
            supersede = getattr(sync, "supersede_light", None)
            for light_id in light_ids:
                if callable(supersede):
                    supersede(light_id)
                self._last_applied_per_light.pop(light_id, None)

            self._suspended_external_owner_ids.add(id(owner))
            try:
                result = await self._apply_per_light(
                    targets, MODE_TRANSITION_TIME.get("gaming"),
                )
            finally:
                self._suspended_external_owner_ids.discard(id(owner))

            synchronize = getattr(sync, "synchronize_physical_state", None)
            if callable(synchronize):
                for light_id in result.successful:
                    synchronize(light_id, targets[light_id])
            return result

    async def _apply_uniform(
        self, state: dict[str, Any], transitiontime: int | None = None,
    ) -> LightApplyResult:
        """Apply the same state to all lights — GH#87 step-5 delegate."""
        return await self._applicator.apply_uniform(state, transitiontime)

    async def _apply_per_light(
        self, states: dict[str, dict], transitiontime: int | None = None,
    ) -> LightApplyResult:
        """Apply individual states to each light — GH#87 step-5 delegate."""
        return await self._applicator.apply_per_light(states, transitiontime)

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
        for lid in RELAX_DRIFT_LIGHT_IDS:
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
        if learner and condition and mode != "gaming":
            try:
                learned = learner.has_weather_pref(mode, period, condition)
            except Exception:
                learned = set()
        return _calc_apply_functional_weather_brightness(
            state, mode, period, condition,
            learner_has_learned=learned,
        )

    def _gaming_day_surround_brightness(
        self, state: dict[str, Any], mode: str, period: str,
    ) -> dict[str, Any]:
        """Apply the bounded L1/L3/L4 Gaming/day functional surround."""
        ema, baseline = self._read_fresh_camera_lux()
        return _calc_apply_gaming_day_surround_brightness(
            state, mode, period, self._get_current_weather_condition(),
            lux_reading=ema, baseline_lux=baseline,
            brightness_multiplier=self._mode_brightness.get(mode, 1.0),
        )

    def _get_desired_effect(
        self, mode: str, period: Optional[str] = None,
    ) -> Optional[str | dict[str, Any]]:
        """Determine the dynamic effect target for a mode (shim → effect_manager)."""
        resolved_period = period if period is not None else self._get_time_period()
        return self._effect_manager.get_desired_effect(mode, resolved_period)

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

        # Legacy idle is intentionally dark from midnight until wake_hour so
        # stale/initial detector evidence cannot relight a sleeping apartment.
        # Once explicit Sleeping → Auto has confirmed a human wake, that same
        # idle evidence means Home + General instead. Reuse the established
        # pre-ramp dim-warm state until the normal schedule becomes active.
        if self._home_awake_confirmed and 0 <= hour < schedule.wake_hour:
            state: dict[str, Any] = {
                "on": True,
                "bri": schedule.wake_brightness,
                "hue": 6000,
                "sat": 200,
            }
            state = self._weather_adjust(state)
            await self._apply_legacy_time_based_state(state)
            return

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
            await self._apply_legacy_time_based_state(state)
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
                await self._apply_legacy_time_based_state(state)
                return

    async def _apply_legacy_time_based_state(
        self, state: dict[str, Any],
    ) -> LightApplyResult:
        """Apply legacy idle scheduling without enrolling Plant Wash in it."""
        targets = {
            light_id: state.copy()
            for light_id in LEGACY_TIME_BASED_LIGHT_IDS
        }
        # The old uniform schedule has no reviewed Plant Wash calibration.
        # Keep this legacy path conservative without changing global fan-out.
        targets["6"] = {"on": False}
        return await self._apply_state(targets)

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
                    and self._override_source != "physical_context_relax"
                ):
                    # A user override suspends idle dwell. Otherwise days of
                    # stale idle can trigger ambient_relax immediately after
                    # the override eventually clears.
                    self._idle_entered_at = None
                    elapsed = now - self._override_time
                    if elapsed > timedelta(hours=self._override_timeout_hours):
                        if not self._override_is_user_owned():
                            logger.info(
                                "Autonomous override timed out after %dh "
                                "(mode=%s source=%s)",
                                self._override_timeout_hours,
                                self._override_mode,
                                self._override_source,
                            )
                            await self.clear_override(source="timeout_4h")
                        elif self._has_fresh_mode_replacement(now):
                            logger.info(
                                "Manual override timed out after %dh; fresh "
                                "replacement mode=%s source=%s",
                                self._override_timeout_hours,
                                self._current_mode,
                                self._mode_source_key,
                            )
                            await self.clear_override(source="timeout_4h")
                        elif not self._override_expiry_deferred:
                            logger.info(
                                "Manual override expiry deferred: no fresh "
                                "semantic replacement (underlying=%s source=%s)",
                                self._current_mode,
                                self._mode_source_key,
                            )
                            self._override_expiry_deferred = True

                # Expire stale per-light overrides (same 4h window as the
                # mode-level override, tracked per-entry via the datetime
                # stamped in mark_light_manual).
                self._overrides.expire_manual_stamps(
                    now, self._override_timeout_hours,
                )

                # Shadow-only living-room decision context. This runs after
                # policy/ownership expiry cleanup but before early returns
                # such as away/external-off suppression can hide current
                # evidence. It owns no writer interface and never blocks the
                # existing loop on failure.
                await self.evaluate_living_room_context(
                    trigger="automation_tick",
                )
                if (
                    self._manual_override
                    and self._override_source == "physical_context_relax"
                    and self.is_dnd_active()
                    and self._living_room_atmosphere_curator is not None
                ):
                    self._living_room_atmosphere_curator.reset_session(
                        "dnd_active",
                    )

                # Check for external off (Alexa geofence)
                external_off = await self._check_external_off()
                await self._evaluate_physical_context_relax(
                    now=now, trigger="automation_tick",
                )
                if external_off:
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
                    _rescue_veto = self._attendance_veto_reason()

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
                    _relax_veto = self._attendance_veto_reason()

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
                elif (
                    self._manual_override
                    and self._override_source == "physical_context_relax"
                    and not self.is_dnd_active()
                ):
                    # Couch Relax is lifecycle-backed by the override path,
                    # which ordinary periodic mode reconciliation skips.
                    # Re-enter the normal pipeline so period changes and the
                    # single 30-minute evolution become eligible; per-light
                    # dedup keeps unchanged ticks writer-free.
                    await self._apply_mode("relax")

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
                            veto_reason = self._attendance_veto_reason()

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

                # Confidence fusion — compute and observe only. Fusion has no
                # mode-actuation authority; promotion requires a separate,
                # explicitly approved authority gate in a future change.
                fusion = getattr(self, "_confidence_fusion", None)
                if fusion:
                    fusion_result = fusion.compute_fusion()
                    if fusion_result:
                        self._last_fusion_result = fusion_result
                        fc = fusion_result["fused_confidence"]
                        fm = fusion_result["fused_mode"]
                        shadow_candidate = None
                        veto_reason = None

                        # Preserve former actuation eligibility and attendance
                        # vetoes as shadow telemetry without granting fusion a
                        # writer path into set_manual_override().
                        if (
                            fusion_result.get("can_override")
                            and not self._manual_override
                            and self._current_mode not in ("idle",)
                            and fm != self._current_mode
                        ):
                            veto_reason = self._attendance_veto_reason()
                            shadow_candidate = "override"
                        elif (
                            fusion_result.get("auto_apply")
                            and not self._manual_override
                            and self._current_mode in ("idle",)
                            and fm != self._current_mode
                        ):
                            veto_reason = self._attendance_veto_reason()
                            shadow_candidate = "auto_apply"

                        # Shadow-log every fusion tick so
                        # compute_accuracy_by_source has per-signal data
                        # to tune weights against. broadcast=False to
                        # avoid flooding the pipeline WebSocket at 1/min.
                        if ml_logger:
                            factors = {
                                "agreement": fusion_result["agreement"],
                                "signal_details": fusion_result["signals"],
                                "current_mode": self._current_mode,
                                "action": "shadow",
                            }
                            if shadow_candidate is not None:
                                factors["shadow_candidate"] = shadow_candidate
                            if veto_reason is not None:
                                factors["vetoed_by"] = veto_reason
                            await ml_logger.log_decision(
                                predicted_mode=fm,
                                confidence=fc,
                                decision_source="fusion",
                                factors=factors,
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

        # Gate 6: attendance vetoes — even with dwell met, recent desk attendance
        # OR a recent process=working report means the user isn't actually
        # settling in (they're lying back on the bed momentarily while still
        # on the PC). Reset the dwell so a fresh 120s of bed+reclined-with-no-
        # other-activity is required after attendance clears. Same pair of
        # vetoes that gate late_night_rescue + winddown_push since 2026-05-07
        # (commit 0dcb245). Checked here BEFORE the refractory stamp burn —
        # per feedback_rule_refractory_burn_pattern.md, silent-rejection
        # conditions must run before the stamp or the rule locks itself out
        # for 4h on a no-op.
        at_desk = self.is_recently_at_desk()
        process_working = self.is_recent_process_working()
        if at_desk or process_working:
            logger.debug(
                "Zone+posture rule vetoed at fire-time: recently_at_desk=%s "
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
            self._invalidate_external_light_owners("external_off")
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
        effective_mode = self.effective_mode
        effective_source = self.effective_source
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
            "effective_mode": effective_mode,
            "effective_source": effective_source,
        }

        # --- Output ---
        output = {
            "mode": effective_mode,
            "time_period": period,
            "effect": self._active_effect_name,
            "brightness_multiplier": brightness_mult,
            "lights": dict(self._last_applied_per_light),
            "living_room_atmosphere": (
                self.get_living_room_atmosphere_status()
            ),
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
        await self.evaluate_living_room_context(trigger="pipeline_publish")
        await self._pipeline.broadcast()

    async def _broadcast_mode(self) -> None:
        """Broadcast the current mode to all WebSocket clients."""
        await self._ws_manager.broadcast("mode_update", {
            "mode": self.current_mode,
            "source": self.mode_source,
            "house_state": self.house_state,
            "activity": self.activity,
            "manual_override": self._manual_override,
            "time_period": self._get_time_period(),
        })
        await self._broadcast_pipeline()
