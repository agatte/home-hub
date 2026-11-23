"""Owner trusted-device sessions survive restart without relaxing the WSS gate."""
import os
import sqlite3
import stat
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import owner_session as owner

ORIGIN = "https://hub.example"
HEADERS = {"Origin": ORIGIN}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(owner, "SESSION_DB_PATH", tmp_path / "sessions.sqlite3")
    monkeypatch.setattr(owner.settings, "HOME_HUB_OWNER_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setattr(owner, "_verify", lambda *_: True)
    owner._sessions.clear()
    owner._attempts.clear()
    app = FastAPI()
    app.include_router(owner.router)
    with TestClient(app, base_url=ORIGIN) as test_client:
        yield test_client
    owner._sessions.clear()
    owner._attempts.clear()


def _wss(token, *, origin=ORIGIN, host="hub.example", forwarded=False):
    headers = {"origin": origin, "host": host}
    if forwarded:
        headers["x-forwarded-proto"] = "https"
    return SimpleNamespace(
        scope={"scheme": "wss"},
        headers=headers,
        cookies={owner.COOKIE: token},
        client=SimpleNamespace(host="192.168.86.20"),
    )


def test_trusted_owner_login_survives_backend_restart_and_browser_reopen(client):
    response = client.post("/api/owner/session", headers=HEADERS, json={"password": "correct"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "max-age=31536000" in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    token = client.cookies.get(owner.COOKIE)
    assert token
    assert owner.valid_session(_wss(token))
    # Simulate process restart: only the SQLite store is left.
    owner._sessions.clear()
    assert client.get("/api/owner/session").json() == {"authenticated": True}
    assert owner.valid_session(_wss(token))
    db_contents = owner.SESSION_DB_PATH.read_bytes()
    assert token.encode() not in db_contents
    if os.name == "posix":
        assert stat.S_IMODE(owner.SESSION_DB_PATH.stat().st_mode) == 0o600


def test_logout_revocation_persists_after_restart(client):
    assert client.post("/api/owner/session", headers=HEADERS, json={"password": "correct"}).status_code == 200
    token = client.cookies.get(owner.COOKIE)
    owner._sessions.clear()
    assert owner.valid_session(_wss(token))
    assert client.delete("/api/owner/session", headers=HEADERS).status_code == 200
    owner._sessions.clear()
    assert not owner.valid_session(_wss(token))
    assert client.get("/api/owner/session").json() == {"authenticated": False}


def test_persisted_expiry_and_origin_protection_remain_enforced(client):
    assert client.post("/api/owner/session", headers=HEADERS, json={"password": "correct"}).status_code == 200
    token = client.cookies.get(owner.COOKIE)
    owner._sessions.clear()
    assert not owner.valid_session(_wss(token, origin="https://evil.example"))
    assert not owner.valid_session(_wss(token, host="evil.example"))
    assert not owner.valid_session(_wss(token, forwarded=True))
    assert owner.valid_session(_wss(token))
    owner._sessions.clear()
    with sqlite3.connect(owner.SESSION_DB_PATH) as db:
        db.execute("UPDATE owner_sessions SET expires_at = 1")
    assert not owner.valid_session(_wss(token))
    assert client.get("/api/owner/session").json() == {"authenticated": False}


def test_revoked_device_cannot_be_revived_by_manual_cache_clear(client):
    assert client.post("/api/owner/session", headers=HEADERS, json={"password": "correct"}).status_code == 200
    token = client.cookies.get(owner.COOKIE)
    assert client.delete("/api/owner/session", headers={"Origin": "https://evil.example"}).status_code == 403
    assert owner.valid_session(_wss(token))
    assert client.delete("/api/owner/session", headers=HEADERS).status_code == 200
    owner._sessions.clear()
    assert not owner.valid_session(_wss(token))
