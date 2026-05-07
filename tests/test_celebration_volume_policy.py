"""
Tests for celebration_volume_policy.compute_celebration_volume.

Pure-function policy — no service mocks, just the inputs and expected
outputs. Covers:

  • WPA-driven scaling (4 bands).
  • Margin + clock fallback when WPA is None.
  • Hard suppressions (sleeping, DND, losing blowout).
  • Apartment-context modifiers (late-night cap, camera-absent -10).
  • Clamping at the [5, 50] floor/ceiling.
  • game_state=None synthetic-test path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from backend.services.celebration_volume_policy import (
    compute_celebration_volume,
)
from backend.services.gameday_service import GameDayState, PlayEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _play(
    *,
    play_type: str = "touchdown",
    wpa: Optional[float] = None,
) -> PlayEvent:
    return PlayEvent(
        timestamp=datetime.now(timezone.utc),
        play_type=play_type,  # type: ignore[arg-type]
        description="test",
        player="J. Taylor",
        kicker=None,
        yards=None,
        scoring_team="colts",
        wpa=wpa,
    )


def _state(
    *,
    score_colts: int = 14,
    score_opp: int = 7,
    quarter: int = 2,
    clock: str = "5:32",
) -> GameDayState:
    return GameDayState(
        status="in-progress",
        opponent="Houston Texans",
        kickoff_utc=datetime.now(timezone.utc),
        score_colts=score_colts,
        score_opp=score_opp,
        quarter=quarter,
        clock=clock,
        possession="colts",
        last_play=None,
    )


def _afternoon() -> datetime:
    """A "now" safely outside the late-night window — 14:00 Indy local
    (≈18:00 UTC during DST). Used by tests that don't care about the
    late-night cap."""
    return datetime(2026, 9, 15, 18, 0, 0, tzinfo=timezone.utc)


def _late_night() -> datetime:
    """23:30 Indy local (= 03:30 UTC next day during DST)."""
    return datetime(2026, 9, 16, 3, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# WPA-driven scaling (primary signal)
# ---------------------------------------------------------------------------

class TestWpaScaling:

    @pytest.mark.parametrize("wpa,expected_delta", [
        (0.30, 15),    # huge swing
        (-0.30, 15),   # |WPA| — sign doesn't matter, magnitude does
        (0.18, 10),    # big swing
        (0.08, 0),     # standard
        (0.02, -10),   # decided game / golf clap
    ])
    def test_wpa_band_modifiers(self, wpa, expected_delta):
        # base 30, no other modifiers
        vol = compute_celebration_volume(
            _play(wpa=wpa),
            _state(),
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 30 + expected_delta

    def test_huge_wpa_with_high_base_clamps_to_50(self):
        """Synthetic ceiling test: end_of_game_win base=35, +15 → 50."""
        vol = compute_celebration_volume(
            _play(wpa=0.40),
            _state(),
            base_volume=35,
            now=_afternoon(),
        )
        assert vol == 50  # clamped at _VOL_MAX

    def test_huge_wpa_above_ceiling_does_not_exceed(self):
        """base=40 + 15 → 55 → clamped to 50."""
        vol = compute_celebration_volume(
            _play(wpa=0.30),
            _state(),
            base_volume=40,
            now=_afternoon(),
        )
        assert vol == 50

    def test_wpa_signal_takes_precedence_over_fallback(self):
        """When WPA is present, margin+clock heuristic should NOT also fire.
        A close-game state with a tiny WPA = 0.02 should yield -10, not the
        fallback's +5 for one-score game."""
        vol = compute_celebration_volume(
            _play(wpa=0.02),
            _state(score_colts=14, score_opp=11),  # 3-point game
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 20  # 30 - 10 from WPA, fallback NOT applied


# ---------------------------------------------------------------------------
# Fallback: margin + clock (when WPA is None)
# ---------------------------------------------------------------------------

class TestMarginClockFallback:

    def test_clutch_q4_two_minute_drill(self):
        """Q4 + |margin|<=7 + <2:00 → +15."""
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=20, score_opp=17, quarter=4, clock="1:32"),
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 45

    def test_late_close_q4_no_two_minute(self):
        """Q4 + one-score (margin=4) + 8:00 → +10."""
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=20, score_opp=16, quarter=4, clock="8:14"),
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 40

    def test_one_score_any_quarter(self):
        """Any quarter + margin <= 3 (and not clutch Q4) → +5."""
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=14, score_opp=13, quarter=2, clock="5:00"),
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 35

    def test_winning_blowout_q4(self):
        """Q4 + margin >= 21 → -10 (lights still pop, audio dialed back)."""
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=42, score_opp=14, quarter=4, clock="3:00"),
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 20

    def test_standard_play_no_modifier(self):
        """Mid-game, normal margin → no bump or cut."""
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=14, score_opp=7, quarter=2, clock="10:00"),
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 30


# ---------------------------------------------------------------------------
# Hard suppressions
# ---------------------------------------------------------------------------

class TestSuppressions:

    def test_sleeping_mode_returns_none(self):
        vol = compute_celebration_volume(
            _play(wpa=0.30),
            _state(),
            base_volume=30,
            sleeping_mode=True,
            now=_afternoon(),
        )
        assert vol is None

    def test_dnd_active_returns_none(self):
        vol = compute_celebration_volume(
            _play(wpa=0.30),
            _state(),
            base_volume=30,
            dnd_active=True,
            now=_afternoon(),
        )
        assert vol is None

    def test_losing_blowout_q3_down_21_returns_none(self):
        """Q3, Colts down 21 → silent."""
        vol = compute_celebration_volume(
            _play(wpa=0.10),
            _state(score_colts=3, score_opp=24, quarter=3, clock="5:00"),
            base_volume=30,
            now=_afternoon(),
        )
        assert vol is None

    def test_losing_blowout_q4_down_28_returns_none(self):
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=7, score_opp=35, quarter=4, clock="2:00"),
            base_volume=30,
            now=_afternoon(),
        )
        assert vol is None

    def test_losing_q2_not_yet_blowout(self):
        """Down 21 in Q2 — early game, doesn't yet count as blowout.
        Margin-clock fallback applies normally."""
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=0, score_opp=21, quarter=2, clock="5:00"),
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 30  # standard, no bump

    def test_close_q3_not_blowout(self):
        """Q3 but only down 14 — not a blowout, normal volume."""
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=10, score_opp=24, quarter=3, clock="5:00"),
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 30


# ---------------------------------------------------------------------------
# Apartment-context modifiers
# ---------------------------------------------------------------------------

class TestApartmentModifiers:

    def test_late_night_caps_at_18(self):
        """11:30pm Indy local → cap at 18 even after a +15 huge-swing."""
        vol = compute_celebration_volume(
            _play(wpa=0.30),
            _state(),
            base_volume=30,
            now=_late_night(),
        )
        assert vol == 18

    def test_late_night_does_not_raise_low_volume(self):
        """Cap is min(vol, 18) — if vol was already 15 it stays 15, not 18."""
        vol = compute_celebration_volume(
            _play(wpa=0.02),  # -10 from base 30 → 20
            _state(),
            base_volume=20,  # 20 - 10 = 10
            now=_late_night(),
        )
        assert vol == 10  # min(10, 18) = 10

    def test_camera_absent_subtracts_10(self):
        vol = compute_celebration_volume(
            _play(wpa=0.08),  # standard, +0
            _state(),
            base_volume=30,
            camera_absent=True,
            now=_afternoon(),
        )
        assert vol == 20

    def test_camera_absent_floors_at_5(self):
        """Standard +0, base=10, -10 from camera = 0 → floored to 5."""
        vol = compute_celebration_volume(
            _play(wpa=0.08),
            _state(),
            base_volume=10,
            camera_absent=True,
            now=_afternoon(),
        )
        assert vol == 5

    def test_late_night_and_camera_absent_stack(self):
        """Cap to 18, then -10 from camera → 8."""
        vol = compute_celebration_volume(
            _play(wpa=0.30),
            _state(),
            base_volume=30,
            camera_absent=True,
            now=_late_night(),
        )
        # 30 + 15 = 45 → cap 18 → 18 - 10 = 8
        assert vol == 8


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_game_state_none_uses_base_only(self):
        """Synthetic test path — POST /api/gameday/test/touchdown emits
        a PlayEvent with no live state. Should fall through to base +
        apartment modifiers (no WPA path triggered)."""
        vol = compute_celebration_volume(
            _play(wpa=None),
            game_state=None,
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 30

    def test_game_state_none_with_wpa(self):
        """Synthetic path BUT a wpa was attached (unlikely but defined).
        WPA still applies."""
        vol = compute_celebration_volume(
            _play(wpa=0.30),
            game_state=None,
            base_volume=30,
            now=_afternoon(),
        )
        assert vol == 45

    def test_game_state_none_late_night_caps(self):
        vol = compute_celebration_volume(
            _play(wpa=None),
            game_state=None,
            base_volume=30,
            now=_late_night(),
        )
        assert vol == 18

    def test_unparseable_clock_falls_through(self):
        """Garbage clock string → fallback skips clutch/late branches and
        uses one-score band only when margin <= 3."""
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=14, score_opp=14, quarter=4, clock="???"),
            base_volume=30,
            now=_afternoon(),
        )
        # Q4 + margin=0 (<=7) → +10 (close-game branch fires without
        # needing the clock). +5 close-game also matches but Q4 close
        # branch wins as it's checked first.
        assert vol == 40

    def test_now_is_none_skips_late_night_cap(self):
        """When `now` is None (caller didn't pass it), the late-night cap
        is conservatively skipped — better than capping at the wrong time."""
        vol = compute_celebration_volume(
            _play(wpa=0.30),
            _state(),
            base_volume=30,
            now=None,
        )
        assert vol == 45  # no cap applied


# ---------------------------------------------------------------------------
# Suppression precedence
# ---------------------------------------------------------------------------

class TestSuppressionPrecedence:
    """Hard suppressions are checked in order — sleeping, DND, blowout.
    Any one of them returns None regardless of the others."""

    def test_sleeping_wins_over_huge_wpa(self):
        vol = compute_celebration_volume(
            _play(wpa=0.30),
            _state(),
            sleeping_mode=True,
            now=_afternoon(),
        )
        assert vol is None

    def test_dnd_wins_over_close_game(self):
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=14, score_opp=14, quarter=4, clock="0:30"),
            dnd_active=True,
            now=_afternoon(),
        )
        assert vol is None

    def test_blowout_silent_even_with_late_night_cap(self):
        """Late-night cap is irrelevant once we've decided to suppress."""
        vol = compute_celebration_volume(
            _play(wpa=None),
            _state(score_colts=3, score_opp=42, quarter=4, clock="0:30"),
            now=_late_night(),
        )
        assert vol is None
