"""
Tests for API route endpoints beyond /health and /api/lights.

Uses TestClient with the real app lifespan. Tests verify response
structure rather than exact values since real hardware may not be
connected in CI.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    """Shared TestClient — lifespan runs once for the module."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

class TestWeatherAPI:
    """Verify /api/weather endpoint."""

    def test_weather_returns_200_or_data(self, client):
        resp = client.get("/api/weather")
        # May return null if no API key configured, but should not 500
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------

class TestAutomationAPI:
    """Verify /api/automation endpoints."""

    def test_status_returns_mode(self, client):
        resp = client.get("/api/automation/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "current_mode" in data
        assert "mode_source" in data
        assert "manual_override" in data

    def test_config_returns_200(self, client):
        resp = client.get("/api/automation/config")
        assert resp.status_code == 200

    def test_schedule_returns_200(self, client):
        resp = client.get("/api/automation/schedule")
        assert resp.status_code == 200

    def test_mode_brightness_returns_200(self, client):
        resp = client.get("/api/automation/mode-brightness")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------

class TestScenesAPI:
    """Verify /api/scenes endpoints."""

    def test_scenes_returns_list(self, client):
        resp = client.get("/api/scenes")
        assert resp.status_code == 200
        data = resp.json()
        assert "scenes" in data
        assert isinstance(data["scenes"], list)

    def test_effects_returns_list(self, client):
        resp = client.get("/api/scenes/effects")
        assert resp.status_code == 200
        data = resp.json()
        # May be wrapped in {"effects": [...]} or be a direct list
        if isinstance(data, dict):
            assert "effects" in data
        else:
            assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Sonos
# ---------------------------------------------------------------------------

class TestSonosAPI:
    """Verify /api/sonos endpoints."""

    def test_status_returns_structure(self, client):
        resp = client.get("/api/sonos/status")
        assert resp.status_code == 200
        data = resp.json()
        # May be empty dict if Sonos not connected
        assert isinstance(data, dict)

    def test_favorites_returns_structure(self, client):
        resp = client.get("/api/sonos/favorites")
        assert resp.status_code == 200
        data = resp.json()
        if isinstance(data, dict):
            assert "favorites" in data
            assert isinstance(data["favorites"], list)
        else:
            assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------

class TestMusicAPI:
    """Verify /api/music endpoints."""

    def test_mode_playlists_returns_dict(self, client):
        resp = client.get("/api/music/mode-playlists")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Routines
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class TestEventsAPI:
    """Verify /api/events endpoints."""

    def test_summary_returns_structure(self, client):
        resp = client.get("/api/events/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "activity" in data
        assert "lights" in data
        assert "sonos" in data
        assert "scenes" in data

    def test_activity_returns_paginated(self, client):
        resp = client.get("/api/events/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "events" in data

    def test_patterns_returns_structure(self, client):
        resp = client.get("/api/events/patterns")
        assert resp.status_code == 200
        data = resp.json()
        assert "by_hour" in data
        assert "overrides" in data

    def test_timeline_returns_events(self, client):
        resp = client.get("/api/events/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data


# ---------------------------------------------------------------------------
# Routines
# ---------------------------------------------------------------------------

class TestRoutinesAPI:
    """Verify /api/routines endpoint."""

    def test_routines_returns_structure(self, client):
        resp = client.get("/api/routines")
        assert resp.status_code == 200
        data = resp.json()
        if isinstance(data, dict):
            assert "routines" in data
            assert isinstance(data["routines"], list)
        else:
            assert isinstance(data, list)
