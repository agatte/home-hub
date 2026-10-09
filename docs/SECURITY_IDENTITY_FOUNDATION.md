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
also holds the write reservation through verification to serialize decisions
against revocation across connections. The store is synchronous and connection
thread-affine; hashing under the lock is deliberately conservative, not a
network performance design. Decisions are point-in-time; a returned identity
must never become a reusable authorization cache. OS clock accuracy/rollback,
DB integrity/permissions, backup consistency, and filesystem durability remain
external trust requirements. This module does not provide rate limiting or
constant-time existence hiding; only verifier comparison uses constant time.

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
