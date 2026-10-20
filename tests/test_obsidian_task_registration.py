"""Offline PowerShell functions and mocks only: never connect to Task Scheduler."""
import base64
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import package_obsidian_schedule as package
from test_obsidian_schedule_launcher import spec

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/register_obsidian_mirror_task.ps1"
PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

# The mocked COM/AST checks require native Windows PowerShell. Linux CI cannot run them.
# Keep the full suite active in the protected Windows Sandbox instead of failing on Linux.
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows PowerShell")


def ps(code, functions=True):
    prefix = ""
    if functions:
        # Parse and load ONLY declarations. Main body and COM factory never execute.
        prefix = f"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}',[ref]$tokens,[ref]$errors)
if ($errors.Count) {{ throw 'parse' }}
$ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]}},$false) |
    ForEach-Object {{ . ([scriptblock]::Create($_.Extent.Text)) }}
function New-SchedulerConnection {{ throw 'COM forbidden in tests' }}
"""
    encoded = base64.b64encode((prefix + code).encode("utf-16le")).decode()
    result = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def test_parser_and_default_off():
    assert ps(f"& '{SCRIPT}'", functions=False) == '{"status":"off","registered":false}'
    assert ps("'parsed'") == "parsed"


def test_native_plain_path_walk_and_bounded_file_read(tmp_path):
    # Provider-added PSIsContainer is not present on .Parent/.Directory FileSystemInfo.
    # Exercise the real on-disk ancestor walk under Set-StrictMode, not a path mock.
    folder = tmp_path / "native_path"
    folder.mkdir()
    filename = folder / "manifest.json"
    data = b'{"test":true}'
    filename.write_bytes(data)
    assert ps(f"""
Assert-Plain {literal(str(folder))} $true
Assert-Plain {literal(str(filename))}
$read=Read-Bounded {literal(str(filename))} 128
if ((Get-Digest $read) -cne {literal(package.digest(data))}) {{ throw 'unexpected hash' }}
'verified_native_file_path'
""") == "verified_native_file_path"


@pytest.mark.parametrize("args", ["-Check", "-RegisterDisabled", "-ApproveTaskName 'wrong'",
                                  "-XmlPath 'relative.xml'", "-ApproveXmlSha256 'abc'"])
def test_incomplete_keys_refuse_before_identity_or_com(args):
    code = f"& '{SCRIPT}' {args}; exit $LASTEXITCODE"
    encoded = base64.b64encode(code.encode("utf-16le")).decode()
    result = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"status": "registration_refused", "registered": False}


def test_expected_tree_matches_pure_builder():
    data = spec()
    xml = package.task_xml(data)
    args = '-I -B "' + data["bundle"] + '\\launch_obsidian_mirror.py" --run --anchor ' + package.digest(
        package.manifest_bytes(data))
    assert ps(f"""
$expected=Read-TaskXml (Get-ExpectedXml {literal(data['sid'])} {literal(data['python'])}
    {literal(data['bundle'])} {literal(args)})
$actual=Read-TaskXml {literal(xml)}
Assert-Tree $actual.DocumentElement $expected.DocumentElement
'match'
""".replace("\n    ", " ")) == "match"


@pytest.mark.parametrize("change", ["enabled", "extra", "principal", "command", "trigger", "doctype"])
def test_xml_mutations_refuse(change):
    xml = package.task_xml(spec())
    mutated = {
        "enabled": xml.replace("<Enabled>false</Enabled>", "<Enabled>true</Enabled>"),
        "extra": xml.replace("</Settings>", "<Hidden>true</Hidden></Settings>"),
        "principal": xml.replace("LeastPrivilege", "HighestAvailable"),
        "command": xml.replace("python.exe", "cmd.exe"),
        "trigger": xml.replace("PT1H", "PT1M"),
        "doctype": '<!DOCTYPE Task [<!ENTITY x "bad">]>' + xml,
    }[change]
    assert ps(f"""
$expected=Read-TaskXml {literal(xml)}
try {{
    $actual=Read-TaskXml {literal(mutated)}
    Assert-Tree $actual.DocumentElement $expected.DocumentElement
    throw 'accepted mutation'
}} catch {{ if ($_.Exception.Message -eq 'accepted mutation') {{ throw }} }}
'refused'
""") == "refused"


@pytest.mark.parametrize("path", ["relative", r"C:\Users\x\..\a", r"C:\Users\x\%USER%",
                                  r"C:\Users\x\a:stream", r"C:\Users\x\NUL",
                                  r"C:\Users\x\a.", r"C:\Users\\x", r"\\server\share\x"])
def test_literal_paths_refuse(path):
    assert ps(f"try {{ Assert-LiteralPath {literal(path)}; throw 'accepted' }} "
              "catch { if ($_.Exception.Message -eq 'accepted') { throw } }; 'refused'") == "refused"


@pytest.mark.parametrize("mode", ["empty", "existing", "error", "malformed"])
def test_mock_task_lookup_fails_closed(mode):
    body = {
        "empty": "return [pscustomobject]@{Count=0}",
        "existing": "return $global:collection",
        "error": "throw 'ambiguous COM error'",
        "malformed": "return $null",
    }[mode]
    code = r"""
$global:collection=[pscustomobject]@{Count=1}
$global:collection | Add-Member ScriptMethod Item { param($i)
    return [pscustomobject]@{Name='HomeHub Obsidian Mirror Refresh'; Path='\HomeHub Obsidian Mirror Refresh'}
}
$folder=New-Object PSObject
""" + f"$folder | Add-Member ScriptMethod GetTasks {{ param($flags) {body} }}\n"
    code += "try { Assert-Absent $folder; 'absent' } catch { 'refused' }"
    assert ps(code) == ("absent" if mode == "empty" else "refused")


def test_pins_and_mutation_surface():
    pins = json.loads(ps("Get-ReviewedPins | ConvertTo-Json -Compress"))
    assert pins == spec()["files"]
    source = SCRIPT.read_text()
    assert source.count(".RegisterTask(") == 1
    assert "$xmlText, 2, $who.Sid, $null, 3, $null" in source
    for forbidden in (".DeleteTask(", ".Run(", "schtasks", "Start-Process", "Invoke-Expression",
                      "Enabled = $true", "RegisterTaskDefinition"):
        assert forbidden not in source


def test_postflight_enabled_task_refuses_without_cleanup():
    assert ps(r"""
$task=[pscustomobject]@{Enabled=$true; Path='\HomeHub Obsidian Mirror Refresh'}
try { Assert-Postflight $task 'sid' 'python' 'args' 'bundle'; throw 'accepted' }
catch { if ($_.Exception.Message -eq 'accepted') { throw } }
'refused'
""") == "refused"


@pytest.mark.parametrize("mutation", ["", "$d.Principal.LogonType=1", "$d.Principal.UserId='other'",
                                    "$d.Settings.WakeToRun=$true", "$d.Settings.RestartCount=1",
                                    "$d.Settings.Enabled=$true", "$a.Path='cmd.exe'",
                                    "$a.Arguments='changed'", "$c.Repetition.Interval='PT1M'"])
def test_postflight_essential_fields(mutation):
    code = r"""
$d=[pscustomobject]@{
    RegistrationInfo=[pscustomobject]@{URI='\HomeHub Obsidian Mirror Refresh'}
    Principal=[pscustomobject]@{UserId='sid'; LogonType=3; RunLevel=0}
    Settings=[pscustomobject]@{Enabled=$false; MultipleInstances=2; AllowHardTerminate=$false
        StartWhenAvailable=$false; WakeToRun=$false; ExecutionTimeLimit='PT0S'
        DisallowStartIfOnBatteries=$false; StopIfGoingOnBatteries=$false
        RunOnlyIfNetworkAvailable=$false; RestartCount=0}
    Actions=[pscustomobject]@{Count=1; Context='OrdinaryUser'}
    Triggers=[pscustomobject]@{Count=2}
}
$global:a=[pscustomobject]@{Type=0; Path='python'; Arguments='args'; WorkingDirectory='bundle'}
$global:l=[pscustomobject]@{Type=9; UserId='sid'; Enabled=$true}
$global:c=[pscustomobject]@{Type=2; Enabled=$true; StartBoundary='2026-10-19T00:00:00'; DaysInterval=1
    Repetition=[pscustomobject]@{Interval='PT1H'; Duration='P1D'; StopAtDurationEnd=$false}}
$d.Actions | Add-Member ScriptMethod Item {param($i) return $global:a}
$d.Triggers | Add-Member ScriptMethod Item {param($i) if ($i -eq 1) {return $global:l}; return $global:c}
$task=[pscustomobject]@{Enabled=$false; Path='\HomeHub Obsidian Mirror Refresh'; Definition=$d}
MUTATION
try { Assert-Postflight $task 'sid' 'python' 'args' 'bundle'; 'verified' } catch { 'refused' }
""".replace("MUTATION", mutation)
    assert ps(code) == ("refused" if mutation else "verified")


@pytest.mark.parametrize("mismatch", [False, True])
def test_registration_segment_with_mock_com_only(mismatch):
    source = SCRIPT.read_text()
    segment = source[source.index("    $service = New-SchedulerConnection\n"):
                     source.index("    Write-Output '{\"status\":\"registered_disabled_verified")]
    # Execute the actual mutation segment with only fake objects and fake path reads.
    code = r"""
$global:calls=0; $global:postflights=0
$global:folder=New-Object PSObject
$global:folder | Add-Member ScriptMethod GetTasks { param($flags) [pscustomobject]@{Count=0} }
$global:folder | Add-Member ScriptMethod RegisterTask { param($name,$xml,$flags,$sid,$password,$logon,$sddl)
    if ($name -cne 'HomeHub Obsidian Mirror Refresh' -or $flags -ne 2 -or $sid -cne 'test-sid' -or
        $null -ne $password -or $logon -ne 3 -or $null -ne $sddl -or $xml -cne 'reviewed-xml') { throw 'bad call' }
    $global:calls++
    return [pscustomobject]@{Enabled=$false}
}
$global:folder | Add-Member ScriptMethod GetTask { param($name) [pscustomobject]@{Enabled=$false} }
$global:service=New-Object PSObject
$global:service | Add-Member ScriptMethod GetFolder { param($path) return $global:folder }
function New-SchedulerConnection { return $global:service }
function Read-Bounded { return ,([byte[]]@(1)) }
function Get-Digest { return 'approved' }
function Assert-Postflight {
    $global:postflights++
    MISMATCH
}
$who=@{Sid='test-sid'}; $xmlText='reviewed-xml'; $XmlPath='unused'; $ApproveXmlSha256='approved'
$python='python'; $arguments='args'; $bundle='bundle'; $registrationAttempted=$false
try {
SEGMENT
    'verified'
} catch { if (!$registrationAttempted) { throw }; 'uncertain-preserved' }
if ($global:calls -ne 1) { throw 'call count' }
""".replace("MISMATCH", "throw 'postflight mismatch'" if mismatch else "return")
    code = code.replace("SEGMENT", segment)
    assert ps(code) == ("uncertain-preserved" if mismatch else "verified")


@pytest.mark.parametrize("mutation", ["", "$admin=$true", "$identity.IsAuthenticated=$false",
                                    "$identity.IsSystem=$true", "$identity.User=$null",
                                    "$identity.User.Value='S-1-5-18'", "$interactive=$false",
                                    "$session=0"])
def test_effective_token_policy_with_deny_only_admin_membership(mutation):
    assert ps(r"""
$identity=[pscustomobject]@{IsAuthenticated=$true; IsSystem=$false
    User=[pscustomobject]@{Value='S-1-5-21-123-456-789-1001'}
    Groups=@([pscustomobject]@{Value='S-1-5-32-544'; DenyOnly=$true})}
$admin=$false; $interactive=$true; $session=1; $global:roleCalls=0
$principal=New-Object PSObject
$principal | Add-Member ScriptMethod IsInRole { param($role)
    if ($role -ne [Security.Principal.WindowsBuiltInRole]::Administrator) { throw 'wrong role' }
    $global:roleCalls++
    return $admin
}
MUTATION
try { Assert-OperatorToken $identity $principal $interactive $session; 'accepted' }
catch { 'refused' }
if ($identity.IsAuthenticated -and !$identity.IsSystem -and $identity.User -and
    $identity.User.Value -like 'S-1-5-21-*' -and $global:roleCalls -ne 1) { throw 'role not checked' }
""".replace("MUTATION", mutation)) == ("refused" if mutation else "accepted")


@pytest.mark.parametrize("mutation,reason", [
    ("", ""),
    ("$who.Sid='S-1-5-21-123-456-789-1002'", "manifest"),
    ("$who.Profile='C:\\Users\\Public'", "profile"),
    ("$who.Profile='C:\\Users\\Other'", "stable_bundle"),
    ("$spec.source_commit='stale'", "manifest"),
    ("$spec.PSObject.Properties.Remove('sid')", "manifest"),
    ("$spec | Add-Member NoteProperty extra 'unexpected'", "manifest"),
    ("$spec.python_sha256=('a'*64)", "runtime_pin"),
    ("$spec.python='C:\\Users\\Other\\python.exe'", "manifest"),
    ("$spec.vault=$spec.bundle", "vault"),
    ("$spec.files.PSObject.Properties.Remove('launch_obsidian_mirror.py')", "files"),
    ("$spec.files | Add-Member NoteProperty 'extra.py' ('a'*64)", "files"),
    ("$spec.files.'launch_obsidian_mirror.py'=('a'*64)", "source_pin"),
    ("$global:badSource=$true", "source_pin"),
    ("$global:missingSource=$true", "missing"),
    ("$global:extraMember=$true", "membership"),
    ("$global:missingMember=$true", "membership"),
    ("$global:missingManifest=$true", "missing"),
    ("$global:missingPath='C:\\Synthetic\\plan.xml'", "missing"),
    ("$global:missingPath=$spec.python", "missing"),
    ("$global:missingPath=$spec.bundle", "missing"),
    ("$global:badPath=$true", "reparse"),
    ("$global:staleAnchor=$true", "anchor"),
    ("$global:staleXml=$true", "xml_digest"),
    ("$global:enabledXml=$true", "xml_value"),
])
def test_complete_check_main_with_synthetic_reads(mutation, reason):
    data = spec()
    data["python_sha256"] = package.digest(b"synthetic runtime")
    # No task, Vault or bundle is created. All reads map to in-memory fixture bytes
    # or the nine reviewed repository source files; their real hashes are checked.
    code = r"""
$who=@{Sid=SID; Profile=PROFILE; Name='synthetic\ordinary'}
$spec=SPEC | ConvertFrom-Json
$global:badSource=$false; $global:missingSource=$false
$global:extraMember=$false; $global:missingMember=$false
$global:missingManifest=$false; $global:badPath=$false
$global:missingPath=''
$global:staleAnchor=$false; $global:staleXml=$false; $global:enabledXml=$false
$global:schedulerCalls=0; $global:reads=@(); $global:failure=''
MUTATION
$global:manifest=[Text.Encoding]::UTF8.GetBytes(($spec | ConvertTo-Json -Depth 5 -Compress))
$anchor=Get-Digest $global:manifest
if ($global:staleAnchor) { $anchor='a'*64 }
$arguments='-I -B "'+BUNDLE+'\launch_obsidian_mirror.py" --run --anchor '+$anchor
$text=Get-ExpectedXml SID PYTHON BUNDLE $arguments
if ($global:enabledXml) { $text=$text.Replace('<Enabled>false</Enabled>','<Enabled>true</Enabled>') }
$global:xml=[Text.Encoding]::UTF8.GetBytes($text)
$ApproveXmlSha256=Get-Digest $global:xml
if ($global:staleXml) { $ApproveXmlSha256='a'*64 }
$Check=$true; $RegisterDisabled=$false
$ApproveTaskName='HomeHub Obsidian Mirror Refresh'; $XmlPath='C:\Synthetic\plan.xml'
function Get-OperatorIdentity { return $who }
function New-SchedulerConnection { $global:schedulerCalls++; throw 'COM forbidden' }
function Assert-Plain([string]$Path, [bool]$Directory=$false) {
    Assert-LiteralPath $Path
    if ($Path -ceq $global:missingPath) { throw 'missing' }
    if ($global:badPath) { throw 'reparse' }
    $directories=@(BUNDLE, $spec.vault)
    $files=@($XmlPath, PYTHON, (BUNDLE+'\manifest.json'))
    $files+=@(Get-ReviewedPins | ForEach-Object { $_.Keys } | ForEach-Object { BUNDLE+'\'+$_ })
    if (($Directory -and $Path -cnotin $directories) -or
        (!$Directory -and $Path -cnotin $files)) { throw 'unexpected path' }
}
function Get-ChildItem { param($LiteralPath, [switch]$Force)
    if ($LiteralPath -cne BUNDLE -or !$Force) { throw 'unexpected enumeration' }
    $names=@((Get-ReviewedPins).Keys)+'manifest.json'
    if ($global:extraMember) { $names+='extra.py' }
    if ($global:missingMember) { $names=$names | Where-Object { $_ -ne 'launch_obsidian_mirror.py' } }
    $names | ForEach-Object { [pscustomobject]@{Name=$_} }
}
function Read-Bounded([string]$Path, [long]$Limit) {
    Assert-Plain $Path
    $global:reads+=,$Path
    if ($Path -ceq $XmlPath) { $bytes=$global:xml }
    elseif ($Path -ceq PYTHON) { $bytes=[Text.Encoding]::UTF8.GetBytes('synthetic runtime') }
    elseif ($Path -ceq (BUNDLE+'\manifest.json')) {
        if ($global:missingManifest) { throw 'missing' }; $bytes=$global:manifest
    } else {
        $name=Split-Path $Path -Leaf
        if ($name -cnotin @((Get-ReviewedPins).Keys)) { throw 'unexpected source' }
        if ($global:missingSource) { throw 'missing' }
        $bytes=[IO.File]::ReadAllBytes((Join-Path SOURCES $name))
        if ($global:badSource) { $bytes=[byte[]]@(1) }
    }
    if ($bytes.Length -gt $Limit) { throw 'size' }
    return ,$bytes
}
# Execute every original main-body statement, preserving try/catch and both exit
# branches. Rewrite only ExitStatementAst nodes into returns so assertions run.
$start=$ast.EndBlock.Statements | Where-Object { $_.Extent.Text -eq '$registrationAttempted = $false' }
$main=$ast.Extent.Text.Substring($start.Extent.StartOffset)
$exitNodes=$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.ExitStatementAst]},$true)
foreach ($node in ($exitNodes | Sort-Object { $_.Extent.StartOffset } -Descending)) {
    $offset=$node.Extent.StartOffset-$start.Extent.StartOffset
    $main=$main.Remove($offset,$node.Extent.Text.Length).Insert($offset,'return')
}
$main=$main.Replace('} catch {', '} catch { $global:failure=$_.Exception.Message;')
$result=& ([scriptblock]::Create($main))
if ($global:schedulerCalls -ne 0) { throw 'scheduler called in Check' }
if ($global:failure -cne REASON) { throw ('unexpected refusal: '+$global:failure) }
if (!REASON -and $global:reads.Count -ne 12) { throw 'incomplete validation reads' }
$result
"""
    replacements = {"MUTATION": mutation, "REASON": literal(reason),
                    "SID": literal(data["sid"]), "PROFILE": literal(data["user_root"]),
                    "SPEC": literal(json.dumps(data)), "BUNDLE": literal(data["bundle"]),
                    "PYTHON": literal(data["python"]), "SOURCES": literal(str(SCRIPT.parent))}
    for key, value in replacements.items():
        code = code.replace(key, value)
    result = json.loads(ps(code))
    assert result == {"status": "registration_refused" if mutation else "validated_plan_only",
                      "registered": False}
