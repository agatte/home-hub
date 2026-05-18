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
    apply_functional_weather_brightness,
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
        # working / relax / gaming / watching adapt; cooking + social bypass
        # so their explicit bright/medium palettes don't drift.
        state = {"1": {"on": True, "bri": 200}}
        out_state, out_mult = apply_lux_multiplier(state, "cooking", 50.0, 1.0)
        assert out_state is state
        assert out_mult == 1.0

    def test_gaming_now_adapts(self):
        # Gaming was added to LUX_MODES so dim rooms get a brightness lift.
        state = {"1": {"on": True, "bri": 100}}
        out_state, out_mult = apply_lux_multiplier(
            state, "gaming", lux_reading=40.0, last_multiplier=1.0,
        )
        assert out_mult > 1.0
        assert out_state["1"]["bri"] > 100

    def test_watching_now_adapts(self):
        state = {"1": {"on": True, "bri": 100}}
        out_state, out_mult = apply_lux_multiplier(
            state, "watching", lux_reading=40.0, last_multiplier=1.0,
        )
        assert out_mult > 1.0
        assert out_state["1"]["bri"] > 100

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
        # lux=70 → mult = lerp between (40,1.20) and (90,1.00) at 0.6 → 1.08.
        # If last was 1.07, the diff is 0.01 < LUX_MULT_EPSILON (0.08), so
        # we keep 1.07.
        state = {"1": {"on": True, "bri": 100}}
        out_state, out_mult = apply_lux_multiplier(
            state, "working", lux_reading=70.0, last_multiplier=1.07,
        )
        assert out_mult == 1.07  # Hysteresis won.
        # And state was scaled by 1.07.
        assert out_state["1"]["bri"] == int(100 * 1.07)

    def test_hysteresis_outside_epsilon_uses_new_multiplier(self):
        state = {"1": {"on": True, "bri": 100}}
        # lux=40 → 1.20; last was 1.0 → diff 0.20 > LUX_MULT_EPSILON (0.08)
        # → use 1.20.
        out_state, out_mult = apply_lux_multiplier(
            state, "working", lux_reading=40.0, last_multiplier=1.0,
        )
        assert out_mult == pytest.approx(1.20)
        assert out_state["1"]["bri"] == int(100 * 1.20)

    def test_sub_perceptual_drift_does_not_repush(self):
        # Lux jitter shifts the multiplier by ~5% (within the 8% dead-band
        # raised 2026-05-17). The new multiplier must stay clamped to the
        # last one — these sub-perceptual shifts were the cause of the
        # ~230 bri re-pushes per 30min during a stable room.
        state = {"1": {"on": True, "bri": 100}}
        # lux=60 → ~1.12, last=1.07 → diff 0.05 < 0.08 → keep 1.07.
        out_state, out_mult = apply_lux_multiplier(
            state, "working", lux_reading=60.0, last_multiplier=1.07,
        )
        assert out_mult == 1.07

    def test_lux_mult_epsilon_constant_sanity(self):
        # Lock in 0.08 — lowering this re-introduces the bri-spam regression
        # (2026-05-17 incident). Raise the value if needed; don't lower it
        # without revisiting the spam analysis in the notifier plan.
        assert LUX_MULT_EPSILON == 0.08


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
        # The rule fires for every non-sleeping mode. L1 ratios are mode-
        # agnostic; L2 floors are mode-conditional — working keeps a
        # readable floor for terminal text, everything else goes to the
        # watching/projector dim.
        state = self._state(l1_bri=80, l2_bri=80)

        # Working: L2 floor = 35 (readable but dim).
        out_working = apply_zone_overlay(
            state, "working", "night", "bed", "reclined",
        )
        assert out_working["1"]["bri"] == 25
        assert out_working["2"]["bri"] == 35

        # Relax: L2 floor = 8 (projector / no-screen dim).
        out_relax = apply_zone_overlay(
            state, "relax", "night", "bed", "reclined",
        )
        assert out_relax["1"]["bri"] == 25
        assert out_relax["2"]["bri"] == 8

        # Gaming, social, cooking, idle, gameday all take the watching floor too.
        for non_working_mode in ("gaming", "social", "cooking", "idle", "gameday"):
            out = apply_zone_overlay(
                state, non_working_mode, "night", "bed", "reclined",
            )
            assert out["2"]["bri"] == 8, (
                f"mode={non_working_mode} expected L2=8, got {out['2']['bri']}"
            )

    def test_bed_reclined_working_floors_per_period(self):
        # Working+bed+reclined floors: 50 / 35 / 25 across evening / night /
        # late_night. Repro of the 2026-05-08 scenario — Anthony in bed
        # reclined at 12:46 AM with terminal foregrounded; system is in
        # working mode; L2 must dim to 25 (not the working baseline 160,
        # not the watching dim 5).
        state = self._state(l1_bri=160, l2_bri=189)

        out_evening = apply_zone_overlay(
            state, "working", "evening", "bed", "reclined",
        )
        assert out_evening["2"]["bri"] == 50

        out_night = apply_zone_overlay(
            state, "working", "night", "bed", "reclined",
        )
        assert out_night["2"]["bri"] == 35

        out_late = apply_zone_overlay(
            state, "working", "late_night", "bed", "reclined",
        )
        assert out_late["2"]["bri"] == 25

    def test_bed_reclined_watching_floors_unchanged(self):
        # Regression guard: watching's existing 18 / 8 / 5 floors must
        # not have shifted when adding the working-mode branch.
        state = self._state(l1_bri=200, l2_bri=200)

        out_evening = apply_zone_overlay(
            state, "watching", "evening", "bed", "reclined",
        )
        assert out_evening["2"]["bri"] == 18

        out_night = apply_zone_overlay(
            state, "watching", "night", "bed", "reclined",
        )
        assert out_night["2"]["bri"] == 8

        out_late = apply_zone_overlay(
            state, "watching", "late_night", "bed", "reclined",
        )
        assert out_late["2"]["bri"] == 5

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

    # ── Branch 3: bed zone, posture None or upright ─────────────────
    # Fires when the user is in the bed area during working/idle at
    # evening/night/late_night but pose can't confirm "reclined" (face-
    # only detection or sitting upright). Dims to bedside-reading
    # levels — moderate, not full reclined depth.

    def test_bed_only_working_evening_posture_none_dims(self):
        state = self._state(l1_bri=100, l2_bri=180)
        out = apply_zone_overlay(state, "working", "evening", "bed", None)
        assert out["1"]["bri"] == 60
        assert out["2"]["bri"] == 50

    def test_bed_only_working_late_night_posture_upright_dims(self):
        state = self._state(l1_bri=90, l2_bri=160)
        out = apply_zone_overlay(state, "working", "late_night", "bed", "upright")
        assert out["1"]["bri"] == 30
        assert out["2"]["bri"] == 25

    def test_bed_only_idle_also_fires(self):
        # Mode=idle with posture=None → same dimming as working.
        state = self._state(l1_bri=100, l2_bri=180)
        out_none = apply_zone_overlay(state, "idle", "night", "bed", None)
        assert out_none["1"]["bri"] == 40
        assert out_none["2"]["bri"] == 35
        # Mode=idle with posture=upright → also fires.
        out_upright = apply_zone_overlay(state, "idle", "night", "bed", "upright")
        assert out_upright["1"]["bri"] == 40
        assert out_upright["2"]["bri"] == 35

    def test_bed_only_branch_2_takes_precedence_when_reclined(self):
        # When posture commits "reclined", the existing aggressive
        # branch fires; Branch 3's milder targets are never reached.
        state = self._state(l1_bri=100, l2_bri=180)
        out = apply_zone_overlay(state, "working", "night", "bed", "reclined")
        # Branch 2 working+night: L1 = 25*1.0 = 25, L2 = 35 (working floor).
        # Branch 3 night for working: L1 = 40, L2 = 35. L2 happens to
        # match — what matters is L1 took the lower Branch 2 path (25 vs
        # 40), proving Branch 2 fired first.
        assert out["1"]["bri"] == 25
        assert out["2"]["bri"] == 35

    def test_bed_only_skipped_for_active_modes(self):
        # Brief bed visits during gaming/watching/social/cooking shouldn't
        # trigger the bedside-reading dim — those modes own their own
        # zone behavior (or none).
        state = self._state(l1_bri=100, l2_bri=180)
        for mode in ("gaming", "watching", "social", "cooking"):
            out = apply_zone_overlay(state, mode, "night", "bed", None)
            assert out is state, f"mode={mode} should not trigger Branch 3"

    def test_bed_only_skipped_when_day(self):
        # No daytime dimming — natural light handles it.
        state = self._state(l1_bri=100, l2_bri=180)
        out_none = apply_zone_overlay(state, "working", "day", "bed", None)
        out_upright = apply_zone_overlay(state, "working", "day", "bed", "upright")
        assert out_none is state
        assert out_upright is state

    def test_bed_only_lower_only(self):
        # Already at or below target → leave alone (preserves a learned
        # override that already went lower).
        state = self._state(l1_bri=20, l2_bri=15)
        out = apply_zone_overlay(state, "working", "night", "bed", None)
        assert out is state

    def test_bed_only_skipped_when_zone_desk(self):
        # Desk + posture=None should fall through (Branch 1 only fires
        # for watching, Branch 3 only fires for zone=bed).
        state = self._state(l1_bri=100, l2_bri=180)
        out = apply_zone_overlay(state, "working", "night", "desk", None)
        assert out is state


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

    def test_classify_nws_cloudy_variants(self):
        """NWS sends 'Partly Cloudy' / 'Mostly Cloudy' / 'Cloudy' (singular
        adjective) — the substring match must be ``cloud`` not ``clouds`` or
        these silently fall through to None. Regression catch for the
        functional-weather brightness boost not engaging on real cloudy days.
        """
        assert classify_weather("partly cloudy", {}) == "clouds"
        assert classify_weather("mostly cloudy", {}) == "clouds"
        assert classify_weather("cloudy", {}) == "clouds"
        assert classify_weather("overcast", {}) == "clouds"

    def test_classify_clear_outside_golden_hour(self):
        # No sunset payload → can't be golden hour, returns None.
        assert classify_weather("clear sky", {}) is None

    def test_classify_unknown_returns_none(self):
        assert classify_weather("foggy with sprinkles", {}) is None


# ---------------------------------------------------------------------------
# Functional-mode weather brightness — opposite sign from apply_weather_adjust
# ---------------------------------------------------------------------------


class TestFunctionalWeatherBrightness:

    def test_non_gaming_mode_passes_through(self):
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        for mode in ("working", "relax", "social", "watching", "cooking"):
            out = apply_functional_weather_brightness(state, mode, "day", "rain")
            assert out is state

    def test_non_day_period_passes_through(self):
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        for period in ("evening", "night", "late_night"):
            out = apply_functional_weather_brightness(state, "gaming", period, "rain")
            assert out is state

    def test_none_condition_passes_through(self):
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        out = apply_functional_weather_brightness(state, "gaming", "day", None)
        assert out is state

    def test_unmapped_condition_passes_through(self):
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        out = apply_functional_weather_brightness(
            state, "gaming", "day", "golden_hour",
        )
        assert out is state

    def test_rain_brightens_gaming_day_by_fifteen_percent(self):
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        out = apply_functional_weather_brightness(state, "gaming", "day", "rain")
        assert out["1"]["bri"] == 114  # int(100 * 1.15) = int(114.999…) = 114

    def test_clouds_thunderstorm_snow_multipliers(self):
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        assert apply_functional_weather_brightness(
            state, "gaming", "day", "clouds",
        )["1"]["bri"] == 110
        assert apply_functional_weather_brightness(
            state, "gaming", "day", "thunderstorm",
        )["1"]["bri"] == 120
        assert apply_functional_weather_brightness(
            state, "gaming", "day", "snow",
        )["1"]["bri"] == 105

    def test_hue_and_sat_untouched(self):
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        out = apply_functional_weather_brightness(state, "gaming", "day", "rain")
        assert out["1"]["hue"] == 8000
        assert out["1"]["sat"] == 100

    def test_per_light_dict_all_brightened(self):
        state = {
            "1": {"on": True, "bri": 130, "hue": 47000, "sat": 180},
            "2": {"on": True, "bri": 240, "hue": 46920, "sat": 180},
            "3": {"on": True, "bri": 30,  "hue": 50000, "sat": 180},
            "4": {"on": True, "bri": 30,  "hue": 50000, "sat": 180},
            "5": {"on": True, "bri": 180, "hue": 48500, "sat": 160},
        }
        out = apply_functional_weather_brightness(state, "gaming", "day", "rain")
        assert out["1"]["bri"] == int(130 * 1.15)
        assert out["2"]["bri"] == 254  # int(240 * 1.15) = 276 → clamped
        assert out["3"]["bri"] == int(30 * 1.15)
        assert out["4"]["bri"] == int(30 * 1.15)
        assert out["5"]["bri"] == int(180 * 1.15)

    def test_clamps_to_254(self):
        state = {"1": {"on": True, "bri": 240, "hue": 46920, "sat": 180}}
        out = apply_functional_weather_brightness(
            state, "gaming", "day", "thunderstorm",
        )
        assert out["1"]["bri"] == 254  # 240 * 1.20 = 288 → clamped

    def test_off_lights_pass_through(self):
        state = {
            "1": {"on": False},
            "2": {"on": True, "bri": 100, "hue": 8000, "sat": 100},
        }
        out = apply_functional_weather_brightness(state, "gaming", "day", "rain")
        assert out["1"] == {"on": False}
        assert out["2"]["bri"] == 114

    def test_composes_with_lux_multiplier(self):
        # Mirrors the production pipeline order: lux first, then functional
        # weather. Together they should produce a moderate combined boost.
        # Lux value chosen so the multiplier shift exceeds LUX_MULT_EPSILON
        # (0.08) — otherwise hysteresis keeps the old multiplier.
        state = {"1": {"on": True, "bri": 180, "hue": 48500, "sat": 160}}
        after_lux, _ = apply_lux_multiplier(
            state, "gaming", lux_reading=60.0, last_multiplier=1.0, baseline_lux=90.0,
        )
        # lux=60 with baseline=90 → effective=60 → between (40,1.20) and (90,1.00)
        # frac = (60-40)/(90-40) = 0.4 → mult = 1.20 + 0.4*(1.00-1.20) = 1.12
        # Diff from 1.0 = 0.12 > LUX_MULT_EPSILON, so multiplier updates.
        assert after_lux["1"]["bri"] == int(180 * 1.12)
        out = apply_functional_weather_brightness(
            after_lux, "gaming", "day", "rain",
        )
        assert out["1"]["bri"] == int(int(180 * 1.12) * 1.15)
