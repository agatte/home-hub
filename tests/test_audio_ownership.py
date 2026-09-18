"""Tests for the shared Sonos/audio ownership authority."""
from __future__ import annotations

from copy import deepcopy

import pytest

from backend.services.audio_ownership import (
    INTERRUPTION,
    MANUAL_TRANSPORT_DIMENSIONS,
    MANUAL_VOLUME_DIMENSIONS,
    QUEUE_SOURCE,
    TRANSPORT,
    VOLUME,
    AudioOwnershipService,
)


class MemorySettings:
    def __init__(self, initial: dict | None = None) -> None:
        self.value = deepcopy(initial or {})

    async def load(self, _key: str) -> dict:
        return deepcopy(self.value)

    async def save(self, _key: str, value: dict) -> None:
        self.value = deepcopy(value)


@pytest.mark.asyncio
async def test_conflicting_dimensions_cannot_be_double_owned() -> None:
    settings = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )

    first = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
    )
    assert first is not None

    second = await authority.acquire(
        owner="ambient",
        purpose="ambient_playback",
        dimensions=(QUEUE_SOURCE,),
    )
    assert second is None

    volume = await authority.acquire(
        owner="mode_volume",
        purpose="mode_ramp",
        dimensions=(VOLUME,),
    )
    assert volume is not None


@pytest.mark.asyncio
async def test_manual_volume_only_invalidates_volume_and_interruption() -> None:
    settings = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )
    queue = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
    )
    volume = await authority.acquire(
        owner="mode_volume",
        purpose="mode_ramp",
        dimensions=(VOLUME, INTERRUPTION),
    )
    assert queue is not None and volume is not None

    event = await authority.invalidate_manual(
        MANUAL_VOLUME_DIMENSIONS,
        source="dashboard",
        reason="manual_volume",
    )

    assert event["invalidated"][0]["lease_id"] == volume["lease_id"]
    assert await authority.is_valid(queue["lease_id"])
    assert not await authority.is_valid(volume["lease_id"])


@pytest.mark.asyncio
async def test_manual_transport_retires_queue_transport_but_not_volume() -> None:
    settings = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )

    queue = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
    )
    volume = await authority.acquire(
        owner="mode_volume",
        purpose="mode_ramp",
        dimensions=(VOLUME,),
    )
    assert queue is not None and volume is not None

    await authority.invalidate_manual(
        MANUAL_TRANSPORT_DIMENSIONS,
        source="sonos_app",
        reason="manual_skip",
    )

    assert not await authority.is_valid(queue["lease_id"])
    assert await authority.is_valid(volume["lease_id"])


@pytest.mark.asyncio
async def test_leases_survive_restart_with_evidence() -> None:
    settings = MemorySettings()
    first = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )
    lease = await first.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
        evidence={"phase": "owned", "sonos": {"queue_update_id": "42"}},
        metadata={"mode": "social", "favorite_title": "2000s Hits Essentials"},
    )
    assert lease is not None


    restarted = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )
    await restarted.load()
    restored = await restarted.find_lease(
        owner="music_mapper", purpose="mode_auto_play",
    )

    assert restored is not None
    assert restored["lease_id"] == lease["lease_id"]
    assert restored["evidence"]["sonos"]["queue_update_id"] == "42"
    assert restored["metadata"]["mode"] == "social"


@pytest.mark.asyncio
async def test_unsupported_persisted_version_fails_neutral() -> None:
    settings = MemorySettings({
        "version": 999,
        "generation": 80,
        "leases": {
            "stale": {
                "owner": "music_mapper",
                "purpose": "mode_auto_play",
                "dimensions": [QUEUE_SOURCE, TRANSPORT],
            },
        },
    })
    authority = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )
    await authority.load()

    snapshot = await authority.snapshot()
    assert snapshot["generation"] == 0
    assert snapshot["leases"] == []


@pytest.mark.asyncio
async def test_autonomous_write_and_manual_invalidation_serialize() -> None:
    import asyncio

    settings = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )
    lease = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
    )
    assert lease is not None

    started = asyncio.Event()
    release_operation = asyncio.Event()
    events: list[str] = []

    async def operation():
        events.append("operation_started")
        started.set()
        await release_operation.wait()
        events.append("operation_finished")
        return True

    runner = asyncio.create_task(
        authority.run_if_valid(
            lease["lease_id"], (QUEUE_SOURCE, TRANSPORT), operation,
        )
    )
    await started.wait()
    invalidator = asyncio.create_task(
        authority.invalidate_manual(
            MANUAL_TRANSPORT_DIMENSIONS,
            source="dashboard",
            reason="manual_play",
        )
    )
    await asyncio.sleep(0)
    assert not invalidator.done()

    release_operation.set()
    executed, result = await runner
    await invalidator

    assert executed is True and result is True
    assert events == ["operation_started", "operation_finished"]
    assert not await authority.is_valid(lease["lease_id"])


@pytest.mark.asyncio
async def test_manual_write_stays_serialized_after_invalidation() -> None:
    import asyncio

    settings = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )
    lease = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
    )
    assert lease is not None

    manual_started = asyncio.Event()
    finish_manual = asyncio.Event()
    events: list[str] = []

    async def manual_operation():
        events.append("manual_started")
        manual_started.set()
        await finish_manual.wait()
        events.append("manual_finished")
        return True

    manual = asyncio.create_task(
        authority.run_manual(
            MANUAL_TRANSPORT_DIMENSIONS,
            source="dashboard",
            reason="manual_play",
            operation=manual_operation,
        )
    )
    await manual_started.wait()
    assert lease["lease_id"] not in (settings.value.get("leases") or {})

    acquire = asyncio.create_task(
        authority.acquire(
            owner="music_mapper",
            purpose="mode_auto_play_after_manual",
            dimensions=(QUEUE_SOURCE, TRANSPORT),
        )
    )
    await asyncio.sleep(0)
    assert not acquire.done()

    finish_manual.set()
    assert await manual is True
    replacement = await acquire
    assert replacement is not None
    assert events == ["manual_started", "manual_finished"]
