import base64
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.services.portal_screen_capture_helper as helper
import backend.services.screen_sync as screen_sync_module
from backend.services.screen_sync import (
    LaptopLoopbackCapture,
    PortalCaptureError,
    _parse_portal_message,
)


class _FakeVariant:
    def __init__(self, signature, value):
        self.signature = signature
        self.value = value


@pytest.fixture
def fake_glib(monkeypatch):
    fake = SimpleNamespace(Variant=_FakeVariant)
    monkeypatch.setattr(helper, "GLib", fake)
    return fake


def test_restore_token_is_consumed_then_refreshed_atomically(tmp_path):
    path = tmp_path / "state" / "screen-cast-token"
    helper._save_restore_token("old-token", path)
    assert helper._load_restore_token(path) == "old-token"
    assert helper._consume_restore_token(path) == "old-token"
    assert not path.exists()

    helper._save_restore_token("new-token", path)
    assert helper._load_restore_token(path) == "new-token"
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_invalid_restore_token_is_discarded(tmp_path):
    path = tmp_path / "token"
    path.write_bytes(b"x" * (helper.RESTORE_TOKEN_MAX_BYTES + 1))
    assert helper._load_restore_token(path) is None
    assert not path.exists()

    path.write_bytes(b"\xff")
    assert helper._load_restore_token(path) is None
    assert not path.exists()


def test_only_select_sources_other_error_retries_without_restore_token():
    retryable = helper.PortalRequestError("select_sources", 2, "invalid restore")
    cancelled = helper.PortalRequestError("select_sources", 1, "cancelled")
    start_error = helper.PortalRequestError("start", 2, "failed")

    assert helper._should_retry_without_restore_token(retryable, True) is True
    assert helper._should_retry_without_restore_token(retryable, False) is False
    assert helper._should_retry_without_restore_token(cancelled, True) is False
    assert helper._should_retry_without_restore_token(start_error, True) is False


def test_select_sources_requests_monitor_hidden_cursor_and_persistence(
    monkeypatch,
    fake_glib,
):
    calls = []

    def fake_request(connection, method, parameters, handle_token):
        calls.append((connection, method, parameters, handle_token))
        return 0, {}

    monkeypatch.setattr(helper, "_portal_request", fake_request)
    helper._select_sources("bus", "/session/test", "restore-123")

    _connection, method, parameters, handle_token = calls[0]
    assert method == "SelectSources"
    assert handle_token.startswith("homehub_select_")
    session_handle, options = parameters.value
    assert session_handle == "/session/test"
    assert options["types"].value == 1
    assert options["multiple"].value is False
    assert options["cursor_mode"].value == 1
    assert options["persist_mode"].value == 2
    assert options["restore_token"].value == "restore-123"


def test_start_extracts_stream_and_refresh_token(monkeypatch, fake_glib):
    emitted = []

    def fake_request(_connection, method, _parameters, _handle_token):
        assert method == "Start"
        return 0, {
            "streams": [(77, {"source_type": 1})],
            "restore_token": "fresh-token",
        }

    monkeypatch.setattr(helper, "_portal_request", fake_request)
    monkeypatch.setattr(helper, "_emit_state", lambda state, error=None: emitted.append(state))

    node_id, token = helper._start_session("bus", "/session/test")

    assert emitted == ["awaiting_permission"]
    assert node_id == 77
    assert token == "fresh-token"


def test_gstreamer_command_targets_portal_fd_and_tiny_rgb_stream():
    command = helper._gst_command(9, 77)
    joined = " ".join(command)
    assert "pipewiresrc" in command
    assert "fd=9" in command
    assert "path=77" in command
    assert "format=RGB" in joined
    assert f"width={helper.FRAME_WIDTH}" in joined
    assert f"height={helper.FRAME_HEIGHT}" in joined
    assert "framerate=2/5" in joined
    assert "fdsink" in command


def test_parent_parser_accepts_tiny_frame_and_rejects_bad_length():
    raw = bytes([1, 2, 3, 4, 5, 6] * 2)
    message = {
        "type": "frame",
        "width": 2,
        "height": 2,
        "stride": 6,
        "data": base64.b64encode(raw).decode("ascii"),
    }
    parsed = _parse_portal_message((helper.json.dumps(message) + "\n").encode())
    assert parsed["type"] == "frame"
    assert parsed["pixels"] == [
        (1, 2, 3),
        (4, 5, 6),
        (1, 2, 3),
        (4, 5, 6),
    ]

    message["data"] = base64.b64encode(raw[:-1]).decode("ascii")
    with pytest.raises(PortalCaptureError, match="inconsistent frame data"):
        _parse_portal_message((helper.json.dumps(message) + "\n").encode())


class _FakePortalProcess:
    def __init__(self, messages):
        self.messages = list(messages)
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def read_message(self):
        return self.messages.pop(0)

    async def stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_portal_loop_delivers_frame_and_cleans_helper(monkeypatch):
    fake = _FakePortalProcess(
        [
            {"type": "state", "state": "awaiting_permission", "error": None},
            {"type": "frame", "pixels": [(1, 2, 3)] * 10},
        ]
    )
    loopback = LaptopLoopbackCapture(portal_helper_factory=lambda: fake)
    loopback._running = True
    delivered = []

    monkeypatch.setattr(screen_sync_module.sys, "platform", "linux")
    monkeypatch.setattr(
        screen_sync_module,
        "_pick_dominant",
        lambda _pixels, _picker: (12, 34, 56),
    )

    async def deliver(rgb):
        delivered.append(rgb)
        loopback._running = False

    monkeypatch.setattr(loopback, "_deliver_color", deliver)
    await loopback._portal_loop()

    assert fake.started is True
    assert fake.stopped is True
    assert delivered == [(12, 34, 56)]
    assert loopback.capture_health["state"] == "streaming"
    assert loopback.capture_health["last_success_at"] is not None


@pytest.mark.asyncio
async def test_permission_denied_holds_failure_state_without_restart_loop(monkeypatch):
    fake = _FakePortalProcess(
        [
            {
                "type": "state",
                "state": "permission_denied",
                "error": "screen sharing permission was not granted",
            },
        ]
    )
    loopback = LaptopLoopbackCapture(portal_helper_factory=lambda: fake)
    loopback._running = True
    monkeypatch.setattr(screen_sync_module.sys, "platform", "linux")

    await loopback._portal_loop()

    assert fake.stopped is True
    assert loopback.running is True
    assert loopback.capture_health["state"] == "permission_denied"
    assert loopback.capture_health["consecutive_failures"] == 1
    assert "permission" in loopback.capture_health["last_error"]


class _BlockingPortalProcess:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.waiting = None

    async def start(self):
        self.started = True

    async def read_message(self):
        import asyncio

        self.waiting = asyncio.Event()
        await self.waiting.wait()
        raise AssertionError("unreachable")

    async def stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_stop_cancels_blocking_portal_helper(monkeypatch):
    fake = _BlockingPortalProcess()
    monkeypatch.setattr(screen_sync_module.sys, "platform", "linux")
    loopback = LaptopLoopbackCapture(portal_helper_factory=lambda: fake)

    await loopback.start()
    for _ in range(3):
        await __import__("asyncio").sleep(0)
    await loopback.stop()

    assert fake.started is True
    assert fake.stopped is True
    assert loopback.running is False
    assert loopback.capture_health["state"] == "stopped"


def test_capture_health_exposes_backend_and_state(monkeypatch):
    monkeypatch.setattr(screen_sync_module.sys, "platform", "linux")
    loopback = LaptopLoopbackCapture()
    assert loopback.capture_health["backend"] == "portal"
    assert loopback.capture_health["state"] == "stopped"


def test_open_session_retries_stale_restore_token_and_saves_refresh(monkeypatch):
    sessions = iter(["/session/old", "/session/new"])
    selected = []
    closed = []
    saved = []

    monkeypatch.setattr(helper, "_create_session", lambda _connection: next(sessions))

    def select(_connection, session_handle, restore_token):
        selected.append((session_handle, restore_token))
        if restore_token == "stale-token":
            raise helper.PortalRequestError("select_sources", 2, "stale")

    monkeypatch.setattr(helper, "_select_sources", select)
    monkeypatch.setattr(helper, "_start_session", lambda *_args: (77, "fresh-token"))
    monkeypatch.setattr(helper, "_open_pipewire_remote", lambda *_args: 9)
    monkeypatch.setattr(helper, "_close_session", lambda _conn, session: closed.append(session))
    monkeypatch.setattr(helper, "_save_restore_token", lambda token: saved.append(token) or True)

    result = helper._open_capture_session("bus", "stale-token")

    assert result == ("/session/new", 77, 9)
    assert selected == [
        ("/session/old", "stale-token"),
        ("/session/new", None),
    ]
    assert closed == ["/session/old"]
    assert saved == ["fresh-token"]


def test_restore_token_write_failure_is_nonfatal(tmp_path):
    not_a_directory = tmp_path / "occupied"
    not_a_directory.write_text("file", encoding="utf-8")
    assert helper._save_restore_token("token", not_a_directory / "child") is False


def test_helper_sigterm_unwinds_and_terminates_stream(monkeypatch):
    class FakeProcess:
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    process = FakeProcess()
    monkeypatch.setattr(helper, "_GST_PROCESS", process)
    monkeypatch.setattr(helper, "_STOP_REQUESTED", False)

    with pytest.raises(SystemExit) as stopped:
        helper._request_stop()

    assert stopped.value.code == 0
    assert helper._STOP_REQUESTED is True
    assert process.terminated is True


def test_parent_parser_rejects_non_base64_frame():
    message = {
        "type": "frame",
        "width": 1,
        "height": 1,
        "stride": 3,
        "data": "%%%not-base64%%%",
    }
    with pytest.raises(PortalCaptureError, match="invalid frame data"):
        _parse_portal_message((helper.json.dumps(message) + "\n").encode())
