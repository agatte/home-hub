import time

import pytest
from types import SimpleNamespace

from backend.services.sonos_service import SonosService


class FakeContentDirectory:
    def __init__(self, device):
        self.device = device

    def Browse(self, args, **kwargs):
        values = dict(args)
        start = int(values.get("StartingIndex", 0))
        returned = 1 if self.device.queue_size > start else 0
        item = self.device.queue_item
        resources = tuple(
            (getattr(r, "uri", ""), getattr(r, "protocol_info", ""))
            for r in (getattr(item, "resources", None) or [])
        )
        result = repr((
            getattr(item, "title", ""), getattr(item, "creator", ""),
            getattr(item, "album", ""), getattr(item, "item_class", ""), resources,
        )) if returned else ""
        return {
            "NumberReturned": str(returned),
            "TotalMatches": str(self.device.queue_size),
            "UpdateID": str(self.device.queue_update_id),
            "Result": result,
        }


class FakeAVTransport:
    def __init__(self, device):
        self.device = device
        self.target = None
        self.current_uri = ""

    def GetTransportSettings(self, args, **kwargs):
        return {"PlayMode": self.device.play_mode}

    def GetTransportInfo(self, args, **kwargs):
        return {"CurrentTransportState": self.device.transport_state}

    def SetAVTransportURI(self, args, **kwargs):
        values = dict(args)
        self.current_uri = str(values["CurrentURI"])
        self.device.upnp_calls.append(("SetAVTransportURI", values, kwargs))
        return True

    def Seek(self, args, **kwargs):
        self.target = int(dict(args)["Target"])
        self.device.upnp_calls.append(("Seek", dict(args), kwargs))
        return True

    def GetMediaInfo(self, args, **kwargs):
        return {"CurrentURI": self.current_uri}

    def GetPositionInfo(self, args, **kwargs):
        current = self.device.position_seconds
        if self.device.transport_state == "PLAYING" and self.device.advance_position:
            self.device.position_seconds += 1
        seconds = max(0, int(current))
        return {
            "Track": str(self.target or 0),
            "RelTime": f"0:00:{seconds:02d}",
        }

    def Play(self, args, **kwargs):
        self.device.calls.append(("play_from_queue", self.target - 1))
        self.device.upnp_calls.append(("Play", dict(args), kwargs))
        self.device.transport_state = self.device.transport_state_on_play
        if self.device.volume_on_play is not None:
            self.device.volume = self.device.volume_on_play
        if self.device.source_on_play is not None:
            self.current_uri = self.device.source_on_play
        if self.device.mutate_queue_on_play:
            self.device.queue_update_id += 1
        return True


class FakeRenderingControl:
    def __init__(self, device):
        self.device = device

    def GetVolume(self, args, **kwargs):
        return {"CurrentVolume": str(self.device.volume)}

    def GetMute(self, args, **kwargs):
        return {"CurrentMute": "1" if self.device.mute else "0"}


class FakeDevice:
    def __init__(self):
        self.calls = []
        self.upnp_calls = []
        self.play_mode = "SHUFFLE"
        self.queue_size = 0
        self.transport_state = "STOPPED"
        self.queue_update_id = 1
        self.position_seconds = 0
        self.advance_position = True
        self.transport_state_on_play = "PLAYING"
        self.volume_on_play = None
        self.source_on_play = None
        self.mutate_queue_on_play = False
        self.volume = 20
        self.mute = False
        self.uid = "RINCON_TEST"
        self.queue_item = SimpleNamespace(
            title="Bang!", creator="AJR", album="OK ORCHESTRA",
            item_class="object.item.audioItem.musicTrack",
            resources=[SimpleNamespace(
                uri="x-sonos-http:librarytrack%3aa.1713833576.mp4?sid=204",
                protocol_info="x-sonos-http:*:audio/mp4:*",
            )],
        )
        self.contentDirectory = FakeContentDirectory(self)
        self.avTransport = FakeAVTransport(self)
        self.renderingControl = FakeRenderingControl(self)

    def clear_queue(self):
        self.calls.append(("clear_queue",))

    def play_from_queue(self, index):
        self.calls.append(("play_from_queue", index))

    def remove_from_queue(self, index):
        self.calls.append(("remove_from_queue", index))
        self.queue_size -= 1

    def get_queue(self, start=0, max_items=100):
        return [self.queue_item]

    def get_current_transport_info(self):
        return {"current_transport_state": self.transport_state}


@pytest.mark.asyncio
async def test_apple_share_executor_rejects_mismatched_provider_identity(monkeypatch):
    sonos = SonosService()
    sonos._connected = True
    sonos._device = FakeDevice()
    monkeypatch.setattr(
        sonos, "_canonical_apple_music_share_link",
        lambda url: "song:111",
    )

    result = await sonos.play_apple_music_share_link(
        "222", "https://music.apple.com/us/album/example/1?i=111",
    )

    assert result is False
    assert sonos._device.calls == []


@pytest.mark.asyncio
async def test_apple_share_executor_queues_and_plays_exact_identity(monkeypatch):
    sonos = SonosService()
    sonos._connected = True
    sonos._device = FakeDevice()
    url = "https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4"
    monkeypatch.setattr(
        sonos, "_canonical_apple_music_share_link",
        lambda value: "song:1713833576" if value == url else None,
    )
    monkeypatch.setattr(
        sonos, "_add_apple_music_share_link_sync",
        lambda value: 1 if value == url else 0,
    )

    result = await sonos.play_apple_music_share_link("1713833576", url)

    assert result is True
    assert sonos._device.play_mode == "SHUFFLE"
    assert sonos._device.calls == [("play_from_queue", 0)]


@pytest.mark.asyncio
async def test_failed_sharelink_enqueue_preserves_existing_queue_and_play_mode(monkeypatch):
    sonos = SonosService()
    sonos._connected = True
    sonos._device = FakeDevice()
    url = "https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4"
    monkeypatch.setattr(
        sonos, "_canonical_apple_music_share_link",
        lambda value: "song:1713833576" if value == url else None,
    )

    def fail_enqueue(value):
        raise RuntimeError("queue rejected")

    monkeypatch.setattr(sonos, "_add_apple_music_share_link_sync", fail_enqueue)

    result = await sonos.play_apple_music_share_link("1713833576", url)

    assert result is False
    assert sonos._device.play_mode == "SHUFFLE"
    assert sonos._device.calls == []



def test_real_sharelink_canonicalizer_matches_numeric_apple_track_id():
    sonos = SonosService()
    url = "https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4"

    assert sonos._canonical_apple_music_share_link(url) == "song:1713833576"
    assert sonos._canonical_apple_music_share_link("https://example.com/nope") is None


def test_real_sharelink_serializer_builds_apple_music_queue_metadata():
    calls = []

    class AVTransport:
        def AddURIToQueue(self, args, **kwargs):
            calls.append((args, kwargs))
            return {"FirstTrackNumberEnqueued": "1"}

    sonos = SonosService()
    sonos._device = FakeDevice()
    sonos._device.avTransport = AVTransport()
    url = "https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4"

    queue_number = sonos._add_apple_music_share_link_sync(url)

    assert queue_number == 1
    args = dict(calls[0][0])
    assert args["EnqueuedURI"] == "song%3a1713833576"
    assert "10032020song%3a1713833576" in args["EnqueuedURIMetaData"]
    assert "SA_RINCON52231_X_#Svc52231-0-Token" in args["EnqueuedURIMetaData"]


@pytest.mark.asyncio
async def test_play_failure_retains_append_instead_of_deleting_ambiguous_queue_item(monkeypatch):
    sonos = SonosService()
    sonos._connected = True
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    sonos._device = device
    url = "https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4"
    monkeypatch.setattr(sonos, "_canonical_apple_music_share_link", lambda value: "song:1713833576")
    monkeypatch.setattr(sonos, "_add_apple_music_share_link_sync", lambda value: 101)

    def fail_play(args, **kwargs):
        raise RuntimeError("renderer rejected play")

    device.avTransport.Play = fail_play
    result = await sonos.play_apple_music_share_link(
        "1713833576", url, expected_queue_size=100,
    )
    assert result is False
    assert device.calls == []
    assert device.queue_size == 101


@pytest.mark.asyncio
async def test_preplay_guard_can_refuse_after_enqueue_without_starting_audio(monkeypatch):
    sonos = SonosService()
    sonos._connected = True
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    sonos._device = device
    url = "https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4"
    monkeypatch.setattr(sonos, "_canonical_apple_music_share_link", lambda value: "song:1713833576")
    monkeypatch.setattr(sonos, "_add_apple_music_share_link_sync", lambda value: 101)

    async def deny():
        return False

    result = await sonos.play_apple_music_share_link(
        "1713833576", url, expected_queue_size=100, before_play=deny,
    )
    assert result is False
    assert device.calls == []
    assert device.queue_size == 101


@pytest.mark.asyncio
async def test_unexpected_enqueue_position_refuses_play_without_deleting(monkeypatch):
    sonos = SonosService()
    sonos._connected = True
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 102
    sonos._device = device
    url = "https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4"
    monkeypatch.setattr(sonos, "_canonical_apple_music_share_link", lambda value: "song:1713833576")
    monkeypatch.setattr(sonos, "_add_apple_music_share_link_sync", lambda value: 102)
    result = await sonos.play_apple_music_share_link(
        "1713833576", url, expected_queue_size=100,
    )
    assert result is False
    assert device.calls == []
    assert device.queue_size == 102


@pytest.mark.asyncio
async def test_queue_context_reports_fresh_play_mode_and_size():
    sonos = SonosService()
    sonos._connected = True
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 7
    sonos._device = device

    assert await sonos.get_queue_context() == {
        "available": True,
        "play_mode": "NORMAL",
        "queue_size": 7,
    }


def test_final_checked_play_refuses_same_size_queue_item_replacement():
    sonos = SonosService()
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    sonos._device = device
    snapshot = sonos._queue_item_snapshot_sync(100)

    device.queue_item = SimpleNamespace(
        title="User Track", creator="Someone Else", album="Other",
        item_class="object.item.audioItem.musicTrack",
        resources=[SimpleNamespace(uri="x-sonos-http:user-replacement", protocol_info="")],
    )
    assert sonos._play_queue_item_if_unchanged_sync(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    ) is False
    assert device.calls == []


def test_final_checked_play_refuses_queue_update_or_busy_transport():
    sonos = SonosService()
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    sonos._device = device
    snapshot = sonos._queue_item_snapshot_sync(100)

    device.queue_update_id += 1
    assert sonos._play_queue_item_if_unchanged_sync(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    ) is False
    assert device.calls == []

    device.queue_update_id -= 1
    device.transport_state = "PLAYING"
    assert sonos._play_queue_item_if_unchanged_sync(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    ) is False
    assert device.calls == []


def test_final_checked_play_starts_only_unchanged_exact_queue_object():
    sonos = SonosService()
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    sonos._device = device
    snapshot = sonos._queue_item_snapshot_sync(100)

    assert sonos._play_queue_item_if_unchanged_sync(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    ) is True
    assert device.calls == [("play_from_queue", 100)]


def test_final_checked_play_refuses_external_volume_raise_or_mute():
    sonos = SonosService()
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    sonos._device = device
    snapshot = sonos._queue_item_snapshot_sync(100)

    device.volume = 21
    assert sonos._play_queue_item_if_unchanged_sync(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    ) is False
    assert device.calls == []

    device.volume = 19
    assert sonos._play_queue_item_if_unchanged_sync(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    ) is False
    assert device.calls == []

    device.volume = 20
    device.mute = True
    assert sonos._play_queue_item_if_unchanged_sync(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    ) is False
    assert device.calls == []


def test_final_checked_play_passes_bounded_timeouts_to_mutating_upnp_calls():
    sonos = SonosService()
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    sonos._device = device
    snapshot = sonos._queue_item_snapshot_sync(100)

    assert sonos._play_queue_item_if_unchanged_sync(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    ) is True
    assert len(device.upnp_calls) == 3
    for _name, _args, kwargs in device.upnp_calls:
        assert 0 < kwargs["timeout"] <= 3.0


def test_final_checked_play_aborts_if_external_play_wins_during_setup():
    sonos = SonosService()
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    sonos._device = device
    snapshot = sonos._queue_item_snapshot_sync(100)
    original_seek = device.avTransport.Seek

    def competing_seek(args, **kwargs):
        result = original_seek(args, **kwargs)
        device.transport_state = "PLAYING"
        return result

    device.avTransport.Seek = competing_seek
    assert sonos._play_queue_item_if_unchanged_sync(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    ) is False
    assert device.calls == []


def test_final_checked_play_aborts_if_external_source_wins_during_setup():
    sonos = SonosService()
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    sonos._device = device
    snapshot = sonos._queue_item_snapshot_sync(100)
    original_seek = device.avTransport.Seek

    def competing_seek(args, **kwargs):
        result = original_seek(args, **kwargs)
        device.avTransport.current_uri = "x-rincon-stream:OTHER"
        return result

    device.avTransport.Seek = competing_seek
    assert sonos._play_queue_item_if_unchanged_sync(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    ) is False
    assert device.calls == []

@pytest.mark.asyncio
async def test_sharelink_requires_position_advancement_before_success(monkeypatch):
    sonos = SonosService()
    sonos._connected = True
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    device.advance_position = False
    sonos._device = device
    url = "https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4"
    monkeypatch.setattr(sonos, "_canonical_apple_music_share_link", lambda value: "song:1713833576")
    monkeypatch.setattr(sonos, "_add_apple_music_share_link_sync", lambda value: 101)
    monkeypatch.setattr("backend.services.sonos_service.ASSISTED_START_VERIFY_SECONDS", 0.05)
    monkeypatch.setattr("backend.services.sonos_service.ASSISTED_START_POLL_SECONDS", 0.01)

    result = await sonos.play_apple_music_share_link(
        "1713833576", url, expected_queue_size=100,
    )

    assert result is False
    assert device.calls == [("play_from_queue", 100)]
    assert device.transport_state == "PLAYING"


@pytest.mark.asyncio
async def test_sharelink_start_verification_rejects_queue_takeover_after_play(monkeypatch):
    sonos = SonosService()
    sonos._connected = True
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    device.mutate_queue_on_play = True
    sonos._device = device
    url = "https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4"
    monkeypatch.setattr(sonos, "_canonical_apple_music_share_link", lambda value: "song:1713833576")
    monkeypatch.setattr(sonos, "_add_apple_music_share_link_sync", lambda value: 101)

    result = await sonos.play_apple_music_share_link(
        "1713833576", url, expected_queue_size=100,
    )

    assert result is False
    assert device.calls == [("play_from_queue", 100)]

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("volume_on_play", 19),
        ("transport_state_on_play", "PAUSED_PLAYBACK"),
        ("source_on_play", "x-rincon-stream:OTHER"),
    ],
)
async def test_sharelink_start_verification_yields_to_post_play_manual_takeover(
    monkeypatch, mutation, value,
):
    sonos = SonosService()
    sonos._connected = True
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    setattr(device, mutation, value)
    sonos._device = device
    url = "https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4"
    monkeypatch.setattr(sonos, "_canonical_apple_music_share_link", lambda candidate: "song:1713833576")
    monkeypatch.setattr(sonos, "_add_apple_music_share_link_sync", lambda candidate: 101)

    result = await sonos.play_apple_music_share_link(
        "1713833576", url, expected_queue_size=100,
        before_play=lambda: _async_guard(20),
    )

    assert result is False
    assert device.calls == [("play_from_queue", 100)]


async def _async_guard(volume):
    return {"reason": None, "volume_used": volume}

@pytest.mark.asyncio
async def test_start_verification_enforces_outer_breaker_budget_on_blocking_sample(monkeypatch):
    sonos = SonosService()
    sonos._connected = True
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = 101
    sonos._device = device
    snapshot = sonos._queue_item_snapshot_sync(100)

    def blocking_sample(*_args, **_kwargs):
        time.sleep(0.30)
        return {"state": "PLAYING", "position": 1.0}

    monkeypatch.setattr(sonos, "_playback_start_sample_sync", blocking_sample)
    monkeypatch.setattr("backend.services.sonos_service.ASSISTED_START_VERIFY_SECONDS", 0.08)
    monkeypatch.setattr("backend.services.sonos_service.ASSISTED_START_SAMPLE_BUDGET_SECONDS", 0.03)
    monkeypatch.setattr("backend.services.sonos_service.ASSISTED_START_POLL_SECONDS", 0.01)

    started = time.monotonic()
    result = await sonos._verify_queue_playback_started(
        100, 101, snapshot, queue_uid="RINCON_TEST", max_volume=20,
    )
    elapsed = time.monotonic() - started

    assert result is False
    assert elapsed < 0.20
