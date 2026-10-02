"""Operational isolation backend contract for navigation-v1 replay."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

import backend.replay.isolated_runner as isolated_runner
import backend.replay.windows_sandbox_runner as sandbox_runner
from tests.test_replay_bundle import _write_bundle
from tests.test_replay_navigation_root import _project_import_closure, _project_module_path


def test_guest_export_helper_uses_stream_redirection_and_completion_markers(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    sandbox_runner._write_guest_helpers(stage)

    export = (stage / "export_result.cmd").read_text(encoding="ascii")
    assert 'type "C:\\HomeHubReplayState\\status.json"' in export
    assert 'type "C:\\HomeHubReplayState\\result.json"' in export
    assert "copy /y" not in export.casefold()
    assert "move /y" not in export.casefold()
    assert "status_source_seen.marker" in export
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
    assert root.findtext("./LogonCommand/Command") == (
        f"cmd.exe /d /q /c {sandbox_runner.GUEST_STAGE}\\launch_guest.cmd"
    )


def test_wsb_exec_wraps_batch_helpers_in_cmd(monkeypatch):
    captured: list[list[str]] = []

    def fake_run_command(args, *, timeout=sandbox_runner.COMMAND_TIMEOUT_SECONDS, check=False):
        captured.append(args)
        return subprocess.CompletedProcess(args=args, returncode=7, stdout="", stderr="")

    monkeypatch.setattr(sandbox_runner, "_run_command", fake_run_command)

    completed = sandbox_runner._exec(
        "wsb.exe",
        "12345678-1234-1234-1234-1234567890ab",
        r"C:\HomeHubReplayStage\poll_ready.cmd",
    )

    assert completed.returncode == 7
    assert captured == [
        [
            "wsb.exe",
            "exec",
            "--id",
            "12345678-1234-1234-1234-1234567890ab",
            "-c",
            'cmd.exe /d /q /c "C:\\HomeHubReplayStage\\poll_ready.cmd"',
            "-r",
            "System",
        ]
    ]


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


def test_existing_running_sandbox_blocks_operational_replay(monkeypatch):
    running_id = "12345678-1234-1234-1234-1234567890ab"
    monkeypatch.setattr(
        sandbox_runner,
        "_run_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["wsb", "list", "--raw"],
            returncode=0,
            stdout=json.dumps([{"id": running_id, "status": "Running"}]),
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

    monkeypatch.setattr(sandbox_runner, "backend_available", lambda: True)
    monkeypatch.setattr(sandbox_runner, "_find_wsb", lambda: "wsb.exe")
    monkeypatch.setattr(sandbox_runner, "_assert_no_running_sandbox", lambda _wsb: None)

    def build_stage(_bundle_path, stage_root):
        events.append("build")
        stage_root.mkdir(parents=True)
        return stage_root

    def start(_wsb, config):
        events.append("start")
        assert "<ReadOnly>true</ReadOnly>" in config
        return "12345678-1234-1234-1234-1234567890ab"

    def wait(_wsb, _sandbox_id, **_kwargs):
        events.append("wait_done")

    def share(_wsb, _sandbox_id, _export_root):
        events.append("share_writable_export")

    def wait_share(_wsb, _sandbox_id, _export_root):
        events.append("wait_share_host_backed")

    def export(_wsb, _sandbox_id):
        events.append("export")

    def wait_export(_export_root):
        events.append("wait_export_visible")

    def load(_export_root):
        events.append("load")
        return {"schema_id": sandbox_runner.RESULT_SCHEMA_ID, "status": "ok"}

    def stop(_wsb, _sandbox_id):
        events.append("stop")

    monkeypatch.setattr(sandbox_runner, "build_stage", build_stage)
    monkeypatch.setattr(sandbox_runner, "_start_sandbox", start)
    monkeypatch.setattr(sandbox_runner, "_wait_for_replay", wait)
    monkeypatch.setattr(sandbox_runner, "_share_export", share)
    monkeypatch.setattr(sandbox_runner, "_wait_for_export_share_ready", wait_share)
    monkeypatch.setattr(sandbox_runner, "_export_result", export)
    monkeypatch.setattr(sandbox_runner, "_wait_for_export_visibility", wait_export)
    monkeypatch.setattr(sandbox_runner, "_load_export", load)
    monkeypatch.setattr(sandbox_runner, "_stop_sandbox", stop)

    result = sandbox_runner.run_windows_sandbox_replay("synthetic")
    assert result["status"] == "ok"
    assert events == [
        "build",
        "start",
        "wait_done",
        "share_writable_export",
        "wait_share_host_backed",
        "export",
        "wait_export_visible",
        "load",
        "stop",
    ]


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

    assert events == ["build", "start", "wait_failed", "stop"]


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
