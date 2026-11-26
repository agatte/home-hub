"""Simulated Sonos integration: real selection, policy, prepare and executors."""
import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from soco.data_structures import DidlPlaylistContainer, DidlResource

from backend.services.audio_ownership import AudioOwnershipService, QUEUE_SOURCE, VOLUME
from backend.services.music_assisted_playback import MusicAssistedPlaybackService
from backend.services.music_requests import FamiliarMusicSuggestion
from backend.services.music_selected_plan import SelectedListeningPlan
from backend.services.music_session_service import ListeningSessionService
from backend.services.sonos_service import SonosService
from tests.test_music_favorite_execution import candidate as favorite_candidate
from tests.test_music_selected_plan import request, song


class Device:
    """UPnP simulator with exact queue revision, source and advancing position."""
    uid = "speaker"
    is_coordinator = True
    mute = False
    play_mode = "NORMAL"

    def __init__(self):
        self.avTransport = self.contentDirectory = self.renderingControl = self
        self.state = "STOPPED"
        self.media = self.track = "http://example.invalid/music.mp3"
        self.metadata = (
            '<DIDL-Lite><item><class>object.item.audioItem.musicTrack</class>'
            f'<res protocolInfo="http-get:*:audio/mpeg:*">{self.track}</res></item></DIDL-Lite>'
        )
        self.ids = []
        self.revision = 1
        self.index = 1
        self.position = 0
        self.writes = []
        self._volume = 15
        self.refuse_volume = False
        self.after_unload = lambda: None
        self.uncertain = False
        item = favorite_candidate()
        self.playlist = DidlPlaylistContainer(
            item.title, "SQ:", "SQ:1",
            resources=[DidlResource(item.uri, "x-file-cifs:*:*:*")],
        )

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value):
        self.writes.append(f"Volume:{value}")
        if not self.refuse_volume:
            self._volume = value

    @property
    def queue_size(self):
        return len(self.ids)

    resource_scheme = "x-sonos-http"

    def resource(self, identity):
        return f"{self.resource_scheme}:song%3a{identity}?sid=204"

    def row(self, identity):
        return (f"<item><title>Track {identity}</title><artist>Artist</artist>"
                f"<res>{self.resource(identity)}</res></item>")

    def Browse(self, args, **kwargs):
        values = dict(args)
        offset = int(values["StartingIndex"])
        limit = int(values["RequestedCount"])
        rows = self.ids[offset:offset+limit]
        return {"NumberReturned": str(len(rows)), "TotalMatches": str(len(self.ids)),
                "UpdateID": str(self.revision),
                "Result": "<DIDL-Lite>" + "".join(self.row(i) for i in rows) + "</DIDL-Lite>"}

    def GetTransportSettings(self, args, **kwargs):
        return {"PlayMode": self.play_mode}

    def GetTransportInfo(self, args, **kwargs):
        return {"CurrentTransportState": self.state}

    def GetMediaInfo(self, args, **kwargs):
        return {"CurrentURI": self.media, "CurrentURIMetaData": self.metadata}

    def GetPositionInfo(self, args, **kwargs):
        position = self.position
        if self.state == "PLAYING":
            self.position += 1
        return {"Track": str(self.index), "TrackURI": self.track,
                "TrackMetaData": self.metadata, "RelTime": f"0:00:{position:02}",
                "TrackDuration": "0:03:00"}

    def get_current_transport_info(self):
        return {"current_transport_state": self.state}

    def get_current_track_info(self):
        return {"uri": self.track, "title": "Music" if self.track else ""}

    def GetVolume(self, args, **kwargs):
        return {"CurrentVolume": str(self.volume)}

    def GetMute(self, args, **kwargs):
        return {"CurrentMute": str(int(self.mute))}

    def SetAVTransportURI(self, args, **kwargs):
        uri = dict(args)["CurrentURI"]
        if uri == "":
            self.writes.append("Unload")
            if not self.uncertain:
                self.media = self.track = self.metadata = ""
            self.after_unload()
        else:
            assert uri == "x-rincon-queue:speaker#0"
            assert not self.media and not self.track
            self.writes.append("SetQueue")
            self.media = uri

    def AddURIToQueue(self, args, **kwargs):
        values = dict(args)
        uri = values["EnqueuedURI"]
        assert self.media == self.track == ""
        first = len(self.ids) + 1
        if uri == favorite_candidate().uri:
            self.writes.append("AppendPlaylist")
            new_ids = ["121", "122"]
        else:
            identity = unquote(uri).removeprefix("song:")
            assert identity in {"11", "12"}
            self.writes.append("Append:" + identity)
            new_ids = [identity]
        self.ids.extend(new_ids)
        self.revision += 1
        return {"FirstTrackNumberEnqueued": str(first), "NumTracksAdded": str(len(new_ids)),
                "NewQueueLength": str(len(self.ids))}

    def get_sonos_playlists(self):
        return [self.playlist]

    def Seek(self, args, **kwargs):
        self.index = int(dict(args)["Target"])
        self.track = self.resource(self.ids[self.index-1])
        self.writes.append("Seek")

    def Play(self, args, **kwargs):
        self.state = "PLAYING"
        self.writes.append("Play")


async def make_session(kind):
    async def load(_):
        return {}

    async def save(*_):
        pytest.fail("Unexpected persistent ownership write")

    device = Device()
    sonos = SonosService()
    sonos._connected, sonos._device = True, device
    state = SimpleNamespace(
        sonos=sonos,
        audio_ownership=AudioOwnershipService(setting_loader=load, setting_saver=save),
        music_mapper=SimpleNamespace(_manual_music_block_revision=0),
        automation=SimpleNamespace(current_mode="general", house_state="home",
                                   is_dnd_active=lambda: False, _get_time_period=lambda: "night"),
        away_manager=SimpleNamespace(away=False), tts=SimpleNamespace(is_speaking=False),
        ambient_sound=SimpleNamespace(get_state=lambda: {}),
    )
    assisted = object.__new__(MusicAssistedPlaybackService)
    assisted._app_state, assisted._lifecycle_state = state, lambda: {}
    state.music_assisted_playback = assisted
    req = request()
    if kind == "favorite":
        item = favorite_candidate()
        req = replace(req, familiar_suggestions=(FamiliarMusicSuggestion(item, 1, "familiar", 1, ()),),
                      discovery=None)
        choice = "sonos_favorite:" + item.provider_id
        selected = SelectedListeningPlan(choice, kind, "execution_not_connected", (item,))
    else:
        choice = "artist_mix:11,12"
        # The real SoCo canonicalizer accepts the album URL with track query.
        # Use actual supported share-link shape rather than a synthetic song URL.
        tracks = tuple(
            replace(song(identity), uri=url, playback_reference=url)
            for identity in ("11", "12")
            for url in (f"https://music.apple.com/us/album/example/1?i={identity}",)
        )
        selected = SelectedListeningPlan(choice, kind, "execution_not_connected", tracks)

    class Planner:
        calls = 0
        def hook(self):
            pass

        async def preview(self, request, choice_id, *, limit):
            self.calls += 1
            assert choice_id == choice
            if self.calls == 2:
                self.hook()
            return selected

    planner = Planner()
    service = ListeningSessionService(state, planner)
    token = service.issue(req, owner_scope="owner")["token"]

    async def start():
        return await service.start(token, choice, owner_scope="owner", authorized=lambda: True)

    return state, device, planner, start


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["artist_mix", "favorite"])
@pytest.mark.parametrize("unloaded", [False, True])
@pytest.mark.parametrize("scheme", ["x-sonos-http", "x-sonosapi-hls-static"])
async def test_above_ceiling_is_capped_before_start(kind, unloaded, scheme):
    _, device, _, start = await make_session(kind)
    device.resource_scheme = scheme
    device._volume = 25
    if unloaded:
        device.media = device.track = device.metadata = ""
    result = await start()
    assert result.status == "started", result
    assert device.writes[0] == "Volume:18"
    assert device.volume == 18
    assert "Play" in device.writes
    if not unloaded:
        assert device.writes[1] == "Unload"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source", "manual", "volume", "readback"])
async def test_cap_refusal_stops_all_following_writes(change):
    state, device, planner, start = await make_session("artist_mix")
    device._volume = 25
    if change == "source":
        device.media = device.track = "x-rincon-stream:external"
    elif change == "manual":
        planner.hook = lambda: state.audio_ownership.record_manual_intent((QUEUE_SOURCE,))
    elif change == "volume":
        planner.hook = lambda: setattr(device, "_volume", 24)
    else:
        device.refuse_volume = True
    result = await start()
    assert result.status == ("indeterminate" if change == "readback" else "suppressed"), result
    assert device.writes == (["Volume:18"] if change == "readback" else [])


@pytest.mark.asyncio
async def test_explicit_start_fences_older_volume_authority():
    state, device, planner, start = await make_session("artist_mix")
    device._volume = 25
    old = await state.audio_ownership.capture_opportunistic((VOLUME,))
    observed = []
    planner.hook = lambda: observed.append(state.audio_ownership.opportunistic_is_current(old))
    assert (await start()).status == "started"
    assert observed == [False]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["artist_mix", "favorite"])
@pytest.mark.parametrize("scheme", ["x-sonos-http", "x-sonosapi-hls-static"])
async def test_stopped_source_real_prepare_and_executor(kind, scheme):
    _, device, _, start = await make_session(kind)
    device.resource_scheme = scheme
    result = await start()
    assert result.status == "started", result
    appends = ["Append:11", "Append:12"] if kind == "artist_mix" else ["AppendPlaylist"]
    assert device.writes == ["Unload", *appends, "SetQueue", "Seek", "Play"]
    assert device.volume == 15 and not device.mute
    assert (await start()).status == "suppressed"
    assert device.writes == ["Unload", *appends, "SetQueue", "Seek", "Play"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["artist_mix", "favorite"])
@pytest.mark.parametrize("change", ["source", "uncertain", "manual"])
async def test_stopped_source_real_refusal_or_uncertainty_never_appends(kind, change):
    state, device, planner, start = await make_session(kind)
    if change == "source":
        def change_source():
            device.media = device.track = "x-rincon-stream:external"
        planner.hook = change_source
    elif change == "uncertain":
        device.uncertain = True
    else:
        device.after_unload = lambda: state.audio_ownership.record_manual_intent((QUEUE_SOURCE,))
    result = await start()
    assert result.status == ("suppressed" if change == "source" else "indeterminate"), result
    assert device.writes == ([] if change == "source" else ["Unload"])
    assert (await start()).status == "suppressed"
    assert not device.ids


@pytest.mark.asyncio
async def test_stopped_source_cancel_during_real_unload_never_appends():
    _, device, _, start = await make_session("artist_mix")
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def hold():
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=3)

    device.after_unload = hold
    task = asyncio.create_task(start())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert device.writes == ["Unload"]
    assert (await start()).status == "suppressed"

@pytest.mark.asyncio
async def test_cross_artist_mood_mix_real_planner_prepare_and_executor():
    from tests.test_music_selected_plan import Approvals, Catalog, Taste
    from backend.services.music_selected_plan import SelectedListeningPlanner

    state, device, _, _ = await make_session("artist_mix")
    original = request(album=True)
    cluster = original.discovery.clusters[0]
    first = replace(cluster, tracks=(cluster.tracks[0],))
    second_track = replace(cluster.tracks[1], artist_name="Other", album_provider_id="456",
                           album_external_url="https://music.apple.com/us/album/other/456")
    second = replace(cluster, artist_name="Other", tracks=(second_track,))
    req = replace(original, familiar_suggestions=(),
                  discovery=replace(original.discovery, clusters=(first, second)))
    items = {}
    for identity, artist in (("11", "Artist"), ("12", "Other")):
        url = f"https://music.apple.com/us/album/example/1?i={identity}"
        candidate = song(identity)
        items[identity] = replace(candidate, uri=url, playback_reference=url,
                                  metadata={**candidate.metadata, "artist_name": artist})
    catalog = Catalog(items)
    planner = SelectedListeningPlanner(catalog=catalog, taste_provider=Taste(), approval_service=Approvals())
    service = ListeningSessionService(state, planner)
    issued = service.issue(req, owner_scope="owner")
    assert issued["choice_ids"] == ["artist_mix:11,12"]
    result = await service.start(issued["token"], "artist_mix:11,12", owner_scope="owner",
                                 authorized=lambda: True)
    assert result.status == "started", result
    assert device.writes == ["Unload", "Append:11", "Append:12", "SetQueue", "Seek", "Play"]
    assert catalog.calls == [("itunes_search", identity) for identity in ("11", "12", "11", "12")]

    # A current artist mismatch must veto the whole selection before device I/O.
    state, device, _, _ = await make_session("artist_mix")
    items["12"] = replace(items["12"], metadata={**items["12"].metadata, "artist_name": "Wrong"})
    service = ListeningSessionService(state, planner)
    issued = service.issue(req, owner_scope="owner")
    result = await service.start(issued["token"], "artist_mix:11,12", owner_scope="owner",
                                 authorized=lambda: True)
    assert result.reason == "mix_member_not_verified"
    assert not device.writes
