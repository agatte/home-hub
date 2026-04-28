"""
Tests for feature_builder — the pure-functional layer that the lighting
learner and behavioral predictor depend on.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import ActivityEvent
from backend.services.ml import feature_builder as fb


class TestGetTimePeriod:
    """Boundary checks against the day/evening/night cutoffs."""

    @pytest.mark.parametrize("hour,expected", [
        (0, "night"),
        (7, "night"),
        (8, "day"),
        (12, "day"),
        (17, "day"),
        (18, "evening"),
        (20, "evening"),
        (21, "night"),
        (23, "night"),
    ])
    def test_boundaries(self, hour, expected):
        ts = datetime(2026, 4, 24, hour, 30, tzinfo=timezone.utc)
        assert fb.get_time_period(ts) == expected


class TestGetSeason:
    @pytest.mark.parametrize("month,expected", [
        (1, "winter"), (2, "winter"), (12, "winter"),
        (3, "spring"), (4, "spring"), (5, "spring"),
        (6, "summer"), (7, "summer"), (8, "summer"),
        (9, "fall"), (10, "fall"), (11, "fall"),
    ])
    def test_each_month(self, month, expected):
        ts = datetime(2026, month, 15, 12, 0, tzinfo=timezone.utc)
        assert fb.get_season(ts) == expected


class TestGetTemporalFeatures:
    def test_shape_and_values(self):
        ts = datetime(2026, 4, 24, 14, 37, tzinfo=timezone.utc)  # Friday
        features = fb.get_temporal_features(ts)
        assert features["hour"] == 14
        assert features["minute_bucket"] == 2  # 37 // 15 = 2
        assert features["day_of_week"] == 4  # Friday
        assert features["is_weekend"] is False
        assert features["season"] == "spring"
        assert features["time_period"] == "day"

    def test_weekend_flag(self):
        sat = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
        assert fb.get_temporal_features(sat)["is_weekend"] is True


class TestBuildCurrentFeatures:
    def test_returns_expected_keys(self):
        features = fb.build_current_features(
            current_mode="working",
            current_mode_duration_s=600,
            transitions_today=3,
            manual_override_count_7d=2,
            minutes_since_wake=120,
        )
        for key in (
            "hour", "minute_bucket", "day_of_week", "is_weekend",
            "season", "time_period",
            "previous_mode", "previous_mode_duration_min",
            "minutes_since_wake", "mode_transitions_today",
            "manual_override_count_7d", "season_enc",
        ):
            assert key in features
        assert features["previous_mode_duration_min"] == 10  # 600s / 60
        assert features["manual_override_count_7d"] == 2
        # Unknown mode falls back to len(MODE_ENCODING) sentinel
        assert features["previous_mode"] == fb.MODE_ENCODING["working"]


@pytest.mark.asyncio
class TestBuildTrainingData:
    async def test_empty_db_returns_empty_list(self, ml_db):
        rows = await fb.build_training_data(days=60)
        assert rows == []

    async def test_seeded_events_produce_rows(self, ml_db):
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            for i in range(5):
                session.add(ActivityEvent(
                    timestamp=now - timedelta(hours=5 - i),
                    mode="working" if i % 2 == 0 else "gaming",
                    previous_mode="idle",
                    source="manual",
                    duration_seconds=600,
                ))
            await session.commit()

        rows = await fb.build_training_data(days=60)
        assert len(rows) == 5
        # Each row must carry the target + temporal + behavioral features.
        for row in rows:
            assert "target" in row
            assert "hour" in row
            assert "previous_mode" in row
            assert "manual_override_count_7d" in row

    async def test_window_filter(self, ml_db):
        """Events older than the window are excluded."""
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            session.add(ActivityEvent(
                timestamp=now - timedelta(days=1),
                mode="working", source="manual",
            ))
            session.add(ActivityEvent(
                timestamp=now - timedelta(days=10),
                mode="gaming", source="manual",
            ))
            await session.commit()

        recent = await fb.build_training_data(days=2)
        assert len(recent) == 1
        assert recent[0]["target"] == "working"

    async def test_naive_timestamp_normalized(self, ml_db):
        """SQLite returns naive datetimes; build_training_data must not blow up."""
        # Insert with a naive datetime to mimic the SQLite read-back path.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with ml_db() as session:
            session.add(ActivityEvent(
                timestamp=now - timedelta(hours=1),
                mode="working", source="manual",
            ))
            await session.commit()
        rows = await fb.build_training_data(days=2)
        assert len(rows) == 1


class TestEncodings:
    def test_mode_encoding_covers_predictable_modes(self):
        for mode in fb.PREDICTABLE_MODES:
            assert mode in fb.MODE_ENCODING
        # idle appended after PREDICTABLE_MODES.
        assert fb.MODE_ENCODING["idle"] == len(fb.PREDICTABLE_MODES)
        assert "away" not in fb.MODE_ENCODING

    def test_season_encoding_complete(self):
        for season in ("winter", "spring", "summer", "fall"):
            assert season in fb.SEASON_ENCODING
