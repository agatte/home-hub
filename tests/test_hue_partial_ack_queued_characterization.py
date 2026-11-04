"""Characterize a partial Hue v1 ACK followed by a queued action (#370).

Fake Bridge.request only. The check proves local serialization and exposes the
absence of a settle deadline after partial ACK; it does NOT certify physical
completion or authorize a subsequent real effect/one-shot command.
"""
import asyncio
from contextlib import asynccontextmanager
from threading import Event
from unittest.mock import Mock

import pytest
from phue import Bridge

from backend.services.hue_service import HueService
from backend.services.lighting_transition_boundary import LightingTransitionBoundary


def _reply(**values):
    return [
        {"success": {f"/lights/1/state/{name}": value}}
        for name, value in values.items()
    ]


@pytest.mark.asyncio
async def test_partial_ack_then_queued_write_serializes_but_has_no_settle_evidence():
    worker_started = Event()
    complete_first_worker = Event()
    followup_attempted_boundary = asyncio.Event()
    requests = []
    settle_seen_at_followup = []
    service = HueService("offline.invalid", "offline")
    service._breaker.call_timeout = 15.0  # Accommodate CI executor contention.

    def request(method, path, command):
        assert method == "PUT"
        assert path == "/api/offline/lights/1/state"
        requests.append(dict(command))
        if len(requests) == 1:
            worker_started.set()
            assert complete_first_worker.wait(12), "fake worker release was not signaled"
            # Brightness/transition may be accepted while on is unacknowledged.
            return _reply(bri=40, transitiontime=10)
        settle_seen_at_followup.append(dict(service._transition_settle_until))
        return _reply(on=False, transitiontime=0)

    bridge = object.__new__(Bridge)
    bridge._username = "offline"
    bridge.request = Mock(side_effect=request)
    service._connected = True
    service._bridge = bridge
    boundary = LightingTransitionBoundary(service)
    service.set_transition_boundary(boundary)
    original_serialized = boundary.serialized
    followup = None

    @asynccontextmanager
    async def tracked_serialized():
        if asyncio.current_task() is followup:
            followup_attempted_boundary.set()
        async with original_serialized():
            yield

    boundary.serialized = tracked_serialized
    initial = asyncio.create_task(
        service.set_light("1", {"on": True, "bri": 40, "transitiontime": 10})
    )
    try:
        assert await asyncio.to_thread(worker_started.wait, 8)
        followup = asyncio.create_task(
            service.set_light("1", {"on": False, "transitiontime": 0})
        )
        # Prove the second coroutine attempted to acquire the serializer
        # while the first fake bridge worker was still blocked.
        await asyncio.wait_for(followup_attempted_boundary.wait(), timeout=8)
        assert not followup.done()
        assert bridge.request.call_count == 1
        complete_first_worker.set()
        first_result, followup_result = await asyncio.wait_for(
            asyncio.gather(initial, followup), timeout=12
        )
    finally:
        complete_first_worker.set()
        tasks = [task for task in (initial, followup) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=12)
    assert (first_result, followup_result) == (False, True)
    assert len(requests) == bridge.request.call_count == 2  # no retry or probe
    assert settle_seen_at_followup == [{}]
    assert requests == [
        {"on": True, "bri": 40, "transitiontime": 10},
        {"on": False, "transitiontime": 0},
    ]


@pytest.mark.asyncio
async def test_partial_ack_does_not_create_future_effect_settle_barrier():
    service = HueService("offline.invalid", "offline")
    bridge = object.__new__(Bridge)
    bridge._username = "offline"
    bridge.request = Mock(return_value=_reply(bri=40, transitiontime=10))
    service._connected = True
    service._bridge = bridge
    boundary = LightingTransitionBoundary(service)
    service.set_transition_boundary(boundary)

    assert await service.set_light(
        "1", {"on": True, "bri": 40, "transitiontime": 10}
    ) is False
    assert service._transition_settle_until == {}
    assert service._inflight_until == {}
    # This API is a no-op for rejected ACKs, *not* proof that the bulb did
    # nothing. A real subsequent effect must still satisfy a product policy
    # for uncertain remote outcomes and physical quiescence.
    await asyncio.wait_for(boundary.wait_for_settle(["1"]), timeout=1)
    bridge.request.assert_called_once()
