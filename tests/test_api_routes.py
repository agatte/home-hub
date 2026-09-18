"""
Tests for API route endpoints beyond /health and /api/lights.

Uses TestClient with the real app lifespan. Tests verify response
structure rather than exact values since real hardware may not be
connected in CI.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.weather_service import WeatherService


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

    def test_unconfigured_weather_routes_return_503(self, client):
        previous = app.state.weather_service
        app.state.weather_service = WeatherService()
        try:
            for path in ("/api/weather", "/api/weather/alerts"):
                resp = client.get(path)
                assert resp.status_code == 503
                assert resp.json()["detail"] == "Weather service not configured"
        finally:
            app.state.weather_service = previous


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
        assert "house_state" in data
        assert "activity" in data
        assert "manual_override" in data
        assert "override_source" in data
        assert "override_user_owned" in data

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

    def test_music_taste_returns_read_only_summary(self, client):
        resp = client.get("/api/music/taste?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["entity_counts"]) == {"artists", "tracks", "favorites"}
        assert "top_artists" in data
        assert "top_favorites" in data

    def test_discovery_status_is_shadow_only(self, client):
        resp = client.get("/api/music/discovery/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["shadow"] is True
        assert data["actuation_allowed"] is False
        assert set(data["policies"]) == {"gentle", "explore"}

    def test_discovery_preview_returns_fake_explainable_clusters(self, client):
        previous = app.state.music_discovery

        class FakeResult:
            def to_dict(self):
                return {
                    "status": "shadow_ready",
                    "shadow": True,
                    "actuation_allowed": False,
                    "policy": "explore",
                    "clusters": [{
                        "artist_name": "New Artist",
                        "artist_depth": 2,
                        "novelty_ratio": 1.0,
                        "reasons": ["taste-adjacent"],
                        "tracks": [{"track_name": "New Song"}],
                    }],
                }

        class FakeDiscovery:
            async def preview(self, mode, *, policy, count, tracks_per_artist, intent=None):
                assert mode == "gaming"
                assert policy == "explore"
                assert count == 4
                assert tracks_per_artist == 2
                return FakeResult()

        app.state.music_discovery = FakeDiscovery()
        try:
            resp = client.post(
                "/api/music/discovery/preview?mode=gaming&policy=explore&count=4&tracks_per_artist=2&intent=valheim"
            )
        finally:
            app.state.music_discovery = previous

        assert resp.status_code == 200
        data = resp.json()
        assert data["shadow"] is True
        assert data["actuation_allowed"] is False
        assert data["clusters"][0]["artist_name"] == "New Artist"
        assert data["clusters"][0]["tracks"][0]["track_name"] == "New Song"

    def test_discovery_feedback_persists_explicit_event_only(self, client):
        previous = app.state.music_feedback
        calls = []

        class FakeFeedback:
            async def record(self, **kwargs):
                calls.append(kwargs)
                return ({"id": 9, **kwargs}, False)

        app.state.music_feedback = FakeFeedback()
        try:
            resp = client.post(
                "/api/music/discovery/feedback",
                json={
                    "client_event_id": "event-ui-1",
                    "action": "fits_me",
                    "target_kind": "artist",
                    "artist_name": "Wardruna",
                    "provider": "itunes_search",
                    "provider_id": "123",
                    "mode": "gaming",
                    "policy": "explore",
                    "intent": "Valheim",
                },
            )
        finally:
            app.state.music_feedback = previous

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["duplicate"] is False
        assert calls[0]["action"] == "fits_me"
        assert calls[0]["artist_name"] == "Wardruna"
        assert calls[0]["source"] == "dashboard:music_discovery"

    def test_live_music_context_status_is_shadow_only(self, client):
        previous = app.state.music_live_context

        class FakeLiveContext:
            async def status(self):
                return {
                    "status": "active", "consumer": "gaming",
                    "semantic_request": "valheim", "shadow": True,
                    "actuation_allowed": False,
                }

        app.state.music_live_context = FakeLiveContext()
        try:
            resp = client.get("/api/music/live-context/status")
        finally:
            app.state.music_live_context = previous
        assert resp.status_code == 200
        assert resp.json()["semantic_request"] == "valheim"
        assert resp.json()["actuation_allowed"] is False

    def test_live_music_context_preview_delegates_without_actuation(self, client):
        previous = app.state.music_live_context

        class FakeLiveContext:
            async def preview(self, *, policy, count, tracks_per_artist):
                assert policy == "explore"
                assert count == 4
                assert tracks_per_artist == 2
                return {
                    "status": "shadow_ready", "shadow": True,
                    "actuation_allowed": False,
                    "live_context": {"consumer": "gaming", "semantic_request": "valheim"},
                    "discovery": {"clusters": []},
                }

        app.state.music_live_context = FakeLiveContext()
        try:
            resp = client.post(
                "/api/music/live-context/preview?policy=explore&count=4&tracks_per_artist=2"
            )
        finally:
            app.state.music_live_context = previous
        assert resp.status_code == 200
        data = resp.json()
        assert data["shadow"] is True
        assert data["actuation_allowed"] is False
        assert data["live_context"]["semantic_request"] == "valheim"

    def test_music_request_status_is_shadow_only(self, client):
        previous = app.state.music_requests

        class FakeRequests:
            def status(self):
                return {
                    "shadow": True, "actuation_allowed": False,
                    "supported_kinds": ["familiar", "discovery", "mood", "recommendation"],
                }

        app.state.music_requests = FakeRequests()
        try:
            resp = client.get("/api/music/request/status")
        finally:
            app.state.music_requests = previous
        assert resp.status_code == 200
        assert resp.json()["actuation_allowed"] is False
        assert "familiar" in resp.json()["supported_kinds"]

    def test_music_request_preview_preserves_source_and_structured_contract(self, client):
        previous = app.state.music_requests
        calls = []

        class FakeResult:
            def to_dict(self):
                return {
                    "status": "shadow_ready", "shadow": True,
                    "actuation_allowed": False,
                    "resolved_request": {"kind": "discovery", "policy": "explore"},
                    "familiar_suggestions": [], "discovery": {"clusters": []},
                }

        class FakeRequests:
            async def preview(self, music_request, *, count, tracks_per_artist):
                calls.append((music_request, count, tracks_per_artist))
                return FakeResult()

        app.state.music_requests = FakeRequests()
        try:
            resp = client.post(
                "/api/music/request/preview",
                headers={"X-HomeHub-Source": "test:command"},
                json={
                    "request": "play new music", "mode": "gaming",
                    "count": 4, "tracks_per_artist": 2,
                },
            )
        finally:
            app.state.music_requests = previous
        assert resp.status_code == 200
        music_request, count, tracks_per_artist = calls[0]
        assert music_request.request_text == "play new music"
        assert music_request.mode == "gaming"
        assert music_request.source == "test:command"
        assert count == 4
        assert tracks_per_artist == 2
        assert resp.json()["actuation_allowed"] is False

    def test_music_assisted_playback_status_is_explicit_only(self, client):
        previous = app.state.music_assisted_playback

        class FakeAssisted:
            def status(self):
                return {
                    "enabled": True,
                    "explicit_only": True,
                    "actuation_allowed": True,
                    "autonomous_context_playback": False,
                    "supported_adapters": ["sonos_apple_music_share_link"],
                }

        app.state.music_assisted_playback = FakeAssisted()
        try:
            resp = client.get("/api/music/assisted-playback/status")
        finally:
            app.state.music_assisted_playback = previous
        assert resp.status_code == 200
        data = resp.json()
        assert data["explicit_only"] is True
        assert data["actuation_allowed"] is True
        assert data["autonomous_context_playback"] is False

    def test_music_assisted_playback_preserves_exact_identity_and_source(self, client):
        previous = app.state.music_assisted_playback
        calls = []

        class FakeAssisted:
            async def play_exact(self, **kwargs):
                calls.append(kwargs)
                return {
                    "status": "played",
                    "reason": "explicit_approved_candidate",
                    "duplicate": False,
                    "explicit_only": True,
                    "provider": kwargs["provider"],
                    "provider_id": kwargs["provider_id"],
                }

        app.state.music_assisted_playback = FakeAssisted()
        try:
            resp = client.post(
                "/api/music/assisted-playback",
                headers={"X-HomeHub-Source": "test:music_play"},
                json={
                    "client_event_id": "play-api-1",
                    "provider": "itunes_search",
                    "provider_id": "1713833576",
                },
            )
        finally:
            app.state.music_assisted_playback = previous
        assert resp.status_code == 200
        assert resp.json()["status"] == "played"
        assert calls == [{
            "client_event_id": "play-api-1",
            "provider": "itunes_search",
            "provider_id": "1713833576",
            "source": "test:music_play",
        }]

    def test_music_assisted_playback_rejects_non_object_json(self, client):
        previous = app.state.music_assisted_playback
        calls = []

        class FakeAssisted:
            async def play_exact(self, **kwargs):
                calls.append(kwargs)
                return {"status": "played"}

        app.state.music_assisted_playback = FakeAssisted()
        try:
            resp = client.post("/api/music/assisted-playback", json=["not", "an", "object"])
        finally:
            app.state.music_assisted_playback = previous
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Request body must be a JSON object"
        assert calls == []

    def test_music_assisted_playback_rejects_malformed_json(self, client):
        previous = app.state.music_assisted_playback
        app.state.music_assisted_playback = object()
        try:
            resp = client.post(
                "/api/music/assisted-playback",
                content=b"{",
                headers={"Content-Type": "application/json"},
            )
        finally:
            app.state.music_assisted_playback = previous
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Request body must be valid JSON"

    def test_music_trust_approval_is_shadow_only_and_provider_qualified(self, client):
        previous = app.state.music_requests
        calls = []

        class FakeRequests:
            async def record_trust_event(self, **kwargs):
                calls.append(kwargs)
                return {
                    "status": "ok",
                    "shadow": True,
                    "actuation_allowed": False,
                    "current_approval_action": kwargs["action"],
                    "trust": {
                        "state": "approved",
                        "playback_eligible": True,
                        "explicit_approval": True,
                        "reasons": ["explicit approval for this exact provider identity"],
                    },
                }

        app.state.music_requests = FakeRequests()
        try:
            resp = client.post(
                "/api/music/trust/approval",
                headers={"X-HomeHub-Source": "test:music_trust"},
                json={
                    "client_event_id": "trust-api-1",
                    "action": "approve",
                    "provider": "sonos_favorite",
                    "provider_id": "fav-1",
                },
            )
        finally:
            app.state.music_requests = previous

        assert resp.status_code == 200
        data = resp.json()
        assert data["shadow"] is True
        assert data["actuation_allowed"] is False
        assert data["trust"]["state"] == "approved"
        assert calls == [{
            "client_event_id": "trust-api-1",
            "action": "approve",
            "provider": "sonos_favorite",
            "provider_id": "fav-1",
            "source": "test:music_trust",
        }]

    def test_curator_status_is_shadow_only(self, client):
        resp = client.get("/api/music/curator/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["shadow"] is True
        assert data["actuation_allowed"] is False
        assert set(data["supported_modes"]) == {"gameday", "gaming", "social"}

    def test_curator_preview_rejects_unsupported_mode_without_model_call(self, client):
        resp = client.post("/api/music/curator/preview?mode=working")
        assert resp.status_code == 400
        assert "Unsupported curator mode" in resp.json()["detail"]

    def test_curator_preview_returns_fake_shadow_result(self, client):
        previous = app.state.music_curator

        class FakeResult:
            def to_dict(self):
                return {
                    "status": "shadow_ready",
                    "shadow": True,
                    "actuation_allowed": False,
                    "suggestions": [{"candidate": {"title": "Verified Favorite"}}],
                }

        class FakeCurator:
            supported_modes = ("gameday", "social")

            def supports_mode(self, mode):
                return mode in self.supported_modes

            async def preview(self, mode, *, limit):
                assert mode == "gameday"
                assert limit == 3
                return FakeResult()

        app.state.music_curator = FakeCurator()
        try:
            resp = client.post("/api/music/curator/preview?mode=gameday&limit=3")
        finally:
            app.state.music_curator = previous

        assert resp.status_code == 200
        data = resp.json()
        assert data["shadow"] is True
        assert data["actuation_allowed"] is False
        assert data["suggestions"][0]["candidate"]["title"] == "Verified Favorite"


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


# ---------------------------------------------------------------------------
# Bedroom lux channel (D4 Part C) — store-only endpoints
# ---------------------------------------------------------------------------

class TestBedroomLuxAPI:
    """The /api/camera/desktop/lux store. In-memory channel only — these
    tests deliberately avoid the calibration POST, which writes to the
    shared on-disk settings DB."""

    def test_get_lux_status_shape(self, client):
        resp = client.get("/api/camera/desktop/lux")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["room"] == "bedroom"
        for k in ("ema_lux", "baseline_lux", "calibrated", "last_update"):
            assert k in body

    def test_post_lux_lands_a_reading(self, client):
        r = client.post("/api/camera/desktop/lux", json={"ambient_lux": 42.5})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # The raw smoothed value is observable even before calibration.
        got = client.get("/api/camera/desktop/lux").json()
        assert got["ema_lux"] is not None

    def test_post_lux_rejects_out_of_range(self, client):
        r = client.post("/api/camera/desktop/lux", json={"ambient_lux": 999})
        assert r.status_code == 422  # > 255 fails the Field(le=255) bound

    def test_get_calibrate_pending_shape(self, client):
        # Read-only flag poll (the POST .../calibrate/request writes the shared
        # settings DB, so it's exercised live rather than here).
        resp = client.get("/api/camera/desktop/lux/calibrate/pending")
        assert resp.status_code == 200
        assert isinstance(resp.json().get("pending"), bool)

    def test_get_calibration_config_shape(self, client):
        # Read-only — the agent loads `exposure` from here (Part A). Returns
        # {} when uncalibrated, or the persisted config dict.
        resp = client.get("/api/camera/desktop/lux/calibration")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


def test_music_catalog_status_is_read_only_and_requires_no_second_credential(client):
    previous_apple = app.state.music_apple_catalog
    previous_sonos = app.state.sonos

    class FakeAppleCatalog:
        def status(self):
            return {
                "provider": "itunes_search",
                "service": "Apple Music",
                "sonos_available": True,
                "credentials_required": False,
                "playback_adapter": "sonos_apple_music_share_link",
                "playback_verified": False,
                "verification_state": "queue_test_required",
                "actuation_allowed": False,
            }

    app.state.music_apple_catalog = FakeAppleCatalog()
    app.state.sonos = type("Sonos", (), {"connected": True})()
    try:
        response = client.get("/api/music/catalog/status")
    finally:
        app.state.music_apple_catalog = previous_apple
        app.state.sonos = previous_sonos

    assert response.status_code == 200
    data = response.json()
    assert data["shadow"] is True
    assert data["actuation_allowed"] is False
    apple = next(item for item in data["providers"] if item["provider"] == "itunes_search")
    assert apple["credentials_required"] is False
    assert apple["playback_adapter"] == "sonos_apple_music_share_link"
    assert apple["playback_verified"] is False
    assert apple["verification_state"] == "queue_test_required"
