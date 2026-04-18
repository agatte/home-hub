"""ML decision logger — records every mode decision with reasoning.

Every mode switch (ML, rule engine, time-based, or manual) gets a
decision log entry explaining why. This provides explainability,
enables shadow-mode accuracy evaluation, and feeds the metrics
dashboard.

Each log call is fire-and-forget: errors are logged but never
re-raised so ML logging never disrupts the automation loop.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Integer, func, select

from backend.database import async_session
from backend.models import MLDecision

logger = logging.getLogger("home_hub.ml")


class MLDecisionLogger:
    """Logs ML decisions to the database and broadcasts via WebSocket."""

    def __init__(self, ws_manager: Any) -> None:
        self._ws_manager = ws_manager

    async def log_decision(
        self,
        predicted_mode: str,
        confidence: Optional[float],
        decision_source: str,
        factors: Optional[dict] = None,
        *,
        applied: bool = False,
    ) -> Optional[int]:
        """Record a mode decision and broadcast via WebSocket.

        Args:
            predicted_mode: The mode that was predicted or chosen.
            confidence: Confidence score (0.0-1.0), or None for manual/time.
            decision_source: One of "ml", "rule", "time", "manual".
            factors: Reasoning chain (JSON-serializable dict).
            applied: Whether the prediction was actually acted on.

        Returns:
            The decision row ID, or None on failure.
        """
        try:
            async with async_session() as session:
                decision = MLDecision(
                    predicted_mode=predicted_mode,
                    confidence=confidence,
                    decision_source=decision_source,
                    factors=factors,
                    applied=applied,
                )
                session.add(decision)
                await session.commit()
                await session.refresh(decision)

                # Broadcast for frontend consumption
                await self._ws_manager.broadcast(
                    "ml_decision",
                    {
                        "id": decision.id,
                        "predicted_mode": predicted_mode,
                        "confidence": confidence,
                        "decision_source": decision_source,
                        "applied": applied,
                    },
                )
                return decision.id
        except Exception as exc:
            logger.error("Failed to log ML decision: %s", exc, exc_info=True)
            return None

    async def backfill_actual(self, actual_mode: str) -> None:
        """Fill in actual_mode on the most recent decision that lacks one.

        Called on every mode transition so we can later compute accuracy
        (predicted_mode vs actual_mode).
        """
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(MLDecision)
                    .where(MLDecision.actual_mode.is_(None))
                    .order_by(MLDecision.timestamp.desc())
                    .limit(1)
                )
                decision = result.scalar_one_or_none()
                if decision:
                    decision.actual_mode = actual_mode
                    await session.commit()
        except Exception as exc:
            logger.error("Failed to backfill actual mode: %s", exc, exc_info=True)

    async def on_mode_change(self, new_mode: str) -> None:
        """Mode-change callback — backfills the previous decision's actual_mode."""
        await self.backfill_actual(new_mode)

    async def get_recent(self, limit: int = 10) -> list[dict]:
        """Return recent decisions for the API."""
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(MLDecision)
                    .order_by(MLDecision.timestamp.desc())
                    .limit(limit)
                )
                rows = result.scalars().all()
                return [
                    {
                        "id": r.id,
                        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                        "predicted_mode": r.predicted_mode,
                        "actual_mode": r.actual_mode,
                        "applied": r.applied,
                        "confidence": r.confidence,
                        "decision_source": r.decision_source,
                        "factors": r.factors,
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.error("Failed to fetch recent decisions: %s", exc, exc_info=True)
            return []

    async def compute_accuracy(self, days: int = 7) -> dict:
        """Compute prediction accuracy over a time window.

        Only considers rows where ``applied=True`` and both predicted_mode
        and actual_mode are filled in.

        Returns:
            Dict with ``total``, ``correct``, ``accuracy`` keys.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            async with async_session() as session:
                result = await session.execute(
                    select(
                        func.count().label("total"),
                        func.sum(
                            (MLDecision.predicted_mode == MLDecision.actual_mode).cast(
                                Integer
                            )
                        ).label("correct"),
                    )
                    .where(
                        MLDecision.applied.is_(True),
                        MLDecision.actual_mode.isnot(None),
                        MLDecision.timestamp >= cutoff,
                    )
                )
                row = result.one()
                total = row.total or 0
                correct = row.correct or 0
                return {
                    "total": total,
                    "correct": correct,
                    "accuracy": correct / total if total > 0 else None,
                    "window_days": days,
                }
        except Exception as exc:
            logger.error("Failed to compute accuracy: %s", exc, exc_info=True)
            return {"total": 0, "correct": 0, "accuracy": None, "window_days": days}

    async def compute_accuracy_by_source(
        self, days: int = 14,
    ) -> dict[str, float]:
        """Per-signal accuracy for fusion weight learning.

        Walks ``ml_decisions`` rows where ``decision_source='fusion'`` and
        ``factors`` contains a ``signal_details`` dict (added by the
        automation engine at each fusion log site). For each signal source
        (process / camera / audio_ml / behavioral / rule_engine), computes
        how often that source's per-decision mode vote matched the eventual
        ``actual_mode``. Stale signals are excluded.

        The returned dict is consumable directly by
        ``ConfidenceFusion.update_weights_from_accuracy``. Sources that
        have no usable samples in the window are omitted — the fusion
        method falls back to DEFAULT_WEIGHTS for anything missing.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            async with async_session() as session:
                result = await session.execute(
                    select(MLDecision.factors, MLDecision.actual_mode)
                    .where(
                        MLDecision.decision_source == "fusion",
                        MLDecision.actual_mode.isnot(None),
                        MLDecision.timestamp >= cutoff,
                    )
                )
                rows = result.all()

            totals: dict[str, int] = {}
            correct: dict[str, int] = {}
            for factors, actual in rows:
                if not factors or not isinstance(factors, dict):
                    continue
                signal_details = factors.get("signal_details") or {}
                for src, sig in signal_details.items():
                    if not isinstance(sig, dict):
                        continue
                    if sig.get("stale"):
                        continue
                    mode = sig.get("mode")
                    if not mode:
                        continue
                    totals[src] = totals.get(src, 0) + 1
                    if mode == actual:
                        correct[src] = correct.get(src, 0) + 1

            return {
                src: correct.get(src, 0) / totals[src]
                for src in totals
                if totals[src] > 0
            }
        except Exception as exc:
            logger.error(
                "Failed to compute per-source accuracy: %s", exc,
                exc_info=True,
            )
            return {}
