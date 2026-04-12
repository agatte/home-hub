"""
Tests for the /health endpoint and basic API routing.

Note: TestClient runs the real lifespan which connects to actual Hue/Sonos
on the dev machine. Tests verify response structure rather than exact values.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    """Shared TestClient — lifespan runs once for the module."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestHealthEndpoint:
    """Verify /health returns correct structure and status."""

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_structure(self, client):
        data = client.get("/health").json()
        assert "status" in data
        assert "devices" in data
        assert "hue_bridge" in data["devices"]
        assert "sonos" in data["devices"]
        assert "websocket_clients" in data

    def test_health_devices_are_booleans(self, client):
        data = client.get("/health").json()
        assert isinstance(data["devices"]["hue_bridge"], bool)
        assert isinstance(data["devices"]["sonos"], bool)


class TestLightsAPI:
    """Basic smoke tests for /api/lights."""

    def test_get_lights_returns_list(self, client):
        resp = client.get("/api/lights")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_lights_have_expected_fields(self, client):
        resp = client.get("/api/lights")
        data = resp.json()
        if data:  # Only check if lights are reachable
            light = data[0]
            assert "name" in light
            assert "on" in light
            assert "bri" in light


class TestCORS:
    """Verify CORS is locked down to specific origins."""

    def test_allowed_origin(self, client):
        resp = client.options(
            "/api/lights",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8000"

    def test_disallowed_origin(self, client):
        resp = client.options(
            "/api/lights",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Should NOT have the evil origin in the allow header
        allow_origin = resp.headers.get("access-control-allow-origin", "")
        assert "evil.com" not in allow_origin
