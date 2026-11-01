# Apple Music #431 — identity feasibility and conservative matching policy

**Status:** October 31, 2026. Real, user-initiated *aggregate-only* read from the
private export; no source file or row/track/artist identification transferred to
the repository, ChatGPT agent runtime or production.

## Verified aggregate result

| Metric | Observed |
| --- | ---: |
| All Play Activity event rows | 69,918 |
| PLAY_END event rows | 46,429 |
| PLAY_END rows with populated Provider ID | 21,290 |
| Distinct Provider IDs on PLAY_END | 98 |
| Provider IDs with multiple distinct song+album labels | 65 |
| PLAY_END rows on those multi-label IDs | 21,246 (99.79% of Provider-ID PLAY_END) |
| Largest PLAY_END count assigned to one Provider ID | 7,785 |
| Largest different song+album label count for one Provider ID | 2,153 |
| Completion and early-skip candidates on multi-label Provider IDs | 13,232 of 13,255 (99.83%) |
| Distinct metadata-only title+album labels, no Provider ID | 7,366 |

The output exposed no song, artist, Provider ID, track, path, location, account or
device identifiers. Dates and coarse coverage are separate aggregate fields.

## Decision: Provider ID is NOT a canonical track identifier

The very high cross-label collision rate invalidates this field as a song key
for this export. Retain Provider ID only as untrusted provider/source metadata.
**Never map the 8,967 completion or 4,288 early-skip diagnostic candidates
into persistent taste or per-song rewards solely by this field.** Even the 23
candidate events not on multi-label IDs are unverified as distinct catalog
recordings. Distinct Event IDs do not prove distinct listening sessions.

The legacy scanner's `identity_confidence.provider_id` label merely means
"Provider ID populated" and does **not** imply identity confidence. Rename
or deprecate this misleading label during a reviewed API compatibility pass.

## Stage-one cross-export prototype, synthetic data only

`backend/services/apple_music_history_identity_match.py` has no I/O, DB or
runtime imports. It accepts synthetic Play Activity song names and synthetic
Daily Tracks "Track Description" strings and returns only counts, not the
strings. A Daily Tracks description resembling `Artist - Song` is considered
*provisional* only if it has an unambiguous suffix corresponding to an exact
normalized Play Activity song title. Cases with inconsistent artist prefixes,
alternative hyphen splits or no matching description abstain.

**Limits:** No actual Daily Tracks export, artist name, label, date or library
record has been opened, joined or inspected by this implementation. No
album/recording identity is proven. Daily Tracks date-bucket matching,
session dedup, artist aliases, title collisions, track remasters,
user-initiated status, cross-source Sonos dedup and ownership remain future
bounded work. A simple `Artist - Song` delimiter is not canonical and can
misparse hyphenated artists/titles; always call results provisional.

Existing `backend/services/music_taste.py` is the canonical taste evidence
layer; `music_learning_provenance.py` governs owned Sonos passive learning.
No second taste database is authorized. Historical iPhone travel plays
must never infer home presence or auto-play Sonos.

## Next bounded implementation packet

1. Build a local-only, strict allowlist and resource-limited schema inspector
   for the operator-selected `Apple Music - Play History Daily Tracks.csv`.
   Do not use generic directory/archive traversal or reveal row-level content.
2. Verify actual daily schema and artist description grammar with a limited
   **aggregate-only** operator result; accept version variations and abstain
   on unsupported schema. Avoid new host script-policy changes.
3. Extend the synthetic matcher to compare Play Activity + Daily Tracks with
   date/source provenance. Count ambiguous/unknown/provisional coverage,
   dedup and confidence, never export names or individual plays.
4. Only then design a separate opt-in dry-run taste preview using canonical
   artist+track+source provenance; no persistent DB mutation until separate
   retention, rollback, consent and deployment approvals.

### Verification and boundaries

As of this checkpoint, 45 targeted **synthetic** tests passed across the
original inspector and the new pure identity matcher; Ruff passed.
No commit, push, PR, merge, deployment, host filesystem command, Apple export
transfer, DB write, MusicKit sync, or device action was performed. The earlier
Codex review was blocked by authentication (401) and was **not approved**.


## Implemented local cross-export audit (Oct 31 continuation)

- New standalone `backend/services/apple_music_daily_join_audit.py` accepts
  the separately operator-selected Daily Tracks CSV and optional Play Activity CSV.
  It reads known allowlisted fields only for analysis and emits fixed-schema
  aggregate-only statistics, not titles/artists/identifiers or raw dates.
- Date support uses UTC-normalized playback-end dates; same day and adjacent
  day remain **provisional** and do not establish a recording or unique play.
- Any ambiguous Daily Tracks title delimiters, competing artist labels or
  unsupported field/date formats abstain. No canonical artist identity is
  inferred from title alone. Missing required headers fail closed.
- Script SHA-256:
  `77079D06331E417F5BC10E3C7951A201FB0CFC7FFB201F40B4ACA1D0B60E9CE0`.
- Combined targeted suite now **58 synthetic tests passing** and Ruff green.
  A synthetic scale trial with 50,000 Daily Tracks rows and 69,918 Play
  Activity rows completed in about 2.03 seconds; no user data involved.
- Operator command and privacy contract:
  `docs/APPLE_MUSIC_DAILY_JOIN_OPERATOR_431.md`. It uses inline PowerShell
  with a file picker, so Windows PowerShell script execution policy is unchanged.
- **Superseded status, Oct 31:** the operator ran the hash-pinned local
  matching audit successfully on their real PC and shared *only aggregate*
  output. Daily Tracks: 35,823 rows; Play Activity: 46,429 PLAY_END events.
  Same-date provisional match: 35,868; adjacent-date: 346; ambiguous
  artist: 4,594; title-only/distant date: 3,590; unmatched/undated: 1,948;
  missing title: 83. The provisional same/adjacent total is 36,214 (78.0%),
  **not** 36,214 verified recordings, sessions or preferences. No raw Apple
  file or row values were transferred and no HomeHub taste import occurred.


## Synthetic-only shadow taste-preview contract (Oct 31, #431)

**Implementation:** `backend/services/apple_music_taste_preview.py` exposes
`ApplePreviewEvent` and `preview_apple_taste`. This pure, in-memory code
has no CLI, no file access and no database/production/Apple/Sonos integration.
It does not import, rank, persist or actuate anything. Its only output is
fixed-schema aggregate counts for hypothetical evidence; never artist,
track, recording key, session key, event ID or individual timestamp.

**Distinct evidence/provenance gates:**

1. A separately corroborated canonical **recording** key, with an honest
   exact catalog or exact library mapping proof. Apple Play Activity Provider
   ID, song title alone, and even matched Daily Tracks `Artist - Song` plus
   calendar date **do not** establish such proof.
2. Independently corroborated **playback-session** identity (not the raw Apple
   Event ID, not a date/title coincidence). Input dedupes exact replays and
   multiple Event IDs sharing the same proven session; contradictory event
   IDs, reasons or recording keys revoke the whole affected session.
3. Verified **cross-source non-overlap**, especially vs Sonos. Missing or
   possible overlaps abstain; absence of a match is NOT proof of non-overlap.
4. Valid PLAY_END event/timestamp and bounded played/media durations.
   Natural finish >=80% is only a provisional completion signal; skip before
   30% only a provisional early-skip signal; known neutral/late-skip events
   with >=60 seconds are only a provisional familiarity signal. Unknown,
   scrub and failed-load reasons abstain. **Familiarity != liking**.
5. Even a passing candidate is just a **preview classification**, not a
   positive/negative taste weight or a HomeHub `MusicTasteSnapshot` input.
   No context, mode, weather, home-presence or auto-play may be inferred from
   historical iPhone activity. Cap input count and string keys.

At present **no current real Apple row can meet all these independent proofs**
from the observed exports and their aggregate reports. All synthetic examples
with these proofs are deliberately invented to test the policy; none represent
actual user song or artist preferences.

**Integration/consent gates:** before any real identity-matched ingest,
separately validate source grammar, track/artist catalog identity,
device/session dedup, Apple/Sonos overlap, portability from historical
export to fresh ongoing data, retention/purge, user opt-in, rollback,
review/CI, and an explicit persistence authorization. Then route eligible
evidence through canonical `backend/services/music_taste.py`/provenance,
not a parallel store, and preserve ownership and playback boundaries.

The Codex reviewer originally failed authorization (401) before analysis;
do not claim independent review. No commit/push/PR/merge or deployment has
been authorized by the operator-local inspection.


## Independent catalog and Sonos overlap proof-gap evaluator (Oct 31)

**Implementation:** `backend/services/apple_music_proof_reconciliation.py`;
tests: `tests/test_apple_music_proof_reconciliation.py`. This is an isolated,
pure-Python, **synthetic-only**, read-only evaluator. It neither reads
real Apple exports nor imports Sonos history. It returns only fixed status
labels and aggregate counts; it is **not** wired to HomeHub's taste provider,
database, API, MusicBandit, playback or house state.

### Catalog identity evidence

`HistoricalTrack` requires a case-sensitive independently obtained catalog
identifier and provenance `independent_catalog_lookup`. A matching
`CatalogRecord` from an independently verified source must agree on
normalized song title, artist, album and tightly bounded media duration.
Missing/unknown IDs, Provider IDs masquerading as catalog IDs, conflicting
authoritative responses, version/album/artist mismatches and unknown sources
abstain. Even a matching reference is labeled
`corroborated_catalog_candidate_only`, NOT proof that this recording was
played. Source-provenance strings are assertions from future trusted adapters,
not currently verified or issued by this module. All real Apple samples
examined so far lack verified exact catalog IDs.

### Sonos cross-source overlap evidence

The existing `SonosPlaybackEvent` model contains timestamped events and
favorite/playlist titles, often without stable ownership/session IDs; it
**does not record a complete timeline of catalog-track playback intervals**
or prove exhaustive observation. A point action near the Apple interval
is `possible_overlap_from_sonos_action`; no nearby point events means
`unknown_action_log_cannot_prove_nonoverlap`, NOT "absent".

`assess_sonos_overlap` also models *hypothetical* independently verified
Sonos playback intervals with two-minute clock-skew padding. Any intersecting
interval is possible overlap. Only a trusted, continuous **complete telemetry
coverage receipt** spanning the entire padded Apple playback window, with
no overlap, can yield `no_overlap_with_complete_telemetry`. Such receipts
are **not issued by current SonosPlaybackEvent action logs** or produced
by this patch. Coverage gaps, unknown timestamps and incomplete collectors
must abstain. A future evidence collector must independently establish
completeness, not merely set a source label or boolean.

The result is proof-gap reporting, not a session reconciliation integration.
Inputs are caller-supplied synthetic values; this code cannot authenticate
caller assertions. There is currently no legitimate path to feed these
synthetic results into `ApplePreviewEvent` as a live trusted proof.

### Engineering status and next gate

This pure evaluator plus its synthetic tests are preserved in the original
isolated #431 worktree, alongside the earlier inspector, join-audit, and taste
preview. The complete targeted #431 suite now has **151 passing synthetic
tests**; Ruff and Python compilation passed. The new evaluator SHA-256 is
`731F92086966CCA91CB33847620C7A7B2381A7BD04D5C2AA688C4D813339054B`.

**Next useful work**, pending source/provider capability decisions: identify
an actual authoritative Apple recording-ID source and a safe way to correlate
that identity with historical Play Activity/Daily Tracks; examine whether
Sonos can supply *complete* recording playback windows without changing
its existing shared-audio ownership or playback control. If not, choose a
source-scoped, capped artist-familiarity-only preview as a **new product
decision**, without claiming exact tracks or ratings. No production writes,
automatic playback, external Apple sync or presence inference.

Private Apple exports stay on the operator PC. Commit/push, PR, merge,
new collection/device changes, persistent import, review/CI and deploy remain
separate authorization gates. The earlier Codex reviewer failed 401
authentication and was not accepted as an independent review.


## Artist-label/day familiarity shadow feasibility (Oct 31, #431)

**Implementation:** `backend/services/apple_music_artist_familiarity_preview.py`
plus synthetic tests. It is a pure in-memory, **synthetic-input-only**
policy preview of Apple Daily Tracks' `Track Description`,
`Date Played`, `Play Count` and `Play Duration Milliseconds`.
No private CSV, Sonos history, database, HomeHub runtime, network or live
recommendation is accessed; no file reader/CLI is wired up in this slice.

### Precisely what the preview can and cannot infer

- Parse an `Artist - Song` description only when exactly **one** delimiter
  appears; reject absent/multiple delimiters and empty/oversized labels.
  Unicode NFKC+casefold+whitespace normalization is label deduplication,
  **not authoritative artist identity or artist-alias equivalence**.
- For any *same Daily Tracks calendar date + normalized song-title label*
  attributed to multiple artist labels, **exclude every row in that ambiguous
  title/day group**. Conflicting daily aggregate metrics for a particular
  artist/title/day also exclude that whole title/day group. Source type,
  date type/range, play count, and duration must be valid and bounded.
- A candidate artist-label/day is counted **once per distinct artist label
  and Daily Tracks date**, even with multiple songs, large `Play Count`,
  repeated rows or re-imports. The result is **not** the number of sessions,
  tracks listened to, completion events, or song ratings. Since the actual
  export aggregates play counts, it cannot prove unique listening sessions.
- Keep candidate labels and dates in temporary Python process memory only;
  the returned result has *anonymous aggregate counts* and an artist-label
  frequency histogram `1_day`, `2_to_3_days`, `4_to_9_days`,
  `10_plus_days`. Never expose title, artist, date, keys, hashes or
  per-artist values. Input cap 250k rows. Report is *not a MusicTasteSnapshot*.
- This lane deliberately **does not cross-dedupe with Sonos** or use the
  36,214 provisional Play Activity matching events as 36,214 artist-days.
  Because complete Sonos telemetry and exact recording identity are absent,
  a future artist-level *source-scoped* preview must remain isolated and
  explicitly labeled Apple Daily Tracks provenance. It must not claim
  independent Apple/Sonos plays.
- **Familiarity is not liking.** There is no positive/negative weight,
  "favorite", automatic recommendation effect, home presence or playback
  signal. Even high day-count buckets do not prove an individual artist
  catalog identity; aliases/collaborations/remasters remain unresolved.

### Integration / product decision gate

This is a safe **feasibility policy**, not an accepted real-user import,
provider sync, shadow ranking feature, or consent to persist Apple history.
Before operating on the real private CSV, separately review the scoped
local-only reader, confirm expected Daily Tracks grammar and safe aggregate
privacy, and obtain operator opt-in to run it locally. Before any HomeHub
artist familiarity use, decide how Apple label-only provenance may be
associated with catalog artists, how to avoid Apple/Sonos double counting,
whether source-scoped uncertain familiarity is acceptable, and define
retention, withdrawal/rollback, consent, independent code review, CI and
integration authorizations.

All code remains uncommitted in isolated `feat/apple-history-inspector-431`.
No new real-host command, source export upload, live import, API route,
Sonos action or persistent DB write was performed.


### PR preparation / independent review packet

The new artist-label/day preview is a second, **separate** evidence lane
from exact recording/session taste preview. The former can describe only
Apple Daily Tracks label-day frequency; the latter requires independent
recording+session+cross-source proof and cannot be fed raw title/date joins.
Neither is eligible to alter current `MusicTasteSnapshot`, MusicBandit or
HomeHub playback.

A focused independent review should confirm:

1. No future adaptor can use provisional daily artist labels as verified
   canonical catalog identities, unique playback sessions, Sonos-negative
   non-overlap receipts, or positive/negative preference.
2. Strict parser grammar, album/alias/collaboration ambiguity, repeated
   imports and conflicting title/day artists abstain or cap correctly;
   time-zone differences are not silently treated as equivalent timestamps.
3. Bounded input size and strings, no source row/key/name/date in aggregate
   JSON/errors; no account/location/device private field parsing, logging,
   filesystem writes, networking or runtime model references.
4. `artist_label_day_histogram` counts candidate **labels**, not people,
   sessions or verified distinct artists; counts are not exported to a
   permanent database. No output of individual artist rankings.
5. Existing inspector, probe, cross-export join audit, provenance evaluator,
   taste preview and all synthetic tests remain compatible.
6. If a later operator-local CSV reader is built, it must reuse bounded,
   allowlisted extraction and undergo new privacy review and explicit
   local-run consent before any real-history inspection.

Current #431 source files are all uncommitted and untracked in the isolated
worktree. Do not stage unrelated files. Commit, push, PR creation, merge,
deployment, private-data processing, persistent taste writes and new Sonos
telemetry are **separate gates**. The earlier independent Codex review failed
authentication (401); synthetic test success does not substitute for review.


## Prepared private Daily Tracks local reader (Oct 31, #431)

**Status: prepared in Sandbox and synthetic-tested, NOT yet run against the
user's private Daily Tracks CSV.** This extends the previous pure in-memory
artist-label/day shadow feasibility preview with a bounded standalone
one-file CSV adapter, without adding any HomeHub runtime or database path.

- Source: `backend/services/apple_music_artist_local_audit.py`
  SHA-256 `0B7243A692BEF654A037318B6830D3365F5113A84E3D7808A4D9861DDB3AD562`.
- Adaptor reuses `apple_music_daily_join_audit._csv_rows` for a strict
  100 MiB, 250,000-row, max 256-column, 8,192-char/field file read.
  It decodes UTF-8 BOM/CSV strictly, checks missing or duplicated headers,
  row width and file-change metadata. It reads *one explicitly selected
  regular CSV only*: no folder crawl, ZIP extraction, account access or
  automatic Apple syncing.
- Only `Track Description`, `Date Played`, `Play Count` and
  `Play Duration Milliseconds` are passed to the artist-label/day
  calculation. Python CSV parsing transiently creates a bounded full row
  (including excluded columns), but other columns are never extracted
  into application state, logged or returned. Album, artist, title and
  date labels reside temporarily in memory and are not returned.
- `apple_music_artist_familiarity_preview` rejects ambiguous description
  shapes, conflicting title/day artists and inconsistent aggregate
  metrics; it collapses repeat rows, multiple songs and `Play Count`
  into at most one *candidate artist-label/day*, returning only anonymous
  histogram/counts. It makes **no** verified-artist identity, session,
  preference, Sonos nonoverlap, or playback inference.
- One operator-local PowerShell block with three exact SHA-256 script pins,
  a single extracted CSV picker, and `python -B` invocation is documented
  in `docs/APPLE_MUSIC_ARTIST_LOCAL_OPERATOR_431.md`.
  The block was parsed as valid PowerShell; checksums were verified
  against exact files. Do not execute against real data without separate
  explicit operator opt-in. No new Python installation, script-policy
  change or host-admin action is part of this packet.
- Verification: 29 new synthetic local-reader tests, **213 total targeted
  #431 synthetic tests passing**; Ruff and Python compileall green,
  `git diff --check` clean. Tests cover CLI success, fixed sanitized
  errors, invalid/malformed CSV, private extra-column non-leakage,
  ambiguous artist labels, numeric failure, unextracted ZIP refusal,
  in-memory-only outcomes and no application-created files.
- Existing isolated branch `feat/apple-history-inspector-431` remains
  uncommitted at base `9670b3fcbeee5c51f50c29f610c1f150f81ba7db`
  with **21 scoped untracked files**; no source CSV, real-host file,
  DB record, device or playback action was accessed or changed. Previous
  independent Codex review failed authentication (401); do not equate
  deterministic tests with independent review.

**Next authorization gates:** independent review of reader safety and
metadata semantics, then a separately consented user-initiated local
run returning anonymous JSON. A *different* opt-in/product gate would
be required to store or apply Apple artist familiarity in HomeHub:
source-scoped label/canonical identity rules, Apple/Sonos dedup,
consent/retention/revocation/rollback, CI, PR/merge and deployment.


## Oct 31 — bounded local-reader privacy and source-semantics self-review

This was **internal adversarial self-review, NOT independent Codex review**.
The earlier Codex 401 authentication failure is unresolved; no duplicate worker
was started. Reviewed the local CLI, the in-memory artist-label/day algorithm,
shared bounded CSV parser, operator runbook and synthetic tests.

Two bounded fail-closed issues were identified and fixed WITHOUT changing the
previously pinned cross-export join auditor or HomeHub runtime:

1. Local reuse of the shared date-prefix parser allowed extra trailing text.
   New local-only _strict_day requires exact ASCII YYYY-MM-DD and a valid
   calendar date. The fixed anonymous source_quality counter reports rows
   with invalid/nonexact labels, allowing a future operator to recognize
   a source-format mismatch rather than silently accepting a date prefix.
   Earlier real export data proved 35,823 parseable date PREFIXES, not
   35,823 exact 10-character date strings. Abstain until source format
   is confirmed; do not weaken grammar based on assumptions.
2. The standalone CLI formerly accepted other path extensions as long as
   the contents resembled CSV. It now refuses non-.csv suffixes. This is
   a basic selection guard, not cryptographic file authenticity.

Added regression cases for suffixed timestamps, malformed calendar dates,
Unicode digits, uppercase .CSV, non-.csv with valid CSV contents, sanitized
exceptions and aggregate-only invalid-date counts.

New local reader SHA-256:
44F4E4368E1093A60933907F306B31E64C0AC56525FC678795DA923E58F25084
The runbook pins were updated, exact hashes reverified, and the command
block successfully parsed as PowerShell. Pure artist/day preview and shared
CSV parser pins are unchanged.

Full #431 targeted synthetic suite: **227 passed**; Ruff all checks green,
compilation green, tracked Git diff --check clean. Existing isolated branch
feat/apple-history-inspector-431 remains at
9670b3fcbeee5c51f50c29f610c1f150f81ba7db with 21 issue-scoped
untracked files. No commit, push, PR, merge, private CSV/host access,
HomeHub database, music, device, restart or deployment action occurred.

Residual caveats: CSV library transiently materializes bounded full input
rows including excluded fields (never extracted/logged/returned); in-memory
artist labels are not authoritative catalog IDs. Aggregate histograms are
NOT a formal anonymization guarantee, so even the fixed output should be
treated as private. The full real Daily Tracks date grammar is unverified;
all rows may legitimately abstain under strict validation. No Sonos
non-overlap, session dedup, independent Code/Codex sign-off, or consent to
persist artist familiarity has been established.

Next gate: optional user-initiated real-PC pinned operator audit yielding
aggregate-only JSON; no raw export transfer. Before live Music Intelligence
usage, require independent review, product decisions on label/cross-source
confidence, retention/withdrawal, authorization and integration/CI/deploy.


## Operator-local Daily Tracks format mismatch and reversible fix (Oct 31)

**Verified operator aggregate, no private source transfer:** the user reran
the hash-pinned local artist-label/day audit on their existing extracted Daily
Tracks CSV. It read 35,823 rows, reported **35,823**
`rows_with_invalid_or_nonexact_day`, therefore abstained on all rows:
0 candidate artist-label/days, 0 provisional artist labels, and empty
histogram. This is a **format-validation failure**, not evidence that the
user lacks artist familiarity. The earlier cross-export audit had seen
35,823 parseable date *prefixes*. The exact original date suffix/content
was not shared with HomeHub or recorded in GitHub.

**Bounded reversible revision:** local-only
`backend/services/apple_music_artist_local_audit.py` now accepts both
fully validated ASCII `YYYY-MM-DD` and complete common ISO datetime
labels with seconds and optional fractional seconds and time-zone suffix.
It requires full regex matching AND datetime validity; arbitrary text
following a valid date never passes. For daily aggregation it preserves the
source's date label and **does not convert timezone or infer a session**.
Unsupported full shapes and malformed values still abstain.

The revised anonymous source-quality output now includes
`rows_with_invalid_or_unsupported_day` and a fixed
`date_label_shapes` histogram: `date_only`, `iso_timestamp_utc`,
`iso_timestamp_offset`, `iso_timestamp_no_zone`, `unsupported`.
The values are aggregate counts, **not** observed time/date strings.
This both supports common fully specified formats and ensures that any
remaining unsupported real-world shape can be diagnosed from anonymous
counts rather than requiring disclosure of raw dates or another format
guess. This remains a **source-scoped feasibility audit only**.

New reader SHA-256:
`0C901C095DB466C065B9C5B766A59E7891613946D9F21DEF3870FCD8657E53B0`.
The pinned operator runbook
`docs/APPLE_MUSIC_ARTIST_LOCAL_OPERATOR_431.md` was updated and its
PowerShell block parsed; other two original hashes are unchanged.
Expanded synthetic tests include full ISO UTC/offset/naive forms, fractional
seconds, bad dates/timezones, embedded private suffixes and correct
calendar-label behavior without UTC day shifting.

**Verification:** 242 targeted synthetic #431 tests passed; Ruff,
compileall, PowerShell runbook syntax and three exact hash pins green.
Isolated branch `feat/apple-history-inspector-431` remains at
`9670b3fcbeee5c51f50c29f610c1f150f81ba7db`; all 21 scoped
files remain untracked, no commit/push/PR/merge/deploy or HomeHub
mutation. The updated version **has not yet been run against the
operator's private export**, and whether it accepts all real dates is
still unknown. Independent Codex review remains uncompleted (prior 401).

**Next gate:** optional single user-initiated rerun of the new pinned
local-only script against their *already extracted* CSV, sharing only
fixed aggregate JSON. Do not infer artist liking or enable/persist
HomeHub recommendations regardless of histogram; those are separate
source-identity, dedup, privacy, consent and integration gates.


## Second operator-local date failure / masked-grammar diagnostics (Oct 31)

**Verified operator aggregate:** the user hash-pinned and ran the revised
ISO-supporting artist/local reader on the same private extracted Daily Tracks
CSV, returning 35,823 input rows and **35,823 unsupported date labels**.
All fixed source date buckets were zero except `unsupported=35,823`;
therefore 35,823 observations abstained and the artist/day histogram
remained empty. **This is still not evidence of zero artist familiarity.**
The prior cross-export audit counted 35,823 date *prefixes* as valid,
but the full private suffix remains unknown. No source date or artist data
was transferred. Further guessed parsers are not justified.

**Prepared next bounded offline diagnostic:** the local reader now adds
`source_quality.common_unsupported_masked_shapes` for at most **5**
frequently repeated unknown date-format shapes (minimum **20** matching
rows per shape). Each input digit becomes `9`, letter becomes `A`,
whitespace becomes `_`, allowlisted structural punctuation survives,
and every other character becomes `?`. Only source strings with a
validated ASCII date prefix and length 11..64 are mask candidates;
unsupported/rare/long/unmatched patterns are aggregated into
`rare_or_unclassified_unsupported_rows`, not printed individually.
No source date values, actual words, artist labels, track names, IDs,
rows, or paths appear in the output. Counts are still private aggregate
evidence, not a formal anonymity guarantee. The diagnostic DOES NOT
accept any previously rejected date value or generate taste evidence.

Revised local reader SHA-256:
`A0D60B686CB0062F8949999999A432B5990C162F9702304CBBB1EA7125DF7952`.
`docs/APPLE_MUSIC_ARTIST_LOCAL_OPERATOR_431.md` now uses this checksum.
Other two script pins remain unchanged. Added five synthetic tests for
repeated masks, minimum frequency, five-pattern cap, invalid prefix
suppression and masking raw private letters/digits. Combined **247**
targeted #431 synthetic tests passed, Ruff/compileall green, three
operator checksum pins green and operator PowerShell block parsed.
Current isolated branch `feat/apple-history-inspector-431` remains
at `9670b3fcbeee5c51f50c29f610c1f150f81ba7db` with 21 scoped
untracked files; no commit, push, PR, merge, production write,
private source access, device action or deploy.

**Next step**: optional user-initiated local rerun against existing
private Daily Tracks CSV; share only masked aggregate `source_quality`
for source-format diagnosis, or the entire fixed aggregate JSON if desired.
Then implement the *observed* full-format parser with deterministic
synthetic tests; do not guess again or interpret a blank histogram
as no artist familiarity. Real importing or taste weighting still
requires independent review, explicit user opt-in, provenance,
Sonos dedup, retention and integration/deployment gates.


## Third local diagnostic produced no masks; prefix blind spot corrected (Oct 31)

**New operator evidence:** User executed hash-pinned masked date-shape audit
against the private extracted Daily Tracks export again and shared ONLY
source_quality aggregate JSON. Across 35,823 input rows, every date label
was `unsupported`, `common_unsupported_masked_shapes=[]`, and
`rare_or_unclassified_unsupported_rows=35,823`. This does **not**
demonstrate heterogeneous data: the diagnostic incorrectly required the
very ISO `YYYY-MM-DD` date prefix it was intended to diagnose, and also
excluded strings shorter than 11 or longer than 64 characters.
No underlying date value, artist/title or file was transferred.

**Correction in Sandbox (no private-source access):** The masked-pattern
generator now accepts ANY unsupported nonempty source string of length
1..64, with no date-prefix assumption; all source ASCII letters/digits
are replaced by `A`/`9`, whitespace by `_`, unexpected symbols by
`?`, and only simple structural punctuation remains. Only shapes
occurring >=20 times are reported, up to five groups; all other cases
are counted without displaying individual patterns. New fixed
`unsupported_length_buckets` classify *all* unsupported source fields
as empty, 1-10, 11-32, 33-64, or 65+ characters. Still no actual source
strings, dates, artists, row samples, identifiers, or per-artist counts.
Treat aggregate patterns as private nonetheless.

The previous cross-export date-prefix reader's Python
`date.fromisoformat` also accepts complete ISO basic calendar dates
(`YYYYMMDD`) and ISO week dates (`YYYY-Www-D`, `YYYYWwwD`), none of
which fit the first strict artist/day formats. The new local reader
recognizes these ONLY when the *entire* string matches a corresponding
well-formed shape and `date.fromisoformat` validates it; otherwise
abstains. It is still unknown which actual format the user has.

Updated SHA-256 for `backend/services/apple_music_artist_local_audit.py`:
`DDE9CF79CE9495E55D7E3900E47BCE293D5B3BAE6CA7994BCE19DC05F78BA900`.
`docs/APPLE_MUSIC_ARTIST_LOCAL_OPERATOR_431.md` updated with hash and
privacy caveats. **257 targeted synthetic #431 tests passed**; Ruff,
compileall, exact 3-script hash pins and PowerShell parsing passed.
Isolated worktree unchanged HEAD
`9670b3fcbeee5c51f50c29f610c1f150f81ba7db` on
`feat/apple-history-inspector-431`, 21 issue-scoped untracked files.
No commit/push/PR/merge, source CSV transfer, live database/recommendation
write, host administration, Sonos action or deployment. Independent
Codex review remains outstanding (earlier authentication failure).

**Next:** One optional user-initiated local run using current pinned reader,
sharing only `source_quality`; review recognized format counts or common
fully-masked patterns/length buckets before *any* additional parser
changes. If a date grammar is accepted, the anonymized artist/day
histogram is only a source-scoped familiarity feasibility signal, not
a preference weight or deduplicated Apple/Sonos session count.


## Fourth operator-local run: exact compact calendar date grammar VERIFIED (Oct 31)

**Confirmed on the operator's real extracted Daily Tracks CSV (aggregate-only
output):** all **35,823** `Date Played` fields were classified as the fully
validated `compact_calendar_date` format, exact ASCII `YYYYMMDD`.
`source_quality.date_label_shapes.compact_calendar_date=35823`;
all seven other date-shape buckets (including `unsupported`) were zero;
`rows_with_invalid_or_unsupported_day=0`;
`rare_or_unclassified_unsupported_rows=0`;
all `unsupported_length_buckets=0` and
`common_unsupported_masked_shapes=[]`.

This proves the **date grammar compatibility** of the current hash-pinned
operator-local reader; it supersedes the earlier three failed strict/ISO
runs and their misleading all-zero candidate histograms. The user printed
**only `source_quality`**, so the fourth run's artist-label/day histogram
and candidate counts are **NOT YET OBSERVED**. Do not claim any real artist
count, familiarity distribution, catalog identity, favorite or
Apple/Sonos-independent session. The full CSV, raw dates, artist/song
names, paths and individual records were not transferred.

**No source-reader code change needed:** SHA-256 for
`apple_music_artist_local_audit.py` remains
`DDE9CF79CE9495E55D7E3900E47BCE293D5B3BAE6CA7994BCE19DC05F78BA900`.
Current 257-test synthetic green status is the existing verification,
not new CI or independent Codex review. All 21 task-scoped worktree files
remain uncommitted/unpublished. No real HomeHub learning or persistence.

**Next optional step:** user-controlled local rerun of this unchanged
pinned reader with the same already-extracted Daily Tracks CSV, outputting
only `artist_label_day_histogram` and selected fixed aggregate
`counts`. No more source-date diagnostics or parser guesses are needed.
After inspecting those aggregates, evaluate whether the conservative
artist-label/day signal is useful enough for a scoped product decision;
do NOT import or attach per-artist metadata without independent privacy,
provenance, source-identity/retention, integration, and authorization gates.


## Fifth local operator run: artist-label/day histogram real-data feasibility (Oct 31)

**Source:** Operator-initiated, hash-pinned reader of their own already-
extracted Apple Music Daily Tracks CSV. The operator shared only the
anonymous fixed-schema aggregate counts/histogram in chat. No CSV,
artist/song name, source dates, identifiers, paths, private values or
per-artist counts were transferred. Reader hash remains
`DDE9CF79CE9495E55D7E3900E47BCE293D5B3BAE6CA7994BCE19DC05F78BA900`.

**Measured counts:**
- `input_daily_rows=35823`
- `parsed_description_rows=29014`
- `abstain_invalid_or_ambiguous_description_or_metrics=6809`
- `ambiguous_title_day_groups=18`
- `conflicting_aggregate_title_day_groups=135`
- `abstain_ambiguous_or_conflicting_rows=307`
- `unambiguous_title_day_labels=28653`
- `collapsed_repeated_or_multiple_song_rows=9268`
- `candidate_artist_label_days=19439`
- `distinct_provisional_artist_labels=2569`
- Histogram by days per provisional label:
  `1_day=1306`, `2_to_3_days=577`,
  `4_to_9_days=344`, `10_plus_days=342`.

**Cross-checks:** Parsed + initial abstentions =
29,014 + 6,809 = **35,823** source rows. Parsed rows -
307 conflicts - 9,268 repeated/multi-song collapsed =
**19,439** candidate artist-label/day presences. Histogram =
1,306 + 577 + 344 + 342 = **2,569** label groups.
**1,263** labels appear on more than one export calendar date
(577 + 344 + 342). Counts do not disclose which labels or days.
The earlier all-unsupported-date audits are superseded; the prior
fourth-run `source_quality` found all 35,823 fields valid as compact
calendar `YYYYMMDD`.

**Conclusion:** Proven feasibility of *aggregate, Apple-source-scoped
artist-label/day frequency*. This is a meaningful distinction between
single-day and repeated label exposure. It is NOT a verified artist
catalog identity, number of playback sessions, proof of liked/favorite
artists, cross-source independent evidence, or fit-to-deploy Music
Intelligence input. Nearly 19% of source rows (6,809) still abstain for
mixed invalid/ambiguous description or metrics reasons; these reasons
cannot be separated from the present aggregate output. Likewise the
307 additional rows excluded for conflicting group evidence are not
a song-specific user disapproval signal. No artist label should receive
a personal affinity weight on this evidence alone.

**Next engineering packet (no new private export scan required):**
1. Confirm pure artist-label/day calculations are reproducible and bounded
   under synthetic multi-day collision, aliases, collaborations, duplicates,
   conflicting metrics and Unicode normalization; preserve fail-closed.
2. Independently review privacy/reporting/provenance assumptions, including
   whether any future verified catalog-artist linkage can be made without
   accidentally exposing identities or double-counting Apple/Sonos.
3. Produce a *shadow-only product decision brief* that separates
   source-scoped exposure/familiarity from confirmed liking and states
   coverage/safety caveats. Decide scope/consent/retention/deletion/
   rollback before any actual HomeHub persistence or recommendations.
4. Commit, push, PR/CI, merge and deployment remain separate gates.

The isolated Sandbox worktree remains uncommitted/unpublished, and nothing
was imported into HomeHub, its Sonos source or canonical taste model.


## Shadow-only artist exposure design review / acceptance matrix (Oct 31)

**Product-design packet prepared, NOT approved to integrate**:
`docs/APPLE_MUSIC_SHADOW_EXPOSURE_DECISION_431.md`. This is a
proposed decision for a local Apple-only **anonymous artist-label/day
exposure** lane, not a new artist taste import, recurring shadow service,
production table, recommendation feature or provider sync.

Current authoritative `backend/services/music_taste.py` treats
`MusicArtist(source="import")` library play counts as positive preference
and familiarity 1.0. Feeding Apple export day-label counts into that
path would **incorrectly make exposure = endorsement**. The proposed
contract explicitly prohibits constructing MusicArtist import rows,
canonical `build_music_taste_snapshot` weights, MusicBandit rewards,
candidate trust/proven graduation, recommendations, context/presence,
or Sonos playback from Apple label-only evidence.

Existing user-private aggregate results remain:
35,823 Daily Tracks rows; 29,014 initially parsed rows; 6,809
invalid/ambiguous initial abstentions; 307 further conflicting rows;
19,439 distinct artist-label/day presences; 2,569 provisional labels;
bucket counts 1,306 single-day, 577 two-to-three, 344 four-to-nine
and 342 ten-plus day labels. These are not named catalog artists or
independent playback sessions. No new private data run occurred.

New synthetic boundary tests added in
`tests/test_apple_music_artist_familiarity_preview.py` for
near-spelling alias non-merging, different-day conflict isolation,
reimport/duplicate artist-day idempotence, and Sonos source rejection.
The combined 8 Apple test modules plus canonical
`tests/test_music_taste.py` passed **277 tests**, Ruff green,
compileall green. The live backend codebase had no references to the
local audit CLI outside its own file when inspected. No runtime/schema,
DB, frontend, Sonos, provider or deployment changes were made.

Review status: internal source/code/design review and deterministic
tests performed. **Independent review remains OUTSTANDING** because
the earlier Sandbox Codex Read task failed authentication (401). Do
not misstate this as independent code/privacy sign-off.

Next gates: independently review #431 scoped files and this design;
explicit product decision whether to permit a future per-artist *local*
shadow view and how to opt in, identity/collision handling, raw/derived
data retention and withdrawal, cross-source Sonos overlap and reversible
rollout. No commit, push, PR, merge or deployment authorized.


## #431 independent-review attempt and synthetic noninterference checkpoint (Oct 31)

A **new** read-only Sandbox Codex reviewer was launched after task-registry
inspection: task `0683b5bca4444160b99266ad7b801595`. It exited
`failed` with worker dead and code 1; no report was returned. Current
failure cause was not proven (worker stdout/stderr were empty), although
an earlier separate review attempt had reported auth 401. Thus there is
**NO independent review sign-off**. No Codex Write worker, environment,
credential, commit, push or deployment was authorized or performed.

Directly added nine deterministic, synthetic-only acceptance tests in
`tests/test_apple_music_shadow_exposure_boundary.py` verifying the
isolated local reader's import graph, absence of Apple evidence in the
canonical taste builder, no trust/promotion from a shadow histogram,
order/duplicate/ambiguous-title evidence safety, one explicit local
synthetic input file, no network or output files, no private source text
in results and play-count independence. The tests do not use personal
records or prove future integrations safe.

**Local validation:** 286 passed across eight #431 suites, canonical
`test_music_taste.py`, and the new noninterference suite; Ruff,
compileall and tracked Git diff --check passed. The checksum-pinned
private-reader source was **not changed** and no user export rerun
is necessary. Worktree `feat/apple-history-inspector-431`, unchanged
HEAD `9670b3fcbeee5c51f50c29f610c1f150f81ba7db`, now 23
issue-scoped untracked files; all unrelated work preserved. Separate
design and decision evidence in
`docs/APPLE_MUSIC_SHADOW_EXPOSURE_DECISION_431.md`.

**Remaining gate:** independent privacy/provenance review of code and
data handling, followed by a separate explicit product decision on
opt-in per-artist identity, Apple/Sonos nonoverlap, retention/withdrawal,
rollback, and the normal commit/PR/CI/merge/deploy authorizations. No
Apple label/day evidence should enter `MusicArtist(source='import')`,
canonical taste, MusicBandit, trust, recommendations, room presence,
or Sonos playback without those decisions.


## #431 integration readiness / reviewer blocker recheck (Oct 31)

**Status:** Integration-preparation only. No independently accepted code/privacy
review, commit, published branch, PR, merge, deployment or live/real-data
action. The isolated worktree's base remains
`9670b3fcbeee5c51f50c29f610c1f150f81ba7db`, branch
`feat/apple-history-inspector-431`.

**Review-tool evidence:** The most recent Codex read-only task
`0683b5bca4444160b99266ad7b801595` remains failed with code 1,
no usable last-message or JSONL events and zero-byte worker stdout/stderr.
It exited before an independent report; its actual failure cause is
unverified (the earlier, separate attempt had an authentication 401).
Do not keep relaunching, modify credentials or equate direct checks
with independent review. GitHub PR #432 is separate and open.

**Concrete safeguard repaired:** Existing static noninterference test
previously ignored relative imports (`from .music_taste ...`).
Changed the test to fail closed on ANY new import outside an explicit
standard-library and two offline Apple-module allowlist. Six new
negative tests prove disallowed relative imports into
`music_taste` or `database`, absolute `backend.models`,
network modules and `from . import music_taste` are caught.
No operator-facing reader code or existing reader checksum changed.

**Live Git evidence:** GitHub comparison showed `master` 19 commits
ahead of this base, with a changed-file set confined to lighting,
Quiet Atlas and Obsidian. No overlap with #431's issue-scope paths
at the time of comparison. A future integration must re-verify live
heads, #432 and possible concurrent work, and handle the 24
intentional untracked files without broad cleanup/reset/rebase.

**Final local verification:** 292 targeted synthetic tests passed,
covering eight #431 Apple suites, canonical `test_music_taste.py`
and the now-15-test `test_apple_music_shadow_exposure_boundary.py`.
Ruff/compileall and `git diff --check` green. Exact untracked
candidate is 8 backend files, 9 tests, 6 docs, 1 PowerShell script,
all under #431; no tracked edits. Operator reader SHA remains
`DDE9CF79CE9495E55D7E3900E47BCE293D5B3BAE6CA7994BCE19DC05F78BA900`.
The integration package and normal gates are now in
`docs/APPLE_MUSIC_PR_READINESS_431.md`.

**Next:** Obtain a real independent privacy/provenance review, address
findings with synthetic tests, then request the separate appropriate
Git integration authorization. Product gates for per-artist exposure
identity, user consent, retention/withdrawal, Apple/Sonos overlap and
canonical taste remain OPEN. Do not request any new private CSV scan,
and do not allow exposure counts to imply likes or affect playback.


## Published PR #439 independent-review continuation: exact-date output leak (Oct 31)

**Direct privacy finding / bounded remediation, pending publication at this
checkpoint:** The Play Activity inspector's otherwise aggregate-only report
included `utc_coverage.earliest_date` and
`utc_coverage.latest_date` derived from real source timestamps.
Although not individual playback records, those were *exact personal
calendar dates*, contradicting the claim that no source dates leave the
reader. The output field is **removed entirely**, as are the in-memory
min/max trackers; the aggregate `counts.valid_timestamps` still shows
date parsing coverage without disclosing when listening occurred.
Synthetic regression tests now reject a source-day/date-range leak for
multiple distinct timestamp dates and preserve no-source-text output.

The checksum-pinned **Play Activity** inspector (distinct from the
Daily Tracks artist/day reader) now has SHA-256
`853BBAB8C98B47AF4ACF52C87FB0BF3F569ED2DC9DEE12853F9F1DE8E6AA78D7`;
its Windows operator script and read-only runbook hash pins were
updated together. Do not use old pins for this inspector. The separate
**Daily Tracks** operator reader remains byte-for-byte unchanged at
`DDE9CF79CE9495E55D7E3900E47BCE293D5B3BAE6CA7994BCE19DC05F78BA900`.
No private Apple CSV scan was performed for this correction.

**Independent reviewer attempt:** GitHub documentation specifies
`copilot-pull-request-reviewer[bot]` as the REST review-request identity.
A bounded API request on ready-for-review PR #439 returned a successful
PR result, but GitHub still showed **no requested reviewer in normalized
metadata, no submitted reviews and no review threads** at subsequent
poll. Therefore no actual independent review or acceptance can be
claimed. Do not merge based on this request alone.

Product and integration safety gates remain open: source-scoped
provisional labels are not verified artist identities or liking;
no Apple/Sonos independent session proof; no canonical taste model,
MusicBandit, production or playback changes; no merge/deploy authority.


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


## Nov 1 second Codex review findings — next correction (conditional merge BLOCKED)

Independent Codex review of PR #439 at `c6ba1f2ccbec8f4702da58e5fc643bfe9c0e45e1`
**completed with two new P2 findings**; the first three are not
automatically accepted merely because a follow-up review occurred:
1. The schema preflight's earlier physical-newline presence test did
   not prove completion of a logical CSV header containing quoted
   newlines. A cutoff at byte 32,768 could accept a truncated final
   field and hide a malformed UTF-8 continuation beyond the sample.
   Fix: keep incremental UTF-8 decoding but, after the parser consumes
   its first logical CSV record, require that its actual final consumed
   physical line ends with CR/LF when the sample does not reach EOF.
   The parser's consumed source offset, not any earlier newline,
   determines completion. Synthetic adversarial multiline-header and
   valid multiline-header/data-boundary cases were added.
2. `docs/APPLE_MUSIC_ARTIST_LOCAL_OPERATOR_431.md` still pinned an
   obsolete hash for `apple_music_daily_join_audit.py`; the current
   shared `apple_music_csv_record_budget.py` was not included in that
   operator pin set. This prevented legitimate operator invocation.
   The operator guide now verifies both current SHA-256 values.
   The Daily Tracks schema preflight runbook pin is also updated to
   match the amended schema probe.

These corrections are local and have **not** been applied to any private
CSV. The previously run Daily Tracks artist reader remains unchanged at
SHA256 `DDE9CF79CE9495E55D7E3900E47BCE293D5B3BAE6CA7994BCE19DC05F78BA900`.
The review's five P2 findings and the separate retention/identity/
Apple-Sonos product gates must remain auditable. Prior GitHub CI and
review results were against earlier commits. Do not merge or deploy
before the new head is green and independent review outcomes are checked.
