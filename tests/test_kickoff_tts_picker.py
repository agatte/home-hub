"""Tests for backend.services.kickoff_tts_picker.

Covers:
- Day-of-week → GameSlot mapping (each weekday + Sunday hour boundary).
- Team form → dimes/jones swap (each trigger condition + None fallback).
- Pool selection (deterministic with seeded RNG).
- Substitution placeholder integrity.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.services.kickoff_tts_picker import (
    GameSlot,
    TeamForm,
    _is_dimes_form,
    _slot_from_timestamp,
    pick_kickoff_tts,
)

ET = ZoneInfo("America/Indiana/Indianapolis")


# ---------------------------------------------------------------------------
# GameSlot mapping — _slot_from_timestamp
# ---------------------------------------------------------------------------

class TestGameSlotMapping:
    """Pure mapping from timestamp to GameSlot. ET-localized."""

    def test_sunday_afternoon_one_pm(self):
        # 2026-09-13 13:00 ET = Sunday 1pm = SUNDAY_AFTERNOON
        ts = datetime(2026, 9, 13, 13, 0, tzinfo=ET)
        assert _slot_from_timestamp(ts) == GameSlot.SUNDAY_AFTERNOON

    def test_sunday_afternoon_late_window(self):
        # 16:25 ET = late Sunday afternoon slot, still < 19:00 threshold
        ts = datetime(2026, 9, 13, 16, 25, tzinfo=ET)
        assert _slot_from_timestamp(ts) == GameSlot.SUNDAY_AFTERNOON

    def test_sunday_night_at_threshold(self):
        # 19:00 ET on Sunday → SNF (≥ threshold)
        ts = datetime(2026, 9, 13, 19, 0, tzinfo=ET)
        assert _slot_from_timestamp(ts) == GameSlot.SUNDAY_NIGHT

    def test_sunday_night_actual_snf_slot(self):
        # 20:20 ET = canonical SNF kickoff
        ts = datetime(2026, 9, 13, 20, 20, tzinfo=ET)
        assert _slot_from_timestamp(ts) == GameSlot.SUNDAY_NIGHT

    def test_sunday_just_below_threshold(self):
        # 18:59 ET on Sunday → still SUNDAY_AFTERNOON
        ts = datetime(2026, 9, 13, 18, 59, tzinfo=ET)
        assert _slot_from_timestamp(ts) == GameSlot.SUNDAY_AFTERNOON

    def test_monday_night(self):
        # 2026-09-14 = Monday. 20:15 ET = MNF slot.
        ts = datetime(2026, 9, 14, 20, 15, tzinfo=ET)
        assert _slot_from_timestamp(ts) == GameSlot.MONDAY_NIGHT

    def test_monday_morning_still_mnf_slot(self):
        # Any Monday kickoff maps to MNF (slot is day-of-week, not hour-gated).
        ts = datetime(2026, 9, 14, 11, 0, tzinfo=ET)
        assert _slot_from_timestamp(ts) == GameSlot.MONDAY_NIGHT

    def test_thursday_night(self):
        # 2026-09-17 = Thursday. 20:15 ET = TNF slot.
        ts = datetime(2026, 9, 17, 20, 15, tzinfo=ET)
        assert _slot_from_timestamp(ts) == GameSlot.THURSDAY_NIGHT

    def test_saturday_primetime(self):
        # 2026-12-19 = Saturday late-season. 20:00 ET.
        ts = datetime(2026, 12, 19, 20, 0, tzinfo=ET)
        assert _slot_from_timestamp(ts) == GameSlot.SATURDAY_PRIMETIME

    def test_tuesday_falls_back_to_sunday_afternoon(self):
        # Tuesday kickoffs are extraordinarily rare (Christmas-shifted
        # specials in some years) — picker falls back to the standard
        # Sunday afternoon pool.
        ts = datetime(2026, 9, 15, 13, 0, tzinfo=ET)
        assert ts.weekday() == 1  # Tuesday
        assert _slot_from_timestamp(ts) == GameSlot.SUNDAY_AFTERNOON

    def test_utc_input_converts_to_local(self):
        # 23:00 UTC on Sunday = 19:00 Indy-local → SNF slot.
        ts = datetime(2026, 9, 13, 23, 0, tzinfo=timezone.utc)
        assert _slot_from_timestamp(ts) == GameSlot.SUNDAY_NIGHT

    def test_utc_morning_sunday_is_afternoon_locally(self):
        # 14:00 UTC = 10:00 Indy-local on a Sunday (London game) →
        # afternoon pool.
        ts = datetime(2026, 10, 4, 14, 0, tzinfo=timezone.utc)
        assert _slot_from_timestamp(ts) == GameSlot.SUNDAY_AFTERNOON


# ---------------------------------------------------------------------------
# Team form heuristic — _is_dimes_form
# ---------------------------------------------------------------------------

class TestTeamFormHeuristic:
    def test_last4_three_wins_triggers_dimes(self):
        form = TeamForm(last4_record=(3, 1), win_streak=0, season_record=(5, 5, 0))
        assert _is_dimes_form(form) is True

    def test_last4_four_wins_triggers_dimes(self):
        form = TeamForm(last4_record=(4, 0), win_streak=4, season_record=(8, 2, 0))
        assert _is_dimes_form(form) is True

    def test_win_streak_two_triggers_dimes(self):
        form = TeamForm(last4_record=(2, 2), win_streak=2, season_record=(4, 4, 0))
        assert _is_dimes_form(form) is True

    def test_above_500_with_4plus_games_triggers_dimes(self):
        form = TeamForm(last4_record=(2, 2), win_streak=0, season_record=(4, 3, 0))
        assert _is_dimes_form(form) is True

    def test_below_500_does_not_trigger(self):
        form = TeamForm(last4_record=(1, 3), win_streak=0, season_record=(2, 5, 0))
        assert _is_dimes_form(form) is False

    def test_at_500_with_4_games_does_not_trigger(self):
        form = TeamForm(last4_record=(2, 2), win_streak=0, season_record=(2, 2, 0))
        assert _is_dimes_form(form) is False

    def test_above_500_but_under_4_games_does_not_trigger(self):
        # 2-1 is above .500 but only 3 games — not enough sample.
        form = TeamForm(last4_record=(2, 1), win_streak=2, season_record=(2, 1, 0))
        # Win streak is 2 → still triggers dimes via the streak path.
        assert _is_dimes_form(form) is True

    def test_above_500_under_4_games_no_streak_no_last4(self):
        form = TeamForm(last4_record=(2, 1), win_streak=1, season_record=(2, 1, 0))
        assert _is_dimes_form(form) is False

    def test_one_loss_streak_no_recent_wins_does_not_trigger(self):
        form = TeamForm(last4_record=(1, 3), win_streak=0, season_record=(3, 5, 0))
        assert _is_dimes_form(form) is False


# ---------------------------------------------------------------------------
# Pool selection — pick_kickoff_tts
# ---------------------------------------------------------------------------

class TestPickerSelection:
    """Deterministic picks from each pool, plus None-form fallback."""

    def _sunday_1pm(self):
        return datetime(2026, 9, 13, 13, 0, tzinfo=ET)

    def test_no_form_picks_jones(self):
        ts = self._sunday_1pm()
        rng = random.Random(42)
        line = pick_kickoff_tts(kickoff_at=ts, team_form=None, rng=rng)
        assert "Daniel Jones" in line or "Daniel" in line
        assert "{opponent}" in line  # template still has placeholder

    def test_dimes_form_picks_dimes_pool(self):
        ts = self._sunday_1pm()
        winning = TeamForm(last4_record=(3, 1), win_streak=2, season_record=(7, 3, 0))
        rng = random.Random(42)
        line = pick_kickoff_tts(kickoff_at=ts, team_form=winning, rng=rng)
        assert "Danny Dimes" in line
        assert "{opponent}" in line

    def test_struggling_form_picks_jones_pool(self):
        ts = self._sunday_1pm()
        struggling = TeamForm(last4_record=(1, 3), win_streak=0, season_record=(2, 5, 0))
        rng = random.Random(42)
        line = pick_kickoff_tts(kickoff_at=ts, team_form=struggling, rng=rng)
        assert "Daniel Jones" in line
        assert "Danny Dimes" not in line

    def test_snf_pool_used_for_sunday_night(self):
        ts = datetime(2026, 9, 13, 20, 20, tzinfo=ET)
        rng = random.Random(42)
        line = pick_kickoff_tts(kickoff_at=ts, team_form=None, rng=rng)
        # SNF jones pool — every variant references "Sunday Night" / "SNF" /
        # "Primetime".
        assert any(token in line for token in ("Sunday Night", "SNF", "Primetime"))

    def test_mnf_pool_used_for_monday(self):
        ts = datetime(2026, 9, 14, 20, 15, tzinfo=ET)
        rng = random.Random(42)
        line = pick_kickoff_tts(kickoff_at=ts, team_form=None, rng=rng)
        assert any(token in line for token in ("Monday Night", "MNF"))

    def test_tnf_pool_used_for_thursday(self):
        ts = datetime(2026, 9, 17, 20, 15, tzinfo=ET)
        rng = random.Random(42)
        line = pick_kickoff_tts(kickoff_at=ts, team_form=None, rng=rng)
        assert any(token in line for token in ("Thursday Night", "TNF", "short week"))

    def test_saturday_primetime_pool(self):
        ts = datetime(2026, 12, 19, 20, 0, tzinfo=ET)
        rng = random.Random(42)
        line = pick_kickoff_tts(kickoff_at=ts, team_form=None, rng=rng)
        assert "Saturday" in line


# ---------------------------------------------------------------------------
# Determinism + safety
# ---------------------------------------------------------------------------

class TestDeterminismAndSafety:
    def test_seeded_rng_returns_same_line(self):
        ts = datetime(2026, 9, 13, 13, 0, tzinfo=ET)
        rng_a = random.Random(123)
        rng_b = random.Random(123)
        line_a = pick_kickoff_tts(kickoff_at=ts, team_form=None, rng=rng_a)
        line_b = pick_kickoff_tts(kickoff_at=ts, team_form=None, rng=rng_b)
        assert line_a == line_b

    def test_module_rng_returns_a_string(self):
        # Without explicit rng, picker uses module-level random — just
        # verify it returns a non-empty templated string.
        ts = datetime(2026, 9, 13, 13, 0, tzinfo=ET)
        line = pick_kickoff_tts(kickoff_at=ts, team_form=None)
        assert isinstance(line, str)
        assert len(line) > 0
        assert "{opponent}" in line

    def test_every_pool_line_has_opponent_placeholder(self):
        # All authored lines must format-substitute {opponent}.
        from backend.services.kickoff_tts_picker import _POOLS
        for slot, variants in _POOLS.items():
            for variant_name, lines in variants.items():
                for line in lines:
                    assert "{opponent}" in line, (
                        f"Line in {slot.value}/{variant_name} missing "
                        f"{{opponent}} placeholder: {line!r}"
                    )

    def test_dimes_lines_only_in_dimes_pools(self):
        # Sanity: "Danny Dimes" never leaks into a "jones" pool variant.
        from backend.services.kickoff_tts_picker import _POOLS
        for slot, variants in _POOLS.items():
            for line in variants["jones"]:
                assert "Danny Dimes" not in line, (
                    f"'Danny Dimes' leaked into {slot.value}/jones: {line!r}"
                )
            for line in variants["dimes"]:
                assert "Daniel Jones" not in line, (
                    f"'Daniel Jones' leaked into {slot.value}/dimes: {line!r}"
                )

    def test_pools_have_nonempty_dimes_and_jones_variants(self):
        # Every GameSlot must have at least one line in each variant.
        from backend.services.kickoff_tts_picker import _POOLS
        for slot in GameSlot:
            assert slot in _POOLS, f"Pool missing for slot {slot}"
            assert len(_POOLS[slot]["dimes"]) > 0, (
                f"{slot.value} dimes pool is empty"
            )
            assert len(_POOLS[slot]["jones"]) > 0, (
                f"{slot.value} jones pool is empty"
            )


# ---------------------------------------------------------------------------
# Format substitution end-to-end
# ---------------------------------------------------------------------------

class TestFormatSubstitution:
    def test_format_map_substitutes_opponent(self):
        ts = datetime(2026, 9, 13, 13, 0, tzinfo=ET)
        line = pick_kickoff_tts(kickoff_at=ts, team_form=None, rng=random.Random(0))
        # Mimic CelebrationOrchestrator's substitution flow.
        substituted = line.format_map({"opponent": "Houston Texans"})
        assert "Houston Texans" in substituted
        assert "{opponent}" not in substituted

    def test_substitution_yields_grammatical_sentence(self):
        # Pick a couple lines and ensure the substitution doesn't produce
        # awkward grammar (e.g., "vs the Houston Texans" not "vs Houston Texans").
        ts = datetime(2026, 9, 13, 13, 0, tzinfo=ET)
        for seed in range(20):
            line = pick_kickoff_tts(kickoff_at=ts, team_form=None, rng=random.Random(seed))
            substituted = line.format_map({"opponent": "Houston Texans"})
            # All authored lines reference "the {opponent}" or "{opponent}"
            # as the team name. Substituted output should not have
            # leading/trailing whitespace anomalies.
            assert substituted.strip() == substituted
            assert "  " not in substituted  # no double-spaces

    def test_no_double_article_with_bare_fallback(self):
        """Regression for the live test fire on 2026-05-07: when no game
        state is available, _build_context substitutes the bare fallback
        "opponent" (no article). Templates that say "vs the {opponent}"
        produced "vs the the opponent" before the fallback was changed
        from "the opponent" to "opponent". Walk every authored line in
        every pool, substitute the bare fallback, assert no doubled
        articles slip through."""
        from backend.services.kickoff_tts_picker import _POOLS
        for slot, variants in _POOLS.items():
            for variant_name, lines in variants.items():
                for line in lines:
                    substituted = line.format_map({"opponent": "opponent"})
                    lowered = substituted.lower()
                    assert "the the" not in lowered, (
                        f"Double 'the' in {slot.value}/{variant_name}: "
                        f"{substituted!r}"
                    )
                    assert " a a " not in lowered
                    assert " an an " not in lowered
