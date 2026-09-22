"""Manual Sonos ingress must invalidate autonomous ownership before writes."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import backend.api.routes.guest as guest
import backend.api.routes.sonos as sonos_routes
from backend.api.schemas.sonos import TTSRequest, VolumeRequest
from backend.main import _handle_sonos_command
from backend.schemas.ws import SonosCommandData
from backend.services.audio_ownership import (
    MANUAL_QUEUE_DIMENSIONS,
    MANUAL_TRANSPORT_DIMENSIONS,
    MANUAL_VOLUME_DIMENSIONS,
)


class RecorderOwnership:
    def __init__(self, events: list, lease=None) -> None:
        self.events = events
        self.lease = lease

    async def find_lease(self, *, owner: str, purpose: str | None = None):
        self.events.append(("capture", owner, purpose))
        return self.lease

    async def run_manual(
        self, dimensions, *, source: str, reason: str, operation,
    ):
        self.events.append(
            ("invalidate", frozenset(dimensions), source, reason)
        )
        return await operation()


class RecorderTTS:
    def __init__(self, events: list) -> None:
        self.events = events

    async def speak(
        self,
        text: str,
        volume: int | None = None,
        *,
        manual_source: str | None = None,
        manual_reason: str | None = None,
    ) -> bool:
        self.events.append(
            ("tts", text, volume, manual_source, manual_reason)
        )
        return True


class RecorderSonos:
    def __init__(self, events: list) -> None:
        self.events = events
        self.connected = True
        self.breaker_open = False
        self.volume = 20


    async def play(self) -> bool:
        self.events.append(("play",))
        return True

    async def pause(self) -> bool:
        self.events.append(("pause",))
        return True

    async def next_track(self) -> bool:
        self.events.append(("next",))
        return True

    async def previous_track(self) -> bool:
        self.events.append(("previous",))
        return True

    async def set_volume(self, volume: int) -> bool:
        self.events.append(("volume", volume))
        self.volume = volume
        return True

    async def get_status(self) -> dict:
        return {"volume": self.volume, "track": ""}

    async def play_favorite(self, title: str) -> bool:
        self.events.append(("favorite", title))
        return True


def request(events: list):
    state = SimpleNamespace(
        sonos=RecorderSonos(events),
        audio_ownership=RecorderOwnership(events),
        event_logger=None,
        automation=None,
        tts=RecorderTTS(events),
        effect_manager=None,
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=state),
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
    )


@pytest.mark.asyncio
async def test_rest_play_invalidates_before_transport_write() -> None:
    events: list = []
    req = request(events)

    result = await sonos_routes.sonos_play(req)

    assert result["status"] == "ok"
    assert events == [
        ("invalidate", MANUAL_TRANSPORT_DIMENSIONS, "manual", "manual_play"),
        ("play",),
    ]


@pytest.mark.asyncio
async def test_rest_volume_invalidates_only_volume_before_write() -> None:
    events: list = []
    req = request(events)

    result = await sonos_routes.set_sonos_volume(VolumeRequest(volume=31), req)

    assert result == {"status": "ok", "volume": 31}
    assert events == [
        ("invalidate", MANUAL_VOLUME_DIMENSIONS, "manual", "manual_volume"),
        ("volume", 31),
    ]


@pytest.mark.asyncio
async def test_rest_favorite_invalidates_queue_before_write() -> None:
    events: list = []
    req = request(events)

    result = await sonos_routes.play_favorite("Party Mix", req)

    assert result["status"] == "ok"
    assert events == [
        (
            "invalidate", MANUAL_QUEUE_DIMENSIONS,
            "manual", "manual_favorite_play",
        ),
        ("favorite", "Party Mix"),
    ]


@pytest.mark.asyncio
async def test_guest_transport_invalidates_before_write(monkeypatch) -> None:
    events: list = []
    req = request(events)
    monkeypatch.setattr(guest, "_last_guest_sonos_at", 0.0)

    result = await guest.guest_sonos_transport("next", req)

    assert result == {"status": "ok", "action": "next"}
    assert events == [
        ("invalidate", MANUAL_TRANSPORT_DIMENSIONS, "guest", "guest_next"),
        ("next",),
    ]


@pytest.mark.asyncio
async def test_websocket_volume_invalidates_before_write() -> None:
    events: list = []
    req = request(events)
    app = req.app

    await _handle_sonos_command(
        app,
        SonosCommandData(action="volume", volume=27),
    )

    assert events == [
        (
            "invalidate", MANUAL_VOLUME_DIMENSIONS,
            "websocket", "manual_ws_volume",
        ),
        ("volume", 27),
    ]

@pytest.mark.asyncio
async def test_rest_tts_serializes_full_manual_interruption() -> None:
    events: list = []
    req = request(events)

    result = await sonos_routes.speak_text.__wrapped__(
        TTSRequest(text="Hello", volume=18), req,
    )

    assert result == {"status": "ok", "text": "Hello"}
    assert events == [
        ("tts", "Hello", 18, "manual", "manual_tts"),
    ]


@pytest.mark.asyncio
async def test_guest_toast_serializes_full_manual_interruption(monkeypatch) -> None:
    events: list = []
    req = request(events)
    monkeypatch.setattr(guest, "_last_guest_toast_at", 0.0)

    result = await guest.speak_guest_toast(
        guest.ToastRequest(message="Cheers", name=None),
        req,
    )

    assert result["status"] == "ok"
    assert events == [
        (
            "tts",
            "Cheers",
            guest.GUEST_TOAST_VOLUME,
            "guest",
            "guest_toast_tts",
        ),
    ]


class RecorderEventLogger:
    def __init__(self, events: list) -> None:
        self.events = events

    async def log_sonos_event(self, **kwargs) -> None:
        self.events.append(("log", kwargs))


def _learning_lease() -> dict:
    return {
        "lease_id": "lease-ingress",
        "owner": "music_mapper",
        "purpose": "mode_auto_play",
        "dimensions": ["queue_source", "transport"],
        "evidence": {"phase": "owned", "sonos": {"transport_state": "PLAYING"}},
        "metadata": {
            "mode": "social",
            "favorite_title": "Owned Favorite",
            "weather_class": "clear",
            "learning_eligible": True,
        },
    }


@pytest.mark.asyncio
async def test_rest_next_captures_session_before_manual_invalidation() -> None:
    events: list = []
    req = request(events)
    req.app.state.audio_ownership = RecorderOwnership(events, _learning_lease())
    req.app.state.event_logger = RecorderEventLogger(events)
    req.app.state.automation = SimpleNamespace(current_mode="social")

    result = await sonos_routes.sonos_next(req)

    assert result["status"] == "ok"
    assert events[0] == ("capture", "music_mapper", "mode_auto_play")
    assert events[1] == (
        "invalidate", MANUAL_TRANSPORT_DIMENSIONS, "manual", "manual_next",
    )
    assert events[2] == ("next",)
    log = events[3][1]
    assert log["favorite_title"] == "Owned Favorite"
    assert log["session_id"] == "lease-ingress"
    assert log["ownership_lease_id"] == "lease-ingress"


@pytest.mark.asyncio
async def test_websocket_next_captures_session_before_manual_invalidation() -> None:
    events: list = []
    req = request(events)
    req.app.state.audio_ownership = RecorderOwnership(events, _learning_lease())
    req.app.state.event_logger = RecorderEventLogger(events)
    req.app.state.automation = SimpleNamespace(current_mode="social")

    await _handle_sonos_command(
        req.app,
        SonosCommandData(action="next"),
    )

    assert events[0] == ("capture", "music_mapper", "mode_auto_play")
    assert events[1] == (
        "invalidate", MANUAL_TRANSPORT_DIMENSIONS, "websocket", "manual_ws_next",
    )
    assert events[2] == ("next",)
    log = events[3][1]
    assert log["favorite_title"] == "Owned Favorite"
    assert log["session_id"] == "lease-ingress"
    assert log["ownership_lease_id"] == "lease-ingress"
