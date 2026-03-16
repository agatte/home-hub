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
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("home_hub.automation")

# Indianapolis timezone (Indiana doesn't follow standard Eastern DST rules)
TZ = ZoneInfo("America/Indiana/Indianapolis")


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
    away_start_hour: Optional[int] = 7     # None = no away period
    away_end_hour: Optional[int] = 18
    evening_start_hour: int = 18
    winddown_start_hour: int = 21


@dataclass
class ScheduleConfig:
    """Combined weekday + weekend schedule configuration."""

    weekday: DaySchedule = field(default_factory=DaySchedule)
    weekend: DaySchedule = field(default_factory=lambda: DaySchedule(
        wake_hour=8,
        ramp_start_hour=8,
        ramp_duration_minutes=120,
        away_start_hour=None,
        away_end_hour=None,
    ))


# Default mode brightness multipliers (1.0 = unchanged)
DEFAULT_MODE_BRIGHTNESS: dict[str, float] = {
    "gaming": 1.0,
    "working": 1.0,
    "watching": 1.0,
    "relax": 1.0,
    "movie": 1.0,
    "social": 1.0,
}


# Light ID → room mapping for readability
LIGHT_IDS = {
    "living_room": "1",
    "bedroom": "2",
    "kitchen_front": "3",
    "kitchen_back": "4",
}

# Mode priority — higher index wins when multiple sources report
MODE_PRIORITY = {
    "sleeping": 0,
    "away": 0,
    "idle": 1,
    "working": 2,
    "watching": 3,
    "social": 4,
    "gaming": 5,
}

# ---------------------------------------------------------------------------
# Activity light states — time-aware per-light states
# ---------------------------------------------------------------------------
# Structure: mode → time_period → per-light state dict
# Time periods: "day" (8-18), "evening" (18-21), "night" (21-8)
# Social mode is flat (no time keys) — routed through party sub-modes.

_LIGHT_OFF = {"on": False}


def _uniform(bri: int, hue: int, sat: int) -> dict[str, dict]:
    """Build a per-light dict where all 4 lights get the same state."""
    state = {"on": True, "bri": bri, "hue": hue, "sat": sat}
    return {"1": state, "2": state.copy(), "3": state.copy(), "4": state.copy()}


def _gaming_state(bri: int, hue: int, sat: int) -> dict[str, dict]:
    """Build gaming state: lights 1/3/4 warm bias, light 2 fallback (screen sync overrides)."""
    bias = {"on": True, "bri": bri, "hue": hue, "sat": sat}
    return {
        "1": bias,
        "2": bias.copy(),  # Fallback — screen sync overrides this immediately
        "3": bias.copy(),
        "4": bias.copy(),
    }


def _watching_state(bri: int, hue: int, sat: int) -> dict[str, dict]:
    """Build watching/movie state: bedroom lamp on, others off."""
    return {
        "1": _LIGHT_OFF,
        "2": {"on": True, "bri": bri, "hue": hue, "sat": sat},
        "3": _LIGHT_OFF,
        "4": _LIGHT_OFF,
    }


ACTIVITY_LIGHT_STATES: dict[str, dict[str, Any]] = {
    # Warm bias + screen sync on bedroom lamp (light 2 overridden by sync)
    # Time baselines: day=220, evening=180, night=60
    "gaming": {
        "day":     _gaming_state(230, 8000, 140),
        "evening": _gaming_state(210, 8000, 150),
        "night":   _gaming_state(120, 8000, 160),
    },
    # Warm productive — near time baseline, functional lighting
    "working": {
        "day":     _uniform(230, 10000, 100),
        "evening": _uniform(180, 8500, 130),
        "night":   _uniform(80, 8000, 140),
    },
    # Bedroom bias light only — brighter during day for screen contrast
    "watching": {
        "day":     _watching_state(100, 8000, 160),
        "evening": _watching_state(70, 8000, 180),
        "night":   _watching_state(30, 8000, 200),
    },
    # Base state for social/party — no time awareness (flat, no period keys)
    "social": {
        "1": {"on": True, "bri": 200, "hue": 0, "sat": 254},
        "2": {"on": True, "bri": 200, "hue": 0, "sat": 254},
        "3": {"on": True, "bri": 200, "hue": 0, "sat": 254},
        "4": {"on": True, "bri": 200, "hue": 0, "sat": 254},
    },
    # Amber candlelight — paired with candle effect
    "relax": {
        "day":     _uniform(200, 7000, 200),
        "evening": _uniform(150, 6500, 220),
        "night":   _uniform(80, 6500, 220),
    },
    # Movie alias — same structure as watching
    "movie": {
        "day":     _watching_state(100, 8000, 160),
        "evening": _watching_state(70, 8000, 180),
        "night":   _watching_state(30, 8000, 200),
    },
}

# ---------------------------------------------------------------------------
# Party sub-modes for social mode
# ---------------------------------------------------------------------------

SOCIAL_STYLES: dict[str, dict[str, Any]] = {
    "color_cycle": {
        "display_name": "Color Cycle",
        "description": "Slow rotation through all colors",
        "base_state": None,  # Uses default social base state
        "effect": "prism",
    },
    "club": {
        "display_name": "Club",
        "description": "Deep purple and magenta with sparkle",
        "base_state": {
            "1": {"on": True, "bri": 180, "hue": 50000, "sat": 254},
            "2": {"on": True, "bri": 180, "hue": 54000, "sat": 254},
            "3": {"on": True, "bri": 180, "hue": 50000, "sat": 254},
            "4": {"on": True, "bri": 180, "hue": 54000, "sat": 254},
        },
        "effect": "sparkle",
    },
    "rave": {
        "display_name": "Rave",
        "description": "High energy rapid color changes",
        "base_state": {
            "1": {"on": True, "bri": 254, "hue": 0, "sat": 254},
            "2": {"on": True, "bri": 254, "hue": 21845, "sat": 254},
            "3": {"on": True, "bri": 254, "hue": 43690, "sat": 254},
            "4": {"on": True, "bri": 254, "hue": 10922, "sat": 254},
        },
        "effect": "prism",
    },
    "fire_and_ice": {
        "display_name": "Fire & Ice",
        "description": "Warm red/orange meets cool blue",
        "base_state": {
            "1": {"on": True, "bri": 200, "hue": 2000, "sat": 254},
            "2": {"on": True, "bri": 200, "hue": 3000, "sat": 254},
            "3": {"on": True, "bri": 200, "hue": 46920, "sat": 254},
            "4": {"on": True, "bri": 200, "hue": 46920, "sat": 254},
        },
        "effect": None,
    },
}

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


def _morning_ramp(
    minute_in_window: int,
    window_minutes: int = 120,
) -> dict[str, Any]:
    """
    Calculate gradual morning light ramp from warm/dim to daylight/bright.

    Args:
        minute_in_window: Minutes elapsed since the ramp start.
        window_minutes: Total ramp duration in minutes.

    Returns:
        Light state dict interpolated between warm/dim and daylight/bright.
    """
    progress = min(1.0, max(0.0, minute_in_window / window_minutes))

    bri = int(80 + (254 - 80) * progress)
    hue = int(8000 + (34000 - 8000) * progress)
    sat = int(180 + (50 - 180) * progress)

    return {"on": True, "bri": bri, "hue": hue, "sat": sat}


def _get_time_period_static() -> str:
    """Determine the current time period (static fallback, uses defaults)."""
    hour = datetime.now(tz=TZ).hour
    if 8 <= hour < 18:
        return "day"
    elif 18 <= hour < 21:
        return "evening"
    else:
        return "night"


def _resolve_activity_state(
    mode: str,
    time_period: Optional[str] = None,
) -> dict[str, Any]:
    """
    Look up the time-appropriate light state for an activity mode.

    Time-aware entries have "day"/"evening"/"night" keys. Flat entries
    (like social) are returned as-is.

    Args:
        mode: Activity mode name.
        time_period: Override time period. Uses static default if None.
    """
    entry = ACTIVITY_LIGHT_STATES.get(mode)
    if entry is None:
        return {}
    # Time-aware entries have period keys
    if "day" in entry:
        period = time_period or _get_time_period_static()
        return entry.get(period, entry.get("night", {}))
    # Flat per-light dict (social — no time awareness)
    return entry


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
    ) -> None:
        self._hue = hue
        self._hue_v2 = hue_v2
        self._ws_manager = ws_manager

        # Current state
        self._current_mode: str = "idle"
        self._mode_source: str = "time"
        self._manual_override: bool = False
        self._override_mode: Optional[str] = None
        self._override_time: Optional[datetime] = None
        self._last_activity: Optional[str] = None
        self._last_activity_change: Optional[datetime] = None

        # Per-light state tracking for deduplication
        self._last_applied_per_light: dict[str, dict] = {}

        # Track if lights were turned off externally (Alexa geofence)
        self._external_off_detected: bool = False

        # Sleep fade task (gradual dim → off)
        self._sleep_fade_task: Optional[asyncio.Task] = None

        # Screen sync service (set by main.py after construction)
        self._screen_sync = None

        # Mode change callbacks (e.g., music mapper auto-play)
        self._on_mode_change_callbacks: list = []

        # Config
        self._enabled: bool = True
        self._override_timeout_hours: int = 4
        self._gaming_effect: Optional[str] = None
        self._social_style: str = "color_cycle"
        self._active_effect: bool = False  # Track if a Hue dynamic effect is running

        # Configurable schedule and mode brightness
        self._schedule_config = schedule_config or ScheduleConfig()
        self._mode_brightness = {**DEFAULT_MODE_BRIGHTNESS, **(mode_brightness or {})}

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

    @property
    def social_style(self) -> str:
        return self._social_style

    @social_style.setter
    def social_style(self, value: str) -> None:
        if value in SOCIAL_STYLES:
            self._social_style = value
        else:
            logger.warning(f"Unknown social style: {value}")

    @property
    def social_effect(self) -> str:
        """Backward-compatible accessor — returns effect for current social style."""
        style = SOCIAL_STYLES.get(self._social_style, {})
        return style.get("effect", "prism") or "prism"

    @social_effect.setter
    def social_effect(self, value: str) -> None:
        """Backward-compatible setter — maps effect name to a social style."""
        for style_name, style in SOCIAL_STYLES.items():
            if style.get("effect") == value:
                self._social_style = style_name
                return
        self._social_style = "color_cycle"

    @property
    def screen_sync(self):
        return self._screen_sync

    @screen_sync.setter
    def screen_sync(self, service) -> None:
        self._screen_sync = service

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

    def update_mode_brightness(self, brightness: dict[str, float]) -> None:
        """Hot-reload per-mode brightness multipliers."""
        self._mode_brightness = {**DEFAULT_MODE_BRIGHTNESS, **brightness}
        self._last_applied_per_light = {}  # Force re-apply
        logger.info(f"Mode brightness updated: {brightness}")

    def _get_time_period(self) -> str:
        """Determine the current time period using the schedule config."""
        now = datetime.now(tz=TZ)
        hour = now.hour
        schedule = (
            self._schedule_config.weekday
            if now.weekday() < 5
            else self._schedule_config.weekend
        )
        if schedule.away_start_hour is not None and schedule.away_end_hour is not None:
            day_start = schedule.away_start_hour
        else:
            day_start = schedule.ramp_start_hour + (
                schedule.ramp_duration_minutes // 60
            )
        day_end = schedule.evening_start_hour

        if day_start <= hour < day_end:
            return "day"
        elif day_end <= hour < schedule.winddown_start_hour:
            return "evening"
        else:
            return "night"

    def _build_time_rules(self, schedule: DaySchedule) -> list:
        """
        Build time rule tuples dynamically from a DaySchedule config.

        Returns the same format as the old WEEKDAY_TIME_RULES / WEEKEND_TIME_RULES
        constants: list of (start_hour, end_hour, state_or_ramp).
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

        if schedule.away_start_hour is not None:
            # Weekday pattern: ramp → away (off) → evening
            ramp_end = min(ramp_end_hour, schedule.away_start_hour)
            rules.append((
                schedule.ramp_start_hour,
                ramp_end,
                ("morning_ramp", schedule.ramp_start_hour, schedule.ramp_duration_minutes),
            ))
            if schedule.away_end_hour is not None:
                rules.append((
                    schedule.away_start_hour,
                    schedule.away_end_hour,
                    {"on": False},
                ))
                # Evening warm
                rules.append((
                    schedule.away_end_hour,
                    schedule.winddown_start_hour,
                    {"on": True, "bri": 180, "hue": 8000, "sat": 160},
                ))
        else:
            # Weekend pattern: ramp → daytime bright → evening
            ramp_end = min(ramp_end_hour, schedule.evening_start_hour)
            rules.append((
                schedule.ramp_start_hour,
                ramp_end,
                ("morning_ramp", schedule.ramp_start_hour, schedule.ramp_duration_minutes),
            ))
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
        """Apply per-mode brightness multiplier to a light state."""
        multiplier = self._mode_brightness.get(mode, 1.0)
        if multiplier == 1.0:
            return state

        # Per-light dict: keys are light IDs with dict values
        is_per_light = all(
            isinstance(v, dict) for v in state.values()
        ) and any(k in ("1", "2", "3", "4") for k in state.keys())

        if is_per_light:
            result = {}
            for lid, ls in state.items():
                ls_copy = ls.copy()
                if ls_copy.get("on", True) and "bri" in ls_copy:
                    ls_copy["bri"] = max(1, min(254, int(ls_copy["bri"] * multiplier)))
                result[lid] = ls_copy
            return result
        else:
            result = state.copy()
            if result.get("on", True) and "bri" in result:
                result["bri"] = max(1, min(254, int(result["bri"] * multiplier)))
            return result

    def register_on_mode_change(self, callback) -> None:
        """
        Register a callback to be invoked when the active mode changes.

        Args:
            callback: Async callable accepting a single mode string argument.
        """
        self._on_mode_change_callbacks.append(callback)

    async def _fire_mode_change_callbacks(self, mode: str) -> None:
        """Invoke all registered mode-change callbacks."""
        for callback in self._on_mode_change_callbacks:
            try:
                await callback(mode)
            except Exception as e:
                logger.error(f"Mode change callback error: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Activity reporting
    # ------------------------------------------------------------------

    async def report_activity(self, mode: str, source: str) -> None:
        """
        Process an activity report from the PC agent or ambient monitor.

        Args:
            mode: Detected mode (gaming, watching, working, social, idle, away).
            source: Detection source ("process" or "ambient").
        """
        if not self._enabled:
            return

        # Ambient "idle" should not override process-detected activity
        if source == "ambient" and mode == "idle":
            if self._mode_source == "process" and self._current_mode != "idle":
                return

        old_mode = self._current_mode

        # Ambient social can override process idle, but not gaming
        if source == "ambient" and mode == "social":
            if self._current_mode == "gaming":
                return

        # Accept the new mode
        self._current_mode = mode
        self._mode_source = source
        self._last_activity = mode
        self._last_activity_change = datetime.now(tz=TZ)

        # Clear manual override on activity change
        if self._manual_override and old_mode != mode:
            logger.info(
                f"Activity changed ({old_mode} → {mode}) — clearing manual override"
            )
            self._manual_override = False
            self._override_mode = None
            self._override_time = None

        # Clear external off detection on any activity
        if mode not in ("idle", "away"):
            self._external_off_detected = False

        # Apply the appropriate light state
        if not self._manual_override:
            await self._apply_mode(mode)

        # Fire mode change callbacks (e.g., music auto-play)
        if old_mode != mode:
            await self._fire_mode_change_callbacks(mode)

        # Broadcast mode change
        await self._broadcast_mode()

    async def set_manual_override(self, mode: str) -> None:
        """Set a manual mode override from the dashboard."""
        self._manual_override = True
        self._override_mode = mode
        self._override_time = datetime.now(tz=TZ)
        self._last_activity_change = self._override_time

        logger.info(f"Manual override set: {mode}")
        # Broadcast first so the UI updates immediately, then apply lights
        await self._broadcast_mode()
        await self._apply_mode(mode)
        # Fire mode change callbacks (e.g., music auto-play)
        await self._fire_mode_change_callbacks(mode)

    async def clear_override(self) -> None:
        """Clear the manual override and return to automatic mode."""
        self._manual_override = False
        self._override_mode = None
        self._override_time = None

        logger.info("Manual override cleared — returning to auto")

        # Re-apply current detected mode or time-based
        if self._current_mode in ("idle", "away"):
            await self._apply_time_based()
        else:
            await self._apply_mode(self._current_mode)

        await self._broadcast_mode()

    async def set_social_style(self, style: str) -> None:
        """
        Switch the active party sub-mode and apply it immediately.

        Args:
            style: One of SOCIAL_STYLES keys.
        """
        if style not in SOCIAL_STYLES:
            logger.warning(f"Unknown social style: {style}")
            return

        self._social_style = style
        logger.info(f"Social style changed to: {style}")

        # Re-apply if currently in social mode
        if self.current_mode == "social":
            await self._apply_mode("social")
            await self._broadcast_mode()

    # ------------------------------------------------------------------
    # Light state application
    # ------------------------------------------------------------------

    async def _apply_mode(self, mode: str) -> None:
        """Apply light state for a given mode."""
        # Cancel any in-progress sleep fade if switching to an active mode
        if mode != "sleeping" and self._sleep_fade_task and not self._sleep_fade_task.done():
            self._sleep_fade_task.cancel()
            self._sleep_fade_task = None
            logger.info("Sleep fade cancelled — activity resumed")

        # Stop screen sync if leaving a mode that uses it
        if mode not in ("watching", "gaming") and self._screen_sync:
            await self._screen_sync.stop()

        # Stop active effects only if one is running (saves ~4 HTTP calls)
        if self._active_effect and self._hue_v2 and self._hue_v2.connected:
            await self._hue_v2.stop_effect_all()
            self._active_effect = False

        # Sleep mode: gradual fade over 10 minutes then lights off
        if mode == "sleeping":
            if self._sleep_fade_task and not self._sleep_fade_task.done():
                return  # Fade already in progress
            self._sleep_fade_task = asyncio.create_task(self._sleep_fade())
            return

        # Social mode: route through party sub-mode system
        if mode == "social":
            await self._apply_social_style()
            return

        if mode in ACTIVITY_LIGHT_STATES:
            state = _resolve_activity_state(mode, self._get_time_period())
            state = self._apply_brightness_multiplier(state, mode)
            await self._apply_state(state)

            # Start screen sync for watching and gaming modes
            if mode in ("watching", "gaming") and self._screen_sync:
                # Gaming gets higher brightness cap matching the time-aware values
                if mode == "gaming":
                    state_l2 = state.get("2", {})
                    max_bri = state_l2.get("bri", 160)
                    await self._screen_sync.start(max_brightness=max_bri)
                else:
                    await self._screen_sync.start(max_brightness=80)

            # Apply dynamic effects for certain modes
            if self._hue_v2 and self._hue_v2.connected:
                if mode == "relax":
                    await self._hue_v2.set_effect_all("candle")
                    self._active_effect = True
        else:
            # Unknown mode — fall back to time-based
            await self._apply_time_based()

    async def _apply_social_style(self) -> None:
        """Apply the current party sub-mode (base colors + effect)."""
        style = SOCIAL_STYLES.get(self._social_style, SOCIAL_STYLES["color_cycle"])

        # Apply base state (per-light or default social)
        base = style.get("base_state")
        if base:
            await self._apply_state(base)
        else:
            await self._apply_state(ACTIVITY_LIGHT_STATES["social"])

        # Apply effect
        effect = style.get("effect")
        if effect and self._hue_v2 and self._hue_v2.connected:
            await self._hue_v2.set_effect_all(effect)
            self._active_effect = True

    async def _sleep_fade(self) -> None:
        """
        Gradually dim lights over 10 minutes then turn off.

        Runs as a background task so it doesn't block the automation loop.
        Cancellable if the user wakes up (mouse/keyboard activity detected).
        """
        try:
            # Get current brightness from first light as baseline
            lights = await self._hue.get_all_lights()
            if not lights:
                return
            current_bri = lights[0].get("bri", 80)

            # 6 steps over 10 minutes (~100 seconds each)
            steps = 6
            step_interval = 100
            bri_step = current_bri / steps

            logger.info(
                f"Sleep fade started: {current_bri} → off over "
                f"{steps * step_interval // 60} minutes"
            )

            for i in range(1, steps + 1):
                await asyncio.sleep(step_interval)
                new_bri = max(1, int(current_bri - bri_step * i))
                state = {"on": True, "bri": new_bri, "hue": 6000, "sat": 200}
                self._last_applied_per_light = {}  # Force apply
                await self._apply_state(state)
                logger.info(f"Sleep fade step {i}/{steps}: bri={new_bri}")

            # Final: lights off
            await asyncio.sleep(step_interval)
            self._last_applied_per_light = {}
            await self._apply_state({"on": False})
            logger.info("Sleep fade complete — lights off")

        except asyncio.CancelledError:
            logger.info("Sleep fade cancelled")
            raise
        except Exception as e:
            logger.error(f"Sleep fade error: {e}", exc_info=True)

    async def _apply_state(self, state: dict[str, Any]) -> None:
        """
        Apply a light state — supports both uniform and per-light formats.

        Args:
            state: Either a flat dict (applied to all lights) or a dict keyed
                   by light ID with individual states per light.
        """
        if not self._hue or not self._hue.connected:
            return

        # Detect format: per-light dicts have string keys like "1", "2"
        is_per_light = all(
            isinstance(v, dict) for v in state.values()
        ) and any(k in ("1", "2", "3", "4") for k in state.keys())

        if is_per_light:
            await self._apply_per_light(state)
        else:
            await self._apply_uniform(state)

    async def _apply_uniform(self, state: dict[str, Any]) -> None:
        """Apply the same state to all lights (backward-compatible path)."""
        # Convert to per-light for dedup tracking
        per_light = {lid: state for lid in ("1", "2", "3", "4")}
        if per_light == self._last_applied_per_light:
            return

        self._last_applied_per_light = {lid: state.copy() for lid in ("1", "2", "3", "4")}
        await self._hue.set_all_lights(state)
        logger.info(f"Applied uniform state: bri={state.get('bri')}, hue={state.get('hue')}")

    async def _apply_per_light(self, states: dict[str, dict]) -> None:
        """Apply individual states to each light (parallel when possible)."""
        # Optimization: if all lights get the same state, use the uniform path
        unique_states = list(states.values())
        if all(s == unique_states[0] for s in unique_states):
            await self._apply_uniform(unique_states[0])
            return

        # Build list of lights that actually changed
        tasks = []
        changed_ids = []
        for light_id, state in states.items():
            last = self._last_applied_per_light.get(light_id)
            if state != last:
                tasks.append(self._hue.set_light(light_id, state))
                self._last_applied_per_light[light_id] = state.copy()
                changed_ids.append(light_id)

        if tasks:
            await asyncio.gather(*tasks)
            on_ids = [lid for lid in changed_ids if states[lid].get("on", True)]
            off_ids = [lid for lid in changed_ids if not states[lid].get("on", True)]
            logger.info(f"Applied per-light state: on={on_ids}, off={off_ids}")

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

        for start, end, rule in rules:
            if start <= hour < end:
                if isinstance(rule, tuple) and rule[0] == "morning_ramp":
                    _, ramp_start_hour, ramp_duration = rule
                    minutes_since_start = (hour - ramp_start_hour) * 60 + minute
                    state = _morning_ramp(minutes_since_start, ramp_duration)
                else:
                    state = rule
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
                if not self._enabled:
                    await asyncio.sleep(60)
                    continue

                now = datetime.now(tz=TZ)

                # Check manual override timeout
                if self._manual_override and self._override_time:
                    elapsed = now - self._override_time
                    if elapsed > timedelta(hours=self._override_timeout_hours):
                        logger.info(
                            f"Manual override timed out after "
                            f"{self._override_timeout_hours}h"
                        )
                        await self.clear_override()

                # Check for external off (Alexa geofence)
                if await self._check_external_off():
                    await asyncio.sleep(60)
                    continue

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
                    # Re-apply activity mode to pick up day→evening→night transitions
                    # Dedup in _last_applied_per_light makes this a no-op most cycles
                    await self._apply_mode(self._current_mode)

                await asyncio.sleep(60)

            except asyncio.CancelledError:
                logger.info("Automation engine stopped")
                break
            except Exception as e:
                logger.error(f"Automation engine error: {e}", exc_info=True)
                await asyncio.sleep(60)

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

    async def _broadcast_mode(self) -> None:
        """Broadcast the current mode to all WebSocket clients."""
        await self._ws_manager.broadcast("mode_update", {
            "mode": self.current_mode,
            "source": self.mode_source,
            "manual_override": self._manual_override,
            "social_style": self._social_style,
        })
