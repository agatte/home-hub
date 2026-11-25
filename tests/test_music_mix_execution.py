from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.services.music_mix_execution import start_selected_mix
from backend.services.music_selected_plan import SelectedListeningPlan
from backend.services.playlist_catalog import VerifiedMusicCandidate


def song(identity):
    url = f"https://music.apple.com/us/song/example/{identity}"
    return VerifiedMusicCandidate(
        "itunes_search", identity, "track", f"Track {identity}", url, "synthetic",
        playback_capability="supported", playback_adapter="sonos_apple_music_share_link",
        playback_reference=url, metadata={"playback_verification": "live_verified"},
    )


def plan():
    return SelectedListeningPlan("artist_mix:11,12", "artist_mix", "execution_not_connected",
                                 (song("11"), song("12")))


class FakeSonos:
    def __init__(self):
        self.device = SimpleNamespace(uid="speaker")
        self.queue = []
        self.writes = []
        self.active = True
        self.admitted = True
        self.verify = True
        self.change_after_append = False
        self.bad_resource = False
        self.fail_play = False
        self.change_after_verification = False
        self.unknown_append = False

    def _canonical_apple_music_share_link(self, url):
        return "song:" + url.rsplit("/", 1)[-1]

    async def _safe_call(self, fn, *args):
        return fn(*args)

    async def _safe_mutation_call(self, fn):
        assert self.admitted
        return fn()

    async def get_prepare_evidence(self):
        return self._prepare_evidence_sync()

    def _prepare_evidence_sync(self):
        return {"queue_size": len(self.queue), "queue_uid": "speaker", "volume": 15}

    def prepare_unloaded(self, evidence):
        return evidence["queue_size"] == 0

    def _add_apple_music_share_link_sync(self, url):
        identity = url.rsplit("/", 1)[-1]
        self.writes.append(("append", identity))
        self.queue.append(identity)
        if self.change_after_append:
            self.active = False
        if self.unknown_append:
            raise RuntimeError("accepted append then connection lost")
        return len(self.queue)

    def _queue_item_snapshot_sync(self, index, timeout):
        identity = self.queue[index] if not self.bad_resource else "999"
        return (str(len(self.queue)), len(self.queue),
                f"<DIDL-Lite><item><res>x-sonos-http:song%3a{identity}?sid=204</res></item></DIDL-Lite>")

    def _play_queue_item_if_unchanged_sync(self, index, size, snapshot, **kwargs):
        assert self.admitted
        self.writes.append(("play", index))
        assert size == len(self.queue)
        assert snapshot == self._queue_item_snapshot_sync(index, 1)
        assert kwargs == {"queue_uid": "speaker", "max_volume": 15}
        return not self.fail_play

    async def _verify_queue_playback_started(self, *args, **kwargs):
        if self.change_after_verification:
            self.active = False
        return self.verify

    async def preflight(self, *, expected_queue_size, allowed_loaded_provider_id=None):
        reason = None if len(self.queue) == expected_queue_size else "queue_changed"
        return {"reason": reason, "volume_used": 15}

    async def run(self, operation):
        return await operation() if self.admitted else None

    def current(self):
        return self.active


async def start(fake, selected=None):
    return await start_selected_mix(
        fake, selected or plan(), mutation_runner=fake.run,
        preflight=fake.preflight, still_current=fake.current,
    )


@pytest.mark.asyncio
async def test_exact_mix_appends_in_order_and_starts_only_first_item():
    fake = FakeSonos()
    result = await start(fake)
    assert result.status == "started"
    assert result.confirmed_appends == 2
    assert fake.writes == [("append", "11"), ("append", "12"), ("play", 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("setup", ["occupied", "denied", "stale", "forged"])
async def test_refuses_before_any_write(setup):
    fake = FakeSonos()
    selected = plan()
    if setup == "occupied":
        fake.queue.append("existing")
    elif setup == "denied":
        fake.admitted = False
    elif setup == "stale":
        fake.active = False
    else:
        selected = replace(selected, choice_id="artist_mix:11,99")
    result = await start(fake, selected)
    assert result.status == "suppressed"
    assert fake.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("flag,expected", [
    ("change_after_append", 1), ("bad_resource", 0), ("unknown_append", 0),
])
async def test_partial_or_unknown_append_is_retained_and_no_play(flag, expected):
    fake = FakeSonos()
    setattr(fake, flag, True)
    result = await start(fake)
    assert result.status == "indeterminate"
    assert result.confirmed_appends == expected
    assert fake.writes == [("append", "11")]
    assert fake.queue == ["11"]


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["fail_play", "change_after_verification", "unverified"])
async def test_no_success_without_advancing_playback_and_current_authority(flag):
    fake = FakeSonos()
    if flag == "unverified":
        fake.verify = False
    else:
        setattr(fake, flag, True)
    result = await start(fake)
    assert result.status == "indeterminate"
    assert result.confirmed_appends == 2
    assert fake.queue == ["11", "12"]


@pytest.mark.asyncio
async def test_external_replacement_of_earlier_item_aborts_before_play():
    fake = FakeSonos()
    original = fake._add_apple_music_share_link_sync

    def replace_first(url):
        position = original(url)
        if position == 2:
            fake.queue[0] = "999"
        return position

    fake._add_apple_music_share_link_sync = replace_first
    result = await start(fake)
    assert result.status == "indeterminate"
    assert result.confirmed_appends == 1
    assert fake.writes == [("append", "11"), ("append", "12")]

@pytest.mark.asyncio
async def test_device_replacement_during_append_refuses_next_write():
    fake = FakeSonos()
    original = fake._add_apple_music_share_link_sync

    def append_then_replace(url):
        position = original(url)
        fake.device = SimpleNamespace(uid="speaker")
        return position

    fake._add_apple_music_share_link_sync = append_then_replace
    result = await start(fake)
    assert result.status == "indeterminate"
    assert fake.writes == [("append", "11")]


@pytest.mark.asyncio
async def test_queue_replacement_in_worker_refuses_second_append():
    fake = FakeSonos()
    original = fake._safe_mutation_call

    async def replace_before_worker(fn):
        if fake.queue:
            fake.queue[0] = "999"
        return await original(fn)

    fake._safe_mutation_call = replace_before_worker
    result = await start(fake)
    assert result.status == "indeterminate"
    assert fake.writes == [("append", "11")]
