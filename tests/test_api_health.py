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


class TestHealthTaskHeartbeats:
    """Verify the background-task heartbeat surface on /health."""

    def test_tasks_block_present(self, client):
        data = client.get("/health").json()
        assert "tasks" in data
        assert "tasks_stale" in data
        assert isinstance(data["tasks"], list)
        assert isinstance(data["tasks_stale"], list)

    def test_each_task_row_has_expected_shape(self, client):
        data = client.get("/health").json()
        if not data["tasks"]:
            pytest.skip("No heartbeats registered — likely a partial lifespan")
        row = data["tasks"][0]
        assert "name" in row and isinstance(row["name"], str)
        assert "interval_seconds" in row and isinstance(row["interval_seconds"], (int, float))
        assert "age_seconds" in row and isinstance(row["age_seconds"], (int, float))
        assert "stale" in row and isinstance(row["stale"], bool)

    def test_clean_startup_is_healthy(self, client):
        data = client.get("/health").json()
        assert data["status"] == "healthy"
        assert data["tasks_stale"] == []

    def test_backdated_tick_flips_to_degraded(self, client):
        # Backdate one task's heartbeat past the staleness threshold and
        # confirm /health flips to "degraded" with the task listed.
        from datetime import datetime, timedelta, timezone

        registry = app.state.heartbeats
        # Pick whatever's registered — we don't care which.
        snap = registry.snapshot()
        if not snap:
            pytest.skip("No heartbeats registered")
        target = snap[0]["name"]
        original = registry._beats[target].last_tick
        try:
            # 10x the interval ago — well past the 2x threshold.
            registry._beats[target].last_tick = (
                datetime.now(timezone.utc)
                - timedelta(seconds=snap[0]["interval_seconds"] * 10)
            )
            data = client.get("/health").json()
            assert data["status"] == "degraded"
            assert target in data["tasks_stale"]
            # Status is degraded but HTTP is still 200 — Uptime Kuma's
            # existing HTTP probe must keep working.
        finally:
            registry._beats[target].last_tick = original

        # Cleanup leaves us healthy again.
        recovered = client.get("/health").json()
        assert recovered["status"] == "healthy"
        assert recovered["tasks_stale"] == []


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
