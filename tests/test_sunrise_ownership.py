"""Sunrise final-write authority tests; all hardware is mocked."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.automation_engine import AutomationEngine
from backend.services.morning_routine import MorningRoutineService
from backend.services.scheduler import AsyncScheduler, ScheduledTask
import backend.services.scheduler as scheduler_module


@pytest.fixture
def engine(mock_hue, mock_hue_v2, mock_ws):
    engine = AutomationEngine(mock_hue, mock_hue_v2, mock_ws)
    engine.is_dnd_active = lambda: False
    engine._effect_manager._tracker_known = True
    mock_hue.set_light = AsyncMock(return_value=True)
    return engine


@pytest.fixture
def morning(engine, monkeypatch):
    monkeypatch.setattr("backend.services.morning_routine.asyncio.sleep", AsyncMock())
    return MorningRoutineService(None, engine)


def block(engine, authority):
    now = datetime.now(timezone.utc)
    if authority == "dnd":
        engine.is_dnd_active = lambda: True
    elif authority == "away":
        engine._away_hold = True
    elif authority == "external_off":
        engine._external_off_detected = True
    elif authority == "manual":
        engine._state.manual_light_overrides["2"] = now
    elif authority == "transit":
        engine._state.transit_light_overrides["2"] = now + timedelta(minutes=5)
    elif authority == "sync":
        engine._current_mode = "watching"
        engine._screen_sync = SimpleNamespace(fresh_owned_light_ids=lambda: {"2"})
    elif authority == "owner":
        engine.register_external_light_owner(SimpleNamespace(
            owned_light_targets=lambda: {"2": {"on": True}}))
    elif authority == "scene":
        engine._active_scene_override_key = ("working", "day", "native", "bridge")
    elif authority == "scene_pending":
        engine._gaming_scene_transition_pending = True
    elif authority == "effect_unknown":
        engine._effect_manager._tracker_known = False
    elif authority in {"effect", "effect_all"}:
        engine._effect_manager._active_name = "fire"
        engine._effect_manager._active_lights = ["2"] if authority == "effect" else None


AUTHORITIES = ["dnd", "away", "external_off", "manual", "transit", "sync",
               "owner", "scene", "scene_pending", "effect_unknown",
               "effect", "effect_all"]


@pytest.mark.parametrize("authority", AUTHORITIES)
async def test_authority_stops_ramp(engine, morning, authority):
    block(engine, authority)
    assert await morning.sunrise_ramp() is False
    engine._hue.set_light.assert_not_called()


async def test_payload_and_no_lifecycle_mutation(engine, morning):
    engine._current_mode = "sleeping"
    before = (engine.current_mode, engine.house_state, engine._away_hold,
              engine._override_mode, engine._external_off_detected)
    engine._effect_manager._active_name = "fire"
    engine._effect_manager._active_lights = ["5"]
    assert await morning.sunrise_ramp() is True
    calls = engine._hue.set_light.call_args_list
    assert len(calls) == 16
    assert calls[0].args == ("2", {"on": True, "ct": 500, "bri": 1, "transitiontime": 120})
    assert calls[-1].args == ("2", {"on": True, "ct": 250, "bri": 150, "transitiontime": 120})
    assert all(set(call.args[1]) == {"on", "ct", "bri", "transitiontime"} for call in calls)
    assert before == (engine.current_mode, engine.house_state, engine._away_hold,
                      engine._override_mode, engine._external_off_detected)


async def test_deduplicated_step_is_accepted(engine, morning):
    engine._last_applied_per_light["2"] = {"on": True, "ct": 500, "bri": 1}
    assert await morning.sunrise_ramp() is True
    assert engine._hue.set_light.await_count == 15


@pytest.mark.parametrize("failure", [False, RuntimeError("bridge failure")])
async def test_failed_step_stops_future_steps(engine, morning, failure):
    engine._hue.set_light.side_effect = [True, failure]
    assert await morning.sunrise_ramp() is False
    assert engine._hue.set_light.await_count == 2


@pytest.mark.parametrize("authority", AUTHORITIES)
async def test_final_step_rechecks_after_boundary(engine, morning, monkeypatch, authority):
    reached = asyncio.Event()
    resume = asyncio.Event()
    sleeps = 0

    async def interval(seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 15:
            reached.set()
            await resume.wait()

    monkeypatch.setattr("backend.services.morning_routine.asyncio.sleep", interval)
    task = asyncio.create_task(morning.sunrise_ramp())
    await reached.wait()
    async with engine._transition_boundary.serialized():
        resume.set()
        checkpoint = asyncio.Event()
        asyncio.get_running_loop().call_soon(checkpoint.set)
        await checkpoint.wait()
        assert engine._hue.set_light.await_count == 15
        assert not task.done()
        block(engine, authority)
    assert await task is False
    assert engine._hue.set_light.await_count == 15


@pytest.mark.parametrize("location", ["interval", "boundary", "write"])
async def test_overlap_and_cancellation_restart(engine, morning, monkeypatch, location):
    entered = asyncio.Event()
    wait = asyncio.Event()

    async def pause(*args):
        entered.set()
        await wait.wait()
        return True

    if location == "interval":
        monkeypatch.setattr("backend.services.morning_routine.asyncio.sleep", pause)
    elif location == "write":
        engine._hue.set_light.side_effect = pause
    if location == "boundary":
        release_boundary = asyncio.Event()

        async def hold_boundary():
            async with engine._transition_boundary.serialized():
                entered.set()
                await release_boundary.wait()

        blocker = asyncio.create_task(hold_boundary())
        await entered.wait()
        task = asyncio.create_task(morning.sunrise_ramp())
        checkpoint = asyncio.Event()
        asyncio.get_running_loop().call_soon(checkpoint.set)
        await checkpoint.wait()
        assert await asyncio.wait_for(morning.sunrise_ramp(), 0.5) is False
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release_boundary.set()
        await blocker
    else:
        task = asyncio.create_task(morning.sunrise_ramp())
        await entered.wait()
        assert await asyncio.wait_for(morning.sunrise_ramp(), 0.5) is False
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not morning._sunrise_active
    engine._hue.set_light.side_effect = None
    monkeypatch.setattr("backend.services.morning_routine.asyncio.sleep", AsyncMock())
    assert await morning.sunrise_ramp() is True

async def test_expired_transit_does_not_false_veto(engine, morning):
    engine._state.transit_light_overrides["2"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    assert await morning.sunrise_ramp() is True
    assert engine._hue.set_light.await_count == 16

async def test_scheduler_restart_after_minute_does_not_catch_up(monkeypatch):
    callback = AsyncMock()
    scheduler = AsyncScheduler()
    scheduler.add_task(ScheduledTask(
        name="sunrise_ramp", hour=6, minute=10, weekdays=[0], callback=callback,
    ))

    class FrozenDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 5, 6, 11, tzinfo=tz)

    async def stop_after_one_tick(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(scheduler_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", stop_after_one_tick)
    await scheduler.run_loop()
    callback.assert_not_awaited()


async def test_scheduler_restart_same_minute_respects_persisted_last_run(monkeypatch):
    callback = AsyncMock()
    scheduler = AsyncScheduler()
    scheduler.add_task(ScheduledTask(
        name="sunrise_ramp", hour=6, minute=10, weekdays=[0], callback=callback,
    ))
    last_run = datetime(2026, 10, 5, 6, 10, tzinfo=scheduler_module.TZ)

    async def load_state(_key):
        return {
            "sunrise_ramp": {
                "last_run": last_run.isoformat(),
                "last_status": "ok",
                "last_error": None,
            }
        }

    await scheduler.load_state(load_state)

    class FrozenDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 5, 6, 10, 30, tzinfo=tz)

    async def stop_after_one_tick(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(scheduler_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", stop_after_one_tick)
    await scheduler.run_loop()
    callback.assert_not_awaited()
