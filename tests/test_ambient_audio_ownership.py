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

    async def get_playback_ownership_evidence(
        self, *, call_timeout: float | None = None,
    ) -> dict:
        del call_timeout
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


@pytest.mark.asyncio
async def test_ambient_start_waits_through_transitioning_until_playing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)

    original_play = sonos.play_uri_if_unchanged
    original_get = sonos.get_playback_ownership_evidence
    post_reads = 0

    async def delayed_play(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    async def staged_get(**_kwargs) -> dict:
        nonlocal post_reads
        if sonos.play_calls:
            post_reads += 1
            if post_reads >= 2:
                sonos.evidence["transport_state"] = "PLAYING"
        return await original_get()

    async def no_wait(_seconds: float) -> None:
        return None

    sonos.play_uri_if_unchanged = delayed_play
    sonos.get_playback_ownership_evidence = staged_get
    monkeypatch.setattr(ambient_module.asyncio, "sleep", no_wait)

    await service._start_sonos_ambient()

    assert post_reads >= 2
    assert service._sonos_ambient_active is True
    assert service._playing is True
    assert sonos.evidence["transport_state"] == "PLAYING"
    lease = (await authority.snapshot())["leases"][0]
    assert set(lease["dimensions"]) == set(AMBIENT_AUDIO_DIMENSIONS)

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_ambient_start_timeout_retains_lease_until_terminal_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)

    original_play = sonos.play_uri_if_unchanged

    async def stuck_transition(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    sonos.play_uri_if_unchanged = stuck_transition
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_START_VERIFY_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_START_VERIFY_POLL_SECONDS",
        0.001,
    )
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_PENDING_START_POLL_SECONDS",
        0.001,
    )

    await service._start_sonos_ambient()

    assert service._sonos_ambient_active is False
    assert service._playing is True
    assert service._sonos_ambient_pending is True
    assert service._sonos_pending_start_context is not None
    assert sonos.pause_calls == []
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert set(leases[0]["dimensions"]) == set(AMBIENT_AUDIO_DIMENSIONS)

    sonos.evidence["transport_state"] = "STOPPED"
    await drain_sonos_tasks(service)

    assert service._sonos_ambient_active is False
    assert service._playing is False
    assert service._sonos_ambient_pending is False
    assert service._sonos_pending_start_context is None
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_rendering_takeover_during_start_yields_only_volume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)

    original_play = sonos.play_uri_if_unchanged
    original_get = sonos.get_playback_ownership_evidence
    post_reads = 0

    async def delayed_play(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    async def staged_get(**_kwargs) -> dict:
        nonlocal post_reads
        if sonos.play_calls:
            post_reads += 1
            if post_reads == 1:
                sonos.evidence["volume"] = 11
            elif post_reads >= 2:
                sonos.evidence["transport_state"] = "PLAYING"
        return await original_get()

    async def no_wait(_seconds: float) -> None:
        return None

    sonos.play_uri_if_unchanged = delayed_play
    sonos.get_playback_ownership_evidence = staged_get
    monkeypatch.setattr(ambient_module.asyncio, "sleep", no_wait)

    await service._start_sonos_ambient()

    assert service._sonos_ambient_active is True
    assert sonos.evidence["transport_state"] == "PLAYING"
    assert sonos.evidence["volume"] == 11
    lease = (await authority.snapshot())["leases"][0]
    assert set(lease["dimensions"]) == {QUEUE_SOURCE, TRANSPORT}
    assert service._sonos_owned_evidence["volume"] == 11

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_ambient_start_yields_if_queue_fingerprint_changes_during_settle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)

    original_play = sonos.play_uri_if_unchanged
    original_get = sonos.get_playback_ownership_evidence
    post_reads = 0

    async def delayed_play(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    async def takeover_get(**_kwargs) -> dict:
        nonlocal post_reads
        if sonos.play_calls:
            post_reads += 1
            if post_reads == 1:
                sonos.evidence["queue_update_id"] = "manual-change"
                sonos.evidence["queue_size"] = 1
        return await original_get()

    sonos.play_uri_if_unchanged = delayed_play
    sonos.get_playback_ownership_evidence = takeover_get

    await service._start_sonos_ambient()

    assert service._sonos_ambient_active is False
    assert service._playing is False
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_ambient_pending_start_adopts_late_playing_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)

    original_play = sonos.play_uri_if_unchanged

    async def delayed_play(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    sonos.play_uri_if_unchanged = delayed_play
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_START_VERIFY_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_START_VERIFY_POLL_SECONDS",
        0.001,
    )
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_PENDING_START_POLL_SECONDS",
        0.001,
    )

    await service._start_sonos_ambient()

    assert service._sonos_ambient_active is False
    assert service._sonos_ambient_pending is True
    assert service._playing is True
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    lease_id = leases[0]["lease_id"]

    sonos.evidence["transport_state"] = "PLAYING"
    await drain_sonos_tasks(service)

    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    assert service._playing is True
    assert sonos.evidence["transport_state"] == "PLAYING"
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert leases[0]["lease_id"] == lease_id
    assert set(leases[0]["dimensions"]) == set(AMBIENT_AUDIO_DIMENSIONS)

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


def _configure_fast_pending_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_START_VERIFY_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_START_VERIFY_POLL_SECONDS",
        0.001,
    )
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_PENDING_START_POLL_SECONDS",
        0.001,
    )


@pytest.mark.asyncio
async def test_pending_start_evidence_outage_keeps_lease_until_playing_observed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged
    original_get = sonos.get_playback_ownership_evidence
    observable = False

    async def delayed_play(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    async def outage_after_play(**_kwargs):
        if sonos.play_calls and not observable:
            return None
        return await original_get()

    sonos.play_uri_if_unchanged = delayed_play
    sonos.get_playback_ownership_evidence = outage_after_play
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()

    leases = (await authority.snapshot())["leases"]
    assert service._sonos_ambient_pending is True
    assert len(leases) == 1
    lease_id = leases[0]["lease_id"]

    observable = True
    sonos.evidence["transport_state"] = "PLAYING"
    await drain_sonos_tasks(service)

    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert leases[0]["lease_id"] == lease_id

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_pause_during_pending_start_preserves_exact_resume_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged
    play_count = 0

    async def first_start_delayed(*args, **kwargs) -> bool:
        nonlocal play_count
        played = await original_play(*args, **kwargs)
        if played:
            play_count += 1
            if play_count == 1:
                sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    sonos.play_uri_if_unchanged = first_start_delayed
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()
    assert service._sonos_ambient_pending is True

    await service.pause()
    await drain_sonos_tasks(service)

    assert service._playing is False
    assert service._sonos_ambient_pending is False
    assert sonos.evidence["transport_state"] == "PAUSED_PLAYBACK"
    assert service._sonos_paused_evidence is not None
    assert service._sonos_paused_uri is not None
    assert (await authority.snapshot())["leases"] == []

    await service.resume()
    await drain_sonos_tasks(service)

    assert service._sonos_ambient_active is True
    assert service._playing is True
    assert sonos.evidence["transport_state"] == "PLAYING"

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_stop_during_pending_start_pauses_before_releasing_without_resume_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged

    async def delayed_play(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    sonos.play_uri_if_unchanged = delayed_play
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()
    assert service._sonos_ambient_pending is True

    await service.stop()
    await drain_sonos_tasks(service)

    assert service._current_sound is None
    assert service._playing is False
    assert service._sonos_ambient_pending is False
    assert sonos.evidence["transport_state"] == "PAUSED_PLAYBACK"
    assert sonos.pause_calls
    assert service._sonos_paused_evidence is None
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_new_play_replaces_pending_source_under_same_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    (Path(ambient_module.SHORT_AMBIENT_DIR) / "wind.mp3").write_bytes(b"")
    service.scan_sounds()

    original_play = sonos.play_uri_if_unchanged
    play_count = 0

    async def first_start_delayed(*args, **kwargs) -> bool:
        nonlocal play_count
        played = await original_play(*args, **kwargs)
        if played:
            play_count += 1
            if play_count == 1:
                sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    sonos.play_uri_if_unchanged = first_start_delayed
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()
    leases = (await authority.snapshot())["leases"]
    assert service._sonos_ambient_pending is True
    assert len(leases) == 1
    lease_id = leases[0]["lease_id"]

    result = await service.play("wind.mp3", source="manual")
    assert result["status"] == "ok"
    await drain_sonos_tasks(service)

    assert service._current_sound == "wind.mp3"
    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    assert len(sonos.play_calls) == 2
    assert sonos.play_calls[-1][0].endswith("/wind.mp3")
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert leases[0]["lease_id"] == lease_id

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_shutdown_during_pending_start_releases_without_sonos_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged

    async def delayed_play(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    sonos.play_uri_if_unchanged = delayed_play
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()

    assert service._sonos_ambient_pending is True
    assert sonos.pause_calls == []
    await service.shutdown()

    assert service._shutting_down is True
    assert service._sonos_ambient_pending is False
    assert service._sonos_pending_start_context is None
    assert sonos.pause_calls == []
    assert sonos.evidence["transport_state"] == "TRANSITIONING"
    assert (await authority.snapshot())["leases"] == []



@pytest.mark.asyncio
async def test_pending_start_stale_stopped_target_keeps_lease_until_playing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Accepted Play may expose the target URI before transport leaves STOPPED."""
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged

    async def target_uri_but_stale_stopped(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "STOPPED"
        return played

    sonos.play_uri_if_unchanged = target_uri_but_stale_stopped
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()

    assert service._sonos_ambient_active is False
    assert service._sonos_ambient_pending is True
    assert service._playing is True
    assert sonos.evidence["transport_state"] == "STOPPED"
    assert sonos.evidence["current_uri"].endswith("/rain.mp3")
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    lease_id = leases[0]["lease_id"]
    assert set(leases[0]["dimensions"]) == set(AMBIENT_AUDIO_DIMENSIONS)

    sonos.evidence["transport_state"] = "PLAYING"
    await drain_sonos_tasks(service)

    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    assert service._playing is True
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert leases[0]["lease_id"] == lease_id

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )


@pytest.mark.asyncio
async def test_pending_start_stale_preflight_reads_keep_lease_until_target_visible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Evidence may lag the accepted Play and still report the full preflight."""
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_get = sonos.get_playback_ownership_evidence
    preflight = deepcopy(sonos.evidence)
    expose_target = False

    async def lagged_get(**_kwargs) -> dict:
        if sonos.play_calls and not expose_target:
            return deepcopy(preflight)
        return await original_get()

    sonos.get_playback_ownership_evidence = lagged_get
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()

    assert sonos.evidence["transport_state"] == "PLAYING"
    assert service._sonos_ambient_active is False
    assert service._sonos_ambient_pending is True
    assert service._playing is True
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    lease_id = leases[0]["lease_id"]

    expose_target = True
    await drain_sonos_tasks(service)

    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    assert service._playing is True
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert leases[0]["lease_id"] == lease_id

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )



@pytest.mark.asyncio
async def test_pending_monitor_exception_rearms_reconciler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged

    async def delayed_play(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    sonos.play_uri_if_unchanged = delayed_play
    _configure_fast_pending_start(monkeypatch)
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_PENDING_START_POLL_SECONDS",
        0.02,
    )

    await service._start_sonos_ambient()
    assert service._sonos_ambient_pending is True
    assert service._sonos_lease_id is not None

    original_read = service._read_start_evidence
    failures = 0

    async def fail_once(timeout_seconds: float):
        nonlocal failures
        if failures == 0:
            failures += 1
            raise RuntimeError("synthetic pending observer failure")
        return await original_read(timeout_seconds)

    service._read_start_evidence = fail_once
    sonos.evidence["transport_state"] = "PLAYING"

    for _ in range(100):
        if service._sonos_ambient_active:
            break
        await asyncio.sleep(0.01)

    assert failures == 1
    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    assert service._sonos_pending_start_context is None
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert leases[0]["lease_id"] == service._sonos_lease_id

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )



@pytest.mark.asyncio
async def test_stop_during_stale_preflight_pending_start_retires_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged
    preflight = deepcopy(sonos.evidence)

    async def accepted_but_preflight_still_visible(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence = deepcopy(preflight)
        return played

    sonos.play_uri_if_unchanged = accepted_but_preflight_still_visible
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()
    assert service._sonos_ambient_pending is True
    assert service._sonos_lease_id is not None

    await service.stop()
    await drain_sonos_tasks(service)

    assert service._current_sound is None
    assert service._playing is False
    assert service._sonos_ambient_pending is False
    assert service._sonos_pending_start_context is None
    assert sonos.pause_calls
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_stop_during_stale_target_stopped_pending_start_retires_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged

    async def accepted_target_still_stopped(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence["transport_state"] = "STOPPED"
        return played

    sonos.play_uri_if_unchanged = accepted_target_still_stopped
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()
    assert service._sonos_ambient_pending is True
    assert service._sonos_lease_id is not None

    await service.stop()
    await drain_sonos_tasks(service)

    assert service._current_sound is None
    assert service._playing is False
    assert service._sonos_ambient_pending is False
    assert service._sonos_pending_start_context is None
    assert sonos.pause_calls
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_pause_during_stale_preflight_pending_start_retires_without_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged
    preflight = deepcopy(sonos.evidence)

    async def accepted_but_preflight_still_visible(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence = deepcopy(preflight)
        return played

    sonos.play_uri_if_unchanged = accepted_but_preflight_still_visible
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()
    assert service._sonos_ambient_pending is True

    await service.pause()
    await drain_sonos_tasks(service)

    assert service._playing is False
    assert service._sonos_ambient_pending is False
    assert service._sonos_pending_start_context is None
    assert service._sonos_paused_evidence is None
    assert sonos.pause_calls
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_resume_stale_exact_paused_preflight_keeps_lease_until_playing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    await service._start_sonos_ambient()
    await service.pause()

    paused_preflight = deepcopy(sonos.evidence)
    assert paused_preflight["transport_state"] == "PAUSED_PLAYBACK"
    assert service._sonos_paused_evidence is not None

    original_play = sonos.play_uri_if_unchanged

    async def accepted_resume_but_paused_still_visible(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played:
            sonos.evidence = deepcopy(paused_preflight)
        return played

    sonos.play_uri_if_unchanged = accepted_resume_but_paused_still_visible
    _configure_fast_pending_start(monkeypatch)

    result = await service.resume()
    assert result["status"] == "ok"

    for _ in range(100):
        if service._sonos_pending_start_context is not None:
            break
        await asyncio.sleep(0.005)

    assert service._sonos_ambient_active is False
    assert service._sonos_ambient_pending is True
    assert service._sonos_lease_id is not None
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    lease_id = leases[0]["lease_id"]

    sonos.evidence["transport_state"] = "PLAYING"
    await drain_sonos_tasks(service)

    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert leases[0]["lease_id"] == lease_id

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )



@pytest.mark.asyncio
async def test_new_play_during_pending_stop_cleanup_restarts_fresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    (Path(ambient_module.SHORT_AMBIENT_DIR) / "wind.mp3").write_bytes(b"")
    service.scan_sounds()

    original_play = sonos.play_uri_if_unchanged

    async def first_start_delayed(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played and len(sonos.play_calls) == 1:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    sonos.play_uri_if_unchanged = first_start_delayed
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()
    assert service._sonos_ambient_pending is True

    original_pause = service._pause_pending_start_exact
    pause_completed = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def pause_then_hold(*, lease_id: str, evidence: dict) -> bool:
        paused = await original_pause(lease_id=lease_id, evidence=evidence)
        pause_completed.set()
        await release_cleanup.wait()
        return paused

    service._pause_pending_start_exact = pause_then_hold

    await service.stop()
    await asyncio.wait_for(pause_completed.wait(), timeout=1.0)

    result = await service.play("wind.mp3", source="manual")
    assert result["status"] == "ok"
    assert service._current_sound == "wind.mp3"
    assert service._playing is True

    release_cleanup.set()
    for _ in range(200):
        if (
            service._sonos_ambient_active
            and service._sonos_ambient_uri
            and service._sonos_ambient_uri.endswith("/wind.mp3")
        ):
            break
        await asyncio.sleep(0.01)

    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    assert service._current_sound == "wind.mp3"
    assert service._sonos_ambient_uri.endswith("/wind.mp3")
    assert len(sonos.play_calls) == 2
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert set(leases[0]["dimensions"]) == set(AMBIENT_AUDIO_DIMENSIONS)

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )



@pytest.mark.asyncio
async def test_resume_during_pending_pause_cleanup_replays_same_source_under_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged

    async def first_start_delayed(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played and len(sonos.play_calls) == 1:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    sonos.play_uri_if_unchanged = first_start_delayed
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()
    assert service._sonos_ambient_pending is True
    original_lease = service._sonos_lease_id
    assert original_lease is not None

    original_pause = service._pause_pending_start_exact
    pause_completed = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def pause_then_hold(*, lease_id: str, evidence: dict) -> bool:
        paused = await original_pause(lease_id=lease_id, evidence=evidence)
        pause_completed.set()
        await release_cleanup.wait()
        return paused

    service._pause_pending_start_exact = pause_then_hold

    await service.pause()
    await asyncio.wait_for(pause_completed.wait(), timeout=1.0)

    result = await service.resume()
    assert result["status"] == "ok"
    assert service._current_sound == "rain.mp3"
    assert service._playing is True

    release_cleanup.set()
    for _ in range(200):
        if service._sonos_ambient_active:
            break
        await asyncio.sleep(0.01)

    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    assert service._sonos_lease_id == original_lease
    assert service._sonos_ambient_uri.endswith("/rain.mp3")
    assert len(sonos.play_calls) == 2
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert leases[0]["lease_id"] == original_lease

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )



@pytest.mark.asyncio
async def test_verifier_carries_transient_progress_into_pending_terminal_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_get = sonos.get_playback_ownership_evidence
    reads_after_play = 0

    async def staged_get(**_kwargs) -> dict:
        nonlocal reads_after_play
        current = await original_get()
        if not sonos.play_calls:
            return current
        reads_after_play += 1
        current["transport_state"] = (
            "TRANSITIONING" if reads_after_play == 1 else "STOPPED"
        )
        sonos.evidence["transport_state"] = current["transport_state"]
        return current

    sonos.get_playback_ownership_evidence = staged_get
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_START_VERIFY_TIMEOUT_SECONDS",
        0.02,
    )
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_START_VERIFY_POLL_SECONDS",
        0.001,
    )
    monkeypatch.setattr(
        ambient_module,
        "AMBIENT_PENDING_START_POLL_SECONDS",
        0.001,
    )

    await service._start_sonos_ambient()

    for _ in range(100):
        if service._sonos_lease_id is None:
            break
        await asyncio.sleep(0.005)

    assert reads_after_play >= 2
    assert service._sonos_lease_id is None
    assert service._sonos_ambient_pending is False
    assert service._sonos_ambient_active is False
    assert service._playing is False
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_resume_during_pending_cleanup_survives_post_pause_evidence_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = await make_authority()
    service, sonos = make_service(monkeypatch, tmp_path, authority)
    original_play = sonos.play_uri_if_unchanged

    async def first_start_delayed(*args, **kwargs) -> bool:
        played = await original_play(*args, **kwargs)
        if played and len(sonos.play_calls) == 1:
            sonos.evidence["transport_state"] = "TRANSITIONING"
        return played

    sonos.play_uri_if_unchanged = first_start_delayed
    _configure_fast_pending_start(monkeypatch)

    await service._start_sonos_ambient()
    assert service._sonos_ambient_pending is True
    original_lease = service._sonos_lease_id
    assert original_lease is not None

    original_pause = service._pause_pending_start_exact
    original_read = service._read_start_evidence
    pause_completed = asyncio.Event()
    release_cleanup = asyncio.Event()
    reads_after_patch = 0

    async def staged_read(timeout_seconds: float):
        nonlocal reads_after_patch
        reads_after_patch += 1
        if reads_after_patch == 2:
            return None
        return await original_read(timeout_seconds)

    async def pause_then_hold(*, lease_id: str, evidence: dict) -> bool:
        paused = await original_pause(lease_id=lease_id, evidence=evidence)
        pause_completed.set()
        await release_cleanup.wait()
        return paused

    service._read_start_evidence = staged_read
    service._pause_pending_start_exact = pause_then_hold

    await service.pause()
    await asyncio.wait_for(pause_completed.wait(), timeout=1.0)

    result = await service.resume()
    assert result["status"] == "ok"
    release_cleanup.set()

    for _ in range(200):
        if service._sonos_ambient_active:
            break
        await asyncio.sleep(0.01)

    assert reads_after_patch >= 3
    assert service._sonos_ambient_active is True
    assert service._sonos_ambient_pending is False
    assert service._sonos_lease_id == original_lease
    assert len(sonos.play_calls) == 2
    leases = (await authority.snapshot())["leases"]
    assert len(leases) == 1
    assert leases[0]["lease_id"] == original_lease

    await service._stop_sonos_ambient(
        reason="test_cleanup",
        pause_owned=False,
    )
