"""
Tests for the rule engine — rule generation, checking, CRUD, suggestions.

Uses in-memory SQLite with seeded activity events.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models import ActivityEvent, Base, LearnedRule
from backend.services.rule_engine_service import RuleEngineService

TZ = ZoneInfo("America/Indiana/Indianapolis")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class MockWS:
    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, msg_type, data):
        self.broadcasts.append((msg_type, data))


@pytest.fixture
async def db_and_service(monkeypatch):
    """In-memory DB with predictable activity events + RuleEngineService."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("backend.services.rule_engine_service.async_session", session_factory)

    now = datetime.now(timezone.utc)
    local_now = now.astimezone(TZ)

    async with session_factory() as session:
        # Strong pattern: gaming on current weekday at current hour (5 events)
        for i in range(5):
            ts = now - timedelta(weeks=i)
            session.add(ActivityEvent(
                timestamp=ts, mode="gaming", previous_mode="idle",
                source="process", duration_seconds=3600,
            ))

        # Weak pattern: mixed modes at hour+1 (no clear winner)
        next_hour = now.replace(minute=0, second=0) + timedelta(hours=1)
        for i, mode in enumerate(["working", "gaming", "relax", "watching"]):
            session.add(ActivityEvent(
                timestamp=next_hour - timedelta(weeks=i),
                mode=mode, previous_mode="idle",
                source="process", duration_seconds=1800,
            ))

        # Idle-only pattern at hour+2 (should be excluded)
        idle_hour = now.replace(minute=0, second=0) + timedelta(hours=2)
        for i in range(4):
            session.add(ActivityEvent(
                timestamp=idle_hour - timedelta(weeks=i),
                mode="idle", previous_mode="away",
                source="process", duration_seconds=600,
            ))

        await session.commit()

    ws = MockWS()
    service = RuleEngineService(ws_manager=ws, min_confidence=0.70, min_samples=3)
    yield engine, service, ws, session_factory
    await engine.dispose()


# ---------------------------------------------------------------------------
# Rule generation
# ---------------------------------------------------------------------------

class TestRuleGeneration:
    """Test regenerate_rules() pattern detection."""

    async def test_generates_rule_from_clear_pattern(self, db_and_service):
        _, service, _, session_factory = db_and_service
        stats = await service.regenerate_rules()
        assert stats["created"] >= 1

        rules = await service.get_rules()
        gaming_rules = [r for r in rules if r["predicted_mode"] == "gaming"]
        assert len(gaming_rules) >= 1
        assert gaming_rules[0]["confidence"] >= 70

    async def test_skips_low_confidence_slots(self, db_and_service):
        _, service, _, _ = db_and_service
        await service.regenerate_rules()
        rules = await service.get_rules()
        # The mixed-mode slot (25% each) should NOT produce a rule
        confidences = [r["confidence"] for r in rules]
        assert all(c >= 70 for c in confidences)

    async def test_excludes_idle_away_predictions(self, db_and_service):
        _, service, _, _ = db_and_service
        await service.regenerate_rules()
        rules = await service.get_rules()
        modes = [r["predicted_mode"] for r in rules]
        assert "idle" not in modes
        assert "away" not in modes

    async def test_upsert_on_regenerate(self, db_and_service):
        _, service, _, _ = db_and_service
        await service.regenerate_rules()
        rules_first = await service.get_rules()
        await service.regenerate_rules()
        rules_second = await service.get_rules()
        # Same number of rules (upserted, not duplicated)
        assert len(rules_first) == len(rules_second)

    async def test_idle_events_do_not_dilute_confidence(self, db_and_service):
        """Idle/away events in a slot shouldn't push non-skip modes below the
        confidence threshold (regression: live data had working=3, idle=10 in
        the same bucket and no rule generated because 3/13 = 23%)."""
        _, service, _, session_factory = db_and_service
        now = datetime.now(timezone.utc)
        target = now.replace(minute=30, second=0, microsecond=0) + timedelta(hours=5)
        async with session_factory() as session:
            for i in range(3):
                session.add(ActivityEvent(
                    timestamp=target - timedelta(weeks=i),
                    mode="working", previous_mode="idle",
                    source="process", duration_seconds=3600,
                ))
            for i in range(10):
                session.add(ActivityEvent(
                    timestamp=target - timedelta(weeks=i, seconds=(i + 1) * 2),
                    mode="idle", previous_mode="working",
                    source="process", duration_seconds=60,
                ))
            await session.commit()

        await service.regenerate_rules()
        rules = await service.get_rules()
        local_target = target.astimezone(TZ)
        matching = [
            r for r in rules
            if r["day_of_week"] == local_target.weekday() and r["hour"] == local_target.hour
        ]
        assert len(matching) == 1
        assert matching[0]["predicted_mode"] == "working"
        assert matching[0]["confidence"] == 100  # 3 working / 3 non-skip = 100%
        assert matching[0]["sample_count"] == 3  # skip modes excluded from count

    async def test_ambient_noise_downweighted_so_process_signal_wins(self, db_and_service):
        """Per-source weighting should let a process-driven working signal
        cross the confidence threshold even with ambient noise in the slot.
        Raw: 10 working / 17 = 59%, no rule. Weighted: 10.0 / (10.0 + 3.5) =
        74%, rule fires. Regression from live bug where ambient=social events
        flooded working buckets and no rules formed outside Monday mornings."""
        _, service, _, session_factory = db_and_service
        now = datetime.now(timezone.utc)
        target = now.replace(minute=30, second=0, microsecond=0) + timedelta(hours=6)
        async with session_factory() as session:
            # 10 process=working events (weighted 10.0)
            for i in range(10):
                session.add(ActivityEvent(
                    timestamp=target - timedelta(seconds=i * 5),
                    mode="working", previous_mode="idle",
                    source="process", duration_seconds=5,
                ))
            # 7 ambient=social events (weighted 3.5 — raw count would pull
            # working confidence below 70%, weighted keeps it above)
            for i in range(7):
                session.add(ActivityEvent(
                    timestamp=target - timedelta(seconds=i * 3 + 1),
                    mode="social", previous_mode="idle",
                    source="ambient", duration_seconds=1,
                ))
            await session.commit()

        await service.regenerate_rules()
        rules = await service.get_rules()
        local_target = target.astimezone(TZ)
        matching = [
            r for r in rules
            if r["day_of_week"] == local_target.weekday() and r["hour"] == local_target.hour
        ]
        assert len(matching) == 1
        assert matching[0]["predicted_mode"] == "working"
        assert matching[0]["confidence"] >= 70
        # sample_count is raw event count for non-skip modes: 10 + 7 = 17
        assert matching[0]["sample_count"] == 17

    async def test_deletes_stale_rules(self, db_and_service):
        engine, service, _, session_factory = db_and_service
        await service.regenerate_rules()
        rules_before = await service.get_rules()
        assert len(rules_before) >= 1

        # Delete all activity events so no rules qualify
        async with session_factory() as session:
            from sqlalchemy import delete
            await session.execute(delete(ActivityEvent))
            await session.commit()

        stats = await service.regenerate_rules()
        assert stats["deleted"] >= 1
        rules_after = await service.get_rules()
        assert len(rules_after) == 0


# ---------------------------------------------------------------------------
# Rule checking
# ---------------------------------------------------------------------------

class TestRuleChecking:
    """Test check_rules() nudge behavior."""

    async def test_suggests_when_idle_and_match(self, db_and_service):
        _, service, ws, session_factory = db_and_service

        # Insert a rule for right now (clear any existing for this slot first)
        now = datetime.now(TZ)
        async with session_factory() as session:
            from sqlalchemy import delete
            await session.execute(
                delete(LearnedRule).where(
                    LearnedRule.day_of_week == now.weekday(),
                    LearnedRule.hour == now.hour,
                )
            )
            session.add(LearnedRule(
                day_of_week=now.weekday(), hour=now.hour,
                predicted_mode="gaming", confidence=0.85, sample_count=7,
            ))
            await session.commit()

        result = await service.check_rules("idle")
        assert result is not None
        assert result["predicted_mode"] == "gaming"
        suggestions = [b for b in ws.broadcasts if b[0] == "mode_suggestion"]
        assert len(suggestions) >= 1

    async def test_no_suggestion_when_active(self, db_and_service):
        _, service, _, _ = db_and_service
        result = await service.check_rules("gaming")
        assert result is None

    async def test_cooldown_prevents_repeat(self, db_and_service):
        _, service, ws, session_factory = db_and_service
        now = datetime.now(TZ)
        async with session_factory() as session:
            session.add(LearnedRule(
                day_of_week=now.weekday(), hour=now.hour,
                predicted_mode="working", confidence=0.80, sample_count=5,
            ))
            await session.commit()

        first = await service.check_rules("idle")
        assert first is not None
        second = await service.check_rules("idle")
        assert second is None  # cooldown

    async def test_no_suggestion_for_disabled_rule(self, db_and_service):
        _, service, _, session_factory = db_and_service
        now = datetime.now(TZ)
        async with session_factory() as session:
            session.add(LearnedRule(
                day_of_week=now.weekday(), hour=now.hour,
                predicted_mode="relax", confidence=0.90, sample_count=10,
                enabled=False,
            ))
            await session.commit()

        result = await service.check_rules("idle")
        assert result is None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestRuleCRUD:
    """Test get/update/delete operations."""

    async def test_get_rules(self, db_and_service):
        _, service, _, session_factory = db_and_service
        async with session_factory() as session:
            session.add(LearnedRule(
                day_of_week=0, hour=10, predicted_mode="working",
                confidence=0.75, sample_count=4,
            ))
            await session.commit()

        rules = await service.get_rules()
        assert len(rules) >= 1
        assert rules[0]["predicted_mode"] == "working"

    async def test_update_rule_toggles(self, db_and_service):
        _, service, _, session_factory = db_and_service
        async with session_factory() as session:
            session.add(LearnedRule(
                day_of_week=1, hour=14, predicted_mode="gaming",
                confidence=0.80, sample_count=5,
            ))
            await session.commit()

        rules = await service.get_rules()
        rule_id = rules[-1]["id"]
        result = await service.update_rule(rule_id, enabled=False)
        assert result["enabled"] is False

    async def test_delete_rule(self, db_and_service):
        _, service, _, session_factory = db_and_service
        async with session_factory() as session:
            session.add(LearnedRule(
                day_of_week=2, hour=8, predicted_mode="working",
                confidence=0.90, sample_count=10,
            ))
            await session.commit()

        rules = await service.get_rules()
        rule_id = rules[-1]["id"]
        assert await service.delete_rule(rule_id) is True
        assert await service.delete_rule(rule_id) is False  # already gone


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

class TestSuggestions:
    """Test accept/dismiss suggestion flow."""

    async def test_accept_returns_suggestion(self, db_and_service):
        _, service, _, _ = db_and_service
        service._last_suggestion = {"predicted_mode": "gaming", "rule_id": 1}
        result = await service.accept_suggestion()
        assert result["predicted_mode"] == "gaming"
        assert service.last_suggestion is None

    async def test_accept_none_when_empty(self, db_and_service):
        _, service, _, _ = db_and_service
        result = await service.accept_suggestion()
        assert result is None

    async def test_dismiss_clears_and_broadcasts(self, db_and_service):
        _, service, ws, _ = db_and_service
        service._last_suggestion = {"predicted_mode": "relax"}
        await service.dismiss_suggestion()
        assert service.last_suggestion is None
        dismissed = [b for b in ws.broadcasts if b[0] == "mode_suggestion_dismissed"]
        assert len(dismissed) == 1
