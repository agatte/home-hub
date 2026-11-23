import base64
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from backend.api import owner_session as owner
from backend.api.auth import require_owner_or_explicit_key
from backend.main import websocket_endpoint


@pytest.fixture
def client(monkeypatch):
    salt = b"0123456789abcdef"
    digest = hashlib.pbkdf2_hmac("sha256", b"fake passphrase", salt, 600000)
    verifier = "pbkdf2_sha256$600000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()
    monkeypatch.setattr(owner.settings, "HOME_HUB_OWNER_PASSWORD_VERIFIER", verifier)
    monkeypatch.setattr(owner.settings, "HOME_HUB_OWNER_ALLOWED_ORIGINS", "https://hub.example")
    owner._sessions.clear()
    owner._attempts.clear()
    app = FastAPI()
    app.include_router(owner.router)
    return TestClient(app, base_url="https://hub.example")


def test_login_origin_expiry_logout(client, monkeypatch):
    headers = {"Origin": "https://hub.example"}
    assert client.post('/api/owner/session', headers=headers, json={'password': 'wrong'}).status_code == 401
    assert client.post('/api/owner/session', headers={'Origin': 'https://evil.example'}, json={'password': 'fake passphrase'}).status_code == 403
    assert client.post('/api/owner/session', headers={'Origin': 'https://hub.example', 'Host': 'evil.example'}, json={'password': 'fake passphrase'}).status_code == 403
    result = client.post('/api/owner/session', headers=headers, json={'password': 'fake passphrase'})
    assert result.status_code == 200
    assert 'HttpOnly' in result.headers['set-cookie'] and 'SameSite=strict' in result.headers['set-cookie'] and 'Secure' in result.headers['set-cookie']
    assert client.get('/api/owner/session').json()['authenticated']
    token = client.cookies.get(owner.COOKIE)
    assert client.delete('/api/owner/session', headers=headers).status_code == 200
    assert token not in owner._sessions
    client.post('/api/owner/session', headers=headers, json={'password': 'fake passphrase'})
    token = client.cookies.get(owner.COOKIE)
    owner._sessions[token] = 0
    assert not client.get('/api/owner/session').json()['authenticated']
    monkeypatch.setattr(owner.settings, 'HOME_HUB_OWNER_PASSWORD_VERIFIER', '')
    assert client.post('/api/owner/session', headers=headers, json={'password': 'fake passphrase'}).status_code == 401


def test_http_and_forwarded_denied(client, monkeypatch):
    monkeypatch.setattr(owner.settings, 'HOME_HUB_OWNER_ALLOWED_ORIGINS', 'http://hub.example')
    with TestClient(client.app, base_url='http://hub.example') as http:
        assert http.post('/api/owner/session', headers={'Origin': 'http://hub.example'}, json={'password': 'fake passphrase'}).status_code == 403
    assert client.post('/api/owner/session', headers={'Origin': 'https://hub.example', 'X-Forwarded-Proto': 'https'}, json={'password': 'fake passphrase'}).status_code == 403


@pytest.mark.asyncio
async def test_socket_owner_and_revocation(monkeypatch):
    monkeypatch.setattr(owner.settings, 'HOME_HUB_OWNER_ALLOWED_ORIGINS', 'https://hub.example')
    owner._sessions['fake-token'] = owner.time.monotonic() + 60
    manager = SimpleNamespace(connect=AsyncMock(), disconnect=Mock())
    state = SimpleNamespace(ws_manager=manager, hue=SimpleNamespace(connected=True), sonos=SimpleNamespace(connected=True), build_id='fake', automation=SimpleNamespace(current_mode='idle', mode_source='test', manual_override=None, house_state='home', activity='general', get_time_period=lambda: 'day'))
    frame = json.dumps({'type': 'light_command', 'data': {'command_id': 'fixture_123', 'light_id': '1', 'on': True}})
    async def receive():
        if not hasattr(receive, 'count'):
            receive.count = 1
            return frame
        owner._sessions.clear()
        if receive.count == 1:
            receive.count += 1
            return frame
        raise WebSocketDisconnect()
    socket = SimpleNamespace(app=SimpleNamespace(state=state), headers={'origin': 'https://hub.example', 'host': 'hub.example'}, scope={'scheme': 'wss'}, cookies={owner.COOKIE: 'fake-token'}, client=SimpleNamespace(host='192.0.2.1'), send_text=AsyncMock(), receive_text=receive)
    with patch('backend.main._handle_light_command', new_callable=AsyncMock, return_value='acknowledged') as light:
        await websocket_endpoint(socket)
    sent = [json.loads(c.args[0]) for c in socket.send_text.await_args_list]
    assert sent[0]['data']['light_command_results'] is True
    assert [m['data']['status'] for m in sent if m['type'] == 'light_command_result'] == ['acknowledged', 'denied']
    light.assert_awaited_once()


@pytest.mark.asyncio
async def test_rest_cookie_and_key(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(owner.settings, 'HOME_HUB_OWNER_ALLOWED_ORIGINS', 'https://hub.example')
    monkeypatch.setattr(owner.settings, 'HOME_HUB_API_KEY', 'fake-key')
    request = SimpleNamespace(headers={'origin': 'https://hub.example', 'host': 'hub.example'}, scope={'scheme': 'https'}, cookies={}, client=SimpleNamespace(host='192.168.1.2'))
    with pytest.raises(HTTPException):
        await require_owner_or_explicit_key(request, None, None)
    await require_owner_or_explicit_key(request, 'fake-key', None)
    owner._sessions['fake-token'] = owner.time.monotonic() + 60
    request.cookies[owner.COOKIE] = 'fake-token'
    await require_owner_or_explicit_key(request, None, None)

def test_loopback_exemption_and_rate_limit(client, monkeypatch):
    monkeypatch.setattr(owner.settings, 'HOME_HUB_OWNER_ALLOWED_ORIGINS', 'http://localhost:8000')
    with TestClient(client.app, base_url='http://localhost:8000', client=('127.0.0.1', 1234)) as local:
        headers = {'Origin': 'http://localhost:8000'}
        for _ in range(5):
            assert local.post('/api/owner/session', headers=headers, json={'password': 'wrong'}).status_code == 401
        assert local.post('/api/owner/session', headers=headers, json={'password': 'fake passphrase'}).status_code == 429
        owner._attempts.clear()
        result = local.post('/api/owner/session', headers=headers, json={'password': 'fake passphrase'})
        assert result.status_code == 200
        assert 'Secure' not in result.headers['set-cookie']


def test_real_login_socket_hue_and_revocation(client):
    from backend.main import websocket_endpoint
    from tests.test_ws_manual_light_guard import Engine, Hue

    engine = Engine()
    engine.mode_source = 'test'
    engine.manual_override = None
    engine.activity = 'general'
    engine.get_time_period = lambda: 'day'
    hue = Hue(engine)
    app = client.app
    async def connect(ws):
        await ws.accept()
    app.state.ws_manager = SimpleNamespace(connect=connect, disconnect=Mock())
    app.state.hue = hue
    app.state.sonos = SimpleNamespace(connected=False)
    app.state.automation = engine
    app.state.build_id = 'fake'
    app.add_api_websocket_route('/ws', websocket_endpoint)
    headers = {'Origin': 'https://hub.example'}
    assert client.post('/api/owner/session', headers=headers, json={'password': 'fake passphrase'}).status_code == 200
    with client.websocket_connect('wss://hub.example/ws', headers=headers) as ws:
        ws.receive_json()
        ws.receive_json()
        frame = {'type': 'light_command', 'data': {'command_id': 'fixture_123', 'light_id': '2', 'bri': 100}}
        ws.send_json(frame)
        assert ws.receive_json()['data']['status'] == 'acknowledged'
        assert hue.calls == [('2', {'bri': 100})]
        assert client.delete('/api/owner/session', headers=headers).status_code == 200
        ws.send_json(frame)
        assert ws.receive_json()['data']['status'] == 'denied'
        assert len(hue.calls) == 1


@pytest.mark.asyncio
async def test_sonos_session_revalidated_and_authenticated_validation(monkeypatch):
    monkeypatch.setattr(owner.settings, 'HOME_HUB_OWNER_ALLOWED_ORIGINS', 'https://hub.example')
    owner._sessions.clear()
    owner._sessions['fake-token'] = owner.time.monotonic() + 60
    manager = SimpleNamespace(connect=AsyncMock(), disconnect=Mock())
    sonos = SimpleNamespace(connected=True, pause=AsyncMock(return_value=True))
    state = SimpleNamespace(ws_manager=manager, hue=SimpleNamespace(connected=True), sonos=sonos, build_id='fake', automation=SimpleNamespace(current_mode='idle', mode_source='test', manual_override=None, house_state='home', activity='general', get_time_period=lambda: 'day'))
    commands = iter([
        {'type': 'light_command', 'data': {'light_id': '1', 'bri': 9999}},
        {'type': 'sonos_command', 'data': {'action': 'pause'}},
        {'type': 'sonos_command', 'data': {'action': 'pause'}},
    ])
    async def receive():
        try:
            frame = next(commands)
        except StopIteration:
            raise WebSocketDisconnect()
        if frame['type'] == 'sonos_command' and sonos.pause.await_count:
            owner._sessions.clear()
        return json.dumps(frame)
    socket = SimpleNamespace(app=SimpleNamespace(state=state), headers={'origin': 'https://hub.example', 'host': 'hub.example'}, scope={'scheme': 'wss'}, cookies={owner.COOKIE: 'fake-token'}, client=SimpleNamespace(host='192.0.2.1'), send_text=AsyncMock(), receive_text=receive)
    await websocket_endpoint(socket)
    errors = [json.loads(c.args[0])['data']['reason'] for c in socket.send_text.await_args_list if json.loads(c.args[0])['type'] == 'error']
    assert errors == ['validation', 'unauthorized']
    sonos.pause.assert_awaited_once()




@pytest.mark.asyncio
@pytest.mark.parametrize('expiry', [None, 0])
async def test_anonymous_and_expired_sonos_denied(monkeypatch, expiry):
    monkeypatch.setattr(owner.settings, 'HOME_HUB_OWNER_ALLOWED_ORIGINS', 'https://hub.example')
    owner._sessions.clear()
    if expiry is not None:
        owner._sessions['fake-token'] = expiry
    manager = SimpleNamespace(connect=AsyncMock(), disconnect=Mock())
    sonos = SimpleNamespace(connected=True, pause=AsyncMock())
    state = SimpleNamespace(ws_manager=manager, hue=SimpleNamespace(connected=True), sonos=sonos, build_id='fake', automation=SimpleNamespace(current_mode='idle', mode_source='test', manual_override=None, house_state='home', activity='general', get_time_period=lambda: 'day'))
    socket = SimpleNamespace(app=SimpleNamespace(state=state), headers={'origin': 'https://hub.example', 'host': 'hub.example'}, scope={'scheme': 'ws'}, cookies={owner.COOKIE: 'fake-token'}, client=SimpleNamespace(host='192.0.2.1'), send_text=AsyncMock(), receive_text=AsyncMock(side_effect=[json.dumps({'type': 'sonos_command', 'data': {'action': 'pause'}}), WebSocketDisconnect()]))
    await websocket_endpoint(socket)
    assert json.loads(socket.send_text.await_args_list[-1].args[0])['data']['reason'] == 'unauthorized'
    sonos.pause.assert_not_awaited()
