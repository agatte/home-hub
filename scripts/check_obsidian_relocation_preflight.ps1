#requires -Version 5.1
<#
#489 DRAFT: default-off, read-only operator preflight.
No Vault contents, deletions, moves, task invocation or task writes.
A shape check is NOT migration authorization or acceptance.
#>
[CmdletBinding()]
param([switch]$Check,[switch]$LibraryOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Assert-Plain {
    param([object]$Entry,[bool]$Directory)
    if($null -eq $Entry -or [bool]$Entry.PSIsContainer -ne $Directory -or
       (([IO.FileAttributes]$Entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)){
        throw 'wrong_type_or_reparse'
    }
}
function Test-SiblingShape {
    param([object[]]$Entries)
    $prefix='.HomeHub Knowledge Vault-homehub-'
    $pattern='^\.HomeHub Knowledge Vault-homehub-(backup|completed-stage|complete)-([0-9a-f]{32})(\.json)?$'
    $groups=@{}
    $seen=[System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $names=New-Object 'System.Collections.Generic.List[string]'
    foreach($entry in @($Entries)){
        if($null -eq $entry -or $null -eq $entry.Name){continue}
        $name=[string]$entry.Name
        if(-not $name.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){continue}
        if(-not $seen.Add($name)){throw 'duplicate_sibling_name'}
        $match=[regex]::Match($name,$pattern,[Text.RegularExpressions.RegexOptions]::CultureInvariant)
        if(-not $match.Success){throw 'unexpected_or_active_sibling_namespace'}
        $kind=$match.Groups[1].Value; $token=$match.Groups[2].Value
        $extension=$match.Groups[3].Value
        if(($kind -ceq 'complete') -ne ($extension -ceq '.json')){throw 'wrong_receipt_extension'}
        Assert-Plain -Entry $entry -Directory ($kind -cne 'complete')
        if(-not $groups.ContainsKey($token)){$groups[$token]=@{}}
        if($groups[$token].ContainsKey($kind)){throw 'duplicate_kind'}
        $groups[$token][$kind]=$name; $names.Add($name)
    }
    $triples=0;$standalone=0
    foreach($token in $groups.Keys){
        $p=$groups[$token]
        if($p.Count -eq 1 -and $p.ContainsKey('backup')){$standalone++}
        elseif($p.Count -eq 3 -and $p.ContainsKey('backup') -and
               $p.ContainsKey('completed-stage') -and $p.ContainsKey('complete')){$triples++}
        else{throw 'incomplete_sibling_group'}
    }
    if($triples -lt 1 -or $names.Count -ne (3*$triples+$standalone)){throw 'empty_or_inconsistent'}
    $sorted=[string[]]$names.ToArray()
    [Array]::Sort($sorted,[StringComparer]::Ordinal)
    $payload=[Text.Encoding]::UTF8.GetBytes(($sorted -join [char]10))
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$fingerprint=([BitConverter]::ToString($sha.ComputeHash($payload))).Replace('-','').ToLowerInvariant()}
    finally{$sha.Dispose()}
    [pscustomobject]@{
        Count=$names.Count;Triples=$triples;Standalone=$standalone
        NamesSHA256=$fingerprint;Scope='top_level_names_and_types_only'
    }
}
if($LibraryOnly){
    if([Environment]::UserName -cne 'WDAGUtilityAccount'){throw 'sandbox_library_only'}
    return
}
if(-not $Check){
    [pscustomobject]@{status='OFF';checked=$false;move_authorized=$false}|ConvertTo-Json -Compress
    return
}

# Explicit real-host operator invocation only; no generic path parameters.
$profile='C:\Users\Anthony'
$docs=$profile+'\Documents'
$vault=$docs+'\HomeHub Knowledge Vault'
$dest=$docs+'\HomeHub Vault Storage'
$python=$profile+'\AppData\Local\Programs\Python\Python313\python.exe'
$bundle=$profile+'\AppData\Local\HomeHub\ObsidianMirror\5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5'
$exe=$profile+'\AppData\Local\HomeHub\ObsidianMirror\HiddenLauncher\20261025\ObsidianMirrorHiddenLauncher.exe'
if([Environment]::UserName -cne 'Anthony' -or
   [Environment]::GetFolderPath('UserProfile') -cne $profile -or
   [Environment]::GetFolderPath('MyDocuments') -cne $docs){throw 'wrong_profile_or_documents_path'}
$ident=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($ident)
if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'elevated_context_refused'}
foreach($p in @($profile,$docs,$vault)){
    Assert-Plain -Entry (Get-Item -LiteralPath $p -Force -ErrorAction Stop) -Directory $true
}
if(Test-Path -LiteralPath $dest){throw 'occupied_destination'}
foreach($name in @('.obsidian','HomeHub Source')){
    Assert-Plain -Entry (Get-Item -LiteralPath (Join-Path $vault $name) -Force -ErrorAction Stop) -Directory $true
}
$shape=Test-SiblingShape -Entries @(Get-ChildItem -LiteralPath $docs -Force -ErrorAction Stop)
$task=Get-ScheduledTask -TaskName 'HomeHub Obsidian Mirror Refresh' -TaskPath '\' -ErrorAction Stop
if(@($task.Actions).Count -ne 1 -or
   [string]$task.Actions[0].Execute -cne $exe -or
   -not [string]::IsNullOrWhiteSpace([string]$task.Actions[0].Arguments) -or
   [string]$task.Actions[0].WorkingDirectory -cne $bundle -or
   [string]$task.State -ne 'Ready'){throw 'unexpected_task_action_or_state'}
$info=Get-ScheduledTaskInfo -TaskName 'HomeHub Obsidian Mirror Refresh' -TaskPath '\' -ErrorAction Stop
Assert-Plain -Entry (Get-Item -LiteralPath $python -Force -ErrorAction Stop) -Directory $false
$pythonSha=(Get-FileHash -LiteralPath $python -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
[pscustomobject]@{
    status='SHAPE_ONLY_NEEDS_SEALS_ACLS_QUIESCENCE_AND_APPROVAL'
    checked=$true;move_authorized=$false;install_authorized=$false
    destination_absent=$true
    sibling_count=$shape.Count;complete_triples=$shape.Triples
    standalone_backups=$shape.Standalone;names_sha256=$shape.NamesSHA256
    task_state=[string]$task.State;task_last_run=[string]$info.LastRunTime
    task_last_result=[int]$info.LastTaskResult;task_next_run=[string]$info.NextRunTime
    task_old_action_unchanged=$true;python_sha256=$pythonSha
    user_sid_not_disclosed=$true;no_content_seals_or_acl_verification=$true
    timestamp_utc=[DateTime]::UtcNow.ToString('o')
}|ConvertTo-Json -Depth 5
