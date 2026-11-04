"""Offline privacy boundary; no config, real handlers, Hue clients or network.

Preparation for #370 only. These checks do not certify telemetry integrations,
future phue versions, or physical bridge acceptance. Publishing/live observation
still requires independent review and separate authorization.
"""
import ast
import logging
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from backend.services.hue_service import HueService
from backend.services.hue_v2_service import HueV2Service

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ('198.51.100.44', 'synthetic-private-key', 'synthetic-resource',
           'synthetic-effect', '54321')


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.mark.parametrize('level', [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL])
def test_setup_suppresses_library_before_handlers(level):
    library = logging.getLogger('phue_modern')
    app = logging.getLogger('home_hub')
    root = logging.getLogger()
    old = (library.disabled, library.level, library.propagate, app.level)
    old_handlers = app.handlers[:]
    sink = Capture()
    config = SimpleNamespace(LOG_DIR=MagicMock(), settings=SimpleNamespace(LOG_LEVEL='DEBUG'))
    tracing = SimpleNamespace(request_id_var=SimpleNamespace(get=lambda: None))
    def guarded_handler():
        assert library.disabled  # Guard precedes creation of application handlers.
        return Capture()

    try:
        library.disabled = False
        library.setLevel(level)
        library.propagate = True
        library.addHandler(sink)
        root.addHandler(sink)
        app.handlers = [sink]
        # Evaluate the actual startup module without loading settings or opening files.
        with patch.dict(sys.modules, {'backend.config': config, 'backend.services.tracing': tracing}), \
                patch('logging.handlers.RotatingFileHandler', side_effect=lambda *a, **k: guarded_handler()), \
                patch('logging.StreamHandler', side_effect=lambda *a, **k: guarded_handler()):
            namespace = runpy.run_path(str(ROOT / 'backend/utils/logger.py'))
        assert library.disabled
        for severity in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL):
            library.log(severity, ' '.join(PRIVATE), exc_info=(RuntimeError, RuntimeError(PRIVATE[1]), None))
        assert not sink.records
        # Guard is idempotent and does not globally disable application diagnostics.
        namespace['suppress_hue_library_logging']()
        app.warning('Synthetic application status')
        assert any(r.getMessage() == 'Synthetic application status' for r in sink.records)
    finally:
        library.disabled, library.level, library.propagate, app.level = old
        library.removeHandler(sink)
        root.removeHandler(sink)
        app.handlers = old_handlers


@pytest.fixture
def capture_services():
    sink = Capture()
    loggers = [logging.getLogger(n) for n in ('home_hub.hue', 'home_hub.hue_v2')]
    old = [(l.handlers[:], l.level, l.propagate, l.disabled) for l in loggers]
    for logger in loggers:
        logger.handlers = [sink]
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.disabled = False
    yield sink
    for logger, state in zip(loggers, old):
        logger.handlers, logger.level, logger.propagate, logger.disabled = state


def assert_private(sink):
    # Never include captured text/sentinels in failure output.
    assert bool(sink.records)
    assert all(not any(value in r.getMessage() for value in PRIVATE) for r in sink.records)
    assert all(not r.exc_info and not r.stack_info for r in sink.records)


@pytest.mark.asyncio
async def test_v1_connect_and_write(capture_services):
    service = HueService(*PRIVATE[:2])
    fake_bridge = Mock()
    def connect(*args):
        logging.getLogger('phue_modern').info(' '.join(PRIVATE))
        return fake_bridge
    # Library guard is covered separately; keep synthetic library output in memory.
    with patch.dict(sys.modules, {'phue': SimpleNamespace(Bridge=connect)}), \
            patch.object(logging.getLogger('phue_modern'), 'disabled', True):
        await service.connect()
    service._safe_call = AsyncMock(return_value=[[{'success': {'/lights/1/state/on': True}},
                                                  {'success': {'/lights/1/state/hue': 54321}}]])
    assert await service.set_light('1', {'on': True, 'hue': 54321})
    service._safe_call.return_value = []
    assert not await service.set_light('1', {'on': True})
    service._safe_call.side_effect = RuntimeError(' '.join(PRIVATE))
    assert not await service.set_light('1', {'on': True})
    assert await service.get_all_lights() == []
    with patch.dict(sys.modules, {'phue': SimpleNamespace(Bridge=Mock(side_effect=RuntimeError(' '.join(PRIVATE))))}):
        await service.connect()
    assert_private(capture_services)
    assert any('physical completion unverified' in r.getMessage() for r in capture_services.records)
    assert any('remote outcome' in r.getMessage() for r in capture_services.records)


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['accepted', 'rejected', 'exception', 'http', 'rate_limit'])
async def test_v2_write_and_inventory(capture_services, outcome):
    service = HueV2Service(*PRIVATE[:2])
    service._connected = True
    service._v1_to_v2 = {PRIVATE[2]: PRIVATE[2]}
    client = Mock(put=AsyncMock(), get=AsyncMock(side_effect=RuntimeError(' '.join(PRIVATE))))
    service._client = client
    for operation in ('scene', 'effect'):
        response = Mock(status_code=200)
        response.json.return_value = {'errors': [], 'data': [{'rid': PRIVATE[2], 'rtype': 'scene' if operation == 'scene' else 'light'}]}
        if outcome == 'rejected':
            response.json.return_value = {'errors': [{'description': ' '.join(PRIVATE)}], 'data': []}
        client.put.side_effect = None
        if outcome == 'exception':
            client.put.side_effect = RuntimeError(' '.join(PRIVATE))
        elif outcome in ('http', 'rate_limit'):
            response.raise_for_status.side_effect = httpx.HTTPStatusError(' '.join(PRIVATE), request=Mock(), response=SimpleNamespace(status_code=429 if outcome == 'rate_limit' else 500))
        client.put.return_value = response
        result = await (service.activate_scene(PRIVATE[2]) if operation == 'scene' else service.set_effect(PRIVATE[2], PRIVATE[3]))
        assert result is (outcome == 'accepted')
    await service.set_effect('unmapped', PRIVATE[3])
    await service.get_scenes(force_refresh=True)
    await service.get_rooms()
    assert_private(capture_services)


def test_service_logging_has_no_unreviewed_dynamic_data_or_tracebacks():
    # Structural coverage includes polling/stream retry loops without running them.
    # Only reviewed local counts and backoff constants may be interpolated.
    for filename in ('hue_service.py', 'hue_v2_service.py'):
        tree = ast.parse((ROOT / 'backend/services' / filename).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != 'logger':
                continue
            assert node.func.attr != 'exception'
            assert not node.keywords
            for arg in node.args:
                if isinstance(arg, ast.Constant):
                    continue
                if isinstance(arg, ast.JoinedStr):
                    assert all(isinstance(v, ast.Constant) or ast.unparse(v.value) == 'len(self._v1_to_v2)' for v in arg.values)
                else:
                    assert isinstance(arg, ast.Name) and arg.id in {'backoff', '_STREAM_SILENT_RECONNECT_SECONDS'}


@pytest.mark.asyncio
async def test_v2_connection_failure_is_private(capture_services):
    service = HueV2Service(*PRIVATE[:2])
    with patch('backend.services.hue_v2_service.httpx.AsyncClient',
               side_effect=RuntimeError(' '.join(PRIVATE))):
        await service.connect()
    assert not service.connected
    assert_private(capture_services)
