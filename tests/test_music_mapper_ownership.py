"""Ownership/restart tests for MusicMapper mode auto-play (#273/#274)."""
from __future__ import annotations

from copy import deepcopy

import pytest

from backend.services.audio_ownership import (
    MANUAL_TRANSPORT_DIMENSIONS,
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
        self.play_success = True
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
            assert expected_queue_evidence == self.neutral_evidence
        if self.play_success:
            self.state = "PLAYING"
        return self.play_success

    async def get_queue_ownership_evidence(self) -> dict | None:
        if self.state in {"STOPPED", "NO_MEDIA_PRESENT"}:
            return deepcopy(self.neutral_evidence)
        return deepcopy(self.evidence)


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
