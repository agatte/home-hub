"""
Shared RGB → Hue HSB conversion + per-light tuning constants.

Extracted from ``screen_sync.py`` so other services that drive arbitrary
RGB into a Hue bulb (e.g. ``lol_champion_service``) get the same fabric-
shade sat boost on L2 and the same perceptual-luma compensation on L5
without re-implementing the math. Touching either dict here changes the
behaviour of every consumer in lockstep.

The numerical constants and the rationale behind them — `_LUMA_REFERENCE
= 0.25`, L2's `1.2` sat boost, the Rec.601 weights — were tuned via live
A/B on the actual bulbs during the screen-sync iteration; do not adjust
without re-validating against ScreenSyncService's behaviour.
"""
from __future__ import annotations

import colorsys

# Per-light saturation boost. RGB→HSB conversion applies this multiplier
# to saturation; L2's fabric shade washes punch out, so +20% restores
# vibrancy. L5's clear glass shows the bulb's color directly with no
# diffusion, so any boost reads as oversaturated next to L2 — leave it
# at neutral (1.0).
PER_LIGHT_SAT_BOOST: dict[str, float] = {
    "2": 1.2,
    "5": 1.0,
}
DEFAULT_SAT_BOOST = 1.2

# Per-light perceptual-luminance compensation. The human eye is far more
# sensitive to yellow-green (peak ~555nm) than to deep blue, so the same
# HSV value reads very differently depending on hue. Through L2's fabric
# shade the difference washes out, but L5's clear glass exposes the bulb
# color directly and the mismatch is very visible.
PER_LIGHT_LUMA_COMP: dict[str, bool] = {
    "5": True,
}
DEFAULT_LUMA_COMP = False

# Reference 0.25 is aggressive — pure white scales to 25% of HSV value,
# green to 43%, yellow to 28%, cyan to 36%, magenta to 60%; pure blue
# and dark red stay full-bri (clamped to 1.0).
_LUMA_REFERENCE = 0.25

DEFAULT_MIN_BRIGHTNESS = 15


def rgb_to_hue_hsb(
    rgb: tuple[int, int, int],
    max_brightness: int,
    min_brightness: int = DEFAULT_MIN_BRIGHTNESS,
    sat_boost: float = DEFAULT_SAT_BOOST,
    luma_comp: bool = DEFAULT_LUMA_COMP,
) -> tuple[float, float, float]:
    """Convert RGB (0-255) to Hue bridge HSB values, clamped to brightness range.

    ``sat_boost`` is per-light: L2's fabric shade benefits from +20%
    vibrancy compensation, L5's clear glass needs neutral (1.0) to avoid
    looking oversaturated next to L2.

    ``luma_comp`` enables perceptual-luminance compensation. When True,
    the brightness target is scaled by ``_LUMA_REFERENCE / chroma_luma``
    (clamped to ≤1.0) so high-luma hues (yellow ~0.89, green ~0.59) are
    dampened relative to low-luma hues (blue ~0.11, red ~0.30). This
    makes visible-bulb output read approximately hue-independent — used
    on L5 (clear glass) where the eye sees the bulb color directly and
    the Rec.601 mismatch is most visible.
    """
    r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    hue_val = h * 65535
    sat_val = min(254, s * 254 * sat_boost)

    bri_target = v * 254
    if luma_comp and v > 0.01:
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        chroma_luma = luma / v  # hue-invariant: depends only on hue, not v
        scale = min(1.0, _LUMA_REFERENCE / max(0.1, chroma_luma))
        bri_target *= scale

    bri_val = max(min_brightness, min(max_brightness, bri_target))

    return (hue_val, sat_val, bri_val)
