"""Offline Hue bulk ACK and guarded REST ownership contracts.

Real HueService methods use fake bridge replies; route tests use the real
FastAPI handler with synthetic owner evidence and fake per-fixture writes.
No bridge discovery, network, host service or physical actuation occurs.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from backend.services.hue_service import HueService
from backend.services.lighting_transition_boundary import LightingTransitionBoundary
from backend.api.routes.lights import set_all_lights
from backend.api.schemas.lights import LightState
from fastapi import HTTPException
from tests.test_ws_manual_light_guard import Engine, Hue


def _hue(lights, results):
    hue = HueService(bridge_ip="", username="")
    hue._connected = True
    hue.get_all_lights = AsyncMock(return_value=lights)
    hue.set_light = AsyncMock(side_effect=results)
    return hue


@pytest.mark.parametrize("serialized", [False, True])
@pytest.mark.parametrize("results, expected", [([], False), ([True], True),
                                              ([True, True], True),
                                              ([True, False], False),
                                              ([False, False], False)])
async def test_service_bulk_acknowledgement(results, expected, serialized):
    lights = [{"light_id": str(i), "on": False} for i in range(len(results))]
    hue = _hue(lights, results)
    state = {"on": True}
    if serialized:
        boundary = LightingTransitionBoundary(hue)
        hue.set_transition_boundary(boundary)
        async with boundary.serialized():
            actual = await hue.set_all_lights(state)
    else:
        actual = await hue.set_all_lights(state)
    assert actual is expected
    hue.get_all_lights.assert_awaited_once_with()
    assert hue.set_light.await_args_list == [call(light["light_id"], state) for light in lights]


async def _guarded_route(results):
    """Invoke actual REST with a final-write fence and per-fixture fake ACK."""
    engine = Engine()
    hue = Hue(engine)
    hue.breaker_open = False
    lights = [
        {"light_id": str(i + 1), "name": f"Light {i + 1}",
         "on": False, "bri": 10, "reachable": True}
        for i in range(len(results))
    ]
    hue.get_all_lights = AsyncMock(return_value=lights)
    hue.get_light = AsyncMock(side_effect=lambda lid: next(
        (light for light in lights if light["light_id"] == lid), None,
    ))
    original_set_light = hue.set_light

    async def write_with_reply(light_id, state):
        hue.ack = results[int(light_id) - 1]
        return await original_set_light(light_id, state)

    hue.set_light = AsyncMock(side_effect=write_with_reply)
    events = SimpleNamespace(log_light_adjustment=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        hue=hue, automation=engine, event_logger=events,
    )))
    reply = await set_all_lights(LightState(bri=100), request)
    return reply, engine, hue, events


@pytest.mark.parametrize("results", [
    [True], [True, True], [True, False], [False, False],
])
async def test_route_logs_only_acknowledged_guarded_bulk_changes(results):
    reply, engine, hue, events = await _guarded_route(results)
    accepted = [str(i + 1) for i, result in enumerate(results) if result]
    uncertain = [str(i + 1) for i, result in enumerate(results) if not result]
    assert reply == {
        "status": "partial_failure" if uncertain else "ok",
        "updated": accepted, "blocked": [], "unavailable": [],
        "uncertain": uncertain,
    }
    assert hue.get_all_lights.await_count == 1
    assert hue.set_light.await_args_list == [
        call(str(i + 1), {"bri": 100}) for i in range(len(results))
    ]
    assert engine.stamps == [(lid, {"bri": 100}) for lid in accepted]
    assert engine.persists == len(accepted)
    assert events.log_light_adjustment.await_args_list == [
        call(light_id=lid, light_name=f"Light {lid}",
             bri_before=10, bri_after=100, hue_before=None, hue_after=None,
             sat_before=None, sat_after=None, ct_before=None, ct_after=None,
             mode_at_time="relaxing", trigger="all_lights")
        for lid in accepted
    ]


async def test_route_empty_bulk_inventory_fails_closed():
    engine = Engine()
    hue = Hue(engine)
    hue.breaker_open = False
    hue.get_all_lights = AsyncMock(return_value=[])
    events = SimpleNamespace(log_light_adjustment=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        hue=hue, automation=engine, event_logger=events,
    )))
    with pytest.raises(HTTPException) as error:
        await set_all_lights(LightState(bri=100), request)
    assert error.value.status_code == 503
    assert hue.calls == []
    assert engine.stamps == []
    events.log_light_adjustment.assert_not_awaited()


async def test_route_discovery_lost_after_successful_pre_read():
    """Inventory listing never grants identity or physical write authority."""
    engine = Engine()
    hue = Hue(engine)
    hue.breaker_open = False
    hue.get_all_lights = AsyncMock(return_value=[
        {"light_id": "1", "name": "Light 1", "on": True, "bri": 10},
    ])
    hue.get_light = AsyncMock(return_value=None)
    events = SimpleNamespace(log_light_adjustment=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        hue=hue, automation=engine, event_logger=events,
    )))
    assert await set_all_lights(LightState(bri=100), request) == {
        "status": "partial_failure", "updated": [], "blocked": [],
        "unavailable": ["1"], "uncertain": [],
    }
    assert hue.calls == []
    assert engine.stamps == []
    events.log_light_adjustment.assert_not_awaited()
