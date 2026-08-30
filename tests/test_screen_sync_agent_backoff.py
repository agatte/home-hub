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


def test_foreground_snapshot_media_matches_activity_detector_rule() -> None:
    assert screen_sync_agent._foreground_snapshot_is_media(
        "firefox.exe", "Blue Planet - YouTube - Mozilla Firefox"
    ) is True
    assert screen_sync_agent._foreground_snapshot_is_media(
        "firefox.exe", "ChatGPT - homehub - Mozilla Firefox"
    ) is False
    assert screen_sync_agent._foreground_snapshot_is_media(
        "stremio.exe", "Stremio"
    ) is True


def test_color_payload_carries_immediate_foreground_media(monkeypatch) -> None:
    monkeypatch.setattr(screen_sync_agent, "_foreground_media_active", lambda: False)

    payload = screen_sync_agent._build_color_payload((1, 2, 3), 17)

    assert payload == {
        "source": "desktop",
        "r": 1, "g": 2, "b": 3,
        "luma": 17,
        "foreground_media": False,
    }
