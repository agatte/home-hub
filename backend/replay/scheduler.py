"""Stable virtual-time queue; participant continuations are async and never sleep."""

from __future__ import annotations

import heapq
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from .clock import ReplayClock
from .schema import InputEnvelopeV1


Continuation = Callable[[], Awaitable[None]]
InputDispatcher = Callable[[InputEnvelopeV1], Awaitable[None]]


@dataclass(frozen=True, eq=False)
class ScheduledHandle:
    """Identity belongs to one scheduler and survives cancellation/completion."""

    enqueue_sequence: int


class ReplayScheduler:
    def __init__(self, clock: ReplayClock) -> None:
        self.clock = clock
        self._queue: list[tuple[int, int, ScheduledHandle, str, Continuation]] = []
        self._states: dict[ScheduledHandle, str] = {}
        self._next_sequence = 0
        self._running = False

    def schedule(
        self, deadline_mono_ns: int, participant: str, continuation: Continuation
    ) -> ScheduledHandle:
        if isinstance(deadline_mono_ns, bool) or not isinstance(deadline_mono_ns, int):
            raise TypeError("scheduler deadline must be an integer nanosecond value")
        if deadline_mono_ns < self.clock.monotonic_ns():
            raise ValueError("cannot schedule before current virtual monotonic time")
        if not isinstance(participant, str) or not participant:
            raise ValueError("participant must be a nonempty string")
        if not callable(continuation):
            raise TypeError("continuation must be an async callable")
        handle = ScheduledHandle(self._next_sequence)
        self._next_sequence += 1
        self._states[handle] = "pending"
        heapq.heappush(
            self._queue,
            (deadline_mono_ns, handle.enqueue_sequence, handle, participant, continuation),
        )
        return handle

    def cancel(self, handle: ScheduledHandle) -> None:
        if handle not in self._states:
            raise ValueError("handle does not belong to this scheduler")
        if self._states[handle] == "pending":
            self._states[handle] = "cancelled"

    async def run_until(self, end_mono_ns: int) -> None:
        if self._running:
            raise RuntimeError("run_until cannot be nested")
        if isinstance(end_mono_ns, bool) or not isinstance(end_mono_ns, int):
            raise TypeError("run_until end must be an integer nanosecond value")
        if end_mono_ns < self.clock.monotonic_ns():
            raise ValueError("run_until cannot move virtual time backward")
        self._running = True
        try:
            while self._queue and self._queue[0][0] <= end_mono_ns:
                deadline, _, handle, _, continuation = heapq.heappop(self._queue)
                if self._states[handle] == "cancelled":
                    continue
                self.clock.advance_to(deadline)
                self._states[handle] = "running"
                try:
                    await continuation()
                finally:
                    self._states[handle] = "done"
            self.clock.advance_to(end_mono_ns)
        finally:
            self._running = False


def schedule_recorded_inputs(
    scheduler: ReplayScheduler,
    inputs: Iterable[InputEnvelopeV1],
    dispatcher: InputDispatcher,
    *,
    backend_boot_id: str,
    backend_session_id: str,
    clock_domain: str,
) -> tuple[ScheduledHandle, ...]:
    """Enqueue validated JSONL events in recorded receipt/dispatch order.

    This only delivers records supplied by the caller. It never derives polls
    or deadlines from elapsed time or from neighboring evidence.
    """

    if scheduler.clock.clock_domain != clock_domain:
        raise ValueError("scheduler clock domain differs from recorded inputs")
    events = tuple(inputs)
    previous_mono = scheduler.clock.monotonic_ns()
    previous_dispatch = -1
    seen_ids: set[str] = set()
    for event in events:
        if (
            event.backend_boot_id != backend_boot_id
            or event.backend_session_id != backend_session_id
            or event.clock_domain != clock_domain
        ):
            raise ValueError(f"{event.event_id}: recorded input identity differs from checkpoint")
        if event.event_id in seen_ids:
            raise ValueError(f"duplicate recorded event_id {event.event_id}")
        if (
            event.received_mono_ns < previous_mono
            or event.backend_dispatch_sequence <= previous_dispatch
        ):
            raise ValueError("recorded inputs must be in monotonic/dispatch JSONL order")
        seen_ids.add(event.event_id)
        previous_mono = event.received_mono_ns
        previous_dispatch = event.backend_dispatch_sequence

    handles = []
    for event in events:

        async def deliver(record: InputEnvelopeV1 = event) -> None:
            await dispatcher(record)

        handles.append(scheduler.schedule(event.received_mono_ns, event.kind, deliver))
    return tuple(handles)
