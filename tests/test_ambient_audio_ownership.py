from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes import routines
from backend.services import ambient_sound_service as ambient_module
from backend.services.audio_ownership import (
    QUEUE_SOURCE,
    TRANSPORT,
    VOLUME,
    AudioOwnershipService,
)
from backend.services.ambient_sound_service import (
    AMBIENT_AUDIO_DIMENSIONS,
    AMBIENT_AUDIO_OWNER,
    AMBIENT_AUDIO_PURPOSE,
    AmbientSoundService,
)


class MemorySettings:
    def __init__(self) -> None:
        self.value: dict = {}

    async def load(self, _key: str) -> dict:
        return deepcopy(self.value)

    async def save(self, _key: str, value: dict) -> None:
        self.value = deepcopy(value)


class FakeSonos:
    def __init__(self) -> None:
        self.connected = True
        self.evidence = {
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
        self.play_calls: list[tuple] = []
        self.pause_calls: list[dict] = []
        self.volume_calls: list[int] = []

    async def get_playback_ownership_evidence(self) -> dict:
        return deepcopy(self.evidence)

    @staticmethod
    def _matches(current: dict, expected: dict, *, include_volume: bool) -> bool:
        keys = [
            "queue_uid",
            "queue_update_id",
            "queue_size",
            "queue_first_item_hash",
            "play_mode",
            "transport_state",
            "current_uri",
            "queue_track",
            "queue_track_uri",
        ]
        if include_volume:
            keys += ["volume", "mute"]
        return all(current.get(key) == expected.get(key) for key in keys)

    async def play_uri_if_unchanged(
        self,
        expected: dict,
        uri: str,
        *,
        volume: int | None = None,
        meta: str | None = None,
        force_radio: bool = False,
        still_allowed=None,
        mutation_lock=None,
    ) -> bool:
        del meta
        if mutation_lock is not None:
            mutation_lock.acquire()
        try:
            if not self._matches(self.evidence, expected, include_volume=True):
                return False
            if still_allowed is not None and not still_allowed():
                return False
            self.play_calls.append((uri, volume, force_radio))
            self.evidence["current_uri"] = (
                f"x-rincon-mp3radio:{uri}" if force_radio else uri
            )
            self.evidence["transport_state"] = "PLAYING"
            self.evidence["play_mode"] = "NORMAL"
            if volume is not None:
                self.evidence["volume"] = volume
            return True
        finally:
            if mutation_lock is not None:
                mutation_lock.release()

    async def play_uri_if_source_unchanged(
        self,
        expected: dict,
        uri: str,
        *,
        meta: str | None = None,
        force_radio: bool = False,
        still_allowed=None,
        mutation_lock=None,
    ) -> bool:
        del meta
        if mutation_lock is not None:
            mutation_lock.acquire()
        try:
            if not self._matches(self.evidence, expected, include_volume=False):
                return False
            if still_allowed is not None and not still_allowed():
                return False
            self.play_calls.append((uri, None, force_radio))
            self.evidence["current_uri"] = (
                f"x-rincon-mp3radio:{uri}" if force_radio else uri
            )
            self.evidence["transport_state"] = "PLAYING"
            self.evidence["play_mode"] = "NORMAL"
            return True
        finally:
            if mutation_lock is not None:
                mutation_lock.release()

    async def pause_if_playback_unchanged(
        self,
        expected: dict,
        *,
        still_allowed=None,
        mutation_lock=None,
    ) -> bool:
        if mutation_lock is not None:
            mutation_lock.acquire()
        try:
            self.pause_calls.append(deepcopy(expected))
            if not self._matches(self.evidence, expected, include_volume=False):
                return False
            if still_allowed is not None and not still_allowed():
                return False
            self.evidence["transport_state"] = "PAUSED_PLAYBACK"
            return True
        finally:
            if mutation_lock is not None:
                mutation_lock.release()

    async def set_volume_if_playback_unchanged(
        self,
        expected: dict,
        target: int,
        *,
        still_allowed=None,
        mutation_lock=None,
    ) -> bool:
        if mutation_lock is not None:
            mutation_lock.acquire()
        try:
            if not self._matches(self.evidence, expected, include_volume=True):
                return False
            if still_allowed is not None and not still_allowed():
                return False
            self.volume_calls.append(target)
            self.evidence["volume"] = target
            return True
        finally:
            if mutation_lock is not None:
                mutation_lock.release()




async def drain_sonos_tasks(service: AmbientSoundService) -> None:
    tasks = [
        task
        for task in tuple(service._pending_sonos_tasks)
        if not task.done()
    ]
    if tasks:
        await asyncio.gather(*tasks)

async def make_authority() -> AudioOwnershipService:
    store = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=store.load,
        setting_saver=store.save,
    )
    await authority.load()
    return authority


def make_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    authority: AudioOwnershipService,
    sonos: FakeSonos | None = None,
) -> tuple[AmbientSoundService, FakeSonos]:
    long_dir = tmp_path / "data" / "ambient"
    short_dir = tmp_path / "backend" / "static" / "ambient"
    long_dir.mkdir(parents=True)
    short_dir.mkdir(parents=True)
    (short_dir / "rain.mp3").write_bytes(b"")
    monkeypatch.setattr(
        ambient_module,
        "SCAN_DIRS",
        ((long_dir, "/static/ambient-long"), (short_dir, "/static/ambient")),
    )
    monkeypatch.setattr(ambient_module, "SHORT_AMBIENT_DIR", short_dir)
    monkeypatch.setattr(ambient_module, "LONG_AMBIENT_DIR", long_dir)

    ws = MagicMock()
    ws.broadcast = AsyncMock()
    fake = sonos or FakeSonos()
    service = AmbientSoundService(
        ws_manager=ws,
        weather_service=MagicMock(),
        sonos=fake,
        audio_ownership=authority,
    )
    service._save_config = AsyncMock()
    service._automation = MagicMock(
        current_mode="relax",
        house_state="home",
    )
    service._automation.is_dnd_active.return_value = False
    service.scan_sounds()
    service._current_sound = "rain.mp3"
    service._source = "weather"
    service._playing = True
    service._sonos_ambient_pending = True
    return service, fake


@pytest.mark.asyncio
async def test_ambient_starts_only_from_neutral_sonos_and_acquires_all_dimensions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)

    await service._start_sonos_ambient()

    assert service._sonos_ambient_active is True
    assert len(sonos.play_calls) == 1
    snapshot = await authority.snapshot()
    assert len(snapshot["leases"]) == 1
    lease = snapshot["leases"][0]
    assert lease["owner"] == AMBIENT_AUDIO_OWNER
    assert lease["purpose"] == AMBIENT_AUDIO_PURPOSE
    assert set(lease["dimensions"]) == set(AMBIENT_AUDIO_DIMENSIONS)
    assert lease["evidence"]["phase"] == "owned"
    assert lease["evidence"]["sonos"]["transport_state"] == "PLAYING"

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport,play_mode,current_uri",
    [
        ("PAUSED_PLAYBACK", "NORMAL", "x-sonos-spotify:manual"),
        ("STOPPED", "SHUFFLE", "http://127.0.0.1:8000/static/ambient/fireplace.mp3"),
    ],
)
async def test_ambient_refuses_paused_or_stale_residual_sonos(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    transport: str,
    play_mode: str,
    current_uri: str,
) -> None:
    authority = await make_authority()
    sonos = FakeSonos()
    sonos.evidence["transport_state"] = transport
    sonos.evidence["play_mode"] = play_mode
    sonos.evidence["current_uri"] = current_uri
    service, sonos = make_service(monkeypatch, tmp_path, authority, sonos)

    await service._start_sonos_ambient()

    assert service._sonos_ambient_active is False
    assert service._playing is False
    assert sonos.play_calls == []
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_manual_source_takeover_yields_without_pausing_new_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    sonos.evidence["current_uri"] = "x-sonos-spotify:manual"
    sonos.evidence["transport_state"] = "PLAYING"

    assert await service._reconcile_owned_playback() is None

    assert service._sonos_ambient_active is False
    assert service._playing is False
    assert sonos.pause_calls == []
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_manual_pause_yields_and_never_restarts_ambient(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()
    assert len(sonos.play_calls) == 1

    sonos.evidence["transport_state"] = "PAUSED_PLAYBACK"

    assert await service._reconcile_owned_playback() is None

    assert len(sonos.play_calls) == 1
    assert service._sonos_ambient_active is False
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_external_volume_change_surrenders_only_volume_dimension(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    sonos.evidence["volume"] = 11

    fresh = await service._reconcile_owned_playback()

    assert fresh is not None
    assert service._sonos_ambient_active is True
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert set(leases[0]["dimensions"]) == {QUEUE_SOURCE, TRANSPORT}

    wrote = await service._ramp_owned_volume(30, steps=2, interval=0)
    assert wrote is False
    assert sonos.volume_calls == []

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_restart_retires_persisted_ambient_lease_without_device_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = MemorySettings()
    authority = AudioOwnershipService(
        setting_loader=store.load,
        setting_saver=store.save,
    )
    await authority.load()
    lease = await authority.acquire(
        owner=AMBIENT_AUDIO_OWNER,
        purpose=AMBIENT_AUDIO_PURPOSE,
        dimensions=AMBIENT_AUDIO_DIMENSIONS,
        evidence={"phase": "owned", "sonos": {"current_uri": "ambient"}},
    )
    assert lease is not None

    sonos = FakeSonos()
    sonos.evidence["transport_state"] = "PLAYING"
    sonos.evidence["current_uri"] = "http://127.0.0.1:8000/static/ambient/rain.mp3"
    service, sonos = make_service(monkeypatch, tmp_path, authority, sonos)
    service._load_stream_library = AsyncMock()

    async def load_setting(key: str) -> dict:
        if key != ambient_module.AMBIENT_CONFIG_KEY:
            return {}
        return {
            "volume": 0.3,
            "mode_sounds": {"relax": "rain.mp3"},
            "mode_auto_play": {"relax": True},
            "weather_reactive": True,
            "last_sound": "rain.mp3",
            "last_playing": True,
            "last_source": "weather",
            "sonos_enabled": True,
            "sonos_only_migrated": True,
            "sonos_present_volume": 25,
            "sonos_away_volume": 35,
            "sonos_mode_volume_overrides": {},
        }

    save_setting = AsyncMock()
    monkeypatch.setattr(routines, "load_setting", load_setting)
    monkeypatch.setattr(routines, "save_setting", save_setting)
    service._save_config = AmbientSoundService._save_config.__get__(service)

    await service.load_from_db()

    assert service._playing is False
    assert service._sonos_ambient_active is False
    assert (await authority.snapshot())["leases"] == []
    assert sonos.play_calls == []
    assert sonos.pause_calls == []


def test_ambient_lifecycle_and_dnd_are_stronger_than_audio_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = MagicMock()
    service, _ = make_service(monkeypatch, tmp_path, authority)  # type: ignore[arg-type]

    service._automation.house_state = "away"
    assert service._sonos_eligible() is False

    service._automation.house_state = "home"
    service._automation.is_dnd_active.return_value = True
    assert service._sonos_eligible() is False

    service._automation.is_dnd_active.return_value = False
    service._automation.current_mode = "sleeping"
    assert service._sonos_eligible() is False


@pytest.mark.asyncio
async def test_ambient_pause_then_resume_reacquires_only_exact_paused_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()
    assert service._sonos_ambient_active is True

    await service.pause(learn=False)

    assert service._sonos_ambient_active is False
    assert service._sonos_paused_evidence is not None
    assert sonos.evidence["transport_state"] == "PAUSED_PLAYBACK"
    assert (await authority.snapshot())["leases"] == []

    result = await service.resume()
    await drain_sonos_tasks(service)

    assert result["status"] == "ok"
    assert service._sonos_ambient_active is True
    assert len(sonos.play_calls) == 2
    assert sonos.evidence["transport_state"] == "PLAYING"
    assert service._sonos_paused_evidence is None

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_paused_ambient_claim_cannot_resume_after_manual_source_takeover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()
    await service.pause(learn=False)

    sonos.evidence["current_uri"] = "x-sonos-spotify:manual"
    sonos.evidence["transport_state"] = "PAUSED_PLAYBACK"

    service._playing = True
    service._sonos_ambient_pending = True
    await service._start_sonos_ambient()

    assert service._sonos_ambient_active is False
    assert service._sonos_paused_evidence is None
    assert len(sonos.play_calls) == 1
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("volume", 11),
        ("mute", True),
    ],
)
async def test_pause_resume_never_reclaims_surrendered_volume_dimension(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: int | bool,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    sonos.evidence[field] = value
    fresh = await service._reconcile_owned_playback()
    assert fresh is not None
    lease = (await authority.snapshot())["leases"][0]
    assert set(lease["dimensions"]) == {QUEUE_SOURCE, TRANSPORT}

    await service.pause(learn=False)
    assert service._sonos_paused_dimensions == {QUEUE_SOURCE, TRANSPORT}

    result = await service.resume()
    await drain_sonos_tasks(service)

    assert result["status"] == "ok"
    assert service._sonos_ambient_active is True
    lease = (await authority.snapshot())["leases"][0]
    assert set(lease["dimensions"]) == {QUEUE_SOURCE, TRANSPORT}
    assert await service._ramp_owned_volume(30, steps=2, interval=0) is False
    assert sonos.volume_calls == []

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_shutdown_abandons_active_ambient_without_sonos_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    persisted_playing: list[bool] = []

    async def capture_save() -> None:
        persisted_playing.append(service._playing)

    service._save_config = AsyncMock(side_effect=capture_save)
    await service._start_sonos_ambient()
    assert sonos.evidence["transport_state"] == "PLAYING"

    await service.shutdown()
    await asyncio.sleep(0)

    assert service._playing is False
    assert service._sonos_ambient_active is False
    assert persisted_playing[-1] is False
    assert sonos.evidence["transport_state"] == "PLAYING"
    assert sonos.pause_calls == []
    assert len(sonos.play_calls) == 1
    assert sonos.volume_calls == []
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_away_transition_cancels_inflight_owned_volume_ramp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    original_write = sonos.set_volume_if_playback_unchanged

    async def first_step_then_away(
        expected: dict,
        target: int,
        *,
        still_allowed=None,
        mutation_lock=None,
    ) -> bool:
        wrote = await original_write(
            expected,
            target,
            still_allowed=still_allowed,
            mutation_lock=mutation_lock,
        )
        if wrote:
            service._automation.house_state = "away"
        return wrote

    sonos.set_volume_if_playback_unchanged = first_step_then_away

    completed = await service._ramp_owned_volume(35, steps=3, interval=0)

    assert completed is False
    assert len(sonos.volume_calls) == 1
    assert service._playing is False
    assert service._sonos_ambient_active is False
    assert sonos.evidence["transport_state"] == "PAUSED_PLAYBACK"
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_dnd_transition_pauses_active_ambient_on_loop_recheck(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    background = service._sonos_loop_task
    service._sonos_loop_task = None
    if background is not None:
        background.cancel()
        await asyncio.gather(background, return_exceptions=True)

    service._automation.is_dnd_active.return_value = True

    async def immediate_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(ambient_module.asyncio, "sleep", immediate_sleep)
    await service._sonos_ambient_loop()

    assert service._playing is False
    assert service._sonos_ambient_active is False
    assert sonos.evidence["transport_state"] == "PAUSED_PLAYBACK"
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_pause_resume_race_serializes_to_one_coherent_resumed_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    entered = asyncio.Event()
    release = asyncio.Event()
    original_pause = sonos.pause_if_playback_unchanged

    async def gated_pause(
        expected: dict,
        *,
        still_allowed=None,
        mutation_lock=None,
    ) -> bool:
        entered.set()
        await release.wait()
        return await original_pause(
            expected,
            still_allowed=still_allowed,
            mutation_lock=mutation_lock,
        )

    sonos.pause_if_playback_unchanged = gated_pause

    pause_task = asyncio.create_task(service.pause(learn=False))
    await entered.wait()
    resume_task = asyncio.create_task(service.resume())
    await asyncio.sleep(0)

    assert resume_task.done() is False

    release.set()
    await pause_task
    result = await resume_task
    await drain_sonos_tasks(service)

    assert result["status"] == "ok"
    assert service._playing is True
    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    assert sonos.evidence["transport_state"] == "PLAYING"
    assert len(sonos.play_calls) == 2
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert set(leases[0]["dimensions"]) == set(AMBIENT_AUDIO_DIMENSIONS)

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("volume", 9),
        ("mute", True),
    ],
)
async def test_immediate_rendering_takeover_before_pause_is_not_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: int | bool,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    # Physical/app takeover happens immediately before Pause, before the
    # background loop has had a chance to reconcile it.
    sonos.evidence[field] = value
    await service.pause(learn=False)

    assert service._sonos_paused_dimensions == {QUEUE_SOURCE, TRANSPORT}
    assert sonos.evidence["transport_state"] == "PAUSED_PLAYBACK"

    result = await service.resume()
    await drain_sonos_tasks(service)

    assert result["status"] == "ok"
    lease = (await authority.snapshot())["leases"][0]
    assert set(lease["dimensions"]) == {QUEUE_SOURCE, TRANSPORT}
    assert await service._ramp_owned_volume(30, steps=2, interval=0) is False
    assert sonos.volume_calls == []

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_shutdown_latch_rejects_reentrant_start_after_cancel_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    save_entered = asyncio.Event()
    save_release = asyncio.Event()

    async def gated_save() -> None:
        save_entered.set()
        await save_release.wait()

    service._save_config = AsyncMock(side_effect=gated_save)

    shutdown_task = asyncio.create_task(service.shutdown())
    await save_entered.wait()

    assert service._shutting_down is True
    before = len(sonos.play_calls)
    service._playing = True
    service._current_sound = "rain.mp3"
    service._spawn_sonos_task(service._start_sonos_ambient())
    await asyncio.sleep(0)

    assert len(sonos.play_calls) == before
    assert not [
        task
        for task in service._pending_sonos_tasks
        if not task.done()
    ]

    save_release.set()
    await shutdown_task

    assert (await authority.snapshot())["leases"] == []
    assert sonos.evidence["transport_state"] == "PLAYING"


@pytest.mark.asyncio
async def test_mute_takeover_during_volume_write_yields_volume_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    original_write = sonos.set_volume_if_playback_unchanged

    async def write_then_mute(
        expected: dict,
        target: int,
        *,
        still_allowed=None,
        mutation_lock=None,
    ) -> bool:
        wrote = await original_write(
            expected,
            target,
            still_allowed=still_allowed,
            mutation_lock=mutation_lock,
        )
        if wrote:
            sonos.evidence["mute"] = True
        return wrote

    sonos.set_volume_if_playback_unchanged = write_then_mute

    completed = await service._ramp_owned_volume(30, steps=2, interval=0)

    assert completed is False
    assert sonos.evidence["mute"] is True
    assert len(sonos.volume_calls) == 1
    lease = (await authority.snapshot())["leases"][0]
    assert set(lease["dimensions"]) == {QUEUE_SOURCE, TRANSPORT}

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_mute_takeover_during_source_swap_yields_volume_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    wind_entry = deepcopy(service._sound_index["rain.mp3"])
    wind_entry["label"] = "Wind"
    service._sound_index["wind.mp3"] = wind_entry

    original_play = sonos.play_uri_if_unchanged

    async def play_then_mute(
        expected: dict,
        uri: str,
        *,
        volume: int | None = None,
        meta: str | None = None,
        force_radio: bool = False,
        still_allowed=None,
        mutation_lock=None,
    ) -> bool:
        played = await original_play(
            expected,
            uri,
            volume=volume,
            meta=meta,
            force_radio=force_radio,
            still_allowed=still_allowed,
            mutation_lock=mutation_lock,
        )
        if played:
            sonos.evidence["mute"] = True
        return played

    sonos.play_uri_if_unchanged = play_then_mute

    await service._swap_sonos_ambient("wind.mp3")

    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_uri is not None
    assert service._sonos_ambient_uri.endswith("/wind.mp3")
    assert sonos.evidence["mute"] is True
    lease = (await authority.snapshot())["leases"][0]
    assert set(lease["dimensions"]) == {QUEUE_SOURCE, TRANSPORT}
    assert service._sonos_owned_evidence["mute"] is True

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_shutdown_latch_wins_if_set_after_stop_reconcile_before_pause(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    original_run = authority.run_if_valid
    latched = False

    async def latch_before_pause(lease_id, dimensions, operation):
        nonlocal latched
        if (
            not latched
            and set(dimensions) == set({QUEUE_SOURCE, TRANSPORT})
        ):
            latched = True
            service._shutting_down = True
        return await original_run(lease_id, dimensions, operation)

    authority.run_if_valid = latch_before_pause

    await service._stop_sonos_ambient(reason="ambient_disabled")

    assert latched is True
    assert sonos.evidence["transport_state"] == "PLAYING"
    assert sonos.pause_calls == []
    assert service._sonos_paused_evidence is None
    assert service._sonos_paused_dimensions == frozenset()
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("volume", 8),
        ("mute", True),
    ],
)
async def test_rendering_takeover_during_pause_strips_volume_from_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: int | bool,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    original_pause = sonos.pause_if_playback_unchanged

    async def pause_then_render_change(
        expected: dict,
        *,
        still_allowed=None,
        mutation_lock=None,
    ) -> bool:
        paused = await original_pause(
            expected,
            still_allowed=still_allowed,
            mutation_lock=mutation_lock,
        )
        if paused:
            sonos.evidence[field] = value
        return paused

    sonos.pause_if_playback_unchanged = pause_then_render_change

    await service.pause(learn=False)

    assert sonos.evidence["transport_state"] == "PAUSED_PLAYBACK"
    assert service._sonos_paused_dimensions == {QUEUE_SOURCE, TRANSPORT}
    assert (await authority.snapshot())["leases"] == []

    result = await service.resume()
    await drain_sonos_tasks(service)

    assert result["status"] == "ok"
    lease = (await authority.snapshot())["leases"][0]
    assert set(lease["dimensions"]) == {QUEUE_SOURCE, TRANSPORT}
    assert await service._ramp_owned_volume(30, steps=2, interval=0) is False

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_swap_retries_source_only_when_volume_lease_is_invalidated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    wind_entry = deepcopy(service._sound_index["rain.mp3"])
    wind_entry["label"] = "Wind"
    service._sound_index["wind.mp3"] = wind_entry

    original_run = authority.run_if_valid
    invalidated = False

    async def invalidate_volume_before_full_swap(
        lease_id, dimensions, operation,
    ):
        nonlocal invalidated
        if (
            not invalidated
            and set(dimensions) == set(AMBIENT_AUDIO_DIMENSIONS)
        ):
            invalidated = True
            await authority.release(
                lease_id,
                dimensions=(VOLUME,),
                reason="test_manual_volume_race",
            )
            sonos.evidence["volume"] = 11
        return await original_run(lease_id, dimensions, operation)

    authority.run_if_valid = invalidate_volume_before_full_swap

    await service._swap_sonos_ambient("wind.mp3")

    assert invalidated is True
    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_uri is not None
    assert service._sonos_ambient_uri.endswith("/wind.mp3")
    assert sonos.evidence["volume"] == 11
    assert sonos.play_calls[-1][1] is None
    lease = (await authority.snapshot())["leases"][0]
    assert set(lease["dimensions"]) == {QUEUE_SOURCE, TRANSPORT}

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_queue_change_during_pause_destroys_resumable_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()

    original_pause = sonos.pause_if_playback_unchanged

    async def pause_then_replace_queue(
        expected: dict,
        *,
        still_allowed=None,
        mutation_lock=None,
    ) -> bool:
        paused = await original_pause(
            expected,
            still_allowed=still_allowed,
            mutation_lock=mutation_lock,
        )
        if paused:
            # Same URI, but a different queue generation is manual ownership.
            sonos.evidence["queue_update_id"] = "manual-replacement"
            sonos.evidence["queue_size"] = 1
        return paused

    sonos.pause_if_playback_unchanged = pause_then_replace_queue

    initial_play_calls = len(sonos.play_calls)
    await service.pause(learn=False)

    assert sonos.evidence["transport_state"] == "PAUSED_PLAYBACK"
    assert service._sonos_paused_evidence is None
    assert service._sonos_paused_dimensions == frozenset()
    assert (await authority.snapshot())["leases"] == []

    result = await service.resume()
    await drain_sonos_tasks(service)

    assert result["status"] == "ok"
    assert len(sonos.play_calls) == initial_play_calls
    assert service._sonos_ambient_active is False
    assert service._playing is False
    assert (await authority.snapshot())["leases"] == []
