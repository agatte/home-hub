import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.services.audio_ownership import AudioOwnershipService, MANUAL_TRANSPORT_DIMENSIONS, QUEUE_SOURCE, VOLUME
from backend.services.music_mix_execution import MixStartResult
from backend.services.music_selected_plan import SelectedListeningPlan
from backend.services.music_session_service import ListeningSessionService, MAX_TICKETS
from backend.services.music_sustained_listening import SustainedListening
from backend.services.music_selected_manual_execution import ManualStartProof
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
        self._lifecycle_state = lambda: {}

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
        automation=SimpleNamespace(current_mode="general", house_state="home", _get_time_period=lambda: "night"),
        away_manager=SimpleNamespace(away=False),
        tts=SimpleNamespace(is_speaking=False),
        ambient_sound=SimpleNamespace(get_state=lambda: {}),
        sonos=SimpleNamespace(connected=True, breaker_open=False),
    )
    planner = Planner()
    now = [0]
    service = ListeningSessionService(state, planner, clock=lambda: now[0])
    writes = []

    async def executor(sonos, selected, *, still_current, ceiling, continuation=()):
        if not still_current():
            return MixStartResult("suppressed", "mock_refused"), None
        assert ceiling() == 18
        writes.append(selected.choice_id)
        return MixStartResult("started", "mock_verified", 2), None

    monkeypatch.setattr("backend.services.music_session_service.execute_selected_manual", executor)
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
    assert service.issue(request(album=True), owner_scope="owner")["choice_ids"] == ["artist_mix:11,12", "sonos_favorite:fav1"]
    assert service.issue(replace(request(), actuation_allowed=True), owner_scope="owner") == {"status": "unavailable", "reason": "preview_unavailable"}
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
@pytest.mark.parametrize("change", ["manual", "volume", "away", "tts", "clock", "revoked"])
async def test_revalidation_and_newer_authority_win(monkeypatch, change):
    service, state, planner, now, writes = await fixture(monkeypatch)
    token = ticket(service)

    def hook(call):
        if call != 2:
            return
        if change == "manual":
            state.audio_ownership.record_manual_intent((QUEUE_SOURCE,))
        elif change == "volume":
            state.audio_ownership.record_manual_intent((VOLUME,))
        elif change == "away":
            state.away_manager.away = True
        elif change == "tts":
            state.tts.is_speaking = True
        elif change == "clock":
            now[0] = 120

    planner.hook = hook
    planner.change = change == "revoked"
    assert (await start(service, token)).status == "suppressed"
    assert writes == []


@pytest.mark.asyncio
async def test_explicit_play_retires_ordinary_owner_but_preserves_interruption(monkeypatch):
    service, state, _, _, writes = await fixture(monkeypatch)
    auth = state.audio_ownership
    await auth.acquire(owner="other", purpose="test", dimensions=(QUEUE_SOURCE,))
    assert (await start(service, ticket(service))).status == "started"
    assert not (await auth.snapshot())["leases"]
    lease = await auth.acquire_interruption(
        owner="tts", purpose="test", dimensions=MANUAL_TRANSPORT_DIMENSIONS,
    )
    assert lease is not None
    assert (await start(service, ticket(service))).status == "suppressed"
    assert writes == ["artist_mix:11,12"]
    assert (await auth.snapshot())["leases"][0]["lease_id"] == lease["lease_id"]


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
async def test_runtime_mode_change_after_issue_allows_explicit_selection(monkeypatch):
    service, state, _, _, writes = await fixture(monkeypatch)
    token = ticket(service)
    state.automation.current_mode = "sleeping"
    state.automation.house_state = "sleeping"
    assert (await start(service, token)).status == "started"
    assert writes == ["artist_mix:11,12"]

@pytest.mark.asyncio
async def test_familiar_only_ticket_dispatches_exact_favorite(monkeypatch):
    service, _, planner, _, writes = await fixture(monkeypatch)
    selected = replace(request(), discovery=None)
    issued = service.issue(selected, owner_scope="owner")
    assert issued["choice_ids"] == ["sonos_favorite:fav1"]

    async def preview(request, choice_id, *, limit):
        return SelectedListeningPlan(choice_id, "favorite", "execution_not_connected", (favorite(),))

    monkeypatch.setattr(planner, "preview", preview)
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

    async def executor(sonos, selected, *, still_current, ceiling, continuation):
        assert continuation == (() if revoked else tail)
        assert still_current()
        writes.extend([item.provider_id for item in selected.candidates + continuation])
        return MixStartResult("started", "mock_verified", len(writes)), None

    monkeypatch.setattr("backend.services.music_session_service.execute_selected_manual", executor)
    receipt = await start(service, ticket(service))
    assert receipt.status == "started"
    assert writes == (["11", "12"] if revoked else ["11", "12", "21"])

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
    state.sonos = SimpleNamespace(device=device, connected=True, breaker_open=False)
    rows = tuple(
        f'<item><title>Track {i}</title><artist>Artist</artist><res>x-sonos-http:song%3a{i}?sid=204</res></item>'
        for i in ("11", "12")
    )

    async def executor(sonos, selected, *, still_current, ceiling, continuation=()):
        assert still_current()
        writes.append(selected.choice_id)
        proof = None if outcome == "no_proof" else ManualStartProof(
            ("revision", 2, "<DIDL-Lite>" + rows[0] + "</DIDL-Lite>"),
            "speaker", 15, device, rows, 0,
        )
        if outcome == "revoked":
            allowed[0] = False
        return MixStartResult("indeterminate" if outcome == "unknown" else "started", "mock", 2), proof

    monkeypatch.setattr("backend.services.music_session_service.execute_selected_manual", executor)
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
    original = state.audio_ownership.run_manual

    async def delayed(*args, **kwargs):
        now[0] += 4
        return await original(*args, **kwargs)

    state.audio_ownership.run_manual = delayed
    receipt = await start(service, ticket(service))
    assert receipt.status == "suppressed"
    assert not writes


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["artist_mix", "favorite"])
async def test_explicit_selection_starts_verified_stopped_source_once(kind):
    from tests.test_music_stopped_source_integration import make_session
    _, device, _, play = await make_session(kind)
    assert (await play()).status == "started"
    writes = list(device.writes)
    assert writes.count("Play") == 1
    assert (await play()).status == "suppressed"
    assert device.writes == writes


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"transport_state": "TRANSITIONING"}, {"queue_size": -1},
    {"volume": -1}, {"volume": 101}, {"mute": True},
    {"metadata": ""}, {"queue_track_uri": "http://example.invalid/other.mp3"},
    {"play_mode": "UNKNOWN"}, {"coordinator": False}, {"queue_update_id": ""},
])
async def test_unknown_or_unsafe_source_never_admitted(change):
    from tests.test_music_stopped_source_integration import make_session
    from backend.services.music_selected_manual_execution import ordinary_source
    state, _, _, _ = await make_session("artist_mix")
    evidence = state.sonos._prepare_evidence_sync()
    assert ordinary_source(state.sonos, evidence)
    assert not ordinary_source(state.sonos, dict(evidence, **change))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source", "manual", "device", "revoked"])
async def test_source_or_authority_change_before_append(change):
    from tests.test_music_stopped_source_integration import make_session
    state, device, planner, play = await make_session("artist_mix")
    if change == "manual":
        planner.hook = lambda: state.audio_ownership.record_manual_intent((QUEUE_SOURCE,))
    elif change == "revoked":
        original = planner.preview
        async def preview(*args, **kwargs):
            result = await original(*args, **kwargs)
            return replace(result, candidates=()) if planner.calls == 2 else result
        planner.preview = preview
    else:
        original = state.sonos.get_prepare_evidence
        async def changed():
            result = await original()
            if change == "source":
                device.revision += 1
            else:
                state.sonos._device = object()
            return result
        state.sonos.get_prepare_evidence = changed
    assert (await play()).status != "started"
    assert not device.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["manual", "volume", "device", "uncertain"])
async def test_change_after_first_append_prevents_play(change):
    from tests.test_music_selected_manual_integration import session
    state, device, _, play = await session("artist_mix", transport="STOPPED")
    def changed():
        if change == "manual":
            state.audio_ownership.record_manual_intent((QUEUE_SOURCE,))
        elif change == "volume":
            device._volume = 12
        elif change == "device":
            state.sonos._device = object()
        else:
            device.ids[-1] = "999"
    device.after_append = changed
    receipt = await play()
    assert receipt.status == "indeterminate", receipt
    assert device.writes == ["Append:11"]
    assert (await play()).status == "suppressed"
