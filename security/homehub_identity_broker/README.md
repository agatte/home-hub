# HomeHub identity broker source (inactive)

This standalone standard-library package imports no HomeHub runtime. It has no
CLI, production listener, service unit, installer, settings, credential issuer or
operator endpoint. `runtime.Broker.process` accepts one already-bounded VERIFY
frame; private mutation methods are reserved for a future authenticated OS-local
operator composition. Python privacy is not an OS authorization boundary.
`offline_fixture.py` is exclusively a disposable fake-state builder and must not
be included in a serving composition. Nothing here mints credentials.

Registry, journal/deny fence and injected HMAC key require separately protected
custody outside app data/backups. Parents must exist. One Broker object owns the
single thread lock; multiple objects/processes serving the same paths are NOT
supported. A future reviewed Linux launcher must enforce singleton ownership,
root-controlled executable/dependencies, dedicated identity, safe pathname/ACL
and mount custody, inherited sockets, SO_PEERCRED and separate admin default-deny.
No such launcher or client connector is supplied here. Do not install this tree.

Production durability defaults to file fsync, atomic replace and POSIX directory
fsync; unsupported platforms refuse. Windows tests inject a no-op directory
barrier explicitly: they prove ordering/error behavior, not storage durability.
SQLite uses FULL synchronous transactions and DELETE journal mode. Durable
PENDING denial precedes DB writes; both journal and denial fence must authenticate
the entire committed state. Pending/missing/malformed/mismatched/stale state or
leftover exclusive `.next` files deny. No automatic repair or resume exists.

Private rotate accepts only a prehashed replacement record and durably revokes
the old record in the same transition. There is no recipient delivery or pending
delivery implementation: reserved delivery/rotation queues must be empty, and
nonempty queues quarantine. Intentional restore from healthy state empties all
credentials with a distinct generation; it never imports backup verifiers.
Quarantined state requires future separately reviewed trusted offline recovery.

HMAC is not a monotonic root rollback authority. Full coordinated rollback of
registry, fences and key is outside this model. A failure during final durability
acknowledgment poisons the current object and attempts durable PENDING denial;
if storage itself cannot persist evidence, no Python algorithm proves crash
persistence. Linux filesystem/power-loss testing and operational quarantine are
required before activation. Synthetic hooks unwind exceptions; they do not
simulate actual kernel power loss. Root installation, backup exclusions, protected
fresh revision observation and independent backend rollback enforcement remain
unimplemented release gates. See docs/SECURITY_RECOVERY_DECISION_287.md.

## November 14 P3 hardening follow-up (source only)

Fixed limits are 256 KiB serialized state, 128 credentials (including revoked
records), 1 MiB registry file, and 256 KiB + 512 bytes for each journal/denial
fence. Oversized, empty, malformed, truncated or extra state rows quarantine.
SQLite reads enumerate at most two row metadata entries, check type/byte length,
apply SQLITE_LIMIT_LENGTH and retrieve a bounded blob. File checks require
nonempty regular files within limits before bulk reads; anchors additionally use
fstat before/after and a limit + 1 read. No unbounded fetchall or file read remains
in verification. Inventory/state limits also apply before transitions. Fixed
profile grants and the two full protected-state checks per verification remain.

These limits and metadata checks do NOT establish OS custody or race-proof safe
SQLite URI resolution. Symlink/ancestor replacement, SQLite sidecars, permissions,
mounts and concurrent writers remain external protected-OS/singleton prerequisites.
Full coordinated rollback of registry, anchors and key remains outside the model.

Local Windows validation: the requested runtime/client/protocol/Linux-prototype
suite passed **387 tests, 22 skipped in 77.73s**. Three final focused tests passed
**3 tests, 144 deselected in 3.16s** (pre-read rejection, regular-file metadata,
inclusive credential cap), for **390 passed, 22 skipped** across both runs.
Used main/.venv/Scripts/python.exe -B, APP_ENV=testing,
PYTHONDONTWRITEBYTECODE=1, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1,
-p pytest_asyncio.plugin -p no:cacheprovider. Ruff check --no-cache on this package
and tests/test_identity_broker_state_runtime.py and git diff --check passed.

New disposable tests cover bootstrap interruptions; one-step open/write/rename
faults at all four guard/journal atomic writes during bootstrap and revocation;
preserved exclusive .next evidence; and failed fallback denial persistence.
When no storage mutation occurred, the old exact committed state may remain;
when the final state committed, only that exact state may remain. The failed
object always poisons itself. This is exception injection, not kernel crash or
power-loss proof. Every backend fixed profile and every accepted grant is tested
through the current VerifyClient with synthetic async transport, checking kind,
source, lane, wrong source/lane, expiry, revocation and generation/revision denial;
guest_gateway remains grantless. Denials do not echo the synthetic token.

Only runtime.py, tests/test_identity_broker_state_runtime.py and this README were
changed in this follow-up; all work is local and uncommitted. No Linux AF_UNIX,
SO_PEERCRED, POSIX durability, root custody or live runtime acceptance is claimed.
The separately authorized Linux singleton/socket/OS custody and crash-durability
harness, protected freshness observer and all live activation gates remain open.

## Linux VERIFY transport experiment: DO NOT INSTALL / NOT DEPLOYABLE

`linux_verify_server.py` supplies only `FixtureVerifyServer` and an injected
inherited-descriptor seam. Production construction is refused; fixture intent
and snapshots are explicitly not root provisioner attestation. There is no
entrypoint, environment enablement, service unit, binding, connector, issuer or
admin implementation. No backend/ASGI/UI change accompanies this experiment.
The previous transport-only prototype remains untouched and disconnected.

The systemd ABI parser checks exact LISTEN_PID/FDS/FDNAMES for verify and optional
admin, mapping consecutive inherited descriptors from 3. Tests inject duplication
of their own disposable listeners. Descriptor socket identity and pathname inode
are separate expectations: AF_UNIX/SOCK_STREAM/listening state, exact path,
unique descriptor identities, node owner/group/mode and non-inheritance are
checked. These are snapshots, not continuous ancestor/ACL/MAC/mount or privileged
executable custody proof. No untrusted environment or caller-selected UID can
turn this fixture class into production authority. A separate reviewed root
provisioner attestation and trusted launcher are still absent and required.

SO_PEERCRED is read before any request body; only the injected fixture backend
UID and optional exact GID pass. Admin always closes without reading or invoking
Broker, even when verify capacity is exhausted. One accept per endpoint per tick,
admin first, prevents verify backlog draining from starving that denial. There
are 1..32 active verify clients (default 8), a whole request/read/work/write
deadline of at most two seconds (default 0.5), a 2048-byte payload cap and one
request per connection. Clients MUST half-close their write side: EOF proves
frame termination; surplus/delayed second frames fail. Valid requests reach only
the existing exact v1 Broker.process. Responses retain its framing, nonce and
policy; tokens are never logged or returned. Malformed/unauthorized/admin/busy
connections close without an application response.

PBKDF2/state work runs in one daemon thread, with zero queued broker operations.
Timeout closes the client and discards late results while work retains capacity.
`stop()` cancels all pending clients and closes duplicate listeners, never unlinking
caller-owned paths. A future trusted launcher must bind SIGTERM to stop; only the
disposable test launcher does so here. The same Broker object refuses another
server until its prior worker exits. Separate objects/processes are NOT protected
by this local guard. Python cannot interrupt blocked storage/PBKDF2, snapshot
syscalls or prove physical deadline guarantees; the daemon thread may outlive
the transport. A production process supervisor, storage bounds, singleton
custody and shutdown/restart proof remain mandatory. There is no production
termination or systemd acceptance from this source.

Before deployment: prove dedicated OS owner and continuous path/ACL/MAC/mount
custody; hardened root-owned packaged executable/interpreter/dependencies; real
socket units and distinct non-backend admin principal (admin still unimplemented);
independent state/key/journal backup exclusions; protected freshness observer;
root deployment/downgrade floor; exact-source Linux integration and filesystem
durability; approved issuance/recovery, recipient/CSRF/session lifecycle;
proxy/TLS and native/kiosk/iPhone rollout; #293 and #461 guarded L1-L6 acceptance.
The owner-supplied November 14 Latitude parent/OS snapshot and five separate
disposable Linux primitive probes do not satisfy any exact-source execution gate.
