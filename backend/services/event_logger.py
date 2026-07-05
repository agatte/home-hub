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

from sqlalchemy import select, text, update
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

    def __init__(self, camera_service=None, weather_service=None) -> None:
        # Optional camera_service reference for enrichment of activity_events
        # with zone/posture/lux at the moment of each mode transition. Late-
        # bind via set_camera_service when bootstrap order has the logger
        # constructed before the camera (current ordering — see bootstrap.py).
        self._camera_service = camera_service
        # Optional weather_service reference for enrichment of
        # light_adjustments with weather_class at adjustment time. Late-bound
        # via set_weather_service for the same boot-order reason.
        self._weather_service = weather_service
        self._presence_fusion = None
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
        # SourceTrust registry — gates camera enrichment. When the camera
        # source is untrusted (e.g. lux frozen), zone/posture/lux are written
        # NULL instead of the garbage values, so the predictor never trains on
        # poisoned features. None → fail-open (enrich as before).
        self._source_trust = None

    def set_heartbeat_registry(self, registry) -> None:
        """Inject the heartbeat registry (called from lifespan)."""
        self._heartbeat = registry

    def set_source_trust_registry(self, registry) -> None:
        """Inject the source-trust registry (called from lifespan)."""
        self._source_trust = registry

    def set_camera_service(self, camera_service) -> None:
        """Inject the camera service (called from lifespan after camera starts)."""
        self._camera_service = camera_service

    def set_weather_service(self, weather_service) -> None:
        """Inject the weather service (called from lifespan after weather starts)."""
        self._weather_service = weather_service

    def set_presence_fusion(self, presence_fusion) -> None:
        """Inject PresenceFusion for light-adjustment context enrichment."""
        self._presence_fusion = presence_fusion

    def _resolve_weather_class(self) -> Optional[str]:
        """Return classify_for_bandit() of the cached observation, or None.

        Mirrors MusicMapper._current_weather_class but folds the WEATHER_ANY
        sentinel back to None so log_light_adjustment can write NULL into
        the DB column when no observation is available yet (retrain folds
        NULL → "any" — see backend.services.ml.weather_class).
        """
        if not self._weather_service:
            return None
        try:
            from backend.services.weather_class import (
                WEATHER_ANY, classify_for_bandit,
            )
            weather = self._weather_service.get_cached()
            cls = classify_for_bandit(weather)
            return None if cls == WEATHER_ANY else cls
        except Exception:
            return None

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

        Enrichment: snapshots camera zone/posture/lux and looks up the most
        recent audio_ml class within the last 60 seconds. All four are frozen
        at call time so retries log the context as it was during the transition,
        not as it is at retry time.
        """
        captured_now = datetime.now(timezone.utc)
        zone, posture, lux = self._snapshot_camera_state()
        audio_class = await self._lookup_recent_audio_class()

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
                zone=zone,
                posture=posture,
                audio_class=audio_class,
                lux=lux,
            ))

        await self._write("mode", _write)

    def _snapshot_camera_state(self) -> tuple[Optional[str], Optional[str], Optional[float]]:
        """Read current zone/posture/lux from the camera service, tolerating
        a missing service or a service whose properties happen to raise.
        Returns ``(None, None, None)`` if anything goes wrong — enrichment is
        best-effort, never blocks the write path.
        """
        cs = self._camera_service
        if cs is None:
            return None, None, None
        # Source-trust gate: an untrusted camera (lux variance collapse, etc.)
        # must not poison the predictor's training features. Drop enrichment to
        # NULLs for the untrusted window rather than baking in garbage — this
        # is the boundary that would have stopped the 2026-05-27 lux pin from
        # poisoning watching-class accuracy for five days. The transition row
        # itself is still written; only the camera-derived fields go NULL.
        if self._source_trust is not None:
            try:
                if not self._source_trust.verdict("camera").get("trusted", True):
                    return None, None, None
            except Exception:  # never block the write path on the gate
                pass
        try:
            return (
                getattr(cs, "zone", None),
                getattr(cs, "posture", None),
                getattr(cs, "ema_lux", None),
            )
        except Exception:  # pragma: no cover — defensive
            return None, None, None

    async def _lookup_recent_audio_class(self) -> Optional[str]:
        """Return the top_class from the most recent audio_ml ml_decisions
        row within the last 60 seconds, or None if no such row exists or the
        query fails. Best-effort — never raises.
        """
        try:
            async with async_session() as session:
                result = await session.execute(text("""
                    SELECT json_extract(factors, '$.top_class')
                    FROM ml_decisions
                    WHERE decision_source = 'audio_ml'
                      AND timestamp >= datetime('now', '-60 seconds')
                    ORDER BY timestamp DESC
                    LIMIT 1
                """))
                row = result.fetchone()
                return row[0] if row else None
        except Exception:
            return None

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
        weather_class: Optional[str] = None,
        zone_at_time: Optional[str] = None,
        posture_at_time: Optional[str] = None,
    ) -> None:
        """Record a light change issued from the dashboard or an API client.

        ``weather_class`` (clear / clouds / rain / thunderstorm / snow /
        golden_hour) captured at adjustment time enables the LightingLearner
        weather-aware retrain. NULL when the weather service hasn't polled
        yet or the caller didn't pass it — retrain folds those rows into
        the "any" bucket.
        """
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

        if weather_class is None:
            weather_class = self._resolve_weather_class()
        if zone_at_time is None and posture_at_time is None:
            zone_at_time, posture_at_time = self._snapshot_presence_context()

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
                zone_at_time=zone_at_time,
                posture_at_time=posture_at_time,
                trigger=trigger,
                weather_class=weather_class,
            ))

        await self._write("light", _write)

    def _snapshot_presence_context(self) -> tuple[Optional[str], Optional[str]]:
        """Read current fused zone/posture for light-adjustment learning."""
        presence = self._presence_fusion
        if presence is None:
            return None, None
        try:
            return presence.latest_zone(), presence.latest_posture()
        except Exception:  # pragma: no cover - defensive enrichment path
            return None, None

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
        weather_class: Optional[str] = None,
    ) -> None:
        """Record a Sonos playback event.

        ``weather_class`` (Phase B, 2026-05-12) is captured at log time so
        the music bandit's nightly retrain can rebuild weather-aware arms
        across 90 days of history. Callers that don't supply it leave the
        column NULL; retrain treats NULL rows as WEATHER_ANY.
        """
        async def _write(session) -> None:
            session.add(SonosPlaybackEvent(
                event_type=event_type,
                favorite_title=favorite_title,
                mode_at_time=mode_at_time,
                volume=volume,
                triggered_by=triggered_by,
                weather_class=weather_class,
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
