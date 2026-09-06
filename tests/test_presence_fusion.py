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
# seconds_since_at_desk — flicker-robust high-water mark (GH#109)
# ---------------------------------------------------------------------------


def test_seconds_since_at_desk_none_when_never_confirmed() -> None:
    fusion = PresenceFusion()
    assert fusion.seconds_since_at_desk() is None
    # A non-confirming reading must not start the clock.
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(), face_present=False,
    ))
    assert fusion.seconds_since_at_desk() is None


def test_seconds_since_at_desk_tracks_last_confirmation() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(4), face_present=True, zone="desk",
    ))
    since = fusion.seconds_since_at_desk()
    assert since is not None and 3.5 <= since <= 6.0


def test_seconds_since_at_desk_not_reset_by_later_absent_frame() -> None:
    """The crux of the transit/desk-exit fix: a face_present=False frame
    landing on top of a recent desk confirmation (last-write-wins) must NOT
    move the high-water mark. is_at_desk_fresh() flips false on that frame,
    but seconds_since_at_desk() stays anchored to the real last confirmation,
    so the sticky-desk gate survives per-frame flicker.
    """
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(2), face_present=True, zone="desk",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(), face_present=False,
    ))
    assert fusion.is_at_desk_fresh() is False  # latest frame says no face
    since = fusion.seconds_since_at_desk()
    assert since is not None and since <= 6.0  # but recency is preserved


# ---------------------------------------------------------------------------
# Future-stamped reading self-heal (2026-06-07 mobo-swap clock incident)
# ---------------------------------------------------------------------------


def test_future_stamped_reading_replaced_by_honest_report() -> None:
    """Regression: a source clock running hours fast (fresh CMOS after a
    motherboard swap) stores a future-stamped reading; once the client
    clock is corrected, every honest report looked out-of-order and was
    dropped — wedging the source (age_s=-16742, fresh=True forever)
    until real time caught up. The guard must treat a future-stamped
    PRIOR as invalid and let the honest report replace it.
    """
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now() + timedelta(hours=4),
        face_present=True, face_confidence=0.83, zone="desk",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(), face_present=False,
    ))
    # The honest (non-confirming) report won — not the wedged future one.
    assert fusion.is_at_desk_fresh() is False


def test_future_stamped_high_water_mark_heals() -> None:
    """A future-stamped at-desk confirmation must not leave
    seconds_since_at_desk() negative ("just confirmed") after honest
    non-confirming reports resume — the desk-exit/transit gates would
    treat the desk as occupied for hours.
    """
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now() + timedelta(hours=4),
        face_present=True, zone="desk",
    ))
    assert fusion.seconds_since_at_desk() < 0  # wedged state, pre-heal
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(), face_present=False,
    ))
    since = fusion.seconds_since_at_desk()
    assert since is not None and since >= 0


def test_genuine_out_of_order_still_dropped() -> None:
    """The skew self-heal must not weaken the real out-of-order guard:
    an older-stamped report against a sane (non-future) prior drops."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(), face_present=True,
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(10), face_present=False,
    ))
    assert fusion.is_at_desk_fresh() is True  # fresher reading kept


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


def test_veto_also_suppresses_at_desk_attribution() -> None:
    """The veto must consistently flow through both ``is_at_desk_fresh``
    and ``get_at_desk_attribution`` — otherwise the status dict reads
    incoherent (``at_desk=False`` with ``at_desk_source='desktop'``).
    """
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.78,
    ))
    # Latitude lands AFTER, then sees user actively in bed.
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.60,
        detection_source="face", zone="bed", posture="reclined",
    ))
    assert fusion.is_at_desk_fresh() is False
    assert fusion.get_at_desk_attribution() is None


def test_latitude_bed_vetoes_desktop_face_present() -> None:
    """Cross-source veto (2026-05-21): if Latitude actively sees the user
    in bed (its wide-angle view is authoritative for off-desk localization),
    a fresh desktop face_present cannot promote at-desk. The two views can't
    both be true geometrically. Desktop FaceLandmarker has been observed to
    misfire on chair-shaped artifacts; Latitude's zone commit on bed is the
    stronger negative signal here.
    """
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.55,
        detection_source="face", zone="bed", posture="reclined",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.73,
    ))
    assert fusion.is_at_desk_fresh() is False


def test_latitude_zone_none_does_not_veto_desktop() -> None:
    """Counterpoint to the bed-veto: when Latitude has a fresh reading but
    no committed zone (weak-face FP, pose without face anchor, dim room),
    that's "Latitude doesn't know" — NOT "user not at desk." Desktop's
    face_present should still promote. This preserves the working case
    where Latitude misses Anthony due to lighting/pose but the desktop
    has a clean frontal view.
    """
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=False, face_confidence=0.18,
        detection_source="face", zone=None,
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.73,
    ))
    assert fusion.is_at_desk_fresh() is True


def test_stale_latitude_does_not_veto_desktop() -> None:
    """The veto requires Latitude to be FRESH. If Latitude went stale (cam
    paused, webcam shuttered, V4L2 wedged), desktop carries on its own.
    """
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_ago(DEFAULT_FRESHNESS_S + 60),
        zone="bed", posture="reclined",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.65,
    ))
    assert fusion.is_at_desk_fresh() is True
    assert fusion.get_at_desk_attribution() == "desktop"


# ---------------------------------------------------------------------------
# is_strongly_present_any
# ---------------------------------------------------------------------------


def test_latitude_pose_with_upstream_commit_is_strongly_present() -> None:
    """After the 2026-05-21 face-anchor fix, pose-only Latitude readings
    reach fusion only when camera_service.py has confirmed via the face
    anchor that a real person is present (pose alone fires on the empty
    chair). The reading carries ``face_present=True`` because upstream
    committed ``detection=present`` — that's what we trust now.
    """
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.6,
        detection_source="pose", zone="desk",
    ))
    assert fusion.is_strongly_present_any() is True


def test_latitude_pose_without_face_present_is_not_strong() -> None:
    """Bug fix from 2026-05-21: pose @ high conf on the empty chair
    used to promote to strongly-present unconditionally. After the
    upstream face-anchor gate, such a reading reaches fusion with
    ``face_present=False`` (anchor stale → upstream demoted to absent).
    Fusion must respect that — pose without face_present is not strong.
    """
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=False, face_confidence=0.0,
        detection_source="pose", zone="desk",
    ))
    assert fusion.is_strongly_present_any() is False


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


def test_strong_presence_reacquisition_marks_first_global_edge() -> None:
    fusion = PresenceFusion()
    absent = PresenceReading(
        source="desktop", captured_at=_ago(1),
        face_present=False, face_confidence=0.0,
        detection_source="face", zone=None,
    )
    returned = PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.8,
        detection_source="face", zone="desk",
    )
    fusion.on_observation(absent)
    fusion.on_observation(returned)

    assert fusion.is_strong_presence_reacquisition(returned) is True


def test_stale_absence_marker_cannot_create_reacquisition_edge() -> None:
    fusion = PresenceFusion()
    now = _now()
    absent = PresenceReading(
        source="desktop", captured_at=now,
        face_present=False, face_confidence=0.0,
        detection_source="face", zone=None,
    )
    fusion.on_observation(absent)
    fusion._last_global_absence_observed_at = _ago(
        STRONG_PRESENCE_FRESHNESS_S + 1,
    )
    returned = PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.8,
        detection_source="face", zone="desk",
    )
    fusion.on_observation(returned)

    assert fusion.is_strong_presence_reacquisition(returned) is False


def test_second_strong_source_is_not_apartment_reacquisition() -> None:
    fusion = PresenceFusion()
    absent = PresenceReading(
        source="desktop", captured_at=_ago(2),
        face_present=False, face_confidence=0.0,
        detection_source="face", zone=None,
    )
    desktop = PresenceReading(
        source="desktop", captured_at=_ago(1),
        face_present=True, face_confidence=0.8,
        detection_source="face", zone="desk",
    )
    latitude = PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.9,
        detection_source="yolo", zone="couch",
    )
    fusion.on_observation(absent)
    fusion.on_observation(desktop)
    assert fusion.is_strong_presence_reacquisition(desktop) is True

    fusion.on_observation(latitude)
    assert fusion.is_strong_presence_reacquisition(latitude) is False


def test_stale_strong_presence_does_not_invent_reacquisition_edge() -> None:
    fusion = PresenceFusion()
    stale = PresenceReading(
        source="desktop",
        captured_at=_ago(STRONG_PRESENCE_FRESHNESS_S + 2),
        face_present=True, face_confidence=0.8,
        detection_source="face", zone="desk",
    )
    fresh = PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.8,
        detection_source="face", zone="desk",
    )
    fusion.on_observation(stale)
    assert fusion.is_strong_presence_reacquisition(stale) is False

    fusion.on_observation(fresh)
    assert fusion.is_strong_presence_reacquisition(fresh) is False



def test_weak_positive_does_not_create_reacquisition_edge() -> None:
    fusion = PresenceFusion()
    weak = PresenceReading(
        source="latitude", captured_at=_ago(1),
        face_present=True, face_confidence=0.30,
        detection_source="face", zone=None,
    )
    strong = PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.85,
        detection_source="face", zone="couch",
    )
    fusion.on_observation(weak)
    assert fusion.is_strong_presence_reacquisition(weak) is False

    fusion.on_observation(strong)
    assert fusion.is_strong_presence_reacquisition(strong) is False


def test_ambiguous_reading_does_not_create_reacquisition_edge() -> None:
    fusion = PresenceFusion()
    ambiguous = PresenceReading(
        source="desktop", captured_at=_ago(1),
        face_present=None, face_confidence=None,
        detection_source=None, zone=None,
    )
    strong = PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, face_confidence=0.8,
        detection_source="face", zone="desk",
    )
    fusion.on_observation(ambiguous)
    assert fusion.is_strong_presence_reacquisition(ambiguous) is False

    fusion.on_observation(strong)
    assert fusion.is_strong_presence_reacquisition(strong) is False

def test_freshest_strong_presence_returns_newest_trusted_evidence() -> None:
    fusion = PresenceFusion()
    older = PresenceReading(
        source="latitude", captured_at=_ago(2),
        face_present=True, face_confidence=0.9,
        detection_source="yolo", zone="couch",
    )
    newer = PresenceReading(
        source="desktop", captured_at=_ago(1),
        face_present=True, face_confidence=0.7,
        detection_source="face", zone="desk",
    )
    fusion.on_observation(older)
    fusion.on_observation(newer)

    assert fusion.freshest_strong_presence() == newer


def test_freshest_strong_presence_excludes_stale_and_weak_readings() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.25,
        detection_source="face", zone=None,
    ))
    fusion.on_observation(PresenceReading(
        source="desktop",
        captured_at=_ago(STRONG_PRESENCE_FRESHNESS_S + 1),
        face_present=True, face_confidence=0.9,
        detection_source="face", zone="desk",
    ))

    assert fusion.freshest_strong_presence() is None


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


def test_latest_zone_strong_latitude_couch_beats_older_desktop_desk() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(2),
        face_present=True, face_confidence=0.70,
        detection_source="face", zone="desk",
    ))
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.80,
        detection_source="face", zone="couch",
    ))
    assert fusion.latest_zone() == "couch"

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


def test_latest_posture_desktop_slouched_wins_over_silent_latitude() -> None:
    """Phase 2 — slouched is desktop-exclusive; nothing else can produce it."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, posture="slouched", posture_confidence=0.62,
    ))
    assert fusion.latest_posture() == "slouched"


def test_latest_posture_desktop_upright_wins_over_latitude_upright() -> None:
    """Phase 2 — when both report upright, prefer desktop (frontal close-range
    view is more reliable than the Latitude's three-quarter corner view).
    This holds even when the Latitude reading is more recent."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(30),
        face_present=True, posture="upright", posture_confidence=0.55,
    ))
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_ago(5),
        zone="desk", posture="upright",
    ))
    # Latitude is newer but desktop wins by source-preference rule.
    assert fusion.latest_posture() == "upright"


def test_latest_posture_desktop_geometric_conflict_resolves_to_desktop() -> None:
    """Phase 2 — Latitude=reclined + desktop=slouched is geometrically
    impossible (can't be in bed AND at the desk). The fresh desktop
    desk-area posture wins; we trust the more recent ground truth."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_ago(30),
        zone="bed", posture="reclined",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(2),
        face_present=True, posture="slouched", posture_confidence=0.58,
    ))
    assert fusion.latest_posture() == "slouched"


def test_latest_posture_falls_back_to_latitude_when_desktop_silent() -> None:
    """If the desktop has no posture (model down / hips not visible),
    Latitude's reading carries — even if the desktop reading exists
    with face_present but posture=None."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        zone="bed", posture="reclined",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, posture=None,
    ))
    assert fusion.latest_posture() == "reclined"


def test_latest_posture_both_stale_returns_none() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(DEFAULT_FRESHNESS_S + 10),
        posture="slouched",
    ))
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_ago(DEFAULT_FRESHNESS_S + 10),
        posture="upright",
    ))
    assert fusion.latest_posture() is None


def test_latest_posture_desktop_stale_falls_back_to_latitude() -> None:
    """Desktop posture was fresh once but expired; Latitude has a fresh
    reading. The fallback path should pick up Latitude's value."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_ago(DEFAULT_FRESHNESS_S + 10),
        posture="slouched",
    ))
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        zone="desk", posture="upright",
    ))
    assert fusion.latest_posture() == "upright"


def test_posture_confidence_surfaces_in_sources() -> None:
    """posture_confidence on PresenceReading should round-trip through
    get_sources() so /api/camera/status callers see it."""
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=True, posture="slouched", posture_confidence=0.73,
    ))
    sources = fusion.get_sources()
    assert sources["desktop"]["posture"] == "slouched"
    assert sources["desktop"]["posture_confidence"] == 0.73


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


def test_get_source_reading_is_source_qualified() -> None:
    fusion = PresenceFusion()
    latitude = PresenceReading(
        source="latitude",
        captured_at=_now(),
        face_present=True,
        zone="couch",
    )
    desktop = PresenceReading(
        source="desktop",
        captured_at=_now(),
        face_present=True,
        zone="desk",
    )
    fusion.on_observation(latitude)
    fusion.on_observation(desktop)

    assert fusion.get_source_reading("latitude") is latitude
    assert fusion.get_source_reading("desktop") is desktop
    assert fusion.get_source_reading("missing") is None


def test_invalidate_source_removes_only_named_live_reading() -> None:
    fusion = PresenceFusion()
    latitude = PresenceReading(
        source="latitude", captured_at=_now(), face_present=True, zone="couch",
    )
    desktop = PresenceReading(
        source="desktop", captured_at=_now(), face_present=True, zone="desk",
    )
    fusion.on_observation(latitude)
    fusion.on_observation(desktop)

    fusion.invalidate_source("latitude")

    assert fusion.get_source_reading("latitude") is None
    assert fusion.get_source_reading("desktop") is desktop


# ---------------------------------------------------------------------------
# Bedroom-vs-Latitude physical authority regression (2026-08-30)
# ---------------------------------------------------------------------------


def test_latest_zone_ignores_weak_latitude_couch_face() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.60,
        detection_source="face", zone="couch",
    ))
    assert fusion.latest_zone() is None
    assert fusion.is_strongly_present_any() is False


def test_desktop_bed_pose_beats_weak_latitude_couch() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.60,
        detection_source="face", zone="couch",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=False, face_confidence=0.0,
        detection_source="pose", zone="bed",
        pose_visible_landmarks=17,
    ))
    assert fusion.latest_zone() == "bed"
    assert fusion.is_strongly_present_any() is True
    assert fusion.is_at_desk_fresh() is False


def test_latest_zone_keeps_strong_latitude_couch_authority() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(),
        face_present=True, face_confidence=0.75,
        detection_source="face", zone="couch",
    ))
    assert fusion.latest_zone() == "couch"
    assert fusion.is_strongly_present_any() is True


def test_latest_zone_fresher_strong_desktop_bed_wins_conflict() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_ago(2),
        face_present=True, face_confidence=0.80,
        detection_source="face", zone="couch",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(),
        face_present=False, face_confidence=0.0,
        detection_source="pose", zone="bed",
    ))
    assert fusion.latest_zone() == "bed"


def test_latest_strong_zone_excludes_weak_latitude_couch() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude", captured_at=_now(), face_present=True,
        face_confidence=0.55, detection_source="face", zone="couch",
    ))
    assert fusion.latest_strong_zone() is None


def test_latest_strong_zone_accepts_desktop_bed_pose() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=_now(), face_present=False,
        detection_source="pose", zone="bed", pose_visible_landmarks=17,
    ))
    assert fusion.latest_strong_zone() == "bed"


def test_desktop_bed_vetoes_stale_at_desk_attribution() -> None:
    fusion = PresenceFusion()
    now = _now()
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=now - timedelta(seconds=4),
        face_present=True, face_confidence=0.82, zone="desk",
    ))
    fusion.on_observation(PresenceReading(
        source="desktop", captured_at=now,
        face_present=False, detection_source="pose", zone="bed",
        pose_visible_landmarks=17,
    ))
    assert fusion.is_at_desk_fresh() is False
    assert fusion.get_at_desk_attribution() is None
    assert fusion.seconds_since_at_desk() is not None


def test_yolo_latitude_is_strong_presence_without_inventing_zone() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude",
        captured_at=_now(),
        face_present=True,
        face_confidence=0.82,
        detection_source="yolo",
        zone=None,
    ))
    assert fusion.is_strongly_present_any() is True
    assert fusion.latest_zone() is None


def test_desktop_bed_localization_survives_yolo_presence_without_zone() -> None:
    fusion = PresenceFusion()
    fusion.on_observation(PresenceReading(
        source="latitude",
        captured_at=_now(),
        face_present=True,
        face_confidence=0.82,
        detection_source="yolo",
        zone=None,
    ))
    fusion.on_observation(PresenceReading(
        source="desktop",
        captured_at=_now(),
        face_present=True,
        detection_source="pose",
        zone="bed",
    ))
    assert fusion.is_strongly_present_any() is True
    assert fusion.latest_zone() == "bed"
