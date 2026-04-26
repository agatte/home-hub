"""
Per-light target state calculator — pure functions over lookup tables.

Given a mode, time period, schedule, environment readings (lux,
zone, posture, weather), this module produces the per-light target
dict that ``AutomationEngine`` then dedupes, filters for overrides,
and ships to the Hue bridge.

Extracted from ``automation_engine.py`` so the engine itself can stay
focused on orchestration (mode resolution, override timeouts, fusion
voting, callback dispatch, effect lifecycle, bridge I/O). Every
function here is pure — no ``self``, no I/O, no service objects.
The engine reads state off services and threads primitives in.

The four most-grepped constants (``ACTIVITY_LIGHT_STATES``,
``EFFECT_AUTO_MAP``, ``DEFAULT_MODE_BRIGHTNESS``,
``MODE_TRANSITION_TIME``) are re-exported from
``backend.services.automation_engine`` for back-compat with callers
that imported them from there.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

# Indianapolis timezone — Indiana doesn't follow standard Eastern DST.
# Re-declared here (rather than imported from automation_engine) so
# this module has no engine dependency.
TZ = ZoneInfo("America/Indiana/Indianapolis")


# ---------------------------------------------------------------------------
# Mode brightness multipliers
# ---------------------------------------------------------------------------

# Default per-mode brightness multiplier (1.0 = unchanged). Settings UI
# exposes these as 0.3..1.5 sliders persisted in mode_brightness_config.
DEFAULT_MODE_BRIGHTNESS: dict[str, float] = {
    "gaming": 1.0,
    "working": 1.0,
    "watching": 1.0,
    "relax": 1.0,
    "cooking": 1.0,
    "social": 1.0,
}


# ---------------------------------------------------------------------------
# Mode transition speeds (deciseconds: 10 = 1 second)
# ---------------------------------------------------------------------------

MODE_TRANSITION_TIME: dict[str, int] = {
    "working":  20,   # 2s smooth
    "gaming":    5,   # 0.5s snappy
    "watching": 30,   # 3s cinematic fade
    "relax":    50,   # 5s gentle
    "social":   10,   # 1s
    "sleeping": 50,   # 5s gradual
    "cooking":  10,   # 1s — kitchen lights up the moment you tap the tile
    "idle":     20,   # 2s
    "away":     30,   # 3s
}


# ---------------------------------------------------------------------------
# Ambient lux adaptive brightness
# ---------------------------------------------------------------------------

# Modes where ambient adaptation is desirable. Functional modes
# (gaming, watching, cooking) bypass so spatial design stays predictable.
LUX_MODES = frozenset(("working", "relax"))

# Piecewise-linear curve mapping camera-derived ambient brightness
# (gray.mean, 0–255) to a brightness multiplier. Dark rooms (low lux)
# lift brightness; bright rooms dim.
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


# ---------------------------------------------------------------------------
# Time-period rollover for fades + activity_light_states lookup
# ---------------------------------------------------------------------------

WINDDOWN_RAMP_MINUTES = 30  # Duration of evening → night fade (minutes)


# ---------------------------------------------------------------------------
# Activity light states — time-aware per-light states
# ---------------------------------------------------------------------------
# Structure: mode → time_period → per-light state dict
# Time periods: "day", "evening", "night", "late_night"
# Social mode is flat (no time keys) — routed through party sub-modes.

_LIGHT_OFF = {"on": False}

# Auto-activate effects based on mode + time period.
# Each cell is either:
#   None           — no effect
#   {"effect": name, "lights": None}          — apply to all mapped lights
#   {"effect": name, "lights": ["1", "2"]}    — apply to specific v1 light IDs only
# Relax uses per-light targeting so the moss-shadow kitchen pendants
# (L3/L4) don't get masked by flame-colored candle/fire flicker.
# Social is static (no cycling) so it has no entry and the engine's
# _get_desired_effect returns None for it.
EFFECT_AUTO_MAP: dict[str, dict[str, dict[str, Any] | None]] = {
    "relax": {
        "day":        {"effect": "opal",   "lights": None},
        "evening":    {"effect": "candle", "lights": ["1", "2"]},
        "night":      {"effect": "fire",   "lights": ["1", "2"]},
        "late_night": {"effect": "fire",   "lights": ["1", "2"]},
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


ACTIVITY_LIGHT_STATES: dict[str, dict[str, Any]] = {
    # ── Gaming ────────────────────────────────────────────────────────
    "gaming": {
        "day": {
            "1": {"on": True, "bri": 130, "hue": 47000, "sat": 220},
            "2": {"on": True, "bri": 240, "hue": 46920, "sat": 220},
            "3": {"on": True, "bri": 30,  "hue": 50000, "sat": 220},
            "4": {"on": True, "bri": 30,  "hue": 50000, "sat": 220},
        },
        "evening": {
            "1": {"on": True, "bri": 45,  "hue": 47000, "sat": 230},
            "2": {"on": True, "bri": 150, "hue": 46920, "sat": 230},
            "3": {"on": True, "bri": 22,  "hue": 50000, "sat": 230},
            "4": {"on": True, "bri": 22,  "hue": 50000, "sat": 230},
        },
        "night": {
            "1": {"on": True, "bri": 40,  "hue": 47000, "sat": 240},
            "2": {"on": True, "bri": 140, "hue": 46920, "sat": 240},
            "3": {"on": True, "bri": 18,  "hue": 50000, "sat": 240},
            "4": {"on": True, "bri": 18,  "hue": 50000, "sat": 240},
        },
    },
    # ── Working ───────────────────────────────────────────────────────
    "working": {
        "day": {
            "1": {"on": True, "bri": 180, "ct": 233},
            "2": {"on": True, "bri": 254, "ct": 210},
            "3": {"on": True, "bri": 140, "ct": 250},
            "4": {"on": True, "bri": 140, "ct": 250},
        },
        "evening": {
            "1": {"on": True, "bri": 100, "ct": 370},
            "2": {"on": True, "bri": 180, "ct": 333},
            "3": {"on": True, "bri": 60,  "ct": 400},
            "4": {"on": True, "bri": 60,  "ct": 400},
        },
        "night": {
            "1": {"on": True, "bri": 60,  "ct": 440},
            "2": {"on": True, "bri": 130, "ct": 370},
            "3": _LIGHT_OFF,
            "4": _LIGHT_OFF,
        },
    },
    # ── Watching ──────────────────────────────────────────────────────
    "watching": {
        "day": {
            "1": {"on": True, "bri": 80,  "ct": 320},
            "2": {"on": True, "bri": 70,  "ct": 370},
            "3": {"on": True, "bri": 30,  "ct": 333},
            "4": {"on": True, "bri": 30,  "ct": 333},
        },
        "evening": {
            "1": {"on": True, "bri": 65,  "ct": 400},
            "2": {"on": True, "bri": 40,  "ct": 400},
            "3": _LIGHT_OFF,
            "4": _LIGHT_OFF,
        },
        "night": {
            "1": {"on": True, "bri": 45,  "ct": 454},
            "2": {"on": True, "bri": 20,  "ct": 454},
            "3": _LIGHT_OFF,
            "4": _LIGHT_OFF,
        },
    },
    # ── Social ────────────────────────────────────────────────────────
    "social": {
        "1": {"on": True, "bri": 140, "hue": 58500, "sat": 160},
        "2": {"on": True, "bri": 120, "hue": 6500,  "sat": 200},
        "3": {"on": True, "bri": 70,  "hue": 4000,  "sat": 254},
        "4": {"on": True, "bri": 70,  "hue": 4000,  "sat": 254},
    },
    # ── Relax ─────────────────────────────────────────────────────────
    "relax": {
        "day": {
            "1": {"on": True, "bri": 95, "hue": 7500,  "sat": 200},
            "2": {"on": True, "bri": 85, "hue": 8000,  "sat": 190},
            "3": {"on": True, "bri": 30, "hue": 20000, "sat": 100},
            "4": {"on": True, "bri": 30, "hue": 20000, "sat": 100},
        },
        "evening": {
            "1": {"on": True, "bri": 70, "hue": 6000,  "sat": 230},
            "2": {"on": True, "bri": 55, "hue": 6500,  "sat": 220},
            "3": {"on": True, "bri": 15, "hue": 20000, "sat": 100},
            "4": {"on": True, "bri": 15, "hue": 20000, "sat": 100},
        },
        "night": {
            "1": {"on": True, "bri": 38, "hue": 5000,  "sat": 254},
            "2": {"on": True, "bri": 28, "hue": 4500,  "sat": 254},
            "3": {"on": True, "bri": 8,  "hue": 20000, "sat": 100},
            "4": {"on": True, "bri": 8,  "hue": 20000, "sat": 100},
        },
        "late_night": {
            "1": {"on": True, "bri": 28, "hue": 3000,  "sat": 254},
            "2": {"on": True, "bri": 22, "hue": 2500,  "sat": 254},
            "3": {"on": True, "bri": 5,  "hue": 20000, "sat": 100},
            "4": {"on": True, "bri": 5,  "hue": 20000, "sat": 100},
        },
    },
    # ── Cooking ───────────────────────────────────────────────────────
    "cooking": {
        "day": {
            "1": {"on": True, "bri": 150, "ct": 320},
            "2": {"on": True, "bri": 80,  "ct": 333},
            "3": {"on": True, "bri": 254, "ct": 286},
            "4": {"on": True, "bri": 254, "ct": 286},
        },
        "evening": {
            "1": {"on": True, "bri": 100, "ct": 370},
            "2": {"on": True, "bri": 50,  "ct": 400},
            "3": {"on": True, "bri": 230, "ct": 333},
            "4": {"on": True, "bri": 230, "ct": 333},
        },
        "night": {
            "1": {"on": True, "bri": 60,  "ct": 420},
            "2": {"on": True, "bri": 25,  "ct": 454},
            "3": {"on": True, "bri": 180, "ct": 370},
            "4": {"on": True, "bri": 180, "ct": 370},
        },
    },
}


# ---------------------------------------------------------------------------
# Bed+reclined zone-posture overlay tunables
# ---------------------------------------------------------------------------

# Watching + zone=bed + posture=reclined target brightness per period.
# LOWER than the baseline watching state — projector + lying back means
# bright lamps compete with the screen and hit eyes more directly than
# when sitting upright. Day is unset (napping in daylight needs no rule).
#
# L1-night is the user-facing knob (settings page slider); evening and
# late_night L1 scale proportionally to the ratios in the original
# tuning. L2 is held at these tuned values — sits out of line of sight
# when reclined and is already near-off.
BED_RECLINED_L1_NIGHT_DEFAULT = 25
BED_RECLINED_L2_WATCHING_BRI = {
    "evening":    18,
    "night":      8,
    "late_night": 5,
}
BED_RECLINED_L1_RATIO = {
    "evening":    1.8,   # default 45 when night=25
    "night":      1.0,
    "late_night": 0.6,   # default 15 when night=25
}

# Maximum age (in seconds) for a committed zone/posture to be honored
# by the overlay. Older than this and the value is treated as missing —
# mirrors ConfidenceFusion's SOURCE_STALE_SECONDS so stale camera state
# can't drive the lights when the user has been gone for a while.
ZONE_POSTURE_FRESHNESS_SECONDS = 300


# ---------------------------------------------------------------------------
# Pure helpers — used by engine and exposed for tests
# ---------------------------------------------------------------------------


def morning_ramp(
    minute_in_window: int,
    window_minutes: int = 120,
) -> dict[str, Any]:
    """Calculate gradual morning light ramp from warm/dim to daylight/bright.

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


def lerp_light_state(
    state_a: dict[str, Any],
    state_b: dict[str, Any],
    progress: float,
) -> dict[str, Any]:
    """Interpolate between two light states.

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


def get_time_period_static() -> str:
    """Determine the current time period using fixed defaults.

    Used as a fallback when no schedule config is available
    (e.g. by ``resolve_activity_state`` when called without
    a precomputed period).
    """
    hour = datetime.now(tz=TZ).hour
    if 8 <= hour < 18:
        return "day"
    elif 18 <= hour < 21:
        return "evening"
    else:
        return "night"


def get_time_period(schedule, now: Optional[datetime] = None) -> str:
    """Determine the current time period using the schedule config.

    Returns one of: "day", "evening", "night", "late_night". The
    late_night slot runs from schedule.late_night_start_hour until
    the next day's wake_hour — modes without a late_night state
    fall back to night via ``resolve_activity_state``.

    Args:
        schedule: A ``ScheduleConfig`` (with .weekday and .weekend
            ``DaySchedule`` children).
        now: Override for the current time (used by tests). Defaults
            to ``datetime.now(tz=TZ)``.

    The morning ramp window (ramp_start_hour..ramp_start_hour+duration)
    counts as "day" — the ramp's brightness curve comes from
    ``_build_time_rules``' morning_ramp handling, not this bucket; the
    user is awake and active, so day-mode states are the right baseline.
    """
    if now is None:
        now = datetime.now(tz=TZ)
    hour = now.hour
    day = schedule.weekday if now.weekday() < 5 else schedule.weekend

    if day.ramp_start_hour <= hour < day.evening_start_hour:
        return "day"
    if day.evening_start_hour <= hour < day.winddown_start_hour:
        return "evening"
    # late_night wraps midnight: [late_night_start_hour, 24) ∪ [0, wake_hour)
    if hour >= day.late_night_start_hour or hour < day.wake_hour:
        return "late_night"
    return "night"


def resolve_activity_state(
    mode: str,
    time_period: Optional[str] = None,
) -> dict[str, Any]:
    """Look up the time-appropriate light state for an activity mode.

    Time-aware entries have "day"/"evening"/"night" (and optionally
    "late_night") keys. Flat entries (social) are returned as-is.

    Args:
        mode: Activity mode name.
        time_period: Override time period. Uses the static default
            when None.
    """
    entry = ACTIVITY_LIGHT_STATES.get(mode)
    if entry is None:
        return {}
    if "day" in entry:
        period = time_period or get_time_period_static()
        # late_night falls back to night for modes that don't define it
        if period == "late_night" and "late_night" not in entry:
            period = "night"
        return entry.get(period, entry.get("night", {}))
    return entry


# ---------------------------------------------------------------------------
# Per-light state transformations — pure
# ---------------------------------------------------------------------------


def _is_per_light_dict(state: dict[str, Any]) -> bool:
    """True if ``state`` is the per-light shape (keys are light IDs)."""
    return all(isinstance(v, dict) for v in state.values()) and any(
        k in ("1", "2", "3", "4") for k in state.keys()
    )


def apply_brightness_multiplier(
    state: dict[str, Any],
    mode: str,
    multipliers: dict[str, float],
) -> dict[str, Any]:
    """Apply per-mode brightness multiplier to a light state.

    Pure: returns a new state dict, never mutates the input.
    """
    multiplier = multipliers.get(mode, 1.0)
    if multiplier == 1.0:
        return state

    if _is_per_light_dict(state):
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


def apply_lux_multiplier(
    state: dict[str, Any],
    mode: str,
    lux_reading: Optional[float],
    last_multiplier: float,
    baseline_lux: Optional[float] = None,
) -> tuple[dict[str, Any], float]:
    """Adjust per-light brightness by camera-derived ambient lux.

    Pure: caller owns the hysteresis state and gets the new value
    back. ``last_multiplier`` is what was applied last tick; this
    function returns the multiplier that should be remembered for
    next tick (which may be the same ``last_multiplier`` if the new
    raw reading is within ``LUX_MULT_EPSILON``, or a fresh value).

    Returns ``(new_state, new_last_multiplier)``. Engine stores the
    second element back into ``self._last_lux_multiplier``.

    No-op (returns state unchanged + ``last_multiplier`` unchanged) when:
      - mode is not in LUX_MODES (only working / relax adapt)
      - ``lux_reading`` is None (camera not wired, paused, stale, etc;
        engine resolves freshness before calling)
    """
    if mode not in LUX_MODES or lux_reading is None:
        return state, last_multiplier

    raw_mult = lux_to_multiplier(
        float(lux_reading),
        float(baseline_lux) if baseline_lux else 90.0,
    )
    # Hysteresis: stay on the last multiplier if the new raw value is
    # within epsilon — keeps the resulting state dict bit-identical so
    # the per-light dedupe downstream skips bridge writes.
    if abs(raw_mult - last_multiplier) < LUX_MULT_EPSILON:
        multiplier = last_multiplier
    else:
        multiplier = raw_mult

    if multiplier == 1.0:
        return state, multiplier

    if _is_per_light_dict(state):
        result: dict[str, Any] = {}
        for lid, ls in state.items():
            ls_copy = ls.copy()
            if ls_copy.get("on", True) and "bri" in ls_copy:
                ls_copy["bri"] = max(1, min(254, int(ls_copy["bri"] * multiplier)))
            result[lid] = ls_copy
        return result, multiplier

    result = state.copy()
    if result.get("on", True) and "bri" in result:
        result["bri"] = max(1, min(254, int(result["bri"] * multiplier)))
    return result, multiplier


def apply_zone_overlay(
    state: dict[str, Any],
    mode: str,
    period: str,
    zone: Optional[str],
    posture: Optional[str],
    bed_reclined_l1_night: int = BED_RECLINED_L1_NIGHT_DEFAULT,
) -> dict[str, Any]:
    """Zone- and posture-aware per-light adjustments as the final overlay.

    Two branches:

    1. ``zone=desk`` + watching: LIFT L2 above the projector-safe dim —
       watching at the desk is YouTube / a monitor stream and the
       projector is off, so the default dim L2 reads as too dark.
    2. ``zone=bed + posture=reclined`` (any mode except sleeping):
       LOWER L1 and L2 below the baseline. ``bed + reclined`` is a
       physical fact about the user's body, not a mode label — when
       you're lying down with the projector on, bright bedside lamps
       compete with the screen and hit eyes directly regardless of
       what the activity detector thinks you're doing.

    Only ever moves brightness in one direction per branch (lift-only
    for desk, lower-only for reclined) so a learned override stays
    preserved if it already moved the same way.

    ``zone`` and ``posture`` are passed in pre-resolved — the engine
    handles freshness-gating via the camera service. ``None`` for
    either means "no fresh reading" and the overlay is a no-op.
    """
    is_per_light = all(isinstance(v, dict) for v in state.values()) and "2" in state
    if not is_per_light:
        return state

    # Branch 1 — watching at desk: lift L2.
    if zone == "desk" and mode == "watching":
        zone_bri_by_period = {
            "day": 160,
            "evening": 110,
            "night": 70,
            "late_night": 50,
        }
        target_bri = zone_bri_by_period.get(period)
        if target_bri is None:
            return state
        current_bri = int(state["2"].get("bri", 0))
        if current_bri >= target_bri:
            return state
        new_state = {lid: dict(ls) for lid, ls in state.items()}
        new_state["2"]["bri"] = target_bri
        return new_state

    # Branch 2 — reclined in bed: lower L1 and L2. Mode-agnostic
    # except for sleeping (already at ember-dim, no-op anyway).
    if zone == "bed" and posture == "reclined" and mode != "sleeping":
        ratio = BED_RECLINED_L1_RATIO.get(period)
        l2_target = BED_RECLINED_L2_WATCHING_BRI.get(period)
        if ratio is None or l2_target is None:
            return state
        l1_target = max(1, min(254, int(bed_reclined_l1_night * ratio)))
        targets = {"1": l1_target, "2": l2_target}
        new_state = {lid: dict(ls) for lid, ls in state.items()}
        changed = False
        for light_id, target in targets.items():
            if light_id not in new_state:
                continue
            current = int(new_state[light_id].get("bri", 0))
            if current <= target:
                continue  # Already at or below target — don't raise.
            new_state[light_id]["bri"] = target
            changed = True
        if not changed:
            return state
        return new_state

    return state


def is_zone_posture_freshness_ok(
    committed_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> bool:
    """True if a zone/posture commit timestamp is fresh enough to honor.

    Matches the staleness threshold ConfidenceFusion uses, so a stale
    camera commit (e.g. from before the last sleep cycle) can't leak
    into the lighting decision.

    A ``None`` ``committed_at`` returns False (no fresh commit).
    """
    if committed_at is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    age = (now - committed_at).total_seconds()
    return age <= ZONE_POSTURE_FRESHNESS_SECONDS


# ---------------------------------------------------------------------------
# Weather adjustment — pure (caller resolves the condition string)
# ---------------------------------------------------------------------------


def classify_weather(desc: str, weather: dict[str, Any]) -> Optional[str]:
    """Map a weather description string + payload to a condition category.

    Returns one of "thunderstorm", "rain", "snow", "clouds",
    "golden_hour", or None. The golden-hour case reads the sunset
    timestamp from ``weather`` to decide if we're within the ±30
    minute window.
    """
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
            sunset_utc = datetime.fromtimestamp(sunset_ts, tz=timezone.utc)
            sunset_local = sunset_utc.astimezone(TZ)
            minutes_to_sunset = (sunset_local - now).total_seconds() / 60
            if -30 <= minutes_to_sunset <= 30:
                return "golden_hour"
    return None


def adjust_single_light(
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
        adj["bri"] = max(1, adj.get("bri", 200) - 30)
        if uses_ct:
            adj["ct"] = max(153, adj["ct"] - 80)
        else:
            adj["hue"] = min(65535, adj.get("hue", 8000) + 12000)
            adj["sat"] = min(254, adj.get("sat", 100) + 60)

    elif condition == "rain":
        adj["bri"] = max(1, adj.get("bri", 200) - 15)
        if uses_ct:
            adj["ct"] = max(153, adj["ct"] - 50)
        else:
            adj["hue"] = max(0, adj.get("hue", 8000) + 4000)
            adj["sat"] = min(254, adj.get("sat", 100) + 30)

    elif condition == "snow":
        adj["bri"] = min(254, adj.get("bri", 200) + 25)
        if uses_ct:
            adj["ct"] = max(153, adj["ct"] - 60)

    elif condition == "clouds":
        adj["bri"] = max(1, int(adj.get("bri", 200) * 0.85))
        if uses_ct:
            adj["ct"] = min(500, adj["ct"] + 25)

    elif condition == "golden_hour":
        if uses_ct:
            adj["ct"] = min(500, adj["ct"] + 50)
        else:
            adj["hue"] = min(65535, adj.get("hue", 8000) + 3000)
            adj["sat"] = min(254, adj.get("sat", 100) + 40)

    return adj


def apply_weather_adjust(
    state: dict[str, Any],
    condition: Optional[str],
) -> dict[str, Any]:
    """Apply subtle weather-based adjustments to light states.

    Caller resolves the condition (via ``classify_weather`` or by
    pulling it off the cached weather payload). ``None`` means
    "no condition matched" — function is a no-op.

    Works with both flat and per-light formats. Lights that are off
    pass through untouched.
    """
    if condition is None:
        return state

    if _is_per_light_dict(state):
        return {
            lid: adjust_single_light(ls, condition) if ls.get("on", True) else ls
            for lid, ls in state.items()
        }
    return adjust_single_light(state, condition)
