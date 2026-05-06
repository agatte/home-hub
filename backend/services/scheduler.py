"""
Async cron-like scheduler for recurring tasks.

Uses asyncio to schedule tasks at specific times on specific weekdays.
No external dependencies — runs inside the FastAPI event loop.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Coroutine
from zoneinfo import ZoneInfo

logger = logging.getLogger("home_hub.scheduler")

TZ = ZoneInfo("America/Indiana/Indianapolis")


@dataclass
class ScheduledTask:
    """A recurring task that runs at a specific time on specific weekdays."""

    name: str
    hour: int  # 0-23
    minute: int  # 0-59
    weekdays: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri
    callback: Callable[[], Coroutine] = None
    enabled: bool = True
    last_run: datetime | None = None
    last_status: str = "pending"  # pending | ok | error
    last_error: str | None = None


class AsyncScheduler:
    """
    Manages scheduled tasks and executes them at the configured times.

    Checks every 30 seconds whether any task should fire by comparing the
    current time (in US/Eastern) to each task's schedule.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._heartbeat = None  # HeartbeatRegistry, set via set_heartbeat_registry

    def set_heartbeat_registry(self, registry) -> None:
        """Inject the heartbeat registry (called from lifespan)."""
        self._heartbeat = registry

    def add_task(self, task: ScheduledTask) -> None:
        """Register a scheduled task."""
        self._tasks[task.name] = task
        logger.info(
            f"Scheduled task '{task.name}' at "
            f"{task.hour:02d}:{task.minute:02d} on days {task.weekdays}"
        )

    def remove_task(self, name: str) -> None:
        """Remove a scheduled task."""
        self._tasks.pop(name, None)

    def enable_task(self, name: str) -> None:
        """Enable a scheduled task."""
        if name in self._tasks:
            self._tasks[name].enabled = True

    def disable_task(self, name: str) -> None:
        """Disable a scheduled task."""
        if name in self._tasks:
            self._tasks[name].enabled = False

    def get_tasks(self) -> list[dict]:
        """Get all registered tasks with their status."""
        result = []
        now = datetime.now(tz=TZ)
        for task in self._tasks.values():
            next_run = self._next_run_time(task, now)
            last_run_age = (
                (now - task.last_run).total_seconds()
                if task.last_run is not None else None
            )
            result.append({
                "name": task.name,
                "time": f"{task.hour:02d}:{task.minute:02d}",
                "weekdays": task.weekdays,
                "enabled": task.enabled,
                "last_run": task.last_run.isoformat() if task.last_run else None,
                "last_run_age_seconds": last_run_age,
                "last_status": task.last_status,
                "last_error": task.last_error,
                "next_run": next_run.isoformat() if next_run else None,
            })
        return result

    def _next_run_time(
        self, task: ScheduledTask, now: datetime
    ) -> datetime | None:
        """Calculate the next run time for a task."""
        from datetime import timedelta

        if not task.enabled or not task.weekdays:
            return None

        for day_offset in range(8):
            candidate = (now + timedelta(days=day_offset)).replace(
                hour=task.hour, minute=task.minute, second=0, microsecond=0
            )
            if candidate.weekday() in task.weekdays and candidate > now:
                return candidate

        return None

    async def _execute_task(self, task: ScheduledTask, now: datetime) -> None:
        """Run a scheduled task once and stamp its status fields.

        ``last_run`` is stamped before the callback fires (the task fired,
        regardless of outcome). ``last_status`` / ``last_error`` reflect
        the callback's result — surfaced via ``/health.scheduler_tasks``
        for the runbook to query.
        """
        logger.info(f"Executing scheduled task: {task.name}")
        task.last_run = now
        try:
            await task.callback()
            task.last_status = "ok"
            task.last_error = None
        except Exception as e:
            task.last_status = "error"
            task.last_error = repr(e)[:500]
            logger.error(
                f"Scheduled task '{task.name}' failed: {e}",
                exc_info=True,
            )

    async def run_loop(self) -> None:
        """
        Background task — checks every 30 seconds if any task should fire.

        Compares current time in US/Eastern to each task's schedule. A task
        fires if it matches the current hour/minute/weekday and hasn't already
        run in this minute.
        """
        logger.info("Scheduler started")

        while True:
            try:
                if self._heartbeat is not None:
                    self._heartbeat.tick("scheduler")
                now = datetime.now(tz=TZ)

                for task in self._tasks.values():
                    if not task.enabled or not task.callback:
                        continue

                    # Check if this is the right time and day
                    if (
                        now.hour == task.hour
                        and now.minute == task.minute
                        and now.weekday() in task.weekdays
                    ):
                        # Don't run twice in the same minute
                        if task.last_run:
                            last = task.last_run
                            if (
                                last.year == now.year
                                and last.month == now.month
                                and last.day == now.day
                                and last.hour == now.hour
                                and last.minute == now.minute
                            ):
                                continue

                        await self._execute_task(task, now)

                await asyncio.sleep(30)

            except asyncio.CancelledError:
                logger.info("Scheduler stopped")
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                await asyncio.sleep(30)
