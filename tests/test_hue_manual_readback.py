"""Manual readback runs through the existing poll loop, not a new writer."""
import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from backend.services.hue_service import HueService


@pytest.mark.asyncio
async def test_manual_ack_wakes_slow_poller_after_settle_and_coalesces_pair():
    hue = HueService("offline.invalid", "fake")
    hue.set_v2_stream_active(True)
    first_read = asyncio.Event()
    updated = asyncio.Event()
    reads = []
    reported = []
    states = [{"light_id": lid, "on": False} for lid in ("3", "4")]

    async def read():
        reads.append(time.monotonic())
        first_read.set()
        return [dict(row) for row in states]

    async def broadcast(kind, data):
        assert kind == "light_update"
        reported.append(dict(data))
        if len([row for row in reported if row["on"]]) == 2:
            updated.set()

    hue.get_all_lights = read
    hue.set_light = AsyncMock()
    ws = type("WS", (), {})()
    ws.broadcast = broadcast
    task = asyncio.create_task(hue.poll_state_loop(ws))
    try:
        await asyncio.wait_for(first_read.wait(), 2)
        deadline = time.monotonic() + 0.1
        for row in states:
            row["on"] = True
            lid = row["light_id"]
            hue._inflight_until[lid] = deadline
            hue.request_manual_readback(lid)
        await asyncio.wait_for(updated.wait(), 2)
        assert len(reads) == 2
        assert reads[-1] >= deadline
        assert reported == [
            {"light_id": "3", "on": False}, {"light_id": "4", "on": False},
            {"light_id": "3", "on": True}, {"light_id": "4", "on": True},
        ]
        assert not hue._manual_readbacks
        hue.set_light.assert_not_called()
    finally:
        task.cancel()
        await task


@pytest.mark.asyncio
async def test_precommand_read_returning_late_cannot_publish_stale_manual_state():
    hue = HueService("offline.invalid", "fake")
    hue.set_v2_stream_active(True)
    entered, release, updated = asyncio.Event(), asyncio.Event(), asyncio.Event()
    reads = 0
    reported = []

    async def read():
        nonlocal reads
        reads += 1
        if reads == 1:
            entered.set()
            await release.wait()
            return [{"light_id": "3", "on": False}]
        return [{"light_id": "3", "on": True}]

    async def broadcast(kind, data):
        assert kind == "light_update"
        reported.append(dict(data))
        updated.set()

    hue.get_all_lights = read
    ws = type("WS", (), {})()
    ws.broadcast = broadcast
    task = asyncio.create_task(hue.poll_state_loop(ws))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        hue._inflight_until["3"] = time.monotonic()
        hue.request_manual_readback("3")
        release.set()
        await asyncio.wait_for(updated.wait(), 2)
        assert reads == 2
        assert reported == [{"light_id": "3", "on": True}]
        assert not hue._manual_readbacks
    finally:
        task.cancel()
        await task
