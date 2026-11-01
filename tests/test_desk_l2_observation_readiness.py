"""#370 advisory source-readiness regression tests, no runtime caller/Hue."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.desk_l2_observation_readiness import (
    assess_desk_l2_observations,
)
from backend.services.lux_channel import LuxChannel
from backend.services.presence_fusion import PresenceReading

NOW = datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc)


def desk(**changes):
    return replace(
        PresenceReading(
            source="desktop",
            captured_at=NOW,
            zone="desk",
            face_present=True,
            detection_source="face",
        ),
        **changes,
    )


def opposition(**changes):
    return replace(
        PresenceReading(
            source="latitude",
            captured_at=NOW,
            zone="couch",
            face_present=True,
            detection_source="yolo",
        ),
        **changes,
    )


def channel(*, room="bedroom", baseline=80.0, sample=40.0, when=NOW):
    c = LuxChannel(room, baseline_lux=baseline)
    if sample is not None:
        c.update(sample, captured_at=when)
    return c


def assess(*, desktop=None, latitude=None, bedroom=None, now=NOW):
    return assess_desk_l2_observations(
        desktop=desk() if desktop is None else desktop,
        latitude=latitude,
        bedroom_channel=channel() if bedroom is None else bedroom,
        now=now,
    )


def test_both_observations_ready_never_grant_lighting_authority():
    result = assess()
    assert result.desktop_observation_ready is True
    assert result.bedroom_sample_ready is True
    assert result.reasons == ()
    assert result.authorizes_lighting is False
    assert not hasattr(result, "candidate_l2")
    with pytest.raises(FrozenInstanceError):
        result.authorizes_lighting = True


@pytest.mark.parametrize(
    "bad",
    [
        {"source": "latitude"},
        {"zone": "bed"},
        {"zone": None},
        {"face_present": False},
        {"face_present": 1},
        {"detection_source": "pose"},
        {"detection_source": "process"},
        {"captured_at": NOW - timedelta(seconds=9)},
        {"captured_at": NOW + timedelta(seconds=3)},
        {"captured_at": NOW.replace(tzinfo=None)},
    ],
)
def test_physical_desk_fails_closed_for_source_face_zone_and_age(bad):
    result = assess(desktop=desk(**bad))
    assert result.desktop_observation_ready is False
    assert "desktop_unqualified" in result.reasons
    assert result.bedroom_sample_ready is True


@pytest.mark.parametrize("age", [-2, 0, 8])
def test_desk_inclusive_existing_source_window(age):
    result = assess(desktop=desk(captured_at=NOW - timedelta(seconds=age)))
    assert result.desktop_observation_ready is True


@pytest.mark.parametrize(
    "bad",
    [
        {"zone": "couch"},
        {"zone": "bed"},
    ],
)
def test_fresh_strong_latitude_conflict_beats_fresh_desktop(bad):
    result = assess(latitude=opposition(**bad))
    assert result.desktop_observation_ready is False
    assert result.reasons == ("opposing_physical_presence",)


@pytest.mark.parametrize(
    "change",
    [
        {"face_present": False},
        {"detection_source": "face", "face_confidence": 0.0},
        {"captured_at": NOW - timedelta(seconds=9)},
        {"captured_at": NOW + timedelta(seconds=3)},
        {"zone": "desk"},
    ],
)
def test_weak_stale_future_or_nonconflicting_latitude_does_not_override(change):
    assert assess(latitude=opposition(**change)).desktop_observation_ready is True


@pytest.mark.parametrize(
    "room,baseline,sample,age",
    [
        ("living-room", 80.0, 40.0, 0),
        ("bedroom", None, 40.0, 0),
        ("bedroom", 0.0, 40.0, 0),
        ("bedroom", -1.0, 40.0, 0),
        ("bedroom", float("nan"), 40.0, 0),
        ("bedroom", float("inf"), 40.0, 0),
        ("bedroom", 80.0, None, 0),
        ("bedroom", 80.0, -1.0, 0),
        ("bedroom", 80.0, float("nan"), 0),
        ("bedroom", 80.0, float("inf"), 0),
        ("bedroom", 80.0, 40.0, 301),
        ("bedroom", 80.0, 40.0, -3),
    ],
)
def test_lux_rejects_wrong_room_uncalibrated_nonfinite_stale_and_future(
    room,
    baseline,
    sample,
    age,
):
    result = assess(
        bedroom=channel(
            room=room,
            baseline=baseline,
            sample=sample,
            when=NOW - timedelta(seconds=age),
        )
    )
    assert result.desktop_observation_ready is True
    assert result.bedroom_sample_ready is False
    assert result.reasons == ("bedroom_lux_unqualified",)


@pytest.mark.parametrize("age", [-2, 0, 300])
def test_bedroom_sample_allowed_bounds_are_advisory_only(age):
    result = assess(bedroom=channel(when=NOW - timedelta(seconds=age)))
    assert result.bedroom_sample_ready is True
    assert result.authorizes_lighting is False


def test_timezone_naive_clock_abstains_instead_of_creating_source_freshness():
    result = assess(now=NOW.replace(tzinfo=None))
    assert not result.desktop_observation_ready
    assert not result.bedroom_sample_ready
    assert result.reasons == ("desktop_unqualified", "bedroom_lux_unqualified")


def test_all_missing_inputs_fail_closed():
    result = assess_desk_l2_observations(
        desktop=None,
        latitude=None,
        bedroom_channel=None,
        now=NOW,
    )
    assert result.reasons == ("desktop_unqualified", "bedroom_lux_unqualified")
    assert not result.authorizes_lighting


def test_snapshot_reuse_after_new_conflict_does_not_grant_future_owner():
    early = assess()
    late = assess(latitude=opposition())
    assert early.desktop_observation_ready
    assert not late.desktop_observation_ready
    # A reusable pure earlier record cannot authorize the real final write.
    assert early.authorizes_lighting is False
    assert late.authorizes_lighting is False


@pytest.mark.parametrize("age", [-2, 0, 8])
@pytest.mark.parametrize("kind", ["yolo", "pose"])
def test_strong_latitude_conflict_existing_age_boundaries(age, kind):
    lat = opposition(
        detection_source=kind,
        captured_at=NOW - timedelta(seconds=age),
    )
    assert assess(latitude=lat).desktop_observation_ready is False


def test_latitude_face_threshold_and_wrong_source_are_not_conflated():
    from backend.services.presence_fusion import LATITUDE_STRONG_FACE_THRESHOLD

    at_threshold = opposition(
        detection_source="face",
        face_confidence=LATITUDE_STRONG_FACE_THRESHOLD,
    )
    below_threshold = replace(
        at_threshold,
        face_confidence=LATITUDE_STRONG_FACE_THRESHOLD - 0.01,
    )
    wrong_source = replace(at_threshold, source="desktop")
    assert not assess(latitude=at_threshold).desktop_observation_ready
    assert assess(latitude=below_threshold).desktop_observation_ready
    assert assess(latitude=wrong_source).desktop_observation_ready


def test_classification_never_mutates_incoming_observations():
    desktop = desk()
    latitude = opposition(zone="desk")
    lux = channel()
    before = (desktop, latitude, lux.status(), lux.last_lux_update)
    first = assess(desktop=desktop, latitude=latitude, bedroom=lux)
    second = assess(desktop=desktop, latitude=latitude, bedroom=lux)
    assert first == second
    assert (desktop, latitude, lux.status(), lux.last_lux_update) == before
    assert first.authorizes_lighting is False
