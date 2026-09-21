"""Static/recovery contracts for the Windows unified-supervisor setup."""
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"


def _text(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8-sig")


def test_supervisor_launcher_uses_repo_dot_venv_not_machine_python():
    text = _text("start-supervisor.ps1")
    assert '.venv\\Scripts\\pythonw.exe' in text
    assert "C:\\Python313" not in text
    assert "\\venv\\Lib\\site-packages" not in text


def test_setup_installs_stable_localappdata_launcher_and_all_six_agents():
    text = _text("setup-supervisor-task.ps1")
    assert 'Join-Path $env:LOCALAPPDATA "home-hub"' in text
    assert 'Copy-Item (Join-Path $PSScriptRoot "start-supervisor.ps1")' in text
    assert 'Copy-Item (Join-Path $PSScriptRoot "start-supervisor-hidden.vbs")' in text
    assert '.venv\\Scripts\\pythonw.exe' in text
    for agent in (
        "activity_detector",
        "ambient_monitor",
        "screen_sync",
        "sleep_watcher",
        "emotion_capture",
        "monitor_brightness",
    ):
        assert agent in text


def test_vbs_waits_so_task_multiple_instance_guard_remains_effective():
    text = _text("start-supervisor-hidden.vbs")
    assert '", 0, True' in text
    assert '", 0, False' not in text


def test_obsolete_per_agent_scripts_fail_closed():
    for name in (
        "setup-ambient-task.ps1",
        "setup-detector-task.ps1",
        "restart-detector.ps1",
    ):
        text = _text(name)
        assert "RETIRED" in text
        assert "exit 1" in text
        assert "Register-ScheduledTask" not in text
        assert "Start-Process" not in text


def test_detached_recovery_prefers_installed_runtime_launcher(monkeypatch, tmp_path):
    from backend.services.pc_agent import supervisor_recovery

    runtime = tmp_path / "home-hub" / "start-supervisor-hidden.vbs"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("' test launcher", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    observed = {}

    def fake_popen(args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs

    monkeypatch.setattr(supervisor_recovery.subprocess, "Popen", fake_popen)
    supervisor_recovery.WindowsRecoveryOperations().kick_canonical_launcher()

    assert Path(observed["args"][1]) == runtime
    assert Path(observed["kwargs"]["cwd"]) == ROOT
    assert observed["kwargs"]["creationflags"] == supervisor_recovery.CREATE_NO_WINDOW
