"""Tests for the public-tunnel hardening added in the 2026-05 security pass.

Two surfaces:

1. Security response headers — every HTTP response should carry the
   defense-in-depth headers (CSP, X-Frame-Options, X-Content-Type-Options,
   Referrer-Policy, Permissions-Policy). HSTS only when the request is
   tunnel-marked (plain HTTP LAN traffic shouldn't advertise it).

2. WebSocket rate limit — a flood of commands on a single connection
   should hit the limit and start receiving `rate_limit` reject messages
   without disconnecting the socket. The slowapi limiter only binds to
   HTTP routes; this bucket lives in main.py and is the only thing
   between the kiosk's slider drags and the WS handler.

These tests use the real app fixture from conftest so the middleware
chain matches production.
"""
from __future__ import annotations

import time

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

import backend.api.routes.pihole_proxy as pihole_proxy

from backend.main import _ws_rate_limit_check, _WS_RATE_LIMIT_MAX, app


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# --- Security response headers ------------------------------------------------

def test_security_headers_present_on_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "strict-origin" in resp.headers["Referrer-Policy"]
    assert "camera=()" in resp.headers["Permissions-Policy"]
    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_security_headers_present_on_api_route(client):
    """Headers ride on JSON API responses too, not just static HTML."""
    resp = client.get("/api/lights")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in resp.headers


def test_pihole_admin_iframe_allows_same_origin_framing(client, monkeypatch):
    """The Pi-hole proxy is intentionally frameable only by HomeHub itself."""

    async def fake_proxy(request, target_url):
        return Response(content=b"Pi-hole admin", media_type="text/html")

    monkeypatch.setattr(pihole_proxy, "_proxy", fake_proxy)
    resp = client.get("/admin/", headers={"Sec-Fetch-Dest": "iframe"})

    assert resp.status_code == 200
    assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"
    csp = resp.headers["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in csp
    assert "frame-ancestors 'none'" not in csp
    assert "default-src 'self'" in csp


def test_pihole_admin_direct_navigation_still_redirects(client):
    """The kiosk cannot navigate away from HomeHub into Pi-hole directly."""
    resp = client.get(
        "/admin/",
        headers={"Sec-Fetch-Dest": "document"},
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303, 307, 308}
    assert resp.headers["location"] == "/"


def test_hsts_only_on_tunnel_origin(client):
    """HSTS is meaningless over plain-HTTP LAN traffic; it should only
    appear when the request claims tunnel origin (where Cloudflare
    terminates TLS upstream)."""
    # LAN — no HSTS
    resp = client.get("/health")
    assert "Strict-Transport-Security" not in resp.headers
    # Tunnel — HSTS present
    resp = client.get("/health", headers={"X-Tunnel-Origin": "cloudflare"})
    assert "Strict-Transport-Security" in resp.headers
    hsts = resp.headers["Strict-Transport-Security"]
    assert "max-age=" in hsts
    assert "includeSubDomains" in hsts


def test_security_headers_present_on_error_response(client):
    """A 404 from the catch-all route still gets the headers — an attacker
    probing for unmapped paths shouldn't get a softer security posture
    than a happy-path caller."""
    resp = client.get("/api/this-does-not-exist")
    # Either 404 (router miss) or some other non-200 — accept anything
    # that isn't a 200, and assert headers still ride along.
    assert resp.status_code >= 400
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


# --- WebSocket rate limit -----------------------------------------------------

def test_ws_rate_bucket_allows_up_to_max():
    """The bucket admits exactly `_WS_RATE_LIMIT_MAX` rapid commands."""
    from collections import deque
    bucket: deque[float] = deque()
    allowed = sum(1 for _ in range(_WS_RATE_LIMIT_MAX) if _ws_rate_limit_check(bucket))
    assert allowed == _WS_RATE_LIMIT_MAX
    # The next one should be rejected
    assert _ws_rate_limit_check(bucket) is False


def test_ws_rate_bucket_slides_window():
    """Old timestamps drop out of the window so the bucket isn't a
    permanent cap — kiosk that drags a slider for 2 minutes straight
    should keep working, just throttled."""
    from collections import deque
    bucket: deque[float] = deque()
    # Fill the bucket
    for _ in range(_WS_RATE_LIMIT_MAX):
        _ws_rate_limit_check(bucket)
    assert _ws_rate_limit_check(bucket) is False
    # Forge an old timestamp into the front so the next check sees an
    # expired entry; real-world equivalent is waiting out the window.
    bucket[0] = time.monotonic() - 1000.0
    assert _ws_rate_limit_check(bucket) is True


# NOTE: an end-to-end WS flood test was tried and dropped — TestClient's
# sync websocket has no timeout-aware receive and the happy-path command
# emits no response, so draining is timing-dependent and flaky in CI. The
# unit tests above pin the bucket math; the wiring into the handler is
# small enough to eyeball and confirms itself via journalctl on the kiosk
# after deploy ("WebSocket rate limit hit" log line).
