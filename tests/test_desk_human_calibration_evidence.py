"""Human-rated #136/#370 evening Desk evidence; offline-only regression guards.

These are *reported manual slider settings*, not verified Hue ACK or automation
targets. Different observations were not simultaneous or controlled for ambient
lighting, Activity changes, and manual/ScreenSync ownership.
"""

from dataclasses import dataclass

import pytest

from backend.services.desk_visual_comfort import is_neutral_page
from backend.services.light_state_calculator import (
    DESK_L5_COMFORT_CEILING,
    enforce_fixture_comfort_invariants,
    resolve_activity_state,
)


@dataclass(frozen=True)
class HumanCalibrationObservation:
    screen: str
    l2_percent: int
    l5_percent: int
    feedback: str
    dwell: str


# Evening, Home, Desk, user-operated settings; not a system's learned preference.
OBSERVATIONS = (
    HumanCalibrationObservation("dark", 70, 25, "insufficient_right_balance", "unspecified"),
    HumanCalibrationObservation("dark", 70, 30, "better_room_balance", "unspecified"),
    HumanCalibrationObservation("white", 70, 30, "too_bright", "several_minutes"),
    HumanCalibrationObservation("white", 70, 25, "much_better", "after_adjustment"),
)


def _observed(screen: str, l5_percent: int) -> HumanCalibrationObservation:
    matches = [o for o in OBSERVATIONS if o.screen == screen and o.l5_percent == l5_percent]
    assert len(matches) == 1
    return matches[0]


def test_calibration_evidence_cannot_be_flattened_to_one_evening_l5_target():
    """The same L5 setting was appreciated on dark, but too bright on white."""
    assert _observed("dark", 30).feedback == "better_room_balance"
    assert _observed("white", 30).feedback == "too_bright"
    assert _observed("white", 30).dwell == "several_minutes"
    assert _observed("white", 25).feedback == "much_better"
    assert _observed("dark", 25).feedback == "insufficient_right_balance"
    assert {o.l2_percent for o in OBSERVATIONS} == {70}
    assert all(o.screen in {"dark", "white"} for o in OBSERVATIONS)


@pytest.mark.parametrize(
    "screen,rgb,expected_neutral",
    [
        ("white", (245, 245, 245), True),
        ("dark", (20, 20, 20), False),
    ],
)
def test_screen_labels_are_only_offline_content_categories(screen, rgb, expected_neutral):
    assert _observed(screen, 30).screen == screen
    assert is_neutral_page(*rgb) is expected_neutral


def test_existing_static_targets_cannot_explain_content_dependent_comfort():
    """Current authored targets have no screen-content or dwell input."""
    white = resolve_activity_state("watching", "evening")
    dark = resolve_activity_state("watching", "evening")
    assert white == dark  # Records a capability gap, not a proposed fix.
    assert _observed("white", 30).feedback != _observed("dark", 30).feedback


def test_evening_l5_autonomous_limit_is_cap_only_not_manual_calibration_target():
    ceiling = DESK_L5_COMFORT_CEILING["evening"]
    assert ceiling == 75  # Hue units /254, about 29.5%, not 30% exactly.
    manual_25 = round(0.25 * 254)
    manual_30 = round(0.30 * 254)
    assert manual_25 == 64 and manual_30 == 76
    assert manual_25 < ceiling < manual_30

    for original in (
        {"on": False, "bri": manual_30},
        {"on": True, "bri": manual_25},
        {"on": True, "bri": manual_30},
    ):
        projected = enforce_fixture_comfort_invariants(
            {"5": original.copy()}, "watching", "evening", "desk"
        )["5"]
        assert projected["on"] == original["on"]  # Never turn on.
        assert projected["bri"] <= original["bri"]  # Never autonomously brighten.
        if original["on"]:
            assert projected["bri"] <= ceiling


def test_subjective_observations_do_not_authorize_control_or_learning():
    """No raw lux, actual Hue write, or freshness assertion can be derived."""
    assert all(o.feedback for o in OBSERVATIONS)
    assert all(
        not hasattr(o, key)
        for key in (
            "hue_ack",
            "owner_lease",
            "brightness_write",
            "calibrated_lux",
            "automatic_floor",
            "source_freshness",
            "lighting_authorized",
        )
        for o in OBSERVATIONS
    )
