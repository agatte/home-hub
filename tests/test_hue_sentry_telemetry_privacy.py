"""#370 offline synthetic containment proof. Run with --noconftest.

No app/lifespan/config import, real transport, device, or credential use.
Pinned SDK upgrade gate: recheck automatic HTTPX breadcrumbs and logger emitters.
"""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import sentry_sdk
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.transport import Transport

from backend.utils.sentry_privacy import redact_http_client_breadcrumbs
from tests.test_hue_httpx_logging_privacy import harness, local_loop, PRIVATE_URL

ROOT = Path(__file__).resolve().parents[1]
EMITTERS = ('httpcore.connection', 'httpcore.http11', 'httpcore.http2',
            'httpcore.proxy', 'httpcore.socks')
DSN = 'http://synthetic@192.0.2.99/1'


class MemoryTransport(Transport):
    def __init__(self, options):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == 'event':
                self.events.append(item.payload.json)


@pytest.fixture(autouse=True)
def restore_emitters(monkeypatch):
    # Bound automatic discovery to the relevant installed integrations. Avoid
    # importing unrelated optional SDK integrations and their process hooks.
    from sentry_sdk.integrations.logging import LoggingIntegration
    import sentry_sdk.integrations
    # Simulate fresh process startup: 2.59.0 caches installed integrations
    # globally and does not re-apply disabled_integrations to an earlier client.
    for cache in ('_installed_integrations', '_processed_integrations'):
        monkeypatch.setattr(sentry_sdk.integrations, cache,
                            getattr(sentry_sdk.integrations, cache) - {'httpx'})
    monkeypatch.setattr(sentry_sdk.integrations, 'iter_default_integrations',
                        lambda auto: iter((LoggingIntegration, HttpxIntegration)))
    loggers = [logging.getLogger(n) for n in EMITTERS]
    states = [(l.filters[:], l.level, l.disabled) for l in loggers]
    yield
    for logger, (filters, level, disabled) in zip(loggers, states):
        logger.filters, logger.level, logger.disabled = filters, level, disabled


def startup_options(env):
    tree = ast.parse((ROOT / 'backend/main.py').read_text(encoding='utf-8'))
    call = next(n.value for n in tree.body if isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call)
                and ast.unparse(n.value.func) == 'sentry_sdk.init')
    namespace = dict(settings=SimpleNamespace(APP_ENV=env, SENTRY_DSN=DSN),
                     HttpxIntegration=HttpxIntegration,
                     redact_http_client_breadcrumbs=redact_http_client_breadcrumbs)
    return {kw.arg: eval(compile(ast.Expression(kw.value), '<startup>', 'eval'), namespace)
            for kw in call.keywords}


@pytest.mark.parametrize('disabled,redactor,expect_private', [
    (False, False, True), (True, False, False),
    (False, True, False), (True, True, False),
])
def test_sdk_mocktransport_breadcrumb_boundary(harness, disabled, redactor, expect_private):
    assert sentry_sdk.VERSION == '2.59.0'
    options = startup_options('production')
    if not disabled:
        options.pop('disabled_integrations')
    if not redactor:
        options.pop('before_send')
    # SDK transport is entirely in memory; harness blocks socket/DNS access.
    with sentry_sdk.isolation_scope() as scope:
        scope.clear_breadcrumbs()
        with sentry_sdk.Client(**options, transport=MemoryTransport) as client:
            scope.set_client(client)
            assert (client.get_integration(HttpxIntegration) is None) == disabled
            with httpx.Client(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200))) as http:
                http.get(PRIVATE_URL, headers={'hue-application-key': 'fabricated-header'})
            assert not harness.sink.records
            sentry_sdk.capture_event({'level': 'error', 'message': 'Sanitized failure'})
            events = client.transport.events
            assert len(events) == 1
            crumbs = events[0].get('breadcrumbs', {}).get('values', [])
            leaked = any(c.get('category') == 'httplib' and
                         'fabricated-only-token' in c.get('data', {}).get('url', '')
                         for c in crumbs)
            assert leaked == expect_private
            assert events[0]['message'] == 'Sanitized failure'


@pytest.mark.parametrize('env', ['development', 'test', 'production'])
def test_startup_dsn_gate_and_error_reporting(monkeypatch, env):
    monkeypatch.setenv('SENTRY_DSN', DSN)
    options = startup_options(env)
    assert options['include_local_variables'] is False
    assert options['send_default_pii'] is False
    assert options['traces_sample_rate'] == 0
    with sentry_sdk.isolation_scope() as scope:
        with sentry_sdk.Client(**options, transport=MemoryTransport) as client:
            scope.set_client(client)
            assert client.dsn == (DSN if env == 'production' else '')
            sentry_sdk.capture_event({'level': 'error', 'message': 'Application failure'})
            if env == 'production':
                assert len(client.transport.events) == 1
            else:
                assert client.transport is None


@pytest.mark.parametrize('name', EMITTERS)
def test_httpcore_debug_never_reaches_callhandlers(harness, name):
    install = harness.ns['suppress_httpcore_debug_logging']
    install()
    install()
    emitter = logging.getLogger(name)
    emitter.setLevel(logging.DEBUG)
    emitter.disabled = False
    assert sum(getattr(f, '_homehub_httpcore_trace_filter', False)
               for f in emitter.filters) == 1
    with patch.object(logging.Logger, 'callHandlers') as dispatch:
        emitter.debug("receive.failed exception=RuntimeError('%s')", PRIVATE_URL)
        emitter.debug("headers=%s", [('hue-application-key', 'fabricated-header')])
        dispatch.assert_not_called()
        emitter.info('Connection status')
        assert dispatch.call_count == 1
        assert dispatch.call_args.args[0].levelno == logging.INFO
        logging.getLogger('unrelated.client').debug('Unrelated diagnostic')
        assert dispatch.call_count == 2


def test_redactor_preserves_app_info_without_payload_access():
    class Unrenderable:
        def __str__(self):
            raise AssertionError('payload rendered')
        __repr__ = __str__
    private = Unrenderable()
    app = {'category': 'app.activity', 'message': 'Mode selected'}
    crumbs = [app] + [{'category': name, 'data': private, 'message': private}
                     for name in ('httplib', 'httplib.child', 'httpx',
                                  'httpx.child', 'httpcore', 'httpcore.http11')]
    error = {'values': [{'type': 'RuntimeError', 'value': 'Sanitized'}]}
    event = {'exception': error, 'breadcrumbs': {'values': crumbs}}
    result = redact_http_client_breadcrumbs(event, {})
    assert result is not event and result['exception'] is error
    assert result['breadcrumbs']['values'] == [app]
    assert len(event['breadcrumbs']['values']) == 7


@pytest.mark.parametrize('crumbs', [None, [], 'malformed', {}, {'values': None},
                                  {'values': [None, {}, {'category': 1}]}])
def test_malformed_breadcrumbs_fail_closed(crumbs):
    result = redact_http_client_breadcrumbs({'message': 'App', 'breadcrumbs': crumbs}, {})
    assert result['message'] == 'App'
    assert not result.get('breadcrumbs', {}).get('values', [])


@pytest.mark.parametrize('event', [None, [], 'malformed'])
def test_malformed_event_dropped(event):
    assert redact_http_client_breadcrumbs(event, {}) is None


def test_startup_order_and_websocket_generic_message():
    source = (ROOT / 'backend/utils/logger.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    setup = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'setup_logging')
    calls = [ast.unparse(n.func) for n in ast.walk(setup) if isinstance(n, ast.Call)]
    assert calls.index('suppress_httpcore_debug_logging') < calls.index('RotatingFileHandler')
    assert calls.index('suppress_hue_httpx_logging') < calls.index('RotatingFileHandler')
    main = (ROOT / 'backend/main.py').read_text(encoding='utf-8')
    assert 'app_logger.error("WebSocket command failed")' in main
    assert 'WebSocket error: {e}' not in main


def test_pinned_httpcore_trace_payloads_blocked(harness):
    import httpcore
    from httpcore._trace import Trace
    assert httpcore.__version__ == '1.0.9'
    emitter = logging.getLogger('httpcore.http11')
    request = httpcore.Request('GET', PRIVATE_URL)
    with patch.object(logging.Logger, 'callHandlers') as dispatch:
        with pytest.raises(RuntimeError):
            with Trace('send_request_headers', emitter, request):
                raise RuntimeError(PRIVATE_URL)
        with Trace('receive_response_headers', emitter, request) as trace:
            trace.return_value = (b'HTTP/1.1', 200, b'OK',
                                  [(b'location', PRIVATE_URL.encode())])
        dispatch.assert_not_called()


def test_sdk_none_dsn_would_fall_back_to_fabricated_env(monkeypatch):
    monkeypatch.setenv('SENTRY_DSN', DSN)
    with sentry_sdk.Client(dsn=None, default_integrations=False,
                           transport=MemoryTransport) as client:
        assert client.dsn == DSN


def test_missing_breadcrumbs_preserves_application_event():
    event = {'level': 'error', 'message': 'App failure'}
    result = redact_http_client_breadcrumbs(event, None)
    assert result == event and result is not event
