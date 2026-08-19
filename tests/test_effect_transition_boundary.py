"""Regression coverage for serialized, settled Hue effect release safety."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routes.scenes import _activate_scene_safely
from backend.services.automation_constants import TZ
from backend.services.automation_engine import AutomationEngine
from backend.services.effect_manager import EffectManager
from backend.services.hue_service import HueService
from backend.services.light_applicator import LightApplyResult
from backend.services.lighting_transition_boundary import LightingTransitionBoundary
from backend.services.screen_sync import ScreenSyncService


def _engine(mock_hue, mock_hue_v2, mock_ws) -> AutomationEngine:
    return AutomationEngine(mock_hue, mock_hue_v2, mock_ws)


@pytest.mark.asyncio
async def test_effect_to_static_waits_for_writes_and_physical_settle():
    events: list[str] = []
    settle_entered = asyncio.Event()
    allow_settle = asyncio.Event()

    class Hue:
        async def wait_for_transition_settle(self, light_ids) -> None:
            events.append("settle_started")
            settle_entered.set()
            await allow_settle.wait()
            events.append("settled")

    hue_v2 = MagicMock()
    hue_v2.connected = True
    hue_v2.mapped_light_ids = ["1", "2"]

    async def stop_all() -> bool:
        events.append("no_effect")
        return True

    hue_v2.stop_effect_all = stop_all
    manager = EffectManager(
        hue_v2,
        transition_boundary=LightingTransitionBoundary(Hue()),
    )
    manager._active_name = "glisten"
    manager._tracker_known = True

    async def establish(required: set[str]) -> LightApplyResult:
        events.extend(f"write:{light_id}" for light_id in sorted(required))
        return LightApplyResult(successful=set(required))

    task = asyncio.create_task(
        manager.reconcile(None, establish_safety=establish)
    )
    await settle_entered.wait()

    assert events == ["write:1", "write:2", "settle_started"]
    assert "no_effect" not in events

    allow_settle.set()
    assert await task is True
    assert events[-2:] == ["settled", "no_effect"]


@pytest.mark.asyncio
async def test_sleeping_release_waits_for_acknowledged_transition_deadlines():
    events: list[str] = []
    writes: dict[str, dict] = {}
    settle_entered = asyncio.Event()
    allow_settle = asyncio.Event()

    class Hue:
        connected = True

        async def set_light(self, light_id: str, state: dict) -> bool:
            writes[light_id] = state.copy()
            events.append(f"safety_write:{light_id}")
            return True

        async def wait_for_transition_settle(self, light_ids) -> None:
            assert set(light_ids) == set(writes)
            events.append("settle_started")
            settle_entered.set()
            await allow_settle.wait()
            events.append("settled")

    hue = Hue()
    hue_v2 = MagicMock()
    hue_v2.connected = True
    hue_v2.mapped_light_ids = ["1", "2", "3"]

    async def stop_all() -> bool:
        events.append("no_effect")
        return True

    hue_v2.stop_effect_all = stop_all
    manager = EffectManager(
        hue_v2,
        transition_boundary=LightingTransitionBoundary(hue),
    )
    manager._active_name = "glisten"
    manager._tracker_known = True
    engine = AutomationEngine(
        hue,
        hue_v2,
        MagicMock(),
        effect_manager=manager,
    )

    async def fade() -> None:
        events.append("fade")

    engine._sleep_fade = fade
    task = asyncio.create_task(engine._apply_mode("sleeping", force_resend=True))
    await settle_entered.wait()

    assert set(writes) == {"1", "2", "3"}
    assert all(state["bri"] == 20 for state in writes.values())
    assert all(state["transitiontime"] == 10 for state in writes.values())
    assert "no_effect" not in events
    assert "fade" not in events

    allow_settle.set()
    await task
    await engine._sleep_fade_task

    assert events.index("settled") < events.index("no_effect") < events.index("fade")


@pytest.mark.asyncio
async def test_sleeping_release_preserves_fresh_screen_sync_targets():
    events: list[str] = []
    writes: dict[str, dict] = {}

    class Hue:
        connected = True

        async def set_light(self, light_id: str, state: dict) -> bool:
            writes[light_id] = state.copy()
            events.append(f"write:{light_id}")
            return True

        async def wait_for_transition_settle(self, light_ids) -> None:
            assert set(light_ids) == {"2", "5"}
            events.append("settled")

    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    hue_v2 = MagicMock()
    hue_v2.connected = True
    hue_v2.mapped_light_ids = ["2", "5"]

    async def stop_all() -> bool:
        events.append("no_effect")
        return True

    hue_v2.stop_effect_all = stop_all
    manager = EffectManager(hue_v2, transition_boundary=boundary)
    manager._active_name = "glisten"
    manager._tracker_known = True
    sync = ScreenSyncService(
        hue,
        target_light_ids=["2", "5"],
        transition_boundary=boundary,
    )
    await sync.apply_color("2", 255, 0, 0, mode="watching")
    await sync.apply_color("5", 0, 0, 255, mode="watching")
    await sync.apply_color("2", 255, 0, 0, mode="watching")
    await sync.apply_color("5", 0, 0, 255, mode="watching")
    held = {
        light_id: sync.authoritative_state(light_id)
        for light_id in ("2", "5")
    }
    writes.clear()
    events.clear()

    engine = AutomationEngine(
        hue,
        hue_v2,
        MagicMock(),
        effect_manager=manager,
        screen_sync=sync,
    )
    engine._current_mode = "sleeping"
    engine._sleep_fade = AsyncMock()

    await engine._apply_mode("sleeping")
    await engine._sleep_fade_task

    for light_id, target in held.items():
        assert {
            key: writes[light_id][key] for key in target
        } == target
        assert writes[light_id]["transitiontime"] == 10
        assert writes[light_id]["bri"] != 20
        assert sync.authoritative_state(light_id) == target
    assert set(events[:2]) == {"write:2", "write:5"}
    assert events[2:] == ["settled", "no_effect"]


@pytest.mark.asyncio
async def test_sleeping_release_rejects_stale_screen_sync_targets():
    events: list[str] = []
    writes: dict[str, dict] = {}

    class Hue:
        connected = True

        async def set_light(self, light_id: str, state: dict) -> bool:
            writes[light_id] = state.copy()
            return True

        async def wait_for_transition_settle(self, _light_ids) -> None:
            events.append("settled")

    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    hue_v2 = MagicMock()
    hue_v2.connected = True
    hue_v2.mapped_light_ids = ["2", "5"]

    async def stop_all() -> bool:
        events.append("no_effect")
        return True

    hue_v2.stop_effect_all = stop_all
    manager = EffectManager(hue_v2, transition_boundary=boundary)
    manager._active_name = "glisten"
    manager._tracker_known = True
    sync = ScreenSyncService(hue, target_light_ids=["2", "5"])
    await sync.apply_color("2", 255, 0, 0, mode="watching")
    await sync.apply_color("5", 0, 0, 255, mode="watching")
    sync._last_color_at -= timedelta(seconds=30)
    writes.clear()

    engine = AutomationEngine(
        hue,
        hue_v2,
        MagicMock(),
        effect_manager=manager,
        screen_sync=sync,
    )
    engine._current_mode = "sleeping"
    engine._sleep_fade = AsyncMock()

    await engine._apply_mode("sleeping")
    await engine._sleep_fade_task

    assert {state["bri"] for state in writes.values()} == {20}
    assert events == ["settled", "no_effect"]


@pytest.mark.asyncio
async def test_sleeping_release_blocks_screen_sync_through_no_effect():
    events: list[str] = []
    settle_entered = asyncio.Event()
    allow_settle = asyncio.Event()

    class Hue:
        connected = True

        async def set_light(self, light_id: str, state: dict) -> bool:
            source = "sleep" if state.get("bri") == 20 else "screen"
            events.append(f"{source}_write:{light_id}")
            return True

        async def wait_for_transition_settle(self, _light_ids) -> None:
            events.append("settle_started")
            settle_entered.set()
            await allow_settle.wait()
            events.append("settled")

    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    hue_v2 = MagicMock()
    hue_v2.connected = True
    hue_v2.mapped_light_ids = ["2", "5"]

    async def stop_all() -> bool:
        events.append("no_effect")
        return True

    hue_v2.stop_effect_all = stop_all
    manager = EffectManager(hue_v2, transition_boundary=boundary)
    manager._active_name = "glisten"
    manager._tracker_known = True
    sync = ScreenSyncService(
        hue,
        target_light_ids=["2", "5"],
        transition_boundary=boundary,
    )
    engine = AutomationEngine(
        hue,
        hue_v2,
        MagicMock(),
        effect_manager=manager,
        screen_sync=sync,
    )
    engine._sleep_fade = AsyncMock()

    sleeping = asyncio.create_task(engine._apply_mode("sleeping"))
    await settle_entered.wait()
    screen = asyncio.create_task(
        sync.apply_color("2", 255, 0, 0, mode="watching"),
    )
    await asyncio.sleep(0)

    assert not any(event.startswith("screen_write:") for event in events)
    assert "no_effect" not in events

    allow_settle.set()
    await asyncio.wait_for(asyncio.gather(sleeping, screen), timeout=1.0)
    await engine._sleep_fade_task

    screen_index = next(
        index for index, event in enumerate(events)
        if event.startswith("screen_write:")
    )
    assert events.index("settled") < events.index("no_effect") < screen_index


@pytest.mark.asyncio
async def test_sleeping_release_reestablishes_transit_targets_without_clearing_owner(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    manager = engine._effect_manager
    manager._active_name = "glisten"
    manager._tracker_known = True
    deadline = datetime.now(tz=TZ) + timedelta(minutes=5)
    held = {
        "1": {"on": True, "bri": 75, "ct": 400},
        "3": {"on": True, "bri": 35, "ct": 400},
        "4": {"on": True, "bri": 35, "ct": 400},
    }
    engine._transit_light_overrides = {
        light_id: deadline for light_id in held
    }
    engine._state.transit_light_targets = {
        light_id: state.copy() for light_id, state in held.items()
    }
    calls: list[tuple[str, dict]] = []
    events: list[str] = []

    async def write(light_id: str, state: dict) -> bool:
        calls.append((light_id, state.copy()))
        events.append(f"write:{light_id}")
        return True

    async def settle(_light_ids) -> None:
        events.append("settled")

    async def stop_all() -> bool:
        events.append("no_effect")
        return True

    mock_hue.set_light = write
    mock_hue.wait_for_transition_settle = settle
    mock_hue_v2.stop_effect_all = stop_all
    engine._sleep_fade = AsyncMock()

    await engine._apply_mode("sleeping", force_resend=True)
    await engine._sleep_fade_task

    by_id = {light_id: state for light_id, state in calls}
    for light_id, target in held.items():
        assert {
            key: by_id[light_id][key] for key in target
        } == target
        assert by_id[light_id]["transitiontime"] == 10
    assert set(engine._transit_light_overrides) == {"1", "3", "4"}
    assert engine._state.transit_light_targets == held
    assert events.index("settled") < events.index("no_effect")


@pytest.mark.asyncio
async def test_failed_sleeping_safety_write_aborts_release_and_retries(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    manager = engine._effect_manager
    manager._active_name = "glisten"
    manager._tracker_known = True
    attempts: list[str] = []

    async def fail_l3(light_id: str, _state: dict) -> bool:
        attempts.append(light_id)
        return light_id != "3"

    mock_hue.set_light = fail_l3
    mock_hue.wait_for_transition_settle = AsyncMock()
    mock_hue_v2.stop_effect_all = AsyncMock(return_value=True)
    engine._sleep_fade = AsyncMock()

    await engine._apply_mode("sleeping", force_resend=True)

    mock_hue.wait_for_transition_settle.assert_not_awaited()
    mock_hue_v2.stop_effect_all.assert_not_awaited()
    engine._sleep_fade.assert_not_awaited()
    assert engine._sleep_fade_task is None
    assert manager.active_name == "glisten"
    assert "3" not in engine._last_applied_per_light

    await engine._apply_mode("sleeping", force_resend=False)

    assert attempts.count("3") == 2
    mock_hue_v2.stop_effect_all.assert_not_awaited()
    assert manager.active_name == "glisten"


@pytest.mark.asyncio
async def test_unknown_tracker_still_requires_safety_before_stop():
    hue_v2 = MagicMock()
    hue_v2.connected = True
    hue_v2.mapped_light_ids = ["1"]
    hue_v2.stop_effect_all = AsyncMock(return_value=True)
    manager = EffectManager(hue_v2)
    establish = AsyncMock(
        return_value=LightApplyResult(successful={"1"}),
    )

    assert await manager.reconcile(None, establish_safety=establish) is True

    establish.assert_awaited_once_with({"1"})
    hue_v2.stop_effect_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_partial_write_dedup_is_independent_and_failed_light_retries(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    attempts: list[str] = []

    async def mixed(light_id: str, _state: dict) -> bool:
        attempts.append(light_id)
        return light_id != "3"

    mock_hue.set_light = mixed
    states = {
        "1": {"on": True, "bri": 75, "ct": 400},
        "3": {"on": True, "bri": 35, "ct": 400},
        "4": {"on": True, "bri": 35, "ct": 400},
    }

    first = await engine._apply_per_light(states, transitiontime=30)

    assert first.successful == {"1", "4"}
    assert first.failed == {"3"}
    assert set(engine._last_applied_per_light) == {"1", "4"}

    attempts.clear()
    second = await engine._apply_per_light(states, transitiontime=30)
    assert attempts == ["3"]
    assert second.failed == {"3"}


@pytest.mark.asyncio
async def test_failed_required_safety_write_aborts_release_and_stays_retryable(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    engine._get_time_period = lambda now=None: "night"
    mock_hue_v2.stop_effect_all = AsyncMock(return_value=True)
    attempts: list[str] = []

    async def fail_l3(light_id: str, state: dict) -> bool:
        attempts.append(light_id)
        return light_id != "3"

    mock_hue.set_light = fail_l3
    await engine._apply_mode("watching", force_resend=True)

    mock_hue_v2.stop_effect_all.assert_not_awaited()
    assert "3" not in engine._last_applied_per_light

    attempts.clear()
    await engine._apply_mode("watching", force_resend=False)
    assert "3" in attempts
    mock_hue_v2.stop_effect_all.assert_not_awaited()


@pytest.mark.asyncio
async def test_transit_protected_gaming_to_watching_reestablishes_held_targets(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    engine._get_time_period = lambda now=None: "night"
    deadline = datetime.now(tz=TZ) + timedelta(minutes=5)
    held = {
        "1": {"on": True, "bri": 75, "ct": 400},
        "3": {"on": True, "bri": 35, "ct": 400},
        "4": {"on": True, "bri": 35, "ct": 400},
    }
    engine._transit_light_overrides = {
        light_id: deadline for light_id in held
    }
    engine._state.transit_light_targets = {
        light_id: state.copy() for light_id, state in held.items()
    }
    calls: list[tuple[str, dict]] = []

    async def write(light_id: str, state: dict) -> bool:
        calls.append((light_id, state.copy()))
        return True

    mock_hue.set_light = write
    mock_hue_v2.stop_effect_all = AsyncMock(return_value=True)
    mock_hue_v2.set_effect = AsyncMock(return_value=True)
    engine._transition_boundary.wait_for_settle = AsyncMock()

    await engine._apply_mode("watching", force_resend=True)

    by_id = {light_id: state for light_id, state in calls}
    for light_id, target in held.items():
        assert by_id[light_id]["bri"] == target["bri"]
    assert set(engine._transit_light_overrides) == {"1", "3", "4"}
    assert engine._state.transit_light_targets == held
    engine._transition_boundary.wait_for_settle.assert_awaited_once()
    mock_hue_v2.stop_effect_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_watching_three_second_ack_is_not_physical_completion():
    hue = HueService("bridge", "user")
    hue._connected = True
    hue._bridge = MagicMock()
    hue._safe_call = AsyncMock(return_value=None)

    with (
        patch(
            "backend.services.hue_service.time.monotonic",
            side_effect=[100.0, 100.0, 100.0, 103.0],
        ),
        patch(
            "backend.services.hue_service.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep_mock,
    ):
        assert await hue.set_light(
            "1", {"on": True, "bri": 75, "transitiontime": 30},
        )
        await hue.wait_for_transition_settle(["1"])

    sleep_mock.assert_awaited_once_with(3.0)


@pytest.mark.asyncio
async def test_transition_lock_blocks_periodic_and_screen_writers_without_deadlock():
    settle_entered = asyncio.Event()
    allow_settle = asyncio.Event()
    events: list[str] = []

    class Hue:
        connected = True

        async def wait_for_transition_settle(self, _light_ids) -> None:
            events.append("settle")
            settle_entered.set()
            await allow_settle.wait()

        async def set_light(self, light_id: str, state: dict) -> bool:
            events.append(f"hue_write:{light_id}:{state['bri']}")
            return True

    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    hue_v2 = MagicMock()
    hue_v2.connected = True
    hue_v2.mapped_light_ids = ["2"]

    async def stop_effect() -> bool:
        events.append("no_effect")
        return True

    hue_v2.stop_effect_all = stop_effect
    manager = EffectManager(hue_v2, transition_boundary=boundary)
    sync = ScreenSyncService(
        hue,
        target_light_ids=["2"],
        transition_boundary=boundary,
    )
    engine = AutomationEngine(
        hue,
        hue_v2,
        MagicMock(),
        effect_manager=manager,
        screen_sync=sync,
    )

    async def establish(required: set[str]) -> LightApplyResult:
        events.append("mode_write")
        return LightApplyResult(successful=set(required))

    transition = asyncio.create_task(
        manager.reconcile(None, establish_safety=establish),
    )
    await settle_entered.wait()
    periodic = asyncio.create_task(
        engine._apply_per_light(
            {"2": {"on": True, "bri": 80, "ct": 400}},
            transitiontime=20,
        )
    )
    screen = asyncio.create_task(
        sync.apply_color("2", 255, 0, 0, mode="watching"),
    )
    await asyncio.sleep(0)

    assert events == ["mode_write", "settle"]

    allow_settle.set()
    await asyncio.wait_for(
        asyncio.gather(transition, periodic, screen),
        timeout=1.0,
    )
    assert events[2] == "no_effect"
    assert len([event for event in events if event.startswith("hue_write:")]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_preset_and_native_scene_paths_release_only_after_safety(
    native: bool,
):
    events: list[str] = []

    class Hue:
        async def wait_for_transition_settle(self, _light_ids) -> None:
            events.append("settled")

    hue_v2 = MagicMock()
    hue_v2.connected = True
    hue_v2.mapped_light_ids = ["1"]

    async def stop() -> bool:
        events.append("no_effect")
        return True

    hue_v2.stop_effect_all = stop
    hue_v2.set_effect_all = AsyncMock(return_value=True)
    manager = EffectManager(
        hue_v2,
        transition_boundary=LightingTransitionBoundary(Hue()),
    )

    class Automation:
        async def establish_effect_release(
            self, _states, _transitiontime, required,
        ) -> LightApplyResult:
            events.append("safety_write")
            return LightApplyResult(successful=set(required))

    async def native_action() -> bool:
        events.append("native_scene")
        return True

    assert await _activate_scene_safely(
        Automation(),
        manager,
        {"1": {"on": True, "bri": 80, "ct": 400}},
        None,
        action=native_action if native else None,
    )

    expected = ["safety_write", "settled", "no_effect"]
    if native:
        expected.append("native_scene")
    assert events == expected


@pytest.mark.asyncio
async def test_transit_clear_effect_reconcile_uses_safe_order(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    engine._current_mode = "watching"
    engine._get_time_period = lambda now=None: "night"
    engine._transit_light_overrides = {
        "1": datetime.now(tz=TZ) + timedelta(minutes=5),
    }
    engine._state.transit_light_targets = {
        "1": {"on": True, "bri": 75, "ct": 400},
    }
    events: list[str] = []

    async def write(light_id: str, _state: dict) -> bool:
        events.append(f"write:{light_id}")
        return True

    async def settle(_light_ids) -> None:
        events.append("settled")

    async def stop() -> bool:
        events.append("no_effect")
        return True

    mock_hue.set_light = write
    engine._transition_boundary.wait_for_settle = settle
    mock_hue_v2.stop_effect_all = stop
    mock_hue_v2.set_effect = AsyncMock(return_value=True)

    await engine.clear_transit_override(["1"])

    assert "1" not in engine._transit_light_overrides
    assert events.index("settled") > max(
        index for index, value in enumerate(events) if value.startswith("write:")
    )
    assert events.index("no_effect") > events.index("settled")


@pytest.mark.asyncio
async def test_august_3_254_fixture_never_exposes_unprotected_transit_lamps(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = _engine(mock_hue, mock_hue_v2, mock_ws)
    engine._get_time_period = lambda now=None: "night"
    deadline = datetime.now(tz=TZ) + timedelta(minutes=5)
    held_bri = {"1": 75, "3": 35, "4": 35}
    engine._transit_light_overrides = {
        light_id: deadline for light_id in held_bri
    }
    engine._state.transit_light_targets = {
        light_id: {"on": True, "bri": bri, "ct": 400}
        for light_id, bri in held_bri.items()
    }
    physical = {light_id: 254 for light_id in ["1", "2", "3", "4", "5"]}
    exposed_254: list[str] = []

    async def write(light_id: str, state: dict) -> bool:
        physical[light_id] = state["bri"]
        return True

    async def unsafe_release_model() -> bool:
        for light_id in held_bri:
            if physical[light_id] == 254:
                exposed_254.append(light_id)
        return True

    mock_hue.set_light = write
    mock_hue_v2.stop_effect_all = unsafe_release_model
    mock_hue_v2.set_effect = AsyncMock(return_value=True)
    engine._transition_boundary.wait_for_settle = AsyncMock()

    await engine._apply_mode("watching", force_resend=True)

    assert exposed_254 == []
    assert {light_id: physical[light_id] for light_id in held_bri} == held_bri
