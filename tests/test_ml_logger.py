"""
Tests for MLDecisionLogger — DB writes, broadcast, accuracy, override rate.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.models import ActivityEvent, MLDecision
from backend.services.ml.ml_logger import MLDecisionLogger


@pytest.fixture
def logger(mock_ws):
    return MLDecisionLogger(ws_manager=mock_ws)


@pytest.mark.asyncio
class TestLogDecision:
    async def test_writes_row(self, logger, ml_db):
        decision_id = await logger.log_decision(
            predicted_mode="working",
            confidence=0.92,
            decision_source="fusion",
            factors={"why": "test"},
            applied=True,
        )
        assert decision_id is not None
        async with ml_db() as session:
            result = await session.execute(select(MLDecision))
            rows = result.scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.predicted_mode == "working"
        assert row.confidence == 0.92
        assert row.decision_source == "fusion"
        assert row.factors == {"why": "test"}
        assert row.applied is True

    async def test_broadcast_true_emits_ws(self, logger, ml_db, mock_ws):
        await logger.log_decision(
            predicted_mode="working", confidence=0.8,
            decision_source="ml", broadcast=True,
        )
        assert any(t == "ml_decision" for t, _ in mock_ws.broadcasts)

    async def test_broadcast_false_no_ws(self, logger, ml_db, mock_ws):
        await logger.log_decision(
            predicted_mode="working", confidence=0.8,
            decision_source="ml", broadcast=False,
        )
        assert not mock_ws.broadcasts

    async def test_applied_false_still_recorded(self, logger, ml_db):
        await logger.log_decision(
            predicted_mode="relax", confidence=0.5,
            decision_source="rule", applied=False, broadcast=False,
        )
        async with ml_db() as session:
            result = await session.execute(select(MLDecision))
            row = result.scalar_one()
        assert row.applied is False


@pytest.mark.asyncio
class TestOnModeChange:
    async def test_first_call_records_no_backfill(self, logger, ml_db):
        # No prior _last_mode → backfill skipped, just records state.
        await logger.on_mode_change("working")
        assert logger._last_mode == "working"
        assert logger._last_transition_at is not None

    async def test_second_call_backfills_window(self, logger, ml_db):
        # First on_mode_change establishes the session start. Decision rows
        # written AFTER this point are inside the window the next call will
        # backfill.
        await logger.on_mode_change("working")

        await logger.log_decision(
            predicted_mode="working", confidence=0.9,
            decision_source="fusion", broadcast=False,
        )
        await logger.log_decision(
            predicted_mode="gaming", confidence=0.6,
            decision_source="fusion", broadcast=False,
        )

        # Second backfills "working" onto rows in the window.
        await logger.on_mode_change("gaming")

        async with ml_db() as session:
            result = await session.execute(select(MLDecision))
            rows = result.scalars().all()
        # Both rows should now carry actual_mode='working'.
        assert all(r.actual_mode == "working" for r in rows)


@pytest.mark.asyncio
class TestBackfillActualRange:
    async def test_only_updates_rows_since_cutoff(self, logger, ml_db):
        """A row older than `since` and the 2h cap stays NULL."""
        old = datetime.now(timezone.utc) - timedelta(hours=5)
        recent = datetime.now(timezone.utc) - timedelta(minutes=10)
        async with ml_db() as session:
            session.add(MLDecision(
                timestamp=old, predicted_mode="working", confidence=0.8,
                decision_source="fusion", applied=True,
            ))
            session.add(MLDecision(
                timestamp=recent, predicted_mode="gaming", confidence=0.7,
                decision_source="fusion", applied=True,
            ))
            await session.commit()

        n = await logger.backfill_actual_range(
            "working", since=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        assert n == 1

        async with ml_db() as session:
            result = await session.execute(
                select(MLDecision).order_by(MLDecision.timestamp.asc())
            )
            rows = result.scalars().all()
        assert rows[0].actual_mode is None  # old row untouched
        assert rows[1].actual_mode == "working"


@pytest.mark.asyncio
class TestGetRecent:
    async def test_returns_descending_limited(self, logger, ml_db):
        for i in range(5):
            await logger.log_decision(
                predicted_mode=f"mode{i}", confidence=0.5,
                decision_source="ml", broadcast=False,
            )
        rows = await logger.get_recent(limit=3)
        assert len(rows) == 3
        # Most recent first — last inserted has highest id.
        assert rows[0]["predicted_mode"] == "mode4"


@pytest.mark.asyncio
class TestComputeAccuracy:
    async def test_known_set(self, logger, ml_db):
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            # 3 correct, 1 wrong, 1 unfilled.
            for predicted, actual in [
                ("working", "working"),
                ("working", "working"),
                ("gaming", "gaming"),
                ("relax", "watching"),
            ]:
                session.add(MLDecision(
                    timestamp=now - timedelta(hours=1),
                    predicted_mode=predicted, actual_mode=actual,
                    confidence=0.9, decision_source="fusion", applied=True,
                ))
            session.add(MLDecision(
                timestamp=now - timedelta(hours=1),
                predicted_mode="working", actual_mode=None,
                confidence=0.9, decision_source="fusion", applied=True,
            ))
            await session.commit()

        result = await logger.compute_accuracy(days=7)
        assert result["total"] == 4
        assert result["correct"] == 3
        assert result["accuracy"] == pytest.approx(0.75)


@pytest.mark.asyncio
class TestComputeAccuracyBySource:
    async def test_per_signal_breakdown(self, logger, ml_db):
        now = datetime.now(timezone.utc)
        # Two fusion rows: process voted right both times, camera voted
        # right once and wrong once.
        async with ml_db() as session:
            session.add(MLDecision(
                timestamp=now - timedelta(hours=1),
                predicted_mode="working", actual_mode="working",
                confidence=0.9, decision_source="fusion", applied=True,
                factors={"signal_details": {
                    "process": {"mode": "working", "stale": False},
                    "camera": {"mode": "working", "stale": False},
                }},
            ))
            session.add(MLDecision(
                timestamp=now - timedelta(hours=1),
                predicted_mode="gaming", actual_mode="gaming",
                confidence=0.8, decision_source="fusion", applied=True,
                factors={"signal_details": {
                    "process": {"mode": "gaming", "stale": False},
                    "camera": {"mode": "relax", "stale": False},
                }},
            ))
            await session.commit()

        result = await logger.compute_accuracy_by_source(days=14)
        assert result["process"] == pytest.approx(1.0)
        assert result["camera"] == pytest.approx(0.5)


@pytest.mark.asyncio
class TestComputeOverrideRate:
    async def test_shape_with_seeded_events(self, logger, ml_db):
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            # One auto event then a manual override 1 minute later.
            session.add(ActivityEvent(
                timestamp=now - timedelta(minutes=10),
                mode="working", source="automation",
            ))
            session.add(ActivityEvent(
                timestamp=now - timedelta(minutes=9),
                mode="relax", source="manual",
            ))
            # Cold manual switch hours later — no prior in 5min window.
            session.add(ActivityEvent(
                timestamp=now - timedelta(hours=2),
                mode="gaming", source="manual",
            ))
            await session.commit()

        result = await logger.compute_override_rate(days=1, window_minutes=5)
        for key in (
            "total_manual", "overrides", "cold_switches",
            "overrides_per_day", "window_minutes", "window_days",
        ):
            assert key in result
        assert result["total_manual"] == 2
        assert result["overrides"] == 1
        assert result["cold_switches"] == 1
