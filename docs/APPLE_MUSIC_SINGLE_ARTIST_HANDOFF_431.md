# #431 — single-artist consent and ephemeral receiver, merged offline foundation

**Status: MERGED OFFLINE-ONLY in PR #495 (2026-11-05 UTC), squash commit 6daf2cde7df080415f28187ae43181e38ed3b10a; NOT DEPLOYED, ACTIVATED OR APPROVED FOR REAL-NAME TRANSFER.** This eight-file foundation was reviewed and merged after exact-head CI and synthetic Windows Tk acceptance. Its source modules remain inert: a separate, secure, reviewed transport, dedicated authentication and user-operated sender are prerequisites for any real transfer.

**Owner:** Sensing & Intelligence / Music Intelligence. Parent issue: [#254](https://github.com/agatte/home-hub/issues/254). Primary record and consent gates: [#431](https://github.com/agatte/home-hub/issues/431), especially [the accepted narrow data-sharing decision](https://github.com/agatte/home-hub/issues/431#issuecomment-6647769532) and [stage-4 offline test/security evidence](https://github.com/agatte/home-hub/issues/431#issuecomment-6649060854).

## Accepted product boundary (November 4, 2026)

The owner approved **one explicitly selected and individually reconfirmed provisional artist name**, from their **own real Windows PC**, to their **own HomeHub Latitude backend**, for **temporary review**. Every actual name still needs deliberate one-item consent on the real PC before transfer. This does not permit archive uploads, bulk/automatic scanning or sync, exposing a real name to ChatGPT/Sandbox/GitHub, third-party catalog egress, durable preference storage, artist/track identity assertions, music taste/ranking changes, Home/away inferences, or Sonos actions.

The existing Windows local Tk artist-label reviewer and deployed Quiet Atlas fictional artist-review page are **untouched** by this branch. The former was previously tried by the operator; the latter is a fictional preview, not a real-data endpoint. Apple Daily Tracks' label/day exposure is **not evidence** of a verified artist identity, distinct play session, favorable preference, song recording, or independence from Sonos.

## Exactly eight new files in this review candidate

1. **backend/services/apple_music_single_artist_handoff.py** — pure offline one-artist preview and one-use confirmation challenge, typed redacted objects, neutral date-band validation, exact eight-field body with false eligibility flags and a 512-byte UTF-8 artist bound. Its confirmed boolean is a model of a UI event, not real human/device/server authentication. No transport, disk or telemetry.
2. **scripts/apple_music_single_artist_review_adapter.py** — ties one selected row to an existing volatile LocalReviewSession candidate list; detects source-list identity/content changes, cancellation, reused preview and wrong recipient. It does not modify or install the existing default local-review launcher.
3. **backend/services/apple_music_ephemeral_review_receiver.py** — **UNREGISTERED in-process simulation** with fixed eight-field schema, bounded payloads, synthetic externally passed credential comparison, mutex-protected one-slot receipt, 60-second default deadline, one-time take and redacted acknowledgment. This is **not** a FastAPI endpoint, genuine TLS verifier, replay ledger or provider identity proof. The transport_verified test Boolean MUST NEVER be asserted from untrusted HTTP input or treated as TLS proof.
4. **scripts/apple_music_local_handoff_rehearsal.py** — opt-in CLI entrypoint that mounts the existing Tk reviewer and adds a clearly marked *offline-only* one-artist confirmation button. The modal shows the selected provisional name, neutral observed-date band, intended HomeHub recipient and future disclosure. It rechecks the underlying session, selected Treeview row, source label and review action before and after the dialog. **Even after Yes, the prepared body is immediately discarded and no send happens.** The default local reviewer remains unchanged.
5. **tests/test_apple_music_single_artist_handoff.py** — fictional-only consent/adapter/receiver checks, including validation, cancellation, forgery, immutable preview, bad credentials, expiry, stale source, concurrency and redaction.
6. **tests/test_apple_music_local_handoff_rehearsal.py** — fictional-only no-I/O, modal cancellation, source/session/row/action changes, no-preconsent payload and abort checks.
7. **tests/test_apple_music_local_handoff_tk.py** — actual mounted Tk Treeview/button tests with fabricated names; skips if no display.
8. **docs/APPLE_MUSIC_SINGLE_ARTIST_HANDOFF_431.md** — the merged offline-foundation contract, evidence limits and future secure-transfer gates.

## Verification / evidence scope

Before offline-only merge, corrected Stage 4 source/test files passed **65 synthetic tests and 22 subtests** under Linux/Xvfb. Windows Sandbox independently passed **65 scoped tests** under Python 3.13/Tk 8.6 and **five additional scenarios using the original Tk review window with fictional in-memory data**. GitHub exact-head Check run 41967657312 (backend, lint, frontend) completed **SUCCESS**. All tests use invented labels and no private CSV. The staged ZIP CRC and each of its code/test file checksums were verified before publication; changes to this Markdown status page do not alter executable contract. The green CI and fictional original-window tests do **not** prove operator-led file selection, authenticated TLS, private data acceptance, or production runtime.

**Dated security environment observation:** Earlier protected Windows Sandbox Git failed under Smart App Control unsigned-DLL enforcement (Code Integrity 3033/3077/3118). During the final PR #495 review Git 2.55.0.windows.3 ran again without any policy modification; mapped repository ownership still requires a bounded per-command `safe.directory` setting. Neither the PR nor this status correction changes host/Sandbox security. Do not presume future Git availability without live probes.

## Closed gates before any real Apple name is transferred

### 1. Dedicated identity, transport and endpoint

- Design a minimal opt-in receiving API in a **separate** reviewed change. Existing ordinary HomeHub require_api_key authorizes some RFC1918/loopback callers without a key; require_api_key_strict still exempts direct localhost. **Neither alone is sufficient** for private Apple artist names.
- Bind a dedicated, scoped credential to the operator/session; require authentication on *every* peer including localhost/LAN and restrict repeated/parallel submissions. Review origin, CSRF, request method/size, trusted proxy, rate limit and false/expired/replayed token cases. Prove server-side nonce lifecycle and restart behavior; the offline receiver intentionally does not.
- Establish an encrypted, server-authenticated PC→Latitude channel with reviewed TLS certificate/identity and exact destination; currently observed plain HTTP http://homehub-dashboard.local:8000 is insufficient. Do not provision secrets or change network/host settings without specific approval.
- Never place an artist name in URLs, query strings, error text or headers. Audit API/proxy/Sentry/log bodies, crash traces, client history, cache and backups before enabling. No raw-name debugging, permanent persistence, automatic retries or insecure fallback.

### 2. Actual human and source consent

- The existing on-PC local reviewer must read **only** one deliberate chosen Apple Daily Tracks file under its already-bounded local rules, with no background sync.
- A real sender (not present here) must show exact selected unverified name, exact HomeHub recipient, information disclosed, and explicit affirmative single-use confirmation; fresh source/action/selection revision and a server-issued short-lived challenge must still be valid at sending time. Cancellation, closing, changed selection and source withdrawal must abort.
- The rehearsal's current dict snapshot cannot detect a state changed and restored *identically* during a modal; use a monotonic event revision for the live sender. Python object disposal does not guarantee byte-zeroization.
- A catalog query to Apple, Last.fm or anyone outside HomeHub requires a distinct, per-request consent decision identifying that provider. Provider-qualified artist identification and a human match acceptance are additional independent steps.

### 3. Evidence, learning and device authority

- Even a successful private transport is **not** listening proof, artist identity, favorable preference or Sonos-negative session proof. Keep source-qualified unverified Apple evidence separate from canonical taste.
- Never synthesize MusicArtist(source="import") for Apple label/day buckets; that existing path conveys undeserved positive familiarity. Do not update MusicTasteSnapshot, MusicBandit, discovery ranking, Sonos or any physical-context/light/presence writer.
- Before later persistence/ranking, choose retention, consent receipts, source provenance, idempotent reimport, removal/withdrawal, cache/backup effects, and rollback; prove track recording+session identity and address unknown Apple/Sonos overlap. Any non-actuating shadow experiment needs its own reviewed scope and explicit approval.

## Review and release gates

**PR #495 is merged for offline-only groundwork; its merge and green CI do not authorize deployment or real-name transfer.** Before a future real-transfer release, independently review the new transport/authentication/logging/retention changes, complete operator-visible one-item confirmation on the real PC and a fictional-only end-to-end security test, and obtain separate scoped integration and deployment approvals. No live API registration, Apple export reads, external catalog queries, production database or device writes are part of this packet.

**How to run the candidate tests** in a full compatible checkout with dependencies available:

~~~sh
xvfb-run -a python -B -m pytest -q tests/test_apple_music_single_artist_handoff.py tests/test_apple_music_local_handoff_rehearsal.py tests/test_apple_music_local_handoff_tk.py
~~~

The optional on-PC **offline rehearsal** entrypoint is:
~~~sh
python -B -m scripts.apple_music_local_handoff_rehearsal --offline-rehearsal
~~~
It **only** shows a local modal and discards the proposed payload. Do not use it on real private data through a remote agent, or infer authorization to send a real name from a mock approval.

## Resume

Owning issue [#431](https://github.com/agatte/home-hub/issues/431) holds current delivery and remaining consent/security gates. Next is a separately reviewed security/transport protocol proposal, dedicated bypass-free authentication design, monotonic GUI revision, bounded retention, logging audit and a fictional-only test plan; **not** production activation. Future Git repairs must preserve Smart App Control and unrelated worktrees. All post-PR integration, actual data movement, identity verification, durable learning and Sonos actions remain separately gated.

See [the proposed secure handoff protocol](APPLE_MUSIC_SECURE_HANDOFF_PROTOCOL_431.md) for the separate, NOT APPROVED future transport design and fictional offline gate boundary.
