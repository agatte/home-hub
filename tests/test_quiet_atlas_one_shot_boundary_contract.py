"""#461: existing primitives only; NOT a native Quiet Atlas one-shot endpoint.

All bridge operations below are fakes. A future route still needs approved
takeover policy, server preflight, idempotency and authoritative readback.
Fake transport success does not establish physical confirmation (#370).
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.api.routes import lights
from backend.api.schemas.lights import LightState
from backend.services.automation_engine import AutomationEngine
from backend.services.lighting_transition_boundary import LightingTransitionBoundary
from backend.services.screen_sync import ScreenSyncService, SCREEN_SYNC_FRESH_SECONDS


@pytest.fixture
def rig(mock_hue, mock_hue_v2, mock_ws, monkeypatch):
    """Real engine, fixture-only bridge, no lifespan or persistence connection."""
    engine = AutomationEngine(mock_hue, mock_hue_v2, mock_ws)
    engine._current_mode = "working"
    engine._effect_manager._tracker_known = True
    engine._last_applied_per_light = {"2": {"on": True, "bri": 80}}
    monkeypatch.setattr(mock_hue, "breaker_open", False, raising=False)
    write = AsyncMock(wraps=mock_hue.set_light)
    monkeypatch.setattr(mock_hue, "set_light", write)
    monkeypatch.setattr(engine, "persist_manual_light_ownership", AsyncMock())
    sync = ScreenSyncService(mock_hue, ["1", "2", "3", "4", "5"],
                             engine.lighting_transition_boundary)
    engine._screen_sync = sync
    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr("backend.services.screen_sync.datetime", Clock)
    return engine, sync, mock_hue, write, now


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,valid", [(["3"], True), (["2"], False), (None, False)])
async def test_existing_scoped_intent_revocation(rig, scope, valid):
    engine, _, _, _, _ = rig
    boundary = engine.lighting_transition_boundary
    single = boundary.authority.issue("probe", ["2"])
    whole = boundary.authority.issue("probe", None)
    queued = asyncio.Event()

    async def check_after_wait():
        queued.set()
        async with boundary.serialized():
            assert engine.validate_lighting_lease(single) is valid
            assert not engine.validate_lighting_lease(whole)
            assert engine.validate_lighting_lease(boundary.authority.issue("probe", ["2"]))

    async with boundary.serialized():
        assert engine.validate_lighting_lease(single)
        assert engine.validate_lighting_lease(whole)
        task = asyncio.create_task(check_after_wait())
        await queued.wait()
        assert not task.done()
        boundary.authority.invalidate(scope)
    await task


@pytest.mark.asyncio
async def test_existing_delegated_validator_rejects_intent_changed_while_queued(rig):
    engine, _, hue, write, _ = rig
    boundary = engine.lighting_transition_boundary
    lease = boundary.authority.issue("probe", ["2"])
    before = deepcopy(engine._last_applied_per_light)
    targets = deepcopy(engine._state.manual_light_targets)
    queued = asyncio.Event()
    validations = []

    def validate():
        validations.append(boundary.held_by_current_task)
        return engine.validate_lighting_lease(lease)

    async def candidate():
        queued.set()
        async with boundary.serialized():
            accepted = await boundary.run_write(
                lambda: hue.set_light("2", {"bri": 100}), validator=validate,
                light_ids=["2"],
            )
            if accepted:
                engine.mark_light_manual("2", {"bri": 100})
                engine.record_leased_light_write("2", {"bri": 100})
            return accepted

    # Child task cannot inherit the parent's boundary ownership.
    async with boundary.serialized():
        assert engine.validate_lighting_lease(lease)
        task = asyncio.create_task(candidate())
        await queued.wait()
        assert not task.done()
        boundary.authority.invalidate(["2"])
    assert await task is False
    assert validations == [True]
    write.assert_not_awaited()
    assert engine.manual_light_overrides == {}
    assert engine._state.manual_light_targets == targets
    assert engine._last_applied_per_light == before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["other_process", "closed", "intent_only"])
async def test_existing_engine_rejects_non_write_leases(rig, kind):
    engine, _, hue, write, _ = rig
    boundary = engine.lighting_transition_boundary
    lease = boundary.authority.issue("probe", ["2"], intent_only=kind == "intent_only")
    async with boundary.serialized():
        if kind == "intent_only":
            assert boundary.authority.valid(lease)  # Fresh setup is still no permission.
        else:
            assert engine.validate_lighting_lease(lease)
        if kind == "closed":
            boundary.authority.close()
        elif kind == "other_process":
            lease = LightingTransitionBoundary(hue).authority.issue("probe", ["2"])
        assert not engine.validate_lighting_lease(lease)
        assert await boundary.run_write(
            lambda: hue.set_light("2", {"bri": 100}),
            validator=lambda: engine.validate_lighting_lease(lease),
        ) is False
    write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [
    "manual", "transit", "screen_sync", "scene", "effect", "unknown_effect",
    "external", "legacy_external", "away", "external_off", "host_return",
    "sleeping", "disabled", "pending_scene",
])
async def test_existing_owner_policy_rejects_even_current_lease(rig, owner):
    engine, sync, hue, write, now = rig
    boundary = engine.lighting_transition_boundary
    async with boundary.serialized():
        assert engine.validate_lighting_lease(boundary.authority.issue("probe", ["2"]))
    if owner == "manual":
        engine.mark_light_manual("2", {"bri": 60})
    elif owner == "transit":
        engine._transit_light_overrides["2"] = now + timedelta(minutes=10)
    elif owner == "screen_sync":
        assert sync._record_source_write("desktop", "2")
        assert sync.fresh_owned_light_ids() == {"2"}
    elif owner == "scene":
        engine._active_scene_override_key = ("working", "day", "fixture", "test")
    elif owner == "effect":
        engine._effect_manager._active_name = "candle"
        engine._effect_manager._active_lights = ["2"]
    elif owner == "unknown_effect":
        engine._effect_manager._tracker_known = False
    elif owner in {"external", "legacy_external"}:
        external = SimpleNamespace(owned_light_targets=lambda: {"2": {"bri": 60}})
        if owner == "external":
            external.set_lighting_authority_notifier = lambda notifier: None
        engine.register_external_light_owner(external)
    elif owner == "sleeping":
        engine._manual_override = True
        engine._override_mode = "sleeping"
    else:
        field = {"away": "_away_hold", "external_off": "_external_off_detected",
                 "host_return": "_host_return_hold", "disabled": "_enabled",
                 "pending_scene": "_gaming_scene_transition_pending"}[owner]
        setattr(engine, field, owner != "disabled")
    # Issue AFTER acquisition: this tests policy, not just generation mismatch.
    lease = boundary.authority.issue("probe", ["2"])
    async with boundary.serialized():
        assert boundary.authority.valid(lease)
        assert not engine.validate_lighting_lease(lease)
        assert await boundary.run_write(
            lambda: hue.set_light("2", {"bri": 100}),
            validator=lambda: engine.validate_lighting_lease(lease),
        ) is False
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_screen_source_expiry_releases_without_permanent_lockout(rig):
    engine, sync, _, write, now = rig
    boundary = engine.lighting_transition_boundary
    assert sync._record_source_write("desktop", "2")
    assert sync._record_source_write("laptop", "3")
    assert sync._last_frame_kind_by_light["2"][0] == "desktop"
    assert sync._last_frame_kind_by_light["3"][0] == "laptop"
    sync._last_color_at_by_light["2"] = now - timedelta(seconds=SCREEN_SYNC_FRESH_SECONDS)
    old = boundary.authority.issue("probe", ["2"])
    assert sync.fresh_owned_light_ids() == {"3"}  # Laptop frame cannot renew L2.
    async with boundary.serialized():
        assert not engine.validate_lighting_lease(old)
        assert engine.validate_lighting_lease(boundary.authority.issue("probe", ["2"]))
        assert not engine.validate_lighting_lease(boundary.authority.issue("probe", ["3"]))
    write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_result", [False, True])
async def test_existing_repeated_cancellation_fences_pending_fake_io(rig, transport_result):
    engine, _, hue, write, _ = rig
    boundary = engine.lighting_transition_boundary
    started, release, queued, entered = (asyncio.Event() for _ in range(4))
    settled, confirmed = [], []

    async def pending_io():
        started.set()
        await release.wait()
        await hue.set_light("2", {"bri": 100})
        settled.append(True)
        return transport_result

    async def caller():
        async with boundary.serialized():
            result = await boundary.run_write(pending_io, light_ids=["2"])
            confirmed.append(result)  # Cancellation must never reach acknowledgement.

    async def next_action():
        queued.set()
        async with boundary.serialized():
            assert settled == [True]
            entered.set()

    task = asyncio.create_task(caller())
    other = None
    try:
        # Fail deterministically if a future boundary regression stops progress.
        # Keep both awaits inside cleanup so neither path strands an async task.
        await asyncio.wait_for(started.wait(), timeout=10)
        other = asyncio.create_task(next_action())
        await asyncio.wait_for(queued.wait(), timeout=10)
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(0)  # Deliver cancellation, no timing assumption.
            assert not task.done()
            assert not entered.is_set()
            assert boundary._lock.locked()
        write.assert_not_awaited()
    finally:
        release.set()
        outstanding = [pending for pending in (task, other) if pending is not None]
        try:
            await asyncio.wait_for(
                asyncio.gather(*outstanding, return_exceptions=True),
                timeout=10,
            )
        finally:
            for pending in outstanding:
                if not pending.done():
                    pending.cancel()
    assert task.cancelled()
    assert other.exception() is None
    assert entered.is_set() and settled == [True]
    assert confirmed == []
    write.assert_awaited_once_with("2", {"bri": 100})
    assert engine.manual_light_overrides == {}


@pytest.mark.asyncio
async def test_existing_manual_put_restamps_after_explicit_clear_in_fake_modes(rig):
    """REST manual writes require a coherent Hue/engine boundary.

    In real lifespan HueService binds this shared boundary; a detached fake
    must fail closed instead of silently using the legacy write-then-stamp
    behavior. Explicitly test bound fake writes and Sleeping/disabled denial.
    """
    engine, _, hue, write, _ = rig
    request = SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace(
        hue=hue, automation=engine,
    )))
    # A detached fake cannot simulate a production-eligible Hue writer.
    with pytest.raises(HTTPException) as error:
        await lights.set_light("2", LightState(bri=50), request)
    assert error.value.status_code == 503
    write.assert_not_awaited()

    # Supply the same coherent boundary and source-qualified fixture identity
    # as the actual HueService, with no bridge or physical I/O.
    hue._transition_boundary = engine.lighting_transition_boundary
    original_read = hue.get_light

    async def qualified_read(light_id):
        record = await original_read(light_id)
        return {"light_id": str(light_id), **record} if record else None

    hue.get_light = qualified_read
    expected_writes = 0
    for mode, enabled, bri, should_write in [
        ("working", True, 60, True),
        ("watching", True, 70, True),
        ("sleeping", False, 80, False),
        ("working", True, 90, True),
    ]:
        engine._clear_per_light_overrides()
        engine._current_mode = mode
        engine.enabled = enabled
        assert engine.manual_light_overrides == {}
        if should_write:
            assert await lights.set_light("2", LightState(bri=bri), request) == {
                "status": "ok", "light_id": "2",
            }
            expected_writes += 1
            assert (await hue.get_light("2"))["bri"] == bri
            assert "2" in engine.manual_light_overrides
            assert engine._state.manual_light_targets["2"]["bri"] == bri
            # An acknowledged manual writer evicts the prior automation dedup
            # value so mode reconciliation after manual expiry cannot skip.
            assert "2" not in engine._last_applied_per_light
        else:
            with pytest.raises(HTTPException) as denied:
                await lights.set_light("2", LightState(bri=bri), request)
            assert denied.value.status_code == 409
            assert engine.manual_light_overrides == {}
        assert write.await_count == expected_writes

    assert write.await_count == 3
    assert engine.persist_manual_light_ownership.await_count == 3
    engine._clear_per_light_overrides()
    async with engine.lighting_transition_boundary.serialized():
        assert engine.validate_lighting_lease(
            engine.lighting_transition_boundary.authority.issue("probe", ["2"]),
        )
