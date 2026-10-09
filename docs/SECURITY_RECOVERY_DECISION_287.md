# #287 recovery architecture decision — proposed, NOT LIVE

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

**Next gate remains C (separately authorized read-only host-readiness inspection),
then D (explicit installation/recovery authorization).** This harness is offline
evidence only; #287 remains open and no live broker or enforcement is established.
