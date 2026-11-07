"""Offline launcher extraction and real Windows sharing tests; never run Codex."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "scripts" / "CodexSandboxTask.ps1"
SPEC = importlib.util.spec_from_file_location(
    "retirement", SCRIPT.with_name("safe_retire_worktree.py"))
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
TARGET = r"C:\Work\home-hub-project\worktrees\fixture-504"


@unittest.skipUnless(os.name == "nt", "Windows FileShare contract")
class LifecycleTests(unittest.TestCase):
    def powershell(self, code):
        return subprocess.run(["powershell.exe", "-NoProfile", "-Command", code],
                              capture_output=True, text=True, timeout=30,
                              env={k: v for k, v in os.environ.items()
                                   if not k.upper().startswith("GIT_")})

    def extraction(self):
        path = str(SCRIPT).replace("'", "''")
        return f"""
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors)
if($errors.Count){{ throw 'Parse failed' }}
$names=@('Get-LifecycleRoot','Assert-LifecyclePath','Open-LifecycleLease','Assert-LifecycleWorktree','Resolve-Work','Open-WorkerLease','Read-QueuedState','Load-Json','Save-Json','UtcNow')
$ast.FindAll({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in $names}},$true) | ForEach-Object {{ Invoke-Expression $_.Extent.Text }}
"""

    def test_root_child_case_and_foreign_paths(self):
        result = self.powershell(self.extraction() + r"""
$root=Get-LifecycleRoot 'C:\Work\home-hub-project\worktrees\Fixture-504'
if($root -cne (Get-LifecycleRoot 'c:\WORK\home-hub-project\worktrees\fixture-504\backend')){ throw 'Child key mismatch' }
foreach($p in @('C:\Users\Anthony\repo','C:\Work\osrs-flip-assistant-project\x','C:\Work\home-hub-project\main')){
 if($null -ne (Get-LifecycleRoot $p)){ throw 'Foreign lifecycle key' }
}
foreach($p in @('C:\Work\home-hub-project\worktrees','C:\Work\home-hub-project\worktrees\bad.name')){
 $refused=$false; try { Get-LifecycleRoot $p }catch{ $refused=$true }; if(-not $refused){ throw 'Invalid path admitted' }
}
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_shared_exclusive_interoperability_and_revalidation(self):
        with tempfile.TemporaryDirectory(dir=SCRIPT.parents[1]) as folder:
            root = Path(folder)
            (root / "codex-run-locks").mkdir()
            setup = self.extraction() + f"$StateRoot='{folder}';\n" + 'function Resolve-Work([string]$Raw) { return $Raw };\n'
            # Stub only Git validation: lock functions and Win32 sharing are real.
            shared = setup + f"""
function Resolve-Work([string]$Raw) {{ return $Raw }}
function Assert-LifecycleWorktree {{ }}
$a=Open-LifecycleLease '{TARGET}'
$b=Open-LifecycleLease '{TARGET}\\backend'
[Console]::WriteLine('ready')
[Console]::Out.Flush()
[Console]::ReadLine() | Out-Null
$b.Dispose(); $a.Dispose()
"""
            process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-Command", shared],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), "ready")
                with patch.object(guard, "RUNS", root / "codex-runs"):
                    with self.assertRaises(guard.Refused), guard.lease(Path(TARGET)):
                        self.fail("Shared workers must exclude retirement")
                process.communicate("release\n", timeout=30)
                self.assertEqual(process.returncode, 0)
                with patch.object(guard, "RUNS", root / "codex-runs"):
                    with guard.lease(Path(TARGET)):
                        result = self.powershell(setup + f"""
$script:validated=$false
function Assert-LifecycleWorktree {{ $script:validated=$true; throw 'Should not reach Git' }}
try {{ $h=Open-LifecycleLease '{TARGET}'; exit 9 }}catch{{ if($script:validated){{ exit 8 }}; exit 0 }}
""")
                        self.assertEqual(result.returncode, 0, result.stderr)
                    # A queued worker after retirement must revalidate, fail, and
                    # release its handle without ever entering the runner.
                    result = self.powershell(setup + f"""
$script:validated=$false
function Assert-LifecycleWorktree {{ $script:validated=$true; throw 'Removed registration' }}
try {{ $h=Open-LifecycleLease '{TARGET}'; exit 9 }}catch{{ if(-not $script:validated){{ exit 8 }}; exit 0 }}
""")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    with guard.lease(Path(TARGET)):
                        pass
                result = self.powershell(setup + "\n$StateRoot+='missing'; Open-LifecycleLease '" + TARGET + "'")
                self.assertNotEqual(result.returncode, 0)
            finally:
                if process.poll() is None:
                    process.communicate("release\n", timeout=30)
                process.stdout.close()
                process.stderr.close()
                process.stdin.close()

    def test_actual_registered_root_and_child_validation(self):
        root = str(SCRIPT.parents[1])
        result = self.powershell(self.extraction() + f"""
$root=Get-LifecycleRoot '{root}\\backend'
Assert-LifecycleWorktree $root '{root}\\backend'
$refused=$false
try {{ Assert-LifecycleWorktree $root '{root}\\missing-lifecycle-fixture' }}catch{{ $refused=$true }}
if(-not $refused){{ throw 'Missing queued workdir admitted' }}
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_workspace_paths_reject_alias_spelling_before_io(self):
        result = self.powershell(self.extraction() + r"""
function Assert-LifecyclePath { throw 'Unexpected filesystem inspection' }
foreach($p in @('\\server\share','C:relative','C:\Work\HOME-H~1\main',
 'C:\Work\home-hub-project\main:stream','C:\Work\home-hub-project\main\..\main',
 'C:\Work\home-hub-project\main\child.','C:\Work\home-hub-project\main\\child',
 ('C:\Work\home-hub-project\'+[char]0x00e4), 'C:\Work\home-hub-project\NUL')){
 $refused=$false
 try { Open-LifecycleLease $p }catch{
  if($_.Exception.Message -eq 'Unexpected filesystem inspection'){ throw }
  $refused=$true
 }
 if(-not $refused){ throw 'Alias admitted' }
}
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nonparticipating_roots_and_child_reparse_ancestry(self):
        # Inject an ancestor's reparse bit; no junction creation or traversal.
        result = self.powershell(self.extraction() + r"""
function Test-Path { return $true }
function Get-Item([string]$LiteralPath){
 if($LiteralPath.Contains('\alias\')){ throw 'Inspected child through alias' }
 $attributes=[IO.FileAttributes]::Directory
 if($LiteralPath.EndsWith('\alias')){ $attributes=$attributes -bor [IO.FileAttributes]::ReparsePoint }
 return [pscustomobject]@{FullName=$LiteralPath; Attributes=$attributes}
}
foreach($p in @('C:\Work\home-hub-project\main\alias\backend',
 'C:\Work\osrs-flip-assistant-project\alias\backend',
 'C:\Work\PC-Performance-Audit\alias\backend', ($env:TEMP+'\alias\backend'),
 'C:\Work\home-hub-project\worktrees\fixture-504\alias\backend')){
 $refused=$false; try { Open-LifecycleLease $p }catch{
  if($_.Exception.Message -ne 'Untrusted lifecycle path.'){ throw }
  $refused=$true
 }; if(-not $refused){ throw 'Child alias admitted' }
}
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reload_generation_and_real_task_exclusion(self):
        with tempfile.TemporaryDirectory(dir=SCRIPT.parents[1]) as folder:
            result = self.powershell(self.extraction() + f"$folder='{folder}';\n" + r"""
$Utf8=New-Object System.Text.UTF8Encoding($false)
$token='a'*32; $next='b'*32
$path=Join-Path $folder 'state.json'
Save-Json $path @{status='queued'; queue_token=$token}
# Cached queued state must not admit after a completed or superseded transition.
$cached=Load-Json $path
foreach($status in @('completed','superseded','queued')){
 Save-Json $path @{status=$status; queue_token=$next}
 $lease=Open-WorkerLease $folder
 try {
  $refused=$false; try { Read-QueuedState $folder $token }catch{ $refused=$true }
  if(-not $refused){ throw 'Stale worker admitted' }
  if($status -eq 'queued'){
   $fresh=Read-QueuedState $folder $next
   if($fresh.queue_token -cne $next){ throw 'Fresh generation lost' }
  }
  # Real Windows sharing excludes Resume/Supersede/Worker competitors.
  $refused=$false; try { $other=Open-WorkerLease $folder; $other.Dispose() }catch{ $refused=$true }
  if(-not $refused){ throw 'Concurrent transition admitted' }
 }finally{ $lease.Dispose() }
}
# Legacy queued records have no generation and require inspected recovery.
Save-Json $path @{status='queued'}
$refused=$false; try { Read-QueuedState $folder $token }catch{ $refused=$true }
if(-not $refused){ throw 'Legacy queue admitted' }
$lease=Open-WorkerLease $folder; $lease.Dispose()
""")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_resume_supersede_serialization_and_release_on_failure(self):
        # Execute the actual action blocks with fixture-only process/launch stubs.
        with tempfile.TemporaryDirectory(dir=SCRIPT.parents[1]) as folder:
            result = self.powershell(self.extraction() + f"$fixture='{folder}';\n" + r"""
$Utf8=New-Object System.Text.UTF8Encoding($false)
$source=[IO.File]::ReadAllText($ast.Extent.File)
$supersede=$source.Substring($source.IndexOf("if($"+'Action -eq ''Supersede''){'))
$supersede=$supersede.Substring(0,$supersede.IndexOf("if($"+'Action -eq ''Resume''){'))
$resume=$source.Substring($source.IndexOf("if($"+'Action -eq ''Resume''){'))
$resume=$resume.Substring(0,$resume.IndexOf("if($"+'Action -ne ''Worker'')'))
function TaskFolder { return $fixture }
function Task-View {
 $s=Load-Json (Join-Path $fixture 'state.json')
 return [pscustomobject]@{worker_alive=$false; status=$s.status}
}
function Assert-No-ActiveWriter { }
function Open-LifecycleLease {
 return [IO.File]::Open((Join-Path $fixture 'lifecycle.lock'),'OpenOrCreate','ReadWrite','None')
}
function Start-Worker {
 # Parent must have released task ownership before a child could acquire it.
 $probe=Open-WorkerLease $fixture; $probe.Dispose()
 return 123
}
$TaskId='c'*32; $VerifiedNoCodexProcess=$true; $Reason='fixture only'
Save-Json (Join-Path $fixture 'task.json') @{workdir=$fixture; ephemeral=$false}
function Reset-State {
 Save-Json (Join-Path $fixture 'state.json') @{
 status='failed'; thread_id='fixture-thread'; expected_thread_id=$null
 worker_pid=$null; worker_start_utc=$null; updated_utc=''; codex_exit_code=1; error=''
 }
}
foreach($actionName in @('Resume','Supersede')){
 Reset-State
 $Action=$actionName
 $block=if($Action -eq 'Resume'){ $resume }else{ $supersede }
 $held=Open-WorkerLease $fixture
 try {
  $refused=$false; try { & ([scriptblock]::Create($block)) }catch{ $refused=$true }
  if(-not $refused){ throw 'Transition ignored task ownership' }
  if((Load-Json (Join-Path $fixture 'state.json')).status -ne 'failed'){ throw 'State overwritten' }
 }finally{ $held.Dispose() }
 # Resume's lifecycle handle must have been released on task-lock failure.
 $probe=Open-LifecycleLease; $probe.Dispose()
}
Reset-State
$Action='Resume'; & ([scriptblock]::Create($resume)) | Out-Null
$queued=Load-Json (Join-Path $fixture 'state.json')
if($queued.status -ne 'queued' -or $queued.queue_token -notmatch '^[0-9a-f]{32}$'){ throw 'Resume generation missing' }
# Supersede wins before the delayed child arrives.
$Action='Supersede'; & ([scriptblock]::Create($supersede)) | Out-Null
$probe=Open-WorkerLease $fixture
try {
 $refused=$false; try { Read-QueuedState $fixture $queued.queue_token }catch{ $refused=$true }
 if(-not $refused){ throw 'Superseded child admitted' }
}finally{ $probe.Dispose() }
$Action='Resume'; $refused=$false
try { & ([scriptblock]::Create($resume)) }catch{ $refused=$true }
if(-not $refused){ throw 'Superseded task resumed' }
$probe=Open-WorkerLease $fixture; $probe.Dispose()
$probe=Open-LifecycleLease; $probe.Dispose()
""")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_worker_releases_all_handles_on_setup_and_postflight_errors(self):
        with tempfile.TemporaryDirectory(dir=SCRIPT.parents[1]) as folder:
            result = self.powershell(self.extraction() + f"$fixture='{folder}';\n" + r"""
$Utf8=New-Object System.Text.UTF8Encoding($false)
$source=[IO.File]::ReadAllText($ast.Extent.File)
$worker=$source.Substring($source.IndexOf("if($"+'Action -ne ''Worker'')'))
$StateRoot=$fixture
[IO.Directory]::CreateDirectory((Join-Path $fixture 'codex-run-locks')) | Out-Null
function TaskFolder { return $fixture }
function Open-LifecycleLease {
 return [IO.File]::Open((Join-Path $fixture 'lifecycle.lock'),'OpenOrCreate','ReadWrite','None')
}
function Git-Snapshot { return @{head='fixture'; status=''} }
# This fixture runner cannot launch Codex or any external process.
$Runner={ throw 'fixture runner exception' }
$Action='Worker'; $TaskId='a'*32; $QueueToken='b'*32
Save-Json (Join-Path $fixture 'task.json') @{
 workdir=$fixture; mode='Write'; model=''; ephemeral=$false
}
[IO.File]::WriteAllText((Join-Path $fixture 'combined-prompt.txt'),'fixture')
$realSave=${function:Save-Json}
foreach($failure in @('initial-save','attempt-directory','result-save')){
 $ErrorActionPreference='Stop'
 $script:injectedFailure=''
 & $realSave (Join-Path $fixture 'state.json') @{
 status='queued'; queue_token=$QueueToken; attempts=0; updated_utc=''
 worker_pid=$null; worker_start_utc=$null; error=$null; expected_thread_id=$null
 thread_id=$null; codex_exit_code=$null; last_event_utc=$null
 }
 $script:injectedFailure=$failure
 function Save-Json([string]$Path,$Value){
  if(($script:injectedFailure -eq 'initial-save' -and $Path.EndsWith('state.json') -and $Value.status -eq 'running') -or
     ($script:injectedFailure -eq 'result-save' -and $Path.EndsWith('result.json'))){ throw 'fixture save failure' }
  & $realSave $Path $Value
 }
 if($failure -eq 'attempt-directory'){
  [IO.Directory]::CreateDirectory((Join-Path $fixture 'attempt-001')) | Out-Null
 }
 $refused=$false; try { & ([scriptblock]::Create($worker)) }catch{ $refused=$true }
 if(-not $refused){ throw ('Injected failure not reached: '+$failure) }
 $ErrorActionPreference='Stop'
 $probe=Open-WorkerLease $fixture; $probe.Dispose()
 $probe=Open-LifecycleLease; $probe.Dispose()
 foreach($lock in [IO.Directory]::GetFiles((Join-Path $fixture 'codex-run-locks'))){
  $probe=[IO.File]::Open($lock,'Open','ReadWrite','None'); $probe.Dispose()
 }
 # Attempt-directory remains as evidence; result case uses a new attempt number.
 if($failure -eq 'attempt-directory'){
  $worker=$worker.Replace("'attempt-{0:D3}'", "'postflight-{0:D3}'")
 }
}
""")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_link_and_access_errors_fail_before_validation(self):
        # No ACL or reparse mutations: inject path inspection failures only.
        for reason in ("Untrusted lifecycle path", "Access denied"):
            result = self.powershell(self.extraction() + f"""
$StateRoot='fixture'
function Resolve-Work([string]$Raw) {{ Assert-LifecyclePath $Raw; return $Raw }}
$script:validated=$false
function Assert-LifecyclePath {{ throw '{reason}' }}
function Assert-LifecycleWorktree {{ $script:validated=$true }}
try {{ Open-LifecycleLease '{TARGET}'; exit 9 }}catch{{ if($script:validated){{ exit 8 }}; exit 0 }}
""")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_worker_admission_precedes_running_and_write_lock(self):
        text = SCRIPT.read_text(encoding="utf-8")
        start = text[text.index("if($Action -eq 'Start'){"):text.index("if($Action -eq 'Supersede'){")]
        resume = text[text.index("if($Action -eq 'Resume'){"):text.index("if($Action -ne 'Worker')")]
        self.assertLess(start.index("Open-LifecycleLease"), start.index("Resolve-Work"))
        self.assertLess(start.index("Open-LifecycleLease"), start.index("Git-Snapshot"))
        for block in (start, resume):
            self.assertLess(block.index("Open-LifecycleLease"), block.index("$s.status='queued'" if block is resume else "status='queued'"))
            self.assertIn("if($lifecycleLease){ $lifecycleLease.Dispose() }", block)
        worker = text[text.index("if($Action -ne 'Worker')"):]
        self.assertLess(worker.index("Open-LifecycleLease"), worker.index("$workerLease=Open-WorkerLease"))
        self.assertLess(worker.index("$workerLease=Open-WorkerLease"), worker.index("Read-QueuedState"))
        self.assertNotIn("$s=Load-Json", worker)
        supersede = text[text.index("if($Action -eq 'Supersede'){"):text.index("if($Action -eq 'Resume'){")]
        for block in (resume, supersede):
            self.assertLess(block.index("Open-WorkerLease"), block.index("$s=Load-Json"))
            self.assertIn("$workerLease.Dispose()", block)
        self.assertIn("-QueueToken ", text)
        self.assertIn("}finally{\n    if($workdirLease)", worker)
        self.assertLess(worker.index("Open-LifecycleLease"), worker.index("$s.status='running'"))
        self.assertIn("finally{ if($lifecycleLease)", text)
