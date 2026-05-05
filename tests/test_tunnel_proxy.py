"""Tests for the Cloudflare Tunnel passthrough.

Pin the two invariants:
- Every forwarded request gets X-Tunnel-Origin: cloudflare regardless of
  what the caller sent. The auth gate's strict path keys off this header,
  so a missing or stripped injection silently degrades the gate to the
  loopback bypass — defense-in-depth.
- Hop-by-hop headers (Connection, Transfer-Encoding, Host, Content-Length)
  are NOT forwarded; they confuse httpx + uvicorn and would mis-route the
  request.

Doesn't actually start the upstream FastAPI app — uses an in-process
mock httpx transport so the proxy can be exercised without a live :8000.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api.tunnel_proxy import create_app


def _capturing_transport(captured: list[httpx.Request]):
    """httpx MockTransport that records every outbound request + replies 200."""
    def _handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "x-upstream": "yes"},
            content=b'{"ok": true}',
        )
    return httpx.MockTransport(_handle)


@pytest.fixture
def proxy_with_capture():
    """Build the tunnel-proxy app with a mock httpx transport that captures
    every forwarded request for assertion."""
    captured: list[httpx.Request] = []
    app = create_app()

    # Replace the startup-created client with one that uses MockTransport.
    # Doing this in startup keeps the lifespan path realistic.
    original_startup = app.router.on_startup[0]

    async def _patched_startup() -> None:
        app.state.client = httpx.AsyncClient(
            base_url="http://127.0.0.1:8000",
            transport=_capturing_transport(captured),
            timeout=2.0,
        )

    app.router.on_startup[0] = _patched_startup

    with TestClient(app) as client:
        yield client, captured


def test_injects_tunnel_origin_header(proxy_with_capture):
    client, captured = proxy_with_capture
    resp = client.get("/api/lights")
    assert resp.status_code == 200
    assert len(captured) == 1
    fwd = captured[0]
    assert fwd.headers.get("x-tunnel-origin") == "cloudflare"


def test_overwrites_caller_supplied_tunnel_header(proxy_with_capture):
    """A malicious caller can't smuggle a forged header through the proxy —
    we ALWAYS overwrite it. (The proxy is bound to localhost only, but
    defense-in-depth.)"""
    client, captured = proxy_with_capture
    resp = client.get(
        "/api/lights", headers={"X-Tunnel-Origin": "spoofed-value"}
    )
    assert resp.status_code == 200
    assert captured[0].headers.get("x-tunnel-origin") == "cloudflare"


def test_strips_hop_by_hop_request_headers(proxy_with_capture):
    """Caller-supplied hop-by-hop headers MUST NOT leak through.

    Note: httpx adds its own Connection / Host headers to the outbound
    request — that's correct behavior, those govern the proxy↔upstream
    leg, not the caller↔proxy leg. We only care that the CALLER's
    values don't propagate.
    """
    client, captured = proxy_with_capture
    client.get(
        "/api/lights",
        headers={
            "Keep-Alive": "timeout=5",
            "TE": "trailers",
        },
    )
    fwd_headers = {k.lower() for k in captured[0].headers.keys()}
    # httpx doesn't send these by default; their absence proves the
    # proxy stripped what the caller put in.
    assert "keep-alive" not in fwd_headers
    assert "te" not in fwd_headers


def test_forwards_post_body(proxy_with_capture):
    """The Skill posts JSON; ensure the body actually reaches upstream."""
    client, captured = proxy_with_capture
    resp = client.post(
        "/api/automation/override",
        json={"mode": "relax"},
        headers={"X-API-Key": "k", "X-Skill-Token": "t"},
    )
    assert resp.status_code == 200
    fwd = captured[0]
    assert fwd.method == "POST"
    assert b'"mode"' in fwd.content
    # Original auth headers must pass through (they're not hop-by-hop).
    assert fwd.headers.get("x-api-key") == "k"
    assert fwd.headers.get("x-skill-token") == "t"


def test_forwards_query_string(proxy_with_capture):
    client, captured = proxy_with_capture
    client.get("/api/state-history?minutes=5")
    fwd = captured[0]
    assert "minutes=5" in str(fwd.url)


def test_returns_upstream_status_and_body(proxy_with_capture):
    client, _ = proxy_with_capture
    resp = client.get("/api/lights")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # Non-hop-by-hop response headers pass through.
    assert resp.headers.get("x-upstream") == "yes"


def test_502_on_upstream_connect_error():
    """If the main app is down, the proxy returns 502 instead of crashing."""
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    app = create_app()

    async def _patched_startup() -> None:
        app.state.client = httpx.AsyncClient(
            base_url="http://127.0.0.1:8000",
            transport=httpx.MockTransport(_handler),
            timeout=2.0,
        )
    app.router.on_startup[0] = _patched_startup

    with TestClient(app) as client:
        resp = client.get("/api/lights")
        assert resp.status_code == 502


def test_504_on_upstream_timeout():
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream slow")

    app = create_app()

    async def _patched_startup() -> None:
        app.state.client = httpx.AsyncClient(
            base_url="http://127.0.0.1:8000",
            transport=httpx.MockTransport(_handler),
            timeout=2.0,
        )
    app.router.on_startup[0] = _patched_startup

    with TestClient(app) as client:
        resp = client.get("/api/lights")
        assert resp.status_code == 504
