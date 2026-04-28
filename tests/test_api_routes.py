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

    def test_weather_returns_200_or_unavailable(self, client):
        resp = client.get("/api/weather")
        # 200 if NWS fetch succeeded, 502 if upstream failed (CI network),
        # 503 if the service is not initialized at all.
        assert resp.status_code in (200, 502, 503)


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

    def test_status_returns_200_or_503(self, client):
        resp = client.get("/api/sonos/status")
        # 200 if Sonos on network, 503 if not (CI has no speaker)
        assert resp.status_code in (200, 503)

    def test_favorites_returns_200_or_503(self, client):
        resp = client.get("/api/sonos/favorites")
        assert resp.status_code in (200, 503)


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


# ---------------------------------------------------------------------------
# Learning — predictor promote gate
# ---------------------------------------------------------------------------

class TestPredictorPromoteGate:
    """Verify /api/learning/predictor/promote refuses degenerate models.

    Background: 2026-04-27 the LightGBM predictor collapsed to a single
    output class (`away` 898/898). The gate inspects recent shadow
    predictions before allowing promotion; a retrain that produces
    diverse outputs unblocks it automatically.

    Localhost requests bypass `require_api_key` so no header is sent.
    The TestClient hits the real on-disk DB, which holds production
    `decision_source='ml'` rows. Whatever the row distribution looks
    like at test time, it should be either degenerate (gate fires 409)
    or diverse (gate passes, would attempt promote — see below).
    """

    def test_returns_409_or_short_circuits(self, client):
        bp = getattr(client.app.state, "behavioral_predictor", None)
        if bp is None:
            pytest.skip("behavioral_predictor not initialized (lightgbm missing?)")

        # If the predictor is already active, the route short-circuits before
        # the gate. Demote to ensure we exercise the gate path.
        original_status = bp._status
        if original_status == "active":
            try:
                bp.demote()
            except Exception:
                pytest.skip("could not force-demote predictor for gate test")

        try:
            resp = client.post("/api/learning/predictor/promote")
            # Two healthy outcomes: gate fires (409) on degenerate data, or
            # gate passes (200) on diverse data and the promote runs.
            # Anything else (5xx, 400) means the gate is broken.
            assert resp.status_code in (200, 409), resp.text
            if resp.status_code == 409:
                detail = resp.json()["detail"]
                assert detail["error"] == "predictor_degenerate"
                assert "diagnostics" in detail
                diag = detail["diagnostics"]
                # Diagnostics carry the sample-distribution breakdown.
                for key in ("total", "unique_modes", "top_mode_share", "reason"):
                    assert key in diag
        finally:
            # Restore the predictor state we found, regardless of outcome.
            if original_status == "active" and bp._status != "active":
                try:
                    bp.promote()
                except Exception:
                    pass
            elif original_status == "shadow" and bp._status != "shadow":
                try:
                    bp.demote()
                except Exception:
                    pass
