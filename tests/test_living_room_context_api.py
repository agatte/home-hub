"""Read-only API consistency and health behavior for the living-room gate."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.auth import require_api_key
from backend.api.routes import automation, health


ENVELOPE = {
    "shadow_only": True,
    "snapshot": {
        "version": "living_room_capability_snapshot.v1",
        "evaluated_at": "2026-08-01T20:00:00+00:00",
    },
    "decision": {
        "version": "living_room_decision_context.v1",
        "outcome": "degraded_skip",
        "reason_codes": ["authoritative_living_room_absent"],
        "scene_selected": False,
        "actuation_attempted": False,
        "actuation_outcome": "not_attempted",
    },
}

RECOVERED_ENVELOPE = {
    **ENVELOPE,
    "decision": {
        **ENVELOPE["decision"],
        "outcome": "eligible",
        "reason_codes": [],
    },
}


class FakeGate:
    def __init__(self) -> None:
        self.evaluate_calls = 0
        self.history_limits: list[int] = []
        self.malfunction = False
        self.recovered = False

    def _envelope(self):
        return RECOVERED_ENVELOPE if self.recovered else ENVELOPE

    def current_envelope(self):
        return self._envelope()

    def current_status(self):
        return {
            **self._envelope(),
            "evaluator_age_seconds": 2.0,
            "persistence_health": {"status": "healthy"},
        }

    async def history(self, limit: int):
        self.history_limits.append(limit)
        return [
            {
                "id": i,
                "evaluated_at": f"2026-08-01T20:{60 - i:02d}:00+00:00",
                **self._envelope(),
            }
            for i in range(1, min(limit, 3) + 1)
        ]

    def health_summary(self):
        envelope = self._envelope()
        return {
            "status": "degraded" if self.malfunction else "healthy",
            "shadow_only": True,
            "outcome": envelope["decision"]["outcome"],
            "reason_codes": envelope["decision"]["reason_codes"],
            "evaluator_age_seconds": 2.0,
            "evaluator_error": "RuntimeError" if self.malfunction else None,
            "persistence": {
                "status": "degraded" if self.malfunction else "healthy"
            },
        }


class FakeEngine:
    pipeline_history = []
    current_mode = "idle"
    mode_source = "time"
    last_weather_class = None
    last_lux_multiplier = 1.0

    def _build_pipeline_state(self):
        return {"timestamp": "held-pipeline-state"}

    def get_living_room_atmosphere_status(self):
        return {
            "enabled": False,
            "selected_atmosphere": "moss_ember",
            "reason_codes": ["feature_disabled"],
            "application": {
                "state": "fallback",
                "reason": "feature_disabled",
            },
        }

    async def get_living_room_atmosphere_history(self, limit: int):
        return [{"atmosphere_id": "moss_ember", "limit_seen": limit}]


def _client() -> tuple[TestClient, FakeGate]:
    app = FastAPI()
    app.include_router(automation.router)
    app.include_router(health.router)
    app.dependency_overrides[require_api_key] = lambda: None
    gate = FakeGate()
    app.state.living_room_decision_gate = gate
    app.state.automation = FakeEngine()
    return TestClient(app), gate


def test_current_and_pipeline_return_same_stored_envelope_without_recompute() -> None:
    client, gate = _client()
    current = client.get("/api/automation/living-room-context")
    pipeline = client.get("/api/automation/pipeline")
    assert current.status_code == 200
    assert pipeline.status_code == 200
    current_envelope = {
        "shadow_only": current.json()["shadow_only"],
        "snapshot": current.json()["snapshot"],
        "decision": current.json()["decision"],
        "atmosphere": current.json()["atmosphere"],
    }
    pipeline_envelope = pipeline.json()["living_room_context"]
    assert current_envelope == pipeline_envelope
    assert current_envelope["shadow_only"] is True
    assert pipeline_envelope["shadow_only"] is True
    assert current_envelope["decision"]["scene_selected"] is False
    assert current_envelope["decision"]["actuation_attempted"] is False
    assert current_envelope["decision"]["actuation_outcome"] == "not_attempted"
    assert current_envelope["atmosphere"]["selected_atmosphere"] == "moss_ember"
    assert gate.evaluate_calls == 0


def test_current_includes_evaluator_age_and_persistence_health() -> None:
    client, _gate = _client()
    body = client.get("/api/automation/living-room-context").json()
    assert body["evaluator_age_seconds"] == 2.0
    assert body["persistence_health"]["status"] == "healthy"


def test_history_defaults_to_50_and_is_bounded_to_100() -> None:
    client, gate = _client()
    response = client.get("/api/automation/living-room-context/history")
    assert response.status_code == 200
    assert gate.history_limits == [50]
    records = response.json()["records"]
    assert records[0]["id"] == 1
    assert response.json()["atmosphere_records"] == [
        {"atmosphere_id": "moss_ember", "limit_seen": 50}
    ]

    accepted = client.get(
        "/api/automation/living-room-context/history?limit=100"
    )
    assert accepted.status_code == 200
    rejected = client.get(
        "/api/automation/living-room-context/history?limit=101"
    )
    assert rejected.status_code == 422
    rejected_low = client.get(
        "/api/automation/living-room-context/history?limit=0"
    )
    assert rejected_low.status_code == 422


def test_normal_degraded_decision_does_not_degrade_backend_health() -> None:
    client, gate = _client()
    gate.malfunction = False
    body = client.get("/health").json()
    assert body["status"] == "healthy"
    assert body["living_room_decision_gate"]["outcome"] == "degraded_skip"


def test_evaluator_or_recorder_malfunction_degrades_health() -> None:
    client, gate = _client()
    gate.malfunction = True
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["living_room_decision_gate"]["status"] == "degraded"
    assert "living_room_decision_gate" in body["details"]


def test_recovered_current_pipeline_health_and_history_agree() -> None:
    client, gate = _client()
    gate.recovered = True

    current = client.get("/api/automation/living-room-context").json()
    pipeline = client.get("/api/automation/pipeline").json()
    health_body = client.get("/health").json()
    history = client.get(
        "/api/automation/living-room-context/history?limit=1"
    ).json()["records"]

    current_envelope = {
        "shadow_only": current["shadow_only"],
        "snapshot": current["snapshot"],
        "decision": current["decision"],
        "atmosphere": current["atmosphere"],
    }
    assert current_envelope == pipeline["living_room_context"]
    assert history[0]["snapshot"] == current["snapshot"]
    assert history[0]["decision"] == current["decision"]
    assert current["persistence_health"]["status"] == "healthy"
    gate_health = health_body["living_room_decision_gate"]
    assert gate_health["status"] == "healthy"
    assert gate_health["outcome"] == "eligible"
    assert gate_health["reason_codes"] == []
