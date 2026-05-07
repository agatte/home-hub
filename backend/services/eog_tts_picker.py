"""
End-of-game (win) TTS line picker — pure function, no I/O.

Picks the EOG_WIN TTS line based on final-score margin. Two pools:

- **close** (margin ≤ 7): one-score win. High-energy "we earned it"
  tone. Late comebacks land here.
- **comfortable** (margin > 7): two-score-or-more win. Measured
  celebratory tone — the apartment doesn't need maximum hype on a
  blowout that was decided in Q3.

Mirrors `td_tts_picker.py` and `fg_tts_picker.py`'s shape: pure
module, no service deps. Caller (CelebrationOrchestrator's `_run_tts`
for the end_of_game_win branch) extracts the score margin from
context and calls.

EOG_LOSS stays silent (`tts_lines=[]` per `docs/GAMEDAY_SPEC.md` §2.2)
— no picker for losses.
"""
from __future__ import annotations

import logging
import random
from typing import Optional

logger = logging.getLogger("home_hub.eog_tts")

# 7-point margin threshold — within one score = "close win," beyond =
# comfortable. Matches NFL "one-score game" convention.
CLOSE_WIN_MARGIN = 7

_POOLS: dict[str, list[str]] = {
    "close": [
        "Colts win! Final score, {colts_score} to {opp_score}!",
        "Colts take it, {colts_score} to {opp_score}! Way to go boys!",
        "Indy holds on — {colts_score} to {opp_score}! What a game!",
        "Colts win it! {colts_score} to {opp_score} over the {opponent}!",
        "We earned that one. Colts beat the {opponent} {colts_score} to {opp_score}!",
        "Colts grind it out — final: {colts_score} to {opp_score}!",
        "Colts win the close one! {colts_score} to {opp_score}.",
    ],
    "comfortable": [
        "That's a Colts victory — {colts_score} to {opp_score}!",
        "Final: Colts {colts_score}, {opponent} {opp_score}. Indy on top!",
        "Colts roll — {colts_score} to {opp_score} over the {opponent}.",
        "Colts handle the {opponent}, {colts_score} to {opp_score}.",
        "Comfortable win for Indy. {colts_score} to {opp_score} over the {opponent}.",
        "Colts take care of business: {colts_score} to {opp_score}.",
    ],
}


def _pool_key_for_margin(colts_score: int, opp_score: int) -> str:
    """Map a final-score margin to a pool key. Negative margin (Colts
    lost) shouldn't happen on the EOG_WIN code path; fall back to
    "close" as a defensive default — caller dispatches to EOG_LOSS
    anyway when score_colts <= score_opp."""
    margin = colts_score - opp_score
    if margin <= 0:
        return "close"  # defensive — orchestrator routes losses elsewhere
    if margin <= CLOSE_WIN_MARGIN:
        return "close"
    return "comfortable"


def pick_eog_win_tts(
    *,
    colts_score: int,
    opp_score: int,
    rng: Optional[random.Random] = None,
) -> str:
    """Pick an end-of-game win TTS line based on margin.

    Args:
        colts_score: Colts final score.
        opp_score: opponent final score.
        rng: optional `random.Random` for deterministic tests.

    Returns:
        TTS template with `{colts_score}`, `{opp_score}`, and
        `{opponent}` placeholders still in place — caller substitutes
        via `format_map`.
    """
    pool_key = _pool_key_for_margin(colts_score, opp_score)
    pool = _POOLS[pool_key]
    rng = rng or random
    chosen = rng.choice(pool)
    logger.debug(
        "eog_win_tts: margin=%d pool=%s line=%r",
        colts_score - opp_score, pool_key, chosen,
    )
    return chosen
