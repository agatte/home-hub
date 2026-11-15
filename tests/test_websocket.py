"""Real ASGI /ws route with synthetic identity and actuator services only.

No application lifespan, broker provisioning, network or physical I/O.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
import pytest

from backend.main import websocket_endpoint
from backend.services.websocket_manager import WebSocketManager
from tests.support.ws_runtime import Socket, configure_runtime, scope


def state_app(profile="owner_browser", *, configured=True, authorize=None):
    app = FastAPI()
    app.add_api_websocket_route("/ws", websocket_endpoint)
    app.state.hue = SimpleNamespace(connected=False)
    app.state.sonos = SimpleNamespace(connected=False)
    app.state.automation = SimpleNamespace(
        current_mode="working", mode_source="synthetic", manual_override=False,
        house_state="home", activity="working", get_time_period=lambda: "afternoon")
    app.state.build_id = "synthetic"
    app.state.ambient_sound = SimpleNamespace(get_state=lambda: {
        "playing": False, "volume": 0.2, "url": "PRIVATE", "config": {"secret": "PRIVATE"}})
    app.state.presence = SimpleNamespace(get_status=lambda: pytest.fail("raw presence snapshot"))
    if configured:
        configure_runtime(app.state, Socket(), profile, authorize)
    else:
        app.state.ws_manager = WebSocketManager()
    return app


async def exchange(app, *, request_scope=None, commands=(), on_receive=None):
    sent = []
    messages = [{"type": "websocket.connect"}]
    messages += [{"type": "websocket.receive", "text": c} for c in commands]
    messages += [{"type": "websocket.disconnect", "code": 1000}]
    async def receive():
        if len(messages) == 1 and on_receive:
            await on_receive()
        return messages.pop(0)
    async def send(message):
        sent.append(message)
    request = request_scope or scope()
    request = dict(request, asgi={"version": "3.0"}, root_path="",
                   server=("hub.test", 443), client=("synthetic", 1), subprotocols=[])
    await app(request, receive, send)
    return sent


def frames(messages):
    return [json.loads(message["text"]) for message in messages if message["type"] == "websocket.send"]


@pytest.mark.asyncio
@pytest.mark.parametrize("configured,mutation", [(False, "none")] + [
    (True, m) for m in ("anonymous", "origin", "host", "forwarded", "x-forwarded-proto",
                       "scheme", "token", "query", "duplicate-host")])
async def test_real_route_rejects_preaccept_without_snapshot(configured, mutation, monkeypatch):
    app = state_app(configured=configured)
    monkeypatch.setattr("backend.main._ws_initial_events", lambda *a: pytest.fail("snapshot before auth"))
    request = scope()
    if mutation == "anonymous":
        request["headers"] = request["headers"][:1]
    elif mutation in {"origin", "host"}:
        request["headers"] = [(k, b"https://evil.test" if k.decode() == mutation else v)
                              for k, v in request["headers"]]
    elif mutation in {"forwarded", "x-forwarded-proto"}:
        request["headers"].append((mutation.encode(), b"https"))
    elif mutation == "scheme":
        request["scheme"] = "ws"
    elif mutation == "token":
        request["headers"][-1] = (b"cookie", b"__Host-homehub_ws=invalid")
    elif mutation == "query":
        request["query_string"] = b"token=synthetic"
    elif mutation == "duplicate-host":
        request["headers"].append(request["headers"][0])
    result = await exchange(app, request_scope=request)
    assert result == [{"type": "websocket.close", "code": 1008, "reason": ""}]
    assert app.state.ws_manager.connection_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["owner_browser", "kiosk", "windows_desktop", "desktop_notifier"])
async def test_route_initial_and_real_manager_broadcast_are_profile_filtered(profile):
    app = state_app(profile)
    async def publish():
        manager = app.state.ws_manager
        for kind, data in [
            ("light_update", {"light_id": "2", "bri": 100, "private": {"nested": "PRIVATE"}}),
            ("sonos_update", {"state": "PLAYING", "track": "test", "artwork_url": "PRIVATE"}),
            ("mode_update", {"mode": "working", "time_period": "afternoon", "process": "PRIVATE"}),
            ("notification", {"title": "Synthetic", "actions": [{"url": "PRIVATE"}]}),
            ("light_command_result", {"command_id": "synthetic_123", "status": "denied"}),
            ("pipeline_state", {"raw": "PRIVATE"}), ("unreviewed", {"raw": "PRIVATE"}),
        ]:
            await manager.broadcast(kind, data)
    result = await exchange(app, request_scope=scope(profile), on_receive=publish)
    observed = frames(result)
    assert result[0]["type"] == "websocket.accept"
    assert "PRIVATE" not in repr(observed)
    assert not any(f["type"] == "light_command_result" for f in observed)
    if profile in {"owner_browser", "kiosk"}:
        assert observed[0]["type"] == "connection_status"
        assert observed[0]["data"]["light_command_results"] is True
        assert len(observed[0]["data"]["request_id"]) == 12
        assert observed[1]["data"]["house_state"] == "home"
        assert {"ambient_update", "light_update", "sonos_update"} <= {f["type"] for f in observed}
    elif profile == "windows_desktop":
        assert all(set(f["data"]) <= {"mode", "time_period"} for f in observed)
        assert all(f["type"] == "mode_update" for f in observed)
    else:
        assert observed == [{"type": "notification", "data": {
            "title": "Synthetic", "factors": [], "actions": []}}]


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["owner_browser", "kiosk"])
@pytest.mark.parametrize("status", ["acknowledged", "denied", "unavailable", "uncertain"])
async def test_route_light_receipt_is_private_and_uses_final_handler(profile, status, monkeypatch):
    app = state_app(profile)
    handler = AsyncMock(return_value=status)
    monkeypatch.setattr("backend.main._handle_light_command", handler)
    command = {"type": "light_command", "data": {
        "light_id": "2", "bri": 100, "command_id": "synthetic_123"}}
    result = frames(await exchange(app, request_scope=scope(profile), commands=[json.dumps(command)]))
    handler.assert_awaited_once()
    assert handler.call_args.args[1].light_id == "2"
    assert [f for f in result if f["type"] == "light_command_result"] == [{
        "type": "light_command_result", "data": {
            "command_id": "synthetic_123", "light_id": "2", "status": status}}]
    assert not any(f["type"] == "light_update" for f in result)
    if status != "acknowledged":
        assert result[-1] == {"type": "light_command_reconciliation", "data": {
            "command_id": "synthetic_123", "light_id": "2"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["windows_desktop", "desktop_notifier"])
async def test_native_profile_cannot_reach_either_actuator(profile, monkeypatch):
    light, sonos = AsyncMock(), AsyncMock()
    monkeypatch.setattr("backend.main._handle_light_command", light)
    monkeypatch.setattr("backend.main._handle_sonos_command", sonos)
    for command in [{"type": "light_command", "data": {"light_id": "2", "on": True}},
                    {"type": "sonos_command", "data": {"action": "pause"}}]:
        app = state_app(profile)
        result = await exchange(app, request_scope=scope(profile), commands=[json.dumps(command)])
        assert result[-1]["type"] == "websocket.close"
    light.assert_not_awaited()
    sonos.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [
    {"light_id": 1, "bri": 100}, {"light_id": "2", "bri": True},
    {"light_id": "2", "bri": 999}, {"light_id": "2", "ct": 250, "hue": 1},
    {"light_id": "2", "on": True, "source": "owner"},
    {"light_id": "2", "on": True, "lane": "browser"},
])
async def test_route_strict_validation_echoes_no_payload(data, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr("backend.main._handle_light_command", handler)
    data["command_id"] = "synthetic_invalid"
    result = frames(await exchange(state_app(), commands=[json.dumps({"type": "light_command", "data": data})]))
    assert result[-2:] == [
        {"type": "error", "data": {"reason": "validation"}},
        {"type": "light_command_result", "data": {"command_id": "synthetic_invalid", "status": "invalid"}},
    ]
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_sonos_handler_retains_audio_ownership():
    app = state_app()
    app.state.sonos.connected = True
    app.state.sonos.pause = AsyncMock(return_value=True)
    calls = []
    async def run_manual(dimensions, **kwargs):
        calls.append(kwargs)
        return await kwargs["operation"]()
    app.state.audio_ownership = SimpleNamespace(
        record_manual_intent=lambda dimensions: 7, run_manual=run_manual)
    await exchange(app, commands=[json.dumps({"type": "sonos_command", "data": {"action": "pause"}})])
    app.state.sonos.pause.assert_awaited_once()
    assert calls[0]["source"] == "websocket"
    assert calls[0]["intent_revision"] == 7


@pytest.mark.asyncio
async def test_receipt_revocation_after_dispatch_suppresses_private_result(monkeypatch):
    from backend.identity_core import Identity
    from backend.identity_policy import PROFILES
    active = True
    async def authorize(token, operation, *, lane, stage):
        if active:
            return Identity("synthetic", "owner_browser", PROFILES["owner_browser"].source, lane)
        return None
    async def dispatched(*args):
        nonlocal active
        active = False
        return "acknowledged"
    monkeypatch.setattr("backend.main._handle_light_command", dispatched)
    result = frames(await exchange(state_app(authorize=authorize), commands=[json.dumps({
        "type": "light_command", "data": {"light_id": "2", "on": True, "command_id": "synthetic_123"}})]))
    assert not any(f["type"] == "light_command_result" for f in result)


def test_manager_has_no_legacy_raw_socket_registration():
    manager = WebSocketManager()
    assert not hasattr(manager, "connect")
    assert not hasattr(manager, "_connections")
    assert manager.connection_count == 0


@pytest.mark.asyncio
async def test_private_result_never_crosses_same_profile_sockets(monkeypatch):
    app = state_app()
    boundary = app.state.ws_manager._boundary
    one, two = Socket(send_text=AsyncMock()), Socket(send_text=AsyncMock())
    for ws in (one, two):
        ws.scope, ws.accept, ws.close = scope(), AsyncMock(), AsyncMock()
        assert await boundary.admit(ws)
    monkeypatch.setattr("backend.main._handle_light_command", AsyncMock(return_value="denied"))
    assert await boundary.inbound(one, json.dumps({"type": "light_command", "data": {
        "light_id": "2", "on": True, "command_id": "only_socket_one"}}))
    assert len(one.send_text.await_args_list) == 2
    two.send_text.assert_not_awaited()
    await boundary.broadcast("light_command_result", {"command_id": "only_socket_one", "status": "denied"})
    two.send_text.assert_not_awaited()
    await boundary.close(one)
    await boundary.close(two)


@pytest.mark.asyncio
async def test_close_cancels_suspended_send_and_preserves_other_client():
    app = state_app()
    boundary = app.state.ws_manager._boundary
    boundary._io_timeout = 0.05
    entered, release = asyncio.Event(), asyncio.Event()
    leaked = []
    async def delayed(payload):
        entered.set()
        await release.wait()
        leaked.append(payload)
    slow, fast = Socket(send_text=delayed), Socket(send_text=AsyncMock())
    for ws in (slow, fast):
        ws.scope, ws.accept, ws.close = scope(), AsyncMock(), AsyncMock()
        assert await boundary.admit(ws)
    pending = asyncio.create_task(boundary.broadcast("mode_update", {"mode": "working"}))
    await entered.wait()
    await boundary.close(slow)
    release.set()
    await pending
    assert leaked == []
    fast.send_text.assert_awaited_once()
    assert boundary.connection_count == 1
    await boundary.close(fast)


@pytest.mark.asyncio
async def test_producer_cancellation_closes_socket_without_late_frame():
    app = state_app()
    boundary = app.state.ws_manager._boundary
    entered = asyncio.Event()
    async def delayed(payload):
        entered.set()
        await asyncio.Event().wait()
    ws = Socket(scope=scope(), accept=AsyncMock(), close=AsyncMock(), send_text=delayed)
    assert await boundary.admit(ws)
    pending = asyncio.create_task(boundary.send(ws, "mode_update", {"mode": "working"}))
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert boundary.connection_count == 0
    assert not await boundary.send(ws, "mode_update", {"mode": "sleeping"})


@pytest.mark.asyncio
async def test_concurrent_producers_have_bounded_pending_send_work():
    boundary = state_app().state.ws_manager._boundary
    entered = asyncio.Event()
    async def delayed(payload):
        entered.set()
        await asyncio.Event().wait()
    ws = Socket(scope=scope(), accept=AsyncMock(), close=AsyncMock(), send_text=delayed)
    assert await boundary.admit(ws)
    pending = [asyncio.create_task(boundary.send(ws, "mode_update", {"mode": "working"}))
               for _ in range(40)]
    await entered.wait()
    await asyncio.sleep(0)
    assert boundary._sessions[ws].pending_sends <= 8
    assert len(boundary._sessions[ws].work) == 1
    assert len(boundary._verifications["active"]) <= 1
    await boundary.close(ws)
    results = await asyncio.gather(*pending)
    assert not any(results)


@pytest.mark.asyncio
async def test_revocation_watcher_cancels_dispatch_and_sends_no_receipt(monkeypatch):
    from backend.identity_core import Identity
    active = True
    entered, canceled = asyncio.Event(), asyncio.Event()
    async def authorize(token, operation, *, lane, stage):
        return Identity("synthetic", "owner_browser", "owner", lane) if active else None
    async def dispatched(*args):
        nonlocal active
        active = False
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            canceled.set()
    monkeypatch.setattr("backend.main._handle_light_command", dispatched)
    app = state_app(authorize=authorize)
    app.state.ws_manager._boundary._recheck = 0.005
    result = frames(await exchange(app, commands=[json.dumps({"type": "light_command", "data": {
        "light_id": "2", "on": True, "command_id": "synthetic_123"}})]))
    assert entered.is_set() and canceled.is_set()
    assert not any(f["type"] == "light_command_result" for f in result)


@pytest.mark.asyncio
async def test_close_during_command_authorization_never_invokes_final_handler(monkeypatch):
    from backend.identity_core import Identity
    from backend.identity_policy import WS_LIGHT_COMMAND
    ws = Socket(scope=scope(), accept=AsyncMock(), close=AsyncMock(), send_text=AsyncMock())
    app = None
    async def authorize(token, operation, *, lane, stage):
        if operation == WS_LIGHT_COMMAND:
            await app.state.ws_manager._boundary.close(ws)
        return Identity("synthetic", "owner_browser", "owner", lane)
    app = state_app(authorize=authorize)
    handler = AsyncMock()
    monkeypatch.setattr("backend.main._handle_light_command", handler)
    boundary = app.state.ws_manager._boundary
    assert await boundary.admit(ws)
    assert not await boundary.inbound(ws, json.dumps({"type": "light_command", "data": {
        "light_id": "2", "on": True}}))
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_audio_ownership_is_unavailable_without_write():
    app = state_app()
    app.state.sonos.connected = True
    app.state.sonos.pause = AsyncMock()
    result = frames(await exchange(app, commands=[json.dumps({
        "type": "sonos_command", "data": {"action": "pause"}})]))
    assert result[-1] == {"type": "error", "data": {"reason": "unavailable"}}
    app.state.sonos.pause.assert_not_awaited()


@pytest.mark.asyncio
async def test_socket_raising_cancellation_cannot_cancel_broadcast_producer():
    boundary = state_app().state.ws_manager._boundary
    async def canceled_transport(payload):
        raise asyncio.CancelledError
    bad, fast = Socket(send_text=canceled_transport), Socket(send_text=AsyncMock())
    for ws in (bad, fast):
        ws.scope, ws.accept, ws.close = scope(), AsyncMock(), AsyncMock()
        assert await boundary.admit(ws)
    await boundary.broadcast("mode_update", {"mode": "working"})
    fast.send_text.assert_awaited_once()
    assert boundary.connection_count == 1
    await boundary.close(fast)


@pytest.mark.asyncio
async def test_ordinary_lifespan_composes_fail_closed_websocket_before_device_start(
    monkeypatch,
):
    """Exercise the real bootstrap path, stopping *before* Hue/Sonos or tasks.

    No real DB, broker, bridge, service startup, credentials or network I/O.
    Synthetic endpoint absence must not become an anonymous fallback.
    """
    from backend import bootstrap
    from backend.services import heartbeat

    async def fake_init_db():
        return None

    def stop_before_devices():
        raise RuntimeError("synthetic stop before external services")

    monkeypatch.setattr(bootstrap, "init_db", fake_init_db)
    monkeypatch.setattr(bootstrap, "_compute_build_id", lambda: "synthetic")
    monkeypatch.setattr(heartbeat, "HeartbeatRegistry", stop_before_devices)
    app = FastAPI()
    app.add_api_websocket_route("/ws", websocket_endpoint)
    with pytest.raises(RuntimeError, match="synthetic stop before external services"):
        async with bootstrap.lifespan(app):
            pytest.fail("test must never run real application services")

    manager = app.state.ws_manager
    assert type(manager) is WebSocketManager
    assert manager._boundary is None
    assert manager.connection_count == 0
    monkeypatch.setattr(
        "backend.main._ws_initial_events",
        lambda *args: pytest.fail("unconfigured startup evaluated a snapshot"),
    )
    outcome = await exchange(app, request_scope=scope())
    assert outcome == [{"type": "websocket.close", "code": 1008, "reason": ""}]
    await manager.broadcast("mode_update", {"mode": "home", "private": "never"})
    assert manager.connection_count == 0
