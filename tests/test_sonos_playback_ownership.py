from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock

import pytest

from backend.config import settings
from backend.services.sonos_service import SonosService


def evidence() -> dict:
    return {
        "queue_uid": "RINCON_TEST",
        "queue_update_id": "1",
        "queue_size": 0,
        "queue_first_item_hash": None,
        "play_mode": "NORMAL",
        "transport_state": "STOPPED",
        "current_uri": "",
        "queue_track": 0,
        "queue_track_uri": "",
        "volume": 15,
        "mute": False,
    }


def service_with(current: dict) -> SonosService:
    service = SonosService.__new__(SonosService)
    service._connected = True
    service._device = MagicMock()
    service._playback_ownership_evidence_sync = MagicMock(
        return_value=dict(current)
    )

    async def passthrough(fn, *args, **kwargs):
        kwargs.pop("call_timeout", None)
        return fn(*args, **kwargs)

    service._safe_mutation_call = passthrough
    return service


@pytest.mark.asyncio
async def test_conditional_play_uri_mutates_only_exact_preflight() -> None:
    expected = evidence()
    service = service_with(expected)
    service._play_uri_sync = MagicMock()
    uri = f"http://{settings.LOCAL_IP}:8000/static/ambient/rain.mp3"

    played = await service.play_uri_if_unchanged(
        expected,
        uri,
        volume=25,
        force_radio=False,
    )

    assert played is True
    service._play_uri_sync.assert_called_once_with(uri, 25, None, False)


@pytest.mark.asyncio
async def test_conditional_play_uri_refuses_changed_preflight() -> None:
    expected = evidence()
    changed = dict(expected, current_uri="x-sonos-spotify:manual")
    service = service_with(changed)
    service._play_uri_sync = MagicMock()
    uri = f"http://{settings.LOCAL_IP}:8000/static/ambient/rain.mp3"

    played = await service.play_uri_if_unchanged(expected, uri, volume=25)

    assert played is False
    service._play_uri_sync.assert_not_called()


@pytest.mark.asyncio
async def test_conditional_pause_ignores_volume_but_requires_same_source() -> None:
    expected = dict(evidence(), transport_state="PLAYING", volume=25)
    current = dict(expected, volume=11)
    service = service_with(current)

    paused = await service.pause_if_playback_unchanged(expected)

    assert paused is True
    service._device.pause.assert_called_once_with()


@pytest.mark.asyncio
async def test_conditional_pause_refuses_source_takeover() -> None:
    expected = dict(evidence(), transport_state="PLAYING")
    changed = dict(expected, current_uri="x-sonos-spotify:manual")
    service = service_with(changed)

    paused = await service.pause_if_playback_unchanged(expected)

    assert paused is False
    service._device.pause.assert_not_called()


@pytest.mark.asyncio
async def test_conditional_volume_refuses_manual_volume_change() -> None:
    expected = dict(evidence(), transport_state="PLAYING", volume=25)
    current = dict(expected, volume=14)
    service = service_with(current)
    service._device.volume = 14

    wrote = await service.set_volume_if_playback_unchanged(expected, 30)

    assert wrote is False
    assert service._device.volume == 14


@pytest.mark.asyncio
async def test_source_conditional_play_ignores_rendering_drift() -> None:
    expected = evidence()
    current = dict(expected, volume=7, mute=True)
    service = service_with(current)
    service._play_uri_sync = MagicMock()
    uri = f"http://{settings.LOCAL_IP}:8000/static/ambient/rain.mp3"

    played = await service.play_uri_if_source_unchanged(
        expected,
        uri,
        force_radio=False,
    )

    assert played is True
    service._play_uri_sync.assert_called_once_with(uri, None, None, False)


@pytest.mark.asyncio
async def test_source_conditional_play_refuses_source_takeover() -> None:
    expected = evidence()
    changed = dict(
        expected,
        current_uri="x-sonos-spotify:manual",
        volume=7,
        mute=True,
    )
    service = service_with(changed)
    service._play_uri_sync = MagicMock()
    uri = f"http://{settings.LOCAL_IP}:8000/static/ambient/rain.mp3"

    played = await service.play_uri_if_source_unchanged(expected, uri)

    assert played is False
    service._play_uri_sync.assert_not_called()


def test_conditional_pause_checks_guard_after_waiting_for_mutation_fence() -> None:
    expected = dict(evidence(), transport_state="PLAYING")
    service = service_with(expected)
    fence = threading.Lock()
    started = threading.Event()
    result: dict[str, bool] = {}
    allowed = True

    def still_allowed() -> bool:
        return allowed

    def worker() -> None:
        started.set()
        result["paused"] = service._pause_if_playback_unchanged_sync(
            expected,
            still_allowed,
            fence,
        )

    fence.acquire()
    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(timeout=1)
    assert thread.is_alive()

    allowed = False
    fence.release()
    thread.join(timeout=1)

    assert thread.is_alive() is False
    assert result["paused"] is False
    service._device.pause.assert_not_called()



@pytest.mark.asyncio
async def test_timed_playback_evidence_reads_reuse_one_settled_worker() -> None:
    service = SonosService()
    service._connected = True
    service._device = MagicMock()
    service._breaker.call_timeout = 1.0

    started = threading.Event()
    release = threading.Event()
    calls = 0

    def blocking_read() -> dict:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2.0)
        return evidence()

    service._playback_ownership_evidence_sync = blocking_read

    first = await service.get_playback_ownership_evidence(call_timeout=0.05)
    assert first is None
    assert started.is_set()
    assert calls == 1

    second = await service.get_playback_ownership_evidence(call_timeout=0.05)
    assert second is None
    assert calls == 1

    in_flight = service._playback_evidence_read_task
    assert in_flight is not None
    assert in_flight.done() is False

    release.set()
    settled = await asyncio.wait_for(asyncio.shield(in_flight), timeout=1.0)
    assert settled == evidence()
    await asyncio.sleep(0)

    fresh = await service.get_playback_ownership_evidence(call_timeout=0.2)
    assert fresh == evidence()
    assert calls == 2



def test_conditional_pause_treats_already_stopped_701_as_success() -> None:
    expected = evidence()
    service = service_with(expected)
    service._device.pause.side_effect = Exception(
        "UPnP Error 701 received: Transition not available"
    )

    paused = service._pause_if_playback_unchanged_sync(expected)

    assert paused is True
    service._device.pause.assert_called_once_with()
