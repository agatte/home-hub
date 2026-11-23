"""TLS admission gate: new WSS clients may not read household state anonymously.

The original plain-WS client cohort on :8000 remains readable and every
actuator frame retains its separate owner-session check.
"""
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from backend.api import owner_session as owner
from backend.main import websocket_endpoint
from backend.services.websocket_manager import WebSocketManager


@pytest.fixture(autouse=True)
def secure_origin(monkeypatch):
    monkeypatch.setattr(owner.settings, "HOME_HUB_OWNER_ALLOWED_ORIGINS", "https://hub.example")
    owner._sessions.clear()
    yield
    owner._sessions.clear()


@pytest.mark.parametrize("headers", [
    {"Origin": "https://hub.example"},
    {"Origin": "https://evil.example", "Cookie": "homehub_owner=valid"},
    {"Origin": "https://hub.example", "Cookie": "homehub_owner=expired"},
    {"Origin": "https://hub.example", "Cookie": "homehub_owner=valid",
     "X-Forwarded-Proto": "https"},
])
def test_secure_anonymous_or_spoofed_socket_rejected_before_any_state(headers):
    owner._sessions["valid"] = time.monotonic() + 60
    owner._sessions["expired"] = 0
    app = FastAPI()
    app.add_api_websocket_route("/ws", websocket_endpoint)
    # No ws_manager / Hue services are mounted: premature admission would
    # raise instead of rejecting before touching backend state or broadcasting.
    with TestClient(app, base_url="https://hub.example") as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("wss://hub.example/ws", headers=headers):
                pass
    assert error.value.code == 1008


def test_original_plain_ws_read_cohort_stays_available_without_login():
    app = FastAPI()

    async def connect(ws):
        await ws.accept()

    app.state.ws_manager = SimpleNamespace(connect=connect, disconnect=Mock())
    app.state.hue = SimpleNamespace(connected=True)
    app.state.sonos = SimpleNamespace(connected=False)
    app.state.build_id = "offline"
    app.state.automation = SimpleNamespace(
        current_mode="Home", mode_source="offline",
        manual_override=None, house_state="Home", activity="General",
        get_time_period=lambda: "day",
    )
    app.add_api_websocket_route("/ws", websocket_endpoint)
    with TestClient(app, base_url="http://localhost:8000",
                    client=("127.0.0.1", 1234)) as client:
        with client.websocket_connect("ws://localhost:8000/ws") as ws:
            connected = ws.receive_json()
            assert connected["type"] == "connection_status"
            assert connected["data"]["light_command_results"] is False
            mode = ws.receive_json()
            assert mode["type"] == "mode_update"
            assert mode["data"]["mode"] == "Home"


def _fake_socket(scheme, token="valid"):
    ws = Mock()
    ws.scope = {"scheme": scheme}
    ws.headers = {"origin": "https://hub.example", "host": "hub.example"}
    ws.client = SimpleNamespace(host="192.168.86.20")
    ws.cookies = {owner.COOKIE: token}
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_secure_broadcast_stops_immediately_on_logout_but_plain_ws_continues():
    owner._sessions["valid"] = time.monotonic() + 60
    manager = WebSocketManager()
    secured = _fake_socket("wss")
    native = _fake_socket("ws")
    manager._connections.update({secured, native})

    await manager.broadcast("mode_update", {"mode": "Home"})
    secured.send_text.assert_awaited_once()
    native.send_text.assert_awaited_once()
    assert json.loads(secured.send_text.await_args.args[0])["data"]["mode"] == "Home"

    # Owner-session logout clears this process-wide session store.
    owner._sessions.clear()
    await manager.broadcast("mode_update", {"mode": "Winding Down"})
    secured.send_text.assert_awaited_once()
    secured.close.assert_awaited_once_with(code=1008)
    assert secured not in manager._connections
    assert native in manager._connections
    assert native.send_text.await_count == 2


@pytest.mark.asyncio
async def test_secure_broadcast_fails_closed_when_session_never_existed():
    manager = WebSocketManager()
    secured = _fake_socket("wss", token="unknown")
    manager._connections.add(secured)
    await manager.broadcast("light_update", {"light_id": "1"})
    secured.send_text.assert_not_awaited()
    secured.close.assert_awaited_once_with(code=1008)
    assert manager.connection_count == 0


def _owner_request(token="valid"):
    return SimpleNamespace(
        headers={"origin": "https://hub.example", "host": "hub.example"},
        scope={"scheme": "https"},
        cookies={owner.COOKIE: token},
        client=SimpleNamespace(host="192.168.86.20"),
        url=SimpleNamespace(scheme="https"),
    )


@pytest.mark.asyncio
async def test_logout_waits_for_started_secure_broadcast_before_revoking():
    import asyncio

    from starlette.responses import Response

    owner._sessions["valid"] = time.monotonic() + 60
    manager = WebSocketManager()
    secured = _fake_socket("wss")
    started = asyncio.Event()
    finish = asyncio.Event()

    async def blocked_send(_payload):
        started.set()
        await finish.wait()

    secured.send_text = AsyncMock(side_effect=blocked_send)
    manager._connections.add(secured)
    broadcast = asyncio.create_task(manager.broadcast("mode_update", {"mode": "Home"}))
    await asyncio.wait_for(started.wait(), 1)

    logout = asyncio.create_task(owner.logout(_owner_request(), Response()))
    await asyncio.sleep(0)
    assert not logout.done(), "Logout must not complete while authorized WSS frame is pending"

    finish.set()
    await asyncio.wait_for(asyncio.gather(broadcast, logout), 2)
    assert "valid" not in owner._sessions
    secured.send_text.assert_awaited_once()

    await manager.broadcast("mode_update", {"mode": "Away"})
    secured.send_text.assert_awaited_once()
    secured.close.assert_awaited_once_with(code=1008)
    assert manager.connection_count == 0


@pytest.mark.asyncio
async def test_wss_logout_during_handshake_prevents_initial_state_snapshot():
    import asyncio

    from starlette.responses import Response

    owner._sessions["valid"] = time.monotonic() + 60
    connect_started = asyncio.Event()
    allow_connect = asyncio.Event()

    async def connect(_ws):
        connect_started.set()
        await allow_connect.wait()

    manager = SimpleNamespace(connect=connect, disconnect=Mock())
    state = SimpleNamespace(
        ws_manager=manager,
        hue=SimpleNamespace(connected=True),
        sonos=SimpleNamespace(connected=True),
        build_id="offline",
        automation=SimpleNamespace(
            current_mode="Home", mode_source="offline",
            manual_override=None, house_state="Home",
            activity="General", get_time_period=lambda: "day",
        ),
    )
    ws = SimpleNamespace(
        app=SimpleNamespace(state=state),
        scope={"scheme": "wss"},
        headers={"origin": "https://hub.example", "host": "hub.example"},
        client=SimpleNamespace(host="192.168.86.20"),
        cookies={owner.COOKIE: "valid"},
        send_text=AsyncMock(),
        receive_text=AsyncMock(),
        close=AsyncMock(),
    )
    handshake = asyncio.create_task(websocket_endpoint(ws))
    await asyncio.wait_for(connect_started.wait(), 1)
    await owner.logout(_owner_request(), Response())
    allow_connect.set()
    await asyncio.wait_for(handshake, 2)

    ws.send_text.assert_not_awaited()
    ws.close.assert_awaited_once_with(code=1008)
    manager.disconnect.assert_called_once_with(ws)
