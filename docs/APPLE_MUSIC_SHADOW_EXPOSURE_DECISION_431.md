# Apple Music artist exposure — #431 shadow-only design decision packet

**2026-10-31 · Status: recommended design / acceptance proposal, NOT approved integration.**
Owner: Sensing & Intelligence / Music Intelligence; parent [#254](https://github.com/agatte/home-hub/issues/254), work item [#431](https://github.com/agatte/home-hub/issues/431).

## Executive recommendation

**Proceed only with an Apple Daily Tracks, source-scoped, aggregate-only
*artist-label exposure* lane. Do not import artist label/day frequency into
the canonical taste model, MusicBandit, catalog identity, recommendations,
Sonos ownership, playback, house state, or presence.**

At this stage, "shadow" means a manually invoked, local-only review that
returns anonymous aggregate counts; it does NOT imply a continuously running
HomeHub shadow service, a production shadow table, per-artist ranking, or
automated personalized learning. Nothing from a mobile listening export
changes a HomeHub physical-context or autoplay fact.

A later per-artist integration is a **new product/privacy decision**, not
an implementation detail of this approval. Choose an explicit operator opt-in,
source identity, retention and withdrawal model before even presenting
artist-identified evidence to HomeHub.

## Empirical basis (operator-local only, no raw private history shared)

The user ran the checksum-pinned offline scanner against their already
extracted Daily Tracks CSV. All 35,823 'Date Played' fields were validated
as exact compact ISO calendar dates (YYYYMMDD). The following are **aggregate
facts**, not unique sessions, popularity/affinity or approved user taste:

| Observed measurement | Value | Meaning / ceiling |
| --- | ---: | --- |
| Daily Tracks source rows | 35,823 | Rows, not plays |
| Initially parsed description and metrics | 29,014 | 81.0% of rows; not verified artist identities |
| Initial malformed/ambiguous/invalid abstentions | 6,809 | 19.0% of rows, mixed causes |
| Further ambiguous/conflicting parsed rows withheld | 307 | Revokes uncertain same title/day groups |
| Candidate artist-label/day presences | 19,439 | Distinct label/calendar-day pairs after de-dup |
| Provisional normalized artist labels | 2,569 | Not canonical artists or unique artist IDs |
| One-day labels | 1,306 | Single-day observed exposure |
| Two-to-three-day labels | 577 | Repeated observed exposure |
| Four-to-nine-day labels | 344 | Recurrent observed exposure |
| Ten-plus-day labels | 342 | Frequent observed exposure (unverified label) |

Arithmetic controls: 29,014 + 6,809 = 35,823;
29,014 - 307 - 9,268 repeated/multi-song collapsed = 19,439;
1,306 + 577 + 344 + 342 = 2,569.
Thus **1,263** provisional labels appeared across 2+ Apple export dates.
The distribution is a feasibility signal, not a recommendation weight.

## Three deliberately separate concepts

| Concept | Current source proof | Permitted output | Forbidden inference |
| --- | --- | --- | --- |
| Apple Daily Tracks **label exposure** | Parsable unambiguous 'Artist - Song' label with valid Apple export date and metrics; at most one label/day | Anonymous source-scoped aggregate frequency buckets | Actual canonical artist, preference/liking, play session, physical presence |
| **Catalog artist identity** | No proof in Daily Tracks. Needs separately independently verifiable provider/library identity, collision/alias policy, and human review for uncertainty | Future reviewed per-artist *candidate* mapping only after opt-in | Equate normalized text with verified provider ID; merge aliases/collaborators automatically |
| **Preference/session evidence** | No verified Apple exact-recording+session proof or Sonos-negative overlap from these exports. Explicit HomeHub feedback and scoped Sonos playback have separate semantics | Existing canonical taste evidence remains authoritative | Positive/negative weight, proven/familiar trust graduation, autoplay or MusicBandit reward from label-days |

**Important existing-code collision:** `backend/services/music_taste.py`
currently treats `MusicArtist(source="import")` library play counts as
positive evidence, calculates familiarity 1.0, and combines explicit
feedback plus Sonos playback with preference and trust policy. Therefore
**do not synthesize `MusicArtist` rows, set `source="import"`, or feed a
new Apple count through `build_music_taste_snapshot`**. That would
silently turn source-label exposure into an endorsement and could alter
recommendation trust. The existing `classify_candidate` also does
not propagate track familiarity from a familiar artist; preserve that.

## Shadow-only boundary and contract

**Current safe lane (existing and verified):** An operator manually selects
one extracted, local Apple Daily Tracks CSV. A bounded read-only adapter
allowlists description, date, play count and duration. Pure in-memory logic
normalizes text labels, excludes ambiguous title/day and inconsistent daily
metrics, coalesces repeats and multiple songs to one label/day. It returns
only fixed aggregate counts and 1 / 2–3 / 4–9 / 10+ histogram, plus
fixed format/source-quality warnings. No identities, dates, hashed labels,
sample rows, playlists or per-artist counts leave the tool. Its output is
still personal aggregate information, NOT a proven anonymity guarantee.

**Proposed later shadow candidate (NOT currently approved):** If a future
product decision explicitly permits *per-artist* inspection, keep source
labels local/in-memory first with no permanent mapping or server transfer.
Every candidate must carry `source=apple_daily_tracks`,
`evidence_type=artist_label_day_exposure`, `identity_status=unverified`,
`preference_eligible=false`, `session_proven=false`,
`cross_source_independent=false` and `actuation_eligible=false`.
These are **design contract fields**, not an implemented schema. No model
consumer may silently reinterpret their numeric frequencies as taste
weights, artist depth, proven track familiarity or recommendation approval.
Catalog mapping needs explicit separate validation plus consent.

**Presentation:** neutral terms such as "seen across Apple export days"
and "unverified artist label"; not "favorite", "liked", "you played X
times", "top artist", "proven", "disliked" or "recommended because you like".
Unknown/excluded evidence must not be presented as absence or dislike.

## Threats, abstentions, and invariants

1. **Source and identity**: 'Artist - Song' is a delimiter hypothesis; it
   can misparse collaborations, multi-part artist names, song titles with
   dashes, alternate spellings, Unicode equivalence, live/remastered
   versions and compilation credits. NFKC/casefold is label dedup, not
   catalog identity or an artist-alias graph. Same title/day credited to
   different artists and duplicate rows with conflicting metrics abstain.
2. **Aggregation**: Daily Tracks has `Play Count` but cannot prove distinct
   sessions. Cap at one label per export calendar day and do not multiply by
   play-count or duration. A single date field is a source label, not exact
   listening timestamp. Calendar boundaries/time zones are not proof of
   physical home presence.
3. **Cross-source**: timestamped SonosPlaybackEvent actions are not a
   complete recording-level Sonos timeline. Lack of a nearby action does
   NOT establish that an Apple play was independent. Avoid combining Apple
   label/day evidence with Sonos favorites or bandit posterior as though it
   were independent positive evidence.
4. **Coverage**: 6,809 initial + 307 further excluded source rows; do not
   let ~19% initial abstentions disappear from coverage or quality reports.
   Do not attribute discarded rows to specific listening preferences. A
   zero histogram after 100% date rejection is a failed audit, NOT zero taste.
5. **Privacy**: keep raw exports on operator PC; no CSV upload into
   Sandbox/GitHub/Obsidian/Latitude, no real artist names, raw dates, source
   rows, hashed identity or unique personal samples in issues/CI logs.
   Even aggregates can be personal; obtain purpose-specific opt-in and
   define how to delete future persisted derived data.
6. **Consequences**: prohibit API/ranking, model training, database import,
   Apple account sync, real-time context, home/away/sleep inference,
   playlist queue, playback, Sonos writes, MusicBandit updates, automatic
   scheduled scans or background monitoring without separate authorization.
7. **Reversibility**: current local audit has no durable output; disposal of
   process-local intermediate values is the rollback. A later storage
   proposal must specify its provenance IDs, idempotent re-import, deletion
   by source, consent withdrawal, rollback and backfill semantics BEFORE
   building migrations or data writes.

## Acceptance matrix for a subsequent independently reviewed slice

- **Data integrity**: synthetic parser accepts validated full-format
  YYYYMMDD and rejects malformed dates, headers, metrics, oversized files
  or mixed/conflicting same-day descriptions. Empty/unparseable input
  abstains with a fixed aggregate reason, never a fabricated empty taste.
- **Metamorphic/idempotency**: input reorder and exact reimport produce
  identical aggregate histogram; repeated songs/rows or large `Play Count`
  do not change artist/day count. Adding a conflicting artist label or
  inconsistent metrics revokes affected title/day evidence, regardless of
  order. No automatic merging of near-spellings or collaborations.
- **Evidence contract**: Apple label/day counts NEVER become positive or
  negative affinity, track/favorite familiarity, trusted/proven candidate
  classification, bandit reward or playlist-playback signal. No adjacency
  may be mistaken for exact song familiarity.
- **Provenance/cross-source**: synthetic Sonos overlap unknown means
  independence unknown, even with no matching Sonos action log. Provider
  IDs and provisional title/date match do not prove recording or session.
- **Privacy/noninterference**: only allowlisted fields; no source paths,
  identity strings, row samples or dates in aggregate JSON, exceptions,
  command logs or GitHub; no network/file/database writes, music API,
  Sonos queue or HomeHub state effects. Review actual import graph and
  mutation surfaces, not just test reports.
- **Product validation**: require a human-reviewed evaluation plan:
  source-label vs catalog-identity collision rate, 6,809 initial
  abstention breakdown without raw data transfer, whether user wants
  per-artist inspection, and whether no-op source-only exposure provides
  any value before recommendation effects are permitted.
- **Gate**: independent privacy/provenance review plus full CI (once
  separately authorized PR exists). Do not declare production acceptance
  based solely on 286 targeted synthetic tests.

## Decision and handoff gates

**Already evidenced:** Date format accepted for 35,823/35,823 rows;
aggregate label-day counts and bucket distribution; pure offline read-only
prototype with 286 synthetic targeted tests passing at last verification;
no real-song identity, cross-source or user-presence claims.

**Recommended next step under #431:** independent adversarial review of
the currently preserved 23 untracked scoped files and this design packet, plus
a synthetic noninterference acceptance matrix. This may proceed without
another user PC command and without new private-data extraction.

**Stop and request a distinct product decision before:** showing any
identified artist from the export, storing any Apple history or derived
label/day record, introducing new schema/API/sync, altering canonical
taste or recommendation ranking, or affecting Sonos/house state.

**Separate Git/release gates:** commit, push, PR creation, merge and
deployment require the usual distinct authorizations. Independent Codex
review has not completed due to earlier authentication 401; direct
internal self-review is not a substitute.


## Oct 31 continuation — direct noninterference tests and independent review status

- Launched a **separate read-only** Sandbox Codex review with the durable
  launcher, task `0683b5bca4444160b99266ad7b801595`, after inspecting
  the registry. It is recorded `failed`, `worker_alive=false`, exit
  code 1, and did not return a review report. Its exact current failure
  cause is **not established** from the available empty worker stdout/
  stderr logs. An earlier review had encountered authentication 401, but
  do not infer that the new failure is necessarily 401 or claim an
  independent sign-off.
- Added the separate synthetic-only
  `tests/test_apple_music_shadow_exposure_boundary.py` (9 tests). It
  checks no live service/database/network dependencies in Apple audit
  imports; no Apple history dependency in current canonical
  `music_taste`; canonical empty taste stays exploratory and has zero
  affinity even when a separate Apple shadow report sees 12 days; input
  reorder/duplicate/concurrent artist-title ambiguity stay conservative;
  an explicitly selected synthetic CSV is the only file opened and no
  output files or network calls occur; all examined play counts still
  count as only one artist-label/day.
- The full bounded regression packet **286 passed**, including the eight
  Apple synthetic suites, canonical `tests/test_music_taste.py`, and the
  new 9 noninterference tests. Ruff for reviewed sources/tests,
  compileall for the Apple modules, and tracked `git diff --check`
  succeeded. These are *local deterministic checks*, not Linux CI or
  an independent security audit. Existing user-private read-only
  checksum-pinned local reader was **not modified**, and no additional
  CSV scan was requested.
- Worktree: `feat/apple-history-inspector-431`,
  HEAD `9670b3fcbeee5c51f50c29f610c1f150f81ba7db`.
  Exactly **23 issue-scoped untracked files**; no commits, pushes,
  PR creation, merges, live services, production DB, Sonos or deployment
  actions. Existing #432 PR remains a separate lane.
- Review interpretation: No code path from the local Apple audit into
  canonical taste was found in the checked import graph; absence of a
  found path is **not a formal proof** that no future consumer can
  misuse outputs. CSV parsing temporarily creates full bounded rows,
  including extra columns, before the adapter allowlists four fields;
  aggregate buckets are personal data, not guaranteed anonymous.
  Adding any per-artist mapping, cache, server sync, recommendation
  influence, or production storage requires a distinct product and
  privacy gate even after independent review.

**Next safe engineering step:** resolve/obtain independent review via
the normal reviewer tooling without changing credentials in this task,
then address evidenced issues, or prepare a scoped integration PR only
at a separate explicit commit/publish gate. The policy for mapping
artist text to catalog identity, retention, opt-in and withdrawal
remains unapproved; do not assume a green test count resolves it.
