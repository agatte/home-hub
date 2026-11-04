"""Offline bulk acknowledgement contracts; run with --noconftest.

Load the route functions from source without application/auth imports, which
would load environment settings. Use the real Hue service and serializer with
stubbed discovery/writes, and stub broadcast/event logging. No bridge is created.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from backend.api._guards import _check_hue_available
from backend.api.schemas.lights import LightState
from backend.services.hue_service import HueService
from backend.services.lighting_transition_boundary import LightingTransitionBoundary


def _route():
    path = Path(__file__).resolve().parents[1] / "backend/api/routes/lights.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                 and node.name in {"set_all_lights", "_log_light_change"}]
    assert len(functions) == 2
    for node in functions:
        node.decorator_list = []
    namespace = {"Request": object, "LightState": LightState,
                 "_check_hue_available": _check_hue_available}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["set_all_lights"]


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


@pytest.mark.parametrize("results, expected", [([], "partial_failure"),
                                              ([True], "ok"),
                                              ([True, True], "ok"),
                                              ([True, False], "partial_failure"),
                                              ([False, False], "partial_failure")])
async def test_route_logs_only_fully_acknowledged_bulk_changes(results, expected):
    # Off lights are discoverable and remain valid targets.
    lights = [{"light_id": str(i), "name": f"Light {i}", "on": False, "bri": 10}
              for i in range(len(results))]
    hue = _hue(lights, results)
    await _assert_route(hue, lights, expected)
    assert hue.set_light.await_args_list == [call(light["light_id"], {"bri": 100})
                                            for light in lights]


async def _assert_route(hue, lights, expected):
    ws = SimpleNamespace(broadcast=AsyncMock())
    events = SimpleNamespace(log_light_adjustment=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        hue=hue, ws_manager=ws, event_logger=events, automation=None)))
    assert await _route()(LightState(bri=100), request) == {"status": expected}
    assert hue.get_all_lights.await_count == 3  # before, write discovery, after
    assert ws.broadcast.await_args_list == [call("light_update", light) for light in lights]
    if expected == "ok":
        assert events.log_light_adjustment.await_args_list == [call(
            light_id=light["light_id"], light_name=light["name"],
            bri_before=10, bri_after=100, hue_before=None, hue_after=None,
            sat_before=None, sat_after=None, ct_before=None, ct_after=None,
            mode_at_time=None, trigger="all_lights") for light in lights]
    else:
        events.log_light_adjustment.assert_not_awaited()


async def test_route_discovery_lost_after_successful_pre_read():
    lights = [{"light_id": "1", "name": "Light 1", "on": True, "bri": 10}]
    hue = _hue(lights, [])
    # A successful pre-read cannot prove the subsequent bulk write happened.
    hue.get_all_lights.side_effect = [lights, [], lights]
    await _assert_route(hue, lights, "partial_failure")
    hue.set_light.assert_not_awaited()
