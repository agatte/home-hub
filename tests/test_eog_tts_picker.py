"""Tests for backend.services.eog_tts_picker.

Covers margin-based pool selection (close ≤ 7, comfortable > 7),
threshold boundaries, defensive negative-margin fallback, and
substitution placeholder integrity.
"""
from __future__ import annotations

import random

from backend.services.eog_tts_picker import (
    CLOSE_WIN_MARGIN,
    _POOLS,
    _pool_key_for_margin,
    pick_eog_win_tts,
)


class TestMarginBranching:
    def test_one_point_win_picks_close(self):
        assert _pool_key_for_margin(21, 20) == "close"

    def test_seven_point_win_at_threshold_picks_close(self):
        assert _pool_key_for_margin(21, 14) == "close"

    def test_eight_point_win_picks_comfortable(self):
        assert _pool_key_for_margin(28, 20) == "comfortable"

    def test_blowout_picks_comfortable(self):
        assert _pool_key_for_margin(45, 10) == "comfortable"

    def test_zero_margin_falls_back_to_close(self):
        # Defensive — orchestrator routes losses (Colts lose) to
        # EOG_LOSS, so this code path shouldn't fire on a tied/lost
        # game. If it does, "close" is the safe default.
        assert _pool_key_for_margin(20, 20) == "close"

    def test_negative_margin_falls_back_to_close(self):
        # Same defense: orchestrator routes losses elsewhere.
        assert _pool_key_for_margin(14, 21) == "close"

    def test_threshold_is_documented_constant(self):
        # Lock the value so silent edits surface in CI.
        assert CLOSE_WIN_MARGIN == 7


class TestPickerSelection:
    def test_close_win_uses_close_pool(self):
        line = pick_eog_win_tts(colts_score=24, opp_score=21, rng=random.Random(42))
        assert line in _POOLS["close"]

    def test_comfortable_win_uses_comfortable_pool(self):
        line = pick_eog_win_tts(colts_score=35, opp_score=14, rng=random.Random(42))
        assert line in _POOLS["comfortable"]

    def test_walkoff_one_point_uses_close_pool(self):
        line = pick_eog_win_tts(colts_score=27, opp_score=26, rng=random.Random(99))
        assert line in _POOLS["close"]


class TestPoolIntegrity:
    def test_every_line_has_score_placeholders(self):
        for pool_key, lines in _POOLS.items():
            for line in lines:
                assert "{colts_score}" in line, (
                    f"{pool_key}: missing {{colts_score}}: {line!r}"
                )
                assert "{opp_score}" in line, (
                    f"{pool_key}: missing {{opp_score}}: {line!r}"
                )

    def test_every_pool_has_minimum_lines(self):
        for pool_key, lines in _POOLS.items():
            assert len(lines) >= 4, (
                f"{pool_key} pool too small: {len(lines)} lines"
            )

    def test_close_pool_has_high_energy_token(self):
        # Spot-check: close pool should have at least some "what a
        # game" / energy phrasing (not a flat statement of facts).
        energy = sum(
            1 for line in _POOLS["close"]
            if any(t in line for t in ("Way to go", "What a", "earned", "grind", "holds on"))
        )
        assert energy >= 3, (
            f"close pool needs more energy: {energy}/{len(_POOLS['close'])} energetic lines"
        )

    def test_comfortable_pool_is_measured(self):
        # Spot-check: comfortable pool shouldn't have ALL-CAPS or
        # hyperbolic energy ("ARE YOU KIDDING ME") — those belong in
        # the TD game_changing pool, not EOG comfortable wins.
        for line in _POOLS["comfortable"]:
            assert "!!" not in line, (
                f"Comfortable pool too hot: {line!r}"
            )
            assert "ARE YOU" not in line


class TestSubstitution:
    def test_format_map_substitutes_scores_and_opponent(self):
        line = pick_eog_win_tts(colts_score=27, opp_score=24, rng=random.Random(0))
        substituted = line.format_map({
            "colts_score": 27,
            "opp_score": 24,
            "opponent": "Houston Texans",
        })
        assert "27" in substituted
        assert "24" in substituted
        assert "{colts_score}" not in substituted
        assert "{opp_score}" not in substituted

    def test_substitution_clean_across_seeds_and_margins(self):
        for seed in range(15):
            for margin in (3, 7, 8, 21):
                line = pick_eog_win_tts(
                    colts_score=20 + margin,
                    opp_score=20,
                    rng=random.Random(seed),
                )
                substituted = line.format_map({
                    "colts_score": 20 + margin,
                    "opp_score": 20,
                    "opponent": "Houston Texans",
                })
                assert substituted.strip() == substituted
                assert "  " not in substituted


class TestDeterminism:
    def test_seeded_rng_reproducible(self):
        rng_a = random.Random(42)
        rng_b = random.Random(42)
        assert pick_eog_win_tts(colts_score=24, opp_score=21, rng=rng_a) == \
            pick_eog_win_tts(colts_score=24, opp_score=21, rng=rng_b)
