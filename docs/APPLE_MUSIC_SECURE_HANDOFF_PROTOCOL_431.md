# #431 secure single-artist handoff protocol

**PROPOSED / NOT APPROVED — 2026-11-05. No real-name transfer authorized by this design.**

Owner: [#431](https://github.com/agatte/home-hub/issues/431), Music Intelligence.
[PR #495](https://github.com/agatte/home-hub/pull/495) merged the inert offline
foundation at `6daf2cde7df080415f28187ae43181e38ed3b10a`. Local Git confirms
that commit and its offline-only message. Issue/PR live state was not fetched:
this task forbids network access. The supplied status reconciliation is preserved
in [the foundation contract](APPLE_MUSIC_SINGLE_ARTIST_HANDOFF_431.md).
[PROJECT_SPEC.md, Music Curator](PROJECT_SPEC.md#music-curator) remains product
authority; this proposal grants no taste, ranking, identity or device authority.

## Scope and present evidence

The only future disclosure contemplated is one individually selected and
explicitly reconfirmed provisional artist from the owner's real Windows PC to
the owner's HomeHub Latitude, for temporary review. No private input was opened
for this slice. No real name belongs in Sandbox, chat, GitHub or these tests.
No bulk transfer, import/export, catalog lookup, learning or Sonos action follows.
Third-party catalog access needs separate per-provider, per-request consent.
**No Cloudflare transfer absent new explicit consent**, including adding a route
to the existing public tunnel allowlist.

Current code observations, not production probes:

- `backend/api/auth.py`: `require_api_key` has local/private/LAN bypasses;
  `require_api_key_strict` still bypasses direct localhost. Neither is a sufficient
  dedicated identity boundary for this proposal.
- `backend/api/tunnel_proxy.py`: a separate Cloudflare allowlist and marker
  rewriting exist, with HTTP loopback upstream and URL/error logging. Its current
  contract does not implement this private transfer protocol.
- `scripts/apple_music_local_handoff_rehearsal.py` and
  `scripts/apple_music_single_artist_review_adapter.py` compare snapshots.
  Identical restoration during a nested modal can escape equality checks.
- `backend/services/apple_music_ephemeral_review_receiver.py` is an unregistered
  simulation. Its caller-supplied credential/transport flag is not authentication
  or TLS evidence; lazy expiry is not proactive purge. Removing a Python reference
  is not verified erasure.

All remain LIVE TRANSFER BLOCKERS. This patch changes none of those files.

`backend/services/apple_music_offline_handoff_gate.py` is a separate fictional
state model with no payload, UI hooks, transport, routes or storage. Its synthetic
caller-provided principal, audience, session, boot epoch and confirmation fields
**DO NOT establish human identity or TLS**. It models one challenge/attempt per
instance, locked consumption, revision events and injected monotonic deadlines.
Every selection/action/source reload/discard event must advance revision even if
values are identical; the current GUI is NOT wired to do so. Explicit `sweep()`
and `close()` drop challenge references, but there is no timer or automatic
purge. Default challenge randomness is lazy secure randomness; deterministic
injection is fictional-test-only. A new object has no old challenge state.
This is not a receiver replacement or production replay ledger.

## Threat model and trust boundaries

Protect the provisional name, consent context, credentials, nonce and temporary
review against unintended disclosure, replay, substitution and retention.
Threats include a hostile LAN/localhost client, compromised browser origin,
spoofed forwarding headers, mistaken server identity, stale modal events,
concurrent submissions, malformed bodies, logs and ambiguous delivery. A
compromised authenticated endpoint, OS administrator or malicious operator
cannot be made safe by an in-memory Python gate. Availability attacks may burn
challenges; fail closed rather than permit reuse.

The real sender must verify a reviewed HTTPS server certificate chain and exact
hostname/destination, with no HTTP fallback, insecure verification option or
redirect to another host. Private **Tailscale Serve HTTPS is a candidate only**;
its configuration, certificate identity, access policy and privacy properties
are NOT known configured or verified here. VPN reachability alone is not proof
of application identity. Review TLS termination and the protected final hop,
including preventing direct backend access around the intended ingress.

Use independent dedicated scoped authentication on start, submit, withdraw and
read, including every LAN and localhost peer. Do not inherit the existing bypass
functions or treat IP address as identity. Bind authenticated principal, exact
recipient audience, server-generated session and fresh unpredictable server boot
epoch to server-owned challenge state. Never trust identity, transport_verified,
revision authority or boot authority merely because a client sent a field.
Provisioning, credential lifecycle and deployment require separate approval.

Require exact allowed Origin/Host, reject cross-origin browser requests, and
review CSRF protection for every operation (including read/consume); CORS alone
is insufficient. Prefer no ambient cookie authority; if cookies are introduced,
review SameSite, secure flags and CSRF token binding. Deny unreviewed origins,
methods, content types, redirects, caches and service-worker interception.
Trust forwarded identity/scheme/host only from a bounded reviewed proxy; strip
client forwarding and tunnel-marker claims before inserting trusted metadata.
Generate server request IDs; ignore or strictly validate inbound IDs. Never use
an inbound ID as identity or reflect arbitrary values into logs or errors.

Names, credentials and nonces must never enter URLs, query strings, headers,
request IDs, access/error logs, Sentry, analytics, exception locals or debug dumps.
Audit sender, TLS terminator, proxy, app and UI together; fixed redacted failures
and acknowledgments, `Cache-Control: no-store`, no history/localStorage or body
logging. Sanitizing only application logging leaves other copies exposed.

## Conceptual future sequence (not implemented)

1. **Start:** authenticate and validate the exact HTTPS destination and origin.
   With no name submitted, create one bounded volatile session and unpredictable
   one-use nonce tied to principal/audience/boot, deadline and operation purpose.
   Limit active sessions and rates. A new start must not silently retry an old
   attempt. Server enforces a monotonic TTL, proposed maximum 60 seconds.
2. **Local preview:** deliberate one-row selection on the real PC shows the exact
   unverified name, recipient and temporary-review disclosure. Capture an event
   revision before opening the modal. All selection/action/source reload/discard
   callbacks increment revision; reject-label, No, cancel, window close or any
   event invalidates the challenge, even if values are restored afterward.
3. **Submit:** only explicit Yes plus unchanged original revision permits one
   attempt. Bind the original snapshot revision and server-owned challenge to the
   authenticated session. Validate under a single admission lock/transaction;
   consume before validation, with no second attempt on failure. Invalid attempts
   for an identifiable session revoke its outstanding challenge; unparseable or
   unauthenticated requests never create authority and must be rate limited.
   A server cannot independently infer GUI events: reviewed sender wiring and
   fictional mounted-event tests are an additional mandatory trust boundary.
4. **Parse/admit:** bound streamed **raw body bytes before JSON parsing**, proposed
   maximum 2048 bytes for the whole versioned envelope including bounded control
   fields. Reject compressed bodies, oversized/chunked accumulation, duplicate
   JSON keys at every nesting level, invalid UTF-8, unknown fields and wrong types.
   Keep the existing exact eight-field name payload contract and 512-byte UTF-8
   label limit; envelope version/control fields require independent schema review.
   Do not confuse the offline receiver's reserialized 1024-byte check with a raw
   ingress cap. No reflected body/error content. Admit one volatile review slot
   with all existing unverified/false eligibility flags preserved.
5. **Read:** only the same dedicated authorized principal/audience/boot may
   consume the temporary review once over the reviewed HTTPS channel. No generic
   unauthenticated dashboard/read endpoint, cache or list/history API. Read checks
   TTL and revocation atomically with removal. A returned UI copy also needs a
   bounded lifetime and close/withdraw cleanup; server removal cannot erase it.
6. **Withdraw:** authenticated withdrawal invalidates outstanding nonce and any
   unread review immediately under the same lifecycle lock. Cancellation wins
   if processed before admission/read; an already disclosed copy cannot be
   recalled. Use a fixed acknowledgment without a name. Withdrawal cannot revive
   or extend a session. An uncertain withdrawal outcome must be reported honestly.
7. **Expire/stop:** proactive bounded-frequency purge, proposed at most one second
   after the 60-second deadline, plus checks on every operation. Exact deadline
   is expired (`now >= deadline`). Close/shutdown drops references. Restart gets
   a fresh boot epoch, no state rehydration and no acceptance of old nonces.
   Bound the spent-session/replay ledger in memory through its validity window;
   expired or unknown sessions cannot be recreated by submit. Multiworker state
   ownership and process routing need separate design proof before deployment.

**No retries after an ambiguous timeout**, for submit or consuming read. Do not
assume failure means no disclosure. Show a fixed uncertain-delivery message;
wait for expiry/verify withdrawal through a separately reviewed path, then require
fresh deliberate per-item consent for any later session. No retry queue,
idempotent name resubmission or background resync is authorized.

## Retention and residual risk

Proactive purge removes reachable application state, not all byte copies. Python
strings, allocator copies, UI buffers, TLS/proxy buffers, crash dumps, swap,
hibernation, VM snapshots, backups and telemetry can retain data. No zeroization
guarantee is made. Before real use, independently review OS crash/swap policies,
proxy buffering, backups and logging on both endpoints, and agree a bounded
retention/residual-risk statement. This slice does not change those policies.
No database, persistent receipt containing a name, replay-state rehydration or
backup inclusion is proposed. A crash/clock fault fails closed. Actual transport
needs lifecycle cleanup tests; synthetic object disposal cannot prove erasure.

## Acceptance, evidence and next approval gates

Draft PR #498 publishes the fictional gate, its unittest module, the
merged-status reconciliation and this PROPOSED protocol for code review.
No API registration, auth change, TLS configuration, secret provisioning,
private data, network or production effect is authorized by that publication.
The focused suite covers refusal, binding, revision restoration, exact deadline,
cancellation, sweep/close/restart, clock failure, concurrent one-use redemption,
redacted repr/errors and blocked I/O during synthetic import/lifecycle.

ChatGPT owns integration/handoff. Before real transfer, in order:

1. Independently review this proposal and the offline diff; resolve auth, server
   identity, sender-event authority, retention and multiworker ownership decisions
   in #431. Proposal acceptance is not implementation approval.
2. Obtain explicit scope approval for a separate secure implementation; develop
   dedicated bypass-free auth, reviewed HTTPS ingress, bounded parsing, nonce
   lifecycle, mounted sender event wiring, purge and private read/withdraw paths.
3. Run fictional end-to-end security acceptance on the actual approved topology:
   wrong cert/host; localhost/LAN bypass attempts; spoofed origin/CSRF/proxy/IDs;
   duplicates/oversize bodies; concurrent replay; event change-and-restore;
   timeout/no retry; restart; proactive expiry; withdrawal/read races; redacted
   logs across every hop. Audit crash/swap/backups and record residual risk.
4. Complete independent exact-diff security review and required CI; obtain
   explicit integration/merge and deployment/configuration approvals separately.
   Deployment must use the existing authorized release process. No approval is
   implied here, and no deployment or host mutation has occurred.
5. Operator verifies recipient and retention disclosure on the real PC, selects
   exactly one provisional artist and explicitly reconfirms that actual item.
   No remote-agent access to the private source or name is implied. Catalog,
   identity matching, persistence, ranking and device actions remain separately gated.

Resume from draft PR #498 and issue #431; recheck the exact head and CI before
integration. The three prior offline suites and the new suite are the bounded
regression target, with AST parsing and Git whitespace/scope checks.
Their success proves synthetic behavior only, not human consent, TLS, cleanup
of OS copies or live security.

Validation on 2026-11-05 in the approved Windows Sandbox, Python 3.13:
new gate suite **20 passed** (including fresh-import and extreme-TTL guards);
prior single-artist suite **40 passed**; prior rehearsal suite **20 passed**;
prior mounted Tk suite **5 passed**, no skips.
Each ran separately with `-B -m unittest discover -s tests -p <module> -q`.
Python AST parsing of both new Python files and `git diff --check` passed.
The original four-file publication is review-only; any corrective push and
merge need their own separate approval. No deployment is authorized.
