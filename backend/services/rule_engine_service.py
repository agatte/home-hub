"""
Rule engine — learns time-based mode patterns and nudges the user.

Periodically scans activity_events for recurring patterns (e.g., "gaming
on Friday at 8pm 85% of the time") and stores them as LearnedRule rows.
When the user is idle and a rule matches the current time, broadcasts a
suggestion via WebSocket. The user can accept or dismiss — rules never
auto-apply in v1.
"""
import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update

from backend.database import async_session
from backend.models import ActivityEvent, LearnedRule, RuleSuggestion
from backend.services.ml.confidence_fusion import VALID_MODES

# Pending rows older than this are auto-expired by `expire_stale_pending`,
# and `restore_pending_on_boot` will expire (not re-broadcast) anything
# older than this on startup.
SUGGESTION_MAX_AGE_MINUTES = 60

logger = logging.getLogger("home_hub.rules")

TZ = ZoneInfo("America/Indiana/Indianapolis")

# Modes that aren't worth predicting — "you're usually idle" isn't helpful
_SKIP_MODES = frozenset(("idle",))

# Slots where the user is at the office — no meaningful at-home PC activity,
# so don't try to predict modes here. Hours are local (TZ above). Default:
# 8am–4:59pm Mon–Fri (the 17:00 commute slot stays open).
_BLACKOUT_SLOTS: frozenset = frozenset(
    (day, hour) for day in range(0, 5) for hour in range(8, 17)
)

# Per-source vote weights. Ambient/audio_ml post per-second, so without
# weighting they flood buckets (a podcast in the background produces
# 60 social votes to 12 working votes per minute). Process detector and
# manual overrides are authoritative; camera is reliable but posts often;
# ambient/audio_ml are noisy.
_SOURCE_WEIGHTS: dict[str, float] = {
    "manual": 1.0,
    "process": 1.0,
    "camera": 0.8,
    "ambient": 0.5,
    "audio_ml": 0.5,
}
_DEFAULT_SOURCE_WEIGHT = 1.0

GENERATION_INTERVAL_HOURS = 6

_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _as_utc(dt: datetime) -> datetime:
    """Normalize a datetime to tz-aware UTC. SQLite returns naive datetimes."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _suggestion_to_dict(
    row: "RuleSuggestion",
    override: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Serialize a RuleSuggestion row to the API/JSON shape.

    `confidence` is emitted as an int percent (UX payload contract);
    timestamps are ISO8601 UTC. `override` lets the accept/dismiss
    path return the post-update view without a re-query.
    """
    override = override or {}
    confidence_raw = override.get("confidence", row.confidence)
    fired_at = _as_utc(row.fired_at)
    resolved_at = override.get("resolved_at", row.resolved_at)
    if resolved_at is not None:
        resolved_at = _as_utc(resolved_at).isoformat()
    payload = override.get("payload")
    if payload is None and row.payload:
        try:
            payload = json.loads(row.payload)
        except Exception:
            payload = {}
    data = {
        "id": row.id,
        "rule_id": row.rule_id,
        "kind": override.get("kind", row.kind),
        "fired_at": fired_at.isoformat(),
        "predicted_mode": override.get("predicted_mode", row.predicted_mode),
        "confidence": int(round(float(confidence_raw) * 100)),
        "sample_count": row.sample_count,
        "current_mode_at_fire": row.current_mode_at_fire,
        "status": override.get("status", row.status),
        "resolved_at": resolved_at,
        "resolved_source": override.get("resolved_source", row.resolved_source),
    }
    if payload is not None:
        data["payload"] = payload
    return data


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
        confidence_fusion=None,
        ml_logger=None,
        lighting_learner=None,
        notifier_service=None,
        api_key: Optional[str] = None,
        public_base_url: Optional[str] = None,
        automation=None,
        presence=None,
    ) -> None:
        self._ws_manager = ws_manager
        self._min_confidence = min_confidence
        self._min_samples = min_samples
        self._cooldowns: dict[int, datetime] = {}  # rule_id → last nudged at
        self._last_suggestion: Optional[dict[str, Any]] = None
        self._fusion = confidence_fusion
        self._ml_logger = ml_logger
        # Brightness-suggestion plumbing — lighting_learner produces the
        # candidates, notifier_service is the surface. api_key + public
        # base url are baked into the action URLs ntfy.sh callbacks hit.
        self._lighting_learner = lighting_learner
        self._notifier = notifier_service
        self._automation = automation
        self._presence = presence
        self._api_key = api_key
        self._public_base_url = (
            (public_base_url or "").rstrip("/")
            or "http://192.168.86.210:8000"  # LAN bypass for require_api_key
        )
        self._last_brightness_scan: dict[str, Any] = {
            "scanned_at": None,
            "candidate_count": 0,
            "emitted_count": 0,
            "duplicate_count": 0,
            "rejection_counts": {},
        }
        self._heartbeat = None  # HeartbeatRegistry, injected by main.py

    def set_heartbeat_registry(self, registry) -> None:
        """Inject the heartbeat registry (called from lifespan)."""
        self._heartbeat = registry

    def set_brightness_suggestion_deps(
        self,
        *,
        lighting_learner=None,
        notifier_service=None,
        api_key: Optional[str] = None,
        public_base_url: Optional[str] = None,
        automation=None,
        presence=None,
    ) -> None:
        """Late-bind the brightness-suggestion collaborators.

        Bootstrap order constructs rule_engine before notifier_service, so
        these get wired post-construction. Anything passed as None leaves
        the existing value untouched (test override path).
        """
        if lighting_learner is not None:
            self._lighting_learner = lighting_learner
        if notifier_service is not None:
            self._notifier = notifier_service
        if api_key is not None:
            self._api_key = api_key
        if public_base_url is not None:
            self._public_base_url = public_base_url.rstrip("/")
        if automation is not None:
            self._automation = automation
        if presence is not None:
            self._presence = presence

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
            # Drop rows for retired modes (e.g. pre-2026-04-27 `away` data)
            # before they can seed rules whose votes fusion would silently
            # reject. VALID_MODES is the source of truth for what fusion
            # accepts.
            if row.mode not in VALID_MODES:
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

        # Determine which slots qualify as rules. Skip-modes (idle) are
        # excluded from both dominant-mode selection and the denominator —
        # they aren't worth predicting and shouldn't dilute confidence of
        # genuine activity modes.
        qualified: dict[tuple[int, int], dict[str, Any]] = {}
        for key, raw_counts in slot_raw.items():
            if key in _BLACKOUT_SLOTS:
                continue
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
        WebSocket when current_mode is idle. Respects a 1-hour
        cooldown per rule to avoid repeated nudges.

        Returns:
            Suggestion dict if a nudge was sent, None otherwise.
        """
        now = datetime.now(TZ)
        day = now.weekday()
        hour = now.hour

        # Blackout: don't predict during the user's at-the-office hours
        # even if a stale rule somehow exists for one of those slots.
        if (day, hour) in _BLACKOUT_SLOTS:
            return None

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

        # Defensive: a rule predicting a retired mode would be silently
        # rejected by fusion's report_signal — bail before that happens.
        if rule.predicted_mode not in VALID_MODES:
            return None

        # Permanent guardrail — if either dependency is missing at the
        # moment of a real match, the lane is silent for this rule fire
        # AND every future one (deps are set once at construction). Log
        # WARN so journalctl catches the regression. Was previously
        # masked by `if self._fusion:` / `if self._ml_logger:` guards.
        if self._fusion is None or self._ml_logger is None:
            logger.warning(
                "rule_engine match for rule_id=%d (day=%d hour=%d %s) "
                "but deps missing: fusion=%s ml_logger=%s — fusion lane "
                "will be silent. Check bootstrap construction order.",
                rule.id, day, hour, rule.predicted_mode,
                self._fusion is not None, self._ml_logger is not None,
            )

        # Vote in confidence fusion regardless of current mode — fusion
        # weighs this against the active signals.
        if self._fusion:
            self._fusion.report_signal(
                "rule_engine",
                rule.predicted_mode,
                rule.confidence,
                factors=_build_rule_factors(rule),
            )

        # Persist a per-lane row in ml_decisions so per-source accuracy
        # and the analytics dashboard have something to show. Shadow row
        # (applied=False) — rule_engine is a voter, not an actuator.
        if self._ml_logger:
            await self._ml_logger.log_decision(
                predicted_mode=rule.predicted_mode,
                confidence=rule.confidence,
                decision_source="rule_engine",
                factors={
                    "slot": f"{day}:{hour}",
                    "rule_id": rule.id,
                    "sample_count": rule.sample_count,
                    "rule_confidence": rule.confidence,
                },
                applied=False,
                broadcast=False,
            )

        # Nudges are only useful when we don't already know what the user
        # is doing — skip the suggestion path otherwise.
        if current_mode != "idle":
            return None

        # Cooldown — don't nudge more than once per hour per rule
        last_nudge = self._cooldowns.get(rule.id)
        if last_nudge and (now - last_nudge) < timedelta(hours=1):
            return None

        self._cooldowns[rule.id] = now

        # Persist this fire. Mark any prior pending row as `superseded`
        # in the same transaction so the "latest pending" lookup the
        # accept/dismiss endpoints rely on always returns one row.
        # Roll back the in-memory cooldown stamp on DB failure so we
        # don't phantom-suppress this rule for the next hour on a pure
        # infra error.
        now_utc = datetime.now(timezone.utc)
        try:
            async with async_session() as session:
                prior_pending = (await session.execute(
                    select(RuleSuggestion).where(
                        RuleSuggestion.status == "pending",
                        RuleSuggestion.kind == "mode",
                    )
                )).scalars().all()

                new_row = RuleSuggestion(
                    rule_id=rule.id,
                    fired_at=now_utc,
                    predicted_mode=rule.predicted_mode,
                    confidence=float(rule.confidence),
                    sample_count=int(rule.sample_count),
                    current_mode_at_fire=current_mode,
                    status="pending",
                    kind="mode",
                )
                session.add(new_row)
                await session.flush()  # populate new_row.id

                for prior in prior_pending:
                    prior.status = "superseded"
                    prior.resolved_at = now_utc
                    prior.resolved_source = f"superseded_by:{new_row.id}"

                await session.commit()
                new_id = new_row.id
        except Exception:
            self._cooldowns.pop(rule.id, None)
            logger.exception(
                "rule_suggestions DB insert failed for rule_id=%d; cooldown rolled back",
                rule.id,
            )
            return None

        pct = round(rule.confidence * 100)
        suggestion = {
            "suggestion_id": new_id,
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
        if self._notifier:
            try:
                accept_url = (
                    f"{self._public_base_url}"
                    f"/api/rules/suggestion/accept/{new_id}"
                )
                dismiss_url = (
                    f"{self._public_base_url}"
                    f"/api/rules/suggestion/dismiss/{new_id}"
                )
                await self._notifier.emit_suggestion(
                    suggestion_id=new_id,
                    title="Mode suggestion",
                    body=suggestion["message"],
                    accept_url=accept_url,
                    dismiss_url=dismiss_url,
                    api_key=self._api_key,
                    extra={
                        "kind": "suggestion",
                        "suggestion_kind": "mode",
                        "predicted_mode": rule.predicted_mode,
                        "confidence": pct,
                        "sample_count": rule.sample_count,
                        "rule_id": rule.id,
                    },
                )
            except Exception:
                logger.exception(
                    "NotifierService.emit_suggestion failed for mode sid=%d",
                    new_id,
                )
        logger.info(
            "Rule nudge: %s at day=%d hour=%d (%d%% confidence) suggestion_id=%d",
            rule.predicted_mode, day, hour, pct, new_id,
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

    async def accept_suggestion(self, remote: str = "unknown") -> Optional[dict[str, Any]]:
        """Accept the latest pending suggestion. DB-backed; race-safe.

        Returns the resolved row as a dict on success. Returns None when
        there's no pending row OR when a concurrent click already
        resolved it (caller maps to 410 Gone). Caller is responsible
        for applying the override via `automation.set_manual_override`.
        """
        return await self._resolve_pending(
            new_status="accepted",
            resolved_source=f"user_accept:{remote}",
            broadcast_dismiss=False,
        )

    async def accept_suggestion_by_id(
        self,
        suggestion_id: int,
        remote: str = "unknown",
    ) -> Optional[dict[str, Any]]:
        """Accept one specific pending mode suggestion by id.

        Desktop notification buttons are long-lived enough that "latest
        pending" is the wrong target: a newer nudge could supersede the row
        after the toast was shown. This method resolves only the row the
        button was created for.
        """
        return await self._resolve_suggestion_by_id(
            suggestion_id=suggestion_id,
            new_status="accepted",
            resolved_source=f"user_accept:{remote}",
            broadcast_dismiss=False,
        )

    async def dismiss_suggestion(self, remote: str = "unknown") -> Optional[dict[str, Any]]:
        """Dismiss the latest pending suggestion. DB-backed; idempotent.

        Broadcasts `mode_suggestion_dismissed` whether or not a row was
        actually resolved — UI's optimistic dismiss should always settle.
        """
        return await self._resolve_pending(
            new_status="dismissed",
            resolved_source=f"user_dismiss:{remote}",
            broadcast_dismiss=True,
        )

    async def dismiss_suggestion_by_id(
        self,
        suggestion_id: int,
        remote: str = "unknown",
    ) -> Optional[dict[str, Any]]:
        """Dismiss one specific pending mode suggestion by id."""
        return await self._resolve_suggestion_by_id(
            suggestion_id=suggestion_id,
            new_status="dismissed",
            resolved_source=f"user_dismiss:{remote}",
            broadcast_dismiss=True,
        )

    # ------------------------------------------------------------------
    # Brightness-kind suggestions (LightingLearner scanner output)
    # ------------------------------------------------------------------

    async def emit_brightness_suggestion(
        self,
        candidate: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Persist a brightness suggestion and return the inserted row.

        Deduplicates: if a pending kind="brightness" row already exists
        for the same (light_id, mode, period, weather_class) bucket, this
        method returns None (caller skips emission for that bucket).

        Caller is responsible for routing the returned dict through
        NotifierService.emit_suggestion to surface it.
        """
        import json as _json

        scope = candidate.get("scope") or "light"
        light_id = str(candidate["light_id"])
        room = candidate.get("room")
        mode = candidate["mode"]
        period = candidate["period"]
        weather = candidate["weather_class"]
        zone = candidate.get("zone_at_time")

        async with async_session() as session:
            # Deduplicate against pending rows for the same bucket.
            existing = (await session.execute(
                select(RuleSuggestion).where(
                    RuleSuggestion.status == "pending",
                    RuleSuggestion.kind == "brightness",
                )
            )).scalars().all()
            for row in existing:
                if not row.payload:
                    continue
                try:
                    parsed = _json.loads(row.payload)
                except Exception:
                    continue
                same_context = (
                    parsed.get("mode") == mode
                    and parsed.get("period") == period
                    and parsed.get("weather_class") == weather
                    and parsed.get("zone_at_time") == zone
                )
                if scope == "room":
                    duplicate = (
                        same_context
                        and parsed.get("scope") == "room"
                        and parsed.get("room") == room
                    )
                else:
                    duplicate = (
                        same_context
                        and str(parsed.get("light_id")) == light_id
                        and (parsed.get("scope") in (None, "light"))
                    )
                if duplicate:
                    return None  # already pending — don't double-emit

            sample_count = int(candidate.get("sample_count", 0))
            # Confidence proxy: sample_count / 10 capped at 1.0 — gives the
            # UI a meaningful "how strong is this pattern" value without
            # introducing a separate dimension.
            confidence = min(1.0, sample_count / 10.0)

            if not self._brightness_context_matches(candidate):
                return None

            row = RuleSuggestion(
                rule_id=None,
                predicted_mode=mode,
                confidence=confidence,
                sample_count=sample_count,
                current_mode_at_fire=mode,
                status="pending",
                kind="brightness",
                payload=_json.dumps(candidate),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            # Augment the standard dict with kind="brightness" + parsed
            # payload so the WS consumer (BrightnessSuggestionCard.svelte)
            # has light_id/mode/period/weather_class/suggested_bri to render.
            # _suggestion_to_dict was written for kind="mode" rows and
            # doesn't include these fields.
            base = _suggestion_to_dict(row)
            base["kind"] = "brightness"
            try:
                base["payload"] = _json.loads(row.payload) if row.payload else {}
            except Exception:
                base["payload"] = {}
            return base

    async def accept_brightness_suggestion(
        self,
        suggestion_id: int,
        remote: str = "unknown",
    ) -> Optional[dict[str, Any]]:
        """Resolve a specific brightness suggestion as accepted.

        Returns the resolved row (with parsed payload) on success, None if
        the row is missing, already-resolved, or wrong kind. Caller writes
        the learned pref through LightingLearner.write_learned_pref.
        """
        import json as _json

        now_utc = datetime.now(timezone.utc)
        async with async_session() as session:
            row = (await session.execute(
                select(RuleSuggestion).where(
                    RuleSuggestion.id == suggestion_id,
                    RuleSuggestion.kind == "brightness",
                    RuleSuggestion.status == "pending",
                )
            )).scalar_one_or_none()
            if row is None:
                return None
            payload = {}
            if row.payload:
                try:
                    payload = _json.loads(row.payload)
                except Exception:
                    payload = {}

            if not self._brightness_context_matches(payload):
                result = await session.execute(
                    update(RuleSuggestion)
                    .where(
                        RuleSuggestion.id == suggestion_id,
                        RuleSuggestion.status == "pending",
                    )
                    .values(
                        status="expired",
                        resolved_at=now_utc,
                        resolved_source=f"context_mismatch:{remote}",
                    )
                )
                await session.commit()
                if result.rowcount == 0:
                    return None
                await self._broadcast_brightness_dismissed(suggestion_id)
                return {
                    "id": suggestion_id,
                    "kind": "brightness",
                    "status": "expired",
                    "payload": payload,
                    "resolved_at": now_utc.isoformat(),
                }

            result = await session.execute(
                update(RuleSuggestion)
                .where(
                    RuleSuggestion.id == suggestion_id,
                    RuleSuggestion.status == "pending",
                )
                .values(
                    status="accepted",
                    resolved_at=now_utc,
                    resolved_source=f"user_accept:{remote}",
                )
            )
            await session.commit()
            if result.rowcount == 0:
                return None

        # Drop the dashboard card (other WS clients also clear).
        await self._broadcast_brightness_dismissed(row.id)

        return {
            "id": row.id,
            "kind": "brightness",
            "status": "accepted",
            "payload": payload,
            "resolved_at": now_utc.isoformat(),
        }

    async def scan_and_emit_brightness_suggestions(self) -> int:
        """Run the LightingLearner scanner, persist candidates as suggestions,
        and fire notifications for each new row.

        Returns the number of new suggestions emitted (0 if nothing fresh
        to surface — e.g. all candidates already pending or already learned).
        Called from the hourly background loop.
        """
        if not self._lighting_learner:
            return 0
        try:
            candidates = await self._lighting_learner.scan_for_suggestions()
        except Exception:
            logger.exception("LightingLearner scan_for_suggestions failed")
            self._last_brightness_scan = {
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "candidate_count": 0,
                "emitted_count": 0,
                "duplicate_count": 0,
                "rejection_counts": {},
                "last_error": "scan_for_suggestions failed",
            }
            return 0

        learner_scan = {}
        if hasattr(self._lighting_learner, "get_last_suggestion_scan_status"):
            try:
                learner_scan = self._lighting_learner.get_last_suggestion_scan_status()
            except Exception:
                learner_scan = {}

        emitted = 0
        duplicate_count = 0
        for candidate in candidates:
            try:
                row = await self.emit_brightness_suggestion(candidate)
            except Exception:
                logger.exception(
                    "emit_brightness_suggestion failed for candidate=%r",
                    candidate,
                )
                continue
            if not row:
                if self._brightness_context_matches(candidate):
                    duplicate_count += 1
                continue  # duplicate of an already-pending bucket or inactive context
            emitted += 1

            # Broadcast a WS event so the dashboard's BrightnessSuggestionCard
            # can render without waiting for the next reconnect or poll.
            try:
                await self._ws_manager.broadcast("brightness_suggestion", row)
            except Exception:
                logger.exception("brightness_suggestion WS broadcast failed")

            # Fire the notification (desktop toast + iPhone push). Failure
            # is non-fatal — the row stays pending and the dashboard banner
            # is the secondary surface.
            if self._notifier:
                try:
                    body = self._format_brightness_body(candidate)
                    accept_url = (
                        f"{self._public_base_url}"
                        f"/api/rules/brightness-suggestion/accept/{row['id']}"
                    )
                    dismiss_url = (
                        f"{self._public_base_url}"
                        f"/api/rules/brightness-suggestion/dismiss/{row['id']}"
                    )
                    await self._notifier.emit_suggestion(
                        suggestion_id=row["id"],
                        title="Brightness preference?",
                        body=body,
                        accept_url=accept_url,
                        dismiss_url=dismiss_url,
                        api_key=self._api_key,
                        extra={"payload": candidate},
                    )
                except Exception:
                    logger.exception(
                        "NotifierService.emit_suggestion failed sid=%d",
                        row["id"],
                    )

        self._last_brightness_scan = {
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "candidate_count": len(candidates),
            "emitted_count": emitted,
            "duplicate_count": duplicate_count,
            "rejection_counts": learner_scan.get("rejection_counts", {}),
        }
        if emitted:
            logger.info(
                "Emitted %d brightness suggestion(s) from %d candidate(s)",
                emitted, len(candidates),
            )
        return emitted

    @staticmethod
    def _format_brightness_body(candidate: dict[str, Any]) -> str:
        """Render a human-readable suggestion body for the notification.

        bri values are stored in Hue 0-254 scale; we present them as 0-100%
        for the user. Dropping the "Ã— base" multiplier here — when the
        engine default is small (kitchen pair=22, relax late_night=10) the
        ratio reads as alarmingly large for what's actually a sensible
        change. Absolute target + default conveys the same info without
        the math-shock.
        """
        mode = candidate.get("mode", "?")
        period = candidate.get("period", "?")
        weather = candidate.get("weather_class", "?")
        light_id = candidate.get("light_id", "?")
        room = candidate.get("room")
        bri = candidate.get("suggested_bri")
        base = candidate.get("base_bri")
        n = candidate.get("sample_count", 0)
        days = candidate.get("distinct_days")
        evidence = (
            f"{n} observations across {days} days"
            if days else f"{n} observations"
        )

        def _pct(v: Any) -> str:
            try:
                return f"{round(int(v) / 254 * 100)}%"
            except (TypeError, ValueError):
                return "?"

        if candidate.get("scope") == "room" and room:
            target = candidate.get("target_pct")
            target_str = f"{target}%" if target is not None else _pct(bri)
            label = str(room).replace("_", " ")
            return (
                f"{label.title()} {mode}/{period} has been landing around "
                f"~{target_str} during {weather} ({evidence}). "
                f"Apply this now and remember it for similar moments?"
            )

        bri_str = _pct(bri)
        base_str = f" (default {_pct(base)})" if base else ""
        return (
            f"You've been setting L{light_id} to ~{bri_str}{base_str} "
            f"during {weather} {mode}/{period} ({evidence}). "
            f"Apply this now and remember it for similar moments?"
        )



    async def _broadcast_brightness_dismissed(self, suggestion_id: int) -> None:
        try:
            await self._ws_manager.broadcast(
                "brightness_suggestion_dismissed", {"id": suggestion_id},
            )
        except Exception:
            logger.exception(
                "brightness_suggestion_dismissed broadcast failed sid=%d",
                suggestion_id,
            )

    def _brightness_context_matches(self, payload: dict[str, Any]) -> bool:
        """True only while a brightness suggestion's context is active."""
        automation = self._automation
        if automation is None:
            return False
        expected_mode = payload.get("mode")
        if expected_mode and getattr(automation, "current_mode", None) != expected_mode:
            return False
        get_period = getattr(automation, "get_time_period", None)
        current_period = get_period() if callable(get_period) else None
        if payload.get("period") != current_period:
            return False
        expected_weather = payload.get("weather_class")
        current_weather = getattr(automation, "last_weather_class", None)
        if expected_weather and expected_weather != current_weather:
            return False
        expected_zone = payload.get("zone_at_time")
        if expected_zone:
            latest_zone = getattr(self._presence, "latest_zone", None)
            current_zone = latest_zone() if callable(latest_zone) else None
            if current_zone != expected_zone:
                return False
        return True

    async def brightness_scan_loop(self, interval_seconds: int = 3600) -> None:
        """Periodically scan for new brightness suggestions and emit them.

        Wired into the bootstrap's `tasks` list so shutdown's cancel-and-
        wait path tears it down. Default cadence is hourly — same as the
        rule-engine's overall pulse — but configurable for tests.
        """
        # Stagger the first run so it doesn't race the model-manager load
        # at boot. 60s lets all wiring settle (notifier startup, weather
        # service first poll, etc.).
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return
        while True:
            try:
                await self.scan_and_emit_brightness_suggestions()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("brightness_scan_loop iteration failed")
            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                return

    async def dismiss_brightness_suggestion(
        self,
        suggestion_id: int,
        remote: str = "unknown",
    ) -> Optional[dict[str, Any]]:
        """Resolve a specific brightness suggestion as dismissed.

        Broadcasts `brightness_suggestion_dismissed` whether or not a row
        was actually resolved so all open dashboards drop the card together
        (optimistic-dismiss semantics, matches the mode-suggestion path).
        """
        now_utc = datetime.now(timezone.utc)
        async with async_session() as session:
            result = await session.execute(
                update(RuleSuggestion)
                .where(
                    RuleSuggestion.id == suggestion_id,
                    RuleSuggestion.kind == "brightness",
                    RuleSuggestion.status == "pending",
                )
                .values(
                    status="dismissed",
                    resolved_at=now_utc,
                    resolved_source=f"user_dismiss:{remote}",
                )
            )
            await session.commit()
            resolved = result.rowcount > 0

        try:
            await self._ws_manager.broadcast(
                "brightness_suggestion_dismissed", {"id": suggestion_id},
            )
        except Exception:
            logger.exception(
                "brightness_suggestion_dismissed broadcast failed sid=%d",
                suggestion_id,
            )

        if not resolved:
            return None
        return {"id": suggestion_id, "status": "dismissed"}

    async def _resolve_pending(
        self,
        new_status: str,
        resolved_source: str,
        broadcast_dismiss: bool,
    ) -> Optional[dict[str, Any]]:
        """Shared accept/dismiss path. Race-safe via WHERE status='pending'."""
        now_utc = datetime.now(timezone.utc)
        async with async_session() as session:
            latest = (await session.execute(
                select(RuleSuggestion)
                .where(
                    RuleSuggestion.status == "pending",
                    RuleSuggestion.kind == "mode",
                )
                .order_by(RuleSuggestion.fired_at.desc())
                .limit(1)
            )).scalar_one_or_none()

            resolved_dict: Optional[dict[str, Any]] = None
            if latest is not None:
                result = await session.execute(
                    update(RuleSuggestion)
                    .where(
                        RuleSuggestion.id == latest.id,
                        RuleSuggestion.status == "pending",
                    )
                    .values(
                        status=new_status,
                        resolved_at=now_utc,
                        resolved_source=resolved_source,
                    )
                )
                await session.commit()
                if result.rowcount > 0:
                    resolved_dict = _suggestion_to_dict(latest, override={
                        "status": new_status,
                        "resolved_at": now_utc,
                        "resolved_source": resolved_source,
                    })

        if resolved_dict is not None:
            self._last_suggestion = None

        if broadcast_dismiss:
            await self._ws_manager.broadcast("mode_suggestion_dismissed", {})

        return resolved_dict

    async def _resolve_suggestion_by_id(
        self,
        *,
        suggestion_id: int,
        new_status: str,
        resolved_source: str,
        broadcast_dismiss: bool,
    ) -> Optional[dict[str, Any]]:
        """Shared id-addressed mode suggestion accept/dismiss path."""
        now_utc = datetime.now(timezone.utc)
        async with async_session() as session:
            row = (await session.execute(
                select(RuleSuggestion).where(
                    RuleSuggestion.id == suggestion_id,
                    RuleSuggestion.kind == "mode",
                    RuleSuggestion.status == "pending",
                )
            )).scalar_one_or_none()

            resolved_dict: Optional[dict[str, Any]] = None
            if row is not None:
                result = await session.execute(
                    update(RuleSuggestion)
                    .where(
                        RuleSuggestion.id == suggestion_id,
                        RuleSuggestion.kind == "mode",
                        RuleSuggestion.status == "pending",
                    )
                    .values(
                        status=new_status,
                        resolved_at=now_utc,
                        resolved_source=resolved_source,
                    )
                )
                await session.commit()
                if result.rowcount > 0:
                    resolved_dict = _suggestion_to_dict(row, override={
                        "status": new_status,
                        "resolved_at": now_utc,
                        "resolved_source": resolved_source,
                    })

        cached_id = (self._last_suggestion or {}).get("suggestion_id")
        if resolved_dict is not None and cached_id == suggestion_id:
            self._last_suggestion = None

        if broadcast_dismiss:
            await self._ws_manager.broadcast(
                "mode_suggestion_dismissed", {"id": suggestion_id},
            )

        return resolved_dict

    async def expire_stale_pending(
        self, max_age_minutes: int = SUGGESTION_MAX_AGE_MINUTES,
    ) -> int:
        """Auto-expire pending rows older than the max-age window.

        Called from the 60s automation tick. If any expired row matches
        the in-memory cache, clears it + broadcasts dismissal so the UI
        drops the card.
        """
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(minutes=max_age_minutes)

        async with async_session() as session:
            stale = (await session.execute(
                select(RuleSuggestion).where(
                    RuleSuggestion.status == "pending",
                    RuleSuggestion.fired_at < cutoff,
                )
            )).scalars().all()

            if not stale:
                return 0

            stale_ids = {row.id for row in stale}
            for row in stale:
                row.status = "expired"
                row.resolved_at = now_utc
                row.resolved_source = "auto_expire"
            await session.commit()

        cached_id = (self._last_suggestion or {}).get("suggestion_id")
        if cached_id is not None and cached_id in stale_ids:
            self._last_suggestion = None
            await self._ws_manager.broadcast("mode_suggestion_dismissed", {})

        logger.info("Expired %d stale rule suggestion(s)", len(stale_ids))
        return len(stale_ids)

    async def restore_pending_on_boot(
        self, max_age_minutes: int = SUGGESTION_MAX_AGE_MINUTES,
    ) -> None:
        """Re-broadcast the latest pending suggestion after a restart.

        Mirrors `automation.load_override_state()` — without this a deploy
        mid-suggestion would drop the in-memory `_last_suggestion` and
        the kiosk would lose the card on WS reconnect. If the latest
        pending row is older than the max-age window, it's expired in-
        place instead.
        """
        async with async_session() as session:
            latest = (await session.execute(
                select(RuleSuggestion)
                .where(
                    RuleSuggestion.status == "pending",
                    RuleSuggestion.kind == "mode",
                )
                .order_by(RuleSuggestion.fired_at.desc())
                .limit(1)
            )).scalar_one_or_none()

        if latest is None:
            return

        age = datetime.now(timezone.utc) - _as_utc(latest.fired_at)
        if age > timedelta(minutes=max_age_minutes):
            await self.expire_stale_pending(max_age_minutes=max_age_minutes)
            return

        pct = round(latest.confidence * 100)
        suggestion = {
            "suggestion_id": latest.id,
            "rule_id": latest.rule_id,
            "predicted_mode": latest.predicted_mode,
            "confidence": pct,
            "sample_count": latest.sample_count,
            "message": (
                f"You're usually in {latest.predicted_mode} mode around this time "
                f"({pct}% confidence from {latest.sample_count} observations)"
            ),
        }
        self._last_suggestion = suggestion
        await self._ws_manager.broadcast("mode_suggestion", suggestion)

        logger.info(
            "Restored pending suggestion %d (%s) on boot",
            latest.id, latest.predicted_mode,
        )

    async def get_suggestion_history(
        self, status: Optional[str] = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent suggestion fires, newest first. Backs GET /suggestions."""
        limit = max(1, min(int(limit), 200))
        async with async_session() as session:
            stmt = select(RuleSuggestion).order_by(RuleSuggestion.fired_at.desc()).limit(limit)
            if status:
                stmt = select(RuleSuggestion).where(
                    RuleSuggestion.status == status,
                ).order_by(RuleSuggestion.fired_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()

        return [_suggestion_to_dict(r) for r in rows]

    async def get_latest_pending(self) -> Optional[dict[str, Any]]:
        """Latest pending row as dict, or None. Used by GET /api/rules/status."""
        async with async_session() as session:
            latest = (await session.execute(
                select(RuleSuggestion)
                .where(
                    RuleSuggestion.status == "pending",
                    RuleSuggestion.kind == "mode",
                )
                .order_by(RuleSuggestion.fired_at.desc())
                .limit(1)
            )).scalar_one_or_none()

        return _suggestion_to_dict(latest) if latest is not None else None

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Health entry for the /health ml block.

        The rule engine is intrinsically data-gated — it only exists
        when enough activity history has accumulated to clear
        ``min_confidence`` Ã— ``min_samples`` thresholds. So we report
        ``status="shadow"`` until rules exist; absence of rules is not
        a failure. Generation-loop wedges are caught separately by the
        heartbeat surface (``tasks.rule_engine``).
        """
        return {
            "status": "shadow",
            "model_loaded": True,
            "last_predict_at": None,
            "consecutive_failures": 0,
            "last_failure": None,
            "active_cooldowns": len(self._cooldowns),
            "has_pending_suggestion": self._last_suggestion is not None,
            "brightness_scan": dict(self._last_brightness_scan),
        }

    async def run_generation_loop(self) -> None:
        """Background task — regenerates rules every 6 hours."""
        logger.info("Rule engine started (regenerating every %dh)", GENERATION_INTERVAL_HOURS)

        while True:
            try:
                if self._heartbeat is not None:
                    self._heartbeat.tick("rule_engine")
                await self.regenerate_rules()
            except asyncio.CancelledError:
                logger.info("Rule engine stopped")
                break
            except Exception as e:
                logger.error("Rule generation failed: %s", e, exc_info=True)

            await asyncio.sleep(GENERATION_INTERVAL_HOURS * 3600)
