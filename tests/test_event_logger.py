"""
Tests for the EventLogger retry queue + threshold alerts.

The retry path is exercised by patching `async_session` so the first call
fails with a transient `OperationalError` and the second call succeeds. We
then drive the drain function manually instead of waiting 30s.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.services import event_logger as event_logger_module
from backend.services.event_logger import (
    EventLogger,
    RETRY_QUEUE_MAXLEN,
    WARN_THRESHOLDS,
)


class _FakeSession:
    """Minimal async-session stand-in that tracks adds + commits."""

    def __init__(self) -> None:
        self.added = []
        self.committed = False

    async def execute(self, *_args, **_kwargs):
        # Backfill SELECT path returns "no prior event"
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True


def _failing_then_succeeding_session(fail_times: int):
    """
    Build an `async_session` replacement whose `__aenter__` raises
    OperationalError `fail_times` times, then yields working FakeSessions.
    """
    state = {"calls": 0, "sessions": []}

    @asynccontextmanager
    async def cm():
        state["calls"] += 1
        if state["calls"] <= fail_times:
            raise OperationalError("stmt", {}, Exception("locked"))
        s = _FakeSession()
        state["sessions"].append(s)
        try:
            yield s
        finally:
            pass

    return cm, state


@pytest.mark.asyncio
async def test_transient_error_enqueues_then_drain_succeeds():
    cm, state = _failing_then_succeeding_session(fail_times=1)
    el = EventLogger()

    with patch.object(event_logger_module, "async_session", cm):
        await el.log_mode_change(mode="working", previous_mode="idle", source="test")
        # First write failed → queued, no drop yet.
        assert el.get_drop_counts()["mode"] == 0
        assert el.get_queue_depth() == 1

        # Drive one drain cycle manually — second async_session() call succeeds.
        await el._drain_once()

        assert el.get_queue_depth() == 0
        assert el.get_drop_counts()["mode"] == 0
        assert state["calls"] == 2
        assert len(state["sessions"]) == 1
        assert state["sessions"][0].committed


@pytest.mark.asyncio
async def test_persistent_error_drops_after_max_attempts():
    """3 failed attempts → entry drops out, drop_count increments."""
    cm, _state = _failing_then_succeeding_session(fail_times=999)
    el = EventLogger()

    with patch.object(event_logger_module, "async_session", cm):
        await el.log_mode_change(mode="working", previous_mode="idle", source="test")
        # Initial enqueue (attempts=1) — no drop yet.
        assert el.get_drop_counts()["mode"] == 0

        # Drain twice more: attempts 2, 3 → still queued / dropped after 3.
        await el._drain_once()  # attempt 2 — requeue at attempts=3? actually 3
        # First drain: attempts is 1 → fails → requeue at 2.
        await el._drain_once()  # attempt 3 — fails → requeue at 4 > MAX, drops
        await el._drain_once()  # nothing to do (or final drop)

        assert el.get_queue_depth() == 0
        assert el.get_drop_counts()["mode"] >= 1


@pytest.mark.asyncio
async def test_integrity_error_drops_immediately_no_retry():
    """Deterministic errors aren't queued — they go straight to drop."""

    @asynccontextmanager
    async def cm():
        raise IntegrityError("stmt", {}, Exception("dup"))
        yield  # pragma: no cover

    el = EventLogger()
    with patch.object(event_logger_module, "async_session", cm):
        await el.log_mode_change(mode="working", previous_mode="idle", source="test")

    assert el.get_drop_counts()["mode"] == 1
    assert el.get_queue_depth() == 0


@pytest.mark.asyncio
async def test_overflow_increments_when_queue_full():
    cm, _state = _failing_then_succeeding_session(fail_times=999)
    el = EventLogger()

    with patch.object(event_logger_module, "async_session", cm):
        # Fill the queue.
        for _ in range(RETRY_QUEUE_MAXLEN):
            await el.log_mode_change(mode="working", previous_mode=None, source="t")
        assert el.get_queue_depth() == RETRY_QUEUE_MAXLEN

        # One more should overflow.
        await el.log_mode_change(mode="idle", previous_mode="working", source="t")

        assert el.get_overflow_counts()["mode"] >= 1
        # Total drops include the overflow drop.
        assert el.get_drop_counts()["mode"] >= 1


@pytest.mark.asyncio
async def test_warn_threshold_logged(caplog):
    """First WARN_THRESHOLDS[0] drops should trigger one WARN log."""
    cm, _state = _failing_then_succeeding_session(fail_times=999)
    el = EventLogger()
    threshold = WARN_THRESHOLDS[0]

    with patch.object(event_logger_module, "async_session", cm):
        with caplog.at_level(logging.WARNING, logger="home_hub.events"):
            # Force overflow drops so the drop counter reaches the threshold
            # without depending on retry-loop scheduling.
            for _ in range(RETRY_QUEUE_MAXLEN + threshold):
                await el.log_mode_change(mode="m", previous_mode=None, source="t")

    assert el.get_drop_counts()["mode"] >= threshold
    warn_messages = [
        rec.message for rec in caplog.records
        if rec.levelno >= logging.WARNING and "drops" in rec.message
    ]
    assert any(f"{threshold} drops" in m or "drops" in m for m in warn_messages)


@pytest.mark.asyncio
async def test_start_and_stop_are_idempotent():
    el = EventLogger()
    task1 = await el.start()
    task2 = await el.start()
    # Same task returned because the first is still running.
    assert task1 is task2
    await el.stop()
    assert task1.cancelled() or task1.done()
    # Stop is safe to call again.
    await el.stop()


@pytest.mark.asyncio
async def test_skipped_no_change_light_adjustment_does_not_touch_db():
    """before == after means nothing actually changed — skip the write entirely."""
    calls = {"n": 0}

    @asynccontextmanager
    async def cm():
        calls["n"] += 1
        yield _FakeSession()

    el = EventLogger()
    with patch.object(event_logger_module, "async_session", cm):
        await el.log_light_adjustment(
            light_id="1",
            bri_before=100,
            bri_after=100,
        )
    assert calls["n"] == 0
