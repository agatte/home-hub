# #287 recovery architecture decision — proposed, NOT LIVE

## November 14, 2026: offline packaging/custody preflight candidate

Local source only in `identity-287-broker-session-20261114`, base `01824867`;
the existing eight-file draft delta was preserved. Network/host reads and Git
publication were prohibited; draft #533 head `a4dd554e` and its previous Linux
CI results are owner-supplied history, not independently reverified here.

The [fixed offline custody plan](../security/homehub_identity_broker/README.md#offline-custody-install-plan-november-14-2026-no-install)
adds `custody_plan.py` and `tests/test_identity_broker_custody_plan.py`. It is a
NO-INSTALL manifest/linter, with no privileged provider, unit or installer. It
narrows proposed package/runtime/config/key/state/sidecar/journal/fence/lock/floor
paths and explicitly distinguishes fixture metadata/hash consistency from root
attestation. All reports deny runtime authority, including a positive synthetic
snapshot. All previous proof, transport and runtime code remains untouched.

Blocking design decision: neither a manifest nor matching fresh metadata/hashes
in a user-writable Python tree can establish continuous root-controlled execution,
dependency closure, mount/namespace/ACL/MAC custody or independent rollback-floor
enforcement. The chosen safe protocol is advisory lint only. `RootCustodyProof.check`
continues unconditional denial; no runtime consumer uses this plan. A separately
reviewed root-owned installer/attestor design and explicit owner approval remain
necessary before any root/PID1 installation or acceptance. The README specifies
the exact acceptance/recovery gates and observable/TOCTOU limits. No security
integration, merge, deployment or #287/#293/#461 completion is claimed.

Validation of this candidate (Windows Sandbox, existing interpreter only):

- New `test_identity_broker_custody_plan.py`: **46 passed**.
- New suite plus `test_linux_protected_verify_integration.py`: **69 passed,
  28 skipped**. The standalone new-suite rerun overlaps and is not additive.
- Existing `test_linux_identity_broker_verify_server.py`,
  `test_identity_broker_state_runtime.py`, `test_identity_broker_verify_client.py`,
  `test_identity_broker_protocol.py`, `test_linux_broker_socket_prototype.py`:
  **399 passed, 50 skipped**.
- Disjoint total: **468 passed, 78 skipped**. All Linux skips are **NOT VERIFIED**.
- Ruff `check --no-cache` on the new module/test, two-file in-memory `compile`
  and `git diff --check` passed. Pytest used `-B -p pytest_asyncio.plugin
  -p no:cacheprovider -q`, `APP_ENV=testing`, `PYTHONDONTWRITEBYTECODE=1`,
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; no tools were installed or fetched.

Next exact-source Linux gate: run the new custody suite and all six named broker
suites with those pytest options against disposable fixtures. Specifically the
unchanged protected-verify integration suite must execute **51 cases with zero
skips**; this Windows run executes only 23 of them. The new 46-case suite must
also pass on Linux. Privileged-only tests in the other suites require a separately
authorized disposable root environment and their explicit opt-in; nonroot skips
do not satisfy them. Then separately approve the root installer/attestor design
and real PID1/dedicated-account acceptance described in the package README.
No Latitude installation, production probe or client cutover is authorized.

**Status:** reviewed candidate for the next implementation slice, 2026-10-09. This is a
design/proposed rollout contract, **not** authorization to install a privileged
service, modify credentials, restore databases, change host permissions, deploy,
or enable HomeHub authentication. The offline core from PRs #345 and #346 is
merged but is not wired to runtime routes.

## Evidence and target threat boundary

- `deployment/home-hub.service` runs `run.py` as the **Latitude systemd user
  service**, in the home checkout; the repo does not install a system-level
  privileged identity authority today.
- `backend/database.py` uses `DATA_DIR/home_hub.db` for application state.
  `scripts/backup-db.sh` (04:30 user cron) quiesces **only**
  `home-hub.service`, runs `sqlite3 .backup` for that **one application DB**,
  checks integrity and resumes backend/health. It does not currently back up
  an identity registry, because none is active.
- `backend/identity_core.py` takes an explicit SQLite path and in-process
  object capability. It **does not** establish an OS trust boundary. The
  existing design at `docs/SECURITY_IDENTITY_FOUNDATION.md` discusses a more
  demanding externally anchored protocol; none of it is implemented.

**Phase-1 security goal:** a compromised/untrusted HomeHub backend process or
ordinary HomeHub application-DB backup/restore must **not** alter, restore or
re-authorize revoked identity credentials. Protect fixed-principal decisions
and local recovery from untrusted LAN/HTTP/WS callers and same-UID applications
*to the extent the OS boundary can actually enforce*. Fail closed on ambiguous
registry restore or an interrupted mutation.

**Trusted in this phase:** the OS kernel, root/authorized OS administrators,
the reviewed privileged broker code and its separate service identity, protected
system storage, and the integrity of the Latitude installation. **Not covered:**
root compromise, an attacker who can restore the broker state plus its
out-of-backup journal or revert an entire OS/disk image, physical/firmware
attacks, or a compromised backend that bypasses *its own* actuator enforcement.
The existing deploy/rollback path does not yet enforce an identity-aware
minimum backend version. Before activation an **independently enforced**
startup/rollback floor must prevent an old release from silently re-enabling
legacy trust or ignoring broker decisions; an old backend cannot be trusted
to enforce its own downgrade rejection. A root-owned file or local
systemd encrypted credential is **not** a hardware
monotonic counter; encrypted-at-rest secrets do not prove anti-rollback.

## Chosen first implementation path: separate OS identity broker

**Recommendation: a dedicated system-level `homehub-identity` broker account
with root-controlled executable, dependencies and unit, private registry and independent
fail-closed revision journal outside both application DB and routine backups.**
Implement and verify it first as a synthetic, offline adapter. Do **not**
require TPM NV counters for this bounded first rollout. Reserve a TPM/external
authority decision for a separately requested threat boundary that includes
privileged whole-system rollback.

- On the Latitude, a root-installed **system** service (not a `systemctl --user`
  unit and not a subcommand in `scripts/deploy.sh`) runs as a dedicated
  non-login OS identity. Reviewed code, interpreter/dependencies, configuration,
  executable parent directories and unit are root-controlled **outside the
  writable HomeHub checkout or virtualenv**; private registry and state files
  are inaccessible to the HomeHub user. Proposed
  locations are `/var/lib/homehub-identity/` for *registry*, a distinctly
  managed *anchor/journal* file and `/run/homehub-identity/` for AF_UNIX IPC.
  Exact paths, ACLs and `systemd` hardening are subject to read-only Latitude
  inspection and explicit host-administration approval.
- A narrowly scoped **verify-only** AF_UNIX endpoint is accessible to the
  HomeHub service user; the broker enforces credential validity and the
  reviewed fixed policy. A distinct administrative endpoint is usable only
  through OS-authenticated, operator-approved local escalation, never merely
  by matching private IP/localhost or claiming a username/source. Check kernel
  `SO_PEERCRED` plus socket permissions, **but recognize all processes of
  the same UID are indistinguishable by UID alone**. Treat the entire HomeHub
  user UID as untrusted for *administrative* authority. Admin IPC accepts
  only root or an explicitly approved OS administrator UID **distinct from
  the HomeHub UID**, after interactive operator authorization; merely
  possessing the backend UID is never sufficient.
- No generic shell, arbitrary filesystem access, SQL executor or dynamic role
  editing is exposed over either socket. Normal verify IPC never receives the
  in-process administrative capability. The protected broker owns the
  `IdentityStore` connection and is the only authorized writer to registry
  and journal. Do not expose DB files or token verifier material to
  `app_settings`, debug SQL or ordinary exports.
- For enrollment/recovery, an explicit OS-local operator invokes a **fixed
  audited command** through interactive OS authorization (e.g. narrowly
  reviewed sudo/polkit integration). Do not add passwordless elevation or
  reusable host-admin/Host Bridge authority. The operator selects one reviewed
  fixed profile and recipient. For phase 1, the broker directly issues
  credentials to a **separately authenticated target** through an owned secure
  operator-approved channel. Do not ship generalized one-use pairing
  tickets in phase 1: a stolen ticket can be redeemed first and a same-UID
  local socket does not authenticate which browser/process holds it. Any
  uncertain or lost delivery requires revocation **of the minted credential**
  before re-enrollment; merely burning the ticket is not enough. The admin
  command emits only non-secret status: no bearer token in stdout, arguments,
  environment, clipboard history or logs. Do not add anonymous LAN pairing.
- Windows Supervisor/Notifier, browser, kiosk, guest and other clients remain
  clients **of Latitude authority**. No elevated Windows-side broker or
  Windows-to-Latitude administrative shortcut is required for phase 1.
  Per-client secret storage/provisioning needs its own authorized acceptance.
  The initial broker must not assume Supervisor and Notifier use different OS
  accounts: both may run under the same Windows login.
- The broker may validate a credential, but an arbitrary operation/lane string
  provided by compromised backend code is not an independent authorization
  boundary. Route adapters must supply owned operation IDs; protect actuator
  writes and sensitive responses downstream as separate rollout gates. Short
  credential verification must never imply physical presence/room authority.

## Restore boundary and anti-rollback protocol within that boundary

1. **Keep identity separate from `home_hub.db`** and explicitly exclude the
   broker's registry and journal from the existing 04:30 application backup.
   Normal application-DB restoration neither changes the identity registry
   nor re-enables revoked verifiers. Confirm this in a synthetic restore test
   and by examining the exact installed backup configuration before activation.
2. Store a committed **generation, monotonic logical revision and authenticated
   digest of the *complete security state*** in a broker-only protected
   *out-of-registry* journal. Include protocol minimum version, instance ID,
   credential profile/source/revocation/expiry, bounded rotation, and pending
   pairing state in the canonical digest. Journal must NOT be restored along
   with a registry snapshot. Treat an absent/mismatched or untrusted journal as
   quarantine, not bootstrap. This protects only while the separate journal
   and protected OS identity remain trusted; it is **not** TPM-level protection.
3. All enroll/rotate/revoke/pair operations serialize behind one broker gate
   that suspends new decisions **and drains in-flight authorization decisions**,
   checks the committed digest, computes the next
   state, and durably persists a **PENDING / DENY** journal record *before*
   committing the new SQLite state. After durable DB commit, finalize the
   journal to the matching revision/digest, verify and reopen authorization.
   Use owned atomic file replacement plus file-and-directory fsync (or a
   reviewed equivalent) and explicit failure injection. No atomic transaction
   spans the two stores; uncertain writes remain quarantined. Do not report
   successful revocation or deliver enrollment material until finalization.
4. On restart, **PENDING** always denies. A trusted operator may finalize only
   if the exact intended new DB digest matches; old/torn/ambiguous state
   quarantines. Never roll the journal backward to let previously revoked
   credentials become valid. Old executable versions failing protocol
   minimum-version validation must also deny.
5. Intentional **identity-registry** restore is not the ordinary app restore.
   Stop serving, obtain explicit local operator authorization and validate the
   backup as **offline evidence only**. **Every intentional identity registry
   restore, even one labeled current, requires full invalidation of all prior
   credentials, sessions and pairing tickets**, followed by an empty new
   generation and separately authenticated fresh enrollment through the
   protected journal protocol. Never import restored verifiers into serving
   state. An exact-current state after an ordinary clean broker restart is
   *not* an identity restore and can resume only after journal/digest/version
   verification. If journal/state is lost, remain closed until explicit
   trusted operator recovery; do not auto-pair after restart.

**Important limitation:** an authorized root user (or offline attacker with
whole-disk control) can restore *both* registry and the journal to a matching
old generation. Detecting that threat requires a tested external monotonic
authority or TPM-backed primitive plus an independent recovery contract; defer
until that security requirement is explicitly chosen and hardware/rollback
support is proved. `systemd-creds` is useful for service secret delivery but
cannot, by itself, provide a monotonic revocation/revision anchor.

## Why other options are deferred

| Option | What it proves | Why not phase 1 |
| --- | --- | --- |
| In-process capability / same-user separate file | Only application-level checks | Backend and helpers share authority; no OS separation or independent rollback enforcement |
| Protected broker + separate registry/journal **(selected)** | Ordinary app DB restore and unprivileged backend cannot resurrect credentials if OS isolation and journal protocol hold | Requires explicit system-service installation/host governance; root/whole-system rollback remains a trust limit |
| TPM NV monotonic epoch or external authority | Can extend defense to privileged full-volume snapshot rollback, depending on hardware/atomicity and recovery design | TPM capabilities, wear/availability, reset/replacement, atomic pending sequence and operator custody unverified; do not claim it exists today |

## Bounded implementation and acceptance sequence

- **A. Offline policy/broker protocol:** simulate trusted broker and an
  unprivileged backend caller, fixed operation/lane decisions, exact OS peer
  role authorization, bounded admin verbs and no reusable admin capability in
  the verify channel. Model UID limitations explicitly.
- **B. Synthetic durable journal:** use disposable directories and SQLite
  fixtures to test normal app-DB restoration, **all** intentional identity
  registry restores requiring invalidation, journal loss, digest
  tampering, pre-pending crash, pending-before-DB crash,
  DB-committed-before-finalization crash, post-finalization ack loss,
  crashes during new-empty-generation recovery, concurrent verification versus
  revocation, uncertain credential delivery/revocation and
  rotation/revocation failures. Include old-broker startup and a rolled-back
  backend attempting to bypass broker enforcement; fail closed via an
  independently enforced minimum-compatible-version mechanism.
  Defer generic ticket-redemption testing until authenticated recipient
  binding is designed. Test denial after restart, preserving audit evidence;
  never silently repair mismatches.
- **C. Host-readiness inspection (read-only):** verify Latitude OS/systemd
  version, available service isolation/ACL approach, installed 04:30 backup
  scope, filesystem boundaries, and actual recovery entrypoint availability.
  Record evidence without reading credentials, registries, cameras or data.
- **D. Separate authorization gate:** before any system service/user creation,
  sudo/polkit rule, registry migration, key/ticket provisioning, production
  deployment, restart, hardware operation or restore, obtain explicit approval
  and a host-safe bounded execution/recovery plan. Do not widen Host Bridge.
- **E. Client-by-client adoption:** prove kiosk/browser/Windows/guest/Latitude
  compatibility, fail-closed evidence ageing (not fabricated Away/Home),
  response privacy, CSRF/Origin/Host/WS enforcement (#293), source trust and
  actuator write ownership. Only then consider legacy trust retirement.

## Decision status and next gate

**Selected for offline prototyping, not approved for live installation.** The
first candidate should implement **only an unprivileged synthetic broker
protocol and crash/restore tests in the Sandbox**, with no actual credentials
or services. Revisit external TPM only if the user wants whole-system rollback
resistance. Leave #287 open and preserve the separate authorization gates.

Reference: `docs/SECURITY_IDENTITY_FOUNDATION.md`, #284, #287, #293,
`deployment/home-hub.service`, `backend/database.py`, `scripts/backup-db.sh`.

## Offline synthetic protocol evidence (#287)

`tests/support/synthetic_broker.py` and
`tests/test_identity_broker_protocol.py` model the selected two-store sequence
using disposable SQLite and an independent JSON journal under pytest temporary
directories. They have no production import path. All credentials, profiles,
peer UIDs and approvals are fake fixture inputs. A supplied shared lock represents
the single broker authority; it serializes verification, administration and
diagnostics across fresh broker objects. This is not a cross-process lock or OS
access control. Same-UID fixture peers are deliberately indistinguishable.

The canonical digest includes the complete stored JSON security state, including
instance, random generation, logical revision, protocol/code floor, every
credential binding/verifier/expiry/revocation/delivery flag, and empty session and
ticket inventories. No session issuance or pairing protocol is implemented.
Rotation deliberately uses zero overlap. Tokens use clearly fake material and
simple hash verifiers, not production credential cryptography. The journal's
digest is an integrity comparison whose authenticity depends on trusted journal
ownership; it is not a signature, MAC or hardware monotonic authority.

Mutations validate COMMITTED state, durably persist a separate protected
`deny.guard` target intent, persist PENDING, commit SQLite with FULL synchronous
durability, replace the journal with COMMITTED, recheck the exact guard target,
then remove the guard with a modeled deletion durability barrier before acknowledgment.
Guard presence denies even when visible COMMITTED bytes and SQLite match.
Failures never silently clear the guard; explicit approved recovery may re-finalize
a matching PENDING or COMMITTED target, recommit SQLite with FULL synchronous
durability, and clear it after durability rechecks. Tests inject exceptions at
these boundaries and reopen fresh broker
objects against disk; they do not simulate actual power loss or kill a process.
Journal writes flush/fsync the file and use atomic replacement. A separate
injected directory durability barrier models the required directory fsync;
Windows has no real directory fsync in this harness. The injected barrier is an
exception/visibility model, not a simulation of lost filesystem writes. On a
guard-deletion barrier exception the model restores a file-fsynced guard before
propagating failure; interruption or further filesystem failure during that repair,
and power loss between unlink and its durability barrier, cannot be proven safe
by ordinary fresh Python objects. Windows/Latitude filesystem guarantees,
replacement semantics, SQLite recovery and actual power-loss behavior require
platform-specific validation before any live readiness claim.

PENDING or guard presence always denies ordinary authorization. Separately approved fixture admin
recovery finalizes only an exact target state. Old/mismatched/corrupt evidence
requires explicit fresh empty generation recovery, never rewinding a trusted
journal to fit a backup. When the journal is lost or unreadable, the model cannot
reconstruct its logical revision; separately approved recovery establishes a new
random empty generation rather than claiming monotonic history. A corrupt SQLite
file cannot be repaired by this bounded model: recovery can leave PENDING and
remains quarantined, requiring a separately designed evidence-preserving repair
procedure. No automatic file removal or schema repair is provided.

Enrollment persists uncertain delivery before returning fake material. A fixture
admin may confirm successful delivery; without durable confirmation, verification
denies across restarts and replacement is blocked until the minted credential is revoked. Lost acknowledgments never
replay secret material. A confirmation interrupted before final durability denies;
a lost status acknowledgment after final durability does not undo confirmation.
The synthetic command is named `restore_intent_invalidate`, accepts no backup
argument, and establishes an empty new generation. It does not validate or install
a backup; read-only backup validation remains deferred to a separately reviewed
production restore design. No backup verifiers are ever imported.
The precise accepted-command boundary is successful guard file fsync, replacement
and directory barrier under the shared stop-serving/drain gate. Before that
boundary the command is NOT ACCEPTED, no backup may be installed, and unchanged
old state may continue serving. Intent initiation alone is not durable acceptance.
A visible guard after an uncertain first barrier conservatively denies even if
acceptance was not acknowledged. After durable intent acceptance all prior
credentials deny across fresh instances until empty-generation finalization.
A crash before the first guard replacement leaves unchanged files and cannot be
detected without an external trigger. This limitation also applies to exact-current
backups; no unconditional denial is claimed for a not-yet-accepted command. Ordinary
application-DB restoration does not alter either broker store. An unannounced
exact-current copy is indistinguishable from a clean restart: the intentional
restore rule still depends on an independently owned restore entrypoint.

The fixture-supplied startup floor models independent deployment enforcement; it
does not stop an actual old executable from ignoring the protocol. Tests explicitly
demonstrate that registry-only rollback denies with the intact journal, while
restoring both stores to a matching old snapshot resurrects credentials. Root,
whole-state rollback, clock integrity, authenticated recipient delivery, durable
operator approval, process isolation, route/actuator enforcement and protection
against arbitrary trusted Python code remain outside this prototype.

**Host-readiness gate C was partially verified read-only on 2026-10-10.**
The Latitude is Ubuntu 24.04.4/systemd 255, with an active `anthony` user unit,
04:30 user cron entry, and no identity broker account/service/state directories.
The installed unit matches the GitHub source SHA-256. See #287 for the host
inspection evidence. DB/backup file ACLs and actual backup success remain unchecked.
**Next gate D requires separate authorization for any installation or recovery**,
after resolving root-controlled code/socket custody, authenticated operators,
and an independently enforced minimum backend version. This harness is offline
evidence only; #287 remains open and no live broker or enforcement exists.

## Appendix: Linux privilege boundary conformance candidate (OFFLINE ONLY)

`tests/support/linux_broker_boundary.py` and `tests/test_linux_broker_boundary.py`
are test-only contracts, not an operational broker. They neither import backend
code nor issue credentials, execute SQL/shell, provision accounts, install units,
or start/administer systemd. Production backend UID 1000 is contextual evidence;
fixtures use distinct dummy numeric UIDs 41001–41004, never account lookups.

The transport helper requires connected Linux AF_UNIX SOCK_STREAM and reads
`SO_PEERCRED` using `getsockopt(SOL_SOCKET, SO_PEERCRED, calcsize('iII'))` and
`unpack('iII')`: native signed pid_t and unsigned uid_t/gid_t. PID <= 0 and
UID/GID 0xFFFFFFFF sentinels fail closed; valid IDs above signed INT_MAX are
preserved, but confer no authority under the fixed low-UID fixture policy.
Damaged connected-socket tests inject both sentinels and high 32-bit IDs;
these are decoder tests, not measured kernel-issued high-ID identities.
Request identity/source/profile/approval fields deny rather than
confer authority. Backend UID admits only the exact `verify` operation on the
verify endpoint. Fixed administrative operation IDs require a separate endpoint,
root or configured distinct admin UID, and a simulated fresh interactive approval.
This approval boolean is trusted fixture input, not a wire field or a real
sudo/polkit implementation. Admission does not perform the named operation.
Unknown operations and missing/mismatched peer identities deny. UID identity
cannot distinguish two clients running as the same UID, authenticate a browser,
or establish recipient/source or physical-presence authority.

Linux peer credentials are captured at connect/listen/socketpair time, not
necessarily those of the current descriptor holder after privilege drop or FD
passing. A root-only, disposable-container opt-in test connects before the child
clears supplementary groups and drops GID/UID, then sends its post-drop fixture
identity; the parent must still observe the original connect-time UID/GID.
This test does not enable an admin role. Future real authorization must close
old admitted connections and invalidate authorizations after restart, downgrade,
or privilege changes, and must never accept a delegated credential-less admin FD.
Cached peercred alone cannot enable admin authority. These are lifecycle design
requirements for a future service; no actual admin socket exists in this model.

Linux non-root runs still measure forked same-UID peer PID/UID/GID and reject
unsupported/unconnected transports. The multi-UID proof requires both root and
`HOMEHUB_DISPOSABLE_LINUX_BOUNDARY=1`, set only by the orchestrator in an
independent disposable container. It uses fork, clears supplementary groups, and
sets GID/UID only in children; no account database changes occur. All sockets,
synthetic registry/journal/guard files and permission changes stay below per-test
tmp roots. Children enter that tmp root before dropping privileges to avoid
pytest ancestor permissions obscuring the dedicated-directory measurement.
The dedicated 0700 broker-owned directory and root-only admin directory remain
actual traversal barriers. A temporarily widened verify socket measures third-UID
policy denial separately from filesystem denial. Child waits are bounded and
children are reaped on success or failure. Use a short unique `--basetemp` in the
container to respect Linux AF_UNIX pathname limits; do not use real host paths.

Path-custody tests use complete synthetic absolute metadata trees, including a
virtual `/`; they never inspect host code/interpreter/config paths. Each executable,
interpreter, dependency and configuration path must have a root-owned parent chain
with no symlinks or group/world write access. Protected regular files require
integer `nlink == 1`; hardlink aliases (`nlink > 1`) fail closed. Directories do
not require one link: Linux directory link counts naturally reach two or more.
Backend-owned code/venv fails closed.
The private state directory instead requires the configured dedicated broker
owner/group and exactly 0700, beneath trusted parents. This owner comes from
trusted test configuration, never an apparent UID supplied by a request.
Socket metadata contracts require a root-controlled run parent, explicit 0660
broker/backend-group verify socket, and a separate root-only 0700 parent with
0600 root-owned admin socket. That root-only example cannot serve a non-root
admin UID: any distinct-admin variant needs separately approved ACL/ownership
design and tests. Snapshot metadata checks alone cannot establish race-free
custody, ACL denial, SELinux/AppArmor AVC policy, mount trust, or executable
integrity. This is a metadata snapshot only: real lstat checks, symlink/TOCTOU
races and filesystem aliases still require Linux installer/audit checks. Those
require separate Linux installation evidence.

### Non-deployable system-service illustration

**Design text only. Do not copy/install/start this unit.** Referenced executable,
accounts and directories do not exist as part of this candidate. The root-only
admin listener would require a separately reviewed root-owned socket activation
or equivalent arrangement; this unprivileged service template does not create it.

```ini
[Unit]
Description=NON-DEPLOYABLE HomeHub identity boundary illustration

[Service]
User=homehub-identity
Group=homehub-identity
ExecStart=/opt/homehub-identity/bin/python /opt/homehub-identity/broker.py
StateDirectory=homehub-identity
StateDirectoryMode=0700
RuntimeDirectory=homehub-identity
RuntimeDirectoryMode=0700
UMask=0077
ProtectSystem=strict
ProtectHome=true
NoNewPrivileges=yes
RestrictAddressFamilies=AF_UNIX
PrivateIPC=yes
```

The entire `/opt` code/interpreter/dependency/config chain must be root-controlled;
state under the proposed StateDirectory is dedicated-broker-owned. A private
RuntimeDirectory alone cannot expose verify IPC to the backend. Separate
root-controlled verify/admin socket parents, socket modes, backend group/ACL
access and Linux SO_PEERCRED policy need an explicit installation design.
systemd may recursively adjust StateDirectory ownership when existing ownership
differs: inspect exact existing paths, contents, links, ownership and mount/ACL
boundaries and obtain installation approval before using this mechanism. Never
point it at an application checkout, shared database, or unrelated state.

Passing this harness proves only the checks actually executed. Windows skips
Linux kernel tests; non-root Linux skips the privileged multi-UID test. Neither
passing tier proves systemd hardening, real-account provisioning, single active
broker enforcement, durability/fsync/power-loss recovery, external rollback
resistance, or old backend/actuator bypass prevention. No production readiness
claim follows. Those remain separately measured activation gates; #287 stays open.

## Offline inherited-socket prototype appendix (2026-10-10)

**NOT INSTALLABLE / NOT PRODUCTION / DO NOT INSTALL. #287 remains open.**
`tests/support/linux_broker_socket_prototype.py` is a standalone test-only Linux
process; it imports neither backend nor identity_core, creates no listener,
credentials, registry, journal or storage, and exposes no executable commands,
SQL, file paths or credential issuance. Trusted launcher configuration supplies
the backend UID/group and rooted socket locations; wire claims cannot change it.
Named system identities in the illustrative units are conceptual, not provisioned.
No `/opt/homehub-identity-prototype` package is supplied or installed.

The ABI requires exact current `LISTEN_PID`, `LISTEN_FDS=2`, and
exactly two unique `LISTEN_FDNAMES` names `{verify,admin}`, mapped to fd 3/4
by position, with distinct kernel socket identities. Both `verify:admin` and
`admin:verify` are accepted when their concrete sockets match that permutation.
Both must be AF_UNIX SOCK_STREAM with SO_ACCEPTCONN, at the exact named pathname
under the injected trusted root. Names alone confer no authority. Mismatched permutations,
missing, surplus, duplicated, non-socket or rogue listeners fail startup; there
is no one-FD fallback. Activation environment is consumed and listener FDs made
non-inheritable. The subprocess test launcher uses a fresh interpreter to dup
and exec rather than forking inside threaded pytest, whitelists inherited FDs,
closes aliases, and reaps/terminates children with deadlines.

The root anchor and immediate socket parents are lstat-checked for trusted owner,
directory type and absence of group/world writes. The exact admin parent is 0700;
accessible nodes require root/custody-owner 0600 admin or owner/backend-group
0660 verify. Fixture roots explicitly stop traversal: this does not audit their
ancestors. Illustrative production paths use `/run` as root, with separate
`/run/homehub-identity-prototype-verify` (0755) and
`/run/homehub-identity-prototype-admin` (0700) parents. PID1 owns both listeners,
verify uses group `homehub-backend`; admin remains root:root. SocketUser need not
equal service User: a non-root process can accept through an inherited root-owned
listener without directory traversal. The opt-in test measures this kernel
property separately. An unprivileged broker cannot lstat the admin node inside
0700; it checks the parent and exact kernel listener path, relying on
an explicit **trusted-OS provisioner attestation requirement before launch and
while serving** for the inaccessible root socket pathname inode, ownership/mode,
parent custody and ACL. It does not claim to have verified that node. The offline
`custody(..., provisioner_preflight=True)` snapshot fails closed on inaccessible
or misprovisioned nodes; a synthetic accessible fixture exercises bad socket and
parent modes. This helper does not implement ACL audit or continuous attestation.
No broker privilege elevation, traversal relaxation or ACL bypass is introduced.
Kernel FD inode identity is checked for uniqueness and owner/type; Linux socket
FD and filesystem pathname inodes are different identities and are not equated.
Snapshot checks do not prove pathname-to-FD
binding against replacement races, ACL/MAC policy, mount integrity, or package
custody. Socket mode cannot prevent FD delegation or distinguish same-UID clients.

One tiny JSON object is framed by client write EOF, capped at 256 bytes and a
0.3-second hard receive deadline, without extension for partial reads. A selector
multiplexes at most eight active clients, reserves one slot for admin, accepts
once per endpoint per cycle with admin first, and caps response writes at 0.1
seconds. Excess connections close; malformed/oversized verify requests deny.
Wrong verify UID is rejected using SO_PEERCRED before receiving a body. Admin
always receives fixed `UNIMPLEMENTED/DENY` without waiting for any request body.
For verify, duplicate, malformed and surplus fields deny;
only `operation` is accepted. Kernel SO_PEERCRED supplies connect-time PID/UID/GID.
Only exact `verify` from the trusted backend UID yields
`TRANSPORT_ALLOWED_TRUE`, always accompanied by `CREDENTIALS_VERIFIED_FALSE` and
`credentials_verified=false`. This is transport admission, never real auth.
Every admin connection denies, including root mutation requests and incomplete
or invalid requests. No operator authorization
boolean or reusable approval exists. Each connection closes after its response;
termination stops new decisions, closes pending clients, and
listener cleanup runs on exit. A maximum ten-second process lifetime bounds the
demo, with a shorter fixture lifetime. Restart retains no approvals or state.
Only a fixed READY marker is logged, never requests or exception details.

The three units in `tests/fixtures/linux_identity_broker_systemd/` have explicit
Service links, FileDescriptorName, Accept=no, modes and named identities. The
dedicated unprivileged service uses an absent root-controlled non-home package,
ProtectSystem=strict, ProtectHome, NoNewPrivileges, empty capabilities and AF_UNIX
restriction. Its private runtime directory does not own either socket. There is
no StateDirectory: this transport-only illustration has no registry and must not
cause state-directory ownership changes. ExecStart uses trusted named
`--backend-user homehub-backend --backend-group homehub-backend`, alternatives to
numeric test CLI UID/GID; no unknown groups or accounts are installed. No Install
section is provided, and the deliberately absent DO-NOT-INSTALL condition remains.
Descriptor order across multiple socket units is unspecified; name-position
mapping accepts either order and rejects concrete socket mismatches.

`tests/test_linux_broker_socket_prototype.py` runs parser negatives and static unit
text assertions on Windows using ConfigParser. These checks do **not** establish
systemd grammar or acceptance by a running manager. Linux-only tests launch the
exact source with real
inherited listeners, exercise kernel peer UID admission/denial, admin denial,
payload limits, timeout, startup failures, termination and restart. The separate
root tier requires `HOMEHUB_DISPOSABLE_LINUX_BOUNDARY=1`; only child processes drop
UID/GID/groups in a dedicated launcher subprocess before exec, with no pytest
preexec_fn. Only the unique disposable pytest tmp root is chmod 0755; ancestors
remain untouched. The launcher enters that root before dropping UID, and broker
custody snapshots relative to this explicit anchor avoid traversal of private
pytest ancestors; admin remains behind its unchanged 0700 parent. Verify is provisioned root:GID41001 mode 0660 **before** startup
and trusted CLI `--backend-gid=41001` is supplied. The full broker runs as distinct
UID/GID41003 with no supplementary groups. A UID41001 backend accesses verify,
receives credentials_verified=false and cannot traverse admin; the broker accepts
the inherited root admin FD subject to the explicit provisioner trust dependency.
It creates no accounts. A Linux saturation test holds twelve incomplete verify
connections, checks prompt admin denial, bounded FD cleanup and prompt SIGTERM.
These are subprocess/kernel ABI tests, **not an actual systemd launch**.

Corrective Windows validation: 72 passed, 26 Linux-only tests skipped across the
prototype and prior boundary suite; unique disposable TEMP basetemp, Python -B
and no pytest cache. `git diff --check` passed. Linux exact-source
and disposable root tests must run in the orchestrator's separate disposable
container. External `systemd-analyze verify` is a separate grammar gate, followed
by real PID1 systemd activation, restart/stop and hardening lifecycle gates. No
manager is available here; neither ConfigParser nor subprocess/kernel tests prove
manager acceptance. No systemd command, installation or live validation occurred.
Remaining gates include genuine fresh operator authorization and recipient
authentication, a real broker storage/journal/durability protocol, independent
backend rollback floor and actuator enforcement, root-controlled package/dependency
and ACL audit, an approved safe installer, recovery/restore invalidation gates,
and measured manager activation. No production behavior or deployment changes.

## November 14, 2026: second source-only protocol implementation

The inactive verify-only client and separate browser/kiosk issuance contract are
implemented locally; see [the foundation's second source milestone](SECURITY_IDENTITY_FOUNDATION.md#november-14-second-source-milestone-inactive-broker-and-browser-issuance)
for exact wire schemas and trust gates. This does not change the selected OS
broker architecture, authorize installation or complete #287/#293. Neither the
synthetic storage broker nor the transport-only Linux prototype supports this
new AuthN protocol. There is no socket connector or live issuer.

The client requires trusted current generation AND revision observations to
reject delayed responses across restore and security mutation; implementing and
proving that protected freshness channel remains an operational prerequisite.
Issuer evidence is opaque trusted injection, not proof from HTTP, a same-UID
process or a synthetic signature. Uncertain issuance must be revoked through the
separate privileged owner before retry; logout/rotate/restore require durable
broker lifecycle transitions. No application DB fallback, pairing route, TLS
change, host action or physical write was introduced. Offline tests prove only
the source contracts; independent review and all operational/physical acceptance
gates remain open. #461 guarded inline controls retain their original L1-L6,
manual/ScreenSync/final-owner and kiosk/iPhone acceptance requirements.

## November 14, 2026: standalone protected-state SOURCE milestone (inactive)

Local uncommitted implementation in
`worktrees/identity-287-broker-session-20261114` adds the stdlib-only package
`security/homehub_identity_broker/` and
`tests/test_identity_broker_state_runtime.py`. This is source engineering for
#287 -> #293 -> #461, not installation, activation, credential provisioning,
independent security review, or physical acceptance. The existing redesigned
Home and guarded inline L1-L6 controls remain the primary product goal.
Network reads were prohibited for this task; issue state was not freshly checked.

`runtime.py` implements exact version-1 length-prefixed bounded ASCII VERIFY,
strict duplicate/key/type validation, fixed source/profile/lane grants,
browser_session/native_bearer distinction, salted PBKDF2-HMAC-SHA256 verifiers
(600,000 iterations), per-use expiry/revocation and correlated generation/revision.
`policy.py` is an independent fixed inventory; a test compares it to backend
policy without importing the backend into the broker. No SQL/admin opcode,
token echo, issuer, settings, backend DB dependency or network transport exists.
Malformed envelopes raise a fixed sanitized error for a future transport to close;
valid requests receive exactly a verified response or bounded denial envelope.

The private SQLite state is independently authenticated by an HMAC journal and
permanent denial fence using separately injected key material. The MAC covers
all schema/version/generation/revision fields and every credential verifier,
profile/source/grant/kind/revocation/expiry plus reserved rotation/delivery queues.
Queues must be empty until an authenticated recipient delivery protocol exists;
nonempty queues quarantine rather than pretend to implement delivery.
Private rotate accepts prehashed replacement state, revokes the old record with
zero overlap and enforces unchanged principal/profile. Private restore from
healthy state empties every credential and changes generation. No recovery of
quarantined state, re-enrollment or token minting is implemented.

Transitions serialize with verification through one Broker object's thread lock:
PENDING denial fence fsync/replace/directory-fsync, PENDING journal, SQLite FULL
commit plus directory barrier, COMMITTED journal, DB reread, COMMITTED fence,
full recheck, acknowledgment. Missing/mismatched/PENDING/stale state and leftover
exclusive `.next` files quarantine; no automatic bootstrap, repair or cleanup.
Initial error injection found that an fsync failure before rename could otherwise
leave old committed state readable after reopen; persistent `.next` evidence now
closes that path. In-memory uncertainty poisons the current object, with a
best-effort persistent PENDING write. Simultaneous objects/processes are NOT
supported: a future protected singleton launcher is mandatory.

`offline_fixture.py` is deliberately separate from serving code. Its explicit
fixture-intent flag is not OS authentication and cannot authorize live bootstrap.
Only tests supply fake prehashed records and a fake HMAC key. No real credential
or operator identity was created. File fsync and POSIX directory fsync are source
operations; Windows explicitly refuses the default directory barrier. Tests inject
a model barrier and use disposable registry and separate anchor directories.
Exception hooks are not actual power loss. If storage cannot durably record final
uncertainty, Python cannot prove persistence; Linux filesystem crash/power-loss
and operational quarantine remain gates. Matching root rollback of registry,
journal/fence and key remains undetectable, not TPM/monotonic proof.

The optional Linux connector/daemon was deferred to finish the state/protocol
correctly. Existing `tests/support/linux_broker_socket_prototype.py` remains
transport-only, disconnected from this package. No root service or operator
shortcut was created. Required next gate: independent source review, then a
separately authorized disposable Linux exact-source durability and singleton/
OS-custody integration harness, inherited socket and SO_PEERCRED checks, admin
default-deny, and protected fresh generation/revision observer. Before any live
activation additionally prove root-owned package/interpreter/dependencies/systemd,
ACL/MAC/mount and socket replacement safety, backup exclusion, an independently
protected backend downgrade floor, trusted OS-local recovery and recipient-bound
credential delivery. Native/browser/kiosk/TLS migration and witnessed Home/iPhone
L1-L6/manual/ScreenSync/final-owner acceptance remain separate gates. No install,
service restart, host mutation, deployment or device writes occurred.

Source milestone validation (final current-code run): **330 passed, 22 skipped**
in 40.31s across `test_identity_broker_state_runtime.py`,
`test_identity_broker_verify_client.py`, `test_identity_broker_protocol.py` and
`test_linux_broker_socket_prototype.py`. Skips are Linux/POSIX gates. Executed
with absolute `C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B`,
APP_ENV=testing, PYTHONDONTWRITEBYTECODE=1, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1,
`pytest -p pytest_asyncio.plugin -p no:cacheprovider`. Ruff `check --no-cache`
passed on the package and new test; `git diff --check` passed. Tests cover
independent journal/DB tampering, authenticated invalid policy, missing stores,
fake bootstrap/reopen, expiry including expiry during PBKDF2, exact existing
client compatibility, native/browser kind, revision/generation, app restore,
identity restore invalidation, revoke/rotate, PENDING interruption at each stage,
file and directory fsync failures at every anchor, SQLite failures, secret-error
suppression and a verification/revocation race. These are synthetic exception
and disposable-storage proofs, not real service/systemd/power-loss acceptance.

Exact incremental paths (all other pre-existing work left intact):
`security/homehub_identity_broker/__init__.py`,
`security/homehub_identity_broker/policy.py`,
`security/homehub_identity_broker/runtime.py`,
`security/homehub_identity_broker/offline_fixture.py`,
`security/homehub_identity_broker/README.md`,
`tests/test_identity_broker_state_runtime.py`, this document and
`docs/SECURITY_IDENTITY_FOUNDATION.md`. Branch remains
`work/287-broker-session-contract-20261114`, HEAD
`1f5d296e2c8f0504b8718ceedfaba89b1a961b8a`; nothing staged or published.

## November 14, 2026: inert Linux VERIFY transport source boundary

In the same local worktree/base, `security/homehub_identity_broker/linux_verify_server.py`
adds a guarded **fixture-only, DO-NOT-INSTALL / NOT DEPLOYABLE** transport around
the existing protected-state Broker.process. Production construction is refused.
No CLI, production launch path, unit, enrollment/issuance/rotate socket, backend
connector or ASGI change exists. The prior prototype remains transport-only and
untouched. No change to the original #461 design/lighting files accompanies this
milestone. All prior tracked/untracked work remains local and uncommitted.

Injected systemd ABI metadata is checked against exact descriptor/path snapshots;
it is not privileged attestation. Verify authenticates kernel SO_PEERCRED before
reading data, permits only injected fixture UID/optional GID, requires EOF after
one four-byte-framed <=2048-byte request and delegates only to strict existing v1
verification. Admin closes before body and never invokes Broker. Nonblocking
admission/I/O bounds active clients and whole exchange time; zero broker queue
and one off-loop worker prevent PBKDF2 blocking the selector. Late decisions are
discarded, capacity remains held until actual completion, stop closes pending
clients without unlinking sockets, and same-object restart refuses an active old
worker. This is not cross-process singleton or interruptible-storage proof.
The [package README](../security/homehub_identity_broker/README.md#linux-verify-transport-experiment-do-not-install--not-deployable)
records limits, fixture trust boundary and remaining custody/lifecycle gates.

Owner-supplied Latitude evidence (not independently fetched): Ubuntu 24.04.5,
systemd 255, kernel 7.0.0-42-generic; /var, /var/lib, /run and /etc/systemd/system
root:root 0755; dedicated identities, broker units and data directories absent.
Existing home-hub.service active and the named 04:30 application-DB backup script
describe only that snapshot. They prove neither privileged custody nor restore
floor, backup exclusion/absence of other backups, nor authority for host writes.
The separate disposable kernel 6.18 primitive probes did not execute this source.

Required gate: execute `tests/test_linux_identity_broker_verify_server.py` on an
actual disposable Linux kernel, using these exact source files and synthetic
tmp fixtures, without global sudo. Windows skips are not Linux verification.
The Linux cases include peer denial before body, peer proof/token/nonce,
malformed/truncated/oversized/duplicate/surplus frames, revoked/expired state,
congestion/admin denial, deadlines/late results, same-object restart, real SIGTERM
through a fixture-only launcher, and descriptor mismatch. Actual systemd activation,
distinct dedicated principals, root custody/ACL/MAC/mount/replacement safety,
cross-process singleton and filesystem crash/power-loss remain additional gates.

Before any production composition additionally require hardened root-owned
packaged executable/interpreter/dependencies, separately reviewed root provisioner
attestation and real socket units, separate non-backend admin principal, protected
key/state/journal backup exclusions, fresh protected generation/revision observer,
root deployment/downgrade floor, approved issuance/recovery and recipient/session
lifecycle, proxy/TLS/native/kiosk/iPhone rollout, separately authorized security
integration/deployment, #293 and #461 guarded L1-L6 acceptance. No installation,
network fetch, publication, host/account/credential change or live action occurred.

Final Windows exact-source validation: **399 passed, 50 skipped in 77.80s** across
`test_linux_identity_broker_verify_server.py`, `test_identity_broker_state_runtime.py`,
`test_identity_broker_verify_client.py`, `test_identity_broker_protocol.py` and
`test_linux_broker_socket_prototype.py`. Nine new Windows-runnable static cases
passed; all 28 new actual-Linux cases and 22 existing Linux/POSIX cases skipped.
Command used `C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m pytest
-p pytest_asyncio.plugin -p no:cacheprovider <the five files> -q`, APP_ENV=testing,
PYTHONDONTWRITEBYTECODE=1, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1. Both new Python files
compiled without bytecode output; Ruff `check --no-cache` on the broker package
and new test and `git diff --check` passed. This does not claim any new Linux
kernel test passed. Exact incremental files for this transport task are the new
module and new test, the package README, this document and
`docs/SECURITY_IDENTITY_FOUNDATION.md`; existing runtime/policy/client/prototype,
ASGI and #461 design/lighting sources were not edited.

## November 14, 2026: next offline verify integration bridge

Task base: clean branch `work/287-broker-session-contract-20261114`, HEAD
`01824867a796a3386205dccdad7839c1ef9d1a46`, in the existing protected Sandbox
worktree `identity-287-broker-session-20261114`. The task brief supplied draft
#533 head/tree/CI context; no network fetch or independent hosted CI verification
was authorized or attempted. Registry metadata showed earlier tasks completed
and the current Write task running; no second worker/subagent was launched.

Source outputs are `security/homehub_identity_broker/linux_protected_verify.py`
(separate Linux service adapter, root-only proof seam, exact path/FD checks and
protected cross-process flock lifetime),
`backend/services/linux_identity_broker_io.py` (async ProtectedVerifyIO connector),
and `tests/test_linux_protected_verify_integration.py` (synthetic exact-pair tests).
The existing server now shares its bounded transport internally while preserving
the fixture-only constructor guard; VerifyClient changes only its module status
documentation. This note, the identity foundation note and package README record
the narrower result and remaining gates. No runtime/bootstrap/UI/lighting,
policy/runtime state algorithm, fixture issuer or installation changes occur.

The [package bridge contract](../security/homehub_identity_broker/README.md#november-14-offline-protected-integration-bridge-blocked-at-os-attestation)
details invariants. **Blocker:** shipped `RootCustodyProof.check` always denies.
Caller subclasses and fabricated policy objects do not grant custody. No safe
systemd/root mount/key/storage attestor is implemented without actual privileged
OS integration; the task explicitly permits this fail-closed narrower outcome.
Future reviewed root packaging must implement that interface independently and
bind exact descriptors/policy/storage, never flip the fixture guard or install a
permissive Python provider. Native tests intentionally patch missing custody and
distinct-principal validation for disposable paths/same-process synthetic IDs.
Their successes would prove socket/protocol/locking mechanisms, not root custody.

The service holds its kernel lock until its final worker exits, quarantines
custody/state mismatch, and never creates/unlinks listener or lock paths. No
admin channel exists. The connector checks dedicated broker SO_PEERCRED before
credential bytes, rechecks pinned socket/ancestor identities, enforces bounded
framing/exact EOF/deadlines/capacity and closes without raw token diagnostics.
No retry, reuse or grant cache. Directory/ACL errors have no security fallback.
No Python deadline can interrupt a blocked local filesystem syscall; supervisor
termination and protected filesystem behavior still require OS acceptance.

Next gates remain independent trusted **fresh** generation/revision observation,
actual issuance/operator/recipient delivery and lifecycle reconciliation, reviewed
root packaging/attestor, exact-source disposable Linux execution, filesystem
crash/power-loss and backup/downgrade floor acceptance, secure client/TLS rollout,
separately authorized live integration/deployment and physical #293/#461 delivery.
No source change in this task authorizes a live broker, browser issuer or Hue
write. No secret store, real key/token, host/device/account/credential mutation,
tool installation, network fetch, Git publication, deployment or cleanup occurred.

Windows validation: **417 passed, 77 skipped in 80.19s** across
`test_linux_protected_verify_integration.py`,
`test_linux_identity_broker_verify_server.py`, `test_identity_broker_state_runtime.py`,
`test_identity_broker_verify_client.py`, `test_identity_broker_protocol.py`, and
`test_linux_broker_socket_prototype.py`. The new suite contributes **18 passed,
27 native Linux skips**; existing suites contribute 399 passed/50 skips. Counts
overlap focused runs; they are not additive. A final **18 passed, 27 skipped in
2.46s** run verifies final source compilation, default-denial and policy checks,
including distinct service/backend groups. Native listener type/non-inheritance
checks remain unexecuted on Windows. Fingerprints identify final source below. Used existing
`C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m pytest
-p pytest_asyncio.plugin -p no:cacheprovider <six files> -q`, `APP_ENV=testing`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. Ruff
`check --no-cache` on the broker package, connector, client and new test passed;
tracked diff whitespace checks passed. No native test or systemd check ran in
this Windows Sandbox. Exact-source Linux execution remains a separate next gate,
using the same six suites and disposable synthetic state, without sudo/install.

Final source file SHA-256 fingerprints (raw workspace bytes; no secret material):

| Source output | SHA-256 |
| --- | --- |
| `security/homehub_identity_broker/linux_protected_verify.py` | `27315E616BA7B51BA9328FF3ADCC7E541E482AF8C5B793FC6FEBA96C78A43954` |
| `security/homehub_identity_broker/linux_verify_server.py` | `7CDB1597AC785DD8253F002278A82FBB1EBB58D309B6BDCF632E9A8B93BDCB29` |
| `backend/services/linux_identity_broker_io.py` | `128E2BF4979DE5CED3C560518D32B039D2211F05AC83D904B23950B2E4A0B990` |
| `backend/services/identity_broker_verify_client.py` | `9A63EEB7B8BB553C91F386F8112D91E656D31E1A8C5239C4778E0003F1AA7DAA` |
| `tests/test_linux_protected_verify_integration.py` | `61A393C78CCEE20FF8905C42C8656B7237D54FF8D3A7E88497B342E58C640AD2` |

Preserve these bytes for exact-source Linux testing, or explicitly record any
Git CRLF/LF normalization and recompute fingerprints. Runtime/policy dependencies
remain at the named task base. All eight incremental paths are unstaged and
uncommitted; the other three paths are the package README and the two security
documents. No main/other-worktree changes were made.


### November 14 P2/P3 independent-review remediation (uncommitted)

This follow-up supersedes the preceding source fingerprints for changed files.
P2 now uses explicit `LaunchPolicy.creator_peer` (exact PID/UID/GID) for client
SO_PEERCRED comparison, before request bytes. The unavailable root attestor must
bind this value to trusted listener creation/provenance; root UID or caller policy
alone is not trust. Root/PID1-created inherited sockets need not report the later
nonroot acceptor. Production remains denied by the exact shipped proof class.
P3 now closes the owned listener on preflight custody denial even when transport
serve never runs, retaining worker-before-lock-release ordering and never unlinking
caller paths. The initial quarantined state also goes through this finalizer.

Changed in this follow-up only: `backend/services/linux_identity_broker_io.py`,
`security/homehub_identity_broker/linux_protected_verify.py`,
`tests/test_linux_protected_verify_integration.py`,
`security/homehub_identity_broker/README.md` and this document. The pre-existing
eight-file delta is preserved; no additional file is introduced.

Final Windows validation, existing Sandbox venv Python, `-B`, APP_ENV=testing,
PYTHONDONTWRITEBYTECODE=1, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1,
`-p pytest_asyncio.plugin -p no:cacheprovider`:

- `tests/test_linux_protected_verify_integration.py`,
  `tests/test_linux_identity_broker_verify_server.py`,
  `tests/test_identity_broker_verify_client.py`,
  `tests/test_identity_broker_protocol.py`,
  `tests/test_identity_broker_state_runtime.py`: **393 passed, 57 skipped, 87.55s**.
- `tests/test_linux_broker_socket_prototype.py`: **29 passed, 21 skipped, 2.26s**.
- Total disjoint final runs: **422 passed, 78 skipped**. Linux skips are NOT verified.
- Ruff `check --no-cache` passed on the five Python source/test outputs below.
  All five compiled in memory with `compile`; no bytecode cache was written.
  `git diff --check` passed. No install, network, commit or live action occurred.

The first run had four synthetic-test failures (389 passed/57 skipped) because
Windows lacks AF_UNIX and the mock replaced the global socket factory. The test
now injects a module-local socket facade, isolating asyncio; the final rerun above
passed. Synthetic coverage accepts exact PID1/root creator with nonroot service
policy, rejects acceptor credentials/other root PID/wrong GID before token bytes,
and checks preflight listener closure and lock-release ordering.

Next Linux gate: execute these same six suites from the exact source below,
including the newly added post-construction custody-loss test proving actual FD
closure, flock reacquisition, broker poisoning and preserved caller socket path.
Then independently review/authorize root attestor/packaging and prove actual
root/PID1-created listener handoff to a distinct nonroot acceptor; no synthetic
Windows tuple proves those kernel or OS-custody properties. All previously named
freshness, issuer, durability and production activation gates remain open.

Current raw-workspace source SHA-256 (normalization requires recomputation):

| Source output | SHA-256 |
| --- | --- |
| `security/homehub_identity_broker/linux_protected_verify.py` | `0142482A26FCDF580BD16FD7403D0202AD23E17ADAD2880B25FEA063F3CF7AE3` |
| `security/homehub_identity_broker/linux_verify_server.py` | `7CDB1597AC785DD8253F002278A82FBB1EBB58D309B6BDCF632E9A8B93BDCB29` |
| `backend/services/linux_identity_broker_io.py` | `9A2454F13E262A87B7DA011557F78FD41F387E08AE33CCC79D89D7D43F5188D3` |
| `backend/services/identity_broker_verify_client.py` | `9A63EEB7B8BB553C91F386F8112D91E656D31E1A8C5239C4778E0003F1AA7DAA` |
| `tests/test_linux_protected_verify_integration.py` | `9C9F8875D2CF4820C144CC3CBFA3EF800A1689EC747A94305BE3089813FD29E9` |
## November 14 Linux OS metadata blocker probe (local source only)

This bounded follow-up adds `linux_os_preflight.py` and
`tests/test_linux_os_preflight.py`; the package README describes its exact
observation/trust split. No runtime, backend, WebSocket, unit template or custody
proof changed. The public zero-argument probe performs actual Linux kernel
credential and held-dirfd metadata observations of only the fixed proposed
deployment. It never reads key/registry/config contents or accepts caller paths,
identity approval strings, floor assertions or executable commands. It detects
unsafe root ancestors, leaf type/mode/link/known-root-owner errors, symlinks
and persistent binding changes. The two deliberately broker-owned 0700 private
state directories cannot have their owner IDs independently authenticated here.
Their descendants, including WAL/SHM and pending anchors, are **uninspected** and
explicitly `private-ancestor-identity-unverified` rather than misclassified as
unsafe or absent. Account IDs are not authenticated through NSS; unknown
dedicated ownership and all private-child inspection remain missing.

The output is a bounded blocker report, never an authorization. All reports
retain missing root-controlled code/dependency closure, dedicated account and
supplementary membership, PID1 descriptor provenance, ACL/MAC, namespace/mount
alias protection, continuous custody/reboot/ABA, backup/crash durability and
independent external backend startup/deploy/rollback floor. A same-directory
floor file supplies no independent enforcement. `RootCustodyProof.check` remains
unconditional Denied. There is no startable service, installer or CLI. Native
tests use temporary files only and require no sudo; Windows native skips do not
prove these mechanisms. Next gate is exact-source disposable Linux execution
and review, then separately authorized root-controlled composition and OS
acceptance. Existing issuer/freshness/TLS/mobile/kiosk/#293/#461 gates remain.

Evidence is local to the named identity-287-broker-session-20261114 worktree,
HEAD `01824867a796a3386205dccdad7839c1ef9d1a46`, preserving the initial 13-path
dirty state. Owner-supplied draft #533 head `330e26e6bc16484fdb52a854cafc124d42fcacf4`
and green CI were not independently checked: network/issue retrieval/publication
were prohibited. No commit, ref update, install, credential, host/live write,
deployment, restart or cleanup occurred. The existing /ws provisioning blocker
and unconditional production custody denial remain in force.

Local Windows validation: focused preflight/custody/unit-contract/protected
integration suites **284 passed, 43 skipped**; the new suite contributes
**3 passed, 15 explicitly native Linux skips**. Ruff without cache, in-memory
compilation and `git diff --check` passed. No native Linux test was executed.
