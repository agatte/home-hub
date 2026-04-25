"""
Background-task heartbeat registry.

Long-running asyncio loops (Hue/Sonos polling, automation engine, scheduler,
camera, etc.) call ``tick(name)`` once per iteration; ``/health`` reads
``snapshot()`` to flag any task whose last tick is older than 2x its
expected interval. The class is pure data — no I/O, no async — so it can
be instantiated once in lifespan and injected into each service via a
setter (mirrors ``automation._confidence_fusion = ...`` in ``main.py``).

A task is considered "warm" the moment ``register`` is called: ``last_tick``
is initialized to the registration timestamp so a freshly-started service
isn't flagged as stale before its first iteration even runs. Long-cadence
tasks (rule engine, 6h) get the same warm-up allotment.

Tests in ``tests/test_heartbeat.py`` lock the staleness math.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Optional


@dataclass
class _Heartbeat:
    name: str
    expected_interval_seconds: float
    last_tick: datetime


class HeartbeatRegistry:
    """In-memory map of task name → last-tick timestamp + expected cadence."""

    # Multiplier on expected_interval before a task is flagged stale.
    # 2x means a 1s poll is stale at >2s, a 60s loop at >120s, etc.
    STALE_MULTIPLIER = 2.0

    def __init__(self) -> None:
        self._beats: dict[str, _Heartbeat] = {}
        self._lock = Lock()

    def register(self, name: str, expected_interval_seconds: float) -> None:
        """Add a task to the registry with its expected polling cadence.

        Initializes ``last_tick`` to now so the task gets a full warm-up
        window before it can be flagged as stale.
        """
        if expected_interval_seconds <= 0:
            raise ValueError(
                f"expected_interval_seconds must be positive, got {expected_interval_seconds}"
            )
        now = datetime.now(timezone.utc)
        with self._lock:
            self._beats[name] = _Heartbeat(
                name=name,
                expected_interval_seconds=float(expected_interval_seconds),
                last_tick=now,
            )

    def deregister(self, name: str) -> None:
        """Remove a task from the registry. Used when an opt-in service
        (camera) is disabled or paused — better to drop out cleanly than
        be flagged stale during legitimate downtime."""
        with self._lock:
            self._beats.pop(name, None)

    def tick(self, name: str) -> None:
        """Update ``last_tick`` for a registered task. No-op for unknown
        names — keeps callers from raising during teardown races."""
        beat = self._beats.get(name)
        if beat is None:
            return
        beat.last_tick = datetime.now(timezone.utc)

    def snapshot(self, now: Optional[datetime] = None) -> list[dict]:
        """Return per-task heartbeat status for ``/health``.

        Each row: ``{name, interval_seconds, age_seconds, stale}``.
        Sorted by name for stable output across calls. ``now`` is
        injectable for tests so staleness can be exercised without
        sleeping.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        rows: list[dict] = []
        with self._lock:
            beats = list(self._beats.values())
        for beat in beats:
            age = (now - beat.last_tick).total_seconds()
            rows.append(
                {
                    "name": beat.name,
                    "interval_seconds": beat.expected_interval_seconds,
                    "age_seconds": round(age, 3),
                    "stale": age > beat.expected_interval_seconds * self.STALE_MULTIPLIER,
                }
            )
        rows.sort(key=lambda r: r["name"])
        return rows

    def clear(self) -> None:
        """Drop all heartbeats. Used by tests for isolation."""
        with self._lock:
            self._beats.clear()
