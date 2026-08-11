"""Isolated restart-agents.ps1 regression tests; no live task/process mutations."""

from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "restart-agents.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def _run(command: str) -> subprocess.CompletedProcess[str]:
    if not POWERSHELL:
        pytest.skip("PowerShell is unavailable")
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-Command", command],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )


def _quoted_path() -> str:
    return str(SCRIPT).replace("'", "''")


def test_process_matcher_excludes_unrelated_supervisor_script():
    result = _run(
        f". '{_quoted_path()}' -FunctionsOnly; "
        "if (Test-HomeHubCommandLine 'pythonw.exe C:\\other\\backup_supervisor.py') "
        "{ exit 9 } else { exit 0 }",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_process_matcher_accepts_system_and_venv_home_hub_modules():
    result = _run(
        f". '{_quoted_path()}' -FunctionsOnly; "
        "$system = Test-HomeHubCommandLine "
        "'C:\\Python313\\pythonw.exe -m backend.services.pc_agent.supervisor --active'; "
        "$venv = Test-HomeHubCommandLine "
        "'C:\\home-hub\\venv\\Scripts\\pythonw.exe -m "
        "backend.services.pc_agent.activity_detector'; "
        "if ($system -and $venv) { exit 0 } else { exit 9 }",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _mocked_script(*, enable_fails: bool, launcher_fails: bool) -> str:
    enable_body = (
        "[Console]::WriteLine('RESTORE_ATTEMPTED'); throw 'reenable failed'"
        if enable_fails
        else "[Console]::WriteLine('RESTORE_ATTEMPTED'); $global:taskState = 'Ready'"
    )
    start_body = "throw 'launcher failed'" if launcher_fails else "$global:launched = $true"
    return f"""
$global:taskState = 'Ready'
$global:launched = $false
$global:replacement = [pscustomobject]@{{
    ProcessId = 4567
    CreationDate = [DateTime]::Now.AddSeconds(2)
    CommandLine = 'pythonw.exe -m backend.services.pc_agent.supervisor --active'
}}
function Get-ScheduledTask {{ param($TaskName, $ErrorAction) [pscustomobject]@{{ State = $global:taskState }} }}
function Disable-ScheduledTask {{ param($TaskName, $ErrorAction) $global:taskState = 'Disabled' }}
function Enable-ScheduledTask {{ param($TaskName, $ErrorAction) {enable_body} }}
function Stop-ScheduledTask {{ param($TaskName, $ErrorAction) }}
function Get-CimInstance {{
    param($ClassName, $Filter, $ErrorAction)
    if ($Filter -eq "Name = 'pythonw.exe'" -and $global:launched) {{ $global:replacement }}
}}
function Start-Process {{ param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle) {start_body} }}
function Start-Sleep {{ param($Milliseconds, $Seconds) }}
function Invoke-RestMethod {{
    param($Uri, $TimeoutSec)
    $identity = "$($global:replacement.ProcessId):$($global:replacement.CreationDate.ToUniversalTime().ToFileTimeUtc())"
    [pscustomobject]@{{ supervisor_pid = 4567; supervisor_instance = $identity }}
}}
& '{_quoted_path()}'
"""


def test_reenable_failure_is_nonzero_and_never_prints_final_ok():
    result = _run(_mocked_script(enable_fails=True, launcher_fails=False))
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE_ATTEMPTED" in output
    assert "OK: replacement supervisor" not in output


def test_earlier_replacement_failure_still_attempts_task_restoration():
    result = _run(_mocked_script(enable_fails=False, launcher_fails=True))
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE_ATTEMPTED" in output
    assert "OK: replacement supervisor" not in output
