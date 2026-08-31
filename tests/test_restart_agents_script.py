"""Isolated restart-agents.ps1 regression tests; no live task/process mutations."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from backend.services.pc_agent.supervisor_recovery import WindowsRecoveryOperations


SCRIPT = Path(__file__).parents[1] / "scripts" / "restart-agents.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
POWERSHELL_TIMEOUT_SECONDS = 30


def _run(command: str) -> subprocess.CompletedProcess[str]:
    if not POWERSHELL:
        pytest.skip("PowerShell is unavailable")
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-Command", command],
        capture_output=True,
        check=False,
        text=True,
        # PowerShell startup and script dot-sourcing are normally quick, but can
        # exceed 15 seconds on a loaded Linux CI runner. This test only asserts
        # an isolated matcher result; it does not exercise restart operations.
        timeout=POWERSHELL_TIMEOUT_SECONDS,
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


def test_cim_precision_loss_does_not_change_native_backend_identity_match():
    result = _run(
        f". '{_quoted_path()}' -FunctionsOnly; "
        "function Get-NativeProcessCreationFileTime { [UInt64]134309599872776092 }; "
        "function Get-CimInstance { [pscustomobject]@{ ProcessId = 4692; "
        "CreationDate = [DateTime]::FromFileTimeUtc(134309599872776090); "
        "CommandLine = 'pythonw.exe -m backend.services.pc_agent.supervisor' } }; "
        "$snapshot = Get-HomeHubProcesses; "
        "$cim = \"$($snapshot.ProcessId):134309599872776090\"; "
        "$backend = '4692:134309599872776092'; "
        "if ($snapshot.Identity -eq $backend -and $cim -ne $backend) "
        "{ exit 0 } else { exit 9 }",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_process_identity_matches_backend_identity_exactly():
    if os.name != "nt":
        pytest.skip("Native Windows process identity is unavailable")
    backend_identity = WindowsRecoveryOperations().identity_for_pid(os.getpid())
    assert backend_identity is not None

    result = _run(
        f". '{_quoted_path()}' -FunctionsOnly; "
        f"$native = Get-NativeProcessIdentity {os.getpid()}; "
        f"if ($native.Identity -eq '{backend_identity.value}') "
        "{ exit 0 } else { exit 9 }",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pid_reuse_with_different_native_creation_time_is_rejected():
    result = _run(
        f". '{_quoted_path()}' -FunctionsOnly; "
        "function Get-CimInstance { "
        "[pscustomobject]@{ ProcessId = 8123; CommandLine = "
        "'pythonw.exe -m backend.services.pc_agent.supervisor' } }; "
        "function Get-NativeProcessCreationFileTime { [UInt64]222 }; "
        "$snapshot = [pscustomobject]@{ ProcessId = 8123; Identity = '8123:111' }; "
        "$inspection = Get-IdentityInspection $snapshot; "
        "if ($inspection.Status -eq 'AbsentOrDifferent') { exit 0 } else { exit 9 }",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_identity_lookup_failure_is_indeterminate_and_never_terminates():
    result = _run(
        f". '{_quoted_path()}' -FunctionsOnly; "
        "$global:terminateCalled = $false; "
        "function Get-CimInstance { "
        "[pscustomobject]@{ ProcessId = 8123; CommandLine = "
        "'pythonw.exe -m backend.services.pc_agent.supervisor' } }; "
        "function Get-NativeProcessCreationFileTime { $null }; "
        "function Invoke-CimMethod { $global:terminateCalled = $true }; "
        "$snapshot = [pscustomobject]@{ ProcessId = 8123; Identity = '8123:111' }; "
        "$inspection = Get-IdentityInspection $snapshot; "
        "$stopped = Stop-ExactIdentity $snapshot; "
        "$gone = Wait-IdentityGone $snapshot 0; "
        "if ($inspection.Status -eq 'Indeterminate' -and -not $stopped -and "
        "-not $gone -and -not $global:terminateCalled) { exit 0 } else { exit 9 }",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_exact_identity_with_unrelated_current_process_is_indeterminate():
    result = _run(
        f". '{_quoted_path()}' -FunctionsOnly; "
        "$global:terminateCalled = $false; "
        "function Get-CimInstance { [pscustomobject]@{ ProcessId = 8123; "
        "CommandLine = 'pythonw.exe C:\\other\\backup_supervisor.py' } }; "
        "function Get-NativeProcessCreationFileTime { [UInt64]111 }; "
        "function Invoke-CimMethod { $global:terminateCalled = $true }; "
        "$snapshot = [pscustomobject]@{ ProcessId = 8123; Identity = '8123:111' }; "
        "$inspection = Get-IdentityInspection $snapshot; "
        "$stopped = Stop-ExactIdentity $snapshot; "
        "if ($inspection.Status -eq 'Indeterminate' -and -not $stopped -and "
        "-not $global:terminateCalled) { exit 0 } else { exit 9 }",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_final_success_requires_matching_pid_and_exact_native_identity():
    result = _run(
        f". '{_quoted_path()}' -FunctionsOnly; "
        "$replacement = [pscustomobject]@{ ProcessId = 4692; "
        "Identity = '4692:134309599872776092' }; "
        "$exact = [pscustomobject]@{ supervisor_pid = 4692; "
        "supervisor_instance = '4692:134309599872776092' }; "
        "$wrongPid = [pscustomobject]@{ supervisor_pid = 4693; "
        "supervisor_instance = '4692:134309599872776092' }; "
        "$wrongInstance = [pscustomobject]@{ supervisor_pid = 4692; "
        "supervisor_instance = '4692:134309599872776090' }; "
        "if ((Test-ReplacementHealthIdentity $exact $replacement) -and "
        "-not (Test-ReplacementHealthIdentity $wrongPid $replacement) -and "
        "-not (Test-ReplacementHealthIdentity $wrongInstance $replacement)) "
        "{ exit 0 } else { exit 9 }",
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
    result = _run(_mocked_script(enable_fails=True, launcher_fails=True))
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE_ATTEMPTED" in output
    assert "Scheduled Task restoration failed: reenable failed" in output
    assert "OK: replacement supervisor" not in output


def test_earlier_replacement_failure_still_attempts_task_restoration():
    result = _run(_mocked_script(enable_fails=False, launcher_fails=True))
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE_ATTEMPTED" in output
    assert "OK: replacement supervisor" not in output
