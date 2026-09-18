"""Cancellation-safe Sonos mutation serialization (#274)."""
from __future__ import annotations

import asyncio
import threading
from copy import deepcopy

import pytest

from backend.services.audio_ownership import (
    MANUAL_TRANSPORT_DIMENSIONS,
    QUEUE_SOURCE,
    TRANSPORT,
    AudioOwnershipService,
)
from backend.services.sonos_service import SonosService


class MemorySettings:
    def __init__(self) -> None:
        self.value: dict = {}

    async def load(self, _key: str) -> dict:
        return deepcopy(self.value)

    async def save(self, _key: str, value: dict) -> None:
        self.value = deepcopy(value)


@pytest.mark.asyncio
async def test_timed_out_sonos_worker_settles_before_manual_write_can_start() -> None:
    settings = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=settings.load,
        setting_saver=settings.save,
    )
    lease = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
    )
    assert lease is not None

    sync_started = threading.Event()
    release_sync = threading.Event()
    events: list[str] = []

    class BlockingDevice:
        def play(self) -> None:
            events.append("sync_started")
            sync_started.set()
            release_sync.wait(timeout=2.0)
            events.append("sync_finished")

    sonos = SonosService()
    sonos._connected = True
    sonos._device = BlockingDevice()
    sonos._breaker.call_timeout = 0.02

    async def autonomous_write() -> bool:
        return await sonos.play()

    auto_task = asyncio.create_task(
        authority.run_if_valid(
            lease["lease_id"],
            (QUEUE_SOURCE, TRANSPORT),
            autonomous_write,
        )
    )
    for _ in range(100):
        if sync_started.is_set():
            break
        await asyncio.sleep(0.005)
    assert sync_started.is_set()

    async def manual_write() -> bool:
        events.append("manual_write")
        return True

    manual_task = asyncio.create_task(
        authority.run_manual(
            MANUAL_TRANSPORT_DIMENSIONS,
            source="dashboard",
            reason="manual_play",
            operation=manual_write,
        )
    )

    await asyncio.sleep(0.06)
    assert not auto_task.done()
    assert not manual_task.done()
    assert events == ["sync_started"]

    release_sync.set()
    executed, result = await auto_task
    manual_result = await manual_task

    assert executed is True
    assert result is False
    assert manual_result is True
    assert events == ["sync_started", "sync_finished", "manual_write"]
