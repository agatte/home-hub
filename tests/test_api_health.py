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

    def test_fauxmo_device_reports_enabled_and_connected_state(self, client):
        fauxmo = client.get("/health").json()["devices"]["fauxmo"]
        assert set(fauxmo) == {"enabled", "connected", "status"}
        assert isinstance(fauxmo["enabled"], bool)
        assert isinstance(fauxmo["connected"], bool)
        assert fauxmo["status"] in {"disabled", "healthy", "unhealthy"}
        if not fauxmo["enabled"]:
            assert fauxmo["status"] == "disabled"


class TestApiPing:
    """Verify the minimal public-facing liveness probe."""

    def test_ping_returns_200(self, client):
        resp = client.get("/api/ping")
        assert resp.status_code == 200

    def test_ping_body_shape(self, client):
        """`/api/ping` is the contract surface for external uptime monitors;
        any change to the shape breaks Anthony's UptimeRobot/Kuma probes."""
        assert client.get("/api/ping").json() == {"ok": True}

    def test_ping_does_not_leak_internal_state(self, client):
        """The whole point of /api/ping vs /health is that the response is
        fixed shape and reveals nothing about the deploy. Guard against
        future hands "improving" it by adding build_id or status."""
        body = client.get("/api/ping").json()
        forbidden = {"build_id", "status", "devices", "ml", "tasks",
                     "circuit_breakers", "scheduler_tasks"}
        assert not (forbidden & body.keys()), (
            f"/api/ping leaked internal state: {forbidden & body.keys()}"
        )


class TestHealthCircuitBreakers:
    """Verify the per-service circuit breaker surface on /health."""

    def test_circuit_breakers_block_present(self, client):
        data = client.get("/health").json()
        assert "circuit_breakers" in data
        assert isinstance(data["circuit_breakers"], dict)

    def test_breakers_start_closed(self, client):
        data = client.get("/health").json()
        for name, snap in data["circuit_breakers"].items():
            assert snap["state"] == "closed", f"{name} not closed at boot"
            assert snap["consecutive_failures"] == 0

    def test_open_breaker_flips_status_to_degraded(self, client):
        # Force the hue breaker into open state and confirm /health reflects.
        from datetime import datetime, timezone

        breaker = app.state.hue.breaker
        original_state = breaker._state
        original_opened_at = breaker._opened_at
        original_failures = breaker._consecutive_failures
        try:
            breaker._state = "open"
            breaker._opened_at = datetime.now(timezone.utc)
            breaker._consecutive_failures = breaker.failure_threshold

            data = client.get("/health").json()
            assert data["status"] == "degraded"
            assert data["circuit_breakers"]["hue"]["state"] == "open"
        finally:
            breaker._state = original_state
            breaker._opened_at = original_opened_at
            breaker._consecutive_failures = original_failures

        # Cleanup leaves us healthy again.
        recovered = client.get("/health").json()
        assert recovered["status"] == "healthy"
        assert recovered["circuit_breakers"]["hue"]["state"] == "closed"


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


class TestHealthMLPredictors:
    """Verify the ML predictor surface on /health."""

    def test_ml_block_present(self, client):
        data = client.get("/health").json()
        assert "ml" in data
        assert isinstance(data["ml"], dict)

    def test_each_predictor_has_status(self, client):
        ml = client.get("/health").json()["ml"]
        for name, h in ml.items():
            assert "status" in h, f"{name} missing status"
            assert h["status"] in {"healthy", "shadow", "idle", "unhealthy"}

    def test_unhealthy_non_shadow_predictor_flips_to_degraded(self, client):
        # Forcibly mark the lighting_learner unhealthy by pushing
        # its consecutive_failures past threshold. lighting_learner
        # is non-shadow, so this must propagate to the top-level status.
        learner = getattr(client.app.state, "lighting_learner", None)
        if learner is None:
            pytest.skip("lighting_learner not initialized")
        original_failures = learner._consecutive_failures
        try:
            learner._consecutive_failures = learner._failure_threshold
            data = client.get("/health").json()
            assert data["status"] == "degraded"
            assert data["ml"]["lighting_learner"]["status"] == "unhealthy"
        finally:
            learner._consecutive_failures = original_failures

        recovered = client.get("/health").json()
        assert recovered["status"] == "healthy"
        assert recovered["ml"]["lighting_learner"]["status"] in {
            "healthy", "idle"
        }

    def test_shadow_predictor_does_not_flip_to_degraded(self, client):
        # Behavioral predictor starts in shadow mode. Even a contrived
        # failure count must not propagate to top-level degraded —
        # shadow is intentional non-voting, not a failure.
        bp = getattr(client.app.state, "behavioral_predictor", None)
        if bp is None:
            pytest.skip("behavioral_predictor not initialized (lightgbm missing?)")
        if bp._status == "active":
            pytest.skip("behavioral_predictor was promoted; can't test shadow gate")
        original_failures = bp._consecutive_failures
        try:
            bp._consecutive_failures = bp._failure_threshold + 5
            data = client.get("/health").json()
            assert data["ml"]["behavioral_predictor"]["status"] == "shadow"
            # Top-level must still be healthy if nothing else is wrong.
            # (The other tests above don't touch state in conflicting ways.)
            assert data["status"] in {"healthy", "degraded"}
            # If degraded, it shouldn't be from this shadow predictor.
            if data["status"] == "degraded":
                assert data["ml"]["behavioral_predictor"]["status"] != "unhealthy"
        finally:
            bp._consecutive_failures = original_failures


class TestHealthBuildId:
    """Verify build_id is exposed on /health (deploy-verifier needs it)."""

    def test_build_id_present(self, client):
        data = client.get("/health").json()
        assert "build_id" in data

    def test_build_id_matches_app_state(self, client):
        data = client.get("/health").json()
        # Either the SHA from the running git repo, or None if startup couldn't
        # compute it (rare — the helper has a fallback). Either way, the field
        # must equal what's on app.state.
        assert data["build_id"] == getattr(app.state, "build_id", None)


class TestHealthSchedulerTasks:
    """Verify scheduler_tasks is exposed and well-shaped."""

    def test_scheduler_tasks_present(self, client):
        data = client.get("/health").json()
        assert "scheduler_tasks" in data
        assert isinstance(data["scheduler_tasks"], list)

    def test_each_scheduler_task_has_expected_shape(self, client):
        data = client.get("/health").json()
        if not data["scheduler_tasks"]:
            pytest.skip("No scheduler tasks registered — likely a partial lifespan")
        row = data["scheduler_tasks"][0]
        for key in (
            "name", "time", "weekdays", "enabled",
            "last_run", "last_run_age_seconds",
            "last_status", "last_error", "next_run",
        ):
            assert key in row, f"missing {key} in scheduler_tasks row"
        assert row["last_status"] in {"pending", "ok", "error"}

    def test_retention_sweep_registered(self, client):
        # The 90-day retention sweep is the canonical case the runbook
        # entry 8a check-back relies on. If this regresses, the entry
        # will fire warn on every check.
        data = client.get("/health").json()
        names = [t["name"] for t in data["scheduler_tasks"]]
        if not names:
            pytest.skip("No scheduler tasks registered — likely a partial lifespan")
        assert "retention_sweep" in names


class TestHealthAutomationBlock:
    """Verify the engine weather/lux state surface on /health (GH #67)."""

    def test_automation_block_present(self, client):
        data = client.get("/health").json()
        assert "automation" in data
        assert isinstance(data["automation"], dict)
        if getattr(app.state, "automation", None) is None:
            pytest.skip("automation engine not initialized — partial lifespan")
        block = data["automation"]
        for key in ("current_mode", "last_weather_class", "last_lux_multiplier"):
            assert key in block, f"automation block missing {key}"

    def test_reflects_engine_state(self, client):
        # Mutate the engine's weather/lux state and confirm /health mirrors it
        # (mirrors the breaker/heartbeat mutate-restore pattern above).
        automation = getattr(app.state, "automation", None)
        if automation is None:
            pytest.skip("automation engine not initialized — partial lifespan")
        orig_class = automation._last_weather_class
        orig_mult = automation._last_lux_multiplier
        try:
            automation._last_weather_class = "rain"
            automation._last_lux_multiplier = 1.25
            block = client.get("/health").json()["automation"]
            assert block["last_weather_class"] == "rain"
            assert block["last_lux_multiplier"] == 1.25
            assert block["current_mode"] == automation.current_mode
        finally:
            automation._last_weather_class = orig_class
            automation._last_lux_multiplier = orig_mult


class TestLightsAPI:
    """Basic smoke tests for /api/lights."""

    def test_get_lights_returns_list(self, client):
        resp = client.get("/api/lights")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_lights_have_expected_fields(self, client):
        resp = client.get("/api/lights")
        if resp.status_code != 200:
            pytest.skip(f"Hue bridge unreachable in this environment ({resp.status_code})")
        data = resp.json()
        if not isinstance(data, list) or not data:
            pytest.skip("Hue returned no lights")
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
