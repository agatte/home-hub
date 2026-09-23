"""Virtual wall and monotonic time for one offline replay boot."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .schema import TimeIdentityV1


class ReplayTimeError(ValueError):
    """A bundle cannot provide an unambiguous virtual time mapping."""


def parse_utc(value: str, label: str) -> datetime:
    """Parse an explicitly UTC timestamp without losing sub-microsecond digits."""

    if not isinstance(value, str) or re.search(r"\.\d{7,}", value):
        raise ReplayTimeError(f"{label} must be a UTC timestamp with microsecond precision")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReplayTimeError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ReplayTimeError(f"{label} must be aware UTC")
    return parsed.astimezone(timezone.utc)


def _delta_ns(later: datetime, earlier: datetime) -> int:
    delta = later - earlier
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


class ReplayClock:
    """Map one recorded monotonic domain to UTC without consulting system time.

    UTC datetimes have microsecond resolution, so sub-microsecond monotonic
    advances are rounded down to the preceding UTC microsecond on reads.
    """

    def __init__(self, time: TimeIdentityV1, checkpoint_utc: str) -> None:
        if time.adjustments:
            raise ReplayTimeError("non-empty wall-time adjustments have no v1 replay mapping")
        self.clock_domain = time.clock_domain
        self.backend_monotonic_origin_ns = time.backend_monotonic_origin_ns
        self.wall_time_anchor_utc = parse_utc(time.wall_time_anchor_utc, "wall_time_anchor_utc")
        checkpoint = parse_utc(checkpoint_utc, "checkpoint_utc")
        cut = self.backend_monotonic_origin_ns + _delta_ns(checkpoint, self.wall_time_anchor_utc)
        if cut < 0:
            raise ReplayTimeError("checkpoint precedes the nonnegative monotonic domain")
        self._mono_ns = cut
        if self.utc_now() != checkpoint:
            raise ReplayTimeError("checkpoint cannot be represented by the clock anchor")

    def monotonic_ns(self) -> int:
        return self._mono_ns

    def utc_now(self) -> datetime:
        offset_ns = self._mono_ns - self.backend_monotonic_origin_ns
        try:
            return self.wall_time_anchor_utc + timedelta(microseconds=offset_ns // 1_000)
        except OverflowError as exc:
            raise ReplayTimeError("virtual wall time exceeds datetime range") from exc

    def advance_to(self, mono_ns: int) -> None:
        if isinstance(mono_ns, bool) or not isinstance(mono_ns, int):
            raise TypeError("monotonic deadline must be an integer nanosecond value")
        if mono_ns < self._mono_ns:
            raise ReplayTimeError("virtual monotonic time cannot move backward")
        previous = self._mono_ns
        self._mono_ns = mono_ns
        try:
            self.utc_now()
        except ReplayTimeError:
            self._mono_ns = previous
            raise
