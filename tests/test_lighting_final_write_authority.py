"""#323 application integration contracts (all bridge writes are fixture fakes)."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.routes import scenes
from backend.services.automation_engine import AutomationEngine
from backend.services.screen_sync import ScreenSyncService


@asynccontextmanager
async def independent_blocker(boundary):
    entered, release = asyncio.Event(), asyncio.Event()

    async def block():
        async with boundary.serialized():
            entered.set()
            await release.wait()

    task = asyncio.create_task(block())
    await entered.wait()
    try:
        yield
    finally:
        release.set()
        await task


@pytest.fixture
def lighting(mock_hue, mock_hue_v2, mock_ws, monkeypatch):
    for lid, light in mock_hue._lights.items():
        light["light_id"] = lid
        light["colormode"] = "hs"
    original_write = mock_hue.set_light
    original_read = mock_hue.get_all_lights
    monkeypatch.setattr(mock_hue, "breaker_open", False, raising=False)

    async def detached_readback():
        return deepcopy(await original_read())

    async def acknowledge_color_space(lid, state):
        success = await original_write(lid, state)
        if success:
            if "ct" in state:
                mock_hue._lights[lid]["colormode"] = "ct"
            elif "hue" in state or "sat" in state:
                mock_hue._lights[lid]["colormode"] = "hs"
        return success

    monkeypatch.setattr(mock_hue, "set_light", acknowledge_color_space)
    monkeypatch.setattr(mock_hue, "get_all_lights", detached_readback)
    engine = AutomationEngine(mock_hue, mock_hue_v2, mock_ws)
    engine._current_mode = "gaming"
    engine._current_game = "rust"
    engine._effect_manager._tracker_known = True
    engine._last_applied_per_light = {lid: {"on": True, "bri": 100, "ct": 350} for lid in ("1", "2", "3", "4", "5", "6")}
    sync = ScreenSyncService(mock_hue, ["1", "2", "3", "4", "5"], engine.lighting_transition_boundary)
    engine._screen_sync = sync
    sync.set_lighting_authority_validator(engine.lighting_transition_boundary, engine.validate_screen_sync_lease)
    monkeypatch.setattr(scenes, "_try_it_state", {"trial": None})
    monkeypatch.setattr(scenes, "_try_control_lock", asyncio.Lock())
    monkeypatch.setattr(scenes, "_log_scene_activation", AsyncMock())
    request = SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace(
        hue=mock_hue, hue_v2=mock_hue_v2, automation=engine,
        effect_manager=engine._effect_manager, ws_manager=mock_ws,
    )))
    return engine, sync, request


def takeover(engine, sync, kind):
    authority = engine.lighting_transition_boundary.authority
    if kind == "manual":
        engine.mark_light_manual("2", {"bri": 20})
    elif kind == "away":
        engine.arm_away_suppression("test")
    elif kind == "sleeping":
        engine._override_mode = "sleeping"
        engine._manual_override = True
    elif kind == "lifecycle":
        engine._host_return_hold = True
    elif kind == "scene":
        authority.invalidate()  # EffectManager publishes serialized scene intent.
    elif kind == "screen_sync":
        sync._record_source_write("desktop", "2")
    elif kind == "auto":
        engine._clear_per_light_overrides()
    elif kind == "mode":
        engine._current_mode = "watching"
        engine._current_mode = "gaming"  # ABA must still revoke.
    elif kind == "transit":
        engine._transit_light_overrides["2"] = engine.manual_light_overrides.get("2")
        authority.invalidate(["2"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["manual", "away", "sleeping", "lifecycle", "scene", "screen_sync", "auto", "mode"])
async def test_try_it_waiting_restore_cannot_overwrite_new_authority(lighting, kind):
    engine, sync, request = lighting
    engine.mark_light_manual("2", {"bri": 100})  # The trial's own stamp is allowed.
    trial = {
        "engine": engine, "hue": request.app.state.hue, "ws": request.app.state.ws_manager,
        "snapshot": [{"light_id": "2", "on": True, "bri": 100, "ct": 350, "colormode": "ct"}],
        "lease": engine.lighting_transition_boundary.authority.issue("try_it", None),
    }
    scenes._try_it_state["trial"] = trial
    started = asyncio.Event()

    async def restore():
        started.set()
        return await scenes._restore_trial(trial, 10)

    with patch.object(request.app.state.hue, "set_light", wraps=request.app.state.hue.set_light) as write:
        async with independent_blocker(engine.lighting_transition_boundary):
            task = asyncio.create_task(restore())
            await started.wait()
            takeover(engine, sync, kind)
        assert await task is False
        write.assert_not_called()


@pytest.mark.asyncio
async def test_unchanged_try_it_reverts_and_supersedes_caches(lighting):
    engine, sync, request = lighting
    engine.mark_light_manual("2", {"bri": 20})
    trial = {
        "engine": engine, "hue": request.app.state.hue, "ws": request.app.state.ws_manager,
        "snapshot": [{"light_id": "2", "on": True, "bri": 100, "ct": 350, "colormode": "ct"}],
        "lease": engine.lighting_transition_boundary.authority.issue("try_it", None),
    }
    scenes._try_it_state["trial"] = trial
    assert await scenes._restore_trial(trial, 10)
    assert "2" not in engine._last_applied_per_light
    assert engine._state.manual_light_targets["2"]["bri"] == 100
    assert "2" not in sync.fresh_owned_light_ids()


@pytest.mark.asyncio
async def test_try_it_replacement_cancel_and_restart_fail_closed(lighting, monkeypatch):
    engine, sync, request = lighting
    holding = asyncio.Event()

    async def delay(seconds):
        if seconds == 30:
            holding.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(scenes.asyncio, "sleep", delay)
    await scenes.try_scene("deep_focus", request)
    old = scenes._try_it_state["trial"]
    await holding.wait()
    await scenes.try_scene("night_work", request)
    new = scenes._try_it_state["trial"]
    assert new is not old and old["task"].cancelled()
    assert scenes._try_it_state["trial"] is new
    engine.lighting_transition_boundary.authority.close()
    with patch.object(request.app.state.hue, "set_light", wraps=request.app.state.hue.set_light) as write:
        assert (await scenes.cancel_try(request))["status"] == "discarded"
        write.assert_not_called()
    assert scenes._try_it_state["trial"] is None and new["task"].cancelled()


@pytest.mark.asyncio
async def test_timer_cancellation_does_not_restore_or_clear_replacement(lighting, monkeypatch):
    engine, sync, request = lighting
    waiting = asyncio.Event()

    async def delay(seconds):
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(scenes.asyncio, "sleep", delay)
    old = {"engine": engine, "hue": request.app.state.hue}
    scenes._try_it_state["trial"] = old
    task = asyncio.create_task(scenes._revert_after_delay(old, 30))
    await waiting.wait()
    new = {}
    scenes._try_it_state["trial"] = new
    with patch.object(request.app.state.hue, "set_light", wraps=request.app.state.hue.set_light) as write:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        write.assert_not_called()
    assert scenes._try_it_state["trial"] is new


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [None, "manual", "away", "sleeping", "lifecycle", "scene", "screen_sync", "mode", "automation"])
async def test_native_scene_delayed_acknowledgement(lighting, monkeypatch, kind):
    engine, sync, request = lighting
    acknowledged, resume = asyncio.Event(), asyncio.Event()
    boundary = engine.lighting_transition_boundary
    issue = boundary.authority.issue
    captures = []

    def capture(producer, targets, **kwargs):
        if producer == "native_scene_ack":
            assert boundary.held_by_current_task
            captures.append(True)
        return issue(producer, targets, **kwargs)

    monkeypatch.setattr(boundary.authority, "issue", capture)

    real_sleep = asyncio.sleep

    async def delay(seconds):
        if seconds == 0.5 and not boundary.held_by_current_task:
            acknowledged.set()
            await resume.wait()
            return
        await real_sleep(0)

    monkeypatch.setattr(scenes.asyncio, "sleep", delay)
    with patch.object(engine, "mark_light_manual", wraps=engine.mark_light_manual) as mark:
        task = asyncio.create_task(scenes._activate_scene("native-test", request))
        await acknowledged.wait()
        assert captures == [True]
        if kind == "automation":
            await engine._apply_per_light({"2": {"on": True, "bri": 50, "ct": 350}}, 0)
        elif kind is not None:
            takeover(engine, sync, kind)
        mark.reset_mock()
        resume.set()
        assert (await task)["status"] == "ok"
        if kind is None:
            assert mark.call_count == len(await request.app.state.hue.get_all_lights())
        else:
            mark.assert_not_called()


@pytest.mark.asyncio
async def test_registered_external_owner_notifier_and_disjoint_light(lighting):
    engine, sync, request = lighting

    class Owner:
        def __init__(self):
            self.targets = {}

        def set_lighting_authority_notifier(self, notifier):
            self.notify = notifier

        def owned_light_targets(self):
            return self.targets.copy()

    owner = Owner()
    engine.register_external_light_owner(owner)
    boundary = engine.lighting_transition_boundary
    lease = boundary.authority.issue("rust", ["2"])
    owner.targets = {"3": {"bri": 100}}
    owner.notify(["3"])
    async with boundary.serialized():
        assert engine.validate_lighting_lease(lease, allow_screen_sync=True)
    owner.targets = {"2": {"bri": 100}}
    owner.notify(["2", "3"])
    owner.targets = {}
    owner.notify(["2"])
    async with boundary.serialized():
        assert not engine.validate_lighting_lease(lease, allow_screen_sync=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["manual", "transit", "screen_sync", "external", "mode", "away"])
async def test_rust_final_restore_respects_real_engine_owners(lighting, monkeypatch, kind):
    from backend.services.rust_event_service import RustEventService

    engine, sync, request = lighting
    rust = RustEventService(request.app.state.hue, sync, engine)
    holding, resume = asyncio.Event(), asyncio.Event()

    async def hold(seconds):
        holding.set()
        await resume.wait()

    monkeypatch.setattr("backend.services.rust_event_service.asyncio.sleep", hold)
    with patch.object(request.app.state.hue, "set_light", wraps=request.app.state.hue.set_light) as write:
        await rust.report_damage(100)
        task = rust._flinch_task
        await holding.wait()
        assert write.call_count == 2
        if kind == "transit":
            await engine.apply_transit_override({"2": {"on": True, "bri": 200, "ct": 350}})
        elif kind == "external":
            class Owner:
                def set_lighting_authority_notifier(self, notifier):
                    self.notify = notifier

                def owned_light_targets(self):
                    return {"2": {"on": True, "bri": 200}}

            owner = Owner()
            engine.register_external_light_owner(owner)
            owner.notify(["2"])
        else:
            takeover(engine, sync, kind)
        write.reset_mock()
        resume.set()
        await task
        restored = {call.args[0] for call in write.call_args_list}
        assert "2" not in restored
        if kind in {"manual", "transit", "screen_sync", "external"}:
            assert restored == {"5"}  # A disjoint per-light lease stays valid.
        else:
            assert not restored
        assert rust._flinch_task is None and not rust._flinching


@pytest.mark.asyncio
async def test_rust_baseline_requires_source_qualified_rust_frame(lighting):
    engine, sync, request = lighting
    await sync.apply_color("2", 255, 0, 0, "gaming")  # No accepted Gaming plan: no owner.
    sync._last_sent_state["2"] = {"bri": 100, "hue": 1000, "sat": 100}
    sync._record_source_write("laptop", "2")
    authority = engine.lighting_transition_boundary.authority
    lease = authority.issue("rust", ["2"])
    async with engine.lighting_transition_boundary.serialized():
        assert not engine.validate_lighting_lease(lease, allow_screen_sync=True, screen_sync_kind="rust")
    sync.supersede_light("2")
    assert await sync.apply_rust_brightness("2", 100)
    lease = authority.issue("rust", ["2"])
    async with engine.lighting_transition_boundary.serialized():
        assert engine.validate_lighting_lease(lease, allow_screen_sync=True, screen_sync_kind="rust")


@pytest.mark.asyncio
async def test_rust_overlay_preserves_screen_source_and_forgets_automation_target(lighting, monkeypatch):
    from backend.services.rust_event_service import RustEventService

    engine, sync, request = lighting
    assert await sync.apply_rust_brightness("2", 100)
    observed = sync.last_color_at_by_light["2"]
    rust = RustEventService(request.app.state.hue, sync, engine)
    monkeypatch.setattr("backend.services.rust_event_service.asyncio.sleep", AsyncMock())
    with patch.object(request.app.state.hue, "set_light", wraps=request.app.state.hue.set_light) as write:
        await rust._do_flinch()
    assert len([call for call in write.call_args_list if call.args[0] == "2"]) == 2
    assert "2" not in engine._last_applied_per_light
    assert sync.rust_owned_light_ids() == {"2"}
    assert sync.last_color_at_by_light["2"] == observed
    assert sync.authoritative_state("2") is None  # Next source frame must reconcile.
    with patch.object(request.app.state.hue, "set_light", wraps=request.app.state.hue.set_light) as write:
        assert await sync.apply_rust_brightness("2", 100)
        write.assert_called_once()


@pytest.mark.asyncio
async def test_trial_cannot_adopt_new_intent_during_scene_safety(lighting, monkeypatch):
    from fastapi import HTTPException

    engine, sync, request = lighting
    writing, resume = asyncio.Event(), asyncio.Event()
    write = request.app.state.hue.set_light

    async def wait_for_ack(lid, state):
        if lid == "2":
            writing.set()
            await resume.wait()
        return await write(lid, state)

    async def immediate_delay(seconds):
        return None

    monkeypatch.setattr(request.app.state.hue, "set_light", wait_for_ack)
    monkeypatch.setattr(scenes.asyncio, "sleep", immediate_delay)
    task = asyncio.create_task(scenes.try_scene("deep_focus", request))
    await writing.wait()
    engine.mark_light_manual("2", {"bri": 20})
    resume.set()
    with pytest.raises(HTTPException) as exc_info:
        await task
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail in {
        "Scene trial authority changed",
        "Scene transition aborted: safe effect release not established",
    }
    assert scenes._try_it_state["trial"] is None
    assert engine._state.manual_light_targets["2"]["bri"] == 20


@pytest.mark.asyncio
async def test_native_try_it_survives_its_own_screen_sync_release(lighting, monkeypatch):
    engine, sync, request = lighting
    assert await sync.apply_rust_brightness("2", 100, source="desktop")
    assert "2" in sync.fresh_owned_light_ids()

    real_sleep = scenes.asyncio.sleep

    async def bounded_sleep(seconds):
        if seconds == 0.5:
            return
        await real_sleep(0)

    monkeypatch.setattr(scenes.asyncio, "sleep", bounded_sleep)
    result = await scenes.try_scene("native-test", request)
    assert result["status"] == "ok"
    trial = scenes._try_it_state["trial"]
    assert trial is not None and trial["lease"] is not None
    await scenes.close_scene_trials()


@pytest.mark.asyncio
async def test_away_convergence_rejects_queued_screensync_and_keeps_failed_off_suppressed(
    lighting, monkeypatch,
):
    from backend.services.away_manager import AwayManager
    engine, sync, request = lighting
    hue = request.app.state.hue
    monkeypatch.setattr("backend.services.away_manager.OFF_RETRY_DELAYS", (0,))
    manager = AwayManager(
        engine=engine, hue_getter=lambda: hue, sonos_getter=lambda: None,
        tts_getter=lambda: None, notifier_getter=lambda: None,
        save_setting=AsyncMock(), load_setting=AsyncMock(return_value=None),
    )
    original = hue.set_light
    writes = []
    fail_once = True

    async def write(lid, state):
        nonlocal fail_once
        writes.append((lid, dict(state)))
        if lid == "2" and fail_once and state.get("on") is False:
            fail_once = False
            return False
        return await original(lid, state)

    monkeypatch.setattr(hue, "set_light", write)
    async with independent_blocker(engine.lighting_transition_boundary):
        queued_on = asyncio.create_task(sync.apply_rust_brightness("2", 150))
        await asyncio.sleep(0)
        leave = asyncio.create_task(manager.handle_event("leave", "test"))
        # Leave arms suppression synchronously before waiting for Hue boundary.
        for _ in range(3):
            await asyncio.sleep(0)
        assert engine._away_hold
    assert await queued_on is False
    await leave
    await manager._off_task
    assert manager.status()["off_convergence"]["outcome"] == "converged"
    assert all(state.get("on") is False for _, state in writes)
    assert [lid for lid, _ in writes].count("2") == 2
    assert engine._away_hold and engine._external_off_detected
    await manager.close()


@pytest.mark.asyncio
async def test_bridge_loss_preserves_external_off_and_hard_hold(lighting):
    engine, _, request = lighting
    engine.arm_away_suppression("test")
    # Fixture Hue exposes connected as a normal attribute.
    request.app.state.hue.connected = False
    assert await engine._check_external_off() is True
    assert engine._away_hold and engine._external_off_detected
