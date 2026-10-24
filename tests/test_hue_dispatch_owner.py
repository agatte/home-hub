"""Owner fencing at the real Hue thread dispatch; no bridge/network access."""
import asyncio
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import patch

import pytest

from backend.services.hue_service import HueService
from backend.services.lighting_transition_boundary import (
    LightingTransitionBoundary, lighting_write_validator,
)


def service():
    hue = HueService("fake", "fake")
    hue._connected = True
    calls = []

    class Bridge:
        def set_light(self, lid, command):
            calls.append((lid, command))

    hue._bridge = Bridge()
    boundary = LightingTransitionBoundary(hue)
    hue.set_transition_boundary(boundary)
    return hue, boundary, calls


@pytest.mark.asyncio
async def test_dispatch_owner_changes():
    # Single/multi light, ABA, manual and sleep takeover, unchanged and
    # unqualified consumers. Pause inside the executor before the guard runs.
    for count in (1, 2):
        for takeover in ("aba", "manual", "sleep", "unchanged", "unqualified"):
            hue, boundary, calls = service()
            owner = [7, "gaming"]
            expected = tuple(owner)
            entered = [Event() for _ in range(count)]
            release = Event()
            original = asyncio.to_thread
            index = 0

            async def paused(fn, *args, **kwargs):
                nonlocal index
                slot = index
                index += 1

                def worker():
                    entered[slot].set()
                    assert release.wait(3)
                    return fn(*args, **kwargs)

                return await original(worker)

            async def apply():
                async with boundary.serialized():
                    writes = [lambda lid=str(i): hue.set_light(lid, {"bri": 100})
                              for i in range(1, count + 1)]
                    validator = None if takeover == "unqualified" else lambda: tuple(owner) == expected
                    if count == 1:
                        return [await boundary.run_write(writes[0], validator=validator)]
                    return await boundary.write_many(writes, validator=validator)

            with patch("asyncio.to_thread", paused):
                task = asyncio.create_task(apply())
                try:
                    while not all(event.is_set() for event in entered):
                        await asyncio.sleep(0)
                    if takeover == "aba":
                        owner[:] = [8, "working"]
                        owner[:] = [9, "gaming"]
                    elif takeover in ("manual", "sleep"):
                        owner[:] = [8, takeover]
                    release.set()
                    allowed = takeover in ("unchanged", "unqualified")
                    assert await task == [allowed] * count
                    assert len(calls) == (count if allowed else 0)
                    assert bool(hue._inflight_until) == allowed
                    assert bool(hue._transition_settle_until) == allowed
                finally:
                    release.set()
                    await task
            assert lighting_write_validator.get() is None


@pytest.mark.asyncio
async def test_half_open_dispatch_rechecks_falsy_validator():
    hue, boundary, calls = service()
    hue.breaker._state = hue.breaker.OPEN
    hue.breaker._opened_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    validations = []

    def validator():
        validations.append(True)
        return True if len(validations) == 1 else None

    async with boundary.serialized():
        assert await boundary.run_write(
            lambda: hue.set_light("1", {"bri": 100}), validator=validator,
        ) is False
    assert len(validations) == 2
    assert calls == []
    assert hue._inflight_until == {}


@pytest.mark.asyncio
async def test_cancelled_dispatch_retains_boundary_until_worker_settles():
    hue, boundary, calls = service()
    entered, release = Event(), Event()
    original = asyncio.to_thread
    owner = [1]

    async def paused(fn, *args, **kwargs):
        def worker():
            entered.set()
            assert release.wait(3)
            return fn(*args, **kwargs)
        return await original(worker)

    async def apply():
        async with boundary.serialized():
            return await boundary.run_write(
                lambda: hue.set_light("1", {"bri": 100}),
                validator=lambda: owner[0] == 1,
            )

    async def follower():
        async with boundary.serialized():
            return True

    with patch("asyncio.to_thread", paused):
        task = asyncio.create_task(apply())
        other = None
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            task.cancel()
            task.cancel()
            owner[0] = 2
            other = asyncio.create_task(follower())
            for _ in range(20):
                await asyncio.sleep(0)
            assert not task.done()
            assert not other.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await other
            assert calls == []
        finally:
            release.set()
            await asyncio.gather(task, *([other] if other else []), return_exceptions=True)

@pytest.mark.asyncio
async def test_guarded_worker_validates_lighting_lease_in_thread():
    """A real ScreenSync-style lease is valid in the delegated thread only."""
    hue, boundary, calls = service()
    async with boundary.serialized():
        lease = boundary.authority.issue("screen_sync", ["1"])
        def valid():
            return boundary.authority.valid(lease)
        assert await boundary.run_write(
            lambda: hue.set_light("1", {"bri": 100}), validator=valid,
        ) is True
    assert calls == [(1, {"bri": 100})]
    # A plain detached executor caller must not acquire Hue authority.
    with pytest.raises(RuntimeError, match="final boundary"):
        await asyncio.to_thread(lambda: boundary.authority.valid(lease))


@pytest.mark.asyncio
async def test_screen_lease_revoked_while_bridge_worker_queued():
    """Thread-entry rechecks the latest lease; cancellation cannot bypass it."""
    hue, boundary, calls = service()
    original = asyncio.to_thread
    entered, release = Event(), Event()

    async def paused(fn, *args, **kwargs):
        def worker():
            entered.set()
            assert release.wait(3)
            return fn(*args, **kwargs)
        return await original(worker)

    async def apply():
        async with boundary.serialized():
            lease = boundary.authority.issue("screen_sync", ["1"])
            def valid():
                return boundary.authority.valid(lease)
            return await boundary.run_write(
                lambda: hue.set_light("1", {"bri": 110}),
                validator=valid,
            )

    with patch("asyncio.to_thread", paused):
        task = asyncio.create_task(apply())
        try:
            for _ in range(500):
                if entered.is_set():
                    break
                await asyncio.sleep(0.002)
            assert entered.is_set()
            boundary.authority.invalidate(["1"])
            release.set()
            assert await task is False
            assert calls == []
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_authority_change_after_bridge_entry_cannot_revoke_transport():
    """Remaining #370/#387 gate: semantic publication and transport aren't atomic.

    Treating worker validation as admission orders serialized bridge writes, but
    synchronous intent can still change before the admitted transport sends.
    Strict semantic ordering needs intent publication/admission to share an
    arbiter (or a transport-level cancellable protocol). The existing async
    boundary cannot provide that guarantee, and a lock across bridge I/O is
    intentionally not introduced. This test proves the limitation offline.
    """
    hue, boundary, calls = service()
    entered, release = Event(), Event()
    owner = [1]

    def transport(lid, command):
        entered.set()
        assert release.wait(3)
        calls.append((lid, command))

    hue._bridge.set_light = transport

    async def apply():
        async with boundary.serialized():
            return await boundary.run_write(
                lambda: hue.set_light("1", {"bri": 100}),
                validator=lambda: owner[0] == 1,
            )

    task = asyncio.create_task(apply())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        owner[0] = 2
        release.set()
        assert await task is True
        assert calls == [(1, {"bri": 100})]
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke", ["source", "lease", "none"])
async def test_delegated_write_composes_source_and_local_lease_at_worker_entry(revoke):
    hue, boundary, calls = service()
    source_revision = [0]
    entered, release = Event(), Event()
    original = asyncio.to_thread

    async def paused(fn, *args, **kwargs):
        def worker():
            entered.set()
            assert release.wait(3)
            return fn(*args, **kwargs)
        return await original(worker)

    async def apply():
        token = lighting_write_validator.set(lambda: source_revision[0] == 0)
        try:
            async with boundary.serialized():
                lease = boundary.authority.issue("scene_transition", None, intent_only=True)
                return await boundary.run_write(
                    lambda: hue.set_light("1", {"bri": 100}),
                    validator=lambda: boundary.authority.valid(lease),
                )
        finally:
            lighting_write_validator.reset(token)

    with patch("asyncio.to_thread", paused):
        task = asyncio.create_task(apply())
        try:
            assert await original(entered.wait, 2)
            if revoke == "source":
                source_revision[0] += 1
            elif revoke == "lease":
                boundary.authority.invalidate()
            release.set()
            assert await task is (revoke == "none")
            assert calls == ([(1, {"bri": 100})] if revoke == "none" else [])
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["scene", "effect", "per_light_effect"])
@pytest.mark.parametrize("wait_at", ["safety", "settle"])
async def test_native_transition_post_await_source_checkpoint(path, wait_at):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.services.effect_manager import EffectManager

    hue, boundary, calls = service()
    native = SimpleNamespace(
        connected=True, mapped_light_ids={"1"},
        stop_effect_all=AsyncMock(return_value=True),
        set_effect_all=AsyncMock(return_value=True),
        set_effect=AsyncMock(return_value=True),
    )
    manager = EffectManager(native, transition_boundary=boundary)
    entered, release = asyncio.Event(), asyncio.Event()
    source_current = [True]
    action = AsyncMock(return_value=True)

    async def checkpoint():
        entered.set()
        await release.wait()

    async def safety(ids):
        if wait_at == "safety":
            await checkpoint()
        return True

    async def settle(ids):
        if wait_at == "settle":
            await checkpoint()

    boundary.wait_for_settle = settle

    async def apply():
        token = lighting_write_validator.set(lambda: source_current[0])
        try:
            if path == "scene":
                return await manager.replace_with_action(action, safety)
            if path == "effect":
                return await manager.reconcile("candle", safety)
            return await manager.reconcile_light("1", "candle", safety)
        finally:
            lighting_write_validator.reset(token)

    task = asyncio.create_task(apply())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        source_current[0] = False
        release.set()
        assert await asyncio.wait_for(task, 2) is False
        action.assert_not_awaited()
        native.stop_effect_all.assert_not_awaited()
        native.set_effect_all.assert_not_awaited()
        native.set_effect.assert_not_awaited()
        assert calls == []
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
