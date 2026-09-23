"""Small clock interface for deterministic decision evaluation.

Production participants may use SystemDecisionClock, while offline replay can
inject a deterministic implementation. Wall-time policy remains wall-time
policy; monotonic_ns is reserved for deterministic scheduling and ordering.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol


class DecisionClock(Protocol):
    """Clock surface shared by production decision participants and replay."""

    def utc_now(self) -> datetime:
        """Return the current aware UTC wall time."""

    def monotonic_ns(self) -> int:
        """Return a monotonic timestamp used only for ordering/scheduling."""


class SystemDecisionClock:
    """Production clock delegating to current system time behavior."""

    def __init__(
        self,
        *,
        utc_now_fn: Callable[[], datetime] | None = None,
        monotonic_ns_fn: Callable[[], int] | None = None,
    ) -> None:
        self._utc_now_fn = utc_now_fn or (lambda: datetime.now(timezone.utc))
        self._monotonic_ns_fn = monotonic_ns_fn or time.monotonic_ns

    def utc_now(self) -> datetime:
        now = self._utc_now_fn()
        if now.tzinfo is None:
            raise ValueError("DecisionClock.utc_now() must return an aware datetime")
        return now.astimezone(timezone.utc)

    def monotonic_ns(self) -> int:
        return int(self._monotonic_ns_fn())
