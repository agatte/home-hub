"""#370 L2 source-readiness evidence, not a runtime source adapter.

These tests show where *available* data is weaker than the assertions
required by the unwired L2 resolver.  They deliberately do not change source
semantics or establish physical calibration/write authority.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from backend.services.automation_constants import PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
from backend.services.desk_visual_comfort import (
    DeskDiffuseL2Context,
    resolve_desk_diffuse_l2_candidate,
)
from backend.services.lux_channel import LuxChannel
from backend.services.presence_fusion import PresenceFusion, PresenceReading


def _synthetic_context(**changes):
    # All positive assertions are *synthetic*: they are not produced by
    # LuxChannel, PresenceFusion, or a trusted runtime adapter.
    base = DeskDiffuseL2Context(
        activity="general", period="day", calibration_period="day",
        calibrated_floor=120, original_l2_bri=60, effective_l2_cap=180,
        branch="static", house_state="Home", awake=True,
        physical_source="desktop", physical_zone="desk",
        physical_qualified=True, physical_fresh=True,
        eligible_screen_viewing=True, calibration_verified=True,
        bedroom_lux_trusted=True, bedroom_lux_calibrated=True,
        bedroom_lux_room_qualified=True, bedroom_lux_fresh=True,
        original_l2_on=True, rebrightening_authorized=True,
        transition_epoch_current=True,
    )
    return replace(base, **changes)


def test_bedroom_calibration_baseline_is_not_a_qualified_reading():
    channel = LuxChannel("bedroom")
    channel.update(80.0)
    # Shadow status includes raw EMA before a usable calibrated baseline exists.
    assert channel.status()["ema_lux"] == 80.0
    assert channel.ema_lux is None
    decision = resolve_desk_diffuse_l2_candidate(
        _synthetic_context(bedroom_lux_calibrated=False, calibration_verified=False)
    )
    assert decision.candidate_l2 is None
    assert decision.reason == "unverified_calibration"


def test_fresh_living_room_lux_is_not_bedroom_lux():
    channel = LuxChannel("living-room", baseline_lux=85)
    channel.update(55.0)
    assert channel.is_fresh(30) and channel.ema_lux == 55.0
    assert channel.room != "bedroom"
    result = resolve_desk_diffuse_l2_candidate(
        _synthetic_context(bedroom_lux_room_qualified=False)
    )
    assert result.candidate_l2 is None
    assert result.reason == "untrusted_lux"


def test_low_level_lux_freshness_alone_accepts_future_stamps():
    # The desktop HTTP ingest route clamps forward skew above 2 seconds; the
    # generic store is also callable in-process. Its is_fresh checks only
    # age <= max_age, not a nonnegative age / proven source identity.
    channel = LuxChannel("bedroom", baseline_lux=85.0)
    channel.update(55.0, captured_at=datetime.now(timezone.utc) + timedelta(minutes=1))
    assert channel.is_fresh(30) is True
    result = resolve_desk_diffuse_l2_candidate(
        _synthetic_context(bedroom_lux_fresh=False)
    )
    assert result.candidate_l2 is None
    assert result.reason == "untrusted_lux"


def test_raw_desktop_source_snapshot_is_not_policy_freshness():
    now = datetime.now(timezone.utc)
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop",
        captured_at=now - timedelta(seconds=PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS + 1),
        face_present=True,
        detection_source="face",
        zone="desk",
    ))
    reading = fusion.get_source_reading("desktop")
    assert reading is not None and reading.source == "desktop"
    assert reading.zone == "desk" and reading.face_present is True
    assert (now - reading.captured_at).total_seconds() > PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
    result = resolve_desk_diffuse_l2_candidate(
        _synthetic_context(physical_fresh=False)
    )
    assert result.candidate_l2 is None
    assert result.reason == "ineligible_context"


def test_screen_sync_snapshot_assertion_cannot_replace_live_frame_guard():
    # The resolver is pure and cannot enforce the write boundary's epoch.
    before = _synthetic_context(
        branch="screen_sync", screen_sync_owns_l2=True,
        screen_sync_lease_current=True, same_frame_guard_guaranteed=True,
    )
    assert resolve_desk_diffuse_l2_candidate(before).candidate_l2 == 120
    unsafe = replace(before, same_frame_guard_guaranteed=False)
    result = resolve_desk_diffuse_l2_candidate(unsafe)
    assert result.candidate_l2 is None
    assert result.reason == "screen_sync_guard_missing"
    # An unchanged early snapshot will STILL propose a candidate.
    assert resolve_desk_diffuse_l2_candidate(before).candidate_l2 == 120
