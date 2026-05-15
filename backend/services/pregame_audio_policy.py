"""
Pre-game (T-30 transition) audio policy — pure function, no I/O.

Computes the audio behavior for the pregameday → gameday transition: which
TTS line to speak (or silence) and whether to fire the Sonos hype playlist,
factoring in season stakes (playoff probability + week + division gap +
elimination status) and apartment-level signals (sleeping mode, DND).

Sister module to `celebration_volume_policy.py` — same design philosophy
(read the room, gate on hard suppressions, return a structured decision
the orchestrator dispatches). GAMEDAY_SPEC §10.3.

Pure module by design — easy to unit-test, no service dependencies. The
MusicMapper's pregameday→gameday transition handler imports
`compute_pregame_audio`, gathers stakes context from `app_settings` +
automation_engine, and passes everything in.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("home_hub.pregame_audio")


# Stakes tier names — used in PregameAudioDecision.tier for downstream
# logging / digest readability + the synthetic test endpoint's override.
TIER_ELIMINATED = "eliminated"
TIER_BIG_STAKES = "big_stakes"
TIER_CLUTCH = "clutch"
TIER_VICTORY_LAP = "victory_lap"
TIER_STANDARD = "standard"
TIER_PRESEASON = "preseason"
TIER_SUPPRESSED = "suppressed"  # sleeping/DND — distinct from "eliminated" silence

VALID_TIERS = {
    TIER_ELIMINATED, TIER_BIG_STAKES, TIER_CLUTCH,
    TIER_VICTORY_LAP, TIER_STANDARD, TIER_PRESEASON,
}


# TTS line pools — placeholder text per GAMEDAY_SPEC §10.3. Real authoring
# tracked at GH #6; iterate before preseason. {opponent} is substituted.
_TTS_LINES_STANDARD: tuple[str, ...] = (
    "Colts kick off in 30 minutes against the {opponent}.",
    "Game day. Colts and {opponent} in 30.",
    "Half an hour till kickoff. Colts and {opponent}.",
)

_TTS_LINES_BIG_STAKES: tuple[str, ...] = (
    "Colts and {opponent} in 30 minutes. Big implications today.",
    "Half an hour to kickoff against the {opponent}. The standings are watching.",
    "Colts. {opponent}. Thirty minutes. This one matters.",
)

_TTS_LINES_CLUTCH: tuple[str, ...] = (
    "This is a must-win. Colts and {opponent} in half an hour.",
    "Colts and {opponent}. Thirty minutes. Win or pack it in.",
    "Late-season clutch. Colts and {opponent} in 30.",
)

_TTS_LINES_VICTORY_LAP: tuple[str, ...] = (
    "Playoffs locked. Colts and {opponent} in 30. Resting starters?",
    "Thirty minutes. Colts and {opponent}. The seed is safe.",
    "Colts and {opponent} in half an hour. Easy does it.",
)

_TTS_LINES_PRESEASON: tuple[str, ...] = (
    "Preseason kickoff in 30 minutes. Colts and {opponent}. Tuning the apparatus.",
    "Preseason. Colts and {opponent} in 30. Don't read too much into it.",
)


@dataclass(frozen=True)
class PregameAudioDecision:
    """Audio dispatch for the pregameday → gameday transition.

    Both `tts_line` None and `sonos_hype_play` False = silent transition
    (lights only). Hard suppressions (sleeping_mode, dnd_active, eliminated)
    return both null/False.

    `sonos_vibe` is a hint to MusicMapper's playlist selector for tiers
    where the room shouldn't be at full hype — `mellow` for victory-lap
    (locked seed, low-stakes win), `None` otherwise (default hype vibe).
    """
    tier: str
    tts_line: Optional[str]
    sonos_hype_play: bool
    sonos_vibe: Optional[str] = None


def compute_pregame_audio(
    *,
    opponent: str,
    season_week: int,
    is_preseason: bool,
    playoff_probability: Optional[float],
    is_eliminated: bool,
    division_gap_games: Optional[int],
    record: Optional[tuple[int, int, int]] = None,  # (w, l, t) — reserved for future tiebreaks
    sleeping_mode: bool = False,
    dnd_active: bool = False,
    line_index: int = 0,
) -> PregameAudioDecision:
    """Return the audio decision for the pregameday→gameday transition.

    Args:
        opponent: Display name of the opposing team, e.g. "Houston Texans".
            Substituted into the TTS line via str.format.
        season_week: NFL week 1-18 (preseason uses week 0 — see is_preseason).
        is_preseason: True for any preseason game. Overrides the season-week
            tier ladder with a preseason-specific TTS pool, no hype.
        playoff_probability: ESPN's playoff odds for the Colts, 0.0-1.0, or
            None (weeks 1-3 don't have stable playoff probability yet).
        is_eliminated: True when mathematically out of contention. Hard
            suppression — lights flip but audio stays silent.
        division_gap_games: Games behind the division leader, or None
            (weeks 1-2 or bye-week unknowns).
        record: Optional (wins, losses, ties). Reserved for future tiebreaks;
            currently unused.
        sleeping_mode: True when automation_engine.current_mode == "sleeping".
        dnd_active: True when automation_engine.is_dnd_active().
        line_index: Caller-supplied rotation key so the same game returns the
            same line on re-fires (deterministic). Production passes
            `season_week`; tests can pass 0 for predictable line selection.

    Returns:
        PregameAudioDecision — tier name + TTS line (or None) + sonos flags.
    """
    # Hard suppressions — lights still flip, audio stays silent.
    if is_eliminated:
        logger.debug("pregame audio: suppressed (eliminated)")
        return PregameAudioDecision(
            tier=TIER_ELIMINATED, tts_line=None, sonos_hype_play=False,
        )
    if sleeping_mode:
        logger.debug("pregame audio: suppressed (sleeping mode)")
        return PregameAudioDecision(
            tier=TIER_SUPPRESSED, tts_line=None, sonos_hype_play=False,
        )
    if dnd_active:
        logger.debug("pregame audio: suppressed (DND active)")
        return PregameAudioDecision(
            tier=TIER_SUPPRESSED, tts_line=None, sonos_hype_play=False,
        )

    # Preseason gets its own line pool, no hype regardless of stakes math.
    if is_preseason:
        line = _pick_line(_TTS_LINES_PRESEASON, line_index, opponent)
        return PregameAudioDecision(
            tier=TIER_PRESEASON, tts_line=line, sonos_hype_play=False,
        )

    # Tier ladder — first match wins. Locked-seed (victory lap) gets first
    # crack so a late-week game where the Colts have both playoffs locked
    # AND a close division race doesn't fire the clutch line.
    tier, pool, hype, vibe = _classify_tier(
        season_week=season_week,
        playoff_probability=playoff_probability,
        division_gap_games=division_gap_games,
    )
    line = _pick_line(pool, line_index, opponent)
    return PregameAudioDecision(
        tier=tier, tts_line=line, sonos_hype_play=hype, sonos_vibe=vibe,
    )


def _classify_tier(
    *,
    season_week: int,
    playoff_probability: Optional[float],
    division_gap_games: Optional[int],
) -> tuple[str, tuple[str, ...], bool, Optional[str]]:
    """Map regular-season stakes to (tier_name, line_pool, hype_play, vibe).

    Priority order matters — locked-seed beats clutch (don't fire
    must-win lines once playoffs are mathematically secured).
    """
    # Locked playoff seed — high playoff probability + late season.
    if (
        season_week >= 15
        and playoff_probability is not None
        and playoff_probability >= 0.95
    ):
        return TIER_VICTORY_LAP, _TTS_LINES_VICTORY_LAP, True, "mellow"

    # Late-season clutch — week 14+ and tight division race.
    if (
        season_week >= 14
        and division_gap_games is not None
        and division_gap_games <= 1
    ):
        return TIER_CLUTCH, _TTS_LINES_CLUTCH, True, None

    # Big stakes — mid-season+ with a meaningful playoff swing window.
    if (
        season_week >= 8
        and playoff_probability is not None
        and 0.20 <= playoff_probability <= 0.80
    ):
        return TIER_BIG_STAKES, _TTS_LINES_BIG_STAKES, True, None

    # Standard / early season — catch-all. No hype, just announce.
    return TIER_STANDARD, _TTS_LINES_STANDARD, False, None


def decision_for_tier(
    tier: str,
    opponent: str,
    *,
    line_index: int = 0,
    sleeping_mode: bool = False,
    dnd_active: bool = False,
) -> PregameAudioDecision:
    """Build a PregameAudioDecision for a given tier name directly.

    Used by the synthetic test endpoint at `POST /api/gameday/test/pregame`
    (GAMEDAY_SPEC §10.6) to exercise each tier's audio behavior without
    constructing fake stakes inputs. Production code path is
    `compute_pregame_audio` — it runs the stakes ladder for real games.

    Hard suppressions (sleeping_mode, dnd_active) still apply — even a
    "big_stakes" test fire stays silent if the user's asleep.

    Raises ValueError on unknown tier names.
    """
    if sleeping_mode:
        return PregameAudioDecision(
            tier=TIER_SUPPRESSED, tts_line=None, sonos_hype_play=False,
        )
    if dnd_active:
        return PregameAudioDecision(
            tier=TIER_SUPPRESSED, tts_line=None, sonos_hype_play=False,
        )

    if tier == TIER_ELIMINATED:
        return PregameAudioDecision(
            tier=TIER_ELIMINATED, tts_line=None, sonos_hype_play=False,
        )
    if tier == TIER_PRESEASON:
        line = _pick_line(_TTS_LINES_PRESEASON, line_index, opponent)
        return PregameAudioDecision(
            tier=TIER_PRESEASON, tts_line=line, sonos_hype_play=False,
        )
    if tier == TIER_VICTORY_LAP:
        line = _pick_line(_TTS_LINES_VICTORY_LAP, line_index, opponent)
        return PregameAudioDecision(
            tier=TIER_VICTORY_LAP, tts_line=line,
            sonos_hype_play=True, sonos_vibe="mellow",
        )
    if tier == TIER_CLUTCH:
        line = _pick_line(_TTS_LINES_CLUTCH, line_index, opponent)
        return PregameAudioDecision(
            tier=TIER_CLUTCH, tts_line=line, sonos_hype_play=True,
        )
    if tier == TIER_BIG_STAKES:
        line = _pick_line(_TTS_LINES_BIG_STAKES, line_index, opponent)
        return PregameAudioDecision(
            tier=TIER_BIG_STAKES, tts_line=line, sonos_hype_play=True,
        )
    if tier == TIER_STANDARD:
        line = _pick_line(_TTS_LINES_STANDARD, line_index, opponent)
        return PregameAudioDecision(
            tier=TIER_STANDARD, tts_line=line, sonos_hype_play=False,
        )
    raise ValueError(f"Unknown tier: {tier!r}. Valid: {sorted(VALID_TIERS)}")


def _pick_line(pool: tuple[str, ...], line_index: int, opponent: str) -> str:
    """Deterministic rotation through a pool with `{opponent}` substitution.

    line_index is taken mod len(pool) so callers can pass season_week (or
    any integer) without worrying about overflow. Empty pools fall back to
    a hard-coded standard line — should never happen in production.
    """
    if not pool:
        logger.warning("pregame audio: empty line pool, using fallback")
        return f"Game day. Colts and {opponent}."
    idx = line_index % len(pool)
    return pool[idx].format(opponent=opponent)
