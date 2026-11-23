"""Scoped #461 mutation authorization with a fake app and no lifespan."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import owner_session as owner
from backend.api.routes import ambient, automation, routines, scenes, sonos


@pytest.mark.parametrize(('method', 'path'), [
    ('POST', '/api/scenes/example/activate'), ('POST', '/api/scenes/custom'),
    ('PUT', '/api/scenes/custom/example'), ('DELETE', '/api/scenes/custom/example'),
    ('POST', '/api/scenes/effects/example'), ('POST', '/api/scenes/effects/example/light/1'),
    ('POST', '/api/scenes/try/cancel'), ('POST', '/api/scenes/example/try'),
    ('POST', '/api/automation/override'), ('POST', '/api/automation/dnd'), ('DELETE', '/api/automation/dnd'),
    *[('POST', '/api/ambient/' + p) for p in ('play', 'pause', 'resume', 'stop', 'volume', 'config')],
    ('POST', '/api/routines/morning/test'), ('POST', '/api/routines/morning/toggle'), ('PUT', '/api/routines/morning/config'),
    ('POST', '/api/sonos/tts'), ('POST', '/api/sonos/favorites/example/play'), ('POST', '/api/sonos/favorites/refresh'),
])
@pytest.mark.parametrize('host', ['127.0.0.1', '192.168.1.10'])
def test_mutation_credentials(method, path, host, monkeypatch):
    monkeypatch.setattr(owner.settings, 'HOME_HUB_API_KEY', 'fake-key')
    monkeypatch.setattr(owner.settings, 'HOME_HUB_SKILL_TOKEN', 'fake-skill')
    monkeypatch.setattr(owner.settings, 'HOME_HUB_OWNER_ALLOWED_ORIGINS', 'https://hub.example')
    owner._sessions['fixture'] = owner.time.monotonic() + 60
    app = FastAPI()
    for route in (ambient, automation, routines, scenes, sonos):
        app.include_router(route.router)
    with TestClient(app, base_url='https://hub.example', client=(host, 1234), raise_server_exceptions=False) as client:
        def call(headers=None):
            return client.request(method, path, headers=headers or {}, json={}).status_code
        assert call() == 401
        assert call({'X-API-Key': 'fake-key'}) != 401
        client.cookies.set(owner.COOKIE, 'fixture')
        assert call({'Origin': 'https://hub.example'}) != 401
        tunnel = {'X-Tunnel-Origin': 'cloudflare', 'Origin': 'https://hub.example'}
        assert call(tunnel) == 401
        assert call({**tunnel, 'X-API-Key': 'fake-key'}) == 401
        assert call({**tunnel, 'X-API-Key': 'fake-key', 'X-Skill-Token': 'fake-skill'}) != 401
