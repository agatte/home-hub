"""Screen-sync supervisor heartbeat coverage for intentional retry backoff."""

from backend.services.pc_agent import screen_sync_agent


class FakeStopEvent:
    """Deterministic stand-in that records waits and can interrupt one call."""

    def __init__(self, stop_on_wait: int | None = None) -> None:
        self.waits: list[float] = []
        self._stop_on_wait = stop_on_wait

    def wait(self, duration: float) -> bool:
        self.waits.append(duration)
        return self._stop_on_wait == len(self.waits)


def test_maximum_backoff_keeps_heartbeat_progress_and_full_duration() -> None:
    stop = FakeStopEvent()
    heartbeats: list[None] = []

    interrupted = screen_sync_agent._wait_for_backoff(
        stop, 60.0, lambda: heartbeats.append(None),
    )

    assert interrupted is False
    assert stop.waits == [10.0] * 6
    assert sum(stop.waits) == 60.0
    assert len(heartbeats) == 5


def test_stop_event_interrupts_backoff_without_waiting_remaining_slices() -> None:
    stop = FakeStopEvent(stop_on_wait=2)
    heartbeats: list[None] = []

    interrupted = screen_sync_agent._wait_for_backoff(
        stop, 60.0, lambda: heartbeats.append(None),
    )

    assert interrupted is True
    assert stop.waits == [10.0, 10.0]
    assert len(heartbeats) == 1


def test_standalone_backoff_uses_original_single_interruptible_wait() -> None:
    stop = FakeStopEvent()

    interrupted = screen_sync_agent._wait_for_backoff(stop, 60.0, None)

    assert interrupted is False
    assert stop.waits == [60.0]
