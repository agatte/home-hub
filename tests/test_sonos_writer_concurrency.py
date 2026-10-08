"""Real authority + fake synchronous device regressions for the #276 audit."""
from __future__ import annotations

import asyncio
import threading
from copy import deepcopy

import pytest

from backend.services.audio_ownership import (
    MANUAL_TRANSPORT_DIMENSIONS,
    MANUAL_VOLUME_DIMENSIONS,
    QUEUE_SOURCE,
    TRANSPORT,
    VOLUME,
    AudioOwnershipService,
)
from backend.services.mode_volume_service import ModeVolumeService
from backend.services.sonos_service import SonosService


class MemorySettings:
    def __init__(self) -> None:
        self.value: dict = {}

    async def load(self, _key: str) -> dict:
        return deepcopy(self.value)

    async def save(self, _key: str, value: dict) -> None:
        self.value = deepcopy(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_raises", [False, True])
async def test_repeated_cancellation_keeps_authority_until_worker_settles(
    worker_raises: bool,
) -> None:
    """A second cancellation and a worker failure must not free authority early."""
    settings = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )
    lease = await authority.acquire(
        owner="music_mapper", purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
    )
    assert lease is not None
    started = asyncio.Event()
    release = threading.Event()
    events: list[str] = []
    loop = asyncio.get_running_loop()

    class Device:
        def play(self) -> None:
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise AssertionError("test did not release fake worker")
            events.append("settled")
            if worker_raises:
                raise RuntimeError("fake device failure after cancellation")

    sonos = SonosService()
    sonos._connected = True
    sonos._device = Device()
    sonos._breaker.call_timeout = 10
    auto = asyncio.create_task(authority.run_if_valid(
        lease["lease_id"], (QUEUE_SOURCE, TRANSPORT), sonos.play,
    ))
    manual_entered = asyncio.Event()

    async def manual_write() -> bool:
        events.append("manual")
        manual_entered.set()
        return True

    manual = None
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        auto.cancel()
        await asyncio.sleep(0)
        auto.cancel()
        manual = asyncio.create_task(authority.run_manual(
            MANUAL_TRANSPORT_DIMENSIONS, source="dashboard",
            reason="manual_play", operation=manual_write,
        ))
        for _ in range(10):
            await asyncio.sleep(0)
        assert not auto.done()
        assert not manual_entered.is_set()
        assert events == []
    finally:
        release.set()
        results = await asyncio.gather(
            auto, *([manual] if manual is not None else []),
            return_exceptions=True,
        )
    assert isinstance(results[0], asyncio.CancelledError)
    assert results[1] is True
    assert events == ["settled", "manual"]


@pytest.mark.asyncio
async def test_manual_volume_between_real_authority_ramp_steps_preserves_queue(
    monkeypatch,
) -> None:
    """Exercise actual token invalidation, rather than a mocked guard result."""
    settings = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )
    queue_lease = await authority.acquire(
        owner="music_mapper", purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
    )
    assert queue_lease is not None
    token = await authority.capture_opportunistic((VOLUME,))
    assert token is not None
    between_steps = asyncio.Event()
    continue_ramp = asyncio.Event()
    writes: list[int] = []

    class Device:
        volume = 20

    sonos = SonosService()
    sonos._connected = True
    sonos._device = Device()

    async def set_volume(value: int) -> bool:
        result = await SonosService.set_volume(sonos, value)
        writes.append(sonos._device.volume)
        return result

    monkeypatch.setattr(sonos, "set_volume", set_volume)
    service = ModeVolumeService(sonos, None, audio_ownership=authority)
    service._request_generation = 1
    real_sleep = asyncio.sleep

    async def step_barrier(seconds: float) -> None:
        if seconds == 123:
            between_steps.set()
            await continue_ramp.wait()
        else:
            await real_sleep(seconds)

    monkeypatch.setattr(
        "backend.services.mode_volume_service.asyncio.sleep", step_barrier,
    )
    ramp = asyncio.create_task(service._run_owned_ramp(
        mode="gaming", generation=1, token=token, current=20,
        target=26, steps=3, interval=123,
    ))
    try:
        await asyncio.wait_for(between_steps.wait(), timeout=2)
        assert writes == [22]
        assert await authority.run_manual(
            MANUAL_VOLUME_DIMENSIONS, source="dashboard",
            reason="manual_volume", operation=lambda: sonos.set_volume(7),
        )
    finally:
        continue_ramp.set()
        completed = await ramp
    assert completed is False
    assert writes == [22, 7]
    assert sonos._device.volume == 7
    assert await authority.is_valid(
        queue_lease["lease_id"], (QUEUE_SOURCE, TRANSPORT),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("intervention", ["manual", "stronger_owner", "newer_mode", "none"])
async def test_mode_setup_keeps_original_volume_epoch(monkeypatch, intervention) -> None:
    """A status-read barrier exposes invalidation before the first ramp write."""
    settings = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    writes: list[int] = []

    class Device:
        _volume = 20
        mute = False

        @property
        def volume(self):
            return self._volume

        @volume.setter
        def volume(self, value):
            self._volume = value
            writes.append(value)

        def get_current_transport_info(self):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(timeout=5):
                raise AssertionError("test did not release status read")
            return {"current_transport_state": "PLAYING"}

        def get_current_track_info(self):
            return {}

    class Automation:
        def _get_time_period(self):
            return "day"

        def is_dnd_active(self):
            return False

    async def curves(_key):
        return {"gaming": {"day": 25, "fade_duration_s": 1}}

    monkeypatch.setattr("backend.services.mode_volume_service.load_setting", curves)
    sonos = SonosService()
    sonos._connected = True
    sonos._device = Device()
    service = ModeVolumeService(sonos, Automation(), audio_ownership=authority)
    ramps = []
    original_ramp = service._run_owned_ramp

    async def tracked_ramp(**kwargs):
        ramps.append(asyncio.current_task())
        return await original_ramp(**kwargs)

    monkeypatch.setattr(service, "_run_owned_ramp", tracked_ramp)
    request = asyncio.create_task(service.on_mode_change("gaming"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        if intervention == "manual":
            assert await authority.run_manual(
                MANUAL_VOLUME_DIMENSIONS, source="dashboard",
                reason="manual_volume", operation=lambda: sonos.set_volume(7),
            )
        elif intervention == "stronger_owner":
            lease = await authority.acquire(
                owner="tts", purpose="speech", dimensions=(VOLUME,),
            )
            assert lease is not None
            assert await authority.release(lease["lease_id"])
        elif intervention == "newer_mode":
            # A newer request while disconnected supersedes without another read/ramp.
            sonos._connected = False
            await service.on_mode_change("idle")
            sonos._connected = True
    finally:
        release.set()
        await request
        await asyncio.sleep(0)
        if ramps:
            await asyncio.gather(*ramps)
    expected = [25] if intervention == "none" else [7] if intervention == "manual" else []
    assert writes == expected
    assert sonos._device.volume == (25 if intervention == "none" else 7 if intervention == "manual" else 20)
    assert bool(ramps) is (intervention == "none")
