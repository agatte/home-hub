# Identity foundation for #287 — NOT LIVE

This first offline slice is **NOT ENFORCED**, not provisioned, and not imported
by existing routes, startup, legacy `backend/api/auth.py`, or any client. It does
not complete #287. No production credential or migration is supplied.

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
