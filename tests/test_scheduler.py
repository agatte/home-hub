"""
Tests for the async scheduler — task registration, next-run calculation, dedup.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.services.scheduler import AsyncScheduler, ScheduledTask

TZ = ZoneInfo("America/Indiana/Indianapolis")


# ---------------------------------------------------------------------------
# ScheduledTask dataclass defaults
# ---------------------------------------------------------------------------

class TestScheduledTask:
    """Verify ScheduledTask defaults."""

    def test_default_weekdays_are_weekdays(self):
        task = ScheduledTask(name="t", hour=8, minute=0)
        assert task.weekdays == [0, 1, 2, 3, 4]

    def test_default_enabled(self):
        task = ScheduledTask(name="t", hour=8, minute=0)
        assert task.enabled is True

    def test_default_last_run_is_none(self):
        task = ScheduledTask(name="t", hour=8, minute=0)
        assert task.last_run is None


# ---------------------------------------------------------------------------
# AsyncScheduler
# ---------------------------------------------------------------------------

class TestAsyncScheduler:
    """Test scheduler task management and next-run calculation."""

    @pytest.fixture
    def scheduler(self):
        return AsyncScheduler()

    def test_add_task(self, scheduler):
        task = ScheduledTask(name="morning", hour=6, minute=40)
        scheduler.add_task(task)
        assert "morning" in scheduler._tasks

    def test_remove_task(self, scheduler):
        task = ScheduledTask(name="morning", hour=6, minute=40)
        scheduler.add_task(task)
        scheduler.remove_task("morning")
        assert "morning" not in scheduler._tasks

    def test_remove_nonexistent_is_safe(self, scheduler):
        scheduler.remove_task("nope")  # should not raise

    def test_enable_disable(self, scheduler):
        task = ScheduledTask(name="morning", hour=6, minute=40)
        scheduler.add_task(task)
        scheduler.disable_task("morning")
        assert scheduler._tasks["morning"].enabled is False
        scheduler.enable_task("morning")
        assert scheduler._tasks["morning"].enabled is True

    def test_get_tasks_returns_formatted(self, scheduler):
        task = ScheduledTask(name="morning", hour=6, minute=40)
        scheduler.add_task(task)
        tasks = scheduler.get_tasks()
        assert len(tasks) == 1
        assert tasks[0]["name"] == "morning"
        assert tasks[0]["time"] == "06:40"
        assert tasks[0]["enabled"] is True

    def test_next_run_disabled_returns_none(self, scheduler):
        task = ScheduledTask(name="t", hour=8, minute=0, enabled=False)
        now = datetime(2026, 4, 14, 7, 0, tzinfo=TZ)  # Tuesday
        assert scheduler._next_run_time(task, now) is None

    def test_next_run_no_weekdays_returns_none(self, scheduler):
        task = ScheduledTask(name="t", hour=8, minute=0, weekdays=[])
        now = datetime(2026, 4, 14, 7, 0, tzinfo=TZ)
        assert scheduler._next_run_time(task, now) is None

    def test_next_run_today_if_in_future(self, scheduler):
        # Tuesday April 14, 7am — task at 8am on weekdays should be today
        task = ScheduledTask(name="t", hour=8, minute=0, weekdays=[0, 1, 2, 3, 4])
        now = datetime(2026, 4, 14, 7, 0, tzinfo=TZ)
        result = scheduler._next_run_time(task, now)
        assert result is not None
        assert result.day == 14
        assert result.hour == 8

    def test_next_run_tomorrow_if_past(self, scheduler):
        # Tuesday April 14, 9am — task at 8am should be Wednesday
        task = ScheduledTask(name="t", hour=8, minute=0, weekdays=[0, 1, 2, 3, 4])
        now = datetime(2026, 4, 14, 9, 0, tzinfo=TZ)
        result = scheduler._next_run_time(task, now)
        assert result is not None
        assert result.day == 15

    def test_next_run_skips_weekend(self, scheduler):
        # Friday April 17, 9am — task at 8am on weekdays should be Monday
        task = ScheduledTask(name="t", hour=8, minute=0, weekdays=[0, 1, 2, 3, 4])
        now = datetime(2026, 4, 17, 9, 0, tzinfo=TZ)
        result = scheduler._next_run_time(task, now)
        assert result is not None
        assert result.weekday() == 0  # Monday


# ---------------------------------------------------------------------------
# Task status fields surfaced via /health.scheduler_tasks
# ---------------------------------------------------------------------------

class TestTaskStatusFields:
    """Verify last_status / last_error stamping + get_tasks shape."""

    def test_default_status_is_pending(self):
        task = ScheduledTask(name="t", hour=8, minute=0)
        assert task.last_status == "pending"
        assert task.last_error is None

    def test_get_tasks_includes_status_fields(self):
        scheduler = AsyncScheduler()
        scheduler.add_task(ScheduledTask(name="morning", hour=6, minute=40))
        snapshot = scheduler.get_tasks()[0]
        assert snapshot["last_status"] == "pending"
        assert snapshot["last_error"] is None
        assert snapshot["last_run_age_seconds"] is None

    @pytest.mark.asyncio
    async def test_execute_task_success_path(self):
        scheduler = AsyncScheduler()
        ran = []

        async def cb():
            ran.append(1)

        task = ScheduledTask(name="t", hour=0, minute=0, callback=cb)
        await scheduler._execute_task(task, datetime(2026, 5, 6, 12, 0, tzinfo=TZ))

        assert ran == [1]
        assert task.last_status == "ok"
        assert task.last_error is None
        assert task.last_run is not None

    @pytest.mark.asyncio
    async def test_execute_task_failure_captures_error(self):
        scheduler = AsyncScheduler()

        async def cb():
            raise RuntimeError("boom")

        task = ScheduledTask(name="t", hour=0, minute=0, callback=cb)
        # Helper must not propagate the exception — scheduler can't crash
        # on one task or every other task in the loop dies.
        await scheduler._execute_task(task, datetime(2026, 5, 6, 12, 0, tzinfo=TZ))

        assert task.last_status == "error"
        assert "RuntimeError" in (task.last_error or "")
        assert "boom" in (task.last_error or "")
        assert task.last_run is not None  # task fired even though it raised

    @pytest.mark.asyncio
    async def test_execute_task_truncates_long_errors(self):
        scheduler = AsyncScheduler()
        long_msg = "x" * 1000

        async def cb():
            raise RuntimeError(long_msg)

        task = ScheduledTask(name="t", hour=0, minute=0, callback=cb)
        await scheduler._execute_task(task, datetime(2026, 5, 6, 12, 0, tzinfo=TZ))

        assert task.last_error is not None
        assert len(task.last_error) <= 500
