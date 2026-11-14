# HomeHub identity broker source (inactive)

## Offline custody install plan (November 14, 2026; NO INSTALL)

`custody_plan.py` supplies a versioned, fixed manifest and pure injected-evidence
linter. It performs no filesystem reads, account lookup, hashing of host files,
network access, installation or execution. `manifest()` returns the exact proposed
paths, principals, modes, verify-only creator contract, backup exclusions,
independent floor and unit assertions. `lint_manifest()` rejects changed, missing
or unknown fields (including bool substituted for integer version). It is a source
contract, not a JSON configuration loader, signed package or proof of identity.

`preflight()` accepts two complete **synthetic quiescent** metadata inventories,
explicit absence entries, numeric principal mappings, independently expected
release hashes, a clock and explicitly unresolved attestor requirements. It
checks each ancestor from `/`, exact final ownership/mode/type, no symlinks,
non-directory link count one, explicit no-ACL/reviewed-mount labels, distinct
nonroot broker/backend UID and GID, and unchanged snapshot evidence. The four
non-secret release artifacts require matching SHA-256 labels captured within
60 seconds, without future timestamps. Hash labels are injected, not measured;
there is no trust in a caller-supplied hash, clock, account or inventory.
Never supply key, registry, journal or credential contents to this checker.

`Report.snapshot_consistent` means only the observable fixture checks matched.
Every report retains `root-attestor-required:*` issues, `advisory_only=True` and
`runtime_authorized=False`. Missing/ambiguous mount, ACL, namespace, provisioner,
closure, backup or floor evidence cannot become accepted OS evidence by passing
a string/manifest. There is no attestor implementation, runtime import, service
unit, ExecStart, CLI, installer or enable flag. `RootCustodyProof.check` remains
unconditionally denied. Never use this report as that proof.

The `/opt/.../package` and `/opt/.../runtime` artifacts are proposed sealed release
objects, **not supplied executables**. Their transitive Python/native loader,
libraries, imports, configuration and environment closure still needs a reviewed
build inventory and independent root enforcement. File hashes alone cannot prove
that closure. Ordinary checkout/venv execution is ineligible. The key is proposed
root:broker 0640 below root-controlled parents; only the distinct broker may read
it, and backend group membership in broker/root groups is forbidden. Private
registry and anchor directories are broker:broker 0700 under protected parents.
Registry DELETE-journal and unexpected WAL/SHM files must be private when present;
their presence is not proof of valid SQLite state. The current runtime retains
`state.deny` as an authenticated COMMITTED/PENDING fence; do not delete it on
this plan's authority. `.json.next`/`.deny.next` presence is uncertainty and blocks
the clean preflight. The checker does not authenticate state or repair anything.

Snapshot comparisons miss ABA, mount aliases, delegated descriptors, supplementary
group access and changes after return. A complete fake inventory cannot establish
that a real directory has no other children. No Linux syscall, ACL/MAC, PID1,
power-loss, actual hash measurement or continuous custody acceptance follows.
Focused fixtures are in `tests/test_identity_broker_custody_plan.py`.

Before any installation, the owner must separately approve the exact reviewed
release/build closure, root-owned installer and rollback/recovery plan, explicit
paths/accounts/groups, PID1/socket creation and exact creator PID/UID/GID binding.
The installer design must refuse existing ambiguous state, links, mounts and ACLs
without auto-chown/cleanup. Independently protect backend startup/deploy/rollback
floor outside the backend UID and application backups, including all older launch
paths; a floor file without enforcement is insufficient. Reject unsupported mount,
namespace or MAC custody. Root/PID1 acceptance must measure dedicated-account
isolation, backend denial of key/state/sidecars/admin, descriptor provenance,
creator mismatch denial before bytes, singleton lock retention through worker
exit, restart/stop, backup exclusions and downgrade rejection. Recovery preserves
uncertain evidence and stays closed; intentional registry restore invalidates all
old credentials via a fresh empty generation, never rewinds the journal/floor.
Whole-root/disk rollback remains outside the selected software-journal boundary.

First run the exact changed source tests on disposable Linux without skipping
native integration cases. Root/PID1 acceptance is a subsequent separately approved
disposable-system gate, not a reason to install on Latitude. Fresh generation/
revision authority, secure operator/recipient issuance and delivery, client/TLS
rollout and fail-closed cutover remain separate blockers. Draft #533 must not be
merged/deployed while default-deny `/ws` would disconnect unprovisioned clients.
Original #461 Home/kiosk/iPhone and guarded L1-L6 acceptance remains outstanding.

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
No deployable launcher is supplied here. The later inactive connector/adapter
below still require privileged attestation. Do not install this tree.

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

## November 14 offline protected integration bridge (blocked at OS attestation)

`linux_protected_verify.LinuxVerifyService` is a separate verify-only adapter
around the shared bounded transport and the exact `runtime.Broker.process`.
`FixtureVerifyServer` still requires `fixture_only=True`; its production guard
and `PRODUCTION_SUPPORTED=False` remain. The adapter never binds a socket,
creates state/lock files, reads ambient configuration, issues credentials, exposes
admin methods or installs/enables a unit. No backend bootstrap uses it.

The proposed fixed composition paths are `/run/homehub-identity/verify.sock`
and separately protected `/run/homehub-identity-lock/verify.lock`. They are source
constants, not HTTP/WS/env/CLI options. Root-controlled launch policy must pin
distinct nonroot service/backend UID and GID, listener kernel descriptor and
pathname identities, lock inode and exact socket creator PID/UID/GID. Service
real/effective/saved IDs and
supplementary groups are checked; the inherited listener must be non-inheritable,
AF_UNIX stream/listening, at the exact path with root ownership and backend group
0660. Accepted backend peers require exact kernel UID **and** GID before reads.
Only a separately root-provisioned listener may be passed by the trusted launcher.

`protected_path` walks from `/` with held no-follow directory FDs, checks
root-owned ancestors without group/other write permission, rejects POSIX ACL
xattrs with no unsupported-filesystem fallback, and pins complete identity chains
across operations. Socket/lock type, owner, group, exact mode and inode are checked.
This is deliberately **not** proof of mount namespace, bind-mount, MAC, privileged
executable/dependency or key/storage custody. Those require root-only attestation.

**Explicit blocker:** `RootCustodyProof.check` always raises in shipped source.
Caller subclasses, booleans, arbitrary objects and policy snapshots cannot enable
either adapter. There is no flag to waive this gate. A separately reviewed,
independently root-packaged implementation must attest actual systemd descriptor
provenance/launch policy, continuous namespace/ACL/MAC/mount custody, dedicated
identities, packaged executable/interpreter/dependencies, separately protected key,
registry/journal/fence, sidecars, backup exclusions and deployment/rollback floor.
The exact injected objects must be bound by that attestor, not trusted because
their fields claim root ownership. Python application objects are not an OS
security boundary; Python code that can replace trusted modules is outside this
model. Neither a mutable `valid` attribute nor a caller subclass is attestation.
No such provider or root packaging is implemented in this slice. Thus this is
tested narrower integration source, **not a startable production service**.

After proof, service boot opens the existing protected lock without creation,
checks FD/path identity and takes a fresh-description nonblocking exclusive kernel
`flock`. It checks complete authenticated broker state and real POSIX directory
fsync before serving. No fixture barrier is allowed. The lock is held through
shutdown until storage work actually exits. A stopped transport cannot release
singleton ownership while its old worker remains alive. Python cannot interrupt
a blocked filesystem call: a trusted supervisor must ultimately terminate the
process if necessary. Custody failure poisons the current broker/service; a
quarantined Broker response also terminates serving. No repair, retry or writing
through uncertain storage paths is attempted. Persistent corrupt/PENDING evidence
remains; volatile poisoning is not an independent monotonic rollback fence.

`backend/services/linux_identity_broker_io.LinuxProtectedVerifyIO` implements the
existing `ProtectedVerifyIO` protocol. Before sending any token bytes it checks
protected path custody, connects once, checks the exact attestor-bound socket creator PID/UID/GID, then rechecks custody. It pins the socket inode/ancestor chain, bounds the
whole connect/write/read/EOF exchange to at most two seconds, bounds allocation
to a 2048-byte JSON frame, requires exact EOF, closes on cancellation/failure and
retains no grant or connection cache. Capacity is bounded with no work queue or
retry. All exchange failures have fixed diagnostics without sensitive exception
context. Synchronous custody syscalls still depend on the trusted local filesystem
and provider; this is not a hard real-time storage-interruption guarantee.

The Linux integration tests use the exact service, connector, VerifyClient and
Broker with one synthetic `desktop_notifier` native profile token. They patch
only the missing custody/policy gates for disposable paths and same-process test
identities: they do **not** demonstrate root ownership, distinct OS accounts,
real systemd activation or privileged attestation. Native sockets, SO_PEERCRED,
cross-process flock, framing/deadlines, cancellation, saturation, worker shutdown,
journal quarantine, revocation and zero-overlap rotation execute on Linux only.
Windows runs source/default-denial/policy checks and explicitly skips native cases.

Remaining gates: exact-source Linux execution, independently reviewed root-only
attestor/service packaging and OS acceptance, crash/power-loss durability, fresh
independent trusted `generation()`/`revision()` observer, real operator/recipient
credential issuer and delivery/reconciliation, TLS/native/kiosk/iPhone rollout,
separate integration/deployment authorization and witnessed #293/#461 physical
L1-L6/manual/ScreenSync/final-owner acceptance. Test snapshot callbacks supply no
freshness authority. No live injection or issuer is added here.


### November 14 independent review P2/P3 remediation (local source)

P2: `LaunchPolicy.creator_peer` explicitly pins the socket **creator** PID/UID/GID,
not the later nonroot acceptor. Linux inherited root/PID1 listeners report creator
credentials. The connector compares the entire tuple before request bytes and
rechecks custody. Root UID alone, another root PID, and service acceptor credentials
are insufficient. The unavailable root attestor must independently authenticate
this exact binding against descriptor provenance and trusted launch policy; policy
fields alone supply no authority. `RootCustodyProof.check` still always denies.
No production provider, activation flag or environment fallback was added.

P3: service finalization now stops transport and closes its owned listener even
when preflight custody fails before transport entry. It joins any storage worker
before closing the singleton lock; no caller pathname is unlinked. Synthetic
Windows regression covers preflight denial/descriptor cleanup ordering. A separate
Linux regression invalidates proof after construction and checks listener closure,
actual flock reacquisition, broker poisoning and preservation of the socket path.

Next gate: run the exact focused suites on Linux, including the new preflight
flock regression and real SO_PEERCRED integration; skips are not verification.
Then separately review/authorize a root-packaged attestor and demonstrate a real
root/PID1-created inherited listener accepted by the dedicated nonroot service,
with exact creator binding, denial before bytes for mismatches, protected custody
and singleton/shutdown proof. Synthetic Windows creator tuples do not establish
that OS acceptance. All prior issuer/freshness/durability/activation gates remain.


Final Windows validation for this follow-up: **422 passed, 78 Linux skips** across
six disjoint suites; Ruff without cache, five-file in-memory compilation and
`git diff --check` passed. Exact suite counts, changed paths and current source
fingerprints are recorded in the P2/P3 follow-up in
[the recovery decision](../../docs/SECURITY_RECOVERY_DECISION_287.md).


### November 14 inactive system-manager source contract (#287 / #461)

Local source-only milestone: `unit_contract.py` and the two
`systemd/homehub-identity.{socket,service}.in` fragments specify one proposed
verify-only socket and a dedicated nonroot service. These are **DO-NOT-INSTALL**
review inputs, not installable unit filenames. The service has no `ExecStart` and
neither fragment has `[Install]`. There is no installer, command generator,
account creation, enable flag, runtime entrypoint or activation authorization.
Do not rename/copy the socket fragment into a unit search path: a socket unit can
bind a listener independently of whether its service can execute. No host unit,
`deployment/` artifact, root action or live listener was created by this work.

`validate_sources()` checks the fixed filenames, plain input types, unique
sections/directives, exact schema and exact source text (LF/CRLF equivalent).
Unknown keys, extra comments, resets, repeated `ListenStream`, alternate paths,
exec/environment/credential directives, `[Install]` and drop-ins all fail.
`validate_supplied_files()` reads only its own two fixed sibling source files;
symlink/reparse ancestors/files, hard links and extra directory entries fail.
This read-only lint is not a race-safe filesystem attestor. Mutable Python source
or monkeypatches are outside the authority boundary. A consistent report always
has `runtime_authorized == False`; it cannot satisfy `RootCustodyProof`, whose
shipped implementation remains unconditional denial. No runtime source changed.

Proposed systemd v255 contract, **not systemd-verified here**:

- The separate **system** manager owns `homehub-identity.socket` and
  `homehub-identity.service`; the existing production user `home-hub.service`
  cannot supply this authority. `Accept=no` proposes a single stream listener at
  `/run/homehub-identity/verify.sock`, explicitly selects
  `Service=homehub-identity.service`, and names the inherited descriptor
  `FileDescriptorName=verify`. The service's `Sockets=homehub-identity.socket`
  names that socket unit; it is not a pathname or an activation ordering proof.
  A future trusted launcher must require exactly one descriptor, matching
  `LISTEN_PID`, `LISTEN_FDS=1`, `LISTEN_FDNAMES=verify`, correct AF_UNIX/listening
  state and path/FD identity, before clearing activation environment and making
  its owned descriptor noninheritable. By-name selection alone is not trust.
  The older fixture parser's optional admin support is not authorized by this
  contract: no admin socket or issuer is supplied.
- `SocketUser=root`, `SocketGroup=homehub-backend`, `SocketMode=0660` apply to the
  pathname; they do not prove creator credentials or the listener FD's metadata.
  `DirectoryMode=0755` proposes a mode for automatically created parent directories,
  not their ownership, existing directory repair, ACLs or continuous protection.
  Independently enforced root provisioning/tmpfiles must precreate and attest
  `/run` and both listener/lock parents before any socket start. Proposed layout
  (documentation only, no tmpfiles install file): `/run` root:root without group
  or world write; `/run/homehub-identity` and `/run/homehub-identity-lock`
  root:root 0755; existing `verify.lock` root:homehub-identity 0660, single link,
  never recreated by the broker. Backend membership must never permit parent
  replacement. No `RuntimeDirectory` delegates these directories to the service.
  `RemoveOnStop=no` avoids proposing stop-time unlink as recovery; stale socket
  handling and safe replacement still need a separately reviewed root lifecycle.
- Fixed `User=homehub-identity` and `Group=homehub-identity` require distinct
  nonzero UID/GID from root and homehub-backend. No DynamicUser or backend/root
  supplementary membership is allowed. Empty `SupplementaryGroups=` is not proof
  that NSS/account supplementary groups are absent; independently attest actual
  account membership AND process credentials against the existing service check.
  Empty capability sets, NoNewPrivileges, strict system/home protection, private
  devices/tmp/mounts, namespace restrictions and AF_UNIX-only address creation
  are proposed defense in depth. They neither authenticate inherited FDs nor
  enforce verify-only protocol on their own. AF_UNIX remains permitted.
- Writable exceptions are limited to the two existing sealed state directories
  and the precreated singleton lock file. Key/policy/package paths stay read-only.
  Private mounts and writable bind exceptions require real OS acceptance against
  the service's no-follow path walks, mount custody, SQLite sidecars, lock inode
  and directory fsync. No supplementary shell, debug execution, OnFailure action,
  network listener or journal output is proposed. Standard streams are null.
  Revisit operational diagnostics through separate privacy/security review.
  No environment or credential injection directive is allowed; this does not
  prove the system manager, NSS or the eventual executable has no ambient
  environment. A root-sealed launcher must independently sanitize its environment
  and dependencies, without accepting application/environment enablement flags.

Open root/OS acceptance gates (none waived by exact source lint):

1. Independently review the authoritative v255 directive semantics and effective
   system-manager configuration, vendor fragments, drop-ins, default dependencies,
   ordering and inherited descriptor behavior on the intended host. No network or
   native systemd verification was authorized in this task; this is a blocker to
   installability, not a claimed validated unit. `[Install]` absence prevents no
   manual start; source-only filenames and the missing service command are the
   present packaging boundary, not a privilege mechanism.
2. Supply a separately approved root-sealed executable/interpreter/loader/library
   and dependency closure, trusted launch/stop handling, root-only attestor and
   account/provisioner package. Never execute the checkout/venv. Independently
   enforce sealed state/key/SQLite and sidecar custody, singleton lifetime,
   namespace/mount/ACL/MAC continuity, backup exclusions and root-controlled
   startup/deploy/rollback floor outside replayable broker storage.
3. Prove actual Linux creator PID/UID/GID, path inode and descriptor identity.
   PID1 reexec may preserve descriptors while a restart/rebind may replace the
   socket inode. Neither PID=1 nor root ownership alone authenticates continuity;
   do not substitute the later service acceptor's credentials, blindly repin,
   tolerate churn or assume socket inode equals the pathname inode. On changed
   binding/custody, deny before request bytes and require independently attested
   fresh composition. Reexec/restart/mount transition acceptance remains open.
4. Separately authorize high-risk integration and each root/provisioner/host action.
   Then establish real issuer/delivery, independent monotonic floor and freshness,
   crash durability, TLS/native/kiosk/iPhone and #293/#461 L1-L6 physical acceptance.
   Draft #533 remains unmerged, unprovisioned and unsafe to activate for current
   `/ws` clients. No bridge/client/lighting/UI/runtime behavior changed here.

Evidence is local and uncommitted in
`C:/Work/home-hub-project/worktrees/identity-287-broker-session-20261114`, based on
local `01824867a796a3386205dccdad7839c1ef9d1a46`. The owner's reported remote
#533 head `947753055e3b6eb6348a2be91de74cc2cfb84dfb` and previous green CI were
not rechecked: network/publication were explicitly prohibited. Earlier dated
status/fingerprints above remain historical; this append does not publish them.


Validation for this local source-only milestone: new contract suite **204 passed**;
combined contract/custody/protected-integration suites **279 passed, 28 Linux-only
skips** on Windows with existing venv Python `-B`, APP_ENV=testing,
PYTHONDONTWRITEBYTECODE=1, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1,
`-p pytest_asyncio.plugin -p no:cacheprovider`. Ruff `check --no-cache`, in-memory
compile of both new Python files and `git diff --check` passed. The ten existing
file contents (README original byte prefix) and Git index were preserved. No
native Linux/systemd acceptance, network, publication or activation was performed.
### November 14 actual-kernel metadata preflight candidate (inert)

`linux_os_preflight.probe()` is a standalone read-only, Linux-only diagnostic
with no arguments, CLI, service wiring or installer. It traverses the fixed
`custody_plan.ARTIFACTS` paths from a held `/` descriptor using Linux
`O_PATH|O_NOFOLLOW|O_CLOEXEC`, checks root-owned nonwritable ancestors, leaf
type/mode/link count and available root identities, and rechecks every held
name/inode/metadata binding. It observes real/saved/effective process IDs and
supplementary groups directly through kernel APIs. It reads no file contents,
resolves no usernames/NSS, connects no socket and executes no commands. Output
contains only fixed artifact ordinals and bounded status codes; ordinal order
is the source ARTIFACTS order. For the two intentionally broker-owned 0700 state
directories, this probe can inspect the directory's type/mode but cannot bind
its numeric UID/GID to the named broker account. Its descendants (including
WAL/SHM, journal and pending .next files) are explicitly marked
`private-ancestor-identity-unverified` and **not inspected**; that status never
proves absence or safe custody. A trusted independent account-binding and
root-owned composition must inspect those children before activation.

This is useful for detecting absent installation, unsafe ancestors, wrong root
ownership/modes, symlinks and persistent replacement in the current namespace.
An O_PATH FD pins metadata without opening a FIFO/device or secret for reading.
Failures suppress raw exceptions and paths. No arbitrary path enters the public
probe. Private dirfd helpers are disposable-test primitives, not privileged APIs.
Dedicated account UID/GID binding is explicitly unverified; no caller identity
or 'approved' string can fill it in. Clean metadata does not authenticate source,
process root identity, namespace, installation or file contents. An adversarial
kernel/filesystem or blocked filesystem syscall is outside this diagnostic's
proof and time bounds. It must not be run through an unreviewed privileged wrapper.

Every report retains unconditional missing requirements and
`runtime_authorized == False`. No snapshot-consistent success or attestation
token is issued. ACL/MAC, mount aliases, loaded interpreter/dependency closure,
actual PID1/system-manager descriptor creator provenance, dedicated identities
and supplementary membership, reboot/inode/ABA continuity, backup exemptions,
crash durability and external backend rollback/startup/deploy floor remain
unproved. Root ownership of backend-floor.json cannot enforce a floor outside
the app. `RootCustodyProof.check` is unchanged and always denies.

`tests/test_linux_os_preflight.py` uses disposable native Linux files and actual
O_PATH/dirfd/fstat syscalls, including wrong/unavailable identities, replacement,
hardlink, mode and symlink cases. It requires no sudo and changes nothing outside
pytest temporary directories. Windows executes static/default-denial cases and
explicitly skips native cases. Exact-source Linux CI execution remains required;
Windows skips are not kernel acceptance. No backend, WebSocket, issuer, UI or
lighting cutover is supplied. Real mobile Home/kiosk and guarded L1-L6 remain
blocked on the previously documented provisioning and separately authorized
root composition, security integration, deployment and physical acceptance.
