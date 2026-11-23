"""Offline tests for the temporary #461 fail-closed command boundary."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.websockets import WebSocketDisconnect

from backend.api.auth import require_explicit_api_key
from backend.main import websocket_endpoint


@pytest.mark.asyncio
async def test_socket_subscribes_but_never_dispatches_commands():
    manager = SimpleNamespace(connect=AsyncMock(), disconnect=Mock())
    state = SimpleNamespace(
        ws_manager=manager, hue=SimpleNamespace(connected=True),
        sonos=SimpleNamespace(connected=True), build_id="fixture",
        automation=SimpleNamespace(current_mode="idle", mode_source="test",
            manual_override=None, house_state="home", activity="general",
            get_time_period=lambda: "day"),
    )
    frames = [
        {"type": "light_command", "data": {"command_id": "fixture_123", "light_id": "1", "on": True}},
        {"type": "sonos_command", "data": {"action": "play"}},
    ]
    socket = SimpleNamespace(app=SimpleNamespace(state=state), send_text=AsyncMock(),
        receive_text=AsyncMock(side_effect=[*(json.dumps(f) for f in frames), WebSocketDisconnect()]))
    with patch("backend.main._handle_light_command", new_callable=AsyncMock) as light, \
         patch("backend.main._handle_sonos_command", new_callable=AsyncMock) as sonos:
        await websocket_endpoint(socket)
    sent = [json.loads(c.args[0]) for c in socket.send_text.await_args_list]
    assert sent[0]["data"]["light_command_results"] is False
    assert sent[1]["type"] == "mode_update"
    assert sent[2]["data"] == {"command_id": "fixture_123", "status": "denied"}
    assert sent[3]["data"]["reason"] == "unauthorized"
    light.assert_not_awaited()
    sonos.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_key_required_even_for_localhost(monkeypatch):
    from backend.api.auth import settings
    monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "fixture-key")
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})
    with pytest.raises(HTTPException):
        await require_explicit_api_key(request, None, None)
    await require_explicit_api_key(request, "fixture-key", None)
