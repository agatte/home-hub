# #431 — No-paid-developer native-iPhone scrobble feasibility and read-only probe

**Status (2026-11-11): [PR #520](https://github.com/agatte/home-hub/pull/520) and [PR #521](https://github.com/agatte/home-hub/pull/521) merged to GitHub master; Latitude remains UNDEPLOYED, Last.fm shadow polling remains DISABLED by default, and native iPhone → Last.fm delivery is OWNER-VERIFIED. The following ranking preview is entirely OFFLINE/SYNTHETIC.** Owner: [#431](https://github.com/agatte/home-hub/issues/431);
parent [#254](https://github.com/agatte/home-hub/issues/254).

## Why this separate lane exists

The owner has **no paid Apple Developer Program membership** and must not
be asked that again as an unknown prerequisite. Official HomeHub MusicKit
developer-token integration therefore is not the near-term path. The existing
private Apple Data & Privacy Play Activity export remains a no-paid-developer
historical evidence path; it is **manual**, not a continuous travel sync.

Potential **optional** alternative: a trusted iOS scrobbler observes music
played through Apple's *native* Music app and forwards qualified plays to an
independent Last.fm account, which has a documented read-only
`user.getRecentTracks` endpoint. HomeHub already uses an optional
`LASTFM_API_KEY` for artist discovery metadata. The owner separately and
explicitly authorized the one-time read-only check on November 10, 2026;
this does **not** authorize autonomous sync or taste/ranking updates.

## External capabilities researched November 10, 2026

- [Scrobblie](https://scrobblie.fm/faq) advertises native Apple Music
  capture, background attempts/catch-up, and a **free 175 scrobbles/week**
  quota; it requires iOS 26 or later and a Last.fm account. The vendor
  acknowledges force-quitting the app stops background delivery. A free
  tier does not establish unlimited event coverage or repeated-play fidelity.
- [Finale for Last.fm](https://apps.apple.com/us/app/finale-for-last-fm/id1518365620)
  advertises Apple Music and automatic background scrobbling; its basic
  app listing is free. No claims about completeness are yet verified.
- [QuietScrob](https://apps.apple.com/us/app/quietscrob-last-fm-scrobbler/id741599377)
  advertises native-app scrobbles when reopened or left in the background,
  including streamed tracks; also has in-app purchases. Not tested here.
- [Last.fm user.getRecentTracks](https://www.last.fm/api/show/user.getRecentTracks)
  is a documented **read-only** interface, requiring a Last.fm API key but
  no personal Last.fm session token for the call. Maximum reported page
  size is 200; sample data contains track/artist details, a UTC scrobble
  timestamp, and occasionally a `nowplaying` entry. These are
  provider assertions, **not verified distinct Apple playback sessions**.

**Privacy warning:** A scrobbler sends selected listening metadata to
**Last.fm, a third party**. Its visibility, retention, sharing, deletion
semantics, and the iOS app's own data handling must be reviewed before any
owner account, app permission, or optional sharing is configured. Do not
infer that a public Last.fm API read means the underlying account is private.
**Owner decision (2026-11-10):** The owner is comfortable trying a free
scrobbler that shares listening information with Last.fm and delegated
selection of the simplest credible option. This is informed agreement to
**evaluate and personally set up a voluntary trial**. The owner later
confirmed the app was set up and authorized a **specific one-time read-only
history check**. There is no authority to store credentials or raw responses,
activate automatic polling, or change recommendations. A pseudonymous Last.fm
profile may still expose actual listening publicly. Hiding recent listening
on Last.fm can prevent its unauthenticated API read; that privacy/function
trade-off must be visible before the trial.

## Owner-authorized real Last.fm observation (November 10, 2026)

The owner supplied an exact Last.fm username **in the private conversation**
and expressly approved a read-only recent-history check. Do not place that
username, track/artist labels, song URLs, API keys, tokens, raw JSON, or
exact playback timestamps in GitHub notes.

Initial anonymous one-page API probe and independent reusable script check
using HomeHub's existing **local development** `LASTFM_API_KEY` (held only
in process memory, never logged or printed) returned:

- Requested account **matched** the provider's response account.
- Provider reported **1,105 historical scrobbles** total; newest first
  page contained 50 tracks with 50 parseable UTC timestamps and 50
  available artist/track label pairs; no currently-playing marker and no
  UTC-second collisions in this page.
- **Zero tracks in the latest 24 hours or seven days.** The newest
  returned track was from **2016**, despite the owner's report that the
  newly installed iPhone scrobbler seems to be working.
- This proves the **HTTPS API path and application key work**, **not**
  that current native iPhone scrobbles reached the requested Last.fm
  account, nor that any distinct play sessions are verified**. The
  historical total is an API assertion, not validated listening coverage.

Reusable opt-in Windows-only `scripts/Read-LastFmRecent-431.ps1` keeps a
fixed HTTPS provider endpoint, a single page up to 50 observations, a 15s
timeout, a 512,000-character JSON budget, no HTTP redirects, system
certificate validation, and aggregate-only fixed-output or redacted errors.
It accepts an already-configured key from process environment or an
explicit operator-supplied local `.env` path and **does not log or return
the key, full request URI, username, raw timestamps, track or artist names**.
It never writes a file or connects to HomeHub, Sonos or the DB. This is
a **single operator action**, not a polling service; the script is not
deployed and should not be run automatically. Synthetic stdin fixtures
in `tests/test_lastfm_recent_readonly_probe_431.py` passed **8/8**
on Windows Python 3.13/PowerShell, covering optional fields, denial,
mismatched user, current-track exclusion, timestamp collisions, JSON size
budget, limit, and non-leakage. Live read also returned aggregate success.

**Next integration gate (delivery proof passed):** The owner later inspected
Scrobblie's local History (three tracks marked Scrobbled, Queue 0 pending /
0 failed / 0 skipped) and opened Last.fm's own server-side Profile view.
The same three newly played tracks appeared there; Last.fm's total rose
from the **previously API-observed 1,105 to 1,108**. This is
**OWNER-VERIFIED server-side delivery**, not an independent new assistant
API fetch, long-term background/repeat/skip accuracy proof, or a HomeHub
recommendation effect. The **older 2016-only API snapshot is now stale**;
do not describe iPhone → Last.fm submission as blocked. iCloud Sync was
OFF for this successful trial and is not required for Last.fm submission.
No credentials, tracks or exact listening timestamps were shared in GitHub.
Continue a source-qualified read-only **HomeHub** adapter offline first,
then gate actual automatic account reads, persistent taste and deployment
separately. No need to change iPhone configuration for this milestone.

## Bounded Python source adapter — offline-tested

`backend/services/apple_music_lastfm_recent_source.py` is the first
HomeHub-shaped, manually invoked **read-only Python adapter**, sharing
the existing pure `apple_music_lastfm_shadow_feasibility` parser. It
prepares **one** official HTTPS `user.getrecenttracks` request at a fixed
endpoint, with a single-page limit of 50, 12s timeout, system certificate
validation, disabled redirects, <=512 kB response bound and fixed redacted
errors. It accepts an explicitly supplied username and application API key
**in memory only** and exposes anonymous freshness/collision counts with
source qualification, never song/artist/account labels or timestamps.
A test-only injected fetch function supplies fictional responses; the default
would contact the provider **only when someone explicitly calls it**.
The disabled-by-default runtime wrapper below can schedule it only after
explicit valid configuration. It never updates taste, infers presence or
controls Sonos. The source itself does not
establish verified independent plays (`verified_independent_plays=0`) and
refuses to mark any observation as taste eligible.

`tests/test_apple_music_lastfm_recent_source.py`: 10 synthetic unit
tests cover fixed HTTPS request shape, bounded payloads, provider errors,
private-data redaction, malformed dates and unexpected account mismatch,
future timestamps, collision handling and no unearned reward. The standard
library implementation keeps this testable on the protected Windows Sandbox
without installing additional packages. These synthetic tests do **not**
represent a new personal Last.fm account query or permission for unattended
polling, persistence or live API route publication.

## Disabled runtime shadow feed — local implementation, not deployed

The #431 development milestone adds `backend/services/lastfm_shadow.py`,
lifespan registration, and GET `/api/music/lastfm-shadow/status`. Defaults
are `LASTFM_SHADOW_ENABLED=false`, empty `LASTFM_SHADOW_USERNAME`, and
`LASTFM_SHADOW_POLL_MINUTES=15` (5..1440). Existing `LASTFM_API_KEY`
metadata behavior is unchanged. Disabled or invalid/missing configuration
creates **no producer task and no Last.fm requests**. The runtime gate
validates account shape, key shape and interval without displaying values.

When separately authorized and configured, each poll uses one page of at
most 50 historical resources plus an optional currently-playing resource.
Current tracks and missing artist/title/date abstain from identity counting.
Only assertions within the preceding seven days produce internal HMAC-SHA256
fingerprints of source + artist + title + second, keyed with fresh random
service-lifetime bytes. Raw music stays within transient parsing; fingerprints
never leave the service. First success seeds a baseline. Subsequent unseen
observations are counted against a maximum 4,096-entry, seven-day memory.
Identical overlapping observations collapse; different artists/titles at the
same second remain different assertions. No backfill or durable history exists.
Eviction, provider corrections, page gaps and restarts prevent exact lifetime
deduplication; counts are not sessions, preference, completion, Apple identity,
or evidence of independence from Sonos. Restart resets every counter and key.

Status returns anonymous counters, baseline and fetch freshness/state only.
It contains no labels, account, keys, fingerprints or absolute timestamps.
`recent_page_last_24_hours` is a provider assertion count from the last success;
`freshness` describes the fetch, **not** proof of current listening. No success
or more than two poll intervals since success is stale; failed polls report
degraded and preserve prior counters. Reads never refresh the source.
Both `require_api_key_strict` and `require_localhost` apply: strict auth alone
would allow remote key holders, so the additional existing direct-loopback
guard rejects LAN and tunnel-origin callers even with credentials. No new
listener, tunnel or auth exception is introduced.

The owned asyncio task uses `asyncio.to_thread` for urllib and the existing
lifespan cancellation list. Cancellation does not wait for the worker request;
an already-running thread cannot be forcibly stopped. Transport retains a 12s
socket timeout, byte cap, no redirects, and a checked body-read deadline; DNS
and platform socket behavior are not a guaranteed total wall-clock deadline.
Cancelled worker results cannot update service state. No exception text or
request details are logged, and there are no files, DB writes or downstream
recommendation/control consumers.

Validation uses fictional JSON and injected transports only. Python 3.13
stdlib tests cover lifecycle, baseline/dedup, memory expiry/cap, failure/stale
status, cancellation, redaction, and route/auth bodies. FastAPI is absent and
there is no worktree virtual environment: actual ASGI dependency integration
remains unverified; no packages were installed. No personal account was read.

**Next exact gates:** validate the actual FastAPI route/configuration and
lifespan in an authorized existing dependency environment; obtain separate
publication/integration and deployment authorization; obtain explicit owner
authorization for unattended reads of the chosen account and configuration
before supplying its username/key and setting the flag true. Deployment must
follow the existing release procedure. This task authorizes none of those
actions. Preference/schema/persistence changes remain separately CLOSED and
the original #431 acceptance remains OPEN.

## What the current fictional code proves

`backend/services/apple_music_lastfm_shadow_feasibility.py` consumes a
small, already-decoded **invented** collection of `user.getRecentTracks`
responses. It makes **no** network call, reads no files, uses no credentials,
stores nothing. The bounded runtime source now reuses this parser; its three-page
budget is only a synthetic test bound, **not** Last.fm's pagination limit.
It accepts at most 200 resources/page, excludes `nowplaying`, verifies
ASCII decimal timestamp *shape* in a conservative UTC range, and counts
repeated timestamps only as collisions. The returned immutable report
contains **aggregate counters only**, never song/artist names, URLs,
identifiers, date values, user accounts, or device/location data.

The report always states `verified_play_sessions=0`,
`recording_identity_verified=False`, `taste_updates_eligible=False`,
and `complete_history_proven=False`. It cannot establish actual Apple
source, track identity, skip/completion, exact timestamp, distinct plays,
independent Sonos non-overlap, completeness, consent, or preference.
The input itself is assumed decoded and has **no raw JSON byte bound or
authentication**; no live endpoint should pass untrusted bytes to this
module without a separate explicitly approved guard.

Fictional cases in
`tests/test_apple_music_lastfm_shadow_feasibility.py` cover pagination
budgets, no-current-track confusion, repeated timestamps, malformed API
response shapes, redacted refusals, Unicode/bad timestamps, input
immutability, and no network/DB access.

## Product decision and later trial gates

1. **Trial choice:** Owner has **agreed in principle** to free Last.fm
   scrobbling on November 10. Recommend free [Scrobblie](https://apps.apple.com/us/app/scrobblie-last-fm-scrobbler/id6761430824)
   first for Apple Music without changing players, with [Finale](https://apps.apple.com/us/app/finale-for-last-fm/id1518365620)
   as a fully free/open-source alternative. Scrobblie requires iOS 26+,
   has a 175/week free cap and may miss delayed/background/new-to-library
   plays; do not buy Pro before a meaningful trial. The owner must still
   create or choose a Last.fm profile and explicitly authorize the iPhone
   app, aware of the possible public listening profile. The owner reported
   that setup works and subsequently **confirmed three new scrobbles on
   Last.fm's server-side website**, total **1,108**, after the earlier
   one-shot API saw **1,105** historical records. Delivery is therefore
   **owner-verified**; automatic HomeHub reads, account changes and
   importing records still require their separate gates.
2. **Small owner-present proof (after voluntary device setup):** Keep playing
   in the native Apple Music app. Test one saved-library song, one streamed
   non-library song, and a deliberate repeated/quickly skipped song, with
   background app and force-quit/catch-up cases. Verify coverage after
   reconnection and source time quality, without forwarding private titles,
   exact timestamps or credentials into GitHub/Sandbox/ChatGPT. Use an
   anonymous coverage matrix, not screenshots or raw scrobble lists.
3. **Read-only ingestion architecture (distinct approval):** Make any
   future HomeHub adapter explicitly opt-in and pull-only, with a dedicated
   source identity, bounded date range, pagination, rate limits, log/URL
   redaction, dedup/gaps, revoke/disconnect and local-first retention
   policy. A Last.fm API key is **not** an Apple identity or proof that
   its entries came from the owner's iPhone.
4. **Preference gate (still CLOSED):** Verify independent recording
   identity, meaningful play/session conditions, missing data and Sonos
   overlap. Only after separate consent, security and schema/rollback
   review may source-qualified shadow familiarity be attempted. No
   `MusicArtist(source="import")` boost, MusicBandit reward, Home/Away,
   room, Sonos action, or deployment is justified by this experiment.

**Original #431 acceptance remains OPEN:** Listening to the native iPhone
Music app during travel should eventually improve HomeHub suggestions with
zero presence/room or Sonos actuation. Neither this fictional module nor
the manual export satisfies that real-world outcome.

## Offline canonical ranking preview � #431 bounded development milestone

`python -B scripts/demo_lastfm_taste_preview.py` runs a wholly synthetic,
nonpersistent example using `lastfm_taste_preview.py`, the current
`MusicTasteSnapshot.classify_candidate`, and the unchanged
`MusicDiscoveryService.preview`. It has no account input or transport. Catalog
verification is an invented fixture assertion, not a real catalog lookup; all
tracks remain `metadata_only`. No runtime registration or API is added.

The fixed-clock seven-day batch accepts at most 512 assertions and requires exact
artist/title plus an aware date. It rejects malformed, now-playing, future and
stale assertions. Exact artist/title/time duplicates collapse; different songs
in the same second remain distinct. Explicit fixture-confirmed Sonos overlap
suppresses familiarity, including conflicting duplicates. Names/times alone do
not establish overlap or independence.

The overlay deep-copies the baseline and uses absolute familiarity targets
(0.45 for one observation, diminishing to a 0.80 cap), so replaying a batch is
idempotent. Artist depth uses distinct named tracks, capped at four; track depth
is capped at five. Existing greater familiarity/depth wins. Explicitly positive/negative
canonical artists remain entirely unchanged, including their existing track-ranking
contribution: passive tracks for those artists stay diagnostic-only to prevent
accidental dilution of explicit feedback in the existing classifier. Preference,
weights, contexts, Sonos provenance and observation dates are never rewritten.
Existing source tags are retained, and the synthetic Last.fm source tag is
added only when a neutral entity gains familiarity or depth. No title-only
keys are added. Counts describe provider assertions, not verified plays, likes,
dislikes, completion or Apple identity. Diagnostics separate observed counts,
suppression and inferred targets. Existing canonical title-only fallback, if
already present in a supplied baseline, remains the canonical classifier's
behavior; this experiment supplies no such ambiguous evidence.

The fictional gentle-policy example moves Copper Kites from second (0.5372)
to first (0.6272): two distinct heard tracks supply 0.03 depth contribution,
and repeated exact Paper Comet observations change novelty, supplying 0.06.
Preference stays zero. Velvet Abacus retains its existing explicit positive
artist evidence **and unchanged per-artist ranking score**, rather than being
penalized for a neutral scrobble. Tin Orchard remains excluded by canonical Not for me feedback.
A single observation of Marble Otters stays exploratory. Output omits dates,
URLs and account identifiers. The existing HMAC-only runtime shadow status
**does not expose named tracks** and is not a data source for this demo.

Validation is synthetic only: the focused regression suite covers repeat caps,
permutations/dedup/idempotency, collisions, invalid records, exact identities,
Sonos overlap, canonical preservation/rejection and deterministic CLI output,
plus the neighboring taste/discovery suites: **51 tests passed** (19 preview,
32 neighboring); scoped Ruff and `git diff --check` passed. Two CLI runs were
byte-identical. No personal data was queried and
no production behavior was verified. #431 and original #254 acceptance remain
open. Next gate is owner review/integration of this offline milestone. Any live
adapter still requires separately authorized opt-in/account data access and
privacy/retention/revocation design, qualified named identity and Sonos overlap
proof, persistence/schema review if proposed, and separately authorized
deployment through the established release procedure. No live enablement is
implied by this preview.

## 2026-11-11: offline named-evidence consent rehearsal after PR #522

Local development only, based on `d2d7fc1a`; no runtime registration or account
read. `lastfm_named_evidence_dryrun.py` accepts a caller-supplied list of at most
50 fabricated provider-shaped observations and a separate matching list of
fictional source/Sonos qualifications. A fresh `FictionalConsent` requires
both explicit synthetic-only and named-rehearsal opt-ins; it is consumed by one
batch attempt. Every eligible row requires an out-of-band fictional source
qualification, never a provider-carried authority field. These declarations
**cannot authenticate consent or detect whether a caller has substituted
personal data**. This API is for trusted synthetic tests,
not a guard suitable for accepting real payloads. No live-source readiness is
claimed. The delegated synthetic worker made no live API reads; the controller
independently checked current GitHub issue scope.

Exact artist + title + ASCII UTC epoch second is required. Now-playing, invalid
markers, malformed identities/dates, future records and records older than seven
days abstain. Each preview rechecks freshness against its explicit fixture clock.
Exact normalized artist/title/second duplicates collapse. Distinct artists with
the same title remain separate; title-only, delimiter-ambiguous and missing-name
observations cannot create evidence. This is textual assertion matching, not
recording/catalog resolution or Unicode-confusable identity verification.

Out-of-band per-observation Sonos qualification must carry the fictional
`synthetic:complete_sonos_coverage_non_overlap` marker. Confirmed overlap is
suppressed; absent, malformed or ambiguous coverage abstains. The most restrictive
qualification wins for duplicates, regardless of order. Provider-shaped rows
asserting `authority` or `sonos_proof` are rejected: a Last.fm payload must
never certify its own source identity or absence of Sonos overlap. A real
implementation
would need independently collected, source-qualified Sonos interval coverage,
clock/time uncertainty and gap rules, and identity resolution. A lack of Sonos
events, a timestamp/name match or this fixture marker is **not real overlap proof**.

Eligible assertions enter the existing pure overlay on a private deep copy of
the baseline. Any added provenance is `lastfm_unattributed`: neither Apple-verified
identity nor independent plays, likes, dislikes, completion, genre/context
preference or actuation. Existing canonical positive/negative evidence and
rejection remain authoritative. No ranking engine is added. The identity-bearing
overlay snapshot and its diagnostics are deliberately not exported: the public
result contains aggregate counters and fixed qualifications only, with redacted
object representations/errors. There is no fetch, polling, log, persistence or
serialization path; explicit serialization of the session/token is refused.

The temporary session owns copied primitive observations and a copied baseline.
Use it as a context manager; exit (including exceptions), `drop()`, or token
`revoke()` releases those references and blocks further previews. The consumed
token cannot reopen a session: another batch needs new explicit fictional consent.
Overlay results exist only during a preview and are discarded before returning
aggregates. There is no background expiry worker or secure memory erasure promise.
The caller owns its original inputs; Python debugger/traceback/private-attribute
access and process-memory copies are outside this contract. Do not pass personal
data or publish raw tracebacks with locals. Aggregate results already returned
cannot be recalled. A future real-data design must separately define maximum
session lifetime, automatic expiry, all consumer copies, retention and deletion.

Staging gates remain separate: (1) controller review of these local synthetic
diffs/tests; (2) explicit owner privacy approval for the exact account, real named
read scope, transport/redaction and transient retention/revocation design;
(3) independent identity/time and real Sonos overlap proof, with unknown coverage
still abstaining; (4) separately approved retention/schema or ranking effects and
their rollback/revocation consumers; (5) authorized integration/deployment and
physical acceptance. This rehearsal grants none of those permissions and does
not satisfy original #431 acceptance. The HMAC-only merged-but-not-deployed shadow
feed intentionally has **no name bridge**; `lastfm_shadow.py`, its network source,
bootstrap, canonical taste/discovery, DB and Sonos are untouched. No current
Latitude health or deployed SHA was investigated.

Local validation after independent trust-boundary correction: **81 passed**
across `test_lastfm_named_evidence_dryrun.py`,
`test_lastfm_taste_preview.py`, `test_music_taste.py` and
`test_music_discovery.py`; scoped Ruff and `git diff --check` passed. Used the
specified main venv, `APP_ENV=testing`, disabled bytecode/cache and plugin
autoload, with `pytest_asyncio.plugin` explicitly enabled for the existing async
tests. Initial local evidence was developed in isolated worktree
`lastfm-evidence-contract-431-20261111`, branch
`work/431-lastfm-evidence-contract-20261111`; GitHub publication/merge and any
future release are evidenced separately under issue #431.
