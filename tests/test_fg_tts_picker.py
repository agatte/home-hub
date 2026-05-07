"""Tests for backend.services.fg_tts_picker.

Covers distance-based pool selection (<50yd standard, ≥50yd big_kick),
None fallback, substitution placeholder integrity, and the
50-yard boundary specifically.
"""
from __future__ import annotations

import random

import pytest

from backend.services.fg_tts_picker import (
    BIG_KICK_THRESHOLD_YARDS,
    _POOLS,
    _pool_key_for_distance,
    pick_fg_tts,
)


class TestDistanceBranching:
    """The distance threshold determines which pool the line comes from."""

    def test_chip_shot_picks_standard(self):
        line = pick_fg_tts(yards=20, rng=random.Random(42))
        assert line in _POOLS["standard"]

    def test_45_yarder_picks_standard(self):
        # 45 < 50 threshold → standard
        line = pick_fg_tts(yards=45, rng=random.Random(42))
        assert line in _POOLS["standard"]

    def test_at_threshold_picks_big_kick(self):
        # 50 = threshold → big_kick
        line = pick_fg_tts(yards=50, rng=random.Random(42))
        assert line in _POOLS["big_kick"]

    def test_long_kick_picks_big_kick(self):
        line = pick_fg_tts(yards=58, rng=random.Random(42))
        assert line in _POOLS["big_kick"]

    def test_just_below_threshold(self):
        line = pick_fg_tts(yards=49, rng=random.Random(42))
        assert line in _POOLS["standard"]

    def test_none_yards_picks_standard(self):
        line = pick_fg_tts(yards=None, rng=random.Random(42))
        assert line in _POOLS["standard"]

    def test_unknown_yards_via_pool_key(self):
        # Direct call to the helper.
        assert _pool_key_for_distance(None) == "standard"
        assert _pool_key_for_distance(0) == "standard"
        assert _pool_key_for_distance(49) == "standard"
        assert _pool_key_for_distance(50) == "big_kick"
        assert _pool_key_for_distance(65) == "big_kick"


class TestPoolIntegrity:
    """Every authored line must carry the right substitution placeholders."""

    def test_every_standard_line_has_kicker_and_yards(self):
        for line in _POOLS["standard"]:
            assert "{kicker}" in line, f"Missing {{kicker}}: {line!r}"
            assert "{yards}" in line, f"Missing {{yards}}: {line!r}"

    def test_every_big_kick_line_has_kicker_and_yards(self):
        for line in _POOLS["big_kick"]:
            assert "{kicker}" in line, f"Missing {{kicker}}: {line!r}"
            assert "{yards}" in line, f"Missing {{yards}}: {line!r}"

    def test_pools_have_minimum_variants(self):
        # Avoid a future trim to fewer than 3 lines per pool — too small
        # a sample produces obvious repetition over a season.
        assert len(_POOLS["standard"]) >= 3, "standard pool too small"
        assert len(_POOLS["big_kick"]) >= 3, "big_kick pool too small"

    def test_threshold_is_documented_constant(self):
        # Future refactors that change the threshold should update tests.
        # Lock the current value here so a silent edit fails this test.
        assert BIG_KICK_THRESHOLD_YARDS == 50


class TestSubstitution:
    def test_format_map_substitutes_kicker_and_yards(self):
        line = pick_fg_tts(yards=42, rng=random.Random(0))
        substituted = line.format_map({"kicker": "Matt Gay", "yards": 42})
        assert "Matt Gay" in substituted
        assert "42" in substituted
        assert "{kicker}" not in substituted
        assert "{yards}" not in substituted

    def test_substitution_with_long_kick(self):
        line = pick_fg_tts(yards=55, rng=random.Random(7))
        substituted = line.format_map({"kicker": "Matt Gay", "yards": 55})
        assert "55" in substituted
        assert "Matt Gay" in substituted

    def test_no_double_spaces_after_substitution_with_real_yards(self):
        # Real ESPN play events always carry yardage. The picker doesn't
        # claim graceful substitution when yards is empty/None — every
        # standard-pool line references "{yards}" because real plays
        # always have it. Synthetic test fires with yards=None will
        # produce mildly awkward output ("from  yards") which is
        # acceptable for the rare synthetic-test path.
        for seed in range(20):
            for yards_val in (25, 50, 60):
                line = pick_fg_tts(yards=yards_val, rng=random.Random(seed))
                substituted = line.format_map({
                    "kicker": "Matt Gay",
                    "yards": yards_val,
                })
                assert substituted.strip() == substituted
                assert "  " not in substituted


class TestDeterminism:
    def test_seeded_rng_returns_same_line(self):
        rng_a = random.Random(123)
        rng_b = random.Random(123)
        line_a = pick_fg_tts(yards=42, rng=rng_a)
        line_b = pick_fg_tts(yards=42, rng=rng_b)
        assert line_a == line_b

    def test_module_rng_returns_a_string(self):
        line = pick_fg_tts(yards=42)
        assert isinstance(line, str)
        assert len(line) > 0
        assert "{kicker}" in line
        assert "{yards}" in line
