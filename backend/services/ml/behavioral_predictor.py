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
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select

from backend.database import async_session
from backend.models import ActivityEvent
from backend.services.ml.feature_builder import (
    AUDIO_CLASS_ENCODING,
    MODE_ENCODING,
    POSTURE_ENCODING,
    PREDICTABLE_MODES,
    ZONE_ENCODING,
    build_runtime_features,
    build_training_data,
)
from backend.services.ml.health_mixin import HealthTrackable
from backend.services.ml.model_manager import ModelManager

logger = logging.getLogger("home_hub.ml")

# Minimum events required before training is attempted.
MIN_TRAINING_EVENTS = 500

# Features used by the model (order matters for LightGBM — APPEND only;
# reordering invalidates feature_importance and breaks any saved model).
# The four trailing entries (zone_enc / posture_enc / audio_class_enc /
# lux) were added 2026-05-04 as part of the camera+audio enrichment work.
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
    "zone_enc",
    "posture_enc",
    "audio_class_enc",
    "lux",
    "previous_zone_enc",
]

# Confidence thresholds for gated actions.
#
# AUTO_APPLY_THRESHOLD is the gate the engine uses to decide whether to
# actually act on a prediction. SUGGEST_THRESHOLD only filters which
# predictions are surfaced at all (returned + logged in shadow). The
# 2026-04-27 audit found the original 0.70 cutoff was too tight for an
# 8-way softmax — predictions sat at 0.20–0.65 and never made it into
# `ml_decisions`, masking what the model actually believed. Dropping
# the gate to 0.30 lets diverse predictions appear in shadow logs;
# AUTO_APPLY_THRESHOLD still protects production behavior.
AUTO_APPLY_THRESHOLD = 0.95
SUGGEST_THRESHOLD = 0.30
# Predictions below this threshold are still emitted (so shadow logs see
# the predictor's full output) but are tagged low_confidence=True so
# accuracy metrics can ignore them. Calibrated to ~4× the uniform-random
# baseline on an 8-way softmax (1/8 ≈ 0.125).
LOW_CONFIDENCE_TAG_THRESHOLD = 0.50

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
    "zone_enc": "Zone",
    "posture_enc": "Posture",
    "audio_class_enc": "Audio",
    "lux": "Lux",
    "previous_zone_enc": "Prev Zone",
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
            reverse = {v: k for k, v in MODE_ENCODING.items()}
            return reverse.get(int(value), str(value))
        except Exception:
            return str(value)
    if col == "zone_enc":
        try:
            idx = int(value)
            reverse = {v: k for k, v in ZONE_ENCODING.items()}
            return reverse.get(idx, "—" if idx == len(ZONE_ENCODING) else str(value))
        except Exception:
            return str(value)
    if col == "posture_enc":
        try:
            idx = int(value)
            reverse = {v: k for k, v in POSTURE_ENCODING.items()}
            return reverse.get(idx, "—" if idx == len(POSTURE_ENCODING) else str(value))
        except Exception:
            return str(value)
    if col == "audio_class_enc":
        try:
            idx = int(value)
            reverse = {v: k for k, v in AUDIO_CLASS_ENCODING.items()}
            return reverse.get(idx, str(value))
        except Exception:
            return str(value)
    if col == "lux":
        try:
            v = float(value)
            return "—" if v != v else f"{v:.0f}"  # NaN check via self-inequality
        except (TypeError, ValueError):
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
        # Per-class isotonic calibrators fit on the val split after each
        # retrain. None = calibrators not available (pre-2026-05-11 model
        # files or load failure); predict() falls back to raw probs and
        # logs a warning on first use.
        self._calibrators: Optional[list] = None
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

                # Refuse stale models whose feature count no longer matches
                # FEATURE_COLUMNS — would crash predict() with a length
                # mismatch on the input vector. The 04:00 nightly retrain
                # rebuilds against the current FEATURE_COLUMNS, so dropping
                # the old model here is graceful: predict() returns None
                # until the new model lands.
                loaded_n = self._model.num_feature()
                if loaded_n != len(FEATURE_COLUMNS):
                    logger.warning(
                        "Behavioral predictor model has stale feature count "
                        "(loaded=%d, expected=%d) — refusing to load; will "
                        "rebuild on next nightly retrain.",
                        loaded_n,
                        len(FEATURE_COLUMNS),
                    )
                    self._model = None
                    return

                self._status = meta.get("status", "shadow")
                self._last_trained = meta.get("version")
                self._last_accuracy = meta.get("accuracy_7d")
                self._training_rows = meta.get("training_rows", 0)
                # Make a silently-reverted promotion visible — boot logs
                # reveal whether the predictor came up shadow or active.
                logger.info(
                    "Behavioral predictor loaded: status=%s, accuracy_7d=%s, "
                    "training_rows=%d, last_trained=%s",
                    self._status, self._last_accuracy,
                    self._training_rows, self._last_trained,
                )

                # Reconstruct label encoder from metadata
                encoder_data = meta.get("label_encoder", {})
                label_encoder = {int(k): v for k, v in encoder_data.items()}

                # Refuse stale models. If the saved encoder targets a mode
                # that's no longer valid (e.g. `away` after the home/away
                # retirement), argmax could land on a class that doesn't
                # exist in the current mode set. Drop the model; the
                # nightly retrain at 4 AM rebuilds against MODE_ENCODING.
                stale_modes = [
                    m for m in label_encoder.values()
                    if m not in MODE_ENCODING and m not in PREDICTABLE_MODES
                ]
                if stale_modes:
                    logger.warning(
                        "Behavioral predictor model has stale label encoder "
                        "(modes=%s no longer valid) — refusing to load; will "
                        "rebuild on next retrain.",
                        sorted(stale_modes),
                    )
                    self._model = None
                    return

                self._label_encoder = label_encoder

                # Calibrators ship as a joblib sidecar next to the
                # booster. Missing-file path is the expected state right
                # after a deploy that introduces calibration but before
                # the next 04:00 retrain has run — predict() falls back
                # to raw probs and logs a warning on first use.
                self._calibrators = self._load_calibrators()

                logger.info(
                    "Loaded behavioral predictor (status=%s, accuracy=%.1f%%, "
                    "rows=%d, calibrators=%s)",
                    self._status,
                    (self._last_accuracy or 0) * 100,
                    self._training_rows,
                    "loaded" if self._calibrators is not None else "absent",
                )
            except Exception as exc:
                logger.error("Failed to load behavioral predictor: %s", exc)
                self._model = None

    # ------------------------------------------------------------------
    # Calibrator persistence
    # ------------------------------------------------------------------

    def _calibrator_path(self) -> Path:
        return self._model_manager.data_dir / "mode_predictor_calib.pkl"

    def _load_calibrators(self) -> Optional[list]:
        """Load per-class isotonic calibrators from the joblib sidecar.

        Returns None when the file is missing or the loaded list doesn't
        match the booster's class count. Both are recoverable on the
        next 04:00 retrain — predict() falls back to raw probs in the
        meantime.
        """
        path = self._calibrator_path()
        if not path.exists():
            return None
        try:
            import joblib
            calibrators = joblib.load(path)
            if not isinstance(calibrators, list):
                return None
            # The label_encoder was already populated by the caller — a
            # length mismatch means the calibrators were fit against a
            # different class set (e.g. cooking removal mid-deploy).
            if len(calibrators) != len(self._label_encoder):
                logger.warning(
                    "Calibrator class count mismatch (loaded=%d, expected=%d) "
                    "— ignoring sidecar; will refit on next retrain.",
                    len(calibrators), len(self._label_encoder),
                )
                return None
            return calibrators
        except Exception as exc:
            logger.warning("Failed to load calibrators: %s", exc)
            return None

    def _save_calibrators(self, calibrators: list) -> None:
        """Persist the calibrator list as a joblib sidecar."""
        try:
            import joblib
            joblib.dump(calibrators, self._calibrator_path())
        except Exception as exc:
            logger.warning("Failed to save calibrators: %s", exc)

    @staticmethod
    def _apply_calibrators(
        probs: Any, calibrators: list, np: Any,
    ) -> Any:
        """Apply per-class isotonic calibration and renormalize to sum=1.

        IsotonicRegression maps each raw class probability onto an
        empirical accuracy curve fit at retrain time. Per-class
        application breaks the softmax-sum constraint, so we renormalize
        before downstream consumers (argmax + confidence) read the
        result. A degenerate all-zero output (extremely rare — would
        require every class's calibrator to map probs to 0) falls back
        to uniform.
        """
        calibrated = np.array(
            [
                float(calibrators[i].transform([probs[i]])[0])
                for i in range(len(probs))
            ]
        )
        total = float(calibrated.sum())
        if total > 0:
            return calibrated / total
        # Degenerate: every class's calibrator mapped to 0. In practice
        # blocked by the identity-fallback branch in _train_sync (no
        # class is allowed to fit with zero positives), but log here so
        # any path that does land here is visible in journalctl rather
        # than silently returning a meaningless uniform.
        logger.warning(
            "Calibrator output degenerate (all classes mapped to 0) — "
            "falling back to uniform distribution across %d classes. "
            "Next 04:00 retrain should refit; investigate sidecar if "
            "this persists.",
            len(calibrated),
        )
        return np.full_like(calibrated, 1.0 / len(calibrated))

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
        model, accuracy, label_encoder, calibrators = await asyncio.to_thread(
            self._train_sync, rows, lgb, np
        )

        if model is None:
            return

        # Save model to disk
        model_path = self._model_manager.data_dir / "mode_predictor.lgb"
        model.save_model(str(model_path))

        # Save calibrators alongside the booster. None happens when the
        # val split was too small to fit even a single class — leave the
        # old sidecar in place so predict() can keep using whichever
        # calibrators it had.
        if calibrators is not None:
            self._save_calibrators(calibrators)
            self._calibrators = calibrators

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
                return None, 0, {}, None

            # Class-balanced sample weights — sqrt-softened majority-ratio
            # so minority classes get a meaningful boost without the
            # extreme-tail blowups that the sklearn "balanced" formula
            # produces on rare classes.
            #
            # 2026-05-11 weekly evaluator surfaced 0 gaming predictions
            # over 7d despite 70 actual-next-mode hits — gaming at 8% of
            # the 60d corpus only got a 1.46× boost under inverse
            # frequency, not enough to lift it past majority bias.
            # Meanwhile cooking (now retired from PREDICTABLE_MODES) was
            # getting a 15× boost on 19 samples and destabilizing the
            # softmax. The sqrt formula yields a gentler spread — for
            # the current corpus it's roughly:
            #   working ~1.00, watching ~1.22, gaming ~1.97,
            #   social ~2.44, relax ~2.60
            class_counts = np.bincount(y_train, minlength=len(unique_modes))
            class_weights = np.sqrt(
                class_counts.max() / np.maximum(class_counts, 1)
            )
            # 2026-05-19 escalation per project_step5_predictor_validation.md.
            # 5/11's sqrt-softened weights lifted gaming recall from 0% to
            # ~8.5% of predictions but the 5/18 weekly eval still showed
            # working→gaming class collapse: 102/105 high-conf working
            # predictions had actual=gaming. conf>=0.8 accuracy was 0/17
            # by end of day. Gaming is now ~35% of daily actuals but stays
            # <9% of predictions — the model needs more training mass on
            # gaming, not just a softmax tilt. ×2.0 on top of the sqrt
            # boost (~1.97 → ~3.94 effective) is the documented next step
            # before considering structural fixes (previous_zone feature,
            # calibrator re-fit). Other classes intentionally unchanged so
            # the 5/25 weekly eval can attribute any movement to this.
            GAMING_WEIGHT_BOOST = 2.0
            gaming_idx = mode_to_int.get("gaming")
            if gaming_idx is not None:
                class_weights[gaming_idx] *= GAMING_WEIGHT_BOOST
            sample_weight = class_weights[y_train]

            train_data = lgb.Dataset(
                X_train, label=y_train, weight=sample_weight,
                feature_name=FEATURE_COLUMNS,
            )
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

            params = {
                "objective": "multiclass",
                "num_class": len(unique_modes),
                "metric": "multi_logloss",
                "num_leaves": 31,
                "learning_rate": 0.1,
                "feature_fraction": 0.9,
                # min_child_samples=50 (default 20) — directly attacks the
                # 2026-05-11 conf=1.0 inversion symptom. Smaller leaves
                # could fit tight on majority+minority boundary noise and
                # emit deceptively high softmax peaks; widening the
                # minimum samples per leaf smooths the decision surface
                # and pairs naturally with the post-fit calibrator.
                "min_child_samples": 50,
                "verbose": -1,
            }

            model = lgb.train(
                params,
                train_data,
                num_boost_round=100,
                valid_sets=[val_data],
                callbacks=[lgb.log_evaluation(period=0)],  # suppress logging
            )

            # Compute validation accuracy on the raw booster output —
            # used as the headline 7d accuracy. The calibrators only
            # rescale confidence scores; argmax stays the same as raw
            # probs in the typical case.
            val_preds = model.predict(X_val)
            val_pred_classes = np.argmax(val_preds, axis=1)
            accuracy = float(np.mean(val_pred_classes == y_val))

            # Per-class isotonic calibration — fit on val-set probs so
            # the model's confidence scores become monotonic with
            # empirical accuracy. Addresses the 2026-05-11 conf=1.0
            # inversion finding (top-bucket accuracy at 17.6% vs
            # conf=0.9 at 61%). Each calibrator is one-vs-rest:
            # IsotonicRegression on (raw_prob_for_class_i, was_class_i).
            #
            # Edge case: if a class never appears in val (positives==0),
            # IsotonicRegression collapses to a constant zero output,
            # which would zero out that class at inference time and
            # break renormalization. Substitute the identity mapping
            # for any such class so it falls back to raw probs.
            calibrators: list = []
            try:
                from sklearn.isotonic import IsotonicRegression
                for class_idx in range(len(unique_modes)):
                    raw = val_preds[:, class_idx]
                    target = (y_val == class_idx).astype(int)
                    if target.sum() == 0:
                        # No positives — identity calibrator.
                        cal = IsotonicRegression(out_of_bounds="clip")
                        cal.fit([0.0, 1.0], [0.0, 1.0])
                    else:
                        cal = IsotonicRegression(
                            out_of_bounds="clip", y_min=0.0, y_max=1.0,
                        )
                        cal.fit(raw, target)
                    calibrators.append(cal)
            except Exception as exc:
                logger.warning(
                    "Calibrator fit failed (%s) — leaving sidecar untouched",
                    exc,
                )
                calibrators = None  # type: ignore[assignment]

            # Per-class val metrics — recall (correct / actual), precision
            # (correct / predicted), and F1. Surfaces class-balance
            # regressions in journalctl: a starved class shows up as
            # recall=0 with predicted=0, the 2026-05-11 gaming-class
            # symptom. With sample weights minority classes should gain
            # recall at some cost to majority precision; if any class
            # still reads 0% with sample size ≥ 5 the features don't
            # carry the signal and weights alone won't fix it.
            per_class_actual: dict[str, int] = {}
            per_class_predicted: dict[str, int] = {}
            per_class_correct: dict[str, int] = {}
            for pred, actual in zip(val_pred_classes, y_val):
                actual_mode = label_encoder.get(int(actual), "unknown")
                pred_mode = label_encoder.get(int(pred), "unknown")
                per_class_actual[actual_mode] = (
                    per_class_actual.get(actual_mode, 0) + 1
                )
                per_class_predicted[pred_mode] = (
                    per_class_predicted.get(pred_mode, 0) + 1
                )
                if int(pred) == int(actual):
                    per_class_correct[actual_mode] = (
                        per_class_correct.get(actual_mode, 0) + 1
                    )
            per_class_metrics: dict[str, dict] = {}
            for mode in sorted(set(per_class_actual) | set(per_class_predicted)):
                n_actual = per_class_actual.get(mode, 0)
                n_pred = per_class_predicted.get(mode, 0)
                n_correct = per_class_correct.get(mode, 0)
                recall = n_correct / n_actual if n_actual > 0 else 0.0
                precision = n_correct / n_pred if n_pred > 0 else 0.0
                f1 = (
                    2 * precision * recall / (precision + recall)
                    if (precision + recall) > 0 else 0.0
                )
                per_class_metrics[mode] = {
                    "n": n_actual,
                    "predicted": n_pred,
                    "correct": n_correct,
                    "recall": round(recall, 3),
                    "precision": round(precision, 3),
                    "f1": round(f1, 3),
                }
            class_weight_str = ", ".join(
                f"{label_encoder[i]}={class_weights[i]:.2f}"
                for i in range(len(unique_modes))
            )
            calib_str = (
                "fit" if calibrators
                else ("skipped" if calibrators is None else "empty")
            )
            logger.info(
                "Behavioral predictor train: weights={%s}, per_class_val=%s, "
                "overall_val=%.3f, calibrators=%s",
                class_weight_str, per_class_metrics, accuracy, calib_str,
            )

            return model, accuracy, label_encoder, calibrators

        except Exception as exc:
            logger.error("Training failed: %s", exc, exc_info=True)
            return None, 0, {}, None

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    async def predict(
        self,
        current_mode: str,
        zone: Optional[str] = None,
        posture: Optional[str] = None,
        audio_class: Optional[str] = None,
        lux: Optional[float] = None,
    ) -> Optional[dict]:
        """Predict the most likely mode given current context.

        Queries activity_events to build the live feature vector — same
        shape as training rows, including dwell / transitions-today /
        manual-overrides-7d / minutes-since-wake. The pre-2026-04-28
        version called this with only ``current_mode`` and left the
        other four features at 0, which silently broke train/serve
        parity.

        Args:
            current_mode: The mode the engine currently believes is
                active. Used as ``previous_mode`` in the feature vector.
            zone, posture, audio_class, lux: Camera + audio context at
                inference time. None values are encoded as the unknown
                sentinel for categoricals or NaN for lux. Caller should
                pass the camera service's freshness-gated values so
                stale committed state doesn't poison inference.

        Returns:
            Dict with ``predicted_mode``, ``confidence``, ``factors``,
            ``distribution`` (per-class probabilities) when a model is
            loaded. ``shadow`` flag set when the predictor isn't
            promoted to active. Returns None on no model, model error,
            or confidence below ``SUGGEST_THRESHOLD``.
        """
        if self._model is None:
            return None

        try:
            import numpy as np
        except ImportError:
            return None

        try:
            features = await build_runtime_features(
                current_mode,
                zone=zone,
                posture=posture,
                audio_class=audio_class,
                lux=lux,
            )

            # Build feature vector in the same column order as training
            x = np.array([[features.get(col, 0) for col in FEATURE_COLUMNS]])

            probs = self._model.predict(x)[0]
            # Apply isotonic calibration when available. Older models
            # deployed before the 2026-05-11 calibration work ship
            # without a sidecar — predict() keeps working on raw probs
            # until the next 04:00 retrain refits both pieces together.
            if self._calibrators is not None and len(self._calibrators) == len(probs):
                probs = self._apply_calibrators(probs, self._calibrators, np)
            top_idx = int(np.argmax(probs))
            confidence = float(probs[top_idx])
            predicted_mode = self._label_encoder.get(top_idx, "unknown")

            # Full distribution: {mode_name: probability} for every
            # class the model knows about. Surfaced into shadow logs so
            # we can see what the model thinks across ALL classes, not
            # just the argmax — necessary for diagnosing single-class
            # collapse and threshold tuning.
            distribution = {
                self._label_encoder.get(i, f"class_{i}"): float(p)
                for i, p in enumerate(probs)
            }
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

        # Tag low-confidence predictions so accuracy metrics can filter
        # them out. SUGGEST_THRESHOLD=0.30 floods ml_decisions with
        # near-random predictions (1/8 ≈ 0.125 baseline on an 8-way
        # softmax); without the tag, those rows poison per-source
        # accuracy. compute_per_source_metrics excludes these.
        low_confidence = confidence < LOW_CONFIDENCE_TAG_THRESHOLD

        # Feature-vector echo for explainability. Keyed by FEATURE_COLUMNS
        # so audits can `json_extract(factors, '$.features.audio_class_enc')`
        # — list-of-dicts truncated to 5 made the 5/05-retrain features
        # invisible to ml-model-evaluator and predictor-promotion-advisor.
        # NaN floats (e.g. lux when no fresh camera read) serialize as the
        # literal `NaN`, which breaks sqlite json_valid() so json_extract
        # returns null instead of the value. Coerce NaN → None.
        feature_values: dict[str, Any] = {}
        for col in FEATURE_COLUMNS:
            value = features.get(col)
            if value is None:
                continue
            if isinstance(value, float) and math.isnan(value):
                continue
            feature_values[col] = value

        result = {
            "predicted_mode": predicted_mode,
            "confidence": confidence,
            "source": "behavioral_predictor",
            "low_confidence": low_confidence,
            "factors": {
                "features": feature_values,
                "distribution": distribution,
                "low_confidence": low_confidence,
            },
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
            "feature_importance": self.get_feature_importances(),
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

    async def check_and_demote_if_degenerate(self, ml_logger) -> dict:
        """Auto-demote counterpart to /predictor/promote's diversity gate.

        No-op when status != 'active' (nothing to demote). Otherwise
        queries the same compute_prediction_diversity helper and only
        demotes on a confirmed-collapse reason ('single_class' or
        'near_single_class'). 'insufficient_samples' / 'no_predictions'
        / 'query_failed' are treated as "don't know yet" — they will
        never trigger demotion of an otherwise-healthy promoted
        predictor (a freshly-promoted model with <50 logged
        predictions would otherwise flap straight back to shadow).

        Returns ``{"action": "skipped"|"kept_active"|"auto_demoted", ...}``
        merged with the diversity diagnostics — for journalctl + the
        scheduler's per-task log line.
        """
        if self._status != "active":
            return {"action": "skipped", "reason": "not_active"}
        diversity = await ml_logger.compute_prediction_diversity()
        if diversity.get("diverse"):
            return {"action": "kept_active", **diversity}
        if diversity.get("reason") not in ("single_class", "near_single_class"):
            # Anti-flap: missing data isn't grounds for demotion.
            return {"action": "kept_active", **diversity}
        self.demote()
        logger.warning(
            "Behavioral predictor AUTO-DEMOTED to shadow — degenerate "
            "outputs over %sd window: %s",
            diversity.get("window_days"), diversity,
        )
        return {"action": "auto_demoted", **diversity}
