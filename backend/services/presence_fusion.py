"""Multi-source presence fusion — combines Latitude camera + desktop pc_agent.

As of 2026-05-27 the Latitude camera relocated to the living room: it sees
the couch and produces ``zone=couch`` (its bedroom desk/bed left-right split
is retired). The desktop pc_agent (frontal at-desk) is now the authoritative
"at desk" source — it emits ``zone=desk`` on a confident face. ``reclined``
posture is no longer produced now that no camera frames the bed.

This service merges the two into a single attendance model:

  - ``is_at_desk_fresh()``        — True if ANY source confirms at-desk
  - ``is_strongly_present_any()`` — True if ANY source has a fresh, strong reading
  - ``latest_zone`` / ``latest_posture`` — Latitude-authoritative (it has both zones)
  - ``get_at_desk_attribution()`` — which source most recently confirmed at-desk
  - ``get_sources()``             — per-source freshness for diagnostics

Inputs:
  - Latitude ``CameraService`` registers a callback that fires after each
    frame with a ``PresenceReading(source="latitude", ...)``.
  - Desktop pc_agent POSTs to ``/api/camera/observation`` which routes the
    payload through ``on_observation(reading)``.

The merge layer is intentionally additive: existing Latitude-specific
surfaces (camera page snapshots + lux calibration UI) keep reading
``CameraService`` directly. ``PresenceFusion`` is what mode logic and
attendance vetoes should consult, because it's source-aware.

Future sources (bedroom ESP32-CAM, kitchen Reolink) add their own
``source`` string and submit ``PresenceReading``s via the same endpoint —
no ``PresenceFusion`` code change required unless they unlock new zones
or postures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("home_hub.presence_fusion")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mirrors ``light_state_calculator.ZONE_POSTURE_FRESHNESS_SECONDS`` — the
# attendance gate's max-age for zone/posture commits. Used by mode logic
# and attendance vetoes.
DEFAULT_FRESHNESS_S = 300

# Strong-presence freshness for the transit / desk-exit "is someone here
# right now?" check. ~4 polls at the 2s camera cadence; longer would
# treat brief gaps as continuous presence and defeat absent-dwell.
STRONG_PRESENCE_FRESHNESS_S = 8

# Face confidence ceiling above which the Latitude face path qualifies
# as "strong" on its own (mirrors ``camera_service.FACE_TRUST_THRESHOLD``
# so the two stay in lockstep — chair-backs / picture frames / wall art
# typically score 0.15-0.50 and don't clear this bar).
LATITUDE_STRONG_FACE_THRESHOLD = 0.70

# Canonical source names. New sources don't need to be enumerated here
# (the merge is dict-keyed by string), but the route layer validates
# inbound payloads against this set.
KNOWN_SOURCES = frozenset({"latitude", "desktop"})


@dataclass(frozen=True)
class PresenceReading:
    """One observation from a single presence source."""

    source: str
    captured_at: datetime  # UTC
    face_present: Optional[bool] = None
    face_confidence: Optional[float] = None
    # ``detection_source`` is Latitude-specific: "face" | "pose" | None.
    # Desktop only runs FaceLandmarker; left None there.
    detection_source: Optional[str] = None
    zone: Optional[str] = None  # "desk" | "bed" | None
    # Latitude reports "upright" | "reclined". Desktop adds
    # "slouched" / "upright" (frontal-only). New sources may extend
    # the vocabulary; consumers should treat unknown values as opaque.
    posture: Optional[str] = None
    posture_confidence: Optional[float] = None  # 0..1
    pose_visible_landmarks: Optional[int] = None  # diagnostics


class PresenceFusion:
    """Source-aware attendance + zone/posture merger.

    Constructed once at startup. Each presence source is wired to call
    ``on_observation()`` with a tagged ``PresenceReading`` whenever it
    has a fresh detection result; the fusion holds only the latest
    reading per source.
    """

    def __init__(self) -> None:
        self._readings: dict[str, PresenceReading] = {}
        # Stamp the last source that confirmed at-desk so dashboards
        # can show "Latitude is currently the source backing your at-desk
        # status" vs the desktop pc_agent. Cleared when its reading
        # falls out of the freshness window (lazily, in the getter).
        self._last_at_desk_source: Optional[str] = None
        self._last_at_desk_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def on_observation(self, reading: PresenceReading) -> None:
        """Record one observation. Last-write-wins per source."""
        if not isinstance(reading, PresenceReading):
            logger.debug("on_observation called with non-PresenceReading: %r", reading)
            return
        prior = self._readings.get(reading.source)
        if prior is not None and reading.captured_at < prior.captured_at:
            # Out-of-order arrival (clock skew, network reorder) — drop
            # rather than overwrite fresher state with stale data.
            return
        self._readings[reading.source] = reading

        if self._is_at_desk(reading):
            self._last_at_desk_source = reading.source
            self._last_at_desk_at = reading.captured_at

    # ------------------------------------------------------------------
    # Attendance queries
    # ------------------------------------------------------------------

    def _latitude_says_bed(self, max_age_s: int) -> bool:
        """Helper: is Latitude actively localizing the user to bed?

        Single-arity rule: the cross-source veto fires only when Latitude
        has a fresh reading with ``zone=='bed'`` AND ``face_present=True``.
        ``zone=None`` is "I don't know," not "off-desk" — never veto on it.
        Extracted so ``is_at_desk_fresh`` and ``get_at_desk_attribution``
        stay consistent (a desktop attribution shouldn't survive a veto
        that returned False from the at-desk query).
        """
        now = datetime.now(timezone.utc)
        for reading in self._readings.values():
            if (now - reading.captured_at).total_seconds() > max_age_s:
                continue
            if (
                reading.source == "latitude"
                and reading.zone == "bed"
                and reading.face_present
            ):
                return True
        return False

    def is_at_desk_fresh(self, max_age_s: int = DEFAULT_FRESHNESS_S) -> bool:
        """True iff any source has a fresh at-desk confirmation.

        Latitude: ``zone == 'desk'`` within the freshness window. After
        2026-05-21, the camera_service.py face-anchor gate prevents pose-on-
        chair from committing ``zone=desk`` without a recent face — so a
        fresh Latitude ``zone=desk`` is itself trustworthy.

        Desktop: a fresh ``face_present`` reading implies the user is engaged
        at the monitor (FaceLandmarker is frontal close-range; profile or
        no-face frames don't fire). NOT a FoV-bounded claim — the desktop
        webcam actually has a wide field of view that includes the bed in
        the background; reliability comes from the model's detection profile.

        Cross-source veto: see ``_latitude_says_bed`` — when Latitude
        positively localizes user to bed, desktop face_present is vetoed.
        """
        now = datetime.now(timezone.utc)
        any_at_desk = False
        for reading in self._readings.values():
            if (now - reading.captured_at).total_seconds() > max_age_s:
                continue
            if self._is_at_desk(reading):
                any_at_desk = True
        if any_at_desk and self._latitude_says_bed(max_age_s):
            # Geometric impossibility: Latitude sees user in bed AND desktop
            # face says at-desk. Trust the wider-angle view.
            return False
        return any_at_desk

    def is_strongly_present_any(
        self, max_age_s: int = STRONG_PRESENCE_FRESHNESS_S,
    ) -> bool:
        """True iff any source reports a fresh, *strong* presence reading.

        "Strong" excludes the weak-face-only Latitude case (chair-back FPs
        that clear ``MIN_FACE_CONFIDENCE`` but aren't actually Anthony).
        Desktop face-present already gates client-side on
        ``FACE_CONFIDENCE_FLOOR=0.30`` — anything that reaches us with
        ``face_present=True`` is a frontal close-up which is inherently
        strong. Used by ``transit_lighting`` + ``desk_exit_kitchen`` to
        suppress absent-dwell timers when another source confirms someone
        is actually here.
        """
        now = datetime.now(timezone.utc)
        for reading in self._readings.values():
            if (now - reading.captured_at).total_seconds() > max_age_s:
                continue
            if self._is_strongly_present(reading):
                return True
        return False

    def is_present_within_seconds(self, window_s: int) -> bool:
        """True iff any source had a present reading inside ``window_s``.

        Weaker than ``is_strongly_present_any`` — used by celebration TTS
        gating where "someone might be here, dial down" is the right
        bar. Counts any reading with ``face_present`` true OR a committed
        zone / posture (Latitude commits imply recent presence by
        construction).
        """
        now = datetime.now(timezone.utc)
        for reading in self._readings.values():
            if (now - reading.captured_at).total_seconds() > window_s:
                continue
            if reading.face_present:
                return True
            if reading.zone is not None or reading.posture is not None:
                return True
        return False

    def get_at_desk_attribution(self) -> Optional[str]:
        """Most recent source to confirm at-desk, or None if stale.

        Respects the cross-source veto: if Latitude currently sees the user
        in bed, the stored ``_last_at_desk_source`` (likely "desktop" from
        a still-fresh frontal face reading) is suppressed — the status dict
        would otherwise read ``at_desk=False, at_desk_source="desktop"``,
        which is incoherent.
        """
        if self._last_at_desk_at is None:
            return None
        age = (
            datetime.now(timezone.utc) - self._last_at_desk_at
        ).total_seconds()
        if age > DEFAULT_FRESHNESS_S:
            return None
        if self._latitude_says_bed(DEFAULT_FRESHNESS_S):
            return None
        return self._last_at_desk_source

    # ------------------------------------------------------------------
    # Merged zone/posture
    # ------------------------------------------------------------------

    def latest_zone(
        self, max_age_s: int = DEFAULT_FRESHNESS_S,
    ) -> Optional[str]:
        """Best zone reading.

        Latitude is authoritative for its own zone (``couch`` since the
        2026-05-27 living-room move; ``bed``/``desk`` historically). When it
        has no fresh zone (capture failure, no one in the living room) but the
        desktop sees a fresh face, fall back to ``"desk"`` — the desktop is
        the at-desk authority.
        """
        lat = self._readings.get("latitude")
        if lat is not None and lat.zone is not None and self._fresh(lat, max_age_s):
            return lat.zone
        if self._desktop_at_desk_fresh(max_age_s):
            return "desk"
        return None

    def latest_posture(
        self, max_age_s: int = DEFAULT_FRESHNESS_S,
    ) -> Optional[str]:
        """Best posture reading across sources, honoring geometry.

        Merge rule (Phase 2):
          - If the desktop has a fresh desk-area posture
            (``upright`` / ``slouched``), prefer it. The desktop's frontal
            close-range view is more reliable than the Latitude's
            three-quarter corner view for desk-area posture, and
            ``slouched`` is desktop-only by construction.
          - Else fall back to the most-recent fresh non-None reading
            across all sources. This covers Latitude-only postures
            (``reclined``, bed-only) and any source-of-last-resort
            scenarios where future cameras might be the only contributor.

        ``reclined`` and ``slouched`` are geometrically exclusive (one
        requires being in bed, the other at the desk), so the only
        practical conflict is when both Latitude and desktop report
        ``upright``. The desktop wins by design — its frontal view sees
        the subject head-on at high confidence; the Latitude sees a
        three-quarter profile at 2-3m.
        """
        now = datetime.now(timezone.utc)
        desktop = self._readings.get("desktop")
        if (
            desktop is not None
            and desktop.posture in ("upright", "slouched")
            and self._fresh(desktop, max_age_s)
        ):
            return desktop.posture

        # Fall back to most-recent fresh non-None across all sources.
        candidates: list[tuple[float, str]] = []
        for reading in self._readings.values():
            if reading.posture is None:
                continue
            age = (now - reading.captured_at).total_seconds()
            if age > max_age_s:
                continue
            candidates.append((age, reading.posture))
        if not candidates:
            return None
        candidates.sort()  # smallest age first
        return candidates[0][1]

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_sources(self) -> dict[str, dict]:
        """Per-source state — for ``/api/camera/status`` + dashboards."""
        now = datetime.now(timezone.utc)
        out: dict[str, dict] = {}
        for source, reading in self._readings.items():
            age_s = (now - reading.captured_at).total_seconds()
            out[source] = {
                "last_at": reading.captured_at.isoformat(),
                "age_s": round(age_s, 1),
                "fresh": age_s <= DEFAULT_FRESHNESS_S,
                "face_present": reading.face_present,
                "face_confidence": reading.face_confidence,
                "detection_source": reading.detection_source,
                "zone": reading.zone,
                "posture": reading.posture,
                "posture_confidence": reading.posture_confidence,
            }
        return out

    def get_status(self) -> dict:
        """Aggregate snapshot — included in ``/api/camera/status`` payloads."""
        return {
            "at_desk_fresh": self.is_at_desk_fresh(),
            "at_desk_source": self.get_at_desk_attribution(),
            "strongly_present": self.is_strongly_present_any(),
            "zone": self.latest_zone(),
            "posture": self.latest_posture(),
            "sources": self.get_sources(),
        }

    def as_fusion_factor(self) -> Optional[dict]:
        """Return a ``ConfidenceFusion``-ready factor entry naming the
        contributing presence sources, or ``None`` when no source has a
        recent reading.

        The factor is informational — it doesn't influence weighting,
        only surfaces "which presence sources are alive right now" in
        the analytics constellation. The ``fusion-lane-auditor`` agent
        keys on this to assert both sources are contributing.
        """
        now = datetime.now(timezone.utc)
        # Wider window than STRONG_PRESENCE_FRESHNESS_S because this is
        # for lane attribution, not real-time gating: 30s catches the
        # desktop 2s cadence even after a single missed POST.
        active = sorted(
            source
            for source, reading in self._readings.items()
            if (now - reading.captured_at).total_seconds() <= 30.0
        )
        if not active:
            return None
        return {
            "key": "presence_sources",
            "label": "Presence sources",
            "value": ",".join(active),
            "display": ", ".join(active),
            "impact": 0.4,
            "stale": False,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fresh(reading: PresenceReading, max_age_s: int) -> bool:
        age = (
            datetime.now(timezone.utc) - reading.captured_at
        ).total_seconds()
        return age <= max_age_s

    def _desktop_at_desk_fresh(self, max_age_s: int) -> bool:
        desk = self._readings.get("desktop")
        if desk is None or not desk.face_present:
            return False
        return self._fresh(desk, max_age_s)

    @staticmethod
    def _is_at_desk(reading: PresenceReading) -> bool:
        """Whether one reading, on its own, confirms 'at desk'."""
        if reading.source == "latitude":
            return reading.zone == "desk"
        if reading.source == "desktop":
            return bool(reading.face_present)
        # Unknown future source — be conservative; require zone=desk.
        return reading.zone == "desk"

    @staticmethod
    def _is_strongly_present(reading: PresenceReading) -> bool:
        """Whether one reading qualifies as strong presence.

        Latitude pose is NOT automatically strong (was unconditionally True
        before 2026-05-21). MediaPipe pose fires at 0.98 confidence with
        full landmark visibility on the empty office chair — see
        ``project_latitude_pose_on_chair_false_positive.md``. Pose-only
        presence is now gated upstream in ``camera_service.py`` by the
        face-anchor cross-validation: pose without a recent face anchor
        in the same zone no longer commits ``detection=present``. So a
        Latitude reading that reaches us with ``detection_source='pose'``
        already passed that gate — we can trust pose presence here, but
        we still demand the face_present flag to confirm the upstream
        commit actually fired.
        """
        if reading.source == "latitude":
            if reading.detection_source == "pose":
                # Trust upstream's face-anchor gate (camera_service.py).
                return bool(reading.face_present)
            if reading.detection_source == "face":
                return (
                    reading.face_confidence or 0.0
                ) >= LATITUDE_STRONG_FACE_THRESHOLD
            return False
        if reading.source == "desktop":
            return bool(reading.face_present)
        # Unknown source — accept face_present at face value.
        return bool(reading.face_present)
