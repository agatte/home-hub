"""Shared serialization and physical-settle boundary for Hue effect changes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator, Iterable


class LightingTransitionBoundary:
    """Serialize Hue writes while an effect lifecycle transition is active.

    Ordinary writers take this lock only around their bridge write. Effect
    transitions hold it across safety establishment, physical settling, and
    effect release/start. The ContextVar is an ownership marker, not a
    re-entrant lock: nested collaborators observe the existing boundary and
    avoid trying to acquire the same ``asyncio.Lock`` again.
    """

    def __init__(self, hue_service) -> None:
        self._hue = hue_service
        self._lock = asyncio.Lock()
        self._held: ContextVar[bool] = ContextVar(
            "hue_effect_transition_boundary_held", default=False,
        )

    @property
    def held_by_current_task(self) -> bool:
        """Whether the current task is already inside the boundary."""
        return self._held.get()

    @asynccontextmanager
    async def serialized(self) -> AsyncIterator[None]:
        """Acquire the boundary once for the current transition task."""
        if self.held_by_current_task:
            raise RuntimeError("Hue transition boundary cannot be re-entered")
        async with self._lock:
            token = self._held.set(True)
            try:
                yield
            finally:
                self._held.reset(token)

    async def wait_for_settle(self, light_ids: Iterable[str]) -> None:
        """Wait for successful writes' commanded transitions to complete."""
        waiter = getattr(self._hue, "wait_for_transition_settle", None)
        if waiter is not None:
            await waiter(light_ids)
