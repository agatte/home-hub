"""Host-side transient Windows Sandbox runner for navigation-v1 replay."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .validate import REQUIRED_MEMBERS, load_fixture_bundle

STAGE_SCHEMA_ID = "homehub.replay.stage.v1"
RESULT_SCHEMA_ID = "homehub.replay.navigation.result.v1"
MIN_WINDOWS_BUILD = 26100
SANDBOX_START_TIMEOUT_SECONDS = 45
REPLAY_READY_TIMEOUT_SECONDS = 90
EXPORT_READY_TIMEOUT_SECONDS = 15
COMMAND_TIMEOUT_SECONDS = 20
CO_E_APPSINGLEUSE = 0x800401F6

GUEST_STAGE = r"C:\HomeHubReplayStage"
GUEST_EXPORT = r"C:\HomeHubReplayExport"
GUEST_DONE = r"C:\HomeHubReplayState\done.marker"
GUEST_STATUS = r"C:\HomeHubReplayState\status.json"
GUEST_RESULT = r"C:\HomeHubReplayState\result.json"

PROJECT_FILES = (
    "backend/__init__.py",
    "backend/replay/__init__.py",
    "backend/replay/checkpoints.py",
    "backend/replay/clock.py",
    "backend/replay/isolated_child.py",
    "backend/replay/navigation_v1.py",
    "backend/replay/scheduler.py",
    "backend/replay/schema.py",
    "backend/replay/sinks.py",
    "backend/replay/validate.py",
    "backend/replay/windows_guest_broker.py",
    "backend/services/__init__.py",
    "backend/services/automation_constants.py",
    "backend/services/camera_constants.py",
    "backend/services/decision_clock.py",
    "backend/services/engine_state.py",
    "backend/services/heartbeat.py",
    "backend/services/light_applicator.py",
    "backend/services/light_override_manager.py",
    "backend/services/light_state_calculator.py",
    "backend/services/lighting_transition_boundary.py",
    "backend/services/navigation_activity_policy.py",
    "backend/services/presence_fusion.py",
    "backend/services/transit_lighting_service.py",
    "backend/services/working_light_composition.py",
)

DEPENDENCY_ENTRIES = (
    "annotated_types",
    "pydantic",
    "pydantic_core",
    "typing_extensions.py",
    "typing_inspection",
    "tzdata",
)

RUNTIME_TOP_LEVEL_FILES = (
    "python.exe",
    "pythonw.exe",
    "python3.dll",
    "python313.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
)

_RUNTIME_DIRS = ("DLLs",)
_EXCLUDED_RUNTIME_DIR_NAMES = {
    "__pycache__",
    "ensurepip",
    "idlelib",
    "site-packages",
    "test",
    "tkinter",
    "turtledemo",
}
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class WindowsSandboxReplayError(RuntimeError):
    """A transient Windows Sandbox replay could not be established or completed."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _windows_build() -> int | None:
    if os.name != "nt":
        return None
    try:
        return int(platform.version().split(".")[-1])
    except (TypeError, ValueError):
        return None


def _find_wsb() -> str | None:
    return shutil.which("wsb.exe") or shutil.which("wsb")


def backend_available() -> bool:
    build = _windows_build()
    return bool(
        build is not None
        and build >= MIN_WINDOWS_BUILD
        and os.environ.get("USERNAME", "").casefold() != "wdagutilityaccount"
        and _find_wsb()
    )


def _copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise WindowsSandboxReplayError(f"stage source must be a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree_filtered(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise WindowsSandboxReplayError(f"stage source must be a regular directory: {source}")
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
        ),
    )


def _copy_runtime(base_prefix: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    copied = set()
    for name in RUNTIME_TOP_LEVEL_FILES:
        source = base_prefix / name
        if source.is_file():
            _copy_file(source, destination / name)
            copied.add(name)
    for required in ("python.exe", "pythonw.exe", "python313.dll"):
        if required not in copied:
            raise WindowsSandboxReplayError(f"Python runtime is missing required file {required}")

    for name in _RUNTIME_DIRS:
        source = base_prefix / name
        if source.is_dir():
            _copy_tree_filtered(source, destination / name)

    lib_source = base_prefix / "Lib"
    if not lib_source.is_dir():
        raise WindowsSandboxReplayError("Python runtime has no Lib directory")

    def ignore_lib(directory: str, names: list[str]) -> set[str]:
        ignored = {
            name
            for name in names
            if name in _EXCLUDED_RUNTIME_DIR_NAMES
            or name == "__pycache__"
            or name.endswith((".pyc", ".pyo"))
        }
        if Path(directory) == lib_source:
            ignored.add("site-packages")
        return ignored

    shutil.copytree(lib_source, destination / "Lib", ignore=ignore_lib)


def _copy_dependencies(site_packages: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for name in DEPENDENCY_ENTRIES:
        source = site_packages / name
        if source.is_file():
            _copy_file(source, destination / name)
        elif source.is_dir():
            _copy_tree_filtered(source, destination / name)
        else:
            raise WindowsSandboxReplayError(f"required replay dependency is unavailable: {name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_manifest(stage_root: Path) -> dict[str, Any]:
    files = {}
    for path in sorted(stage_root.rglob("*")):
        if path.is_file() and path.name != "stage_manifest.json":
            files[path.relative_to(stage_root).as_posix()] = _sha256(path)
    if not files:
        raise WindowsSandboxReplayError("replay stage unexpectedly contains no files")
    return {"schema_id": STAGE_SCHEMA_ID, "files": files}


def _write_guest_helpers(stage_root: Path) -> None:
    launch = (
        "@echo off\r\n"
        "setlocal\r\n"
        f'"{GUEST_STAGE}\\runtime\\python.exe" -I -S -B '
        f'"{GUEST_STAGE}\\project\\backend\\replay\\windows_guest_broker.py"\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    )
    poll = f'@echo off\r\nif exist "{GUEST_DONE}" exit /b 0\r\nexit /b 3\r\n'
    probe_export = (
        "@echo off\r\n"
        f'if not exist "{GUEST_EXPORT}" exit /b 4\r\n'
        f'>"{GUEST_EXPORT}\\share_ready.marker" echo ready\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    )
    export = (
        "@echo off\r\n"
        f'if not exist "{GUEST_EXPORT}" exit /b 4\r\n'
        f'>"{GUEST_EXPORT}\\export_begin.marker" echo begin\r\n'
        f'if not exist "{GUEST_STATUS}" exit /b 5\r\n'
        f'>"{GUEST_EXPORT}\\status_source_seen.marker" echo seen\r\n'
        f'type "{GUEST_STATUS}" > "{GUEST_EXPORT}\\status.json" || exit /b 6\r\n'
        f'>"{GUEST_EXPORT}\\status_written.marker" echo written\r\n'
        f'if exist "{GUEST_RESULT}" type "{GUEST_RESULT}" > '
        f'"{GUEST_EXPORT}\\result.json" || exit /b 7\r\n'
        f'if exist "{GUEST_RESULT}" >"{GUEST_EXPORT}\\result_written.marker" echo written\r\n'
        f'>"{GUEST_EXPORT}\\export_complete.marker" echo complete\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    )
    for name, content in (
        ("launch_guest.cmd", launch),
        ("poll_ready.cmd", poll),
        ("probe_export.cmd", probe_export),
        ("export_result.cmd", export),
    ):
        (stage_root / name).write_text(content, encoding="ascii", newline="")


def build_stage(bundle_path: str | Path, stage_root: Path) -> Path:
    """Build the exact read-only artifact exposed to the transient replay VM."""

    bundle_root = Path(bundle_path).resolve()
    load_fixture_bundle(bundle_root)

    if stage_root.exists():
        raise WindowsSandboxReplayError("stage destination already exists")
    stage_root.mkdir(parents=True)

    repo_root = repository_root()
    project_root = stage_root / "project"
    for relative in PROJECT_FILES:
        source = repo_root / relative
        if not source.is_file():
            raise WindowsSandboxReplayError(f"reviewed project closure file is missing: {relative}")
        _copy_file(source, project_root / relative)

    staged_bundle = stage_root / "bundle"
    staged_bundle.mkdir()
    for name in sorted(REQUIRED_MEMBERS):
        _copy_file(bundle_root / name, staged_bundle / name)

    base_prefix = Path(sys.base_prefix).resolve()
    _copy_runtime(base_prefix, stage_root / "runtime")

    site_packages = Path(sys.prefix).resolve() / "Lib" / "site-packages"
    if not site_packages.is_dir():
        raise WindowsSandboxReplayError(
            "operational replay must run from the restored HomeHub virtualenv"
        )
    _copy_dependencies(site_packages, stage_root / "deps")
    _write_guest_helpers(stage_root)

    manifest = _stage_manifest(stage_root)
    (stage_root / "stage_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return stage_root


def build_wsb_configuration(stage_root: Path) -> str:
    stage_text = escape(str(stage_root.resolve()))
    command = escape(f"cmd.exe /d /q /c {GUEST_STAGE}\\launch_guest.cmd")
    return (
        "<Configuration>"
        "<vGPU>Disable</vGPU>"
        "<Networking>Disable</Networking>"
        "<AudioInput>Disable</AudioInput>"
        "<VideoInput>Disable</VideoInput>"
        "<ProtectedClient>Enable</ProtectedClient>"
        "<PrinterRedirection>Disable</PrinterRedirection>"
        "<ClipboardRedirection>Disable</ClipboardRedirection>"
        "<MemoryInMB>3072</MemoryInMB>"
        "<MappedFolders><MappedFolder>"
        f"<HostFolder>{stage_text}</HostFolder>"
        f"<SandboxFolder>{GUEST_STAGE}</SandboxFolder>"
        "<ReadOnly>true</ReadOnly>"
        "</MappedFolder></MappedFolders>"
        "<LogonCommand>"
        f"<Command>{command}</Command>"
        "</LogonCommand>"
        "</Configuration>"
    )


def _walk_json_for_uuid(value: Any) -> str | None:
    if isinstance(value, str) and _UUID_RE.fullmatch(value):
        return value
    if isinstance(value, dict):
        preferred = ("id", "sandboxId", "sandbox_id")
        for key in preferred:
            if key in value:
                found = _walk_json_for_uuid(value[key])
                if found:
                    return found
        for child in value.values():
            found = _walk_json_for_uuid(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _walk_json_for_uuid(child)
            if found:
                return found
    return None


def parse_sandbox_id(raw_output: str) -> str:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise WindowsSandboxReplayError(
            "Windows Sandbox CLI returned invalid JSON from start"
        ) from exc
    sandbox_id = _walk_json_for_uuid(parsed)
    if sandbox_id is None:
        raise WindowsSandboxReplayError("Windows Sandbox CLI did not return a sandbox ID")
    return sandbox_id


def parse_sandbox_inventory(raw_output: str) -> list[dict[str, str]]:
    """Parse the fail-closed raw session inventory returned by `wsb list --raw`."""

    if not raw_output.strip():
        return []
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise WindowsSandboxReplayError(
            "Windows Sandbox CLI returned invalid JSON from list"
        ) from exc

    if isinstance(parsed, list):
        records = parsed
    elif isinstance(parsed, dict):
        if "WindowsSandboxEnvironments" in parsed:
            records = parsed["WindowsSandboxEnvironments"]
        elif "sessions" in parsed:
            records = parsed["sessions"]
        elif "items" in parsed:
            records = parsed["items"]
        elif any(key in parsed for key in ("id", "Id", "ID", "sandboxId", "sandbox_id")):
            records = [parsed]
        else:
            raise WindowsSandboxReplayError(
                "Windows Sandbox CLI returned an unsupported list JSON shape"
            )
    else:
        raise WindowsSandboxReplayError(
            "Windows Sandbox CLI returned an unsupported list JSON shape"
        )

    if not isinstance(records, list):
        raise WindowsSandboxReplayError(
            "Windows Sandbox CLI returned an unsupported list JSON shape"
        )

    normalized: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            raise WindowsSandboxReplayError(
                "Windows Sandbox CLI returned a malformed session record"
            )
        sandbox_id = next(
            (record[key] for key in ("id", "Id", "ID", "sandboxId", "sandbox_id") if key in record),
            None,
        )
        status = next(
            (record[key] for key in ("status", "Status", "state", "State") if key in record),
            None,
        )
        if not isinstance(sandbox_id, str) or not _UUID_RE.fullmatch(sandbox_id):
            raise WindowsSandboxReplayError(
                "Windows Sandbox CLI session record has no valid sandbox ID"
            )
        if not isinstance(status, str) or status.casefold() not in {"running", "stopped"}:
            raise WindowsSandboxReplayError(
                "Windows Sandbox CLI session record has an unsupported status"
            )
        normalized.append(
            {
                "id": sandbox_id,
                "status": status.casefold(),
            }
        )
    return normalized


def _run_command(
    args: list[str],
    *,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WindowsSandboxReplayError(
            f"failed to execute Windows Sandbox CLI: {args[1] if len(args) > 1 else args[0]}"
        ) from exc
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise WindowsSandboxReplayError(
            f"Windows Sandbox CLI command failed ({completed.returncode}): {detail}"
        )
    return completed


def _exclusive_access_error() -> WindowsSandboxReplayError:
    return WindowsSandboxReplayError(
        "operational replay requires exclusive Windows Sandbox access; "
        "close the existing Windows Sandbox session and retry"
    )


def _assert_no_running_sandbox(wsb: str) -> None:
    completed = _run_command([wsb, "list", "--raw"], check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise WindowsSandboxReplayError(
            "failed to inventory existing Windows Sandbox sessions"
            + (f": {detail}" if detail else "")
        )
    sessions = parse_sandbox_inventory(completed.stdout)
    if any(session["status"] == "running" for session in sessions):
        raise _exclusive_access_error()


def _start_sandbox(wsb: str, config: str) -> str:
    completed = _run_command(
        [wsb, "start", "--raw", "--config", config],
        timeout=SANDBOX_START_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        if completed.returncode & 0xFFFFFFFF == CO_E_APPSINGLEUSE:
            raise _exclusive_access_error()
        detail = (completed.stderr or completed.stdout).strip()
        raise WindowsSandboxReplayError(
            f"Windows Sandbox CLI command failed ({completed.returncode}): {detail}"
        )
    return parse_sandbox_id(completed.stdout)


def _exec(
    wsb: str,
    sandbox_id: str,
    command: str,
) -> subprocess.CompletedProcess[str]:
    guest_command = command
    if command.casefold().endswith(".cmd"):
        guest_command = f'cmd.exe /d /q /c "{command}"'
    return _run_command(
        [
            wsb,
            "exec",
            "--id",
            sandbox_id,
            "-c",
            guest_command,
            "-r",
            "System",
        ],
        check=False,
    )


def _wait_for_replay(
    wsb: str,
    sandbox_id: str,
    *,
    timeout: float = REPLAY_READY_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout
    poll_command = f"{GUEST_STAGE}\\poll_ready.cmd"
    last_code = None
    while time.monotonic() < deadline:
        completed = _exec(wsb, sandbox_id, poll_command)
        last_code = completed.returncode
        if completed.returncode == 0:
            return
        time.sleep(0.5)
    raise WindowsSandboxReplayError(
        f"isolated replay did not become ready before timeout; last poll={last_code}"
    )


def _share_export(
    wsb: str,
    sandbox_id: str,
    export_root: Path,
) -> None:
    _run_command(
        [
            wsb,
            "share",
            "--id",
            sandbox_id,
            "-f",
            str(export_root),
            "-s",
            GUEST_EXPORT,
            "--allow-write",
        ],
        check=True,
    )


def _wait_for_export_share_ready(
    wsb: str,
    sandbox_id: str,
    export_root: Path,
    *,
    timeout: float = EXPORT_READY_TIMEOUT_SECONDS,
) -> None:
    """Prove the dynamic writable share is host-backed before exporting replay data."""

    marker = export_root / "share_ready.marker"
    probe_command = f"{GUEST_STAGE}\\probe_export.cmd"
    deadline = time.monotonic() + timeout
    last_code: int | None = None

    while time.monotonic() < deadline:
        completed = _exec(wsb, sandbox_id, probe_command)
        last_code = completed.returncode
        if marker.is_file():
            try:
                if marker.read_text(encoding="ascii").strip() == "ready":
                    return
            except OSError:
                pass
        time.sleep(0.1)

    raise WindowsSandboxReplayError(
        "writable replay export share did not become host-backed before timeout; "
        f"last probe={last_code}"
    )


def _export_result(wsb: str, sandbox_id: str) -> None:
    completed = _exec(
        wsb,
        sandbox_id,
        f"{GUEST_STAGE}\\export_result.cmd",
    )
    if completed.returncode != 0:
        raise WindowsSandboxReplayError(
            f"replay result export failed with exit code {completed.returncode}"
        )


def _wait_for_export_visibility(
    export_root: Path,
    *,
    timeout: float = EXPORT_READY_TIMEOUT_SECONDS,
) -> None:
    """Wait for the dynamic share to become visible on the host after guest copy."""

    status_path = export_root / "status.json"
    result_path = export_root / "result.json"
    complete_path = export_root / "export_complete.marker"
    deadline = time.monotonic() + timeout
    last_status: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        if status_path.is_file():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                status = None
            if isinstance(status, dict):
                last_status = status
                if not complete_path.is_file():
                    time.sleep(0.1)
                    continue
                if status.get("status") != "ok":
                    return
                if result_path.is_file():
                    try:
                        result = json.loads(result_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        result = None
                    if isinstance(result, dict):
                        return
        time.sleep(0.1)

    visible = sorted(path.name for path in export_root.iterdir()) if export_root.is_dir() else []
    raise WindowsSandboxReplayError(
        "replay sandbox export did not become visible on the host before timeout; "
        f"visible={visible!r}, status={last_status!r}"
    )


def _stop_sandbox(wsb: str, sandbox_id: str) -> None:
    _run_command(
        [wsb, "stop", "--id", sandbox_id],
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )


def _load_export(export_root: Path) -> dict[str, Any]:
    status_path = export_root / "status.json"
    if not status_path.is_file():
        raise WindowsSandboxReplayError("replay sandbox exported no status")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WindowsSandboxReplayError("replay sandbox exported invalid status JSON") from exc
    if status.get("status") != "ok":
        raise WindowsSandboxReplayError(f"isolated replay failed: {status.get('message', status)}")

    result_path = export_root / "result.json"
    if not result_path.is_file():
        raise WindowsSandboxReplayError("replay sandbox exported no result")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WindowsSandboxReplayError("replay sandbox exported invalid result JSON") from exc
    if result.get("schema_id") != RESULT_SCHEMA_ID or result.get("status") != "ok":
        raise WindowsSandboxReplayError("replay sandbox result failed schema/status checks")
    self_test = result.get("isolation_self_test")
    if not isinstance(self_test, dict) or self_test.get("status") != "passed":
        raise WindowsSandboxReplayError("replay sandbox did not pass its isolation self-test")
    return result


def run_windows_sandbox_replay(bundle_path: str | Path) -> dict[str, Any]:
    """Execute one validated bundle in a fresh hardware-isolated Windows Sandbox."""

    if not backend_available():
        raise WindowsSandboxReplayError(
            "Windows Sandbox replay backend is unavailable on this host"
        )
    wsb = _find_wsb()
    assert wsb is not None
    _assert_no_running_sandbox(wsb)

    with tempfile.TemporaryDirectory(prefix="homehub-replay-stage-") as stage_dir:
        with tempfile.TemporaryDirectory(prefix="homehub-replay-export-") as export_dir:
            stage_root = Path(stage_dir) / "stage"
            export_root = Path(export_dir)
            build_stage(bundle_path, stage_root)
            config = build_wsb_configuration(stage_root)

            sandbox_id: str | None = None
            try:
                sandbox_id = _start_sandbox(wsb, config)
                _wait_for_replay(wsb, sandbox_id)
                # The writable result share is deliberately absent until the
                # replay child has exited and the broker has closed its pipe.
                _share_export(wsb, sandbox_id, export_root)
                _wait_for_export_share_ready(wsb, sandbox_id, export_root)
                _export_result(wsb, sandbox_id)
                _wait_for_export_visibility(export_root)
                return _load_export(export_root)
            finally:
                if sandbox_id is not None:
                    _stop_sandbox(wsb, sandbox_id)
