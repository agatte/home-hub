# Aug 17 regressions for Transit attendance and screen-sync ownership.

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from backend.services.automation_constants import SCREEN_SYNC_FRESH_SECONDS, TZ
from backend.services.automation_engine import AutomationEngine
from backend.services.screen_sync import ScreenSyncService


def _engine(mock_hue, mock_hue_v2, mock_ws) -> AutomationEngine:
    return AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
    )


def _record_process(
    engine: AutomationEngine,
    *,
    device: str,
    idle_seconds: float,
    received_at: datetime,
) -> None:
    engine._record_process_semantic(
        "gaming",
        [
            {"key": "device", "value": device},
            {"key": "idle", "value": idle_seconds},
        ],
        received_at,
    )


def test_recent_desktop_interaction_requires_fresh_low_idle_evidence(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    now = datetime.now(tz=TZ)

    _record_process(
        engine, device="desktop", idle_seconds=0.0, received_at=now,
    )
    assert engine.is_recent_desktop_interaction(
        max_idle_seconds=15,
        max_report_age_seconds=10,
    )

    _record_process(
        engine, device="desktop", idle_seconds=15.0, received_at=now,
    )
    assert not engine.is_recent_desktop_interaction(
        max_idle_seconds=15,
        max_report_age_seconds=10,
    )

    _record_process(
        engine,
        device="desktop",
        idle_seconds=0.0,
        received_at=now - timedelta(seconds=11),
    )
    assert not engine.is_recent_desktop_interaction(
        max_idle_seconds=15,
        max_report_age_seconds=10,
    )


def test_recent_desktop_interaction_ignores_other_devices(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    _record_process(
        engine,
        device="latitude",
        idle_seconds=0.0,
        received_at=datetime.now(tz=TZ),
    )

    assert not engine.is_recent_desktop_interaction(
        max_idle_seconds=15,
        max_report_age_seconds=10,
    )


@pytest.mark.asyncio
async def test_screen_sync_protection_tracks_fresh_lights_not_capability_list(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    engine._current_mode = "gaming"
    sync = ScreenSyncService(
        mock_hue,
        target_light_ids=["2", "5", "1", "3", "4"],
        transition_boundary=engine._transition_boundary,
    )
    engine._screen_sync = sync

    await sync.apply_color(
        "2", 255, 255, 255,
        mode="gaming", source="desktop", period="day",
    )
    await sync.apply_color(
        "5", 255, 255, 255,
        mode="gaming", source="desktop", period="day",
    )

    assert sync.target_lights == ["2", "5", "1", "3", "4"]
    assert sync.fresh_owned_light_ids() == {"2", "5"}
    assert engine._protected_light_ids() == {"2", "5"}


@pytest.mark.asyncio
async def test_newer_other_light_does_not_refresh_stale_authoritative_target(
    mock_hue,
):
    sync = ScreenSyncService(
        mock_hue,
        target_light_ids=["2", "5", "1", "3", "4"],
    )

    await sync.apply_color(
        "1", 255, 0, 0,
        mode="watching", source="laptop", period="day",
    )
    assert sync.authoritative_state("1") is not None
    sync._last_color_at_by_light["1"] -= timedelta(
        seconds=SCREEN_SYNC_FRESH_SECONDS + 1,
    )

    await sync.apply_color(
        "2", 0, 0, 255,
        mode="watching", source="desktop", period="day",
    )

    assert sync.last_source == "desktop"
    assert "2" in sync.fresh_owned_light_ids()
    assert "1" not in sync.fresh_owned_light_ids()
    assert sync.fresh_authoritative_state("1") is None
    assert sync.fresh_authoritative_state("2") is not None


@pytest.mark.asyncio
async def test_transit_clear_reapplies_living_room_with_fresh_desktop_sync(
    mock_hue, mock_hue_v2, mock_ws, monkeypatch,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    monkeypatch.setattr(engine, "_get_time_period", lambda now=None: "day")
    engine._current_mode = "gaming"

    # Model the production incident: Gaming was already established and the
    # effect tracker was settled. A brand-new engine starts tracker-unknown,
    # which intentionally runs effect-release safety across every mapped lamp.
    desired = engine._get_desired_effect("gaming")
    desired_name, desired_lights = engine._effect_manager._normalize_desired(desired)
    engine._effect_manager._active_name = desired_name
    engine._effect_manager._active_lights = desired_lights
    engine._effect_manager._tracker_known = True

    mock_hue.set_light = AsyncMock(return_value=True)

    sync = ScreenSyncService(
        mock_hue,
        target_light_ids=["2", "5", "1", "3", "4"],
        transition_boundary=engine._transition_boundary,
    )
    engine._screen_sync = sync

    await sync.apply_color(
        "2", 255, 255, 255,
        mode="gaming", source="desktop", period="day",
    )
    await sync.apply_color(
        "5", 255, 255, 255,
        mode="gaming", source="desktop", period="day",
    )
    assert engine._protected_light_ids() == {"2", "5"}

    path_state = {
        "1": {"on": True, "bri": 55, "ct": 360},
        "3": {"on": True, "bri": 40, "ct": 360},
        "4": {"on": True, "bri": 40, "ct": 360},
    }
    await engine.apply_transit_override(
        path_state,
        duration_seconds=600,
        transition_time=5,
    )
    assert set(engine._transit_light_overrides) == {"1", "3", "4"}

    mock_hue.set_light.reset_mock()
    await engine.clear_transit_override(light_ids=["1", "3", "4"])

    writes = {
        call.args[0]: call.args[1]
        for call in mock_hue.set_light.await_args_list
    }
    assert set(writes) == {"1", "3", "4", "6"}
    assert all(state.get("ct") == 286 for state in writes.values())
    assert all("hue" not in state and "sat" not in state for state in writes.values())
    assert engine._transit_light_overrides == {}
    assert engine._protected_light_ids() == {"2", "5"}
