"""Ownership/restart tests for MusicMapper mode auto-play (#273/#274)."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import patch

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
from backend.services.music_mapper import MusicMapper


class MemorySettings:
    def __init__(self) -> None:
        self.value: dict = {}

    async def load(self, _key: str) -> dict:
        return deepcopy(self.value)

    async def save(self, _key: str, value: dict) -> None:
        self.value = deepcopy(value)


class Ws:
    def __init__(self) -> None:
        self.broadcasts: list[tuple[str, dict]] = []

    async def broadcast(self, kind: str, payload: dict) -> None:
        self.broadcasts.append((kind, payload))


class Sonos:
    def __init__(self) -> None:
        self.connected = True
        self.state = "STOPPED"
        self.volume = 0
        self.mute = False
        self.play_success = True
        self.play_calls: list[str] = []
        self.volume_writes: list[int] = []
        self.neutral_evidence = {
            "queue_uid": "RINCON_TEST",
            "queue_update_id": "6",
            "queue_size": 0,
            "queue_first_item_hash": None,
            "play_mode": "NORMAL",
            "transport_state": "STOPPED",
            "current_uri": "x-rincon-queue:RINCON_TEST#0",
            "queue_track": 0,
            "queue_track_uri": "",
        }
        self.evidence = {
            "queue_uid": "RINCON_TEST",
            "queue_update_id": "7",
            "queue_size": 100,
            "queue_first_item_hash": "abc",
            "play_mode": "SHUFFLE",
            "transport_state": "PLAYING",
            "current_uri": "x-rincon-queue:RINCON_TEST#0",
            "queue_track": 4,
            "queue_track_uri": "x-sonos-http:track4",
        }
        self.release_calls: list[dict] = []

    async def get_status(self) -> dict:
        return {"state": self.state}

    async def play_favorite(
        self, title: str, *, expected_queue_evidence: dict | None = None,
    ) -> bool:
        if expected_queue_evidence is not None:
            for key, value in self.neutral_evidence.items():
                assert expected_queue_evidence.get(key) == value
        self.play_calls.append(title)
        if self.play_success:
            self.state = "PLAYING"
        return self.play_success

    async def get_playback_ownership_evidence(self) -> dict | None:
        evidence = await self.get_queue_ownership_evidence()
        if evidence is None:
            return None
        evidence["volume"] = self.volume
        evidence["mute"] = self.mute
        return evidence

    async def set_volume_if_playback_unchanged(
        self,
        expected: dict,
        target: int,
        **_kwargs,
    ) -> bool:
        current = await self.get_playback_ownership_evidence()
        if current != expected:
            return False
        self.volume = int(target)
        self.volume_writes.append(self.volume)
        return True

    async def get_queue_ownership_evidence(self) -> dict | None:
        if self.state in {"STOPPED", "NO_MEDIA_PRESENT"}:
            return deepcopy(self.neutral_evidence)
        return deepcopy(self.evidence)


class SettlingSonos(Sonos):
    """Model real Sonos returning TRANSITIONING briefly after queue play."""

    def __init__(self, transition_reads: int = 3) -> None:
        super().__init__()
        self.transition_reads = transition_reads

    async def play_favorite(
        self, title: str, *, expected_queue_evidence: dict | None = None,
    ) -> bool:
        if expected_queue_evidence is not None:
            for key, value in self.neutral_evidence.items():
                assert expected_queue_evidence.get(key) == value
        self.play_calls.append(title)
        if self.play_success:
            self.state = "TRANSITIONING"
        return self.play_success

    async def get_queue_ownership_evidence(self) -> dict | None:
        if self.state == "TRANSITIONING":
            if self.transition_reads > 0:
                self.transition_reads -= 1
                evidence = deepcopy(self.evidence)
                evidence["transport_state"] = "TRANSITIONING"
                return evidence
            self.state = "PLAYING"
        return await super().get_queue_ownership_evidence()


def entry(title: str = "2000s Hits Essentials") -> dict:
    return {
        "id": 1,
        "favorite_title": title,
        "vibe": "energetic",
        "auto_play": True,
        "priority": 10,
    }


async def make_authority(settings: MemorySettings) -> AudioOwnershipService:
    authority = AudioOwnershipService(
        setting_loader=settings.load,
        setting_saver=settings.save,
    )
    await authority.load()
    return authority


@pytest.mark.asyncio
async def test_auto_play_persists_exact_queue_ownership() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    mapper = MusicMapper(sonos, Ws(), audio_ownership=authority)
    mapper._cache["social"] = [entry()]

    result = await mapper.on_mode_change("social")

    assert result["action"] == "auto_played"
    snapshot = await authority.snapshot()
    assert len(snapshot["leases"]) == 1
    lease = snapshot["leases"][0]
    assert lease["metadata"]["mode"] == "social"
    assert lease["evidence"] == {"phase": "owned", "sonos": sonos.evidence}


@pytest.mark.asyncio
async def test_mode_exit_retires_lease_without_destructive_cleanup() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    mapper = MusicMapper(sonos, Ws(), audio_ownership=authority)
    mapper._cache["social"] = [entry()]
    await mapper.on_mode_change("social")

    await mapper.on_mode_change("working")

    assert sonos.release_calls == []
    assert sonos.state == "PLAYING"
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_manual_takeover_removes_lease_before_mode_exit() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    mapper = MusicMapper(sonos, Ws(), audio_ownership=authority)
    mapper._cache["social"] = [entry()]
    await mapper.on_mode_change("social")

    await authority.invalidate_manual(
        MANUAL_TRANSPORT_DIMENSIONS,
        source="sonos_app",
        reason="manual_skip",
    )
    await mapper.on_mode_change("working")

    assert sonos.release_calls == []
    assert sonos.state == "PLAYING"
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_restart_rehydrates_lease_but_mode_exit_never_cleans_sonos() -> None:
    settings = MemorySettings()
    first_authority = await make_authority(settings)
    sonos = Sonos()
    first_mapper = MusicMapper(sonos, Ws(), audio_ownership=first_authority)
    first_mapper._cache["social"] = [entry()]
    await first_mapper.on_mode_change("social")

    restarted_authority = await make_authority(settings)
    restarted_mapper = MusicMapper(
        sonos, Ws(), audio_ownership=restarted_authority,
    )

    await restarted_mapper.on_mode_change("working")

    assert sonos.release_calls == []
    assert sonos.state == "PLAYING"
    assert (await restarted_authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_failed_auto_play_leaves_no_lease() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    sonos.play_success = False
    mapper = MusicMapper(sonos, Ws(), audio_ownership=authority)
    mapper._cache["social"] = [entry()]

    result = await mapper.on_mode_change("social")

    assert result is None
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_success_without_fingerprint_retires_lease_fail_safe() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    sonos.evidence = None
    mapper = MusicMapper(sonos, Ws(), audio_ownership=authority)
    mapper._cache["social"] = [entry()]

    result = await mapper.on_mode_change("social")

    assert result["action"] == "auto_played"
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_stale_source_or_play_mode_is_not_treated_as_idle_permission() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    sonos.neutral_evidence["play_mode"] = "SHUFFLE"
    sonos.neutral_evidence["current_uri"] = (
        "http://127.0.0.1:8000/static/ambient/fireplace.mp3"
    )
    mapper = MusicMapper(sonos, Ws(), audio_ownership=authority)
    mapper._cache["social"] = [entry()]

    result = await mapper.on_mode_change("social")

    assert result["action"] == "suggested"
    assert sonos.state == "STOPPED"
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_cursor_change_before_poll_still_never_allows_mode_exit_cleanup() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    mapper = MusicMapper(sonos, Ws(), audio_ownership=authority)
    mapper._cache["social"] = [entry()]
    await mapper.on_mode_change("social")

    sonos.evidence["queue_track"] = 5
    sonos.evidence["queue_track_uri"] = "x-sonos-http:track5"

    await mapper.on_mode_change("working")

    assert sonos.release_calls == []
    assert sonos.state == "PLAYING"
    assert (await authority.snapshot())["leases"] == []


class PregameAutomation:
    def __init__(self) -> None:
        self.current_mode = "gameday"
        self.house_state = "home"
        self.dnd = False
        self.period = "evening"

    def is_dnd_active(self) -> bool:
        return self.dnd

    def _get_time_period(self) -> str:
        return self.period


class PregameTTS:
    def __init__(self, callback=None) -> None:
        self.callback = callback
        self.calls: list[tuple[str, int | None]] = []

    async def speak(self, line: str, *, volume: int | None = None) -> None:
        self.calls.append((line, volume))
        if self.callback is not None:
            result = self.callback()
            if result is not None:
                await result


def pregame_decision():
    from backend.services.pregame_audio_policy import PregameAudioDecision

    return PregameAudioDecision(
        tier="standard",
        tts_line="Game day. Colts and Chiefs in 30.",
        sonos_hype_play=True,
        sonos_vibe=None,
    )


async def _no_sleep(*_args, **_kwargs) -> None:
    return None


async def _gameday_volume_settings(_key: str) -> dict:
    return {"gameday": {"evening": 25}}


@pytest.mark.asyncio
async def test_pregame_hype_sets_mode_volume_after_tts_restores_zero() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    automation = PregameAutomation()
    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["sonos_fired"] is True
    assert result["sonos_reason"] == "played"
    assert sonos.volume == 25
    assert sonos.volume_writes == [25]
    assert sonos.play_calls == ["Colts Hype"]

    snapshot = await authority.snapshot()
    assert len(snapshot["leases"]) == 1
    lease = snapshot["leases"][0]
    assert lease["owner"] == "music_mapper"
    assert lease["purpose"] == "mode_auto_play"
    assert lease["dimensions"] == ["queue_source", "transport"]
    assert lease["metadata"]["mode"] == "gameday"
    assert lease["metadata"]["source"] == "pregame_audio"
    assert lease["evidence"]["phase"] == "owned"


@pytest.mark.asyncio
async def test_pregame_refreshes_single_tts_queue_update_before_hype() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    sonos.neutral_evidence["play_mode"] = "SHUFFLE"
    automation = PregameAutomation()

    def tts_self_update() -> None:
        sonos.neutral_evidence["queue_update_id"] = "7"

    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(tts_self_update),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["sonos_fired"] is True
    assert result["sonos_reason"] == "played"
    assert sonos.play_calls == ["Colts Hype"]
    assert sonos.volume == 25

    snapshot = await authority.snapshot()
    assert len(snapshot["leases"]) == 1
    lease = snapshot["leases"][0]
    assert lease["dimensions"] == ["queue_source", "transport"]
    assert lease["evidence"]["phase"] == "owned"
    assert lease["evidence"]["sonos"]["queue_update_id"] == "7"


@pytest.mark.asyncio
async def test_pregame_does_not_refresh_unexpected_second_queue_update() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    sonos.neutral_evidence["play_mode"] = "SHUFFLE"
    automation = PregameAutomation()

    def external_queue_change() -> None:
        sonos.neutral_evidence["queue_update_id"] = "8"

    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(external_queue_change),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["sonos_fired"] is False
    assert result["sonos_reason"] == "sonos_source_changed_during_tts_gap"
    assert sonos.play_calls == []
    assert sonos.volume_writes == []
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_pregame_hype_waits_for_transitioning_sonos_to_settle() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = SettlingSonos(transition_reads=4)
    automation = PregameAutomation()
    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["sonos_fired"] is True
    assert result["sonos_reason"] == "played"
    assert sonos.state == "PLAYING"
    assert sonos.transition_reads == 0
    assert sonos.volume == 25
    assert sonos.volume_writes == [25]

    snapshot = await authority.snapshot()
    assert len(snapshot["leases"]) == 1
    lease = snapshot["leases"][0]
    assert lease["dimensions"] == ["queue_source", "transport"]
    assert lease["evidence"]["phase"] == "owned"
    assert lease["evidence"]["sonos"]["transport_state"] == "PLAYING"


@pytest.mark.asyncio
async def test_pregame_manual_source_takeover_during_tts_gap_suppresses_hype() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    automation = PregameAutomation()

    async def takeover() -> None:
        sonos.state = "PLAYING"

    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(takeover),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["sonos_fired"] is False
    assert result["sonos_reason"] == "sonos_source_changed_during_tts_gap"
    assert sonos.play_calls == []
    assert sonos.volume_writes == []
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_pregame_central_manual_takeover_wins_even_if_device_returns_to_baseline() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    automation = PregameAutomation()

    async def takeover() -> None:
        await authority.invalidate_manual(
            MANUAL_TRANSPORT_DIMENSIONS,
            source="sonos_app",
            reason="manual_song_during_pregame_gap",
        )

    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(takeover),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["sonos_fired"] is False
    assert result["sonos_reason"] == "manual_source_takeover_during_tts_gap"
    assert sonos.play_calls == []
    assert sonos.volume_writes == []


@pytest.mark.asyncio
async def test_pregame_lifecycle_change_after_tts_suppresses_hype() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    automation = PregameAutomation()

    def leave_gameday() -> None:
        automation.current_mode = "watching"

    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(leave_gameday),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["tts_fired"] is True
    assert result["sonos_fired"] is False
    assert result["sonos_reason"] == "lifecycle:mode_changed:watching"
    assert sonos.play_calls == []
    assert sonos.volume_writes == []


@pytest.mark.asyncio
async def test_pregame_manual_volume_change_is_preserved_while_hype_still_plays() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    automation = PregameAutomation()

    def manual_volume() -> None:
        sonos.volume = 20

    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(manual_volume),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["sonos_fired"] is True
    assert result["sonos_reason"] == "played"
    assert sonos.volume == 20
    assert sonos.volume_writes == []
    assert sonos.play_calls == ["Colts Hype"]


@pytest.mark.asyncio
async def test_pregame_pending_lease_allows_tts_interruption_overlay() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    mapper = MusicMapper(sonos, Ws(), audio_ownership=authority)

    baseline = await sonos.get_playback_ownership_evidence()
    lease, reason = await mapper._reserve_pregame_hype_lease(baseline)

    assert reason is None
    assert lease is not None
    interruption = await authority.acquire_interruption(
        owner="tts_service",
        purpose="speech",
        dimensions=(QUEUE_SOURCE, TRANSPORT, VOLUME, INTERRUPTION),
    )
    assert interruption is not None

    executed, _ = await authority.run_if_valid(
        lease["lease_id"],
        (QUEUE_SOURCE, TRANSPORT),
        _no_sleep,
    )
    assert executed is False

    await authority.release(interruption["lease_id"], reason="tts_complete")
    assert await authority.is_valid(
        lease["lease_id"],
        (QUEUE_SOURCE, TRANSPORT, VOLUME),
    )


@pytest.mark.asyncio
async def test_pregame_stopped_existing_queue_is_conditionally_replaceable() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    sonos.neutral_evidence.update({
        "queue_update_id": "42",
        "queue_size": 18,
        "queue_first_item_hash": "stale-prior-queue",
        "play_mode": "SHUFFLE",
        "queue_track": 3,
        "queue_track_uri": "x-sonos-http:old-track",
    })
    automation = PregameAutomation()
    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["sonos_fired"] is True
    assert result["sonos_reason"] == "played"
    assert sonos.play_calls == ["Colts Hype"]
    assert sonos.volume == 25


@pytest.mark.asyncio
async def test_pregame_failed_play_never_writes_startup_volume() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    sonos.play_success = False
    automation = PregameAutomation()
    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["sonos_fired"] is False
    assert result["sonos_reason"] == "play_failed"
    assert sonos.volume_writes == []
    assert sonos.volume == 0
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_pregame_dnd_change_after_tts_suppresses_hype() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    automation = PregameAutomation()

    def enable_dnd() -> None:
        automation.dnd = True

    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(enable_dnd),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["tts_fired"] is True
    assert result["sonos_fired"] is False
    assert result["sonos_reason"] == "lifecycle:dnd_active"
    assert sonos.play_calls == []
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_pregame_central_manual_volume_change_preserves_volume_and_hype() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    automation = PregameAutomation()

    async def manual_volume() -> None:
        sonos.volume = 20
        await authority.invalidate_manual(
            MANUAL_VOLUME_DIMENSIONS,
            source="sonos_app",
            reason="manual_volume_during_pregame_tts",
        )

    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(manual_volume),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["sonos_fired"] is True
    assert result["sonos_reason"] == "played"
    assert sonos.volume == 20
    assert sonos.volume_writes == []
    snapshot = await authority.snapshot()
    assert len(snapshot["leases"]) == 1
    assert snapshot["leases"][0]["dimensions"] == ["queue_source", "transport"]


@pytest.mark.asyncio
async def test_real_pregame_dispatch_requires_gameday_mode() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    automation = PregameAutomation()
    automation.current_mode = "pregameday"
    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(pregame_decision())

    assert result["tts_fired"] is False
    assert result["sonos_fired"] is False
    assert result["sonos_reason"] == "lifecycle:mode_changed:pregameday"


@pytest.mark.asyncio
async def test_synthetic_pregame_dispatch_allows_pregameday_mode() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    automation = PregameAutomation()
    automation.current_mode = "pregameday"
    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    with patch("backend.services.music_mapper.asyncio.sleep", new=_no_sleep):
        result = await mapper.dispatch_pregame_audio(
            pregame_decision(),
            synthetic=True,
        )

    assert result["tts_fired"] is True
    assert result["sonos_fired"] is True
    assert result["sonos_reason"] == "played"
    assert sonos.volume == 25



@pytest.mark.asyncio
async def test_pregame_gap_cancellation_retires_pending_lease() -> None:
    settings = MemorySettings()
    authority = await make_authority(settings)
    sonos = Sonos()
    automation = PregameAutomation()
    mapper = MusicMapper(
        sonos,
        Ws(),
        tts_service=PregameTTS(),
        audio_ownership=authority,
        setting_loader=_gameday_volume_settings,
    )
    mapper.set_automation(automation)
    mapper._cache["pregameday"] = [entry("Colts Hype")]

    async def cancel_gap(*_args, **_kwargs) -> None:
        raise asyncio.CancelledError

    with patch("backend.services.music_mapper.asyncio.sleep", new=cancel_gap):
        with pytest.raises(asyncio.CancelledError):
            await mapper.dispatch_pregame_audio(pregame_decision())

    assert (await authority.snapshot())["leases"] == []
