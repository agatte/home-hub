import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.services.music_favorite_execution import start_selected_favorite
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
        self.other = SimpleNamespace(title=item.title, uri="file:///jffs/settings/savedqueues.rsq#2")
        self.playlists = [self.other, self.target]
        self.reference = SimpleNamespace(resources=[SimpleNamespace(uri=item.uri)])
        self.favorites = [SimpleNamespace(title=item.title, reference=self.reference)]
        self.music_library = SimpleNamespace(get_sonos_favorites=lambda: self.favorites)

    def get_sonos_playlists(self):
        return self.playlists

    def add_to_queue(self, item):
        self.sonos.writes.append(("append", item))
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

    def _queue_item_snapshot_sync(self, index, timeout):
        xml = "<DIDL-Lite><item><res>x-sonos-http:song%3a123?sid=204</res></item></DIDL-Lite>"
        return "new", self.size, xml

    def _prepare_evidence_sync(self):
        self.snap_calls += 1
        xml = self._queue_item_snapshot_sync(0, 1)[2]
        return {
            "queue_uid": "speaker", "queue_size": self.size,
            "queue_update_id": "new" if self.size else "old",
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
        assert size == 3
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


async def start(sonos, selected=None):
    return await start_selected_favorite(
        sonos, selected or plan(), mutation_runner=sonos.run, preflight=sonos.preflight,
        still_current=lambda: sonos.current,
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
