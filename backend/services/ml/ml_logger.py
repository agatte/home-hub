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

from sqlalchemy import Integer, func, select, update

from backend.database import async_session
from backend.models import ActivityEvent, MLDecision

logger = logging.getLogger("home_hub.ml")


class MLDecisionLogger:
    """Logs ML decisions to the database and broadcasts via WebSocket."""

    # Retroactive backfill is capped so system-start, overnight, or
    # long-idle gaps can't be mislabeled with stale mode state.
    _BACKFILL_MAX_HOURS = 2

    def __init__(self, ws_manager: Any) -> None:
        self._ws_manager = ws_manager
        # Tracks the session state for windowed actual_mode backfill.
        # Populated by on_mode_change; prior mode + its start time.
        self._last_mode: Optional[str] = None
        self._last_transition_at: Optional[datetime] = None

    async def log_decision(
        self,
        predicted_mode: str,
        confidence: Optional[float],
        decision_source: str,
        factors: Optional[dict] = None,
        *,
        applied: bool = False,
        broadcast: bool = True,
    ) -> Optional[int]:
        """Record a mode decision and optionally broadcast via WebSocket.

        Args:
            predicted_mode: The mode that was predicted or chosen.
            confidence: Confidence score (0.0-1.0), or None for manual/time.
            decision_source: One of "ml", "rule", "time", "manual", "fusion".
            factors: Reasoning chain (JSON-serializable dict).
            applied: Whether the prediction was actually acted on.
            broadcast: Whether to emit the ml_decision WebSocket event.
                Set False for high-frequency shadow writes (fusion computes
                every 60s) to avoid flooding the pipeline view.

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

                if broadcast:
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

        Kept for backwards compatibility. New callers should prefer
        ``backfill_actual_range`` which tags every shadow row in the
        session window, not just the last one.
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

    async def backfill_actual_range(
        self, actual_mode: str, since: Optional[datetime],
    ) -> int:
        """Tag every decision row in [since, now] that lacks actual_mode.

        Fusion shadow-logs once per 60s, so single-row backfill would
        leave 99%+ of rows without ground truth. This bulk UPDATE tags
        every row in the just-ended session window with the mode that
        was actually active during it.

        The window is capped at ``_BACKFILL_MAX_HOURS`` so system-start,
        overnight sleeps, or long-idle gaps can't be mislabeled — rows
        older than the cap stay NULL and correctly drop out of
        ``compute_accuracy_by_source``.

        Returns the number of rows updated (0 on error or empty window).
        """
        try:
            now = datetime.now(timezone.utc)
            cap_cutoff = now - timedelta(hours=self._BACKFILL_MAX_HOURS)
            effective_since = max(since, cap_cutoff) if since else cap_cutoff

            async with async_session() as session:
                result = await session.execute(
                    update(MLDecision)
                    .where(
                        MLDecision.actual_mode.is_(None),
                        MLDecision.timestamp >= effective_since,
                    )
                    .values(actual_mode=actual_mode)
                )
                await session.commit()
                return result.rowcount or 0
        except Exception as exc:
            logger.error(
                "Failed to backfill actual mode range: %s", exc, exc_info=True,
            )
            return 0

    async def on_mode_change(self, new_mode: str) -> None:
        """Mode-change callback — backfills the just-ended session window.

        Tags every decision row written between the previous transition
        (or a 2h cap, whichever is smaller) and now with the mode that
        was active during that window. The first call after startup has
        no previous mode to backfill — it just records state.
        """
        now = datetime.now(timezone.utc)
        if self._last_mode is not None:
            await self.backfill_actual_range(
                self._last_mode, self._last_transition_at,
            )
        self._last_mode = new_mode
        self._last_transition_at = now

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

    async def compare_strategies(self, days: int = 14) -> dict:
        """A/B comparison of fusion vs rule-engine-only vs process-priority.

        All three strategies are evaluated on the same row set: fusion
        decisions with backfilled ``actual_mode``. For each row, we
        read the per-signal votes from ``factors.signal_details`` and
        compare each signal's mode vote to the eventual ``actual_mode``.
        Stale or missing signals are skipped for that row only.

        Returns a dict keyed by strategy with ``total``, ``correct``,
        and ``accuracy`` fields.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            async with async_session() as session:
                result = await session.execute(
                    select(
                        MLDecision.predicted_mode,
                        MLDecision.actual_mode,
                        MLDecision.factors,
                    )
                    .where(
                        MLDecision.decision_source == "fusion",
                        MLDecision.actual_mode.isnot(None),
                        MLDecision.timestamp >= cutoff,
                    )
                )
                rows = result.all()

            strategies = ("fusion", "rule_engine", "process")
            totals = {s: 0 for s in strategies}
            correct = {s: 0 for s in strategies}

            for predicted, actual, factors in rows:
                # fusion: compare the decision's chosen mode to actual.
                totals["fusion"] += 1
                if predicted == actual:
                    correct["fusion"] += 1

                if not factors or not isinstance(factors, dict):
                    continue
                signal_details = factors.get("signal_details") or {}

                for strat in ("rule_engine", "process"):
                    sig = signal_details.get(strat)
                    if not isinstance(sig, dict) or sig.get("stale"):
                        continue
                    mode = sig.get("mode")
                    if not mode:
                        continue
                    totals[strat] += 1
                    if mode == actual:
                        correct[strat] += 1

            return {
                strat: {
                    "total": totals[strat],
                    "correct": correct[strat],
                    "accuracy": (
                        correct[strat] / totals[strat]
                        if totals[strat] > 0 else None
                    ),
                }
                for strat in strategies
            }
        except Exception as exc:
            logger.error(
                "Failed to compare strategies: %s", exc, exc_info=True,
            )
            return {}

    async def compute_override_rate(
        self, days: int = 7, window_minutes: int = 5,
    ) -> dict:
        """Count user overrides vs cold manual switches.

        An *override* is a ``source='manual'`` activity event whose mode
        differs from the nearest preceding event (any source) within
        ``window_minutes``. A *cold switch* is any other manual event —
        either no prior event in the window, or the prior event already
        agreed with the user's choice.

        Phase 3's autonomy gate is <2 overrides/day sustained 30 days
        (docs/CONFIDENCE_FUSION.md). This is the primary tracking metric.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            window = timedelta(minutes=window_minutes)

            async with async_session() as session:
                result = await session.execute(
                    select(
                        ActivityEvent.timestamp,
                        ActivityEvent.mode,
                        ActivityEvent.source,
                    )
                    .where(ActivityEvent.timestamp >= cutoff)
                    .order_by(ActivityEvent.timestamp.asc())
                )
                rows = result.all()

            overrides = 0
            cold = 0
            total_manual = 0
            # Two-pointer walk: for each manual row, look back for the
            # nearest prior event still within the window.
            for i, row in enumerate(rows):
                if row.source != "manual":
                    continue
                total_manual += 1
                # SQLite returns naive datetimes; normalize.
                row_ts = row.timestamp
                if row_ts.tzinfo is None:
                    row_ts = row_ts.replace(tzinfo=timezone.utc)

                prior_mode = None
                for j in range(i - 1, -1, -1):
                    prior = rows[j]
                    prior_ts = prior.timestamp
                    if prior_ts.tzinfo is None:
                        prior_ts = prior_ts.replace(tzinfo=timezone.utc)
                    if row_ts - prior_ts > window:
                        break
                    prior_mode = prior.mode
                    break

                if prior_mode is not None and prior_mode != row.mode:
                    overrides += 1
                else:
                    cold += 1

            return {
                "total_manual": total_manual,
                "overrides": overrides,
                "cold_switches": cold,
                "overrides_per_day": overrides / days if days > 0 else 0,
                "window_minutes": window_minutes,
                "window_days": days,
            }
        except Exception as exc:
            logger.error(
                "Failed to compute override rate: %s", exc, exc_info=True,
            )
            return {
                "total_manual": 0,
                "overrides": 0,
                "cold_switches": 0,
                "overrides_per_day": 0,
                "window_minutes": window_minutes,
                "window_days": days,
            }
