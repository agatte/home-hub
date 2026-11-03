"""#370 cross-prototype safety reconciliation, still purely non-actuating.

The published desk_visual_comfort resolver is canonical for this offline candidate.
Do not import the alternate unpublished desk_diffuse_eligibility policy or infer
sensor evidence, ownership, calibration, or device write permission here.
"""

from dataclasses import fields, replace

import pytest

from backend.services.desk_visual_comfort import (
    DeskDiffuseL2Context,
    resolve_desk_diffuse_l2_candidate,
)


def _context(**changes):
    base = DeskDiffuseL2Context(
        activity="general",
        period="evening",
        calibration_period="evening",
        calibrated_floor=120,
        original_l2_bri=60,
        effective_l2_cap=180,
        branch="static",
        house_state="Home",
        awake=True,
        physical_source="desktop",
        physical_zone="desk",
        physical_qualified=True,
        physical_fresh=True,
        eligible_screen_viewing=True,
        calibration_verified=True,
        bedroom_lux_trusted=True,
        bedroom_lux_calibrated=True,
        bedroom_lux_room_qualified=True,
        bedroom_lux_fresh=True,
        original_l2_on=True,
        rebrightening_authorized=True,
        transition_epoch_current=True,
    )
    return replace(base, **changes)


def _decision(**changes):
    return resolve_desk_diffuse_l2_candidate(_context(**changes))


@pytest.mark.parametrize(
    "state",
    [
        "home",
        "HOME",
        "Away",
        "Winding Down",
        "Sleeping",
        "",
        None,
    ],
)
def test_only_explicit_user_facing_home_is_eligible(state):
    result = _decision(house_state=state)
    assert result.candidate_l2 is None
    assert result.reason == "ineligible_context"


@pytest.mark.parametrize("field", [f.name for f in fields(DeskDiffuseL2Context) if f.type is bool])
@pytest.mark.parametrize("not_a_boolean", [0, 1, None, "true", float("nan")])
def test_all_trusted_boolean_assertions_fail_closed_on_bad_type(field, not_a_boolean):
    # True and 1 are equal in Python; the published contract must not equate them.
    result = _decision(**{field: not_a_boolean})
    assert result.candidate_l2 is None
    assert result.reason == "invalid_input"


@pytest.mark.parametrize(
    "veto",
    [
        "dnd",
        "manual_l2",
        "scene",
        "effect",
        "transit",
        "protected",
        "external_owner",
        "external_off",
        "hard_off",
        "stronger_device_owner",
    ],
)
def test_upstream_rebrightening_assertion_cannot_override_veto(veto):
    result = _decision(**{veto: True})
    assert result.candidate_l2 is None
    assert result.reason == "owner_veto"


@pytest.mark.parametrize(
    "fact",
    [
        "physical_qualified",
        "physical_fresh",
        "eligible_screen_viewing",
    ],
)
def test_software_activity_cannot_substitute_for_physical_desk(fact):
    result = _decision(activity="working", **{fact: False})
    assert result.candidate_l2 is None
    assert result.reason == "ineligible_context"


@pytest.mark.parametrize(
    "fact",
    [
        "bedroom_lux_trusted",
        "bedroom_lux_calibrated",
        "bedroom_lux_room_qualified",
        "bedroom_lux_fresh",
    ],
)
def test_generic_or_stale_lux_cannot_enable_floor(fact):
    result = _decision(**{fact: False})
    assert result.candidate_l2 is None
    assert result.reason == "untrusted_lux"


def test_one_policy_for_owned_screensync_and_unowned_static():
    owned = dict(
        screen_sync_owns_l2=True,
        screen_sync_lease_current=True,
        same_frame_guard_guaranteed=True,
    )
    assert _decision(branch="static", **owned).reason == "screen_sync_owner"
    assert _decision(branch="screen_sync", **owned).candidate_l2 == 120
    for field in owned:
        result = _decision(branch="screen_sync", **{**owned, field: False})
        assert result.candidate_l2 is None
        assert result.reason == "screen_sync_guard_missing"
    assert _decision(branch="screen_sync", dnd=True, **owned).reason == "owner_veto"


def test_cap_and_off_cannot_be_promoted_to_write_permission():
    assert _decision(original_l2_on=False).reason == "preserve_off"
    assert _decision(effective_l2_cap=50).reason == "cap_below_original"
    capped = _decision(effective_l2_cap=90)
    assert capped.candidate_l2 == 90
    assert capped.capped is True
    assert capped.light_id == "2"
    assert capped.policy == "desk_diffuse_l2_unwired_v1"


def test_immutable_earlier_snapshot_is_not_final_ownership_fence():
    early = _context()
    assert resolve_desk_diffuse_l2_candidate(early).candidate_l2 == 120
    assert (
        resolve_desk_diffuse_l2_candidate(replace(early, transition_epoch_current=False)).reason
        == "stale_boundary"
    )
    # Re-reading the early immutable assertion still returns a candidate:
    # only the real serialized final write boundary can reject that race.
    assert resolve_desk_diffuse_l2_candidate(early).candidate_l2 == 120
