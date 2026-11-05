"""Shared Desk comfort values and pure candidates; no actuator authority."""
from math import isfinite
from types import MappingProxyType

DESK_WATCHING_FILL = MappingProxyType({"evening": 110, "night": 90, "late_night": 70})


def desk_diffuse_fill_candidate(
    l2: dict, *, activity: str, period: str, house: str, source: str | None,
    zone: str | None, face_present: bool, sample_age: float | None,
    conflicting_physical: bool, owners: frozenset[str], enabled: bool, dnd: bool,
) -> dict:
    """Offline #370 warm L2 candidate, NOT an actuation permission or lease.

    Deliberately unwired: the caller must eventually capture/revalidate source
    epochs and all owners at the existing final-write boundary. Ages here are
    elapsed seconds from an accepted physical observation, never software input.
    Unknown owners fail closed; manual Activity alone is semantic preference.
    Only already-on warm CT targets qualify; HSB conversion needs a separately
    reviewed composition decision. Floors are tuning candidates, not lux claims.
    This function cannot author L5 or the kitchen pair.
    """
    floors = DESK_WATCHING_FILL
    if (
        not enabled or dnd or house != "home" or conflicting_physical
        or source != "desktop" or zone != "desk" or face_present is not True
        or sample_age is None or not isfinite(sample_age) or not 0 <= sample_age <= 30
        or owners - {"manual_activity"}
        or activity not in {"general", "idle", "working", "watching", "gaming",
                            "relax", "social", "cooking"}
        or period not in floors or l2.get("on") is not True
        or "hue" in l2 or "sat" in l2
    ):
        return l2
    ct, bri = l2.get("ct"), l2.get("bri")
    if (
        not isinstance(ct, (int, float)) or not isfinite(ct) or not 333 <= ct <= 500
        or not isinstance(bri, (int, float)) or not isfinite(bri) or not 1 <= bri <= 254
        or bri >= floors[period]
    ):
        return l2
    return {**l2, "bri": floors[period]}


def is_neutral_page(r: int, g: int, b: int) -> bool:
    """A bright, nearly achromatic representative frame (not a dark screen)."""
    return min(r, g, b) >= 180 and max(r, g, b) - min(r, g, b) <= 24


def twilight_monitor_target(
    base: int, night: int, *, seconds_after_sunset: float,
    bedroom_lux: float | None, baseline: float | None, sample_age: float | None,
    qualified_desk: bool, calibrated_bedroom: bool,
) -> int:
    """Offline #371 candidate: dark-bedroom twilight can approach Night early.

    Caller supplies normalized monitor percentages and explicitly qualified
    bedroom samples. This hook is deliberately NOT wired to the monitor agent:
    generic camera/status lux does not satisfy this contract. No activity,
    cloud cover, or software process can establish Desk or darkness.
    """
    values = (seconds_after_sunset, bedroom_lux, baseline, sample_age)
    if not qualified_desk or not calibrated_bedroom:
        return base
    if any(value is None or not isfinite(value) for value in values):
        return base
    if baseline <= 0 or bedroom_lux < 0 or not 0 <= sample_age <= 30:
        return base
    if seconds_after_sunset < 0 or bedroom_lux / baseline > 0.5:
        return base
    # Bounded 30-minute ramp; existing later period resolution still owns Night.
    fraction = min(1.0, seconds_after_sunset / 1800)
    return round(base + (min(base, night) - base) * fraction)
