"""Shared serialization and physical-settle boundary for Hue effect changes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator, Awaitable, Callable, Iterable

from backend.services.lighting_authority import LightingAuthority


async def settle_lighting_io(awaitable):
    """Defer cancellation until local mutation work has actually settled.

    Shielding alone leaves orphan work. Repeated cancellation must also retain
    the fence; consume a settled failure before propagating caller cancellation.
    """
    operation = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not operation.cancelled():
            operation.exception()
        raise


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
        self.authority = LightingAuthority(self)
        self._held: ContextVar[asyncio.Task | None] = ContextVar(
            "hue_effect_transition_boundary_held", default=None,
        )

    @property
    def held_by_current_task(self) -> bool:
        """Whether the current task is already inside the boundary."""
        try:
            task = asyncio.current_task()
        except RuntimeError:
            return False
        return task is not None and self._held.get() is task

    @asynccontextmanager
    async def serialized(self) -> AsyncIterator[None]:
        """Acquire the boundary once for the current transition task."""
        if self.held_by_current_task:
            raise RuntimeError("Hue transition boundary cannot be re-entered")
        async with self._lock:
            token = self._held.set(asyncio.current_task())
            try:
                yield
            finally:
                self._held.reset(token)

    async def wait_for_settle(self, light_ids: Iterable[str]) -> None:
        """Wait for successful writes' commanded transitions to complete."""
        waiter = getattr(self._hue, "wait_for_transition_settle", None)
        if waiter is not None:
            await waiter(light_ids)

    def _delegate_write(self, write: Callable[[], Awaitable], validator=None):
        if not self.held_by_current_task:
            raise RuntimeError("Lighting write delegation requires the boundary")

        async def mutate():
            token = self._held.set(asyncio.current_task())
            try:
                if validator is not None and not validator():
                    return False
                return await write()
            finally:
                self._held.reset(token)

        return asyncio.create_task(mutate())

    async def run_write(self, write: Callable[[], Awaitable], *, validator=None, light_ids=None):
        """Delegate one mutation explicitly, retaining the caller's fence."""
        return await settle_lighting_io(self._delegate_write(write, validator))

    async def write_many(
        self, writes: Iterable[Callable[[], Awaitable]], *,
        light_ids=None, validator=None,
    ):
        """Parallel canonical writes with explicit, bounded lock delegation."""
        operations = [
            self._delegate_write(write, validator=validator)
            for write in writes
        ]
        return await settle_lighting_io(asyncio.gather(*operations, return_exceptions=True))
