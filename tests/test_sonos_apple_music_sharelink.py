import pytest

from backend.services.sonos_service import SonosService


class FakeDevice:
    def __init__(self):
        self.calls = []
        self.play_mode = "SHUFFLE"

    def clear_queue(self):
        self.calls.append(("clear_queue",))

    def play_from_queue(self, index):
        self.calls.append(("play_from_queue", index))


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
