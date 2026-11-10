# #431 — No-paid-developer native-iPhone scrobble feasibility (fictional only)

**Status: SOURCE-ONLY DRAFT [PR #520](https://github.com/agatte/home-hub/pull/520); OWNER OPEN TO AN OPTIONAL FREE LAST.FM TRIAL; NO USER ACCOUNT CONNECTED OR PERSONAL HISTORY ACCESSED (2026-11-10).** Owner: [#431](https://github.com/agatte/home-hub/issues/431);
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
`LASTFM_API_KEY` for artist discovery metadata; this is **not** authorization
to query the owner's personal Last.fm listening history.

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
**evaluate and personally set up a voluntary trial**, not authority for
HomeHub to fetch personal tracks, install apps, store credentials, activate
a continuous source, or change recommendations. A pseudonymous Last.fm
profile may still expose actual listening publicly. Hiding recent listening
on Last.fm can prevent its unauthenticated API read; that privacy/function
trade-off must be visible before the trial.

## What the current fictional code proves

`backend/services/apple_music_lastfm_shadow_feasibility.py` consumes a
small, already-decoded **invented** collection of `user.getRecentTracks`
responses. It makes **no** network call, reads no files, uses no credentials,
stores nothing, and is not imported into the HomeHub runtime. Its three-page
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
   app, aware of the possible public listening profile. No scrobbler
   installation or Last.fm personal-history fetch has occurred in this
   HomeHub work. Do not use the existing Last.fm discovery API key to
   fetch account history without a further narrow owner approval.
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
