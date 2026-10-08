"""Restart durability contracts; settings and Hue are entirely disposable mocks."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.automation_engine import AutomationEngine


@pytest.fixture
def store(monkeypatch):
    data = {}

    async def save(key, value):
        data[key] = copy.deepcopy(value)

    async def load(key):
        return copy.deepcopy(data.get(key, {}))

    monkeypatch.setattr("backend.api.routes.routines.save_setting", save)
    monkeypatch.setattr("backend.api.routes.routines.load_setting", load)
    return data


def engine():
    hue = MagicMock()
    hue.connected = True
    hue.set_light = AsyncMock(return_value=True)
    hue.set_all_lights = AsyncMock(return_value=True)
    return AutomationEngine(hue, MagicMock(), MagicMock())


def saved(store):
    from backend.api.routes.automation import OVERRIDE_STATE_KEY
    return store[OVERRIDE_STATE_KEY]


@pytest.mark.asyncio
async def test_restart_protects_without_targets_or_device_write(store):
    first = engine()
    first.mark_light_manual("1", {"bri": 42, "on": True})
    await first.persist_manual_light_ownership()
    assert saved(store)["manual_light_stamps_utc"].keys() == {"1"}
    assert "manual_light_targets" not in saved(store)
    restored = engine()
    await restored.load_override_state()
    assert restored.manual_light_overrides == first.manual_light_overrides
    assert restored._state.manual_light_targets == {}
    assert "1" in restored._applicator.protected_light_ids()
    restored._hue.set_light.assert_not_called()
    restored._hue.set_all_lights.assert_not_called()
    await restored._applicator.apply_state({"1": {"on": True, "bri": 200}})
    restored._hue.set_light.assert_not_called()
    restored._hue.set_all_lights.assert_not_called()
    restored._clear_per_light_overrides()
    await restored.persist_manual_light_ownership()
    assert saved(store)["manual_light_stamps_utc"] == {}
    third = engine()
    await third.load_override_state()
    assert third.manual_light_overrides == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [[], None, "bad", {"1": "bad"},
    {"1": 23}, {"1": "2026-10-01T12:00:00"}, {"invalid": "bad"},
    {"999": datetime.now(timezone.utc).isoformat()},
    {"1": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()},
    {"1": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}])
async def test_rejects_invalid_or_expired_metadata(store, value):
    from backend.api.routes.automation import OVERRIDE_STATE_KEY
    store[OVERRIDE_STATE_KEY] = {"manual_light_stamps_utc": value}
    e = engine()
    await e.load_override_state()
    assert e.manual_light_overrides == {}
    assert saved(store)["manual_light_stamps_utc"] == value
    e._hue.set_light.assert_not_called()
    e._hue.set_all_lights.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("release", ["clear", "expiry"])
async def test_delayed_commit_cannot_resurrect_release(store, monkeypatch, release):
    from backend.api.routes import routines
    original = routines.save_setting
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = 0

    async def delayed(key, value):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await finish.wait()
        await original(key, value)

    monkeypatch.setattr(routines, "save_setting", delayed)
    e = engine()
    e.mark_light_manual("1")
    marking = asyncio.create_task(e.persist_manual_light_ownership())
    await asyncio.wait_for(entered.wait(), timeout=2)
    if release == "clear":
        e._clear_per_light_overrides()
    else:
        assert e._overrides.expire_manual_stamps(
            datetime.now(timezone.utc) + timedelta(hours=5), 4)
    releasing = asyncio.create_task(e.persist_manual_light_ownership())
    await asyncio.sleep(0)
    assert calls == 1  # The clear/expiry save is waiting behind the first commit.
    finish.set()
    await asyncio.wait_for(asyncio.gather(marking, releasing), timeout=2)
    assert saved(store)["manual_light_stamps_utc"] == {}
    fresh = engine()
    await fresh.load_override_state()
    assert fresh.manual_light_overrides == {}


@pytest.mark.asyncio
async def test_queued_callers_snapshot_current_state(store):
    e = engine()
    # Explicit async owners may queue, but synchronous marking never saves.
    e.mark_light_manual("1")
    first = asyncio.create_task(e.persist_manual_light_ownership())
    e.mark_light_manual("2")
    second = asyncio.create_task(e.persist_manual_light_ownership())
    e._clear_per_light_overrides()
    await asyncio.gather(first, second, e.persist_manual_light_ownership())
    assert saved(store)["manual_light_stamps_utc"] == {}


@pytest.mark.asyncio
async def test_invalid_metadata_preserves_shared_state_on_load(store, monkeypatch):
    from backend.api.routes.automation import OVERRIDE_STATE_KEY
    stamp = datetime.now(timezone.utc) - timedelta(minutes=10)
    payload = {
        "manual_light_stamps_utc": {
            "1": "malformed",
            "2": (stamp - timedelta(hours=5)).isoformat(),
            "3": stamp.isoformat(),
            "999": stamp.isoformat(),
        },
        "manual_override": True,
        "override_mode": "relax",
        "override_source": "api:test",
        "override_time_utc": stamp.isoformat(),
        "home_awake_confirmed": True,
        "zone_posture_last_fired_utc": stamp.isoformat(),
        "watching_sleep_guard_last_fired_utc": stamp.isoformat(),
        "user_cleared_override_at_utc": stamp.isoformat(),
        "user_clear_allows_physical_context_relax": True,
        "last_bed_reclined_during_watching_utc": stamp.isoformat(),
    }
    store[OVERRIDE_STATE_KEY] = copy.deepcopy(payload)
    e = engine()
    persist = AsyncMock(wraps=e._persist_override_state)
    monkeypatch.setattr(e, "_persist_override_state", persist)
    await e.load_override_state()
    persist.assert_not_awaited()
    assert saved(store) == payload
    assert e._manual_override is True
    assert e._override_mode == "relax"
    assert e._override_source == "api:test"
    assert e._override_time == stamp
    assert e._home_awake_confirmed is True
    assert e._zone_posture_last_fired_at == stamp
    assert e._watching_sleep_guard_last_fired_at == stamp
    assert e._user_cleared_override_at == stamp
    assert e._user_clear_allows_physical_context_relax is True
    assert e._last_bed_reclined_during_watching_at == stamp
    assert e.manual_light_overrides == {"3": stamp}
    e._hue.set_light.assert_not_called()
    e._hue.set_all_lights.assert_not_called()
    await e.persist_manual_light_ownership()
    expected = copy.deepcopy(payload)
    expected["manual_light_stamps_utc"] = {"3": stamp.isoformat()}
    assert saved(store) == expected


@pytest.mark.asyncio
async def test_synchronous_marks_do_not_schedule_saves(store, monkeypatch):
    e = engine()
    persist = AsyncMock()
    monkeypatch.setattr(e, "_persist_override_state", persist)
    e.mark_light_manual("1")
    e._clear_per_light_overrides()
    e.mark_light_manual("2")
    assert e._overrides.expire_manual_stamps(
        datetime.now(timezone.utc) + timedelta(hours=5), 4)
    assert not e._overrides.expire_manual_stamps(datetime.now(timezone.utc), 4)
    await asyncio.sleep(0)
    persist.assert_not_called()
    assert store == {}


@pytest.mark.asyncio
async def test_expiry_survives_restart(store):
    e = engine()
    e.mark_light_manual("1")
    await e.persist_manual_light_ownership()
    restored = engine()
    await restored.load_override_state()
    assert restored._overrides.expire_manual_stamps(
        datetime.now(timezone.utc) + timedelta(hours=5), 4)
    await restored._persist_override_state()  # Same awaited path as run_loop.
    fresh = engine()
    await fresh.load_override_state()
    assert fresh.manual_light_overrides == {}


@pytest.mark.asyncio
async def test_auto_clear_after_restore_awaits_one_shared_save(store, monkeypatch):
    first = engine()
    first.mark_light_manual("1")
    await first.persist_manual_light_ownership()
    restored = engine()
    await restored.load_override_state()
    # Existing hard Away semantics still prevent any reconciliation writes.
    restored._away_hold = True
    monkeypatch.setattr(restored, "_broadcast_mode", AsyncMock())
    persist = AsyncMock(wraps=restored._persist_override_state)
    monkeypatch.setattr(restored, "_persist_override_state", persist)
    await restored.clear_override(source="api:test", user_requested_auto=True)
    persist.assert_awaited_once()
    assert saved(store)["manual_light_stamps_utc"] == {}
    restored._hue.set_light.assert_not_called()
    restored._hue.set_all_lights.assert_not_called()
    fresh = engine()
    await fresh.load_override_state()
    assert fresh.manual_light_overrides == {}


@pytest.mark.asyncio
async def test_manual_persistence_failure_is_awaited_and_logged(store, monkeypatch, caplog):
    completed = False

    async def failing_save(key, value):
        nonlocal completed
        await asyncio.sleep(0)
        completed = True
        raise RuntimeError("disposable store failure")

    monkeypatch.setattr("backend.api.routes.routines.save_setting", failing_save)
    e = engine()
    e.mark_light_manual("1")
    create_task = MagicMock(side_effect=AssertionError("background persistence task"))
    monkeypatch.setattr(asyncio, "create_task", create_task)
    await e.persist_manual_light_ownership()
    assert completed
    assert "Failed to persist override state" in caplog.text
    assert "disposable store failure" in caplog.text
    create_task.assert_not_called()
    assert "1" in e.manual_light_overrides


def test_production_manual_marks_have_awaited_persistence_boundary():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    call_sites = 0
    for path in (root / "backend").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        marks = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "mark_light_manual"]
        covered = set()
        for owner in ast.walk(tree):
            if not isinstance(owner, ast.AsyncFunctionDef):
                continue
            nodes = list(ast.walk(owner))
            boundaries = [node for node in nodes if isinstance(node, ast.Await)
                          and isinstance(node.value, ast.Call)
                          and isinstance(node.value.func, ast.Attribute)
                          and node.value.func.attr == "persist_manual_light_ownership"]
            # A synchronous scene helper may mark within its async batch owner.
            for mark in marks:
                if mark in nodes and any(
                    boundary.lineno > mark.lineno
                    and ast.dump(boundary.value.func.value) == ast.dump(mark.func.value)
                    for boundary in boundaries
                ):
                    covered.add(mark)
        assert covered == set(marks), (path, [mark.lineno for mark in marks if mark not in covered])
        call_sites += len(marks)
    assert call_sites > 0
