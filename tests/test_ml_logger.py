"""
Tests for MLDecisionLogger — DB writes, broadcast, accuracy, override rate.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.models import ActivityEvent, MLDecision, MLMetric
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
class TestComputePerSourceMetrics:
    """Richer view of per-source accuracy with sample + correct counts."""

    async def test_returns_accuracy_samples_correct(self, logger, ml_db):
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            # 2 fusion rows. process: 2/2 correct. camera: 1/2 correct.
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

        rich = await logger.compute_per_source_metrics(days=14)
        assert rich["process"] == {
            "accuracy": pytest.approx(1.0),
            "samples": 2,
            "correct": 2,
        }
        assert rich["camera"] == {
            "accuracy": pytest.approx(0.5),
            "samples": 2,
            "correct": 1,
        }

    async def test_legacy_wrapper_still_returns_flat_dict(self, logger, ml_db):
        """compute_accuracy_by_source must remain a flat {src: float} dict
        so update_weights_from_accuracy and /retune-weights keep working."""
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            session.add(MLDecision(
                timestamp=now - timedelta(hours=1),
                predicted_mode="working", actual_mode="working",
                confidence=0.9, decision_source="fusion", applied=True,
                factors={"signal_details": {
                    "process": {"mode": "working", "stale": False},
                }},
            ))
            await session.commit()

        flat = await logger.compute_accuracy_by_source(days=14)
        assert flat == {"process": pytest.approx(1.0)}


@pytest.mark.asyncio
class TestPersistAccuracyMetrics:
    """Nightly persistence of per-source accuracy into ml_metrics."""

    async def test_writes_one_row_per_source(self, logger, ml_db):
        metrics = {
            "process": {"accuracy": 0.91, "samples": 200, "correct": 182},
            "camera": {"accuracy": 0.42, "samples": 195, "correct": 82},
            "audio_ml": {"accuracy": 0.55, "samples": 180, "correct": 99},
        }
        n = await logger.persist_accuracy_metrics(metrics, window_days=14)
        assert n == 3

        async with ml_db() as session:
            rows = (await session.execute(
                select(MLMetric).order_by(MLMetric.metric_name)
            )).scalars().all()

        assert len(rows) == 3
        names = [r.metric_name for r in rows]
        assert names == ["accuracy_audio_ml", "accuracy_camera", "accuracy_process"]
        camera = next(r for r in rows if r.metric_name == "accuracy_camera")
        assert camera.value == pytest.approx(0.42)
        assert camera.extra == {
            "samples": 195, "correct": 82, "window_days": 14,
        }
        assert camera.date == datetime.now(timezone.utc).date()

    async def test_idempotent_on_repeat_call(self, logger, ml_db):
        """Running twice in the same UTC day must leave one row per source,
        not two — delete-then-insert handles re-runs cleanly."""
        first = {
            "process": {"accuracy": 0.80, "samples": 100, "correct": 80},
            "camera": {"accuracy": 0.50, "samples": 100, "correct": 50},
        }
        second = {
            "process": {"accuracy": 0.85, "samples": 110, "correct": 93},
            "camera": {"accuracy": 0.55, "samples": 110, "correct": 60},
        }

        await logger.persist_accuracy_metrics(first, window_days=14)
        await logger.persist_accuracy_metrics(second, window_days=14)

        async with ml_db() as session:
            rows = (await session.execute(select(MLMetric))).scalars().all()

        assert len(rows) == 2
        process = next(r for r in rows if r.metric_name == "accuracy_process")
        # Second call's value should win.
        assert process.value == pytest.approx(0.85)
        assert process.extra["samples"] == 110

    async def test_empty_metrics_writes_nothing(self, logger, ml_db):
        n = await logger.persist_accuracy_metrics({})
        assert n == 0
        async with ml_db() as session:
            rows = (await session.execute(select(MLMetric))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
class TestComputePredictionDiversity:
    async def _seed(self, ml_db, mode_counts: dict, days_old: float = 0.5):
        """Seed `decision_source='ml'` rows with the given mode distribution."""
        ts = datetime.now(timezone.utc) - timedelta(days=days_old)
        async with ml_db() as session:
            for mode, n in mode_counts.items():
                for _ in range(n):
                    session.add(MLDecision(
                        timestamp=ts,
                        predicted_mode=mode,
                        confidence=0.9,
                        decision_source="ml",
                        applied=False,
                    ))
            await session.commit()

    async def test_no_predictions_blocks(self, logger, ml_db):
        result = await logger.compute_prediction_diversity()
        assert result["diverse"] is False
        assert result["reason"] == "no_predictions"
        assert result["total"] == 0

    async def test_insufficient_samples_blocks(self, logger, ml_db):
        await self._seed(ml_db, {"working": 10, "gaming": 5})
        result = await logger.compute_prediction_diversity(min_samples=50)
        assert result["diverse"] is False
        assert result["reason"] == "insufficient_samples"
        assert result["total"] == 15
        assert result["unique_modes"] == 2

    async def test_single_class_blocks(self, logger, ml_db):
        # Reproduces the 4/27 single-class collapse pattern.
        await self._seed(ml_db, {"working": 60})
        result = await logger.compute_prediction_diversity()
        assert result["diverse"] is False
        assert result["reason"] == "single_class"
        assert result["unique_modes"] == 1
        assert result["top_mode_share"] == 1.0

    async def test_near_single_class_blocks(self, logger, ml_db):
        # 96% one mode, 4% another → still degenerate.
        await self._seed(ml_db, {"working": 96, "idle": 4})
        result = await logger.compute_prediction_diversity()
        assert result["diverse"] is False
        assert result["reason"] == "near_single_class"
        assert result["top_mode_share"] == pytest.approx(0.96)

    async def test_diverse_passes(self, logger, ml_db):
        await self._seed(ml_db, {
            "working": 40, "gaming": 20, "watching": 25, "idle": 15,
        })
        result = await logger.compute_prediction_diversity()
        assert result["diverse"] is True
        assert result["reason"] == "ok"
        assert result["unique_modes"] == 4
        assert result["total"] == 100

    async def test_window_excludes_stale_rows(self, logger, ml_db):
        # 40 rows from 30 days ago — outside the 7d default window.
        await self._seed(ml_db, {"working": 40}, days_old=30)
        result = await logger.compute_prediction_diversity(days=7)
        assert result["diverse"] is False
        assert result["reason"] == "no_predictions"

    async def test_other_decision_sources_ignored(self, logger, ml_db):
        # Fusion rows with diverse predictions don't unblock the predictor gate.
        ts = datetime.now(timezone.utc) - timedelta(hours=1)
        async with ml_db() as session:
            for mode in ("working", "gaming", "watching", "relax", "idle"):
                for _ in range(20):
                    session.add(MLDecision(
                        timestamp=ts,
                        predicted_mode=mode,
                        confidence=0.9,
                        decision_source="fusion",
                        applied=True,
                    ))
            await session.commit()
        result = await logger.compute_prediction_diversity()
        assert result["diverse"] is False
        assert result["reason"] == "no_predictions"


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
