# Native ordinary-user operator adapter. No invocation is authorized by this file.
[CmdletBinding(PositionalBinding = $false)]
param(
    [switch]$Check,
    [switch]$RegisterDisabled,
    [string]$ApproveTaskName,
    [string]$ApproveXmlSha256,
    [string]$XmlPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-LiteralPath([string]$Path) {
    if ($Path -cnotmatch '^[A-Z]:\\' -or $Path -match '[%~$`<>"|?*\x00-\x1f]' -or
        $Path.Substring(3).Contains(':') -or [IO.Path]::GetFullPath($Path) -cne $Path) { throw 'path' }
    foreach ($part in $Path.Substring(3).Split('\')) {
        if (!$part -or $part -match '[. ]$' -or $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { throw 'path' }
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

function Read-Bounded([string]$Path, [long]$Limit) {
    Assert-Plain $Path
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'Read')
    try {
        if ($stream.Length -gt $Limit) { throw 'size' }
        $bytes = New-Object byte[] ([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $n = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if (!$n) { throw 'short_read' }
            $offset += $n
        }
        return ,$bytes
    } finally { $stream.Dispose() }
}

function Get-Digest([byte[]]$Bytes) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose() }
}

function Read-TaskXml([string]$Text) {
    $settings = New-Object Xml.XmlReaderSettings
    $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $settings.MaxCharactersInDocument = 32768
    $reader = [Xml.XmlReader]::Create([IO.StringReader]::new($Text), $settings)
    try {
        $doc = New-Object Xml.XmlDocument
        $doc.XmlResolver = $null
        $doc.Load($reader)
        return ,$doc
    } finally { $reader.Dispose() }
}

function Assert-Tree($Actual, $Expected) {
    # Exact structure, order, namespace, attributes and literal text; no extra nodes.
    if ($Actual.LocalName -cne $Expected.LocalName -or $Actual.NamespaceURI -cne $Expected.NamespaceURI -or
        $Actual.Attributes.Count -ne $Expected.Attributes.Count -or
        $Actual.ChildNodes.Count -ne $Expected.ChildNodes.Count) { throw 'xml_shape' }
    foreach ($a in $Expected.Attributes) {
        if ($Actual.GetAttribute($a.Name) -cne $a.Value) { throw 'xml_attribute' }
    }
    for ($i = 0; $i -lt $Expected.ChildNodes.Count; $i++) {
        $a = $Actual.ChildNodes[$i]; $e = $Expected.ChildNodes[$i]
        if ($a.NodeType -ne $e.NodeType) { throw 'xml_node' }
        if ($e.NodeType -eq [Xml.XmlNodeType]::Element) { Assert-Tree $a $e }
        elseif ($a.Value -cne $e.Value) { throw 'xml_value' }
    }
}

function Assert-OperatorToken($Identity, $Principal, [bool]$Interactive, [int]$SessionId) {
    if (!$Identity.IsAuthenticated -or $Identity.IsSystem -or !$Identity.User -or
        $Identity.User.Value -notmatch '^S-1-5-21-(?:[1-9][0-9]{0,9}-){3}[1-9][0-9]{0,9}$' -or
        $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
        !$Interactive -or $SessionId -le 0) { throw 'identity' }
    # IsInRole checks the effective token; deny-only Administrators membership is allowed.
}

function Get-OperatorIdentity {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    Assert-OperatorToken $identity $principal ([Environment]::UserInteractive) ([Diagnostics.Process]::GetCurrentProcess().SessionId)
    $account = $identity.User.Translate([Security.Principal.NTAccount]).Value
    if ($account -cne $identity.Name -or
        ([Security.Principal.NTAccount]::new($account)).Translate([Security.Principal.SecurityIdentifier]).Value -cne $identity.User.Value) { throw 'identity' }
    return @{ Sid = $identity.User.Value; Profile = [Environment]::GetFolderPath('UserProfile'); Name = $account }
}

function New-SchedulerConnection {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    return $service
}

function Assert-Absent($Folder) {
    # Enumeration avoids treating an ambiguous COM lookup failure as "not found".
    $tasks = $Folder.GetTasks(1)
    if ($null -eq $tasks -or $tasks.Count -isnot [int] -or $tasks.Count -lt 0) { throw 'lookup' }
    for ($i = 1; $i -le $tasks.Count; $i++) {
        $task = $tasks.Item($i)
        if (!$task.Name -or !$task.Path) { throw 'lookup' }
        if ($task.Name -ieq 'HomeHub Obsidian Mirror Refresh' -or
            $task.Path -ieq '\HomeHub Obsidian Mirror Refresh') { throw 'exists' }
    }
}

function Assert-Postflight($Task, [string]$Sid, [string]$Python, [string]$Arguments, [string]$Bundle) {
    if (!$Task -or $Task.Enabled -ne $false -or $Task.Path -cne '\HomeHub Obsidian Mirror Refresh') { throw 'postflight' }
    $d = $Task.Definition
    if ($d.RegistrationInfo.URI -cne '\HomeHub Obsidian Mirror Refresh' -or
        $d.Principal.UserId -cne $Sid -or $d.Principal.LogonType -ne 3 -or $d.Principal.RunLevel -ne 0 -or
        $d.Settings.Enabled -ne $false -or $d.Settings.MultipleInstances -ne 2 -or
        $d.Settings.AllowHardTerminate -ne $false -or $d.Settings.StartWhenAvailable -ne $false -or
        $d.Settings.WakeToRun -ne $false -or $d.Settings.ExecutionTimeLimit -cne 'PT0S' -or
        $d.Settings.DisallowStartIfOnBatteries -ne $false -or $d.Settings.StopIfGoingOnBatteries -ne $false -or
        $d.Settings.RunOnlyIfNetworkAvailable -ne $false -or $d.Settings.RestartCount -ne 0 -or
        $d.Actions.Count -ne 1 -or $d.Actions.Context -cne 'OrdinaryUser' -or $d.Triggers.Count -ne 2) { throw 'postflight' }
    $a = $d.Actions.Item(1)
    if ($a.Type -ne 0 -or $a.Path -cne $Python -or $a.Arguments -cne $Arguments -or $a.WorkingDirectory -cne $Bundle) { throw 'postflight' }
    $l = $d.Triggers.Item(1); $c = $d.Triggers.Item(2)
    if ($l.Type -ne 9 -or $l.UserId -cne $Sid -or $l.Enabled -ne $true -or
        $c.Type -ne 2 -or $c.Enabled -ne $true -or $c.StartBoundary -cne '2026-10-19T00:00:00' -or
        $c.DaysInterval -ne 1 -or $c.Repetition.Interval -cne 'PT1H' -or
        $c.Repetition.Duration -cne 'P1D' -or $c.Repetition.StopAtDurationEnd -ne $false) { throw 'postflight' }
}

function Get-ReviewedPins {
    return @{
        'create_obsidian_pilot.py' = 'd79b6788ede512dcccaebe226ffa79d0621b7a1db6f68302514bcda21b14542a'
        'launch_obsidian_mirror.py' = 'e8771f93a7c8d694242b2e4015f369e9daea11e8e564ccb56da3ac0a6e29efcd'
        'manage_obsidian_vault.py' = '0fc3981bdad21fe384db3ceae99e46b2bbad142d941272a681430dda82157500'
        'obsidian_github_docs_source.py' = '1d4cddd425c0f4f961fb20654851417aaae39c25429ba66e99208b9137450526'
        'obsidian_raw_blob_transport.py' = '0b44b30519bf6ce7ae2065a51a2d210405290983e21cdb412ff4b48ea88e48d8'
        'obsidian_simple_mirror.py' = 'de9a0b6cb5a5919e9832788b904145f6aa0eb1caaccbd5365990ff2d51f318e6'
        'obsidian_source_verifier.py' = 'eabd0a292a5268903e8fa47b4ea4bc1c49af473ee27bd2324303a9ee2d4fdfbe'
        'obsidian_verified_stage.py' = 'a69a38ca77e8f5444911aca06a949ababd8f407bb8aba6f49baf0b6742f24682'
        'run_obsidian_simple_mirror.py' = '4f8859954d96b6496660e2faacc19b3a9c7e44f7f9bca2b8032e2fbb5dfd3fef'
    }
}

function Get-ExpectedXml([string]$Sid, [string]$Python, [string]$Bundle, [string]$Arguments) {
    $template = @'
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><RegistrationInfo><URI>\HomeHub Obsidian Mirror Refresh</URI></RegistrationInfo><Triggers><LogonTrigger><Enabled>true</Enabled><UserId>SID_PLACEHOLDER</UserId></LogonTrigger><CalendarTrigger><Repetition><Interval>PT1H</Interval><Duration>P1D</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>2026-10-19T00:00:00</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers><Principals><Principal id="OrdinaryUser"><UserId>SID_PLACEHOLDER</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals><Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>false</AllowHardTerminate><StartWhenAvailable>false</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><Enabled>false</Enabled><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT0S</ExecutionTimeLimit></Settings><Actions Context="OrdinaryUser"><Exec><Command>PYTHON_PLACEHOLDER</Command><Arguments>ARGUMENTS_PLACEHOLDER</Arguments><WorkingDirectory>BUNDLE_PLACEHOLDER</WorkingDirectory></Exec></Actions></Task>
'@
    foreach ($pair in @(@('SID_PLACEHOLDER', $Sid), @('PYTHON_PLACEHOLDER', $Python), @('BUNDLE_PLACEHOLDER', $Bundle), @('ARGUMENTS_PLACEHOLDER', $Arguments))) {
        $template = $template.Replace($pair[0], [Security.SecurityElement]::Escape($pair[1]))
    }
    return $template
}

$registrationAttempted = $false
try {
    if (!$Check -and !$RegisterDisabled -and !$ApproveTaskName -and !$ApproveXmlSha256 -and !$XmlPath) {
        Write-Output '{"status":"off","registered":false}'
        exit 0
    }
    if (($Check -eq $RegisterDisabled) -or $ApproveTaskName -cne 'HomeHub Obsidian Mirror Refresh' -or
        $ApproveXmlSha256 -cnotmatch '^[0-9a-f]{64}$' -or !$XmlPath) { throw 'keys' }
    $who = Get-OperatorIdentity
    Assert-LiteralPath $who.Profile
    if ($who.Profile -cnotmatch '^C:\\Users\\[^\\]+$' -or
        (Split-Path $who.Profile -Leaf) -match '^(?i:public|default|all users)$') { throw 'profile' }
    $raw = Read-Bounded $XmlPath 32768
    if ((Get-Digest $raw) -cne $ApproveXmlSha256) { throw 'xml_digest' }
    $utf8 = [Text.UTF8Encoding]::new($false, $true)
    $xmlText = $utf8.GetString($raw)
    $doc = Read-TaskXml $xmlText
    $ns = New-Object Xml.XmlNamespaceManager($doc.NameTable)
    $ns.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
    $exec = $doc.SelectNodes('/t:Task/t:Actions/t:Exec', $ns)
    if ($exec.Count -ne 1) { throw 'action' }
    $bundle = $exec[0].WorkingDirectory
    $python = $exec[0].Command
    $arguments = $exec[0].Arguments
    $base = 'f91407d165fd1263319bbadc45586da3681560aa'
    if ($bundle -cne ($who.Profile + '\AppData\Local\HomeHub\ObsidianMirror\' + $base)) { throw 'stable_bundle' }
    Assert-Plain $bundle $true
    Assert-Plain $python
    if (!$python.StartsWith($who.Profile + '\', [StringComparison]::Ordinal) -or
        (Split-Path $python -Leaf) -cne 'python.exe' -or $python -match '\\(?i:worktrees|\.git)\\') { throw 'python' }
    $manifestRaw = Read-Bounded ($bundle + '\manifest.json') 16384
    $anchor = Get-Digest $manifestRaw
    if ($arguments -cne ('-I -B "' + $bundle + '\launch_obsidian_mirror.py" --run --anchor ' + $anchor)) { throw 'anchor' }
    $spec = $utf8.GetString($manifestRaw) | ConvertFrom-Json
    $keys = @('source_commit','user_root','sid','bundle','python','python_sha256','vault','files')
    if (@(Compare-Object @($spec.PSObject.Properties.Name) $keys).Count -or
        $spec.source_commit -cne $base -or $spec.user_root -cne $who.Profile -or
        $spec.sid -cne $who.Sid -or $spec.bundle -cne $bundle -or $spec.python -cne $python -or
        $spec.python_sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'manifest' }
    Assert-Plain $spec.vault $true
    if (!$spec.vault.StartsWith($who.Profile + '\', [StringComparison]::Ordinal) -or
        $spec.vault -ceq $bundle -or $spec.vault.StartsWith($bundle + '\', [StringComparison]::Ordinal) -or
        $bundle.StartsWith($spec.vault + '\', [StringComparison]::Ordinal)) { throw 'vault' }
    if ((Get-Digest (Read-Bounded $python 104857600)) -cne $spec.python_sha256) { throw 'runtime_pin' }
    $pins = Get-ReviewedPins
    if (@(Compare-Object @($spec.files.PSObject.Properties.Name) @($pins.Keys)).Count) { throw 'files' }
    $members = @(Get-ChildItem -LiteralPath $bundle -Force | ForEach-Object Name)
    if (@(Compare-Object $members (@($pins.Keys) + 'manifest.json')).Count) { throw 'membership' }
    foreach ($name in $pins.Keys) {
        if ($spec.files.$name -cne $pins[$name] -or
            (Get-Digest (Read-Bounded ($bundle + '\' + $name) 2097152)) -cne $pins[$name]) { throw 'source_pin' }
    }
    $expected = Read-TaskXml (Get-ExpectedXml $who.Sid $python $bundle $arguments)
    if ($doc.ChildNodes.Count -ne 1) { throw 'document' }
    Assert-Tree $doc.DocumentElement $expected.DocumentElement
    if ($Check) {
        Write-Output '{"status":"validated_plan_only","registered":false}'
        exit 0
    }
    $service = New-SchedulerConnection
    $folder = $service.GetFolder('\')
    Assert-Absent $folder
    # Last possible drift check before the only mutation; same-user malware is out of scope.
    if ((Get-Digest (Read-Bounded $XmlPath 32768)) -cne $ApproveXmlSha256) { throw 'xml_drift' }
    $registrationAttempted = $true
    $task = $folder.RegisterTask('HomeHub Obsidian Mirror Refresh', $xmlText, 2, $who.Sid, $null, 3, $null)
    Assert-Postflight $task $who.Sid $python $arguments $bundle
    Assert-Postflight ($folder.GetTask('HomeHub Obsidian Mirror Refresh')) $who.Sid $python $arguments $bundle
    Write-Output '{"status":"registered_disabled_verified","registered":true}'
    exit 0
} catch {
    if ($registrationAttempted) {
        Write-Output '{"status":"registration_uncertain_STOP_manual_review_preserve_task","registered":"unknown"}'
    } else { Write-Output '{"status":"registration_refused","registered":false}' }
    exit 2
}
