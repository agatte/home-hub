"""Isolated owner-browser listening route tests; no device or production DB."""
import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import owner_session
from backend.api.routes.music import router
from backend.rate_limit import limiter
from backend.services.music_mix_execution import MixStartResult
from tests.test_music_selected_plan import request


class Requests:
    async def preview(self, *args, **kwargs):
        return request()


class Session:
    def __init__(self):
        self.calls = []

    def issue(self, preview, *, owner_scope, limit):
        self.calls.append(("issue", owner_scope, limit))
        return {"status": "selection_available", "token": "synthetic-ticket"}

    async def start(self, token, choice_id, *, owner_scope, authorized):
        assert authorized()
        self.calls.append(("start", token, choice_id, owner_scope))
        return MixStartResult("suppressed", "mock_no_device")


def client_for(monkeypatch):
    monkeypatch.setattr(owner_session.settings, "HOME_HUB_OWNER_ALLOWED_ORIGINS", "https://testserver")
    monkeypatch.setattr(owner_session, "_valid_token", lambda token: token == "synthetic-owner")
    app = FastAPI()
    app.state.limiter = limiter
    app.state.music_requests = Requests()
    app.state.music_listening_session = Session()
    app.include_router(router)
    return TestClient(app, base_url="https://testserver"), app.state.music_listening_session


def test_preview_and_start_require_direct_owner_context(monkeypatch):
    client, service = client_for(monkeypatch)
    preview = {"request": "relaxing", "listening": True}
    payload = {"token": "synthetic-ticket", "choice_id": "artist_mix:11,12"}
    assert "listening_selection" not in client.post("/api/music/request/preview", json=preview).json()
    assert client.post("/api/music/listening/start", json=payload).status_code == 401
    client.cookies.set(owner_session.COOKIE, "synthetic-owner")
    assert client.post("/api/music/listening/start", json=payload).status_code == 401
    headers = {"Origin": "https://testserver"}
    assert client.post("/api/music/listening/start", json=payload,
                       headers={**headers, "X-Tunnel-Origin": "cloudflare"}).status_code == 401
    assert client.post("/api/music/listening/start", json=payload,
                       headers={**headers, "X-Forwarded-For": "127.0.0.1"}).status_code == 401
    assert service.calls == []
    response = client.post("/api/music/request/preview", json=preview, headers=headers)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["listening_selection"]["token"] == "synthetic-ticket"
    scope = hashlib.sha256(b"synthetic-owner").hexdigest()
    assert service.calls == [("issue", scope, 6)]
    response = client.post("/api/music/listening/start", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {"status": "suppressed", "reason": "mock_no_device", "confirmed_appends": 0, "continuation_tracks": 0, "sustained_listening": False}
    assert service.calls[-1] == ("start", "synthetic-ticket", "artist_mix:11,12", scope)
    assert client.post("/api/music/listening/start", json={**payload, "owner_scope": "forged"},
                       headers=headers).status_code == 422
    assert len(service.calls) == 2
