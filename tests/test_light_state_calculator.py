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
    ALL_LIGHT_IDS,
    AUTOMATIC_EFFECT_LIGHT_IDS,
    BED_RECLINED_L1_NIGHT_DEFAULT,
    DEFAULT_MODE_BRIGHTNESS,
    EFFECT_AUTO_MAP,
    GAME_LIGHT_PROFILES,
    LIGHT_IDS,
    LUX_MULT_EPSILON,
    TZ,
    apply_brightness_multiplier,
    apply_functional_weather_brightness,
    apply_gaming_day_surround_brightness,
    apply_lux_multiplier,
    apply_weather_adjust,
    apply_zone_overlay,
    classify_weather,
    get_time_period,
    is_zone_posture_freshness_ok,
    path_light_brightness,
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

    def test_plant_wash_is_canonical_and_every_mode_state_covers_it(self):
        assert LIGHT_IDS["plant_wash"] == "6"
        assert ALL_LIGHT_IDS == ("1", "2", "3", "4", "5", "6")

        for mode_state in ACTIVITY_LIGHT_STATES.values():
            period_states = (
                mode_state.values() if "day" in mode_state else (mode_state,)
            )
            for state in period_states:
                assert set(state) == set(ALL_LIGHT_IDS)

        for profile in GAME_LIGHT_PROFILES.values():
            for state in profile.values():
                assert set(state) == set(ALL_LIGHT_IDS)

    def test_plant_wash_modes_are_deliberate_and_non_uniform(self):
        states = [
            ACTIVITY_LIGHT_STATES["gaming"]["evening"]["6"],
            ACTIVITY_LIGHT_STATES["working"]["night"]["6"],
            ACTIVITY_LIGHT_STATES["relax"]["day"]["6"],
            ACTIVITY_LIGHT_STATES["relax"]["night"]["6"],
            ACTIVITY_LIGHT_STATES["cooking"]["day"]["6"],
        ]
        assert len({tuple(sorted(state.items())) for state in states}) == len(states)
        assert ACTIVITY_LIGHT_STATES["relax"]["day"]["6"]["bri"] == 185
        assert ACTIVITY_LIGHT_STATES["working"]["night"]["6"] == {"on": False}

    def test_automatic_effect_scopes_preserve_original_five_lights(self):
        assert AUTOMATIC_EFFECT_LIGHT_IDS == ("1", "2", "3", "4", "5")
        for periods in EFFECT_AUTO_MAP.values():
            for target in periods.values():
                if target is not None:
                    assert target["lights"] is not None
                    assert "6" not in target["lights"]

    def test_generic_gaming_state_is_detached_from_canonical(self):
        state = resolve_activity_state("gaming", "day")
        assert state["2"]["bri"] == 240

        state["2"]["bri"] = 189
        state["extra"] = {"on": False}

        fresh = resolve_activity_state("gaming", "day")
        assert fresh["2"]["bri"] == 240
        assert "extra" not in fresh
        assert ACTIVITY_LIGHT_STATES["gaming"]["day"]["2"]["bri"] == 240

    def test_learner_style_overlay_does_not_leak_to_later_resolution(self):
        state = resolve_activity_state("gaming", "day")
        pre = state["2"]
        state["2"] = {**pre, **{"bri": 189}}

        assert state["2"]["bri"] == 189
        assert resolve_activity_state("gaming", "day")["2"]["bri"] == 240

    def test_additional_period_aware_mode_is_detached(self):
        state = resolve_activity_state("watching", "night")
        canonical_bri = ACTIVITY_LIGHT_STATES["watching"]["night"]["2"]["bri"]
        state["2"]["bri"] = canonical_bri + 100

        fresh = resolve_activity_state("watching", "night")
        assert fresh["2"]["bri"] == canonical_bri
        assert (
            ACTIVITY_LIGHT_STATES["watching"]["night"]["2"]["bri"]
            == canonical_bri
        )

    def test_game_profile_state_is_detached(self):
        state = resolve_activity_state("gaming", "day", game="rust")
        canonical_bri = GAME_LIGHT_PROFILES["rust"]["day"]["2"]["bri"]
        state["2"]["bri"] = canonical_bri + 50

        fresh = resolve_activity_state("gaming", "day", game="rust")
        assert fresh["2"]["bri"] == canonical_bri
        assert GAME_LIGHT_PROFILES["rust"]["day"]["2"]["bri"] == canonical_bri

    def test_flat_mode_state_is_detached(self):
        state = resolve_activity_state("social", "day")
        canonical_bri = ACTIVITY_LIGHT_STATES["social"]["2"]["bri"]
        state["2"]["bri"] = canonical_bri + 50

        assert resolve_activity_state("social", "night")["2"]["bri"] == canonical_bri
        assert ACTIVITY_LIGHT_STATES["social"]["2"]["bri"] == canonical_bri

    def test_repeated_resolutions_do_not_alias_each_other(self):
        first = resolve_activity_state("gaming", "day")
        second = resolve_activity_state("gaming", "day")

        assert first is not second
        assert first["2"] is not second["2"]
        first["2"]["bri"] = 189
        assert second["2"]["bri"] == 240

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
        # L1 keeps the night fill level but warms further.
        assert state["1"]["bri"] == 45
        assert state["1"]["ct"] == 454
        # L2 stays the dominant task light, slightly below the night level.
        assert state["2"]["bri"] == 95
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
        # Only relax adapts now (2026-05-30, room-correct scope). cooking /
        # social / gaming / watching / working all bypass — the living-room
        # camera can't see the rooms those modes happen in.
        state = {"1": {"on": True, "bri": 200}}
        out_state, out_mult, _ = apply_lux_multiplier(state, "cooking", 50.0, 1.0)
        assert out_state is state
        assert out_mult == 1.0

    def test_gaming_no_longer_adapts(self):
        # Gaming dropped from LUX_MODES 2026-05-30: it's a bedroom-desk mode
        # the living-room couch camera can't see, so couch lux must not scale
        # it (was cross-room contamination). Now a no-op.
        state = {"1": {"on": True, "bri": 100}}
        out_state, out_mult, _ = apply_lux_multiplier(
            state, "gaming", lux_reading=40.0, last_multiplier=1.0,
        )
        assert out_state is state
        assert out_mult == 1.0

    def test_watching_no_longer_adapts(self):
        # Watching (projector, bedroom) dropped from LUX_MODES same as gaming.
        state = {"1": {"on": True, "bri": 100}}
        out_state, out_mult, _ = apply_lux_multiplier(
            state, "watching", lux_reading=40.0, last_multiplier=1.0,
        )
        assert out_state is state
        assert out_mult == 1.0

    def test_no_reading_noop(self):
        state = {"1": {"on": True, "bri": 200}}
        out_state, out_mult, _ = apply_lux_multiplier(state, "relax", None, 1.0)
        assert out_state is state
        assert out_mult == 1.0

    def test_dark_room_lifts_brightness(self):
        # Lux below baseline → multiplier > 1.0 → brighter.
        state = {"1": {"on": True, "bri": 100}}
        out_state, out_mult, _ = apply_lux_multiplier(
            state, "relax", lux_reading=40.0, last_multiplier=1.0,
        )
        assert out_mult > 1.0
        assert out_state["1"]["bri"] > 100

    def test_bright_room_dims(self):
        state = {"1": {"on": True, "bri": 100}}
        out_state, out_mult, _ = apply_lux_multiplier(
            state, "relax", lux_reading=180.0, last_multiplier=1.0,
        )
        assert out_mult < 1.0
        assert out_state["1"]["bri"] < 100

    def test_hysteresis_within_epsilon_keeps_old_multiplier(self):
        # lux=70 → mult = lerp between (40,1.20) and (90,1.00) at 0.6 → 1.08.
        # If last was 1.07, the diff is 0.01 < LUX_MULT_EPSILON (0.08), so
        # we keep 1.07.
        state = {"1": {"on": True, "bri": 100}}
        out_state, out_mult, _ = apply_lux_multiplier(
            state, "relax", lux_reading=70.0, last_multiplier=1.07,
        )
        assert out_mult == 1.07  # Hysteresis won.
        # And state was scaled by 1.07.
        assert out_state["1"]["bri"] == int(100 * 1.07)

    def test_hysteresis_outside_epsilon_uses_new_multiplier(self):
        state = {"1": {"on": True, "bri": 100}}
        # lux=40 → 1.20; last was 1.0 → diff 0.20 > LUX_MULT_EPSILON (0.08)
        # → use 1.20.
        out_state, out_mult, _ = apply_lux_multiplier(
            state, "relax", lux_reading=40.0, last_multiplier=1.0,
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
        out_state, out_mult, _ = apply_lux_multiplier(
            state, "relax", lux_reading=60.0, last_multiplier=1.07,
        )
        assert out_mult == 1.07

    def test_lux_mult_epsilon_constant_sanity(self):
        # Lock in 0.08 — lowering this re-introduces the bri-spam regression
        # (2026-05-17 incident). Raise the value if needed; don't lower it
        # without revisiting the spam analysis in the notifier plan.
        assert LUX_MULT_EPSILON == 0.08

    def test_weather_baseline_shift_pushes_across_dead_band(self):
        """The exact symptom from 2026-05-18: thunderstorm + small lux drop
        gets dead-band suppressed without the shift. Shift raises baseline
        so the same reading produces a multiplier that crosses 8% epsilon.

        Tests steady-state (same weather_class on both ticks) — class-change
        bypass is tested separately in
        ``test_weather_class_change_bypasses_dead_band``.
        """
        state = {"1": {"on": True, "bri": 100}}
        # Real values: ema_lux=134, baseline=143, last_mult=1.0.
        # No shift: effective = 134 - 143 + 90 = 81 → between (40,1.20)(90,1.00)
        # frac=0.82 → raw_mult = 1.036. Diff from 1.0 is 0.036 < 0.08 → 1.0.
        _, mult_clear, _ = apply_lux_multiplier(
            state, "relax", lux_reading=134.0,
            last_multiplier=1.0, baseline_lux=143.0,
            weather_class="clear", last_weather_class="clear",
        )
        assert mult_clear == 1.0  # Dead-band suppressed.
        # With thunderstorm +30: effective_baseline=173.
        # effective = 134 - 173 + 90 = 51 → between (40,1.20)(90,1.00)
        # frac=(51-40)/50=0.22 → raw_mult = 1.20 + 0.22*(-0.20) = 1.156.
        # Diff from 1.0 is 0.156 > 0.08 → applied even at steady state.
        _, mult_storm, _ = apply_lux_multiplier(
            state, "relax", lux_reading=134.0,
            last_multiplier=1.0, baseline_lux=143.0,
            weather_class="thunderstorm", last_weather_class="thunderstorm",
        )
        assert mult_storm > 1.05
        assert mult_storm > mult_clear

    def test_weather_shift_monotonic_storm_intensity(self):
        """Heavier weather → bigger lift at near-baseline lux."""
        state = {"1": {"on": True, "bri": 100}}
        # Pin last_weather_class == weather_class so the dead-band is
        # what's under test (not the class-change bypass).
        common = dict(
            state=state, mode="relax",
            lux_reading=134.0, last_multiplier=1.0, baseline_lux=143.0,
        )
        _, mult_clear, _ = apply_lux_multiplier(
            **common, weather_class="clear", last_weather_class="clear",
        )
        _, mult_clouds, _ = apply_lux_multiplier(
            **common, weather_class="clouds", last_weather_class="clouds",
        )
        _, mult_rain, _ = apply_lux_multiplier(
            **common, weather_class="rain", last_weather_class="rain",
        )
        _, mult_storm, _ = apply_lux_multiplier(
            **common, weather_class="thunderstorm",
            last_weather_class="thunderstorm",
        )
        assert mult_clear <= mult_clouds <= mult_rain <= mult_storm

    def test_weather_shift_noop_when_none(self):
        """No weather_class arg → behavior matches pre-Layer-2 path."""
        state = {"1": {"on": True, "bri": 100}}
        # Both calls pin last_weather_class to match weather_class so the
        # class-change bypass doesn't muddy the equivalence check.
        _, mult_no_arg, _ = apply_lux_multiplier(
            state, "relax", lux_reading=60.0,
            last_multiplier=1.0, baseline_lux=90.0,
            last_weather_class=None,
        )
        _, mult_clear, _ = apply_lux_multiplier(
            state, "relax", lux_reading=60.0,
            last_multiplier=1.0, baseline_lux=90.0,
            weather_class="clear", last_weather_class="clear",
        )
        assert mult_no_arg == mult_clear

    def test_weather_class_change_bypasses_dead_band(self):
        """The 2026-05-19 18:46 ET regression: weather class transitions must
        force-apply the new multiplier even when the resulting delta is inside
        the LUX_MULT_EPSILON (0.08) dead-band. Pinned to the diagnosed case:
        lux=123.6, baseline=143.47. No-shift mult=1.0794. Rain shift +15.0
        raises effective_baseline to 158.47, effective_lux=55.13, frac=0.3026
        between (40,1.20)(90,1.00), raw_mult=1.1394. Δ=0.060 < 0.08, so the
        steady-state dead-band would suppress; the class change must override.
        """
        state = {"1": {"on": True, "bri": 100}}
        # Steady-state on "clouds" with last_multiplier ≈ no-shift raw — a
        # same-class call obeys epsilon and clamps to last.
        _, mult_steady, class_steady = apply_lux_multiplier(
            state, "relax", lux_reading=123.6,
            last_multiplier=1.0794, baseline_lux=143.47,
            weather_class="clouds", last_weather_class="clouds",
        )
        # Within dead-band → clamps to last.
        assert mult_steady == pytest.approx(1.0794)
        assert class_steady == "clouds"

        # Transition clouds → rain at the SAME lux: shift raises raw_mult to
        # ~1.139, Δ=0.060 < 0.08 → would have been suppressed pre-fix.
        # Class change bypasses the epsilon and the new value lands.
        _, mult_transition, class_transition = apply_lux_multiplier(
            state, "relax", lux_reading=123.6,
            last_multiplier=1.0794, baseline_lux=143.47,
            weather_class="rain", last_weather_class="clouds",
        )
        assert mult_transition == pytest.approx(1.1394, abs=1e-3)
        assert class_transition == "rain"
        # And the new class is returned so the engine can remember it.
        assert class_transition != class_steady

    def test_weather_class_returned_for_engine_state(self):
        """The third tuple element echoes weather_class so the engine can
        store it back for next-tick comparison."""
        state = {"1": {"on": True, "bri": 100}}
        _, _, returned_class = apply_lux_multiplier(
            state, "relax", lux_reading=60.0,
            last_multiplier=1.0, baseline_lux=90.0,
            weather_class="rain", last_weather_class=None,
        )
        assert returned_class == "rain"

        # When mode is non-LUX, the early-return preserves last_weather_class
        # so the engine doesn't desync its hysteresis on a cooking tick.
        _, _, preserved = apply_lux_multiplier(
            state, "cooking", lux_reading=60.0,
            last_multiplier=1.0,
            weather_class="rain", last_weather_class="clouds",
        )
        assert preserved == "clouds"


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

    def test_aesthetic_modes_pass_through(self):
        """relax/social/cooking never get the functional weather boost —
        their palettes are intentional, not visibility-driven."""
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        for mode in ("relax", "social", "cooking", "sleeping", "idle"):
            out = apply_functional_weather_brightness(state, mode, "day", "rain")
            assert out is state

    def test_unmapped_bucket_passes_through(self):
        """No (mode, period, condition) entry → no-op. Late-night gaming
        has no rain/clouds/snow entries, so all of those pass through."""
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        for cond in ("rain", "clouds", "snow"):
            out = apply_functional_weather_brightness(
                state, "gaming", "late_night", cond,
            )
            assert out is state
        # watching evening also has no entries
        out = apply_functional_weather_brightness(
            state, "watching", "evening", "thunderstorm",
        )
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

    def test_working_day_thunderstorm_applies(self):
        """Working mode now gets a weather boost (Layer 1 extension)."""
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        out = apply_functional_weather_brightness(
            state, "working", "day", "thunderstorm",
        )
        assert out["1"]["bri"] == 118  # int(100 * 1.18)

    def test_gaming_evening_thunderstorm_applies(self):
        """Gaming evening now gets a smaller boost during severe weather."""
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        out = apply_functional_weather_brightness(
            state, "gaming", "evening", "thunderstorm",
        )
        assert out["1"]["bri"] == 110  # int(100 * 1.10)

    def test_watching_day_rain_applies_smaller(self):
        """Watching's projector mode gets a smaller daytime lift to preserve
        cinematic dim intent."""
        state = {"1": {"on": True, "bri": 100, "hue": 8000, "sat": 100}}
        out = apply_functional_weather_brightness(
            state, "watching", "day", "rain",
        )
        assert out["1"]["bri"] == 106  # int(100 * 1.06)

    def test_learner_has_learned_skips_specific_lights(self):
        """The Layer-5 fade-out: lights with a learned preference bypass the
        heuristic boost while peers without learning still get it."""
        state = {
            "1": {"on": True, "bri": 100, "hue": 8000, "sat": 100},
            "2": {"on": True, "bri": 100, "hue": 8000, "sat": 100},
        }
        out = apply_functional_weather_brightness(
            state, "gaming", "day", "rain",
            learner_has_learned={"1"},
        )
        assert out["1"]["bri"] == 100  # untouched — learner owns this bucket
        assert out["2"]["bri"] == 114  # heuristic still applies

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

    def test_lux_and_weather_layers_are_mode_disjoint(self):
        # Post-2026-05-30 room-correct scoping: lux adaptation fires ONLY for
        # relax (the couch/living-room mode the camera sees), while functional
        # weather brightness fires for gaming/working/watching. The two layers
        # no longer overlap on any single mode, so neither double-applies.
        state = {"1": {"on": True, "bri": 180, "hue": 48500, "sat": 160}}
        # Gaming: lux is a no-op (dropped from LUX_MODES); weather still lifts.
        after_lux_gaming, _, _ = apply_lux_multiplier(
            state, "gaming", lux_reading=60.0, last_multiplier=1.0, baseline_lux=90.0,
        )
        assert after_lux_gaming is state  # lux skipped gaming entirely
        weather_gaming = apply_functional_weather_brightness(
            state, "gaming", "day", "rain",
        )
        assert weather_gaming["1"]["bri"] > 180  # weather layer applies to gaming
        # Relax: lux lifts (lux=60, baseline=90 → mult 1.12); weather is a no-op.
        after_lux_relax, _, _ = apply_lux_multiplier(
            state, "relax", lux_reading=60.0, last_multiplier=1.0, baseline_lux=90.0,
        )
        assert after_lux_relax["1"]["bri"] == int(180 * 1.12)
        weather_relax = apply_functional_weather_brightness(
            after_lux_relax, "relax", "day", "rain",
        )
        # relax isn't a functional-weather mode → bri unchanged by that layer.
        assert weather_relax["1"]["bri"] == after_lux_relax["1"]["bri"]


class TestGamingDaySurroundBrightness:

    @staticmethod
    def _state(game=None):
        return resolve_activity_state("gaming", "day", game=game)

    @staticmethod
    def _after_weather(state, condition):
        return apply_functional_weather_brightness(
            state, "gaming", "day", condition,
        )

    @pytest.mark.parametrize(
        ("condition", "expected_l1", "expected_kitchen"),
        [
            ("clear", 130, 30),
            ("clouds", 155, 50),
            ("rain", 170, 70),
            ("thunderstorm", 180, 75),
        ],
    )
    def test_weather_floors(self, condition, expected_l1, expected_kitchen):
        state = self._after_weather(self._state(), condition)
        out = apply_gaming_day_surround_brightness(
            state, "gaming", "day", condition,
        )
        assert out["1"]["bri"] == expected_l1
        assert out["3"]["bri"] == out["4"]["bri"] == expected_kitchen

    def test_misleading_high_lux_cannot_cancel_rain_floor(self):
        state = self._after_weather(self._state(), "rain")
        out = apply_gaming_day_surround_brightness(
            state, "gaming", "day", "rain",
            lux_reading=139.30, baseline_lux=73.97,
        )
        assert out["1"]["bri"] == 170
        assert out["3"]["bri"] == out["4"]["bri"] == 70

    def test_dark_lux_lifts_within_caps_and_preserves_pair(self):
        state = self._state()
        state["3"]["bri"] = 80
        state["4"]["bri"] = 60
        out = apply_gaming_day_surround_brightness(
            state, "gaming", "day", "clear",
            lux_reading=20.0, baseline_lux=90.0,
        )
        assert out["1"]["bri"] == 169
        assert out["3"]["bri"] == out["4"]["bri"] == 85
        assert out["1"]["bri"] <= 190

    def test_lift_caps_never_dim_pre_lifted_values(self):
        state = self._state()
        state["1"]["bri"] = 220
        state["3"]["bri"] = 100
        state["4"]["bri"] = 95
        out = apply_gaming_day_surround_brightness(
            state, "gaming", "day", "thunderstorm",
        )
        assert out["1"]["bri"] == 220
        assert out["3"]["bri"] == out["4"]["bri"] == 100

    def test_only_surround_brightness_changes(self):
        state = self._state()
        original = {lid: light.copy() for lid, light in state.items()}
        out = apply_gaming_day_surround_brightness(
            state, "gaming", "day", "rain",
        )
        assert out["2"] == original["2"]
        assert out["5"] == original["5"]
        for lid in ("1", "3", "4"):
            assert {k: v for k, v in out[lid].items() if k != "bri"} == {
                k: v for k, v in original[lid].items() if k != "bri"
            }

    def test_game_profile_keeps_colors_and_receives_floor(self):
        state = self._state("rust")
        original = {lid: light.copy() for lid, light in state.items()}
        out = apply_gaming_day_surround_brightness(
            state, "gaming", "day", "rain",
        )
        assert out["1"]["bri"] == 170
        assert out["3"]["bri"] == out["4"]["bri"] == 70
        for lid in ("1", "3", "4"):
            assert out[lid]["hue"] == original[lid]["hue"]
            assert out[lid]["sat"] == original[lid]["sat"]

    def test_mode_multiplier_composes_before_floor(self):
        multiplied = apply_brightness_multiplier(
            self._state(), "gaming", {"gaming": 1.2},
        )
        out = apply_gaming_day_surround_brightness(
            multiplied, "gaming", "day", "clear",
            brightness_multiplier=1.2,
        )
        assert out["1"]["bri"] == 156
        assert out["3"]["bri"] == out["4"]["bri"] == 36

    def test_clear_weather_respects_reduced_mode_multiplier(self):
        multiplied = apply_brightness_multiplier(
            self._state(), "gaming", {"gaming": 0.5},
        )
        out = apply_gaming_day_surround_brightness(
            multiplied, "gaming", "day", "clear",
            brightness_multiplier=0.5,
        )
        assert out["1"]["bri"] == 65
        assert out["3"]["bri"] == out["4"]["bri"] == 15

    @pytest.mark.parametrize(
        ("multiplier", "expected_l1", "expected_kitchen"),
        [
            (0.5, 85, 35),
            (1.2, 204, 84),
            (1.5, 254, 105),
        ],
    )
    def test_rain_envelope_scales_with_mode_multiplier(
        self, multiplier, expected_l1, expected_kitchen,
    ):
        state = apply_brightness_multiplier(
            self._state(), "gaming", {"gaming": multiplier},
        )
        state = self._after_weather(state, "rain")
        out = apply_gaming_day_surround_brightness(
            state, "gaming", "day", "rain",
            brightness_multiplier=multiplier,
        )
        assert out["1"]["bri"] == expected_l1
        assert out["3"]["bri"] == out["4"]["bri"] == expected_kitchen

    @pytest.mark.parametrize("period", ["evening", "night", "late_night"])
    def test_other_periods_are_unchanged(self, period):
        state = resolve_activity_state("gaming", period)
        assert apply_gaming_day_surround_brightness(
            state, "gaming", period, "thunderstorm",
            lux_reading=20.0, baseline_lux=90.0,
        ) is state


# ---------------------------------------------------------------------------
# path_light_brightness — baseline-relative D1 navigation brightness
# ---------------------------------------------------------------------------


class TestPathLightBrightness:
    """Darkness-scaled path light: d = clamp((baseline-lux)/baseline, 0, 1),
    bri = round(lo + d*(hi-lo)). Anchors from the curator design pass."""

    def test_room_at_baseline_lands_on_lo(self):
        # lux == baseline → d=0 → minimal path light (the lo anchor).
        assert path_light_brightness(
            74.0, 74.0, "evening", kind="desk_exit_kitchen", fallback=120,
        ) == 55  # desk_exit_kitchen evening lo

    def test_pitch_black_lands_on_hi(self):
        # lux == 0 → d=1 → max navigational boost (the hi anchor).
        assert path_light_brightness(
            0.0, 74.0, "evening", kind="desk_exit_kitchen", fallback=120,
        ) == 140  # desk_exit_kitchen evening hi

    def test_dark_room_interpolates(self):
        # lux=15, baseline=74 → d≈0.797 → 30 + 0.797*(70-30) ≈ 62.
        assert path_light_brightness(
            15.0, 74.0, "night", kind="desk_exit_kitchen", fallback=60,
        ) == 62

    def test_brighter_than_baseline_clamps_to_lo(self):
        # lux > baseline (room brighter than calibrated) → d clamps to 0,
        # never goes below lo (no negative boost).
        assert path_light_brightness(
            200.0, 74.0, "late_night", kind="corridor_kitchen", fallback=40,
        ) == 25  # corridor_kitchen lo

    def test_none_lux_returns_fallback(self):
        assert path_light_brightness(
            None, 74.0, "evening", kind="transit_l1", fallback=120,
        ) == 120

    def test_none_baseline_returns_fallback(self):
        assert path_light_brightness(
            40.0, None, "evening", kind="transit_l1", fallback=120,
        ) == 120

    def test_nonpositive_baseline_returns_fallback(self):
        # Guards a division-by-zero / nonsense calibration.
        assert path_light_brightness(
            40.0, 0.0, "evening", kind="transit_kitchen", fallback=80,
        ) == 80

    def test_missing_anchor_returns_fallback(self):
        # No curve row for (transit_l1, late_night) — transit maps its
        # late_night tier onto the "night" row, so this key is intentionally
        # absent and must degrade to the fixed fallback.
        assert path_light_brightness(
            10.0, 74.0, "late_night", kind="transit_l1", fallback=60,
        ) == 60

    def test_l1_night_floor_respected(self):
        # transit_l1 night lo is the floor-corrected 45 (L1 ≥45 night-
        # visibility floor) — a bright room must never drive L1 below it.
        assert path_light_brightness(
            74.0, 74.0, "night", kind="transit_l1", fallback=60,
        ) == 45

    def test_corridor_l1_dark_caps_at_hi(self):
        # Validated-comfortable late-night L1 ceiling is 100, not above.
        assert path_light_brightness(
            0.0, 74.0, "late_night", kind="corridor_l1", fallback=100,
        ) == 100


class TestGameLightProfiles:
    """Per-game lighting profile resolution (Rust 'Rusted Ember')."""

    def test_rust_profile_selected_only_for_gaming(self):
        from backend.services.light_state_calculator import (
            GAME_LIGHT_PROFILES,
            get_mode_state_table,
        )
        assert get_mode_state_table("gaming", "rust") is GAME_LIGHT_PROFILES["rust"]
        # Generic gaming when no game / unknown game.
        assert get_mode_state_table("gaming", None) is ACTIVITY_LIGHT_STATES["gaming"]
        assert get_mode_state_table("gaming", "valorant") is ACTIVITY_LIGHT_STATES["gaming"]
        # Profile never leaks into other modes.
        assert get_mode_state_table("working", "rust") is ACTIVITY_LIGHT_STATES["working"]

    def test_rust_state_is_ember_with_paired_moss_kitchen(self):
        from backend.services.light_state_calculator import resolve_activity_state
        for period in ("day", "evening", "night", "late_night"):
            st = resolve_activity_state("gaming", period, "rust")
            # L2 ember matches the screen_sync RUST_EMBER constants (lock-step).
            from backend.services.screen_sync import RUST_EMBER_HUE, RUST_EMBER_SAT
            assert st["2"]["hue"] == RUST_EMBER_HUE and st["2"]["sat"] == RUST_EMBER_SAT
            # Kitchen pair rule: L3 == L4, muted moss.
            assert st["3"] == st["4"], f"kitchen pair must match in {period}"
            assert st["3"]["hue"] == 20000
            # L1 stays above the night hallway-spill visibility floor.
            assert st["1"]["bri"] >= 45

    def test_rust_dims_toward_late_night(self):
        from backend.services.light_state_calculator import resolve_activity_state
        day_l2 = resolve_activity_state("gaming", "day", "rust")["2"]["bri"]
        late_l2 = resolve_activity_state("gaming", "late_night", "rust")["2"]["bri"]
        assert late_l2 < day_l2
