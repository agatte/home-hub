# Identity foundation for #287 — NOT LIVE

The identity core remains **unprovisioned** and is not an OS authority. The
November 14 source-only WebSocket cutover below now imports its fixed identity
contracts into `/ws` and startup, but installs no verifier, issuer or client
credential. This unmerged branch denies `/ws` before accept by default. HTTP
routes and legacy `backend/api/auth.py` are outside this cutover. Neither #287
nor #293 is operationally complete; no production migration is supplied.

`backend/identity_core.py` uses an explicitly supplied disposable SQLite path
and opaque administrative capability. It has no default production path, CLI,
HTTP enrollment, anonymous pairing, first-user bypass, or settings dump. The
embedding caller must establish OS-local authorization before handing the store
its capability. Object identity is only an in-process capability contract, **not
proof of OS provenance**: arbitrary trusted Python code can construct a store.
No such trusted local bootstrap/recovery adapter is implemented here. Do not
serialize the capability or mint it in response to loopback/private-IP requests.
Recovery has no unrevocation API; authorized enrollment creates a new principal.

Enrollment returns synthetic bearer material once to its caller, excluded from
the result repr. Never log/serialize that result into debug surfaces. Verifiers
use independent 32-byte salts and PBKDF2-HMAC-SHA256 with 600,000 iterations;
secrets contain 256 random bits. No plaintext verifier/token is persisted.
Credential lookup IDs and principal IDs are independently random. Credentials
have bounded lifetimes (maximum 366 days). Rotation caps all predecessors at
their existing expiry or the new overlap deadline, whichever is earlier;
maximum overlap is one hour, zero invalidates predecessors immediately.
Individual revocation and whole-principal revocation cover overlapping tokens.
Principal revocation is irreversible through this API.

The finite inventory in `identity_policy.py` represents exact HTTP actions and
one WebSocket event subscription. It is deliberately incomplete: omitted
operations deny, including every guest-gateway operation for now. Fixed profiles
are owner browser, kiosk, Windows desktop, Desktop Notifier, MCP, Latitude,
guest gateway, Alexa, limited Shortcuts, and local operator/lifecycle. No runtime
role editing or IAM is introduced. Owner is not a wildcard administrator.
The Windows principal has one credential for six supervised lanes: activity,
audio, screen, camera, display, sleep. Health is allowed for each; action grants
are lane-specific. These are policy labels, not process isolation: possession
of the shared desktop credential permits all its granted lanes.

Future adapters must select operation and lane from owned server code and derive
source from the returned identity. Never bind operation/lane to caller fields.
An optional caller source assertion can only deny a mismatch; it cannot confer
authority. Private addresses have no meaning here. Identity authenticates a
producer; it does not establish physical sensing trust/freshness, YOLO person
authority, room location, house state, or actuator ownership. Existing lighting
and lifecycle apply chokepoints remain required.

SQLite mutations use `BEGIN IMMEDIATE`, foreign keys, and FULL synchronous
commits. Enrollment and rotation roll back together on failure. Authorization
first reads a joined credential/principal snapshot with a finalized cursor and
no explicit transaction. It cheaply denies ineligible records, then performs
PBKDF2 outside database locks. Only verified candidates enter a short
`BEGIN IMMEDIATE`: the complete record must still match, and current expiry,
fixed profile grants, exact server operation/lane and source are checked again.
Any observed record change denies this attempt, even an expiry shortening that
has not yet expired. Policy values are immutable and compared across phases.
No second hash runs under the reservation. Enrollment/rotation hashing still
occurs inside their atomic administrative transactions; this slice changes
only authorization.

A competing writer can leave the first read seeing the old committed record;
the final reservation must wait for that writer or raise a SQLite lock error,
never grant from the stale read. SQLite's existing default busy timeout applies
(five seconds); callers must treat database errors as denial/unavailability and
may retry a whole authorization with bounded abuse limits. An exclusive writer
can also block the initial read. This differs from authorization itself holding
a lock during expensive hashing. Connections remain synchronous and thread-affine;
authorization refuses a caller-owned transaction rather than hashing under its
locks. Decisions are point-in-time at the final check, not future permission:
revocation may occur immediately after commit/before the caller uses the result.
Future adapters must revalidate each action and own session termination rules.

No schema revision counter is added: exact values detect changes visible at the
second read, not a malicious change-and-restore (ABA) between reads. Supported
revocation is irreversible and rotation never extends predecessor expiry, so
those administrative transitions cannot restore the original snapshot. Arbitrary
DB writers and mutable policy replacement are outside the trusted API contract;
OS isolation and the recovery design below must address that boundary. OS clock
accuracy/rollback, DB integrity/permissions, backup consistency, and filesystem
durability remain external trust requirements. This module does not provide rate
limiting or constant-time existence hiding; only verifier comparison uses constant
time. Whole-database rollback remains possible in the current implementation.

## Activation and integration gates

- Remaining #287: owned OS-local bootstrap/recovery capability issuance,
  deployment-specific storage permissions, complete reviewed endpoint/action
  inventory, legitimate-client enrollment and rotation delivery, secret-safe
  transport, abuse limits, operational recovery and failure handling. Bind each
  source/lane through owned adapters and preserve additive rollout before enforcement.
- **Restore/revocation blocker:** an entire DB backup can resurrect revoked
  verifiers. A revision in the same DB cannot detect this. The synthetic restore
  test demonstrates that limitation intentionally. Before any live adoption,
  implement and review an external non-rollback trust anchor/revocation epoch
  protocol, or an explicitly authorized restore procedure that invalidates every
  restored credential and requires fresh enrollment before serving requests.
  Include atomicity/crash recovery and older-backup detection; no prevention is
  claimed by this slice. Never silently use a restored registry live.
- #293: authenticate the WebSocket handshake, map subscriptions/messages to
  reviewed operation identifiers, filter outbound events per profile, revalidate
  revocation/expiry during long sessions, terminate revoked sessions, and prevent
  source/lane spoofing. `WS /ws:mode_update` is only an offline policy proposal;
  it does not filter or secure the current `/ws` stream.
- Browser/native/gateway migrations (#288–#292) and enforcement need their own
  client compatibility and rollout gates. Existing LAN/loopback/shared-key auth
  remains unchanged. No route wiring or production rollout is authorized here.

## OS-local recovery and restore protection - DESIGN ONLY

**Current phase-1 architecture proposal:** see
[`SECURITY_RECOVERY_DECISION_287.md`](SECURITY_RECOVERY_DECISION_287.md).
It narrows the first deployment boundary to an isolated system broker with
protected registry and independent software journal, **not** immediate TPM
installation. Root/whole-system rollback remains outside this first boundary.
Every intentional identity-registry restore requires full credential
invalidation and fresh operator enrollment; generic one-use pairing is deferred
until recipient authentication exists. The more demanding hardware-backed
option below remains a future alternative, **not** the selected first step.
**The following older pairing/Windows-broker details, restore protocol and
acceptance matrix apply only to the deferred higher-assurance alternative.
The phase-1 restore and recipient-authentication rules in the linked decision
take precedence.** In particular, no identity backup (even one labeled
current) may resume using previously issued credentials after an intentional
phase-1 identity-registry restore.

Nothing in this section is implemented: no handler, privileged service/socket,
pairing UI, anchor/key provisioning, migration, or live enforcement is supplied.
The current store does **not** prevent restored revocations from resurrecting.
The following is a recommended protocol for a separately reviewed activation gate.

### Authority and pairing

On Latitude, propose a narrowly scoped privileged identity broker under a
separate OS account, with root-owned executable/configuration and registry/anchor
access denied to the backend service account. Operators invoke a local terminal
command through explicit sudo/polkit authorization for a fixed action inventory
(enroll fixed profile, revoke, restore, inspect non-secret status). If local IPC
is later needed, use a permission-restricted Unix socket and kernel peer identity;
loopback addresses, headers and supplied usernames are never authorization.
On Windows, propose an elevated, administrator-owned recovery tool/broker with
restricted ACLs and OS-authenticated local IPC (e.g. a local-only named pipe with
remote access rejected and verified client token). UAC elevation, executable
integrity, and the actual operator identity must be checked; membership asserted
by the client is insufficient. Windows client recovery does not gain Latitude
registry administration merely by running on Windows: authoritative enrollment
requires separately authorized Latitude-local operator action.

A same-user process can generally inspect/inject into another process or edit
its files; opaque Python objects, file permissions shared with the backend user,
and user-scoped DPAPI alone cannot protect this boundary. Recommend moving
verifier validation and all registry mutations into the broker: the backend gets
only bounded authorization decisions, never raw anchor keys or unrestricted
registry writes. A compromised backend can still bypass its own action checks;
protecting actuators from that requires independent enforcement at the actuator
boundary and is outside this identity slice. Root/Administrator, kernel,
firmware/TPM compromise, physical tampering and an operator knowingly approving
malicious actions are explicit trust limits. Do not claim same-user isolation
without separate accounts, protected code, and enforcement outside that user.

Pairing is explicitly operator initiated, limited to one reviewed fixed profile
and recipient, and cannot request grants/source/lane beyond that profile. Propose
a high-entropy one-use ticket valid for at most five minutes, with a broker-held
verifier, target binding, deployment generation and monotonic deadline. Permit
at most five redemption attempts per ticket and bounded per-operator/global
issuance; invalidate on expiry, use, restart, restore or generation change.
Consume the ticket and enroll atomically; do not return bearer material before
commit. A lost response burns the ticket: revoke the uncertain enrollment and
issue another, rather than replaying secret delivery. Only trusted local IPC
may redeem it in this proposal. For remote clients use separately authenticated,
operator-approved provisioning/delivery, not an unauthenticated network pairing
endpoint. Keep tickets and issued tokens out of logs, command lines, clipboard
history and status output; return them once through an owned secure channel.

### External anchor and crash-safe mutation

Recommend an external hardware-backed monotonic generation/epoch plus a
non-exportable key, outside all registry backups and inaccessible to backend
users. A TPM-backed broker is a candidate, not a claim that current hardware
supports the required atomic monotonic storage. An external independently
administered authority is an alternative. A second ordinary file, same-disk
journal, key encryption, signature, or counter in the DB detects corruption but
cannot alone prevent restoring the file/key/counter together. Platform support,
TPM endurance, recovery custody and durable atomic anchor updates require a
prototype and review before selecting either mechanism.

The anchor must bind deployment ID, generation, protocol/minimum code version,
committed epoch and authenticated registry security-state digest. Pairing state
and every security-relevant credential/profile/revocation change participate.
Bind exact canonical state, not merely an epoch field: otherwise an older DB
could be relabeled with a newer counter. All authentication and administration
pass through one broker gate. Proposed two-resource protocol:

1. Acquire exclusive broker lifecycle/mutation gate; drain authorization decisions
   and suspend new ones. Verify DB security state matches the committed anchor.
   Compute the proposed next state and digest in a transaction; do not expose
   new tokens or acknowledge successful revocation yet.
2. Atomically and durably advance the external anchor to a **pending** record
   containing old committed state and new epoch/digest. A pending record always
   disables authorization, including after reboot. If this cannot be persisted,
   roll back DB work and remain on the verified old state; uncertain persistence
   means quarantine, not fallback.
3. Commit the DB next state with FULL durability and protocol metadata. Atomically
   finalize the anchor to that exact new committed epoch/digest. Recheck both
   resources, release the gate and only then acknowledge or deliver secrets.
   A revocation is not reported successful until both resources are durable.
4. On restart, pending + exact new DB state may finalize through a bounded trusted
   recovery path. Pending + old, absent, corrupt or different DB state must stay
   quarantined; never revert the advanced anchor to enable the old credentials.
   Require explicit operator recovery/full re-enrollment. If DB commit succeeded
   but acknowledgement was lost, status can report the non-secret committed
   action ID; enrollment secrets are never replayed.

No atomic transaction spans SQLite and the anchor. The pending deny state is
what makes the gap safe, at the cost of availability and possible re-enrollment.
Anchor APIs must themselves support atomic durable pending/final transitions;
torn records, unavailable hardware, failed fsync or uncertain completion deny.
Digest verification and broker ownership must cover startup and every decision;
no long-lived backend cache may bypass the gate. Runtime file replacement and
out-of-band DB writes are denied by ownership and treated as tampering. A digest
computed only once at boot is insufficient if such writes remain possible.

### Backup, restore and recovery lifecycle

Take backups only through the broker's quiescence gate, after draining mutations
and verifying a committed anchor. Use SQLite's consistent backup facility rather
than copying an active DB/WAL; record deployment/generation/epoch, protocol
version, digest and non-secret operator audit evidence. Protect backup verifier
material as credentials. Never restore/clone the external anchor from a DB
backup. Backup availability does not grant restore authority.

Restore requires explicit OS-local operator authorization naming the backup and
expected identity-loss impact, with serving stopped at the broker gate. Validate
format, integrity and anchor binding before reopening. An exact current backup
may resume only if the complete security state matches the external anchor;
older, different-generation, unbound or uncertain backups remain quarantined.
Never silently accept older revocations. Recommended older-backup recovery is
full re-enrollment: preserve the backup as offline evidence, advance the anchor
into a new deployment generation/key binding with an empty credential registry,
use the same pending/commit/final protocol, invalidate all restored credentials
and tickets, and enroll fresh principals through local operator actions. Restored
non-identity application data must not import old credentials into the new
registry. Do not clear the anchor or reduce its epoch to make a backup fit.

Loss/reset/replacement of the anchor is an incident, not first-user bootstrap.
Deny all restored credentials; require physical/local authorized recovery and
independently protected operator evidence to establish a new generation and
fresh enrollment. If that authority/evidence is unavailable, remain offline.
Planned machine replacement also requires explicit authority and generation
separation; never clone a serving identity authority. Refuse older code/protocol
that cannot validate the anchor's minimum version. OS boot/code integrity or an
independent broker must enforce this: an old backend able to skip the broker
would defeat an application-only downgrade check.

Alternatives: an external authority avoids local TPM lifecycle constraints but
adds availability/administration dependencies; TPM anchoring permits offline
operation but needs platform-specific durability, wear and reset handling.
Always invalidating every credential on any restore is simpler operationally,
but still needs an independently enforced restore gate and protected generation
anchor to prevent covert restore or downgrade. A revocation-only external log
could retain unaffected enrollments but introduces authenticated replay,
compaction and atomicity complexity; defer it. Recommend fail-closed full
re-enrollment rather than automatic reconciliation of ambiguous states.

### Acceptance matrix for the future protocol

These are future tests, not claims about the current implementation. Use only
synthetic registries/anchors; include broker isolation and hardware-specific
power-loss validation before live activation.

| Sequence / failure | Required outcome |
| --- | --- |
| Backend/same-user process tries admin IPC or DB/key access | OS denies; no capability minted from loopback or client fields |
| Local authorized operator pairs a fixed profile | One bounded enrollment; exact grants/source; secret delivered once |
| Ticket replay, wrong recipient/profile, expiry, attempt limit, clock rollback | Deny; monotonic deadline; no reset of budget on restart |
| Concurrent ticket redemption or revoke/enroll | Single commit order; no duplicate use or stale authorization |
| Backup E, revoke at E+1, restore backup E | Quarantine; revoked token denied; explicit fresh generation required |
| Restore exact committed state | Resume only after anchor/digest/protocol verification |
| Crash before pending anchor persistence | Verified old state only; uncertain write quarantines |
| Power loss after pending, before/during DB commit | Deny on restart; old/torn DB never silently resumes |
| DB committed, power loss before anchor finalization | Exact pending/new digest may finalize; any mismatch quarantines |
| Finalization durable, crash before response | Revoke remains effective; lost enrollment delivery never replays secret |
| Anchor missing/reset, DB missing/corrupt, digest mismatch | Deny; authorized incident recovery and full re-enrollment |
| Full re-enrollment fails at each write boundary | Pending quarantine until verified new empty generation; old tokens deny |
| Older executable, copied DB with forged epoch, cloned authority | Reject via protected minimum version and deployment/digest binding |
| Backup during rotation/revoke or active WAL writes | Owned quiescence gives consistent committed snapshot or refuses |
| Root/admin or actuator backend compromise | Explicit trust-limit evidence; no claim identity alone contains it |

Open activation gates: choose and prove anchor atomicity/durability on owned
hardware; define operator recovery custody and code-integrity enforcement;
review broker account/IPC isolation and complete grant inventory. No live
provisioning or irreversible hardware writes are authorized by this design.

## Offline WebSocket manual-command operation matrix (#293 / #461; NOT LIVE)

The existing `backend/identity_policy.py` inventory now proposes two exact,
**inbound** operations: `WS /ws:light_command` and
`WS /ws:sonos_command`. The pure `ws_command_operation` selector maps
only precisely spelled current message kinds to these IDs; malformed,
nested, unknown or alternate names return no operation. There is no URL
prefix matching, dynamic role, generic wildcard or caller-chosen source.

The fixed profile matrix grants these commands only to the **owner_browser**
principal on server-bound `browser` lane and **kiosk** principal on
server-bound `display` lane. Windows Supervisor (including its six shared
credential lanes), Desktop Notifier, MCP, Latitude, guest gateway, Alexa,
Shortcuts and local operator have **no** WebSocket light or Sonos command
grant. The original `WS /ws:mode_update` subscription grants remain
unchanged. The independent reviewed-grant snapshot is updated deliberately.

Synthetic tests of `IdentityStore.authorize` exercise approved owner/kiosk
lanes, wrong lanes, foreign source assertions, known non-owner profiles,
unknown operation names, revocation and expiry. The server adapter in
future #293 must derive operation and lane from **authenticated** principal
and owned code, not `source`/device/lane values in a JSON frame or
headers. Identity authorizes client intent; it never replaces Hue
LightingAuthority, scene/ScreenSync/transit/manual ownership, Sonos audio
ownership, source freshness or physical evidence.

**Not implemented or authorized here:** This offline inventory is NOT
imported by `backend/main.py:/ws`. No WebSocket auth, session cookie,
Origin/Host enforcement, native-client credential provisioning, initial
snapshot projection, broadcast filtering, revocation of connected sockets,
rate/resource budgets or production rollout is performed. The current
anonymous WebSocket is **still unsafe**. The final #293 implementation
requires reviewed pre-accept verification and filtered outbound streams,
plus separate owner/kiosk/iPhone and native client compatibility trials.
There is no token in browser source code or URL, no new endpoint, and no
live credential change.

This addition only prepares the command authorization seam needed by
the guarded lighting controls in #461/#530. It must not be merged or
activated as a security fix on its own; #287, #293 and #284 remain open
until their respective full original acceptance criteria are met.


## #293 authenticated runtime source cutover

November 14, 2026.

**Current source evidence in this section supersedes the older offline-only
WS statements above.** Local uncommitted target:
`C:/Work/home-hub-project/worktrees/ws-cutover-293-20261114`, branch
`work/293-ws-cutover-20261114`, base
`1f5d296e2c8f0504b8718ceedfaba89b1a961b8a`. The 52-file synthetic seed was
preserved, with bounded additional engineering in this target only. This is
**source-ready for synthetic injection, NOT deployable, installed, live,
merged, physically accepted or complete security enforcement**. Production
remains unchanged because the branch is unmerged. No source A/B/C or original
synthetic worktree was modified. Network issue reads were prohibited; acceptance
here uses the owner's supplied #287/#293 contract and local source evidence.

### Single socket owner and startup contract

`backend/main.py:/ws` now delegates exclusively to `WebSocketManager.serve`.
The manager has no legacy `connect`, raw connection set, accept or raw broadcast
implementation. Every existing producer still calls the same `broadcast` API,
which reaches `AuthenticatedBoundary` and its per-principal projection. Unknown
events deny, including for owner. Initial and private frames take the same
projection and fresh authorization path. Private receipts, reconciliation and
errors categorically cannot be broadcast.

`bootstrap.lifespan` accepts only explicitly supplied trusted application state
`ws_runtime_configuration: WebSocketRuntimeConfiguration`. Its fields are a
`TrustedAsyncAuthorizer`, exact `Endpoint` tuple and default-false
`browser_issuer_ready`. Nothing in this branch populates that state, reads a
credential file, opens broker IPC, creates an IdentityStore, issues cookies,
exposes a configuration route or obtains same-process broker authority. Missing
configuration rejects with close 1008 **before accept or snapshot evaluation**.
A synchronous verifier is refused. This seam is application composition, not
proof of OS isolation or a deployed verifier protocol.

Browser/kiosk admission requires exact owned HTTPS origin, exact Host, ASGI
`wss` scheme and `__Host-homehub_ws` cookie. Native admission requires the exact
HTTPS endpoint, `wss`, Authorization bearer and no Origin/cookie. Query strings,
subprotocol credentials, duplicate headers, Forwarded and x-forwarded-* deny.
No request-derived endpoint, loopback/LAN exception, assume-HTTPS flag or proxy
header normalization exists. TLS-terminating proxy scope normalization requires
separate owned ASGI review; do not enable forwarded-header trust as a workaround.
The HTTP numeric-loopback kiosk configuration still cannot admit Secure cookies.

Authorization has independent bounded admission/active capacity, bounded work
retained until an expired/canceled verifier really finishes, no grant cache and
fixed operation/lane/source checks. There are at most 16 sessions by default,
8 pending send callers per socket, 4096 input characters, 16384 serialized output
characters, four inbound commands/second, eight admission attempts/second and
bounded per-socket I/O. Authorization serializes per session; broadcast fanout
is bounded by the session inventory. Excess pending sends deny without raw
fallback. A slow client cannot hold another client's send. Session removal
clears its bearer reference and cancels owned transport/dispatch work; post-await
session checks and task-start checks prevent a closed session from resuming a
queued send or command. Idle and dispatch-time watchdogs recheck at five seconds
by default. Revocation is fresh point-in-time authorization, not an instantaneous
network recall: bytes already sent cannot be recalled, and a write already
started under the existing actuator transaction may have to settle.

### Fixed producer, snapshot and consumer inventory

A source AST inventory found these 25 literal producer event kinds; all known
broadcast call sites use the shared manager. Dynamic manager forwarding does
not add an event grant. The tables pin the currently supported contracts rather
than imply arbitrary future emitters are safe.

| Event(s) | Existing producer(s) | Runtime delivery |
| --- | --- | --- |
| light_update | Hue poll/v2 stream, guest/scenes routes, personality vibe router | owner/browser and kiosk/display only |
| mode_update | AutomationEngine and initial memory snapshot | owner/kiosk; Windows display gets mode/time_period only |
| sonos_update | Sonos poll | owner/kiosk only |
| ambient_update | AmbientSoundService and initial memory snapshot | owner/kiosk, bounded status fields only |
| dnd_update | DNDManager | owner/kiosk only |
| music_suggestion, music_auto_played | MusicMapper | owner/kiosk, title/mode/status text only |
| mode_suggestion, mode_suggestion_dismissed | RuleEngineService | owner/kiosk only |
| brightness_suggestion, brightness_suggestion_dismissed | RuleEngineService | owner/kiosk, fixed single-fixture payload only |
| camera_update | CameraService | owner/kiosk, explicit status fields only |
| gameday_state, gameday_play | GameDayService | owner/kiosk, nested fixed game/play/drive fields |
| gameday_viewer_state, gameday_viewer_sync | GameDayViewerSync | owner/kiosk, fixed game/viewer-clock fields |
| gameday_celebration | CelebrationOrchestrator | owner/kiosk, sequence_key/started_at only |
| notification | NotifierService, CameraService watchdog | Desktop Notifier only; text/factors; actions always empty |
| champion_color | LoLChampionService | DENIED: no reviewed visual event contract |
| ml_decision | MLDecisionLogger | DENIED: arbitrary factors/private inputs |
| ml_prediction | AutomationEngine | DENIED: prediction/private diagnostics contract absent |
| music_auto_play_failed | MusicMapper | DENIED: failure-detail contract absent |
| music_weather_suggestion | MusicMapper | DENIED: weather/suggestion contract absent |
| pipeline_state | PipelineBroadcaster | DENIED: arbitrary fusion/process/physical inputs |
| scene_failed | AutomationEngine | DENIED: failure/scene-detail contract absent |

Additional route-only frames are `connection_status`, private
`light_command_result`, private `light_command_reconciliation` and bounded
`error`. The old initial `presence_update` is **not evaluated or sent**: raw
presence has no safe scoped contract. The old `rate_limit` event is retired;
over-budget inbound sessions close instead. No initial device reads occur;
L1-L6/Sonos observations still arrive from existing REST priming and producers.

Critical wire allowlists (all unknown keys, including nested keys, are stripped;
a malformed allowed field denies its event):

| Contract | Allowed fields |
| --- | --- |
| Home fixture | light_id (exact 1-6), name, on, bri, hue, sat, ct, colormode, reachable |
| Owner/kiosk mode | mode, time_period, source, manual_override, house_state, activity, override_source, override_user_owned |
| Connection status | hue, sonos, build_id, request_id, light_command_results |
| Sonos | state, track, artist, album, volume, mute, duration, position |
| Game | status, opponent, kickoff_utc, score_colts, score_opp, quarter, clock, possession, last_play, current_drive |
| Nested play | timestamp, play_type, description, player, kicker, yards, scoring_team, wpa |
| Nested drive | team, plays, yards, elapsed |
| Viewer clock | enabled, active, authoritative, presentation_active, reason, service, player, playback_status, media_timestamp, observed_at, sample_age_seconds, lag_seconds, normal_streak, seek_generation, last_seek_direction, program_time_offset_seconds |
| Celebration | sequence_key, started_at |
| Desktop brightness | mode, time_period (only windows_desktop/display) |
| Notifier | title, subtitle, kind, output_delta; up to six factors containing label/value; actions=[] |
| Private light result | command_id, light_id when valid, status (acknowledged/denied/unavailable/invalid/uncertain) |
| Private reconciliation | command_id, light_id; never raw observation |

Remaining exact DND, music/rule, camera and ambient scalar allowlists and their
range/length checks live in `_OWNER_EVENTS` in
`backend/services/ws_authenticated_boundary.py`; `_fields` recursively projects
nested game and brightness objects. No key is accepted by prefix or wildcard.
Sonos `art_url` and raw `error` text, ambient `sound_url`, sound inventory and
mode/configuration maps, rule room/bulk brightness payloads and notifier action
URLs remain denied. These are **known compatibility losses**, not complete
feature parity. In particular pipeline diagnostics stop updating, artwork is
absent from WS snapshots, ambient settings fields can be absent after status
replacement, room-scoped suggestions may lack their payload, notifier buttons
are unavailable, and failures/champion/weather suggestions are not delivered.
A safe owned contract or explicit feature removal is needed before release.

Actual consumers checked: `frontend-svelte/src/lib/stores/init.js` and its
lighting/automation/Sonos/ambient/camera/pipeline/rule stores; isolated
`stores/gameday.js` uses a second HubSocket and the five Game Day kinds;
`pc_agent/monitor_brightness.py` consumes mode/time_period;
`pc_agent/desktop_notifier.py` consumes notification and previously executable
actions. `pc_agent/sleep_watcher.py` polls HTTP, not this WS display lane.
`frontend-svelte/src/lib/ws.js` still uses same-origin new WebSocket(url):
pre-accept denial never triggers onopen, so it retains disconnected/unavailable
UX. No Authorization-in-browser workaround, JS credential or URL token was
added. Native WS client source migration is described below; operational authentication remains unconfigured.

### Commands, receipts and actuator limits

Exact strict commands select `WS /ws:light_command` or
`WS /ws:sonos_command`; only owner/browser and kiosk/display have those grants.
Client lane/source/role fields and mixed CT/HSB deny. The protected dispatcher
passes validated light data to the existing `_handle_light_command` and
`dispatch_manual_light`, preserving `LightingTransitionBoundary`, immutable
queued authority, final Hue fence, manual persistence and uncertain cache
reconciliation. Sonos requires audio ownership to exist, then uses the existing
manual-intent revision and `run_manual` safeguards. No direct runtime fallback
writes if audio ownership is missing.

The dispatcher returns at most two private events; it receives no socket. Each
receipt reauthorizes and projects separately. Capability is advertised only
when the protected dispatcher exists. Safe invalid command correlation can be
returned without echoing validation payloads. ACK remains bridge transport plus
durable manual-owner state, never physical completion. Reconciliation contains
only fixture/correlation IDs and requests the existing client-side version-fenced
read; no server GET or stale/private observation is sent. Command cancellation,
disconnect, expiry or revocation never fabricates an ACK or retries a write.
Already-started shielded actuator transactions retain their established
settle/ownership cleanup semantics, and may finish after socket close; identity
is point-in-time intent permission, not a revocable physical write lease.

### Remaining gates and next safe step

The selected separate OS broker, protected registry, independently managed
rollback journal, OS-authorized enrollment/recovery and downgrade floor from
`SECURITY_RECOVERY_DECISION_287.md` are **not installed**. Its synthetic broker
and Linux socket prototype remain test fixtures and are not imported at runtime.
A typed injection-only verify-client contract now exists in the second source
milestone below. The existing synthetic broker and Linux socket demo use
different protocols and cannot serve it. No protected connector, production
broker or secure issuer implementation exists.

Next gate: independently review the read-only broker and issuer source contracts
below, then separately authorize operational
broker installation and secure browser/iPhone/kiosk session delivery. Prove
kiosk TLS, owned proxy scope, CSRF/session lifecycle, expiry/revocation/rotation,
native secret delivery and client migrations, omitted event contracts, rollback
floor and credential-loss recovery. HTTP/API/guest trust migration remains
separate; this WS change does not secure those routes. Follow with exact-head
CI and proportionate independent security/ownership review, separately approved
high-risk integration/publication, Latitude deployment via the release procedure,
#296 fixture evidence and witnessed L1-L6/kiosk/iPhone acceptance. No host setup,
credential delivery, physical action or retirement is authorized by this source
work. Do not release this branch with its default disconnected clients.


### Offline validation of this source integration

- Combined scoped run: **669 passed, 32 subtests passed, zero failures**
  (194.37s). This includes the original 626 identity/projection/guard/Hue/lighting
  selection plus 40 route tests, two authenticated tracing tests and the real
  projected Game Day JSON boundary test.
- Final affected route/concurrency suite: **41/41 passed** (21.87s), including
  the additional regression proving a transport-raised cancellation cannot
  terminate its broadcast producer. This test was added after broad collection;
  the 669 count does not include that additional case. It is not a second full
  combined 670-test run.
- Final existing cancellation/timeout/idle/resource regression selection:
  **14 passed, 176 deselected** (15.37s) against the final boundary.
- Existing dependency-free frontend suites: **58/58 passed**, no failures,
  skips or frontend source changes. Covered actual LightCard handlers, command
  tracking, private receipts, observed-state fencing and redesigned/classic Home.
  No node_modules exists in this target; full frontend CI/build/browser trials
  were not run and no dependency was installed or copied.
- Ruff `check --no-cache`, tracked `git diff --check` and explicit UTF-8,
  whitespace/conflict-marker checks on all 13 incremental paths passed.

Python used `C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B`,
`APP_ENV=testing`, `PYTHONDONTWRITEBYTECODE=1`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `-p pytest_asyncio.plugin` and
`-p no:cacheprovider`. Only a pre-existing Starlette/httpx deprecation warning
was emitted; no dependency update was attempted. Tests never run the application
lifespan or use production stores, credentials, brokers, sockets or Hue/Sonos.
The target has no .env file (existence checked without reading secret contents).
All evidence is local and uncommitted, not hosted CI, deployment, live health,
kiosk/iPhone witness or physical acceptance.

### November 14 second source milestone: inactive broker and browser issuance

Local, uncommitted work in `identity-287-broker-session-20261114` on
`work/287-broker-session-contract-20261114`, base
`1f5d296e2c8f0504b8718ceedfaba89b1a961b8a`. This extends the seeded cutover;
it does not activate it, satisfy #287/#293, or complete #461 UI acceptance.
No network/GitHub refresh was authorized for this offline task; November 14
issue acceptance is supplied by the task brief, not independently fetched here.

`backend/services/identity_broker_verify_client.py` implements a typed,
verify-only `ProtectedVerifyIO.exchange_verify(bytes) -> bytes` contract and
`VerifyClient.authorize` returning exactly `Identity` or `None`. Its
`authorizer()` reuses `TrustedAsyncAuthorizer` without changing runtime defaults.
There is no connector, environment switch, IdentityStore verifier, generic RPC,
admin method, service or installation. Any real broker must separately implement
this protocol; the Linux prototype's generic verify result is never AuthN.

Wire v1 uses one connection and one request/response, four-byte unsigned
big-endian body length (1..2048), ASCII JSON object, exact frame termination
and no extra bytes. No duplicate keys, nonfinite JSON, malformed, truncated,
unknown-version or surplus fields are accepted. `read_frame` bounds body reads
before allocation; the future I/O adapter must own exact EOF checking, deadline,
peer proof and connection cleanup. No retry, pool, cache or loopback fallback.

Exact request keys: `version` (integer 1), `method` (`verify`), `nonce` (fresh
32 lowercase hex), `token` (opaque `32hex.43urlsafe` verifier input), `operation`,
`lane`, `generation` (32 lowercase hex), `revision` (integer 0..2^53-1).
Operation/lane/stage are server-owned, checked against immutable `PROFILES`;
no client profile/source argument can select privileges. Stage is local capacity
selection, never a broker/admin operation. Credentials never enter command-line
arguments, logs, URLs or cookies through this client.

Every response has exactly `version`, correlated `nonce`, `status`, `generation`,
`revision`. Denial statuses are `denied`, `revoked`, `expired`, `quarantined`,
`unavailable`, `error`, with no identity or credential fields. `verified` requires
exactly these additional fields: `principal_id` (32 lowercase hex), `profile`,
`source`, `lane`, `operation`, `kind`, `expires_at` (finite Unix seconds).
Kind must be `browser_session` for owner_browser/kiosk and `native_bearer` for
other profiles. Source and grants must exactly match immutable policy; operation
and lane must echo the server request. No token/verifier is ever returned.
Unknown statuses and every failure collapse to `None`; parser errors have fixed
text and no sensitive exception cause/context. Adapter exceptions are consumed
without logging or propagation.

Trusted nonblocking `generation()` and `revision()` observers must supply CURRENT
protected broker state, not static config, HTTP input, app DB state or values
learned from the response being checked. Revision advances on every security
mutation, generation changes on restore; both are checked before and after I/O.
A delayed pre-revocation/rotation response cannot cross an observed revision
change. A real protected observer and its freshness/linearization protocol are
**unimplemented operational dependencies**; these callbacks are injection seams,
not independent OS proof. Read skew denies. Broker verification must serialize
with mutation, independently validate its journal/downgrade floor, and bind
credentials to current generation. Responses expire at consumption time; every
WS use revalidates, without caching grants. Authorization is point-in-time:
mutation after the final check cannot undo an actuator transaction already
started under the existing ownership fences.

The client reserves one admission slot and a separately configurable 1..64 active
slots, with a 0..5 second (exclusive zero) whole exchange budget. Timeouts/caller
cancellation discard authorization, retaining physical work capacity until actual
completion. A stalled or cancellation-suppressing adapter can exhaust its bounded
slots but cannot create late grants. A future adapter must guarantee bounded
cleanup; no abandoned executor or unbounded queue is provided.

For real AF_UNIX I/O, a reviewed Linux connector must verify the exact
root-controlled socket path, trusted ancestors, socket type/owner/mode/group,
ACL/MAC custody, peer SO_PEERCRED dedicated broker identity and replacement-race
handling. Broker must also authenticate permitted backend peers. Same UID is
never operator authority. Windows tests cannot establish Linux proof. This
milestone deliberately provides **no actual connection implementation**.

`backend/services/browser_session_issuance.py` defines a separate
`PrivilegedBrowserIssuer.issue_browser_session(IssuanceRequest, *,
operator_action, recipient_evidence, csrf_evidence) -> bytes` seam. Request fields
are nonce, server-fixed owner_browser/kiosk profile, exact HTTPS origin,
recipient_id, generation and issue/rotate action. Non-null opaque evidence is
necessary but NEVER sufficient: only a future privileged issuer may authenticate
fresh OS-authorized explicit operator action, particular recipient and
session-bound CSRF evidence. Booleans are refused. No HTTP header, IP, first
caller, same UID, local pairing or synthetic signature constitutes proof.

Issuer responses use the same bounded frame codec with exactly version, nonce,
status=`issued`, profile, origin, recipient_id, generation,
kind=`browser_session`, token and expires_at. All request bindings are checked,
as is current generation; expiry must allow 1..3600 seconds of remaining life.
Raw native credentials cannot satisfy this kind contract. The protected issuer
owns independent random session minting, one-way verifier storage, expiry,
revocation, persistence and generation, outside the HomeHub DB. Nothing here
mints a token. Issuer receives no authority to use the verify-only endpoint for
mutation.

The necessary delivery checks require exact Host and Origin, HTTPS, same-origin
POST, empty query, no duplicate or forwarded headers. They do NOT establish
recipient or OS authentication. Only a verified result produces CookieDelivery,
whose sole delivery method returns a Set-Cookie header, never token JSON or a
JS accessor. Exact format: `__Host-homehub_ws=<session>; Secure; HttpOnly;
SameSite=Strict; Path=/; Max-Age=<1..3600>`, no Domain; age rounds down. Future
HTTP delivery must have an empty no-store response and separately authenticated
recipient/TLS provenance and CSRF; no route exists now. Plaintext loopback kiosk
issuance is refused. Cookie attributes cannot be proven by a WS request.

Rotate must durably revoke old sessions before acknowledging new delivery with
zero overlap. Logout must durably revoke at the privileged broker before clearing
its cookie; clearing alone is not revocation. Restore must change generation and
invalidate sessions before serving. Uncertain delivery/cancellation requires
privileged reconciliation and revocation of the minted session before another
issuance; never blindly retry. The future issuance owner must bound admission,
I/O deadlines and cleanup. This pure orchestration does not spawn a timed-out
issuer task or claim to reconcile cancellation. None of these operational
lifecycle duties is implemented by a fake issuer.

Synthetic tests exercise framing/partial reads, nonce replay, response and
identity forgery, denied/revoked/expired/error states, revision/generation races,
timeouts/cancellation/capacity, WebSocketManager projection and revocation,
issuer prerequisites, exact cookies and Origin/Host/TLS/CSRF rejection. Fixture
object identity is only simulated authority. Existing real ASGI tests cover
unconfigured /ws closing 1008 before accept and no snapshot/fallback.

Release remains blocked by independent source security review, real protected
broker/state observer/connector/issuer, protected storage+journal durability and
rollback floor, authenticated operator and recipient delivery, CSRF and secure
kiosk/iPhone TLS, bounded delivery reconciliation/logout/rotation, native secret
provisioning and client migrations, omitted projection contracts, HTTP/guest
trust migration, separately authorized integration and deploy, #296 fixture
identity, and witnessed #461 guarded L1-L6/kiosk/iPhone acceptance. Identity is
never lighting ownership; manual/ScreenSync/final-owner fences remain mandatory.

#### Second milestone verification and exact local delta

- Combined offline run: **639 passed** in 160.93s across
  `test_identity_broker_verify_client`, `test_browser_session_issuance`,
  `test_identity_foundation`, `test_identity_broker_protocol`,
  `test_ws_authenticated_boundary`, `test_ws_identity_policy_proposal`,
  `test_ws_native_projection`, and `test_websocket`.
- Final new-contract run after adding three lifecycle/ASGI cases:
  **122 passed** in 24.42s. This includes an issued-cookie handshake through
  the actual ASGI /ws route, protected-verifier injection, profile projection,
  revoked-cookie preaccept denial, issuer replay and secret-error suppression.
  Counts overlap; no final combined 642-test run is claimed.
- Existing Python from `main/.venv/Scripts/python.exe -B`, APP_ENV=testing,
  PYTHONDONTWRITEBYTECODE=1, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1,
  `-p pytest_asyncio.plugin -p no:cacheprovider`. No application lifespan,
  actual authentication service, network, credentials or physical I/O.
- Ruff check --no-cache passed for both new modules and both test files;
  git diff --check passed. No frontend changes/build or installation.

Exactly six intentional incremental paths relative to the preserved source:

1. `backend/services/identity_broker_verify_client.py` (new)
2. `backend/services/browser_session_issuance.py` (new)
3. `tests/test_identity_broker_verify_client.py` (new)
4. `tests/test_browser_session_issuance.py` (new)
5. `docs/SECURITY_IDENTITY_FOUNDATION.md` (focused update and appended evidence)
6. `docs/SECURITY_RECOVERY_DECISION_287.md` (appended gate note)

Preservation comparison expanded the source's status entries to 59 files. All
remain present; source content is preserved outside the intentional foundation
doc update. Four additional byte differences are **only CRLF/LF** in
`backend/identity_policy.py`, `backend/main.py`,
`backend/services/websocket_manager.py`, `tests/test_websocket.py`; these four
files were not edited by this task. They are reported rather than silently
normalized to satisfy the task brief's byte-identical seed description. All
other seeded files compare byte-for-byte. No source/main writes, staging,
commit, push, PR, merge, deployment, host mutation or live acceptance occurred.
Independent review belongs to the next caller; these results are not that review.

## November 14: standalone broker protected-state source, still inactive

The next local source milestone adds `security/homehub_identity_broker/` and
`tests/test_identity_broker_state_runtime.py`; see the [recovery decision source
milestone](SECURITY_RECOVERY_DECISION_287.md#november-14-2026-standalone-protected-state-source-milestone-inactive)
for the exact state protocol, limits and next gates. The package has no backend
imports, network listener, issuer, installation or runtime composition. It
implements strict compatible VERIFY, immutable profile parity, salted PBKDF2,
HMAC over complete state, independent PENDING denial, serialized private
revoke/zero-overlap rotate/empty-generation restore, and fail-closed reopen.
Offline bootstrap is isolated in a fixture-only module and supplies no OS privilege.
Reserved pending-delivery queues remain unsupported and must be empty.

Windows disposable tests model directory durability and inject crash/I/O failures;
they cannot prove Linux custody, actual power loss, systemd, external rollback
floors or recipient delivery. One object serializes all decisions/mutations;
protected multi-process singleton enforcement is not implemented. No integrated
AF_UNIX connector/daemon or fresh protected revision observer is supplied.
Independent source review belongs to the caller. No production readiness or
credential issuance follows from this milestone. Root-owned packaging/systemd,
OS custody and fresh observer, independent backend rollback enforcement,
OS-local recovery/recipient delivery, client/TLS migration and real Home/iPhone
L1-L6 acceptance remain open. No network issue refresh was permitted; evidence
is local and uncommitted, with earlier unrelated work preserved.

Final scoped current-code validation: **330 passed, 22 Linux/POSIX skips** in
40.31s across state-runtime, verify-client, synthetic broker-protocol and Linux
socket-prototype tests. Ruff package/new-test check and `git diff --check` passed.
Exact command environment and incremental paths are recorded in the linked
recovery decision; no Linux service, root custody or live acceptance is claimed.

### November 14: guarded Linux VERIFY transport source, still not deployable

`security/homehub_identity_broker/linux_verify_server.py` now has an injection-only
fixture transport for the existing Broker.process, exact inherited-descriptor
snapshots and SO_PEERCRED-before-body checks. It refuses production construction;
fixture intent is not root provisioner attestation. There is no CLI/unit, actual
backend connector, admin implementation, issuer or change to /ws, the redesigned
UI or lighting. Bounded nonblocking I/O, one off-loop broker worker with zero
work queue, late-result discard and cancellation are source mechanisms, not
proof of continuous path custody or interruptible storage. Admin always closes
without reading data. Tests include a disposable SIGTERM launcher only.

See the [dated recovery boundary](SECURITY_RECOVERY_DECISION_287.md#november-14-2026-inert-linux-verify-transport-source-boundary)
and [package limitations](../security/homehub_identity_broker/README.md#linux-verify-transport-experiment-do-not-install--not-deployable).
Exact-source Linux execution, protected root packaging/OS custody/singleton,
freshness observer, backup exclusions and deployment floor, distinct admin
principal, approved issuance/recovery/proxy/TLS/client rollout and #293/#461
L1-L6/kiosk/iPhone acceptance remain open. Windows static tests and the supplied
Latitude parent snapshot or separate primitive probes do not satisfy them.


### November 14: Windows native WS consumer source migration (#287/#293/#461)

`backend/services/pc_agent/native_ws_credentials.py` reads Windows Generic
Credentials bound to both profile and exact WSS destination. Reserved prefixes are
`HomeHub/identity/windows_desktop/ws` (brightness) and
`HomeHub/identity/desktop_notifier/ws` (Notifier). The exact target is
`<prefix>/<canonical-host>:<effective-port>/ws`, for example
`HomeHub/identity/windows_desktop/ws/homehub.example:443/ws` or
`HomeHub/identity/desktop_notifier/ws/[2001:db8::1]:8443/ws`.
These are illustrative destinations, not production hostnames. Omitted WSS ports
and explicit `:443` select the same target. Other ports/hosts require separately
provisioned targets; there is no generic profile-only fallback or allowlist input.

Later, separately authorized real-host enrollment must independently verify the
HomeHub endpoint and its certificate trust, then provision the exact URL-bound
profile target. Changing `--server` cannot retrieve an existing credential bound
to another destination. TLS validation alone does not authorize a destination;
operator enrollment of that target supplies the independent host pinning. Targets
separate profile/destination selection, not same-login OS access. Do not provision
attacker-selected targets or reuse bearer values across destination/profile targets.

Only strict lower-case ASCII DNS labels (no IDNA A-labels), canonical IPv4 or
compressed lower-case bracketed IPv6, canonical decimal ports 1?65535, and exact
`/ws` are accepted. Unicode, percent escapes, userinfo, queries, fragments,
controls, trailing DNS dots and alternate spellings reject before any lookup.
Legacy valid `ws://` URLs read no credentials and send no Authorization header,
even when a corresponding WSS credential exists. Missing WSS credentials preserve
no-header behavior; an enforcing server will deny until enrollment is complete.
Malformed credentials refuse the attempt. WSS uses standard certificate/hostname
validation. Handshake logging is suppressed; errors never log raw URLs, target
names, headers or underlying exceptions. No credentials belong in logs, argv,
environment variables or source.

Blob contract remains exactly 152 bytes of UTF-16LE: the 76-character opaque
native bearer without a terminator. There is no creation, mutation, enumeration,
file/env/argv fallback or cache. Each reconnect reads anew using System32
CredReadW and frees its allocation using CredFree. Both worker loops preserve
parsing, stop and backoff behavior.

This is source-only readiness. Real OS credential enrollment and acceptance,
secure WSS endpoint/certificate rollout, Broker protected issuer/delivery gates,
packaged Notifier rebuild and host rollout remain separately authorized work.
No real credential store, network, device or host lifecycle action was exercised.

Offline P1 remediation validation: 341 tests passed across
`test_native_ws_credentials`, `test_monitor_brightness`,
`test_ws_authenticated_boundary` and `test_ws_native_projection` using the
Sandbox Python with APP_ENV=testing and pytest plugin autoload disabled.
After strengthening Win32 target-mismatch/freeing and worker integration checks,
all 66 final credential tests passed. Targeted Ruff and `git diff --check` passed.
Credential API ownership and both worker loops use synthetic mocks; no real
Credential Manager reads occur. These results are local source evidence only.
