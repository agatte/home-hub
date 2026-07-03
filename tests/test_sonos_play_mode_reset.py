"""Pin the play_mode handling that fixes the TTS-repeat bug.

``_shuffle_and_play`` sets the player to ``SHUFFLE`` (= shuffle +
repeat-all per SoCo's enum) and play_mode is a PERSISTENT player
setting. A finite file later played via ``play_uri`` (TTS "good
night", iTunes previews) would loop forever until manually paused.

Fix under test:
1. ``play_uri`` with ``force_radio=False`` forces ``NORMAL`` first.
2. Duck-and-resume goes through SoCo's ``soco.snapshot.Snapshot``:
   capture is unconditional (even idle/stopped), and restore rebuilds
   the transport — queue position + seek + play_mode for queue
   playback, URI + metadata for streams (never re-applying repeat to a
   bare finite URI), and parks a still-playing TTS clip when the
   speaker was idle before.
"""
from unittest.mock import MagicMock

import pytest

from backend.config import settings
from backend.services.sonos_service import SonosService


class FakeDevice:
    """Minimal SoCo stand-in tracking play_mode writes."""

    def __init__(self, play_mode: str = "SHUFFLE") -> None:
        self.play_mode = play_mode
        self.volume = 30
        self.play_uri = MagicMock()
        self.play_from_queue = MagicMock()


class FakeSnapshotDevice:
    """SoCo stand-in rich enough for soco.snapshot.Snapshot round-trips."""

    def __init__(
        self,
        media_uri: str,
        media_meta: str = "",
        transport_state: str = "PLAYING",
        play_mode: str = "SHUFFLE",
        playlist_position: str = "3",
        position: str = "0:01:00",
    ) -> None:
        self.is_coordinator = True
        self.volume = 30
        self.mute = False
        self.bass = 0
        self.treble = 0
        self.loudness = True
        self.fixed_volume = False
        self.play_mode = play_mode
        self.cross_fade = False
        # Mutable so tests can simulate the TTS clip playing at restore time.
        self.transport_state = transport_state
        self._track = {"playlist_position": playlist_position, "position": position}
        self.avTransport = MagicMock()
        self.avTransport.GetMediaInfo.return_value = {
            "CurrentURI": media_uri,
            "CurrentURIMetaData": media_meta,
        }
        for m in ("pause", "play", "stop", "seek", "play_from_queue", "play_uri"):
            setattr(self, m, MagicMock())

    def get_current_track_info(self) -> dict:
        return dict(self._track)

    def get_current_transport_info(self) -> dict:
        return {"current_transport_state": self.transport_state}


def _service(device) -> SonosService:
    svc = SonosService(sonos_ip="192.0.2.1")
    svc._device = device
    svc._connected = True
    return svc


@pytest.fixture
def tts_url() -> str:
    return f"http://{settings.LOCAL_IP}:8000/static/tts/night.mp3"


@pytest.mark.asyncio
async def test_play_uri_resets_shuffle_to_normal(tts_url: str) -> None:
    """Finite file + lingering SHUFFLE → play_mode forced to NORMAL."""
    device = FakeDevice(play_mode="SHUFFLE")
    svc = _service(device)

    assert await svc.play_uri(tts_url) is True

    assert device.play_mode == "NORMAL"
    device.play_uri.assert_called_once()


@pytest.mark.asyncio
async def test_play_uri_radio_does_not_touch_play_mode(tts_url: str) -> None:
    """force_radio=True (continuous stream) leaves play_mode alone."""
    device = FakeDevice(play_mode="SHUFFLE")
    svc = _service(device)

    assert await svc.play_uri(tts_url, force_radio=True) is True

    assert device.play_mode == "SHUFFLE"


def _simulate_tts(device: FakeSnapshotDevice) -> None:
    """Mutate the fake to the state a just-played TTS clip leaves behind."""
    device.play_mode = "NORMAL"  # play_uri forced it
    device.volume = 55           # TTS bumped it
    device.transport_state = "PLAYING"  # clip still on the transport


@pytest.mark.asyncio
async def test_restore_resumes_queue_with_saved_mode_and_position() -> None:
    """Queue snapshot → play_from_queue at saved index + seek + SHUFFLE back."""
    device = FakeSnapshotDevice(
        media_uri="x-rincon-queue:RINCON_FAKE#0",
        transport_state="PLAYING",
        play_mode="SHUFFLE",
        playlist_position="3",
        position="0:01:00",
    )
    svc = _service(device)

    snap = await svc.get_current_playback_snapshot()
    assert snap is not None
    _simulate_tts(device)

    await svc.restore_playback(snap)

    device.pause.assert_called_once()
    device.play_from_queue.assert_called_once_with(2, False)  # 1-based → 0-based
    device.seek.assert_called_once_with("0:01:00")
    assert device.play_mode == "SHUFFLE"
    assert device.volume == 30
    device.play.assert_called_once()  # prior state was PLAYING
    device.play_uri.assert_not_called()


@pytest.mark.asyncio
async def test_restore_stream_never_reapplies_repeat() -> None:
    """Stream snapshot replays URI + metadata but never touches play_mode —
    repeat-all on a bare finite URI is exactly the TTS-loop bug."""
    uri = "x-rincon-mp3radio://example-stream/radio"
    meta = "<DIDL-Lite>radio</DIDL-Lite>"
    device = FakeSnapshotDevice(
        media_uri=uri,
        media_meta=meta,
        transport_state="PLAYING",
        play_mode="NORMAL",
    )
    svc = _service(device)

    snap = await svc.get_current_playback_snapshot()
    assert snap is not None
    _simulate_tts(device)

    await svc.restore_playback(snap)

    device.play_uri.assert_called_once_with(uri, meta, start=False)
    assert device.play_mode == "NORMAL"
    device.play_from_queue.assert_not_called()
    assert device.volume == 30


@pytest.mark.asyncio
async def test_tts_while_idle_restore_parks_clip() -> None:
    """Speaker was STOPPED before TTS → restore pauses + stops the clip
    instead of leaving the transport sitting on it (the bedtime gap)."""
    device = FakeSnapshotDevice(
        media_uri="",
        transport_state="STOPPED",
        play_mode="NORMAL",
    )
    svc = _service(device)

    snap = await svc.get_current_playback_snapshot()
    assert snap is not None
    _simulate_tts(device)  # clip is PLAYING at restore time

    await svc.restore_playback(snap)

    device.pause.assert_called_once()   # stops the audible clip first
    device.stop.assert_called_once()    # prior state STOPPED → park transport
    device.play.assert_not_called()
    assert device.volume == 30


@pytest.mark.asyncio
async def test_snapshot_capture_failure_returns_none() -> None:
    """UPnP error during capture → None (TTS must still speak)."""
    device = FakeSnapshotDevice(media_uri="x-rincon-queue:RINCON_FAKE#0")
    device.avTransport.GetMediaInfo.side_effect = RuntimeError("UPnP 500")
    svc = _service(device)

    assert await svc.get_current_playback_snapshot() is None


@pytest.mark.asyncio
async def test_snapshot_capture_disconnected_returns_none() -> None:
    """Not connected → None without touching the device."""
    svc = SonosService(sonos_ip="192.0.2.1")
    svc._device = None
    svc._connected = False

    assert await svc.get_current_playback_snapshot() is None
