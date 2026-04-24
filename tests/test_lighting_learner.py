"""
Tests for LightingPreferenceLearner — EMA-based per-light preference learner.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import LightAdjustment
from backend.services.ml.lighting_learner import (
    EMA_ALPHA,
    LightingPreferenceLearner,
    MIN_ADJUSTMENTS,
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
        # Pre-write a lighting_prefs.json.
        prefs = {"working:day": {"1": {"bri": 200}}}
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

    def test_returns_dict_when_prefs_exist(self, learner):
        learner._preferences = {"working:day": {"1": {"bri": 180}}}
        assert learner.get_overlay("working", "day") == {"1": {"bri": 180}}


class TestGetStatus:
    def test_shape(self, learner):
        learner._preferences = {
            "working:day": {"1": {"bri": 180}, "2": {"bri": 150}},
            "relax:night": {"1": {"bri": 50}},
        }
        status = learner.get_status()
        assert status["learned_combos"] == 2
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
        # Expect one combo learned for working:day light_id="1".
        assert "working:day" in learner._preferences
        assert "1" in learner._preferences["working:day"]
        learned = learner._preferences["working:day"]["1"]
        assert "bri" in learned
        # EMA over [180..186] should land in that range.
        assert 180 <= learned["bri"] <= 186


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
