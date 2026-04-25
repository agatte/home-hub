"""Behavioral mode predictor — LightGBM-based mode prediction.

Trains on activity_events to predict what mode the user will switch to,
given temporal and behavioral features.  Replaces the frequency-based
rule engine as the primary predictor (rule engine becomes fallback).

Starts in shadow mode: predictions are logged but not acted upon until
manually promoted via the API.

Requires: lightgbm, numpy.  If not installed, the predictor is disabled
and the rule engine continues as the sole predictor.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select

from backend.database import async_session
from backend.models import ActivityEvent
from backend.services.ml.feature_builder import (
    PREDICTABLE_MODES,
    build_current_features,
    build_training_data,
)
from backend.services.ml.health_mixin import HealthTrackable
from backend.services.ml.model_manager import ModelManager

logger = logging.getLogger("home_hub.ml")

# Minimum events required before training is attempted.
MIN_TRAINING_EVENTS = 500

# Features used by the model (order matters for LightGBM).
FEATURE_COLUMNS = [
    "hour",
    "minute_bucket",
    "day_of_week",
    "is_weekend",
    "season_enc",
    "previous_mode",
    "previous_mode_duration_min",
    "minutes_since_wake",
    "mode_transitions_today",
    "manual_override_count_7d",
]

# Confidence thresholds for gated actions.
AUTO_APPLY_THRESHOLD = 0.95
SUGGEST_THRESHOLD = 0.70

# Human-readable labels and display formatters for the analytics constellation.
_FEATURE_LABELS: dict[str, str] = {
    "hour": "Hour",
    "minute_bucket": "Quarter",
    "day_of_week": "Day",
    "is_weekend": "Weekend",
    "season_enc": "Season",
    "previous_mode": "Prev Mode",
    "previous_mode_duration_min": "Dwell",
    "minutes_since_wake": "Since Wake",
    "mode_transitions_today": "Transitions",
    "manual_override_count_7d": "Overrides 7d",
}

_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_SEASON_NAMES = ("Winter", "Spring", "Summer", "Fall")


def _format_feature_display(col: str, value: Any) -> str:
    """Format a raw feature value into a UI-friendly string."""
    if value is None:
        return "—"
    if col == "hour":
        try:
            return f"{int(value):02d}:00"
        except (TypeError, ValueError):
            return str(value)
    if col == "day_of_week":
        try:
            idx = int(value)
            return _DAY_NAMES[idx] if 0 <= idx < len(_DAY_NAMES) else str(value)
        except (TypeError, ValueError):
            return str(value)
    if col == "season_enc":
        try:
            idx = int(value)
            return _SEASON_NAMES[idx] if 0 <= idx < len(_SEASON_NAMES) else str(value)
        except (TypeError, ValueError):
            return str(value)
    if col == "is_weekend":
        return "yes" if value else "no"
    if col == "previous_mode":
        # Reverse-encoded lookup — MODE_ENCODING lives in feature_builder.
        try:
            from backend.services.ml.feature_builder import MODE_ENCODING
            reverse = {v: k for k, v in MODE_ENCODING.items()}
            return reverse.get(int(value), str(value))
        except Exception:
            return str(value)
    if col in ("previous_mode_duration_min", "minutes_since_wake"):
        try:
            return f"{float(value):.0f}m"
        except (TypeError, ValueError):
            return str(value)
    if col == "minute_bucket":
        try:
            return f":{int(value) * 15:02d}"
        except (TypeError, ValueError):
            return str(value)
    return str(value)


class BehavioralPredictor(HealthTrackable):
    """LightGBM mode predictor with shadow mode support.

    Lifecycle:
        1. Instantiated in ``main.py`` lifespan (wrapped in try/except ImportError).
        2. If a trained model exists on disk, it's loaded immediately.
        3. ``retrain()`` is called nightly at 4 AM by ``ModelManager``.
        4. ``predict()`` is called every 60s from the automation loop.
        5. Starts in ``shadow`` status — predictions logged but not returned.
        6. Promote to ``active`` via ``POST /api/learning/predictor/promote``.
    """

    def __init__(self, model_manager: ModelManager) -> None:
        self._model_manager = model_manager
        self._model: Any = None
        self._label_encoder: dict[int, str] = {}  # int → mode name
        self._status: str = "shadow"  # "shadow", "active", "demoted"
        self._last_trained: Optional[datetime] = None
        self._last_accuracy: Optional[float] = None
        self._training_rows: int = 0
        self._init_health_tracking()

        # Try loading existing model
        self._load_existing()

    def _load_existing(self) -> None:
        """Load a previously trained model from disk."""
        try:
            import lightgbm as lgb
        except ImportError:
            logger.warning("lightgbm not installed — behavioral predictor disabled")
            return

        meta = self._model_manager._meta.get("mode_predictor", {})
        model_path = self._model_manager.data_dir / "mode_predictor.lgb"

        if model_path.exists():
            try:
                self._model = lgb.Booster(model_file=str(model_path))
                self._status = meta.get("status", "shadow")
                self._last_trained = meta.get("version")
                self._last_accuracy = meta.get("accuracy_7d")
                self._training_rows = meta.get("training_rows", 0)

                # Reconstruct label encoder from metadata
                encoder_data = meta.get("label_encoder", {})
                self._label_encoder = {int(k): v for k, v in encoder_data.items()}

                logger.info(
                    "Loaded behavioral predictor (status=%s, accuracy=%.1f%%, rows=%d)",
                    self._status,
                    (self._last_accuracy or 0) * 100,
                    self._training_rows,
                )
            except Exception as exc:
                logger.error("Failed to load behavioral predictor: %s", exc)
                self._model = None

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    async def retrain(self) -> None:
        """Retrain the model from activity_events.  Called nightly."""
        try:
            import lightgbm as lgb
            import numpy as np
        except ImportError:
            logger.warning("lightgbm/numpy not installed — skipping retrain")
            return

        # Check we have enough data
        async with async_session() as session:
            result = await session.execute(
                select(func.count()).select_from(ActivityEvent)
            )
            event_count = result.scalar() or 0

        if event_count < MIN_TRAINING_EVENTS:
            logger.info(
                "Not enough events for training: %d/%d",
                event_count,
                MIN_TRAINING_EVENTS,
            )
            return

        # Build features (runs DB queries)
        rows = await build_training_data(days=60)
        if len(rows) < MIN_TRAINING_EVENTS:
            logger.info("Not enough training rows after feature engineering: %d", len(rows))
            return

        # Run training in a thread to avoid blocking the event loop
        model, accuracy, label_encoder = await asyncio.to_thread(
            self._train_sync, rows, lgb, np
        )

        if model is None:
            return

        # Save model to disk
        model_path = self._model_manager.data_dir / "mode_predictor.lgb"
        model.save_model(str(model_path))

        self._model = model
        self._label_encoder = label_encoder
        self._last_trained = datetime.now(timezone.utc)
        self._last_accuracy = accuracy
        self._training_rows = len(rows)

        # Preserve current status (don't auto-promote)
        self._model_manager.save_model(
            "mode_predictor",
            model_path,  # pass path, model already saved
            file_name="mode_predictor.lgb",
            metadata={
                "accuracy_7d": accuracy,
                "training_rows": len(rows),
                "status": self._status,
                "label_encoder": {str(k): v for k, v in label_encoder.items()},
            },
        )

        logger.info(
            "Behavioral predictor retrained: accuracy=%.1f%%, rows=%d, status=%s",
            accuracy * 100,
            len(rows),
            self._status,
        )

    def _train_sync(self, rows: list[dict], lgb: Any, np: Any) -> tuple:
        """Synchronous training logic (runs in thread)."""
        try:
            # Separate features and targets
            targets = [r["target"] for r in rows]
            unique_modes = sorted(set(targets))
            mode_to_int = {m: i for i, m in enumerate(unique_modes)}
            label_encoder = {i: m for m, i in mode_to_int.items()}

            y = np.array([mode_to_int[t] for t in targets])
            X = np.array([[r.get(col, 0) for col in FEATURE_COLUMNS] for r in rows])

            # Train/validation split: last 7 days as validation
            split_idx = max(1, int(len(rows) * 0.85))
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]

            if len(X_val) == 0 or len(set(y_train)) < 2:
                logger.warning("Not enough diversity in training data")
                return None, 0, {}

            train_data = lgb.Dataset(X_train, label=y_train, feature_name=FEATURE_COLUMNS)
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

            params = {
                "objective": "multiclass",
                "num_class": len(unique_modes),
                "metric": "multi_logloss",
                "num_leaves": 31,
                "learning_rate": 0.1,
                "feature_fraction": 0.9,
                "verbose": -1,
            }

            model = lgb.train(
                params,
                train_data,
                num_boost_round=100,
                valid_sets=[val_data],
                callbacks=[lgb.log_evaluation(period=0)],  # suppress logging
            )

            # Compute validation accuracy
            val_preds = model.predict(X_val)
            val_pred_classes = np.argmax(val_preds, axis=1)
            accuracy = float(np.mean(val_pred_classes == y_val))

            return model, accuracy, label_encoder

        except Exception as exc:
            logger.error("Training failed: %s", exc, exc_info=True)
            return None, 0, {}

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    async def predict(self, **context: Any) -> Optional[dict]:
        """Predict the most likely mode given current context.

        Args:
            **context: Keyword args passed to ``build_current_features``.

        Returns:
            Dict with ``predicted_mode``, ``confidence``, ``factors``
            if a model is loaded and status is ``active``.  Returns None
            if in shadow mode, no model, or confidence below threshold.
        """
        if self._model is None:
            return None

        try:
            import numpy as np
        except ImportError:
            return None

        try:
            features = build_current_features(**context)

            # Build feature vector in the same column order as training
            x = np.array([[features.get(col, 0) for col in FEATURE_COLUMNS]])

            probs = self._model.predict(x)[0]
            top_idx = int(np.argmax(probs))
            confidence = float(probs[top_idx])
            predicted_mode = self._label_encoder.get(top_idx, "unknown")
        except Exception as exc:
            self._track_predict(False, exc)
            logger.warning("Behavioral predict() failed: %s", exc)
            return None

        # Successful inference — update health counters even if we end
        # up returning None due to a low-confidence prediction. The
        # model is working; it just doesn't have a confident answer.
        self._track_predict(True)

        if predicted_mode == "unknown" or confidence < SUGGEST_THRESHOLD:
            return None

        # Build top contributing factors for explainability
        factors = []
        for i, col in enumerate(FEATURE_COLUMNS):
            if features.get(col) is not None:
                factors.append({
                    "feature": col,
                    "value": features[col],
                })

        result = {
            "predicted_mode": predicted_mode,
            "confidence": confidence,
            "source": "behavioral_predictor",
            "factors": factors[:5],  # top 5 features
            "fusion_factors": self._build_fusion_factors(features),
        }

        # Shadow mode: return prediction for logging but caller should
        # check status before acting on it
        if self._status != "active":
            result["shadow"] = True

        return result

    def get_feature_importances(self) -> dict[str, float]:
        """Return per-feature importance scores normalized to [0, 1].

        Used by the analytics constellation to size/rank the behavioral
        lane's sub-factor pips. Returns empty dict if the model isn't
        loaded or doesn't expose importances (e.g. the shadow stub).
        """
        model = self._model
        if model is None:
            return {}
        try:
            raw = model.feature_importance()
        except Exception:
            return {}
        total = float(sum(raw)) or 1.0
        return {
            col: float(raw[i]) / total
            for i, col in enumerate(FEATURE_COLUMNS)
            if i < len(raw)
        }

    def _build_fusion_factors(self, features: dict) -> list[dict]:
        """Produce constellation-shaped factors from a feature vector.

        Returns at most 3 entries ranked by model importance (falls back
        to a hand-picked default when the model isn't loaded) and with
        human-readable ``display`` values.
        """
        importances = self.get_feature_importances()
        if importances:
            ranked = sorted(
                FEATURE_COLUMNS, key=lambda c: importances.get(c, 0), reverse=True,
            )
        else:
            # Default ordering when no trained model is available.
            ranked = ["hour", "day_of_week", "previous_mode"]

        factors: list[dict] = []
        for col in ranked[:3]:
            if col not in features:
                continue
            raw_value = features[col]
            factors.append({
                "key": col,
                "label": _FEATURE_LABELS.get(col, col),
                "value": raw_value,
                "display": _format_feature_display(col, raw_value),
                "impact": round(max(0.0, min(1.0, importances.get(col, 0.5))), 3),
            })
        return factors

    # ------------------------------------------------------------------
    # Status management
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return predictor status for the API."""
        return {
            "status": self._status,
            "model_loaded": self._model is not None,
            "last_trained": (
                self._last_trained.isoformat()
                if isinstance(self._last_trained, datetime)
                else self._last_trained
            ),
            "accuracy_7d": self._last_accuracy,
            "training_rows": self._training_rows,
            "min_events": MIN_TRAINING_EVENTS,
            "auto_apply_threshold": AUTO_APPLY_THRESHOLD,
            "suggest_threshold": SUGGEST_THRESHOLD,
        }

    def health(self) -> dict:
        """Health entry for the /health ml block.

        ``shadow`` and ``demoted`` are intentional non-voting states; we
        report them as such so the aggregator doesn't flip the system
        to degraded for a predictor that's correctly idle by design.
        """
        is_shadow = self._status != "active"
        return HealthTrackable.health(
            self,
            is_shadow=is_shadow,
            model_loaded=self._model is not None,
            extra={"predictor_status": self._status},
        )

    def promote(self) -> None:
        """Promote from shadow to active — predictions will be acted upon."""
        self._status = "active"
        self._model_manager.update_meta("mode_predictor", status="active")
        logger.info("Behavioral predictor PROMOTED to active")

    def demote(self) -> None:
        """Demote back to shadow — predictions logged but not acted upon."""
        self._status = "shadow"
        self._model_manager.update_meta("mode_predictor", status="shadow")
        logger.info("Behavioral predictor DEMOTED to shadow")
