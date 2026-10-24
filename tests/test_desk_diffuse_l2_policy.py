"""Fictional calibration numbers prove pure math, never physical comfort."""
from dataclasses import FrozenInstanceError, asdict, replace
from itertools import product

import pytest

from backend.services.desk_visual_comfort import (
    DeskDiffuseL2Context,
    resolve_desk_diffuse_l2_candidate as resolve,
)


def eligible(**changes):
    return replace(DeskDiffuseL2Context(
        activity="general", period="day", calibration_period="day", calibrated_floor=120,
        original_l2_bri=60, effective_l2_cap=180, branch="static", house_state="Home",
        awake=True, physical_source="desktop", physical_zone="desk", physical_qualified=True,
        physical_fresh=True, eligible_screen_viewing=True, calibration_verified=True,
        bedroom_lux_trusted=True, bedroom_lux_calibrated=True, bedroom_lux_room_qualified=True,
        bedroom_lux_fresh=True, original_l2_on=True, rebrightening_authorized=True,
        transition_epoch_current=True,
    ), **changes)


@pytest.mark.parametrize("activity,period,branch", list(product(
    ("general", "working", "watching", "gaming", "relax", "social", "cooking"),
    ("day", "evening", "night", "late_night"), ("static", "screen_sync"),
)))
def test_seven_activities_four_periods_two_composers(activity, period, branch):
    c = eligible(activity=activity, period=period, calibration_period=period, branch=branch,
                 screen_sync_owns_l2=branch == "screen_sync", screen_sync_lease_current=True,
                 same_frame_guard_guaranteed=True)
    d = resolve(c)
    assert d.candidate_l2 == (120 if activity in ("general", "working", "watching") else None)
    assert d.reason == ("candidate" if d.candidate_l2 else "ineligible_activity")


@pytest.mark.parametrize("field,value,reason", [
    *[(field, False, "ineligible_context") for field in (
        "awake", "physical_qualified", "physical_fresh", "eligible_screen_viewing")],
    *[("house_state", state, "ineligible_context") for state in (
        "Away", "Winding Down", "Sleeping", "unknown")],
    *[("physical_source", source, "ineligible_context") for source in (
        "process", "latitude", "camera", "unknown")],
    *[("physical_zone", zone, "ineligible_context") for zone in ("bed", "couch", "unknown")],
    *[(field, False, "untrusted_lux") for field in (
        "bedroom_lux_trusted", "bedroom_lux_calibrated", "bedroom_lux_room_qualified",
        "bedroom_lux_fresh")],
    *[(field, True, "owner_veto") for field in (
        "dnd", "manual_l2", "scene", "effect", "transit", "protected", "external_owner",
        "external_off", "hard_off", "stronger_device_owner")],
    ("rebrightening_authorized", False, "owner_veto"),
    ("calibration_verified", False, "unverified_calibration"),
    ("calibrated_floor", None, "unverified_calibration"),
    ("calibration_period", "night", "unverified_calibration"),
    ("transition_epoch_current", False, "stale_boundary"),
    ("original_l2_on", False, "preserve_off"),
    ("screen_sync_owns_l2", True, "screen_sync_owner"),
    ("period", "unknown", "invalid_input"),
    ("branch", "other_writer", "invalid_input"),
    ("awake", 1, "invalid_input"),
])
def test_abstention_gates(field, value, reason):
    d = resolve(eligible(**{field: value}))
    assert d.reason == reason
    assert d.candidate_l2 is None


@pytest.mark.parametrize("period", ("day", "evening", "night", "late_night"))
@pytest.mark.parametrize("game,allowed", [
    (None, False), ("accepted_director", True), ("rust", False), ("game_day", False),
    ("unrecognized", False),
])
def test_gaming_requires_explicit_accepted_director(period, game, allowed):
    assert (resolve(eligible(activity="gaming", gaming_context=game, period=period,
                             calibration_period=period)).candidate_l2 is not None) == allowed


@pytest.mark.parametrize("field", (
    "screen_sync_owns_l2", "screen_sync_lease_current", "same_frame_guard_guaranteed",
))
def test_screen_sync_requires_all_external_guards(field):
    c = eligible(branch="screen_sync", screen_sync_owns_l2=True,
                 screen_sync_lease_current=True, same_frame_guard_guaranteed=True)
    assert resolve(replace(c, **{field: False})).reason == "screen_sync_guard_missing"


@pytest.mark.parametrize("field", ("calibrated_floor", "original_l2_bri", "effective_l2_cap"))
@pytest.mark.parametrize("value", (float("nan"), float("inf"), -float("inf"), 0, -1, 255,
                                  True, 1.5, "120"))
def test_invalid_brightness_fails_closed(field, value):
    d = resolve(eligible(**{field: value}))
    assert d.reason == "invalid_input"
    assert d.candidate_l2 is None


@pytest.mark.parametrize("floor,cap,target,reason,capped", [
    (50, 180, None, "no_lift", False), (60, 180, None, "no_lift", False),
    (120, 100, 100, "candidate_capped", True),
    (120, 60, None, "no_lift", True), (120, 59, None, "cap_below_original", True),
    (120, 120, 120, "candidate", False), (254, 254, 254, "candidate", False),
])
def test_floor_cap_and_original(floor, cap, target, reason, capped):
    d = resolve(eligible(calibrated_floor=floor, effective_l2_cap=cap))
    assert (d.candidate_l2, d.reason, d.capped) == (target, reason, capped)


def test_monotonic_clamping_entire_hue_domain():
    for cap in (1, 59, 60, 61, 120, 254):
        previous = 60
        for floor in range(1, 255):
            d = resolve(eligible(calibrated_floor=floor, effective_l2_cap=cap))
            actual = d.candidate_l2 if d.candidate_l2 is not None else 60
            assert actual >= previous
            if d.candidate_l2 is not None:
                assert 60 < d.candidate_l2 <= cap
            previous = actual
    for floor in (1, 60, 120, 254):
        targets = [resolve(eligible(calibrated_floor=floor, effective_l2_cap=cap)).candidate_l2
                   for cap in range(1, 255)]
        assert [t or 60 for t in targets] == sorted(t or 60 for t in targets)


def test_never_relight_even_with_full_floor():
    assert resolve(eligible(original_l2_on=False, calibrated_floor=254)).candidate_l2 is None


def test_snapshot_staleness_is_only_a_synthetic_boundary():
    c = eligible()
    assert resolve(c).candidate_l2 == 120
    assert resolve(replace(c, transition_epoch_current=False)).reason == "stale_boundary"
    # Old immutable snapshot remains eligible: this helper cannot implement final fencing.
    assert resolve(c).candidate_l2 == 120


def test_immutable_identity_no_mutation_and_repeatable():
    c = eligible()
    before = asdict(c)
    d = resolve(c)
    assert asdict(c) == before
    assert resolve(c) == d
    assert d.light_id == "2"
    assert d.policy == "desk_diffuse_l2_unwired_v1"
    with pytest.raises(FrozenInstanceError):
        c.original_l2_on = False
    with pytest.raises(FrozenInstanceError):
        d.candidate_l2 = 254
