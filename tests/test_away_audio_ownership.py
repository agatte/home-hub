"""Departure ownership races: actual authority/Sonos, disposable device only."""
import asyncio
import threading
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from backend.services.audio_ownership import (
    INTERRUPTION, MANUAL_TRANSPORT_DIMENSIONS, QUEUE_SOURCE, TRANSPORT, VOLUME,
    AudioOwnershipService,
)
from backend.services.away_manager import AWAY_CONFIG_KEY, AWAY_STATE_KEY
from backend.services.music_mapper import MusicMapper
from backend.services.music_learning_provenance import MODE_AUTOPLAY_OWNER, MODE_AUTOPLAY_PURPOSE
from backend.services.sonos_service import SonosService
from backend.services.tts_service import TTSService
from tests.test_away_manager import _make_manager
from tests.test_tts_duck_resume import OwnedTTSFakeSonos, _owned_evidence

pytestmark = pytest.mark.asyncio


class Device:
    def __init__(self, state="PLAYING"):
        self.evidence = _owned_evidence()
        self.evidence["transport_state"] = state
        self.writes = []

    def pause(self):
        self.writes.append("pause")
        self.evidence["transport_state"] = "PAUSED_PLAYBACK"

    def play(self):
        self.writes.append("play")
        self.evidence["transport_state"] = "PLAYING"


def setup(*, state="PLAYING", enabled=True, connected=True):
    manager, engine, settings, hue, _, tts, notifier = _make_manager()
    settings.store[AWAY_CONFIG_KEY] = {"pause_music_on_leave": enabled}
    authority = AudioOwnershipService(
        setting_loader=settings.load, setting_saver=settings.save,
    )
    manager._audio_ownership = authority
    sonos = SonosService()
    device = Device(state)
    sonos._device = device
    sonos._connected = connected
    sonos._playback_ownership_evidence_sync = lambda: deepcopy(device.evidence)
    manager._sonos_getter = lambda: sonos
    return manager, authority, sonos, device, engine, settings, hue, notifier


async def manual_play(authority, sonos):
    return await authority.run_manual(
        MANUAL_TRANSPORT_DIMENSIONS, source="dashboard", reason="play",
        operation=sonos.play,
    )


@pytest.mark.parametrize("state,enabled,connected,expected", [
    ("PLAYING", True, True, ["pause"]),
    ("STOPPED", True, True, []),
    ("PAUSED_PLAYBACK", True, True, []),
    ("PLAYING", False, True, []),
    ("PLAYING", True, False, []),
])
async def test_departure_policy(state, enabled, connected, expected):
    manager, authority, sonos, device, engine, settings, hue, notifier = setup(
        state=state, enabled=enabled, connected=connected,
    )
    await manager.handle_event("leave", "test")
    assert device.writes == expected
    assert settings.store[AWAY_STATE_KEY]["away"]
    assert engine._away_hold
    hue.set_light.assert_awaited_once()
    notifier.emit_alert.assert_awaited_once()
    assert (await authority.snapshot())["leases"] == []
    await manager.close()


async def test_duplicate_callback_and_geofence_do_not_pause_manual_away_play():
    manager, authority, sonos, device, engine, _, _, notifier = setup()
    mapper = MusicMapper(sonos, AsyncMock(), audio_ownership=authority)
    mapper.set_automation(engine)
    mapper.set_away_manager(manager)
    await asyncio.gather(
        manager.handle_event("leave", "geofence"), mapper.on_mode_change("away"),
        mapper.on_mode_change("away"),
    )
    assert device.writes == ["pause"]
    notifier.emit_alert.assert_awaited_once()
    await manual_play(authority, sonos)
    await mapper.on_mode_change("away")
    await manager.handle_event("leave", "duplicate")
    assert device.writes == ["pause", "play"]
    await manager.close()


@pytest.mark.parametrize("where", ["persistence", "status", "authority"])
async def test_new_manual_play_invalidates_departure_before_awaits(where):
    manager, authority, sonos, device, _, settings, _, _ = setup()
    started, release = asyncio.Event(), asyncio.Event()
    save = settings.save
    read = sonos.get_playback_ownership_evidence
    run = authority.run_departure_pause

    async def gated_save(key, value):
        if key == AWAY_STATE_KEY:
            started.set()
            await release.wait()
        await save(key, value)

    async def gated_read():
        evidence = await read()
        started.set()
        await release.wait()
        return evidence

    async def gated_run(*args):
        started.set()
        await release.wait()
        return await run(*args)

    if where == "persistence":
        manager._save_setting = gated_save
    elif where == "status":
        sonos.get_playback_ownership_evidence = gated_read
    else:
        authority.run_departure_pause = gated_run
    leave = asyncio.create_task(manager.handle_event("leave", "test"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert await manual_play(authority, sonos)
    finally:
        release.set()
        await leave
    assert device.writes == ["play"]
    await manager.close()


async def test_manual_intent_during_final_sync_proof_wins_before_pause():
    manager, authority, sonos, device, _, _, _, _ = setup()
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    reads = 0

    def proof():
        nonlocal reads
        reads += 1
        result = deepcopy(device.evidence)
        if reads == 2:
            loop.call_soon_threadsafe(started.set)
            assert release.wait(5)
        return result

    sonos._playback_ownership_evidence_sync = proof
    leave = asyncio.create_task(manager.handle_event("leave", "test"))
    manual = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        revision = authority.capture_manual_intent()
        manual = asyncio.create_task(manual_play(authority, sonos))
        # Observe intent at entry, while the manual device write awaits the lock.
        while authority.capture_manual_intent() == revision:
            await asyncio.sleep(0)
        assert device.writes == []
    finally:
        release.set()
        await asyncio.gather(leave, *([manual] if manual else []))
    assert device.writes == ["play"]
    await manager.close()


@pytest.mark.parametrize("new_departure", [False, True])
async def test_home_supersedes_pending_departure_without_resume(new_departure):
    manager, authority, sonos, device, _, _, _, _ = setup()
    started, release = asyncio.Event(), asyncio.Event()
    read = sonos.get_playback_ownership_evidence
    calls = 0

    async def gated_read():
        nonlocal calls
        calls += 1
        evidence = await read()
        if calls == 1:
            started.set()
            await release.wait()
        return evidence

    sonos.get_playback_ownership_evidence = gated_read
    leave = asyncio.create_task(manager.handle_event("leave", "old"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        await manager.handle_event("arrive", "test")
        assert device.writes == []
        if new_departure:
            await manager.handle_event("leave", "new")
            # Same physical state again must not make the old generation eligible.
            await manual_play(authority, sonos)
    finally:
        release.set()
        await leave
    assert device.writes == (["pause", "play"] if new_departure else [])
    await manager.close()


@pytest.mark.parametrize("failure", [TimeoutError(), RuntimeError("offline")])
async def test_failed_read_keeps_durable_away_lights_and_one_notification(failure):
    manager, _, sonos, device, engine, settings, hue, notifier = setup()
    sonos.get_playback_ownership_evidence = AsyncMock(side_effect=failure)
    await manager.handle_event("leave", "test")
    assert settings.store[AWAY_STATE_KEY]["away"] and engine._away_hold
    assert device.writes == []
    hue.set_light.assert_awaited_once()
    notifier.emit_alert.assert_awaited_once()
    await manager.close()


@pytest.mark.parametrize("field,value", [
    ("transport_state", "STOPPED"), ("current_uri", "manual-source"),
    ("queue_update_id", "new-generation"),
])
async def test_final_device_proof_change_refuses_pause(field, value):
    manager, authority, sonos, device, _, _, _, _ = setup()
    run = authority.run_departure_pause

    async def changed(*args):
        device.evidence[field] = value
        return await run(*args)

    authority.run_departure_pause = changed
    await manager.handle_event("leave", "test")
    assert device.writes == []
    await manager.close()


@pytest.mark.parametrize("enabled,home_before_finish,semantic", [(True, False, False), (False, False, False), (False, True, False), (True, False, True), (False, False, True)])
async def test_tts_overlap_never_restores_pre_departure_transport(
    tmp_path, monkeypatch, enabled, home_before_finish, semantic,
):
    manager, authority, _, _, _, _, _, _ = setup(enabled=enabled)
    sonos = OwnedTTSFakeSonos()
    manager._sonos_getter = lambda: sonos
    paused = []

    async def pause(expected, *, still_allowed):
        if not still_allowed() or sonos.evidence != expected:
            return False
        sonos.evidence["transport_state"] = "PAUSED_PLAYBACK"
        paused.append(True)
        return True

    sonos.pause_if_playback_unchanged = pause
    started, release = asyncio.Event(), asyncio.Event()

    async def gated_sleep(delay):
        if delay >= 60:
            return
        started.set()
        await release.wait()

    monkeypatch.setattr("backend.services.tts_service.asyncio.sleep", gated_sleep)
    tts = TTSService(sonos, tmp_path, "127.0.0.1", audio_ownership=authority)
    tts._generate_audio = AsyncMock(return_value=tmp_path / "test.mp3")
    speaking = asyncio.create_task(tts.speak("hello", volume=60))
    try:
        await asyncio.wait_for(started.wait(), 2)
        if semantic:
            before = await authority.snapshot()
            await manager.on_audio_mode_change("away")
            assert await authority.snapshot() == before
            assert not authority._lifecycle_away and not manager.away
        else:
            await manager.handle_event("leave", "test")
        if home_before_finish:
            manager._tts_getter = lambda: None
            await manager.handle_event("arrive", "test")
    finally:
        release.set()
        await speaking
    assert paused == ([True] if enabled and not semantic else [])
    assert sonos.restore_calls == ([(False, True), (True, False)] if semantic else [(False, True)])
    assert sonos.evidence["volume"] == 20
    if semantic:
        assert not sonos.evidence["current_uri"].endswith("test.mp3")
    else:
        assert sonos.evidence["current_uri"].endswith("test.mp3")
    assert (await authority.snapshot())["leases"] == []
    await tts.close()
    await manager.close()


async def test_lifecycle_retires_only_transport_and_restart_does_not_pause():
    manager, authority, sonos, device, _, settings, _, _ = setup(enabled=False)
    lease = await authority.acquire(
        owner="mapper", purpose="owned", dimensions=(QUEUE_SOURCE, TRANSPORT, VOLUME),
    )
    await manager.handle_event("leave", "test")
    assert await authority.is_valid(lease["lease_id"], (QUEUE_SOURCE, VOLUME))
    assert not await authority.is_valid(lease["lease_id"], (TRANSPORT,))
    restarted, *_ = _make_manager(settings=settings)
    fresh = AudioOwnershipService(setting_loader=settings.load, setting_saver=settings.save)
    restarted._audio_ownership = fresh
    restarted._sonos_getter = lambda: sonos
    await restarted.load_state()
    assert fresh._lifecycle_away
    assert not await fresh.is_valid(lease["lease_id"], (TRANSPORT,))
    assert device.writes == []
    await restarted.handle_event("leave", "duplicate")
    assert device.writes == []
    await restarted.close()
    await manager.close()


@pytest.mark.parametrize("end", ["timeout", "cancel", "failure"])
async def test_pause_worker_settlement_preserves_manual_order(end, monkeypatch):
    manager, authority, sonos, device, _, _, hue, notifier = setup()
    started = asyncio.Event()
    release = threading.Event()
    cancellation_seen = asyncio.Event()
    loop = asyncio.get_running_loop()
    shield = asyncio.shield
    mutation = sonos._safe_mutation_call

    async def observed_shield(worker):
        try:
            return await shield(worker)
        except asyncio.CancelledError:
            cancellation_seen.set()
            raise

    async def bounded_mutation(fn, *args, **kwargs):
        if fn == sonos._pause_if_playback_unchanged_sync and end == "timeout":
            kwargs["call_timeout"] = 0.001
        return await mutation(fn, *args, **kwargs)

    monkeypatch.setattr(asyncio, "shield", observed_shield)
    sonos._safe_mutation_call = bounded_mutation

    def slow_pause():
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        device.writes.append("pause_settled")
        if end == "failure":
            raise RuntimeError("fake pause failure")
        device.evidence["transport_state"] = "PAUSED_PLAYBACK"

    device.pause = slow_pause
    leave = asyncio.create_task(manager.handle_event("leave", "test"))
    manual = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        if end == "cancel":
            leave.cancel()
        if end == "timeout":
            await asyncio.wait_for(cancellation_seen.wait(), 2)
        manual = asyncio.create_task(manual_play(authority, sonos))
        revision = authority.capture_manual_intent()
        while authority.capture_manual_intent() == revision:
            await asyncio.sleep(0)
        assert device.writes == []
        assert not leave.done()
        assert not manual.done()
        hue.set_light.assert_awaited_once()
        notifier.emit_alert.assert_awaited_once()
    finally:
        release.set()
        results = await asyncio.gather(leave, *([manual] if manual else []), return_exceptions=True)
    assert results[-1] is True
    assert device.writes == ["pause_settled", "play"]
    assert (await authority.snapshot())["leases"] == []
    await manager.close()


async def test_audio_provenance_storage_failure_does_not_abort_lights():
    manager, authority, _, device, engine, settings, hue, notifier = setup()
    authority._save_setting = AsyncMock(side_effect=RuntimeError("storage unavailable"))
    await manager.handle_event("leave", "test")
    assert settings.store[AWAY_STATE_KEY]["away"] and engine._away_hold
    assert device.writes == ["pause"]
    hue.set_light.assert_awaited_once()
    notifier.emit_alert.assert_awaited_once()
    await manager.close()


async def test_dnd_callback_and_sleeping_do_not_create_departure():
    manager, authority, sonos, device, engine, _, _, _ = setup()
    mapper = MusicMapper(sonos, AsyncMock(), audio_ownership=authority)
    mapper.set_automation(engine)
    mapper.set_away_manager(manager)
    engine._dnd = True
    await mapper.on_mode_change("away")
    assert not manager.away and device.writes == []
    engine._dnd = False
    await mapper.on_mode_change("sleeping")
    assert not manager.away and device.writes == []
    # Explicit occupancy departure remains authoritative during DND/Sleeping.
    engine._mode = "sleeping"
    engine._dnd = True
    await manager.handle_event("leave", "test")
    assert device.writes == ["pause"]
    await manager.close()


async def test_legacy_mode_audio_entry_shares_departure_without_inventing_occupancy():
    manager, authority, sonos, device, engine, settings, hue, notifier = setup()
    mapper = MusicMapper(sonos, AsyncMock(), audio_ownership=authority)
    mapper.set_automation(engine)
    mapper.set_away_manager(manager)
    await mapper.on_mode_change("away")
    assert device.writes == ["pause"]
    assert not manager.away and not engine._away_hold
    assert AWAY_STATE_KEY not in settings.store
    hue.set_light.assert_not_awaited()
    notifier.emit_alert.assert_not_awaited()
    await manual_play(authority, sonos)
    await manager.handle_event("leave", "geofence")
    assert device.writes == ["pause", "play", "pause"]
    assert manager.away and settings.store[AWAY_STATE_KEY]["away"]
    await manager.handle_event("arrive", "test")
    await mapper.on_mode_change("working")
    assert device.writes == ["pause", "play", "pause"]
    await manual_play(authority, sonos)
    await mapper.on_mode_change("away")
    assert device.writes == ["pause", "play", "pause", "play", "pause"]
    await manager.close()


async def test_lifecycle_supersedes_opportunistic_transport_without_touching_volume():
    manager, authority, _, _, _, _, _, _ = setup(enabled=False)
    transport = await authority.capture_opportunistic((TRANSPORT,))
    volume = await authority.capture_opportunistic((VOLUME,))
    await manager.handle_event("leave", "test")
    operation = AsyncMock(return_value=True)
    assert await authority.run_if_opportunistic(transport, operation) == (False, None)
    operation.assert_not_awaited()
    assert await authority.run_if_opportunistic(volume, operation) == (True, True)
    await manager.close()


async def test_delayed_old_pause_claim_cannot_overwrite_new_transition_claim():
    manager, authority, sonos, device, _, _, _, _ = setup()
    started, release = asyncio.Event(), asyncio.Event()
    pause = manager._pause_departure
    calls = 0

    async def delayed(token):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        await pause(token)

    manager._pause_departure = delayed
    old = asyncio.create_task(manager.handle_event("leave", "old"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        await manager.handle_event("arrive", "test")
        await manager.handle_event("leave", "new")
    finally:
        release.set()
        await old
    await manual_play(authority, sonos)
    await manager.on_audio_mode_change("away")
    assert device.writes == ["pause", "play"]
    await manager.close()


@pytest.mark.parametrize("dimension", [VOLUME, INTERRUPTION])
@pytest.mark.parametrize("where", ["status", "persistence"])
async def test_non_transport_manual_adjustment_does_not_cancel_pause(dimension, where):
    manager, authority, sonos, device, _, settings, _, _ = setup()
    started, release = asyncio.Event(), asyncio.Event()
    read, save = sonos.get_playback_ownership_evidence, settings.save

    async def gated_read():
        started.set()
        await release.wait()
        return await read()

    async def gated_save(key, value):
        if key == AWAY_STATE_KEY:
            started.set()
            await release.wait()
        await save(key, value)

    if where == "status":
        sonos.get_playback_ownership_evidence = gated_read
    else:
        manager._save_setting = gated_save
    leave = asyncio.create_task(manager.handle_event("leave", "test"))
    async def adjust():
        device.evidence["volume"] = 37
    try:
        await asyncio.wait_for(started.wait(), 2)
        await authority.run_manual((dimension,), source="dashboard", reason="adjust", operation=adjust)
    finally:
        release.set()
        await leave
    assert device.writes == ["pause"]
    assert device.evidence["volume"] == 37
    await manager.close()


async def test_ambiguous_track_surrender_during_preflight_is_not_explicit_play():
    manager, authority, sonos, device, _, _, _, _ = setup()
    lease = await authority.acquire(owner="mapper", purpose="test", dimensions=(QUEUE_SOURCE, TRANSPORT))
    started, release = asyncio.Event(), asyncio.Event()
    read = sonos.get_playback_ownership_evidence
    async def gated_read():
        started.set()
        await release.wait()
        return await read()
    sonos.get_playback_ownership_evidence = gated_read
    leave = asyncio.create_task(manager.handle_event("leave", "test"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        revision = authority.capture_manual_intent()
        device.evidence["current_uri"] = "next-natural-track"
        await authority.invalidate_manual(MANUAL_TRANSPORT_DIMENSIONS, source="sonos_poll", reason="ambiguous_track_boundary")
        assert authority.capture_manual_intent() == revision
        assert not await authority.is_valid(lease["lease_id"], (QUEUE_SOURCE,))
    finally:
        release.set()
        await leave
    assert device.writes == ["pause"]
    await manager.close()


async def test_semantic_away_preserves_all_leases_and_durable_provenance():
    manager, authority, sonos, device, engine, settings, hue, notifier = setup(state="STOPPED")
    mapper = MusicMapper(sonos, AsyncMock(), audio_ownership=authority)
    mapper.set_away_manager(manager)
    lease = await authority.acquire(owner=MODE_AUTOPLAY_OWNER, purpose=MODE_AUTOPLAY_PURPOSE, dimensions=(QUEUE_SOURCE, TRANSPORT, VOLUME, INTERRUPTION), metadata={"mode": "working"})
    before = await authority.snapshot()
    stored = deepcopy(settings.store)
    await mapper.on_mode_change("away")
    assert await authority.snapshot() == before
    assert settings.store == stored
    assert await authority.is_valid(lease["lease_id"], (TRANSPORT, INTERRUPTION))
    assert not authority._lifecycle_away and not manager.away and not engine._away_hold
    assert device.writes == []
    hue.set_light.assert_not_awaited()
    notifier.emit_alert.assert_not_awaited()
    await manager.close()


@pytest.mark.parametrize("cancel", ["manual", "mode_exit", "physical"])
async def test_semantic_pending_pause_has_independent_cancellation(cancel):
    manager, authority, sonos, device, _, _, _, _ = setup()
    started, release = asyncio.Event(), asyncio.Event()
    read = sonos.get_playback_ownership_evidence
    calls = 0
    async def gated_read():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        return await read()
    sonos.get_playback_ownership_evidence = gated_read
    semantic = asyncio.create_task(manager.on_audio_mode_change("away"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        if cancel == "manual":
            await manual_play(authority, sonos)
        elif cancel == "mode_exit":
            await manager.on_audio_mode_change("working")
        else:
            await manual_play(authority, sonos)
            await manager.handle_event("leave", "geofence")
            await manager.on_audio_mode_change("working")
            assert authority._lifecycle_away
    finally:
        release.set()
        await semantic
    assert device.writes == ({"manual": ["play"], "mode_exit": [], "physical": ["play", "pause"]}[cancel])
    await manager.close()


@pytest.mark.parametrize("channel", ["rest", "ws"])
@pytest.mark.parametrize("action", ["next", "previous"])
async def test_explicit_skip_records_intent_before_learning_capture(channel, action, monkeypatch):
    from types import SimpleNamespace
    import backend.api.routes.sonos as routes
    from backend.main import _handle_sonos_command
    from backend.schemas.ws import SonosCommandData
    manager, authority, sonos, device, _, _, _, _ = setup()
    started, release = asyncio.Event(), asyncio.Event()
    read = sonos.get_playback_ownership_evidence
    async def gated_read():
        started.set()
        await release.wait()
        return await read()
    sonos.get_playback_ownership_evidence = gated_read
    capture_started, capture_release = asyncio.Event(), asyncio.Event()
    async def capture(_authority):
        capture_started.set()
        await capture_release.wait()
        return None
    monkeypatch.setattr(routes, "capture_owned_music_session", capture)
    monkeypatch.setattr("backend.services.music_learning_provenance.capture_owned_music_session", capture)
    async def skip():
        device.writes.append(action)
        return True
    sonos.next_track = skip
    sonos.previous_track = skip
    state = SimpleNamespace(sonos=sonos, audio_ownership=authority, event_logger=None, automation=None)
    request = SimpleNamespace(app=SimpleNamespace(state=state), headers={}, client=SimpleNamespace(host="127.0.0.1"))
    leave = asyncio.create_task(manager.handle_event("leave", "test"))
    command = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        revision = authority.capture_manual_intent()
        command = asyncio.create_task(
            getattr(routes, "sonos_" + action)(request) if channel == "rest"
            else _handle_sonos_command(request.app, SonosCommandData(action=action))
        )
        await asyncio.wait_for(capture_started.wait(), 2)
        assert authority.capture_manual_intent() == revision + 1
        release.set()
        await leave
        assert device.writes == []
    finally:
        release.set()
        capture_release.set()
        await asyncio.gather(leave, *([command] if command else []))
    assert device.writes == [action]
    assert authority.capture_manual_intent() == revision + 1
    await manager.close()


@pytest.mark.parametrize("stage", ["entry", "queue", "admission"])
async def test_semantic_away_cancels_inflight_autoplay(stage):
    from tests.test_music_mapper_ownership import Sonos, entry
    manager, authority, _, _, _, _, _, _ = setup()
    sonos = Sonos()
    manager._sonos_getter = lambda: sonos
    mapper = MusicMapper(sonos, AsyncMock(), audio_ownership=authority)
    mapper.set_away_manager(manager)
    mapper.pick_playlist = lambda mode: entry()
    started, release = asyncio.Event(), asyncio.Event()
    read = sonos.get_queue_ownership_evidence
    run = authority.run_if_valid
    async def gated_read():
        started.set()
        await release.wait()
        return await read()
    async def gated_run(*args):
        started.set()
        await release.wait()
        return await run(*args)
    if stage == "entry":
        release_lease = mapper._release_mode_audio_lease
        async def gated_release(mode):
            started.set()
            await release.wait()
            await release_lease(mode)
        mapper._release_mode_audio_lease = gated_release
    elif stage == "queue":
        sonos.get_queue_ownership_evidence = gated_read
    else:
        authority.run_if_valid = gated_run
    working = asyncio.create_task(mapper.on_mode_change("working"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        # Avoid reusing the gated queue read for the semantic STOPPED proof.
        sonos.get_playback_ownership_evidence = AsyncMock(return_value={"transport_state": "STOPPED"})
        await mapper.on_mode_change("away")
    finally:
        release.set()
        await working
    assert sonos.play_calls == []
    await manager.close()


@pytest.mark.parametrize("source", ["playlist", "cloud"])
async def test_semantic_away_cancels_autoplay_during_real_favorite_lookup(source):
    from types import SimpleNamespace
    from tests.test_music_mapper_ownership import Sonos, entry
    manager, authority, sonos, device, _, _, _, _ = setup(state="STOPPED")
    neutral = Sonos().neutral_evidence
    sonos.get_status = AsyncMock(return_value={"state": "STOPPED"})
    sonos.get_queue_ownership_evidence = AsyncMock(return_value=deepcopy(neutral))
    sonos.get_playback_ownership_evidence = AsyncMock(return_value={"transport_state": "STOPPED"})
    sonos._queue_ownership_evidence_sync = lambda: deepcopy(neutral)
    device.clear_queue = lambda: device.writes.append("clear")
    device.add_to_queue = lambda item: device.writes.append("add")
    sonos._shuffle_and_play = lambda device, still_allowed=None: device.writes.append("autoplay")
    started, release = asyncio.Event(), asyncio.Event()
    item = SimpleNamespace(title=entry()["favorite_title"], resources=["playable"])
    async def playlists():
        if source == "playlist":
            started.set()
            await release.wait()
            return [item]
        return []
    async def cloud():
        started.set()
        await release.wait()
        sonos._favorites_objects_cache = [item]
        return []
    sonos._get_sonos_playlists_cached = playlists
    sonos._get_cloud_favorites_cached = cloud
    mapper = MusicMapper(sonos, AsyncMock(), audio_ownership=authority)
    mapper.set_away_manager(manager)
    mapper.pick_playlist = lambda mode: entry()
    working = asyncio.create_task(mapper.on_mode_change("working"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        await mapper.on_mode_change("away")
    finally:
        release.set()
        await working
    assert device.writes == []
    await manager.close()


@pytest.mark.parametrize("channel", ["rest", "ws"])
@pytest.mark.parametrize("action", ["next", "previous"])
@pytest.mark.parametrize("newer", ["play", "pause"])
@pytest.mark.parametrize("stage", ["capture", "persistence"])
async def test_superseded_skip_never_writes_or_logs(channel, action, newer, stage, monkeypatch):
    from types import SimpleNamespace
    import backend.api.routes.sonos as routes
    from backend.main import _handle_sonos_command
    from backend.schemas.ws import SonosCommandData
    manager, authority, sonos, device, _, _, _, _ = setup()
    await authority.snapshot()
    started, release = asyncio.Event(), asyncio.Event()
    async def capture(_authority):
        if stage == "capture":
            started.set()
            await release.wait()
        return None
    monkeypatch.setattr(routes, "capture_owned_music_session", capture)
    monkeypatch.setattr("backend.services.music_learning_provenance.capture_owned_music_session", capture)
    save = authority._save_setting
    async def gated_save(key, value):
        if not started.is_set():
            started.set()
            await release.wait()
        await save(key, value)
    if stage == "persistence":
        authority._save_setting = gated_save
    async def skip():
        device.writes.append(action)
        return True
    sonos.next_track = skip
    sonos.previous_track = skip
    logger = SimpleNamespace(log_sonos_event=AsyncMock())
    state = SimpleNamespace(sonos=sonos, audio_ownership=authority, event_logger=logger, automation=None)
    request = SimpleNamespace(app=SimpleNamespace(state=state), headers={}, client=SimpleNamespace(host="127.0.0.1"))
    async def command(name):
        if channel == "rest":
            return await getattr(routes, "sonos_" + name)(request)
        return await _handle_sonos_command(request.app, SonosCommandData(action=name))
    old = asyncio.create_task(command(action))
    latest = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        revision = authority.capture_manual_intent()
        latest = asyncio.create_task(command(newer))
        # Give the newer command its synchronous ingress before releasing storage.
        await asyncio.sleep(0)
        assert authority.capture_manual_intent() == revision + 1
        if stage == "capture":
            await latest
            generation = (await authority.snapshot())["generation"]
        release.set()
        result = await old
        await latest
        assert result == ({"status": "error"} if channel == "rest" else None)
        assert device.writes == [newer]
        if stage == "capture":
            assert (await authority.snapshot())["generation"] == generation
        assert [call.kwargs["event_type"] for call in logger.log_sonos_event.await_args_list] == [newer]
    finally:
        release.set()
        await asyncio.gather(old, *([latest] if latest else []))
        await manager.close()


@pytest.mark.parametrize("source", ["playlist", "cloud"])
@pytest.mark.parametrize("stage", ["add", "play_mode"])
async def test_semantic_away_blocks_final_play_after_soco_queue_prep(source, stage):
    from types import SimpleNamespace
    from tests.test_music_mapper_ownership import Sonos, entry
    manager, authority, sonos, _, _, _, _, _ = setup(state="STOPPED")
    neutral = Sonos().neutral_evidence
    sonos.get_status = AsyncMock(return_value={"state": "STOPPED"})
    sonos.get_queue_ownership_evidence = AsyncMock(return_value=deepcopy(neutral))
    sonos.get_playback_ownership_evidence = AsyncMock(return_value={"transport_state": "STOPPED"})
    sonos._queue_ownership_evidence_sync = lambda: deepcopy(neutral)
    started, release = threading.Event(), threading.Event()
    class QueueDevice:
        queue_size = 2
        def __init__(self):
            self.writes = []
        def clear_queue(self):
            self.writes.append("clear")
        def add_to_queue(self, item):
            self.writes.append("add")
            if stage == "add":
                started.set()
                assert release.wait(5)
        @property
        def play_mode(self):
            return "NORMAL"
        @play_mode.setter
        def play_mode(self, value):
            self.writes.append(value)
            if stage == "play_mode":
                started.set()
                assert release.wait(5)
        def play_from_queue(self, index):
            self.writes.append("play")
    device = QueueDevice()
    sonos._device = device
    item = SimpleNamespace(title=entry()["favorite_title"], resources=["playable"])
    sonos._get_sonos_playlists_cached = AsyncMock(return_value=[item] if source == "playlist" else [])
    sonos._get_cloud_favorites_cached = AsyncMock(return_value=[])
    sonos._favorites_objects_cache = [item] if source == "cloud" else []
    events = SimpleNamespace(log_sonos_event=AsyncMock())
    mapper = MusicMapper(sonos, AsyncMock(), audio_ownership=authority, event_logger=events)
    mapper.set_away_manager(manager)
    mapper.pick_playlist = lambda mode: entry()
    working = asyncio.create_task(mapper.on_mode_change("working"))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        await asyncio.wait_for(mapper.on_mode_change("away"), 2)
        assert not working.done()
    finally:
        release.set()
        await working
        await manager.close()
    assert device.writes == ["clear", "add", "SHUFFLE"]
    events.log_sonos_event.assert_not_awaited()
    assert mapper._learning_tasks == {}
    assert not any(lease.get("purpose") == MODE_AUTOPLAY_PURPOSE for lease in (await authority.snapshot())["leases"])
