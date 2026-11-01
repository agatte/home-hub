# HomeHub #431 - operator-only, read-only aggregate CSV inspection.
# DRAFT / REVIEW HOLD: do not run with private CSV until approval.
# This script is NEVER invoked by HomeHub, Codex, Sandbox automation or services.
$ErrorActionPreference = 'Stop'
$scanner = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend\services\apple_music_history_inspector.py'
$expected = 'E25BFC34A3A33A1B0135F772D116179DB971991E352E8DFAB4F67A167D0D21DA'
if (-not (Test-Path -LiteralPath $scanner -PathType Leaf)) {
    throw 'Reviewed inspector is unavailable.'
}
if ((Get-FileHash -LiteralPath $scanner -Algorithm SHA256).Hash -ne $expected) {
    throw 'Inspector SHA-256 changed; reviewed version must be revalidated.'
}
$budget = Join-Path (Split-Path -Parent $scanner) 'apple_music_csv_record_budget.py'
$budgetPin = 'E02788CA4ABEEAD3D136AFF0FAC67061E4F45AD0BFDD8C483A55930F5B7ABA9D'
if (-not (Test-Path -LiteralPath $budget -PathType Leaf) -or
    (Get-FileHash -LiteralPath $budget -Algorithm SHA256).Hash -ne $budgetPin) {
    throw 'CSV record budget dependency differs from the reviewed version.'
}
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) { throw 'A normal Python 3 interpreter is required.' }
Add-Type -AssemblyName System.Windows.Forms
$picker = New-Object System.Windows.Forms.OpenFileDialog
$picker.Title = 'Select Apple Music Play Activity.csv (local read-only inspection)'
$picker.Filter = 'CSV files (*.csv)|*.csv'
$picker.CheckFileExists = $true
$picker.Multiselect = $false
if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    Write-Host 'Cancelled. No input read.'
    return
}
$selected = $picker.FileName
if ([System.IO.Path]::GetFileName($selected) -ine 'Apple Music Play Activity.csv') {
    throw 'Only Apple Music Play Activity.csv is allowed.'
}
$file = Get-Item -LiteralPath $selected
if ($file.Length -le 0 -or $file.Length -gt 104857600) {
    throw 'CSV size outside the allowed 100 MiB range.'
}
Write-Host 'Read-only local scan. Aggregate JSON is printed here only.'
Write-Host 'No database import, network access, Sonos action, or automatic sync.'
$confirmation = Read-Host 'Type INSPECT to read the selected CSV'
if ($confirmation -cne 'INSPECT') {
    Write-Host 'Cancelled. No input read.'
    return
}
& $python.Source $scanner $selected
if ($LASTEXITCODE -ne 0) {
    throw 'Scanner rejected the CSV; no import was attempted.'
}
