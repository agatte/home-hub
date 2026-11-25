import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.services.audio_ownership import AudioOwnershipService, QUEUE_SOURCE
from backend.services.music_mix_execution import MixStartResult
from backend.services.music_selected_plan import SelectedListeningPlan
from backend.services.music_session_service import ListeningSessionService, MAX_TICKETS
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
async def test_tail_is_revalidated_under_shared_admission(monkeypatch, revoked):
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
