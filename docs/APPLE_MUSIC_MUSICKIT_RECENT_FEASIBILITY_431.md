# #431 MusicKit recently played feasibility — fictional-only packet

**Status: LOCAL EXPERIMENT / NOT PUBLISHED OR APPROVED FOR LIVE USE — November 9, 2026.**

Parent: [#254](https://github.com/agatte/home-hub/issues/254). Owner:
[#431](https://github.com/agatte/home-hub/issues/431), Sensing & Intelligence.
This packet is source research plus a pure, non-actuating fixture assessment.
It contains **no personal account data, token, HTTP client, key, request, file
import, HomeHub runtime integration, persistence, recommendation update, or
Sonos/device command**. Nothing here authorizes production deployment or private
Apple Music transfer.

## User goal and authority boundary

The original outcome is that *native iPhone Apple Music listening, including
while traveling*, improves HomeHub song/artist familiarity and eventually
recommendations **without** guessing physical presence or waking Sonos. A
catalog resource alone is not an event or a human preference. Existing HomeHub
taste and playback authority remain unchanged.

The operator confirmed on November 9 that there has been **no newer music
trial** after the existing earlier Apple Music history work. The successful
October 12 Sonos audible playback and October 31 operator-local export analysis
are separate evidence, neither an automatic history sync test.

## What Apple currently documents (source reviewed November 9)

- [Get Recently Played Tracks](https://developer.apple.com/documentation/applemusicapi/get-v1-me-recent-played-tracks):
  `GET /v1/me/recent/played/tracks`; required `types` parameter can include
  `songs`, `library-songs`, `music-videos`, `library-music-videos`.
  Pagination uses `offset`; `limit` defaults to 30, maximum 30.
  Response is a paginated **Resource collection**, with track attributes.
- [User Authentication for MusicKit](https://developer.apple.com/documentation/applemusicapi/user-authentication-for-musickit):
  personal recent history requires a **Music User Token** and informed user
  authorization; Apple platform and web MusicKit can manage user tokens.
- [Generating Developer Tokens](https://developer.apple.com/documentation/applemusicapi/generating-developer-tokens):
  developer authorization is also required; other platforms require
  developer-token signature and identifier/key handling. No such key/token was
  requested or prepared in this experiment.
- [MusicKit platform overview](https://developer.apple.com/musickit/):
  Apple describes recently played content and personal recommendations, not
  a guaranteed per-play event feed with complete historical coverage.

**Important limitation:** Apple's documented *sample* for recent tracks
contains resource IDs, types and attributes (including catalog track duration),
**not** a verified unique playback-event ID, observed play/end timestamps, actual
played duration, skip reason or per-source overlap proof. Absence in that sample
is not a proof that no Apple API response can ever contain more fields. Until
supported by actual reviewed API contract/controlled opt-in observation, treat
all such play/session details as **unverified** and do not infer them.

## Two lanes: do not collapse them

| Question | Apple Data & Privacy CSV (operator-local) | MusicKit recently played API |
| --- | --- | --- |
| Mode | Manual historical export, not automatic sync | Potential repeatable authorized fetch |
| Access | Raw private source stays on operator-controlled PC; strict allowlist inspector | Requires developer and personal user authorization, consent/revocation, private network trust |
| Evidence | Event-type/reason/duration/timestamps may exist, quality and dedup **not fully proven** | Catalog/library resources; no verified per-play event ledger in documented sample |
| Identity | Provider ID sparsity, title/artist ambiguity, Daily Tracks join provisional | Catalog song ID *shape* useful for exposure feasibility, not verified recording equivalence |
| Duplicate risk | Repeat events, overlap with Sonos, uncertain Event ID semantics | Reappearing resource IDs across pages/fetches are not independently proven replays |
| Maximum safe output now | Anonymous aggregates from existing offline inspection | Anonymous fixture-only exposure shape/coverage counters |
| Preference eligibility now | **None** without verified sessions and non-overlap and new consent | **None** without playback/session proof and new consent |

For both lanes, never derive Home/Away, room, travel location, Sonos activity,
MusicBandit reward, familiar/proven trust, taste weight or per-song replay count
from provisional Apple metadata. Do not create `MusicArtist(source="import")`
rows: existing taste code treats such rows as positive familiarity.

## Fictional-only executable experiment

`backend/services/apple_music_musickit_recent_feasibility.py` accepts at most
four already-decoded fictional pages (a **test budget**, not an Apple API
pagination limit), at most 30 resources per page. It checks resource-envelope
shape and only recognizes ASCII positive decimal catalog-song ID **format**;
library identifiers and videos cannot become catalog song identities. It counts
observations, distinct catalog ID strings, duplicate-resource observations,
invalid ID shapes, library items and videos. It never follows `next`, decodes a
JSON response, makes a network request, stores identifiers, reads a file or
generates a user-visible label. Pagination `next` is reduced to an opaque
boolean and never emitted. Its immutable aggregate result expressly reports
zero verified sessions and refuses all taste eligibility / completeness proof.

Fictional regressions in
`tests/test_apple_music_musickit_recent_feasibility.py` exercise repeated
resources within/across pages, apparent played timestamps, anonymous output,
library IDs, music videos, missing/invalid IDs, malformed/unhashable types,
invalid next cursors, page budgets, non-mutating input, and blocked network/DB
operations during a fresh module import.

Validation (Windows Sandbox, Python 3.13):

```powershell
& 'C:\Tools\Python313\python.exe' -B -m unittest discover -s tests -p test_apple_music_musickit_recent_feasibility.py -q
```

**Passing fictional tests do not prove a live MusicKit response, Apple account
entitlements, token renewal, revocation, paging stability, rate limits, recent
history timing/coverage, actual device independence or preference accuracy.**

## Decisions and next gates

1. **Feasibility verdict:** MusicKit recent tracks is promising as a
   *recent resource/catalog exposure* signal, **NOT** an accepted
   playback-session or like/dislike signal. It cannot yet deliver the full
   originally requested familiarity-learning outcome.
2. **Before any real API call:** Choose user-device authorization architecture
   (iPhone-native MusicKit vs consented web MusicKit), token custody/renewal,
   privacy notice/withdrawal, bounded polling cadence, exact origin/TLS trust,
   request/response logging suppression, host/backup/crash exposure and
   fail-closed error behavior. Compare Apple's application/token requirements
   and real user entitlements. This is a **new owner decision**; no credential
   provisioning or account authentication is approved by this packet.
3. **Before any real source inspection:** Explicitly authorize a bounded,
   operator-present, private-device probe. Collect only aggregate schema,
   response quality and freshness/coverage facts; never share tokens, private
   song names or raw logs in GitHub, Sandbox or ChatGPT. Do not assume a
   token from one device can be reused on another.
4. **Before preferences:** Independently verify actual playback sessions,
   catalog exactness, Sonos cross-source nonoverlap, consent and withdrawal.
   Shadow read-only exposure is an independent decision; approved, durable
   familiarity/personalization requires a new reviewed schema, migration,
   idempotency and rollback plus separate deployment/owner acceptance.
5. **Original acceptance remains open:** Only user-verified listening-history
   effects on later HomeHub recommendations, with no away-presence or Sonos
   actuation, can satisfy the end goal. No new real-world music trial occurred
   in this fictional packet.