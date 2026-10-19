# #399 scheduled mirror launcher candidate: OFF, not installed

Local Sandbox implementation, 2026-10-19, based on
`f91407d165fd1263319bbadc45586da3681560aa`, branch
`work/399-hourly-launcher-20261019`, worktree
`C:\Work\home-hub-project\worktrees\obsidian-hourly-launcher-399-20261019`.
Changes are uncommitted and unpublished. No permanent Vault, Scheduler, service,
Host Bridge, credentials or network was accessed by this implementation task.

## Authority and accepted behavior

The supplied #399 product contract and operator decisions are the offline issue
record for this task; GitHub was not fetched. October 18 accepted the regenerable
mirror, Obsidian remaining open, brief mixed versions and cooperative races.
Unknown edits, locks, interruptions and incomplete evidence refuse without cleanup.
Personal notes, `.obsidian` and historical backups remain outside refresh scope.
The supplied physical one-shot acceptance is operator-reported, not reproduced here.
Older atomic-swap/app-closure requirements do not block this simplified runner.

October 19 accepted hourly plus user-specific logon while signed in:
[#399 cadence decision](https://github.com/agatte/home-hub/issues/399#issuecomment-6260713157).
No logged-out operation, catch-up, wake, restart or retry. Automatic refresh is OFF.
The existing [one-shot CLI](OBSIDIAN_SIMPLE_MIRROR_RUNNER.md) remains the writer.

## Executable implementation

- `scripts/launch_obsidian_mirror.py`: default prints `{"status": "off"}`;
  no local writer imports or path probes. Scheduled execution requires both
  `--run --anchor <reviewed manifest SHA-256>` and Python `-I -B`.
- `scripts/package_obsidian_schedule.py`: default is OFF. Pure `--xml` builds
  disabled XML on stdout. Explicit two-key `--stage --approve-stage <exact bundle>`
  prepares a new bundle, never registers a task. No registration or activation
  API, password, elevated principal, shell invocation or task replacement exists.
- `scripts/obsidian_launcher_pins.json`: static candidate pins for the reviewed
  base revision's eight local writer modules plus this new launcher. The launcher
  never creates or updates pins. Candidate launcher bytes are additions to that
  base. The `source_commit` label is the baseline SHA, **not a claim that the base Git commit already contains this launcher**.
  Review and publish these additions before approving an installation; retain the
  exact file hashes as the candidate build identity.

The exact local import closure is `run_obsidian_simple_mirror`,
`obsidian_simple_mirror`, `obsidian_github_docs_source`,
`obsidian_raw_blob_transport`, `obsidian_source_verifier`,
`obsidian_verified_stage`, `manage_obsidian_vault`, `create_obsidian_pilot`.
The last two are transitive dependencies even though their management commands
are never called. An AST inventory regression test checks this closure.
Only these eight `.py` files, the launcher and `manifest.json` may exist in the
installed directory. Missing/extra files (including caches), pin changes,
reparse/symlink ancestors and path misbindings refuse before local imports.

The launcher compares a manifest's bytes to the **external task-action digest**,
then validates its exact schema, fixed base SHA, module set, canonical Windows
paths, process-token SID/profile/elevation/session and exact interpreter path/hash.
The bundle must be exactly
`C:\Users\<ordinary user>\AppData\Local\HomeHub\ObsidianMirror\f91407d165fd1263319bbadc45586da3681560aa`.
Python must be explicitly user-local; Vault must be explicitly under that user's
profile, outside the bundle. No environment identity or target default is used.
The current process must be unelevated and outside session zero. Scheduler's
InteractiveToken principal is the additional signed-in execution constraint.

Verified module bytes are retained in memory and imported by an explicit loader;
module preloading refuses. Isolated Python excludes working-directory/user-site
imports. The selected Python installation, standard library, DLLs and its ordinary
user profile ACLs still need independent host review. Hashing `python.exe` alone
is not a signature for the full Python runtime. Launcher self-checks detect drift
in a cooperative installation; they cannot defend against malicious code replacing
the launcher itself. Same-user malware resistance is explicitly out of scope.
No complex anti-malware/ACL framework is introduced.

The launcher calls the existing CLI exactly once, in process, with fixed
`--apply --approve-local-evaluation --vault <fixed Vault> --expected-vault <same>`.
It does not perform a separate source acquisition/check. Source unavailability
skips without fallback; existing writer lock/pending checks protect manual races.
No child process exists to orphan. The only output is a bounded status JSON with
validated SHA labels; incidental stdout/stderr is discarded, report capture is
limited to 512 characters, and exception contents are never emitted. There are no
persistent logs. Both launcher and package builder refuse malformed arguments with
one fixed bounded JSON status and exit 2, without echoing argv to stderr; explicit
`--help` retains its fixed display and successful exit. Strict flag spelling remains
required (`allow_abbrev=False`). Invalid report/status/exit requires review, never an internal retry.

## Package and XML interface (future approved operator use)

All examples here describe a future approved host operation, **not authorization**.
Use the reviewed ordinary user's Python with `-B` for the package builder. Its
`--spec-json` argument is one literal JSON object, not an environment expansion or
shell-generated command. Required exact keys:

| Key | Value |
| --- | --- |
| `source_commit` | Fixed base SHA above |
| `user_root` | Exact `C:\Users\<ordinary user>` |
| `sid` | Reviewed ordinary current-user SID |
| `bundle` | Exact versioned user-local directory above |
| `python` | Reviewed user-local absolute `python.exe` |
| `python_sha256` | Independently checked interpreter digest |
| `vault` | Exact existing accepted Vault path |
| `files` | Exact filename-to-SHA256 mapping from static pins |

`--spec-json <object> --xml` emits disabled XML without probing paths or writing
anything. The action contains `-I -B "<bundle>\launch_obsidian_mirror.py" --run
--anchor <manifest digest>`. Manifest bytes are deterministic UTF-8 JSON with
sorted keys and compact separators, no newline. Independently review these exact
bytes and the resulting digest/action; a computed digest is a review artifact,
not automatic approval. Never regenerate a new manifest to bless unexpected drift.

After separate installation approval, the staging interface is
`--spec-json <object> --stage --approve-stage <exact bundle>
--reviewed-pins-sha256 <independently reviewed static pins file digest>`.
Both keys and the pins digest are required. The bundle parent must already exist
and have separately reviewed identity/permissions. Staging verifies all source
bytes and interpreter before creating the exclusive new version directory;
existing destinations refuse. Partial packaging is retained for manual review;
there is no overwrite, cleanup, repair, self-update or backup rotation.
No actual stable host bundle was prepared in this task; tests stage TEMP only.

The pure XML builder specifies exactly `HomeHub Obsidian Mirror Refresh`,
InteractiveToken, LeastPrivilege, matching user logon and daily midnight calendar
with PT1H/P1D repetition. Settings are Enabled=false, IgnoreNew,
StartWhenAvailable=false, WakeToRun=false, no RestartOnFailure,
ExecutionTimeLimit=PT0S, AllowHardTerminate=false; battery transitions do not kill
writes. It supplies absolute interpreter, launcher and working directory.
Logon and an adjacent hourly trigger can run sequentially; IgnoreNew only skips
overlap. DST and missed-trigger semantics still require physical acceptance.

## Runtime policy and remaining gates

Runtime uses the existing bounded per-request transport (12 seconds per request),
bounded file sizes/membership and in-process ownership. **There is no total wall
clock deadline.** Scheduler must not kill a write: PT0S and no hard termination
are deliberate. A slow/hung instance holds IgnoreNew until it finishes; external
logoff/shutdown/kill can still interrupt the process. Preserve all interruption
evidence. Before activation, measure worst-case acquisition on the selected host
and approve this no-forced-termination policy. A safe total deadline would require
cooperative cancellation before the writer's mutation boundary, not a child kill.
No physical runtime/termination proof is claimed by offline tests.

At the previously accepted 58-file snapshot each occurrence uses 58 anonymous raw
requests plus five GitHub metadata requests if identical or six if changed.
Offline/rate limits can skip occurrences; no availability/quota guarantee is made.
Successful updates retain backups/completed evidence indefinitely. Capacity and
manual review remain necessary; **no automatic backup retention or cleanup**.

Remaining concrete gates, in order:

1. Independent review/publication of candidate code, static pins and tests. Review
   exact ordinary-user identity, user-local Python/runtime, fixed Vault and stable
   bundle manifest/action digest. No source worktree may be the installed bundle.
2. Separately authorize host bundle preparation. Verify pinned installed bytes
   and Python compatibility; preserve prior versions. No host preparation here.
3. **Installer integration remains intentionally unimplemented:** this slice uses
   the permitted pure XML builder. A future registration adapter must require two
   exact operator-controlled keys plus separate disabled-registration approval,
   create only the named disabled task, refuse an existing task, and neither start
   nor enable it. XML must first be schema/import tested on Windows with a mocked
   adapter; actual registration needs separate host authorization. Merely staging
   a bundle or generating XML grants neither registration nor activation.
4. Separately approve activation. Record task definition/digest, SID, interpreter,
   bundle pins and target; offer optional app-closed preference (not a requirement).
   Physically verify logon/reboot, logged-off skip, offline/no-change/forward update,
   Obsidian-open behavior, personal notes/settings/backup preservation, manual
   overlap and interruption refusal. Rollback is separately authorized disable of
   only the exact task; retain Vault, bundles, locks and backups.

`plan_obsidian_schedule.py` remains an older pure advisory JSON interface; its
`implemented=false` and gates describe that planner output, not this launcher.
No registration/activation shortcut was added to it.

## Offline evidence

`tests/test_obsidian_schedule_launcher.py` exercises inert defaults and single
keys, malformed/unknown and hostile 1000-byte arguments with no stderr or operations,
explicit successful help, pure deterministic disabled XML, exact module
closure/static pins, identity/path/interpreter/module/manifest tampering, reparse
refusal, retained verified import bytes, package refusal before writes, exclusive
TEMP staging, bounded output and actual one-shot synthetic Vault outcomes.
The existing planner/runner/mirror/raw transport tests remain part of validation.
These are local fixture results, not real Scheduler, ACL or permanent Vault proof.

Local validation on 2026-10-19: **174 tests and 46 subtests passed** with approved
`C:\Work\home-hub-project\main\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider`
against `test_obsidian_schedule_launcher.py`, `test_plan_obsidian_schedule.py`,
`test_run_obsidian_simple_mirror.py`, `test_obsidian_simple_mirror.py`, and
`test_obsidian_raw_blob_transport.py` under `tests/`. Approved Ruff 0.15.10
`check --no-cache` passed for those tests and corresponding six scripts
(launcher, package, planner, runner, mirror, raw transport). `git diff --check`
passed. All fixture writes were disposable TEMP artifacts; no live source
acquisition, stable host package preparation, task registration or activation ran.
