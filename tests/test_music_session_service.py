import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.services.audio_ownership import AudioOwnershipService, MANUAL_TRANSPORT_DIMENSIONS, QUEUE_SOURCE
from backend.services.music_mix_execution import MixStartResult
from backend.services.music_selected_plan import SelectedListeningPlan
from backend.services.music_session_service import ListeningSessionService, MAX_TICKETS
from backend.services.music_sustained_listening import SustainedListening
from tests.test_music_selected_plan import favorite, request, song


class Planner:
    def __init__(self):
        self.calls = 0
        self.change = False
        self.hook = None

    async def preview(self, request, choice_id, *, limit):
        self.calls += 1
        if self.hook:
            self.hook(self.calls)
        if self.change and self.calls == 2:
            return SelectedListeningPlan(choice_id, "artist_mix", "revoked")
        return SelectedListeningPlan(choice_id, "artist_mix", "execution_not_connected",
                                     (song("11"), song("12")))


class Runtime:
    def __init__(self):
        self.reason = None
        self.volume = 15

    def _policy_reason(self):
        return self.reason

    async def _runtime_preflight(self, **kwargs):
        return {"reason": self.reason, "volume_used": self.volume}


async def fixture(monkeypatch):
    async def load(key):
        return {}

    async def save(key, value):
        pass

    authority = AudioOwnershipService(setting_loader=load, setting_saver=save)
    state = SimpleNamespace(
        audio_ownership=authority,
        music_mapper=SimpleNamespace(_manual_music_block_revision=0),
        music_assisted_playback=Runtime(),
        automation=SimpleNamespace(current_mode="general", _get_time_period=lambda: "night"),
        sonos=object(),
    )
    planner = Planner()
    now = [0]
    service = ListeningSessionService(state, planner, clock=lambda: now[0])
    writes = []

    async def executor(sonos, selected, *, mutation_runner, preflight, still_current):
        async def operation():
            if not still_current():
                return None
            writes.append(selected.choice_id)
            return True

        proof = await mutation_runner(operation)
        return MixStartResult("started", "mock_verified", 2) if proof else MixStartResult("suppressed", "mock_refused")

    monkeypatch.setattr("backend.services.music_session_service.start_selected_mix", executor)
    return service, state, planner, now, writes


def ticket(service):
    return service.issue(request(), owner_scope="owner")["token"]


async def start(service, token, choice="artist_mix:11,12", owner="owner"):
    return await service.start(token, choice, owner_scope=owner, authorized=lambda: True)


@pytest.mark.asyncio
async def test_single_selection_and_duplicate_never_replays(monkeypatch):
    service, _, planner, _, writes = await fixture(monkeypatch)
    token = ticket(service)
    first, second = await asyncio.gather(start(service, token), start(service, token))
    assert {first.status, second.status} == {"started", "suppressed"}
    assert writes == ["artist_mix:11,12"]
    assert planner.calls == 2


@pytest.mark.asyncio
async def test_wrong_owner_cannot_use_or_consume_ticket(monkeypatch):
    service, _, _, _, writes = await fixture(monkeypatch)
    token = ticket(service)
    assert (await start(service, token, owner="guest")).reason == "selection_unavailable"
    assert writes == []
    assert (await start(service, token)).status == "started"


@pytest.mark.asyncio
async def test_expired_hidden_album_and_untrusted_preview_abstain(monkeypatch):
    service, _, planner, now, writes = await fixture(monkeypatch)
    token = ticket(service)
    now[0] = 120
    assert (await start(service, token)).reason == "selection_expired"
    assert (await start(service, ticket(service), "artist_mix:11,99")).reason == "choice_not_visible"
    assert service.issue(request(album=True), owner_scope="owner")["choice_ids"] == ["sonos_favorite:fav1"]
    assert service.issue(replace(request(), actuation_allowed=True), owner_scope="owner") == {"status": "unavailable"}
    with pytest.raises(TypeError):
        service.issue({}, owner_scope="owner")
    assert planner.calls == 0 and writes == []


@pytest.mark.asyncio
async def test_bounded_memory_and_restart_never_replays(monkeypatch):
    service, state, planner, _, writes = await fixture(monkeypatch)
    oldest = ticket(service)
    for _ in range(MAX_TICKETS):
        latest = ticket(service)
    assert (await start(service, oldest)).reason == "selection_unavailable"
    restarted = ListeningSessionService(state, planner)
    assert (await start(restarted, latest)).reason == "selection_unavailable"
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["manual", "mode", "mapper", "policy", "clock", "revoked"])
async def test_revalidation_and_newer_authority_win(monkeypatch, change):
    service, state, planner, now, writes = await fixture(monkeypatch)
    token = ticket(service)

    def hook(call):
        if call != 2:
            return
        if change == "manual":
            state.audio_ownership.record_manual_intent((QUEUE_SOURCE,))
        elif change == "mode":
            state.automation.current_mode = "gaming"
        elif change == "mapper":
            state.music_mapper._manual_music_block_revision += 1
        elif change == "policy":
            state.music_assisted_playback.reason = "sleeping_active"
        elif change == "clock":
            now[0] = 120

    planner.hook = hook
    planner.change = change == "revoked"
    assert (await start(service, token)).status == "suppressed"
    assert writes == []


@pytest.mark.asyncio
async def test_existing_owner_and_volume_ceiling_refuse(monkeypatch):
    service, state, _, _, writes = await fixture(monkeypatch)
    state.music_assisted_playback.volume = 30
    assert (await start(service, ticket(service))).status == "suppressed"
    state.music_assisted_playback.volume = 15
    await state.audio_ownership.acquire(owner="other", purpose="test", dimensions=(QUEUE_SOURCE,))
    assert (await start(service, ticket(service))).reason == "audio_ownership_busy"
    assert writes == []


@pytest.mark.asyncio
async def test_cancelled_selection_is_not_replayable(monkeypatch):
    service, _, planner, _, writes = await fixture(monkeypatch)
    token = ticket(service)

    def cancel(call):
        raise asyncio.CancelledError

    planner.hook = cancel
    with pytest.raises(asyncio.CancelledError):
        await start(service, token)
    assert (await start(service, token)).reason == "selection_unavailable"
    assert writes == []

@pytest.mark.asyncio
async def test_revoked_browser_session_refuses_before_first_write(monkeypatch):
    service, _, planner, _, writes = await fixture(monkeypatch)
    token = ticket(service)
    active = [True]

    def hook(call):
        if call == 2:
            active[0] = False

    planner.hook = hook
    receipt = await service.start(
        token, "artist_mix:11,12", owner_scope="owner", authorized=lambda: active[0],
    )
    assert receipt.status == "suppressed"
    assert writes == []
    assert (await start(service, token)).reason == "selection_unavailable"


@pytest.mark.asyncio
async def test_runtime_mode_change_after_issue_refuses(monkeypatch):
    service, state, _, _, writes = await fixture(monkeypatch)
    token = ticket(service)
    state.automation.current_mode = "working"
    assert (await start(service, token)).reason == "selection_mode_changed"
    assert writes == []

@pytest.mark.asyncio
async def test_familiar_only_ticket_dispatches_exact_favorite(monkeypatch):
    service, _, planner, _, writes = await fixture(monkeypatch)
    selected = replace(request(), discovery=None)
    issued = service.issue(selected, owner_scope="owner")
    assert issued["choice_ids"] == ["sonos_favorite:fav1"]

    async def preview(request, choice_id, *, limit):
        return SelectedListeningPlan(choice_id, "favorite", "execution_not_connected", (favorite(),))

    async def executor(sonos, plan, *, mutation_runner, preflight, still_current):
        async def operation():
            assert still_current()
            writes.append(plan.choice_id)
            return True
        assert await mutation_runner(operation)
        return MixStartResult("started", "mock_verified", 1)

    monkeypatch.setattr(planner, "preview", preview)
    monkeypatch.setattr("backend.services.music_session_service.start_selected_favorite", executor)
    receipt = await start(service, issued["token"], "sonos_favorite:fav1")
    assert receipt.status == "started"
    assert writes == ["sonos_favorite:fav1"]

@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_tail_is_revalidated_before_shared_admission(monkeypatch, revoked):
    service, _, planner, _, writes = await fixture(monkeypatch)
    tail = (song("21"),)

    class Continuation:
        async def preview(self, selected, *, mode):
            assert selected.choice_id == "artist_mix:11,12"
            return tail

        async def revalidate(self, candidates, *, mode):
            assert candidates == tail
            assert planner.calls == 2
            return not revoked

    service._continuation_planner = Continuation()

    async def executor(sonos, selected, *, mutation_runner, preflight, still_current, continuation):
        assert continuation == tail

        async def operation():
            assert still_current()
            writes.extend([item.provider_id for item in selected.candidates + continuation])
            return True

        proof = await mutation_runner(operation)
        return MixStartResult("started", "mock_verified", 3, 1) if proof else MixStartResult("suppressed", "mock_refused")

    monkeypatch.setattr("backend.services.music_session_service.start_selected_mix", executor)
    receipt = await start(service, ticket(service))
    assert receipt.status == ("suppressed" if revoked else "started")
    assert writes == ([] if revoked else ["11", "12", "21"])

@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["confirmed", "unknown", "no_proof", "revoked"])
async def test_sustained_session_requires_confirmed_start_and_original_authority(monkeypatch, outcome):
    service, state, _, now, writes = await fixture(monkeypatch)
    state.bootstrap_ready = True
    allowed = [True]

    class Continuation:
        async def preview(self, selected, *, mode):
            return ()

    service._continuation_planner = Continuation()
    service._sustained = SustainedListening(service._continuation_planner, clock=lambda: now[0])
    device = object()
    state.sonos = SimpleNamespace(device=device)
    rows = tuple(
        f'<item><title>Track {i}</title><artist>Artist</artist><res>x-sonos-http:song%3a{i}?sid=204</res></item>'
        for i in ("11", "12")
    )

    async def executor(sonos, selected, *, mutation_runner, preflight, still_current, on_started):
        async def operation():
            writes.append(selected.choice_id)
            return True
        assert await mutation_runner(operation)
        if outcome != "no_proof":
            on_started(("revision", 2, "<DIDL-Lite>" + rows[0] + "</DIDL-Lite>"),
                       "speaker", 15, device, rows)
        if outcome == "revoked":
            allowed[0] = False
        return MixStartResult("indeterminate" if outcome == "unknown" else "started", "mock", 2)

    monkeypatch.setattr("backend.services.music_session_service.start_selected_mix", executor)
    receipt = await service.start(ticket(service), "artist_mix:11,12",
                                  owner_scope="owner", authorized=lambda: allowed[0])
    assert receipt.sustained_listening is (outcome == "confirmed")
    assert (service._sustained._active is not None) is (outcome == "confirmed")
    if outcome == "confirmed":
        now[0] = 121
        assert service._sustained._current(service._sustained._active)
        allowed[0] = False
        assert not service._sustained._current(service._sustained._active)

@pytest.mark.asyncio
async def test_manual_stop_finishes_during_start_provider_revalidation(monkeypatch):
    service, state, planner, _, writes = await fixture(monkeypatch)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = planner.preview

    async def held_lookup(*args, **kwargs):
        result = await original(*args, **kwargs)
        if planner.calls == 2:
            entered.set()
            await release.wait()
        return result

    planner.preview = held_lookup
    task = asyncio.create_task(start(service, ticket(service)))

    async def stop():
        return True

    try:
        await asyncio.wait_for(entered.wait(), 2)
        result = await asyncio.wait_for(state.audio_ownership.run_manual(
            MANUAL_TRANSPORT_DIMENSIONS, source="test", reason="stop", operation=stop,
        ), timeout=1)
        assert result is True
        assert not writes
    finally:
        release.set()
        receipt = await task
    assert receipt.status == "suppressed"
    assert not writes


@pytest.mark.asyncio
async def test_stale_start_validation_waiting_for_writer_lock_abstains(monkeypatch):
    service, state, _, now, writes = await fixture(monkeypatch)
    original = state.audio_ownership.run_if_opportunistic

    async def delayed(token, operation):
        now[0] += 4
        return await original(token, operation)

    state.audio_ownership.run_if_opportunistic = delayed
    receipt = await start(service, ticket(service))
    assert receipt.status == "suppressed"
    assert not writes


class StoppedSource:
    """Sanitized shape of the physically verified stopped HTTP music source."""

    def __init__(self, state, writes):
        self.state = state
        self.writes = writes
        self.device = object()
        uri = "http://example.invalid/music.mp3"
        self.evidence = {
            "queue_uid": "speaker", "queue_update_id": "revision", "queue_size": 0,
            "coordinator": True, "play_mode": "NORMAL", "mute": False, "volume": 15,
            "transport_state": "STOPPED", "current_uri": uri, "queue_track_uri": uri,
            "metadata": (
                '<DIDL-Lite><item><class>object.item.audioItem.musicTrack</class>'
                f'<res protocolInfo="http-get:*:audio/mpeg:*">{uri}</res></item></DIDL-Lite>'
            ),
        }
        self.outcome = "ready"
        self.hook = None
        self.unloaded = False

    async def get_prepare_evidence(self):
        return dict(self.evidence)

    async def prepare_if_unchanged(self, expected, current):
        if self.hook:
            self.hook()
        if expected != self.evidence or not current() or self.outcome == "refused":
            return {"status": "refused", "reason": "source_or_authority_changed"}
        self.writes.append("unload")
        if self.outcome == "unknown":
            return {"status": "not_ready", "reason": "unload_not_verified"}
        self.unloaded = True
        return {"status": "ready", "reason": "unloaded_verified_play_requires_separate_action"}


async def stopped_fixture(monkeypatch):
    service, state, planner, now, writes = await fixture(monkeypatch)
    source = StoppedSource(state, writes)
    state.sonos = source

    async def preflight(**kwargs):
        if source.unloaded:
            return {"reason": None, "volume_used": source.evidence["volume"]}
        return {"reason": "sonos_busy"}

    state.music_assisted_playback._runtime_preflight = preflight

    async def executor(sonos, selected, *, mutation_runner, preflight, still_current):
        async def operation():
            evidence = await preflight(expected_queue_size=0)
            if not sonos.unloaded or evidence["reason"] is not None or not still_current():
                return None
            writes.append(selected.choice_id)
            return True
        proof = await mutation_runner(operation)
        return MixStartResult("started", "verified", 2) if proof else MixStartResult("suppressed", "mock_refused")

    monkeypatch.setattr("backend.services.music_session_service.start_selected_mix", executor)
    monkeypatch.setattr("backend.services.music_session_service.start_selected_favorite", executor)
    return service, state, planner, source, writes


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["artist_mix", "favorite"])
async def test_explicit_selection_prepares_verified_stopped_source_once(monkeypatch, kind):
    service, _, planner, _, writes = await stopped_fixture(monkeypatch)
    choice = "artist_mix:11,12"
    token = ticket(service)
    if kind == "favorite":
        async def preview(request, choice_id, *, limit):
            return SelectedListeningPlan(choice_id, "favorite", "execution_not_connected", (favorite(),))
        monkeypatch.setattr(planner, "preview", preview)
        choice = "sonos_favorite:fav1"
        token = service.issue(replace(request(), discovery=None), owner_scope="owner")["token"]
    assert (await start(service, token, choice)).status == "started"
    assert writes == ["unload", choice]
    assert (await start(service, token, choice)).status == "suppressed"
    assert writes == ["unload", choice]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"transport_state": "PAUSED_PLAYBACK"}, {"transport_state": "PLAYING"},
    {"queue_size": 1}, {"volume": 0}, {"volume": 19}, {"mute": True},
    {"metadata": ""}, {"queue_track_uri": "http://example.invalid/other.mp3"},
    {"play_mode": "SHUFFLE"}, {"coordinator": False}, {"queue_update_id": ""},
])
async def test_stopped_source_ineligible_never_unloads(monkeypatch, change):
    service, _, _, source, writes = await stopped_fixture(monkeypatch)
    source.evidence.update(change)
    assert (await start(service, ticket(service))).status == "suppressed"
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source", "manual", "device", "revoked"])
async def test_stopped_source_revalidates_before_unload(monkeypatch, change):
    service, state, planner, source, writes = await stopped_fixture(monkeypatch)

    def hook(call):
        if call == 2:
            if change == "source":
                source.evidence["queue_update_id"] = "new"
            elif change == "manual":
                state.audio_ownership.record_manual_intent((QUEUE_SOURCE,))
            elif change == "device":
                source.device = object()

    planner.hook = hook
    planner.change = change == "revoked"
    assert (await start(service, ticket(service))).status == "suppressed"
    assert writes == []


@pytest.mark.asyncio
async def test_unknown_preparation_never_appends_or_retries(monkeypatch):
    service, _, _, source, writes = await stopped_fixture(monkeypatch)
    source.outcome = "unknown"
    token = ticket(service)
    receipt = await start(service, token)
    assert receipt.status == "indeterminate"
    assert receipt.reason == "source_preparation_unverified"
    assert (await start(service, token)).status == "suppressed"
    assert writes == ["unload"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["manual", "volume", "device"])
async def test_change_after_verified_unload_prevents_start(monkeypatch, change):
    service, state, _, source, writes = await stopped_fixture(monkeypatch)
    original = source.prepare_if_unchanged

    async def changed(expected, current):
        receipt = await original(expected, current)
        if change == "manual":
            state.audio_ownership.record_manual_intent((QUEUE_SOURCE,))
        elif change == "volume":
            source.evidence["volume"] = 12
        else:
            source.device = object()
        return receipt

    source.prepare_if_unchanged = changed
    receipt = await start(service, ticket(service))
    assert receipt.status == "indeterminate"
    assert writes == ["unload"]


@pytest.mark.asyncio
async def test_verified_unload_is_not_repeated_at_second_writer_admission(monkeypatch):
    service, _, _, _, writes = await stopped_fixture(monkeypatch)

    async def executor(sonos, selected, *, mutation_runner, preflight, still_current):
        async def operation():
            assert sonos.unloaded
            writes.append("phase")
            return True
        assert await mutation_runner(operation)
        assert await mutation_runner(operation)
        return MixStartResult("started", "verified", 2)

    monkeypatch.setattr("backend.services.music_session_service.start_selected_mix", executor)
    assert (await start(service, ticket(service))).status == "started"
    assert writes == ["unload", "phase", "phase"]
