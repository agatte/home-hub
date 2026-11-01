# #431 — private Daily Tracks artist-label/day histogram operator packet

**Status (2026-11-01): The operator previously completed a local-only,
aggregate-only run and shared anonymous counts; the code remains offline
and does NOT constitute consent to a taste import, account sync or production
use. This version's updated dependency pins have not been rerun on private
data and require independent review.**

This is an **opt-in, local-only, read-only anonymous feasibility audit** of
the existing separately extracted `Apple Music - Play History Daily Tracks.csv`.
No Apple archive upload or move, no scanning folders/ZIP files, no historical
Play Activity file needed, no Git/Obsidian/Latitude/production data writes.
Unlike exact-track learning, only **artist-label/date presence** is counted;
artist labels are not catalog identities, plays, or preference weights.

Implementation files (all under `backend/services` in isolated #431 worktree):

| File | SHA-256 |
| --- | --- |
| `apple_music_artist_local_audit.py` | `DDE9CF79CE9495E55D7E3900E47BCE293D5B3BAE6CA7994BCE19DC05F78BA900` |
| `apple_music_artist_familiarity_preview.py` | `427699DABC46391DD664C9A6280201044DBC4A71F19B9DCFAC91C5A51F7ED76F` |
| `apple_music_daily_join_audit.py` (join auditor) | `DB7EA46CF68938F73F33B301547327593FE20D20AA5146B3B85793A3765165B6` |
| `apple_music_csv_record_budget.py` (shared bounded parser) | `E02788CA4ABEEAD3D136AFF0FAC67061E4F45AD0BFDD8C483A55930F5B7ABA9D` |

## Future optional real-PC operator run — **requires separate user opt-in**

On the *real Windows PC*, in a normal non-admin PowerShell window, run this
**entire** block at once. Do not run if a hash/path guard fails; never paste
individual subsequent commands after a rejection. The standalone file must
already exist at the given path. This is a script run, not an installation,
an execution-policy adjustment, or a HomeHub import.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $root = 'C:\Users\Anthony\Documents\home-hub-project\worktrees\apple-history-inspector-431\backend\services'
    $pins = [ordered]@{
        'apple_music_artist_local_audit.py' = 'DDE9CF79CE9495E55D7E3900E47BCE293D5B3BAE6CA7994BCE19DC05F78BA900'
        'apple_music_artist_familiarity_preview.py' = '427699DABC46391DD664C9A6280201044DBC4A71F19B9DCFAC91C5A51F7ED76F'
        'apple_music_daily_join_audit.py' = 'DB7EA46CF68938F73F33B301547327593FE20D20AA5146B3B85793A3765165B6'
        'apple_music_csv_record_budget.py' = 'E02788CA4ABEEAD3D136AFF0FAC67061E4F45AD0BFDD8C483A55930F5B7ABA9D'
    }
    foreach ($filename in $pins.Keys) {
        $scriptFile = Join-Path $root $filename
        if (-not (Test-Path -LiteralPath $scriptFile -PathType Leaf)) {
            throw 'Required local audit code is missing. Stop.'
        }
        if ((Get-FileHash -LiteralPath $scriptFile -Algorithm SHA256).Hash -ne $pins[$filename]) {
            throw 'Local audit version mismatch. Stop.'
        }
    }

    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Filter = 'CSV (*.csv)|*.csv'
    $picker.Title = 'Select the EXTRACTED Apple Music - Play History Daily Tracks.csv'
    $picker.CheckFileExists = $true
    if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Host 'Cancelled; no audit performed.'
        return
    }
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $reader = Join-Path $root 'apple_music_artist_local_audit.py'
    & $python -B $reader $picker.FileName
    if ($LASTEXITCODE -ne 0) {
        throw 'Local artist audit rejected the selected CSV. Stop.'
    }
}
```

The file picker chooses **one already extracted CSV** anywhere on your PC.
It cannot navigate inside ZIP archives; do not move the CSV merely to match
a presumed folder. This is deliberately NOT part of the current prepared
implementation gate. Do **not** send the original CSV, ZIP, row values, artist
names, song titles, paths, or per-artist day counts into chat.

## Security, interpretation and non-goals

- The program reuses the bounded `_csv_rows` parser: one user-selected
  .csv regular file, max 100 MiB, 250,000 rows, 256 columns, 8192-character source
  fields, UTF-8 BOM handling, duplicate/missing header refusal, strict CSV
  structural checks and change-during-read metadata check.
- Python's CSV library **parses the entire bounded CSV row transiently**.
  Only the four allowlisted fields are passed to the in-memory aggregator:
  `Track Description`, `Date Played`, `Play Count`,
  `Play Duration Milliseconds`. Account, IP, location, device, and other
  data must not be analyzed, retained, logged, hashed, exported, or persisted.
- The only printed result is fixed aggregate JSON. Names, timestamps, dates,
  song titles, IDs and per-artist labels never appear in it or known failure
  messages. Parsed artist/title/day values exist **transiently in RAM** for
  the computation. No application data files are written; `python -B`
  avoids normal Python module bytecode cache writes.
- Accept exact ASCII `YYYY-MM-DD` dates or **fully validated** ISO-like
  timestamps with seconds, optional fractional seconds, and optional
  `Z`/numeric timezone offset. Malformed dates, unsupported suffixes, and
  unrecognized forms abstain; never accept a date prefix alone. The
  source calendar date label is preserved *without* UTC conversion and
  does not represent a unique session. Anonymous `source_quality`
  includes `rows_with_invalid_or_unsupported_day` and fixed
  `date_label_shapes` buckets, with no actual dates or formats values
  copied from the input. The operator's first local run rejected all
  **35,823** rows as non-exact dates; this supports a format mismatch,
  not a finding of zero artist familiarity. A second operator-local run
  also rejected all 35,823 rows after adding full ISO timestamp support.
  The most recent third operator run also returned **no masked patterns**,
  with all 35,823 rows in `rare_or_unclassified_unsupported_rows`.
  This revealed a blind spot in that diagnostic: it required a canonical
  `YYYY-MM-DD` prefix and limited the source string's length. The
  current version removes the prefix requirement for **masked diagnostic
  only**; it reports coarse `unsupported_length_buckets` even for
  oversized values and at most five common date-format patterns
  repeated in at least 20 rows. Every source digit becomes 9, ASCII
  letter becomes A, whitespace becomes _, and other symbols are masked
  except allowlisted structural punctuation. Rare masks are suppressed.
  No original date, word, label or per-row value leaves the script.
  It also supports fully validated standard ISO basic calendar dates
  (`YYYYMMDD`) and standard ISO week dates (`YYYY-Www-D` or basic).
  These are full-format validations, not prefix guesses. Even masked
  aggregates are private; you decide whether to share them.
- Strictly reject ambiguous `Artist - Song` formatting and conflicting
  same-day titles/metrics; multiple songs/plays/repeated rows by one label
  on a day count as one **artist-label/day** only. Unknown/invalid rows
  abstain; errors fail closed. Calendar days are Apple's export date labels,
  not inferred UTC playback-session timestamps.
- Histograms are anonymous and **not unique artist catalog counts**, exact
  playback sessions, liking, dislike, rating, HomeHub preferences, or proof
  that Apple and Sonos listening are independent. No audio, playback,
  house-state, presence, recommendation or database effects.
- **Independent review outstanding.** Successful synthetic tests establish
  only offline behavior, not the real export's precise artist-label grammar
  or privacy acceptance. Running against real personal data requires a
  separately explicit user request. Using it to learn or store anything
  in HomeHub requires separate consent, provenance, retention/withdrawal
  and integration/CI/deploy authorization.
