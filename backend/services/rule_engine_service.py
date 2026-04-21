"""
Rule engine — learns time-based mode patterns and nudges the user.

Periodically scans activity_events for recurring patterns (e.g., "gaming
on Friday at 8pm 85% of the time") and stores them as LearnedRule rows.
When the user is idle and a rule matches the current time, broadcasts a
suggestion via WebSocket. The user can accept or dismiss — rules never
auto-apply in v1.
"""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from backend.database import async_session
from backend.models import ActivityEvent, LearnedRule

logger = logging.getLogger("home_hub.rules")

TZ = ZoneInfo("America/Indiana/Indianapolis")

# Modes that aren't worth predicting — "you're usually idle" isn't helpful
_SKIP_MODES = frozenset(("idle", "away"))

# Per-source vote weights. Ambient/audio_ml post per-second, so without
# weighting they flood buckets (a podcast in the background produces
# 60 social votes to 12 working votes per minute). Process detector and
# manual overrides are authoritative; camera is reliable but posts often;
# ambient/audio_ml are noisy.
_SOURCE_WEIGHTS: dict[str, float] = {
    "manual": 1.0,
    "process": 1.0,
    "presence": 1.0,
    "camera": 0.8,
    "ambient": 0.5,
    "audio_ml": 0.5,
}
_DEFAULT_SOURCE_WEIGHT = 1.0

GENERATION_INTERVAL_HOURS = 6

_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _build_rule_factors(rule: "LearnedRule") -> list[dict]:
    """Describe a matching learned rule as constellation sub-factors.

    Returned shape follows the fusion ``factors`` contract. Exposes the
    slot (day + hour), sample count, and per-rule confidence so the
    analytics view shows *why* the rule engine is voting.
    """
    try:
        day_label = _DAY_NAMES[rule.day_of_week] if 0 <= rule.day_of_week < 7 else "?"
    except (TypeError, IndexError):
        day_label = "?"

    sample_impact = min(1.0, (rule.sample_count or 0) / 30.0)
    return [
        {
            "key": "slot",
            "label": "Slot",
            "value": f"{rule.day_of_week}:{rule.hour}",
            "display": f"{day_label} {rule.hour:02d}:00",
            "impact": 1.0,
        },
        {
            "key": "samples",
            "label": "Samples",
            "value": int(rule.sample_count or 0),
            "display": f"n={int(rule.sample_count or 0)}",
            "impact": round(sample_impact, 3),
        },
        {
            "key": "rule_confidence",
            "label": "Rule conf.",
            "value": float(rule.confidence or 0.0),
            "display": f"{int(round((rule.confidence or 0) * 100))}%",
            "impact": float(rule.confidence or 0.0),
        },
    ]


class RuleEngineService:
    """Frequency-based rule engine — learns and suggests modes from patterns."""

    def __init__(
        self,
        ws_manager,
        min_confidence: float = 0.70,
        min_samples: int = 3,
    ) -> None:
        self._ws_manager = ws_manager
        self._min_confidence = min_confidence
        self._min_samples = min_samples
        self._cooldowns: dict[int, datetime] = {}  # rule_id → last nudged at
        self._last_suggestion: Optional[dict[str, Any]] = None
        self._fusion = None  # ConfidenceFusion handle, injected by main.py

    # ------------------------------------------------------------------
    # Rule generation
    # ------------------------------------------------------------------

    async def regenerate_rules(self) -> dict[str, int]:
        """
        Scan 30 days of activity events and upsert learned rules.

        For each (day_of_week, hour) slot, finds the dominant mode.
        If it meets confidence and sample thresholds, upserts a rule.
        Stale rules (slots that no longer qualify) are deleted.

        Returns:
            Dict with created, updated, and deleted counts.
        """
        since = datetime.now(timezone.utc) - timedelta(days=30)

        async with async_session() as session:
            rows = (await session.execute(
                select(ActivityEvent).where(ActivityEvent.timestamp >= since)
            )).scalars().all()

        # Aggregate by (day, hour, mode) in local timezone. Track raw counts
        # (for the sample-count threshold) and source-weighted votes (for
        # dominant-mode selection and confidence).
        slot_raw: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        slot_weighted: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for row in rows:
            ts = row.timestamp
            if ts is None:
                continue
            if not isinstance(ts, datetime):
                ts = datetime.fromisoformat(str(ts))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            local = ts.astimezone(TZ)
            key = (local.weekday(), local.hour)
            weight = _SOURCE_WEIGHTS.get(row.source, _DEFAULT_SOURCE_WEIGHT)
            slot_raw[key][row.mode] += 1
            slot_weighted[key][row.mode] += weight

        # Determine which slots qualify as rules. Skip-modes (idle/away) are
        # excluded from both dominant-mode selection and the denominator —
        # they aren't worth predicting and shouldn't dilute confidence of
        # genuine activity modes.
        qualified: dict[tuple[int, int], dict[str, Any]] = {}
        for key, raw_counts in slot_raw.items():
            weighted_counts = slot_weighted[key]
            candidate_weights = {
                m: w for m, w in weighted_counts.items() if m not in _SKIP_MODES
            }
            weighted_total = sum(candidate_weights.values())
            if weighted_total <= 0:
                continue

            top_mode = max(candidate_weights, key=candidate_weights.get)
            confidence = candidate_weights[top_mode] / weighted_total
            sample_count = sum(
                c for m, c in raw_counts.items() if m not in _SKIP_MODES
            )

            if (
                confidence >= self._min_confidence
                and sample_count >= self._min_samples
            ):
                qualified[key] = {
                    "predicted_mode": top_mode,
                    "confidence": round(confidence, 3),
                    "sample_count": sample_count,
                }

        # Upsert qualified rules, delete stale ones
        created = 0
        updated = 0
        now = datetime.now(timezone.utc)

        async with async_session() as session:
            existing = (await session.execute(select(LearnedRule))).scalars().all()
            existing_map = {(r.day_of_week, r.hour): r for r in existing}

            # Update or create
            for (day, hour), data in qualified.items():
                rule = existing_map.pop((day, hour), None)
                if rule:
                    rule.predicted_mode = data["predicted_mode"]
                    rule.confidence = data["confidence"]
                    rule.sample_count = data["sample_count"]
                    rule.updated_at = now
                    updated += 1
                else:
                    session.add(LearnedRule(
                        day_of_week=day,
                        hour=hour,
                        predicted_mode=data["predicted_mode"],
                        confidence=data["confidence"],
                        sample_count=data["sample_count"],
                    ))
                    created += 1

            # Delete rules whose slots no longer qualify
            deleted = len(existing_map)
            for stale_rule in existing_map.values():
                await session.delete(stale_rule)

            await session.commit()

        logger.info(
            "Rules regenerated: %d created, %d updated, %d deleted",
            created, updated, deleted,
        )
        return {"created": created, "updated": updated, "deleted": deleted}

    # ------------------------------------------------------------------
    # Rule checking (called from automation loop)
    # ------------------------------------------------------------------

    async def check_rules(self, current_mode: str) -> Optional[dict[str, Any]]:
        """
        Check if a learned rule matches the current time and suggest a mode.

        Always reports the matched rule to confidence fusion (rule_engine
        is a fusion voter — weight 0.10). Only nudges the user via
        WebSocket when current_mode is idle/away. Respects a 1-hour
        cooldown per rule to avoid repeated nudges.

        Returns:
            Suggestion dict if a nudge was sent, None otherwise.
        """
        now = datetime.now(TZ)
        day = now.weekday()
        hour = now.hour

        async with async_session() as session:
            result = await session.execute(
                select(LearnedRule).where(
                    LearnedRule.day_of_week == day,
                    LearnedRule.hour == hour,
                    LearnedRule.enabled.is_(True),
                )
            )
            rule = result.scalar_one_or_none()

        if not rule:
            return None

        # Vote in confidence fusion regardless of current mode — fusion
        # weighs this against the active signals.
        if self._fusion:
            self._fusion.report_signal(
                "rule_engine",
                rule.predicted_mode,
                rule.confidence,
                factors=_build_rule_factors(rule),
            )

        # Nudges are only useful when we don't already know what the user
        # is doing — skip the suggestion path otherwise.
        if current_mode not in ("idle", "away"):
            return None

        # Cooldown — don't nudge more than once per hour per rule
        last_nudge = self._cooldowns.get(rule.id)
        if last_nudge and (now - last_nudge) < timedelta(hours=1):
            return None

        self._cooldowns[rule.id] = now

        pct = round(rule.confidence * 100)
        suggestion = {
            "rule_id": rule.id,
            "predicted_mode": rule.predicted_mode,
            "confidence": pct,
            "sample_count": rule.sample_count,
            "message": (
                f"You're usually in {rule.predicted_mode} mode around this time "
                f"({pct}% confidence from {rule.sample_count} observations)"
            ),
        }
        self._last_suggestion = suggestion

        await self._ws_manager.broadcast("mode_suggestion", suggestion)
        logger.info(
            "Rule nudge: %s at day=%d hour=%d (%d%% confidence)",
            rule.predicted_mode, day, hour, pct,
        )
        return suggestion

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def get_rules(self) -> list[dict[str, Any]]:
        """Return all learned rules ordered by day and hour."""
        async with async_session() as session:
            rows = (await session.execute(
                select(LearnedRule).order_by(LearnedRule.day_of_week, LearnedRule.hour)
            )).scalars().all()

        return [
            {
                "id": r.id,
                "day_of_week": r.day_of_week,
                "hour": r.hour,
                "predicted_mode": r.predicted_mode,
                "confidence": round(r.confidence * 100),
                "sample_count": r.sample_count,
                "enabled": r.enabled,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]

    async def update_rule(self, rule_id: int, enabled: bool) -> Optional[dict]:
        """Toggle a rule's enabled state. Returns updated rule or None."""
        async with async_session() as session:
            result = await session.execute(
                select(LearnedRule).where(LearnedRule.id == rule_id)
            )
            rule = result.scalar_one_or_none()
            if not rule:
                return None
            rule.enabled = enabled
            rule.updated_at = datetime.now(timezone.utc)
            await session.commit()

        logger.info("Rule %d %s", rule_id, "enabled" if enabled else "disabled")
        return {"id": rule_id, "enabled": enabled}

    async def delete_rule(self, rule_id: int) -> bool:
        """Delete a rule by ID. Returns True if deleted."""
        async with async_session() as session:
            result = await session.execute(
                delete(LearnedRule).where(LearnedRule.id == rule_id)
            )
            await session.commit()
            deleted = result.rowcount > 0

        if deleted:
            logger.info("Rule %d deleted", rule_id)
        return deleted

    # ------------------------------------------------------------------
    # Suggestion management
    # ------------------------------------------------------------------

    @property
    def last_suggestion(self) -> Optional[dict[str, Any]]:
        """The most recent active suggestion, or None."""
        return self._last_suggestion

    async def accept_suggestion(self) -> Optional[dict[str, Any]]:
        """Accept the current suggestion. Caller should set_manual_override."""
        suggestion = self._last_suggestion
        self._last_suggestion = None
        return suggestion

    async def dismiss_suggestion(self) -> bool:
        """Dismiss the current suggestion without acting."""
        self._last_suggestion = None
        await self._ws_manager.broadcast("mode_suggestion_dismissed", {})
        return True

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def run_generation_loop(self) -> None:
        """Background task — regenerates rules every 6 hours."""
        logger.info("Rule engine started (regenerating every %dh)", GENERATION_INTERVAL_HOURS)

        while True:
            try:
                await self.regenerate_rules()
            except asyncio.CancelledError:
                logger.info("Rule engine stopped")
                break
            except Exception as e:
                logger.error("Rule generation failed: %s", e, exc_info=True)

            await asyncio.sleep(GENERATION_INTERVAL_HOURS * 3600)
