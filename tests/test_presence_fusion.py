"""Tests for ``PresenceFusion`` — multi-source attendance merge rules.

Verifies the merge contract described in the service docstring + the
plan at C:\\Users\\antho\\.claude\\plans\\the-desktop-camera-we-synchronous-babbage.md:

  - Latitude absent + desktop face_present → at-desk True
  - Latitude desk + desktop stale → Latitude wins (at-desk True via Latitude)
  - Both stale → at-desk False
  - posture=reclined stays Latitude-authoritative
  - Strong presence merges across sources (chair-back weak-face on
    Latitude doesn't promote when desktop is also absent; desktop
    face_present DOES promote even when Latitude is flapping)
  - get_at_desk_attribution returns the most recent confirming source
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.presence_fusion import (
    DEFAULT_FRESHNESS_S,
    STRONG_PRESENCE_FRESHNESS_S,
    PresenceFusion,
    PresenceReading,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ago(seconds: float) -> datetime:
    return _now() - timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# is_at_desk_fresh
# ---------------------------------------------------------------------------


def test_no_sources_means_not_at_desk() -> None:
    fusion = PresenceFusion()
    assert fusion.is_at_desk_fresh() is False
    assert fusion.get_at_desk_attribution() is None


def test_latitude_zone_desk_is_at_desk() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.85,
        detection_source="face", zone="desk", posture="upright",
    ))
    assert fusion.is_at_desk_fresh() is True
    assert fusion.get_at_desk_attribution() == "latitude"


def test_latitude_zone_bed_is_not_at_desk() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        zone="bed", posture="reclined",
    ))
    assert fusion.is_at_desk_fresh() is False
    # And bed reading didn't get stamped as at-desk attribution
    assert fusion.get_at_desk_attribution() is None


def test_desktop_face_present_is_at_desk() -> None:
    """The desktop camera only sees the desk — face_present → at-desk."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.65,
    ))
    assert fusion.is_at_desk_fresh() is True
    assert fusion.get_at_desk_attribution() == "desktop"


def test_desktop_face_absent_is_not_at_desk() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=False, face_confidence=0.05,
    ))
    assert fusion.is_at_desk_fresh() is False


def test_latitude_absent_desktop_present_is_at_desk() -> None:
    """The defining merge case: Latitude misses Anthony (zone=None),
    desktop sees the face. PresenceFusion should report at-desk True."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        # Weak chair-back FP — clears MIN_FACE_CONFIDENCE but no committed zone
        face_present=True, face_confidence=0.18,
        detection_source="face", zone=None, posture=None,
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.78,
    ))
    assert fusion.is_at_desk_fresh() is True
    # Desktop was the most recent at-desk confirmation
    assert fusion.get_at_desk_attribution() == "desktop"


def test_latitude_desk_desktop_stale_means_at_desk_via_latitude() -> None:
    fusion = PresenceFusion()
    # Desktop face seen 10 minutes ago (stale)
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(600),
        face_present=True, face_confidence=0.75,
    ))
    # Latitude commits desk just now
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.85,
        detection_source="face", zone="desk", posture="upright",
    ))
    assert fusion.is_at_desk_fresh() is True
    assert fusion.get_at_desk_attribution() == "latitude"


def test_both_sources_stale_means_not_at_desk() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_ago(DEFAULT_FRESHNESS_S + 60),
        zone="desk", posture="upright",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(DEFAULT_FRESHNESS_S + 60),
        face_present=True, face_confidence=0.80,
    ))
    assert fusion.is_at_desk_fresh() is False
    # Attribution decays past the freshness window
    assert fusion.get_at_desk_attribution() is None


def test_custom_max_age_overrides_default() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_ago(120),
        zone="desk", posture="upright",
    ))
    assert fusion.is_at_desk_fresh(max_age_s=60) is False
    assert fusion.is_at_desk_fresh(max_age_s=180) is True


# ---------------------------------------------------------------------------
# is_strongly_present_any
# ---------------------------------------------------------------------------


def test_latitude_pose_is_strongly_present() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=False, face_confidence=0.0,
        detection_source="pose", zone="desk",
    ))
    assert fusion.is_strongly_present_any() is True


def test_latitude_strong_face_is_strongly_present() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.78,
        detection_source="face", zone="desk",
    ))
    assert fusion.is_strongly_present_any() is True


def test_latitude_weak_face_alone_is_not_strongly_present() -> None:
    """The chair-back FP failure mode — weak face shouldn't promote."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.30,
        detection_source="face", zone=None,
    ))
    assert fusion.is_strongly_present_any() is False


def test_desktop_face_present_is_strongly_present() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.42,
    ))
    assert fusion.is_strongly_present_any() is True


def test_strong_presence_window_is_tight() -> None:
    """Strong presence uses the short window so absent-dwell counters work."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop",
        captured_at=_ago(STRONG_PRESENCE_FRESHNESS_S + 2),
        face_present=True, face_confidence=0.75,
    ))
    assert fusion.is_strongly_present_any() is False
    # But still counts as at-desk fresh (which uses the 300s window)
    assert fusion.is_at_desk_fresh() is True


def test_desktop_strong_overrides_latitude_weak() -> None:
    """The defeat-chair-back-FP case for transit_lighting + desk_exit_kitchen."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.18,  # chair-back FP
        detection_source="face", zone=None,
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.65,
    ))
    assert fusion.is_strongly_present_any() is True


# ---------------------------------------------------------------------------
# latest_zone / latest_posture
# ---------------------------------------------------------------------------


def test_latest_zone_prefers_latitude() -> None:
    """Latitude is authoritative — it's the only source that sees the bed."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        zone="bed", posture="reclined",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.70,
    ))
    # Desktop says "face present at desk" but Latitude says bed —
    # Latitude wins because the desktop only confirms desk by
    # implication and Latitude has the better information.
    assert fusion.latest_zone() == "bed"


def test_latest_zone_falls_back_to_desktop_when_latitude_silent() -> None:
    """Sleeping-mode pause: Latitude stops reporting; desktop is the
    only source. Should fall back to ``desk``."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.55,
    ))
    assert fusion.latest_zone() == "desk"


def test_latest_zone_none_when_all_stale() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_ago(DEFAULT_FRESHNESS_S + 10),
        zone="desk",
    ))
    assert fusion.latest_zone() is None


def test_latest_posture_reclined_stays_latitude_authoritative() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        zone="bed", posture="reclined",
    ))
    assert fusion.latest_posture() == "reclined"


def test_latest_posture_most_recent_wins() -> None:
    """When both sources report posture, most-recent wins (Phase 1 rule)."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_ago(120),
        zone="desk", posture="upright",
    ))
    # Phase 1 desktop doesn't yet report posture, but test the merge for
    # forward-compat. A desktop reading with posture set should win when
    # newer.
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(5),
        face_present=True, posture="slouched",
    ))
    assert fusion.latest_posture() == "slouched"


# ---------------------------------------------------------------------------
# Out-of-order writes
# ---------------------------------------------------------------------------


def test_out_of_order_reading_is_dropped() -> None:
    """Late-arriving reading mustn't erase newer state."""
    fusion = PresenceFusion()
    fresh = PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.80,
    )
    stale = PresenceReading(
        source="desktop", captured_at=_ago(30),
        face_present=False, face_confidence=0.05,
    )
    fusion.on_observation(fresh)
    fusion.on_observation(stale)  # arrives later but timestamped earlier
    # Fresh reading should still be in effect
    assert fusion.is_at_desk_fresh() is True


def test_non_presence_reading_is_ignored() -> None:
    """Defensive: passing something that isn't a PresenceReading is a no-op."""
    fusion = PresenceFusion()
    fusion.on_observation({"source": "desktop", "face_present": True})  # type: ignore[arg-type]
    assert fusion.is_at_desk_fresh() is False


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_get_sources_includes_both() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        zone="desk", face_confidence=0.85, detection_source="face",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.62,
    ))
    sources = fusion.get_sources()
    assert set(sources.keys()) == {"latitude", "desktop"}
    assert sources["latitude"]["zone"] == "desk"
    assert sources["desktop"]["face_present"] is True
    assert sources["latitude"]["fresh"] is True


def test_as_fusion_factor_lists_active_sources_sorted() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.70,
    ))
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        zone="desk", face_confidence=0.80, detection_source="face",
    ))
    factor = fusion.as_fusion_factor()
    assert factor is not None
    assert factor["value"] == "desktop,latitude"


def test_as_fusion_factor_returns_none_when_silent() -> None:
    fusion = PresenceFusion()
    assert fusion.as_fusion_factor() is None
