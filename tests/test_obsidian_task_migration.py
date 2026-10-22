"""#399 source-only existing-task action migration (synthetic Scheduler only)."""
import base64
from pathlib import Path
import re
import subprocess
import sys
import json

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "migrate_obsidian_mirror_task.ps1"
PINS = ROOT / "scripts" / "obsidian_launcher_pins.json"
PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def powershell(code: str, *, functions: bool = False):
    prelude = ""
    if functions:
        prelude = rf"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('{SCRIPT}',[ref]$tokens,[ref]$errors)
if ($errors.Count) {{ throw 'parse' }}
$ast.FindAll({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]}},$false) |
    ForEach-Object {{ . ([scriptblock]::Create($_.Extent.Text)) }}
function New-SchedulerConnection {{ throw 'COM forbidden in fixture' }}
"""
    encoded = base64.b64encode((prelude + code).encode("utf-16le")).decode("ascii")
    return subprocess.run(
        [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", encoded],
        capture_output=True, text=True, check=False, timeout=30,
    )


def test_source_has_one_update_only_mutation_surface():
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count(".RegisterTaskDefinition(") == 1
    assert re.search(
        r"RegisterTaskDefinition\(\s*'HomeHub Obsidian Mirror Refresh',"
        r"\s*\$definition,\s*4,\s*\$Sid,\s*\$null,\s*3,\s*\$null\)", source
    )
    for forbidden in (
        ".RegisterTask(", ".DeleteTask(", ".Run(", ".Stop(",
        "RegisterTaskDefinition('", "schtasks.exe", "Invoke-Expression",
        "Set-ScheduledTask", "Disable-ScheduledTask", "Enable-ScheduledTask",
        "Remove-Item", "Set-ExecutionPolicy",
    ):
        assert forbidden not in source
    assert "Assert-TaskShape $fresh $who.Sid $python $old $oldArgs" in source
    assert "Assert-TaskShape ($folder.GetTask(" in source
    assert "if ($updateAttempted)" in source


def test_exact_new_source_pins_match_merged_release():
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    assert pins["source_commit"] == "5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5"
    assert len(pins["files"]) == 9
    from hashlib import sha256
    for name, expected in pins["files"].items():
        assert sha256((ROOT / "scripts" / name).read_bytes()).hexdigest() == expected
    source = SCRIPT.read_text(encoding="utf-8")
    for name, expected in pins["files"].items():
        assert f"'{name}' = '{expected}'" in source
    assert "e8771f93a7c8d694242b2e4015f369e9daea11e8e564ccb56da3ac0a6e29efcd" in source


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
def test_default_is_inert_even_with_restricted_parent():
    encoded = base64.b64encode(f"& '{SCRIPT}'; exit $LASTEXITCODE".encode("utf-16le")).decode()
    proc = subprocess.run(
        [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", encoded],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == '{"status":"off","mutated":false}'


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
@pytest.mark.parametrize("args", [
    "-Check",
    "-Apply",
    "-Check -Apply -ApproveTaskName 'HomeHub Obsidian Mirror Refresh' "
    "-ApproveNewManifestSha256 ('a'*64)",
    "-Check -ApproveTaskName wrong -ApproveNewManifestSha256 ('a'*64)",
    "-Apply -ApproveTaskName 'HomeHub Obsidian Mirror Refresh' "
    "-ApproveNewManifestSha256 'broken'",
])
def test_incomplete_or_mismatched_keys_refuse_before_host_access(args):
    # The parameter parser must not attempt to inspect files/Task Scheduler.
    code = f"& '{SCRIPT}' {args}; exit $LASTEXITCODE"
    result = powershell(code)
    assert result.returncode == 2, result.stderr
    assert result.stdout.strip() == '{"status":"migration_refused","mutated":false}'


# Mimics native COM Items without ever connecting to the live Scheduler.
SYNTHETIC_TASK = r"""
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$python='C:\Synthetic\Python313\python.exe'
$bundle='C:\Synthetic\Pinned'
$argsExpected='pinned exact launcher action arguments'
$script:action=[pscustomobject]@{Type=0; Path=$python; Arguments=$argsExpected; WorkingDirectory=$bundle}
$actions=[pscustomobject]@{Count=1; Context='OrdinaryUser'}
$actions | Add-Member ScriptMethod Item {param($i) if($i -ne 1){throw 'index'}; return $script:action}
$script:login=[pscustomobject]@{Type=9; UserId=$sid; Enabled=$true}
$repeat=[pscustomobject]@{Interval='PT1H'; Duration='P1D'; StopAtDurationEnd=$false}
$script:calendar=[pscustomobject]@{Type=2; Enabled=$true; StartBoundary='2026-10-19T00:00:00'; DaysInterval=1; Repetition=$repeat}
$triggers=[pscustomobject]@{Count=2}
$triggers | Add-Member ScriptMethod Item {param($i) if($i -eq 1){return $script:login}; if($i -eq 2){return $script:calendar}; throw 'index'}
$settings=[pscustomobject]@{
    Enabled=$true; MultipleInstances=2; AllowHardTerminate=$false
    StartWhenAvailable=$false; WakeToRun=$false; ExecutionTimeLimit='PT0S'
    DisallowStartIfOnBatteries=$false; StopIfGoingOnBatteries=$false
    RunOnlyIfNetworkAvailable=$false; RestartCount=0
}
$definition=[pscustomobject]@{
    RegistrationInfo=[pscustomobject]@{URI='\HomeHub Obsidian Mirror Refresh'}
    Principal=[pscustomobject]@{UserId=$sid; LogonType=3; RunLevel=0}
    Actions=$actions; Triggers=$triggers; Settings=$settings
}
$task=[pscustomobject]@{
    Name='HomeHub Obsidian Mirror Refresh'; Path='\HomeHub Obsidian Mirror Refresh'
    Enabled=$true; State=3; Definition=$definition
}
"""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows COM-like fixture only")
@pytest.mark.parametrize("mutation", [
    "",
    "$task.State=4",
    "$task.Enabled=$false",
    "$definition.Principal.UserId='S-1-5-18'",
    "$definition.Principal.RunLevel=1",
    "$settings.Enabled=$false",
    "$settings.MultipleInstances=0",
    "$calendar.Repetition.Interval='PT30M'",
    "$script:login.Enabled=$false",
    "$script:action.Path='C:\\Wrong\\python.exe'",
    "$actions.Context='unexpected'",
    "$triggers.Count=3",
])
def test_fully_specified_task_contract_refuses_drift(mutation):
    code = SYNTHETIC_TASK + "\n" + mutation + r"""
try {
    Assert-TaskShape $task $sid $python $bundle $argsExpected
    'accepted'
} catch {
    'refused'
}
"""
    result = powershell(code, functions=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("accepted" if not mutation else "refused")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows synthetic task only")
@pytest.mark.parametrize("minutes_ahead,accepted", [(1, False), (3, True), (-1, False)])
def test_refuse_imminent_or_past_hourly_trigger(minutes_ahead, accepted):
    code = SYNTHETIC_TASK + f"""
$task | Add-Member NoteProperty NextRunTime ([datetime]::Now.AddMinutes({minutes_ahead}))
try {{ Assert-SafeSchedulerWindow $task; 'safe' }} catch {{ 'refused' }}
"""
    result = powershell(code, functions=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("safe" if accepted else "refused")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows synthetic task only")
def test_update_only_synthetic_task_changes_exactly_three_action_fields():
    code = SYNTHETIC_TASK + r"""
$script:calls=0
$script:flag=-1
$script:mode=-1
$script:principal=''
$folder=[pscustomobject]@{}
$folder | Add-Member ScriptMethod RegisterTaskDefinition {
    param($name,$definition,$flags,$userId,$password,$logonType,$sddl)
    if ($name -cne 'HomeHub Obsidian Mirror Refresh') { throw 'name' }
    $script:calls++
    $script:flag=$flags
    $script:mode=$logonType
    $script:principal=$userId
    return $script:task
}
$script:task=$task
$newPath='C:\Synthetic\Version2'
$newArgs='new independent pinned arguments'
$originalCalendar=$script:calendar.Repetition.Interval
$originalLogon=$script:login.UserId
$originalIdentity=$definition.Principal.UserId
$result=Invoke-UpdateOnly $folder $task $sid $python $newPath $newArgs
Assert-TaskShape $result $sid $python $newPath $newArgs
if ($script:calls -ne 1 -or $script:flag -ne 4 -or
    $script:mode -ne 3 -or $script:principal -cne $sid -or
    $originalCalendar -cne $script:calendar.Repetition.Interval -or
    $originalLogon -cne $script:login.UserId -or
    $originalIdentity -cne $definition.Principal.UserId) { throw 'mutation_scope' }
'UPDATE_ONLY_SYNTHETIC_PASS'
"""
    result = powershell(code, functions=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "UPDATE_ONLY_SYNTHETIC_PASS"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows synthetic task only")
def test_account_name_and_sid_are_semantically_same_operator():
    code = SYNTHETIC_TASK + r"""
$account=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$definition.Principal.UserId=$account
$script:login.UserId=$account
try {
    Assert-TaskShape $task $sid $python $bundle $argsExpected
    'SID_EQUIVALENT'
} catch { throw }
"""
    result = powershell(code, functions=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SID_EQUIVALENT"
