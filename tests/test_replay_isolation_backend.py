"""Operational isolation backend contract for navigation-v1 replay."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

import backend.replay.isolated_runner as isolated_runner
import backend.replay.windows_sandbox_runner as sandbox_runner
from tests.test_replay_bundle import _write_bundle
from tests.test_replay_navigation_root import _project_import_closure, _project_module_path


def test_windows_temp_root_inherits_acl_and_retries_only_collisions(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_runner.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sandbox_runner, "os", SimpleNamespace(name="nt"))
    prefix = "homehub-replay-stage-"
    collision = tmp_path / f"{prefix}collision"
    collision.mkdir()
    marker = collision / "keep"
    marker.write_text("untouched")
    tokens = iter(["collision", "fresh"])
    monkeypatch.setattr(sandbox_runner.secrets, "token_hex", lambda _size: next(tokens))
    original_mkdir = Path.mkdir
    calls = []

    def mkdir(path, mode=0o777, parents=False, exist_ok=False):
        calls.append((path, mode, parents, exist_ok))
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    root = sandbox_runner._create_replay_temp_root(prefix)
    assert root.path == tmp_path.resolve() / f"{prefix}fresh"
    assert calls == [(collision, 0o777, False, False), (root.path, 0o777, False, False)]
    root.cleanup()
    assert not root.path.exists()
    assert marker.read_text() == "untouched"


def test_windows_temp_root_collision_retries_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_runner.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sandbox_runner, "os", SimpleNamespace(name="nt"))
    calls = []
    monkeypatch.setattr(sandbox_runner.secrets, "token_hex", lambda size: calls.append(size) or "x")
    collision = tmp_path / "homehub-replay-stage-x"
    collision.mkdir()
    with pytest.raises(sandbox_runner.WindowsSandboxReplayError, match="fresh replay temp"):
        sandbox_runner._create_replay_temp_root("homehub-replay-stage-")
    assert calls == [16] * 10
    assert collision.is_dir()


def test_temp_root_does_not_retry_permission_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_runner.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sandbox_runner, "os", SimpleNamespace(name="nt"))
    calls = []

    def denied(*args, **kwargs):
        calls.append(args)
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(PermissionError, match="denied"):
        sandbox_runner._create_replay_temp_root("homehub-replay-stage-")
    assert len(calls) == 1


def test_non_windows_temp_root_uses_private_tempfile_semantics(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_runner.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sandbox_runner, "os", SimpleNamespace(name="posix"))
    original = sandbox_runner.tempfile.mkdtemp
    calls = []

    def mkdtemp(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(sandbox_runner.tempfile, "mkdtemp", mkdtemp)
    root = sandbox_runner._create_replay_temp_root("homehub-replay-stage-")
    assert calls == [{"prefix": "homehub-replay-stage-", "dir": tmp_path.resolve()}]
    root.cleanup()


@pytest.mark.parametrize("invalid", ["parent", "prefix", "identity", "reparse"])
def test_temp_cleanup_rejects_unsafe_roots(tmp_path, monkeypatch, invalid):
    monkeypatch.setattr(sandbox_runner.tempfile, "gettempdir", lambda: str(tmp_path))
    root = sandbox_runner._create_replay_temp_root("homehub-replay-stage-")
    unsafe = root
    with monkeypatch.context() as patch:
        if invalid == "parent":
            unsafe = replace(root, parent=tmp_path / "elsewhere")
        elif invalid == "prefix":
            unsafe = replace(root, prefix="wrong-")
        elif invalid == "identity":
            unsafe = replace(root, identity=(-1, -1))
        else:
            info = root.path.lstat()

            class ReparseInfo:
                st_file_attributes = sandbox_runner.stat.FILE_ATTRIBUTE_REPARSE_POINT
                st_mode = info.st_mode
                st_dev = info.st_dev
                st_ino = info.st_ino

            patch.setattr(Path, "lstat", lambda _path: ReparseInfo())
        with pytest.raises(sandbox_runner.WindowsSandboxReplayError, match="unsafe"):
            unsafe.cleanup()
    assert root.path.exists()
    root.cleanup()


def test_runner_preserves_roots_when_start_outcome_has_no_exact_id(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_runner.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sandbox_runner, "backend_available", lambda: True)
    monkeypatch.setattr(sandbox_runner, "_find_wsb", lambda: "wsb.exe")
    monkeypatch.setattr(sandbox_runner, "_assert_no_running_sandbox", lambda _wsb: None)
    monkeypatch.setattr(sandbox_runner, "build_stage", lambda _bundle, root: root.mkdir())

    start_error = sandbox_runner.WindowsSandboxReplayError("start response could not be trusted")
    monkeypatch.setattr(
        sandbox_runner,
        "_start_sandbox",
        lambda *_args: (_ for _ in ()).throw(start_error),
    )
    monkeypatch.setattr(
        sandbox_runner,
        "_stop_sandbox",
        lambda *_args: pytest.fail("cannot stop without an exact Sandbox ID"),
    )

    with pytest.raises(sandbox_runner.WindowsSandboxReplayError) as caught:
        sandbox_runner.run_windows_sandbox_replay("synthetic")

    assert caught.value is start_error
    roots = list(tmp_path.iterdir())
    assert len(roots) == 2
    assert {path.name.split("-")[2] for path in roots} == {"stage", "export"}
    assert any((path / "stage").is_dir() for path in roots)
    notes = " ".join(getattr(caught.value, "__notes__", []))
    assert "no exact Sandbox ID" in notes
    assert all(path.name in notes for path in roots)


def test_runner_cleans_exact_roots_when_failure_occurs_before_start(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_runner.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sandbox_runner, "backend_available", lambda: True)
    monkeypatch.setattr(sandbox_runner, "_find_wsb", lambda: "wsb.exe")
    monkeypatch.setattr(sandbox_runner, "_assert_no_running_sandbox", lambda _wsb: None)

    build_error = sandbox_runner.WindowsSandboxReplayError("stage build failed")
    monkeypatch.setattr(
        sandbox_runner,
        "build_stage",
        lambda *_args: (_ for _ in ()).throw(build_error),
    )
    monkeypatch.setattr(
        sandbox_runner,
        "_start_sandbox",
        lambda *_args: pytest.fail("startup must not be attempted after build failure"),
    )

    with pytest.raises(sandbox_runner.WindowsSandboxReplayError) as caught:
        sandbox_runner.run_windows_sandbox_replay("synthetic")

    assert caught.value is build_error
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("replay_fails", [False, True])
def test_runner_preserves_roots_and_primary_error_when_stop_fails(
    tmp_path, monkeypatch, replay_fails
):
    monkeypatch.setattr(sandbox_runner.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sandbox_runner, "backend_available", lambda: True)
    monkeypatch.setattr(sandbox_runner, "_find_wsb", lambda: "wsb.exe")
    monkeypatch.setattr(sandbox_runner, "_assert_no_running_sandbox", lambda _wsb: None)
    monkeypatch.setattr(sandbox_runner, "build_stage", lambda _bundle, root: root.mkdir())
    sandbox_id = "12345678-1234-1234-1234-1234567890ab"
    monkeypatch.setattr(sandbox_runner, "_start_sandbox", lambda *_args: sandbox_id)
    primary = ValueError("original replay failure")

    def verify(*_args):
        if replay_fails:
            raise primary

    monkeypatch.setattr(sandbox_runner, "_verify_exec_timing_channel", verify)
    for name in (
        "_run_guest_broker",
        "_wait_for_replay",
        "_share_export",
        "_wait_for_export_share_ready",
        "_export_result",
        "_wait_for_export_visibility",
    ):
        monkeypatch.setattr(sandbox_runner, name, lambda *_args: None)
    monkeypatch.setattr(sandbox_runner, "_load_export", lambda *_args: {"status": "ok"})

    def stop(_wsb, exact_id):
        assert exact_id == sandbox_id
        raise RuntimeError("stop unavailable")

    monkeypatch.setattr(sandbox_runner, "_stop_sandbox", stop)
    expected = ValueError if replay_fails else sandbox_runner.WindowsSandboxReplayError
    with pytest.raises(expected) as caught:
        sandbox_runner.run_windows_sandbox_replay("synthetic")
    roots = list(tmp_path.iterdir())
    assert len(roots) == 2
    assert {path.name.split("-")[2] for path in roots} == {"stage", "export"}
    assert any((path / "stage").is_dir() for path in roots)
    message = (
        " ".join(getattr(caught.value, "__notes__", [])) if replay_fails else str(caught.value)
    )
    assert "stop unavailable" in message
    assert all(path.name in message for path in roots)
    if replay_fails:
        assert caught.value is primary


def test_stop_requires_exact_id_and_success(monkeypatch):
    calls = []

    def command(args, **kwargs):
        calls.append((args, kwargs))
        raise sandbox_runner.WindowsSandboxReplayError("stop failed")

    monkeypatch.setattr(sandbox_runner, "_run_command", command)
    with pytest.raises(sandbox_runner.WindowsSandboxReplayError, match="stop failed"):
        sandbox_runner._stop_sandbox("wsb.exe", "exact-id")
    assert calls == [
        (
            ["wsb.exe", "stop", "--id", "exact-id"],
            {"timeout": sandbox_runner.COMMAND_TIMEOUT_SECONDS, "check": True},
        )
    ]


def test_guest_export_helper_uses_stream_redirection_and_completion_markers(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    sandbox_runner._write_guest_helpers(stage)

    launch_cmd = (stage / "launch_guest.cmd").read_text(encoding="ascii")
    assert sandbox_runner.GUEST_LAUNCH_SEEN in launch_cmd

    fast_cmd = (stage / "exec_fast.cmd").read_text(encoding="ascii")
    fast_py = (stage / "exec_fast.py").read_text(encoding="ascii")
    slow_cmd = (stage / "exec_slow.cmd").read_text(encoding="ascii")
    slow_py = (stage / "exec_slow.py").read_text(encoding="ascii")
    assert f"{sandbox_runner.GUEST_STAGE}\\runtime\\python.exe" in fast_cmd
    assert "exec_fast.py" in fast_cmd
    assert fast_py.strip() == "pass"
    assert f"{sandbox_runner.GUEST_STAGE}\\runtime\\python.exe" in slow_cmd
    assert "exec_slow.py" in slow_cmd
    assert f"time.sleep({sandbox_runner.EXEC_TIMING_SIGNAL_SECONDS!r})" in slow_py

    wait_cmd = (stage / "wait_ready.cmd").read_text(encoding="ascii")
    wait_py = (stage / "wait_ready.py").read_text(encoding="ascii")
    prove_cmd = (stage / "prove_ready.cmd").read_text(encoding="ascii")
    prove_py = (stage / "prove_ready.py").read_text(encoding="ascii")
    assert f"{sandbox_runner.GUEST_STAGE}\\runtime\\python.exe" in wait_cmd
    assert "wait_ready.py" in wait_cmd
    assert repr(sandbox_runner.GUEST_STATE) in wait_py
    assert repr(sandbox_runner.GUEST_DONE) in wait_py
    assert repr(sandbox_runner.GUEST_STATUS) in wait_py
    assert repr(sandbox_runner.GUEST_READY) in wait_py
    assert 'ready.write_text("ready\\n", encoding="ascii")' in wait_py
    assert "while not" in wait_py
    assert "time.sleep(0.1)" in wait_py
    assert f"{sandbox_runner.GUEST_STAGE}\\runtime\\python.exe" in prove_cmd
    assert "prove_ready.py" in prove_cmd
    assert repr(sandbox_runner.GUEST_READY) in prove_py
    assert f"time.sleep({sandbox_runner.EXEC_TIMING_SIGNAL_SECONDS!r})" in prove_py

    diagnose_cmd = (stage / "diagnose_phase.cmd").read_text(encoding="ascii")
    diagnose_py = (stage / "diagnose_phase.py").read_text(encoding="ascii")
    assert f"{sandbox_runner.GUEST_STAGE}\\runtime\\python.exe" in diagnose_cmd
    assert "diagnose_phase.py" in diagnose_cmd
    for guest_path in (
        sandbox_runner.GUEST_LAUNCH_SEEN,
        sandbox_runner.GUEST_LOCAL_STAGE,
        sandbox_runner.GUEST_STATE,
        sandbox_runner.GUEST_STATUS,
        sandbox_runner.GUEST_DONE,
    ):
        assert repr(guest_path) in diagnose_py
    assert f"phase * {sandbox_runner.EXEC_DIAGNOSTIC_PHASE_SECONDS!r}" in diagnose_py

    export = (stage / "export_result.cmd").read_text(encoding="ascii")
    assert 'type "C:\\HomeHubReplayState\\status.json"' in export
    assert 'type "C:\\HomeHubReplayState\\result.json"' in export
    assert "copy /y" not in export.casefold()
    assert "move /y" not in export.casefold()
    assert "exec_context.txt" in export
    assert "state_dir.txt" in export
    assert "state_dir_seen.marker" in export
    assert "done_source_seen.marker" in export
    assert "status_source_seen.marker" in export
    assert "result_source_seen.marker" in export
    assert "status_written.marker" in export
    assert "result_written.marker" in export
    assert "export_complete.marker" in export


def test_wsb_configuration_exposes_only_read_only_stage(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()

    root = ET.fromstring(sandbox_runner.build_wsb_configuration(stage))

    assert root.tag == "Configuration"
    assert root.findtext("vGPU") == "Disable"
    assert root.find("VGpu") is None
    assert root.findtext("Networking") == "Disable"
    assert root.findtext("AudioInput") == "Disable"
    assert root.findtext("VideoInput") == "Disable"
    assert root.findtext("ProtectedClient") == "Enable"
    assert root.findtext("PrinterRedirection") == "Disable"
    assert root.findtext("ClipboardRedirection") == "Disable"

    mappings = root.findall("./MappedFolders/MappedFolder")
    assert len(mappings) == 1
    mapping = mappings[0]
    assert mapping.findtext("HostFolder") == str(stage.resolve())
    assert mapping.findtext("SandboxFolder") == sandbox_runner.GUEST_STAGE
    assert mapping.findtext("ReadOnly") == "true"
    assert root.find("LogonCommand") is None


def test_wsb_exec_wraps_batch_helpers_in_cmd(monkeypatch):
    captured = []

    def fake_run_command(args, *, timeout=sandbox_runner.COMMAND_TIMEOUT_SECONDS, check=False):
        captured.append((args, timeout, check))
        return subprocess.CompletedProcess(args=args, returncode=7, stdout="", stderr="")

    monkeypatch.setattr(sandbox_runner, "_run_command", fake_run_command)

    completed = sandbox_runner._exec(
        "wsb.exe",
        "12345678-1234-1234-1234-1234567890ab",
        r"C:\HomeHubReplayStage\wait_ready.cmd",
        timeout=12.5,
    )

    assert completed.returncode == 7
    assert captured == [
        (
            [
                "wsb.exe",
                "exec",
                "--id",
                "12345678-1234-1234-1234-1234567890ab",
                "-c",
                'cmd.exe /d /q /c "C:\\HomeHubReplayStage\\wait_ready.cmd"',
                "-r",
                "System",
            ],
            12.5,
            False,
        )
    ]


def test_guest_broker_is_explicitly_started_via_system_exec(monkeypatch):
    calls = []

    def fake_exec(wsb, sandbox_id, command, *, timeout):
        calls.append((wsb, sandbox_id, command, timeout))
        return subprocess.CompletedProcess(
            args=["wsb", "exec"],
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(sandbox_runner, "_exec", fake_exec)
    sandbox_runner._run_guest_broker(
        "wsb.exe",
        "12345678-1234-1234-1234-1234567890ab",
    )

    assert calls == [
        (
            "wsb.exe",
            "12345678-1234-1234-1234-1234567890ab",
            f"{sandbox_runner.GUEST_STAGE}\\launch_guest.cmd",
            sandbox_runner.BROKER_EXEC_TIMEOUT_SECONDS,
        )
    ]


def test_wsb_exec_timing_channel_distinguishes_guest_runtime(monkeypatch):
    sandbox_id = "12345678-1234-1234-1234-1234567890ab"
    calls = []
    durations = iter([0.4, 4.5, 0.5])

    def measure(_wsb, _sandbox_id, helper, **_kwargs):
        calls.append(helper)
        return next(durations)

    monkeypatch.setattr(sandbox_runner, "_measure_exec_duration", measure)
    sandbox_runner._verify_exec_timing_channel("wsb.exe", sandbox_id)
    assert calls == [
        f"{sandbox_runner.GUEST_STAGE}\\exec_fast.cmd",
        f"{sandbox_runner.GUEST_STAGE}\\exec_slow.cmd",
        f"{sandbox_runner.GUEST_STAGE}\\exec_fast.cmd",
    ]

    # Even multi-second CLI overhead must fail if it does not track guest runtime.
    durations = iter([3.0, 3.2, 3.1])
    monkeypatch.setattr(
        sandbox_runner,
        "_measure_exec_duration",
        lambda *_args, **_kwargs: next(durations),
    )
    with pytest.raises(
        sandbox_runner.WindowsSandboxReplayError,
        match="does not prove guest-process completion",
    ):
        sandbox_runner._verify_exec_timing_channel("wsb.exe", sandbox_id)


def test_guest_ready_proof_requires_positive_timing_signal(monkeypatch):
    sandbox_id = "12345678-1234-1234-1234-1234567890ab"
    durations = iter([0.5, 4.5, 0.6])
    monkeypatch.setattr(
        sandbox_runner,
        "_measure_exec_duration",
        lambda *_args, **_kwargs: next(durations),
    )
    sandbox_runner._prove_guest_ready("wsb.exe", sandbox_id)

    durations = iter([0.5, 0.7, 0.6])
    monkeypatch.setattr(
        sandbox_runner,
        "_measure_exec_duration",
        lambda *_args, **_kwargs: next(durations),
    )
    with pytest.raises(
        sandbox_runner.WindowsSandboxReplayError,
        match="readiness marker was not positively confirmed",
    ):
        sandbox_runner._prove_guest_ready("wsb.exe", sandbox_id)


@pytest.mark.parametrize(
    ("phase_duration", "expected"),
    [
        (0.5, "logon_not_observed"),
        (2.5, "launch_started_before_local_stage"),
        (4.5, "local_stage_present_state_absent"),
        (6.5, "state_present_status_absent"),
        (8.5, "status_present_done_absent"),
        (10.5, "done_present"),
    ],
)
def test_guest_phase_diagnostic_decodes_guest_local_progress(
    monkeypatch,
    phase_duration,
    expected,
):
    durations = iter([0.5, phase_duration, 0.5])
    monkeypatch.setattr(
        sandbox_runner,
        "_verify_exec_timing_channel",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        sandbox_runner,
        "_measure_exec_duration",
        lambda *_args, **_kwargs: next(durations),
    )

    assert (
        sandbox_runner._diagnose_guest_phase(
            "wsb.exe",
            "12345678-1234-1234-1234-1234567890ab",
        )
        == expected
    )


def test_replay_wait_timeout_reports_guest_phase(monkeypatch):
    monkeypatch.setattr(
        sandbox_runner,
        "_exec",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            sandbox_runner.WindowsSandboxReplayError("exec timed out")
        ),
    )
    monkeypatch.setattr(
        sandbox_runner,
        "_diagnose_guest_phase",
        lambda *_args: "local_stage_present_state_absent",
    )

    with pytest.raises(
        sandbox_runner.WindowsSandboxReplayError,
        match="guest_phase=local_stage_present_state_absent",
    ):
        sandbox_runner._wait_for_replay(
            "wsb.exe",
            "12345678-1234-1234-1234-1234567890ab",
            timeout=1.0,
        )


def test_replay_readiness_requires_guest_marker_even_when_cli_returns_zero(monkeypatch):
    sandbox_id = "12345678-1234-1234-1234-1234567890ab"
    calls = []

    def exec_zero(_wsb, _sandbox_id, command, *, timeout):
        calls.append((command, timeout))
        return subprocess.CompletedProcess(
            args=["wsb", "exec"],
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(sandbox_runner, "_exec", exec_zero)
    monkeypatch.setattr(
        sandbox_runner,
        "_prove_guest_ready",
        lambda *_args: calls.append(("proof", None)),
    )
    sandbox_runner._wait_for_replay("wsb.exe", sandbox_id, timeout=12.5)
    assert calls == [
        (
            f"{sandbox_runner.GUEST_STAGE}\\wait_ready.cmd",
            12.5,
        ),
        ("proof", None),
    ]

    # Model a readiness helper that crashed while this CLI misleadingly returned zero:
    # the independent guest-marker proof still blocks the writable export share.
    monkeypatch.setattr(
        sandbox_runner,
        "_prove_guest_ready",
        lambda *_args: (_ for _ in ()).throw(
            sandbox_runner.WindowsSandboxReplayError("marker not confirmed")
        ),
    )
    with pytest.raises(
        sandbox_runner.WindowsSandboxReplayError,
        match="marker not confirmed",
    ):
        sandbox_runner._wait_for_replay("wsb.exe", sandbox_id, timeout=12.5)


def test_backend_availability_is_capability_and_context_gated(monkeypatch):
    monkeypatch.setattr(sandbox_runner, "_windows_build", lambda: sandbox_runner.MIN_WINDOWS_BUILD)
    monkeypatch.setattr(sandbox_runner, "_find_wsb", lambda: r"C:\Windows\System32\wsb.exe")

    monkeypatch.setenv("USERNAME", "Anthony")
    assert sandbox_runner.backend_available() is True

    monkeypatch.setenv("USERNAME", "WDAGUtilityAccount")
    assert sandbox_runner.backend_available() is False

    monkeypatch.setenv("USERNAME", "Anthony")
    monkeypatch.setattr(
        sandbox_runner, "_windows_build", lambda: sandbox_runner.MIN_WINDOWS_BUILD - 1
    )
    assert sandbox_runner.backend_available() is False

    monkeypatch.setattr(sandbox_runner, "_windows_build", lambda: sandbox_runner.MIN_WINDOWS_BUILD)
    monkeypatch.setattr(sandbox_runner, "_find_wsb", lambda: None)
    assert sandbox_runner.backend_available() is False


def test_parse_sandbox_id_is_strict_about_json_and_uuid():
    sandbox_id = "12345678-1234-1234-1234-1234567890ab"
    assert (
        sandbox_runner.parse_sandbox_id(json.dumps({"sandbox": {"sandboxId": sandbox_id}}))
        == sandbox_id
    )

    with pytest.raises(sandbox_runner.WindowsSandboxReplayError, match="invalid JSON"):
        sandbox_runner.parse_sandbox_id("not-json")

    with pytest.raises(sandbox_runner.WindowsSandboxReplayError, match="sandbox ID"):
        sandbox_runner.parse_sandbox_id(json.dumps({"sandboxId": "not-a-uuid"}))


def test_parse_sandbox_inventory_is_strict_and_normalized():
    running_id = "12345678-1234-1234-1234-1234567890ab"
    stopped_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    assert sandbox_runner.parse_sandbox_inventory("") == []
    assert (
        sandbox_runner.parse_sandbox_inventory(json.dumps({"WindowsSandboxEnvironments": []})) == []
    )
    assert sandbox_runner.parse_sandbox_inventory(
        json.dumps(
            {
                "WindowsSandboxEnvironments": [
                    {"Id": running_id, "Status": "Running"},
                    {"ID": stopped_id, "State": "Stopped"},
                ]
            }
        )
    ) == [
        {"id": running_id, "status": "running"},
        {"id": stopped_id, "status": "stopped"},
    ]
    assert sandbox_runner.parse_sandbox_inventory(
        json.dumps({"WindowsSandboxEnvironments": [{"Id": running_id}]})
    ) == [{"id": running_id, "status": "unknown"}]

    with pytest.raises(sandbox_runner.WindowsSandboxReplayError, match="invalid JSON"):
        sandbox_runner.parse_sandbox_inventory("not-json")
    with pytest.raises(
        sandbox_runner.WindowsSandboxReplayError, match="unsupported list JSON shape"
    ):
        sandbox_runner.parse_sandbox_inventory(json.dumps({"unexpected": []}))
    with pytest.raises(sandbox_runner.WindowsSandboxReplayError, match="unsupported status"):
        sandbox_runner.parse_sandbox_inventory(
            json.dumps([{"id": running_id, "status": "Unknown"}])
        )


def test_existing_sandbox_record_blocks_operational_replay(monkeypatch):
    running_id = "12345678-1234-1234-1234-1234567890ab"
    monkeypatch.setattr(
        sandbox_runner,
        "_run_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["wsb", "list", "--raw"],
            returncode=0,
            stdout=json.dumps({"WindowsSandboxEnvironments": [{"Id": running_id}]}),
            stderr="",
        ),
    )

    with pytest.raises(
        sandbox_runner.WindowsSandboxReplayError,
        match="exclusive Windows Sandbox access",
    ):
        sandbox_runner._assert_no_running_sandbox("wsb.exe")


def test_single_use_start_error_is_translated(monkeypatch):
    monkeypatch.setattr(
        sandbox_runner,
        "_run_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["wsb", "start"],
            returncode=sandbox_runner.CO_E_APPSINGLEUSE,
            stdout="",
            stderr="Application cannot be run more than once",
        ),
    )

    with pytest.raises(
        sandbox_runner.WindowsSandboxReplayError,
        match="exclusive Windows Sandbox access",
    ):
        sandbox_runner._start_sandbox("wsb.exe", "<Configuration />")


def test_reviewed_stage_files_match_navigation_root_closure():
    repo = Path(__file__).resolve().parents[1]
    visited, _, _ = _project_import_closure(repo)

    closure_paths: set[str] = set()
    for module_name in visited:
        module_path, _ = _project_module_path(repo, module_name)
        assert module_path is not None
        closure_paths.add(module_path.relative_to(repo).as_posix())

    expected = closure_paths | {
        "backend/replay/isolated_child.py",
        "backend/replay/windows_guest_broker.py",
    }
    assert set(sandbox_runner.PROJECT_FILES) == expected
    assert all(".env" not in path for path in sandbox_runner.PROJECT_FILES)
    assert all("automation_engine.py" not in path for path in sandbox_runner.PROJECT_FILES)


def test_guest_broker_constructs_zero_capability_restricted_child():
    source = (
        Path(__file__).resolve().parents[1] / "backend" / "replay" / "windows_guest_broker.py"
    ).read_text(encoding="utf-8")

    assert "SECURITY_CAPABILITIES(app_sid, None, 0, 0)" in source
    assert "_deny_appcontainer_access(STATE_ROOT, sid_text)" in source
    assert "PROCESS_CREATION_CHILD_PROCESS_RESTRICTED" in source
    assert "PROC_THREAD_ATTRIBUTE_HANDLE_LIST" in source
    assert "PROCESS_CREATION_MITIGATION_POLICY_WIN32K_SYSTEM_CALL_DISABLE_ALWAYS_ON" in source
    assert "internetClient" not in source
    assert "privateNetworkClientServer" not in source


def test_runner_adds_writable_export_only_after_replay_completion(monkeypatch):
    events: list[str] = []
    roots: list[Path] = []

    monkeypatch.setattr(sandbox_runner, "backend_available", lambda: True)
    monkeypatch.setattr(sandbox_runner, "_find_wsb", lambda: "wsb.exe")
    monkeypatch.setattr(sandbox_runner, "_assert_no_running_sandbox", lambda _wsb: None)

    def build_stage(_bundle_path, stage_root):
        events.append("build")
        roots.append(stage_root.parent)
        assert stage_root.name == "stage"
        stage_root.mkdir(parents=True)
        return stage_root

    def start(_wsb, config):
        events.append("start")
        assert "<ReadOnly>true</ReadOnly>" in config
        return "12345678-1234-1234-1234-1234567890ab"

    def verify_exec(_wsb, _sandbox_id):
        events.append("verify_exec_timing")

    def run_broker(_wsb, _sandbox_id):
        events.append("run_broker")

    def wait(_wsb, _sandbox_id, **_kwargs):
        events.append("wait_done")

    def share(_wsb, _sandbox_id, _export_root):
        events.append("share_writable_export")
        roots.append(_export_root)
        assert roots[0] != roots[1]

    def wait_share(_wsb, _sandbox_id, _export_root):
        events.append("wait_share_host_backed")

    def export(_wsb, _sandbox_id, _export_root):
        events.append("export")

    def wait_export(_export_root):
        events.append("wait_export_visible")

    def load(_export_root):
        events.append("load")
        return {"schema_id": sandbox_runner.RESULT_SCHEMA_ID, "status": "ok"}

    def stop(_wsb, _sandbox_id):
        events.append("stop")
        assert all(root.is_dir() for root in roots)

    monkeypatch.setattr(sandbox_runner, "build_stage", build_stage)
    monkeypatch.setattr(sandbox_runner, "_start_sandbox", start)
    monkeypatch.setattr(sandbox_runner, "_verify_exec_timing_channel", verify_exec)
    monkeypatch.setattr(sandbox_runner, "_run_guest_broker", run_broker)
    monkeypatch.setattr(sandbox_runner, "_wait_for_replay", wait)
    monkeypatch.setattr(sandbox_runner, "_share_export", share)
    monkeypatch.setattr(sandbox_runner, "_wait_for_export_share_ready", wait_share)
    monkeypatch.setattr(sandbox_runner, "_export_result", export)
    monkeypatch.setattr(sandbox_runner, "_wait_for_export_visibility", wait_export)
    monkeypatch.setattr(sandbox_runner, "_load_export", load)
    monkeypatch.setattr(sandbox_runner, "_stop_sandbox", stop)

    result = sandbox_runner.run_windows_sandbox_replay("synthetic")
    assert result["status"] == "ok"
    assert all(not root.exists() for root in roots)
    assert events == [
        "build",
        "start",
        "verify_exec_timing",
        "run_broker",
        "wait_done",
        "share_writable_export",
        "wait_share_host_backed",
        "export",
        "wait_export_visible",
        "load",
        "stop",
    ]


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_runner_stops_before_share_when_exec_calibration_fails(monkeypatch, cleanup_fails):
    events: list[str] = []

    monkeypatch.setattr(sandbox_runner, "backend_available", lambda: True)
    monkeypatch.setattr(sandbox_runner, "_find_wsb", lambda: "wsb.exe")
    monkeypatch.setattr(sandbox_runner, "_assert_no_running_sandbox", lambda _wsb: None)

    def build_stage(_bundle_path, stage_root):
        events.append("build")
        stage_root.mkdir(parents=True)
        return stage_root

    monkeypatch.setattr(sandbox_runner, "build_stage", build_stage)
    monkeypatch.setattr(
        sandbox_runner,
        "_start_sandbox",
        lambda _wsb, _config: events.append("start") or "12345678-1234-1234-1234-1234567890ab",
    )

    def fail_calibration(_wsb, _sandbox_id):
        events.append("verify_exec_failed")
        raise sandbox_runner.WindowsSandboxReplayError("exec synchrony untrusted")

    monkeypatch.setattr(sandbox_runner, "_verify_exec_timing_channel", fail_calibration)
    monkeypatch.setattr(
        sandbox_runner,
        "_share_export",
        lambda *_args, **_kwargs: events.append("share"),
    )
    monkeypatch.setattr(
        sandbox_runner,
        "_stop_sandbox",
        lambda *_args, **_kwargs: events.append("stop"),
    )

    original_cleanup = sandbox_runner._ReplayTempRoot.cleanup
    if cleanup_fails:

        def cleanup(root):
            original_cleanup(root)
            raise OSError("cleanup failure")

        monkeypatch.setattr(sandbox_runner._ReplayTempRoot, "cleanup", cleanup)

    with pytest.raises(sandbox_runner.WindowsSandboxReplayError, match="untrusted") as caught:
        sandbox_runner.run_windows_sandbox_replay("synthetic")

    assert events == ["build", "start", "verify_exec_failed", "stop"]
    if cleanup_fails:
        assert len(caught.value.__notes__) == 2
        assert all("cleanup failure" in note for note in caught.value.__notes__)


def test_runner_stops_vm_without_export_when_replay_never_finishes(monkeypatch):
    events: list[str] = []

    monkeypatch.setattr(sandbox_runner, "backend_available", lambda: True)
    monkeypatch.setattr(sandbox_runner, "_find_wsb", lambda: "wsb.exe")
    monkeypatch.setattr(sandbox_runner, "_assert_no_running_sandbox", lambda _wsb: None)

    def build_stage(_bundle_path, stage_root):
        events.append("build")
        stage_root.mkdir(parents=True)
        return stage_root

    monkeypatch.setattr(sandbox_runner, "build_stage", build_stage)
    monkeypatch.setattr(
        sandbox_runner,
        "_start_sandbox",
        lambda _wsb, _config: events.append("start") or "12345678-1234-1234-1234-1234567890ab",
    )
    monkeypatch.setattr(
        sandbox_runner,
        "_verify_exec_timing_channel",
        lambda _wsb, _sandbox_id: events.append("verify_exec_timing"),
    )
    monkeypatch.setattr(
        sandbox_runner,
        "_run_guest_broker",
        lambda _wsb, _sandbox_id: events.append("run_broker"),
    )

    def fail_wait(_wsb, _sandbox_id, **_kwargs):
        events.append("wait_failed")
        raise sandbox_runner.WindowsSandboxReplayError("not ready")

    monkeypatch.setattr(sandbox_runner, "_wait_for_replay", fail_wait)
    monkeypatch.setattr(
        sandbox_runner,
        "_share_export",
        lambda *_args, **_kwargs: events.append("share"),
    )
    monkeypatch.setattr(
        sandbox_runner,
        "_stop_sandbox",
        lambda *_args, **_kwargs: events.append("stop"),
    )

    with pytest.raises(sandbox_runner.WindowsSandboxReplayError, match="not ready"):
        sandbox_runner.run_windows_sandbox_replay("synthetic")

    assert events == [
        "build",
        "start",
        "verify_exec_timing",
        "run_broker",
        "wait_failed",
        "stop",
    ]


def test_export_share_handshake_requires_host_visible_marker(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_exec(_wsb, _sandbox_id, command):
        calls.append(command)
        (tmp_path / "share_ready.marker").write_text("ready\n", encoding="ascii")
        return subprocess.CompletedProcess(
            args=["wsb", "exec"],
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(sandbox_runner, "_exec", fake_exec)
    sandbox_runner._wait_for_export_share_ready(
        "wsb.exe",
        "12345678-1234-1234-1234-1234567890ab",
        tmp_path,
        timeout=1.0,
    )

    assert calls == [f"{sandbox_runner.GUEST_STAGE}\\probe_export.cmd"]


def test_export_result_does_not_trust_wsb_exec_guest_exit_code(monkeypatch, tmp_path):
    calls = []

    def fake_exec(_wsb, _sandbox_id, command):
        calls.append(command)
        return subprocess.CompletedProcess(
            args=["wsb", "exec"],
            returncode=5,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(sandbox_runner, "_exec", fake_exec)
    sandbox_runner._export_result(
        "wsb.exe",
        "12345678-1234-1234-1234-1234567890ab",
        tmp_path,
    )

    assert calls == [f"{sandbox_runner.GUEST_STAGE}\\export_result.cmd"]


def test_export_visibility_wait_tolerates_dynamic_share_delay(tmp_path):
    import threading
    import time

    def publish():
        time.sleep(0.05)
        (tmp_path / "status.json").write_text(
            json.dumps({"status": "ok"}),
            encoding="utf-8",
        )
        (tmp_path / "result.json").write_text(
            json.dumps(
                {
                    "schema_id": sandbox_runner.RESULT_SCHEMA_ID,
                    "status": "ok",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "export_complete.marker").write_text(
            "complete\n",
            encoding="ascii",
        )

    thread = threading.Thread(target=publish)
    thread.start()
    sandbox_runner._wait_for_export_visibility(tmp_path, timeout=1.0)
    thread.join(timeout=1.0)
    assert not thread.is_alive()


def test_export_result_requires_successful_isolation_self_test(tmp_path):
    (tmp_path / "status.json").write_text(
        json.dumps({"status": "ok"}),
        encoding="utf-8",
    )
    (tmp_path / "result.json").write_text(
        json.dumps(
            {
                "schema_id": sandbox_runner.RESULT_SCHEMA_ID,
                "status": "ok",
                "isolation_self_test": {"status": "failed"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        sandbox_runner.WindowsSandboxReplayError,
        match="isolation self-test",
    ):
        sandbox_runner._load_export(tmp_path)

    (tmp_path / "result.json").write_text(
        json.dumps(
            {
                "schema_id": sandbox_runner.RESULT_SCHEMA_ID,
                "status": "ok",
                "isolation_self_test": {"status": "passed", "checks": []},
            }
        ),
        encoding="utf-8",
    )
    result = sandbox_runner._load_export(tmp_path)
    assert result["status"] == "ok"


def test_child_forbidden_paths_cover_legacy_and_split_host_bridge_canaries():
    import backend.replay.isolated_child as isolated_child

    paths = set(isolated_child.FORBIDDEN_PRODUCTION_PATHS)
    assert Path(r"C:\HostBridge\status.json") in paths
    assert Path(r"C:\HostBridgeRequests") in paths
    assert Path(r"C:\HostBridgeResponses") in paths


@pytest.mark.skipif(os.name != "nt", reason="Windows-only child contract")
def test_child_self_test_fails_closed_when_production_path_is_readable(
    tmp_path,
    monkeypatch,
):
    import backend.replay.isolated_child as isolated_child

    exposed = tmp_path / "exposed-secret"
    exposed.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(isolated_child, "FORBIDDEN_PRODUCTION_PATHS", (exposed,))

    with pytest.raises(RuntimeError, match="unexpectedly succeeded"):
        isolated_child._run_isolation_self_test(tmp_path / "unused-bundle")


@pytest.mark.skipif(
    os.environ.get("HOMEHUB_RUN_REPLAY_ISOLATION_E2E") != "1",
    reason="explicit host-only operational isolation acceptance test",
)
def test_windows_sandbox_appcontainer_end_to_end(tmp_path):
    if not sandbox_runner.backend_available():
        pytest.fail("operational Windows Sandbox backend is unavailable on this host")

    bundle_path = _write_bundle(tmp_path / "bundle")
    result = isolated_runner.run_navigation_v1_isolated(bundle_path=bundle_path)

    assert result["schema_id"] == sandbox_runner.RESULT_SCHEMA_ID
    assert result["status"] == "ok"
    assert result["isolation_self_test"]["status"] == "passed"
    assert result["bundle_id"] == "synthetic-navigation-v1"
