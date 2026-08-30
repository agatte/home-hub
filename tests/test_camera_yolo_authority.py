from __future__ import annotations

import pytest

from backend.services.camera_yolo_authority import YoloPresenceAuthority


def test_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError):
        YoloPresenceAuthority(person_confidence_threshold=0.0)
    with pytest.raises(ValueError):
        YoloPresenceAuthority(
            person_confidence_threshold=0.25,
            blinded_confidence_ceiling=0.25,
        )
    with pytest.raises(ValueError):
        YoloPresenceAuthority(present_dwell_frames=0)


def test_near_closed_lid_signature_abstains() -> None:
    authority = YoloPresenceAuthority()
    for confidence in (None, 0.00199, 0.00413, 0.01):
        assert authority.evaluate(confidence) == "unknown"


def test_empty_room_furniture_is_absence_candidate() -> None:
    authority = YoloPresenceAuthority()
    for confidence in (0.05, 0.0811, 0.10, 0.169, 0.232):
        assert authority.evaluate(confidence) == "absent"


def test_real_person_requires_three_frame_dwell() -> None:
    authority = YoloPresenceAuthority()
    assert authority.evaluate(0.308) == "unknown"
    assert authority.evaluate(0.681) == "unknown"
    assert authority.evaluate(0.815) == "present"
    assert authority.evaluate(0.262) == "present"


def test_subthreshold_frame_resets_pending_presence_dwell() -> None:
    authority = YoloPresenceAuthority()
    assert authority.evaluate(0.30) == "unknown"
    assert authority.evaluate(0.23) == "absent"
    assert authority.evaluate(0.30) == "unknown"
    assert authority.evaluate(0.30) == "unknown"
    assert authority.evaluate(0.30) == "present"


def test_blinded_frame_resets_pending_presence_dwell() -> None:
    authority = YoloPresenceAuthority()
    assert authority.evaluate(0.30) == "unknown"
    assert authority.evaluate(0.004) == "unknown"
    assert authority.evaluate(0.30) == "unknown"
    assert authority.evaluate(0.30) == "unknown"
    assert authority.evaluate(0.30) == "present"


def test_reset_clears_pending_dwell() -> None:
    authority = YoloPresenceAuthority(present_dwell_frames=2)
    assert authority.evaluate(0.3) == "unknown"
    authority.reset()
    assert authority.evaluate(0.3) == "unknown"
    assert authority.evaluate(0.3) == "present"
