"""Pin TTSService duck-and-resume and serialization semantics.

If play_uri fails mid-bump (volume already raised, URL fetch failed),
the speaker MUST be restored to its prior volume + playback state.
Without try/finally a failed TTS leaves Sonos parked at TTS volume
indefinitely.
"""
import asyncio
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.audio_ownership import (
    MANUAL_TRANSPORT_DIMENSIONS,
    MANUAL_VOLUME_DIMENSIONS,
    QUEUE_SOURCE,
    TRANSPORT,
    AudioOwnershipService,
)
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


class MemorySettings:
    def __init__(self) -> None:
        self.value: dict = {}

    async def load(self, _key: str) -> dict:
        return deepcopy(self.value)

    async def save(self, _key: str, value: dict) -> None:
        self.value = deepcopy(value)


def _owned_evidence() -> dict:
    return {
        "queue_uid": "RINCON_TEST",
        "queue_update_id": "7",
        "queue_size": 1,
        "queue_first_item_hash": "abc",
        "play_mode": "NORMAL",
        "transport_state": "PLAYING",
        "current_uri": "x-rincon-queue:RINCON_TEST#0",
        "queue_track": 1,
        "queue_track_uri": "x-sonos-http:original",
        "position": "0:00:20",
        "duration": "0:03:00",
        "volume": 20,
        "mute": False,
    }


class OwnedTTSFakeSonos:
    def __init__(self) -> None:
        self.connected = True
        self.evidence = _owned_evidence()
        self.restore_calls: list[tuple[bool, bool]] = []
        self.snapshot = MagicMock()
        self.snapshot.is_coordinator = True
        self.snapshot.volume = 20
        self.snapshot.transport_state = "PLAYING"

    async def get_playback_ownership_evidence(self, **_kwargs) -> dict:
        return deepcopy(self.evidence)

    async def get_current_playback_snapshot(self):
        return self.snapshot

    async def play_uri_if_unchanged(
        self,
        expected: dict,
        uri: str,
        *,
        volume: int | None = None,
        **_kwargs,
    ) -> bool:
        keys = (
            "queue_uid",
            "queue_update_id",
            "queue_size",
            "queue_first_item_hash",
            "play_mode",
            "transport_state",
            "current_uri",
            "queue_track",
            "queue_track_uri",
            "volume",
            "mute",
        )
        if any(self.evidence.get(key) != expected.get(key) for key in keys):
            return False
        self.evidence.update(
            current_uri=uri,
            transport_state="PLAYING",
            volume=volume,
            position="0:00:00",
            duration="0:00:03",
        )
        return True

    async def restore_tts_snapshot_if_unchanged(
        self,
        snapshot,
        *,
        preflight: dict,
        tts_uri: str,
        tts_volume: int,
        restore_source_transport: bool,
        restore_volume: bool,
        play_failed: bool = False,
    ) -> dict:
        self.restore_calls.append((restore_source_transport, restore_volume))
        result = {
            "source_transport_requested": restore_source_transport,
            "source_transport_restored": False,
            "source_transport_reason": "not_requested",
            "volume_requested": restore_volume,
            "volume_restored": False,
            "volume_reason": "not_requested",
            "observed": deepcopy(self.evidence),
        }
        if restore_volume:
            if self.evidence["volume"] != tts_volume:
                result["volume_reason"] = "volume_changed"
            elif self.evidence["mute"] != preflight["mute"]:
                result["volume_reason"] = "mute_changed"
            else:
                self.evidence["volume"] = snapshot.volume
                result["volume_restored"] = True
                result["volume_reason"] = "tts_rendering_unchanged"

        if restore_source_transport:
            if (
                play_failed
                and self.evidence["current_uri"] == preflight["current_uri"]
                and self.evidence["transport_state"] == preflight["transport_state"]
            ):
                result["source_transport_restored"] = True
                result["source_transport_reason"] = "failed_play_prior_source_intact"
            elif self.evidence["current_uri"] != tts_uri:
                result["source_transport_reason"] = "source_changed"
            elif self.evidence["transport_state"] == "PAUSED_PLAYBACK":
                result["source_transport_reason"] = "transport_paused"
            else:
                current_volume = self.evidence["volume"]
                current_mute = self.evidence["mute"]
                self.evidence = deepcopy(preflight)
                self.evidence["volume"] = current_volume
                self.evidence["mute"] = current_mute
                result["source_transport_restored"] = True
                result["source_transport_reason"] = "tts_active"
        result["observed"] = deepcopy(self.evidence)
        return result


async def _authority() -> AudioOwnershipService:
    settings = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=settings.load,
        setting_saver=settings.save,
    )
    await authority.load()
    return authority


@pytest.mark.asyncio
async def test_owned_tts_failed_conditional_play_without_mutation_does_nothing(
    tmp_path: Path,
) -> None:
    authority = await _authority()
    sonos = OwnedTTSFakeSonos()

    async def refuse(*_args, **_kwargs) -> bool:
        return False

    sonos.play_uri_if_unchanged = refuse
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "refused.mp3")

    assert await tts.speak("hello", volume=60) is False

    assert sonos.evidence == _owned_evidence()
    assert sonos.restore_calls == []
    assert (await authority.snapshot())["last_invalidation"] is None


@pytest.mark.asyncio
async def test_owned_tts_failed_play_after_volume_bump_restores_only_own_bump(
    tmp_path: Path,
) -> None:
    authority = await _authority()
    sonos = OwnedTTSFakeSonos()

    async def fail_after_volume(
        _expected: dict,
        _uri: str,
        *,
        volume: int | None = None,
        **_kwargs,
    ) -> bool:
        sonos.evidence["volume"] = volume
        return False

    sonos.play_uri_if_unchanged = fail_after_volume
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "bump.mp3")

    assert await tts.speak("hello", volume=60) is False

    assert sonos.evidence["current_uri"] == _owned_evidence()["current_uri"]
    assert sonos.evidence["volume"] == 20
    assert sonos.restore_calls == [(False, True), (True, False)]
    assert (await authority.snapshot())["last_invalidation"] is None


@pytest.mark.asyncio
async def test_manual_tts_preempts_reserved_writer_but_restores_owned_music(
    tmp_path: Path,
    immediate_sleep: None,
) -> None:
    authority = await _authority()
    music = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
        evidence={"phase": "owned"},
    )
    ramp = await authority.acquire(
        owner="mode_volume",
        purpose="mode_ramp",
        dimensions=("volume",),
        evidence={"phase": "reserved"},
    )
    assert music is not None and ramp is not None

    sonos = OwnedTTSFakeSonos()
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "manual.mp3")

    assert await tts.speak(
        "hello",
        volume=60,
        manual_source="dashboard",
        manual_reason="manual_tts",
    ) is True

    assert await authority.is_valid(music["lease_id"], (QUEUE_SOURCE, TRANSPORT))
    assert not await authority.is_valid(ramp["lease_id"])
    assert sonos.evidence["current_uri"] == _owned_evidence()["current_uri"]
    snapshot = await authority.snapshot()
    assert snapshot["last_invalidation"]["source"] == "dashboard"
    assert snapshot["last_invalidation"]["reason"] == "manual_tts"


@pytest.mark.asyncio
async def test_owned_tts_suppresses_unrestorable_cloud_queue(
    tmp_path: Path,
) -> None:
    authority = await _authority()
    base = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
        evidence={"phase": "owned"},
    )
    assert base is not None
    sonos = OwnedTTSFakeSonos()
    sonos.snapshot.is_playing_cloud_queue = True
    sonos.play_uri_if_unchanged = AsyncMock(return_value=True)
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "cloud.mp3")

    assert await tts.speak("hello", volume=60) is False

    sonos.play_uri_if_unchanged.assert_not_awaited()
    assert sonos.evidence == _owned_evidence()
    assert await authority.is_valid(base["lease_id"], (QUEUE_SOURCE, TRANSPORT))
    assert await authority.find_lease(owner="tts", purpose="announcement") is None


@pytest.mark.asyncio
async def test_owned_tts_unproven_restore_retires_overlaid_owner(
    tmp_path: Path,
    immediate_sleep: None,
) -> None:
    authority = await _authority()
    base = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
        evidence={"phase": "owned"},
    )
    assert base is not None
    sonos = OwnedTTSFakeSonos()
    sonos.restore_tts_snapshot_if_unchanged = AsyncMock(return_value=None)
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "unknown.mp3")

    assert await tts.speak("hello", volume=60) is True

    assert not await authority.is_valid(base["lease_id"])
    assert await authority.find_lease(owner="tts", purpose="announcement") is None


@pytest.mark.asyncio
async def test_owned_tts_restores_and_preserves_interrupted_music_owner(
    tmp_path: Path,
    immediate_sleep: None,
) -> None:
    authority = await _authority()
    base = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
        evidence={"phase": "owned", "sonos": _owned_evidence()},
    )
    assert base is not None
    sonos = OwnedTTSFakeSonos()
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "owned.mp3")

    assert await tts.speak("hello", volume=60) is True

    assert sonos.evidence["current_uri"] == _owned_evidence()["current_uri"]
    assert sonos.evidence["volume"] == 20
    assert sonos.restore_calls == [(False, True), (True, False)]
    assert await authority.is_valid(base["lease_id"], (QUEUE_SOURCE, TRANSPORT))
    assert await authority.find_lease(owner="tts", purpose="announcement") is None


@pytest.mark.asyncio
async def test_owned_tts_manual_source_takeover_cancels_stale_source_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = await _authority()
    base = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
        evidence={"phase": "owned"},
    )
    assert base is not None
    sonos = OwnedTTSFakeSonos()
    started = asyncio.Event()
    release = asyncio.Event()

    async def gated_sleep(delay: float) -> None:
        if delay >= 60:
            return
        started.set()
        await release.wait()

    monkeypatch.setattr("backend.services.tts_service.asyncio.sleep", gated_sleep)
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "source.mp3")

    task = asyncio.create_task(tts.speak("hello", volume=60))
    await started.wait()
    await authority.invalidate_manual(
        MANUAL_TRANSPORT_DIMENSIONS,
        source="dashboard",
        reason="manual_play",
    )
    sonos.evidence.update(
        current_uri="x-sonos-spotify:manual",
        transport_state="PLAYING",
    )
    release.set()

    assert await task is True
    assert sonos.evidence["current_uri"] == "x-sonos-spotify:manual"
    assert sonos.evidence["volume"] == 20
    assert sonos.restore_calls == [(False, True)]
    assert not await authority.is_valid(base["lease_id"])


@pytest.mark.asyncio
async def test_owned_tts_manual_volume_takeover_survives_source_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = await _authority()
    sonos = OwnedTTSFakeSonos()
    started = asyncio.Event()
    release = asyncio.Event()

    async def gated_sleep(delay: float) -> None:
        if delay >= 60:
            return
        started.set()
        await release.wait()

    monkeypatch.setattr("backend.services.tts_service.asyncio.sleep", gated_sleep)
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "volume.mp3")

    task = asyncio.create_task(tts.speak("hello", volume=60))
    await started.wait()
    await authority.invalidate_manual(
        MANUAL_VOLUME_DIMENSIONS,
        source="dashboard",
        reason="manual_volume",
    )
    sonos.evidence["volume"] = 33
    release.set()

    assert await task is True
    assert sonos.evidence["current_uri"] == _owned_evidence()["current_uri"]
    assert sonos.evidence["volume"] == 33
    assert sonos.restore_calls == [(True, False)]


@pytest.mark.asyncio
async def test_owned_tts_manual_pause_never_auto_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = await _authority()
    sonos = OwnedTTSFakeSonos()
    started = asyncio.Event()
    release = asyncio.Event()

    async def gated_sleep(delay: float) -> None:
        if delay >= 60:
            return
        started.set()
        await release.wait()

    monkeypatch.setattr("backend.services.tts_service.asyncio.sleep", gated_sleep)
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "pause.mp3")

    task = asyncio.create_task(tts.speak("hello", volume=60))
    await started.wait()
    await authority.invalidate_manual(
        MANUAL_TRANSPORT_DIMENSIONS,
        source="dashboard",
        reason="manual_pause",
    )
    sonos.evidence["transport_state"] = "PAUSED_PLAYBACK"
    release.set()

    assert await task is True
    assert sonos.evidence["transport_state"] == "PAUSED_PLAYBACK"
    assert sonos.restore_calls == [(False, True)]


@pytest.mark.asyncio
async def test_owned_tts_off_dashboard_source_takeover_retires_old_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = await _authority()
    base = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
        evidence={"phase": "owned"},
    )
    assert base is not None
    sonos = OwnedTTSFakeSonos()
    started = asyncio.Event()
    release = asyncio.Event()

    async def gated_sleep(delay: float) -> None:
        if delay >= 60:
            return
        started.set()
        await release.wait()

    monkeypatch.setattr("backend.services.tts_service.asyncio.sleep", gated_sleep)
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "external.mp3")

    task = asyncio.create_task(tts.speak("hello", volume=60))
    await started.wait()
    sonos.evidence.update(
        current_uri="x-sonos-spotify:external",
        transport_state="PLAYING",
    )
    release.set()

    assert await task is True
    assert sonos.evidence["current_uri"] == "x-sonos-spotify:external"
    assert sonos.evidence["volume"] == 20
    assert not await authority.is_valid(base["lease_id"])


@pytest.mark.asyncio
async def test_owned_tts_cancellation_restores_and_releases_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = await _authority()
    sonos = OwnedTTSFakeSonos()
    started = asyncio.Event()

    async def blocked_sleep(delay: float) -> None:
        if delay >= 60:
            return
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("backend.services.tts_service.asyncio.sleep", blocked_sleep)
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "cancel.mp3")

    task = asyncio.create_task(tts.speak("hello", volume=60))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await authority.find_lease(owner="tts", purpose="announcement") is None
    assert tts.is_speaking is False
    assert sonos.evidence["current_uri"] == _owned_evidence()["current_uri"]
    assert sonos.evidence["volume"] == 20


@pytest.mark.asyncio
async def test_tts_close_abandons_inflight_restore_without_sonos_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = await _authority()
    base = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
        evidence={"phase": "owned"},
    )
    assert base is not None
    sonos = OwnedTTSFakeSonos()
    started = asyncio.Event()
    release = asyncio.Event()

    async def gated_sleep(delay: float) -> None:
        if delay >= 60:
            return
        started.set()
        await release.wait()

    monkeypatch.setattr("backend.services.tts_service.asyncio.sleep", gated_sleep)
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )
    tts._generate_audio = AsyncMock(return_value=tmp_path / "shutdown.mp3")

    task = asyncio.create_task(tts.speak("hello", volume=60))
    await started.wait()
    assert sonos.evidence["current_uri"].endswith("/static/tts/shutdown.mp3")

    await tts.close()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Shutdown must not restore the pre-TTS snapshot. Both the interruption
    # and the owner it overlaid are retired because physical provenance is now
    # ambiguous and no Sonos mutation is allowed during shutdown.
    assert sonos.restore_calls == []
    assert sonos.evidence["current_uri"].endswith("/static/tts/shutdown.mp3")
    assert await authority.find_lease(owner="tts", purpose="announcement") is None
    assert not await authority.is_valid(base["lease_id"])


@pytest.mark.asyncio
async def test_tts_close_cancels_generation_before_any_sonos_mutation(
    tmp_path: Path,
) -> None:
    authority = await _authority()
    sonos = OwnedTTSFakeSonos()
    generation_started = asyncio.Event()
    generation_release = asyncio.Event()
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )

    async def blocked_generation(_text: str) -> Path:
        generation_started.set()
        await generation_release.wait()
        path = tmp_path / "late.mp3"
        path.write_bytes(b"late")
        return path

    tts._generate_audio = blocked_generation

    task = asyncio.create_task(tts.speak("hello", volume=60))
    await generation_started.wait()

    await tts.close()
    generation_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await authority.find_lease(owner="tts", purpose="announcement") is None
    assert sonos.evidence == _owned_evidence()
    assert sonos.restore_calls == []
    assert tts._speech_tasks == set()


@pytest.mark.asyncio
async def test_tts_close_deletes_pending_cleanup_file(tmp_path: Path) -> None:
    sonos = OwnedTTSFakeSonos()
    tts = TTSService(sonos, tmp_path, "127.0.0.1")
    path = tmp_path / "tts" / "pending.mp3"
    path.write_bytes(b"pending")

    tts._schedule_cleanup(path)
    assert path.exists()
    assert len(tts._cleanup_tasks) == 1

    await tts.close()

    assert not path.exists()
    assert tts._cleanup_tasks == set()
    assert tts._cleanup_paths == {}


@pytest.mark.asyncio
async def test_tts_restart_retires_stale_interruption_without_sonos_mutation(
    tmp_path: Path,
) -> None:
    authority = await _authority()
    base = await authority.acquire(
        owner="music_mapper",
        purpose="mode_auto_play",
        dimensions=(QUEUE_SOURCE, TRANSPORT),
        evidence={"phase": "owned"},
    )
    assert base is not None
    stale = await authority.acquire_interruption(
        owner="tts",
        purpose="announcement",
        dimensions=("queue_source", "transport", "volume", "interruption"),
        evidence={"phase": "speaking"},
    )
    assert stale is not None
    sonos = AsyncMock()
    sonos.connected = True
    tts = TTSService(
        sonos, tmp_path, "127.0.0.1", audio_ownership=authority,
    )

    await tts.recover_stale_interruption()

    assert await authority.find_lease(owner="tts", purpose="announcement") is None
    assert not await authority.is_valid(base["lease_id"])
    sonos.assert_not_called()
