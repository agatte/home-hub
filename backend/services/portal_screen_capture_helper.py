#!/usr/bin/env python3
"""GNOME/Wayland ScreenCast helper for Latitude ScreenSync.

Uses one XDG ScreenCast portal session per helper lifetime, then reads a tiny
PipeWire stream through the system GStreamer stack. Only 32x18 RGB frames and
an opaque restore token leave this process; screenshots/video are never stored.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
from typing import Any, Optional

try:
    from gi.repository import Gio, GLib
except ImportError:  # Allows Windows/unit-test import of pure helpers.
    Gio = None  # type: ignore[assignment]
    GLib = None  # type: ignore[assignment]

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"
FRAME_WIDTH = 32
FRAME_HEIGHT = 18
FRAME_STRIDE = FRAME_WIDTH * 3
FRAME_BYTES = FRAME_HEIGHT * FRAME_STRIDE
RESTORE_TOKEN_MAX_BYTES = 4096
REQUEST_TIMEOUT_SECONDS = 180

_STOP_REQUESTED = False
_GST_PROCESS: Optional[subprocess.Popen] = None


class PortalRequestError(RuntimeError):
    def __init__(self, stage: str, response: int, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.response = response


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def _emit_state(state: str, error: Optional[str] = None) -> None:
    payload: dict[str, Any] = {"type": "state", "state": state}
    if error:
        payload["error"] = error[:500]
    _emit(payload)


def _token(prefix: str) -> str:
    return f"homehub_{prefix}_{secrets.token_hex(8)}"


def _restore_token_path() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return root / "home-hub" / "screen-cast-restore-token"


def _load_restore_token(path: Optional[Path] = None) -> Optional[str]:
    path = path or _restore_token_path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if not raw or len(raw) > RESTORE_TOKEN_MAX_BYTES:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    try:
        token = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    if not token or any(ord(char) < 32 for char in token):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return token


def _consume_restore_token(path: Optional[Path] = None) -> Optional[str]:
    path = path or _restore_token_path()
    token = _load_restore_token(path)
    if token is None:
        return None
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return None
    return token


def _save_restore_token(token: str, path: Optional[Path] = None) -> bool:
    if not token or len(token.encode("utf-8")) > RESTORE_TOKEN_MAX_BYTES:
        return False
    path = path or _restore_token_path()
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _deep_unpack(value: Any) -> Any:
    if hasattr(value, "unpack"):
        return _deep_unpack(value.unpack())
    if isinstance(value, dict):
        return {key: _deep_unpack(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_deep_unpack(item) for item in value)
    if isinstance(value, list):
        return [_deep_unpack(item) for item in value]
    return value


def _sender_segment(connection) -> str:
    unique_name = connection.get_unique_name() or ""
    return unique_name.lstrip(":").replace(".", "_")


def _request_path(connection, handle_token: str) -> str:
    return f"/org/freedesktop/portal/desktop/request/{_sender_segment(connection)}/{handle_token}"


def _portal_request(connection, method: str, parameters, handle_token: str):
    expected_path = _request_path(connection, handle_token)
    loop = GLib.MainLoop()
    outcome: dict[str, Any] = {}

    def on_response(_conn, _sender, _path, _iface, _signal, params, _data):
        response, results = _deep_unpack(params)
        outcome["response"] = int(response)
        outcome["results"] = results
        loop.quit()

    subscription = connection.signal_subscribe(
        PORTAL_BUS,
        REQUEST_IFACE,
        "Response",
        expected_path,
        None,
        Gio.DBusSignalFlags.NONE,
        on_response,
        None,
    )
    try:
        reply = connection.call_sync(
            PORTAL_BUS,
            PORTAL_PATH,
            SCREENCAST_IFACE,
            method,
            parameters,
            GLib.VariantType.new("(o)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        returned_path = str(_deep_unpack(reply)[0])
        if returned_path != expected_path and "response" not in outcome:
            connection.signal_unsubscribe(subscription)
            subscription = connection.signal_subscribe(
                PORTAL_BUS,
                REQUEST_IFACE,
                "Response",
                returned_path,
                None,
                Gio.DBusSignalFlags.NONE,
                on_response,
                None,
            )

        def on_timeout():
            outcome["timeout"] = True
            loop.quit()
            return False

        timeout_id = None
        if "response" not in outcome:
            timeout_id = GLib.timeout_add_seconds(REQUEST_TIMEOUT_SECONDS, on_timeout)
            loop.run()
        if timeout_id is not None and hasattr(GLib, "source_remove"):
            try:
                GLib.source_remove(timeout_id)
            except Exception:
                pass
    finally:
        connection.signal_unsubscribe(subscription)

    if outcome.get("timeout"):
        raise RuntimeError(f"portal {method} request timed out")
    return int(outcome["response"]), _deep_unpack(outcome.get("results", {}))


def _create_session(connection) -> str:
    handle_token = _token("create")
    session_token = _token("session")
    options = {
        "handle_token": GLib.Variant("s", handle_token),
        "session_handle_token": GLib.Variant("s", session_token),
    }
    response, results = _portal_request(
        connection,
        "CreateSession",
        GLib.Variant("(a{sv})", (options,)),
        handle_token,
    )
    if response != 0:
        raise PortalRequestError(
            "create_session",
            response,
            f"CreateSession failed with response {response}",
        )
    session_handle = results.get("session_handle")
    if not isinstance(session_handle, str) or not session_handle.startswith("/"):
        raise RuntimeError("CreateSession returned no valid session handle")
    return session_handle


def _select_sources(connection, session_handle: str, restore_token: Optional[str]) -> None:
    handle_token = _token("select")
    options = {
        "handle_token": GLib.Variant("s", handle_token),
        "types": GLib.Variant("u", 1),
        "multiple": GLib.Variant("b", False),
        "cursor_mode": GLib.Variant("u", 1),
        "persist_mode": GLib.Variant("u", 2),
    }
    if restore_token:
        options["restore_token"] = GLib.Variant("s", restore_token)
    response, _results = _portal_request(
        connection,
        "SelectSources",
        GLib.Variant("(oa{sv})", (session_handle, options)),
        handle_token,
    )
    if response != 0:
        raise PortalRequestError(
            "select_sources",
            response,
            f"SelectSources failed with response {response}",
        )


def _start_session(connection, session_handle: str) -> tuple[int, Optional[str]]:
    handle_token = _token("start")
    options = {"handle_token": GLib.Variant("s", handle_token)}
    _emit_state("awaiting_permission")
    response, results = _portal_request(
        connection,
        "Start",
        GLib.Variant("(osa{sv})", (session_handle, "", options)),
        handle_token,
    )
    if response != 0:
        raise PortalRequestError(
            "start",
            response,
            f"Start failed with response {response}",
        )
    streams = results.get("streams")
    if not isinstance(streams, (list, tuple)) or not streams:
        raise RuntimeError("Start returned no PipeWire streams")
    first = streams[0]
    if not isinstance(first, (list, tuple)) or not first:
        raise RuntimeError("Start returned malformed stream metadata")
    node_id = int(first[0])
    restore_token = results.get("restore_token")
    return node_id, restore_token if isinstance(restore_token, str) else None


def _open_pipewire_remote(connection, session_handle: str) -> int:
    reply, fd_list = connection.call_with_unix_fd_list_sync(
        PORTAL_BUS,
        PORTAL_PATH,
        SCREENCAST_IFACE,
        "OpenPipeWireRemote",
        GLib.Variant("(oa{sv})", (session_handle, {})),
        GLib.VariantType.new("(h)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
        None,
    )
    fd_index = int(_deep_unpack(reply)[0])
    return int(fd_list.get(fd_index))


def _close_session(connection, session_handle: Optional[str]) -> None:
    if not session_handle:
        return
    try:
        connection.call_sync(
            PORTAL_BUS,
            session_handle,
            SESSION_IFACE,
            "Close",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            3000,
            None,
        )
    except Exception:
        pass


def _should_retry_without_restore_token(error: PortalRequestError, used_token: bool) -> bool:
    return used_token and error.stage == "select_sources" and error.response == 2


def _open_capture_session(connection, restore_token: Optional[str]):
    token = restore_token
    for _attempt in range(2):
        session_handle = _create_session(connection)
        try:
            _select_sources(connection, session_handle, token)
            node_id, refreshed_token = _start_session(connection, session_handle)
            if refreshed_token:
                _save_restore_token(refreshed_token)
            pipewire_fd = _open_pipewire_remote(connection, session_handle)
            return session_handle, node_id, pipewire_fd
        except PortalRequestError as error:
            _close_session(connection, session_handle)
            if _should_retry_without_restore_token(error, token is not None):
                token = None
                continue
            raise
        except Exception:
            _close_session(connection, session_handle)
            raise
    raise RuntimeError("portal session retry exhausted")


def _gst_command(pipewire_fd: int, node_id: int) -> list[str]:
    return [
        "gst-launch-1.0",
        "-q",
        "pipewiresrc",
        f"fd={pipewire_fd}",
        f"path={node_id}",
        "do-timestamp=true",
        "always-copy=true",
        "!",
        "videoconvert",
        "!",
        "videoscale",
        "!",
        "videorate",
        "!",
        f"video/x-raw,format=RGB,width={FRAME_WIDTH},height={FRAME_HEIGHT},framerate=2/5",
        "!",
        "fdsink",
        "fd=1",
        "sync=false",
    ]


def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _request_stop(_signum=None, _frame=None) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    process = _GST_PROCESS
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
    # Unwind portal waits immediately so main()'s finally closes the PipeWire
    # FD and XDG session. The parent falls back to SIGKILL only if this fails.
    raise SystemExit(0)


def _stream_frames(pipewire_fd: int, node_id: int) -> None:
    global _GST_PROCESS
    process = subprocess.Popen(
        _gst_command(pipewire_fd, node_id),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=(pipewire_fd,),
    )
    _GST_PROCESS = process
    streaming_announced = False
    try:
        assert process.stdout is not None
        while not _STOP_REQUESTED:
            raw = _read_exact(process.stdout, FRAME_BYTES)
            if len(raw) != FRAME_BYTES:
                break
            if not streaming_announced:
                _emit_state("streaming")
                streaming_announced = True
            _emit(
                {
                    "type": "frame",
                    "width": FRAME_WIDTH,
                    "height": FRAME_HEIGHT,
                    "stride": FRAME_STRIDE,
                    "data": base64.b64encode(raw).decode("ascii"),
                }
            )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        _GST_PROCESS = None
    if not _STOP_REQUESTED:
        detail = ""
        if process.stderr is not None:
            try:
                detail = process.stderr.read(2000).decode("utf-8", errors="replace").strip()
            except Exception:
                detail = ""
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"GStreamer PipeWire stream ended unexpectedly{suffix}")


def main() -> int:
    if Gio is None or GLib is None:
        _emit_state("portal_unavailable", "PyGObject/Gio is unavailable")
        return 1

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    session_handle: Optional[str] = None
    pipewire_fd: Optional[int] = None
    connection = None
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        restore_token = _consume_restore_token()
        session_handle, node_id, pipewire_fd = _open_capture_session(
            connection,
            restore_token,
        )
        _stream_frames(pipewire_fd, node_id)
        return 0
    except PortalRequestError as error:
        if error.response == 1:
            _emit_state("permission_denied", "screen sharing permission was not granted")
            return 2
        _emit_state("helper_failed", str(error))
        return 1
    except Exception as error:
        message = str(error) or error.__class__.__name__
        state = "portal_unavailable" if connection is None else "helper_failed"
        _emit_state(state, message)
        return 1
    finally:
        if pipewire_fd is not None:
            try:
                os.close(pipewire_fd)
            except OSError:
                pass
        if connection is not None:
            _close_session(connection, session_handle)


if __name__ == "__main__":
    raise SystemExit(main())
