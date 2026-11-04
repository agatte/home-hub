"""#370 offline evidence only; never imports application settings or lifespan.

Run with --noconftest: the shared conftest imports database -> real config.

Pinned HTTPcore Trace preformats response headers and exception repr into DEBUG
messages, losing structured destination context. The synthetic failure below
proves that separate leakage surface, not an actual Hue failure/production leak.
A host filter cannot safely classify those records; blanket HTTPcore suppression
is deliberately avoided. Real Sentry ingestion, future versions, child loggers,
direct telemetry and later logging reconfiguration remain independent review gates.
"""
import ast
import asyncio
import logging
from pathlib import Path
import runpy
import socket
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpcore
from httpcore._trace import Trace
import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
HOST = '198.51.100.44'
PRIVATE_URL = f'http://{HOST}/api/fabricated-only-token/lights'
PUBLIC_URL = 'http://203.0.113.45/status'
SUMMARY = 'HTTP Request: %s %s "%s %d %s"'


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def local_loop():
    # Windows creates an internal loopback socketpair for event-loop wakeups.
    # Construct it before the transport network-denial guard, then block all
    # socket connects/DNS while exercising HTTPX.
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def harness(monkeypatch, local_loop):
    # Restore every property we mutate, including filters installed by run_path.
    names = ('', 'httpx', 'home_hub', 'phue_modern', 'httpcore.http11')
    loggers = [logging.getLogger(name) for name in names]
    states = [(l.handlers[:], l.filters[:], l.level, l.propagate, l.disabled)
              for l in loggers]
    sink, root_sink = Capture(), Capture()
    for logger in loggers:
        logger.handlers = []
        logger.filters = []
        logger.setLevel(logging.DEBUG)
        logger.disabled = False
        logger.propagate = True
    loggers[0].handlers = [root_sink]
    loggers[1].handlers = [sink]
    settings = SimpleNamespace(HUE_BRIDGE_IP=HOST, LOG_LEVEL='DEBUG')
    config = SimpleNamespace(LOG_DIR=MagicMock(), settings=settings)
    tracing = SimpleNamespace(request_id_var=SimpleNamespace(get=lambda: None))

    def no_network(*args, **kwargs):
        pytest.fail('Network access forbidden')

    monkeypatch.setattr(socket, 'create_connection', no_network)
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    monkeypatch.setattr(socket, 'getaddrinfo', no_network)

    def handler(*args, **kwargs):
        # Installation precedes handler construction/file creation at startup.
        assert any(getattr(f, '_homehub_hue_httpx_filter', False)
                   for f in loggers[1].filters)
        return Capture()

    try:
        with patch.dict(sys.modules, {'backend.config': config,
                                     'backend.services.tracing': tracing}), \
                patch('logging.StreamHandler', side_effect=handler), \
                patch('logging.handlers.RotatingFileHandler', side_effect=handler):
            namespace = runpy.run_path(str(ROOT / 'backend/utils/logger.py'))
            yield SimpleNamespace(ns=namespace, settings=settings, sink=sink,
                                  root_sink=root_sink, logger=loggers[1], loop=local_loop)
    finally:
        for logger, state in zip(loggers, states):
            logger.handlers, logger.filters, logger.level, logger.propagate, logger.disabled = state


@pytest.mark.parametrize('level', [logging.DEBUG, logging.INFO, logging.ERROR])
def test_structured_records_rejected_before_callhandlers(harness, level):
    # Sentry's pinned integration wraps Logger.callHandlers. This equivalent hook
    # asserts rejected records never reach that stage, even with private exc_info.
    old = logging.Logger.callHandlers
    calls = []

    def telemetry(logger, record):
        calls.append(record)
        return old(logger, record)

    with patch.object(logging.Logger, 'callHandlers', telemetry):
        harness.logger.log(level, SUMMARY, 'GET', httpx.URL(PRIVATE_URL),
                           'HTTP/1.1', 200, 'OK',
                           exc_info=(RuntimeError, RuntimeError(PRIVATE_URL), None))
        assert not calls
        assert not harness.sink.records and not harness.root_sink.records
        harness.logger.log(level, SUMMARY, 'GET', httpx.URL(PUBLIC_URL), 'HTTP/1.1', 200, 'OK')
    assert len(calls) == 1
    assert PUBLIC_URL in harness.sink.records[0].getMessage()
    assert len(harness.root_sink.records) == 1


@pytest.mark.parametrize('asynchronous', [False, True])
def test_pinned_httpx_shape_and_fake_transport(harness, asynchronous):
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    async def async_requests():
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get(PRIVATE_URL)
            await client.get(PUBLIC_URL)
    if asynchronous:
        harness.loop.run_until_complete(async_requests())
    else:
        with httpx.Client(transport=transport) as client:
            client.get(PRIVATE_URL)
            client.get(PUBLIC_URL)
    assert len(harness.sink.records) == len(harness.root_sink.records) == 1
    record = harness.sink.records[0]
    assert record.levelno == logging.INFO and record.msg == SUMMARY
    assert len(record.args) == 5 and isinstance(record.args[1], httpx.URL)
    assert PUBLIC_URL in record.getMessage()


@pytest.mark.parametrize('configured,request_host', [
    (HOST, HOST), ('BRIDGE.EXAMPLE.', 'bridge.example'),
    ('bridge.example', 'BRIDGE.EXAMPLE.'), ('2001:db8::1', '[2001:db8::1]'),
    ('2001:db8::1', '[2001:0db8:0000:0000:0000:0000:0000:0001]'),
])
def test_normalized_exact_host_and_idempotence(harness, configured, request_host):
    harness.settings.HUE_BRIDGE_IP = configured
    harness.ns['setup_logging']()
    harness.ns['suppress_hue_httpx_logging']()
    assert len(harness.logger.filters) == 1
    harness.logger.info(SUMMARY, 'GET', httpx.URL(f'http://{request_host}/api/fabricated'),
                        'HTTP/1.1', 200, 'OK')
    assert not harness.sink.records
    harness.logger.info(SUMMARY, 'GET', httpx.URL(PUBLIC_URL), 'HTTP/1.1', 200, 'OK')
    assert len(harness.sink.records) == 1


@pytest.mark.parametrize('configured', [None, '', 'http://bridge.example/api/fabricated',
                                        'user@bridge.example', ' bad host ', '/'])
def test_invalid_config_fails_closed_for_request_summaries(harness, configured):
    harness.settings.HUE_BRIDGE_IP = configured
    harness.logger.info(SUMMARY, 'GET', httpx.URL(PRIVATE_URL), 'HTTP/1.1', 200, 'OK')
    assert not harness.sink.records
    harness.logger.info('Unrelated HTTPX diagnostic')
    assert len(harness.sink.records) == 1


def test_malformed_records_never_render_or_escape(harness):
    class Unrenderable:
        def __str__(self):
            pytest.fail('Private argument rendered')

    for args in [(), ('GET', Unrenderable()), ('GET', httpx.URL('/relative'))]:
        harness.logger.error('HTTP Request: %s', *args)
    harness.logger.error(SUMMARY, 'GET', Unrenderable(), httpx.URL(PUBLIC_URL), 200, 'OK')
    harness.logger.info('HTTP Request: %(url)s', {'url': Unrenderable()})
    class UnparseableURL(httpx.URL):
        @property
        def host(self):
            raise ValueError('Synthetic classification failure')

    harness.logger.info(SUMMARY, 'GET', UnparseableURL(PRIVATE_URL), 'HTTP/1.1', 200, 'OK')
    assert not harness.sink.records and not harness.root_sink.records
    # A suffix match must never classify an unrelated host as the bridge.
    harness.logger.info(SUMMARY, 'GET', httpx.URL(f'http://{HOST}.example/status'),
                        'HTTP/1.1', 200, 'OK')
    assert len(harness.sink.records) == 1


def test_missing_host_fails_closed(harness):
    del harness.settings.HUE_BRIDGE_IP
    harness.logger.info(SUMMARY, 'GET', httpx.URL(PRIVATE_URL), 'HTTP/1.1', 200, 'OK')
    assert not harness.sink.records and not harness.root_sink.records


def test_httpcore_debug_trace_is_filtered(harness):
    """Pinned preformatted DEBUG request, exception and header traces stay private."""
    logger = logging.getLogger('httpcore.http11')
    request = httpcore.Request('GET', PRIVATE_URL)
    with Trace('send_request_headers', logger, request, {'request': request}):
        pass
    records = harness.root_sink.records
    assert not records
    # Earlier fake-only preflight proved these traces can contain fabricated URL
    # paths; the emitting DEBUG filter must block them before any handler/Sentry.
    with pytest.raises(RuntimeError):
        with Trace('send_request_headers', logger, request, {'request': request}):
            raise RuntimeError(PRIVATE_URL)
    assert not records
    with Trace('receive_response_headers', logger, request) as trace:
        trace.return_value = (b'HTTP/1.1', 200, b'OK', [(b'location', PRIVATE_URL.encode())])
    assert not records


def test_startup_guard_precedes_handler_creation():
    tree = ast.parse((ROOT / 'backend/utils/logger.py').read_text(encoding='utf-8'))
    setup = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'setup_logging')
    guard = next(n.lineno for n in ast.walk(setup) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'suppress_hue_httpx_logging')
    mkdir = next(n.lineno for n in ast.walk(setup) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'mkdir')
    assert guard < mkdir
