# #399 existing-task action-only replacement; inert unless explicit keys supplied.
# Source-only code does NOT authorize invocation on the real Windows host.
[CmdletBinding(PositionalBinding = $false)]
param(
    [switch]$Check,
    [switch]$Apply,
    [string]$ApproveTaskName,
    [string]$ApproveNewManifestSha256
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-LiteralPath([string]$Path) {
    if ($Path -cnotmatch '^[A-Z]:\\' -or $Path -match '[%~$`<>"|?*\x00-\x1f]' -or
        $Path.Substring(3).Contains(':') -or [IO.Path]::GetFullPath($Path) -cne $Path) { throw 'path' }
    foreach ($part in $Path.Substring(3).Split('\')) {
        if (!$part -or $part -match '[. ]$' -or
            $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { throw 'path' }
    }
}

function Assert-Plain([string]$Path, [bool]$Directory = $false) {
    Assert-LiteralPath $Path
    $item = Get-Item -LiteralPath $Path -Force
    if (($item -is [IO.DirectoryInfo]) -ne $Directory) { throw 'type' }
    while ($null -ne $item) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'reparse' }
        if ($item -is [IO.DirectoryInfo]) { $item = $item.Parent } else { $item = $item.Directory }
    }
}

function Read-Bounded([string]$Path, [int]$MaxBytes) {
    Assert-Plain $Path
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'Read')
    try {
        if ($stream.Length -gt $MaxBytes) { throw 'size' }
        $result = New-Object byte[] ([int]$stream.Length)
        $offset = 0
        while ($offset -lt $result.Length) {
            $n = $stream.Read($result, $offset, $result.Length - $offset)
            if (!$n) { throw 'short_read' }
            $offset += $n
        }
        return ,$result
    } finally { $stream.Dispose() }
}

function Get-Digest([byte[]]$Bytes) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose() }
}

function Resolve-Sid([string]$AccountOrSid) {
    if (!$AccountOrSid) { throw 'principal' }
    if ($AccountOrSid -match '^S-1-5-21-(?:[1-9][0-9]{0,9}-){3}[1-9][0-9]{0,9}$') {
        return ([Security.Principal.SecurityIdentifier]::new($AccountOrSid)).Value
    }
    return ([Security.Principal.NTAccount]::new($AccountOrSid)).Translate(
        [Security.Principal.SecurityIdentifier]).Value
}

function Get-Operator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($id)
    if (!$id.IsAuthenticated -or $id.IsSystem -or !$id.User -or
        $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
        ![Environment]::UserInteractive -or [Diagnostics.Process]::GetCurrentProcess().SessionId -le 0) {
        throw 'operator'
    }
    $profile = [Environment]::GetFolderPath('UserProfile')
    Assert-LiteralPath $profile
    if ($profile -cnotmatch '^C:\\Users\\[^\\]+$' -or
        (Split-Path $profile -Leaf) -match '^(?i:public|default|all users)$') { throw 'profile' }
    return @{ Sid = $id.User.Value; Profile = $profile }
}

function Get-NewPins {
    return @{
        'create_obsidian_pilot.py' = 'd79b6788ede512dcccaebe226ffa79d0621b7a1db6f68302514bcda21b14542a'
        'launch_obsidian_mirror.py' = '5cdee1d176a26e8f539c28d8aafdc90ff004ecf84c55857c69349a026a16da5f'
        'manage_obsidian_vault.py' = '0fc3981bdad21fe384db3ceae99e46b2bbad142d941272a681430dda82157500'
        'obsidian_github_docs_source.py' = '1d4cddd425c0f4f961fb20654851417aaae39c25429ba66e99208b9137450526'
        'obsidian_raw_blob_transport.py' = '0b44b30519bf6ce7ae2065a51a2d210405290983e21cdb412ff4b48ea88e48d8'
        'obsidian_simple_mirror.py' = 'de9a0b6cb5a5919e9832788b904145f6aa0eb1caaccbd5365990ff2d51f318e6'
        'obsidian_source_verifier.py' = 'eabd0a292a5268903e8fa47b4ea4bc1c49af473ee27bd2324303a9ee2d4fdfbe'
        'obsidian_verified_stage.py' = 'a69a38ca77e8f5444911aca06a949ababd8f407bb8aba6f49baf0b6742f24682'
        'run_obsidian_simple_mirror.py' = '4f8859954d96b6496660e2faacc19b3a9c7e44f7f9bca2b8032e2fbb5dfd3fef'
    }
}

function Assert-NewBundle([string]$NewBundle, [string]$ExpectedManifestHash, $Who, [string]$Python) {
    Assert-Plain $NewBundle $true
    $raw = Read-Bounded ($NewBundle + '\manifest.json') 16384
    if ((Get-Digest $raw) -cne $ExpectedManifestHash) { throw 'manifest_pin' }
    $utf8 = [Text.UTF8Encoding]::new($false, $true)
    $spec = $utf8.GetString($raw) | ConvertFrom-Json
    $keys = @('source_commit','user_root','sid','bundle','python','python_sha256','vault','files')
    $expectedVersion = '5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5'
    if (@(Compare-Object @($spec.PSObject.Properties.Name) $keys).Count -or
        $spec.source_commit -cne $expectedVersion -or $spec.user_root -cne $Who.Profile -or
        $spec.sid -cne $Who.Sid -or $spec.bundle -cne $NewBundle -or $spec.python -cne $Python -or
        $spec.vault -cne ($Who.Profile + '\Documents\HomeHub Knowledge Vault') -or
        $spec.python_sha256 -cne '85b71d8c6ec1905935f74be0c9869aae198d00e98f39df699ec66f9c5a84cecd') {
        throw 'binding'
    }
    Assert-Plain $spec.vault $true
    $pins = Get-NewPins
    if (@(Compare-Object @($spec.files.PSObject.Properties.Name) @($pins.Keys)).Count -or
        @(Compare-Object @(Get-ChildItem -LiteralPath $NewBundle -Force | ForEach-Object Name)
            (@($pins.Keys) + 'manifest.json')).Count) { throw 'membership' }
    foreach ($key in $pins.Keys) {
        if ($spec.files.$key -cne $pins[$key] -or
            (Get-Digest (Read-Bounded ($NewBundle + '\' + $key) 2097152)) -cne $pins[$key]) {
            throw 'module_pin'
        }
    }
    Assert-Plain $Python
    if ((Get-Digest (Read-Bounded $Python 104857600)) -cne $spec.python_sha256) { throw 'python_pin' }
}

function Assert-TaskShape($Task, [string]$Sid, [string]$Python, [string]$Bundle, [string]$Arguments) {
    if (!$Task -or $Task.Name -cne 'HomeHub Obsidian Mirror Refresh' -or
        $Task.Path -cne '\HomeHub Obsidian Mirror Refresh' -or $Task.Enabled -ne $true -or
        $Task.State -ne 3) { throw 'task_state' }
    $d = $Task.Definition
    if (!$d -or $d.RegistrationInfo.URI -cne '\HomeHub Obsidian Mirror Refresh' -or
        (Resolve-Sid $d.Principal.UserId) -cne $Sid -or
        $d.Principal.LogonType -ne 3 -or $d.Principal.RunLevel -ne 0 -or
        $d.Actions.Count -ne 1 -or $d.Actions.Context -cne 'OrdinaryUser' -or
        $d.Triggers.Count -ne 2) { throw 'definition' }
    $s = $d.Settings
    if ($s.Enabled -ne $true -or $s.MultipleInstances -ne 2 -or
        $s.AllowHardTerminate -ne $false -or $s.StartWhenAvailable -ne $false -or
        $s.WakeToRun -ne $false -or $s.ExecutionTimeLimit -cne 'PT0S' -or
        $s.DisallowStartIfOnBatteries -ne $false -or $s.StopIfGoingOnBatteries -ne $false -or
        $s.RunOnlyIfNetworkAvailable -ne $false -or $s.RestartCount -ne 0) {
        throw 'settings'
    }
    $logon = $d.Triggers.Item(1)
    $calendar = $d.Triggers.Item(2)
    if ($logon.Type -ne 9 -or $logon.Enabled -ne $true -or
        (Resolve-Sid $logon.UserId) -cne $Sid -or
        $calendar.Type -ne 2 -or $calendar.Enabled -ne $true -or
        $calendar.StartBoundary -cne '2026-10-19T00:00:00' -or
        $calendar.DaysInterval -ne 1 -or $calendar.Repetition.Interval -cne 'PT1H' -or
        $calendar.Repetition.Duration -cne 'P1D' -or
        $calendar.Repetition.StopAtDurationEnd -ne $false) { throw 'triggers' }
    $action = $d.Actions.Item(1)
    if ($action.Type -ne 0 -or $action.Path -cne $Python -or
        $action.Arguments -cne $Arguments -or $action.WorkingDirectory -cne $Bundle) {
        throw 'action'
    }
}

function New-SchedulerConnection {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    return $service
}

function Assert-SafeSchedulerWindow($Task) {
    # An UPDATE may not run while a scheduled instance is starting. This does
    # not eliminate a separate sign-in race; any uncertain mutation still STOPs.
    $next = [datetime]$Task.NextRunTime
    if ($next -le [datetime]::Now.AddMinutes(2)) { throw 'imminent_trigger' }
}

function Invoke-UpdateOnly($Folder, $Task, [string]$Sid, [string]$Python,
                           [string]$NewBundle, [string]$NewArguments) {
    $definition = $Task.Definition
    $action = $definition.Actions.Item(1)
    $action.Path = $Python
    $action.Arguments = $NewArguments
    $action.WorkingDirectory = $NewBundle
    # TASK_UPDATE (4), never CREATE (2) or CREATE_OR_UPDATE (6).
    return $Folder.RegisterTaskDefinition(
        'HomeHub Obsidian Mirror Refresh', $definition, 4, $Sid, $null, 3, $null)
}

$updateAttempted = $false
try {
    if (!$Check -and !$Apply -and !$ApproveTaskName -and !$ApproveNewManifestSha256) {
        Write-Output '{"status":"off","mutated":false}'
        exit 0
    }
    if (($Check -eq $Apply) -or $ApproveTaskName -cne 'HomeHub Obsidian Mirror Refresh' -or
        $ApproveNewManifestSha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'keys' }

    $who = Get-Operator
    $profile = $who.Profile
    $python = $profile + '\AppData\Local\Programs\Python\Python313\python.exe'
    $parent = $profile + '\AppData\Local\HomeHub\ObsidianMirror'
    $old = $parent + '\f91407d165fd1263319bbadc45586da3681560aa'
    $new = $parent + '\5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5'
    $oldAnchor = 'ea38293f9e18831674f2af857b41e5d6a29e48761c855972f7c6586f9aa1a3bc'
    Assert-Plain $old $true
    if ((Get-Digest (Read-Bounded ($old + '\manifest.json') 16384)) -cne $oldAnchor -or
        (Get-Digest (Read-Bounded ($old + '\launch_obsidian_mirror.py') 2097152)) -cne
        'e8771f93a7c8d694242b2e4015f369e9daea11e8e564ccb56da3ac0a6e29efcd') {
        throw 'old_pin'
    }
    Assert-NewBundle $new $ApproveNewManifestSha256 $who $python
    $oldArgs = '-I -B "' + $old + '\launch_obsidian_mirror.py" --run --anchor ' + $oldAnchor
    $newArgs = '-I -B "' + $new + '\launch_obsidian_mirror.py" --run --anchor ' +
        $ApproveNewManifestSha256

    $service = New-SchedulerConnection
    $folder = $service.GetFolder('\')
    $task = $folder.GetTask('HomeHub Obsidian Mirror Refresh')
    Assert-TaskShape $task $who.Sid $python $old $oldArgs
    if ($Check) {
        Write-Output '{"status":"verified_action_only_plan","mutated":false}'
        exit 0
    }
    # Both absence of a running instance and unchanged old action are rechecked
    # immediately before the only COM update. Any uncertainty means STOP.
    $fresh = $folder.GetTask('HomeHub Obsidian Mirror Refresh')
    Assert-TaskShape $fresh $who.Sid $python $old $oldArgs
    if ((Get-Digest (Read-Bounded ($new + '\manifest.json') 16384)) -cne
        $ApproveNewManifestSha256) { throw 'manifest_drift' }

    Assert-SafeSchedulerWindow $fresh
    # Preserve the ordinary interactive principal; no Run/Stop/Delete actions.
    $updateAttempted = $true
    $updated = Invoke-UpdateOnly $folder $fresh $who.Sid $python $new $newArgs
    Assert-TaskShape $updated $who.Sid $python $new $newArgs
    Assert-TaskShape ($folder.GetTask('HomeHub Obsidian Mirror Refresh')) $who.Sid $python $new $newArgs
    Write-Output '{"status":"existing_action_updated_verified","mutated":true}'
    exit 0
} catch {
    if ($updateAttempted) {
        Write-Output '{"status":"update_uncertain_STOP_manual_review","mutated":"unknown"}'
    } else {
        Write-Output '{"status":"migration_refused","mutated":false}'
    }
    exit 2
}
