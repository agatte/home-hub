#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$scriptPath=Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts') 'check_obsidian_relocation_preflight.ps1'
if([Environment]::UserName -cne 'WDAGUtilityAccount'){throw 'must_be_sandbox'}
. $scriptPath -LibraryOnly
function Fake([string]$name,[bool]$dir,[bool]$reparse=$false){
    $attr=if($dir){[IO.FileAttributes]::Directory}else{[IO.FileAttributes]::Normal}
    if($reparse){$attr=$attr -bor [IO.FileAttributes]::ReparsePoint}
    [pscustomobject]@{Name=$name;PSIsContainer=$dir;Attributes=$attr}
}
function Refuses([object[]]$items,[string]$part){
    try{$null=Test-SiblingShape -Entries $items;throw 'UNEXPECTED_SUCCESS'}
    catch{if($_.Exception.Message -notlike ('*'+$part+'*')){throw}}
}
$p='.HomeHub Knowledge Vault-homehub-';$a='a'*32;$b='b'*32
$items=@((Fake ($p+'backup-'+$a) $true),(Fake ($p+'completed-stage-'+$a) $true),
         (Fake ($p+'complete-'+$a+'.json') $false),(Fake ($p+'backup-'+$b) $true))
$r=Test-SiblingShape -Entries $items
if($r.Count -ne 4 -or $r.Triples -ne 1 -or $r.Standalone -ne 1 -or
   $r.NamesSHA256.Length -ne 64){throw 'bad_good_case'}
$reverse=@($items);[Array]::Reverse($reverse)
if((Test-SiblingShape -Entries $reverse).NamesSHA256 -cne $r.NamesSHA256){throw 'unstable_fingerprint'}
Refuses @($items[0],$items[1]) 'incomplete'
Refuses @($items[0],$items[1],$items[2],$items[0]) 'duplicate'
Refuses @($items[0],$items[1],(Fake ($p+'complete-'+$a+'.json') $true)) 'wrong_type'
Refuses @($items[0],$items[1],(Fake ($p+'complete-'+$a+'.json') $false $true)) 'reparse'
Refuses @($items[0],$items[1],(Fake ($p+'pending-'+$a) $true)) 'unexpected'
Refuses @($items[0],$items[1],(Fake ($p+'complete-'+$a+'.JSON') $false)) 'unexpected'
Refuses @((Fake ($p+'backup-'+$b) $true)) 'empty'
$historic=New-Object 'System.Collections.Generic.List[object]'
for($i=0;$i -lt 44;$i++){
    $tok=('{0:x32}' -f ($i+1))
    $historic.Add((Fake ($p+'backup-'+$tok) $true))
    $historic.Add((Fake ($p+'completed-stage-'+$tok) $true))
    $historic.Add((Fake ($p+'complete-'+$tok+'.json') $false))
}
for($i=45;$i -lt 49;$i++){
    $tok=('{0:x32}' -f $i)
    $historic.Add((Fake ($p+'backup-'+$tok) $true))
}
$h=Test-SiblingShape -Entries $historic.ToArray()
if($h.Count -ne 136 -or $h.Triples -ne 44 -or $h.Standalone -ne 4){
    throw 'dated_inventory_shape_fixture_failed'
}
Write-Output 'SYNTHETIC_PASS; 44 triples + 4 protected standalones = 136; 7 refusal cases, happy path and stable fingerprint; NO HOST PROBE'
