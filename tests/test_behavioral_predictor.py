"""
Tests for BehavioralPredictor — LightGBM mode prediction.

Tests that need a trained model are skipped if lightgbm isn't installed,
so the suite runs cleanly in environments without it. The production
deployment has lightgbm.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.config import settings
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


class TestStaleEncoder:
    """A saved label_encoder that targets retired modes (e.g. ``away``
    after 2026-04-27) must NOT be loaded — argmax could land on a class
    that no longer exists, and predictions would silently produce
    invalid mode strings.
    """

    def test_load_refuses_stale_encoder(self, tmp_model_manager, monkeypatch):
        # Pretend a prior training run saved a model with `away` in the
        # label encoder (a mode that's since been retired). Without the
        # gate, _load_existing would happily restore it.
        meta_path = tmp_model_manager.data_dir / "model_meta.json"
        model_path = tmp_model_manager.data_dir / "mode_predictor.lgb"
        # Need both an artifact on disk AND meta pointing to it. The
        # artifact contents don't matter — the staleness check fires
        # before we try to read the .lgb file.
        model_path.write_bytes(b"")
        tmp_model_manager._meta["mode_predictor"] = {
            "file": "mode_predictor.lgb",
            "status": "shadow",
            "label_encoder": {"0": "working", "1": "away"},
        }
        meta_path.write_text("{}")

        # Construct a fresh predictor — _load_existing runs in __init__.
        predictor = BehavioralPredictor(tmp_model_manager)
        assert predictor._model is None
        assert predictor._label_encoder == {}


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


class _StubMLLogger:
    """Minimal ml_logger stand-in that returns a fixed diversity dict.

    The real MLLogger queries ml_decisions; for the auto-demote unit
    tests we only care that the predictor reads the dict's
    ``diverse`` + ``reason`` fields and acts on them correctly.
    """

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls = 0

    async def compute_prediction_diversity(self, **_kwargs) -> dict:
        self.calls += 1
        return dict(self._payload)


@pytest.mark.asyncio
class TestAutoDemote:
    """check_and_demote_if_degenerate is the runtime counterpart to the
    /predictor/promote diversity gate. Same helper, opposite direction:
    flips ``active`` → ``shadow`` automatically when shadow predictions
    collapse, but never on missing-data signals (anti-flap)."""

    async def test_skipped_when_shadow(self, predictor):
        predictor._status = "shadow"
        ml_log = _StubMLLogger({"diverse": False, "reason": "near_single_class"})
        result = await predictor.check_and_demote_if_degenerate(ml_log)

        assert result["action"] == "skipped"
        assert result["reason"] == "not_active"
        assert predictor._status == "shadow"
        # We don't even ask the helper when status isn't active.
        assert ml_log.calls == 0

    async def test_kept_active_when_diverse(self, predictor):
        predictor._model_manager._meta["mode_predictor"] = {
            "file": "mode_predictor.lgb", "status": "shadow",
        }
        predictor.promote()
        ml_log = _StubMLLogger({
            "diverse": True, "reason": "ok",
            "total": 200, "unique_modes": 4, "top_mode_share": 0.42,
        })

        result = await predictor.check_and_demote_if_degenerate(ml_log)

        assert result["action"] == "kept_active"
        assert predictor._status == "active"

    async def test_kept_active_on_insufficient_samples(self, predictor):
        """Anti-flap: <50 samples must NOT auto-demote a freshly-promoted
        predictor. The diversity helper returns diverse=False for both
        collapse and "not enough data yet" — we have to distinguish."""
        predictor._model_manager._meta["mode_predictor"] = {
            "file": "mode_predictor.lgb", "status": "shadow",
        }
        predictor.promote()
        ml_log = _StubMLLogger({
            "diverse": False, "reason": "insufficient_samples",
            "total": 12, "min_samples": 50,
        })

        result = await predictor.check_and_demote_if_degenerate(ml_log)

        assert result["action"] == "kept_active"
        assert predictor._status == "active"

    async def test_kept_active_on_query_failed(self, predictor):
        predictor._model_manager._meta["mode_predictor"] = {
            "file": "mode_predictor.lgb", "status": "shadow",
        }
        predictor.promote()
        ml_log = _StubMLLogger({
            "diverse": False, "reason": "query_failed", "total": 0,
        })

        result = await predictor.check_and_demote_if_degenerate(ml_log)
        assert result["action"] == "kept_active"
        assert predictor._status == "active"

    async def test_demoted_on_near_single_class(self, predictor):
        predictor._model_manager._meta["mode_predictor"] = {
            "file": "mode_predictor.lgb", "status": "shadow",
        }
        predictor.promote()
        ml_log = _StubMLLogger({
            "diverse": False, "reason": "near_single_class",
            "total": 600, "unique_modes": 7, "top_mode_share": 0.98,
        })

        result = await predictor.check_and_demote_if_degenerate(ml_log)

        assert result["action"] == "auto_demoted"
        assert result["reason"] == "near_single_class"
        assert predictor._status == "shadow"
        # Persisted status flip.
        assert predictor._model_manager._meta["mode_predictor"]["status"] == "shadow"

    async def test_demoted_on_single_class(self, predictor):
        predictor._model_manager._meta["mode_predictor"] = {
            "file": "mode_predictor.lgb", "status": "shadow",
        }
        predictor.promote()
        ml_log = _StubMLLogger({
            "diverse": False, "reason": "single_class",
            "total": 800, "unique_modes": 1, "top_mode_share": 1.0,
        })

        result = await predictor.check_and_demote_if_degenerate(ml_log)

        assert result["action"] == "auto_demoted"
        assert predictor._status == "shadow"


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
class TestStaleFeatureCount:
    """A saved model whose feature count no longer matches FEATURE_COLUMNS
    must be refused on load — predict() would crash with a length mismatch
    on the input vector. The 04:00 nightly retrain rebuilds against the
    current FEATURE_COLUMNS, so dropping the model is graceful.

    Unlike TestStaleEncoder, the empty-bytes trick won't work here — the
    feature-count check runs AFTER lgb.Booster() parses the file, so we
    need a real saved model with the wrong feature count.
    """

    def test_load_refuses_stale_feature_count(self, tmp_model_manager):
        import lightgbm as lgb
        import numpy as np

        # Train a tiny 10-feature booster — the pre-2026-05-04 shape.
        rng = np.random.default_rng(0)
        x = rng.random((50, 10))
        y = rng.integers(0, 3, size=50)
        ds = lgb.Dataset(x, label=y)
        booster = lgb.train(
            {"objective": "multiclass", "num_class": 3, "verbose": -1},
            ds,
            num_boost_round=2,
        )

        model_path = tmp_model_manager.data_dir / "mode_predictor.lgb"
        booster.save_model(str(model_path))
        tmp_model_manager._meta["mode_predictor"] = {
            "file": "mode_predictor.lgb",
            "status": "shadow",
            "label_encoder": {"0": "working", "1": "gaming", "2": "watching"},
        }

        predictor = BehavioralPredictor(tmp_model_manager)
        assert predictor._model is None
        # Predict path returns None cleanly while we wait for retrain.
        import asyncio
        assert asyncio.run(predictor.predict(current_mode="working")) is None


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
        result = await predictor.predict(current_mode="working")
        # Confidence might land below SUGGEST_THRESHOLD with synthetic data;
        # accept None or a properly-shaped dict.
        if result is not None:
            assert "predicted_mode" in result
            assert "confidence" in result
            assert "source" in result
            assert result["source"] == "behavioral_predictor"
            # factors carries both the feature echo and the full-class
            # softmax distribution after the 2026-04-28 plumbing change.
            factors = result["factors"]
            assert isinstance(factors, dict)
            assert "features" in factors
            assert "distribution" in factors
            assert isinstance(factors["distribution"], dict)
            # distribution should sum to ~1.0 across all classes.
            assert abs(sum(factors["distribution"].values()) - 1.0) < 1e-3


@pytest.mark.skipif(not _HAS_LIGHTGBM, reason="lightgbm not installed")
@pytest.mark.asyncio
class TestClassImbalance:
    """Sqrt-softened class weights must give minority classes enough lift
    that the model emits more than a single class. 2026-05-11 weekly
    evaluator caught gaming starvation: 0 predictions over 7d despite 70
    actual hits. With 80/20 imbalance and discriminative features the
    minority class should at least surface in the distribution.
    """

    async def test_minority_class_survives_imbalance(
        self, predictor, ml_db, monkeypatch,
    ):
        local_tz = ZoneInfo(settings.TIMEZONE)
        base_local = datetime.now(local_tz).replace(
            hour=12, minute=0, second=0, microsecond=0,
        )
        async with ml_db() as session:
            # 80/20 working/gaming, held inside the 60d training window.
            # Gaming is explicitly concentrated at local 22:00-23:00 so
            # the temporal features can discriminate after lux was removed.
            for i in range(1000):
                day_offset = i // 25
                if i % 5 == 0:
                    mode = "gaming"
                    ts_local = (
                        base_local - timedelta(days=day_offset)
                    ).replace(hour=22 + (i % 2))
                    audio_class = "game_audio"
                else:
                    mode = "working"
                    ts_local = (
                        base_local - timedelta(days=day_offset)
                    ).replace(hour=9 + (i % 8))
                    audio_class = "speech_single"
                ts = ts_local.astimezone(timezone.utc)
                session.add(ActivityEvent(
                    timestamp=ts, mode=mode, previous_mode="idle",
                    source="manual", duration_seconds=600,
                    zone="desk", posture="upright", audio_class=audio_class,
                ))
            await session.commit()

        await predictor.retrain()
        assert predictor._model is not None

        # Trainer must have surfaced at least 2 classes in its encoder.
        modes_seen = set(predictor._label_encoder.values())
        assert "gaming" in modes_seen, (
            f"Expected gaming in label encoder, got {modes_seen}"
        )

        # Per-class predicted count is the relevant log field; spot-check
        # the distribution from a known gaming-shaped feature vector. The
        # old fixture called predict() with the live wall clock, so a
        # full-suite run could ask the model about a working-shaped "now"
        # even though the test intended to inspect late-night gaming.
        from backend.services.ml.feature_builder import build_training_data
        import backend.services.ml.behavioral_predictor as predictor_module

        rows = await build_training_data(days=60)
        gaming_features = next(r for r in rows if r["target"] == "gaming")
        gaming_features = {
            k: v for k, v in gaming_features.items() if k != "target"
        }

        async def _gaming_runtime_features(*args, **kwargs):
            return gaming_features

        monkeypatch.setattr(
            predictor_module, "build_runtime_features", _gaming_runtime_features,
        )
        predictor._status = "active"
        result = await predictor.predict(current_mode="working")
        if result is not None:
            dist = result["factors"]["distribution"]
            # Either gaming is the top prediction, or it has ≥ 5% mass —
            # both are huge improvements over the 0-prediction baseline.
            assert dist.get("gaming", 0.0) >= 0.05 or (
                result["predicted_mode"] == "gaming"
            ), f"Gaming starved in distribution: {dist}"


@pytest.mark.skipif(not _HAS_LIGHTGBM, reason="lightgbm not installed")
@pytest.mark.asyncio
class TestCalibration:
    """Isotonic post-fit calibration: addresses the 2026-05-11 conf=1.0
    inversion (top-bucket accuracy below conf=0.9). Verify the wiring
    persists and reloads cleanly — the empirical calibration quality is
    validated weekly by the ML evaluator on prod data, not here.
    """

    async def test_calibrators_persisted_on_retrain(self, predictor, ml_db):
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            for i in range(MIN_TRAINING_EVENTS + 50):
                mode = (
                    "working" if i % 3 == 0
                    else "gaming" if i % 3 == 1
                    else "watching"
                )
                session.add(ActivityEvent(
                    timestamp=now - timedelta(minutes=i),
                    mode=mode, previous_mode="idle",
                    source="manual", duration_seconds=600,
                ))
            await session.commit()

        await predictor.retrain()
        # Sidecar file written next to the booster.
        calib_path = predictor._model_manager.data_dir / "mode_predictor_calib.pkl"
        assert calib_path.exists(), "Calibrator sidecar must be persisted"
        # In-memory calibrators populated and shaped to the class set.
        assert predictor._calibrators is not None
        assert len(predictor._calibrators) == len(predictor._label_encoder)

    async def test_load_existing_without_calibrators(
        self, tmp_model_manager, ml_db,
    ):
        """Backward-compat: a model file deployed without a sidecar (the
        first deploy after 2026-05-11) must still load and predict — just
        falls back to raw probs with a warning."""
        import lightgbm as lgb
        import numpy as np

        # Save a minimal booster matching FEATURE_COLUMNS shape.
        from backend.services.ml.behavioral_predictor import FEATURE_COLUMNS
        rng = np.random.default_rng(0)
        x = rng.random((100, len(FEATURE_COLUMNS)))
        y = rng.integers(0, 3, size=100)
        ds = lgb.Dataset(x, label=y)
        booster = lgb.train(
            {"objective": "multiclass", "num_class": 3, "verbose": -1},
            ds, num_boost_round=2,
        )
        model_path = tmp_model_manager.data_dir / "mode_predictor.lgb"
        booster.save_model(str(model_path))
        tmp_model_manager._meta["mode_predictor"] = {
            "file": "mode_predictor.lgb",
            "status": "shadow",
            "label_encoder": {"0": "working", "1": "gaming", "2": "watching"},
        }

        predictor = BehavioralPredictor(tmp_model_manager)
        # Model loaded, calibrators absent — graceful fallback.
        assert predictor._model is not None
        assert predictor._calibrators is None
