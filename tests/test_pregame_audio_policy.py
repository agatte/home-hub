"""
Tests for `compute_pregame_audio` — GAMEDAY_SPEC §10.3 stakes ladder.

Coverage targets per §10.6:
- All 7 tier branches (eliminated, sleeping, DND, preseason, victory-lap,
  clutch, big-stakes, standard)
- Hard suppressions override every tier
- Eliminated overrides stakes (no "eliminated but big stakes")
- Preseason override hits regardless of regular-season fields
- Edge cases: weeks 1-3 (no playoff_probability), week-boundary transitions,
  bye-week (division_gap_games=None), boundary playoff_probability values
- {opponent} substitution renders correctly
- line_index rotation is deterministic
"""
from __future__ import annotations

import pytest

from backend.services.pregame_audio_policy import (
    PregameAudioDecision,
    TIER_BIG_STAKES,
    TIER_CLUTCH,
    TIER_ELIMINATED,
    TIER_PRESEASON,
    TIER_STANDARD,
    TIER_SUPPRESSED,
    TIER_VICTORY_LAP,
    compute_pregame_audio,
)


def _call(**overrides) -> PregameAudioDecision:
    """Default-stuffed caller — lets each test express only its delta.

    Defaults model a regular-season early-week 1 game with no extra signal:
    no playoff probability, not eliminated, not on a tight division pace.
    """
    defaults = dict(
        opponent="Houston Texans",
        season_week=1,
        is_preseason=False,
        playoff_probability=None,
        is_eliminated=False,
        division_gap_games=None,
    )
    defaults.update(overrides)
    return compute_pregame_audio(**defaults)


# ---------------------------------------------------------------------------
# Hard suppressions
# ---------------------------------------------------------------------------

class TestHardSuppressions:

    def test_eliminated_returns_silent(self):
        d = _call(is_eliminated=True, season_week=18, playoff_probability=0.0)
        assert d.tier == TIER_ELIMINATED
        assert d.tts_line is None
        assert d.sonos_hype_play is False

    def test_eliminated_overrides_big_stakes(self):
        """Eliminated wins over a high-stakes pattern that would otherwise fire."""
        d = _call(
            is_eliminated=True,
            season_week=10, playoff_probability=0.50,
        )
        assert d.tier == TIER_ELIMINATED
        assert d.tts_line is None

    def test_sleeping_returns_silent(self):
        d = _call(sleeping_mode=True, season_week=8, playoff_probability=0.50)
        assert d.tier == TIER_SUPPRESSED
        assert d.tts_line is None
        assert d.sonos_hype_play is False

    def test_dnd_returns_silent(self):
        d = _call(dnd_active=True, season_week=14, division_gap_games=0)
        assert d.tier == TIER_SUPPRESSED
        assert d.tts_line is None
        assert d.sonos_hype_play is False

    def test_eliminated_beats_sleeping_in_tier_field(self):
        """If both fire, eliminated tier label wins (it's checked first)."""
        d = _call(is_eliminated=True, sleeping_mode=True)
        assert d.tier == TIER_ELIMINATED


# ---------------------------------------------------------------------------
# Preseason
# ---------------------------------------------------------------------------

class TestPreseason:

    def test_preseason_uses_preseason_pool(self):
        d = _call(is_preseason=True, season_week=0)
        assert d.tier == TIER_PRESEASON
        assert d.tts_line is not None
        assert "Preseason" in d.tts_line
        assert d.sonos_hype_play is False

    def test_preseason_overrides_stakes_math(self):
        """Even if playoff_probability is in the big-stakes range, preseason wins."""
        d = _call(
            is_preseason=True, season_week=0,
            playoff_probability=0.50,
        )
        assert d.tier == TIER_PRESEASON
        assert d.sonos_hype_play is False

    def test_preseason_renders_opponent(self):
        d = _call(is_preseason=True, opponent="Detroit Lions")
        assert "Detroit Lions" in d.tts_line


# ---------------------------------------------------------------------------
# Victory lap (locked playoff seed)
# ---------------------------------------------------------------------------

class TestVictoryLap:

    def test_victory_lap_week_15_locked_seed(self):
        d = _call(season_week=15, playoff_probability=0.97)
        assert d.tier == TIER_VICTORY_LAP
        assert d.sonos_hype_play is True
        assert d.sonos_vibe == "mellow"

    def test_victory_lap_boundary_week_15_exact(self):
        d = _call(season_week=15, playoff_probability=0.95)
        assert d.tier == TIER_VICTORY_LAP

    def test_victory_lap_skipped_at_week_14(self):
        """Week 14 with high playoff_probability is NOT victory lap yet."""
        d = _call(season_week=14, playoff_probability=0.97, division_gap_games=3)
        # Falls to big_stakes via the 0.20-0.80 band? No — 0.97 is outside.
        # Falls to standard.
        assert d.tier == TIER_STANDARD

    def test_victory_lap_beats_clutch_when_seed_locked(self):
        """High playoff_probability + tight division → victory_lap, not clutch."""
        d = _call(
            season_week=15,
            playoff_probability=0.97,
            division_gap_games=0,
        )
        assert d.tier == TIER_VICTORY_LAP


# ---------------------------------------------------------------------------
# Clutch (late-season tight division)
# ---------------------------------------------------------------------------

class TestClutch:

    def test_clutch_week_14_tight_race(self):
        d = _call(season_week=14, division_gap_games=1, playoff_probability=0.45)
        assert d.tier == TIER_CLUTCH
        assert d.sonos_hype_play is True
        assert d.sonos_vibe is None  # default hype

    def test_clutch_division_leader_zero_gap(self):
        d = _call(season_week=16, division_gap_games=0, playoff_probability=0.55)
        assert d.tier == TIER_CLUTCH

    def test_clutch_skipped_when_gap_too_large(self):
        d = _call(season_week=14, division_gap_games=3, playoff_probability=0.45)
        assert d.tier == TIER_BIG_STAKES  # falls to next tier

    def test_clutch_skipped_when_division_gap_unknown(self):
        """None gap (bye-week / pre-week-3 unknowns) doesn't fire clutch."""
        d = _call(season_week=15, division_gap_games=None, playoff_probability=0.45)
        assert d.tier == TIER_BIG_STAKES


# ---------------------------------------------------------------------------
# Big stakes
# ---------------------------------------------------------------------------

class TestBigStakes:

    def test_big_stakes_week_8_midrange(self):
        d = _call(season_week=8, playoff_probability=0.50)
        assert d.tier == TIER_BIG_STAKES
        assert d.sonos_hype_play is True

    def test_big_stakes_boundary_prob_0_20(self):
        d = _call(season_week=10, playoff_probability=0.20)
        assert d.tier == TIER_BIG_STAKES

    def test_big_stakes_boundary_prob_0_80(self):
        d = _call(season_week=10, playoff_probability=0.80)
        assert d.tier == TIER_BIG_STAKES

    def test_big_stakes_skipped_below_0_20(self):
        d = _call(season_week=10, playoff_probability=0.15)
        assert d.tier == TIER_STANDARD

    def test_big_stakes_skipped_above_0_80(self):
        """High prob without late-season + locked-seed gate falls to standard."""
        d = _call(season_week=10, playoff_probability=0.90)
        assert d.tier == TIER_STANDARD

    def test_big_stakes_skipped_at_week_7(self):
        d = _call(season_week=7, playoff_probability=0.50)
        assert d.tier == TIER_STANDARD

    def test_big_stakes_skipped_when_prob_unknown(self):
        d = _call(season_week=10, playoff_probability=None)
        assert d.tier == TIER_STANDARD


# ---------------------------------------------------------------------------
# Standard / early-season catch-all
# ---------------------------------------------------------------------------

class TestStandard:

    def test_standard_week_1(self):
        d = _call(season_week=1)
        assert d.tier == TIER_STANDARD
        assert d.tts_line is not None
        assert d.sonos_hype_play is False

    def test_standard_no_signals(self):
        """Mid-season but no playoff data → standard."""
        d = _call(season_week=10)
        assert d.tier == TIER_STANDARD

    def test_standard_renders_opponent(self):
        d = _call(season_week=1, opponent="Jacksonville Jaguars")
        assert "Jacksonville Jaguars" in d.tts_line


# ---------------------------------------------------------------------------
# Line rotation + opponent substitution
# ---------------------------------------------------------------------------

class TestLineRotation:

    def test_line_index_zero_returns_first(self):
        d0 = _call(season_week=1, line_index=0)
        d1 = _call(season_week=1, line_index=1)
        assert d0.tts_line != d1.tts_line

    def test_line_index_wraps(self):
        """line_index modulo pool length — large values don't break."""
        d = _call(season_week=1, line_index=999_999)
        assert d.tts_line is not None  # didn't IndexError

    def test_line_index_deterministic(self):
        """Same inputs → same line."""
        d1 = _call(season_week=8, playoff_probability=0.50, line_index=2)
        d2 = _call(season_week=8, playoff_probability=0.50, line_index=2)
        assert d1.tts_line == d2.tts_line


# ---------------------------------------------------------------------------
# Decision dataclass shape
# ---------------------------------------------------------------------------

class TestDecisionShape:

    def test_decision_is_frozen(self):
        d = _call()
        with pytest.raises(Exception):
            d.tier = "hacked"  # type: ignore

    def test_decision_has_expected_fields(self):
        d = _call()
        assert hasattr(d, "tier")
        assert hasattr(d, "tts_line")
        assert hasattr(d, "sonos_hype_play")
        assert hasattr(d, "sonos_vibe")
