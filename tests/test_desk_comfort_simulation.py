"""Offline candidate matrix, deliberately not an end-to-end owner simulation.

Reproduce: python -B -m pytest -p no:cacheprovider -s this_file
No Hue/DDC/HTTP calls. Reported values are candidates, never physical adequacy.
"""
from collections import Counter
from itertools import product

import pytest

from backend.services.desk_visual_comfort import is_neutral_page, twilight_monitor_target
from backend.services.light_state_calculator import (
    apply_general_desk_lux_balance,
    apply_zone_overlay,
    enforce_fixture_comfort_invariants,
    resolve_activity_state,
)
from backend.services.screen_sync import ScreenSyncService
from backend.services.pc_agent.monitor_brightness import resolve_target

ACTIVITIES = ("general", "working", "watching", "gaming", "relax", "social", "cooking")
PERIODS = ("day", "evening", "night", "late_night")
OWNERS = ("auto", "manual_activity", "manual_light", "scene", "screen_sync", "away", "sleeping")


def scenarios():
    """All axes are enumerated; unsupported composition is marked explicitly."""
    sync = ScreenSyncService(hue_service=None, target_light_ids=["2", "5"])
    for mode, period, ambient, freshness, zone, screen, owner, weather in product(
        ACTIVITIES, PERIODS, ("dark", "bright"), ("fresh", "stale", "missing"),
        ("desk", None, "couch", "bed"), ("white_page", "dark_screen", "media"),
        OWNERS, ("clouds", "clear"),
    ):
        state = resolve_activity_state(mode, period)
        state = apply_zone_overlay(state, mode, period, zone, None)
        if mode == "general" and zone == "desk" and freshness == "fresh":
            state = apply_general_desk_lux_balance(
                state, 20.0 if ambient == "dark" else 180.0, 90.0,
            )
        state = enforce_fixture_comfort_invariants(state, mode, period, zone)
        envelope = None
        if mode == "watching":
            envelope = tuple(
                (sync.get_floor(mode, lid, zone=zone, period=period,
                                weather_condition=weather),
                 sync.get_cap(mode, lid, zone=zone, posture=None, period=period,
                              weather_condition=weather))
                for lid in ("2", "5")
            )
        monitor_base = resolve_target(mode, period, None, None)
        monitor_candidate = monitor_base
        if period == "evening":
            monitor_candidate = twilight_monitor_target(
                monitor_base, resolve_target(mode, "night", None, None),
                seconds_after_sunset=1800,
                bedroom_lux=20 if ambient == "dark" else 180, baseline=90,
                sample_age={"fresh": 0, "stale": 31, "missing": None}[freshness],
                qualified_desk=zone == "desk", calibrated_bedroom=True,
            )
        yield {
            "mode": mode, "period": period, "ambient": ambient,
            "freshness": freshness, "zone": zone, "screen": screen,
            "owner": owner, "weather": weather, "candidate": state,
            "watching_envelope": envelope,
            "monitor_base": monitor_base, "monitor_twilight_candidate": monitor_candidate,
            "gap": "owner_dispatch" if owner not in ("auto", "manual_activity") else "pipeline_subset",
        }


def test_complete_offline_matrix(capsys):
    count = Counter()
    for row in scenarios():
        count[row["gap"]] += 1
        state = row["candidate"]
        assert state
        assert row["monitor_twilight_candidate"] <= row["monitor_base"]
        assert state["3"] == state["4"]
        if row["watching_envelope"]:
            assert all(lo <= hi for lo, hi in row["watching_envelope"])
        assert all(not ("ct" in light and ("hue" in light or "sat" in light))
                   for light in state.values())
    assert sum(count.values()) == 28224
    # -s makes this stable summary available for the handoff report.
    with capsys.disabled():
        print(f"\nDESK_MATRIX total={sum(count.values())} gaps={dict(count)}")


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
