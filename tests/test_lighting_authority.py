"""Pure/service authority races; fake Hue only, no application configuration."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.lighting_authority import LightingSemanticField
from backend.services.lighting_transition_boundary import LightingTransitionBoundary
from backend.services.screen_sync import ScreenSyncService
from backend.services.rust_event_service import RustEventService
from backend.services.effect_manager import EffectManager
from backend.services.engine_state import EngineState
from backend.services.light_override_manager import LightOverrideManager
from backend.services.light_applicator import LightApplicator
from backend.services.hue_service import HueService


@asynccontextmanager
async def independent_blocker(boundary):
    """Queue producers from a task that never inherits the lock owner's context."""
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


class Hue:
    connected = True

    def __init__(self):
        self.calls = []
        self.success = True

    async def set_light(self, lid, state):
        self.calls.append((lid, state.copy()))
        return self.success


class Engine:
    mode = LightingSemanticField()

    def __init__(self, hue):
        self._transition_boundary = LightingTransitionBoundary(hue)
        self.mode = "gaming"
        self.current_game = "rust"
        self.manual_light_overrides = set()
        self.blocked = set()
        self.cached = {}

    @property
    def lighting_transition_boundary(self):
        return self._transition_boundary

    def validate_lighting_lease(self, lease, **kwargs):
        return (self._transition_boundary.authority.valid(lease)
                and self.mode == kwargs.get("expected_mode", self.mode)
                and not ({lid for lid, _ in lease.light_generations} & (self.blocked | self.manual_light_overrides)))

    def forget_ambiguous_light_write(self, light_ids, **kwargs):
        for lid in light_ids:
            self.cached.pop(lid, None)

    def record_leased_light_write(self, lid, state, **kwargs):
        self._transition_boundary.authority.invalidate([lid])
        self.cached.pop(lid, None)


@pytest.mark.asyncio
async def test_generation_scope_aba_and_restart():
    boundary = LightingTransitionBoundary(Hue())
    authority = boundary.authority
    lease = authority.issue("test", ["2"])
    whole = authority.issue("native", None)
    authority.invalidate(["3"])
    async with boundary.serialized():
        assert authority.valid(lease)
        assert not authority.valid(whole)
    engine = Engine(Hue())
    lease = engine.lighting_transition_boundary.authority.issue("test", ["2"])
    engine.mode = "watching"
    engine.mode = "gaming"
    async with engine.lighting_transition_boundary.serialized():
        assert not engine.lighting_transition_boundary.authority.valid(lease)
    replacement = LightingTransitionBoundary(Hue())
    async with replacement.serialized():
        assert not replacement.authority.valid(lease)
    with pytest.raises(RuntimeError):
        authority.valid(lease)


@pytest.mark.asyncio
async def test_child_task_does_not_inherit_boundary_authority():
    boundary = LightingTransitionBoundary(Hue())
    entered = asyncio.Event()

    async def child():
        assert not boundary.held_by_current_task
        async with boundary.serialized():
            entered.set()

    async with boundary.serialized():
        task = asyncio.create_task(child())
        assert not entered.is_set()
    await task
    assert entered.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["color", "daylight", "gaming", "rust"])
@pytest.mark.parametrize("takeover", ["global", "light", "guard"])
async def test_screen_frame_stale_after_boundary_wait(monkeypatch, path, takeover):
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    sync = ScreenSyncService(hue, ["2"], boundary)
    sync.set_event_logger(SimpleNamespace(log_light_adjustment=AsyncMock()))
    if path == "gaming":
        sync.publish_accepted_gaming_state({"2": {"on": True, "bri": 100, "ct": 350}})
    issued = asyncio.Event()
    original_issue = boundary.authority.issue

    def issue(*args):
        lease = original_issue(*args)
        issued.set()
        return lease

    monkeypatch.setattr(boundary.authority, "issue", issue)
    allowed = True
    calls = {
        "color": lambda: sync.apply_color("2", 255, 0, 0, "watching", final_guard=lambda: allowed),
        "daylight": lambda: sync.apply_watching_daylight("2", final_guard=lambda: allowed),
        "gaming": lambda: sync.apply_color("2", 255, 0, 0, "gaming", final_guard=lambda: allowed),
        "rust": lambda: sync.apply_rust_brightness("2", 100, final_guard=lambda: allowed),
    }
    async with independent_blocker(boundary):
        task = asyncio.create_task(calls[path]())
        await issued.wait()
        if takeover == "guard":
            allowed = False
        else:
            boundary.authority.invalidate(None if takeover == "global" else ["2"])
    assert await task is False
    assert hue.calls == []
    assert sync._last_sent_state == {}
    assert sync._last_daylight_state == {}
    assert sync.last_color_at is None
    assert sync._last_color_at_by_light == {}
    assert sync._hold_refreshed_at == {}
    sync._event_logger.log_light_adjustment.assert_not_awaited()


@pytest.mark.asyncio
async def test_screen_final_check_and_failed_write_do_not_publish(monkeypatch):
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    sync = ScreenSyncService(hue, ["2"], boundary)
    smooth = sync._smooth

    def intervene(*args, **kwargs):
        result = smooth(*args, **kwargs)
        boundary.authority.invalidate(["2"])
        return result

    monkeypatch.setattr(sync, "_smooth", intervene)
    assert await sync.apply_color("2", 255, 0, 0, "watching") is False
    assert not hue.calls and sync.last_color_at is None
    monkeypatch.setattr(sync, "_smooth", smooth)
    lease = boundary.authority.issue("probe", ["2"])
    hue.success = False
    assert await sync.apply_color("2", 255, 0, 0, "watching") is False
    async with boundary.serialized():
        assert boundary.authority.valid(lease)
    assert sync.last_color_at is None
    hue.success = True
    assert await sync.apply_color("2", 255, 0, 0, "watching") is True
    assert sync.last_color_at is not None and "2" in sync._last_sent_state


@pytest.mark.asyncio
@pytest.mark.parametrize("takeover", ["manual", "transit", "screen_sync", "external", "mode", "away"])
async def test_rust_restore_suppressed_during_hold(monkeypatch, takeover):
    hue = Hue()
    engine = Engine(hue)
    sync = SimpleNamespace(last_applied_bri=lambda lid: 120)
    rust = RustEventService(hue, sync, engine)
    holding, resume = asyncio.Event(), asyncio.Event()

    async def hold(delay):
        holding.set()
        await resume.wait()

    monkeypatch.setattr("backend.services.rust_event_service.asyncio.sleep", hold)
    task = asyncio.create_task(rust._do_flinch())
    await holding.wait()
    assert len(hue.calls) == 2
    if takeover == "mode":
        engine.mode = "watching"
    else:
        engine.lighting_transition_boundary.authority.invalidate(None if takeover == "away" else ["2", "5"])
    resume.set()
    await task
    assert len(hue.calls) == 2
    assert not rust._flinching


@pytest.mark.asyncio
async def test_rust_initial_wait_and_close_fail_closed(monkeypatch):
    hue = Hue()
    engine = Engine(hue)
    rust = RustEventService(hue, SimpleNamespace(last_applied_bri=lambda lid: 120), engine)
    boundary = engine.lighting_transition_boundary
    async with independent_blocker(boundary):
        await rust.report_damage(100)
        task = rust._flinch_task
        engine.mode = "watching"
    await task
    assert not hue.calls
    engine.mode = "gaming"
    holding = asyncio.Event()

    async def hold(delay):
        holding.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("backend.services.rust_event_service.asyncio.sleep", hold)
    rust._flinch_cooldown_until = 0
    await rust.report_damage(100)
    await holding.wait()
    assert len(hue.calls) == 2
    await rust.close()
    assert rust._flinch_task is None and not rust._flinching and not rust.under_fire
    assert (await rust.report_damage(100))["reaction"] == "disabled"
    assert len(hue.calls) == 2


@pytest.mark.asyncio
async def test_scene_completion_lease_is_captured_inside_boundary():
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    v2 = SimpleNamespace(connected=True, mapped_light_ids=["2"], stop_effect_all=AsyncMock(return_value=True))
    manager = EffectManager(v2, transition_boundary=boundary)
    captured = []

    def complete():
        assert boundary.held_by_current_task
        captured.append(boundary.authority.issue("native", None))

    assert await manager.replace_with_action(
        AsyncMock(return_value=True), AsyncMock(return_value=True),
        on_complete=complete,
    )
    async with boundary.serialized():
        assert boundary.authority.valid(captured[0])
        boundary.authority.invalidate(["2"])
        assert not boundary.authority.valid(captured[0])


@pytest.mark.asyncio
async def test_override_chokepoints_and_failed_transit():
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    state = EngineState()
    manager = LightOverrideManager(
        state=state, hue_getter=lambda: hue, event_logger_getter=lambda: None,
        current_mode_getter=lambda: "gaming", reapply_mode=AsyncMock(), transition_boundary=boundary,
    )
    lease = boundary.authority.issue("probe", ["2"])
    manager.mark_manual("2", {"bri": 100})
    manager.clear_manual_stamps()
    async with boundary.serialized():
        assert not boundary.authority.valid(lease)
    lease = boundary.authority.issue("probe", ["2"])
    hue.success = False
    await manager.apply_transit_override({"2": {"bri": 100}})
    async with boundary.serialized():
        assert boundary.authority.valid(lease)
    assert not state.transit_light_overrides
    hue.success = True
    await manager.apply_transit_override({"2": {"bri": 100}})
    await manager.clear_transit_override()
    async with boundary.serialized():
        assert not boundary.authority.valid(lease)


@pytest.mark.asyncio
async def test_screen_frame_expires_while_waiting(monkeypatch):
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    sync = ScreenSyncService(hue, ["2"], boundary)
    now = 0.0
    sync._frame_clock = lambda: now
    issued = asyncio.Event()
    issue = boundary.authority.issue

    def capture(*args):
        lease = issue(*args)
        issued.set()
        return lease

    monkeypatch.setattr(boundary.authority, "issue", capture)
    async with independent_blocker(boundary):
        task = asyncio.create_task(sync.apply_color("2", 255, 0, 0, "watching"))
        await issued.wait()
        now = 8.0
    assert await task is False
    assert not hue.calls and sync.last_color_at is None


@pytest.mark.asyncio
async def test_screen_takeover_during_bridge_io_does_not_publish():
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    sync = ScreenSyncService(hue, ["2"], boundary)
    writing, resume = asyncio.Event(), asyncio.Event()
    write = hue.set_light

    async def wait_for_ack(lid, state):
        writing.set()
        await resume.wait()
        return await write(lid, state)

    hue.set_light = wait_for_ack
    task = asyncio.create_task(sync.apply_color("2", 255, 0, 0, "watching"))
    await writing.wait()
    boundary.authority.invalidate(["2"])
    resume.set()
    assert await task is False
    assert sync._last_sent_state == {} and sync.last_color_at is None


@pytest.mark.asyncio
async def test_screen_cancellation_and_shutdown_never_refresh(monkeypatch):
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    sync = ScreenSyncService(hue, ["2"], boundary)
    issued = asyncio.Event()
    issue = boundary.authority.issue

    def capture(*args):
        lease = issue(*args)
        issued.set()
        return lease

    monkeypatch.setattr(boundary.authority, "issue", capture)
    async with independent_blocker(boundary):
        task = asyncio.create_task(sync.apply_color("2", 255, 0, 0, "watching"))
        await issued.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        boundary.authority.close()
    assert await sync.apply_color("2", 255, 0, 0, "watching") is False
    assert not hue.calls and sync.last_color_at is None


@pytest.mark.asyncio
async def test_native_action_does_not_adopt_takeover_during_io():
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    v2 = SimpleNamespace(connected=True, mapped_light_ids=["2"], stop_effect_all=AsyncMock(return_value=True))
    manager = EffectManager(v2, transition_boundary=boundary)
    writing, resume = asyncio.Event(), asyncio.Event()
    complete = []

    async def action():
        writing.set()
        await resume.wait()
        return True

    task = asyncio.create_task(manager.replace_with_action(
        action, AsyncMock(return_value=True), on_complete=lambda: complete.append(True),
    ))
    await writing.wait()
    boundary.authority.invalidate()
    resume.set()
    assert await task is False
    assert complete == []


@pytest.mark.asyncio
async def test_failed_rust_dip_never_restores_or_advances_generation():
    hue = Hue()
    hue.success = False
    engine = Engine(hue)
    rust = RustEventService(hue, SimpleNamespace(last_applied_bri=lambda lid: 120), engine)
    rust.apply_config({"flinch_hold_s": 0})
    authority = engine.lighting_transition_boundary.authority
    lease = authority.issue("probe", ["2", "5"])
    await rust._do_flinch()
    assert len(hue.calls) == 2 and not engine.cached
    async with engine.lighting_transition_boundary.serialized():
        assert authority.valid(lease)


@pytest.mark.asyncio
async def test_effect_publication_revokes_frame_before_waiting_for_boundary(monkeypatch):
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    v2 = SimpleNamespace(connected=True, mapped_light_ids=["2"], stop_effect_all=AsyncMock(return_value=True))
    manager = EffectManager(v2, transition_boundary=boundary)
    published = asyncio.Event()
    invalidate = boundary.authority.invalidate

    def notify(*args):
        invalidate(*args)
        published.set()

    monkeypatch.setattr(boundary.authority, "invalidate", notify)
    lease = boundary.authority.issue("frame", ["2"])
    async with boundary.serialized():
        task = asyncio.create_task(manager.replace_with_action(AsyncMock(return_value=True), AsyncMock(return_value=True)))
        await published.wait()
        assert not boundary.authority.valid(lease)
    assert await task is True


@pytest.mark.asyncio
async def test_trial_setup_distinguishes_safety_acknowledgement_from_takeover():
    boundary = LightingTransitionBoundary(Hue())
    authority = boundary.authority
    setup = authority.issue("try_setup", None, intent_only=True)
    restore = authority.issue("try_restore", None)
    authority.invalidate(["2"], intent=False)
    async with boundary.serialized():
        assert authority.valid(setup)
        assert not authority.valid(restore)
        authority.invalidate(["2"])
        assert not authority.valid(setup)


@pytest.mark.asyncio
async def test_deduplicated_screen_frame_rechecks_before_freshness(monkeypatch):
    hue = Hue()
    sync = ScreenSyncService(hue, ["2"])
    sync.publish_accepted_gaming_state({"2": {"on": True, "ct": 350, "bri": 100}})
    assert await sync.apply_color("2", 255, 0, 0, "gaming")
    before = sync.last_color_at
    # Exercise the ownership-only path with a synchronous final intervention.
    record = sync._record_source_write

    def intervene(source, lid):
        sync._transition_boundary.authority.invalidate([lid])
        return record(source, lid)

    monkeypatch.setattr(sync, "_record_source_write", intervene)
    assert await sync.apply_color("2", 255, 0, 0, "gaming") is False
    assert len(hue.calls) == 1 and sync.last_color_at == before


@pytest.mark.asyncio
async def test_latest_queued_screen_frame_replaces_old_work(monkeypatch):
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    sync = ScreenSyncService(hue, ["2"], boundary)
    first, second = asyncio.Event(), asyncio.Event()
    issue = boundary.authority.issue
    issued = 0

    def capture(*args):
        nonlocal issued
        lease = issue(*args)
        issued += 1
        (first if issued == 1 else second).set()
        return lease

    monkeypatch.setattr(boundary.authority, "issue", capture)
    async with independent_blocker(boundary):
        old = asyncio.create_task(sync.apply_color("2", 255, 0, 0, "watching"))
        await first.wait()
        current = asyncio.create_task(sync.apply_color("2", 0, 0, 255, "watching"))
        await second.wait()
    assert await old is False
    assert await current is True
    assert len(hue.calls) == 1 and sync.last_color_at is not None


@pytest.mark.asyncio
async def test_non_media_frame_cancels_pending_first_color_without_claiming_hold(monkeypatch):
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    sync = ScreenSyncService(hue, ["2"], boundary)
    issued = asyncio.Event()
    issue = boundary.authority.issue

    def capture(*args):
        lease = issue(*args)
        issued.set()
        return lease

    monkeypatch.setattr(boundary.authority, "issue", capture)
    async with independent_blocker(boundary):
        task = asyncio.create_task(sync.apply_color("2", 255, 0, 0, "watching"))
        await issued.wait()
        sync.refresh_watching_hold("desktop", ["2"])
    assert await task is False
    assert not hue.calls and not sync._hold_refreshed_at and sync.last_color_at is None


@pytest.mark.asyncio
async def test_applicator_acknowledgements_are_scoped_and_failure_acquires_nothing():
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    state = EngineState()
    overrides = LightOverrideManager(
        state=state, hue_getter=lambda: hue, event_logger_getter=lambda: None,
        current_mode_getter=lambda: "working", reapply_mode=AsyncMock(), transition_boundary=boundary,
    )
    sync = ScreenSyncService(hue, ["2"], boundary)
    app = LightApplicator(
        state=state, overrides=overrides, hue_getter=lambda: hue,
        event_logger_getter=lambda: None, current_mode_getter=lambda: "working",
        screen_sync_getter=lambda: sync, external_owners_getter=lambda: [],
        suppressed_getter=lambda: False, dispatch_per_light=AsyncMock(),
        dispatch_uniform=AsyncMock(), transition_boundary=boundary,
    )
    lease = boundary.authority.issue("delayed", ["2"])
    disjoint = boundary.authority.issue("delayed", ["3"])
    setup = boundary.authority.issue("try_setup", None, intent_only=True)
    hue.success = False
    result = await app.apply_per_light({"2": {"on": True, "bri": 100, "ct": 350}})
    assert result.failed == {"2"} and not state.last_applied_per_light
    async with boundary.serialized():
        assert boundary.authority.valid(lease)
    hue.success = True
    result = await app.apply_per_light({"2": {"on": True, "bri": 100, "ct": 350}})
    assert result.successful == {"2"}
    async with boundary.serialized():
        assert not boundary.authority.valid(lease)
        assert boundary.authority.valid(disjoint)
        assert boundary.authority.valid(setup)
    assert state.last_applied_per_light["2"] == {"on": True, "bri": 100, "ct": 350}


@pytest.mark.asyncio
async def test_real_hue_adapter_parallel_delegation_does_not_reacquire_parent_lock():
    hue = HueService("fake-bridge", "fake-user")
    calls = []
    hue._connected = True
    hue._bridge = SimpleNamespace(set_light=lambda lid, state: calls.append((lid, state.copy())))
    boundary = LightingTransitionBoundary(hue)
    hue.set_transition_boundary(boundary)
    async with boundary.serialized():
        results = await asyncio.wait_for(boundary.write_many([
            lambda: hue.set_light("2", {"on": True, "bri": 100, "ct": 350}),
            lambda: hue.set_light("5", {"on": True, "bri": 50, "hue": 1000, "sat": 100}),
        ]), timeout=2)
    assert results == [True, True]
    assert {lid for lid, _ in calls} == {2, 5}
    assert set(hue._inflight_until) == {"2", "5"}


@pytest.mark.asyncio
async def test_cancelled_screen_write_retains_fence_until_thread_settles():
    import threading

    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    completed = threading.Event()
    hue = HueService("fake-bridge", "fake-user")
    hue._connected = True

    def bridge_write(lid, state):
        loop.call_soon_threadsafe(entered.set)
        release.wait(5)
        completed.set()

    hue._bridge = SimpleNamespace(set_light=bridge_write)
    boundary = LightingTransitionBoundary(hue)
    hue.set_transition_boundary(boundary)
    sync = ScreenSyncService(hue, ["2"], boundary)
    contender_queued, contender_entered = asyncio.Event(), asyncio.Event()

    async def contender():
        contender_queued.set()
        async with boundary.serialized():
            assert completed.is_set()
            contender_entered.set()

    task = asyncio.create_task(sync.apply_color("2", 255, 0, 0, "watching"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        other = asyncio.create_task(contender())
        await contender_queued.wait()
        task.cancel()  # Repeated cancellation must not release the fence either.
        assert not task.done() and not contender_entered.is_set()
    finally:
        release.set()
    await asyncio.gather(task, return_exceptions=True)
    await other
    assert task.cancelled() and completed.is_set()
    assert sync.last_color_at is None and sync._last_sent_state == {}


@pytest.mark.asyncio
async def test_breaker_timeout_cancellation_waits_for_actual_mutation_thread(monkeypatch):
    import threading

    loop = asyncio.get_running_loop()
    started, timed_out = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    finished = threading.Event()
    hue = HueService("fake-bridge", "fake-user")
    hue._connected = True

    def bridge_write(lid, state):
        loop.call_soon_threadsafe(started.set)
        release.wait(5)
        finished.set()

    hue._bridge = SimpleNamespace(set_light=bridge_write)
    boundary = LightingTransitionBoundary(hue)
    hue.set_transition_boundary(boundary)
    real_wait_for = asyncio.wait_for

    async def expire(awaitable, timeout):
        operation = asyncio.ensure_future(awaitable)
        await started.wait()
        operation.cancel()  # Deterministic stand-in for the breaker timer firing.
        timed_out.set()
        try:
            await operation
        except asyncio.CancelledError:
            raise TimeoutError from None

    monkeypatch.setattr("backend.services.circuit_breaker.asyncio.wait_for", expire)
    task = asyncio.create_task(hue.set_light("2", {"on": True, "bri": 100}))
    try:
        await real_wait_for(timed_out.wait(), timeout=2)
        assert not task.done() and boundary._lock.locked() and not finished.is_set()
    finally:
        release.set()
    assert await task is False
    assert finished.is_set() and not boundary._lock.locked()
    assert not hue._inflight_until


@pytest.mark.asyncio
async def test_cancelled_native_action_settles_and_never_captures_ack():
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    v2 = SimpleNamespace(connected=True, mapped_light_ids=["2"], stop_effect_all=AsyncMock(return_value=True))
    manager = EffectManager(v2, transition_boundary=boundary)
    manager._tracker_known = True
    started, release = asyncio.Event(), asyncio.Event()
    queued, entered = asyncio.Event(), asyncio.Event()
    acknowledged = []

    async def action():
        started.set()
        await release.wait()
        return True

    async def contender():
        queued.set()
        async with boundary.serialized():
            entered.set()

    task = asyncio.create_task(manager.replace_with_action(
        action, AsyncMock(return_value=True), on_complete=lambda: acknowledged.append(True),
    ))
    await started.wait()
    task.cancel()
    other = asyncio.create_task(contender())
    await queued.wait()
    assert not task.done() and not entered.is_set()
    release.set()
    await asyncio.gather(task, return_exceptions=True)
    await other
    assert task.cancelled() and acknowledged == [] and not manager.authority_known


@pytest.mark.asyncio
async def test_empty_target_invalidation_is_a_true_noop():
    boundary = LightingTransitionBoundary(Hue())
    authority = boundary.authority
    whole = authority.issue("whole", None)
    targeted = authority.issue("targeted", ["2"])
    setup = authority.issue("setup", None, intent_only=True)
    authority.invalidate([])
    async with boundary.serialized():
        assert authority.valid(whole)
        assert authority.valid(targeted)
        assert authority.valid(setup)


@pytest.mark.asyncio
async def test_screen_frame_and_hold_expiry_publish_scoped_release():
    from datetime import datetime, timedelta, timezone

    boundary = LightingTransitionBoundary(Hue())
    sync = ScreenSyncService(boundary._hue, ["2", "5"], boundary)
    assert await sync.apply_color("2", 255, 0, 0, "watching")
    sync.refresh_watching_hold("desktop", ["2"])
    whole = boundary.authority.issue("trial", None)
    expired = boundary.authority.issue("restore", ["2"])
    disjoint = boundary.authority.issue("restore", ["5"])
    old = datetime.now(timezone.utc) - timedelta(minutes=1)
    sync._last_color_at_by_light["2"] = old
    sync._hold_refreshed_at[("desktop", "2")] = old
    assert sync.fresh_owned_light_ids() == set()
    async with boundary.serialized():
        assert not boundary.authority.valid(whole)
        assert not boundary.authority.valid(expired)
        assert boundary.authority.valid(disjoint)
    released = boundary.authority.issue("released", None)
    sync.fresh_owned_light_ids()
    async with boundary.serialized():
        assert boundary.authority.valid(released)  # Expiry is published once.


@pytest.mark.asyncio
async def test_unacknowledged_cancel_does_not_advance_write_generation():
    boundary = LightingTransitionBoundary(Hue())
    lease = boundary.authority.issue("probe", ["2"])
    entered, release = asyncio.Event(), asyncio.Event()

    async def write():
        entered.set()
        await release.wait()
        return False

    async def caller():
        async with boundary.serialized():
            await boundary.run_write(write, light_ids=["2"])

    task = asyncio.create_task(caller())
    await entered.wait()
    task.cancel()
    release.set()
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    async with boundary.serialized():
        assert boundary.authority.valid(lease)


@pytest.mark.asyncio
async def test_stale_successful_screen_write_forgets_old_dedup_cache():
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    sync = ScreenSyncService(hue, ["2"], boundary)

    assert await sync.apply_watching_daylight(
        "2", zone="desk", lux_multiplier=1.0,
    )
    assert "2" in sync._last_daylight_state
    original_write = hue.set_light
    writing, resume = asyncio.Event(), asyncio.Event()

    async def delayed_write(lid, state):
        writing.set()
        await resume.wait()
        return await original_write(lid, state)

    hue.set_light = delayed_write
    task = asyncio.create_task(sync.apply_watching_daylight(
        "2", zone="desk", lux_multiplier=1.3,
    ))
    await writing.wait()
    boundary.authority.invalidate(["2"])
    resume.set()
    assert await task is False
    assert "2" not in sync._last_daylight_state
    assert "2" not in sync._last_sent_state
    assert "2" not in sync._last_color_at_by_light

    hue.set_light = original_write
    before = len(hue.calls)
    assert await sync.apply_watching_daylight(
        "2", zone="desk", lux_multiplier=1.0,
    )
    assert len(hue.calls) == before + 1


@pytest.mark.asyncio
async def test_scene_transition_does_not_adopt_takeover_during_safety():
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    stop = AsyncMock(return_value=True)
    action = AsyncMock(return_value=True)
    v2 = SimpleNamespace(
        connected=True, mapped_light_ids=["2"], stop_effect_all=stop,
    )
    manager = EffectManager(v2, transition_boundary=boundary)

    async def safety(_required):
        boundary.authority.invalidate()
        return True

    assert await manager.replace_with_action(action, safety) is False
    action.assert_not_awaited()
    stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_effect_start_is_suppressed_when_intent_changes_during_guard(monkeypatch):
    hue = Hue()
    boundary = LightingTransitionBoundary(hue)
    stop = AsyncMock(return_value=True)
    start = AsyncMock(return_value=True)
    v2 = SimpleNamespace(
        connected=True,
        mapped_light_ids=["2"],
        stop_effect_all=stop,
        set_effect_all=start,
    )
    manager = EffectManager(v2, transition_boundary=boundary)
    manager._tracker_known = False

    async def takeover_sleep(_seconds):
        boundary.authority.invalidate()

    monkeypatch.setattr(
        "backend.services.effect_manager.asyncio.sleep", takeover_sleep,
    )
    assert await manager.reconcile(
        "candle", AsyncMock(return_value=True),
    ) is False
    stop.assert_awaited_once()
    start.assert_not_awaited()
    assert manager.authority_known is False


@pytest.mark.asyncio
async def test_caller_cancel_during_breaker_timeout_cleanup_keeps_hue_fence(monkeypatch):
    import threading

    loop = asyncio.get_running_loop()
    started, timed_out = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    finished = threading.Event()
    hue = HueService("fake-bridge", "fake-user")
    hue._connected = True

    def bridge_write(lid, state):
        loop.call_soon_threadsafe(started.set)
        release.wait(5)
        finished.set()

    hue._bridge = SimpleNamespace(set_light=bridge_write)
    boundary = LightingTransitionBoundary(hue)
    hue.set_transition_boundary(boundary)
    real_wait_for = asyncio.wait_for

    async def expire(awaitable, timeout):
        operation = asyncio.ensure_future(awaitable)
        await started.wait()
        operation.cancel()
        timed_out.set()
        try:
            await operation
        except asyncio.CancelledError:
            raise TimeoutError from None

    monkeypatch.setattr(
        "backend.services.circuit_breaker.asyncio.wait_for", expire,
    )
    task = asyncio.create_task(
        hue.set_light("2", {"on": True, "bri": 100}),
    )
    try:
        await real_wait_for(timed_out.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert boundary._lock.locked()
        assert not finished.is_set()
    finally:
        release.set()

    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert finished.is_set()
    assert not boundary._lock.locked()
    assert not hue._inflight_until
