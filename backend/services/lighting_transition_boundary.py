"""Shared serialization and physical-settle boundary for Hue effect changes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator, Awaitable, Callable, Iterable

from backend.services.lighting_authority import LightingAuthority


# Propagated through delegated tasks and asyncio.to_thread. Validators must be
# synchronous, nonblocking reads of the captured owner (never asyncio APIs).
lighting_write_validator: ContextVar[Callable[[], bool] | None] = ContextVar(
    "homehub_lighting_write_validator", default=None,
)


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
        # Every serialized ownership turn has a unique epoch, including ABA.
        # A to_thread Hue validator must still belong to the same turn.
        self._serialized_epoch = 0
        self._delegated_worker_epoch: ContextVar[int | None] = ContextVar(
            "hue_delegated_worker_epoch", default=None,
        )
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

    @property
    def delegated_worker_validator_active(self) -> bool:
        """Allow synchronous lease validation in the guarded Hue worker only.

        asyncio.to_thread inherits the delegated task context, but has no
        running asyncio Task. An epoch + still-held lock prove that the exact
        delegated serialization turn remains active. A plain executor caller
        or one from an older/cancelled turn cannot use this exception.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            epoch = self._delegated_worker_epoch.get()
            return bool(
                epoch is not None
                and epoch == self._serialized_epoch
                and self._lock.locked()
                and lighting_write_validator.get() is not None
            )
        return False

    @asynccontextmanager
    async def serialized(self) -> AsyncIterator[None]:
        """Acquire the boundary once for the current transition task."""
        if self.held_by_current_task:
            raise RuntimeError("Hue transition boundary cannot be re-entered")
        async with self._lock:
            self._serialized_epoch += 1
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

        epoch = self._serialized_epoch
        inherited_validator = lighting_write_validator.get()
        local_validator = validator

        def validator():
            # Preserve the originating engine/source fence when a native
            # scene/effect supplies its own lease validator after safety/settle.
            return (
                (inherited_validator is None or inherited_validator())
                and (local_validator is None or local_validator())
            )

        async def mutate():
            token = self._held.set(asyncio.current_task())
            validator_token = lighting_write_validator.set(validator)
            worker_epoch_token = self._delegated_worker_epoch.set(epoch)
            try:
                if validator is not None and not validator():
                    return False
                return await write()
            finally:
                self._delegated_worker_epoch.reset(worker_epoch_token)
                lighting_write_validator.reset(validator_token)
                self._held.reset(token)

        return asyncio.create_task(mutate())

    async def run_write(self, write: Callable[[], Awaitable], *, validator=None, light_ids=None):
        """Delegate one mutation explicitly, retaining the caller's fence."""
        return await settle_lighting_io(self._delegate_write(write, validator))

    async def write_many(
        self, writes: Iterable[Callable[[], Awaitable]], *,
        light_ids=None, validator=None, validators=None,
    ):
        """Parallel canonical writes with explicit, bounded lock delegation."""
        writes = list(writes)
        checks = [validator] * len(writes) if validators is None else list(validators)
        if len(checks) != len(writes):
            raise ValueError("Each write requires one validator")
        operations = [
            self._delegate_write(write, validator=check)
            for write, check in zip(writes, checks)
        ]
        return await settle_lighting_io(asyncio.gather(*operations, return_exceptions=True))
