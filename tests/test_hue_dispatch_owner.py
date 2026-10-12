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
