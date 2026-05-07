"""
Kickoff TTS line picker — pure function, no I/O.

Picks the kickoff TTS opener based on game-day context. Two dimensions:

1. **Day-of-week game slot** — Sunday afternoon / Sunday Night / Monday
   Night / Thursday Night / Saturday primetime each get a distinct line
   pool. Derived from kickoff timestamp in Indianapolis local time.
2. **Team form** — when the Colts have been winning recently, lines refer
   to the QB as "Danny Dimes." When struggling, they fall back to
   "Daniel Jones." Form is `None` if not yet computed (early season,
   pre-refresh) — the picker defaults to the measured "Daniel Jones"
   variant in that case.

Mirrors the `celebration_volume_policy.py` pattern: pure module, no
service deps, easy to unit-test. Caller (CelebrationOrchestrator's
`_run_tts` for the kickoff branch) gathers context and passes it in.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — defensive only
    ZoneInfo = None  # type: ignore[misc,assignment]

logger = logging.getLogger("home_hub.kickoff_tts")

_INDY_TZ = ZoneInfo("America/Indiana/Indianapolis") if ZoneInfo else None

# Sunday Night Football kickoff threshold — games ≥19:00 Indy-local on
# Sunday are primetime SNF, < 19:00 are afternoon games. NFL's actual
# SNF window is 20:20 ET, but the 19:00 threshold cleanly separates the
# late afternoon (16:25 ET start) from the SNF slot. Indianapolis tracks
# ET throughout the NFL season (no DST divergence).
_SUNDAY_NIGHT_HOUR = 19


class GameSlot(Enum):
    """Day-of-week game slot derived from kickoff timestamp."""
    SUNDAY_AFTERNOON = "sunday_afternoon"   # default Sunday slot, < 19:00 ET
    SUNDAY_NIGHT = "sunday_night"           # >= 19:00 ET on Sunday (SNF)
    MONDAY_NIGHT = "monday_night"           # any Monday kickoff (MNF)
    THURSDAY_NIGHT = "thursday_night"       # any Thursday kickoff (TNF)
    SATURDAY_PRIMETIME = "saturday_primetime"  # any Saturday kickoff


@dataclass(frozen=True)
class TeamForm:
    """Cached team-performance signal driving the dimes/jones swap.

    Refreshed weekly by a future ScheduledTask reading ESPN standings.
    Until that task ships, callers pass `None` and the picker defaults
    to the "jones" (measured) variant.
    """
    last4_record: tuple[int, int]   # (wins, losses) over last 4 games
    win_streak: int                 # current streak length (0 = no streak)
    season_record: tuple[int, int, int]  # (wins, losses, ties) season-to-date


def _is_dimes_form(form: TeamForm) -> bool:
    """Heuristic for "Colts are rolling." Any of the following triggers
    the "Danny Dimes" variant:
      • last 4 games went 3-1 or better
      • current win streak is 2+
      • season record is above .500 with at least 4 games played
    """
    last4_wins, _last4_losses = form.last4_record
    if last4_wins >= 3:
        return True
    if form.win_streak >= 2:
        return True
    season_wins, season_losses, _season_ties = form.season_record
    games_played = season_wins + season_losses
    if season_wins > season_losses and games_played >= 4:
        return True
    return False


def _slot_from_timestamp(ts: datetime) -> GameSlot:
    """Pure mapping from kickoff timestamp to GameSlot. Caller passes a
    timezone-aware datetime; we convert to Indianapolis local time (which
    tracks ET throughout the NFL season) for the slot decision."""
    if _INDY_TZ is None:
        # Defensive — extremely unlikely on a 3.9+ runtime.
        return GameSlot.SUNDAY_AFTERNOON
    local = ts.astimezone(_INDY_TZ)
    weekday = local.weekday()  # Mon=0 .. Sun=6
    hour = local.hour

    if weekday == 6:  # Sunday
        return (
            GameSlot.SUNDAY_NIGHT if hour >= _SUNDAY_NIGHT_HOUR
            else GameSlot.SUNDAY_AFTERNOON
        )
    if weekday == 0:  # Monday
        return GameSlot.MONDAY_NIGHT
    if weekday == 3:  # Thursday
        return GameSlot.THURSDAY_NIGHT
    if weekday == 5:  # Saturday
        return GameSlot.SATURDAY_PRIMETIME
    # Tue/Wed/Fri kickoffs are extraordinarily rare (Christmas Day Friday
    # specials in 2026, Christmas Day Wednesday/Thursday specials in
    # other years) — fall back to standard Sunday afternoon pool. Revisit
    # if the Colts draw a Friday Christmas game; a FRIDAY_SPECIAL pool
    # would carry holiday-flavored lines.
    return GameSlot.SUNDAY_AFTERNOON


# Line pools. Templates use {opponent} for format_map substitution by
# the caller's `_run_tts`. Each slot has both "dimes" (winning) and
# "jones" (struggling/measured) variants.
_POOLS: dict[GameSlot, dict[str, list[str]]] = {
    GameSlot.SUNDAY_AFTERNOON: {
        "dimes": [
            "Sunday afternoon football, baby. Danny Dimes vs the {opponent}.",
            "Game time. Let's see if Danny Dimes can keep it rolling against the {opponent}.",
            "Colts and the {opponent}. Danny Dimes has the keys.",
            "Here we go — Danny Dimes leading the Colts against the {opponent}.",
        ],
        "jones": [
            "Colts kickoff against the {opponent}. Daniel Jones has work to do.",
            "Game time. Daniel Jones and the Colts vs the {opponent}.",
            "Colts and the {opponent}. Daniel Jones gets another chance.",
            "Sunday football. Let's see what Daniel Jones brings against the {opponent}.",
        ],
    },
    GameSlot.SUNDAY_NIGHT: {
        "dimes": [
            "Sunday Night Football, baby. Danny Dimes and the Colts vs the {opponent}.",
            "Primetime, Danny Dimes. Colts and the {opponent} in the spotlight.",
            "Sunday Night lights — Danny Dimes leading the Colts against the {opponent}.",
            "SNF, here we go. Danny Dimes vs the {opponent}.",
        ],
        "jones": [
            "Sunday Night Football. Daniel Jones gets the primetime spotlight against the {opponent}.",
            "SNF — Colts and the {opponent}. Daniel Jones needs to bring it.",
            "Sunday Night kickoff. Daniel Jones vs the {opponent} in primetime.",
        ],
    },
    GameSlot.MONDAY_NIGHT: {
        "dimes": [
            "Monday Night Football, baby. Danny Dimes vs the {opponent}.",
            "MNF — Colts and the {opponent}. Danny Dimes in primetime.",
            "Monday Night lights. Danny Dimes leading the Colts against the {opponent}.",
            "Here we go, MNF. Danny Dimes vs the {opponent}.",
        ],
        "jones": [
            "Monday Night Football. Daniel Jones in the primetime crucible against the {opponent}.",
            "MNF kickoff. Daniel Jones and the Colts vs the {opponent}.",
            "Monday Night lights. Daniel Jones gets another shot, this time against the {opponent}.",
        ],
    },
    GameSlot.THURSDAY_NIGHT: {
        "dimes": [
            "Thursday Night Football. Danny Dimes vs the {opponent} on a short week.",
            "TNF — short week, but Danny Dimes is rolling. Colts and the {opponent}.",
            "Thursday Night, baby. Danny Dimes vs the {opponent}.",
        ],
        "jones": [
            "Thursday Night Football. Daniel Jones gets the short-week test against the {opponent}.",
            "TNF kickoff. Daniel Jones and the Colts vs the {opponent}.",
            "Thursday Night Football. Daniel Jones leading the Colts against the {opponent}.",
        ],
    },
    GameSlot.SATURDAY_PRIMETIME: {
        "dimes": [
            "Saturday primetime. Danny Dimes vs the {opponent}.",
            "Late-season Saturday football. Danny Dimes and the Colts in primetime against the {opponent}.",
            "Saturday lights. Danny Dimes leading the Colts vs the {opponent}.",
        ],
        "jones": [
            "Saturday primetime. Daniel Jones and the Colts vs the {opponent}.",
            "Late-season Saturday football. Daniel Jones in primetime against the {opponent}.",
        ],
    },
}


def pick_kickoff_tts(
    *,
    kickoff_at: datetime,
    team_form: Optional[TeamForm] = None,
    rng: Optional[random.Random] = None,
) -> str:
    """Pick a kickoff TTS line based on day-of-week + team form.

    Args:
        kickoff_at: timezone-aware datetime of kickoff. Will be converted
            to Indianapolis local time for slot decision.
        team_form: cached team-performance signal. `None` (the default
            until the refresh task ships) → picker uses "jones"
            (measured) pool — err on the side of restraint when we
            don't have form data yet.
        rng: optional `random.Random` instance for deterministic tests.
            Production callers pass `None` to use the module-level RNG.

    Returns:
        TTS template string with `{opponent}` placeholder still in
        place — caller is responsible for `format_map` substitution.
    """
    slot = _slot_from_timestamp(kickoff_at)
    variant = "dimes" if (team_form is not None and _is_dimes_form(team_form)) else "jones"
    pool = _POOLS[slot][variant]
    rng = rng or random
    chosen = rng.choice(pool)
    logger.debug(
        "kickoff_tts: slot=%s variant=%s line=%r",
        slot.value, variant, chosen,
    )
    return chosen
