"""
Tests for feature_builder — the pure-functional layer that the lighting
learner and behavioral predictor depend on.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import ActivityEvent
from backend.services.ml import feature_builder as fb

# Inputs to time-bucketing helpers are interpreted on the apartment-local
# clock. Constructing test datetimes in `_LOCAL_TZ` keeps the boundary
# assertions readable and removes the implicit UTC→local conversion the
# old tests glossed over.
LOCAL = fb._LOCAL_TZ


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
        ts = datetime(2026, 4, 24, hour, 30, tzinfo=LOCAL)
        assert fb.get_time_period(ts) == expected


class TestGetSeason:
    @pytest.mark.parametrize("month,expected", [
        (1, "winter"), (2, "winter"), (12, "winter"),
        (3, "spring"), (4, "spring"), (5, "spring"),
        (6, "summer"), (7, "summer"), (8, "summer"),
        (9, "fall"), (10, "fall"), (11, "fall"),
    ])
    def test_each_month(self, month, expected):
        ts = datetime(2026, month, 15, 12, 0, tzinfo=LOCAL)
        assert fb.get_season(ts) == expected


class TestGetTemporalFeatures:
    def test_shape_and_values(self):
        ts = datetime(2026, 4, 24, 14, 37, tzinfo=LOCAL)  # Friday
        features = fb.get_temporal_features(ts)
        assert features["hour"] == 14
        assert features["minute_bucket"] == 2  # 37 // 15 = 2
        assert features["day_of_week"] == 4  # Friday
        assert features["is_weekend"] is False
        assert features["season"] == "spring"
        assert features["time_period"] == "day"

    def test_weekend_flag(self):
        sat = datetime(2026, 4, 25, 10, 0, tzinfo=LOCAL)
        assert fb.get_temporal_features(sat)["is_weekend"] is True


class TestDSTBoundary:
    """Temporal features must track the apartment wall clock, not UTC.

    Indianapolis has its own DST rules; before #30 the helpers read
    ``.hour`` straight off UTC-tagged timestamps and labeled them with
    local-time semantics. That shifted every "hour" feature by 4-5
    hours year-round and by an extra hour at each DST transition,
    creating a discontinuity in the training set.
    """

    def test_utc_input_converted_to_local_hour(self):
        # 23:00 UTC during EDT (UTC-4) = 19:00 local — evening.
        # The pre-fix code returned "night" because it bucketed 23 directly.
        ts = datetime(2026, 7, 1, 23, 0, tzinfo=timezone.utc)
        assert fb.get_time_period(ts) == "evening"

    def test_utc_input_converted_to_local_hour_winter(self):
        # 23:00 UTC during EST (UTC-5) = 18:00 local — still evening.
        ts = datetime(2026, 1, 15, 23, 0, tzinfo=timezone.utc)
        assert fb.get_time_period(ts) == "evening"

    def test_dst_spring_forward_shifts_offset_not_label(self):
        # 14:00 UTC the day before spring-forward (UTC-5 EST) = 09:00 local.
        # 14:00 UTC the day of spring-forward (UTC-4 EDT)     = 10:00 local.
        # Both still bucket to "day"; the regression is that the local
        # hour feature must actually shift across the boundary instead
        # of staying pinned to UTC.
        before = datetime(2026, 3, 7, 14, 0, tzinfo=timezone.utc)
        after = datetime(2026, 3, 8, 14, 0, tzinfo=timezone.utc)
        assert fb.get_temporal_features(before)["hour"] == 9
        assert fb.get_temporal_features(after)["hour"] == 10
        assert fb.get_time_period(before) == "day"
        assert fb.get_time_period(after) == "day"

    def test_naive_utc_input_still_treated_as_utc(self):
        # SQLite returns naive datetimes; the helpers must coerce them
        # to UTC before converting, not assume they're already local.
        naive = datetime(2026, 7, 1, 23, 0)  # naive == UTC by contract
        assert fb.get_time_period(naive) == "evening"


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


@pytest.mark.asyncio
class TestBuildRuntimeFeatures:
    """The async wrapper that closes the train/serve feature-parity gap.

    Pre-2026-04-28 the predictor was called with only ``current_mode``,
    leaving four history-derived features at 0. These tests pin the
    DB-driven values so a regression of that bug shows up as a test
    failure, not a silent accuracy hit.
    """

    async def test_empty_db_yields_zero_history(self, ml_db):
        features = await fb.build_runtime_features(current_mode="working")
        assert features["minutes_since_wake"] == 0
        assert features["mode_transitions_today"] == 0
        assert features["manual_override_count_7d"] == 0
        assert features["previous_mode_duration_min"] == 0
        # Temporal features still populated even without rows.
        assert "hour" in features
        assert features["previous_mode"] == fb.MODE_ENCODING["working"]

    async def test_history_populates_features(self, ml_db):
        # Anchor every "today" event off today_start (apartment-local
        # midnight, expressed as UTC), not off `now` — `now - 20m` ran
        # before today_start in the post-midnight window and silently
        # dropped one transition. The local-midnight anchor matches
        # `build_runtime_features` after #30, so events seeded here line
        # up with the function's "today" filter regardless of DST.
        now = datetime.now(timezone.utc)
        today_start = now.astimezone(fb._LOCAL_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).astimezone(timezone.utc)
        elapsed = now - today_start
        async with ml_db() as session:
            # First non-idle event of "today" — wake.
            session.add(ActivityEvent(
                timestamp=today_start + timedelta(seconds=30),
                mode="working", source="process", duration_seconds=600,
            ))
            # Two more transitions today, both safely after today_start.
            session.add(ActivityEvent(
                timestamp=today_start + elapsed * 0.5,
                mode="watching", source="process", duration_seconds=600,
            ))
            session.add(ActivityEvent(
                timestamp=today_start + elapsed * 0.9,
                mode="working", source="process", duration_seconds=600,
            ))
            # A manual override 2 days ago — still inside the 7d window.
            session.add(ActivityEvent(
                timestamp=now - timedelta(days=2),
                mode="relax", source="manual", duration_seconds=600,
            ))
            await session.commit()

        features = await fb.build_runtime_features(current_mode="working")
        assert features["mode_transitions_today"] == 3
        assert features["manual_override_count_7d"] == 1
        assert features["minutes_since_wake"] > 0


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


class TestCameraAudioEncodings:
    """Encoding maps for the four columns added 2026-05-04.

    Stable hard-coded indices: a new label out of YAMNet (or a typo on the
    camera side) must route to the unknown sentinel, not silently shift
    every other class's index when the model retrains.
    """

    def test_zone_encoding_known_values(self):
        assert fb._encode_zone("desk") == 0
        assert fb._encode_zone("bed") == 1
        assert fb._encode_zone("couch") == 2

    def test_zone_encoding_unknown_routes_to_sentinel(self):
        sentinel = len(fb.ZONE_ENCODING)
        assert fb._encode_zone(None) == sentinel
        assert fb._encode_zone("kitchen") == sentinel

    def test_posture_encoding_known_values(self):
        assert fb._encode_posture("upright") == 0
        assert fb._encode_posture("reclined") == 1

    def test_posture_encoding_unknown_routes_to_sentinel(self):
        sentinel = len(fb.POSTURE_ENCODING)
        assert fb._encode_posture(None) == sentinel
        assert fb._encode_posture("lying") == sentinel

    def test_audio_class_encoding_known_values(self):
        assert fb._encode_audio_class("silence") == 0
        assert fb._encode_audio_class("speech_multiple") == 2
        assert fb._encode_audio_class("game_audio") == 6

    def test_audio_class_unknown_routes_to_other(self):
        # Unlike zone/posture, unknown audio falls through to the "other"
        # bucket so previously-unseen YAMNet classes still land in vocab.
        assert fb._encode_audio_class(None) == fb.AUDIO_CLASS_ENCODING["other"]
        assert fb._encode_audio_class("cooking") == fb.AUDIO_CLASS_ENCODING["other"]

    def test_lux_encoding_passes_through_floats(self):
        assert fb._encode_lux(150.0) == 150.0
        assert fb._encode_lux(0.0) == 0.0

    def test_lux_encoding_none_becomes_nan(self):
        result = fb._encode_lux(None)
        # NaN is the only float that is not equal to itself.
        assert result != result

    def test_lux_encoding_handles_garbage(self):
        result = fb._encode_lux("not-a-number")
        assert result != result  # NaN


class TestBuildCurrentFeaturesContext:
    """The 4 new context kwargs must reach the encoded fields."""

    def test_camera_and_audio_kwargs_encoded(self):
        features = fb.build_current_features(
            current_mode="working",
            zone="bed",
            posture="reclined",
            audio_class="speech_multiple",
            lux=85.5,
        )
        assert features["zone_enc"] == fb.ZONE_ENCODING["bed"]
        assert features["posture_enc"] == fb.POSTURE_ENCODING["reclined"]
        assert features["audio_class_enc"] == fb.AUDIO_CLASS_ENCODING["speech_multiple"]
        assert features["lux"] == 85.5

    def test_missing_context_uses_sentinels(self):
        features = fb.build_current_features(current_mode="idle")
        assert features["zone_enc"] == len(fb.ZONE_ENCODING)
        assert features["posture_enc"] == len(fb.POSTURE_ENCODING)
        assert features["audio_class_enc"] == fb.AUDIO_CLASS_ENCODING["other"]
        assert features["lux"] != features["lux"]  # NaN


@pytest.mark.asyncio
class TestBuildTrainingDataContext:
    """activity_events.zone/posture/audio_class/lux must reach training rows."""

    async def test_columns_round_trip_through_training(self, ml_db):
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            session.add(ActivityEvent(
                timestamp=now - timedelta(hours=1),
                mode="working", source="manual",
                zone="desk", posture="upright",
                audio_class="speech_single", lux=210.0,
            ))
            await session.commit()

        rows = await fb.build_training_data(days=2)
        assert len(rows) == 1
        row = rows[0]
        assert row["zone_enc"] == fb.ZONE_ENCODING["desk"]
        assert row["posture_enc"] == fb.POSTURE_ENCODING["upright"]
        assert row["audio_class_enc"] == fb.AUDIO_CLASS_ENCODING["speech_single"]
        assert row["lux"] == 210.0

    async def test_null_columns_use_sentinels(self, ml_db):
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            session.add(ActivityEvent(
                timestamp=now - timedelta(hours=1),
                mode="working", source="manual",
                # zone/posture/audio_class/lux all NULL — historical rows
                # the backfill couldn't populate (camera off-frame, no
                # nearby audio_ml row).
            ))
            await session.commit()

        rows = await fb.build_training_data(days=2)
        assert len(rows) == 1
        row = rows[0]
        assert row["zone_enc"] == len(fb.ZONE_ENCODING)
        assert row["posture_enc"] == len(fb.POSTURE_ENCODING)
        assert row["audio_class_enc"] == fb.AUDIO_CLASS_ENCODING["other"]
        assert row["lux"] != row["lux"]  # NaN


@pytest.mark.asyncio
class TestBuildRuntimeFeaturesContext:
    """The async wrapper must forward the 4 new kwargs."""

    async def test_kwargs_forwarded(self, ml_db):
        features = await fb.build_runtime_features(
            current_mode="watching",
            zone="bed",
            posture="reclined",
            audio_class="music",
            lux=42.0,
        )
        assert features["zone_enc"] == fb.ZONE_ENCODING["bed"]
        assert features["posture_enc"] == fb.POSTURE_ENCODING["reclined"]
        assert features["audio_class_enc"] == fb.AUDIO_CLASS_ENCODING["music"]
        assert features["lux"] == 42.0

    async def test_missing_kwargs_use_sentinels(self, ml_db):
        features = await fb.build_runtime_features(current_mode="working")
        assert features["zone_enc"] == len(fb.ZONE_ENCODING)
        assert features["posture_enc"] == len(fb.POSTURE_ENCODING)
        assert features["audio_class_enc"] == fb.AUDIO_CLASS_ENCODING["other"]
        assert features["lux"] != features["lux"]  # NaN


@pytest.mark.asyncio
class TestLatestAudioClass:
    """latest_audio_class queries ml_decisions by source + recency."""

    async def test_returns_top_class_within_window(self, ml_db):
        from backend.models import MLDecision
        async with ml_db() as session:
            session.add(MLDecision(
                predicted_mode="silence",
                applied=False,
                confidence=0.9,
                decision_source="audio_ml",
                factors={"top_class": "speech_multiple"},
            ))
            await session.commit()

        result = await fb.latest_audio_class(window_seconds=60)
        assert result == "speech_multiple"

    async def test_returns_none_when_no_recent_row(self, ml_db):
        result = await fb.latest_audio_class(window_seconds=60)
        assert result is None

    async def test_ignores_non_audio_sources(self, ml_db):
        from backend.models import MLDecision
        async with ml_db() as session:
            session.add(MLDecision(
                predicted_mode="working",
                applied=False,
                confidence=0.9,
                decision_source="camera",
                factors={"top_class": "speech_multiple"},  # camera shouldn't have this
            ))
            await session.commit()

        result = await fb.latest_audio_class(window_seconds=60)
        assert result is None
