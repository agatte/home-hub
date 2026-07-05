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
    # log_mode_change now opens two sessions per call: one for the audio_class
    # lookup (failures are swallowed silently — best-effort enrichment) and
    # one for the actual write. fail_times=2 makes both fail on the first
    # call so the write enqueues; the drain's session call then succeeds.
    cm, state = _failing_then_succeeding_session(fail_times=2)
    el = EventLogger()

    with patch.object(event_logger_module, "async_session", cm):
        await el.log_mode_change(mode="working", previous_mode="idle", source="test")
        # First write failed → queued, no drop yet.
        assert el.get_drop_counts()["mode"] == 0
        assert el.get_queue_depth() == 1

        # Drive one drain cycle manually — third async_session() call succeeds.
        await el._drain_once()

        assert el.get_queue_depth() == 0
        assert el.get_drop_counts()["mode"] == 0
        assert state["calls"] == 3
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




class _FakePresenceFusion:
    def __init__(self, zone=None, posture=None) -> None:
        self._zone = zone
        self._posture = posture

    def latest_zone(self):
        return self._zone

    def latest_posture(self):
        return self._posture


@pytest.mark.asyncio
async def test_log_light_adjustment_enriches_with_presence_context(ml_db):
    """Manual light rows carry fused zone/posture for zone-aware learning."""
    from sqlalchemy import select as sa_select

    from backend.models import LightAdjustment

    el = EventLogger()
    el.set_presence_fusion(_FakePresenceFusion(zone="desk", posture="upright"))

    await el.log_light_adjustment(
        light_id="2",
        bri_before=40,
        bri_after=70,
        mode_at_time="watching",
        trigger="ws",
    )

    async with ml_db() as session:
        row = (await session.execute(sa_select(LightAdjustment))).scalar_one()
    assert row.zone_at_time == "desk"
    assert row.posture_at_time == "upright"

# ---------------------------------------------------------------------------
# Enrichment — camera + audio context on activity_events rows
# ---------------------------------------------------------------------------

class _FakeCameraService:
    """Stand-in for CameraService — exposes the three properties EventLogger reads."""

    def __init__(self, zone=None, posture=None, ema_lux=None) -> None:
        self.zone = zone
        self.posture = posture
        self.ema_lux = ema_lux


@pytest.mark.asyncio
async def test_log_mode_change_enriches_with_camera_state(ml_db):
    """zone/posture/lux from the camera service land on the new ActivityEvent row."""
    from sqlalchemy import select as sa_select

    from backend.models import ActivityEvent

    cam = _FakeCameraService(zone="bed", posture="reclined", ema_lux=42.5)
    el = EventLogger(camera_service=cam)

    await el.log_mode_change(mode="relax", previous_mode="working", source="manual")

    async with ml_db() as session:
        rows = (await session.execute(sa_select(ActivityEvent))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.mode == "relax"
    assert row.zone == "bed"
    assert row.posture == "reclined"
    assert row.lux == 42.5
    assert row.audio_class is None  # No audio_ml row seeded


@pytest.mark.asyncio
async def test_log_mode_change_enriches_with_recent_audio_class(ml_db):
    """audio_class pulls top_class from the most recent audio_ml ml_decisions row."""
    from sqlalchemy import select as sa_select

    from backend.models import ActivityEvent, MLDecision

    # Seed a recent audio_ml decision — uses SQL-side `datetime('now')` default.
    async with ml_db() as session:
        session.add(MLDecision(
            predicted_mode="silence",
            applied=False,
            confidence=0.92,
            decision_source="audio_ml",
            factors={"top_class": "speech_single", "rms_avg": 0.18},
        ))
        await session.commit()

    el = EventLogger()  # No camera_service — tests the audio path in isolation
    await el.log_mode_change(mode="working", previous_mode="idle", source="process")

    async with ml_db() as session:
        rows = (await session.execute(sa_select(ActivityEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].audio_class == "speech_single"
    assert rows[0].zone is None
    assert rows[0].posture is None
    assert rows[0].lux is None


@pytest.mark.asyncio
async def test_log_mode_change_audio_lookup_ignores_stale_rows(ml_db):
    """audio_ml rows older than 60s must not leak into the new event's audio_class."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select as sa_select

    from backend.models import ActivityEvent, MLDecision

    stale = datetime.now(timezone.utc) - timedelta(seconds=120)
    async with ml_db() as session:
        session.add(MLDecision(
            timestamp=stale,
            predicted_mode="silence",
            applied=False,
            confidence=0.9,
            decision_source="audio_ml",
            factors={"top_class": "music"},
        ))
        await session.commit()

    el = EventLogger()
    await el.log_mode_change(mode="cooking", previous_mode="idle", source="manual")

    async with ml_db() as session:
        rows = (await session.execute(sa_select(ActivityEvent))).scalars().all()
    assert rows[0].audio_class is None  # Stale row ignored


class _FakeWeatherService:
    """Stand-in for WeatherService — only get_cached() is consumed."""

    def __init__(self, weather=None) -> None:
        self._weather = weather

    def get_cached(self):
        return self._weather


@pytest.mark.asyncio
async def test_log_light_adjustment_captures_weather_class(ml_db):
    """A wired weather_service populates the new weather_class column."""
    from sqlalchemy import select as sa_select

    from backend.models import LightAdjustment

    weather = _FakeWeatherService(
        weather={"description": "Thunderstorms in vicinity"},
    )
    el = EventLogger(weather_service=weather)
    await el.log_light_adjustment(
        light_id="1", bri_before=100, bri_after=180,
        mode_at_time="gaming", trigger="ws",
    )
    async with ml_db() as session:
        rows = (await session.execute(sa_select(LightAdjustment))).scalars().all()
    assert len(rows) == 1
    assert rows[0].weather_class == "thunderstorm"


@pytest.mark.asyncio
async def test_log_light_adjustment_no_weather_service_writes_null(ml_db):
    """Without a wired weather_service, weather_class is None (DB NULL)."""
    from sqlalchemy import select as sa_select

    from backend.models import LightAdjustment

    el = EventLogger()  # no weather_service
    await el.log_light_adjustment(
        light_id="1", bri_before=100, bri_after=200,
        mode_at_time="working", trigger="ws",
    )
    async with ml_db() as session:
        rows = (await session.execute(sa_select(LightAdjustment))).scalars().all()
    assert rows[0].weather_class is None


@pytest.mark.asyncio
async def test_log_light_adjustment_caller_weather_class_wins(ml_db):
    """When the caller passes weather_class explicitly, the service lookup
    is skipped — useful for synthetic / backfill calls."""
    from sqlalchemy import select as sa_select

    from backend.models import LightAdjustment

    weather = _FakeWeatherService(
        weather={"description": "Sunny and clear"},
    )
    el = EventLogger(weather_service=weather)
    await el.log_light_adjustment(
        light_id="1", bri_before=100, bri_after=180,
        weather_class="rain",  # explicit override
    )
    async with ml_db() as session:
        rows = (await session.execute(sa_select(LightAdjustment))).scalars().all()
    assert rows[0].weather_class == "rain"


@pytest.mark.asyncio
async def test_log_mode_change_camera_disabled_session_logs_none(ml_db):
    """Camera service present but properties returning None (disabled / not yet committed)
    stores None values rather than crashing or lying."""
    from sqlalchemy import select as sa_select

    from backend.models import ActivityEvent

    cam = _FakeCameraService(zone=None, posture=None, ema_lux=None)
    el = EventLogger(camera_service=cam)

    await el.log_mode_change(mode="working", previous_mode="idle", source="process")

    async with ml_db() as session:
        rows = (await session.execute(sa_select(ActivityEvent))).scalars().all()
    assert rows[0].zone is None
    assert rows[0].posture is None
    assert rows[0].lux is None


@pytest.mark.asyncio
async def test_set_camera_service_late_bind_works(ml_db):
    """set_camera_service after construction (bootstrap order) wires correctly."""
    from sqlalchemy import select as sa_select

    from backend.models import ActivityEvent

    el = EventLogger()  # No camera at construction
    cam = _FakeCameraService(zone="desk", posture="upright", ema_lux=180.0)
    el.set_camera_service(cam)

    await el.log_mode_change(mode="working", previous_mode="idle", source="process")

    async with ml_db() as session:
        rows = (await session.execute(sa_select(ActivityEvent))).scalars().all()
    assert rows[0].zone == "desk"
    assert rows[0].posture == "upright"
    assert rows[0].lux == 180.0
