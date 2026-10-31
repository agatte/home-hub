# HomeHub #431 — private Apple Music CSV local inspection

**Status: first user-initiated, private Windows-local inspection completed successfully.**
No private CSV was transferred. The identity-quality diagnostic is a follow-up
read-only operator run, and is not a persistent import. The Python inspector and
PowerShell launcher remain **uncommitted local Sandbox worktree candidates**.
Neither is running as a HomeHub, Windows host, Latitude or Sonos service.

## Reviewed development evidence

- Synthetic suite: 37 passing tests at 2026-10-31; Ruff and compile checks pass.
- Synthetic stress: 69,918 rows, 93.21 MiB, generated and parsed in 5.59 seconds
  in Windows Sandbox. This does **not** establish correctness for Apple's real
  schema or duplicate-session semantics.
- Inspector SHA-256: `E12F8E3A9F6107CDC4D27AF6774982077DB5C36B747981D00F018CDFD1EA8073`
  after this review. The operator launcher checks this hash before any file picker.
- A separate Codex reviewer task failed **before analysis**, due to a 401
  authentication error; this is **not independent approval**.
- Runtime only uses Python standard library. No imports from HomeHub models,
  services or database.

## Operator-only Windows procedure (read-only, explicitly user initiated)

The first run succeeded on the real Windows PC using direct Python invocation.
Its aggregate results identify potentially non-track-specific Provider ID buckets.
The updated report adds aggregate `provider_identity_quality` metrics: distinct
provider IDs among playback ends, collisions across distinct song/album labels,
rows and candidates affected, largest bucket size and distinct metadata-only
song/album labels. No IDs, names, row samples or hashed identifiers are emitted.

PowerShell scripts are restricted on this host. **Do not change execution
policy**. In the same normal, non-admin PowerShell session after the first run,
`$csvPath` remains the locally selected file and `$python` the Python path.
Use direct Python with a fresh hash check for the updated diagnostic:

```powershell
$scanner = 'C:\Users\Anthony\Documents\home-hub-project\worktrees\apple-history-inspector-431\backend\services\apple_music_history_inspector.py'
if ((Get-FileHash -LiteralPath $scanner -Algorithm SHA256).Hash -ne 'E12F8E3A9F6107CDC4D27AF6774982077DB5C36B747981D00F018CDFD1EA8073') { throw 'Inspector changed; stop.' }
if (-not $csvPath -or -not (Test-Path -LiteralPath $csvPath -PathType Leaf)) { throw 'Select the CSV locally as in the first run.' }
& (Get-Command python.exe -ErrorAction Stop).Source $scanner $csvPath
```

The older GUI launcher is retained as a **non-default draft** only for hosts
whose script execution policies permit it. The previously used command is:

```powershell
powershell.exe -NoProfile -File "C:\Users\Anthony\Documents\home-hub-project\worktrees\apple-history-inspector-431\scripts\Inspect-AppleMusicHistory-431.ps1"
```

Do not run this command from Sandbox, RDC, ChatGPT, a service, scheduled task,
or a remote PowerShell session. It is for an explicit human action on the host.

The launcher verifies the exact script hash, opens a native file picker, requires
the basename `Apple Music Play Activity.csv` and a file under 100 MiB, explains
the no-import behavior and requires typing `INSPECT` before reading. It prints
only aggregate JSON to the local PowerShell console, with no output file.

Use only the extracted private CSV already stored on the real Windows PC.
Do not upload or copy Apple ZIP/CSV, individual rows, song lists, raw IDs,
private paths, device fields or account/location fields into GitHub, Obsidian,
Sandbox, Latitude or this conversation. Do not use `Tee-Object`, transcript
logging or output redirection to a synced folder.

## What the aggregate report means

- Event counts are **not** verified unique song plays.
- `distinct_event_ids` counts cryptographic fingerprints of unique event IDs
  within the file; different IDs may describe one playback session.
- Conflicting duplicate IDs revoke candidate evidence to `abstain`, rather
  than arbitrarily accepting the first event.
- `play_end_reason_categories` and `play_end_identity_confidence` isolate the
  subset that can potentially inform the next synthetic-only taste preview.
- `completion_candidate` and `early_skip_candidate` remain diagnostics, not
  positive/negative taste weights. No song or artist is imported or rewarded.
- `provider_identity_quality` is a collision diagnostic, not catalog matching.
  A provider ID seen with multiple distinct song/album labels must not be
  treated as a verified track key. Even a key with one observed label is not
  automatically trustworthy.
- Provider ID populated is **not proof of an exact Apple catalog recording**,
  complete artist identity, or deduplication from Sonos history.
- No inference of physical presence, no away/home state change, no Sonos actions,
  no persistent database writes or automatic Apple Music account sync.

## Limits and remaining gates

The strict CSV reader temporarily materializes full rows **including ignored
sensitive columns**, despite extracting/retaining only allowlisted values for
analysis. Its 100 MiB **binary stream byte budget** includes ignored columns,
and the reader additionally checks physical file metadata, field/row counts,
decoded characters and the same opened file's size/mtime. A malicious writer
could still change bytes without a detectable metadata change; select a stable
local export, not a file being actively modified. It stores bounded digests of
event IDs during the process; the report never includes them.

An authenticated, independent security/privacy review (or a separately accepted
alternative validation) remains the prerequisite for private-data execution.
Commit, push, PR, merge, operator-local private CSV access, database ingestion,
production deployment and autonomous playback are separate gates.
