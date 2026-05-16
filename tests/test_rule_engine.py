"""
Tests for the rule engine — rule generation, checking, CRUD, suggestions.

Uses in-memory SQLite with seeded activity events.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models import ActivityEvent, Base, LearnedRule, RuleSuggestion
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

    # Tests run at unpredictable wall-clock times — clear the office-hours
    # blackout so existing time-sensitive tests don't depend on what hour
    # of what day pytest happens to fire. Blackout behavior gets its own
    # tests below.
    monkeypatch.setattr(
        "backend.services.rule_engine_service._BLACKOUT_SLOTS", frozenset()
    )

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
                mode="idle", previous_mode="working",
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

    async def test_excludes_idle_predictions(self, db_and_service):
        _, service, _, _ = db_and_service
        await service.regenerate_rules()
        rules = await service.get_rules()
        modes = [r["predicted_mode"] for r in rules]
        assert "idle" not in modes

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

async def _seed_rule(session_factory, predicted_mode: str = "gaming") -> int:
    """Insert a LearnedRule + return its id. Day/hour are arbitrary; FK only."""
    async with session_factory() as session:
        rule = LearnedRule(
            day_of_week=0, hour=12, predicted_mode=predicted_mode,
            confidence=0.85, sample_count=7,
        )
        session.add(rule)
        await session.commit()
        return rule.id


async def _seed_pending(
    session_factory, rule_id: int,
    predicted_mode: str = "gaming",
    fired_at: datetime | None = None,
) -> int:
    """Insert a pending RuleSuggestion + return its id."""
    if fired_at is None:
        fired_at = datetime.now(timezone.utc)
    async with session_factory() as session:
        row = RuleSuggestion(
            rule_id=rule_id, fired_at=fired_at, predicted_mode=predicted_mode,
            confidence=0.85, sample_count=7, current_mode_at_fire="idle",
            status="pending",
        )
        session.add(row)
        await session.commit()
        return row.id


class TestSuggestions:
    """Test accept/dismiss suggestion flow (DB-backed)."""

    async def test_accept_returns_suggestion(self, db_and_service):
        _, service, _, session_factory = db_and_service
        rule_id = await _seed_rule(session_factory)
        sug_id = await _seed_pending(session_factory, rule_id)
        service._last_suggestion = {"suggestion_id": sug_id, "predicted_mode": "gaming"}

        result = await service.accept_suggestion(remote="1.2.3.4")
        assert result is not None
        assert result["predicted_mode"] == "gaming"
        assert result["status"] == "accepted"
        assert result["resolved_source"] == "user_accept:1.2.3.4"
        assert service.last_suggestion is None

    async def test_accept_none_when_empty(self, db_and_service):
        _, service, _, _ = db_and_service
        result = await service.accept_suggestion()
        assert result is None

    async def test_accept_none_when_already_resolved(self, db_and_service):
        """Second click loses the race (rowcount=0) → None (route maps to 410)."""
        _, service, _, session_factory = db_and_service
        rule_id = await _seed_rule(session_factory)
        sug_id = await _seed_pending(session_factory, rule_id)

        first = await service.accept_suggestion(remote="1.2.3.4")
        assert first is not None
        second = await service.accept_suggestion(remote="1.2.3.4")
        assert second is None  # already accepted; no pending row to find

    async def test_dismiss_clears_and_broadcasts(self, db_and_service):
        _, service, ws, session_factory = db_and_service
        rule_id = await _seed_rule(session_factory, predicted_mode="relax")
        await _seed_pending(session_factory, rule_id, predicted_mode="relax")
        service._last_suggestion = {"predicted_mode": "relax"}

        result = await service.dismiss_suggestion(remote="1.2.3.4")
        assert result is not None
        assert result["status"] == "dismissed"
        assert result["resolved_source"] == "user_dismiss:1.2.3.4"
        assert service.last_suggestion is None
        dismissed = [b for b in ws.broadcasts if b[0] == "mode_suggestion_dismissed"]
        assert len(dismissed) == 1

    async def test_dismiss_broadcasts_even_on_noop(self, db_and_service):
        """No pending row to dismiss — UI's optimistic dismiss should still settle."""
        _, service, ws, _ = db_and_service
        result = await service.dismiss_suggestion(remote="1.2.3.4")
        assert result is None
        dismissed = [b for b in ws.broadcasts if b[0] == "mode_suggestion_dismissed"]
        assert len(dismissed) == 1


class TestSuggestionPersistence:
    """Test the rule_suggestions table-backed lifecycle."""

    async def test_check_rules_inserts_pending_row(self, db_and_service):
        _, service, ws, session_factory = db_and_service
        now = datetime.now(TZ)
        async with session_factory() as session:
            session.add(LearnedRule(
                day_of_week=now.weekday(), hour=now.hour,
                predicted_mode="gaming", confidence=0.85, sample_count=7,
            ))
            await session.commit()

        result = await service.check_rules("idle")
        assert result is not None
        assert "suggestion_id" in result

        history = await service.get_suggestion_history()
        assert len(history) == 1
        assert history[0]["status"] == "pending"
        assert history[0]["predicted_mode"] == "gaming"
        assert history[0]["sample_count"] == 7
        assert history[0]["current_mode_at_fire"] == "idle"
        assert history[0]["confidence"] == 85  # percent in serialized payload

    async def test_supersede_marks_earlier_pending(self, db_and_service):
        """Two pending rows can't coexist — earlier one gets superseded."""
        _, service, _, session_factory = db_and_service
        rule_id_a = await _seed_rule(session_factory, predicted_mode="working")
        first_id = await _seed_pending(
            session_factory, rule_id_a, predicted_mode="working",
        )

        # Inject a second rule for now's slot to force a fresh fire
        now = datetime.now(TZ)
        async with session_factory() as session:
            session.add(LearnedRule(
                day_of_week=now.weekday(), hour=now.hour,
                predicted_mode="relax", confidence=0.90, sample_count=10,
            ))
            await session.commit()

        result = await service.check_rules("idle")
        assert result is not None
        new_id = result["suggestion_id"]

        history = await service.get_suggestion_history()
        first_row = next(h for h in history if h["id"] == first_id)
        new_row = next(h for h in history if h["id"] == new_id)
        assert first_row["status"] == "superseded"
        assert first_row["resolved_source"] == f"superseded_by:{new_id}"
        assert new_row["status"] == "pending"

    async def test_expire_stale_pending_marks_old_rows(self, db_and_service):
        _, service, ws, session_factory = db_and_service
        rule_id = await _seed_rule(session_factory)
        old_fired = datetime.now(timezone.utc) - timedelta(minutes=90)
        sug_id = await _seed_pending(session_factory, rule_id, fired_at=old_fired)
        service._last_suggestion = {"suggestion_id": sug_id, "predicted_mode": "gaming"}

        count = await service.expire_stale_pending()
        assert count == 1
        assert service.last_suggestion is None

        history = await service.get_suggestion_history()
        assert history[0]["status"] == "expired"
        assert history[0]["resolved_source"] == "auto_expire"

        dismissed = [b for b in ws.broadcasts if b[0] == "mode_suggestion_dismissed"]
        assert len(dismissed) == 1

    async def test_expire_skips_fresh_pending(self, db_and_service):
        _, service, ws, session_factory = db_and_service
        rule_id = await _seed_rule(session_factory)
        fresh_fired = datetime.now(timezone.utc) - timedelta(minutes=30)
        await _seed_pending(session_factory, rule_id, fired_at=fresh_fired)

        count = await service.expire_stale_pending()
        assert count == 0
        history = await service.get_suggestion_history()
        assert history[0]["status"] == "pending"
        dismissed = [b for b in ws.broadcasts if b[0] == "mode_suggestion_dismissed"]
        assert len(dismissed) == 0

    async def test_restore_pending_on_boot_rebroadcasts(self, db_and_service):
        _, service, ws, session_factory = db_and_service
        rule_id = await _seed_rule(session_factory, predicted_mode="working")
        fresh_fired = datetime.now(timezone.utc) - timedelta(minutes=5)
        await _seed_pending(
            session_factory, rule_id, predicted_mode="working", fired_at=fresh_fired,
        )

        await service.restore_pending_on_boot()
        broadcasts = [b for b in ws.broadcasts if b[0] == "mode_suggestion"]
        assert len(broadcasts) == 1
        payload = broadcasts[0][1]
        assert payload["predicted_mode"] == "working"
        assert payload["confidence"] == 85
        assert service.last_suggestion is not None
        assert service.last_suggestion["predicted_mode"] == "working"

    async def test_restore_expires_stale_on_boot(self, db_and_service):
        _, service, ws, session_factory = db_and_service
        rule_id = await _seed_rule(session_factory)
        old_fired = datetime.now(timezone.utc) - timedelta(minutes=120)
        await _seed_pending(session_factory, rule_id, fired_at=old_fired)

        await service.restore_pending_on_boot()
        broadcasts = [b for b in ws.broadcasts if b[0] == "mode_suggestion"]
        assert len(broadcasts) == 0  # stale → expire path, no re-broadcast

        history = await service.get_suggestion_history()
        assert history[0]["status"] == "expired"

    async def test_restore_noop_when_no_pending(self, db_and_service):
        _, service, ws, _ = db_and_service
        await service.restore_pending_on_boot()
        assert len(ws.broadcasts) == 0
        assert service.last_suggestion is None

    async def test_get_suggestion_history_filters_and_paginates(self, db_and_service):
        _, service, _, session_factory = db_and_service
        rule_id = await _seed_rule(session_factory)
        base = datetime.now(timezone.utc)
        async with session_factory() as session:
            for i in range(20):
                status = "accepted" if i % 2 == 0 else "dismissed"
                session.add(RuleSuggestion(
                    rule_id=rule_id, fired_at=base - timedelta(minutes=i),
                    predicted_mode="gaming", confidence=0.85, sample_count=7,
                    status=status, resolved_at=base,
                    resolved_source=f"user_{status}:test",
                ))
            await session.commit()

        accepted = await service.get_suggestion_history(status="accepted", limit=5)
        assert len(accepted) == 5
        assert all(h["status"] == "accepted" for h in accepted)
        # Newest first
        fired_at_ts = [h["fired_at"] for h in accepted]
        assert fired_at_ts == sorted(fired_at_ts, reverse=True)

        all_recent = await service.get_suggestion_history(limit=20)
        assert len(all_recent) == 20

    async def test_get_latest_pending_returns_none_when_no_pending(self, db_and_service):
        _, service, _, session_factory = db_and_service
        rule_id = await _seed_rule(session_factory)
        # Seed a resolved row — should NOT count as latest pending
        async with session_factory() as session:
            session.add(RuleSuggestion(
                rule_id=rule_id, predicted_mode="gaming", confidence=0.85,
                sample_count=7, status="accepted",
                resolved_at=datetime.now(timezone.utc),
                resolved_source="user_accept:test",
            ))
            await session.commit()

        assert await service.get_latest_pending() is None

    async def test_get_latest_pending_returns_newest_pending(self, db_and_service):
        _, service, _, session_factory = db_and_service
        rule_id = await _seed_rule(session_factory)
        await _seed_pending(
            session_factory, rule_id,
            fired_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        newer_id = await _seed_pending(
            session_factory, rule_id,
            fired_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        latest = await service.get_latest_pending()
        assert latest is not None
        assert latest["id"] == newer_id


# ---------------------------------------------------------------------------
# Blackout slots (M-F 8am-4:59pm = at the office)
# ---------------------------------------------------------------------------

class TestBlackoutSlots:
    """Office-hour blackout: don't predict during M-F 8am-5pm."""

    async def test_check_rules_returns_none_in_blackout(
        self, db_and_service, monkeypatch
    ):
        _, service, _, session_factory = db_and_service
        # Re-enable the blackout (cleared by the global fixture). Pin "now"
        # to a known blackout slot: Wednesday 10am local.
        monkeypatch.setattr(
            "backend.services.rule_engine_service._BLACKOUT_SLOTS",
            frozenset({(2, 10)}),
        )

        class FakeNow:
            @staticmethod
            def now(tz=None):
                # Wednesday 10:00 local
                return datetime(2026, 4, 29, 10, 0, tzinfo=TZ)

        monkeypatch.setattr(
            "backend.services.rule_engine_service.datetime", FakeNow
        )

        async with session_factory() as session:
            session.add(LearnedRule(
                day_of_week=2, hour=10, predicted_mode="working",
                confidence=0.95, sample_count=20,
            ))
            await session.commit()

        result = await service.check_rules("idle")
        assert result is None

    async def test_regenerate_skips_blackout_slots(
        self, db_and_service, monkeypatch, session_factory_capture=None
    ):
        _, service, _, session_factory = db_and_service
        monkeypatch.setattr(
            "backend.services.rule_engine_service._BLACKOUT_SLOTS",
            frozenset({(1, 10)}),  # Tuesday 10am
        )

        # Seed a strong working pattern at Tuesday 10am local.
        async with session_factory() as session:
            for i in range(5):
                # Tuesday 2026-04-21 + N weeks earlier, 10am local
                base = datetime(2026, 4, 21, 10, 30, tzinfo=TZ)
                ts = (base - timedelta(weeks=i)).astimezone(timezone.utc)
                session.add(ActivityEvent(
                    timestamp=ts, mode="working", previous_mode="idle",
                    source="process", duration_seconds=3600,
                ))
            await session.commit()

        await service.regenerate_rules()
        rules = await service.get_rules()
        # No rule should exist for Tue 10am (blackout)
        blackout_rules = [
            r for r in rules if r["day_of_week"] == 1 and r["hour"] == 10
        ]
        assert blackout_rules == []


# ---------------------------------------------------------------------------
# ml_logger integration + VALID_MODES guard
# ---------------------------------------------------------------------------

class TestMLLoggerIntegration:
    """rule_engine writes a per-lane row to ml_decisions on each match."""

    async def test_log_decision_called_on_match(self, db_and_service):
        _, _, ws, session_factory = db_and_service

        class MockMLLogger:
            def __init__(self):
                self.calls = []

            async def log_decision(self, **kwargs):
                self.calls.append(kwargs)
                return 1

        mock_logger = MockMLLogger()
        service = RuleEngineService(
            ws_manager=ws,
            min_confidence=0.70,
            min_samples=3,
            ml_logger=mock_logger,
        )

        now = datetime.now(TZ)
        async with session_factory() as session:
            session.add(LearnedRule(
                day_of_week=now.weekday(), hour=now.hour,
                predicted_mode="watching", confidence=0.85, sample_count=8,
            ))
            await session.commit()

        await service.check_rules("idle")
        assert len(mock_logger.calls) == 1
        call = mock_logger.calls[0]
        assert call["decision_source"] == "rule_engine"
        assert call["predicted_mode"] == "watching"
        assert call["applied"] is False
        assert call["broadcast"] is False

    async def test_skips_rule_with_retired_mode(self, db_and_service):
        """Rule predicting a mode no longer in VALID_MODES (e.g. legacy
        `away`) must not vote — fusion would silently reject it anyway."""
        _, _, ws, session_factory = db_and_service

        class MockFusion:
            def __init__(self):
                self.signals = []

            def report_signal(self, *args, **kwargs):
                self.signals.append((args, kwargs))

        class MockMLLogger:
            def __init__(self):
                self.calls = []

            async def log_decision(self, **kwargs):
                self.calls.append(kwargs)
                return 1

        mock_fusion = MockFusion()
        mock_logger = MockMLLogger()
        service = RuleEngineService(
            ws_manager=ws,
            confidence_fusion=mock_fusion,
            ml_logger=mock_logger,
        )

        now = datetime.now(TZ)
        async with session_factory() as session:
            session.add(LearnedRule(
                day_of_week=now.weekday(), hour=now.hour,
                predicted_mode="away", confidence=0.95, sample_count=12,
            ))
            await session.commit()

        result = await service.check_rules("idle")
        assert result is None
        assert mock_fusion.signals == []
        assert mock_logger.calls == []

    async def test_regenerate_drops_retired_mode_rows(self, db_and_service):
        """Activity events with retired modes (away) must not seed rules."""
        _, service, _, session_factory = db_and_service
        now = datetime.now(timezone.utc)
        target = now.replace(minute=30, second=0, microsecond=0) + timedelta(hours=7)
        async with session_factory() as session:
            for i in range(8):
                session.add(ActivityEvent(
                    timestamp=target - timedelta(weeks=i),
                    mode="away", previous_mode="idle",
                    source="process", duration_seconds=3600,
                ))
            await session.commit()

        await service.regenerate_rules()
        rules = await service.get_rules()
        modes = [r["predicted_mode"] for r in rules]
        assert "away" not in modes
