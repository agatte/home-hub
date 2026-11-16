"""REST single-fixture manual authority regression tests, fake devices only.

Exercises the real FastAPI endpoint + shared guarded Hue final-write fence.
No app lifespan, live Hue transport, host mode changes or physical writes.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api.auth import require_api_key
from backend.api.routes.lights import router
from tests.test_ws_manual_light_guard import Engine, Hue


@pytest.fixture
def simulated():
    engine = Engine()
    hue = Hue(engine)
    hue.breaker_open = False
    app = FastAPI()
    app.include_router(router)
    app.state.hue = hue
    app.state.automation = engine
    app.state.event_logger = None
    # The route remains protected by the real dependency. The fixture grants
    # test-only access to inspect behavior after authentication.
    app.dependency_overrides[require_api_key] = lambda: None
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, engine=engine, hue=hue, app=app)


def test_rest_brightness_uses_one_guarded_bulb_write_and_persists(simulated):
    reply = simulated.client.put("/api/lights/2", json={"bri": 101})
    assert reply.status_code == 200, reply.text
    assert reply.json() == {"status": "ok", "light_id": "2"}
    assert simulated.hue.calls == [("2", {"bri": 101})]
    assert simulated.hue.read_count == 1  # guard obtains before-state
    assert simulated.engine.stamps == [("2", {"bri": 101})]
    assert simulated.engine.persists == 1


def test_rest_repeated_owner_action_is_scoped_and_guarded(simulated):
    for payload in ({"on": False}, {"bri": 140}):
        result = simulated.client.put("/api/lights/2", json=payload)
        assert result.status_code == 200, result.text
    assert simulated.hue.calls == [
        ("2", {"on": False}), ("2", {"bri": 140}),
    ]
    assert len(simulated.engine.stamps) == 2
    assert simulated.engine.persists == 2


@pytest.mark.parametrize("attribute,value", [
    ("house_state", "away"),
    ("house_state", "sleeping"),
    ("house_state", "unknown"),
    ("_away_hold", True),
    ("_external_off_detected", True),
    ("_host_return_hold", True),
    ("_active_scene_override_key", "active-scene"),
    ("_gaming_scene_transition_pending", True),
    ("_active_effect_name", "effect"),
    ("_transit_light_overrides", {"2"}),
    ("_screen_sync", SimpleNamespace(fresh_owned_light_ids=lambda: {"2"})),
    ("_external", {"2"}),
    ("_custom_protected", {"2"}),
])
def test_rest_denies_stronger_owners_and_lifecycle_before_hue(
    simulated, attribute, value,
):
    setattr(simulated.engine, attribute, value)
    result = simulated.client.put("/api/lights/2", json={"on": True})
    assert result.status_code == 409, result.text
    assert "owner or lifecycle" in result.json()["detail"]
    assert simulated.hue.calls == []
    assert simulated.engine.stamps == []
    assert simulated.engine.persists == 0


@pytest.mark.parametrize("payload,status", [
    ({}, 400),
    ({"ct": 380, "sat": 0}, 422),
    ({"ct": 380, "hue": 1234}, 422),
    ({"bri": 400}, 422),
    ({"on": "not-a-bool"}, 422),
    ({"bri": 121, "transitiontime": 10000}, 409),
])
def test_rest_invalid_state_cannot_touch_hue(simulated, payload, status):
    result = simulated.client.put("/api/lights/2", json=payload)
    assert result.status_code == status, result.text
    assert simulated.hue.calls == []
    assert simulated.engine.stamps == []


def test_rest_unknown_fixture_fails_closed(simulated):
    response = simulated.client.put("/api/lights/999", json={"on": True})
    assert response.status_code == 404, response.text
    assert simulated.hue.calls == []
    assert simulated.engine.stamps == []


def test_rest_unknown_or_unreachable_hardware_fails_closed(simulated):
    simulated.hue.fixture = {"light_id": "5", "reachable": True}
    result = simulated.client.put("/api/lights/2", json={"bri": 99})
    assert result.status_code == 503, result.text
    assert simulated.hue.calls == []
    simulated.hue.fixture = {"light_id": "2", "reachable": False}
    result = simulated.client.put("/api/lights/2", json={"on": False})
    assert result.status_code == 503, result.text
    assert simulated.hue.calls == []


def test_rest_missing_engine_fails_closed(simulated):
    simulated.app.state.automation = None
    result = simulated.client.put("/api/lights/2", json={"on": False})
    assert result.status_code == 503, result.text
    assert simulated.hue.calls == []


def test_rest_bridge_negative_ack_is_not_success_or_auto_retry(simulated):
    simulated.hue.ack = False
    response = simulated.client.put("/api/lights/2", json={"bri": 75})
    assert response.status_code == 409, response.text
    assert "uncertain" in response.json()["detail"]
    assert simulated.hue.calls == [("2", {"bri": 75})]
    assert simulated.engine.stamps == []
    assert simulated.engine.persists == 0


def test_rest_persistence_failure_does_not_invite_a_second_write(simulated):
    simulated.engine.persist_error = True
    response = simulated.client.put("/api/lights/2", json={"on": False})
    assert response.status_code == 409, response.text
    assert "uncertain" in response.json()["detail"]
    assert simulated.hue.calls == [("2", {"on": False})]
    assert simulated.engine.stamps == [("2", {"on": False})]
    assert simulated.engine.persists == 1


def test_rest_event_log_error_cannot_turn_ack_into_false_failure(simulated):
    async def failed_log(**_):
        raise RuntimeError("mock analytics down")

    simulated.app.state.event_logger = SimpleNamespace(
        log_light_adjustment=failed_log,
    )
    result = simulated.client.put("/api/lights/2", json={"bri": 100})
    assert result.status_code == 200, result.text
    assert simulated.hue.calls == [("2", {"bri": 100})]
    assert simulated.engine.persists == 1


def test_rest_auth_dependency_still_rejects_unauthorized(simulated):
    async def reject():
        raise HTTPException(status_code=401, detail="Unauthorized")

    simulated.app.dependency_overrides[require_api_key] = reject
    result = simulated.client.put("/api/lights/2", json={"on": True})
    assert result.status_code == 401
    assert simulated.hue.calls == []
    assert simulated.engine.stamps == []

def prepare_brightness_inventory(simulated, records):
    simulated.engine._mode_brightness = {"relaxing": 1.0}
    fixtures = {
        str(row["light_id"]): {
            **row, "name": f"Fake {row['light_id']}", "reachable": True,
        }
        for row in records
    }

    async def get_all_lights():
        return list(fixtures.values())

    async def get_light(light_id):
        simulated.hue.read_count += 1
        return fixtures.get(str(light_id))

    simulated.hue.get_all_lights = get_all_lights
    simulated.hue.get_light = get_light


def test_rest_brightness_step_scopes_to_individual_unprotected_fixtures(simulated):
    prepare_brightness_inventory(simulated, [
        {"light_id": "2", "on": True, "bri": 80},
        {"light_id": "3", "on": True, "bri": 80},
    ])
    simulated.engine._transit_light_overrides.add("2")
    response = simulated.client.post("/api/lights/brightness/up")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "partial_failure"
    assert body["blocked"] == ["2"]
    assert body["updated"] == [{"id": "3", "bri": 100}]
    assert body["unavailable"] == []
    assert body["uncertain"] == []
    assert simulated.hue.calls == [("3", {"bri": 100})]
    assert simulated.engine.stamps == [("3", {"bri": 100})]
    assert simulated.engine.persists == 1


def test_rest_brightness_step_denies_without_engine(simulated):
    prepare_brightness_inventory(simulated, [
        {"light_id": "2", "on": True, "bri": 80},
    ])
    simulated.app.state.automation = None
    response = simulated.client.post("/api/lights/brightness/down")
    assert response.status_code == 503, response.text
    assert simulated.hue.calls == []


def test_rest_brightness_step_does_not_retry_ambiguous_bridge_ack(simulated):
    prepare_brightness_inventory(simulated, [
        {"light_id": "2", "on": True, "bri": 100},
    ])
    simulated.hue.ack = False
    response = simulated.client.post("/api/lights/brightness/down")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "partial_failure"
    assert response.json()["uncertain"] == ["2"]
    assert response.json()["updated"] == []
    assert simulated.hue.calls == [("2", {"bri": 80})]
    assert simulated.engine.stamps == []
    assert simulated.engine.persists == 0


def test_rest_brightness_step_invalid_direction_does_not_touch_bridge(simulated):
    response = simulated.client.post("/api/lights/brightness/sideways")
    assert response.status_code == 400
    assert simulated.hue.calls == []


def test_rest_all_lights_splits_guarded_outcomes_without_taking_strong_owner(simulated):
    prepare_brightness_inventory(simulated, [
        {"light_id": "2", "on": True, "bri": 100},
        {"light_id": "3", "on": True, "bri": 100},
    ])
    simulated.engine._screen_sync = SimpleNamespace(
        fresh_owned_light_ids=lambda: {"2"},
    )
    response = simulated.client.post("/api/lights/all", json={"on": False})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "status": "partial_failure",
        "updated": ["3"],
        "blocked": ["2"],
        "unavailable": [],
        "uncertain": [],
    }
    assert simulated.hue.calls == [("3", {"on": False})]
    assert simulated.engine.stamps == [("3", {"on": False})]
    assert simulated.engine.persists == 1


def test_rest_all_lights_never_writes_unregistered_bridge_fixture(simulated):
    prepare_brightness_inventory(simulated, [
        {"light_id": "2", "on": True, "bri": 100},
        {"light_id": "99", "on": True, "bri": 100},
    ])
    reply = simulated.client.post("/api/lights/all", json={"on": False})
    assert reply.status_code == 200, reply.text
    assert reply.json()["updated"] == ["2"]
    assert reply.json()["unavailable"] == ["99"]
    assert simulated.hue.calls == [("2", {"on": False})]


def test_rest_all_lights_ambiguous_ack_is_never_retried(simulated):
    prepare_brightness_inventory(simulated, [
        {"light_id": "2", "on": True, "bri": 100},
    ])
    simulated.hue.ack = False
    reply = simulated.client.post("/api/lights/all", json={"on": False})
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "partial_failure"
    assert reply.json()["uncertain"] == ["2"]
    assert reply.json()["updated"] == []
    assert simulated.hue.calls == [("2", {"on": False})]
    assert simulated.engine.stamps == []


def test_rest_all_lights_missing_authority_fails_before_dispatch(simulated):
    prepare_brightness_inventory(simulated, [
        {"light_id": "2", "on": True, "bri": 100},
    ])
    simulated.app.state.automation = None
    reply = simulated.client.post("/api/lights/all", json={"on": False})
    assert reply.status_code == 503, reply.text
    assert simulated.hue.calls == []


def test_rest_all_lights_rejects_invalid_colorspace(simulated):
    prepare_brightness_inventory(simulated, [
        {"light_id": "2", "on": True, "bri": 100},
    ])
    reply = simulated.client.post(
        "/api/lights/all", json={"ct": 400, "hue": 12000},
    )
    assert reply.status_code == 422, reply.text
    assert simulated.hue.calls == []
