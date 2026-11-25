import asyncio
import hashlib
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from backend.services.audio_ownership import (
    AudioOwnershipService, MANUAL_TRANSPORT_DIMENSIONS, QUEUE_SOURCE, TRANSPORT,
)
from backend.services.music_continuation import QueuedSong
from tests.test_music_continuation import candidate
from backend.services.music_sustained_listening import (
    QueueProof, PlaybackCursor, SustainedListening, continuous_progress, sample_cursor, should_refill, started_queue_proof,
)


async def authority():
    async def load(key):
        return {}

    async def save(key, value):
        pass

    service = AudioOwnershipService(setting_loader=load, setting_saver=save)
    epoch = await service.capture_opportunistic(MANUAL_TRANSPORT_DIMENSIONS, claim=True)
    token = await service.capture_listening_append(
        epoch, manual_revision=service.capture_manual_intent(),
    )
    assert token is not None
    return service, epoch, token


@pytest.mark.asyncio
async def test_poll_boundary_retires_transport_but_not_append_fence():
    service, epoch, token = await authority()
    await service.invalidate_manual(
        MANUAL_TRANSPORT_DIMENSIONS, source="sonos_poll", reason="off_dashboard_track_boundary",
    )
    assert not service.opportunistic_is_current(epoch)
    assert service.listening_append_is_current(token)
    assert await service.capture_listening_append(epoch, manual_revision=0) is None
    async def append():
        return "append"
    assert await service.run_listening_append(token, append) == (True, "append")


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["manual", "manual_write", "away", "interrupt", "claim", "lease", "other_poll", "restart"])
async def test_append_permission_cannot_survive_stronger_authority(cause):
    service, epoch, token = await authority()
    if cause == "manual":
        service.record_manual_intent([TRANSPORT])
    elif cause == "manual_write":
        async def write():
            return True
        await service.run_manual(MANUAL_TRANSPORT_DIMENSIONS, source="sonos_poll",
                                 reason="off_dashboard_track_boundary", operation=write)
    elif cause == "away":
        await service.set_lifecycle_away(True)
        await service.set_lifecycle_away(False)
    elif cause == "interrupt":
        await service.acquire_interruption(owner="tts", purpose="speech",
                                           dimensions=MANUAL_TRANSPORT_DIMENSIONS)
    elif cause == "claim":
        await service.capture_opportunistic(MANUAL_TRANSPORT_DIMENSIONS, claim=True)
    elif cause == "lease":
        await service.acquire(owner="other", purpose="music", dimensions=[QUEUE_SOURCE])
    elif cause == "other_poll":
        await service.invalidate_manual(MANUAL_TRANSPORT_DIMENSIONS, source="sonos_poll", reason="unknown")
    else:
        service, _, _ = await authority()
    assert not service.listening_append_is_current(token)
    async def forbidden():
        pytest.fail("stale append ran")
    assert await service.run_listening_append(token, forbidden) == (False, None)


def proof():
    return QueueProof("speaker", "revision", "hash", 15, tuple(
        QueuedSong(str(i), f"Track {i}", "Artist") for i in range(11, 15)
    ))


def evidence(**changes):
    return {
        "queue_uid": "speaker", "queue_update_id": "revision", "queue_first_item_hash": "hash",
        "queue_size": 4, "current_uri": "x-rincon-queue:speaker#0", "coordinator": True,
        "transport_state": "PLAYING", "play_mode": "NORMAL", "mute": False, "volume": 15,
        "queue_track": 2, "queue_track_uri": "x-sonos-http:song%3a12?sid=204",
        "position": "0:01:00", "duration": "0:03:00", **changes,
    }


@pytest.mark.parametrize("changed", [
    {"transport_state": "PAUSED_PLAYBACK"}, {"transport_state": "STOPPED"},
    {"queue_update_id": "different"}, {"queue_first_item_hash": "different"},
    {"queue_track_uri": "x-sonos-http:song%3a121?sid=204"},
    {"current_uri": "x-rincon-stream:other"}, {"queue_size": 5},
    {"play_mode": "SHUFFLE"}, {"mute": True}, {"volume": 20},
    {"coordinator": False}, {"duration": "NOT_IMPLEMENTED"}, {"queue_track": 5},
])
def test_unknown_or_changed_evidence_cannot_authorize_append(changed):
    assert sample_cursor(proof(), evidence(**changed), now=10) is None


def test_continuity_and_near_end_refill():
    current = sample_cursor(proof(), evidence(), now=10)
    assert current == PlaybackCursor(10, 2, 60, 180)
    assert continuous_progress(PlaybackCursor(5, 2, 55, 180), current)
    assert continuous_progress(PlaybackCursor(5, 1, 177, 180), PlaybackCursor(10, 2, 2, 180))
    assert should_refill(proof(), current, started_at=0)
    assert not should_refill(proof(), current, started_at=-14400)
    assert not should_refill(proof(), PlaybackCursor(10, 1, 60, 180), started_at=0)


@pytest.mark.parametrize("before,after", [
    (PlaybackCursor(0, 1, 20, 180), PlaybackCursor(5, 2, 1, 180)),
    (PlaybackCursor(0, 1, 177, 180), PlaybackCursor(5, 3, 2, 180)),
    (PlaybackCursor(0, 2, 30, 180), PlaybackCursor(5, 1, 5, 180)),
    (PlaybackCursor(0, 1, 30, 180), PlaybackCursor(5, 1, 30, 180)),
    (PlaybackCursor(0, 1, 30, 180), PlaybackCursor(5, 1, 100, 180)),
    (PlaybackCursor(0, 1, 30, 180), PlaybackCursor(13, 1, 43, 180)),
])
def test_skip_seek_stall_or_observation_gap_abstains(before, after):
    assert not continuous_progress(before, after)

class PlayingSonos:
    def __init__(self, now):
        self.now = now
        self.ids = ["11", "12", "13"]
        self.revision = 1
        self.index = 1
        self.position = 20
        self.state = "PLAYING"
        self.writes = []
        self.replace_before_worker = False
        self.fail_append = False
        self.device = SimpleNamespace(contentDirectory=SimpleNamespace(Browse=self.browse))

    def row(self, identity):
        artist = "Related" if identity.startswith("2") else "Artist"
        return f"<item><title>Track {identity}</title><artist>{artist}</artist><res>x-sonos-http:song%3a{identity}?sid=204</res></item>"

    def browse(self, args, *, timeout):
        args = dict(args)
        start = args["StartingIndex"]
        count = args["RequestedCount"]
        rows = self.ids[start:start + count]
        return {"UpdateID": str(self.revision), "TotalMatches": len(self.ids),
                "NumberReturned": len(rows),
                "Result": "<DIDL-Lite>" + "".join(self.row(i) for i in rows) + "</DIDL-Lite>"}

    def _queue_item_snapshot_sync(self, index, timeout):
        return (str(self.revision), len(self.ids),
                "<DIDL-Lite>" + self.row(self.ids[index]) + "</DIDL-Lite>")

    def rows(self):
        return tuple(ET.tostring(ET.fromstring(self.row(i)), encoding="unicode") for i in self.ids)

    def _prepare_evidence_sync(self):
        return evidence(
            queue_update_id=str(self.revision), queue_size=len(self.ids),
            queue_first_item_hash=hashlib.sha256(self._queue_item_snapshot_sync(0, 1)[2].encode()).hexdigest(),
            queue_track=self.index, queue_track_uri=f"x-sonos-http:song%3a{self.ids[self.index-1]}?sid=204",
            transport_state=self.state,
            position=f"0:{self.position//60:02}:{self.position%60:02}",
        )

    async def get_prepare_evidence(self):
        return self._prepare_evidence_sync()

    async def _safe_call(self, fn, *args):
        return fn(*args)

    async def _safe_mutation_call(self, fn):
        if self.replace_before_worker:
            self.ids[1] = "999"
        return fn()

    def _canonical_apple_music_share_link(self, url):
        return "song:" + url.rsplit("/", 1)[-1]

    def _add_apple_music_share_link_sync(self, url):
        identity = url.rsplit("/", 1)[-1]
        self.writes.append(identity)
        self.ids.append(identity)
        self.revision += 1
        if self.fail_append:
            raise RuntimeError("unknown result")
        return len(self.ids)


class Planner:
    def __init__(self):
        self.calls = 0
        self.revoked = False

    async def preview_container(self, songs, *, mode):
        self.calls += 1
        return (candidate("21"), candidate("22"))

    async def revalidate(self, tail, *, mode):
        return not self.revoked


async def installed():
    auth, _, token = await authority()
    now = [0.0]
    sonos = PlayingSonos(now)
    planner = Planner()
    service = SustainedListening(planner, clock=lambda: now[0])
    queue = started_queue_proof(sonos._queue_item_snapshot_sync(0, 1), "speaker", 15, sonos.rows())
    assert service.install(authority=auth, token=token, sonos=sonos, device=sonos.device,
                           proof=queue, rows=sonos.rows(), mode="general", allowed=lambda: True)
    await service.tick()
    return service, auth, sonos, planner, now


@pytest.mark.asyncio
async def test_refill_appends_only_preserves_order_and_updates_provenance():
    service, auth, sonos, planner, now = await installed()
    now[0] = 4
    sonos.position += 4
    await service.tick()
    assert sonos.ids == ["11", "12", "13", "21", "22"]
    assert sonos.writes == ["21", "22"]
    assert service._active.proof.revision == "3"
    assert planner.calls == 1
    # A normal poll track boundary must still retire the original transport
    # epoch; this separate session may continue only with strict progress.
    now[0] = 8
    sonos.position += 4
    await service.tick()
    assert sonos.writes == ["21", "22"]
    assert service._active is not None
    service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["paused", "stopped", "manual", "same_size_replacement", "revoked", "skip", "unknown_write"])
async def test_refill_never_restarts_or_retries(cause):
    service, auth, sonos, planner, now = await installed()
    now[0] = 4
    sonos.position += 4
    if cause == "paused":
        sonos.state = "PAUSED_PLAYBACK"
    elif cause == "stopped":
        sonos.state = "STOPPED"
    elif cause == "manual":
        auth.record_manual_intent([TRANSPORT])
    elif cause == "same_size_replacement":
        sonos.replace_before_worker = True
    elif cause == "revoked":
        planner.revoked = True
    elif cause == "skip":
        sonos.index = 2
        sonos.position = 1
    else:
        sonos.fail_append = True
    await service.tick()
    assert service._active is None
    expected = ["21"] if cause == "unknown_write" else []
    assert sonos.writes == expected
    await service.tick()
    assert sonos.writes == expected

@pytest.mark.asyncio
async def test_manual_stop_finishes_during_read_only_provider_revalidation():
    service, auth, sonos, planner, now = await installed()
    now[0] = 4
    sonos.position += 4
    entered = asyncio.Event()
    release = asyncio.Event()

    async def held_lookup(*args, **kwargs):
        entered.set()
        await release.wait()
        return True

    planner.revalidate = held_lookup
    tick = asyncio.create_task(service.tick())

    async def manual_stop():
        return True

    try:
        await asyncio.wait_for(entered.wait(), 2)
        result = await asyncio.wait_for(auth.run_manual(
            MANUAL_TRANSPORT_DIMENSIONS, source="test", reason="stop",
            operation=manual_stop,
        ), timeout=1)
        assert result is True
        assert not sonos.writes
    finally:
        release.set()
        await tick
    assert service._active is None
    assert not sonos.writes


@pytest.mark.asyncio
async def test_stale_provider_validation_waiting_for_lock_abstains():
    service, auth, sonos, planner, now = await installed()
    now[0] = 4
    sonos.position += 4
    original = auth.run_listening_append

    async def delayed(token, operation):
        now[0] += 4
        sonos.position += 4
        return await original(token, operation)

    auth.run_listening_append = delayed
    await service.tick()
    assert not sonos.writes
    assert service._active is None
