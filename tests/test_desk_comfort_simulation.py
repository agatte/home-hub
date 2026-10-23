"""Offline pure projections and explicit ownership gaps; never actuator authority.

See docs/DESK_COMFORT_ALL_DAY_SIMULATION_2026_10_23.md for isolated reproduction.
"""
from collections import Counter, defaultdict
from itertools import product
import json

import pytest

from backend.services.desk_visual_comfort import is_neutral_page, twilight_monitor_target
from backend.services.light_state_calculator import (
    DESK_L5_COMFORT_CEILING,
    apply_functional_weather_brightness,
    apply_general_desk_lux_balance,
    apply_weather_adjust,
    apply_zone_overlay,
    enforce_fixture_comfort_invariants,
    get_fixture_comfort_brightness_ceiling,
    resolve_activity_state,
)
from backend.services.lux_channel import LUX_EMA_STALE_RESET_SECONDS
from backend.services.effect_manager import WEATHER_SKIP_MODES
from backend.services.screen_sync import ScreenSyncService
from backend.services.pc_agent.monitor_brightness import resolve_target

ACTIVITIES = ("general", "working", "watching", "gaming", "relax", "social", "cooking")
PERIODS = ("day", "evening", "night", "late_night")
OWNERS = (
    "auto", "manual_activity", "manual_light", "scene", "screen_sync", "away",
    "sleeping", "dnd", "transit", "protected", "external_off",
)
# Value and freshness are independent. Stale includes retained low AND high values.
SAMPLES = (
    ("bedroom_low", 20.0, 0, "bedroom"),
    ("bedroom_high", 180.0, 0, "bedroom"),
    ("bedroom_stale_low", 20.0, LUX_EMA_STALE_RESET_SECONDS + 1, "bedroom"),
    ("bedroom_stale_high", 180.0, LUX_EMA_STALE_RESET_SECONDS + 1, "bedroom"),
    ("missing", None, None, "none"),
    ("generic_camera_low", 20.0, 0, "unqualified_camera"),
)
SCREENS = {"white_page": (245, 245, 245), "dark_page": (20, 20, 20),
           "colored_video": (255, 190, 190)}


def qualified_lux(value, age, source):
    """Harness assumption, NOT execution of production freshness arbitration."""
    from math import isfinite

    return (source == "bedroom" and value is not None and isfinite(value)
            and value >= 0 and age is not None and isfinite(age)
            and 0 <= age <= LUX_EMA_STALE_RESET_SECONDS)


def static_projection(mode, period, zone, value, age, source, weather):
    """Explicit subset/order; no learner, gaming director, or owner dispatch."""
    state = resolve_activity_state(mode, period)
    if mode == "general" and zone == "desk" and qualified_lux(value, age, source):
        state = apply_general_desk_lux_balance(state, value, 90.0)
    # Separate functional compensation from mood aesthetics, as in the engine.
    if mode in ("working", "gaming", "watching"):
        state = apply_functional_weather_brightness(state, mode, period, weather)
    state = apply_zone_overlay(state, mode, period, zone, None)
    if mode not in WEATHER_SKIP_MODES:
        state = apply_weather_adjust(state, weather)
    before_cap = state
    state = enforce_fixture_comfort_invariants(state, mode, period, zone)
    return state, before_cap


def scenarios():
    """Execute each physical projection once, then expand cheap owner labels.

    Zone inputs assume upstream fresh source-qualified physical observations;
    None represents unknown, stale or unqualified zone. Bed posture is unknown.
    ScreenSync envelope uses neutral ambient multiplier 1, not inferred frame lux.
    """
    sync = ScreenSyncService(hue_service=None, target_light_ids=["2", "5"])
    for mode, period, sample, zone, screen, weather in product(
        ACTIVITIES, PERIODS, SAMPLES, ("desk", None, "couch", "bed"), SCREENS,
        ("clouds", "clear"),
    ):
        sample_name, value, age, source = sample
        state, before_cap = static_projection(mode, period, zone, value, age, source, weather)
        envelope = {
            lid: [sync.get_floor(mode, lid, zone=zone, period=period,
                                 weather_condition=weather),
                  sync.get_cap(mode, lid, zone=zone, posture=None, period=period,
                               weather_condition=weather)]
            for lid in ("2", "5")
        } if mode in ("watching", "gaming") else None
        monitor_base = resolve_target(mode, period, None, None)
        monitor = monitor_base
        if period == "evening":
            monitor = twilight_monitor_target(
                monitor_base, resolve_target(mode, "night", None, None),
                seconds_after_sunset=1800, bedroom_lux=value, baseline=90,
                sample_age=age, qualified_desk=zone == "desk",
                calibrated_bedroom=source == "bedroom",
            )
        findings = []
        if zone == "desk":
            # ANALYTIC ONLY ordinal comparisons, no comfort/safety threshold.
            # Exclude deliberately low-light Relax/Cooking from this review signal.
            if mode in ("general", "working", "watching", "gaming", "social"):
                if state["2"].get("bri", 0) < state["5"].get("bri", 0):
                    findings.append("static_l2_below_l5_review")
            if mode == "watching" and envelope["2"][0] < state["2"]["bri"]:
                findings.append("watching_floor_below_static_l2_review")
        for owner in OWNERS:
            yield {
                "activity": mode, "period": period, "sample": sample_name,
                "lux_value": value, "sample_age": age, "source": source,
                "zone": zone, "screen": screen, "owner": owner, "weather": weather,
                "neutral_page": is_neutral_page(*SCREENS[screen]),
                "candidate": state, "before_cap": before_cap, "envelope": envelope,
                "monitor_base": monitor_base, "monitor_candidate": monitor,
                "lux_evidence": "supported_input" if qualified_lux(value, age, source)
                                else "guarded_abstain",
                "owner_evidence": "unsupported_end_to_end",
                "owner_intent": "manual_strong_veto" if owner in ("manual_light", "scene")
                                else "requires_owner_dispatch",
                "findings": findings,
            }


def summarize(rows):
    groups = {axis: defaultdict(Counter) for axis in
              ("period", "activity", "owner", "source", "sample", "screen")}
    examples = {}
    total = 0
    for row in rows:
        total += 1
        for axis, buckets in groups.items():
            bucket = buckets[row[axis]]
            bucket["rows"] += 1
            bucket["supported_pure_target_subset"] += 1
            bucket[row["owner_evidence"]] += 1
            bucket[row["owner_intent"]] += 1
            bucket["neutral_page" if row["neutral_page"] else "non_neutral_content"] += 1
            bucket[row["lux_evidence"]] += 1
            for finding in row["findings"]:
                bucket[finding] += 1
        # Canonical clear-weather low-bedroom Desk examples; no owner duplication.
        if (row["owner"] == "auto" and row["sample"] == "bedroom_low"
                and row["weather"] == "clear" and row["zone"] == "desk"):
            if row["screen"] == "white_page" and row["period"] in ("evening", "night"):
                if row["activity"] in ("watching", "relax"):
                    examples[row["activity"] + "_" + row["period"]] = {
                        key: row[key] for key in ("activity", "period", "source", "sample", "zone",
                                                 "candidate", "envelope", "findings")
                    }
    return {"schema_version": 1, "total": total,
            "physical_content_projections": total // len(OWNERS),
            "groups": groups, "examples": examples,
            "limits": ["all owner decisions unsupported end-to-end",
                       "manual strong veto is an intent label, not executed suppression",
                       "Gaming table/envelope is not Gaming Director runtime",
                       "screen classifier and envelope only, no frame-to-brightness equation",
                       "no learner, physical lux, Hue writes, DDC or comfort guarantee"]}


def test_complete_offline_matrix(tmp_path, capsys):
    def checked_rows():
        for row in scenarios():
            state = row["candidate"]
            assert state["3"] == state["4"]
            assert row["monitor_candidate"] <= row["monitor_base"]
            assert state["5"].get("bri", 0) <= row["before_cap"]["5"].get("bri", 0)
            ceiling = get_fixture_comfort_brightness_ceiling(
                "5", row["activity"], row["period"], row["zone"],
            )
            if ceiling is not None and state["5"].get("on", True):
                assert state["5"].get("bri", 0) <= ceiling
            if row["envelope"]:
                assert all(lo <= hi for lo, hi in row["envelope"].values())
            assert all(not ("ct" in light and ("hue" in light or "sat" in light))
                       for light in state.values())
            assert row["neutral_page"] == (row["screen"] == "white_page")
            yield row

    summary = summarize(checked_rows())
    assert summary["total"] == 44352
    assert summary["physical_content_projections"] == 4032
    assert summary["examples"]["watching_evening"]["candidate"]["2"]["bri"] == 110
    assert summary["examples"]["watching_night"]["candidate"]["2"]["bri"] == 70
    assert all(bucket["unsupported_end_to_end"] == bucket["rows"]
               for bucket in summary["groups"]["owner"].values())
    output = tmp_path / "desk-all-day-summary.json"
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with capsys.disabled():
        print(f"\nDESK_MATRIX total={summary['total']} JSON={output}")


@pytest.mark.parametrize("mode,period", list(product(ACTIVITIES, PERIODS)))
def test_fixture_cap_only_never_energizes_or_uplifts(mode, period):
    for light in ({"on": False, "bri": 254}, {"on": True, "bri": 1},
                  {"on": True, "bri": 254}):
        original = {"5": light.copy()}
        result = enforce_fixture_comfort_invariants(original, mode, period, "desk")
        assert result["5"]["on"] == light["on"]
        assert result["5"]["bri"] <= light["bri"]
        assert original == {"5": light}
        if light["on"]:
            assert result["5"]["bri"] <= DESK_L5_COMFORT_CEILING[period]


@pytest.mark.parametrize("value,age,source", [
    (20, LUX_EMA_STALE_RESET_SECONDS + 1, "bedroom"),
    (180, LUX_EMA_STALE_RESET_SECONDS + 1, "bedroom"), (None, None, "none"),
    (20, 0, "unqualified_camera"), (-1, 0, "bedroom"),
    (float("nan"), 0, "bedroom"), (float("inf"), 0, "bedroom"),
])
def test_projection_untrusted_lux_abstains(value, age, source):
    assert not qualified_lux(value, age, source)
    for period in PERIODS:
        actual, _ = static_projection("general", period, "desk", value, age, source, "clear")
        neutral, _ = static_projection("general", period, "desk", None, None, "none", "clear")
        assert actual == neutral


def test_lux_requires_desk_and_weather_has_real_effect():
    for zone in (None, "couch", "bed"):
        low, _ = static_projection("general", "day", zone, 20, 0, "bedroom", "clear")
        high, _ = static_projection("general", "day", zone, 180, 0, "bedroom", "clear")
        assert low == high
    clear, _ = static_projection("working", "evening", "desk", 20, 0, "bedroom", "clear")
    clouds, _ = static_projection("working", "evening", "desk", 20, 0, "bedroom", "clouds")
    assert clouds["2"]["bri"] > clear["2"]["bri"]


@pytest.mark.parametrize("mode,period", list(product(("watching", "gaming"), PERIODS)))
def test_sync_l5_ambient_never_uplifts(mode, period):
    sync = ScreenSyncService(hue_service=None, target_light_ids=["2", "5"])
    neutral = sync.get_cap(mode, "5", "desk", None, period)
    for weather, multiplier in product(("clear", "clouds"), (0.6, 1, 1.5)):
        assert sync.get_cap(mode, "5", "desk", None, period, multiplier, weather) == neutral
        assert neutral <= DESK_L5_COMFORT_CEILING[period]


@pytest.mark.parametrize("period,static_l2,floor", [("evening", 110, 15), ("night", 70, 30)])
def test_watching_floor_gap_is_reproducible_not_a_new_comfort_floor(period, static_l2, floor):
    state, _ = static_projection("watching", period, "desk", 20, 0, "bedroom", "clear")
    sync = ScreenSyncService(hue_service=None, target_light_ids=["2", "5"])
    assert state["2"]["bri"] == static_l2
    assert sync.get_floor("watching", "2", zone="desk", period=period) == floor
    assert floor < static_l2  # ANALYTIC ONLY: calibrate physical usefulness before policy changes.


@pytest.mark.parametrize("age", [None, -1, 31, float("nan"), float("inf")])
def test_twilight_rejects_untrusted_sample(age):
    assert twilight_monitor_target(
        38, 24, seconds_after_sunset=1800, bedroom_lux=20, baseline=90,
        sample_age=age, qualified_desk=True, calibrated_bedroom=True,
    ) == 38


@pytest.mark.parametrize("desk,calibrated,lux", [(False, True, 20), (True, False, 20), (True, True, 180)])
def test_twilight_requires_room_correct_darkness(desk, calibrated, lux):
    assert twilight_monitor_target(
        38, 24, seconds_after_sunset=1800, bedroom_lux=lux, baseline=90,
        sample_age=0, qualified_desk=desk, calibrated_bedroom=calibrated,
    ) == 38


@pytest.mark.parametrize("elapsed,expected", [(-1, 38), (0, 38), (900, 31), (1800, 24), (5400, 24)])
def test_twilight_candidate_ramp(elapsed, expected):
    assert twilight_monitor_target(
        38, 24, seconds_after_sunset=elapsed, bedroom_lux=20, baseline=90,
        sample_age=0, qualified_desk=True, calibrated_bedroom=True,
    ) == expected


def test_white_page_classifier_excludes_dark_and_chromatic_content():
    assert is_neutral_page(245, 245, 245)
    assert not is_neutral_page(20, 20, 20)
    assert not is_neutral_page(255, 190, 190)
