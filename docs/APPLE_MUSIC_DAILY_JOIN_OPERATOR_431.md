# Apple Music #431 — Daily Tracks + Play Activity local join audit

Status: **synthetic-tested, operator-only feasibility check**. The operator
must explicitly select each private CSV on the real Windows PC. No original
CSV or raw artist/track name is copied into GitHub, Sandbox, HomeHub,
Obsidian, Latitude, Sonos or chat. **This is not a track import or consent
to automatic Apple account sync.**

## Source and verification

- Script: `backend/services/apple_music_daily_join_audit.py`
- SHA-256: `DB7EA46CF68938F73F33B301547327593FE20D20AA5146B3B85793A3765165B6`
- Inputs: `Apple Music - Play History Daily Tracks.csv` and
  `Apple Music Play Activity.csv`, separately selected as already extracted
  local CSVs. No ZIP enumeration, archive scanning or uploading.
- Output: fixed-schema aggregate JSON to local terminal stdout only.
- Required Daily Tracks columns: `Track Description`, `Date Played`,
  `Play Count`, `Play Duration Milliseconds`.
- Required Play Activity columns: `Event Type`,
  `Event End Timestamp`, `Song Name`.
- Excluded columns are temporarily parsed by Python's CSV reader but not
  retained beyond a row or output. Artist/title/date evidence is temporarily
  retained *only in process memory* for the local matching calculation.
  Neither keys nor hashes are exported. No file is written.
- Each opened CSV has 100 MiB byte limit, 250,000-row limit, maximum 256
  columns and 8,192-character field limit. Files changed during read are
  rejected using same opened descriptor metadata. Treat only stable files
  as candidates; no guarantee against adversarial same-metadata replacement.

## Schema preflight after a wrong selection (October 31)

The first operator attempt selected a different filename and the Daily Tracks
auditor rejected its schema. The later PowerShell commands still ran because
the user pasted/executed separate blocks after the earlier `throw`. No taste
import or runtime write occurred.

**Before another full scan**, classify only the exact previously selected
`$dailyCsv` file, using the standalone header-only source verifier below.
The classifier reads at most 32 KiB and outputs only fixed labels and
allowlisted header-presence counts. It does not output a file path, actual
column names, metadata values, or a song/artist row.

```powershell
& {
    $probe = 'C:\Users\Anthony\Documents\home-hub-project\worktrees\apple-history-inspector-431\backend\services\apple_music_export_schema_probe.py'
    $pin = 'E0F19FEF13F128B34BF4C9C0F1C51218DD2001B68718A867A0B405A12943ABAF'
    if (-not (Test-Path -LiteralPath $probe -PathType Leaf)) { throw 'Schema probe missing. Stop.' }
    if ((Get-FileHash -LiteralPath $probe -Algorithm SHA256).Hash -ne $pin) { throw 'Schema probe differs from tested version. Stop.' }
    $budget = Join-Path (Split-Path -Parent $probe) 'apple_music_csv_record_budget.py'
    if (-not (Test-Path -LiteralPath $budget -PathType Leaf) -or
        (Get-FileHash -LiteralPath $budget -Algorithm SHA256).Hash -ne 'E02788CA4ABEEAD3D136AFF0FAC67061E4F45AD0BFDD8C483A55930F5B7ABA9D') { throw 'Unverified CSV limiter. Stop.' }
    if (-not $dailyCsv -or -not (Test-Path -LiteralPath $dailyCsv -PathType Leaf)) { throw 'Previous CSV selection is unavailable. Stop.' }
    & (Get-Command python.exe -ErrorAction Stop).Source $probe $dailyCsv
    if ($LASTEXITCODE -ne 0) { throw 'Header classification was rejected. Stop.' }
}
```

Share the classification output only. `daily_tracks` means the file has
every expected header; `play_activity` or `track_play_history` means the
wrong export category was selected. `unknown_or_unsupported` includes
unsupported Daily Tracks schema variants or a different file; investigate
with aggregate-only evidence before changing the matcher. Do not disclose
the private path or any source row. Read-only inspection of the exact
selected CSV is permitted only on the user's own host.

## Operator run

PowerShell execution policy is restricted on the user PC; do **not** change
it. In a normal **non-administrator PowerShell** on the real PC, paste the
following inline statements **as one block**. A failed guard aborts the whole block.
They are not a signed .ps1 or executable install.

```powershell
& {
$tool = 'C:\Users\Anthony\Documents\home-hub-project\worktrees\apple-history-inspector-431\backend\services\apple_music_daily_join_audit.py'
$expected = 'DB7EA46CF68938F73F33B301547327593FE20D20AA5146B3B85793A3765165B6'
if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw 'Audit script unavailable. Stop.' }
if ((Get-FileHash -LiteralPath $tool -Algorithm SHA256).Hash -ne $expected) { throw 'Audit version mismatch. Stop.' }
$budget = Join-Path (Split-Path -Parent $tool) 'apple_music_csv_record_budget.py'
if (-not (Test-Path -LiteralPath $budget -PathType Leaf) -or
    (Get-FileHash -LiteralPath $budget -Algorithm SHA256).Hash -ne 'E02788CA4ABEEAD3D136AFF0FAC67061E4F45AD0BFDD8C483A55930F5B7ABA9D') { throw 'Unverified CSV limiter. Stop.' }
Add-Type -AssemblyName System.Windows.Forms
$pick = New-Object System.Windows.Forms.OpenFileDialog
$pick.Filter = 'CSV (*.csv)|*.csv'
$pick.Title = 'Select Apple Music - Play History Daily Tracks.csv'
$pick.CheckFileExists = $true
if ($pick.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'Daily Tracks selection cancelled.' }
$dailyCsv = $pick.FileName
if ([System.IO.Path]::GetFileName($dailyCsv) -ine 'Apple Music - Play History Daily Tracks.csv') { throw 'Wrong Daily Tracks CSV.' }
if (-not $csvPath -or -not (Test-Path -LiteralPath $csvPath -PathType Leaf) -or ([System.IO.Path]::GetFileName($csvPath) -ine 'Apple Music Play Activity.csv')) {
    $pick.Title = 'Select Apple Music Play Activity.csv'
    if ($pick.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'Play Activity selection cancelled.' }
    $csvPath = $pick.FileName
}
if ([System.IO.Path]::GetFileName($csvPath) -ine 'Apple Music Play Activity.csv') { throw 'Wrong Play Activity CSV.' }
& (Get-Command python.exe -ErrorAction Stop).Source $tool $dailyCsv --play-csv $csvPath
if ($LASTEXITCODE -ne 0) { throw 'Join audit was rejected. Stop.' }
}
```

If the Daily Tracks CSV was not included/extracted, stop and report only that
it is missing. Never send source files, titles, full paths or individual rows.
If the scanner rejects the schema, send only its fixed error message.

## How to read the output

- `daily_rows_with_artist_song_separator` is only a description shape count.
- `play_end_same_date_provisional` is same **UTC calendar date**, not a proven
  artist/track join. `play_end_adjacent_date_provisional` allows one-day
  calendar differences to avoid implying exact timezone alignment.
- `play_end_title_only_no_near_date` is not date-supported evidence.
- `play_end_ambiguous_artist` abstains when two artists or multiple plausible
  separator splits describe the same observed title.
- No per-track/artist rating, unscoped history merge, ranking or HomeHub DB
  write occurs. Apple's Daily Tracks may aggregate multiple sessions per day.
- Only after schema/coverage evidence should a separate, consented, reversible
  identity-normalization and canonical taste-preview packet be developed.

Codex independently reviewed PR #439 at `acc6c9e` and found three
P2 issues; the fixes are being verified. A fresh review of the corrected
head and Linux CI are required. This read-only operator diagnostic is
not permission to import Apple taste evidence, change Sonos, or deploy.
Merge and production actions remain separate gates.
