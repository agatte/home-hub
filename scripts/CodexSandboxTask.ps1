#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Start','Worker','List','Status','Resume','Supersede')][string]$Action='Start',
    [string]$WorkDir='',
    [string]$PromptFile='',
    [ValidateSet('Read','Write')][string]$Mode='Read',
    [string]$Model='',
    [string]$TaskId='',
    [string]$Reason='',
    [string]$QueueToken='',
    [switch]$VerifiedNoCodexProcess
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if($env:USERNAME -ne 'WDAGUtilityAccount'){ throw 'Sandbox-only Codex task orchestration.' }
$StateRoot='C:\Work\PC-Performance-Audit\.rdc-sandbox-state'
$Runs=Join-Path $StateRoot 'codex-runs'
$Runner=Join-Path $StateRoot 'run-codex.cmd'
if(-not (Test-Path -LiteralPath $Runner -PathType Leaf)){ throw 'Codex runner missing.' }
$Utf8=New-Object System.Text.UTF8Encoding($false)

function Save-Json([string]$Path, $Value){
    $tmp=$Path+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
    [IO.File]::WriteAllText($tmp,($Value | ConvertTo-Json -Depth 12),$Utf8)
    if([IO.File]::Exists($Path)){ [IO.File]::Replace($tmp,$Path,$Path+'.previous') }
    else { [IO.File]::Move($tmp,$Path) }
}
function Load-Json([string]$Path){
    if(-not (Test-Path -LiteralPath $Path -PathType Leaf)){ throw "Missing task record: $Path" }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}
function UtcNow { return [DateTime]::UtcNow.ToString('o') }
function TaskFolder([string]$Id){
    if($Id -notmatch '^[0-9a-f]{32}$'){ throw 'TaskId must be a 32-hex GUID.' }
    return (Join-Path $Runs $Id)
}
function Resolve-Work([string]$Raw){
    if([string]::IsNullOrWhiteSpace($Raw)){ throw 'WorkDir required.' }
    # Deliberately narrow spelling: no UNC/device, ADS, 8.3, Unicode or
    # normalization aliases. Validate lexically before inspecting any ancestors.
    if($Raw -cnotmatch '^[Cc]:\\[A-Za-z0-9_ .\\-]+$'){ throw 'Invalid workspace path spelling.' }
    foreach($part in $Raw.Substring(3).Split('\')){
        if(-not $part -or $part -eq '.' -or $part -eq '..' -or $part.EndsWith('.') -or $part.EndsWith(' ') -or $part -match '^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])($|\.)'){
            throw 'Noncanonical workspace component.'
        }
    }
    $resolved=[IO.Path]::GetFullPath($Raw).TrimEnd('\')
    $roots=@('C:\Work\home-hub-project','C:\Work\osrs-flip-assistant-project','C:\Work\PC-Performance-Audit',([IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')))
    $permitted=$false
    foreach($root in $roots){
        if($resolved.Equals($root,[StringComparison]::OrdinalIgnoreCase) -or $resolved.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){ $permitted=$true; break }
    }
    if(-not $permitted){ throw "WorkDir outside Sandbox roots: $resolved" }
    Assert-LifecyclePath $resolved
    if(-not (Test-Path -LiteralPath $resolved -PathType Container)){ throw "WorkDir missing or not a directory: $resolved" }
    return $resolved
}
function Git-Snapshot([string]$Dir){
    # PowerShell 5.1 turns harmless native stderr warnings into terminating errors under Stop.
    $ErrorActionPreference='Continue'
    $g=Get-Command git.exe -ErrorAction SilentlyContinue
    if(-not $g){ return @{head=$null; status=$null} }
    $safe=$Dir.Replace('\','/')
    $head=(& $g.Source -c "safe.directory=$safe" -C $Dir rev-parse HEAD 2>$null | Out-String).Trim()
    if($LASTEXITCODE -ne 0){ return @{head=$null; status=$null} }
    $status=(& $g.Source -c "safe.directory=$safe" -C $Dir status --porcelain=v1 -b 2>$null | Out-String).Trim()
    return @{head=$head; status=$status}
}
function Assert-LifecyclePath([string]$Path){
    # Inspect from the volume root down, before looking through any child.
    $ancestors=New-Object 'System.Collections.Generic.Stack[string]'
    $cursor=[IO.Path]::GetFullPath($Path)
    while($cursor){
        $ancestors.Push($cursor)
        $parent=[IO.Directory]::GetParent($cursor)
        if($null -eq $parent){ break }
        $cursor=$parent.FullName
    }
    while($ancestors.Count){
        $item=Get-Item -LiteralPath $ancestors.Pop() -Force -ErrorAction Stop
        if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){ throw 'Untrusted lifecycle path.' }
    }
}
function Get-LifecycleRoot([string]$Raw){
    # Called only after Resolve-Work rejects aliases and missing ancestors.
    # Missing queued worktrees cannot fall back to non-HomeHub behavior. ASCII names
    # participate, so Python normcase and Ordinal lowercase produce identical keys.
    $path=[IO.Path]::GetFullPath($Raw).TrimEnd('\')
    $boundary='C:\Work\home-hub-project\worktrees'
    if($path.Equals($boundary,[StringComparison]::OrdinalIgnoreCase)){ throw 'Worktree root required.' }
    if(-not $path.StartsWith($boundary+'\',[StringComparison]::OrdinalIgnoreCase)){ return $null }
    $name=$path.Substring($boundary.Length+1).Split('\')[0]
    if($name -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]*$'){ throw 'Invalid lifecycle worktree name.' }
    return ($boundary+'\'+$name).ToLowerInvariant()
}
function Assert-LifecycleWorktree([string]$Root,[string]$Dir){
    Assert-LifecyclePath $Root
    Assert-LifecyclePath $Dir
    Assert-LifecyclePath (Join-Path $Root '.git')
    if(-not [IO.File]::Exists((Join-Path $Root '.git'))){ throw 'Linked worktree metadata required.' }
    Assert-LifecyclePath 'C:\Work\home-hub-project\main\.git'
    $pointer=[IO.File]::ReadAllText((Join-Path $Root '.git')).Trim()
    if(-not $pointer.StartsWith('gitdir: ')){ throw 'Malformed linked worktree metadata.' }
    $admin=$pointer.Substring(8).Replace('/','\')
    if(-not [IO.Path]::IsPathRooted($admin) -or -not ([IO.Path]::GetFullPath($admin).Equals($admin,[StringComparison]::OrdinalIgnoreCase)) -or
       -not ([IO.Path]::GetDirectoryName($admin).Equals('C:\Work\home-hub-project\main\.git\worktrees',[StringComparison]::OrdinalIgnoreCase))){ throw 'Unexpected worktree administration path.' }
    Assert-LifecyclePath $admin
    Assert-LifecyclePath (Join-Path $admin 'gitdir')
    if(-not ([IO.File]::ReadAllText((Join-Path $admin 'gitdir')).Trim().Replace('/','\').Equals((Join-Path $Root '.git'),[StringComparison]::OrdinalIgnoreCase))){ throw 'Broken worktree backlink.' }
    $git='C:\Tools\Git\cmd\git.exe'
    # Inherited Git redirection must not substitute another repository.
    if(@(Get-ChildItem Env: | Where-Object { $_.Name -like 'GIT_*' }).Count){ throw 'Inherited Git environment refused.' }
    $safe=$Root.Replace('\','/')
    $options=@('-c',"safe.directory=$safe",'-c','core.fsmonitor=false','-c','core.hooksPath=NUL')
    $records=@(& $git @options -C 'C:\Work\home-hub-project\main' -c 'safe.directory=C:/Work/home-hub-project/main' worktree list --porcelain 2>$null)
    if($LASTEXITCODE -ne 0){ throw 'Lifecycle registration unavailable.' }
    $matches=@($records | Where-Object { $_.StartsWith('worktree ') -and $_.Substring(9).Replace('/','\').Equals($Root,[StringComparison]::OrdinalIgnoreCase) })
    if($matches.Count -ne 1){ throw 'Lifecycle worktree is not registered.' }
    $top=(& $git @options -C $Dir rev-parse --show-toplevel 2>$null | Out-String).Trim().Replace('/','\')
    if($LASTEXITCODE -ne 0 -or -not $top.Equals($Root,[StringComparison]::OrdinalIgnoreCase)){ throw 'Lifecycle root mismatch.' }
    $common=(& $git @options -C $Dir rev-parse --path-format=absolute --git-common-dir 2>$null | Out-String).Trim().Replace('/','\')
    if($LASTEXITCODE -ne 0 -or -not $common.Equals('C:\Work\home-hub-project\main\.git',[StringComparison]::OrdinalIgnoreCase)){ throw 'Lifecycle common directory mismatch.' }
}
function Open-LifecycleLease([string]$Raw){
    $work=Resolve-Work $Raw
    $root=Get-LifecycleRoot $work
    if($null -eq $root){ return $null } # Other legitimate Sandbox tasks retain existing behavior.
    $lockRoot=Join-Path $StateRoot 'codex-run-locks'
    Assert-LifecyclePath $lockRoot
    if(-not [IO.Directory]::Exists($lockRoot)){ throw 'Lifecycle lock directory missing.' }
    $hash=[Security.Cryptography.SHA256]::Create()
    try { $digest=[BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($root))).Replace('-','').ToLowerInvariant() }
    finally { $hash.Dispose() }
    $path=Join-Path $lockRoot ('lifecycle-'+$digest+'.lock')
    if(Test-Path -LiteralPath $path){ Assert-LifecyclePath $path }
    $handle=[IO.File]::Open($path,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        Assert-LifecyclePath $path
        # Crucially AFTER acquisition, including Worker/Resume after queued delay.
        Assert-LifecycleWorktree $root $work
        return $handle
    }catch{ $handle.Dispose(); throw }
}
function Worker-Live($State,[string]$Id){
    if($null -eq $State.worker_pid -or [int]$State.worker_pid -le 0){ return $false }
    $p=Get-Process -Id ([int]$State.worker_pid) -ErrorAction SilentlyContinue
    if($null -eq $p){ return $false }
    try {
        $actual=$p.StartTime.ToUniversalTime()
        $expected=[DateTime]::Parse([string]$State.worker_start_utc).ToUniversalTime()
        if([Math]::Abs(($actual-$expected).TotalSeconds) -gt 3){ return $false }
        $c=Get-CimInstance Win32_Process -Filter ("ProcessId = "+[int]$State.worker_pid) -ErrorAction Stop
        if($null -eq $c -or -not ([string]$c.CommandLine).Contains($Id)){ return $false }
        return $true
    }catch{ return $false }
}
function Task-View([string]$Id){
    $folder=TaskFolder $Id
    $task=Load-Json (Join-Path $folder 'task.json')
    $s=Load-Json (Join-Path $folder 'state.json')
    $live=Worker-Live $s $Id
    $effective=[string]$s.status
    if($effective -eq 'running' -and -not $live){ $effective='interrupted-or-unverified' }
    if($effective -eq 'queued'){
        $age=([DateTime]::UtcNow - [DateTime]::Parse([string]$s.updated_utc).ToUniversalTime()).TotalSeconds
        if($age -gt 120 -and -not $live){ $effective='queued-stale' }
    }
    [pscustomobject][ordered]@{
        task_id=$Id; status=$effective; recorded_status=$s.status; worker_alive=$live
        worker_pid=$s.worker_pid; thread_id=$s.thread_id; attempts=$s.attempts
        last_event_utc=$s.last_event_utc; codex_exit_code=$s.codex_exit_code
        workdir=$task.workdir; mode=$task.mode; ephemeral=$task.ephemeral
        folder=$folder; last_message=(Join-Path $folder 'last-message.txt')
    }
}
function Assert-No-ActiveWriter([string]$Dir,[string]$Except=''){
    if(-not (Test-Path -LiteralPath $Runs -PathType Container)){ return }
    foreach($d in @(Get-ChildItem -LiteralPath $Runs -Directory)){
        if($d.Name -eq $Except -or $d.Name -notmatch '^[0-9a-f]{32}$'){ continue }
        try {
            $t=Load-Json (Join-Path $d.FullName 'task.json')
            if($t.mode -ne 'Write' -or -not $t.workdir.Equals($Dir,[StringComparison]::OrdinalIgnoreCase)){ continue }
            $v=Task-View $d.Name
            if($v.worker_alive -or $v.status -eq 'queued' -or $v.status -eq 'queued-stale' -or $v.status -eq 'interrupted-or-unverified'){
                throw "Potentially active/unresolved Write task $($d.Name) in same workdir; inspect before starting another."
            }
        }catch{
            if($_.Exception.Message -like 'Potentially active/unresolved*'){ throw }
            throw "Cannot verify prior task $($d.Name); fail closed: $($_.Exception.Message)"
        }
    }
}
function Open-WorkerLease([string]$Folder){
    return [IO.File]::Open((Join-Path $Folder 'worker.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
}
function Read-QueuedState([string]$Folder,[string]$Token){
    $state=Load-Json (Join-Path $Folder 'state.json')
    if($state.status -ne 'queued'){ throw 'Worker refuses non-queued task.' }
    if($Token -notmatch '^[0-9a-f]{32}$' -or
       -not ($state.PSObject.Properties.Name -contains 'queue_token') -or
       [string]$state.queue_token -cne $Token){ throw 'Worker refuses stale queued generation.' }
    return $state
}
function Start-Worker([string]$Id,[string]$Token){
    $folder=TaskFolder $Id
    $s=Load-Json (Join-Path $folder 'state.json')
    if($s.status -ne 'queued' -or $Token -notmatch '^[0-9a-f]{32}$' -or [string]$s.queue_token -cne $Token){ throw 'Invalid queued generation.' }
    $cmd='-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'" -Action Worker -TaskId '+$Id+' -QueueToken '+$Token
    $attempt=[int]$s.attempts+1
    $out=Join-Path $folder ('worker-launch-{0:D3}.stdout.log' -f $attempt)
    $err=Join-Path $folder ('worker-launch-{0:D3}.stderr.log' -f $attempt)
    $p=Start-Process -FilePath 'powershell.exe' -ArgumentList $cmd -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    return $p.Id
}
if($Action -eq 'List'){
    if(Test-Path -LiteralPath $Runs){
        foreach($d in @(Get-ChildItem -LiteralPath $Runs -Directory)){
            if($d.Name -match '^[0-9a-f]{32}$'){
                try { Task-View $d.Name }catch{ Write-Warning ("Cannot read "+$d.Name+": "+$_.Exception.Message) }
            }
        }
    }
    return
}
if($Action -eq 'Status'){
    Task-View $TaskId | ConvertTo-Json -Depth 5
    return
}
if($Action -eq 'Start'){
    $lifecycleLease=Open-LifecycleLease $WorkDir
    try {
    $work=Resolve-Work $WorkDir
    $prompt=[IO.Path]::GetFullPath($PromptFile)
    $temp=[IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
    if(-not $prompt.StartsWith($temp+'\',[StringComparison]::OrdinalIgnoreCase)){ throw 'PromptFile must be Sandbox-local TEMP.' }
    if(-not (Test-Path -LiteralPath $prompt -PathType Leaf)){ throw 'PromptFile missing.' }
    $userPrompt=Get-Content -LiteralPath $prompt -Raw -Encoding UTF8
    if([string]::IsNullOrWhiteSpace($userPrompt)){ throw 'PromptFile empty.' }
    if($Mode -eq 'Write'){ Assert-No-ActiveWriter $work }
    if(-not $TaskId){ $TaskId=[guid]::NewGuid().ToString('N') }
    $folder=TaskFolder $TaskId
    if(Test-Path -LiteralPath $folder){ Task-View $TaskId | ConvertTo-Json -Depth 5; return }
    New-Item -ItemType Directory -Path $folder -ErrorAction Stop | Out-Null
    [IO.File]::WriteAllText((Join-Path $folder 'user-prompt.txt'),$userPrompt,$Utf8)
    $rules=@'
You are working inside the approved Windows Sandbox; its protected mappings, not Codex -C, form the host filesystem boundary.
Only work in the named task/workspace. Never read or disclose .env, keys, passwords, tokens, credential stores, browser profiles, or other secrets.
Do not install/update/download tools, use network fetches, commit, push, merge, deploy, restart services/tasks, change credentials, mutate Host Bridge, or perform destructive cleanup without explicit task authorization.
Preserve unrelated tracked/untracked work. If tooling is missing, stop and report it.
'@
    $nl=[Environment]::NewLine
    if($Mode -eq 'Read'){ $rules+=$nl+'READ-ONLY: do not modify, create, rename, or delete project files.' }
    else{ $rules+=$nl+'WRITE: modify only the files/actions expressly allowed in the task.' }
    $combined=$rules+$nl+'TASK:'+$nl+$userPrompt
    [IO.File]::WriteAllText((Join-Path $folder 'combined-prompt.txt'),$combined,$Utf8)
    $hash=(Get-FileHash -LiteralPath (Join-Path $folder 'combined-prompt.txt') -Algorithm SHA256).Hash
    $pre=Git-Snapshot $work
    $task=[ordered]@{
        id=$TaskId; created_utc=(UtcNow); workdir=$work; mode=$Mode; model=$Model
        ephemeral=($Mode -eq 'Read'); prompt_sha256=$hash; git_head_before=$pre.head
        git_status_before=$pre.status; policy='protected-sandbox-mappings'
    }
    Save-Json (Join-Path $folder 'task.json') $task
    $state=[ordered]@{
        queue_token=[guid]::NewGuid().ToString('N')
        status='queued'; updated_utc=(UtcNow); worker_pid=$null; worker_start_utc=$null
        thread_id=$null; expected_thread_id=$null; attempts=0
        last_event_utc=$null; codex_exit_code=$null; error=$null
    }
    Save-Json (Join-Path $folder 'state.json') $state
    $launchPid=Start-Worker $TaskId ([string]$state.queue_token)
    [pscustomobject]@{task_id=$TaskId; launch_pid=$launchPid; folder=$folder; action='launched-detached'} | ConvertTo-Json
    return
    }finally{ if($lifecycleLease){ $lifecycleLease.Dispose() } }
}
if($Action -eq 'Supersede'){
    $folder=TaskFolder $TaskId
    $workerLease=Open-WorkerLease $folder
    try {
    $s=Load-Json (Join-Path $folder 'state.json')
    $v=Task-View $TaskId
    if($v.worker_alive -or $v.status -eq 'completed'){ throw 'Cannot supersede a live or completed task.' }
    if(-not $VerifiedNoCodexProcess -or [string]::IsNullOrWhiteSpace($Reason)){ throw 'Requires explicit -VerifiedNoCodexProcess and -Reason after process-tree inspection.' }
    $s.status='superseded'; $s.updated_utc=UtcNow
    $s | Add-Member -NotePropertyName superseded_reason -NotePropertyValue $Reason -Force
    Save-Json (Join-Path $folder 'state.json') $s
    Task-View $TaskId | ConvertTo-Json -Depth 5
    return
    }finally{ $workerLease.Dispose() }
}
if($Action -eq 'Resume'){
    $folder=TaskFolder $TaskId
    $task=Load-Json (Join-Path $folder 'task.json')
    $lifecycleLease=Open-LifecycleLease ([string]$task.workdir)
    $workerLease=$null
    try {
    $workerLease=Open-WorkerLease $folder
    $s=Load-Json (Join-Path $folder 'state.json')
    $v=Task-View $TaskId
    if($v.worker_alive -or $v.status -eq 'queued' -or $v.status -eq 'queued-stale'){ throw 'Existing worker may still be active; do not duplicate.' }
    if(-not $VerifiedNoCodexProcess){ throw 'Exact-thread resume requires process-tree inspection and -VerifiedNoCodexProcess.' }
    if($v.status -eq 'completed' -or $v.status -eq 'superseded'){ throw 'Completed or superseded task cannot resume.' }
    if($task.ephemeral -or [string]::IsNullOrWhiteSpace([string]$s.thread_id)){ throw 'Exact thread resume unavailable: inspect and explicitly supersede instead.' }
    Assert-No-ActiveWriter ([string]$task.workdir) $TaskId
    $s.expected_thread_id=$s.thread_id
    $s | Add-Member -NotePropertyName queue_token -NotePropertyValue ([guid]::NewGuid().ToString('N')) -Force
    $s.status='queued'; $s.updated_utc=UtcNow; $s.worker_pid=$null; $s.worker_start_utc=$null
    $s.codex_exit_code=$null; $s.error=$null
    Save-Json (Join-Path $folder 'state.json') $s
    # Persist under task ownership, then release before spawning a nonblocking worker.
    # A concurrent Supersede is safe: Worker reloads status and generation.
    $workerLease.Dispose(); $workerLease=$null
    $launchPid=Start-Worker $TaskId ([string]$s.queue_token)
    [pscustomobject]@{task_id=$TaskId; expected_thread_id=$s.expected_thread_id; launch_pid=$launchPid; action='exact-thread-resume-launched'} | ConvertTo-Json
    return
    }finally{ if($workerLease){ $workerLease.Dispose() }; if($lifecycleLease){ $lifecycleLease.Dispose() } }
}
if($Action -ne 'Worker'){ throw 'Unknown action.' }
$folder=TaskFolder $TaskId
$task=Load-Json (Join-Path $folder 'task.json')
# Hold OS-enforced file handles for the whole attempt: two concurrent launches,
# or two different Write tasks racing on one workdir, must never run together.
$workerLease=$null
$workdirLease=$null
$lifecycleLease=$null
try {
    # Order: lifecycle shared, task exclusive, legacy workdir exclusive. No waits.
    $lifecycleLease=Open-LifecycleLease ([string]$task.workdir)
    $workerLease=Open-WorkerLease $folder
    $s=Read-QueuedState $folder $QueueToken
    if($task.mode -eq 'Write'){
        $lockRoot=Join-Path $StateRoot 'codex-run-locks'
        [IO.Directory]::CreateDirectory($lockRoot) | Out-Null
        $hashAlg=[Security.Cryptography.SHA256]::Create()
        try {
            $bytes=$hashAlg.ComputeHash([Text.Encoding]::UTF8.GetBytes(([string]$task.workdir).ToLowerInvariant()))
            $key=[BitConverter]::ToString($bytes).Replace('-','').ToLowerInvariant()
        }finally{ $hashAlg.Dispose() }
        $workdirLease=[IO.File]::Open((Join-Path $lockRoot ($key+'.lock')),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    }
}catch{
    if($workdirLease){ $workdirLease.Dispose() }
    if($workerLease){ $workerLease.Dispose() }
    if($lifecycleLease){ $lifecycleLease.Dispose() }
    throw ('Refusing concurrent Codex worker: '+$_.Exception.Message)
}
try {
$s.attempts=[int]$s.attempts+1
$s.status='running'; $s.updated_utc=UtcNow; $s.worker_pid=$PID
$s.worker_start_utc=(Get-Process -Id $PID).StartTime.ToUniversalTime().ToString('o')
$s.error=$null
Save-Json (Join-Path $folder 'state.json') $s
$attemptDir=Join-Path $folder ('attempt-{0:D3}' -f $s.attempts)
New-Item -Path $attemptDir -ItemType Directory | Out-Null
$events=Join-Path $attemptDir 'events.jsonl'
$stderr=Join-Path $attemptDir 'stderr.log'
$last=Join-Path $attemptDir 'last-message.txt'
try {
    # Native Codex warning lines on stderr must be logged, not escalated to
    # PowerShell 5.1 NativeCommandError by the outer Stop preference.
    $ErrorActionPreference='Continue'
    # Live Codex SQLite/session state must stay on the Sandbox guest filesystem.
    # Host-mapped folders persist across Sandbox instances but are not a safe
    # SQLite runtime surface. In-guest Windows Sandbox restart preserves this
    # profile state; full close/relaunch intentionally does not.
    $env:CODEX_HOME=Join-Path $env:USERPROFILE '.codex-homehub-rdc'
    $env:CODEX_TASK_WORKDIR=[string]$task.workdir
    $argsList=@('exec','--dangerously-bypass-approvals-and-sandbox','--json','-C',[string]$task.workdir,'-o',$last)
    if(-not [string]::IsNullOrWhiteSpace([string]$task.model)){ $argsList+=@('-m',[string]$task.model) }
    $resuming=-not [string]::IsNullOrWhiteSpace([string]$s.expected_thread_id)
    if($resuming){ $argsList+=@('resume',[string]$s.expected_thread_id,'-') }
    else {
        if($task.ephemeral){ $argsList+='--ephemeral' }
        $argsList+='-'
    }
    $inputFile=Join-Path $folder 'combined-prompt.txt'
    if($resuming){
        $inputFile=Join-Path $attemptDir 'resume-prompt.txt'
        [IO.File]::WriteAllText($inputFile,'Resume this exact task from its existing thread. Inspect current worktree/diff and avoid duplicating already completed work. Preserve all original task safety restrictions. Report what remains and the final result.',$Utf8)
    }
    Get-Content -LiteralPath $inputFile -Raw -Encoding UTF8 | & $Runner @argsList 2>> $stderr | ForEach-Object {
        $line=[string]$_
        [IO.File]::AppendAllText($events,$line+[Environment]::NewLine,$Utf8)
        try {
            $ev=$line | ConvertFrom-Json -ErrorAction Stop
            if($ev.type -eq 'thread.started' -and $ev.thread_id){
                if($resuming -and [string]$ev.thread_id -ne [string]$s.expected_thread_id){ throw 'RESUMED_THREAD_ID_MISMATCH' }
                $s.thread_id=[string]$ev.thread_id
            }
            $s.last_event_utc=UtcNow
            $s.updated_utc=$s.last_event_utc
            Save-Json (Join-Path $folder 'state.json') $s
        }catch{
            if($_.Exception.Message -eq 'RESUMED_THREAD_ID_MISMATCH'){ throw }
        }
    }
    $rc=$LASTEXITCODE
    $s.codex_exit_code=$rc
    if(Test-Path -LiteralPath $last -PathType Leaf){ Copy-Item -LiteralPath $last -Destination (Join-Path $folder 'last-message.txt') -Force }
    if($rc -eq 0){ $s.status='completed' } else { $s.status='failed' }
}catch{
    $s.status='failed'
    $s.error=$_.Exception.Message
    [IO.File]::AppendAllText($stderr,($_.Exception.ToString()+[Environment]::NewLine),$Utf8)
}finally{
    # Attempt Git postflight even after an ordinary worker/CLI exception.
    try {
        $post=Git-Snapshot ([string]$task.workdir)
        Save-Json (Join-Path $attemptDir 'git-after.json') $post
    }catch{
        [IO.File]::AppendAllText($stderr,('Git postflight unavailable: '+$_.Exception.Message+[Environment]::NewLine),$Utf8)
    }
    $s.updated_utc=UtcNow
    Save-Json (Join-Path $folder 'state.json') $s
    Save-Json (Join-Path $attemptDir 'result.json') ([ordered]@{status=$s.status; exit_code=$s.codex_exit_code; thread_id=$s.thread_id; finished_utc=$s.updated_utc; error=$s.error})
}
}finally{
    if($workdirLease){ $workdirLease.Dispose() }
    if($workerLease){ $workerLease.Dispose() }
    if($lifecycleLease){ $lifecycleLease.Dispose() }
}
