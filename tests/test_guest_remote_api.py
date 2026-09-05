"""Pins for the narrow data/control surface exposed through the guest gateway."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import backend.api.routes.guest as guest


def _request(*, hue=None, sonos=None, automation=None, bar=None, plants=None):
    state = SimpleNamespace(
        hue=hue,
        sonos=sonos,
        automation=automation,
        bar_service=bar,
        plant_service=plants,
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=state),
        client=SimpleNamespace(host="127.0.0.1"),
    )


@pytest.mark.asyncio
async def test_guest_state_projects_only_safe_fields() -> None:
    hue = SimpleNamespace(
        connected=True,
        get_all_lights=AsyncMock(return_value=[{
            "light_id": "1", "name": "Lamp", "on": True, "bri": 120,
            "hue": 2000, "sat": 100, "bridge_secret": "nope",
        }]),
    )
    sonos = SimpleNamespace(
        connected=True,
        get_status=AsyncMock(return_value={
            "state": "PLAYING", "track": "Song", "artist": "Artist",
            "album": "Album", "volume": 18, "mute": False,
            "art_url": "http://192.168.86.50/art.jpg",
        }),
    )
    automation = SimpleNamespace(
        current_mode="social", mode_source="manual", manual_override=True,
        override_source="guest",
    )
    body = await guest.get_guest_state(
        _request(hue=hue, sonos=sonos, automation=automation)
    )

    assert body["mode"] == "social"
    assert body["manual_override"] is True
    assert body["source"] == "guest"
    assert body["lights"] == [{
        "light_id": "1", "name": "Lamp", "on": True, "bri": 120,
        "hue": 2000, "sat": 100,
    }]
    assert body["sonos"]["has_art"] is True
    assert "art_url" not in body["sonos"]
    assert "bridge_secret" not in body["lights"][0]


@pytest.mark.asyncio
async def test_guest_sonos_volume_is_server_bounded(monkeypatch) -> None:
    monkeypatch.setattr(guest, "_last_guest_sonos_at", 0.0)
    sonos = SimpleNamespace(
        connected=True,
        get_status=AsyncMock(return_value={"volume": 29}),
        set_volume=AsyncMock(return_value=True),
    )
    result = await guest.guest_sonos_volume("up", _request(sonos=sonos))
    assert result["volume"] == 30
    sonos.set_volume.assert_awaited_once_with(30)


@pytest.mark.asyncio
async def test_guest_kitchen_touches_only_kitchen_pair() -> None:
    hue = SimpleNamespace(
        connected=True,
        breaker_open=False,
        set_light=AsyncMock(return_value=True),
    )
    automation = SimpleNamespace(mark_light_manual=MagicMock())
    result = await guest.guest_kitchen(
        guest.KitchenRequest(enabled=False, scene="party"),
        _request(hue=hue, automation=automation),
    )

    assert result == {"status": "ok", "enabled": False}
    assert hue.set_light.await_count == 2
    calls = [(call.args[0], call.args[1]) for call in hue.set_light.await_args_list]
    assert calls == [("3", {"on": False}), ("4", {"on": False})]


@pytest.mark.asyncio
async def test_guest_kitchen_restore_rejects_non_guest_scene() -> None:
    hue = SimpleNamespace(connected=True, breaker_open=False)
    with pytest.raises(Exception) as exc:
        await guest.guest_kitchen(
            guest.KitchenRequest(enabled=True, scene="focus"),
            _request(hue=hue),
        )
    assert getattr(exc.value, "status_code", None) == 400


@pytest.mark.asyncio
async def test_guest_handback_cannot_clear_newer_host_override() -> None:
    automation = SimpleNamespace(
        override_source="api:192.168.86.30",
        clear_override=AsyncMock(),
    )
    with pytest.raises(Exception) as exc:
        await guest.guest_handback(_request(automation=automation))
    assert getattr(exc.value, "status_code", None) == 409
    automation.clear_override.assert_not_awaited()


@pytest.mark.asyncio
async def test_guest_handback_clears_only_guest_owned_override() -> None:
    automation = SimpleNamespace(
        override_source="guest",
        clear_override=AsyncMock(),
    )
    result = await guest.guest_handback(_request(automation=automation))
    assert result == {"status": "ok"}
    automation.clear_override.assert_awaited_once_with(source="guest_handback")


@pytest.mark.asyncio
async def test_guest_invite_refuses_when_public_ingress_is_offline(monkeypatch) -> None:
    monkeypatch.setattr(guest.settings, "GUEST_PUBLIC_URL", "https://guest.example.test")
    calls = []

    async def fake_gateway_call(method, path):
        calls.append((method, path))
        return {"public_url": "https://guest.example.test"}

    monkeypatch.setattr(guest, "_guest_gateway_call", fake_gateway_call)
    monkeypatch.setattr(guest, "_guest_public_reachable", AsyncMock(return_value=False))
    with pytest.raises(Exception) as exc:
        await guest.create_guest_invite()
    assert getattr(exc.value, "status_code", None) == 503
    assert calls == [("GET", "/internal/status")]


@pytest.mark.asyncio
async def test_guest_status_distinguishes_loopback_from_public_readiness(monkeypatch) -> None:
    monkeypatch.setattr(guest.settings, "GUEST_PUBLIC_URL", "https://guest.example.test")
    monkeypatch.setattr(
        guest,
        "_guest_gateway_call",
        AsyncMock(return_value={"public_url": "https://guest.example.test", "active_sessions": 2}),
    )
    monkeypatch.setattr(guest, "_guest_public_reachable", AsyncMock(return_value=False))
    body = await guest.get_guest_access_status()
    assert body["gateway_reachable"] is True
    assert body["public_reachable"] is False
    assert body["guest_app_ready"] is False
    assert body["active_sessions"] == 2


@pytest.mark.asyncio
async def test_guest_vibes_accept_queueable_cloud_favorites(monkeypatch) -> None:
    monkeypatch.setattr(guest, "_resolve_vibe_mapping", AsyncMock(return_value={
        "hype": "It's Lit!",
        "singalong": "2000s Hits Essentials",
        "throwback": "Replay-all-time",
    }))
    sonos = SimpleNamespace(
        connected=True,
        get_favorites=AsyncMock(return_value=[
            {"title": "It's Lit!", "source": "favorite", "uri": "x-rincon-cpcontainer:playlist"},
            {"title": "AJR", "source": "favorite", "uri": ""},
        ]),
    )
    body = await guest.list_guest_vibes(_request(sonos=sonos))
    by_name = {item["name"]: item for item in body["vibes"]}
    assert by_name["hype"]["available"] is True
    assert set(by_name) == {"hype", "singalong", "throwback"}


@pytest.mark.asyncio
async def test_guest_vibe_rejects_nonqueueable_cloud_favorite_before_play(monkeypatch) -> None:
    monkeypatch.setattr(guest, "_last_guest_vibe_at", 0.0)
    monkeypatch.setattr(guest, "_resolve_vibe_mapping", AsyncMock(return_value={
        "hype": "AJR",
        "singalong": "2000s Hits Essentials",
        "throwback": "Replay-all-time",
    }))
    sonos = SimpleNamespace(
        connected=True,
        get_favorites=AsyncMock(return_value=[{"title": "AJR", "source": "favorite", "uri": ""}]),
        play_favorite=AsyncMock(return_value=True),
    )
    with pytest.raises(Exception) as exc:
        await guest.activate_guest_vibe("hype", _request(sonos=sonos))
    assert getattr(exc.value, "status_code", None) == 409
    assert "does not expose a queueable Sonos resource" in getattr(exc.value, "detail", "")
    sonos.play_favorite.assert_not_awaited()


@pytest.mark.asyncio
async def test_guest_vibe_plays_queueable_cloud_favorite(monkeypatch) -> None:
    monkeypatch.setattr(guest, "_last_guest_vibe_at", 0.0)
    monkeypatch.setattr(guest, "_resolve_vibe_mapping", AsyncMock(return_value={
        "hype": "It's Lit!",
        "singalong": "2000s Hits Essentials",
        "throwback": "Replay-all-time",
    }))
    sonos = SimpleNamespace(
        connected=True,
        get_favorites=AsyncMock(return_value=[
            {"title": "It's Lit!", "source": "favorite", "uri": "x-rincon-cpcontainer:playlist"}
        ]),
        play_favorite=AsyncMock(return_value=True),
    )
    automation = SimpleNamespace(set_manual_override=AsyncMock())
    body = await guest.activate_guest_vibe("hype", _request(sonos=sonos, automation=automation))
    assert body["playlist"] == "It's Lit!"
    sonos.play_favorite.assert_awaited_once_with("It's Lit!")
    automation.set_manual_override.assert_awaited_once_with("social", source="guest")


@pytest.mark.asyncio
async def test_guest_vibe_plays_saved_sonos_playlist(monkeypatch) -> None:
    monkeypatch.setattr(guest, "_last_guest_vibe_at", 0.0)
    monkeypatch.setattr(guest, "_resolve_vibe_mapping", AsyncMock(return_value={
        "hype": "It's Lit!",
        "singalong": "2000s Hits Essentials",
        "throwback": "Chill 2",
    }))
    sonos = SimpleNamespace(
        connected=True,
        get_favorites=AsyncMock(return_value=[{"title": "Chill 2", "source": "playlist"}]),
        play_favorite=AsyncMock(return_value=True),
    )
    automation = SimpleNamespace(set_manual_override=AsyncMock())
    body = await guest.activate_guest_vibe("throwback", _request(sonos=sonos, automation=automation))
    assert body["playlist"] == "Chill 2"
    sonos.play_favorite.assert_awaited_once_with("Chill 2")
    automation.set_manual_override.assert_awaited_once_with("social", source="guest")
