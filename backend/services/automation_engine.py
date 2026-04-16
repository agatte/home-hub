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
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("home_hub.automation")

# Indianapolis timezone (Indiana doesn't follow standard Eastern DST rules)
TZ = ZoneInfo("America/Indiana/Indianapolis")

# Modes during which screen sync colors should be applied. The receiver
# endpoint at POST /api/automation/screen-color drops colors silently when
# the current mode isn't in this set.
SCREEN_SYNC_MODES = frozenset(("gaming", "watching", "movie"))

# Modes that skip weather-reactive lighting adjustments entirely.
# Social has its own party lighting; sleeping is a gradual fade sequence.
WEATHER_SKIP_MODES = frozenset(("social", "sleeping"))

# Weather condition → effect override. When a weather condition matches and
# the mode has no auto-effect already, this effect is applied on top.
# Thunderstorm (sparkle) fires any time of day; others evening/night only.
WEATHER_EFFECT_MAP: dict[str, str | None] = {
    "thunderstorm": "sparkle",
    "rain": "candle",
    "snow": "opal",
}


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


@dataclass
class ScheduleConfig:
    """Combined weekday + weekend schedule configuration."""

    weekday: DaySchedule = field(default_factory=DaySchedule)
    weekend: DaySchedule = field(default_factory=lambda: DaySchedule(
        wake_hour=8,
        ramp_start_hour=8,
        ramp_duration_minutes=120,
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

WINDDOWN_RAMP_MINUTES = 30  # Duration of evening → night fade (minutes)

# Auto-activate effects based on mode + time period.
# None = no auto effect. Social mode handles its own effects via SOCIAL_STYLES.
EFFECT_AUTO_MAP: dict[str, dict[str, str | None]] = {
    "relax":    {"day": "opal",    "evening": "candle",  "night": "fire"},
    "working":  {"day": None,      "evening": None,      "night": None},
    "gaming":   {"day": None,      "evening": None,      "night": None},
    "movie":    {"day": None,      "evening": None,      "night": None},
    "watching": {"day": None,      "evening": "glisten", "night": "glisten"},
}

# Mode-specific transition speeds (deciseconds: 10 = 1 second).
# Each mode gets a physically different feel when transitioning.
MODE_TRANSITION_TIME: dict[str, int] = {
    "working":  20,   # 2s smooth
    "gaming":    5,   # 0.5s snappy
    "watching": 30,   # 3s cinematic fade
    "relax":    50,   # 5s gentle (slower for moodier vibe)
    "social":   10,   # 1s
    "sleeping": 50,   # 5s gradual
    "movie":    30,   # 3s
    "idle":     20,   # 2s
    "away":     30,   # 3s
}


ACTIVITY_LIGHT_STATES: dict[str, dict[str, Any]] = {
    # ── Gaming ────────────────────────────────────────────────────────
    # Dim blue-violet ambient — screen sync on L2 is the star. Accents
    # stay very low so the screen color dominates the room. All HSB.
    "gaming": {
        "day": {
            "1": {"on": True, "bri": 30,  "hue": 47000, "sat": 100},   # Muted blue-violet wash
            "2": {"on": True, "bri": 200, "hue": 46920, "sat": 200},   # Fallback (screen sync overrides)
            "3": {"on": True, "bri": 20,  "hue": 47000, "sat": 80},    # Dim blue accent
            "4": {"on": True, "bri": 15,  "hue": 48000, "sat": 90},    # Faintest depth fill
        },
        "evening": {
            "1": {"on": True, "bri": 22,  "hue": 47000, "sat": 120},   # Slightly richer wash
            "2": {"on": True, "bri": 150, "hue": 46920, "sat": 220},   # Fallback (screen sync overrides)
            "3": {"on": True, "bri": 15,  "hue": 47000, "sat": 100},   # Dimmer accent
            "4": {"on": True, "bri": 10,  "hue": 48000, "sat": 110},   # Near-invisible
        },
        "night": {
            "1": {"on": True, "bri": 12,  "hue": 47000, "sat": 140},   # Barely there glow
            "2": {"on": True, "bri": 100, "hue": 46920, "sat": 240},   # Fallback (screen sync overrides)
            "3": {"on": True, "bri": 8,   "hue": 47000, "sat": 120},   # Ghost light
            "4": {"on": True, "bri": 6,   "hue": 48000, "sat": 130},   # Almost off
        },
    },
    # ── Working ───────────────────────────────────────────────────────
    # Clean ct-mode whites only. Per-light brightness gradient creates
    # depth instead of flat uniform lighting. Evening shifts noticeably
    # warmer. Night: desk lamp functional + ghost-light ambient fill.
    "working": {
        "day": {
            "1": {"on": True, "bri": 180, "ct": 233},    # Bright neutral fill
            "2": {"on": True, "bri": 254, "ct": 210},    # Max bright, slightly cool desk lamp
            "3": {"on": True, "bri": 140, "ct": 250},    # Kitchen fill
            "4": {"on": True, "bri": 100, "ct": 270},    # Warmer back fill
        },
        "evening": {
            "1": {"on": True, "bri": 100, "ct": 340},    # Noticeably warmer, dimmer
            "2": {"on": True, "bri": 180, "ct": 300},    # Still functional desk, warmer
            "3": {"on": True, "bri": 60,  "ct": 370},    # Low warm kitchen
            "4": {"on": True, "bri": 35,  "ct": 400},    # Warm background
        },
        "night": {
            "1": {"on": True, "bri": 25,  "ct": 440},    # Faint warm glow
            "2": {"on": True, "bri": 130, "ct": 350},    # Late-night desk (functional, warm)
            "3": _LIGHT_OFF,                               # Kitchen off
            "4": {"on": True, "bri": 10,  "ct": 454},    # Ghost light depth fill
        },
    },
    # ── Watching ──────────────────────────────────────────────────────
    # Soft warm ambient with warm-neutral bias on L2 (behind screen).
    # More lights stay on than before for comfortable viewing.
    "watching": {
        "day": {
            "1": {"on": True, "bri": 50,  "ct": 370},    # Soft warm ambient
            "2": {"on": True, "bri": 45,  "ct": 280},    # Warm-neutral bias behind screen
            "3": _LIGHT_OFF,
            "4": {"on": True, "bri": 25,  "ct": 400},    # Warm depth fill
        },
        "evening": {
            "1": {"on": True, "bri": 30,  "ct": 420},    # Dim warm glow
            "2": {"on": True, "bri": 35,  "ct": 310},    # Warm bias
            "3": _LIGHT_OFF,
            "4": {"on": True, "bri": 15,  "ct": 454},    # Very dim warm wash
        },
        "night": {
            "1": {"on": True, "bri": 12,  "ct": 454},    # Barely-there amber
            "2": {"on": True, "bri": 20,  "ct": 350},    # Minimal warm bias
            "3": _LIGHT_OFF,
            "4": {"on": True, "bri": 8,   "ct": 454},    # Ghost light
        },
    },
    # Base state for social/party — no time awareness (flat, no period keys).
    # Warm amber-peach palette; sub-styles override when active.
    "social": {
        "1": {"on": True, "bri": 200, "hue": 7000,  "sat": 200},   # Warm amber-peach
        "2": {"on": True, "bri": 180, "hue": 56000, "sat": 180},   # Soft magenta-pink
        "3": {"on": True, "bri": 220, "hue": 5000,  "sat": 220},   # Rich amber (kitchen gathering)
        "4": {"on": True, "bri": 160, "hue": 10000, "sat": 160},   # Warm coral
    },
    # ── Relax ─────────────────────────────────────────────────────────
    # Full HSB warm gradient — amber/gold/ember tones only. Each light
    # gets deeper amber as you move from L1→L4. Paired with opal (day),
    # candle (evening), fire (night) effects.
    "relax": {
        "day": {
            "1": {"on": True, "bri": 100, "hue": 5000,  "sat": 200},   # Warm amber wash
            "2": {"on": True, "bri": 80,  "hue": 6500,  "sat": 180},   # Softer orange-gold
            "3": {"on": True, "bri": 55,  "hue": 4000,  "sat": 220},   # Deeper amber
            "4": {"on": True, "bri": 40,  "hue": 3000,  "sat": 240},   # Burnt orange depth
        },
        "evening": {
            "1": {"on": True, "bri": 55,  "hue": 4000,  "sat": 240},   # Deep amber
            "2": {"on": True, "bri": 45,  "hue": 5500,  "sat": 220},   # Warm gold
            "3": {"on": True, "bri": 30,  "hue": 3000,  "sat": 254},   # Ember glow
            "4": {"on": True, "bri": 20,  "hue": 2000,  "sat": 254},   # Deep red-amber
        },
        "night": {
            "1": {"on": True, "bri": 25,  "hue": 3000,  "sat": 254},   # Dim ember
            "2": {"on": True, "bri": 20,  "hue": 4000,  "sat": 240},   # Faint warm glow
            "3": {"on": True, "bri": 12,  "hue": 2000,  "sat": 254},   # Near-invisible ember
            "4": {"on": True, "bri": 8,   "hue": 1500,  "sat": 254},   # Dying coal
        },
    },
    # ── Movie ─────────────────────────────────────────────────────────
    # Same bias-light approach as watching.
    "movie": {
        "day": {
            "1": {"on": True, "bri": 50,  "ct": 370},
            "2": {"on": True, "bri": 45,  "ct": 280},
            "3": _LIGHT_OFF,
            "4": {"on": True, "bri": 25,  "ct": 400},
        },
        "evening": {
            "1": {"on": True, "bri": 30,  "ct": 420},
            "2": {"on": True, "bri": 35,  "ct": 310},
            "3": _LIGHT_OFF,
            "4": {"on": True, "bri": 15,  "ct": 454},
        },
        "night": {
            "1": {"on": True, "bri": 12,  "ct": 454},
            "2": {"on": True, "bri": 20,  "ct": 350},
            "3": _LIGHT_OFF,
            "4": {"on": True, "bri": 8,   "ct": 454},
        },
    },
}

# ---------------------------------------------------------------------------
# Party sub-modes for social mode
# ---------------------------------------------------------------------------

SOCIAL_STYLES: dict[str, dict[str, Any]] = {
    "color_cycle": {
        "display_name": "Color Cycle",
        "description": "Slow warm-toned color rotation",
        "base_state": None,  # Uses the new social base state
        "effect": "prism",
    },
    "club": {
        "display_name": "Club",
        "description": "Deep purple and magenta with sparkle",
        "base_state": {
            "1": {"on": True, "bri": 180, "hue": 50000, "sat": 254},   # Purple
            "2": {"on": True, "bri": 200, "hue": 54000, "sat": 240},   # Magenta
            "3": {"on": True, "bri": 160, "hue": 48000, "sat": 254},   # Blue-purple
            "4": {"on": True, "bri": 140, "hue": 56000, "sat": 220},   # Pink-magenta
        },
        "effect": "sparkle",
    },
    "rave": {
        "display_name": "Rave",
        "description": "High energy, max brightness, every color",
        "base_state": {
            "1": {"on": True, "bri": 254, "hue": 0,     "sat": 254},   # Red
            "2": {"on": True, "bri": 254, "hue": 25500, "sat": 254},   # Green
            "3": {"on": True, "bri": 254, "hue": 46920, "sat": 254},   # Blue
            "4": {"on": True, "bri": 254, "hue": 12750, "sat": 254},   # Yellow
        },
        "effect": "prism",
    },
    "fire_and_ice": {
        "display_name": "Fire & Ice",
        "description": "Warm reds vs cool blues — temperature contrast",
        "base_state": {
            "1": {"on": True, "bri": 200, "hue": 3000,  "sat": 254},   # Deep orange
            "2": {"on": True, "bri": 180, "hue": 1000,  "sat": 254},   # Red-orange
            "3": {"on": True, "bri": 200, "hue": 44000, "sat": 220},   # Cool blue
            "4": {"on": True, "bri": 180, "hue": 48000, "sat": 200},   # Blue-purple
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


def _lerp_light_state(
    state_a: dict[str, Any],
    state_b: dict[str, Any],
    progress: float,
) -> dict[str, Any]:
    """
    Interpolate between two light states.

    Handles both uniform {bri, hue, sat} and per-light {"1": {...}, ...} formats.
    progress=0.0 returns state_a, progress=1.0 returns state_b.
    """
    progress = min(1.0, max(0.0, progress))

    def _lerp_val(a: int, b: int) -> int:
        return int(a + (b - a) * progress)

    def _lerp_single(sa: dict, sb: dict) -> dict:
        result: dict[str, Any] = {"on": sa.get("on", True) or sb.get("on", True)}
        for key in ("bri", "hue", "sat", "ct"):
            if key in sa and key in sb:
                result[key] = _lerp_val(sa[key], sb[key])
            elif key in sa:
                result[key] = sa[key]
            elif key in sb:
                result[key] = sb[key]
        return result

    is_per_light_a = any(k in ("1", "2", "3", "4") for k in state_a)
    is_per_light_b = any(k in ("1", "2", "3", "4") for k in state_b)

    if is_per_light_a and is_per_light_b:
        return {
            lid: _lerp_single(state_a[lid], state_b[lid])
            for lid in state_a
            if lid in state_b
        }

    return _lerp_single(state_a, state_b)


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
        event_logger=None,
        weather_service=None,
    ) -> None:
        self._hue = hue
        self._hue_v2 = hue_v2
        self._ws_manager = ws_manager
        self._event_logger = event_logger
        self._weather_service = weather_service
        self._music_mapper = None  # Set by main.py after construction

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

        # Per-light state tracking for deduplication
        self._last_applied_per_light: dict[str, dict] = {}

        # Per-light manual overrides — maps light_id → timestamp
        # Lights in this dict are protected from automation until next mode change
        self._manual_light_overrides: dict[str, datetime] = {}

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
        self._social_style: str = "color_cycle"
        self._active_effect_name: Optional[str] = None  # Name of active Hue dynamic effect

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

        # Decision pipeline — real-time snapshot of all inputs → output
        self._screen_sync = None  # Set by main.py after construction
        self._pipeline_history: list[dict] = []
        self._last_pipeline_broadcast: Optional[datetime] = None

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
        """Determine the current time period using the schedule config."""
        now = datetime.now(tz=TZ)
        hour = now.hour
        schedule = (
            self._schedule_config.weekday
            if now.weekday() < 5
            else self._schedule_config.weekend
        )
        day_start = schedule.ramp_start_hour + max(
            1, schedule.ramp_duration_minutes // 60
        )

        if day_start <= hour < schedule.evening_start_hour:
            return "day"
        elif schedule.evening_start_hour <= hour < schedule.winddown_start_hour:
            return "evening"
        else:
            return "night"

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

    async def report_activity(self, mode: str, source: str) -> None:
        """
        Process an activity report from the PC agent, ambient monitor, or camera.

        Args:
            mode: Detected mode (gaming, watching, working, social, idle, away).
            source: Detection source ("process", "ambient", "audio_ml", or "camera").
        """
        if not self._enabled:
            return

        # Ambient "idle" should not override process-detected activity
        if source == "ambient" and mode == "idle":
            if self._mode_source == "process" and self._current_mode != "idle":
                return

        # Camera "away" should not override active process detection
        if source == "camera" and mode == "away":
            if self._mode_source == "process" and self._current_mode not in ("idle", "away"):
                return

        # Camera "idle" (present) should not downgrade higher-priority modes
        if source == "camera" and mode == "idle":
            current_priority = MODE_PRIORITY.get(self._current_mode, 0)
            if current_priority > MODE_PRIORITY.get("idle", 1):
                return

        old_mode = self._current_mode

        # Ambient social can override process idle, but not gaming
        if source == "ambient" and mode == "social":
            if self._current_mode == "gaming":
                return

        # Accept the new detected mode (tracks what the PC is actually doing)
        self._current_mode = mode
        self._mode_source = source
        self._last_activity = mode
        self._last_activity_change = datetime.now(tz=TZ)

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

        # Apply the appropriate light state
        await self._apply_mode(mode)

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

    async def set_manual_override(self, mode: str) -> None:
        """Set a manual mode override from the dashboard."""
        # Capture the effective mode (override if active, else detected) so that
        # event logging and callback gating see the real "previous" mode, not
        # the stale private _current_mode which only reflects PC agent state.
        old_mode = self.current_mode
        self._manual_override = True
        self._override_mode = mode
        self._override_time = datetime.now(tz=TZ)
        self._last_activity_change = self._override_time

        self._clear_per_light_overrides()
        logger.info(f"Manual override set: {mode}")
        # Broadcast first so the UI updates immediately, then apply lights
        await self._broadcast_mode()
        await self._apply_mode(mode)
        # Fire mode change callbacks only if the mode actually changed
        if old_mode != mode:
            await self._fire_mode_change_callbacks(mode)
        if self._event_logger and old_mode != mode:
            await self._event_logger.log_mode_change(
                mode=mode,
                previous_mode=old_mode,
                source="manual",
            )

    async def clear_override(self) -> None:
        """Clear the manual override and return to automatic mode."""
        old_effective = self._override_mode
        self._manual_override = False
        self._override_mode = None
        self._override_time = None

        self._clear_per_light_overrides()
        logger.info("Manual override cleared — returning to auto")

        # Re-apply current detected mode or time-based
        if self._current_mode in ("idle", "away"):
            await self._apply_time_based()
        else:
            await self._apply_mode(self._current_mode)

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

        # Screen sync no longer has a start/stop loop — colors arrive via
        # POST /api/automation/screen-color and are gated by SCREEN_SYNC_MODES
        # at the route handler. No engine-side action needed when modes change.

        # Determine what effect should be active for this mode+period.
        # Only stop effects when switching to a different effect — stopping
        # and re-applying the same effect every cycle resets the brightness
        # base on the bridge, causing dim flickering instead of bright.
        desired_effect = self._get_desired_effect(mode)
        if desired_effect != self._active_effect_name:
            if self._hue_v2 and self._hue_v2.connected and self._active_effect_name:
                await self._hue_v2.stop_effect_all()
            self._active_effect_name = None

        # Clear dedup cache so the new state is always applied — effects and
        # external apps change bridge state independently, making the cache stale.
        self._last_applied_per_light = {}

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

        # Check for scene override (user-mapped Hue scene for this mode+time)
        period = self._get_time_period()
        override_scene = self._scene_overrides.get(mode, {}).get(period)
        if override_scene and self._hue_v2 and self._hue_v2.connected:
            source = self._scene_override_sources.get(mode, {}).get(period, "bridge")
            if source == "bridge":
                await self._hue_v2.activate_scene(override_scene)
                logger.info("Applied scene override for %s/%s: %s", mode, period, override_scene)
            elif source == "preset":
                # Preset scenes are handled via the scenes route — activate by name
                from backend.api.routes.scenes import SCENE_PRESETS, _activate_per_light
                preset = SCENE_PRESETS.get(override_scene)
                if preset:
                    await _activate_per_light(preset["lights"], self._hue)
            # Still apply auto-effects on top of scene overrides
            if self._hue_v2 and self._hue_v2.connected:
                if desired_effect and desired_effect != self._active_effect_name:
                    await asyncio.sleep(0.3)
                    await self._hue_v2.set_effect_all(desired_effect)
                    self._active_effect_name = desired_effect
            return

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
                    for light_id, prefs in overlay.items():
                        if light_id in state:
                            state[light_id] = {**state[light_id], **prefs}

            state = self._apply_brightness_multiplier(state, mode)
            if mode not in WEATHER_SKIP_MODES:
                state = self._weather_adjust(state)
            tt = MODE_TRANSITION_TIME.get(mode)
            await self._apply_state(state, transitiontime=tt)

            # Apply effect if it changed — delay lets the bridge process
            # the light state first so the effect inherits correct brightness.
            if self._hue_v2 and self._hue_v2.connected:
                if desired_effect and desired_effect != self._active_effect_name:
                    await asyncio.sleep(0.3)
                    await self._hue_v2.set_effect_all(desired_effect)
                    self._active_effect_name = desired_effect
                elif not desired_effect and self._active_effect_name:
                    await self._hue_v2.stop_effect_all()
                    self._active_effect_name = None
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
            if effect != self._active_effect_name:
                await self._hue_v2.set_effect_all(effect)
                self._active_effect_name = effect

    async def _sleep_fade(self) -> None:
        """
        Gradually dim lights then turn off.

        Manual trigger: quick 2-minute fade (you asked for lights off).
        Auto-detected: slow 10-minute fade (you drifted off naturally).

        Runs as a background task so it doesn't block the automation loop.
        Cancellable if the user wakes up (mouse/keyboard activity detected).
        """
        try:
            # Get current brightness from first light as baseline
            lights = await self._hue.get_all_lights()
            if not lights:
                return
            current_bri = lights[0].get("bri", 80)

            # Manual = quick fade (2 min), auto = slow fade (10 min)
            if self._manual_override:
                steps = 4
                step_interval = 30  # 4 steps × 30s = 2 minutes
            else:
                steps = 6
                step_interval = 100  # 6 steps × 100s ≈ 10 minutes

            bri_step = current_bri / steps
            total_min = steps * step_interval // 60

            logger.info(
                f"Sleep fade started: {current_bri} → off over "
                f"{total_min} minutes ({'manual' if self._manual_override else 'auto'})"
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
        # If any lights have manual overrides, fall through to per-light path
        if self._manual_light_overrides:
            per_light = {lid: state for lid in ("1", "2", "3", "4")}
            await self._apply_per_light(per_light, transitiontime)
            return

        # Convert to per-light for dedup tracking
        per_light = {lid: state for lid in ("1", "2", "3", "4")}
        if per_light == self._last_applied_per_light:
            return

        self._last_applied_per_light = {lid: state.copy() for lid in ("1", "2", "3", "4")}
        cmd = {**state}
        if transitiontime is not None:
            cmd["transitiontime"] = transitiontime
        await self._hue.set_all_lights(cmd)
        logger.info(f"Applied uniform state: bri={state.get('bri')}, hue={state.get('hue')}")

    async def _apply_per_light(
        self, states: dict[str, dict], transitiontime: int | None = None,
    ) -> None:
        """Apply individual states to each light (parallel when possible)."""
        # Filter out lights with active manual overrides
        if self._manual_light_overrides:
            skipped = [lid for lid in states if lid in self._manual_light_overrides]
            if skipped:
                states = {
                    lid: s for lid, s in states.items()
                    if lid not in self._manual_light_overrides
                }
                logger.debug(f"Skipping manually overridden lights: {skipped}")
                if not states:
                    return

        # Optimization: if all lights get the same state, use the uniform path
        unique_states = list(states.values())
        if not self._manual_light_overrides and all(
            s == unique_states[0] for s in unique_states
        ):
            await self._apply_uniform(unique_states[0], transitiontime)
            return

        # Build list of lights that actually changed
        tasks = []
        changed_ids = []
        for light_id, state in states.items():
            last = self._last_applied_per_light.get(light_id)
            if state != last:
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

    async def _maybe_drift(self) -> None:
        """
        Apply subtle random perturbation to current light state if the mode
        has been unchanged for drift_interval_minutes. Prevents the "nothing
        ever changes" feeling during long sessions.
        """
        if not self._scene_drift_enabled:
            return
        # Only drift during active modes (not idle/away/sleeping/social)
        mode = self.current_mode
        if mode in ("idle", "away", "sleeping", "social"):
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
        if mode not in WEATHER_SKIP_MODES:
            drifted = self._weather_adjust(drifted)
        self._last_applied_per_light = {}  # Force apply
        await self._apply_state(drifted, transitiontime=100)  # 10s imperceptible
        logger.info("Scene drift applied for mode '%s'", mode)

    def _weather_adjust(self, state: dict[str, Any]) -> dict[str, Any]:
        """Apply subtle weather-based adjustments to light states.

        Works with both uniform (flat) and per-light (keyed by ID) formats.
        Respects each light's color mode: adjusts CT for CT-based lights and
        hue/sat for HSB-based lights. Adjustments are small deltas — the
        apartment should feel subtly connected to the outside, not dramatic.
        """
        if not self._weather_service:
            return state

        try:
            weather = self._weather_service.get_cached()
            if not weather:
                return state
        except Exception:
            return state

        desc = weather.get("description", "").lower()
        condition = self._classify_weather(desc, weather)
        if not condition:
            return state

        logger.debug("Weather adjustment: %s (%s)", condition, desc)

        # Detect format: per-light dicts have light ID keys with dict values
        is_per_light = all(
            isinstance(v, dict) for v in state.values()
        ) and any(k in ("1", "2", "3", "4") for k in state.keys())

        if is_per_light:
            return {
                lid: self._adjust_single_light(ls, condition)
                if ls.get("on", True) else ls
                for lid, ls in state.items()
            }
        return self._adjust_single_light(state, condition)

    def _classify_weather(
        self, desc: str, weather: dict[str, Any],
    ) -> str | None:
        """Map weather description to a condition category."""
        if "thunderstorm" in desc:
            return "thunderstorm"
        if "rain" in desc or "drizzle" in desc:
            return "rain"
        if "snow" in desc:
            return "snow"
        if "overcast" in desc or "clouds" in desc:
            return "clouds"
        if "clear" in desc:
            now = datetime.now(tz=TZ)
            sunset_ts = weather.get("sunset")
            if sunset_ts:
                from datetime import timezone as _tz
                sunset_utc = datetime.fromtimestamp(sunset_ts, tz=_tz.utc)
                sunset_local = sunset_utc.astimezone(TZ)
                minutes_to_sunset = (sunset_local - now).total_seconds() / 60
                if -30 <= minutes_to_sunset <= 30:
                    return "golden_hour"
        return None

    def _get_desired_effect(self, mode: str) -> str | None:
        """Determine what dynamic effect should be active for a mode.

        Checks mode-specific auto-effects first (EFFECT_AUTO_MAP), then
        falls back to weather-driven effects for eligible periods.
        Returns None for modes that manage their own effects (sleeping,
        social) or when no effect should be active.
        """
        if mode in ("sleeping", "social"):
            return None
        period = self._get_time_period()
        effect_map = EFFECT_AUTO_MAP.get(mode, {})
        auto_effect = effect_map.get(period)
        if not auto_effect:
            weather_effect = self._get_weather_effect()
            if weather_effect and (
                period in ("evening", "night")
                or weather_effect == "sparkle"
            ):
                auto_effect = weather_effect
        return auto_effect

    def _get_weather_effect(self) -> str | None:
        """Return an effect override based on current weather, or None."""
        if not self._weather_service:
            return None
        try:
            weather = self._weather_service.get_cached()
            if not weather:
                return None
        except Exception:
            return None
        desc = weather.get("description", "").lower()
        for keyword, effect in WEATHER_EFFECT_MAP.items():
            if keyword in desc:
                return effect
        return None

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

    @staticmethod
    def _adjust_single_light(
        light: dict[str, Any], condition: str,
    ) -> dict[str, Any]:
        """Apply weather adjustment to a single light's state dict.

        Respects CT vs HSB: if the light uses ``ct``, adjustments shift
        color temperature. If it uses ``hue``/``sat``, adjustments shift
        those values instead. Never mixes the two color spaces.
        """
        adj = {**light}
        uses_ct = "ct" in adj

        if condition == "thunderstorm":
            # Cooler / purple tint, noticeable dim
            adj["bri"] = max(1, adj.get("bri", 200) - 30)
            if uses_ct:
                adj["ct"] = max(153, adj["ct"] - 80)
            else:
                adj["hue"] = min(65535, adj.get("hue", 8000) + 12000)
                adj["sat"] = min(254, adj.get("sat", 100) + 60)

        elif condition == "rain":
            # Cooler, slightly dimmer — cozy indoor contrast
            adj["bri"] = max(1, adj.get("bri", 200) - 15)
            if uses_ct:
                adj["ct"] = max(153, adj["ct"] - 50)
            else:
                adj["hue"] = max(0, adj.get("hue", 8000) + 4000)
                adj["sat"] = min(254, adj.get("sat", 100) + 30)

        elif condition == "snow":
            # Brighter, crisp cool white
            adj["bri"] = min(254, adj.get("bri", 200) + 25)
            if uses_ct:
                adj["ct"] = max(153, adj["ct"] - 60)

        elif condition == "clouds":
            # Warmer, noticeably dimmer — overcast feel
            adj["bri"] = max(1, int(adj.get("bri", 200) * 0.85))
            if uses_ct:
                adj["ct"] = min(500, adj["ct"] + 25)

        elif condition == "golden_hour":
            # Rich warm golden shift
            if uses_ct:
                adj["ct"] = min(500, adj["ct"] + 50)
            else:
                adj["hue"] = min(65535, adj.get("hue", 8000) + 3000)
                adj["sat"] = min(254, adj.get("sat", 100) + 40)

        return adj

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

                # ML behavioral predictor (primary, if active)
                predictor = getattr(self, "_behavioral_predictor", None)
                ml_logger = getattr(self, "_ml_logger", None)
                if (
                    predictor
                    and not self._manual_override
                    and self._current_mode in ("idle", "away")
                ):
                    prediction = await predictor.predict(
                        current_mode=self._current_mode,
                    )
                    if prediction and not prediction.get("shadow"):
                        confidence = prediction["confidence"]
                        if confidence >= 0.95:
                            # Auto-apply at high confidence
                            await self.set_manual_override(prediction["predicted_mode"])
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

                # Rule engine fallback (fires if ML didn't produce a result)
                rule_engine = getattr(self, "_rule_engine", None)
                if rule_engine and not self._manual_override and self._current_mode in ("idle", "away"):
                    await rule_engine.check_rules(self._current_mode)

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
            "social_style": (
                self._social_style if mode == "social" else None
            ),
            "brightness_multiplier": brightness_mult,
            "lights": dict(self._last_applied_per_light),
        }

        return {
            "timestamp": now.isoformat(),
            "inputs": inputs,
            "resolution": resolution,
            "output": output,
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
            "social_style": self._social_style,
        })
        await self._broadcast_pipeline()
