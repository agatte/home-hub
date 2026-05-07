"""Tests for backend.services.td_tts_picker.

Covers WPA-based pool selection (standard / big_play / game_changing),
threshold boundaries, sign-flipped WPA (Colts losing → negative WPA),
None fallback, and substitution placeholder integrity.
"""
from __future__ import annotations

import random

from backend.services.td_tts_picker import (
    BIG_PLAY_WPA_THRESHOLD,
    GAME_CHANGING_WPA_THRESHOLD,
    _POOLS,
    _pool_key_for_wpa,
    pick_td_tts,
)


class TestWpaBranching:
    """Pool selection by absolute WPA. Sign doesn't matter — a
    Colts-perspective losing team scoring a TD still gets the right
    energy tier from |WPA|."""

    def test_zero_wpa_picks_standard(self):
        assert _pool_key_for_wpa(0.0) == "standard"

    def test_small_positive_picks_standard(self):
        assert _pool_key_for_wpa(0.05) == "standard"

    def test_just_below_big_play_threshold(self):
        assert _pool_key_for_wpa(0.099) == "standard"

    def test_at_big_play_threshold_picks_big_play(self):
        assert _pool_key_for_wpa(0.10) == "big_play"

    def test_mid_big_play(self):
        assert _pool_key_for_wpa(0.15) == "big_play"

    def test_just_below_game_changing(self):
        assert _pool_key_for_wpa(0.199) == "big_play"

    def test_at_game_changing_threshold(self):
        assert _pool_key_for_wpa(0.20) == "game_changing"

    def test_huge_positive_wpa(self):
        assert _pool_key_for_wpa(0.45) == "game_changing"

    def test_negative_wpa_uses_absolute_value(self):
        # Colts losing perspective: a TD that bumps win-prob from 0.10
        # to 0.30 has WPA +0.20, but if Colts are AWAY and the formula
        # sign-flipped, the value could land negative. Picker uses |WPA|.
        assert _pool_key_for_wpa(-0.20) == "game_changing"
        assert _pool_key_for_wpa(-0.15) == "big_play"
        assert _pool_key_for_wpa(-0.05) == "standard"

    def test_none_picks_standard(self):
        assert _pool_key_for_wpa(None) == "standard"


class TestPickerSelection:
    def test_standard_pool_selected(self):
        line = pick_td_tts(wpa=0.05, rng=random.Random(42))
        assert line in _POOLS["standard"]

    def test_big_play_pool_selected(self):
        line = pick_td_tts(wpa=0.15, rng=random.Random(42))
        assert line in _POOLS["big_play"]

    def test_game_changing_pool_selected(self):
        line = pick_td_tts(wpa=0.30, rng=random.Random(42))
        assert line in _POOLS["game_changing"]

    def test_none_falls_back_to_standard(self):
        line = pick_td_tts(wpa=None, rng=random.Random(42))
        assert line in _POOLS["standard"]


class TestPoolIntegrity:
    def test_every_line_has_player_placeholder(self):
        for pool_key, lines in _POOLS.items():
            for line in lines:
                assert "{player}" in line, (
                    f"{pool_key}: missing {{player}}: {line!r}"
                )

    def test_no_yards_or_kicker_placeholders(self):
        # TD lines reference {player} only — never {yards} (that's FG)
        # or {kicker} (also FG).
        for pool_key, lines in _POOLS.items():
            for line in lines:
                assert "{yards}" not in line, (
                    f"{pool_key}: stray {{yards}}: {line!r}"
                )
                assert "{kicker}" not in line, (
                    f"{pool_key}: stray {{kicker}}: {line!r}"
                )

    def test_every_pool_has_minimum_lines(self):
        # Avoid future trims to fewer than 4 lines per pool — repetition
        # gets noticeable below that.
        for pool_key, lines in _POOLS.items():
            assert len(lines) >= 4, f"{pool_key} pool too small: {len(lines)}"

    def test_thresholds_locked(self):
        # Lock current threshold values so a silent edit fails this test.
        assert BIG_PLAY_WPA_THRESHOLD == 0.10
        assert GAME_CHANGING_WPA_THRESHOLD == 0.20

    def test_game_changing_has_caps_or_exclamation_energy(self):
        # Spot-check that the "huge swing" tier has actual energy.
        # At least 3 of the lines should contain ALL-CAPS or "!!" or
        # exclamation-heavy phrasing.
        energy_count = sum(
            1 for line in _POOLS["game_changing"]
            if any(token in line for token in ("ARE YOU", "TOUCHDOWN!", "!!", "Holy", "What a"))
        )
        assert energy_count >= 3, (
            f"game_changing pool needs more energy: {energy_count}/{len(_POOLS['game_changing'])} energetic lines"
        )


class TestSubstitution:
    def test_format_map_substitutes_player(self):
        line = pick_td_tts(wpa=0.15, rng=random.Random(0))
        substituted = line.format_map({"player": "Jonathan Taylor"})
        assert "Jonathan Taylor" in substituted
        assert "{player}" not in substituted

    def test_substitution_clean_across_seeds_and_tiers(self):
        for seed in range(20):
            for wpa_val in (0.05, 0.15, 0.30, None):
                line = pick_td_tts(wpa=wpa_val, rng=random.Random(seed))
                substituted = line.format_map({"player": "Jonathan Taylor"})
                assert substituted.strip() == substituted
                assert "  " not in substituted


class TestDeterminism:
    def test_seeded_rng_reproducible(self):
        rng_a = random.Random(99)
        rng_b = random.Random(99)
        assert pick_td_tts(wpa=0.15, rng=rng_a) == pick_td_tts(wpa=0.15, rng=rng_b)
