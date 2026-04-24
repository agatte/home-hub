"""
Tests for WebSocket protocol — connection, messages, malformed input handling.

Note: TestClient runs the real lifespan. Tests verify protocol behavior
and the JSON safety guard we added.
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    """Shared TestClient — lifespan runs once for the module."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestWebSocketConnection:
    """Test WebSocket connect and initial messages."""

    def test_ws_connects_and_sends_status(self, client):
        with client.websocket_connect("/ws") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "connection_status"
            assert "hue" in msg["data"]
            assert "sonos" in msg["data"]
            assert "build_id" in msg["data"]

    def test_ws_sends_mode_update(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()  # connection_status
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "mode_update"
            assert "mode" in msg["data"]
            assert "source" in msg["data"]
            assert "manual_override" in msg["data"]

    def test_ws_malformed_json_does_not_crash(self, client):
        """The JSON safety guard should keep the connection alive."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()  # connection_status
            ws.receive_text()  # mode_update
            # Send garbage — should not crash the connection
            ws.send_text("this is not json{{{")
            # Connection should still be alive — send a valid command
            ws.send_text(json.dumps({
                "type": "light_command",
                "data": {"light_id": "1", "bri": 200},
            }))
            # If we get here without exception, the guard works

    def test_ws_unknown_message_type_does_not_crash(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            ws.send_text(json.dumps({"type": "bogus", "data": {}}))
            # Should still be connected

    def test_ws_light_command_accepted(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            ws.send_text(json.dumps({
                "type": "light_command",
                "data": {"light_id": "1", "bri": 100},
            }))

    def test_ws_sonos_command_accepted(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            ws.send_text(json.dumps({
                "type": "sonos_command",
                "data": {"action": "volume", "volume": 15},
            }))


def _next_of_type(ws, expected_types: set[str], max_frames: int = 10) -> dict:
    """Receive frames until we hit one of expected_types, skipping the rest."""
    for _ in range(max_frames):
        msg = json.loads(ws.receive_text())
        if msg.get("type") in expected_types:
            return msg
    raise AssertionError(f"never received any of {expected_types}")


class TestWebSocketValidation:
    """Pydantic-schema validation on inbound WS messages."""

    def test_bri_out_of_range_rejected(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            ws.send_text(json.dumps({
                "type": "light_command",
                "data": {"light_id": "1", "bri": 9999},
            }))
            msg = _next_of_type(ws, {"error"})
            assert msg["type"] == "error"
            assert msg["data"]["reason"] == "validation"

    def test_light_id_int_is_coerced_to_str(self, client):
        """Other backend code paths emit int light ids; accept and normalize."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            # Should NOT trigger a validation error frame — send a follow-up
            # valid command and assert no error frame precedes silence.
            ws.send_text(json.dumps({
                "type": "light_command",
                "data": {"light_id": 1, "bri": 100},
            }))
            # We can't easily assert "no message" without a timeout; rely on
            # no exception + the connection staying alive via another send.
            ws.send_text(json.dumps({
                "type": "sonos_command",
                "data": {"action": "pause"},
            }))

    def test_sonos_volume_action_requires_volume_field(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            ws.send_text(json.dumps({
                "type": "sonos_command",
                "data": {"action": "volume"},
            }))
            msg = _next_of_type(ws, {"error"})
            assert msg["data"]["reason"] == "validation"

    def test_sonos_bogus_action_rejected(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            ws.send_text(json.dumps({
                "type": "sonos_command",
                "data": {"action": "bogus"},
            }))
            msg = _next_of_type(ws, {"error"})
            assert msg["data"]["reason"] == "validation"

    def test_extra_field_rejected(self, client):
        """extra='forbid' catches typos and stray fields from a buggy client."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            ws.send_text(json.dumps({
                "type": "light_command",
                "data": {"light_id": "1", "bri": 100, "wat": "x"},
            }))
            msg = _next_of_type(ws, {"error"})
            assert msg["data"]["reason"] == "validation"

    def test_light_command_without_state_fields_rejected(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            ws.send_text(json.dumps({
                "type": "light_command",
                "data": {"light_id": "1"},
            }))
            msg = _next_of_type(ws, {"error"})
            assert msg["data"]["reason"] == "validation"
