"""Pure candidate policies; no sensor discovery or actuator authority."""
from dataclasses import dataclass, fields
from math import isfinite
from typing import Literal


DeskPeriod = Literal["day", "evening", "night", "late_night"]


@dataclass(frozen=True, kw_only=True)
class DeskDiffuseL2Context:
    """Trusted caller assertions, NOT sensor verification or write authority.

    Brightness is integral Hue [1,254]. No calibration/floor is supplied here.
    Lux qualification is mandatory in this initial ambient-dependent prototype.
    Manual Activity selection intentionally has no veto field.
    """

    activity: str
    period: DeskPeriod
    calibration_period: DeskPeriod | None
    calibrated_floor: int | None
    original_l2_bri: int
    effective_l2_cap: int
    branch: Literal["static", "screen_sync"]
    house_state: str = "unknown"
    awake: bool = False
    physical_source: str = "unknown"
    physical_zone: str = "unknown"
    physical_qualified: bool = False
    physical_fresh: bool = False
    eligible_screen_viewing: bool = False
    calibration_verified: bool = False
    bedroom_lux_trusted: bool = False
    bedroom_lux_calibrated: bool = False
    bedroom_lux_room_qualified: bool = False
    bedroom_lux_fresh: bool = False
    original_l2_on: bool = False
    rebrightening_authorized: bool = False
    dnd: bool = False
    manual_l2: bool = False
    scene: bool = False
    effect: bool = False
    transit: bool = False
    protected: bool = False
    external_owner: bool = False
    external_off: bool = False
    hard_off: bool = False
    stronger_device_owner: bool = False
    screen_sync_owns_l2: bool = False
    screen_sync_lease_current: bool = False
    same_frame_guard_guaranteed: bool = False
    transition_epoch_current: bool = False
    gaming_context: Literal["accepted_director", "rust", "game_day"] | None = None


@dataclass(frozen=True)
class DeskDiffuseL2Decision:
    """Offline L2 brightness proposal only; never a payload or permission to write."""

    reason: Literal[
        "invalid_input", "ineligible_context", "ineligible_activity", "unverified_calibration",
        "untrusted_lux", "owner_veto", "stale_boundary", "screen_sync_owner",
        "screen_sync_guard_missing", "preserve_off", "cap_below_original",
        "no_lift", "candidate", "candidate_capped",
    ]
    candidate_l2: int | None = None
    capped: bool = False
    light_id: Literal["2"] = "2"
    policy: Literal["desk_diffuse_l2_unwired_v1"] = "desk_diffuse_l2_unwired_v1"


def resolve_desk_diffuse_l2_candidate(context: DeskDiffuseL2Context) -> DeskDiffuseL2Decision:
    """Gate caller assertions and bound a supplied floor; no IO or implicit clock.

    A current epoch boolean models a snapshot boundary only. The caller must
    still perform final ownership/lease checks at dispatch; this cannot fence a
    write, validate a sensor, acquire ownership, or bypass an existing cap.
    """
    c = context
    if any(type(getattr(c, f.name)) is not bool for f in fields(c) if f.type is bool):
        return DeskDiffuseL2Decision("invalid_input")
    if c.period not in ("day", "evening", "night", "late_night") or c.branch not in (
        "static", "screen_sync",
    ):
        return DeskDiffuseL2Decision("invalid_input")
    if any(type(v) is not int or not 1 <= v <= 254 for v in (
        c.original_l2_bri, c.effective_l2_cap,
    )):
        return DeskDiffuseL2Decision("invalid_input")
    if not c.original_l2_on:
        return DeskDiffuseL2Decision("preserve_off")
    if not (c.house_state == "Home" and c.awake and c.physical_source == "desktop"
            and c.physical_zone == "desk" and c.physical_qualified and c.physical_fresh
            and c.eligible_screen_viewing):
        return DeskDiffuseL2Decision("ineligible_context")
    if c.activity not in ("general", "working", "watching") and not (
        c.activity == "gaming" and c.gaming_context == "accepted_director"
    ):
        return DeskDiffuseL2Decision("ineligible_activity")
    if not c.calibration_verified or c.calibrated_floor is None or c.calibration_period != c.period:
        return DeskDiffuseL2Decision("unverified_calibration")
    if type(c.calibrated_floor) is not int or not 1 <= c.calibrated_floor <= 254:
        return DeskDiffuseL2Decision("invalid_input")
    if not (c.bedroom_lux_trusted and c.bedroom_lux_calibrated
            and c.bedroom_lux_room_qualified and c.bedroom_lux_fresh):
        return DeskDiffuseL2Decision("untrusted_lux")
    if not c.rebrightening_authorized or any((
        c.dnd, c.manual_l2, c.scene, c.effect, c.transit, c.protected,
        c.external_owner, c.external_off, c.hard_off, c.stronger_device_owner,
    )):
        return DeskDiffuseL2Decision("owner_veto")
    if not c.transition_epoch_current:
        return DeskDiffuseL2Decision("stale_boundary")
    if c.branch == "static" and c.screen_sync_owns_l2:
        return DeskDiffuseL2Decision("screen_sync_owner")
    if c.branch == "screen_sync" and not (
        c.screen_sync_owns_l2 and c.screen_sync_lease_current and c.same_frame_guard_guaranteed
    ):
        return DeskDiffuseL2Decision("screen_sync_guard_missing")
    capped = c.calibrated_floor > c.effective_l2_cap
    if c.effective_l2_cap < c.original_l2_bri:
        return DeskDiffuseL2Decision("cap_below_original", capped=capped)
    target = min(c.calibrated_floor, c.effective_l2_cap)
    if target <= c.original_l2_bri:
        return DeskDiffuseL2Decision("no_lift", capped=capped)
    return DeskDiffuseL2Decision("candidate_capped" if capped else "candidate", target, capped)


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
