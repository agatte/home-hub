"""
Event logger — records raw behavioral events to SQLite for future learning.

Captures mode transitions, manual light adjustments, and Sonos playback
events. No analysis is done here — this is pure data capture so the
learning engine has historical data to work with.

Each log call is fire-and-forget: errors don't propagate. Transient DB
errors (SQLite WAL contention, brief IO hiccups) land in a bounded in-memory
retry queue drained every 30s; deterministic errors (IntegrityError, etc.)
go straight to the drop counter. A process restart loses the queue — that's
acceptable for this single-user system.
"""
import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError, TimeoutError as SATimeoutError

from backend.database import async_session
from backend.models import ActivityEvent, LightAdjustment, SceneActivation, SonosPlaybackEvent

logger = logging.getLogger("home_hub.events")

# Retry queue capacity. 200 × ~1KB closure = trivial memory.
RETRY_QUEUE_MAXLEN = 200
# How often the background loop drains the queue.
RETRY_DRAIN_INTERVAL_SECONDS = 30
# Max attempts per queued entry before it's dropped.
MAX_RETRY_ATTEMPTS = 3
# Cumulative-drop thresholds at which we emit a WARN (geometric, per family).
WARN_THRESHOLDS = (5, 10, 25, 100)
# Retryable exception types — transient, worth a second look.
RETRYABLE_EXCEPTIONS = (OperationalError, SATimeoutError, OSError, asyncio.TimeoutError)

# Type alias — a builder that receives a fresh session and performs the insert.
_WriteFn = Callable[["async_session"], Awaitable[None]]


class EventLogger:
    """Thin async wrapper for writing behavioral events to the database."""

    def __init__(self) -> None:
        # Cumulative events dropped by family — both DB-error drops and
        # queue-overflow drops accumulate here so /health shows total loss.
        self._drop_count: dict[str, int] = {
            "mode": 0,
            "light": 0,
            "scene": 0,
            "sonos": 0,
        }
        # Overflow drops only (queue was full when retry was attempted).
        # Tracked separately so operators can distinguish "failed once and lost"
        # from "failed repeatedly and kept getting requeued until full".
        self._overflow_count: dict[str, int] = {
            "mode": 0,
            "light": 0,
            "scene": 0,
            "sonos": 0,
        }
        # Highest WARN-threshold already logged per family.
        self._last_warned_threshold: dict[str, int] = {
            "mode": 0,
            "light": 0,
            "scene": 0,
            "sonos": 0,
        }
        # (family, attempts_so_far, write_fn). Bounded deque drops oldest on full.
        self._retry_queue: deque[tuple[str, int, _WriteFn]] = deque(
            maxlen=RETRY_QUEUE_MAXLEN
        )
        self._retry_task: Optional[asyncio.Task] = None
        self._heartbeat = None  # HeartbeatRegistry, set via set_heartbeat_registry

    def set_heartbeat_registry(self, registry) -> None:
        """Inject the heartbeat registry (called from lifespan)."""
        self._heartbeat = registry

    # ------------------------------------------------------------------ public

    def get_drop_counts(self) -> dict[str, int]:
        """Return cumulative drop counts since process start."""
        return dict(self._drop_count)

    def get_overflow_counts(self) -> dict[str, int]:
        """Return cumulative queue-overflow counts since process start."""
        return dict(self._overflow_count)

    def get_queue_depth(self) -> int:
        """Current pending-retry count across all families."""
        return len(self._retry_queue)

    async def start(self) -> asyncio.Task:
        """Spawn the background retry loop. Idempotent."""
        if self._retry_task is None or self._retry_task.done():
            self._retry_task = asyncio.create_task(self._retry_loop())
        return self._retry_task

    async def stop(self) -> None:
        """Cancel the retry loop. Safe to call if start() was never called."""
        task = self._retry_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------ writes

    async def log_mode_change(
        self,
        mode: str,
        previous_mode: Optional[str],
        source: str,
    ) -> None:
        """
        Record a mode transition.

        Also backfills duration_seconds on the previous event by computing
        the elapsed time since it was written. The `captured_now` is frozen
        at call time so retries compute duration against the real event
        time, not the retry time.
        """
        captured_now = datetime.now(timezone.utc)

        async def _write(session) -> None:
            # Backfill duration on the most recent prior undurated event.
            # Invariant: when a new event lands, the previous event's
            # duration is simply (captured_now - its timestamp).
            result = await session.execute(
                select(ActivityEvent)
                .where(ActivityEvent.duration_seconds.is_(None))
                .order_by(ActivityEvent.timestamp.desc())
                .limit(1)
            )
            prev_event = result.scalar_one_or_none()
            if prev_event and prev_event.timestamp is not None:
                # SQLite stores DateTime(timezone=True) as a naive string,
                # so SQLAlchemy deserializes it without tzinfo. Normalize
                # to UTC before subtracting our tz-aware captured_now.
                prev_ts = prev_event.timestamp
                if not isinstance(prev_ts, datetime):
                    prev_ts = datetime.fromisoformat(str(prev_ts))
                if prev_ts.tzinfo is None:
                    prev_ts = prev_ts.replace(tzinfo=timezone.utc)
                elapsed = int((captured_now - prev_ts).total_seconds())
                await session.execute(
                    update(ActivityEvent)
                    .where(ActivityEvent.id == prev_event.id)
                    .values(duration_seconds=elapsed)
                )

            session.add(ActivityEvent(
                timestamp=captured_now,
                mode=mode,
                previous_mode=previous_mode,
                source=source,
            ))

        await self._write("mode", _write)

    async def log_light_adjustment(
        self,
        light_id: str,
        light_name: Optional[str] = None,
        bri_before: Optional[int] = None,
        bri_after: Optional[int] = None,
        hue_before: Optional[int] = None,
        hue_after: Optional[int] = None,
        sat_before: Optional[int] = None,
        sat_after: Optional[int] = None,
        ct_before: Optional[int] = None,
        ct_after: Optional[int] = None,
        mode_at_time: Optional[str] = None,
        trigger: Optional[str] = None,
    ) -> None:
        """Record a light change issued from the dashboard or an API client."""
        # Skip if nothing actually changed — avoids noise from heartbeat writes
        # and slider debouncing that lands on the same value.
        changed = any(
            after is not None and after != before
            for before, after in (
                (bri_before, bri_after),
                (hue_before, hue_after),
                (sat_before, sat_after),
                (ct_before, ct_after),
            )
        )
        if not changed:
            return

        async def _write(session) -> None:
            session.add(LightAdjustment(
                light_id=light_id,
                light_name=light_name,
                bri_before=bri_before,
                bri_after=bri_after,
                hue_before=hue_before,
                hue_after=hue_after,
                sat_before=sat_before,
                sat_after=sat_after,
                ct_before=ct_before,
                ct_after=ct_after,
                mode_at_time=mode_at_time,
                trigger=trigger,
            ))

        await self._write("light", _write)

    async def log_scene_activation(
        self,
        scene_id: str,
        scene_name: Optional[str],
        source: str,
        mode_at_time: Optional[str],
    ) -> None:
        """Record a scene activation."""
        async def _write(session) -> None:
            session.add(SceneActivation(
                scene_id=scene_id,
                scene_name=scene_name,
                source=source,
                mode_at_time=mode_at_time,
            ))

        await self._write("scene", _write)

    async def log_sonos_event(
        self,
        event_type: str,
        favorite_title: Optional[str],
        mode_at_time: Optional[str],
        volume: Optional[int] = None,
        triggered_by: str = "manual",
    ) -> None:
        """Record a Sonos playback event."""
        async def _write(session) -> None:
            session.add(SonosPlaybackEvent(
                event_type=event_type,
                favorite_title=favorite_title,
                mode_at_time=mode_at_time,
                volume=volume,
                triggered_by=triggered_by,
            ))

        await self._write("sonos", _write)

    # ------------------------------------------------------------------ internal

    async def _write(self, family: str, write_fn: _WriteFn) -> None:
        """
        Execute a write. On transient failure, enqueue for retry; on
        deterministic failure, drop. Never raises.
        """
        try:
            async with async_session() as session:
                await write_fn(session)
                await session.commit()
        except RETRYABLE_EXCEPTIONS as e:
            self._enqueue(family, write_fn, attempts=1, reason=e)
        except IntegrityError as e:
            # Deterministic — retrying won't help. Drop.
            self._drop_count[family] += 1
            self._maybe_warn(family)
            logger.error("event_logger %s: integrity error, dropped: %s", family, e)
        except Exception as e:
            # Unknown — treat as retryable once so a transient we haven't
            # classified yet gets a second chance, then drop.
            self._drop_count[family] += 1
            self._maybe_warn(family)
            logger.error(
                "event_logger %s: unexpected error, dropped: %s",
                family, e, exc_info=True,
            )

    def _enqueue(
        self,
        family: str,
        write_fn: _WriteFn,
        attempts: int,
        reason: Exception,
    ) -> None:
        if len(self._retry_queue) >= RETRY_QUEUE_MAXLEN:
            # deque(maxlen) would drop oldest silently — we prefer explicit
            # overflow accounting so the /health endpoint shows the pressure.
            self._drop_count[family] += 1
            self._overflow_count[family] += 1
            self._maybe_warn(family)
            logger.warning(
                "event_logger %s: retry queue full (cap=%d), dropping: %s",
                family, RETRY_QUEUE_MAXLEN, reason,
            )
            return
        self._retry_queue.append((family, attempts, write_fn))
        logger.debug(
            "event_logger %s: queued for retry (attempt %d, depth=%d): %s",
            family, attempts, len(self._retry_queue), reason,
        )

    def _maybe_warn(self, family: str) -> None:
        """Log WARN once per geometric threshold crossing."""
        count = self._drop_count[family]
        for threshold in WARN_THRESHOLDS:
            if count >= threshold and self._last_warned_threshold[family] < threshold:
                self._last_warned_threshold[family] = threshold
                logger.warning(
                    "event_logger %s: %d drops (queue depth=%d, overflows=%d)",
                    family, count, len(self._retry_queue),
                    self._overflow_count[family],
                )

    async def _retry_loop(self) -> None:
        """Background task: drain the retry queue every RETRY_DRAIN_INTERVAL_SECONDS."""
        try:
            while True:
                await asyncio.sleep(RETRY_DRAIN_INTERVAL_SECONDS)
                if self._heartbeat is not None:
                    self._heartbeat.tick("event_logger_retry")
                await self._drain_once()
        except asyncio.CancelledError:
            raise

    async def _drain_once(self) -> None:
        """Attempt to flush every entry currently in the queue exactly once."""
        if not self._retry_queue:
            return
        # Snapshot and clear — new enqueues during drain go to the next cycle.
        pending = list(self._retry_queue)
        self._retry_queue.clear()
        for family, attempts, write_fn in pending:
            try:
                async with async_session() as session:
                    await write_fn(session)
                    await session.commit()
            except RETRYABLE_EXCEPTIONS as e:
                if attempts >= MAX_RETRY_ATTEMPTS:
                    self._drop_count[family] += 1
                    self._maybe_warn(family)
                    logger.error(
                        "event_logger %s: dropped after %d retries: %s",
                        family, attempts, e,
                    )
                else:
                    self._enqueue(family, write_fn, attempts + 1, e)
            except Exception as e:
                self._drop_count[family] += 1
                self._maybe_warn(family)
                logger.error(
                    "event_logger %s: retry hit non-retryable error: %s",
                    family, e, exc_info=True,
                )
