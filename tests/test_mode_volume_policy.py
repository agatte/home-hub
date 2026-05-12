"""
Tests for mode_volume_policy.compute_mode_volume.

Pure-function policy — no service mocks, just inputs and expected outputs.
Mirrors the structure of tests/test_celebration_volume_policy.py.
"""
from __future__ import annotations

import pytest

from backend.services.mode_volume_policy import (
    MODE_VOLUME_DEFAULTS,
    VolumeDecision,
    compute_mode_volume,
)


# ---------------------------------------------------------------------------
# Default-curve resolution
# ---------------------------------------------------------------------------

class TestDefaults:

    @pytest.mark.parametrize("mode,period,expected", [
        ("gaming",   "day",     25),
        ("gaming",   "evening", 22),
        ("gaming",   "night",   18),
        ("working",  "day",     12),
        ("working",  "evening", 12),
        ("working",  "night",   10),
        ("watching", "day",     22),
        ("watching", "night",   18),
        ("relax",    "day",     18),
        ("relax",    "evening", 16),
        ("relax",    "night",   14),
        ("social",   "day",     30),
        ("cooking",  "evening", 22),
        ("gameday",  "night",   30),
    ])
    def test_each_default_resolves(self, mode, period, expected):
        decision = compute_mode_volume(
            mode,
            time_period=period,
            dnd=False,
            current_volume=0,
        )
        assert decision.target == expected
        assert decision.skip is False
        assert decision.fade_steps >= 1

    def test_late_night_aliases_to_night(self):
        d_night = compute_mode_volume("gaming", time_period="night", dnd=False, current_volume=0)
        d_late = compute_mode_volume("gaming", time_period="late_night", dnd=False, current_volume=0)
        assert d_late.target == d_night.target


# ---------------------------------------------------------------------------
# DND suppression
# ---------------------------------------------------------------------------

class TestDND:

    def test_dnd_skips_with_reason(self):
        decision = compute_mode_volume(
            "gaming",
            time_period="day",
            dnd=True,
            current_volume=12,
        )
        assert decision.skip is True
        assert decision.reason == "dnd"
        # When skipped, target should be the current volume (no-op contract).
        assert decision.target == 12

    def test_dnd_does_not_suppress_sleeping(self):
        """Sleeping wins over DND — bedtime always silences."""
        decision = compute_mode_volume(
            "sleeping",
            time_period="night",
            dnd=True,
            current_volume=20,
        )
        assert decision.skip is False
        assert decision.target == 0
        assert decision.reason == "sleeping_force_silence"


# ---------------------------------------------------------------------------
# Sleeping always silences
# ---------------------------------------------------------------------------

class TestSleeping:

    def test_sleeping_forces_zero(self):
        decision = compute_mode_volume(
            "sleeping",
            time_period="night",
            dnd=False,
            current_volume=30,
        )
        assert decision.target == 0
        assert decision.skip is False

    def test_sleeping_at_zero_already_skips(self):
        decision = compute_mode_volume(
            "sleeping",
            time_period="night",
            dnd=False,
            current_volume=0,
        )
        assert decision.skip is True
        assert decision.reason == "already_at_target"
        assert decision.target == 0


# ---------------------------------------------------------------------------
# Unknown / un-curved modes
# ---------------------------------------------------------------------------

class TestUnknownModes:

    def test_idle_has_no_curve(self):
        """idle is intentionally absent from defaults — Sonos left alone."""
        decision = compute_mode_volume(
            "idle",
            time_period="day",
            dnd=False,
            current_volume=22,
        )
        assert decision.skip is True
        assert decision.reason == "no_curve"
        assert decision.target == 22  # unchanged

    def test_garbage_mode_skipped(self):
        decision = compute_mode_volume(
            "not_a_real_mode",
            time_period="day",
            dnd=False,
            current_volume=15,
        )
        assert decision.skip is True
        assert decision.reason == "no_curve"


# ---------------------------------------------------------------------------
# Already-at-target short-circuit
# ---------------------------------------------------------------------------

class TestAlreadyAtTarget:

    def test_target_equals_current_skips(self):
        decision = compute_mode_volume(
            "gaming",
            time_period="day",  # target 25
            dnd=False,
            current_volume=25,
        )
        assert decision.skip is True
        assert decision.reason == "already_at_target"

    def test_target_just_off_does_not_skip(self):
        decision = compute_mode_volume(
            "gaming",
            time_period="day",
            dnd=False,
            current_volume=24,
        )
        assert decision.skip is False
        assert decision.target == 25


# ---------------------------------------------------------------------------
# Custom config overrides defaults
# ---------------------------------------------------------------------------

class TestCustomConfig:

    def test_persisted_override_wins_per_mode(self):
        custom = {
            "gaming": {"day": 40, "evening": 35, "night": 28, "fade_duration_s": 3},
        }
        decision = compute_mode_volume(
            "gaming",
            time_period="day",
            dnd=False,
            current_volume=0,
            config=custom,
        )
        assert decision.target == 40

    def test_partial_override_falls_back_per_key(self):
        """Override `day` only — `evening` and `night` still resolve from defaults."""
        custom = {"gaming": {"day": 40}}
        decision_day = compute_mode_volume(
            "gaming", time_period="day", dnd=False, current_volume=0, config=custom,
        )
        decision_night = compute_mode_volume(
            "gaming", time_period="night", dnd=False, current_volume=0, config=custom,
        )
        assert decision_day.target == 40  # overridden
        assert decision_night.target == 18  # default

    def test_unrelated_mode_unaffected(self):
        custom = {"gaming": {"day": 99}}
        decision = compute_mode_volume(
            "working", time_period="day", dnd=False, current_volume=0, config=custom,
        )
        assert decision.target == 12  # working default

    def test_target_clamped_above_100(self):
        """Defensive — even if config has a bogus high value, we clamp."""
        custom = {"gaming": {"day": 250}}
        decision = compute_mode_volume(
            "gaming", time_period="day", dnd=False, current_volume=0, config=custom,
        )
        assert 0 <= decision.target <= 100

    def test_config_adds_unknown_mode(self):
        """A new mode not in defaults can be added via config."""
        custom = {
            "custom_mode": {"day": 15, "evening": 12, "night": 10, "fade_duration_s": 4},
        }
        decision = compute_mode_volume(
            "custom_mode",
            time_period="day",
            dnd=False,
            current_volume=0,
            config=custom,
        )
        assert decision.target == 15
        assert decision.skip is False


# ---------------------------------------------------------------------------
# Decision shape
# ---------------------------------------------------------------------------

class TestDecisionShape:

    def test_returns_volume_decision(self):
        decision = compute_mode_volume(
            "gaming", time_period="day", dnd=False, current_volume=0,
        )
        assert isinstance(decision, VolumeDecision)
        assert isinstance(decision.target, int)
        assert isinstance(decision.fade_steps, int)
        assert isinstance(decision.fade_interval, float)
        assert isinstance(decision.skip, bool)
        assert isinstance(decision.reason, str)

    def test_fade_shape_respects_duration(self):
        """5s duration → roughly 5 steps × 1s — adjust if _shape changes."""
        decision = compute_mode_volume(
            "gaming",  # fade_duration_s=5
            time_period="day",
            dnd=False,
            current_volume=0,
        )
        # Step count and interval should multiply back to roughly the duration.
        approx_duration = decision.fade_steps * decision.fade_interval
        assert 4.5 <= approx_duration <= 5.5


# ---------------------------------------------------------------------------
# Defaults sanity check (smoke)
# ---------------------------------------------------------------------------

def test_all_defaults_have_required_keys():
    required = {"day", "evening", "night", "fade_duration_s"}
    for mode, curve in MODE_VOLUME_DEFAULTS.items():
        assert required.issubset(curve.keys()), f"{mode} missing keys"
        for key in ("day", "evening", "night"):
            assert 0 <= curve[key] <= 100, f"{mode}.{key} out of range"
        assert 1 <= curve["fade_duration_s"] <= 30


def test_sleeping_default_is_zero():
    for key in ("day", "evening", "night"):
        assert MODE_VOLUME_DEFAULTS["sleeping"][key] == 0
