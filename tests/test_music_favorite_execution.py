import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.services.music_continuation import QueuedSong
from backend.services.music_favorite_execution import start_selected_favorite
from tests.test_music_continuation import candidate as related_candidate
from backend.services.music_selected_plan import SelectedListeningPlan
from backend.services.playlist_catalog import VerifiedMusicCandidate


def candidate(source="playlist", uri="file:///jffs/settings/savedqueues.rsq#1"):
    identity = hashlib.sha256(f"{source}|{uri}".encode()).hexdigest()[:16]
    return VerifiedMusicCandidate(
        "sonos_favorite", identity, "favorite", "Evening", uri, source,
        playback_capability="supported", playback_adapter="sonos_favorite_title",
        playback_reference="Evening",
    )


def plan(source="playlist"):
    item = candidate(source)
    return SelectedListeningPlan("sonos_favorite:" + item.provider_id, "favorite",
                                 "execution_not_connected", (item,))


class Device:
    uid = "speaker"

    def __init__(self, sonos):
        self.sonos = sonos
        item = candidate()
        self.target = SimpleNamespace(title=item.title, uri=item.uri)
        self.target.resources = [SimpleNamespace(uri=item.uri)]
        self.other = SimpleNamespace(title=item.title, uri="file:///jffs/settings/savedqueues.rsq#2")
        self.playlists = [self.other, self.target]
        self.reference = SimpleNamespace(resources=[SimpleNamespace(uri=item.uri)])
        self.favorites = [SimpleNamespace(title=item.title, reference=self.reference)]
        self.music_library = SimpleNamespace(get_sonos_favorites=lambda: self.favorites)
        self.avTransport = SimpleNamespace(AddURIToQueue=self.append_container)
        self.contentDirectory = SimpleNamespace(Browse=self.browse)

    def append_container(self, args, *, timeout):
        assert timeout == 5.0
        args = dict(args)
        item = self.target if args["EnqueuedURIMetaData"] == "playlist" else self.reference
        assert args["EnqueuedURI"] == item.resources[0].uri
        assert args["DesiredFirstTrackNumberEnqueued"] == args["EnqueueAsNext"] == 0
        self.add_to_queue(item)
        return {"FirstTrackNumberEnqueued": "1",
                "NumTracksAdded": str(self.sonos.receipt_count),
                "NewQueueLength": str(self.sonos.receipt_count)}

    def browse(self, args, *, timeout):
        assert timeout == 3.0
        size = self.sonos.size
        xml = "<DIDL-Lite>" + "".join(self.sonos.item_xml(i) for i in range(size)) + "</DIDL-Lite>"
        return {"UpdateID": self.sonos.revision(), "TotalMatches": size,
                "NumberReturned": size, "Result": xml}

    def get_sonos_playlists(self):
        return self.playlists

    def add_to_queue(self, item):
        self.sonos.writes.append(("append", item))
        self.sonos.tracks = ["121", "122", "123"]
        self.sonos.size = 3
        if self.sonos.fail_append:
            raise RuntimeError("response lost")
        return 1


class Sonos:
    def __init__(self):
        self.size = 0
        self.device = Device(self)
        self.writes = []
        self.current = True
        self.admitted = True
        self.verify = True
        self.fail_append = False
        self.bad_source = False
        self.change_before_append = False
        self.change_before_play = False
        self.snap_calls = 0
        self.receipt_count = 3
        self.tracks = []
        self.bad_metadata = False

    def revision(self):
        return str(self.size)

    def item_xml(self, index):
        identity = self.tracks[index] if index < len(self.tracks) else "123"
        artist = "Related" if identity.startswith("2") else "Artist"
        title = "" if self.bad_metadata else f"<title>Track {identity}</title>"
        return f"<item>{title}<artist>{artist}</artist><res>x-sonos-http:song%3a{identity}?sid=204</res></item>"

    def _queue_item_snapshot_sync(self, index, timeout):
        xml = "<DIDL-Lite>" + self.item_xml(index) + "</DIDL-Lite>"
        return self.revision(), self.size, xml

    def _canonical_apple_music_share_link(self, uri):
        return "song:" + uri.rsplit("/", 1)[-1]

    def _add_apple_music_share_link_sync(self, uri):
        identity = uri.rsplit("/", 1)[-1]
        self.writes.append(("tail", identity))
        self.tracks.append(identity)
        self.size += 1
        return self.size

    def _prepare_evidence_sync(self):
        self.snap_calls += 1
        xml = self._queue_item_snapshot_sync(0, 1)[2]
        return {
            "queue_uid": "speaker", "queue_size": self.size,
            "queue_update_id": self.revision(),
            "queue_first_item_hash": hashlib.sha256(xml.encode()).hexdigest() if self.size else None,
            "volume": 15, "mute": False, "coordinator": True,
            "play_mode": "NORMAL", "transport_state": "STOPPED",
            "current_uri": "x-rincon-stream:external" if (
                self.bad_source or (self.change_before_play and self.snap_calls >= 4)
            ) else "",
            "queue_track_uri": "", "metadata": "", "media_metadata": "", "title": "",
        }

    async def get_prepare_evidence(self):
        return self._prepare_evidence_sync()

    def prepare_unloaded(self, evidence):
        return evidence["queue_size"] == 0 and not evidence["current_uri"]

    async def _safe_call(self, fn, *args):
        return fn(*args)

    async def _safe_mutation_call(self, fn):
        if self.change_before_append:
            self.size = 1
        return fn()

    def _play_queue_item_if_unchanged_sync(self, index, size, snapshot, **kwargs):
        assert size == self.size
        assert snapshot == self._queue_item_snapshot_sync(0, 1)
        assert kwargs == {"queue_uid": "speaker", "max_volume": 15}
        self.writes.append(("play", index))
        return True

    async def _verify_queue_playback_started(self, *args, **kwargs):
        return self.verify

    async def preflight(self, *, expected_queue_size):
        return {"reason": None if self.size == expected_queue_size else "queue_changed",
                "volume_used": 15}

    async def run(self, operation):
        return await operation() if self.admitted else None


async def start(sonos, selected=None, continuation_planner=None):
    return await start_selected_favorite(
        sonos, selected or plan(), mutation_runner=sonos.run, preflight=sonos.preflight,
        still_current=lambda: sonos.current, continuation_planner=continuation_planner,
    )


@pytest.fixture(autouse=True)
def serialize_fake_container(monkeypatch):
    monkeypatch.setattr(
        "backend.services.music_favorite_execution.to_didl_string",
        lambda item: "playlist" if hasattr(item, "title") else "favorite",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["playlist", "favorite"])
async def test_exact_source_and_uri_not_same_title(source):
    sonos = Sonos()
    result = await start(sonos, plan(source))
    assert result.status == "started"
    assert result.confirmed_appends == 1
    expected = sonos.device.target if source == "playlist" else sonos.device.reference
    assert sonos.writes == [("append", expected), ("play", 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["duplicate", "changed", "renamed", "busy", "stale", "denied", "forged", "race"])
async def test_refuses_before_write(problem):
    sonos = Sonos()
    selected = plan()
    if problem == "duplicate":
        sonos.device.playlists.append(sonos.device.target)
    elif problem == "changed":
        sonos.device.target.uri = "other"
    elif problem == "renamed":
        sonos.device.target.title = "Other name"
    elif problem == "busy":
        sonos.size = 1
    elif problem == "stale":
        sonos.current = False
    elif problem == "denied":
        sonos.admitted = False
    elif problem == "forged":
        selected = replace(selected, choice_id="sonos_favorite:unknown")
    else:
        sonos.change_before_append = True
    result = await start(sonos, selected)
    assert result.status == "suppressed"
    assert sonos.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["lost_append", "external_source", "unverified"])
async def test_uncertain_outcome_never_retries_or_clears(problem):
    sonos = Sonos()
    if problem == "lost_append":
        sonos.fail_append = True
    elif problem == "external_source":
        sonos.change_before_play = True
    else:
        sonos.verify = False
    result = await start(sonos)
    assert result.status == "indeterminate"
    assert sonos.size == 3
    assert sonos.writes == [("append", sonos.device.target)] + (
        [("play", 0)] if problem == "unverified" else []
    )

class Continuation:
    def __init__(self, sonos, *, changed=False, revoked=False, duplicate=False):
        self.sonos = sonos
        self.changed = changed
        self.revoked = revoked
        self.duplicate = duplicate
        self.calls = 0

    async def preview_container(self, songs, *, mode):
        self.calls += 1
        assert songs == tuple(QueuedSong(i, f"Track {i}", "Artist") for i in ("121", "122", "123"))
        if self.changed:
            self.sonos.tracks[1] = "999"
        return (related_candidate("121" if self.duplicate else "21"), related_candidate("22"))

    async def revalidate(self, tail, *, mode):
        return not self.revoked


@pytest.mark.asyncio
async def test_playlist_tail_preserves_all_original_tracks_and_plays_once():
    sonos = Sonos()
    planner = Continuation(sonos)
    result = await start(sonos, continuation_planner=planner)
    assert result.status == "started"
    assert result.continuation_tracks == 2
    assert sonos.tracks == ["121", "122", "123", "21", "22"]
    assert sonos.writes == [("append", sonos.device.target), ("tail", "21"), ("tail", "22"), ("play", 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["changed", "duplicate", "receipt"])
async def test_unverified_container_or_tail_never_plays(problem):
    sonos = Sonos()
    planner = Continuation(sonos, changed=problem == "changed", duplicate=problem == "duplicate")
    if problem == "receipt":
        sonos.receipt_count = 2
    result = await start(sonos, continuation_planner=planner)
    assert result.status == "indeterminate"
    assert sonos.writes == [("append", sonos.device.target)]


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["unknown_metadata", "revoked"])
async def test_optional_tail_abstains_and_original_playlist_starts(problem):
    sonos = Sonos()
    sonos.bad_metadata = problem == "unknown_metadata"
    planner = Continuation(sonos, revoked=problem == "revoked")
    result = await start(sonos, continuation_planner=planner)
    assert result.status == "started"
    assert result.continuation_tracks == 0
    assert sonos.writes == [("append", sonos.device.target), ("play", 0)]
    assert planner.calls == (0 if sonos.bad_metadata else 1)
