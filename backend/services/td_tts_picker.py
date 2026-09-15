"""
Touchdown TTS line picker — pure function, no I/O.

WPA selects the excitement tier; touchdown distance only gates wording that
would otherwise make a physical claim about the play. Short-yardage phrasing
is reserved for goal-line scores, long-run phrasing for breakaways, and
unknown/mid-range distances use neutral copy.

Three WPA pools mirror the existing celebration language contract:
- standard: |WPA| < 0.10, or unknown
- big_play: 0.10 <= |WPA| < 0.20
- game_changing: |WPA| >= 0.20
"""
from __future__ import annotations

import logging
import random
from typing import Optional

logger = logging.getLogger("home_hub.td_tts")

BIG_PLAY_WPA_THRESHOLD = 0.10
GAME_CHANGING_WPA_THRESHOLD = 0.20
SHORT_TD_MAX_YARDS = 5
LONG_TD_MIN_YARDS = 30

# These lines are truthful for any touchdown distance.
_POOLS: dict[str, list[str]] = {
    "standard": [
        "Touchdown Colts! {player} in for six!",
        "And it's a Colts touchdown! {player} finds the end zone!",
        "Touchdown Indianapolis! Way to go, {player}!",
        "Six. {player} crosses the line for the Colts.",
        "Colts add another — {player}, end zone.",
    ],
    "big_play": [
        "Touchdown Colts! {player} comes through!",
        "{player} hits paydirt — big response from Indy!",
        "And it's a Colts touchdown! {player} — six points and a swing.",
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

_SHORT_DISTANCE_LINES: dict[str, list[str]] = {
    "standard": ["Six points! {player} punches it in!"],
    "big_play": ["{player} punches it in when Indy needed it!"],
    "game_changing": [],
}

_LONG_DISTANCE_LINES: dict[str, list[str]] = {
    "standard": ["{player}! He goes the distance for the Colts!"],
    "big_play": [],
    "game_changing": [],
}


def _pool_key_for_wpa(wpa: Optional[float]) -> str:
    """Map play-level WPA to the existing touchdown energy tier."""
    if wpa is None:
        return "standard"
    abs_wpa = abs(wpa)
    if abs_wpa >= GAME_CHANGING_WPA_THRESHOLD:
        return "game_changing"
    if abs_wpa >= BIG_PLAY_WPA_THRESHOLD:
        return "big_play"
    return "standard"


def _distance_bucket(yards: Optional[int]) -> str:
    """Return conservative wording authority for a touchdown distance."""
    if yards is None or yards < 0:
        return "neutral"
    if yards <= SHORT_TD_MAX_YARDS:
        return "short"
    if yards >= LONG_TD_MIN_YARDS:
        return "long"
    return "neutral"


def _candidate_lines(pool_key: str, yards: Optional[int]) -> list[str]:
    """Build the truthful line set for an energy tier and distance."""
    lines = list(_POOLS[pool_key])
    bucket = _distance_bucket(yards)
    if bucket == "short":
        lines.extend(_SHORT_DISTANCE_LINES[pool_key])
    elif bucket == "long":
        lines.extend(_LONG_DISTANCE_LINES[pool_key])
    return lines


def pick_td_tts(
    *,
    wpa: Optional[float] = None,
    yards: Optional[int] = None,
    rng: Optional[random.Random] = None,
) -> str:
    """Pick a touchdown TTS line without inventing play distance semantics.

    WPA controls the excitement tier. `yards` only enables phrases that are
    specifically truthful for short (<=5) or long (>=30) touchdowns. Missing
    or mid-range yardage stays on neutral wording.
    """
    pool_key = _pool_key_for_wpa(wpa)
    candidates = _candidate_lines(pool_key, yards)
    rng = rng or random
    chosen = rng.choice(candidates)
    logger.debug(
        "td_tts: wpa=%s yards=%s pool=%s distance=%s line=%r",
        wpa,
        yards,
        pool_key,
        _distance_bucket(yards),
        chosen,
    )
    return chosen
