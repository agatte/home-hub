"""
Tests for the event query service — summary, patterns, timeline, pagination.

Uses in-memory SQLite with seeded event data. Does not test via HTTP
(that's covered by test_api_routes.py) — tests the service layer directly.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models import ActivityEvent, Base, LightAdjustment, SceneActivation, SonosPlaybackEvent
from backend.services.event_query_service import EventQueryService, _since


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def seeded_db(monkeypatch):
    """Create an in-memory DB with event data and patch async_session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        # Activity events — spread over last 7 days
        for i in range(10):
            session.add(ActivityEvent(
                timestamp=now - timedelta(days=i % 7, hours=i),
                mode="working" if i % 3 == 0 else "gaming" if i % 3 == 1 else "idle",
                previous_mode="idle",
                source="process" if i % 2 == 0 else "manual",
                duration_seconds=3600 if i < 8 else None,
            ))

        # Light adjustments
        for i in range(5):
            session.add(LightAdjustment(
                timestamp=now - timedelta(hours=i * 2),
                light_id="1" if i < 3 else "2",
                light_name="Living Room" if i < 3 else "Bedroom",
                bri_before=100, bri_after=200,
                mode_at_time="working",
                trigger="ws" if i < 4 else "rest",
            ))

        # Sonos events
        for i in range(4):
            session.add(SonosPlaybackEvent(
                timestamp=now - timedelta(hours=i * 3),
                event_type="auto_play" if i < 2 else "pause",
                favorite_title="Lo-Fi Beats" if i < 2 else None,
                mode_at_time="working",
                triggered_by="auto" if i < 2 else "manual",
            ))

        # Scene activations
        for i in range(3):
            session.add(SceneActivation(
                timestamp=now - timedelta(hours=i * 4),
                scene_id="deep_focus",
                scene_name="Deep Focus",
                source="preset",
                mode_at_time="working",
            ))

        await session.commit()

    monkeypatch.setattr("backend.services.event_query_service.async_session", session_factory)
    yield engine
    await engine.dispose()


@pytest.fixture
def service():
    return EventQueryService()


# ---------------------------------------------------------------------------
# _since helper
# ---------------------------------------------------------------------------

class TestSince:
    """Test the _since helper."""

    def test_returns_datetime_in_past(self):
        result = _since(7)
        assert result < datetime.now(timezone.utc)

    def test_clamps_to_max(self):
        result_90 = _since(90)
        result_100 = _since(100)
        # Both should be ~90 days ago (100 clamped)
        diff = abs((result_90 - result_100).total_seconds())
        assert diff < 2  # within 2 seconds

    def test_clamps_minimum(self):
        result = _since(0)
        # Should be 1 day ago minimum
        expected = datetime.now(timezone.utc) - timedelta(days=1)
        diff = abs((result - expected).total_seconds())
        assert diff < 2


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestSummary:
    """Test get_summary() aggregation."""

    async def test_returns_all_sections(self, seeded_db, service):
        result = await service.get_summary(days=7)
        assert "activity" in result
        assert "lights" in result
        assert "sonos" in result
        assert "scenes" in result
        assert result["period_days"] == 7

    async def test_activity_counts(self, seeded_db, service):
        result = await service.get_summary(days=7)
        activity = result["activity"]
        assert activity["total_transitions"] == 10
        assert "working" in activity["modes"]
        assert "process" in activity["sources"]

    async def test_avg_duration(self, seeded_db, service):
        result = await service.get_summary(days=7)
        avg = result["activity"]["avg_mode_duration_minutes"]
        assert isinstance(avg, dict)
        # Events with duration_seconds=3600 → 60.0 minutes
        for mode, minutes in avg.items():
            assert minutes == 60.0

    async def test_light_stats(self, seeded_db, service):
        result = await service.get_summary(days=7)
        lights = result["lights"]
        assert lights["total_adjustments"] == 5
        assert lights["most_adjusted_light"]["id"] == "1"
        assert lights["most_adjusted_light"]["count"] == 3

    async def test_sonos_stats(self, seeded_db, service):
        result = await service.get_summary(days=7)
        sonos = result["sonos"]
        assert sonos["total_events"] == 4
        assert sonos["by_type"]["auto_play"] == 2
        assert len(sonos["top_favorites"]) >= 1

    async def test_scene_stats(self, seeded_db, service):
        result = await service.get_summary(days=7)
        scenes = result["scenes"]
        assert scenes["total_activations"] == 3
        assert scenes["by_source"]["preset"] == 3


# ---------------------------------------------------------------------------
# Activity history
# ---------------------------------------------------------------------------

class TestActivity:
    """Test get_activity() pagination and filtering."""

    async def test_returns_events(self, seeded_db, service):
        result = await service.get_activity(days=7)
        assert result["total"] == 10
        assert len(result["events"]) == 10

    async def test_filter_by_mode(self, seeded_db, service):
        result = await service.get_activity(days=7, mode="gaming")
        assert all(e["mode"] == "gaming" for e in result["events"])

    async def test_filter_by_source(self, seeded_db, service):
        result = await service.get_activity(days=7, source="manual")
        assert all(e["source"] == "manual" for e in result["events"])

    async def test_pagination(self, seeded_db, service):
        page1 = await service.get_activity(days=7, limit=3, offset=0)
        page2 = await service.get_activity(days=7, limit=3, offset=3)
        assert len(page1["events"]) == 3
        assert len(page2["events"]) == 3
        # Different events
        ids1 = {e["id"] for e in page1["events"]}
        ids2 = {e["id"] for e in page2["events"]}
        assert ids1.isdisjoint(ids2)


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

class TestPatterns:
    """Test get_patterns() analysis."""

    async def test_returns_structure(self, seeded_db, service):
        result = await service.get_patterns(days=30)
        assert "by_hour" in result
        assert "by_day_hour" in result
        assert "overrides" in result

    async def test_overrides_counted(self, seeded_db, service):
        result = await service.get_patterns(days=30)
        overrides = result["overrides"]
        assert overrides["total"] == 5  # 5 events with source="manual"
        assert overrides["override_rate"] == 0.5

    async def test_by_hour_has_entries(self, seeded_db, service):
        result = await service.get_patterns(days=30)
        assert len(result["by_hour"]) > 0
        for entry in result["by_hour"]:
            assert "hour" in entry
            assert "mode" in entry
            assert "pct" in entry


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

class TestTimeline:
    """Test get_timeline() chronological output."""

    async def test_returns_ordered(self, seeded_db, service):
        result = await service.get_timeline(days=7)
        assert len(result) == 10
        # Should be chronological (ascending)
        timestamps = [e["timestamp"] for e in result]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Light and Sonos history
# ---------------------------------------------------------------------------

class TestLightEvents:
    """Test get_light_events()."""

    async def test_returns_events(self, seeded_db, service):
        result = await service.get_light_events(days=7)
        assert result["total"] == 5

    async def test_filter_by_light_id(self, seeded_db, service):
        result = await service.get_light_events(days=7, light_id="2")
        assert all(e["light_id"] == "2" for e in result["events"])


class TestSonosEvents:
    """Test get_sonos_events()."""

    async def test_returns_events(self, seeded_db, service):
        result = await service.get_sonos_events(days=7)
        assert result["total"] == 4

    async def test_filter_by_type(self, seeded_db, service):
        result = await service.get_sonos_events(days=7, event_type="auto_play")
        assert all(e["event_type"] == "auto_play" for e in result["events"])
