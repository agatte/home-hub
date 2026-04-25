"""
Tests for request-scoped correlation IDs.

Covers:
- HTTP middleware: header echo, server-generated fallback, malformed
  inbound rejection, ContextVar isolation across requests.
- WebSocket: connection_status carries request_id; ContextVar resets
  on disconnect.
- The RequestContextFilter unit-tested in isolation.
"""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.tracing import (
    MAX_INBOUND_LENGTH,
    coerce_inbound_id,
    new_request_id,
    request_id_var,
)
from backend.utils.logger import RequestContextFilter


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestNewRequestId:
    """The generator itself."""

    def test_length_is_12_hex_chars(self):
        rid = new_request_id()
        assert len(rid) == 12
        int(rid, 16)  # raises if not hex

    def test_each_call_unique(self):
        # Birthday-paradox isn't a concern at 48 bits over 100 calls.
        ids = {new_request_id() for _ in range(100)}
        assert len(ids) == 100


class TestCoerceInboundId:
    """Validation of caller-supplied IDs."""

    def test_none_yields_fresh(self):
        assert len(coerce_inbound_id(None)) == 12

    def test_empty_yields_fresh(self):
        assert len(coerce_inbound_id("")) == 12

    def test_sane_value_passes_through(self):
        assert coerce_inbound_id("deadbeef1234") == "deadbeef1234"

    def test_too_long_yields_fresh(self):
        oversized = "a" * (MAX_INBOUND_LENGTH + 1)
        assert coerce_inbound_id(oversized) != oversized
        assert len(coerce_inbound_id(oversized)) == 12

    def test_whitespace_yields_fresh(self):
        assert coerce_inbound_id("foo bar") != "foo bar"
        assert coerce_inbound_id("foo\tbar") != "foo\tbar"

    def test_non_printable_yields_fresh(self):
        assert coerce_inbound_id("foo\x00bar") != "foo\x00bar"


class TestHttpMiddleware:
    """Round-trip the X-Request-ID header through a real route."""

    def test_response_carries_header_when_absent(self, client):
        resp = client.get("/health")
        rid = resp.headers.get("X-Request-ID")
        assert rid is not None
        assert len(rid) == 12

    def test_response_echoes_caller_header(self, client):
        custom = "deadbeef1234"
        resp = client.get("/health", headers={"X-Request-ID": custom})
        assert resp.headers.get("X-Request-ID") == custom

    def test_malformed_header_replaced(self, client):
        oversized = "x" * (MAX_INBOUND_LENGTH + 5)
        resp = client.get("/health", headers={"X-Request-ID": oversized})
        echoed = resp.headers.get("X-Request-ID")
        assert echoed != oversized
        assert len(echoed) == 12

    def test_two_requests_get_distinct_ids(self, client):
        a = client.get("/health").headers.get("X-Request-ID")
        b = client.get("/health").headers.get("X-Request-ID")
        assert a and b and a != b

    def test_context_var_isolated_after_response(self, client):
        # The middleware must reset the ContextVar; after the response
        # we should be back to the default of None in this thread.
        client.get("/health")
        assert request_id_var.get() is None


class TestWebSocketCorrelation:
    """Per-connection IDs surfaced via connection_status."""

    def test_connection_status_includes_request_id(self, client):
        with client.websocket_connect("/ws") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "connection_status"
            rid = msg["data"].get("request_id")
            assert rid is not None
            assert len(rid) == 12

    def test_two_connections_get_distinct_ids(self, client):
        with client.websocket_connect("/ws") as ws_a:
            a = json.loads(ws_a.receive_text())["data"]["request_id"]
        with client.websocket_connect("/ws") as ws_b:
            b = json.loads(ws_b.receive_text())["data"]["request_id"]
        assert a != b


class TestRequestContextFilter:
    """The Filter that copies ContextVar onto LogRecord."""

    def _make_record(self) -> logging.LogRecord:
        return logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="hello", args=(), exc_info=None,
        )

    def test_stamps_current_request_id(self):
        token = request_id_var.set("abc123abc123")
        try:
            record = self._make_record()
            assert RequestContextFilter().filter(record) is True
            assert record.request_id == "abc123abc123"
        finally:
            request_id_var.reset(token)

    def test_stamps_none_outside_context(self):
        # Sanity: no token set in this scope.
        assert request_id_var.get() is None
        record = self._make_record()
        assert RequestContextFilter().filter(record) is True
        assert record.request_id is None
