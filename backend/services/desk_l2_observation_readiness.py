"""Read-only #370 L2 observation readiness. No comfort or actuator authority.

This classifier examines already-delivered snapshots. It does NOT verify HTTP
ingestion identity, calibration provenance, physical screen viewing, an L2 floor,
a Hue owner/lease, or serialized dispatch permission. None of its outputs may
be used as a positive write authorization. Callers must independently recheck
their source and ownership at the real final mutation boundary.
"""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from backend.services.automation_constants import PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
from backend.services.lux_channel import LUX_EMA_STALE_RESET_SECONDS, LuxChannel
from backend.services.presence_fusion import PresenceFusion, PresenceReading

_MAX_FUTURE_SKEW = 2.0


@dataclass(frozen=True)
class DeskL2ObservationReadiness:
    """Advisory evidence only; deliberately no eligible/candidate/writer token."""

    desktop_observation_ready: bool
    bedroom_sample_ready: bool
    reasons: tuple[str, ...]

    @property
    def authorizes_lighting(self) -> bool:
        """Never, even when both observational checks pass."""
        return False


def _age_seconds(now: datetime, captured: object) -> float | None:
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or not isinstance(captured, datetime)
        or captured.tzinfo is None
        or captured.utcoffset() is None
    ):
        return None
    try:
        age = (now - captured).total_seconds()
    except (ValueError, OverflowError, TypeError):
        return None
    return age if isfinite(age) else None


def _valid_measurement(value: object, *, positive: bool) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        n = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return isfinite(n) and (n > 0 if positive else n >= 0)


def assess_desk_l2_observations(
    *,
    desktop: PresenceReading | None,
    latitude: PresenceReading | None,
    bedroom_channel: LuxChannel | None,
    now: datetime,
) -> DeskL2ObservationReadiness:
    """Evaluate named snapshots without mutating a producer or contacting Hue.

    Existing desk semantic arbitration uses an inclusive [-2s,+8s] window.
    Generic LuxChannel has no lower bound on its freshness age; this read-only
    check adds one without changing channel semantics or route behavior.
    """
    reasons: list[str] = []
    desktop_age = _age_seconds(now, getattr(desktop, "captured_at", None))
    desk = bool(
        desktop is not None
        and getattr(desktop, "source", None) == "desktop"
        and getattr(desktop, "zone", None) == "desk"
        and getattr(desktop, "face_present", None) is True
        and getattr(desktop, "detection_source", None) in (None, "face")
        and desktop_age is not None
        and -_MAX_FUTURE_SKEW <= desktop_age <= PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
    )
    if not desk:
        reasons.append("desktop_unqualified")

    latitude_age = _age_seconds(now, getattr(latitude, "captured_at", None))
    conflicting = bool(
        latitude is not None
        and getattr(latitude, "source", None) == "latitude"
        and getattr(latitude, "zone", None) in ("couch", "bed")
        and latitude_age is not None
        and -_MAX_FUTURE_SKEW <= latitude_age <= PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
        and PresenceFusion._is_strongly_present(latitude)
    )
    if conflicting:
        desk = False
        reasons.append("opposing_physical_presence")

    timestamp = getattr(bedroom_channel, "last_lux_update", None)
    lux_age = _age_seconds(now, timestamp)
    room = getattr(bedroom_channel, "room", None)
    ema = getattr(bedroom_channel, "ema_lux", None)
    baseline = getattr(bedroom_channel, "baseline_lux", None)
    lux = bool(
        room == "bedroom"
        and getattr(bedroom_channel, "calibrated", False) is True
        and _valid_measurement(ema, positive=False)
        and _valid_measurement(baseline, positive=True)
        and lux_age is not None
        and -_MAX_FUTURE_SKEW <= lux_age <= LUX_EMA_STALE_RESET_SECONDS
    )
    if not lux:
        reasons.append("bedroom_lux_unqualified")

    return DeskL2ObservationReadiness(
        desktop_observation_ready=desk,
        bedroom_sample_ready=lux,
        reasons=tuple(reasons),
    )
