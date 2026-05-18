"""
Tests for LightingPreferenceLearner — EMA-based per-light preference learner.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import LightAdjustment
from backend.services.ml.lighting_learner import (
    EMA_ALPHA,
    MIN_ADJUSTMENTS,
    MIN_ADJUSTMENTS_WEATHER,
    WEATHER_ANY,
    LightingPreferenceLearner,
)


@pytest.fixture
def learner(tmp_model_manager):
    """Fresh learner backed by an empty tmp ModelManager."""
    return LightingPreferenceLearner(tmp_model_manager)


def _make_adjustment(*, light_id="1", mode="working", hour=14,
                     bri_after=180, trigger="ws", **extra):
    """Build a LightAdjustment row with sane defaults."""
    return LightAdjustment(
        timestamp=datetime(2026, 4, 24, hour, 0, tzinfo=timezone.utc),
        light_id=light_id,
        mode_at_time=mode,
        bri_before=100,
        bri_after=bri_after,
        trigger=trigger,
        **extra,
    )


class TestInit:
    def test_no_persisted_file_yields_empty_prefs(self, learner):
        assert learner._preferences == {}

    def test_loads_persisted_prefs(self, tmp_path):
        from backend.services.ml.model_manager import ModelManager
        # Pre-write a lighting_prefs.json. New key shape includes weather:
        # mode:period:weather. Legacy two-segment keys still load but never
        # match a lookup (get_overlay always asks with a weather class).
        prefs = {"working:day:any": {"1": {"bri": 200}}}
        (tmp_path / "lighting_prefs.json").write_text(json.dumps(prefs))
        # Need a meta file so ModelManager.load_all picks it up.
        (tmp_path / "model_meta.json").write_text(json.dumps({
            "lighting_prefs": {"file": "lighting_prefs.json", "status": "active"},
        }))
        mm = ModelManager(data_dir=tmp_path)

        async def _load():
            await mm.load_all()
        import asyncio
        asyncio.run(_load())

        learner = LightingPreferenceLearner(mm)
        assert learner._preferences == prefs


class TestGetOverlay:
    def test_returns_none_for_unknown_combo(self, learner):
        assert learner.get_overlay("working", "day") is None

    def test_returns_dict_when_any_bucket_exists(self, learner):
        """The 'any' bucket is the cross-weather baseline — applied when no
        weather-specific bucket matches."""
        learner._preferences = {"working:day:any": {"1": {"bri": 180}}}
        assert learner.get_overlay("working", "day") == {"1": {"bri": 180}}

    def test_weather_specific_overrides_any(self, learner):
        """Weather-specific bucket overrides the 'any' bucket per-light."""
        learner._preferences = {
            "working:day:any":          {"1": {"bri": 180}, "2": {"bri": 150}},
            "working:day:thunderstorm": {"1": {"bri": 240}},
        }
        # L1: storm value wins. L2: falls through to "any" baseline.
        out = learner.get_overlay("working", "day", "thunderstorm")
        assert out == {"1": {"bri": 240}, "2": {"bri": 150}}

    def test_unmatched_weather_falls_back_to_any(self, learner):
        learner._preferences = {
            "working:day:any":   {"1": {"bri": 180}},
            "working:day":       {"1": {"bri": 99}},  # legacy key — ignored
        }
        assert learner.get_overlay("working", "day", "rain") == {"1": {"bri": 180}}


class TestHasWeatherPref:
    def test_empty_when_no_weather_bucket(self, learner):
        learner._preferences = {"working:day:any": {"1": {"bri": 180}}}
        assert learner.has_weather_pref("working", "day", "rain") == set()

    def test_excludes_any_bucket_intentionally(self, learner):
        """has_weather_pref drives the Layer-5 heuristic fade-out — only a
        WEATHER-SPECIFIC learned value should suppress the heuristic. The
        'any' baseline isn't weather knowledge."""
        learner._preferences = {"working:day:any": {"1": {"bri": 180}}}
        assert learner.has_weather_pref("working", "day", WEATHER_ANY) == set()

    def test_returns_light_ids_with_bri_in_specific_bucket(self, learner):
        learner._preferences = {
            "working:day:thunderstorm": {
                "1": {"bri": 240},
                "2": {"hue": 8000},  # no bri — excluded
            }
        }
        assert learner.has_weather_pref("working", "day", "thunderstorm") == {"1"}


@pytest.mark.asyncio
class TestWriteLearnedPref:
    async def test_persists_and_is_readable(self, learner):
        await learner.write_learned_pref(
            light_id="2", mode="working", time_period="day",
            weather_class="thunderstorm", bri=210,
        )
        out = learner.get_overlay("working", "day", "thunderstorm")
        assert out == {"2": {"bri": 210}}
        # And the model_manager has the saved model in its registry.
        assert learner._model_manager.get_model("lighting_prefs") is not None


class TestGetStatus:
    def test_shape(self, learner):
        learner._preferences = {
            "working:day:any":  {"1": {"bri": 180}, "2": {"bri": 150}},
            "relax:night:any":  {"1": {"bri": 50}},
        }
        status = learner.get_status()
        assert status["learned_slots"] == 2  # mode:period:weather keys
        assert status["learned_combos"] == 3  # per-light entries: 2 + 1
        assert status["lights_with_preferences"] == 2  # unique ids: 1, 2
        assert status["min_adjustments"] == MIN_ADJUSTMENTS
        assert status["ema_alpha"] == EMA_ALPHA


@pytest.mark.asyncio
class TestRecalculate:
    async def test_no_data_no_overlay(self, learner, ml_db):
        await learner.recalculate()
        assert learner._preferences == {}

    async def test_filters_non_user_triggers(self, learner, ml_db):
        async with ml_db() as session:
            for _ in range(MIN_ADJUSTMENTS + 2):
                # automation trigger should be excluded.
                session.add(_make_adjustment(
                    light_id="1", trigger="automation", bri_after=200,
                ))
            await session.commit()

        await learner.recalculate()
        assert learner._preferences == {}

    async def test_min_adjustments_threshold(self, learner, ml_db):
        async with ml_db() as session:
            # Only 4 user-triggered adjustments — below MIN_ADJUSTMENTS=5.
            for _ in range(MIN_ADJUSTMENTS - 1):
                session.add(_make_adjustment(bri_after=180))
            await session.commit()

        await learner.recalculate()
        assert learner._preferences == {}

    async def test_sufficient_data_writes_ema(self, learner, ml_db):
        async with ml_db() as session:
            for i in range(MIN_ADJUSTMENTS + 2):
                # Vary brightness slightly so EMA produces a stable value.
                session.add(_make_adjustment(bri_after=180 + i))
            await session.commit()

        await learner.recalculate()
        # Expect one combo learned for working:day:any light_id="1".
        assert "working:day:any" in learner._preferences
        assert "1" in learner._preferences["working:day:any"]
        learned = learner._preferences["working:day:any"]["1"]
        assert "bri" in learned
        # EMA over [180..186] should land in that range.
        assert 180 <= learned["bri"] <= 186

    async def test_weather_specific_bucket_lower_threshold(self, learner, ml_db):
        """Three weather-tagged rows cross MIN_ADJUSTMENTS_WEATHER (=3) — the
        weather-specific bucket appears even though the same data is below
        MIN_ADJUSTMENTS (=5) for the 'any' baseline."""
        async with ml_db() as session:
            for i in range(MIN_ADJUSTMENTS_WEATHER):
                session.add(_make_adjustment(
                    bri_after=210 + i,
                    weather_class="thunderstorm",
                ))
            await session.commit()

        await learner.recalculate()
        assert "working:day:thunderstorm" in learner._preferences
        assert "1" in learner._preferences["working:day:thunderstorm"]
        # The "any" baseline shouldn't appear — 3 samples < MIN_ADJUSTMENTS.
        assert "working:day:any" not in learner._preferences

    async def test_weather_specific_overrides_any_after_recalc(
        self, learner, ml_db,
    ):
        """End-to-end: enough rows to populate BOTH any and storm buckets.
        The storm bucket's EMA differs from any's, and the storm value wins
        when get_overlay is asked with weather='thunderstorm'."""
        async with ml_db() as session:
            # 5 clear-weather rows around bri=120 — populates "any".
            for i in range(MIN_ADJUSTMENTS):
                session.add(_make_adjustment(
                    bri_after=120 + i,
                    weather_class="clear",
                ))
            # 3 storm rows around bri=210 — populates storm-specific.
            for i in range(MIN_ADJUSTMENTS_WEATHER):
                session.add(_make_adjustment(
                    bri_after=210 + i,
                    weather_class="thunderstorm",
                ))
            await session.commit()

        await learner.recalculate()
        any_bri = learner._preferences["working:day:any"]["1"]["bri"]
        storm_bri = learner._preferences[
            "working:day:thunderstorm"
        ]["1"]["bri"]
        # Storm bucket only sees storm data — its EMA stays high. Any bucket
        # mixes both, so it's somewhere in between. The directional invariant
        # is what matters: storm > any.
        assert storm_bri > 200  # only storm data
        assert storm_bri > any_bri  # weather-specific bucket reflects storm
        out = learner.get_overlay("working", "day", "thunderstorm")
        assert out["1"]["bri"] == storm_bri


@pytest.mark.asyncio
class TestRecalculateKitchenPair:
    async def test_pair_modes_pool_l3_only(self, learner, ml_db):
        # Only L3 has adjustments in working/day. After recalc, L4 should
        # carry the same EMA via kitchen-pair pooling.
        async with ml_db() as session:
            for i in range(MIN_ADJUSTMENTS + 2):
                session.add(_make_adjustment(
                    light_id="3", mode="working", bri_after=180 + i,
                ))
            await session.commit()

        await learner.recalculate()

        slot = learner._preferences.get("working:day:any", {})
        assert "3" in slot
        assert "4" in slot
        assert slot["3"] == slot["4"]

    async def test_pair_modes_pool_split_history(self, learner, ml_db):
        # L3 and L4 each have 3 adjustments — below MIN_ADJUSTMENTS alone,
        # but pooled they cross the threshold and both light IDs learn.
        async with ml_db() as session:
            for _ in range(3):
                session.add(_make_adjustment(
                    light_id="3", mode="gaming", bri_after=150,
                ))
            for _ in range(3):
                session.add(_make_adjustment(
                    light_id="4", mode="gaming", bri_after=150,
                ))
            await session.commit()

        await learner.recalculate()

        slot = learner._preferences.get("gaming:day:any", {})
        assert "3" in slot
        assert "4" in slot
        assert slot["3"] == slot["4"]

    async def test_relax_does_not_pool(self, learner, ml_db):
        # In relax (not pair-enforced), divergent L3 vs L4 EMAs are allowed.
        async with ml_db() as session:
            for i in range(MIN_ADJUSTMENTS + 2):
                session.add(_make_adjustment(
                    light_id="3", mode="relax", bri_after=80 + i,
                ))
            for i in range(MIN_ADJUSTMENTS + 2):
                session.add(_make_adjustment(
                    light_id="4", mode="relax", bri_after=140 + i,
                ))
            await session.commit()

        await learner.recalculate()

        slot = learner._preferences.get("relax:day:any", {})
        assert "3" in slot
        assert "4" in slot
        assert slot["3"]["bri"] != slot["4"]["bri"]


@pytest.mark.asyncio
class TestScanForSuggestions:
    @staticmethod
    def _recent_adjustment(**kwargs):
        """Build a LightAdjustment with a timestamp inside the scanner's
        14-day window AND deterministically in the "day" period.

        Indianapolis local 14:00 (~18:00 UTC during DST, ~19:00 during
        standard time) is solidly inside the day window regardless of
        DST. Using "now - 1 day, hour-pinned" instead of just "now -
        1 day" prevents the test from flipping period (and therefore
        the dedup bucket key) based on what time of day the suite runs.
        """
        now = datetime.now(timezone.utc) - timedelta(days=1)
        ts = now.replace(hour=18, minute=0, second=0, microsecond=0)
        kwargs.setdefault("light_id", "1")
        kwargs.setdefault("mode_at_time", "working")
        kwargs.setdefault("bri_before", 100)
        kwargs.setdefault("trigger", "ws")
        return LightAdjustment(timestamp=ts, **kwargs)

    async def test_returns_empty_with_no_rows(self, learner, ml_db):
        assert await learner.scan_for_suggestions() == []

    async def test_three_consistent_rows_produce_a_candidate(
        self, learner, ml_db,
    ):
        async with ml_db() as session:
            for v in (210, 215, 208):
                session.add(self._recent_adjustment(
                    bri_after=v, weather_class="thunderstorm",
                ))
            await session.commit()
        suggestions = await learner.scan_for_suggestions()
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s["light_id"] == "1"
        assert s["mode"] == "working"
        assert s["weather_class"] == "thunderstorm"
        assert 208 <= s["suggested_bri"] <= 215
        assert s["sample_count"] == 3

    async def test_high_variance_rejected(self, learner, ml_db):
        async with ml_db() as session:
            # 50, 100, 250 — (250-50)/133 = 1.5 way above 0.20 threshold.
            for v in (50, 100, 250):
                session.add(self._recent_adjustment(
                    bri_after=v, weather_class="rain",
                ))
            await session.commit()
        assert await learner.scan_for_suggestions() == []

    async def test_already_learned_bucket_dedupes(self, learner, ml_db):
        # Pre-seed a learned pref for the bucket the scanner would otherwise
        # surface — scanner must skip it.
        learner._preferences = {
            "working:day:thunderstorm": {"1": {"bri": 211}},
        }
        async with ml_db() as session:
            for v in (210, 215, 208):
                session.add(self._recent_adjustment(
                    bri_after=v, weather_class="thunderstorm",
                ))
            await session.commit()
        assert await learner.scan_for_suggestions() == []


class TestComputeEma:
    def test_known_input(self):
        adjustments = [
            _make_adjustment(bri_after=100),
            _make_adjustment(bri_after=200),
            _make_adjustment(bri_after=200),
            _make_adjustment(bri_after=200),
            _make_adjustment(bri_after=200),
        ]
        learned = LightingPreferenceLearner._compute_ema(adjustments)
        # Manual EMA: start 100, then accumulate towards 200 with α=0.3.
        # 100 → 130 → 151 → 165.7 → 175.99 → round → 176
        assert learned["bri"] == 176

    def test_skips_property_with_too_few_values(self):
        # bri_after present in all 5 → learned. hue_after absent → skipped.
        adjustments = [_make_adjustment(bri_after=180) for _ in range(5)]
        learned = LightingPreferenceLearner._compute_ema(adjustments)
        assert "bri" in learned
        assert "hue" not in learned
