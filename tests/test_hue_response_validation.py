"""Offline response truthfulness using installed phue2 and fake HTTP clients."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from phue import Bridge
from fastapi import HTTPException

from backend.services.hue_service import HueService, _single_light_acknowledged
from backend.services.hue_v2_service import HueV2Service
from backend.services.lighting_transition_boundary import lighting_write_validator


def ack(**values):
    return [{"success": {f"/lights/1/state/{key}": value}} for key, value in values.items()]


def v1_service(payload):
    bridge = object.__new__(Bridge)
    bridge._username = "offline"
    bridge.request = Mock(return_value=payload)
    service = HueService("offline.invalid", "offline")
    service._connected = True
    service._bridge = bridge
    return service


@pytest.mark.parametrize("reply", [
    None, [], {}, True, "ok", [None], [[]],
    [[{"success": {}}]],
    [[{"success": {"/lights/2/state/on": False}}]],
    [[{"success": {"/lights/1/state/bri": 20}}]],
    [ack(on=False) + ack(on=False)],
    [[{"success": {"/lights/1/state/on": 0}}]],
    [[{"success": {"/lights/1/state/on": False}, "error": {}}]],
    [ack(on=False), ack(on=False)],
])
def test_reject_malformed_or_wrong_ack(reply):
    assert not _single_light_acknowledged(reply, 1, {"on": False})


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    None, [], {},
    [{"error": {"type": 201, "description": "offline rejection"}}],
    ack(on=False) + [{"error": {"description": "partial"}}],
    ack(on=False),
    ack(on=False, bri=True),
])
async def test_v1_rejected_response_preserves_existing_mask(payload):
    service = v1_service(payload)
    service._inflight_until = {"1": 12.0}
    service._transition_settle_until = {"1": 11.0}
    assert await service.set_light("1", {"on": False, "bri": 40}) is False
    assert service._inflight_until == {"1": 12.0}
    assert service._transition_settle_until == {"1": 11.0}
    assert service._bridge.request.call_count == 1


@pytest.mark.asyncio
async def test_v1_complete_matching_ack_arms_mask():
    service = v1_service(ack(on=True, bri=40, transitiontime=4))
    assert await service.set_light("1", {"on": True, "bri": 40, "transitiontime": 4}) is True
    assert service._inflight_until["1"] > service._transition_settle_until["1"]
    service._bridge.request.assert_called_once_with(
        "PUT", "/api/offline/lights/1/state", {"on": True, "bri": 40, "transitiontime": 4})


@pytest.mark.asyncio
async def test_v1_error_does_not_create_mask():
    service = v1_service([])
    assert await service.set_light("1", {"on": False}) is False
    assert service._inflight_until == service._transition_settle_until == {}


class FakeClient:
    def __init__(self, payload, status=200):
        self.payload, self.status, self.calls = payload, status, []

    async def put(self, path, json):
        self.calls.append((path, json))
        return httpx.Response(self.status, json=self.payload,
            request=httpx.Request("PUT", "https://offline.invalid" + path))


def v2_service(payload, status=200):
    service = HueV2Service("offline.invalid", "offline")
    service._connected = True
    service._client = FakeClient(payload, status)
    service._v1_to_v2 = {"1": "resource"}
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["scene", "effect"])
@pytest.mark.parametrize("payload", [
    None, [], {}, {"errors": [], "data": []},
    {"errors": [{"description": "rejected"}], "data": []},
    {"errors": [{"description": "partial"}], "data": [{"rid": "resource", "rtype": "light"}]},
    {"errors": None, "data": []}, {"errors": [], "data": {}},
    {"errors": [], "data": [None]},
    {"errors": [], "data": [{"rid": "wrong", "rtype": "light"}]},
    {"errors": [], "data": [
        {"rid": "resource", "rtype": "light"},
        {"rid": "other", "rtype": "light"}]},
    {"errors": [], "data": [
        {"rid": "resource", "rtype": "scene"},
        {"rid": "resource", "rtype": "scene"}]},
])
async def test_v2_rejects_json_errors_and_malformed_envelopes(operation, payload):
    service = v2_service(payload)
    result = await (service.activate_scene("resource") if operation == "scene"
                    else service.set_effect("1", "candle"))
    assert result is False
    assert len(service._client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["scene", "effect"])
async def test_v2_normal_ack_and_source_guard(operation):
    kind = "scene" if operation == "scene" else "light"
    service = v2_service({"errors": [], "data": [{"rid": "resource", "rtype": kind}]})
    async def write():
        return await (service.activate_scene("resource") if operation == "scene"
                      else service.set_effect("1", "candle"))
    assert await write() is True
    token = lighting_write_validator.set(lambda: False)
    try:
        assert await write() is False
    finally:
        lighting_write_validator.reset(token)
    assert len(service._client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,accepted", [
    (ack(on=False), True), ([], False), (ack(on=True), False),
])
async def test_route_only_marks_manual_after_accepted_ack(payload, accepted):
    from backend.api.routes.lights import set_light
    from backend.api.schemas.lights import LightState
    service = v1_service(payload)
    service.get_light = AsyncMock(return_value={"on": True})
    automation = SimpleNamespace(mark_light_manual=Mock(), persist_manual_light_ownership=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        hue=service, automation=automation, event_logger=None)),
        headers={}, client=SimpleNamespace(host="offline"), scope={})
    if accepted:
        assert (await set_light("1", LightState(on=False), request))["status"] == "ok"
        automation.mark_light_manual.assert_called_once_with("1", {"on": False})
        automation.persist_manual_light_ownership.assert_awaited_once()
    else:
        with pytest.raises(HTTPException) as error:
            await set_light("1", LightState(on=False), request)
        assert error.value.status_code == 500
        automation.mark_light_manual.assert_not_called()
        automation.persist_manual_light_ownership.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["scene", "effect"])
@pytest.mark.parametrize("failure", ["http", "json"])
async def test_v2_transport_or_json_failure(operation, failure):
    service = v2_service({}, 503)
    if failure == "json":
        async def put(path, json):
            return httpx.Response(200, content=b"not json",
                request=httpx.Request("PUT", "https://offline.invalid" + path))
        service._client.put = put
    assert await (service.activate_scene("resource") if operation == "scene"
                  else service.set_effect("1", "candle")) is False


def test_exact_ct_ack_and_reject_unsupported_normalization():
    command = {"sat": 0, "ct": 300, "transitiontime": 10}
    assert _single_light_acknowledged([ack(sat=0, ct=300, transitiontime=10)], 1, command)
    assert not _single_light_acknowledged([ack(sat=0, ct=301, transitiontime=9)], 1, command)
    assert not _single_light_acknowledged([ack(sat=0, ct=301)], 1, command)


@pytest.mark.parametrize("command,response", [
    ({"on": False}, ack(on=True)),
    ({"bri": 12}, ack(bri=254)),
    ({"sat": 0, "ct": 300}, ack(sat=254, ct=500)),
    ({"transitiontime": 4}, ack(transitiontime=3)),
])
def test_wrong_value_ack_never_reports_success(command, response):
    assert not _single_light_acknowledged([response], 1, command)


@pytest.mark.asyncio
async def test_contradictory_on_reply_does_not_arm_mask():
    service = v1_service(ack(on=True))
    assert await service.set_light("1", {"on": False}) is False
    assert service._inflight_until == service._transition_settle_until == {}
