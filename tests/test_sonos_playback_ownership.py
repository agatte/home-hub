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


def _tts_snapshot(*, volume: int = 20, state: str = "PLAYING"):
    snapshot = MagicMock()
    snapshot.is_coordinator = True
    snapshot.is_playing_queue = False
    snapshot.is_playing_cloud_queue = False
    snapshot.playlist_position = None
    snapshot.track_position = ""
    snapshot.play_mode = "NORMAL"
    snapshot.media_metadata = ""
    snapshot.volume = volume
    snapshot.transport_state = state
    return snapshot


def test_tts_restore_exact_clip_restores_source_transport_and_volume() -> None:
    preflight = dict(evidence(), transport_state="PLAYING", volume=20)
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    current = dict(
        preflight,
        current_uri=tts_uri,
        transport_state="PLAYING",
        volume=60,
        position="0:00:01",
        duration="0:00:03",
    )
    service = service_with(current)
    service._device.volume = 60
    service._playback_ownership_evidence_sync = MagicMock(side_effect=[
        current,
        dict(preflight, transport_state="PAUSED_PLAYBACK", volume=60),
        dict(preflight, transport_state="PLAYING", volume=60),
    ])
    snapshot = _tts_snapshot(volume=20, state="PLAYING")

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, True,
    )

    assert result["source_transport_restored"] is True
    assert result["source_transport_reason"] == "restored_after_tts_active"
    assert result["volume_restored"] is True
    snapshot._restore_coordinator.assert_not_called()
    assert service._device.volume == 20
    service._device.play.assert_called_once_with()


def test_tts_restore_finite_direct_source_resumes_captured_position() -> None:
    prior_uri = f"http://{settings.LOCAL_IP}:8000/static/ambient/rain.mp3"
    preflight = dict(
        evidence(),
        transport_state="PLAYING",
        current_uri=prior_uri,
        queue_track_uri=prior_uri,
        position="0:00:17",
        duration="0:10:00",
        volume=20,
    )
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    current = dict(
        preflight,
        current_uri=tts_uri,
        queue_track_uri=tts_uri,
        transport_state="PLAYING",
        position="0:00:01",
        duration="0:00:03",
        volume=60,
    )
    selected = dict(
        preflight,
        transport_state="STOPPED",
        position="0:00:00",
        volume=60,
    )
    prepared = dict(
        preflight,
        transport_state="STOPPED",
        volume=60,
    )
    restored = dict(
        preflight,
        transport_state="PLAYING",
        volume=60,
    )
    service = service_with(current)
    service._playback_ownership_evidence_sync = MagicMock(
        side_effect=[current, selected, prepared, restored]
    )
    snapshot = _tts_snapshot(volume=20, state="PLAYING")

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, False,
    )

    assert result["source_transport_restored"] is True
    service._device.avTransport.Seek.assert_called_once_with([
        ("InstanceID", 0),
        ("Unit", "REL_TIME"),
        ("Target", "0:00:17"),
    ])
    service._device.play.assert_called_once_with()


def test_tts_restore_indefinite_direct_stream_never_seeks() -> None:
    prior_uri = "https://example.invalid/live.mp3"
    preflight = dict(
        evidence(),
        transport_state="PLAYING",
        current_uri=prior_uri,
        queue_track_uri=prior_uri,
        position="0:00:17",
        duration="NOT_IMPLEMENTED",
        volume=20,
    )
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    current = dict(
        preflight,
        current_uri=tts_uri,
        queue_track_uri=tts_uri,
        transport_state="PLAYING",
        position="0:00:01",
        duration="0:00:03",
        volume=60,
    )
    prepared = dict(preflight, transport_state="STOPPED", volume=60)
    restored = dict(preflight, transport_state="PLAYING", volume=60)
    service = service_with(current)
    service._playback_ownership_evidence_sync = MagicMock(
        side_effect=[current, prepared, restored]
    )
    snapshot = _tts_snapshot(volume=20, state="PLAYING")

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, False,
    )

    assert result["source_transport_restored"] is True
    service._device.avTransport.Seek.assert_not_called()
    service._device.play.assert_called_once_with()


def test_tts_restore_source_takeover_preserves_new_source_but_restores_volume() -> None:
    preflight = dict(evidence(), transport_state="PLAYING", volume=20)
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    current = dict(
        preflight,
        current_uri="x-sonos-spotify:manual",
        transport_state="PLAYING",
        volume=60,
    )
    service = service_with(current)
    service._device.volume = 60
    snapshot = _tts_snapshot(volume=20, state="PLAYING")

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, True,
    )

    assert result["source_transport_restored"] is False
    assert result["source_transport_reason"] == "source_changed"
    assert result["volume_restored"] is True
    snapshot._restore_coordinator.assert_not_called()
    assert service._device.volume == 20
    service._device.play.assert_not_called()


def test_tts_restore_volume_takeover_preserves_new_volume_but_restores_source() -> None:
    preflight = dict(evidence(), transport_state="PLAYING", volume=20)
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    current = dict(
        preflight,
        current_uri=tts_uri,
        transport_state="PLAYING",
        volume=33,
    )
    service = service_with(current)
    service._device.volume = 33
    service._playback_ownership_evidence_sync = MagicMock(side_effect=[
        current,
        dict(preflight, transport_state="PAUSED_PLAYBACK", volume=33),
        dict(preflight, transport_state="PLAYING", volume=33),
    ])
    snapshot = _tts_snapshot(volume=20, state="PLAYING")

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, True,
    )

    assert result["source_transport_restored"] is True
    assert result["volume_restored"] is False
    assert result["volume_reason"] == "volume_changed"
    snapshot._restore_coordinator.assert_not_called()
    assert service._device.volume == 33
    service._device.play.assert_called_once_with()


def test_tts_restore_refuses_paused_clip_as_manual_transport_takeover() -> None:
    preflight = dict(evidence(), transport_state="PLAYING", volume=20)
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    current = dict(
        preflight,
        current_uri=tts_uri,
        transport_state="PAUSED_PLAYBACK",
        volume=60,
    )
    service = service_with(current)
    snapshot = _tts_snapshot(volume=20, state="PLAYING")

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, False,
    )

    assert result["source_transport_restored"] is False
    assert result["source_transport_reason"] == "transport_paused"
    snapshot._restore_coordinator.assert_not_called()
    service._device.play.assert_not_called()


def test_tts_restore_accepts_proven_natural_clip_end_but_not_early_stop() -> None:
    preflight = dict(evidence(), transport_state="PLAYING", volume=20)
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    snapshot = _tts_snapshot(volume=20, state="PLAYING")

    ended = dict(
        preflight,
        current_uri=tts_uri,
        transport_state="STOPPED",
        volume=60,
        position="0:00:03",
        duration="0:00:03",
    )
    service = service_with(ended)
    service._playback_ownership_evidence_sync = MagicMock(side_effect=[
        ended,
        dict(preflight, transport_state="PAUSED_PLAYBACK", volume=60),
        dict(preflight, transport_state="PLAYING", volume=60),
    ])
    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, False,
    )
    assert result["source_transport_restored"] is True
    assert result["source_transport_reason"] == "restored_after_tts_natural_end"

    early = dict(
        ended,
        position="0:00:01",
        duration="0:00:10",
    )
    service = service_with(early)
    snapshot = _tts_snapshot(volume=20, state="PLAYING")
    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, False,
    )
    assert result["source_transport_restored"] is False
    assert result["source_transport_reason"] == "transport_stopped_early"
    snapshot._restore_coordinator.assert_not_called()


def test_tts_restore_rebases_queue_update_after_restoring_shuffle() -> None:
    queue_uri = "x-rincon-queue:RINCON_TEST#0"
    track_uri = "x-sonos-http:track1"
    preflight = dict(
        evidence(),
        queue_update_id="24",
        queue_size=100,
        queue_first_item_hash="abc",
        play_mode="SHUFFLE",
        transport_state="STOPPED",
        current_uri=queue_uri,
        queue_track=1,
        queue_track_uri=track_uri,
        position="0:00:00",
        duration="0:02:37",
        volume=0,
    )
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    current = dict(
        preflight,
        current_uri=tts_uri,
        queue_track_uri=tts_uri,
        play_mode="NORMAL",
        transport_state="PLAYING",
        position="0:00:02",
        duration="0:00:04",
        volume=24,
    )
    selected = dict(
        preflight,
        play_mode="NORMAL",
        transport_state="STOPPED",
        volume=24,
    )
    mode_restored = dict(
        selected,
        queue_update_id="25",
        play_mode="SHUFFLE",
    )
    service = service_with(current)
    service._playback_ownership_evidence_sync = MagicMock(side_effect=[
        current,
        selected,
        selected,
        mode_restored,
        mode_restored,
        mode_restored,
    ])
    snapshot = _tts_snapshot(volume=0, state="STOPPED")
    snapshot.is_playing_queue = True
    snapshot.playlist_position = 1
    snapshot.track_position = ""
    snapshot.play_mode = "SHUFFLE"

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 24, True, False,
    )

    assert result["source_transport_restored"] is True
    assert result["source_transport_reason"] == "restored_after_tts_active"
    assert preflight["queue_update_id"] == "25"
    assert service._device.play_mode == "SHUFFLE"
    service._device.stop.assert_not_called()


def test_tts_restore_source_less_idle_to_neutral_empty_queue() -> None:
    preflight = dict(
        evidence(),
        transport_state="STOPPED",
        current_uri="",
        queue_size=0,
        volume=20,
    )
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    ended = dict(
        preflight,
        current_uri=tts_uri,
        transport_state="STOPPED",
        volume=60,
        position="0:00:03",
        duration="0:00:03",
    )
    neutral = dict(
        preflight,
        current_uri="x-rincon-queue:RINCON_TEST#0",
        transport_state="STOPPED",
        volume=60,
    )
    service = service_with(ended)
    service._playback_ownership_evidence_sync = MagicMock(
        side_effect=[ended, neutral, neutral]
    )
    snapshot = _tts_snapshot(volume=20, state="STOPPED")

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, False,
    )

    assert result["source_transport_restored"] is True
    assert result["source_transport_reason"] == "restored_after_tts_natural_end"
    service._device.avTransport.SetAVTransportURI.assert_called_once_with([
        ("InstanceID", 0),
        ("CurrentURI", "x-rincon-queue:RINCON_TEST#0"),
        ("CurrentURIMetaData", ""),
    ])
    service._device.pause.assert_not_called()
    service._device.play.assert_not_called()
    service._device.stop.assert_not_called()


def test_tts_restore_refuses_unrestorable_cloud_queue() -> None:
    preflight = dict(evidence(), transport_state="PLAYING", volume=20)
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    current = dict(
        preflight,
        current_uri=tts_uri,
        transport_state="PLAYING",
        volume=60,
    )
    service = service_with(current)
    snapshot = _tts_snapshot(volume=20, state="PLAYING")
    snapshot.is_playing_cloud_queue = True

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, False,
    )

    assert result["source_transport_restored"] is False
    assert result["source_transport_reason"] == "unrestorable_cloud_queue"
    snapshot._restore_coordinator.assert_not_called()
    service._device.play.assert_not_called()


def test_tts_restore_prepare_mismatch_refuses_final_resume() -> None:
    preflight = dict(evidence(), transport_state="PLAYING", volume=20)
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    current = dict(
        preflight,
        current_uri=tts_uri,
        transport_state="PLAYING",
        volume=60,
    )
    takeover = dict(
        preflight,
        current_uri="x-sonos-spotify:manual",
        transport_state="PLAYING",
        volume=60,
    )
    service = service_with(current)
    service._playback_ownership_evidence_sync = MagicMock(
        side_effect=[current, takeover]
    )
    snapshot = _tts_snapshot(volume=20, state="PLAYING")

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, False,
    )

    assert result["source_transport_restored"] is False
    assert result["source_transport_reason"] == "restore_prepare_mismatch"
    snapshot._restore_coordinator.assert_not_called()
    service._device.pause.assert_not_called()
    service._device.play.assert_not_called()


def test_failed_tts_start_with_stopped_tts_uri_rolls_back_owned_residue() -> None:
    preflight = dict(evidence(), transport_state="PLAYING", volume=20)
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    residue = dict(
        preflight,
        current_uri=tts_uri,
        transport_state="STOPPED",
        volume=60,
        position="0:00:00",
        duration="0:00:03",
    )
    service = service_with(residue)
    service._device.volume = 60
    service._playback_ownership_evidence_sync = MagicMock(side_effect=[
        residue,
        dict(preflight, transport_state="PAUSED_PLAYBACK", volume=60),
        dict(preflight, transport_state="PLAYING", volume=60),
    ])
    snapshot = _tts_snapshot(volume=20, state="PLAYING")

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, True, play_failed=True,
    )

    assert result["source_transport_restored"] is True
    assert result["source_transport_reason"] == (
        "restored_after_failed_play_tts_residue"
    )
    assert result["volume_restored"] is True
    snapshot._restore_coordinator.assert_not_called()
    service._device.play.assert_called_once_with()
    assert service._device.volume == 20


def test_failed_tts_start_restores_queue_play_mode_only_drift() -> None:
    preflight = dict(
        evidence(),
        transport_state="PLAYING",
        play_mode="SHUFFLE_NOREPEAT",
        volume=20,
        current_uri="x-rincon-queue:RINCON_TEST#0",
        queue_track=2,
        queue_track_uri="x-sonos-http:track",
    )
    drift = dict(preflight, play_mode="NORMAL", volume=60)
    service = service_with(drift)
    service._device.volume = 60
    service._playback_ownership_evidence_sync = MagicMock(side_effect=[
        drift,
        drift,
        drift,
        dict(preflight, transport_state="STOPPED", volume=60),
        dict(preflight, transport_state="STOPPED", volume=60),
        dict(preflight, transport_state="PLAYING", volume=60),
    ])
    snapshot = _tts_snapshot(volume=20, state="PLAYING")
    snapshot.is_playing_queue = True

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot,
        preflight,
        f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3",
        60,
        True,
        True,
        play_failed=True,
    )

    assert result["source_transport_restored"] is True
    assert result["source_transport_reason"] == (
        "restored_after_failed_play_play_mode_only"
    )
    assert result["volume_restored"] is True
    snapshot._restore_coordinator.assert_not_called()


def test_failed_tts_start_does_not_rollback_different_external_source() -> None:
    preflight = dict(evidence(), transport_state="PLAYING", volume=20)
    tts_uri = f"http://{settings.LOCAL_IP}:8000/static/tts/test.mp3"
    external = dict(
        preflight,
        current_uri="x-sonos-spotify:manual",
        transport_state="PLAYING",
        volume=60,
    )
    service = service_with(external)
    snapshot = _tts_snapshot(volume=20, state="PLAYING")

    result = service._restore_tts_snapshot_if_unchanged_sync(
        snapshot, preflight, tts_uri, 60, True, False, play_failed=True,
    )

    assert result["source_transport_restored"] is False
    assert result["source_transport_reason"] == "source_changed"
    snapshot._restore_coordinator.assert_not_called()
    service._device.play.assert_not_called()
