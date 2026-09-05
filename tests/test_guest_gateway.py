"""Security-boundary tests for the isolated public guest gateway."""
import httpx
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.api.auth import require_api_key

from backend.api.guest_gateway import create_app


def _upstream(request: httpx.Request) -> httpx.Response:
    if request.url.path.startswith("/_app/"):
        return httpx.Response(200, content=b"asset", headers={"content-type": "text/javascript"})
    if request.url.path.startswith("/guest"):
        return httpx.Response(200, content=b"guest-ui", headers={"content-type": "text/html"})
    if request.url.path == "/api/guest/state":
        return httpx.Response(200, json={"status": "ok", "mode": "social"})
    if request.url.path == "/api/guest/sonos/play":
        return httpx.Response(200, json={"status": "ok"})
    return httpx.Response(500, json={"unexpected": request.url.path})


def _client() -> TestClient:
    app = create_app(
        public_url="https://guest.example.test",
        invite_ttl=60,
        session_ttl=600,
        client_transport=httpx.MockTransport(_upstream),
    )
    return TestClient(app, base_url="https://guest.example.test")


def _join(client: TestClient) -> str:
    invite = client.post("/internal/invite")
    assert invite.status_code == 200
    join_url = invite.json()["join_url"]
    token = join_url.rsplit("/", 1)[-1]
    response = client.get(f"/join/{token}", follow_redirects=False)
    assert response.status_code == 303
    return token


def test_guest_surface_requires_session() -> None:
    with _client() as client:
        assert client.get("/guest").status_code == 401
        assert client.get("/api/guest/state").status_code == 401
        assert client.get("/_app/example.js").status_code == 200


def test_invite_is_one_use_and_enables_only_guest_capabilities() -> None:
    with _client() as client:
        token = _join(client)
        assert client.get(f"/join/{token}", follow_redirects=False).status_code == 404
        assert client.get("/guest").text == "guest-ui"
        assert client.get("/api/guest/state").json()["mode"] == "social"
        assert client.post("/api/guest/sonos/play").status_code == 200
        assert client.post("/api/sonos/pause").status_code == 404
        assert client.get("/health").status_code == 404


def test_revoke_invalidates_active_session() -> None:
    with _client() as client:
        _join(client)
        assert client.get("/guest").status_code == 200
        assert client.post("/internal/revoke").status_code == 200
        assert client.get("/guest").status_code == 401


def test_unlisted_guest_route_is_not_forwarded() -> None:
    with _client() as client:
        _join(client)
        assert client.get("/api/guest/status").status_code == 404
        assert client.post("/api/guest/revoke").status_code == 404
        assert client.put("/api/guest/scene/party").status_code == 405


def test_forwarding_prefixes_reject_encoded_dot_segment_escape() -> None:
    with _client() as client:
        assert client.get("/_app/%2e%2e/api/camera/snapshot").status_code == 404
        _join(client)
        assert client.get("/guest/%2e%2e/api/debug/query?sql=SELECT%201").status_code == 404
        assert client.get("/_app/%252e%252e/api/camera/snapshot").status_code == 404


def test_gateway_terminates_forwarded_client_identity_before_write_auth(monkeypatch) -> None:
    """Cloudflare client-IP headers must not leak into the trusted loopback hop."""
    monkeypatch.setattr("backend.api.auth.settings.HOME_HUB_API_KEY", "test-api-key")

    upstream = FastAPI()

    @upstream.post("/api/guest/sonos/play", dependencies=[Depends(require_api_key)])
    async def protected_guest_write() -> dict:
        return {"status": "ok"}

    proxied_upstream = ProxyHeadersMiddleware(upstream, trusted_hosts="*")
    transport = httpx.ASGITransport(
        app=proxied_upstream,
        client=("127.0.0.1", 12345),
    )
    app = create_app(
        public_url="https://guest.example.test",
        invite_ttl=60,
        session_ttl=600,
        client_transport=transport,
    )

    with TestClient(app, base_url="https://guest.example.test") as client:
        _join(client)
        response = client.post(
            "/api/guest/sonos/play",
            headers={
                "X-Forwarded-For": "8.8.8.8",
                "X-Forwarded-Proto": "https",
                "CF-Connecting-IP": "8.8.8.8",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
