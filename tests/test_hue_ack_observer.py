"""Synthetic offline observer lifecycle and write-path integration checks."""
import json
from unittest.mock import Mock

import httpx
import pytest
from phue import Bridge

from backend.services.hue_ack_observer import OneShotHueAckObserver
from backend.services.hue_service import HueService, _WRITE_REVOKED
from backend.services.hue_v2_service import HueV2Service
from backend.services.lighting_transition_boundary import lighting_write_validator

PRIVATE = ('SYNTHETIC_TOKEN', '192.0.2.123',
           '00000000-0000-4000-8000-000000000001', 'RAW_DESCRIPTION')
IDENT = PRIVATE[2]


def ack(**values):
    return [{'success': {f'/lights/1/state/{key}': value}} for key, value in values.items()]


def v1(payload):
    bridge = object.__new__(Bridge)
    bridge._username = 'offline'
    bridge.request = Mock(return_value=payload)
    service = HueService('offline.invalid', 'offline')
    service._connected = True
    service._bridge = bridge
    return service


class Client:
    def __init__(self, payload, status=200, invalid_json=False):
        self.response = Mock()
        self.response.status_code = status
        self.response.raise_for_status = Mock()
        if status == 503:
            self.response.raise_for_status.side_effect = httpx.HTTPError('synthetic')
        self.response.json = Mock(return_value=payload)
        if invalid_json:
            self.response.json.side_effect = ValueError('synthetic')
        self.put = Mock(side_effect=self._put)

    async def _put(self, *args, **kwargs):
        return self.response


def v2(payload, **kwargs):
    service = HueV2Service('offline.invalid', 'offline')
    service._connected = True
    service._client = Client(payload, **kwargs)
    service._v1_to_v2 = {'1': IDENT}
    return service


async def write(service, operation):
    if operation == 'scene':
        return await service.activate_scene(IDENT)
    return await service.set_effect('1', 'candle')


def assert_private(observer):
    rendered = repr(observer.__dict__) + json.dumps(observer.get_summaries())
    assert all(value not in rendered for value in PRIVATE), 'privacy failure'


@pytest.mark.parametrize('limit', [True, 0, 3, 1.0, None, '1'])
def test_invalid_limit(limit):
    with pytest.raises(ValueError):
        OneShotHueAckObserver(max_events=limit)


@pytest.mark.parametrize('ttl', [True, 0, -1, 61, float('nan'), float('inf'), '1'])
def test_invalid_ttl(ttl):
    with pytest.raises(ValueError):
        OneShotHueAckObserver(ttl_seconds=ttl)


@pytest.mark.parametrize('limit', [1, 2])
def test_count_copies_privacy_and_no_raw_retention(limit):
    observer = OneShotHueAckObserver(max_events=limit)
    raw = {'errors': [{'description': ' '.join(PRIVATE)}],
           'data': [{'rid': IDENT, 'rtype': 'light'}]}
    for _ in range(4):
        observer.observe_v2(200, raw, IDENT, 'light')
    summaries = observer.get_summaries()
    assert len(summaries) == limit
    assert summaries[0]['error_count'] == 1
    assert summaries[0]['acceptance'] == 'INCOMPLETE_OR_UNKNOWN'
    summaries[0]['requested_properties'].append(PRIVATE[0])
    summaries[0]['shape'] = PRIVATE[0]
    summaries.clear()
    assert len(observer.get_summaries()) == limit
    assert_private(observer)
    assert all(value is not raw for value in observer.__dict__.values())


def test_expiry_and_disarm():
    now = [0.0]
    observer = OneShotHueAckObserver(max_events=2, ttl_seconds=1, clock=lambda: now[0])
    observer.observe_v1([ack(on=False)], {'on': False}, '1')
    now[0] = 1.0
    observer.observe_v1([ack(on=False)], {'on': False}, '1')
    now[0] = 0.0
    observer.observe_v1([ack(on=False)], {'on': False}, '1')
    assert len(observer.get_summaries()) == 1
    observer = OneShotHueAckObserver()
    observer.disarm()
    observer.observe_v2(200, {}, IDENT, 'light')
    assert observer.get_summaries() == []


def test_expiry_during_summary_and_contention():
    times = iter([0, 0, 60, 60])
    observer = OneShotHueAckObserver(clock=lambda: next(times))
    observer.observe_v1([ack(on=False)], {'on': False}, '1')
    assert observer.get_summaries() == []
    observer = OneShotHueAckObserver()
    with observer._lock:
        observer.observe_v1([ack(on=False)], {'on': False}, '1')
    assert observer.get_summaries() == []


@pytest.mark.asyncio
@pytest.mark.parametrize('payload,accepted', [(ack(on=False), True), ([], False),
    (ack(on=False) + [{'error': {'description': ' '.join(PRIVATE)}}], False)])
async def test_v1_injection_preserves_result_and_masks(payload, accepted):
    service = v1(payload)
    assert service._ack_observer is None
    observer = OneShotHueAckObserver()
    service.set_ack_observer(observer)
    assert await service.set_light('1', {'on': False}) is accepted
    assert bool(service._inflight_until) is accepted
    assert bool(service._transition_settle_until) is accepted
    assert service._bridge.request.call_count == 1
    summaries = observer.get_summaries()
    assert len(summaries) == 1
    assert (summaries[0]['acceptance'] == 'ACCEPTED_NOT_PHYSICAL') is accepted
    assert_private(observer)


@pytest.mark.asyncio
async def test_v1_ct_generated_command_and_default_detach():
    service = v1(ack(sat=0, ct=400))
    assert await service.set_light('1', {'ct': 400}) is True
    observer = OneShotHueAckObserver()
    service.set_ack_observer(observer)
    assert await service.set_light('1', {'ct': 400}) is True
    assert observer.get_summaries()[0]['requested_properties'] == ['sat', 'ct']
    assert observer.get_summaries()[0]['acceptance'] == 'ACCEPTED_NOT_PHYSICAL'
    service.set_ack_observer(None)
    assert await service.set_light('1', {'ct': 400}) is True
    assert service._bridge.request.call_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('accepted', [True, False])
async def test_v1_raising_observer_cannot_change_existing_mask(accepted, caplog):
    service = v1(ack(on=False) if accepted else [])
    service._inflight_until = {'1': 12.0}
    service._transition_settle_until = {'1': 11.0}
    observer = Mock()
    observer.observe_v1.side_effect = RuntimeError(' '.join(PRIVATE))
    service.set_ack_observer(observer)
    assert await service.set_light('1', {'on': False}) is accepted
    observer.observe_v1.assert_called_once()
    assert all(value not in caplog.text for value in PRIVATE), "privacy failure"
    if not accepted:
        assert service._inflight_until == {'1': 12.0}
        assert service._transition_settle_until == {'1': 11.0}


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['disconnected', 'revoked', 'exception', 'none'])
async def test_v1_no_response_no_observation(failure):
    service = v1([])
    observer = Mock()
    service.set_ack_observer(observer)
    if failure == 'disconnected':
        service._connected = False
    else:
        async def safe(*args, **kwargs):
            if failure == 'exception':
                raise RuntimeError('synthetic')
            if failure == 'none':
                return None
            return _WRITE_REVOKED
        service._safe_call = safe
    assert await service.set_light('1', {'on': False}) is False
    observer.observe_v1.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['scene', 'effect'])
@pytest.mark.parametrize('shape', ['accepted', 'malformed', 'error', 'partial'])
async def test_v2_single_parse_and_observation(operation, shape):
    kind = 'scene' if operation == 'scene' else 'light'
    payload = {'errors': [], 'data': [{'rid': IDENT, 'rtype': kind}]}
    if shape == 'malformed':
        payload = None
    elif shape in ('error', 'partial'):
        payload['errors'] = [{'description': ' '.join(PRIVATE)}]
        if shape == 'error':
            payload['data'] = []
    service = v2(payload)
    assert service._ack_observer is None
    observer = OneShotHueAckObserver(max_events=2)
    service.set_ack_observer(observer)
    for _ in range(3):
        assert await write(service, operation) is (shape == 'accepted')
    assert service._client.response.json.call_count == 3
    assert service._client.put.call_count == 3
    assert len(observer.get_summaries()) == 2
    assert (observer.get_summaries()[0]['acceptance'] == 'ACCEPTED_NOT_PHYSICAL') is (shape == 'accepted')
    assert_private(observer)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['scene', 'effect'])
@pytest.mark.parametrize('accepted', [True, False])
async def test_v2_raising_observer_and_default(operation, accepted, caplog):
    kind = 'scene' if operation == 'scene' else 'light'
    service = v2({'errors': [], 'data': [{'rid': IDENT, 'rtype': kind}]} if accepted else {})
    assert await write(service, operation) is accepted
    observer = Mock()
    observer.observe_v2.side_effect = RuntimeError(' '.join(PRIVATE))
    service.set_ack_observer(observer)
    assert await write(service, operation) is accepted
    observer.observe_v2.assert_called_once()
    assert all(value not in caplog.text for value in PRIVATE), "privacy failure"
    assert service._client.response.json.call_count == 2
    assert service._client.put.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['scene', 'effect'])
@pytest.mark.parametrize('failure', ['http', 'json', 'guard', 'disconnected'])
async def test_v2_no_parsed_response_no_observation(operation, failure):
    service = v2({}, status=503 if failure == 'http' else 200,
                 invalid_json=failure == 'json')
    observer = Mock()
    service.set_ack_observer(observer)
    if failure == 'disconnected':
        service._connected = False
    token = lighting_write_validator.set((lambda: False) if failure == 'guard' else None)
    try:
        assert await write(service, operation) is False
    finally:
        lighting_write_validator.reset(token)
    observer.observe_v2.assert_not_called()
    assert service._client.put.call_count == (0 if failure in ('guard', 'disconnected') else 1)


def test_malformed_input_never_retained_and_shared_protocol_budget():
    class Exotic:
        def __repr__(self):
            raise AssertionError('must not render')
    observer = OneShotHueAckObserver(max_events=2)
    observer.observe_v1(Exotic(), Exotic(), Exotic())
    observer.observe_v2(200, {'errors': [], 'data': [
        {'rid': IDENT, 'rtype': 'scene'}]}, IDENT, 'scene')
    observer.observe_v1([ack(on=False)], {'on': False}, '1')
    summaries = observer.get_summaries()
    assert [event['protocol'] for event in summaries] == ['V1', 'V2']
    assert summaries[0]['shape'] == 'MALFORMED'
    assert summaries[1]['acceptance'] == 'ACCEPTED_NOT_PHYSICAL'
    assert_private(observer)


def test_clock_exception_disarms_without_retaining_exception():
    class Clock:
        fail = False
        def __call__(self):
            if self.fail:
                raise ValueError('synthetic')
            return 0
    clock = Clock()
    observer = OneShotHueAckObserver(clock=clock)
    clock.fail = True
    observer.observe_v1(None, None, None)
    clock.fail = False
    observer.observe_v1([ack(on=False)], {'on': False}, '1')
    assert observer.get_summaries() == []



@pytest.mark.asyncio
async def test_v1_optional_observer_absent_on_legacy_fixture():
    service = v1(ack(on=False))
    del service._ack_observer
    assert await service.set_light('1', {'on': False}) is True
    assert service._bridge.request.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['scene', 'effect'])
async def test_v2_optional_observer_absent_on_legacy_fixture(operation):
    kind = 'scene' if operation == 'scene' else 'light'
    service = v2({'errors': [], 'data': [{'rid': IDENT, 'rtype': kind}]})
    del service._ack_observer
    assert await write(service, operation) is True
    assert service._client.put.call_count == 1
