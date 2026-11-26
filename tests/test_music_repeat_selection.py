import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.services.audio_ownership import MANUAL_TRANSPORT_DIMENSIONS, TRANSPORT
from backend.services.music_repeat_selection import probe_repeat_queue, start_repeat_favorite, start_repeat_mix
from backend.services.music_selected_plan import SelectedListeningPlan
from backend.services.music_sustained_listening import (
    RetainedQueue, SustainedListening, started_queue_proof,
)
from backend.services.sonos_service import SonosService
from tests.test_music_continuation import candidate
from tests.test_music_favorite_execution import plan as favorite_plan
from tests.test_music_session_service import start
from tests.test_music_sustained_listening import Planner, PlayingSonos, authority


class StoppedSonos(PlayingSonos):
    def __init__(self, now):
        super().__init__(now)
        self.state = "STOPPED"
        self.verify = True
        self.play_calls = []
        self.bad_suffix = False
        self.device.volume = 15
        self.volume_writes = []
        self.cap_events = []

    async def clamp_prepared_volume(self, device, expected, target, still_current):
        self.cap_events.append("cap")
        receipt = await SonosService.clamp_prepared_volume(self, device, expected, target, still_current)
        if receipt["status"] == "ready":
            self.volume_writes.append(self.device.volume)
        return receipt

    def _prepare_evidence_sync(self):
        return {**super()._prepare_evidence_sync(), "volume": self.device.volume}

    def _add_apple_music_share_link_sync(self, url):
        self.cap_events.append("append")
        position = super()._add_apple_music_share_link_sync(url)
        if self.bad_suffix:
            self.ids[-1] = "999"
        return position

    def _play_queue_item_if_unchanged_sync(self, index, size, snapshot, **kwargs):
        assert size == len(self.ids)
        assert snapshot == self._queue_item_snapshot_sync(index, 1)
        from backend.services.music_queue_identity import play_source_fingerprint
        assert kwargs == {"queue_uid": "speaker", "max_volume": self.device.volume,
                          "expected_source": play_source_fingerprint(self._prepare_evidence_sync())}
        self.play_calls.append(index)
        self.state = "PLAYING"
        self.index = index + 1
        self.position = 0
        return True

    async def _verify_queue_playback_started(self, index, size, snapshot, **kwargs):
        assert self.play_calls == [index]
        assert snapshot == self._queue_item_snapshot_sync(index, 1)
        return self.verify


def selected():
    return SelectedListeningPlan("artist_mix:21,22", "artist_mix", "execution_not_connected",
                                 (candidate("21"), candidate("22")))


def origin_for(sonos):
    rows = sonos.rows()
    proof = started_queue_proof(sonos._queue_item_snapshot_sync(0, 1), "speaker", 15, rows)
    return RetainedQueue("owner", sonos, sonos.device, proof, rows, 100)


async def run_repeat(sonos, origin, *, still_current=lambda: True, plan=None, initial=None):
    if initial is None:
        initial = await probe_repeat_queue(sonos, origin, ceiling=18, still_current=still_current)
    assert initial is not None
    started = []

    async def runner(operation):
        return await operation()

    result = await start_repeat_mix(
        sonos, plan or selected(), origin, initial, mutation_runner=runner,
        still_current=still_current, on_started=lambda *args: started.append(args),
    )
    return result, started


@pytest.mark.asyncio
async def test_repeat_mix_preserves_prefix_and_starts_first_new_item():
    sonos = StoppedSonos([0.0])
    origin = origin_for(sonos)
    result, started = await run_repeat(sonos, origin)
    assert result.status == "started"
    assert result.confirmed_appends == 2
    assert sonos.ids == ["11", "12", "13", "21", "22"]
    assert sonos.writes == ["21", "22"]
    assert sonos.play_calls == [3]
    assert len(started) == 1
    assert started[0][0] == sonos._queue_item_snapshot_sync(0, 1)
    assert started[0][-1] == sonos.rows()


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["paused", "playing", "revision", "same_size_replacement", "foreign_device", "wrong_source", "volume"])
async def test_repeat_probe_abstains_on_unknown_or_active_queue(cause):
    sonos = StoppedSonos([0.0])
    origin = origin_for(sonos)
    if cause == "paused":
        sonos.state = "PAUSED_PLAYBACK"
    elif cause == "playing":
        sonos.state = "PLAYING"
    elif cause == "revision":
        sonos.revision += 1
    elif cause == "same_size_replacement":
        sonos.ids[1] = "999"
    elif cause == "foreign_device":
        origin = replace(origin, device=object())
    else:
        evidence = sonos._prepare_evidence_sync()
        evidence["current_uri" if cause == "wrong_source" else "volume"] = (
            "x-rincon-stream:other" if cause == "wrong_source" else 30
        )

        async def changed():
            return evidence

        sonos.get_prepare_evidence = changed
    assert await probe_repeat_queue(sonos, origin, ceiling=18, still_current=lambda: True) is None
    assert not sonos.writes and not sonos.play_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["worker_replacement", "lost_append", "wrong_suffix", "unverified_play"])
async def test_repeat_uncertainty_never_retries_or_clears(cause):
    sonos = StoppedSonos([0.0])
    origin = origin_for(sonos)
    initial = await probe_repeat_queue(sonos, origin, ceiling=18, still_current=lambda: True)
    sonos.replace_before_worker = cause == "worker_replacement"
    sonos.fail_append = cause == "lost_append"
    sonos.bad_suffix = cause == "wrong_suffix"
    sonos.verify = cause != "unverified_play"
    result, started = await run_repeat(sonos, origin, initial=initial)
    assert result.status == ("suppressed" if cause == "worker_replacement" else "indeterminate")
    assert not started
    assert sonos.writes == ([] if cause == "worker_replacement" else ["21", "22"] if cause == "unverified_play" else ["21"])
    assert sonos.play_calls == ([3] if cause == "unverified_play" else [])


@pytest.mark.asyncio
async def test_repeat_capacity_and_invalid_candidate_abstain():
    sonos = StoppedSonos([0.0])
    sonos.ids = [str(i) for i in range(100, 195)]
    origin = origin_for(sonos)
    result, _ = await run_repeat(sonos, origin)
    assert result.status == "suppressed"
    assert not sonos.writes
    plan = replace(selected(), choice_id="artist_mix:wrong")
    result, _ = await run_repeat(sonos, origin, plan=plan)
    assert result.status == "suppressed"
    assert not sonos.writes


@pytest.mark.asyncio
async def test_retained_queue_is_identity_not_authority_and_expires():
    auth, _, token = await authority()
    now = [0.0]
    sonos = StoppedSonos(now)
    origin = origin_for(sonos)
    service = SustainedListening(Planner(), clock=lambda: now[0])
    assert service.install(authority=auth, token=token, sonos=sonos, device=sonos.device,
                           proof=origin.proof, rows=origin.rows, mode="general",
                           allowed=lambda: True, owner_scope="owner")
    auth.record_manual_intent([TRANSPORT])
    await service.tick()
    assert service._active is None
    retained = service.retained("owner", sonos)
    assert retained is not None
    assert service.retained("other", sonos) is None
    assert SustainedListening(Planner()).retained("owner", sonos) is None
    now[0] = 14400
    assert service.retained("owner", sonos) is None
    assert not service.consume_retained(retained)


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_volume", [0, 15, 25])
async def test_session_new_ticket_can_repeat_ordinary_queue(initial_volume):
    from tests.test_music_selected_manual_integration import session

    state, device, _, play = await session("artist_mix", transport="STOPPED", volume=initial_volume)
    service = state.listening_session
    service._sustained = SustainedListening(Planner())
    receipt = await play()
    assert receipt.status == "started", receipt
    assert receipt.sustained_listening is True
    assert device.ids == ["foreign", "11", "12"] and device.index == 2
    device.state = "STOPPED"
    fresh = service.issue(state.listening_request, owner_scope="owner")
    receipt = await start(service, fresh["token"], choice=state.listening_choice)
    assert receipt.status == "started", receipt
    assert receipt.sustained_listening is True
    assert device.volume == (15 if initial_volume == 15 else 18)
    assert device.ids == ["foreign", "11", "12", "11", "12"]
    assert device.index == 4
    assert service._sustained._active.initial_track == 4
    assert service._sustained._active.proof.offset == 3
    await service._sustained.tick()
    assert service._sustained._active.cursor.track == 4


@pytest.mark.asyncio
async def test_manual_intent_between_repeat_probe_and_append_wins():
    sonos = StoppedSonos([0.0])
    origin = origin_for(sonos)
    auth, epoch, _ = await authority()
    revision = auth.capture_manual_intent()
    def current():
        return auth.opportunistic_is_current(epoch) and auth.capture_manual_intent() == revision
    initial = await probe_repeat_queue(sonos, origin, ceiling=18, still_current=current)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def runner(operation):
        entered.set()
        await release.wait()
        executed, result = await auth.run_if_opportunistic(epoch, operation)
        return result if executed else None

    task = asyncio.create_task(start_repeat_mix(
        sonos, selected(), origin, initial, mutation_runner=runner,
        still_current=current, on_started=lambda *args: pytest.fail("unexpected start"),
    ))
    try:
        await asyncio.wait_for(entered.wait(), 2)

        async def stop():
            return True

        assert await asyncio.wait_for(auth.run_manual(
            MANUAL_TRANSPORT_DIMENSIONS, source="test", reason="stop", operation=stop,
        ), 1)
    finally:
        release.set()
        result = await task
    assert result.status == "suppressed"
    assert not sonos.writes and not sonos.play_calls

@pytest.mark.asyncio
async def test_verified_refill_updates_retained_queue_before_stop():
    auth, _, token = await authority()
    now = [0.0]
    sonos = PlayingSonos(now)
    origin = origin_for(sonos)
    service = SustainedListening(Planner(), clock=lambda: now[0])
    assert service.install(authority=auth, token=token, sonos=sonos, device=sonos.device,
                           proof=origin.proof, rows=origin.rows, mode="general",
                           allowed=lambda: True, owner_scope="owner")
    await service.tick()
    now[0] = 4
    sonos.position += 4
    await service.tick()
    assert sonos.writes == ["21", "22"]
    sonos.state = "STOPPED"
    await service.tick()
    retained = service.retained("owner", sonos)
    assert retained.rows == sonos.rows()
    assert retained.proof.revision == str(sonos.revision)
    assert service._active is None
    assert await probe_repeat_queue(sonos, retained, ceiling=18, still_current=lambda: True)

class SavedPlaylistSonos(StoppedSonos):
    def __init__(self, now):
        super().__init__(now)
        item = favorite_plan().candidates[0]
        self.playlist = SimpleNamespace(
            title=item.title, uri=item.uri, item_id="SQ:1", parent_id="SQ:",
            resources=[SimpleNamespace(uri=item.uri)],
        )
        self.device.get_sonos_playlists = lambda: [self.playlist]
        self.device.avTransport = SimpleNamespace(AddURIToQueue=self.append_saved)
        self.playlist_ids = ["31", "32", "33"]
        self.playlist_revision = "playlist-rev"
        self.playlist_reads = 0
        self.playlist_count = None
        self.changed_expansion = False
        self.wrong_receipt = False
        self.wrong_suffix = False
        self.foreign_service = False
        self.container_calls = []

    def browse(self, args, *, timeout):
        args_dict = dict(args)
        if args_dict["ObjectID"] == "Q:0":
            return super().browse(args, timeout=timeout)
        assert args_dict["ObjectID"] == "SQ:1"
        assert args_dict["StartingIndex"] == 0
        assert 1 <= args_dict["RequestedCount"] <= 32
        assert timeout == 3.0
        self.playlist_reads += 1
        ids = self.playlist_ids[:]
        if self.changed_expansion and self.playlist_reads > 1:
            ids[-1] = "99"
        xml = "<DIDL-Lite>" + "".join(self.row(i) for i in ids) + "</DIDL-Lite>"
        if self.foreign_service:
            xml = xml.replace("sid=204", "sid=9")
        return {"UpdateID": self.playlist_revision,
                "TotalMatches": self.playlist_count if self.playlist_count is not None else len(ids),
                "NumberReturned": len(ids), "Result": xml}

    def append_saved(self, args, *, timeout):
        args = dict(args)
        assert args["EnqueuedURI"] == self.playlist.uri
        assert args["EnqueuedURIMetaData"] == "playlist"
        assert args["DesiredFirstTrackNumberEnqueued"] == args["EnqueueAsNext"] == 0
        assert timeout == 5.0
        offset = len(self.ids)
        self.container_calls.append(args["EnqueuedURI"])
        self.ids.extend(self.playlist_ids)
        if self.wrong_suffix:
            self.ids[-1] = "99"
        self.revision += 1
        return {"FirstTrackNumberEnqueued": str(offset + (2 if self.wrong_receipt else 1)),
                "NumTracksAdded": str(len(self.playlist_ids)), "NewQueueLength": str(len(self.ids))}


async def run_saved(sonos, origin, *, plan=None):
    initial = await probe_repeat_queue(sonos, origin, ceiling=18, still_current=lambda: True)
    assert initial is not None
    started = []

    async def runner(operation):
        return await operation()

    result = await start_repeat_favorite(
        sonos, plan or favorite_plan(), origin, initial, mutation_runner=runner,
        still_current=lambda: True, on_started=lambda *args: started.append(args),
    )
    return result, started


@pytest.fixture
def serialize_saved(monkeypatch):
    monkeypatch.setattr("backend.services.music_repeat_selection.to_didl_string", lambda item: "playlist")


@pytest.mark.asyncio
async def test_repeat_saved_playlist_preserves_prefix_and_starts_exact_suffix(serialize_saved):
    sonos = SavedPlaylistSonos([0.0])
    result, started = await run_saved(sonos, origin_for(sonos))
    assert result.status == "started"
    assert result.confirmed_appends == 1
    assert sonos.playlist_reads == 2
    assert len(sonos.container_calls) == 1
    assert sonos.ids == ["11", "12", "13", "31", "32", "33"]
    assert sonos.play_calls == [3]
    assert len(started) == 1 and started[0][-1] == sonos.rows()


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", [
    "cloud", "identity", "oversized", "foreign_service", "changed_expansion",
    "wrong_receipt", "wrong_suffix", "worker_replacement",
])
async def test_repeat_saved_playlist_refuses_unverified_expansion_or_receipt(serialize_saved, cause):
    sonos = SavedPlaylistSonos([0.0])
    origin = origin_for(sonos)
    plan = favorite_plan()
    if cause == "cloud":
        plan = favorite_plan("favorite")
    elif cause == "identity":
        sonos.playlist.item_id = "SQ:2"
    elif cause == "oversized":
        sonos.playlist_count = 33
    elif cause == "foreign_service":
        sonos.foreign_service = True
    elif cause == "changed_expansion":
        sonos.changed_expansion = True
    elif cause == "wrong_receipt":
        sonos.wrong_receipt = True
    elif cause == "wrong_suffix":
        sonos.wrong_suffix = True
    else:
        sonos.replace_before_worker = True
    result, started = await run_saved(sonos, origin, plan=plan)
    uncertain = cause in {"wrong_receipt", "wrong_suffix"}
    assert result.status == ("indeterminate" if uncertain else "suppressed")
    assert len(sonos.container_calls) == int(uncertain)
    assert not sonos.play_calls and not started

@pytest.mark.asyncio
async def test_repeat_saved_favorite_session_dispatch():
    from tests.test_music_selected_manual_integration import session

    state, device, _, play = await session("favorite", transport="STOPPED", volume=15)
    service = state.listening_session
    service._sustained = SustainedListening(Planner())
    receipt = await play()
    assert receipt.status == "started", receipt
    assert receipt.sustained_listening is True
    assert device.ids == ["foreign", "121", "122"]
    device.state = "STOPPED"
    fresh = service.issue(state.listening_request, owner_scope="owner")
    receipt = await start(service, fresh["token"], choice=state.listening_choice)
    assert receipt.status == "started", receipt
    assert receipt.sustained_listening is True
    assert device.ids == ["foreign", "121", "122", "121", "122"]
    assert device.index == 4
    assert service._sustained._active.initial_track == 4
