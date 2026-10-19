# #399 scheduled mirror candidate: OFF, plan only

2026-10-19 development handoff at `4156e2d93a7cdc991783d3831bb74ecd0e243aa5`.
A pure JSON planner is provided; no launcher, installer, task XML, registration
or activation is shipped here. There is no dormant activation command. Stable
installation identity and timeout policy remain open before installation review.
The [one-shot CLI](OBSIDIAN_SIMPLE_MIRROR_RUNNER.md) is the existing code boundary.

## Evidence and accepted behavior

The supplied #399 task input reports successful permanent Windows one-shot apply
and operator GUI acceptance at the base SHA. This is operator-reported, not
independently reproduced here; byte-exact personal-note and prior-backup hashes
were not persisted. No network or permanent Vault inspection is authorized here.
Automatic refresh remains OFF.

The supplied October 18 decision accepts rebuildable generated `HomeHub Source`,
brief mixed versions and Obsidian remaining open. Cooperative app-open write
races remain possible: this is not an atomic transaction or security boundary.
Older [sync proposals](OBSIDIAN_SYNC_DESIGN.md) and
[persistent Vault guidance](OBSIDIAN_PERSISTENT_VAULT.md) are superseded for this
runner where they require all-launch-path owner checks, app closure or directory
swaps. Do not restore those as blockers. Preserve notes, `.obsidian` and all
historical backups; never clean. Unknown or interrupted evidence requires review.

## Accepted cadence; task contract pending security review

| Item | Candidate |
| --- | --- |
| Identity | One exact named task; ordinary current user's SID, InteractiveToken, Limited; no password, elevation, service or machine task |
| Triggers | **ACCEPTED HOURLY + LOGIN**: user-specific logon plus hourly clock triggers while the ordinary user is signed in |
| Reboot | Resume after that user's logon; no logged-out unattended operation |
| Missed runs | No catch-up burst, wake-to-run or failure restart; next normal trigger only |
| Concurrency | MultipleInstances IgnoreNew plus existing one-shot exact-lock and pending-evidence refusal, including manual-run races |
| Network | No connectivity probe or alternate source; verified acquisition returns unavailable when offline, skipping that occurrence without retries |
| Action | Absolute pinned Python and stable reviewed launcher, fixed argv, exact Vault and expected-Vault; no shell, environment expansion or extra arguments |
| Lifecycle | Immutable versioned user-local reviewed bundle; no disposable worktree, Git pull or self-update |
| Reporting | Bounded fixed status and SHA labels; no exception text, transport payloads or contents; no persistent log by default |
| Preservation | No backup rotation, cleanup, settings writes, lock removal or forced task replacement |

Cadence authority is the operator decision in [#399 comment 6260713157](https://github.com/agatte/home-hub/issues/399#issuecomment-6260713157),
as supplied to this offline task: once per hour plus login, replacing the four-hour
proposal. No network verification was performed. Ordinary user only, InteractiveToken,
least privilege (Scheduler XML `LeastPrivilege`, API `Limited`); logged-off triggers
are skipped, no backlog catch-up, restart or wake. The proposed calendar is daily
local midnight with PT1H repetition for P1D, plus that user's logon trigger.
Logon and an adjacent hourly trigger can both occur; IgnoreNew skips overlap,
not sequential invocations. DST/clock behavior needs physical Windows verification.

At the accepted 58-file snapshot each occurrence acquires 58 raw requests plus
five anonymous GitHub REST requests for identical source or six for changed
source. Login adds another occurrence. Counts vary with source membership;
shared quotas, raw limits and availability mean no rate-limit guarantee.
Offline acquisition fails closed with no fallback or retry.

`scripts/plan_obsidian_schedule.py` prints deterministic JSON to stdout only.
All eight parameters are required: `--user-root`, `--bundle`, `--python`, `--vault`,
`--expected-vault`, `--user-sid`, `--source-commit`, `--manifest-sha256`.
No environment defaults, extra arguments, credential, elevation, registration
or activation flags exist. Missing parameters refuse. It never probes a path,
imports the writer, creates files, calls Scheduler, spawns or accesses network.
Its process disables bytecode caching; direct use should also use `python -B`.

The plan is disabled and explicitly unverified, not importable task XML. Its
future action record names reviewed user-local Python with `-I -B` and a fixed
`launch_obsidian_mirror.py` in the exact versioned bundle. That launcher does
not exist in this slice and the action must not be executed. The fixed CLI argv
records the existing one-shot apply, not a second writer. The bundle must be
`<explicit C:\Users\ordinary-user>\AppData\Local\HomeHub\ObsidianMirror\<40hex SHA>`;
worktrees cannot be installed sources. Python must be an explicit user-local
`python.exe`; the planner does not establish its provenance. No secrets are inputs.
Lexical validation is not host identity, ACL, reparse, pin or review verification.
Caller-provided SHA/digest labels cannot prove source review or bless a bundle.

Keep check-only evaluation separate from approved scheduled apply. An approved
occurrence calls the CLI once with fixed apply mode and its required approval
argument. Do not check then apply as two acquisitions or treat check exit 1 as
write approval. Identical commit writes nothing; update reacquires and validates
source, seals backup first and produces the completed receipt.

## Stable installation and integrity gate

Review exact stable user-local version directory, interpreter, Vault spelling and
user identity before generating an actionable task. Installation needs separate
host approval. Do not install from this worktree or align host main. Retain old
bundles without cleanup.

Pin reviewed source Git SHA plus SHA-256 for launcher, complete transitive local
module bundle, interpreter and configuration. Enumerate dependencies from code,
not just the entrypoint. Pin the manifest digest in the separately reviewed task
action/launcher trust anchor; an editable self-blessing manifest is insufficient.
Reject missing, added, changed, linked/reparse files and untrusted roots before
import/spawn. Isolate Python imports from working directory, user site and
environment; disable bytecode writes. Test compatibility with the selected
installed Python before registration. Pins detect drift, not a malicious same-user
actor able to rewrite task and trust anchor, nor all validation/use races.

## Runtime bounds and refusal policy

Per-request transport timeouts do not bound total runtime as file count grows.
The inert plan records PT0S (no scheduler limit) and AllowHardTerminate=false
to avoid termination mid-apply; this is not approval for unbounded production
runtime. Resolve a safe runtime policy after synthetic worst-case measurement. Forced
scheduler termination can interrupt apply after backup/staging begins. Timeout,
lost child status, malformed output or unknown exit requires manual review with
all evidence retained, never immediate retry. A launcher must wait for its child
and return status; Windows acceptance must prove termination leaves no orphan
writer. Do not ship a detached launcher with a misleading execution bound.

| Exit | Interpretation |
| --- | --- |
| 0 | no_change or updated; validate bounded JSON and SHA fields |
| 1 | update_available only in check-only evaluation; refuse in apply configuration |
| 2 | Refused or failed review evidence; preserve evidence, no retry |
| 3 | Source unavailable; skip, no snapshot fallback or retry loop |
| 4 / unknown | Review required; retain evidence |

Later periodic triggers may still launch after refusal. Existing lock/pending
evidence must continue to refuse. No repair or cleanup is permitted. Disable the
exact task for investigation only under separate operator authorization. A
persistent latch suppressing all future launches would need separately reviewed
write scope; none is introduced here.

## Verification and next gates

Existing offline tests are `tests/test_run_obsidian_simple_mirror.py`,
`tests/test_obsidian_simple_mirror.py` and
`tests/test_obsidian_raw_blob_transport.py`: mocked acquisition, synthetic Vaults,
attempted-write interception, malformed arguments, unavailable source, exact
target and lock/pending refusals, backup and completed receipt. These prove
one-shot contracts, **not scheduler or integrity-launcher acceptance**.

Before executable scheduling is reviewable, add tests for:

1. Default and malformed config and each single activation flag: zero task,
   process, network and write calls before accepted preflight. Offline source:
   mocked acquisition, zero Vault mutations, no fallback or retry.
2. Deterministic idempotent dry-run with no timestamp, directory creation, import
   cache, subprocess or accidental registration/start call.
3. Exact argv for spaces and hostile quoting; reject aliases, environment
   expansion, unexpected fields/modes and mismatched Vault identity.
4. All bundle/interpreter/config pin mismatches before import/spawn, module
   shadowing, reparse roots and manifest trust-anchor changes.
5. Mocked bounded child output/status/timeout ownership, IgnoreNew parameters,
   manual-lock concurrency refusal and no retry after failure.
6. Independently reviewed installation and activation authorization semantics;
   no executable registration/activation path before that review and approval,
   no existing task replacement, credentials or global-policy changes.

Cadence/logon/missed-run policy is accepted. Project Admin next resolves timeout policy, exact
bundle trust anchor and target, then reviews implementation and tests. Separately
authorize publication, stable host installation, disabled registration and
activation. None is authorized by this development task. At activation ask about
optional app-closed preference; closure is not required by the accepted contract.

After approved activation, record exact task definition, SID, bundle pins, target
and rollback (disable only the exact task; retain Vault, backups and bundles).
Physically verify reboot/logon survival, offline skip, no-change/forward update,
Obsidian-open behavior, notes/settings preservation, concurrent runs and
interruption refusal. Backups grow indefinitely with successful updates; discuss
capacity and manual review, never automatic retention cleanup. No live acceptance
is claimed here. This local uncommitted plan is not published GitHub evidence.

Local verification on 2026-10-19: the three test files above passed **76 tests
and 46 subtests**, using
`C:\Work\home-hub-project\main\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider`.
`C:\Work\home-hub-project\main\.venv\Scripts\ruff.exe check --no-cache`
passed for those tests and their three corresponding runner/mirror/raw-transport
scripts. `git diff --check` passed. No tools were installed or fetched; no live
source request, task operation or permanent Vault evaluation was performed.

## Local planner evidence (2026-10-19)

The planner and `tests/test_plan_obsidian_schedule.py` cover deterministic JSON,
no attempted path probes/process/network calls, rejected flags and aliases,
fixed action arguments, hourly/logon settings, logged-off skip semantics and
cache suppression without writer imports. Logged-off skipping is a declarative
InteractiveToken contract, not observed Scheduler behavior. Integrity refusal,
transitive hashes, isolated transitive imports and physical task behavior remain
unimplemented acceptance gates. A future launcher must verify pinned interpreter,
configuration and complete transitive module hashes against a separately trusted
manifest before imports, refuse drift and invoke only the existing one-shot CLI.
No live scheduled apply or physical acceptance is claimed by these tests.

Updated local validation: **108 tests and 46 subtests passed** across planner,
one-shot runner, raw transport and mirror tests using the approved venv Python
with `-B -m pytest -q -p no:cacheprovider`. Ruff `check --no-cache` passed for
those four test files and four corresponding scripts; `git diff --check` passed.
All changes remain local and uncommitted in
`C:\Work\home-hub-project\worktrees\obsidian-auto-399-20261019`, branch
`work/399-auto-schedule-20261019`, base
`4156e2d93a7cdc991783d3831bb74ecd0e243aa5`. The pre-existing candidate and runner
doc additions were retained and extended. No issue comment was published.
