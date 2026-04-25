"""
Health-tracking mixin for ML predictors.

Each predictor with a hot-path inference call inherits HealthTrackable
and wraps its body with `_track_predict(True)` on success or
`_track_predict(False, e)` on failure. The `/health` endpoint then
calls `health()` on each predictor and aggregates the results,
flipping the top-level status to "degraded" when something silent
breaks.

The four health states:

- "healthy"   — predictor is voting and recent inferences succeeded
- "shadow"    — predictor is intentionally not voting (pre-promotion,
                or data-gated by insufficient history). NOT degraded.
- "idle"      — predictor has never been invoked yet (startup transient)
- "unhealthy" — model failed to load while expected, or N consecutive
                failures. Triggers /health degraded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_FAILURE_THRESHOLD = 5
_FAILURE_MESSAGE_MAX = 200


class HealthTrackable:
    """
    Mix-in that gives a predictor three counters and a health() method.

    Subclasses must call `_init_health_tracking()` from their __init__
    (Python doesn't guarantee mixin __init__ chains in our patterns
    here — we keep it explicit so the contract is visible at the
    construction site).
    """

    def _init_health_tracking(
        self, failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    ) -> None:
        self._last_predict_at: Optional[datetime] = None
        self._consecutive_failures: int = 0
        self._last_failure: Optional[str] = None
        self._failure_threshold: int = failure_threshold

    def _track_predict(
        self, success: bool, error: Optional[BaseException] = None
    ) -> None:
        """Record one inference outcome onto the predictor's counters."""
        if success:
            self._last_predict_at = datetime.now(timezone.utc)
            self._consecutive_failures = 0
            self._last_failure = None
            return
        self._consecutive_failures += 1
        if error is not None:
            msg = str(error) or type(error).__name__
            self._last_failure = msg[:_FAILURE_MESSAGE_MAX]
        else:
            self._last_failure = "unknown failure"

    def _health_state(
        self,
        *,
        is_shadow: bool = False,
        model_loaded: bool = True,
    ) -> str:
        """
        Compute the health label from the current counters.

        Subclasses pass `is_shadow=True` when the predictor is
        intentionally not voting; that suppresses the unhealthy label
        even with failures (those are expected in shadow mode and
        shouldn't trigger a degraded /health).
        """
        if is_shadow:
            return "shadow"
        if not model_loaded:
            return "unhealthy"
        if self._consecutive_failures >= self._failure_threshold:
            return "unhealthy"
        if self._last_predict_at is None:
            return "idle"
        return "healthy"

    def health(
        self,
        *,
        is_shadow: bool = False,
        model_loaded: bool = True,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Standard /health entry for this predictor.

        `extra` lets subclasses include their own context (model
        version, arm count, etc.) without each one rebuilding the
        common shape.
        """
        state = self._health_state(
            is_shadow=is_shadow, model_loaded=model_loaded
        )
        result = {
            "status": state,
            "model_loaded": model_loaded,
            "last_predict_at": (
                self._last_predict_at.isoformat()
                if self._last_predict_at is not None
                else None
            ),
            "consecutive_failures": self._consecutive_failures,
            "last_failure": self._last_failure,
        }
        if extra:
            result.update(extra)
        return result
