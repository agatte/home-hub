"""Explicit Hue-app ownership, using disposable fakes and no app lifespan."""
import asyncio
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api.routes.lights import router
from backend.config import settings
from backend.services.automation_engine import AutomationEngine


@pytest.fixture
def engine(mock_hue, mock_hue_v2, mock_ws, monkeypatch):
    engine = AutomationEngine(mock_hue, mock_hue_v2, mock_ws)
    engine._current_mode = "working"
    engine._effect_manager._tracker_known = True
    mock_hue._lights["6"]["on"] = False
    monkeypatch.setattr(mock_hue, "breaker_open", False, raising=False)
    monkeypatch.setattr(mock_hue, "set_light", AsyncMock(return_value=True))
    monkeypatch.setattr(mock_hue, "set_all_lights", AsyncMock(return_value=True))
    monkeypatch.setattr(engine, "_persist_override_state", AsyncMock())
    return engine


@pytest.fixture
def client(engine):
    app = FastAPI()
    app.include_router(router)
    app.state.hue = engine._hue
    app.state.automation = engine
    with TestClient(app) as client:
        yield client


def test_off_fixture_claim_release_and_scoped_dedup(client, engine):
    engine.mark_light_manual("1", {"bri": 90})
    engine._last_applied_per_light.update({"1": {"bri": 90}, "6": {"on": False}})
    reply = client.post("/api/lights/6/hue-app-hold")
    assert reply.status_code == 200
    token = reply.json()["stamp"]
    assert token.endswith("+00:00")
    assert reply.json()["expiry_hours"] == 4
    assert "6" in engine.manual_light_overrides
    assert "6" not in engine._state.manual_light_targets
    assert engine._hue._lights["6"]["on"] is False
    assert client.post("/api/lights/6/hue-app-hold").status_code == 409
    assert client.delete("/api/lights/6/hue-app-hold").status_code == 422
    assert client.request("DELETE", "/api/lights/6/hue-app-hold", json={"stamp": token}).status_code == 200
    assert set(engine.manual_light_overrides) == {"1"}
    assert engine._last_applied_per_light == {"1": {"bri": 90}}
    assert engine.current_mode == "working"
    assert client.request("DELETE", "/api/lights/6/hue-app-hold", json={"stamp": token}).status_code == 409
    engine._hue.set_light.assert_not_called()
    engine._hue.set_all_lights.assert_not_called()


@pytest.mark.asyncio
async def test_static_apply_and_external_display_do_not_claim(engine):
    held = await engine.hue_app_hold("6")
    engine._hue._lights["6"].update(on=True, bri=90)  # stream/poll display cache
    result = await engine._apply_state({"6": {"on": False}})
    assert result.skipped == {"6"}
    engine._hue.set_light.assert_not_called()
    await engine.hue_app_hold("6", held["stamp"])
    assert not engine.manual_light_overrides
    assert (await engine._hue.get_light("6"))["bri"] == 90
    assert not engine.manual_light_overrides  # readback never adopts ownership
    result = await engine._apply_state({"6": {"on": False}})
    assert result.successful == {"6"}
    engine._hue.set_light.assert_awaited_once()


@pytest.mark.parametrize("kind", [
    "away", "external_off", "host_return", "sleeping", "disabled", "dnd",
    "manual", "transit", "sync", "external", "scene", "scene_pending",
    "gaming_scene", "effect", "unknown_effect", "unreachable",
])
@pytest.mark.asyncio
async def test_owner_conflicts(engine, monkeypatch, kind):
    if kind in {"away", "external_off", "host_return", "disabled"}:
        field = {"away": "_away_hold", "external_off": "_external_off_detected",
                 "host_return": "_host_return_hold", "disabled": "_enabled"}[kind]
        setattr(engine, field, kind != "disabled")
    elif kind == "sleeping":
        engine._current_mode = "sleeping"
    elif kind == "dnd":
        monkeypatch.setattr(engine, "is_dnd_active", lambda: True)
    elif kind == "manual":
        engine.mark_light_manual("6", {"bri": 20})
    elif kind == "transit":
        engine._transit_light_overrides["6"] = engine._overrides._clock.utc_now() + timedelta(minutes=5)
    elif kind == "sync":
        engine._screen_sync = SimpleNamespace(fresh_owned_light_ids=lambda: {"6"})
    elif kind == "external":
        engine._external_light_owners.append(SimpleNamespace(owned_light_targets=lambda: {"6": {}}))
    elif kind == "scene":
        engine._active_scene_override_key = ("working", "night", "scene", "test")
    elif kind == "scene_pending":
        engine._gaming_scene_transition_pending = True
    elif kind == "gaming_scene":
        engine._gaming_scene_override = {"scene": "test"}
    elif kind == "effect":
        engine._effect_manager._active_name = "prism"
    elif kind == "unknown_effect":
        engine._effect_manager._tracker_known = False
    elif kind == "unreachable":
        engine._hue._lights["6"]["reachable"] = False
    before = dict(engine.manual_light_overrides)
    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6")
    assert exc.value.status_code == 409
    assert engine.manual_light_overrides == before
    engine._persist_override_state.assert_not_called()
    engine._hue.set_light.assert_not_called()


@pytest.mark.parametrize("lid", ["0", "06", "999", "random"])
def test_arbitrary_fixture_rejected(client, engine, lid):
    assert client.post(f"/api/lights/{lid}/hue-app-hold").status_code == 404
    assert client.request("DELETE", f"/api/lights/{lid}/hue-app-hold", json={"stamp": "old"}).status_code == 404
    engine._hue.set_light.assert_not_called()


@pytest.mark.asyncio
async def test_stale_token_preserves_dashboard_owner(engine):
    held = await engine.hue_app_hold("6")
    engine.mark_light_manual("6", {"bri": 40})
    newer = engine.manual_light_overrides["6"]
    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6", held["stamp"])
    assert exc.value.status_code == 409
    assert engine.manual_light_overrides["6"] == newer
    assert engine._state.manual_light_targets["6"]["bri"] == 40


@pytest.mark.asyncio
async def test_expired_token(engine):
    await engine.hue_app_hold("6")
    engine.manual_light_overrides["6"] -= timedelta(hours=5)
    expired = engine.manual_light_overrides["6"].astimezone(timezone.utc).isoformat()
    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6", expired)
    assert exc.value.status_code == 409
    assert "6" in engine.manual_light_overrides


@pytest.mark.parametrize("release", [False, True])
@pytest.mark.asyncio
async def test_persistence_failure_rolls_back(engine, release):
    token = (await engine.hue_app_hold("6"))["stamp"] if release else None
    before = dict(engine.manual_light_overrides)
    engine._persist_override_state.side_effect = [RuntimeError("fake failure"), None]
    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6", token)
    assert exc.value.status_code == 503
    assert engine.manual_light_overrides == before
    engine._hue.set_light.assert_not_called()


@pytest.mark.parametrize("release", [False, True])
@pytest.mark.asyncio
async def test_failed_persist_does_not_remove_newer_owner(engine, release):
    token = (await engine.hue_app_hold("6"))["stamp"] if release else None

    async def fail(**kwargs):
        engine.mark_light_manual("6", {"bri": 33})
        raise RuntimeError("fake failure")

    engine._persist_override_state.side_effect = fail
    with pytest.raises(HTTPException):
        await engine.hue_app_hold("6", token)
    assert engine._state.manual_light_targets["6"]["bri"] == 33


@pytest.mark.asyncio
async def test_claim_waits_for_inflight_boundary_and_revokes_old_lease(engine):
    boundary = engine._transition_boundary
    async with boundary.serialized():
        old = boundary.authority.issue("mode", ["6"])
        claim = asyncio.create_task(engine.hue_app_hold("6"))
        await asyncio.sleep(0)
        assert "6" not in engine.manual_light_overrides
        assert not claim.done()
    await claim
    async with boundary.serialized():
        assert not boundary.authority.valid(old)
    engine._hue.set_light.assert_not_called()


@pytest.mark.parametrize("verb", ["post", "delete"])
def test_auth(client, engine, monkeypatch, verb):
    monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "test-only-key")
    monkeypatch.setattr(settings, "HOME_HUB_SKILL_TOKEN", "test-only-skill")
    response = getattr(client, verb)("/api/lights/6/hue-app-hold",
                                   headers={"X-Tunnel-Origin": "cloudflare"},
                                   params={"stamp": "old"})
    assert response.status_code == 401
    assert not engine.manual_light_overrides


def test_authenticated_external_claim_release(client, monkeypatch):
    monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "test-only-key")
    monkeypatch.setattr(settings, "HOME_HUB_SKILL_TOKEN", "test-only-skill")
    headers = {"X-Tunnel-Origin": "cloudflare", "X-API-Key": "test-only-key",
               "X-Skill-Token": "test-only-skill"}
    held = client.post("/api/lights/6/hue-app-hold", headers=headers)
    assert held.status_code == 200
    assert client.request("DELETE", "/api/lights/6/hue-app-hold", headers=headers,
                          json={"stamp": held.json()["stamp"]}).status_code == 200


@pytest.mark.asyncio
async def test_cancellation_retains_boundary_until_persistence_settles(engine):
    entered, finish = asyncio.Event(), asyncio.Event()

    async def persist(**kwargs):
        entered.set()
        await finish.wait()

    engine._persist_override_state.side_effect = persist
    claim = asyncio.create_task(engine.hue_app_hold("6"))
    await entered.wait()
    claim.cancel()
    await asyncio.sleep(0)
    assert not claim.done()
    assert engine._transition_boundary._lock.locked()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await claim
    assert "6" in engine.manual_light_overrides
    assert not engine._transition_boundary._lock.locked()
    engine._hue.set_light.assert_not_called()


@pytest.mark.asyncio
async def test_failed_release_does_not_resurrect_mode_cleared_stamp(engine):
    held = await engine.hue_app_hold("6")

    async def fail(**kwargs):
        engine._clear_per_light_overrides()
        engine._current_mode = "relax"
        raise RuntimeError("fake failure")

    engine._persist_override_state.side_effect = fail
    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6", held["stamp"])
    assert exc.value.status_code == 503
    assert not engine.manual_light_overrides


@pytest.mark.asyncio
async def test_strict_persistence_path_uses_real_snapshot(engine, monkeypatch):
    from backend.api.routes import routines

    saved = []

    async def save(key, payload):
        saved.append(payload)

    monkeypatch.setattr(routines, "save_setting", save)
    monkeypatch.setattr(engine, "_persist_override_state",
                        AutomationEngine._persist_override_state.__get__(engine))
    held = await engine.hue_app_hold("6")
    assert saved[-1]["manual_light_stamps_utc"] == {"6": held["stamp"]}
    await engine.hue_app_hold("6", held["stamp"])
    assert saved[-1]["manual_light_stamps_utc"] == {}

    async def fail(key, payload):
        if "6" in payload["manual_light_stamps_utc"]:
            raise RuntimeError("fake failure")

    monkeypatch.setattr(routines, "save_setting", fail)
    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6")
    assert exc.value.status_code == 503
    assert not engine.manual_light_overrides


@pytest.mark.asyncio
async def test_settle_then_recheck_manual_owner(engine, monkeypatch):
    async def settle(ids):
        assert ids == ["6"]
        engine.mark_light_manual("6", {"bri": 50})

    monkeypatch.setattr(engine._hue, "wait_for_transition_settle", settle, raising=False)
    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6")
    assert exc.value.status_code == 409
    assert engine._state.manual_light_targets["6"]["bri"] == 50
    engine._persist_override_state.assert_not_called()


@pytest.mark.parametrize("new_owner", ["manual", "scene", "dnd"])
@pytest.mark.asyncio
async def test_owner_change_during_successful_persist(engine, monkeypatch, new_owner):
    async def persist(**kwargs):
        if engine._persist_override_state.await_count > 1:
            return
        if new_owner == "manual":
            engine.mark_light_manual("6", {"bri": 33})
        elif new_owner == "scene":
            engine._active_scene_override_key = ("working", "night", "scene", "test")
        else:
            monkeypatch.setattr(engine, "is_dnd_active", lambda: True)

    engine._persist_override_state.side_effect = persist
    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6")
    assert exc.value.status_code == 409
    if new_owner == "manual":
        assert engine._state.manual_light_targets["6"]["bri"] == 33
    else:
        assert not engine.manual_light_overrides
    assert engine._persist_override_state.await_count == 2
    engine._hue.set_light.assert_not_called()


@pytest.mark.asyncio
async def test_existing_mode_clear_and_expiry_semantics(engine):
    await engine.hue_app_hold("6")
    engine._clear_per_light_overrides()
    assert not engine.manual_light_overrides
    await engine.hue_app_hold("6")
    assert engine._overrides.expire_manual_stamps(
        engine._overrides._clock.utc_now() + timedelta(hours=5), 4,
    )
    assert not engine.manual_light_overrides
    engine._hue.set_light.assert_not_called()


@pytest.mark.parametrize("release", [False, True])
@pytest.mark.parametrize("compensation_fails", [False, True])
@pytest.mark.parametrize("superseded", [False, True])
@pytest.mark.asyncio
async def test_commit_then_raise_compensates_current_state(
    engine, monkeypatch, release, compensation_fails, superseded,
):
    from backend.api.routes import routines

    token = (await engine.hue_app_hold("6"))["stamp"] if release else None
    engine.mark_light_manual("1", {"bri": 70})
    before = dict(engine.manual_light_overrides)
    stored = {}
    calls = 0

    async def save(key, payload):
        nonlocal calls
        calls += 1
        if calls == 2 and compensation_fails:
            raise RuntimeError("compensation unavailable")
        stored.clear()
        stored.update(payload)
        if calls == 1:
            if superseded:
                engine.mark_light_manual("6", {"bri": 33})
                engine._override_source = "newer-source"
            raise RuntimeError("committed before failure")

    monkeypatch.setattr(routines, "save_setting", save)
    monkeypatch.setattr(engine, "_persist_override_state",
                        AutomationEngine._persist_override_state.__get__(engine))
    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6", token)
    assert exc.value.status_code == 503
    assert calls == 2
    assert engine.manual_light_overrides["1"] == before["1"]
    assert engine.current_mode == "working"
    if superseded:
        assert engine._state.manual_light_targets["6"]["bri"] == 33
        assert engine._override_source == "newer-source"
    if compensation_fails:
        assert "durability uncertain" in exc.value.detail["error"]
        assert exc.value.detail["stamp"] == engine.manual_light_overrides["6"].astimezone(timezone.utc).isoformat()
        assert "recovery" in exc.value.detail
    else:
        assert stored["manual_light_stamps_utc"] == {
            lid: stamp.astimezone(timezone.utc).isoformat()
            for lid, stamp in engine.manual_light_overrides.items()
        }
        if superseded:
            assert stored["override_source"] == "newer-source"
        else:
            assert engine.manual_light_overrides == before
    engine._hue.set_light.assert_not_called()


@pytest.mark.parametrize("effect", [None, "prism"])
@pytest.mark.asyncio
async def test_targetless_hold_blocks_effect_release(engine, effect):
    engine.mark_light_manual("6")
    manager = engine._effect_manager
    manager._active_name = "glisten"
    manager._tracker_known = True
    manager._hue_v2.mapped_light_ids = ["6"]
    manager._hue_v2.stop_effect_all = AsyncMock(return_value=True)
    manager._hue_v2.set_effect_all = AsyncMock(return_value=True)

    async def establish(required):
        result = await engine._applicator.establish_effect_release(
            {"6": {"on": False}}, 0, required,
        )
        assert result.skipped == {"6"}
        return result

    assert await manager.reconcile(effect, establish_safety=establish) is False
    engine._hue.set_light.assert_not_called()
    manager._hue_v2.stop_effect_all.assert_not_called()
    manager._hue_v2.set_effect_all.assert_not_called()


@pytest.mark.asyncio
async def test_failed_compensation_preserves_newer_clear(engine, monkeypatch):
    from backend.api.routes import routines

    calls = 0

    async def save(key, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            engine._clear_per_light_overrides()
            engine._mode_transition_revision += 1
            engine._override_source = "newer-mode"
        raise RuntimeError("store unavailable after possible commit")

    monkeypatch.setattr(routines, "save_setting", save)
    monkeypatch.setattr(engine, "_persist_override_state",
                        AutomationEngine._persist_override_state.__get__(engine))
    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6")
    assert calls == 2
    assert exc.value.status_code == 503
    assert exc.value.detail["stamp"] is not None
    assert exc.value.detail["active_in_memory"] is False
    assert not engine.manual_light_overrides
    assert engine._override_source == "newer-mode"


@pytest.mark.parametrize("conflict", ["scene", "dnd"])
@pytest.mark.asyncio
async def test_commit_then_conflict_cleanup_failure_returns_possible_durable_stamp(
    engine, monkeypatch, conflict,
):
    """A failed cleanup must not hide a Hold that may return on restart."""
    from copy import deepcopy
    from backend.api.routes import routines

    stored = {}
    saves = 0

    async def save(key, payload):
        nonlocal saves
        saves += 1
        if saves == 1:
            stored[key] = deepcopy(payload)
            if conflict == "scene":
                engine._active_scene_override_key = (
                    "working", "night", "scene", "external",
                )
            else:
                monkeypatch.setattr(engine, "is_dnd_active", lambda: True)
        else:
            raise RuntimeError("cleanup save unavailable")

    async def load(key):
        return deepcopy(stored.get(key, {}))

    monkeypatch.setattr(routines, "save_setting", save)
    monkeypatch.setattr(routines, "load_setting", load)
    monkeypatch.setattr(
        engine, "_persist_override_state",
        AutomationEngine._persist_override_state.__get__(engine),
    )

    with pytest.raises(HTTPException) as exc:
        await engine.hue_app_hold("6")

    assert saves == 2
    assert exc.value.status_code == 503
    assert "durability uncertain" in exc.value.detail["error"]
    assert exc.value.detail["active_in_memory"] is False
    assert not engine.manual_light_overrides
    from backend.api.routes.automation import OVERRIDE_STATE_KEY
    persisted_stamp = stored[OVERRIDE_STATE_KEY]["manual_light_stamps_utc"]["6"]
    assert exc.value.detail["stamp"] == persisted_stamp

    restored = AutomationEngine(engine._hue, engine._hue_v2, engine._ws_manager)
    await restored.load_override_state()
    assert restored.manual_light_overrides["6"].astimezone(
        timezone.utc,
    ).isoformat() == persisted_stamp
    engine._hue.set_light.assert_not_called()
