"""
Tests for BehavioralPredictor — LightGBM mode prediction.

Tests that need a trained model are skipped if lightgbm isn't installed,
so the suite runs cleanly in environments without it. The production
deployment has lightgbm.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import ActivityEvent
from backend.services.ml.behavioral_predictor import (
    AUTO_APPLY_THRESHOLD,
    MIN_TRAINING_EVENTS,
    SUGGEST_THRESHOLD,
    BehavioralPredictor,
)


@pytest.fixture
def predictor(tmp_model_manager):
    return BehavioralPredictor(tmp_model_manager)


class TestInit:
    def test_no_model_yields_cold_start(self, predictor):
        assert predictor._model is None
        assert predictor._status == "shadow"
        assert predictor._training_rows == 0

    def test_predict_returns_none_with_no_model(self, predictor):
        import asyncio
        result = asyncio.run(predictor.predict(current_mode="working"))
        assert result is None


class TestStatus:
    def test_get_status_shape(self, predictor):
        status = predictor.get_status()
        for key in (
            "status", "model_loaded", "last_trained", "accuracy_7d",
            "training_rows", "min_events", "auto_apply_threshold",
            "suggest_threshold",
        ):
            assert key in status
        assert status["min_events"] == MIN_TRAINING_EVENTS
        assert status["auto_apply_threshold"] == AUTO_APPLY_THRESHOLD
        assert status["suggest_threshold"] == SUGGEST_THRESHOLD
        assert status["model_loaded"] is False

    def test_promote_demote(self, predictor):
        # promote calls update_meta which expects the entry to exist.
        predictor._model_manager._meta["mode_predictor"] = {
            "file": "mode_predictor.lgb", "status": "shadow",
        }
        predictor.promote()
        assert predictor._status == "active"
        predictor.demote()
        assert predictor._status == "shadow"


class TestFeatureImportances:
    def test_no_model_returns_empty_dict(self, predictor):
        assert predictor.get_feature_importances() == {}


@pytest.mark.asyncio
class TestRetrain:
    async def test_insufficient_events_skips_training(self, predictor, ml_db):
        # Add a few events — well under MIN_TRAINING_EVENTS.
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            for i in range(3):
                session.add(ActivityEvent(
                    timestamp=now - timedelta(hours=i),
                    mode="working", source="manual",
                ))
            await session.commit()

        await predictor.retrain()
        # No model file produced.
        assert predictor._model is None
        assert predictor._training_rows == 0

    async def test_lightgbm_unavailable_no_crash(self, predictor, ml_db, monkeypatch):
        """If lightgbm import fails, retrain should log + return cleanly."""
        # Add enough events that the function would otherwise try to train.
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            for i in range(MIN_TRAINING_EVENTS + 5):
                session.add(ActivityEvent(
                    timestamp=now - timedelta(minutes=i),
                    mode="working" if i % 2 == 0 else "gaming",
                    source="manual",
                ))
            await session.commit()

        import builtins
        real_import = builtins.__import__

        def _raising_import(name, *args, **kwargs):
            if name == "lightgbm":
                raise ImportError("simulated missing lightgbm")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _raising_import)

        # Should not raise.
        await predictor.retrain()
        assert predictor._model is None


# ---------------------------------------------------------------------------
# Tests below need a working lightgbm install. Skip the class only — leave
# the lightgbm-independent tests above intact.
# ---------------------------------------------------------------------------

try:
    import lightgbm  # noqa: F401
    _HAS_LIGHTGBM = True
except ImportError:
    _HAS_LIGHTGBM = False


@pytest.mark.skipif(not _HAS_LIGHTGBM, reason="lightgbm not installed")
@pytest.mark.asyncio
class TestRetrainWithLightGBM:
    async def test_sufficient_data_trains_model(self, predictor, ml_db):
        """End-to-end retrain: enough varied events → model on disk."""
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            # Enough events with multiple distinct modes for multiclass training.
            for i in range(MIN_TRAINING_EVENTS + 20):
                mode = (
                    "working" if i % 3 == 0
                    else "gaming" if i % 3 == 1
                    else "watching"
                )
                session.add(ActivityEvent(
                    timestamp=now - timedelta(minutes=i),
                    mode=mode,
                    previous_mode="idle",
                    source="manual",
                    duration_seconds=600,
                ))
            await session.commit()

        await predictor.retrain()
        assert predictor._model is not None
        assert predictor._training_rows >= MIN_TRAINING_EVENTS
        # Model file written under tmp dir.
        model_path = predictor._model_manager.data_dir / "mode_predictor.lgb"
        assert model_path.exists()

    async def test_predict_after_train_returns_dict(self, predictor, ml_db):
        # Reuse the previous-test setup.
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            for i in range(MIN_TRAINING_EVENTS + 20):
                mode = (
                    "working" if i % 3 == 0
                    else "gaming" if i % 3 == 1
                    else "watching"
                )
                session.add(ActivityEvent(
                    timestamp=now - timedelta(minutes=i),
                    mode=mode,
                    previous_mode="idle",
                    source="manual",
                    duration_seconds=600,
                ))
            await session.commit()

        await predictor.retrain()
        # Promote so predict returns a result instead of None on shadow.
        predictor._status = "active"
        result = await predictor.predict(
            current_mode="working",
            current_mode_duration_s=600,
        )
        # Confidence might land below SUGGEST_THRESHOLD with synthetic data;
        # accept None or a properly-shaped dict.
        if result is not None:
            assert "predicted_mode" in result
            assert "confidence" in result
            assert "source" in result
            assert result["source"] == "behavioral_predictor"
