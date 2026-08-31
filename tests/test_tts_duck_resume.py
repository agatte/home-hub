"""Pin TTSService duck-and-resume and serialization semantics.

If play_uri fails mid-bump (volume already raised, URL fetch failed),
the speaker MUST be restored to its prior volume + playback state.
Without try/finally a failed TTS leaves Sonos parked at TTS volume
indefinitely.
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.tts_service import TTSService

_REAL_SLEEP = asyncio.sleep


@pytest.fixture
def immediate_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid real playback and cleanup delays in TTSService tests."""
    async def _immediate_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("backend.services.tts_service.asyncio.sleep", _immediate_sleep)


@pytest.mark.asyncio
async def test_speak_restores_volume_when_play_uri_fails(tmp_path: Path) -> None:
    """play_uri returns False → finally still resets volume + playback."""
    sonos = AsyncMock()
    sonos.connected = True
    sonos.get_current_playback_snapshot = AsyncMock(
        return_value=MagicMock(name="snapshot")
    )
    sonos.get_status = AsyncMock(return_value={"volume": 25, "state": "PLAYING"})
    sonos.play_uri = AsyncMock(return_value=False)  # Simulate failure
    sonos.set_volume = AsyncMock(return_value=True)
    sonos.restore_playback = AsyncMock(return_value=None)

    tts = TTSService(
        sonos_service=sonos,
        static_dir=tmp_path,
        local_ip="127.0.0.1",
        default_volume=80,
    )
    # Stub _generate_audio so we don't hit edge-tts/internet.
    tts._generate_audio = AsyncMock(return_value=tmp_path / "fake.mp3")

    result = await tts.speak("hello world", volume=60)

    assert result is False
    # Volume MUST be restored to original even on failure
    sonos.set_volume.assert_called_with(25)
    # Snapshot was non-None → restore_playback should have fired
    sonos.restore_playback.assert_awaited_once()


@pytest.mark.asyncio
async def test_speak_restores_volume_when_play_uri_raises(tmp_path: Path) -> None:
    """play_uri raises → finally still resets volume."""
    sonos = AsyncMock()
    sonos.connected = True
    sonos.get_current_playback_snapshot = AsyncMock(
        return_value=MagicMock(name="snapshot")
    )
    sonos.get_status = AsyncMock(return_value={"volume": 18, "state": "PLAYING"})
    sonos.play_uri = AsyncMock(side_effect=RuntimeError("speaker offline"))
    sonos.set_volume = AsyncMock(return_value=True)
    sonos.restore_playback = AsyncMock(return_value=None)

    tts = TTSService(
        sonos_service=sonos,
        static_dir=tmp_path,
        local_ip="127.0.0.1",
        default_volume=80,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "fake.mp3")

    result = await tts.speak("hello", volume=60)

    assert result is False
    sonos.set_volume.assert_called_with(18)


@pytest.mark.asyncio
async def test_speak_succeeds_and_still_restores(tmp_path: Path) -> None:
    """Happy path: play_uri succeeds, finally still runs cleanly."""
    sonos = AsyncMock()
    sonos.connected = True
    sonos.get_current_playback_snapshot = AsyncMock(
        return_value=MagicMock(name="snapshot")
    )
    sonos.get_status = AsyncMock(return_value={"volume": 22, "state": "PLAYING"})
    sonos.play_uri = AsyncMock(return_value=True)
    sonos.set_volume = AsyncMock(return_value=True)
    sonos.restore_playback = AsyncMock(return_value=None)

    tts = TTSService(
        sonos_service=sonos,
        static_dir=tmp_path,
        local_ip="127.0.0.1",
        default_volume=80,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "fake.mp3")

    result = await tts.speak("hello", volume=60)

    assert result is True
    sonos.set_volume.assert_called_with(22)
    sonos.restore_playback.assert_awaited_once()


@pytest.mark.asyncio
async def test_speak_restores_even_when_idle(tmp_path: Path) -> None:
    """Snapshot is captured even when the speaker is idle/paused —
    restore_playback must fire so the TTS clip gets parked and the
    transport returns to its prior state (the bedtime-TTS gap)."""
    sonos = AsyncMock()
    sonos.connected = True
    sonos.get_current_playback_snapshot = AsyncMock(
        return_value=MagicMock(name="snapshot")
    )
    sonos.get_status = AsyncMock(return_value={"volume": 30, "state": "PAUSED_PLAYBACK"})
    sonos.play_uri = AsyncMock(return_value=True)
    sonos.set_volume = AsyncMock(return_value=True)
    sonos.restore_playback = AsyncMock(return_value=None)

    tts = TTSService(
        sonos_service=sonos,
        static_dir=tmp_path,
        local_ip="127.0.0.1",
        default_volume=80,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "fake.mp3")

    await tts.speak("hello", volume=60)

    sonos.set_volume.assert_called_with(30)
    sonos.restore_playback.assert_awaited_once()


@pytest.mark.asyncio
async def test_speak_skips_restore_when_snapshot_capture_fails(tmp_path: Path) -> None:
    """Snapshot capture failed (breaker open / UPnP error → None) →
    TTS still speaks, no restore_playback, volume still reset."""
    sonos = AsyncMock()
    sonos.connected = True
    sonos.get_current_playback_snapshot = AsyncMock(return_value=None)
    sonos.get_status = AsyncMock(return_value={"volume": 30, "state": "PAUSED_PLAYBACK"})
    sonos.play_uri = AsyncMock(return_value=True)
    sonos.set_volume = AsyncMock(return_value=True)
    sonos.restore_playback = AsyncMock(return_value=None)

    tts = TTSService(
        sonos_service=sonos,
        static_dir=tmp_path,
        local_ip="127.0.0.1",
        default_volume=80,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "fake.mp3")

    result = await tts.speak("hello", volume=60)

    assert result is True  # capture failure must not block speech
    sonos.play_uri.assert_awaited_once()
    sonos.set_volume.assert_called_with(30)
    sonos.restore_playback.assert_not_called()


@pytest.mark.asyncio
async def test_overlapping_speech_restores_before_next_snapshot(
    tmp_path: Path, immediate_sleep: None
) -> None:
    """A queued request cannot snapshot the currently-playing TTS clip."""
    sonos = AsyncMock()
    sonos.connected = True
    first_snapshot = MagicMock(name="prior_music")
    second_snapshot = MagicMock(name="restored_music")
    events: list[str] = []
    first_playing = asyncio.Event()
    release_first = asyncio.Event()

    async def snapshot() -> MagicMock:
        snapshot_number = 1 + events.count("snapshot")
        events.append("snapshot")
        return first_snapshot if snapshot_number == 1 else second_snapshot

    async def play_uri(*_args, **_kwargs) -> bool:
        play_number = 1 + events.count("play")
        events.append("play")
        if play_number == 1:
            first_playing.set()
            await release_first.wait()
        return True

    async def restore_playback(snapshot: MagicMock) -> None:
        events.append("restore_first" if snapshot is first_snapshot else "restore_second")

    sonos.get_current_playback_snapshot = snapshot
    sonos.get_status = AsyncMock(return_value={"volume": 25})
    sonos.play_uri = play_uri
    sonos.set_volume = AsyncMock(return_value=True)
    sonos.restore_playback = restore_playback

    tts = TTSService(sonos, tmp_path, "127.0.0.1")
    tts._generate_audio = AsyncMock(
        side_effect=[tmp_path / "first.mp3", tmp_path / "second.mp3"]
    )

    first = asyncio.create_task(tts.speak("first"))
    await first_playing.wait()
    second = asyncio.create_task(tts.speak("second"))
    await _REAL_SLEEP(0)  # Let the second request block on the service lock.
    release_first.set()

    assert await first is True
    assert await second is True
    assert events == [
        "snapshot",
        "play",
        "restore_first",
        "snapshot",
        "play",
        "restore_second",
    ]


@pytest.mark.asyncio
async def test_cancelled_speech_releases_lock_for_next_request(
    tmp_path: Path, immediate_sleep: None
) -> None:
    """Cancellation restores the first clip and never wedges the TTS queue."""
    sonos = AsyncMock()
    sonos.connected = True
    started = asyncio.Event()

    async def play_uri(*_args, **_kwargs) -> bool:
        if not started.is_set():
            started.set()
            await asyncio.Event().wait()
        return True

    sonos.get_current_playback_snapshot = AsyncMock(return_value=MagicMock())
    sonos.get_status = AsyncMock(return_value={"volume": 25})
    sonos.play_uri = play_uri
    sonos.set_volume = AsyncMock(return_value=True)
    sonos.restore_playback = AsyncMock(return_value=None)

    tts = TTSService(sonos, tmp_path, "127.0.0.1")
    tts._generate_audio = AsyncMock(
        side_effect=[tmp_path / "first.mp3", tmp_path / "second.mp3"]
    )

    first = asyncio.create_task(tts.speak("first"))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    assert await tts.speak("second") is True
    assert sonos.restore_playback.await_count == 2
