"""
Touchdown TTS line picker — pure function, no I/O.

Picks the TD TTS line based on play-level WPA (win probability added).
Three pools, mirroring the celebration_volume_policy WPA tiers:

- **standard** (|WPA| < 0.10, or unknown): routine TD — down by three
  scores, garbage-time score, opening drive in week 1. Measured tone.
- **big_play** (0.10 ≤ |WPA| < 0.20): meaningful swing — go-ahead TD,
  closing the gap to one score, end-of-half score that flips momentum.
- **game_changing** (|WPA| ≥ 0.20): "holy shit" tier — game-winning
  TD, late-Q4 go-ahead with two minutes left, walk-off score.

Mirrors `fg_tts_picker.py` and `kickoff_tts_picker.py`'s shape: pure
module, no service deps. Caller (CelebrationOrchestrator's `_run_tts`
for the touchdown branch) extracts WPA from the PlayEvent context and
calls.
"""
from __future__ import annotations

import logging
import random
from typing import Optional

logger = logging.getLogger("home_hub.td_tts")

# WPA tier thresholds. Match the user's spec ("|WPA|<0.10 standard,
# 0.10-0.20 big_play, ≥0.20 game_changing") which is slightly less
# stringent than the volume policy's ±0.05/0.15/0.25 bands — TD tone
# is a coarser dimension than volume nudges, so 3 tiers is right.
BIG_PLAY_WPA_THRESHOLD = 0.10
GAME_CHANGING_WPA_THRESHOLD = 0.20

_POOLS: dict[str, list[str]] = {
    "standard": [
        "Touchdown Colts! {player} in for six!",
        "{player}! He goes the distance for the Colts!",
        "And it's a Colts touchdown! {player} finds the end zone!",
        "Six points! {player} punches it in!",
        "Touchdown Indianapolis! Way to go, {player}!",
        "Six. {player} crosses the line for the Colts.",
        "Colts add another — {player}, end zone.",
    ],
    "big_play": [
        "Touchdown Colts! {player} comes through!",
        "{player} hits paydirt — big response from Indy!",
        "And it's a Colts touchdown! {player} — six points and a swing.",
        "{player} punches it in when Indy needed it!",
        "{player}! Big-time TD for the Colts!",
        "Six! {player} delivers a momentum swing for Indy.",
    ],
    "game_changing": [
        "ARE YOU KIDDING ME?! {player} for the Colts!",
        "TOUCHDOWN! {player}! Are you watching this?!",
        "{player}! What a moment for the Colts!",
        "Holy cow! {player} delivers when it matters most!",
        "{player}! Six points — and the Colts steal it!",
        "Game-changing TD! {player} for Indy!",
        "{player}! Let's go, Colts!",
    ],
}


def _pool_key_for_wpa(wpa: Optional[float]) -> str:
    """Map a play-level WPA to a pool key. `None` (ESPN's WP model
    hasn't yet indexed the play, ~10s lag after the snap) defaults to
    "standard" — measured tone is the safe fallback."""
    if wpa is None:
        return "standard"
    abs_wpa = abs(wpa)
    if abs_wpa >= GAME_CHANGING_WPA_THRESHOLD:
        return "game_changing"
    if abs_wpa >= BIG_PLAY_WPA_THRESHOLD:
        return "big_play"
    return "standard"


def pick_td_tts(
    *,
    wpa: Optional[float] = None,
    rng: Optional[random.Random] = None,
) -> str:
    """Pick a touchdown TTS line based on play-level WPA.

    Args:
        wpa: per-play win-probability change (Colts perspective —
            sign-flipped when away). `None` when ESPN hasn't yet
            indexed the play; picker defaults to "standard" pool.
        rng: optional `random.Random` for deterministic tests.

    Returns:
        TTS template with `{player}` placeholder still in place;
        caller substitutes via `format_map`.
    """
    pool_key = _pool_key_for_wpa(wpa)
    pool = _POOLS[pool_key]
    rng = rng or random
    chosen = rng.choice(pool)
    logger.debug("td_tts: wpa=%s pool=%s line=%r", wpa, pool_key, chosen)
    return chosen
