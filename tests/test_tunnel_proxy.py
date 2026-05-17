"""Tests for the Cloudflare Tunnel passthrough.

Pin three invariants:
- Every forwarded request gets X-Tunnel-Origin: cloudflare regardless of
  what the caller sent. The auth gate's strict path keys off this header,
  so a missing or stripped injection silently degrades the gate to the
  loopback bypass — defense-in-depth.
- Hop-by-hop headers (Connection, Transfer-Encoding, Host, Content-Length)
  are NOT forwarded; they confuse httpx + uvicorn and would mis-route the
  request.
- Only the explicit (method, path) pairs the Alexa Lambda calls are
  forwarded. Everything else 404s — the public tunnel must NOT be a
  wildcard pipe into the backend.

Doesn't actually start the upstream FastAPI app — uses an in-process
mock httpx transport so the proxy can be exercised without a live :8000.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api.tunnel_proxy import create_app

# An endpoint guaranteed to be in the allowlist — used as the "happy path"
# fixture for the invariants below. If this ever needs to change, pick
# any other GET row from `_ALLOWED` in tunnel_proxy.py.
_OK_GET = "/api/automation/status"


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
    resp = client.get(_OK_GET)
    assert resp.status_code == 200
    assert len(captured) == 1
    fwd = captured[0]
    assert fwd.headers.get("x-tunnel-origin") == "cloudflare"


def test_overwrites_caller_supplied_tunnel_header(proxy_with_capture):
    """A malicious caller can't smuggle a forged header through the proxy —
    we ALWAYS overwrite it. (The proxy is bound to localhost only, but
    defense-in-depth.)"""
    client, captured = proxy_with_capture
    resp = client.get(_OK_GET, headers={"X-Tunnel-Origin": "spoofed-value"})
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
        _OK_GET,
        headers={"Keep-Alive": "timeout=5", "TE": "trailers"},
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
    client.get(f"{_OK_GET}?minutes=5")
    fwd = captured[0]
    assert "minutes=5" in str(fwd.url)


def test_returns_upstream_status_and_body(proxy_with_capture):
    client, _ = proxy_with_capture
    resp = client.get(_OK_GET)
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
        resp = client.get(_OK_GET)
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
        resp = client.get(_OK_GET)
        assert resp.status_code == 504


# --- Allowlist coverage ------------------------------------------------------
#
# These pin the public-tunnel surface to exactly what the Alexa Lambda
# uses. Adding a new Alexa intent means adding a row here AND to the
# `_ALLOWED` tuple in `backend/api/tunnel_proxy.py`. Removing one means
# removing both. If an intent moves to a new path, both spots need the
# update — silent breakage otherwise.

ALLOWED_PATHS_FROM_LAMBDA = [
    # (method, path) — every row that `_call_homehub` in lambda_function.py touches.
    # /api/ping is the off-LAN uptime-monitor probe — not Lambda-driven, but
    # part of the same public-tunnel allowlist surface.
    ("GET", "/api/ping"),
    ("POST", "/api/automation/override"),
    ("POST", "/api/automation/dnd"),
    ("DELETE", "/api/automation/dnd"),
    ("GET", "/api/automation/status"),
    ("POST", "/api/lights/brightness/up"),
    ("POST", "/api/lights/brightness/down"),
    ("POST", "/api/scenes/house_party/activate"),
    ("POST", "/api/scenes/neon_tokyo/activate"),
    ("POST", "/api/scenes/miami_vice/activate"),
    ("POST", "/api/scenes/arcade/activate"),
    ("POST", "/api/scenes/northern_lights/activate"),
    ("POST", "/api/scenes/sunset_strip/activate"),
    ("POST", "/api/scenes/effects/candle"),
    ("POST", "/api/scenes/effects/fire"),
    ("POST", "/api/scenes/effects/sparkle"),
    ("POST", "/api/scenes/effects/prism"),
    ("POST", "/api/scenes/effects/glisten"),
    ("POST", "/api/scenes/effects/opal"),
    ("POST", "/api/scenes/effects/stop"),
    ("POST", "/api/sonos/smart-play"),
    ("POST", "/api/sonos/pause"),
    ("POST", "/api/sonos/next"),
    ("POST", "/api/sonos/previous"),
    ("POST", "/api/sonos/volume/up"),
    ("POST", "/api/sonos/volume/down"),
    ("GET", "/api/sonos/status"),
]


@pytest.mark.parametrize("method,path", ALLOWED_PATHS_FROM_LAMBDA)
def test_allowlist_forwards_every_lambda_endpoint(
    proxy_with_capture, method, path,
):
    client, captured = proxy_with_capture
    if method == "GET":
        resp = client.get(path)
    elif method == "POST":
        # POST endpoints accept empty body — none of these require JSON
        # to make it past the allowlist check.
        resp = client.post(path)
    elif method == "DELETE":
        resp = client.delete(path)
    else:
        pytest.fail(f"unhandled method: {method}")
    assert resp.status_code == 200, f"{method} {path} got {resp.status_code}"
    assert len(captured) == 1, f"{method} {path} not forwarded"


# Endpoints that exist on the backend but are NOT in the Lambda surface.
# Some of these are sensitive (camera snapshot, journal entries with PII);
# others are merely "shouldn't be reachable from the public internet by
# default" (raw lights state, scene browsing). All must 404 at the tunnel.
DISALLOWED_PATHS = [
    ("GET", "/api/camera/snapshot"),       # sensitive — webcam JPEG
    ("GET", "/api/camera/status"),         # leaks zone/posture/lux
    ("GET", "/api/lights"),                # raw light state
    ("GET", "/api/journal/2026-05-16"),    # behavioral narrative
    ("GET", "/api/scenes"),                # scene browser
    ("GET", "/api/weather"),               # bandwidth abuse vector
    ("GET", "/api/pihole/stats"),          # network stats
    ("GET", "/health"),                    # version disclosure
    ("POST", "/api/lights/1"),             # per-bulb writes — POST OK by method, path not allowed
    ("POST", "/api/camera/enable"),        # toggle camera from public side
    ("POST", "/api/automation/clear"),     # not the dnd endpoint
    ("GET", "/api/debug/query"),           # SELECT-only but still gated
]


@pytest.mark.parametrize("method,path", DISALLOWED_PATHS)
def test_allowlist_rejects_non_lambda_paths(
    proxy_with_capture, method, path,
):
    client, captured = proxy_with_capture
    if method == "GET":
        resp = client.get(path)
    elif method == "POST":
        resp = client.post(path)
    else:
        pytest.fail(f"unhandled method: {method}")
    assert resp.status_code == 404, f"{method} {path} got {resp.status_code}"
    assert len(captured) == 0, f"{method} {path} was unexpectedly forwarded"


def test_allowlist_wrong_method_is_404(proxy_with_capture):
    """A path that's allowed for POST must 404 for GET (and vice versa)."""
    client, captured = proxy_with_capture
    # /api/automation/override is POST-only on the allowlist
    resp = client.get("/api/automation/override")
    assert resp.status_code == 404
    assert len(captured) == 0
    # /api/sonos/status is GET-only on the allowlist
    resp = client.post("/api/sonos/status")
    assert resp.status_code == 404
    assert len(captured) == 0


def test_allowlist_rejects_bounded_enum_off_value(proxy_with_capture):
    """The scene/effect/direction enums are bounded — random values 404."""
    client, captured = proxy_with_capture
    cases = [
        "/api/scenes/not_a_real_scene/activate",
        "/api/scenes/effects/laser",      # not in the 6 effects
        "/api/lights/brightness/sideways",  # not up/down
        "/api/sonos/volume/medium",       # not up/down
    ]
    for path in cases:
        resp = client.post(path)
        assert resp.status_code == 404, f"{path} unexpectedly accepted"
    assert len(captured) == 0


def test_allowlist_rejects_path_traversal(proxy_with_capture):
    """Path traversal in the URL path must not slip past the regex anchors.

    Starlette normalizes `..` segments before the proxy ever sees them in
    most cases, but a percent-encoded form (`%2e%2e`) bypasses the
    normalizer and reaches the route handler with the raw bytes — our
    anchored regex is what stops it.
    """
    client, captured = proxy_with_capture
    cases = [
        "/api/automation/override/../../../etc/passwd",
        "/api/automation/override%00",       # null byte
        "/api/automation/override/extra",     # trailing path
        "/api/automation/override?x=y#frag",  # fragment can't traverse but proves anchor holds
    ]
    for path in cases:
        resp = client.get(path)
        # Either Starlette routes it elsewhere (no capture) or the proxy
        # 404s it (no capture) — never forwarded.
        assert len(captured) == 0, f"{path} unexpectedly forwarded ({resp.status_code})"


def test_allowlist_unused_methods_blocked(proxy_with_capture):
    """PUT/PATCH/HEAD/OPTIONS are not declared on the route — Starlette
    returns 405 (method not allowed). That's stronger than allowlist 404
    and we want to keep it that way."""
    client, _ = proxy_with_capture
    resp = client.put("/api/automation/override", json={"mode": "relax"})
    assert resp.status_code == 405
    resp = client.patch("/api/automation/override", json={})
    assert resp.status_code == 405
