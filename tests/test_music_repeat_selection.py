import asyncio
from dataclasses import replace

import pytest

from backend.services.audio_ownership import MANUAL_TRANSPORT_DIMENSIONS, TRANSPORT
from backend.services.music_repeat_selection import probe_repeat_queue, start_repeat_mix
from backend.services.music_selected_plan import SelectedListeningPlan
from backend.services.music_sustained_listening import (
    RetainedQueue, SustainedListening, started_queue_proof,
)
from tests.test_music_continuation import candidate
from tests.test_music_session_service import fixture, start, ticket
from tests.test_music_sustained_listening import Planner, PlayingSonos, authority


class StoppedSonos(PlayingSonos):
    def __init__(self, now):
        super().__init__(now)
        self.state = "STOPPED"
        self.verify = True
        self.play_calls = []
        self.bad_suffix = False

    def _add_apple_music_share_link_sync(self, url):
        position = super()._add_apple_music_share_link_sync(url)
        if self.bad_suffix:
            self.ids[-1] = "999"
        return position

    def _play_queue_item_if_unchanged_sync(self, index, size, snapshot, **kwargs):
        assert size == len(self.ids)
        assert snapshot == self._queue_item_snapshot_sync(index, 1)
        assert kwargs == {"queue_uid": "speaker", "max_volume": 15}
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
async def test_session_new_ticket_can_repeat_only_prior_verified_queue(monkeypatch):
    service, state, _, now, _ = await fixture(monkeypatch)
    state.bootstrap_ready = True
    sonos = StoppedSonos(now)
    state.sonos = sonos
    state.music_assisted_playback.reason = None

    async def busy(**kwargs):
        return {"reason": "sonos_busy"}

    state.music_assisted_playback._runtime_preflight = busy
    service._continuation_planner = Planner()
    service._sustained = SustainedListening(service._continuation_planner, clock=lambda: now[0])
    assert (await start(service, ticket(service))).status == "suppressed"
    assert not sonos.writes
    origin = origin_for(sonos)
    auth = state.audio_ownership
    epoch = await auth.capture_opportunistic(MANUAL_TRANSPORT_DIMENSIONS, claim=True)
    append_token = await auth.capture_listening_append(epoch, manual_revision=auth.capture_manual_intent())
    assert service._sustained.install(authority=auth, token=append_token, sonos=sonos,
                                      device=sonos.device, proof=origin.proof, rows=origin.rows,
                                      mode="general", allowed=lambda: True, owner_scope="owner")
    receipt = await start(service, ticket(service))
    assert receipt.status == "started"
    assert receipt.sustained_listening is True
    assert sonos.ids == ["11", "12", "13", "11", "12"]
    assert sonos.play_calls == [3]
    assert service._sustained._active.initial_track == 4
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
