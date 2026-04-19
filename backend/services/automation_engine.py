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

logger = logging.getLogger("home_hub.automation")

# Indianapolis timezone (Indiana doesn't follow standard Eastern DST rules)
TZ = ZoneInfo("America/Indiana/Indianapolis")

# Modes during which screen sync colors should be applied. The receiver
# endpoint at POST /api/automation/screen-color drops colors silently when
# the current mode isn't in this set.
SCREEN_SYNC_MODES = frozenset(("gaming", "watching"))

# Modes that skip weather-reactive lighting adjustments entirely.
# Social has its own party lighting; sleeping is a gradual fade sequence.
# Working/cooking/gaming opt out because they're task- or screen-focused —
# weather-dim-for-cozy is backwards there: overcast days need lamps to
# compensate for dim natural light, not further dim with it.
WEATHER_SKIP_MODES = frozenset(("social", "sleeping", "working", "cooking", "gaming"))

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


# Default mode brightness multipliers (1.0 = unchanged)
DEFAULT_MODE_BRIGHTNESS: dict[str, float] = {
    "gaming": 1.0,
    "working": 1.0,
    "watching": 1.0,
    "relax": 1.0,
    "cooking": 1.0,
    "social": 1.0,
}

# Ambient lux adaptive brightness — piecewise-linear curve mapping
# camera-derived room brightness (gray.mean, 0–255) to a brightness multiplier.
# Only applied in modes where ambient adaptation is desirable; functional
# modes (gaming, watching, cooking) and scene-override-driven activation
# bypass this stage so spatial design stays predictable.
LUX_MODES = frozenset(("working", "relax"))
LUX_CURVE: list[tuple[float, float]] = [(40.0, 1.15), (90.0, 1.00), (180.0, 0.85)]
LUX_MULT_EPSILON = 0.03      # Skip re-apply if multiplier change < 3%
LUX_STALE_SECONDS = 30       # Ignore readings older than this


def lux_to_multiplier(lux: float, baseline: float = 90.0) -> float:
    """Piecewise-linear interpolation across LUX_CURVE anchors.

    The ``baseline`` argument shifts the curve so the user's calibrated
    "normal room" reading lands at the middle anchor (multiplier = 1.00).
    Default baseline of 90 matches the raw LUX_CURVE anchors — used when
    no calibration baseline is available yet.

    Clamps to the first/last anchor's multiplier when lux is outside the
    anchor range. Dark rooms (low lux) lift brightness; bright rooms dim.
    """
    # Shift lux so that the calibrated baseline maps to the curve's midpoint.
    effective = lux - baseline + LUX_CURVE[1][0]
    if effective <= LUX_CURVE[0][0]:
        return LUX_CURVE[0][1]
    if effective >= LUX_CURVE[-1][0]:
        return LUX_CURVE[-1][1]
    for (x0, y0), (x1, y1) in zip(LUX_CURVE, LUX_CURVE[1:]):
        if x0 <= effective <= x1:
            frac = (effective - x0) / (x1 - x0) if x1 != x0 else 0.0
            return y0 + frac * (y1 - y0)
    return 1.0  # Unreachable


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
# Activity light states — time-aware per-light states
# ---------------------------------------------------------------------------
# Structure: mode → time_period → per-light state dict
# Time periods: "day" (8-18), "evening" (18-21), "night" (21-8)
# Social mode is flat (no time keys) — routed through party sub-modes.

_LIGHT_OFF = {"on": False}

WINDDOWN_RAMP_MINUTES = 30  # Duration of evening → night fade (minutes)

# Auto-activate effects based on mode + time period.
# Each cell is either:
#   None           — no effect
#   {"effect": name, "lights": None}          — apply to all mapped lights
#   {"effect": name, "lights": ["1", "2"]}    — apply to specific v1 light IDs only
# Relax uses per-light targeting so the moss-shadow kitchen pendants
# (L3/L4) don't get masked by flame-colored candle/fire flicker.
# Social is static (no cycling) so it has no entry and _get_desired_effect
# returns None for it.
EFFECT_AUTO_MAP: dict[str, dict[str, dict[str, Any] | None]] = {
    "relax": {
        "day":        {"effect": "opal",   "lights": None},         # All lights
        "evening":    {"effect": "candle", "lights": ["1", "2"]},   # Living only
        "night":      {"effect": "fire",   "lights": ["1", "2"]},   # Living only
        "late_night": {"effect": "fire",   "lights": ["1", "2"]},   # Living only
    },
    "working":  {"day": None, "evening": None, "night": None},
    "gaming":   {"day": None, "evening": None, "night": None},
    "cooking":  {"day": None, "evening": None, "night": None},
    "watching": {
        "day":     None,
        "evening": {"effect": "glisten", "lights": None},
        "night":   {"effect": "glisten", "lights": None},
    },
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
    "cooking":  10,   # 1s — kitchen lights up the moment you tap the tile
    "idle":     20,   # 2s
    "away":     30,   # 3s
}


ACTIVITY_LIGHT_STATES: dict[str, dict[str, Any]] = {
    # ── Gaming ────────────────────────────────────────────────────────
    # Dim blue-violet ambient — screen sync on L2 is the star. Accents
    # stay very low so the screen color dominates the room. HSB only,
    # no auto-effects (per user feedback — glisten was removed). Kitchen
    # L3/L4 are PAIRED as violet accents. Brightness steps down progressively
    # after sunset so the screen still dominates at night.
    "gaming": {
        "day": {
            "1": {"on": True, "bri": 130, "hue": 47000, "sat": 220},   # Living room: blue-violet wash, bright enough for overcast
            "2": {"on": True, "bri": 240, "hue": 46920, "sat": 220},   # Desk fallback (screen-sync overrides, cap raised to 240)
            "3": {"on": True, "bri": 30,  "hue": 50000, "sat": 220},   # Kitchen front: violet accent
            "4": {"on": True, "bri": 30,  "hue": 50000, "sat": 220},   # Kitchen back: PAIRED with L3
        },
        "evening": {
            "1": {"on": True, "bri": 45,  "hue": 47000, "sat": 230},
            "2": {"on": True, "bri": 150, "hue": 46920, "sat": 230},   # Fallback (screen-sync caps to 150)
            "3": {"on": True, "bri": 22,  "hue": 50000, "sat": 230},
            "4": {"on": True, "bri": 22,  "hue": 50000, "sat": 230},   # PAIRED
        },
        "night": {
            "1": {"on": True, "bri": 40,  "hue": 47000, "sat": 240},
            "2": {"on": True, "bri": 140, "hue": 46920, "sat": 240},   # Fallback (screen-sync active during gaming)
            "3": {"on": True, "bri": 18,  "hue": 50000, "sat": 240},
            "4": {"on": True, "bri": 18,  "hue": 50000, "sat": 240},   # PAIRED
        },
    },
    # ── Working ───────────────────────────────────────────────────────
    # Clean ct-mode whites only. Per-light brightness gradient creates
    # depth, L2 (bedroom desk lamp) dominates. Evening shifts to 3000K
    # (ct≥333) to respect the strict post-sunset warmth cutoff. Night:
    # IES 1:3 monitor-ambient contrast — bright warm desk, minimal L1
    # ember, kitchen pair fully off so it doesn't distract from focus.
    # Kitchen L3/L4 are PAIRED in this functional mode.
    "working": {
        "day": {
            "1": {"on": True, "bri": 180, "ct": 233},    # Living room: bright neutral fill (4300K)
            "2": {"on": True, "bri": 254, "ct": 210},    # Desk lamp: max bright, cool (4800K)
            "3": {"on": True, "bri": 140, "ct": 250},    # Kitchen front: modest fill (4000K)
            "4": {"on": True, "bri": 140, "ct": 250},    # Kitchen back: PAIRED with L3
        },
        "evening": {
            "1": {"on": True, "bri": 100, "ct": 370},    # Living room: warm fill (2700K)
            "2": {"on": True, "bri": 180, "ct": 333},    # Desk: still functional, 3000K (cutoff)
            "3": {"on": True, "bri": 60,  "ct": 400},    # Kitchen front: low warm (2500K)
            "4": {"on": True, "bri": 60,  "ct": 400},    # Kitchen back: PAIRED with L3
        },
        "night": {
            "1": {"on": True, "bri": 60,  "ct": 440},    # Living room: warm ambient (2270K)
            "2": {"on": True, "bri": 130, "ct": 370},    # Desk: readable + 2700K (cutoff)
            "3": _LIGHT_OFF,                              # Kitchen front: off (behind user)
            "4": _LIGHT_OFF,                              # Kitchen back: PAIRED off
        },
    },
    # ── Watching ──────────────────────────────────────────────────────
    # Projector-friendly: warm throughout (no D65), dim. The projector is
    # on HDMI from the dev PC so L2 is a screen-sync target during watching
    # — the values below are the FALLBACK when sync isn't actively pushing
    # (idle desktop, just-entered mode, etc). Sync caps L2 at bri=80 so it
    # stays subtle. L2 sits on the wall opposite the projection surface,
    # so its light doesn't fall directly on the projected image. Kitchen
    # L3/L4 PAIRED (subtle in day, OFF evening+ to minimize wall bounce).
    "watching": {
        "day": {
            "1": {"on": True, "bri": 80,  "ct": 320},    # Living room: warm ambient (3100K)
            "2": {"on": True, "bri": 70,  "ct": 370},    # Bedroom: warm soft bias (2700K)
            "3": {"on": True, "bri": 30,  "ct": 333},    # Kitchen front: subtle (3000K)
            "4": {"on": True, "bri": 30,  "ct": 333},    # Kitchen back: PAIRED with L3
        },
        "evening": {
            "1": {"on": True, "bri": 65,  "ct": 400},    # Living room: warm, visible through hallway spill (2500K)
            "2": {"on": True, "bri": 40,  "ct": 400},    # Bedroom: warm bias dimmer
            "3": _LIGHT_OFF,                              # Kitchen off — minimize projection wash
            "4": _LIGHT_OFF,                              # Kitchen back: PAIRED off
        },
        "night": {
            "1": {"on": True, "bri": 45,  "ct": 454},    # Living room: candle-like amber, visible from bedroom (2200K)
            "2": {"on": True, "bri": 20,  "ct": 454},    # Bedroom: very warm, very dim
            "3": _LIGHT_OFF,
            "4": _LIGHT_OFF,                              # PAIRED off
        },
    },
    # ── Social ────────────────────────────────────────────────────────
    # "Velvet Speakeasy" — single static palette for small hangouts (drinks,
    # 2–4 guests, chill entertaining). Dusty rose statement on L1 is the
    # industry skin-flatter key; matched burnt-orange pendants provide room
    # glow. No time awareness, no sub-styles, no cycling effect — static
    # saturation does the work.
    "social": {
        "1": {"on": True, "bri": 140, "hue": 58500, "sat": 160},   # Dusty rose (statement)
        "2": {"on": True, "bri": 120, "hue": 6500,  "sat": 200},   # Cognac amber
        # L3/L4 tuned 2026-04-18 — bri dropped from 110 → 70 to respect the
        # clear-glass pendant rule (≤50 outside cooking, slight exception for
        # social to keep kitchen visible). Max saturation makes the deep
        # burnt-ember read as "lounge" instead of "hotel lobby."
        "3": {"on": True, "bri": 70, "hue": 4000, "sat": 254},   # Deep burnt ember (matched pair)
        "4": {"on": True, "bri": 70, "hue": 4000, "sat": 254},   # Deep burnt ember (matched pair)
    },
    # ── Relax ─────────────────────────────────────────────────────────
    # "Moss & Candlelight" biophilic forest-floor palette. Living-room
    # fabric-shaded lamps (L1/L2) run warm ember; kitchen pendants (L3/L4)
    # hold muted moss/sage so they read as foliage-shadow canopy — echoing
    # the plants and the apartment's olive/sage/teal accent palette rather
    # than drowning the room in uniform amber. Kitchen L3/L4 are FREE to
    # diverge (depth via per-light variance).
    # Candle/fire effects are scoped to L1/L2 in EFFECT_AUTO_MAP so the
    # pendants stay static.
    # Hue anchors: 4500=warm red, 6000–8000=amber/honey, 20000=olive/yellow-green.
    # Kitchen L3/L4 tuned 2026-04-19: shifted from pure green (hue 24000–25500,
    # sat 140–240 — read as bright mint through the clear-glass pendants despite
    # spec intent) to desaturated olive (hue 20000, sat 100) for a dusty-sage
    # read. Hue bulbs' native green LED peak lands at mint regardless of sat
    # or brightness; shifting warm (toward yellow-green) + low sat produces
    # the closest feasible "muted sage" on these fixtures.
    "relax": {
        "day": {
            "1": {"on": True, "bri": 95, "hue": 7500,  "sat": 200},   # Honey amber
            "2": {"on": True, "bri": 85, "hue": 8000,  "sat": 190},   # Warm honey
            "3": {"on": True, "bri": 30, "hue": 20000, "sat": 100},   # Dusty sage wash
            "4": {"on": True, "bri": 30, "hue": 20000, "sat": 100},   # Dusty sage wash
        },
        "evening": {
            "1": {"on": True, "bri": 70, "hue": 6000,  "sat": 230},   # Ember
            "2": {"on": True, "bri": 55, "hue": 6500,  "sat": 220},   # Warm ember
            "3": {"on": True, "bri": 15, "hue": 20000, "sat": 100},   # Muted olive
            "4": {"on": True, "bri": 15, "hue": 20000, "sat": 100},   # Muted olive
        },
        "night": {
            "1": {"on": True, "bri": 38, "hue": 5000,  "sat": 254},   # Deep ember
            "2": {"on": True, "bri": 28, "hue": 4500,  "sat": 254},   # Deeper ember
            "3": {"on": True, "bri": 8,  "hue": 20000, "sat": 100},   # Sage shadow
            "4": {"on": True, "bri": 8,  "hue": 20000, "sat": 100},   # Sage shadow
        },
        # "Moss & Ember" — post-11pm cave/den variant. Deeper ember on lamps,
        # barely-there sage in the kitchen. Only relax defines late_night;
        # other modes fall back to their night state.
        "late_night": {
            "1": {"on": True, "bri": 28, "hue": 3000,  "sat": 254},   # Deep ember red-orange
            "2": {"on": True, "bri": 22, "hue": 2500,  "sat": 254},   # Deeper ember
            "3": {"on": True, "bri": 5,  "hue": 20000, "sat": 100},   # Sage trace
            "4": {"on": True, "bri": 5,  "hue": 20000, "sat": 100},   # Sage trace
        },
    },
    # ── Cooking ───────────────────────────────────────────────────────
    # Kitchen pair at peak brightness with 3500K (ct=286) for accurate food
    # colors during the day. L1 provides warm ambient, L2 dim so it doesn't
    # compete. Evening shifts kitchen to 3000K (ct=333, strict cutoff). Night
    # at 2700K/bri=180 — still ~500 lux on the counter for safe prep without
    # blasting eyes at 11pm. Kitchen L3/L4 are PAIRED always.
    "cooking": {
        "day": {
            "1": {"on": True, "bri": 150, "ct": 320},   # Living room: warm ambient (3100K)
            "2": {"on": True, "bri": 80,  "ct": 333},   # Bedroom: dim warm (3000K)
            "3": {"on": True, "bri": 254, "ct": 286},   # Kitchen front: max, 3500K (food color)
            "4": {"on": True, "bri": 254, "ct": 286},   # Kitchen back: PAIRED with L3
        },
        "evening": {
            "1": {"on": True, "bri": 100, "ct": 370},   # (2700K)
            "2": {"on": True, "bri": 50,  "ct": 400},   # (2500K)
            "3": {"on": True, "bri": 230, "ct": 333},   # 3000K (strict cutoff)
            "4": {"on": True, "bri": 230, "ct": 333},   # PAIRED
        },
        "night": {
            "1": {"on": True, "bri": 60,  "ct": 420},   # (2380K)
            "2": {"on": True, "bri": 25,  "ct": 454},   # (2200K)
            "3": {"on": True, "bri": 180, "ct": 370},   # 2700K — warm but still usable
            "4": {"on": True, "bri": 180, "ct": 370},   # PAIRED
        },
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
        # late_night falls back to night for modes that don't define it
        if period == "late_night" and "late_night" not in entry:
            period = "night"
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
        self._sonos = None  # Set by main.py after construction — used by late-night rescue

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
        self._active_effect_name: Optional[str] = None  # Name of active Hue dynamic effect
        # Light IDs targeted by the active effect, or None when the effect runs
        # on all lights. Used by _reconcile_effect to detect target-set changes
        # (e.g., candle → fire on {"1","2"} vs opal on None) and reset cleanly.
        self._active_effect_lights: Optional[list[str]] = None

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

        # Confidence fusion (set by main.py after construction)
        self._confidence_fusion = None
        self._last_fusion_result: Optional[dict] = None

        # Camera service (set when camera is enabled via /api/camera/enable
        # or by main.py boot if camera_enabled setting is true). Used by
        # _apply_lux_multiplier to read the smoothed ambient lux reading.
        self._camera_service = None
        # Last applied lux multiplier — if the new multiplier is within
        # LUX_MULT_EPSILON of this, we keep using the old value so the final
        # state dict is identical and the per-light dedupe at _apply_state
        # naturally skips the bridge write.
        self._last_lux_multiplier: float = 1.0

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
        """Determine the current time period using the schedule config.

        Returns one of: "day", "evening", "night", "late_night". The
        late_night slot runs from schedule.late_night_start_hour until the
        next day's wake_hour — modes without a late_night state fall back
        to their night state via _resolve_activity_state.
        """
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
        if schedule.evening_start_hour <= hour < schedule.winddown_start_hour:
            return "evening"
        # late_night wraps across midnight: [late_night_start_hour, 24) ∪ [0, wake_hour)
        if hour >= schedule.late_night_start_hour or hour < schedule.wake_hour:
            return "late_night"
        return "night"

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

    def set_camera_service(self, camera) -> None:
        """Wire the camera service so ambient lux can modulate brightness.

        Called by main.py at boot (if the camera is already enabled) and by
        the /api/camera/enable route when the camera is toggled on.
        """
        self._camera_service = camera

    # Backwards-compat for tests / callers referencing the classmethod form
    _lux_to_multiplier = staticmethod(lux_to_multiplier)

    def _apply_lux_multiplier(
        self, state: dict[str, Any], mode: str
    ) -> dict[str, Any]:
        """Adjust per-light brightness by camera-derived ambient lux.

        Early-returns the state unchanged when:
          - mode is not in LUX_MODES (only working / relax adapt)
          - no camera service wired up, or it's disabled / paused
          - the camera has not been calibrated (auto-exposure defeats the signal)
          - the last lux reading is older than LUX_STALE_SECONDS
          - the computed multiplier change vs last is below LUX_MULT_EPSILON
            (in that case we reuse the last multiplier, so the result is the
            same state dict the per-light dedupe already skips)
        """
        if mode not in LUX_MODES:
            return state

        camera = self._camera_service
        if camera is None or not getattr(camera, "enabled", False):
            return state
        if getattr(camera, "_paused", False):
            return state

        ema = getattr(camera, "ema_lux", None)
        if ema is None:
            return state  # Not calibrated or no readings yet

        last_update = getattr(camera, "last_lux_update", None)
        if last_update is None:
            return state
        age = (datetime.now(timezone.utc) - last_update).total_seconds()
        if age > LUX_STALE_SECONDS:
            return state

        # Baseline shifts the curve so the user's calibrated "normal" room
        # sits at multiplier = 1.00. Legacy configs (no baseline_lux) fall
        # back to the raw LUX_CURVE anchor (90) for backwards compatibility.
        baseline = getattr(camera, "baseline_lux", None)
        raw_mult = lux_to_multiplier(float(ema), float(baseline) if baseline else 90.0)
        # Hysteresis: if we're within the epsilon of the last multiplier,
        # keep the old value so the state dict stays bit-identical and the
        # downstream per-light dedupe skips writes.
        if abs(raw_mult - self._last_lux_multiplier) < LUX_MULT_EPSILON:
            multiplier = self._last_lux_multiplier
        else:
            multiplier = raw_mult
            self._last_lux_multiplier = raw_mult

        if multiplier == 1.0:
            return state

        # Per-light dict vs flat state (mirrors _apply_brightness_multiplier)
        is_per_light = all(
            isinstance(v, dict) for v in state.values()
        ) and any(k in ("1", "2", "3", "4") for k in state.keys())

        if is_per_light:
            result: dict[str, Any] = {}
            for lid, ls in state.items():
                ls_copy = ls.copy()
                if ls_copy.get("on", True) and "bri" in ls_copy:
                    ls_copy["bri"] = max(1, min(254, int(ls_copy["bri"] * multiplier)))
                result[lid] = ls_copy
            return result

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

        # Report to confidence fusion BEFORE mode-change guards — fusion is a
        # voting system, every signal should be heard even when it loses the
        # mode-change vote. "ambient" (RMS) aliases to the audio_ml lane.
        fusion = getattr(self, "_confidence_fusion", None)
        if fusion:
            if source == "process":
                fusion.report_signal("process", mode, 1.0)
            elif source == "ambient":
                fusion.report_signal("audio_ml", mode, 0.7)
            else:
                fusion.report_signal(source, mode, 0.8)

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
        """Clear the manual override and return to automatic mode.

        Special case: if we were sleeping, don't re-apply anything. The fade
        already finished hours ago and lights are off. Re-applying a detected
        mode (working/idle with its time-based night rule, etc.) would blast
        bright lights on while the user is still asleep — exactly the
        "lights turn back on" bug.
        """
        old_effective = self._override_mode
        self._manual_override = False
        self._override_mode = None
        self._override_time = None

        self._clear_per_light_overrides()
        logger.info("Manual override cleared — returning to auto")

        if old_effective == "sleeping":
            # User is (probably) still asleep or just waking — they'll pick a
            # new mode on the dashboard. Leave lights off.
            await self._broadcast_mode()
            return

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
        logger.info(
            "Transit override cleared for lights %s — reverting to mode %s",
            cleared, self._current_mode,
        )
        # Re-apply the current mode's full light state. Dedup cache will no-op
        # on any lights that weren't in the transit set, so only the cleared
        # lights receive new Hue commands.
        await self._apply_mode(self._current_mode)

    # ------------------------------------------------------------------
    # Light state application
    # ------------------------------------------------------------------

    async def _reconcile_effect(
        self, desired: Optional[str | dict[str, Any]],
    ) -> None:
        """
        Transition from the currently-active v2 effect to the desired one.

        MUST be called AFTER the new light state / scene is on the bridge,
        so stopping the old effect doesn't pop brightness to 100%. The
        bridge will hold the last-set brightness target and return to it
        once the effect releases.

        `desired` accepts three shapes:
          - None:                 no effect should be active
          - str (e.g., "candle"): apply effect to all lights (legacy shape,
                                  used by weather-effect fallback and callers
                                  that don't need per-light targeting)
          - dict {"effect": name, "lights": list[str] | None}:
              explicit — `lights=None` means all mapped lights; a list scopes
              the effect to specific v1 light IDs (e.g., candle on living-room
              lamps while kitchen pendants stay static in relax mode).

        The same-effect short-circuit kicks in only when BOTH the effect name
        and the target light set match — repeated candle/glisten cycles with
        the same scope preserve the brightness base on the bridge. When
        `desired` is None we always call stop_effect_all (even if our tracker
        agrees none is running) to handle effects activated out-of-band by
        the scenes API, presence/winddown services, or left across a restart.

        A 0.5s guard separates stop and start so the two commands don't race.
        """
        if not self._hue_v2 or not self._hue_v2.connected:
            return

        # Normalize desired to (effect_name, target_lights)
        if desired is None:
            desired_effect: Optional[str] = None
            desired_lights: Optional[list[str]] = None
        elif isinstance(desired, str):
            desired_effect = desired
            desired_lights = None
        else:
            desired_effect = desired.get("effect")
            desired_lights = desired.get("lights")

        # Same-effect + same-target short-circuit
        if (
            desired_effect
            and desired_effect == self._active_effect_name
            and desired_lights == self._active_effect_lights
        ):
            return

        # Clear current effect — always call stop_effect_all to handle
        # out-of-band activations cleanly
        await self._hue_v2.stop_effect_all()
        self._active_effect_name = None
        self._active_effect_lights = None

        if not desired_effect:
            return

        await asyncio.sleep(0.5)
        if desired_lights is None:
            await self._hue_v2.set_effect_all(desired_effect)
        else:
            await asyncio.gather(*(
                self._hue_v2.set_effect(lid, desired_effect)
                for lid in desired_lights
            ))
        self._active_effect_name = desired_effect
        self._active_effect_lights = desired_lights

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
        # IMPORTANT: don't stop the current effect yet. Stopping an active
        # effect before the new brightness target is on the bridge causes the
        # bridge to reset brightness to 100%, producing the visible "pop" on
        # mode change. We reconcile effects at the END of this function, after
        # _apply_state (or scene activation) has established the new target.
        desired_effect = self._get_desired_effect(mode)

        # Clear dedup cache so the new state is always applied — effects and
        # external apps change bridge state independently, making the cache stale.
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
            if self._active_effect_name and self._hue_v2 and self._hue_v2.connected:
                await self._hue_v2.stop_effect_all()
                self._active_effect_name = None
                self._active_effect_lights = None

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

    def _get_desired_effect(
        self, mode: str,
    ) -> Optional[str | dict[str, Any]]:
        """Determine what dynamic effect should be active for a mode.

        Returns either:
          - None                                   (no effect)
          - str                                    (weather fallback, all lights)
          - {"effect": name, "lights": list|None}  (mode-specific, per-light scope)

        Sleeping and social manage their own effects (sleeping = none,
        social = none per Velvet Speakeasy static palette).
        """
        if mode in ("sleeping", "social"):
            return None
        period = self._get_time_period()
        effect_map = EFFECT_AUTO_MAP.get(mode, {})
        auto_effect = effect_map.get(period)
        # late_night falls back to night for modes that don't define it
        if auto_effect is None and period == "late_night":
            auto_effect = effect_map.get("night")
        if auto_effect:
            return auto_effect
        # Weather-driven fallback: bare string → applied to all lights
        weather_effect = self._get_weather_effect()
        if weather_effect and (
            period in ("evening", "night", "late_night")
            or weather_effect == "sparkle"
        ):
            return weather_effect
        return None

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
                        await self.clear_override()

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
                # gaming/watching/social/sleeping are respected, and music
                # playback counts as intentional activity.
                if (
                    not self._manual_override
                    and self._get_time_period() == "late_night"
                    and self._current_mode in ("working", "idle")
                    and not await self._sonos_is_playing()
                ):
                    logger.info(
                        "Late-night rescue: switching to relax from %s",
                        self._current_mode,
                    )
                    await self.set_manual_override("relax")

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

                # ML behavioral predictor — runs every cycle so it stays a fresh
                # voter in fusion. Acting on its prediction is still gated to
                # idle/away below (the predictor is most useful when there's no
                # confident signal driving the current mode).
                predictor = getattr(self, "_behavioral_predictor", None)
                ml_logger = getattr(self, "_ml_logger", None)
                prediction = None
                if predictor and not self._manual_override:
                    prediction = await predictor.predict(
                        current_mode=self._current_mode,
                    )
                    if prediction:
                        fusion = getattr(self, "_confidence_fusion", None)
                        if fusion:
                            fusion.report_signal(
                                "behavioral",
                                prediction["predicted_mode"],
                                prediction["confidence"],
                            )
                if (
                    prediction
                    and not self._manual_override
                    and self._current_mode in ("idle", "away")
                ):
                    if not prediction.get("shadow"):
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
                        # with 80%+ agreement
                        if (
                            fusion_result.get("can_override")
                            and not self._manual_override
                            and self._current_mode not in ("idle", "away")
                            and fm != self._current_mode
                        ):
                            logger.info(
                                "Fusion override: %s -> %s "
                                "(%.0f%% confidence, %.0f%% agreement)",
                                self._current_mode, fm, fc * 100,
                                fusion_result["agreement"] * 100,
                            )
                            await self.set_manual_override(fm)
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
                            await self.set_manual_override(fm)
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
