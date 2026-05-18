"""Tests for the desktop pc_agent's frontal-posture classifier.

The classifier is a pair of pure functions in ``emotion_capture``:

  - ``_compute_head_drop_ratio(pose_landmarks, min_visibility)`` —
    returns the normalized ``(shoulder_mid_y - nose.y) / (hip_mid_y -
    nose.y)`` ratio, or ``None`` when landmarks aren't all visible above
    threshold (or torso geometry is degenerate).
  - ``_classify_posture(head_drop, prior)`` — maps the ratio to
    ``"upright"`` / ``"slouched"`` / ``None`` via a 0.46/0.54 dead-band
    that preserves ``prior`` between the bands.

MediaPipe isn't required to test these — synthetic landmark objects
expose the same ``.x``/``.y``/``.visibility`` attributes.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from backend.services.pc_agent.emotion_capture import (
    POSE_LEFT_HIP,
    POSE_LEFT_SHOULDER,
    POSE_NOSE,
    POSE_RIGHT_HIP,
    POSE_RIGHT_SHOULDER,
    POSTURE_HYSTERESIS_FRAMES,
    POSTURE_SLOUCHED,
    POSTURE_UPRIGHT,
    _classify_posture,
    _compute_head_drop_ratio,
)


@dataclass
class _Landmark:
    """Minimal stand-in for MediaPipe's NormalizedLandmark."""

    x: float
    y: float
    visibility: float = 0.95


def _make_pose(
    nose_y: float,
    shoulder_y: float,
    hip_y: float,
    visibility: float = 0.95,
    hip_visibility: float | None = None,
) -> list[_Landmark]:
    """Build a 33-element landmark list with the five indices we use."""
    hip_v = hip_visibility if hip_visibility is not None else visibility
    landmarks = [_Landmark(x=0.5, y=0.5, visibility=0.0) for _ in range(33)]
    landmarks[POSE_NOSE] = _Landmark(x=0.5, y=nose_y, visibility=visibility)
    landmarks[POSE_LEFT_SHOULDER] = _Landmark(
        x=0.4, y=shoulder_y, visibility=visibility,
    )
    landmarks[POSE_RIGHT_SHOULDER] = _Landmark(
        x=0.6, y=shoulder_y, visibility=visibility,
    )
    landmarks[POSE_LEFT_HIP] = _Landmark(x=0.42, y=hip_y, visibility=hip_v)
    landmarks[POSE_RIGHT_HIP] = _Landmark(x=0.58, y=hip_y, visibility=hip_v)
    return landmarks


# ---------------------------------------------------------------------------
# _compute_head_drop_ratio
# ---------------------------------------------------------------------------


def test_upright_geometry_yields_low_ratio() -> None:
    # Head at top, shoulders ~1/3 down torso, hips at bottom →
    # ratio (shoulder - nose) / (hip - nose) ≈ 0.4
    pose = _make_pose(nose_y=0.20, shoulder_y=0.40, hip_y=0.70)
    ratio = _compute_head_drop_ratio(pose)
    assert ratio is not None
    assert ratio == pytest.approx(0.40, abs=0.01)


def test_slouched_geometry_yields_high_ratio() -> None:
    # Head dropped close to shoulder line → ratio ~0.6 (head sits low
    # in the torso bbox)
    pose = _make_pose(nose_y=0.35, shoulder_y=0.55, hip_y=0.70)
    ratio = _compute_head_drop_ratio(pose)
    assert ratio is not None
    assert ratio == pytest.approx((0.55 - 0.35) / (0.70 - 0.35), abs=0.001)
    assert ratio > 0.54


def test_low_visibility_returns_none() -> None:
    pose = _make_pose(nose_y=0.2, shoulder_y=0.4, hip_y=0.7, visibility=0.3)
    assert _compute_head_drop_ratio(pose) is None


def test_low_hip_visibility_returns_none() -> None:
    # Latitude's pattern: hips often the weak landmark. We should also
    # bail when only the hips are weak.
    pose = _make_pose(
        nose_y=0.2, shoulder_y=0.4, hip_y=0.7,
        visibility=0.95, hip_visibility=0.4,
    )
    assert _compute_head_drop_ratio(pose) is None


def test_degenerate_torso_returns_none() -> None:
    # Hip at or above nose — anatomically impossible / misdetection.
    pose = _make_pose(nose_y=0.6, shoulder_y=0.5, hip_y=0.6)
    assert _compute_head_drop_ratio(pose) is None


def test_none_input_returns_none() -> None:
    assert _compute_head_drop_ratio(None) is None


def test_empty_landmarks_list_returns_none() -> None:
    assert _compute_head_drop_ratio([]) is None


def test_min_visibility_param_is_respected() -> None:
    pose = _make_pose(nose_y=0.2, shoulder_y=0.4, hip_y=0.7, visibility=0.5)
    # Default threshold 0.6 → None
    assert _compute_head_drop_ratio(pose) is None
    # Loosened threshold → returns a value
    assert _compute_head_drop_ratio(pose, min_visibility=0.4) is not None


# ---------------------------------------------------------------------------
# _classify_posture
# ---------------------------------------------------------------------------


def test_clearly_upright_returns_upright_high_confidence() -> None:
    posture, conf = _classify_posture(head_drop=0.35, prior=None)
    assert posture == POSTURE_UPRIGHT
    # 0.50 - 0.35 = 0.15 → 0.15 * 5 = 0.75
    assert conf == pytest.approx(0.75, abs=0.001)


def test_clearly_slouched_returns_slouched_high_confidence() -> None:
    posture, conf = _classify_posture(head_drop=0.60, prior=None)
    assert posture == POSTURE_SLOUCHED
    assert conf == pytest.approx(0.50, abs=0.001)


def test_dead_band_with_prior_upright_keeps_upright() -> None:
    posture, conf = _classify_posture(head_drop=0.48, prior=POSTURE_UPRIGHT)
    assert posture == POSTURE_UPRIGHT
    # Confidence reflects how close to the boundary we are
    assert conf is not None
    assert conf == pytest.approx(0.10, abs=0.001)


def test_dead_band_with_prior_slouched_keeps_slouched() -> None:
    posture, _ = _classify_posture(head_drop=0.52, prior=POSTURE_SLOUCHED)
    assert posture == POSTURE_SLOUCHED


def test_dead_band_with_no_prior_returns_none() -> None:
    posture, conf = _classify_posture(head_drop=0.50, prior=None)
    assert posture is None
    # Confidence shouldn't leak a value when posture is None — caller
    # uses both fields together
    assert conf is None


def test_upright_boundary_inclusive() -> None:
    posture, _ = _classify_posture(head_drop=0.46, prior=None)
    assert posture == POSTURE_UPRIGHT


def test_slouched_boundary_inclusive() -> None:
    posture, _ = _classify_posture(head_drop=0.54, prior=None)
    assert posture == POSTURE_SLOUCHED


def test_transitions_through_dead_band() -> None:
    """A real slouching motion: ratio walks from 0.35 to 0.60.

    Mimics what the agent will see at the 2s capture cadence. The
    classifier's job is just per-tick mapping — the 3-frame streak
    hysteresis lives in the EmotionCapture instance, not here.
    """
    prior: str | None = None
    samples = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    results = []
    for head_drop in samples:
        posture, _ = _classify_posture(head_drop, prior=prior)
        # The classifier doesn't update prior — the caller does. Mimic that.
        if posture is not None:
            prior = posture
        results.append(posture)
    assert results == [
        POSTURE_UPRIGHT,
        POSTURE_UPRIGHT,
        POSTURE_UPRIGHT,
        POSTURE_UPRIGHT,  # 0.50 → dead-band, prior=upright kept
        POSTURE_SLOUCHED,
        POSTURE_SLOUCHED,
    ]


def test_none_input_returns_none_tuple() -> None:
    assert _classify_posture(head_drop=None, prior=POSTURE_UPRIGHT) == (
        None, None,
    )


def test_hysteresis_constant_exists_for_caller_reference() -> None:
    # Documents the contract that the caller (EmotionCapture.tick) is
    # expected to apply a frame-streak gate on top of this classifier.
    assert POSTURE_HYSTERESIS_FRAMES == 3
