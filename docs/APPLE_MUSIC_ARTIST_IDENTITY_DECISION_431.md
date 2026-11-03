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

Review these synthetic files and validation results first. Commit, push, and
draft PR creation each remain behind the next explicit authorization gate;
nothing is published by this task.
