"""
Per-mode Sonos volume policy — pure function, no I/O.

Computes a target Sonos volume + fade shape for a given mode + time-of-day,
factoring in DND and a "sleeping always silences" rule.

Pattern mirrors ``celebration_volume_policy.py``: pure module that the
``ModeVolumeService`` actuator imports, gathers context from injected
``AutomationEngine`` + ``SonosService``, and feeds in.

The mode-change callback registered in ``bootstrap`` calls
``compute_mode_volume(...)``; if the returned decision is not ``skip``,
the actuator drives ``sonos.ramp_volume()``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("home_hub.mode_volume")

# Default per-mode targets. Each mode maps to {day, evening, night, fade_duration_s}.
# ``idle`` is intentionally absent — no curve, leaves Sonos at whatever
# the previous mode left it at. ``late_night`` falls back to ``night``.
#
# Defaults are conservative starting points; the settings-page sliders persist
# user overrides into ``app_settings["mode_volume_curves"]``.
MODE_VOLUME_DEFAULTS: dict[str, dict[str, int]] = {
    "gaming":   {"day": 25, "evening": 22, "night": 18, "fade_duration_s": 5},
    "working":  {"day": 12, "evening": 12, "night": 10, "fade_duration_s": 5},
    "watching": {"day": 22, "evening": 22, "night": 18, "fade_duration_s": 5},
    "relax":    {"day": 18, "evening": 16, "night": 14, "fade_duration_s": 8},
    "social":   {"day": 30, "evening": 30, "night": 25, "fade_duration_s": 4},
    "cooking":  {"day": 25, "evening": 22, "night": 20, "fade_duration_s": 4},
    "sleeping": {"day":  0, "evening":  0, "night":  0, "fade_duration_s": 3},
    "gameday":  {"day": 35, "evening": 35, "night": 30, "fade_duration_s": 4},
}

# Per-step interval defaults. A 5s fade across 5 steps yields ~1s/step writes —
# imperceptible drift to the listener.
_DEFAULT_STEP_INTERVAL_S = 1.0
_MIN_STEPS = 1
_MAX_STEPS = 30


@dataclass(frozen=True)
class VolumeDecision:
    """Result of ``compute_mode_volume``.

    Attributes:
        target: Destination Sonos volume in [0, 100].
        fade_steps: Number of intermediate writes the actuator should make.
        fade_interval: Seconds between writes (passed to ``sonos.ramp_volume``).
        skip: When True, the actuator must not touch Sonos volume.
        reason: Diagnostic string surfaced to logs/journal. Always populated.
    """
    target: int
    fade_steps: int
    fade_interval: float
    skip: bool
    reason: str


def compute_mode_volume(
    mode: str,
    *,
    time_period: str,
    dnd: bool,
    current_volume: int,
    config: Optional[dict[str, dict[str, int]]] = None,
) -> VolumeDecision:
    """Compute the target Sonos volume + fade for a mode change.

    Args:
        mode: The new mode the engine just transitioned into.
        time_period: One of ``day``/``evening``/``night``/``late_night``.
            ``late_night`` resolves to the same target as ``night``.
        dnd: True when DND is active. Suppresses everything except sleeping.
        current_volume: Current Sonos volume (0-100). Used to short-circuit
            no-op ramps.
        config: Optional per-mode override dict. Same shape as
            ``MODE_VOLUME_DEFAULTS``. Missing keys fall through to defaults.

    Returns:
        ``VolumeDecision``. Caller checks ``.skip`` before acting.

    Skip rules (in order):
      1. ``mode == "sleeping"`` → target=0, fade, never skipped (silence wins).
      2. ``mode`` not in defaults+config → skip ``no_curve`` (idle, unknowns).
      3. ``dnd`` active → skip ``dnd``.
      4. target equals current_volume → skip ``already_at_target``.
    """
    # Sleeping always silences, even with DND on (DND on top of sleep is fine —
    # both want quiet). This branch comes first so the silence wins.
    if mode == "sleeping":
        # _resolve_curve("sleeping", config) is never None — sleeping is in defaults.
        sleeping_curve = _resolve_curve("sleeping", config) or MODE_VOLUME_DEFAULTS["sleeping"]
        target = 0  # forced; defaults already 0 but defensive
        fade_steps, fade_interval = _shape(sleeping_curve["fade_duration_s"])
        if target == current_volume:
            return VolumeDecision(target, fade_steps, fade_interval, True, "already_at_target")
        return VolumeDecision(target, fade_steps, fade_interval, False, "sleeping_force_silence")

    curve = _resolve_curve(mode, config)
    if curve is None:
        # Unknown mode or one with no curve (idle). Leave Sonos alone.
        return VolumeDecision(current_volume, 0, 0.0, True, "no_curve")

    if dnd:
        return VolumeDecision(current_volume, 0, 0.0, True, "dnd")

    target = _resolve_target(curve, time_period)
    fade_steps, fade_interval = _shape(curve["fade_duration_s"])

    if target == current_volume:
        return VolumeDecision(target, fade_steps, fade_interval, True, "already_at_target")

    return VolumeDecision(target, fade_steps, fade_interval, False, f"fade_to_{mode}_{time_period}")


def _resolve_curve(
    mode: str,
    config: Optional[dict[str, dict[str, int]]],
) -> Optional[dict[str, int]]:
    """Merge persisted overrides over defaults; return None if mode unknown."""
    default = MODE_VOLUME_DEFAULTS.get(mode)
    if default is None and (config is None or mode not in config):
        return None
    merged = dict(default or {})
    if config and mode in config:
        merged.update(config[mode])
    return merged


def _resolve_target(curve: dict[str, int], time_period: str) -> int:
    """Pick the right bucket from a curve. ``late_night`` aliases to ``night``."""
    key = "night" if time_period == "late_night" else time_period
    if key not in ("day", "evening", "night"):
        key = "day"  # defensive fallback for unexpected periods
    raw = int(curve.get(key, 0))
    return max(0, min(100, raw))


def _shape(fade_duration_s: int) -> tuple[int, float]:
    """Convert a fade duration into (steps, interval).

    Strategy: pick ~1s per step so writes feel imperceptible.
    Clamped to [_MIN_STEPS, _MAX_STEPS] for safety.
    """
    duration = max(1, int(fade_duration_s))
    steps = max(_MIN_STEPS, min(_MAX_STEPS, round(duration / _DEFAULT_STEP_INTERVAL_S)))
    interval = duration / steps if steps else _DEFAULT_STEP_INTERVAL_S
    return steps, interval
