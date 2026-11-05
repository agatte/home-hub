# Synthetic guest-only build. No host/task/Vault inputs or installation mode.
$ErrorActionPreference = 'Stop'
if ($env:USERNAME -ne 'WDAGUtilityAccount') { throw 'Sandbox account required' }
$root = Split-Path -Parent $PSScriptRoot
if ($root -ne 'C:\Work\home-hub-project\worktrees\obsidian-vault-relocation-prep-489-20261104') { throw 'Wrong workspace' }
$csc = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$out = Join-Path $env:TEMP ('obsidian-489-synthetic-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $out | Out-Null
$gui = Join-Path $out 'refusal.exe'
$smoke = Join-Path $out 'smoke.exe'
& $csc /nologo /target:winexe "/out:$gui" (Join-Path $root 'tests\obsidian_relocation_refusal_fixture.cs')
if ($LASTEXITCODE -ne 0) { throw 'GUI compile failed' }
& $csc /nologo /target:exe "/out:$smoke" (Join-Path $root 'scripts\obsidian_relocation_hidden_process.cs') (Join-Path $root 'tests\obsidian_relocation_hidden_smoke.cs')
if ($LASTEXITCODE -ne 0) { throw 'Smoke compile failed' }
& $smoke --verify-launcher $gui
if ($LASTEXITCODE -ne 0) { throw 'Synthetic smoke failed' }
foreach ($case in @(@{ Args = ''; Code = 78 }, @{ Args = '--unexpected'; Code = 64 })) {
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $gui
    $start.Arguments = $case.Args
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $process = [System.Diagnostics.Process]::Start($start)
    $process.WaitForExit()
    if ($process.ExitCode -ne $case.Code) { throw 'Refusal mismatch' }
    $process.Dispose()
}
Write-Output 'PASS: no-argument refusal 78; extra-argument refusal 64'
Write-Output "Synthetic artifacts retained at $out"
