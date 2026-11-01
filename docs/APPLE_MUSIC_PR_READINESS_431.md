# #431 — Safe integration / independent review readiness packet

**2026-10-31 · PREPARED ONLY.** Workstream: Sensing & Intelligence / Music Intelligence.
Owning [#431](https://github.com/agatte/home-hub/issues/431), parent
[#254](https://github.com/agatte/home-hub/issues/254).
This packet is NOT consent to commit, push, create a PR, merge, deploy,
perform a private-data run, or enable artist-informed recommendations.

## Current evidence and exact scope

- Sandbox worktree `C:\Work\home-hub-project\worktrees\apple-history-inspector-431`;
  branch `feat/apple-history-inspector-431`;
  unchanged HEAD `9670b3fcbeee5c51f50c29f610c1f150f81ba7db`.
- Exactly **24 intentionally untracked, issue-scoped files**: eight backend
  services, nine tests, six docs, one Windows PowerShell operator script.
  All other tracked worktree content is untouched; there is no staged
  candidate, local commit or published #431 branch/PR.
- GitHub comparison checked on Oct 31: current `master` is **19 commits
  ahead of the worktree base**, and its 21 reported changed paths concern
  Quiet Atlas/lighting/Obsidian; none matched the original 23 #431 file paths; the new readiness doc is
  also outside that comparison's changed paths.
  This is **not** a future merge guarantee and local `origin/master`
  should not be presumed current. Compare live heads and active PRs again
  before any authorized rebase/integration. #432 is an independently open
  Apple handoff documentation PR, not this candidate.
- The operator-proven data grammar is `YYYYMMDD`: all 35,823 Daily Tracks
  `Date Played` values passed. The accepted **anonymous aggregates** are
  19,439 provisional artist-label/day pairs across 2,569 labels; 1,306
  one-day labels, 577 two–three, 344 four–nine, 342 ten-plus; 6,809 initial
  abstentions and 307 further conflict rows. These are **not** verified
  artists, track sessions, Sonos-independent plays, liking or preferences.
  No private source data, raw labels, dates or file paths belong in PR.
- **Reader version already used against private input is pinned and
  unchanged:** `apple_music_artist_local_audit.py` SHA-256
  `DDE9CF79CE9495E55D7E3900E47BCE293D5B3BAE6CA7994BCE19DC05F78BA900`.
  Do not change it and silently reuse old hash-pinned operator commands.

## Bounded files to review / eventually stage *explicitly*

| Source area | Exact candidate paths |
| --- | --- |
| Offline backend services | `backend/services/apple_music_artist_familiarity_preview.py`, `apple_music_artist_local_audit.py`, `apple_music_daily_join_audit.py`, `apple_music_export_schema_probe.py`, `apple_music_history_identity_match.py`, `apple_music_history_inspector.py`, `apple_music_proof_reconciliation.py`, `apple_music_taste_preview.py` (all under `backend/services/`) |
| Synthetic tests | `tests/test_apple_music_artist_familiarity_preview.py`, `test_apple_music_artist_local_audit.py`, `test_apple_music_daily_join_audit.py`, `test_apple_music_export_schema_probe.py`, `test_apple_music_history_identity_match.py`, `test_apple_music_history_inspector.py`, `test_apple_music_proof_reconciliation.py`, `test_apple_music_shadow_exposure_boundary.py`, `test_apple_music_taste_preview.py` (all under `tests/`) |
| Docs | `docs/APPLE_MUSIC_ARTIST_LOCAL_OPERATOR_431.md`, `APPLE_MUSIC_DAILY_JOIN_OPERATOR_431.md`, `APPLE_MUSIC_HISTORY_LOCAL_INSPECTION_431.md`, `APPLE_MUSIC_IDENTITY_FINDINGS_431.md`,  `APPLE_MUSIC_SHADOW_EXPOSURE_DECISION_431.md`,
  `APPLE_MUSIC_PR_READINESS_431.md` (all under `docs/`) |
| Operator entrypoint | `scripts/Inspect-AppleMusicHistory-431.ps1` |

Before staging or publication, inspect **contents and path set** for:
private CSV/archive/ZIP assets; raw artist/song labels/dates, IP or device
data; real-host secrets and credentials; logs or caches; personal temp
files; references to outside worktrees; stale/checksum-mismatched commands;
source-specific event or feedback metadata accidentally treated as taste.
Review doc historical zero histograms as explicitly superseded.

## Independent reviewer / security gate — STILL OPEN

Two read-only Codex review attempts are recorded for this worktree.
Latest task `0683b5bca4444160b99266ad7b801595` exited
`failed` with code 1, worker dead and no review output; no JSONL
events or usable stdout/stderr were found. An **earlier different**
attempt had an authentication 401; the later failure is not proven to
be the same. Do not rerun repeatedly or change credentials/environments
without an evidence-based tooling decision. No independent code or
privacy sign-off currently exists.

**Direct review observations (not independent sign-off):**

- `music_taste.py` maps `MusicArtist(source='import')` play count into
  positive affinity and maximum familiarity. Ingesting Apple label/day
  counts through that path would manufacture a preference and could
  affect rank/trust. No such adapter exists in this candidate.
- Bounded `csv.reader` temporarily materializes *all* CSV columns
  before allowlisting four fields; excluded data are not returned.
  No formal anonymity guarantee applies even to aggregate results.
- The local audit's restricted import graph excludes HomeHub database,
  Sonos, ranking and live-state dependencies. Regression guard now
  checks **both relative and absolute** imports, including synthetic
  attempts to import `music_taste`, `database`, `backend.models`,
  network modules. This guard is intentional fail-on-new-dependency,
  not comprehensive static analysis.
- Exposure from unverified text labels must not be treated as
  catalog identity, unique playback, independent Sonos evidence,
  positive/negative affinity, home/presence, activity or actuation.

**Questions for independent reviewer:** Are private data retained in any
error/exception path? Are byte/row/field and in-memory budgets sufficient?
Do unstable CSV data or symlinks undermine explicit file selection? Does
any collision/alias normalization or group-conflict logic overstate
familiarity? Can reports leak artist/date/track values via exceptions or
a masked aggregate pattern? Can a future import bypass the negative
evidence gates? Does schema or CLI registration unintentionally expose
the operator audit as an HTTP/backend service?

## Local verification and CI packet

After six additional import-graph tests, the ten-test-file targeted
regression packet should contain **292 tests** when green, including
`tests/test_music_taste.py`. This is not a CI result and is not
an assertion about the entire backend suite.

Expected commands (Windows Sandbox worktree with existing `.venv`):
```powershell
$w = 'C:\Work\home-hub-project\worktrees\apple-history-inspector-431'
$py = 'C:\Work\home-hub-project\main\.venv\Scripts\python.exe'
$names = @(
  'test_apple_music_artist_local_audit.py',
  'test_apple_music_artist_familiarity_preview.py',
  'test_apple_music_daily_join_audit.py',
  'test_apple_music_export_schema_probe.py',
  'test_apple_music_history_identity_match.py',
  'test_apple_music_history_inspector.py',
  'test_apple_music_proof_reconciliation.py',
  'test_apple_music_taste_preview.py',
  'test_apple_music_shadow_exposure_boundary.py',
  'test_music_taste.py'
)
& $py -m pytest ($names | ForEach-Object { Join-Path $w ('tests\' + $_) }) -q
# Also run Ruff on the eight #431 modules and these ten tests.
```
Check `git diff --check`; note this does **not** inspect untracked
files, so run tests/format checks on explicit files. On an authorized
published PR, run the repo's actual full Linux CI/lint/backend/frontend
checks and inspect results at the exact PR head, not prior local green.

## Normal future integration order (no actions authorized here)

1. Obtain independent security/privacy/provenance review; make bounded
   code changes and rerun synthetic tests. No need to rerun a user's
   private export solely to exercise test fixtures.
2. Decide product scope: anonymous local-only exposure (existing) vs a
   separately opt-in identified-artist shadow view (not yet approved).
   Identity reconciliation, source provenance, cross-source dedup,
   local/persistent retention and withdrawal are **unresolved**.
3. Re-read GitHub master, #431/#254, #432 and the exact worktree. Preserve
   all untracked work, avoid destructive resets/stashes/cleans. Reconcile
   base only with a verified reversible plan and authorization.
4. **At a distinct commit/push/PR gate**, stage the enumerated issue
   files only, review staged diff for sensitive content, commit,
   publish branch and create scoped PR referencing #431.
5. Run independent PR code review + full Linux CI; address findings
   without changing the user-facing source semantics or broadening the
   private-data surface. Merge and deploy remain **separate gates**.
6. No runtime import, migrations, Apple account tokens, music ranking,
   Sonos/queue/device action, presence inference or production writes
   are part of this candidate.

**Durable resume point:** Current work is a synthetic-tested,
unpublished offline feasibility lane. Next actual blocker is **independent
review**, not a missing Apple date format or a request for more CSV
extraction. The real-history date grammar and aggregate results have
already been verified by the operator.


## Exact-date privacy correction after initial green PR head (Oct 31)

The first published PR #439 head `7640f56cafb328c44063c1e7bae8297407d4b415`
passed the three GitHub Actions jobs. A *subsequent direct review*
found a real privacy defect: `apple_music_history_inspector.py` returned
the exact earliest/latest UTC source calendar dates in `utc_coverage`.
Those fields are removed from the forthcoming correction; fixed aggregate
`counts.valid_timestamps` remains. This invalidates any claim that the
initial head is final privacy-reviewed code. Synthetic multi-date
regression and updated SHA pins cover the fix.

Keep the Play Activity inspector checksum in
`scripts/Inspect-AppleMusicHistory-431.ps1` and
`docs/APPLE_MUSIC_HISTORY_LOCAL_INSPECTION_431.md` identical to the
corrected source SHA-256
`853BBAB8C98B47AF4ACF52C87FB0BF3F569ED2DC9DEE12853F9F1DE8E6AA78D7`.
The independently pinned Daily Tracks artist/day reader hash remains
`DDE9CF79CE9495E55D7E3900E47BCE293D5B3BAE6CA7994BCE19DC05F78BA900`.

A GitHub Copilot review-request API action was attempted using GitHub's
documented bot identity, but subsequent GitHub metadata showed no
requested reviewer or completed review. **Independent review remains
unverified and outstanding.** After publishing the correction, verify
exact head, all Linux CI checks and actual reviewer comments. Do not
merge or deploy on an earlier head's green result.


## Nov 1 Codex review correction (prepared, subject to fresh CI)

A direct Codex Code Review of PR #439 found potential CSV-record memory
amplification from extreme comma counts. A shared, offline-only
`backend/services/apple_music_csv_record_budget.py` now bounds physical
line reads, cumulative logical CSV records, and unquoted columns before
Python's `csv.reader` allocates row fields. Quote escapes, quoted commas,
quoted newlines and 256-column normal rows remain supported in synthetic
tests. Both the Daily Tracks join and Play Activity readers use it.
The schema preflight also uses it for safe header parsing and incremental
UTF-8 decoding to tolerate split trailing multibyte data-row content.
A separate artist-join diagnostic now abstains on **any** description with
more than one ` - ` delimiter, even when only one title suffix is observed.
No private export was re-read to test these corrections.

New inspector/checker SHA pins and shared helper SHA are explicitly checked
in the operator commands. These versioned scripts are pending full
Linux CI and fresh independent review; earlier operator-local results were
produced with older pinned versions and must not be represented as having
been verified using the new parser. The standalone Daily Tracks artist
exposure reader remains unchanged and hash-pinned separately.
