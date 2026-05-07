"""
Field-goal TTS line picker — pure function, no I/O.

Picks the field-goal TTS line based on kick distance. Two pools:

- **standard** (any distance): chip shots through 49-yarders. Measured
  acknowledgement; FG is a smaller celebration than a TD.
- **big_kick** (≥50 yards): the energy line pool. 50+ yard kicks are
  meaningful events that deserve more than the chip-shot opener.

Mirrors `kickoff_tts_picker.py` and `celebration_volume_policy.py`'s
shape: pure module, no service deps, easy to unit-test. Caller
(CelebrationOrchestrator's `_run_tts` for the field_goal branch)
extracts yards + kicker from the PlayEvent context and calls.
"""
from __future__ import annotations

import logging
import random
from typing import Optional

logger = logging.getLogger("home_hub.fg_tts")

# 50+ yard kicks get the "big kick" energy pool. Three thresholds were
# considered (40 / 45 / 50); 50 is the cleanest line — sub-50 is a
# routine pro kick, 50+ historically signaled "big leg" territory.
BIG_KICK_THRESHOLD_YARDS = 50

# Line pools. {kicker} and {yards} are substituted by the caller via
# format_map. Keep templates that read fine when {kicker} falls back
# to "the kicker" and {yards} falls back to empty string (FG events
# may carry incomplete data on synthetic test fires).
_POOLS: dict[str, list[str]] = {
    "standard": [
        "Field goal is good! {kicker} from {yards}!",
        "{kicker} drills it from {yards} yards out!",
        "Three points Colts — {kicker} from {yards}!",
        "Good! {kicker} nails the {yards}-yarder!",
        "Colts on the board — {kicker} from {yards}.",
        "Three points, baby. {kicker} from {yards}.",
        "And it's good — {kicker} doesn't miss from {yards}.",
    ],
    "big_kick": [
        "{kicker} from {yards}! What a leg!",
        "Are you kidding me? {kicker} crushes it from {yards}!",
        "{kicker} from {yards} — that's a bomb of a field goal!",
        "Three points and a big leg — {kicker} from {yards}!",
        "{kicker} from {yards}. Get the man a Gatorade.",
        "Long-range artillery from {kicker} — {yards} yards, all good.",
    ],
}


def _pool_key_for_distance(yards: Optional[int]) -> str:
    """Map a kick distance to the pool key. Unknown distance defaults to
    "standard" — measured tone is the safe fallback when ESPN didn't
    parse the yardage cleanly."""
    if yards is None:
        return "standard"
    if yards >= BIG_KICK_THRESHOLD_YARDS:
        return "big_kick"
    return "standard"


def pick_fg_tts(
    *,
    yards: Optional[int] = None,
    rng: Optional[random.Random] = None,
) -> str:
    """Pick a field-goal TTS line based on kick distance.

    Args:
        yards: kick distance in yards (1-65 typical NFL range). `None`
            when the play event didn't carry a parsed yardage — picker
            defaults to the "standard" pool.
        rng: optional `random.Random` instance for deterministic tests.
            Production callers pass `None` to use the module-level RNG.

    Returns:
        TTS template string with `{kicker}` and `{yards}` placeholders
        still in place — caller is responsible for `format_map`
        substitution.
    """
    pool_key = _pool_key_for_distance(yards)
    pool = _POOLS[pool_key]
    rng = rng or random
    chosen = rng.choice(pool)
    logger.debug(
        "fg_tts: yards=%s pool=%s line=%r", yards, pool_key, chosen,
    )
    return chosen
