"""
Unit tests for the pure light-state calculator.

These hit the calculator module directly — no engine construction,
no mocked services. The engine retains thin shims that delegate
here, so behavior in production is whatever these tests assert.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.services.light_state_calculator import (
    ACTIVITY_LIGHT_STATES,
    BED_RECLINED_L1_NIGHT_DEFAULT,
    DEFAULT_MODE_BRIGHTNESS,
    LUX_MULT_EPSILON,
    TZ,
    apply_brightness_multiplier,
    apply_lux_multiplier,
    apply_weather_adjust,
    apply_zone_overlay,
    classify_weather,
    get_time_period,
    is_zone_posture_freshness_ok,
    resolve_activity_state,
)
from backend.services.automation_engine import DaySchedule, ScheduleConfig


# ---------------------------------------------------------------------------
# get_time_period — schedule-aware
# ---------------------------------------------------------------------------


@pytest.fixture
def schedule():
    """Default weekday/weekend schedule used in production."""
    return ScheduleConfig()


class TestGetTimePeriod:
    """``get_time_period`` honors weekday vs weekend boundaries."""

    def test_weekday_morning_is_day(self, schedule):
        # Monday 10am — past the ramp window, before evening.
        now = datetime(2026, 4, 13, 10, 0, tzinfo=TZ)
        assert get_time_period(schedule, now) == "day"

    def test_weekday_evening_is_evening(self, schedule):
        now = datetime(2026, 4, 13, 19, 0, tzinfo=TZ)
        assert get_time_period(schedule, now) == "evening"

    def test_weekday_winddown_is_night(self, schedule):
        now = datetime(2026, 4, 13, 22, 0, tzinfo=TZ)
        assert get_time_period(schedule, now) == "night"

    def test_weekday_late_night_after_23(self, schedule):
        now = datetime(2026, 4, 13, 23, 30, tzinfo=TZ)
        assert get_time_period(schedule, now) == "late_night"

    def test_weekday_pre_dawn_is_late_night(self, schedule):
        # 03:00 wraps into the late_night window (≥23 OR <wake_hour).
        now = datetime(2026, 4, 14, 3, 0, tzinfo=TZ)
        assert get_time_period(schedule, now) == "late_night"

    def test_weekend_ramp_window_is_day(self, schedule):
        # Saturday 09:00, weekend ramp 08:00 + 120min.
        now = datetime(2026, 4, 18, 9, 0, tzinfo=TZ)
        assert get_time_period(schedule, now) == "day"


# ---------------------------------------------------------------------------
# resolve_activity_state — lookup + late_night fallback
# ---------------------------------------------------------------------------


class TestResolveActivityState:
    """Mode + period → per-light state dict."""

    def test_known_mode_period(self):
        state = resolve_activity_state("working", "day")
        assert state == ACTIVITY_LIGHT_STATES["working"]["day"]

    def test_late_night_falls_back_to_night(self):
        # Cooking has no late_night entry; should return its night state.
        state = resolve_activity_state("cooking", "late_night")
        assert state == ACTIVITY_LIGHT_STATES["cooking"]["night"]

    def test_late_night_uses_explicit_when_defined(self):
        # Relax has its own late_night entry — should NOT fall back.
        state = resolve_activity_state("relax", "late_night")
        assert state == ACTIVITY_LIGHT_STATES["relax"]["late_night"]
        assert state != ACTIVITY_LIGHT_STATES["relax"]["night"]

    def test_working_late_night_is_distinct(self):
        """Working has a true late_night state — warm + functional, kitchen off."""
        state = resolve_activity_state("working", "late_night")
        night = resolve_activity_state("working", "night")
        assert state != night
        # L1: brighter than night (90 vs 60), warmer (ct 454)
        assert state["1"]["bri"] == 90
        assert state["1"]["ct"] == 454
        # L2: brighter than night (160 vs 130)
        assert state["2"]["bri"] == 160
        assert state["2"]["ct"] == 400
        # Kitchen stays off — desk-only late-night functional lighting.
        assert state["3"]["on"] is False
        assert state["4"]["on"] is False

    def test_flat_mode_ignores_period(self):
        # Social is flat — no period dimension. Returns the same dict.
        assert resolve_activity_state("social", "day") == ACTIVITY_LIGHT_STATES["social"]
        assert resolve_activity_state("social", "night") == ACTIVITY_LIGHT_STATES["social"]

    def test_unknown_mode_returns_empty(self):
        assert resolve_activity_state("nonexistent_mode") == {}


# ---------------------------------------------------------------------------
# apply_brightness_multiplier — pure scaling
# ---------------------------------------------------------------------------


class TestApplyBrightnessMultiplier:

    def test_unity_multiplier_noop(self):
        state = {"1": {"on": True, "bri": 200, "ct": 300}}
        out = apply_brightness_multiplier(state, "working", {"working": 1.0})
        assert out == state

    def test_per_light_dict_scales_each(self):
        state = {
            "1": {"on": True, "bri": 200, "ct": 300},
            "2": {"on": True, "bri": 100, "ct": 300},
        }
        out = apply_brightness_multiplier(state, "working", {"working": 0.5})
        assert out["1"]["bri"] == 100
        assert out["2"]["bri"] == 50

    def test_off_light_brightness_untouched(self):
        state = {"1": {"on": False}, "2": {"on": True, "bri": 100}}
        out = apply_brightness_multiplier(state, "working", {"working": 2.0})
        assert "bri" not in out["1"]
        assert out["2"]["bri"] == 200

    def test_clamps_to_valid_range(self):
        state = {"1": {"on": True, "bri": 200}}
        out = apply_brightness_multiplier(state, "working", {"working": 5.0})
        assert out["1"]["bri"] == 254  # Clamped, not 1000.

    def test_default_unity_when_mode_missing(self):
        state = {"1": {"on": True, "bri": 100}}
        # Mode not in the dict — defaults to 1.0 (no-op).
        out = apply_brightness_multiplier(state, "unknown", {})
        assert out == state


# ---------------------------------------------------------------------------
# apply_lux_multiplier — hysteresis state owned by caller
# ---------------------------------------------------------------------------


class TestApplyLuxMultiplier:

    def test_non_lux_mode_noop(self):
        # Only working / relax adapt; gaming bypasses.
        state = {"1": {"on": True, "bri": 200}}
        out_state, out_mult = apply_lux_multiplier(state, "gaming", 50.0, 1.0)
        assert out_state is state
        assert out_mult == 1.0

    def test_no_reading_noop(self):
        state = {"1": {"on": True, "bri": 200}}
        out_state, out_mult = apply_lux_multiplier(state, "working", None, 1.0)
        assert out_state is state
        assert out_mult == 1.0

    def test_dark_room_lifts_brightness(self):
        # Lux below baseline → multiplier > 1.0 → brighter.
        state = {"1": {"on": True, "bri": 100}}
        out_state, out_mult = apply_lux_multiplier(
            state, "working", lux_reading=40.0, last_multiplier=1.0,
        )
        assert out_mult > 1.0
        assert out_state["1"]["bri"] > 100

    def test_bright_room_dims(self):
        state = {"1": {"on": True, "bri": 100}}
        out_state, out_mult = apply_lux_multiplier(
            state, "working", lux_reading=180.0, last_multiplier=1.0,
        )
        assert out_mult < 1.0
        assert out_state["1"]["bri"] < 100

    def test_hysteresis_within_epsilon_keeps_old_multiplier(self):
        # last_multiplier was 1.10; new reading produces ~1.115 (within 0.03).
        state = {"1": {"on": True, "bri": 100}}
        # lux=70 → mult = lerp between (40,1.15) and (90,1.00) at 0.6 → 1.06
        # If last was 1.07, the diff is 0.01 < 0.03, so we keep 1.07.
        out_state, out_mult = apply_lux_multiplier(
            state, "working", lux_reading=70.0, last_multiplier=1.07,
        )
        assert out_mult == 1.07  # Hysteresis won.
        # And state was scaled by 1.07.
        assert out_state["1"]["bri"] == int(100 * 1.07)

    def test_hysteresis_outside_epsilon_uses_new_multiplier(self):
        state = {"1": {"on": True, "bri": 100}}
        # lux=40 → 1.15; last was 1.0 → diff 0.15 > epsilon → use 1.15.
        out_state, out_mult = apply_lux_multiplier(
            state, "working", lux_reading=40.0, last_multiplier=1.0,
        )
        assert out_mult == pytest.approx(1.15)
        assert out_state["1"]["bri"] == int(100 * 1.15)


# ---------------------------------------------------------------------------
# apply_zone_overlay — desk lift + bed-reclined lower
# ---------------------------------------------------------------------------


class TestApplyZoneOverlay:

    def _state(self, l1_bri: int = 80, l2_bri: int = 30) -> dict:
        return {
            "1": {"on": True, "bri": l1_bri, "ct": 400},
            "2": {"on": True, "bri": l2_bri, "ct": 400},
            "3": {"on": False},
            "4": {"on": False},
        }

    def test_desk_watching_lifts_l2(self):
        state = self._state(l2_bri=20)  # Below the day target of 160.
        out = apply_zone_overlay(state, "watching", "day", "desk", None)
        assert out["2"]["bri"] == 160
        # L1 untouched.
        assert out["1"]["bri"] == 80

    def test_desk_only_lifts_for_watching(self):
        # Working at desk: no lift (rule is watching-specific).
        state = self._state(l2_bri=20)
        out = apply_zone_overlay(state, "working", "day", "desk", None)
        assert out is state

    def test_desk_lift_is_lift_only(self):
        # Already brighter than target → leave alone.
        state = self._state(l2_bri=200)
        out = apply_zone_overlay(state, "watching", "day", "desk", None)
        assert out is state

    def test_bed_reclined_lowers_l1_l2_at_night(self):
        state = self._state(l1_bri=80, l2_bri=80)
        out = apply_zone_overlay(state, "watching", "night", "bed", "reclined")
        # night ratios: L1 = 25*1.0 = 25, L2 = 8.
        assert out["1"]["bri"] == 25
        assert out["2"]["bri"] == 8

    def test_bed_reclined_works_across_modes(self):
        # The rule is mode-agnostic except sleeping. Working at bed+reclined
        # should still lower L1/L2.
        state = self._state(l1_bri=80, l2_bri=80)
        out = apply_zone_overlay(state, "working", "night", "bed", "reclined")
        assert out["1"]["bri"] == 25
        assert out["2"]["bri"] == 8

    def test_bed_reclined_skips_sleeping(self):
        state = self._state(l1_bri=80, l2_bri=80)
        out = apply_zone_overlay(state, "sleeping", "night", "bed", "reclined")
        assert out is state

    def test_bed_reclined_lower_only(self):
        # Already below the target — don't raise.
        state = self._state(l1_bri=10, l2_bri=2)
        out = apply_zone_overlay(state, "watching", "night", "bed", "reclined")
        assert out is state

    def test_l1_night_knob_scales_evening_and_late_night(self):
        # Override L1 night to 50 → evening = 50*1.8 = 90, night = 50, late = 30.
        state = self._state(l1_bri=200, l2_bri=200)
        out_eve = apply_zone_overlay(
            state, "watching", "evening", "bed", "reclined",
            bed_reclined_l1_night=50,
        )
        out_night = apply_zone_overlay(
            state, "watching", "night", "bed", "reclined",
            bed_reclined_l1_night=50,
        )
        assert out_eve["1"]["bri"] == 90
        assert out_night["1"]["bri"] == 50

    def test_no_zone_or_posture_noop(self):
        state = self._state()
        out = apply_zone_overlay(state, "watching", "night", None, None)
        assert out is state

    def test_flat_state_passes_through(self):
        # Scene-override payloads don't carry per-light shape; pass through.
        flat = {"on": True, "bri": 100}
        out = apply_zone_overlay(flat, "watching", "night", "bed", "reclined")
        assert out is flat


# ---------------------------------------------------------------------------
# is_zone_posture_freshness_ok
# ---------------------------------------------------------------------------


class TestZonePostureFreshness:

    def test_recent_commit_is_fresh(self):
        now = datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc)
        committed = now - timedelta(seconds=60)
        assert is_zone_posture_freshness_ok(committed, now) is True

    def test_old_commit_is_stale(self):
        now = datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc)
        # ZONE_POSTURE_FRESHNESS_SECONDS = 300, so 600s old is stale.
        committed = now - timedelta(seconds=600)
        assert is_zone_posture_freshness_ok(committed, now) is False

    def test_none_is_not_fresh(self):
        assert is_zone_posture_freshness_ok(None) is False


# ---------------------------------------------------------------------------
# Weather adjustment — classify + apply
# ---------------------------------------------------------------------------


class TestWeatherAdjust:

    def test_no_condition_noop(self):
        state = {"1": {"on": True, "bri": 100, "ct": 300}}
        out = apply_weather_adjust(state, None)
        assert out is state

    def test_rain_dims_and_cools_ct_lights(self):
        state = {"1": {"on": True, "bri": 100, "ct": 300}}
        out = apply_weather_adjust(state, "rain")
        assert out["1"]["bri"] == 85   # -15
        assert out["1"]["ct"] == 250   # -50

    def test_rain_shifts_hue_for_hsb_lights(self):
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        out = apply_weather_adjust(state, "rain")
        assert out["1"]["bri"] == 85
        assert out["1"]["hue"] == 12000  # +4000
        assert out["1"]["sat"] == 130    # +30

    def test_off_lights_pass_through(self):
        state = {
            "1": {"on": False},
            "2": {"on": True, "bri": 100, "ct": 300},
        }
        out = apply_weather_adjust(state, "rain")
        assert out["1"] == {"on": False}
        assert out["2"]["bri"] == 85

    def test_classify_thunderstorm(self):
        assert classify_weather("thunderstorm with rain", {}) == "thunderstorm"

    def test_classify_rain(self):
        assert classify_weather("light rain", {}) == "rain"
        assert classify_weather("drizzle", {}) == "rain"

    def test_classify_snow(self):
        assert classify_weather("snow", {}) == "snow"

    def test_classify_clouds(self):
        assert classify_weather("overcast clouds", {}) == "clouds"

    def test_classify_clear_outside_golden_hour(self):
        # No sunset payload → can't be golden hour, returns None.
        assert classify_weather("clear sky", {}) is None

    def test_classify_unknown_returns_none(self):
        assert classify_weather("foggy with sprinkles", {}) is None
