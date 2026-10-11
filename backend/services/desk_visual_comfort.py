"""Pure candidate policies; no sensor discovery or actuator authority."""
from math import isfinite


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
