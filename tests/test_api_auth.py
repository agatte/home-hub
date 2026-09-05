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


def _make_request(
    host: str,
    header_value: str | None = None,
    *,
    tunnel: bool = False,
) -> MagicMock:
    """Build a fake Request with a controllable client.host.

    When ``tunnel=True``, the X-Tunnel-Origin header is set so the gate
    treats the caller as cloudflared-forwarded and skips bypasses.
    """
    req = MagicMock()
    req.client.host = host
    headers: dict[str, str] = {}
    if header_value is not None:
        headers["X-API-Key"] = header_value
    if tunnel:
        headers["X-Tunnel-Origin"] = "cloudflare"
    req.headers = headers
    return req


class TestRequireApiKeyDependency:
    """Unit tests around the dependency function itself."""

    @pytest.mark.asyncio
    async def test_unset_key_fails_closed(self, monkeypatch):
        # Empty key means: deploy didn't provision auth → reject every write
        # from non-trusted (public) callers. Use a public IP so the RFC1918
        # bypass doesn't short-circuit the check.
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", None)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(_make_request("8.8.8.8"), x_api_key=None)
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
        # Public IP — only the header check can save it.
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        await require_api_key(_make_request("8.8.8.8"), x_api_key="secret")

    @pytest.mark.asyncio
    async def test_missing_header_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(_make_request("8.8.8.8"), x_api_key=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_header_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(_make_request("8.8.8.8"), x_api_key="not-it")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_rfc1918_192_bypass(self, monkeypatch):
        # Phone on the apartment LAN — not pinned in TRUSTED_LAN_IPS,
        # but the RFC1918 bypass covers it.
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        await require_api_key(_make_request("192.168.1.148"), x_api_key=None)

    @pytest.mark.asyncio
    async def test_rfc1918_10_bypass(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        await require_api_key(_make_request("10.0.0.5"), x_api_key=None)

    @pytest.mark.asyncio
    async def test_rfc1918_172_bypass(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        await require_api_key(_make_request("172.16.0.1"), x_api_key=None)

    @pytest.mark.asyncio
    async def test_public_ip_still_rejected(self, monkeypatch):
        # Non-private callers must still present the header.
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(_make_request("8.8.8.8"), x_api_key=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_host_still_rejected(self, monkeypatch):
        # Empty client.host (request.client is None upstream → "") must
        # not crash ipaddress.ip_address; it should fall through to the
        # header check and 401.
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(_make_request(""), x_api_key=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_non_trusted_ip_no_header_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "TRUSTED_LAN_IPS", "192.168.1.30")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            # 1.2.3.4 is public — neither pinned nor RFC1918.
            await require_api_key(_make_request("1.2.3.4"), x_api_key=None)
        assert exc_info.value.status_code == 401


class TestTunnelOriginGate:
    """Phase 5: cloudflared-forwarded traffic must hit the strict path.

    The tunnel passthrough on 127.0.0.1:8001 injects ``X-Tunnel-Origin:
    cloudflare`` on every request. When that header is present:
    - Localhost / RFC1918 / TRUSTED_LAN_IPS bypasses must NOT fire
      (cloudflared delivers to loopback, which would otherwise be
      indistinguishable from the kiosk).
    - Both X-API-Key AND X-Skill-Token are required.
    """

    @pytest.mark.asyncio
    async def test_tunnel_skips_localhost_bypass(self, monkeypatch):
        """Even from 127.0.0.1, the tunnel header forces the header check."""
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "HOME_HUB_SKILL_TOKEN", "skill-secret")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(
                _make_request("127.0.0.1", tunnel=True),
                x_api_key=None,
                x_skill_token=None,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_tunnel_skips_rfc1918_bypass(self, monkeypatch):
        """Forged tunnel header from a LAN IP also routes through header check."""
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "HOME_HUB_SKILL_TOKEN", "skill-secret")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(
                _make_request("192.168.1.148", tunnel=True),
                x_api_key=None,
                x_skill_token=None,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_tunnel_requires_both_headers(self, monkeypatch):
        """API key alone (no skill token) → 401 when tunneled."""
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "HOME_HUB_SKILL_TOKEN", "skill-secret")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(
                _make_request("127.0.0.1", tunnel=True),
                x_api_key="secret",
                x_skill_token=None,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_tunnel_wrong_skill_token(self, monkeypatch):
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "HOME_HUB_SKILL_TOKEN", "skill-secret")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(
                _make_request("127.0.0.1", tunnel=True),
                x_api_key="secret",
                x_skill_token="not-it",
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_tunnel_both_headers_correct(self, monkeypatch):
        """Both headers correct → pass."""
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "HOME_HUB_SKILL_TOKEN", "skill-secret")
        await require_api_key(
            _make_request("127.0.0.1", tunnel=True),
            x_api_key="secret",
            x_skill_token="skill-secret",
        )

    @pytest.mark.asyncio
    async def test_tunnel_unset_skill_token_fails_closed(self, monkeypatch):
        """If the deploy didn't provision HOME_HUB_SKILL_TOKEN, tunneled
        traffic must 503 — refuse rather than silently degrade to API-key
        only."""
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "HOME_HUB_SKILL_TOKEN", None)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(
                _make_request("127.0.0.1", tunnel=True),
                x_api_key="secret",
                x_skill_token="anything",
            )
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_non_tunnel_unaffected_by_skill_token(self, monkeypatch):
        """LAN traffic (no tunnel header) MUST NOT need a skill token."""
        monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "secret")
        monkeypatch.setattr(settings, "HOME_HUB_SKILL_TOKEN", None)
        # RFC1918 caller without any headers — bypass fires.
        await require_api_key(
            _make_request("192.168.1.148", tunnel=False),
            x_api_key=None,
            x_skill_token=None,
        )


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

    def test_sleep_evidence_ingest_rejects_when_auth_dependency_rejects(self, client):
        app.dependency_overrides[require_api_key] = self._stub_reject()
        try:
            resp = client.post(
                "/api/sleep/evidence",
                json={
                    "client_kind": "manual_test",
                    "client_observed_at": "2026-09-05T20:00:00Z",
                    "deleted_sample_uuids": ["test-auth-boundary"],
                },
            )
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.pop(require_api_key, None)

    def test_reads_unaffected_by_dependency(self, client):
        # Reads stay open: even with a forced-reject auth dep, GETs must not
        # be rejected by it. The endpoint may still return 503 if the
        # underlying device is unreachable (e.g. Hue bridge absent in CI) —
        # that's a separate concern; we only care here that auth didn't bite.
        app.dependency_overrides[require_api_key] = self._stub_reject()
        try:
            resp = client.get("/health")
            assert resp.status_code == 200
            resp = client.get("/api/lights")
            assert resp.status_code not in (401, 403)
        finally:
            app.dependency_overrides.pop(require_api_key, None)

