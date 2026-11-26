"""Real selected session, authority and Sonos service against native queue shapes."""
import pytest

from backend.services.audio_ownership import AudioOwnershipService, VOLUME, TRANSPORT
from backend.services.music_sustained_listening import started_queue_proof, sample_cursor
from tests.test_music_stopped_source_integration import Device, make_session


class ManualDevice(Device):
    resource_scheme = "x-sonosapi-hls-static"

    def resource(self, identity):
        if identity in {"foreign", "cloud-track"}:
            return f"http://example.invalid/{identity}.mp3"
        return super().resource(identity)

    def row(self, identity):
        if identity in {"21", "22"}:
            return (f"<item><title>Track {identity}</title><artist>Related</artist>"
                    f"<res>{self.resource(identity)}</res></item>")
        return super().row(identity)

    def AddURIToQueue(self, args, **kwargs):
        # Unlike the old simulator, the speaker may have an active source.
        from urllib.parse import unquote
        from tests.test_music_favorite_execution import candidate as favorite_candidate
        uri = dict(args)["EnqueuedURI"]
        first = len(self.ids) + 1
        if uri == favorite_candidate().uri:
            self.writes.append("AppendPlaylist")
            new_ids = getattr(self, "saved_tracks", ["121", "122"])
        elif uri == getattr(self, "cloud_uri", None):
            self.writes.append("AppendCloud")
            new_ids = self.cloud_tracks
        else:
            identity = unquote(uri).removeprefix("song:")
            assert identity in {"11", "12", "21", "22"}
            self.writes.append("Append:" + identity)
            new_ids = [identity]
        self.ids.extend(new_ids)
        self.revision += 1
        self.after_append()
        return {"FirstTrackNumberEnqueued": str(first), "NumTracksAdded": str(len(new_ids)),
                "NewQueueLength": str(len(self.ids))}

    def __init__(self):
        super().__init__()
        self.after_append = lambda: None

    def Stop(self, args, **kwargs):
        self.state = "STOPPED"
        self.position = 0
        self.writes.append("Stop")

    def SetPlayMode(self, args, **kwargs):
        self.play_mode = dict(args)["NewPlayMode"]
        self.writes.append("Mode:" + self.play_mode)

    def SetAVTransportURI(self, args, **kwargs):
        uri = dict(args)["CurrentURI"]
        assert uri == "x-rincon-queue:speaker#0"
        self.media = uri
        self.writes.append("SetQueue")


async def session(kind, *, transport="PLAYING", volume=0, house="sleeping",
                  prefix=True, shuffle=False):
    state, _, planner, start = await make_session(kind)
    async def load(_):
        return {}
    async def save(*_):
        pass
    state.audio_ownership = AudioOwnershipService(setting_loader=load, setting_saver=save)
    state.automation.house_state = house
    state.automation.current_mode = "sleeping" if house == "sleeping" else "general"
    state.automation.is_dnd_active = lambda: True
    state.bootstrap_ready = True
    device = ManualDevice()
    device._volume = volume
    device.state = transport
    if prefix:
        device.ids = ["foreign"]
        device.media = "x-rincon-queue:speaker#0"
        device.track = device.resource("foreign")
        device.metadata = ""
    else:
        device.media = device.track = device.metadata = ""
    if shuffle:
        device.play_mode = "SHUFFLE"
    state.sonos._device = device
    return state, device, planner, start


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["artist_mix", "favorite"])
@pytest.mark.parametrize("transport", ["PLAYING", "PAUSED_PLAYBACK", "STOPPED"])
@pytest.mark.parametrize("volume", [0, 10, 50])
async def test_explicit_manual_start_preserves_foreign_prefix(kind, transport, volume):
    _, device, _, start = await session(kind, transport=transport, volume=volume)
    result = await start()
    assert result.status == "started", (result, device.writes)
    assert device.ids == ["foreign", *(["11", "12"] if kind == "artist_mix" else ["121", "122"])]
    assert device.state == "PLAYING" and device.index == 2
    assert device.volume == (10 if volume == 10 else 18)
    assert device.writes[-3:] == ["SetQueue", "Seek", "Play"]
    assert not any(w.startswith("Clear") for w in device.writes)
    if transport != "STOPPED" and volume != 10:
        assert device.writes.index("Stop") < device.writes.index("Volume:18")
    assert (await start()).status == "suppressed"


@pytest.mark.asyncio
async def test_unloaded_orphan_and_shuffle():
    _, device, _, start = await session("artist_mix", transport="STOPPED", shuffle=True)
    device.media = device.track = device.metadata = ""
    result = await start()
    assert result.status == "started", (result, device.writes)
    assert device.ids == ["foreign", "11", "12"]
    assert device.index == 2 and device.play_mode == "NORMAL"


@pytest.mark.asyncio
async def test_empty_queue_also_works():
    _, device, _, start = await session("artist_mix", transport="STOPPED", prefix=False)
    result = await start()
    assert result.status == "started", (result, device.writes)
    assert device.ids == ["11", "12"] and device.index == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", [VOLUME, TRANSPORT])
async def test_later_manual_intent_fences_queued_start(dimension):
    state, device, _, start = await session("artist_mix")
    device.after_append = lambda: state.audio_ownership.record_manual_intent((dimension,))
    result = await start()
    assert result.status == "indeterminate", result
    assert device.writes == ["Append:11"]
    assert device.volume == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["away", "tts", "mute", "tv", "prefix"])
async def test_real_conflict_prevents_start(change):
    state, device, _, start = await session("artist_mix")
    if change == "away":
        state.away_manager.away = True
    elif change == "tts":
        state.tts.is_speaking = True
    elif change == "mute":
        device.mute = True
    elif change == "tv":
        device.media = device.track = "x-sonos-htastream:tv"
    else:
        def replace_prefix():
            device.ids[0] = "changed"
        device.after_append = replace_prefix
    result = await start()
    assert result.status != "started", result
    assert "Play" not in device.writes and device.volume == 0


@pytest.mark.asyncio
async def test_suffix_proof_does_not_claim_foreign_entry():
    state, device, _, start = await session("artist_mix", transport="STOPPED")
    assert (await start()).status == "started"
    from backend.services.music_sustained_listening import _read_prefix_sync
    first = state.sonos._queue_item_snapshot_sync(0)
    rows = _read_prefix_sync(device, len(device.ids), first[0])
    proof = started_queue_proof(first, device.uid, device.volume, rows, offset=1)
    assert proof is not None and proof.total_tracks == 3
    assert [s.provider_id for s in proof.songs] == ["11", "12"]
    evidence = state.sonos._prepare_evidence_sync()
    assert sample_cursor(proof, evidence, now=0) is not None
    assert sample_cursor(proof, dict(evidence, queue_track=1), now=0) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("non_apple", [False, True])
async def test_long_saved_playlist_uses_exact_native_resources(non_apple):
    from backend.services.music_sustained_listening import SustainedListening
    from tests.test_music_sustained_listening import Planner

    state, device, _, play = await session("favorite", transport="STOPPED")
    device.saved_tracks = ["cloud-track" if non_apple else "121"] + [str(i) for i in range(200, 239)]
    state.listening_session._sustained = SustainedListening(Planner())
    result = await play()
    assert result.status == "started", (result, device.writes)
    assert device.ids == ["foreign", *device.saved_tracks]
    assert device.index == 2 and device.volume == 18
    assert result.sustained_listening is (not non_apple)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [95, 100, 256])
async def test_large_existing_queue_does_not_consume_session_budget(size):
    from backend.services.music_sustained_listening import SustainedListening
    from tests.test_music_sustained_listening import Planner

    state, device, _, play = await session("artist_mix", transport="STOPPED")
    prefix = ["foreign"] * size
    device.ids = list(prefix)
    state.listening_session._sustained = SustainedListening(Planner())
    result = await play()
    assert result.status == "started" and result.sustained_listening, result
    assert device.ids == [*prefix, "11", "12"]
    assert device.index == size + 1
    proof = state.listening_session._sustained._active.proof
    assert proof.offset == size and len(proof.songs) == 2


@pytest.mark.asyncio
async def test_saved_playlist_changed_after_native_append_never_plays():
    _, device, _, play = await session("favorite", transport="STOPPED")
    device.saved_tracks = ["cloud-track", "121"]
    device.after_append = lambda: device.ids.__setitem__(-1, "999")
    result = await play()
    assert result.status == "indeterminate"
    assert device.writes == ["AppendPlaylist"]
    assert device.volume == 0


@pytest.mark.asyncio
async def test_queue_capacity_refuses_without_deleting():
    from backend.services.music_sustained_listening import MAX_QUEUE_TRACKS
    _, device, _, play = await session("artist_mix", transport="STOPPED")
    device.ids = ["foreign"] * (MAX_QUEUE_TRACKS - 1)
    result = await play()
    assert result.status == "suppressed" and result.reason == "manual_queue_capacity"
    assert not device.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_cloud", [False, True])
async def test_cloud_favorite_preserves_existing_queue(foreign_cloud):
    from dataclasses import replace
    from types import SimpleNamespace
    from soco.data_structures import DidlPlaylistContainer, DidlResource
    from backend.services.music_selected_plan import SelectedListeningPlan
    from backend.services.music_sustained_listening import SustainedListening
    from tests.test_music_favorite_execution import candidate
    from tests.test_music_sustained_listening import Planner

    state, device, planner, _ = await session("favorite", transport="STOPPED")
    service = state.listening_session
    service._sustained = SustainedListening(Planner())
    item = candidate("favorite", "x-rincon-cpcontainer:cloud")
    device.cloud_uri = item.uri
    device.cloud_tracks = ["cloud-track"] if foreign_cloud else ["121", "122"]
    container = DidlPlaylistContainer(
        item.title, "FV:2", "FV:2/1", resources=[DidlResource(item.uri, "x-rincon-cpcontainer:*:*:*")],
    )
    device.music_library = SimpleNamespace(
        get_sonos_favorites=lambda: [SimpleNamespace(title=item.title, reference=container)],
    )
    choice = "sonos_favorite:" + item.provider_id
    selected = SelectedListeningPlan(choice, "favorite", "execution_not_connected", (item,))

    async def preview(*args, **kwargs):
        return selected

    planner.preview = preview
    req = state.listening_request
    req = replace(req, familiar_suggestions=(
        replace(req.familiar_suggestions[0], candidate=item),
    ))
    ticket = service.issue(req, owner_scope="owner")
    result = await service.start(ticket["token"], choice, owner_scope="owner", authorized=lambda: True)
    assert result.status == "started", (result, device.writes)
    assert device.ids == ["foreign", *device.cloud_tracks]
    assert device.index == 2 and device.volume == 18
    assert device.writes.count("AppendCloud") == 1
    assert result.sustained_listening is (not foreign_cloud)


@pytest.mark.asyncio
async def test_suffix_refill_preserves_foreign_prefix_and_manual_precedence():
    from dataclasses import replace
    from backend.services.music_sustained_listening import SustainedListening
    from tests.test_music_continuation import candidate

    state, device, _, play = await session("artist_mix", transport="STOPPED")
    service = state.listening_session
    now = [0.0]

    class Planner:
        async def preview_container(self, songs, *, mode):
            assert [song.provider_id for song in songs] == ["11", "12"]
            url = "https://music.apple.com/us/album/example/1?i=21"
            return (replace(candidate("21"), uri=url, playback_reference=url),)

        async def revalidate(self, tail, *, mode):
            return True

    service._sustained = SustainedListening(Planner(), clock=lambda: now[0])
    result = await play()
    assert result.status == "started" and result.sustained_listening
    active = service._sustained._active
    assert active.proof.offset == 1

    def position_info(args, **kwargs):
        return {"Track": str(device.index), "TrackURI": device.track,
                "TrackMetaData": device.metadata, "RelTime": f"0:00:{device.position:02}",
                "TrackDuration": "0:03:00"}

    device.GetPositionInfo = position_info
    device.position = 20
    await service._sustained.tick()
    now[0] = 4
    device.position = 24
    before = list(device.writes)
    await service._sustained.tick()
    assert device.ids == ["foreign", "11", "12", "21"]
    assert device.writes == [*before, "Append:21"]
    assert service._sustained._active is active
    assert active.proof.offset == 1 and active.proof.total_tracks == 4
    assert [song.provider_id for song in active.proof.songs] == ["11", "12", "21"]
    state.audio_ownership.record_manual_intent((VOLUME,))
    now[0] = 8
    device.position = 28
    await service._sustained.tick()
    assert service._sustained._active is None
    assert device.writes == [*before, "Append:21"]


def _native_stop_reset(device, after_stop=lambda: None):
    """Replay the physical Stop field delta witnessed November 26."""
    old_stop = device.Stop
    old_position = device.GetPositionInfo

    def position(args, **kwargs):
        result = old_position(args, **kwargs)
        if device.state == "STOPPED" and device.index == 0:
            result.update(TrackURI="", TrackMetaData="", TrackDuration="0:00:00")
        elif device.state == "PLAYING":
            result["TrackMetaData"] = (
                '<DIDL-Lite><item xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:title>Old track</dc:title></item></DIDL-Lite>'
            )
        return result

    def stop(args, **kwargs):
        old_stop(args, **kwargs)
        device.index = 0
        device.track = ""
        after_stop()

    device.GetPositionInfo = position
    device.Stop = stop


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["artist_mix", "favorite"])
@pytest.mark.parametrize("volume", [0, 18])
async def test_native_stop_reset_starts_selected_music(kind, volume):
    _, device, _, play = await session(kind, transport="PLAYING", volume=volume)
    device.ids = ["foreign"] * 4
    _native_stop_reset(device)
    result = await play()
    assert result.status == "started", (result, device.writes)
    assert device.ids == ["foreign"] * 4 + (
        ["11", "12"] if kind == "artist_mix" else ["121", "122"]
    )
    assert device.index == 5 and device.volume == 18
    assert device.writes.count("Stop") == 1
    assert device.writes[-3:] == ["SetQueue", "Seek", "Play"]
    if volume == 0:
        assert device.writes.index("Stop") < device.writes.index("Volume:18")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "source", "media_metadata", "queue_rows", "revision", "volume",
    "mute", "mode", "coordinator", "intent", "nonzero_cursor",
])
async def test_native_stop_reset_preserves_other_fences(change):
    state, device, _, play = await session("artist_mix", transport="PLAYING", volume=0)
    device.ids = ["foreign"] * 4

    def mutate():
        if change == "source":
            device.media = "x-sonos-htastream:tv"
        elif change == "media_metadata":
            device.metadata = "<DIDL-Lite/>"
        elif change == "queue_rows":
            device.ids[1] = "different"
        elif change == "revision":
            device.revision += 1
        elif change == "volume":
            device._volume = 10
        elif change == "mute":
            device.mute = True
        elif change == "mode":
            device.play_mode = "SHUFFLE"
        elif change == "coordinator":
            device.is_coordinator = False
        elif change == "intent":
            state.audio_ownership.record_manual_intent((TRANSPORT,))
        elif change == "nonzero_cursor":
            device.index = 2

    _native_stop_reset(device, mutate)
    result = await play()
    assert result.status == "indeterminate"
    assert result.reason == "manual_stop_unverified"
    assert device.writes[-1] == "Stop"
    assert "Play" not in device.writes
    assert not any(w.startswith("Volume:") for w in device.writes)
