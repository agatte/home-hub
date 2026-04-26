"""
Tests for the X-API-Key auth dependency.

Covers:
- Localhost bypass (kiosk colocation).
- Trusted-LAN-IP bypass (dev desktop, phone allowlist).
- Header check happy/sad paths.
- Fail-closed when HOME_HUB_API_KEY is unset.
- Smoke: a representative write endpoint per router actually rejects
  non-trusted unauthenticated requests at the wire.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.auth import TRUSTED_LOCAL, require_api_key
from backend.config import settings
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _make_request(host: str, header_value: str | None = None) -> MagicMock:
    """Build a fake Request with a controllable client.host."""
    req = MagicMock()
    req.client.host = host
    req.headers = {}
    if header_value is not None:
        req.headers = {"X-API-Key": header_value}
    return req


class TestRequireApiKeyDependency:
    """Unit tests around the dependency function itself."""

    @pytest.mark.asyncio
    async def test_unset_key_fails_closed(self, monkeypatch):
        # Empty key means: deploy didn't provision auth → reject every write.
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", None)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(_make_request("192.168.1.99"), x_api_key=None)
        assert exc_info.value.status_code == 503
        assert "HOME_HUB_API_KEY" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_localhost_bypass(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        for host in TRUSTED_LOCAL:
            await require_api_key(_make_request(host), x_api_key=None)  # no raise

    @pytest.mark.asyncio
    async def test_trusted_lan_ip_bypass(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "192.168.1.30,192.168.1.99")
        # Both listed IPs bypass without a header.
        await require_api_key(_make_request("192.168.1.30"), x_api_key=None)
        await require_api_key(_make_request("192.168.1.99"), x_api_key=None)

    @pytest.mark.asyncio
    async def test_correct_header_passes(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        await require_api_key(_make_request("192.168.1.99"), x_api_key="secret")

    @pytest.mark.asyncio
    async def test_missing_header_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(_make_request("192.168.1.99"), x_api_key=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_header_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(_make_request("192.168.1.99"), x_api_key="not-it")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_non_trusted_ip_no_header_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "192.168.1.30")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            # 192.168.1.99 is not in TRUSTED_LAN_IPS.
            await require_api_key(_make_request("192.168.1.99"), x_api_key=None)
        assert exc_info.value.status_code == 401


class TestTrustedLanIpsParsing:
    """Property: trusted_lan_ips_set tolerates whitespace + empty entries."""

    def test_parses_csv(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "192.168.1.30,192.168.1.99")
        assert settings.trusted_lan_ips_set == frozenset({"192.168.1.30", "192.168.1.99"})

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "  192.168.1.30 , 192.168.1.99 ")
        assert settings.trusted_lan_ips_set == frozenset({"192.168.1.30", "192.168.1.99"})

    def test_empty_string_yields_empty_set(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        assert settings.trusted_lan_ips_set == frozenset()


class TestSmokeWiring:
    """End-to-end: representative writes per router actually run the dep.

    The TestClient connects from 127.0.0.1, which always bypasses. To
    exercise the rejection path we override the dependency with a stub
    that simulates a non-trusted host. This proves both that (a) the
    decorator is wired and (b) the dependency hook is reachable.
    """

    def _stub_reject(self):
        from fastapi import HTTPException
        async def _reject(request=None, x_api_key=None):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return _reject

    def test_localhost_writes_succeed_unauthenticated(self, client):
        # Sanity: TestClient is on 127.0.0.1, no override → bypass kicks in,
        # the write may 200 / 400 / 500 depending on backend state, but it
        # must NOT 401. (Some endpoints validate body before they touch
        # state; we just need to confirm auth doesn't reject us.)
        resp = client.post("/api/automation/override", json={"mode": "relax"})
        assert resp.status_code != 401, resp.text

    def test_override_dependency_rejects_when_overridden(self, client):
        # Force-override require_api_key to always reject. Now the same
        # write endpoint should 401 — proving the decorator is wired.
        app.dependency_overrides[require_api_key] = self._stub_reject()
        try:
            resp = client.post("/api/automation/override", json={"mode": "relax"})
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.pop(require_api_key, None)

    def test_lights_set_rejects_when_overridden(self, client):
        app.dependency_overrides[require_api_key] = self._stub_reject()
        try:
            resp = client.put("/api/lights/1", json={"on": True})
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.pop(require_api_key, None)

    def test_sonos_play_rejects_when_overridden(self, client):
        app.dependency_overrides[require_api_key] = self._stub_reject()
        try:
            resp = client.post("/api/sonos/play")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.pop(require_api_key, None)

    def test_scene_activate_rejects_when_overridden(self, client):
        app.dependency_overrides[require_api_key] = self._stub_reject()
        try:
            resp = client.post("/api/scenes/some-scene/activate")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.pop(require_api_key, None)

    def test_reads_unaffected_by_dependency(self, client):
        # Reads stay open: even with a forced-reject auth dep, GETs must
        # succeed because they don't carry the dependency.
        app.dependency_overrides[require_api_key] = self._stub_reject()
        try:
            resp = client.get("/health")
            assert resp.status_code == 200
            resp = client.get("/api/lights")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(require_api_key, None)

    def test_presence_webhook_uses_separate_token(self, client):
        # The presence webhooks must NOT route through require_api_key —
        # they have their own X-Presence-Token. Forcing the API-key dep
        # to reject must not affect them.
        app.dependency_overrides[require_api_key] = self._stub_reject()
        try:
            # Without a configured PRESENCE_WEBHOOK_TOKEN, the webhook
            # returns 503 ("disabled"). Any code other than 401 from the
            # API-key dep proves the two paths are separate.
            resp = client.post("/api/automation/presence/arrived", json={})
            assert resp.status_code != 401, (
                "presence webhook accidentally went through require_api_key"
            )
        finally:
            app.dependency_overrides.pop(require_api_key, None)
