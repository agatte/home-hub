# Artist identity review contract — #431

This is synthetic engineering groundwork, separate from acceptance of the stage B
session-local artist-label/day reviewer. It neither reads exports nor connects to
Apple, Last.fm, Sonos, databases, or existing application runtime. No real artist
values, dates, catalog IDs, or source files belong in fixtures or review output.

## Contract and conservative abstention

`evaluate_artist_identity_review` accepts an immutable tuple of at most 5000
invented observations. Each has one of the accepted viewer's four bands (1, 2–3, 4–9, 10+ source dates) and zero catalog claims, or 1–5
claims. Aliases are bounded at 16; strings at 256 characters. Invalid batches
return one fixed `invalid_input_abstain` indicator and discard all candidate
counts. This indicator is a batch failure, not a count of rejected labels.
Inputs have redacted representations; the evaluator has no logging or IO.
Callers must not serialize the input dataclasses as telemetry.

NFKC/casefold groups potential label conflicts for comparison only. Controls,
format characters, surrogates, empty values, malformed states, mixed sources,
and unknown provenance fail closed. No text normalization confers identity.
Provider and artist ID remain an exact, case-sensitive pair. No cross-provider
merge occurs. A single exact whole display-name match with a typed synthetic
verification claim is only `identity_candidate_for_human_review`, with mapping
status `hypothetical_candidate_only`. Even a spoofed valid synthetic claim grants
zero live identity proofs, preference effect, and ranking effect.

Composite labels are never split at ampersands, “feat.”, or other punctuation.
Only a whole-name exact claim can be a hypothetical candidate, including a
genuine whole artist name containing such punctuation. Alias-only and
normalized-only matches abstain. Multiple distinct claims, conflicting aliases,
shared names across different provider-qualified identities, or inconsistent
claims for one identity revoke candidates. Exact duplicate observations and
claims do not inflate counts. Alias tuple order and duplicate alias entries
currently count as different claims, which can conservatively produce false
conflicts; this is not evidence of different real catalog artists. Catalog
ambiguity/conflict status also takes precedence over review-state counts, so
this aggregate is not a replacement for future per-label human UX.

Any inconsistent observation within the same
normalized label (including different days buckets or review states) revokes
that entire group. Output contains fixed aggregate categories and warnings;
no labels, IDs, per-label buckets, dates, or frequency rankings are returned.

Review state is independent of catalog evidence. `unreviewed` and `reset`
do not accept identity. `needs_verification` is not confirmation;
`reject_label` is not dislike. Arbitrary strings and `confirm_identity` are
invalid here. A future explicit identity acceptance needs a separate contract;
no boolean or caller-supplied provenance string authorizes live trust.

## Future policy and explicit product gates

Actual verified artist identity requires a trustworthy provider catalog lookup,
or a user-supplied provider ID independently verified with that provider, plus
explicit separate match acceptance. Provider verification and user consent
must each have auditable provenance. Neither is implemented by this evaluator.
Track identity is stricter: recording identity, session evidence, and cross-source
reconciliation must be established independently. The synthetic recording
proof-gap evaluator is not an artist proof or a real proof issuer.

Label/day exposure never establishes favorite, familiar, proven, like, dislike,
or positive/negative taste. Never create `MusicArtist(source="import")` rows:
the canonical taste system treats these as positive evidence and familiarity 1.
No taste, MusicBandit, discovery, recommendation, or Sonos actions are connected.
Apple/Sonos overlap remains unknown; do not double count. Optional explicit
preference feedback through #263 would require a new user decision, a separate
opt-in, and a provider-qualified identity.

The consent ladder remains separate: accepted session-local B does not authorize
later C storage. C requires a product decision on scope, retention (no TTL is
proposed here), revocation, and rollback. Later D would require separate approval
for a shadow-only ranking experiment with reviewed data flow and provenance.
Neither C nor D is accepted by this work. Current real input remains private;
no file picker, source discovery, storage, host administration, or device write
is part of this contract.

This synthetic evaluator contract was integrated through merged PR #460; that
source merge is not live Apple identity verification or production deployment.
Catalog lookup, retention, recommendation effects and device/production use
remain separately gated.

## 2026-11-03: Quiet Atlas synthetic handoff seam (local, uncommitted)

`frontend-svelte/src/lib/appleMusicArtistReviewHandoff431.fixture.json` is the
only input to the artist-review route. Its pure client adapter validates the
whole packet before producing a frozen UI projection; invalid packets throw one
fixed error containing no source values. There is no fallback input path.

Schema `artist_review_fixture_431_v1` requires
`provenance=synthetic_fixture_only`, `source=apple_daily_tracks`,
`evidence=artist_label_day_exposure`, `identity_status=unverified` and false
`preference_eligible`, `session_proven`, `cross_source_independent`,
`actuation_eligible`, `live_catalog_enabled`, `network_enabled`,
`persistence_enabled`. These packet-level invariants apply to every row.
Exactly four ordered artist rows contain `ref`, `label`, `date_band` (one of
`1`, `2-3`, `4-9`, `10+`) and `candidate_refs`; exactly five claims contain
`ref`, fictional `provider=DemoCatalog`, `name` and `note`. All labels, bands,
refs and claims are pinned to the invented examples, including two distinct
same-name candidates. Unknown fields, nested extras, altered text/bands,
duplicates, unknown refs, non-data properties and enabled flags reject the
entire packet. Provenance text alone cannot enable arbitrary real labels.

This models the local reviewer's transient (unverified label, date-band) shape,
but does not call that script, read its RAM, adapt its real output, or connect
the aggregate identity evaluator. No CSV/Apple payload, file picker, query
parameter, clipboard, browser storage, export, dynamic private import, provider
request, backend telemetry or HomeHub API is connected. Per-query permission is
a simulation; match selection stays ephemeral mock state and never issues an
identity proof or preference/session/cross-source/actuation eligibility.

Validation: 50 dependency-free Node bridge, route and cancellation checks passed,
including direct entry, client navigation and fixed redacted proxy errors; syntax
and diff whitespace checks. Existing Vitest source assertions now consume the
fixture; mounted flow/focus tests retain consent, next, undo, unsure, reset and
Escape coverage, with an added cancel/skip/reconsent/no-request test. Those
Vitest/Svelte checks and fresh desktop/mobile visual verification remain
unexecuted because this worktree has no node_modules; no packages were installed.
This is local synthetic evidence, not CI, independent review or new visual
acceptance. The artist-review page's layout and handlers are preserved.

An independent code review found the page had no IO, but the inherited root
Svelte layout still initialized HomeHub REST/WebSocket, weather, activity and
ambient services on the preview route. `rootRuntimeTargets` now excludes only
`/quiet-atlas/music/artist-review` (plus existing Guest/prototype behavior)
from normal runtime startup, and uses the root layout's owned cleanup when
navigating into it. Normal Music and functional HomeHub routes retain their
runtime; leaving the preview resumes subscriptions. Node tests cover direct
entry and navigation, with root source wiring assertions. They do not replace
a mounted layout/browser test. Already in-flight REST reads started on the
prior route are not retroactively aborted; normal page assets still load.
No data or device authority is granted by this isolation.

A subsequent independent review found that the Game Day REST prime could still
chain `/state` or `/schedule` after a prior request rejected following feed
cleanup. The scoped `gameday.js` correction guards generation before each next
request and before the schedule-failure store update. Five dependency-free
synthetic tests execute the real prime body with mocked deferred failures:
cleanup before launch, viewer-sync rejection, state rejection, schedule
rejection and normal owned success. This prevents new Game Day follow-on
requests from an abandoned feed; it does not cancel already-started requests
or alter Game Day's successful priming flow. This cross-workstream change
requires ordinary frontend CI and integrated browser lifecycle verification.

Next gates remain separate: explicit consent and reviewed transport before any
real label handoff; per-artist provider disclosure/egress consent, trustworthy
provider verification and separate match acceptance before real identity;
scope, retention, withdrawal/deletion and rollback decisions before persistence.
Session proof, cross-source independence, taste/ranking/import and actuation
remain unaccepted and require their own decisions. Commit/publish/merge/deploy
are not authorized by this local task.
