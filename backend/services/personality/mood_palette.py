"""Mood-vector → HSB (Hue color space) mapping.

Uses Russell's circumplex model placed onto a 4-corner palette:

       arousal +1
            ↑
    sad-     │     stressed/
    excited  │     angry
    cyan ────┼──── red
            (0,0)─→ valence +1
    deep     │     content/
    blue     │     happy
    blue ────┼──── warm-gold
            ↓
       arousal -1

Brightness is modulated by focus (high focus = brighter, more saturated).
At very low confidence the palette collapses to a neutral warm white so
the lamp doesn't strobe on noisy readings.

Returns (hue, sat, bri) in Hue API native units:
    hue ∈ [0, 65535], sat ∈ [0, 254], bri ∈ [0, 254].
"""
from __future__ import annotations

# Corner palette in Hue units (h, s, b). Values picked to read as moods
# in the apartment's existing warm-biased aesthetic, not as primaries.
# A neutral-warm fallback is used when confidence is very low.
_PALETTE_HAPPY = (8000, 230, 230)        # warm gold — (+V, +A)
_PALETTE_CONTENT = (5500, 210, 200)      # amber — (+V, -A)
_PALETTE_SAD = (45000, 200, 130)         # deep blue — (-V, -A)
_PALETTE_STRESSED = (1000, 240, 200)     # red-orange — (-V, +A)
_PALETTE_NEUTRAL = (8000, 80, 180)       # warm cream fallback

# Below this confidence the lamp settles to neutral instead of tracking
# the noisy reading. Matches the Phase A shadow-log gate philosophy:
# don't actuate on uncertain inputs.
MIN_CONFIDENCE_FOR_COLOR = 0.35


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mood_to_hsv(
    valence: float,
    arousal: float,
    focus: float,
    confidence: float,
) -> tuple[int, int, int]:
    """Map a mood vector to a Hue (hue, sat, bri) triple.

    Args:
        valence: -1 (negative) to +1 (positive).
        arousal: -1 (calm) to +1 (energized).
        focus:    0 (distracted) to +1 (locked in).
        confidence: 0 to 1. Below MIN_CONFIDENCE_FOR_COLOR the output
            collapses to the neutral palette so a flickery detector
            doesn't strobe the lamp.
    """
    if confidence < MIN_CONFIDENCE_FOR_COLOR:
        return _PALETTE_NEUTRAL

    v = max(-1.0, min(1.0, valence))
    a = max(-1.0, min(1.0, arousal))
    f = max(0.0, min(1.0, focus))

    # Low-magnitude readings collapse to the neutral warm palette. Without
    # this guard, V/A near zero blends linearly across the sad↔stressed
    # arc (45000↔1000) and lands at ~15000 (yellow-green), which doesn't
    # read as "neutral mood" to a human looking at the lamp.
    if abs(v) + abs(a) < 0.25:
        return _PALETTE_NEUTRAL

    # Bilinear interpolation across the 4 corners.
    # u = (v + 1) / 2 ∈ [0, 1] — 0 at -V, 1 at +V
    # w = (a + 1) / 2 ∈ [0, 1] — 0 at -A, 1 at +A
    u = (v + 1.0) / 2.0
    w = (a + 1.0) / 2.0

    # Per channel, blend along the V axis first then the A axis.
    def _blend(channel_idx: int) -> float:
        bottom = _lerp(
            _PALETTE_SAD[channel_idx],
            _PALETTE_CONTENT[channel_idx],
            u,
        )
        top = _lerp(
            _PALETTE_STRESSED[channel_idx],
            _PALETTE_HAPPY[channel_idx],
            u,
        )
        return _lerp(bottom, top, w)

    # Hue is on a circle so we'd ideally interpolate the short arc, but the
    # four corners are placed so that no quadrant pair crosses the 65535→0
    # wraparound (sad=45000, stressed=1000 — the unhappy half stays on the
    # cool/red side without wrapping). Plain linear blend is fine here and
    # keeps the function pure.
    h = int(round(_blend(0)))
    s = int(round(_blend(1)))
    b_base = _blend(2)

    # Focus modulates brightness ±20%. Low focus pulls down toward dim;
    # high focus pushes up toward saturated.
    focus_mult = 0.80 + 0.40 * f
    b = int(round(b_base * focus_mult))

    h = max(0, min(65535, h))
    s = max(0, min(254, s))
    b = max(20, min(254, b))  # never let the lamp go fully dark mid-show
    return h, s, b
