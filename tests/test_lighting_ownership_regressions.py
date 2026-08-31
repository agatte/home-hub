# Aug 17 regressions for Transit attendance and screen-sync ownership.

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from backend.api.schemas.automation import ActivityReport
from backend.services.automation_constants import SCREEN_SYNC_FRESH_SECONDS, TZ
from backend.services.automation_engine import AutomationEngine
from backend.services.screen_sync import ScreenSyncService
from backend.services.light_state_calculator import resolve_activity_state
from backend.services.lol_champion_service import LoLChampionService


def _engine(mock_hue, mock_hue_v2, mock_ws) -> AutomationEngine:
    return AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
    )


class _ExternalOwner:
    owner_name = "test_external"

    def __init__(self, targets: dict[str, dict]) -> None:
        self._targets = targets

    def owned_light_targets(self) -> dict[str, dict]:
        return {light_id: target.copy() for light_id, target in self._targets.items()}


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
    sync.publish_accepted_gaming_state(resolve_activity_state("gaming", "day"))

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
async def test_external_owner_is_protected_by_normal_gaming_reconciliation(
    mock_hue, mock_hue_v2, mock_ws, monkeypatch,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    engine._current_mode = "gaming"
    monkeypatch.setattr(engine, "_get_time_period", lambda now=None: "day")
    owner = _ExternalOwner({"2": {"on": True, "hue": 100, "sat": 200, "bri": 99}})
    engine.register_external_light_owner(owner)
    mock_hue.set_light = AsyncMock(return_value=True)
    desired = engine._get_desired_effect("gaming")
    engine._effect_manager._active_name, engine._effect_manager._active_lights = (
        engine._effect_manager._normalize_desired(desired)
    )
    engine._effect_manager._tracker_known = True

    await engine._apply_mode("gaming", force_resend=True)

    written_ids = {call.args[0] for call in mock_hue.set_light.await_args_list}
    assert "2" not in written_ids
    assert "2" in engine._protected_light_ids()
    assert engine.get_light_ownership_context()["external_owners"] == [
        {"name": "test_external", "light_ids": ["2"]},
    ]


@pytest.mark.asyncio
async def test_effect_release_uses_external_owner_authoritative_target(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    held = {"2": {"on": True, "hue": 1234, "sat": 210, "bri": 88}}
    engine.register_external_light_owner(_ExternalOwner(held))
    mock_hue.set_light = AsyncMock(return_value=True)

    async with engine._transition_boundary.serialized():
        result = await engine.establish_effect_release(
            {"2": {"on": True, "ct": 250, "bri": 240}}, 10, {"2"},
        )

    assert result.successful == {"2"}
    assert mock_hue.set_light.await_args.args[1]["hue"] == 1234
    assert "ct" not in mock_hue.set_light.await_args.args[1]


@pytest.mark.asyncio
async def test_effect_release_fails_safe_for_unresolved_external_owner(
    mock_hue, mock_hue_v2, mock_ws,
):
    class UnresolvedOwner:
        def owned_light_targets(self):
            return {"2": None}

    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    engine.register_external_light_owner(UnresolvedOwner())
    mock_hue.set_light = AsyncMock(return_value=True)

    async with engine._transition_boundary.serialized():
        result = await engine.establish_effect_release(
            {"2": {"on": True, "ct": 250, "bri": 240}}, 10, {"2"},
        )

    assert result.skipped == {"2"}
    mock_hue.set_light.assert_not_awaited()


@pytest.mark.asyncio
async def test_league_release_reclaims_accepted_plan_despite_fresh_screen_sync(
    mock_hue, mock_hue_v2, mock_ws, monkeypatch,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    monkeypatch.setattr(engine, "_get_time_period", lambda now=None: "day")
    sync = ScreenSyncService(
        mock_hue,
        target_light_ids=["2", "5"],
        transition_boundary=engine._transition_boundary,
    )
    engine._screen_sync = sync
    league = LoLChampionService(mock_hue, engine, mock_ws)
    engine.register_external_light_owner(league)
    monkeypatch.setattr(
        "backend.api.routes.routines.load_setting",
        AsyncMock(return_value={"Ahri": {"r": 255, "g": 105, "b": 180}}),
    )

    await engine.report_activity("gaming", source="pc_agent")
    accepted = {
        light_id: engine._last_gaming_target[light_id].copy()
        for light_id in ("2", "5")
    }
    for light_id in ("2", "5"):
        await sync.apply_color(
            light_id, 1, 2, 3,
            mode="gaming", source="desktop", period="day",
        )
    assert sync.fresh_owned_light_ids() == {"2", "5"}

    await league.apply("Ahri")
    assert sync.fresh_owned_light_ids() == set()
    assert league.active_lights() == {"2", "5"}

    assert await league.clear() is True

    assert league.active_lights() == set()
    assert sync.fresh_owned_light_ids() == set()
    for light_id, target in accepted.items():
        for key, value in target.items():
            assert mock_hue._lights[light_id][key] == value
        assert sync.authoritative_state(light_id) == {"on": True, **sync._stable_target(target)}

    calls: list[tuple[str, dict]] = []
    original = mock_hue.set_light

    async def record(light_id, state):
        calls.append((str(light_id), state.copy()))
        return await original(light_id, state)

    mock_hue.set_light = record
    for light_id in ("2", "5"):
        await sync.apply_color(
            light_id, 200, 0, 0,
            mode="gaming", source="desktop", period="day",
        )

    assert calls == []
    assert sync.fresh_owned_light_ids() == {"2", "5"}


@pytest.mark.asyncio
async def test_away_invalidation_drops_league_and_screen_claims_without_writes(
    mock_hue, mock_hue_v2, mock_ws, monkeypatch,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    sync = ScreenSyncService(
        mock_hue,
        target_light_ids=["2", "5"],
        transition_boundary=engine._transition_boundary,
    )
    engine._screen_sync = sync
    league = LoLChampionService(mock_hue, engine, mock_ws)
    engine.register_external_light_owner(league)
    monkeypatch.setattr(
        "backend.api.routes.routines.load_setting",
        AsyncMock(return_value={"Ahri": {"r": 255, "g": 105, "b": 180}}),
    )
    engine._current_mode = "gaming"
    sync.publish_accepted_gaming_state(resolve_activity_state("gaming", "day"))
    for light_id in ("2", "5"):
        await sync.apply_color(
            light_id, 1, 2, 3,
            mode="gaming", source="desktop", period="day",
        )
    await league.apply("Ahri")
    mock_hue.set_light = AsyncMock(return_value=True)

    engine.arm_away_suppression("test")

    mock_hue.set_light.assert_not_awaited()
    assert league.active_lights() == set()
    assert sync.fresh_owned_light_ids() == set()


@pytest.mark.asyncio
async def test_soft_external_off_clears_league_and_arrival_restores_current_plan(
    mock_hue, mock_hue_v2, mock_ws, monkeypatch,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    monkeypatch.setattr(engine, "_get_time_period", lambda now=None: "day")
    sync = ScreenSyncService(
        mock_hue,
        target_light_ids=["2", "5"],
        transition_boundary=engine._transition_boundary,
    )
    engine._screen_sync = sync
    league = LoLChampionService(mock_hue, engine, mock_ws)
    engine.register_external_light_owner(league)
    monkeypatch.setattr(
        "backend.api.routes.routines.load_setting",
        AsyncMock(return_value={"Ahri": {"r": 255, "g": 105, "b": 180}}),
    )
    await engine.report_activity("gaming", source="pc_agent")
    accepted = {
        light_id: engine._last_gaming_target[light_id].copy()
        for light_id in ("2", "5")
    }
    await league.apply("Ahri")
    for light in mock_hue._lights.values():
        light["on"] = False
    original = mock_hue.set_light
    mock_hue.set_light = AsyncMock(return_value=True)

    assert await engine._check_external_off() is True
    mock_hue.set_light.assert_not_awaited()
    assert league.active_lights() == set()

    mock_hue.set_light = original
    await engine.signal_presence("test")
    await engine.reapply_current_mode(force_resend=True)

    for light_id, target in accepted.items():
        for key, value in target.items():
            assert mock_hue._lights[light_id][key] == value


@pytest.mark.asyncio
async def test_native_gaming_scene_releases_league_and_screen_authority(
    mock_hue, mock_hue_v2, mock_ws, monkeypatch,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    monkeypatch.setattr(engine, "_get_time_period", lambda now=None: "evening")
    sync = ScreenSyncService(
        mock_hue,
        target_light_ids=["2", "5"],
        transition_boundary=engine._transition_boundary,
    )
    engine._screen_sync = sync
    league = LoLChampionService(mock_hue, engine, mock_ws)
    engine.register_external_light_owner(league)
    monkeypatch.setattr(
        "backend.api.routes.routines.load_setting",
        AsyncMock(return_value={"Ahri": {"r": 255, "g": 105, "b": 180}}),
    )
    await engine.report_activity("gaming", source="pc_agent")
    await league.apply("Ahri")
    engine._scene_overrides = {"gaming": {"evening": "native-scene"}}

    await engine.report_activity("gaming", source="pc_agent")

    assert league.active_lights() == set()
    assert sync._accepted_gaming_targets == {}
    assert sync.fresh_owned_light_ids() == set()
    assert engine.get_gaming_diagnostics()["transition_reason"] == "scene_override"


@pytest.mark.asyncio
async def test_gaming_scene_takeover_blocks_league_reacquire_gap(
    mock_hue, mock_hue_v2, mock_ws, monkeypatch,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    monkeypatch.setattr(engine, "_get_time_period", lambda now=None: "evening")
    sync = ScreenSyncService(
        mock_hue,
        target_light_ids=["2", "5"],
        transition_boundary=engine._transition_boundary,
    )
    engine._screen_sync = sync
    league = LoLChampionService(mock_hue, engine, mock_ws)
    engine.register_external_light_owner(league)
    monkeypatch.setattr(
        "backend.api.routes.routines.load_setting",
        AsyncMock(return_value={"Ahri": {"r": 255, "g": 105, "b": 180}}),
    )
    await engine.report_activity("gaming", source="pc_agent")
    await league.apply("Ahri")
    engine._scene_overrides = {"gaming": {"evening": "native-scene"}}

    original_release = engine._release_external_owners_for_scene

    async def release_then_reacquire():
        accepted = await original_release()
        await league.apply("Ahri")
        return accepted

    monkeypatch.setattr(
        engine, "_release_external_owners_for_scene", release_then_reacquire,
    )
    await engine._apply_mode("gaming")

    assert engine.get_gaming_diagnostics()["transition_reason"] == "scene_override"
    assert engine._gaming_scene_transition_pending is False
    assert league.active_lights() == set()
    assert sync._accepted_gaming_targets == {}
    assert engine._protected_light_ids() == set()


@pytest.mark.asyncio
async def test_league_to_another_game_restores_new_accepted_composition(
    mock_hue, mock_hue_v2, mock_ws, monkeypatch,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    monkeypatch.setattr(engine, "_get_time_period", lambda now=None: "day")
    sync = ScreenSyncService(
        mock_hue,
        target_light_ids=["2", "5"],
        transition_boundary=engine._transition_boundary,
    )
    engine._screen_sync = sync
    league = LoLChampionService(mock_hue, engine, mock_ws)
    engine.register_external_light_owner(league)
    monkeypatch.setattr(
        "backend.api.routes.routines.load_setting",
        AsyncMock(return_value={"Ahri": {"r": 255, "g": 105, "b": 180}}),
    )
    await engine.report_activity("gaming", source="pc_agent")
    await league.apply("Ahri")

    await engine.report_activity(
        "gaming", source="pc_agent", factors=[{"key": "game", "value": "rust"}],
    )
    current = {
        light_id: engine._last_gaming_target[light_id].copy()
        for light_id in ("2", "5")
    }
    await league.on_activity_report(
        ActivityReport(
            mode="gaming",
            source="process",
            factors=[{"key": "game", "value": "rust"}],
        ),
        {"semantic_disposition": "accepted"},
    )

    assert league.active_lights() == set()
    for light_id, target in current.items():
        for key, value in target.items():
            assert mock_hue._lights[light_id][key] == value


@pytest.mark.asyncio
async def test_gaming_to_non_gaming_replaces_champion_in_same_mode_transition(
    mock_hue, mock_hue_v2, mock_ws, monkeypatch,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    sync = ScreenSyncService(
        mock_hue,
        target_light_ids=["2", "5"],
        transition_boundary=engine._transition_boundary,
    )
    engine._screen_sync = sync
    league = LoLChampionService(mock_hue, engine, mock_ws)
    engine.register_external_light_owner(league)
    engine.register_on_mode_change(league.on_mode_change)
    monkeypatch.setattr(
        "backend.api.routes.routines.load_setting",
        AsyncMock(return_value={"Ahri": {"r": 255, "g": 105, "b": 180}}),
    )
    await engine.report_activity("gaming", source="pc_agent")
    await league.apply("Ahri")

    await engine.report_activity("working", source="pc_agent")

    assert league.active_lights() == set()
    assert sync._accepted_gaming_targets == {}
    for light_id in ("2", "5"):
        expected = engine._last_applied_per_light[light_id]
        for key, value in expected.items():
            assert mock_hue._lights[light_id][key] == value


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
async def test_transit_clear_cannot_repaint_held_watching_lamps_after_frame_stales(
    mock_hue, mock_hue_v2, mock_ws, monkeypatch,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    monkeypatch.setattr(engine, "_get_time_period", lambda now=None: "night")
    engine._current_mode = "watching"

    desired = engine._get_desired_effect("watching")
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
    for light_id in ("2", "5"):
        await sync.apply_color(
            light_id, 1, 1, 100,
            mode="watching", source="desktop", period="night",
        )
    sync.refresh_watching_hold("desktop", ["2", "5"])

    stale_at = datetime.now(timezone.utc) - timedelta(
        seconds=SCREEN_SYNC_FRESH_SECONDS + 1,
    )
    sync._last_color_at = stale_at
    sync._last_color_at_by_light["2"] = stale_at
    sync._last_color_at_by_light["5"] = stale_at
    assert engine._protected_light_ids() == {"2", "5"}

    await engine.apply_transit_override(
        {"1": {"on": True, "bri": 55, "ct": 360}},
        duration_seconds=600,
        transition_time=5,
    )
    mock_hue.set_light.reset_mock()
    await engine.clear_transit_override(light_ids=["1"])

    writes = {
        call.args[0]: call.args[1]
        for call in mock_hue.set_light.await_args_list
    }
    assert "2" not in writes
    assert "5" not in writes
    assert engine._protected_light_ids() == {"2", "5"}


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
    sync.publish_accepted_gaming_state(resolve_activity_state("gaming", "day"))

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
