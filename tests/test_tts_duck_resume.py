"""Pin TTSService duck-and-resume try/finally semantics.

If play_uri fails mid-bump (volume already raised, URL fetch failed),
the speaker MUST be restored to its prior volume + playback state.
Without try/finally a failed TTS leaves Sonos parked at TTS volume
indefinitely.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.tts_service import TTSService


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
