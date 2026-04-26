"""
Unit tests for the Hue v2 effect manager.

These hit the effect manager directly — engine retains thin shims
that delegate here, so behavior in production is whatever these
tests assert.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.effect_manager import (
    WEATHER_EFFECT_MAP,
    WEATHER_SKIP_MODES,
    EffectManager,
)


def _make_hue_v2(connected: bool = True):
    """Build a hue_v2 stub with stop_effect_all/set_effect_all/set_effect mocked."""
    hue = MagicMock()
    hue.connected = connected
    hue.stop_effect_all = AsyncMock()
    hue.set_effect_all = AsyncMock()
    hue.set_effect = AsyncMock()
    return hue


def _make_weather(description: str | None):
    """Build a weather_service stub. None → get_cached returns None."""
    svc = MagicMock()
    svc.get_cached.return_value = (
        {"description": description} if description is not None else None
    )
    return svc


# ---------------------------------------------------------------------------
# TestReconcile
# ---------------------------------------------------------------------------

class TestReconcile:
    @pytest.mark.asyncio
    async def test_no_op_when_hue_v2_not_connected(self):
        hue = _make_hue_v2(connected=False)
        mgr = EffectManager(hue_v2=hue)

        await mgr.reconcile("candle")

        hue.stop_effect_all.assert_not_called()
        hue.set_effect_all.assert_not_called()
        assert mgr.active_name is None

    @pytest.mark.asyncio
    async def test_same_name_same_lights_short_circuits(self):
        hue = _make_hue_v2()
        mgr = EffectManager(hue_v2=hue)
        # Prime the tracker
        await mgr.reconcile("candle")
        hue.stop_effect_all.reset_mock()
        hue.set_effect_all.reset_mock()

        await mgr.reconcile("candle")

        hue.stop_effect_all.assert_not_called()
        hue.set_effect_all.assert_not_called()
        assert mgr.active_name == "candle"
        assert mgr.active_lights is None

    @pytest.mark.asyncio
    async def test_same_name_different_lights_full_cycle(self):
        hue = _make_hue_v2()
        mgr = EffectManager(hue_v2=hue)
        await mgr.reconcile("candle")  # candle on all
        hue.stop_effect_all.reset_mock()
        hue.set_effect_all.reset_mock()
        hue.set_effect.reset_mock()

        await mgr.reconcile({"effect": "candle", "lights": ["1", "2"]})

        hue.stop_effect_all.assert_awaited_once()
        hue.set_effect.assert_any_await("1", "candle")
        hue.set_effect.assert_any_await("2", "candle")
        assert mgr.active_name == "candle"
        assert mgr.active_lights == ["1", "2"]

    @pytest.mark.asyncio
    async def test_desired_none_always_stops_when_active(self):
        hue = _make_hue_v2()
        mgr = EffectManager(hue_v2=hue)
        await mgr.reconcile("candle")
        hue.stop_effect_all.reset_mock()

        await mgr.reconcile(None)

        hue.stop_effect_all.assert_awaited_once()
        assert mgr.active_name is None
        assert mgr.active_lights is None

    @pytest.mark.asyncio
    async def test_desired_none_stops_even_when_tracker_inactive(self):
        # Out-of-band activations (scenes API, presence service) leave
        # effects running with our tracker showing None — reconcile(None)
        # should still issue stop_effect_all.
        hue = _make_hue_v2()
        mgr = EffectManager(hue_v2=hue)

        await mgr.reconcile(None)

        hue.stop_effect_all.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_start_separated_by_guard_sleep(self):
        hue = _make_hue_v2()
        mgr = EffectManager(hue_v2=hue)
        # Prime with a different effect so reconcile takes the stop+start path
        await mgr.reconcile("opal")
        hue.stop_effect_all.reset_mock()
        hue.set_effect_all.reset_mock()

        with patch(
            "backend.services.effect_manager.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep_mock:
            await mgr.reconcile("candle")

        sleep_mock.assert_awaited_once_with(EffectManager.STOP_START_GUARD_SECONDS)
        hue.stop_effect_all.assert_awaited_once()
        hue.set_effect_all.assert_awaited_once_with("candle")

    @pytest.mark.asyncio
    async def test_dict_shape_with_lights_uses_set_effect_per_id(self):
        hue = _make_hue_v2()
        mgr = EffectManager(hue_v2=hue)

        await mgr.reconcile({"effect": "fire", "lights": ["1", "2"]})

        hue.set_effect_all.assert_not_called()
        hue.set_effect.assert_any_await("1", "fire")
        hue.set_effect.assert_any_await("2", "fire")

    @pytest.mark.asyncio
    async def test_string_shape_uses_set_effect_all(self):
        hue = _make_hue_v2()
        mgr = EffectManager(hue_v2=hue)

        await mgr.reconcile("glisten")

        hue.set_effect_all.assert_awaited_once_with("glisten")
        hue.set_effect.assert_not_called()


# ---------------------------------------------------------------------------
# TestStopAll
# ---------------------------------------------------------------------------

class TestStopAll:
    @pytest.mark.asyncio
    async def test_stop_all_clears_tracker(self):
        hue = _make_hue_v2()
        mgr = EffectManager(hue_v2=hue)
        await mgr.reconcile("candle")
        hue.stop_effect_all.reset_mock()

        await mgr.stop_all()

        hue.stop_effect_all.assert_awaited_once()
        assert mgr.active_name is None
        assert mgr.active_lights is None

    @pytest.mark.asyncio
    async def test_stop_all_noop_when_already_inactive(self):
        # stop_all is the sleep-mode special path — it should NOT issue
        # an unnecessary stop call when we know nothing is running.
        hue = _make_hue_v2()
        mgr = EffectManager(hue_v2=hue)

        await mgr.stop_all()

        hue.stop_effect_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_all_noop_when_hue_v2_disconnected(self):
        hue = _make_hue_v2(connected=False)
        mgr = EffectManager(hue_v2=hue)
        # Pretend an effect was active before disconnect
        mgr._active_name = "candle"

        await mgr.stop_all()

        hue.stop_effect_all.assert_not_called()


# ---------------------------------------------------------------------------
# TestGetDesiredEffect
# ---------------------------------------------------------------------------

class TestGetDesiredEffect:
    def test_sleeping_returns_none(self):
        mgr = EffectManager(hue_v2=_make_hue_v2())
        assert mgr.get_desired_effect("sleeping", "evening") is None
        assert mgr.get_desired_effect("sleeping", "night") is None

    def test_social_returns_none(self):
        mgr = EffectManager(hue_v2=_make_hue_v2())
        assert mgr.get_desired_effect("social", "evening") is None

    def test_relax_evening_returns_candle(self):
        mgr = EffectManager(hue_v2=_make_hue_v2())
        result = mgr.get_desired_effect("relax", "evening")
        assert isinstance(result, dict)
        assert result["effect"] == "candle"

    def test_late_night_falls_back_to_night_for_undefined_modes(self):
        # watching defines glisten for evening + night; late_night should
        # fall back to night per the late_night-fallback rule
        mgr = EffectManager(hue_v2=_make_hue_v2())
        late = mgr.get_desired_effect("watching", "late_night")
        night = mgr.get_desired_effect("watching", "night")
        assert late == night

    def test_weather_fallback_only_when_mode_has_no_auto_effect(self):
        # working has no auto-effect; rain in evening should overlay candle
        mgr = EffectManager(
            hue_v2=_make_hue_v2(),
            weather_service=_make_weather("Rain showers"),
        )
        result = mgr.get_desired_effect("working", "evening")
        assert result == "candle"

    def test_weather_fallback_skipped_during_day(self):
        # rain → candle is evening/night/late_night only
        mgr = EffectManager(
            hue_v2=_make_hue_v2(),
            weather_service=_make_weather("Rain showers"),
        )
        assert mgr.get_desired_effect("working", "day") is None

    def test_sparkle_fires_any_time(self):
        # thunderstorm → sparkle runs at any time of day
        mgr = EffectManager(
            hue_v2=_make_hue_v2(),
            weather_service=_make_weather("Thunderstorm with rain"),
        )
        assert mgr.get_desired_effect("working", "day") == "sparkle"


# ---------------------------------------------------------------------------
# TestGetWeatherEffect
# ---------------------------------------------------------------------------

class TestGetWeatherEffect:
    def test_no_weather_service_returns_none(self):
        mgr = EffectManager(hue_v2=_make_hue_v2())
        assert mgr.get_weather_effect() is None

    def test_no_cached_weather_returns_none(self):
        mgr = EffectManager(hue_v2=_make_hue_v2(), weather_service=_make_weather(None))
        assert mgr.get_weather_effect() is None

    def test_thunderstorm_maps_sparkle(self):
        mgr = EffectManager(
            hue_v2=_make_hue_v2(),
            weather_service=_make_weather("Heavy thunderstorm"),
        )
        assert mgr.get_weather_effect() == "sparkle"

    def test_rain_maps_candle(self):
        mgr = EffectManager(
            hue_v2=_make_hue_v2(),
            weather_service=_make_weather("Light rain"),
        )
        assert mgr.get_weather_effect() == "candle"

    def test_snow_maps_opal(self):
        mgr = EffectManager(
            hue_v2=_make_hue_v2(),
            weather_service=_make_weather("Light snow"),
        )
        assert mgr.get_weather_effect() == "opal"

    def test_unmapped_description_returns_none(self):
        mgr = EffectManager(
            hue_v2=_make_hue_v2(),
            weather_service=_make_weather("Clear and sunny"),
        )
        assert mgr.get_weather_effect() is None

    def test_weather_service_exception_returns_none(self):
        svc = MagicMock()
        svc.get_cached.side_effect = RuntimeError("network down")
        mgr = EffectManager(hue_v2=_make_hue_v2(), weather_service=svc)
        assert mgr.get_weather_effect() is None


# ---------------------------------------------------------------------------
# TestModuleConstants
# ---------------------------------------------------------------------------

class TestModuleConstants:
    def test_weather_effect_map_keys(self):
        assert set(WEATHER_EFFECT_MAP.keys()) == {"thunderstorm", "rain", "snow"}

    def test_weather_skip_modes_excludes_relax_and_watching(self):
        # relax and watching are the two modes whose lighting reads weather;
        # they must NOT be in the skip set
        assert "relax" not in WEATHER_SKIP_MODES
        assert "watching" not in WEATHER_SKIP_MODES

    def test_weather_skip_modes_contains_focused_modes(self):
        assert "social" in WEATHER_SKIP_MODES
        assert "sleeping" in WEATHER_SKIP_MODES
        assert "working" in WEATHER_SKIP_MODES
        assert "gaming" in WEATHER_SKIP_MODES
        assert "cooking" in WEATHER_SKIP_MODES
