# Home Hub Local Workspace

This document describes the Windows development-machine layout and ChatGPT
snapshot workflow. It is operational guidance, not product behavior; the
cross-system product contract remains `docs/PROJECT_SPEC.md`.

## Canonical workspace

The Windows 11 Home Hub workspace is:

```text
C:\Users\Anthony\Documents\home-hub-project\
├── main\       # canonical Home Hub Git checkout
├── worktrees\  # isolated Git worktrees for substantial changes
└── snapshots\  # created on demand by the ChatGPT snapshot helper
```

`main` is the canonical checkout. `snapshots\` is not required to exist until
the helper creates it. Substantial implementation/review work should use sibling
worktrees under `worktrees\` rather than scattered Desktop clones.

Remote Desktop Commander runs inside Windows Sandbox. The authoritative host repo remains `C:\Users\Anthony\Documents\home-hub-project\main`; RDC sees that same mapped checkout at `C:\Work\home-hub-project\main`. Sandbox path differences are expected and do not indicate a broken host recovery.

### Protected Windows Sandbox / host boundary

Protected Windows Sandbox is the normal environment for Windows-side Home Hub development, repo inspection, Codex work, and RDC shell/filesystem operations. The protected host-owned `.wsb` is the authority for what host filesystem state exists inside that environment; `-C`, an RDC allowed-directory setting, or a stale workspace copy of the `.wsb` is not a security boundary.

The finalized protected mapping treats the Sandbox itself as the filesystem/blast-radius boundary. Host `C:\Users\Anthony\Documents\home-hub-project` maps to `C:\Work\home-hub-project` **writable**, and host `C:\Users\Anthony\Documents\osrs-flip-assistant-project` maps to `C:\Work\osrs-flip-assistant-project` **writable**. `C:\Work\PC-Performance-Audit` remains writable. D:/E: forensic sources and Git/Python/Java toolchains remain read-only. Host Bridge exposes `Exchange\Requests` as writable and `Exchange\Responses` as read-only. There is no whole-host `C:` mapping. Read-only mappings stay read-only unless the protected `.wsb` boundary is deliberately changed after review. The corrected protected WSB SHA-256 is `1C3843E3A522E9E7DBF8A797921032EF7DF79008386012C436C0D1154D862980`.

Real write/read/cleanup probes passed after reopening the exact protected WSB for both Home Hub and OSRS, and automatic Sandbox RDC reconnect remained healthy. Within those writable project roots, normal issue-driven development may edit files, create branches/worktrees as appropriate, run tests, and use Codex. The mapping grants filesystem write capability only; it does not waive Home Hub rules protecting unrelated work and secrets or the separate authorization gates for commit, push, merge, deploy, restart, credentials, hardware/device writes, and other consequential actions.

Unrestricted RDC to real host `C:` is prohibited. The real-host endpoint is the restricted Home Hub control plane, not a generic filesystem or shell surface. Real-host administration uses only the typed Host Bridge allowlist; do not create a generic command, arbitrary-path filesystem, registry, service/task, delete, disk/partition, driver, firmware, or credential bridge to solve convenience problems.

Codex may run inside the protected Sandbox and work normally within the writable Home Hub or OSRS project roots, using the documented externally-sandboxed invocation. It gains no extra host authority by delegation and must preserve unrelated work, avoid secret-bearing files, and leave commit/push/merge/deploy/restart and other consequential actions behind their normal authorization gates.

### Durable Sandbox Codex task recovery (Project Admin, 2026-10-06)

The established Sandbox launcher is
C:\Work\PC-Performance-Audit\.rdc-sandbox-state\Invoke-CodexProjectTask.ps1.
It forwards to the repo-owned scripts\CodexSandboxTask.ps1. The matching
run-codex.cmd uses guest-local %USERPROFILE%\.codex-homehub-rdc for live Codex
SQLite/session state and keeps only auth synchronization plus task registry/
evidence on the host-backed .rdc-sandbox-state mapping. Windows Sandbox preserves
the guest profile across an in-guest restart; a full close/relaunch is disposable
and is not claimed as exact-thread-resumable. The runner sets Git safe.directory
to the validated task worktree only and does not require codex on ordinary PATH. It deliberately
uses native C:\Tools\Git\cmd instead of the historical git-shim, which changes
Sandbox SAC policy temporarily; that shim must not be invoked by Codex. This remains
Sandbox-only; real-host RDC is never a fallback.

To start a task, place the prompt under Sandbox $env:TEMP. Run from the live
Sandbox (replace angle-bracket placeholders):

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Work\PC-Performance-Audit\.rdc-sandbox-state\Invoke-CodexProjectTask.ps1" -WorkDir "C:\Work\home-hub-project\main" -PromptFile "<Sandbox TEMP prompt>" -Mode Write

Read mode is ephemeral for scouting; Write mode persists the thread.
Optional -Model overrides the default. The starter returns task_id after
detaching its worker. Do not use the RDC output-process PID as a completion
signal. The task registry is under:
C:\Work\PC-Performance-Audit\.rdc-sandbox-state\codex-runs\<task-id>\.
It stores task.json (prompt hash, workdir, starting HEAD/status), prompt copies,
state.json (PID/start, thread, state), per-attempt JSONL events, stderr, result
and Git postflight, and last-message.txt when produced. Stored prompts/logs
are local task data; never include secrets or archive them publicly.

Recovery after chat/RDC loss or an in-guest Windows Sandbox restart:

1. Enumerate live RDC devices and identify Sandbox from WDAGUtilityAccount
   plus C:\Work. Never reuse a stale device UUID or use the real-host controller.
2. From that Sandbox invoke repo scripts\CodexSandboxTask.ps1 with
   -Action List, or -Action Status -TaskId <32-hex-task-id>, with the same
   PowerShell -NoProfile -ExecutionPolicy Bypass -File invocation form.
   Inspect registry state and logs, not the original RDC output handle.
3. If worker_alive is true, observe it; never spawn a duplicate. If completed,
   consume last-message.txt and verify saved Git postflight against live Git.
4. If the worker and possible Codex child/orphan processes are proven dead,
   and a non-ephemeral exact thread ID exists, use -Action Resume -TaskId <id>
   -VerifiedNoCodexProcess. Resume uses the saved thread, not --last, and
   checks returned identity. Only affirm this flag after process-tree checks.
5. If exact resume is impossible, including after a full Sandbox close/relaunch
   that discarded the guest-local Codex home, preserve partial edits and registry
   logs, explicitly supersede the old task with -Action Supersede -TaskId <id>
   -VerifiedNoCodexProcess -Reason <specific-reason>, and only then consider a
   replacement. Uncertain liveness is a stop condition, not a second worker.

The engine guards against two unresolved Write tasks on one workdir. Sandbox
ExecutionPolicy Bypass here does not change real-host policy or grant additional
machine, service, production, or credential authority.

**Acceptance exercise — 2026-10-06:** Live Sandbox was rediscovered as
WDAGUtilityAccount with C:\Work, not a remembered device UUID. A non-ephemeral
no-edit Codex task was detached from its original RDC output handle, then a
separate control step recovered the same worker (PID 8160; no duplicate),
persistent thread 01a11477-de7b-7903-884f-f357eb531744, and ultimately the
saved last-message.txt marker PROBE_RECOVERY_OK. Task ID:
cbc28c4c562f477d90a3f7a029742dcb. The one attempt exited zero, with
identical Git HEAD/status before and after (aac2dc638635c628560e68d883a068a072da7ad6).
At the time of the recovery probe the repo source and runner changes were
uncommitted; no production or device operation occurred.

Two earlier startup test artifacts remain preserved: a partial staging
failure under codex-runs\_startup-failures and a failed pre-thread task
df29b8b83ebe47fb95006983670b93d4 explicitly marked superseded after
process inspection. Those exposed and fixed PowerShell 5.1 native stderr
warning escalation and an invalid atomic JSON replacement backup path.
The final Codex agent could not get its *internal* git branch commands to
return quickly and reported the branch unavailable; the independent Git
snapshots confirmed master. Treat slow/internal Codex shell execution as a
separate future diagnostic, not as a missing task/thread/result. At this earlier checkpoint, a full Sandbox restart and forcibly interrupted-
thread resume had not yet been performed. The PR #329 acceptance exercise below
supersedes that gap.

**Follow-up Codex native-Git validation — 2026-10-06:** Inspection of the
legacy git-sac-wrapper.ps1 showed it temporarily changes Sandbox SAC policy.
It has **not** been edited or invoked for this fix. The current run-codex.cmd
removes git-shim from its PATH prefix and uses C:\Tools\Git\cmd directly,
with the selected worktree-specific safe.directory. A new no-edit Read task
(2c6fea68aa4e441aa0082c378f806f1c) exited zero, reported Git branch
master, and saved GIT_NATIVE_PROBE_OK in last-message.txt. This also resolves
the earlier Codex-internal git-command timeout in the tested case. The repo
engine additionally records per-attempt launcher stdout/stderr and holds
exclusive task/workdir file locks while Write workers run. PowerShell parsing passed. At this earlier checkpoint, intentional forced
termination and Sandbox restart were not yet tested.

**PR #329 recovery acceptance — 2026-10-07:** The lost-RDC-handle path was
retested with durable no-edit task `e687a0f04fbb4d129d8bcaa6f1e74f2a`.
After ignoring its launcher handle, a fresh control step rediscovered it only
from `codex-runs`, recovered thread
`01a1149c-98fa-7ec1-a6db-d98c2bfa789c`, and consumed the completed
`RECOVERY_HANDLE_PROBE_OK` result with exit code 0.

A first restart probe exposed a real design failure: putting live Codex SQLite
state under the host-mapped `.rdc-sandbox-state\codex-home` left the persisted
thread ID intact but exact resume failed with `list_turns is not supported yet`,
and `migrate-rollouts` then hit SQLite disk-I/O error 8714 on the mapped
`state_5.sqlite`. That failed task (`6ed9407ad6be4b0eb4442897b3e19f95`)
and all attempt evidence remain preserved; no cleanup was used to hide it.

The accepted fix keeps live Codex SQLite/session state in guest-local
`%USERPROFILE%\.codex-homehub-rdc` while task registry/evidence and auth remain
host-backed. Final restart task `5b2b00e094f646a9bdd4c765510afea8`
was rediscovered from the registry with worker PID 2096 and thread
`01a114a6-230c-78e3-9254-32dbb38d24a0`; a second Write launch in the same
worktree exited 1 and the original worker/thread remained unchanged. While that
worker was deliberately sleeping, `Restart-Computer -Force` rebooted the
Sandbox. A newly booted `WDAGUtilityAccount` Sandbox retained the guest-local
Codex home, reported the saved task as `interrupted-or-unverified` with no live
worker, and a process inspection found no Codex/task process. `-Action Resume
-VerifiedNoCodexProcess` launched attempt 2 with the exact persisted thread ID.
The resumed event stream began with the same `thread.started` UUID, exited 0,
and saved `SANDBOX_RESTART_RECOVERY_OK`, the expected branch, and
`NO_EDITS=TRUE`. Git postflight retained HEAD
`d47defc517c4250c21e420aace3fb60a4661eb09` and only the two candidate edits
that already existed before the probe. This proves in-guest restart recovery;
a full Windows Sandbox close/relaunch remains intentionally outside the exact-
thread contract because that lifecycle discards guest-local state.

For destructive operations, prove the exact path first; for Git/worktrees, also prove registration, cleanliness, ancestry/unique-state as applicable. Prefer the narrowest native operation over recursive/broad deletion and retain before/after or rollback evidence sufficient to show what changed and what was preserved. Worktree removal remains subject to the stricter `Safe-RemoveGitWorktree.ps1` rule below.

The canonical checkout moved from
`C:\Users\antho\Desktop\home-hub` on 2026-08-18. Windows agent launchers now
derive the checkout root from their own location, and the
`Home Hub Agent Supervisor` Scheduled Task has been re-registered against the
new `main` path.

## Project-adjacent machine state

Not every Home Hub-related path belongs inside the workspace. Keep these outside
unless a separate recovery explicitly covers them:

- The historical Windows 10 backup path was `C:\Users\antho\HomeHubBackups`.
  It is **not present** on the rebuilt Windows 11 machine. The old Windows
  restic layer was classified during recovery as unrecoverable historical
  infrastructure; do not recreate its secrets or task configuration from stale
  documentation. Any future offsite backup design is new infrastructure.
- `%LOCALAPPDATA%\home-hub` — installed Windows runtime launchers for the
  unified supervisor.
- `%LOCALAPPDATA%\HomeHub` — installed PyInstaller desktop-notifier runtime.
  `HomeHubNotifier.exe` is owned by the separate `Home Hub Desktop Notifier`
  At-Logon Scheduled Task because PyQt6 must run on the GUI main thread rather
  than inside the supervisor's thread-per-agent model.
- `main\.agents\skills\deploy-home\SKILL.md` — current repo-local deployment
  procedure. The old user-global `%USERPROFILE%\.codex\skills\deploy-home`
  location is not present on this rebuild.
- `%USERPROFILE%\.ssh` — user-global SSH configuration and keys. The
  existing Home Hub key remains valid. On this Windows 11 rebuild, use
  `C:\Program Files\Git\usr\bin\ssh.exe` for Home Hub SSH/deployment;
  the inbox `C:\Windows\System32\OpenSSH\ssh.exe` currently exits 255
  before connecting.
- Windows Scheduled Tasks and environment variables — machine configuration,
  not repository content. On the rebuilt Windows 11 machine the user-level
  `HOME_HUB_URL=http://192.168.86.210:8000` setting is required by the repo
  `home-hub` MCP registration so `backend.mcp_server` targets Latitude rather
  than its localhost fallback. This URL is not a secret; do not recreate an
  old `HOME_HUB_API_KEY` unless a current authenticated path actually requires
  one. Windows user-environment changes are inherited only by **newly launched**
  processes. After changing `HOME_HUB_URL`, restart the local MCP host,
  terminal, editor, Claude/Codex session, or other developer process that will
  launch `backend.mcp_server`; a Windows reboot is not required. Verify from a
  fresh process by checking that `backend.mcp_server.BASE_URL` resolves to
  Latitude and that at least one live MCP call such as `get_health()` succeeds.

Do not assume historical machine-local debris (including the old root file named
`=`) still exists. If encountered, preserve unrelated files until explicitly
classified rather than staging or deleting them casually.

## Recovery completion gate

Do **not** declare a Windows/Home Hub rebuild or recovery complete merely because
Git is clean, the Scheduled Task exists, or the supervisor processes are
running. A closeout must cross-check all three sources of authority:

1. `docs/WINDOWS11_RECOVERY_STATUS.md` for the current recovery checklist and
   evidence;
2. the **Historical migration status** section below for migration-era
   machine/workspace surfaces that may have fallen out of newer checklists; and
3. `docs/PROJECT_SPEC.md` for current project-adjacent Windows requirements.

At minimum, verify the canonical checkout/worktree state, both tracked dependency
layers, the unified supervisor and backend agent-health report, the separate
Desktop Notifier installation/task and WebSocket connection, the ChatGPT
snapshot helper with a **real canonical dirty-tree snapshot**, the Home Hub MCP
target from a fresh process, the supported SSH/deployment path, and every
machine-local component that is either intentionally retained or explicitly
retired. Restoring tracked source alone is insufficient: Scheduled Tasks,
`%LOCALAPPDATA%` runtimes, environment variables, SSH configuration, and other
user-global state require behavioral verification after an OS rebuild.

If an older component has been intentionally superseded or retired, record that
disposition rather than recreating it. If evidence is incomplete, leave recovery
open.

## Windows PC-agent runtime

The unified `Home Hub Agent Supervisor` Scheduled Task is the only permanent
Windows Home Hub **agent** task. The separate `Home Hub Desktop Notifier`
At-Logon task is also supported and permanent, but it is a GUI surface rather
than a supervisor agent because PyQt6 must own the GUI main thread. Do not delete
the notifier merely because the supervisor is described as the only permanent
agent task.

On the rebuilt Windows 11 machine the supervisor starts 30 seconds after Anthony
logs on and has a 5-minute watchdog trigger. Its installed task action is:

```text
C:\Windows\System32\wscript.exe
"C:\Users\Anthony\AppData\Local\home-hub\start-supervisor-hidden.vbs"
```

with working directory:

```text
C:\Users\Anthony\Documents\home-hub-project\main
```

The installed VBS calls
`%LOCALAPPDATA%\home-hub\start-supervisor.ps1`, which sets the canonical
project root and launches
`main\.venv\Scripts\pythonw.exe -m backend.services.pc_agent.supervisor`.
The venv launcher currently resolves to the installed Python 3.13 runtime. Do
not hard-code the historical `C:\Python313\pythonw.exe` path.

A Windows rebuild is not complete after installing `requirements.txt` alone.
The desktop supervisor also depends on the tracked Windows-only layer:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-desktop.txt
```

`requirements-desktop.txt` supplies the WinRT GSMTC packages used by browser
Watching detection and PyQt6 for desktop-only UI/notifier surfaces. On the
2026-09-21 recovery audit this entire layer was found missing even though the
supervisor process itself was healthy, which left every desktop browser playback
probe reporting `unavailable`. Verify imports/package health rather than treating
a running supervisor as proof that desktop dependencies are complete.

The Scheduled Task may show `Ready` even while its detached supervisor process
is healthy and running; verify the process identity and backend agent-health
report rather than treating task status alone as runtime health.

Do not recycle the Windows supervisor casually. When a restart is explicitly
authorized, prefer `scripts/restart-agents.ps1`, which snapshots native process
identities and verifies the replacement health report. On 2026-08-30 a
non-elevated shell hit `Access is denied` while that script attempted to manage
the Scheduled Task ACL; the task remained enabled/`Ready` and the old supervisor
remained live. Treat that as a permission boundary: re-inspect task/process
state and use an authorized/elevated recovery path rather than assuming the task
changed or falling back to an unverified PID-only kill. During the same 2026-08-30 deployment, a later exact-identity recycle succeeded without modifying the Scheduled Task; success was accepted only after backend agent health reported the replacement supervisor identity.

When reading UTF-8 logs from Windows PowerShell 5.1, use `-Encoding UTF8`, for
example:

```powershell
Get-Content .\logs\supervisor.log -Encoding UTF8 -Tail 80
```

Without the explicit encoding, characters such as em dashes and arrows may
display as mojibake even when the log file itself is valid UTF-8.

## ChatGPT snapshot helper

Repository files:

```text
main\
├── Create ChatGPT Snapshot.cmd
└── scripts\
    └── create-chatgpt-snapshot.ps1
```

Double-click `Create ChatGPT Snapshot.cmd` to create a ZIP in sibling
`snapshots\`.

The snapshot script:

- derives all paths from its own repository location;
- includes Git-tracked files plus allowlisted untracked source/docs/config;
- records branch, HEAD, Git status, and diff stats in
  `SNAPSHOT_MANIFEST.txt`;
- excludes `.env`/secret material, private keys, databases, logs, caches,
  dependency/build trees, the tracked ambient-audio and static 3D binary asset
  trees, nested archives, files over 25 MB, `.git`, and the unrelated root file
  named `=`;
- does not modify project files;
- opens `snapshots\` and copies the resulting ZIP path to the clipboard.

Snapshots transfer current source context to ChatGPT. They are not backups and
must not contain production data or secrets.

After a Windows rebuild, migration, or material snapshot-helper change, file
presence is not enough to call this workflow recovered. Run the helper from the
canonical `main` checkout while the working tree contains representative dirty
tracked changes and at least one allowlisted untracked source/docs/config file.
Inspect the resulting ZIP and require all of the following before closeout:

- `SNAPSHOT_MANIFEST.txt` records the correct branch, HEAD, Git status, and
  dirty-file context;
- allowlisted untracked source is actually present in the ZIP, not merely named
  in the manifest;
- real `.env` files, private keys, databases, logs, `.git`, caches, and other
  excluded runtime/secret material are absent (`.env.example` is expected and
  allowed);
- the helper exits successfully even when Git emits ordinary Windows
  line-ending advisories; and
- any test snapshot is removed afterward so recovery validation does not become
  permanent clutter.

## Worktrees

### Proposed Sandbox retirement helper (#504, 2026-11-06; not approved policy)

`scripts/safe_retire_worktree.py` began as a local, uncommitted tooling proposal
on 2026-11-06. As of 2026-11-07, it and the proposed Codex launcher interlock
are published for review in [PR #508](https://github.com/agatte/home-hub/pull/508),
head `5771ee638b82b78130c04168ceb3736e58a5df90` (six files, full hosted
CI green). **The proposal is not an active removal policy, even if this PR is
later merged.** The host-only `C:\RecoveryTools\Safe-RemoveGitWorktree.ps1`
rule remains mandatory until an independently approved policy activation and
verified effective Sandbox launcher rollout. A separate exact-target removal
and any remote-read authorization remain required. No real removal was exercised.
The initial design task's no-network restriction is historical; current issue
and PR status must be verified live.

The helper defaults to dry-run. It uses existing Windows Python 3.13 and native
`C:\Tools\Git\cmd\git.exe`, with no install, fetch, force, prune, cache cleanup,
branch deletion or raw filesystem deletion. Each Git subprocess passes a
per-command safe.directory for the mapped checkout, without changing global
or repository Git configuration. It refuses:

- Any account other than Windows guest `WDAGUtilityAccount`, any target outside
  a direct child of `C:\Work\home-hub-project\worktrees`, main, project root,
  child paths, traversal, alternate drives and noncanonical paths.
- Reparse points/junctions/symlinks in target ancestry or tree, malformed/non-file
  `.git`, linked admin directory outside main's `.git\worktrees`, broken backlink,
  wrong common directory/root, or missing/duplicate/locked/prunable/detached or
  mismatched target registration.
- Dirty tracked/submodule state, any `assume-unchanged`/`skip-worktree`
  (including sparse-checkout) index flags, or any untracked content. All
  `git ls-files -v -z` tracked entries must have the ordinary `H` tag;
  unfamiliar flags or malformed output fail closed. Ignored files must
  match exact generated CPython 3.13 `__pycache__` filenames, pytest cache
  metadata/known cache entries, or Ruff cache metadata/version/numeric entries.
  This is a path whitelist, not content authentication. Unknown ignored files,
  including secrets and other versions/layouts, fail closed; no contents are read.
- Missing/malformed task registry or any global task in an active, queued,
  unverified or unknown state. Historical `failed` tasks outside the exact target
  and its lexical descendants are terminal; failed target/descendant tasks block.
  This is not proof that an unrelated failed task did not use an old path alias;
  operator review and quiescence are still required before live removal.
  Only task/state metadata is read, never prompts, logs, credentials or guest
  Codex databases. The proposed apply holds the shared root-worktree lifecycle
  key with Windows FileShare.None; a missing individual lock file is opened or
  created without creating lock directories. Malformed records also block.
- Missing exact lowercase 40hex `--expected-head` / `--expected-master`, wrong
  `--expected-branch`, local `origin/master` mismatch, or HEAD not an ancestor of
  that master. Squash/rebase-equivalent work is not sufficient proof.

Offline dry-run demonstrates **local ancestry only**. It never claims stale
`origin/master` is updated remote evidence. Apply also requires `--verify-remote`,
which performs a separately authorized read-only `git ls-remote origin
refs/heads/master` and demands that exact expected master. It never fetches or
advances local refs; stale local refs stop for a separately approved update.
The remote query uses existing Git configuration; no credential configuration
changes or interactive prompts are allowed. Do not use this option under a
no-network/no-credential-access task. No network option was exercised here.

Illustrative offline command after review (replace placeholders):

```powershell
& C:\Work\home-hub-project\main\.venv\Scripts\python.exe scripts\safe_retire_worktree.py 'C:\Work\home-hub-project\worktrees\<name>' --expected-head <40hex> --expected-branch <branch> --expected-master <40hex>
```

Only after separate policy/target/network gates would both `--apply` and
`--verify-remote` be added. The pilot is never an implicit default. This design
task explicitly preserves `ci-pr-merge-scope-504-20261106` at
`c7ed184fb0e29baa82d144dadce93b173b826132`, branch
`work/504-pr-merge-scope-20261106`; its separate pilot approval is not exercised.

Before the sole destructive command, the helper repeats registry and full
target/main/registration preflight. It calls **only** native `git worktree remove
<exact-target>`, without force. If Git refuses (including ignored caches), stop
and retain the blocker; never auto-clean or force. Git failure/timeout can leave
uncertain partial state: inspect read-only before new authorization, never retry
or repair automatically.

After success it requires target path/registration absent, branch still at exact
expected HEAD, all other registration records unchanged, and main tracked/
untracked status plus listed-file size/mtime/inode metadata unchanged. It prints
sanitized phase/target/ref evidence and snapshot digests; retain stdout and exit
status in a separately approved operator evidence location. No file contents or
Git stderr are printed. Postflight failure stops without rollback; source can be
recovered from the preserved branch only under a new reviewed action. Ignored
generated cache bytes are not backed up or recoverable.

Safety review limits: this is a cooperative local guard, not an OS security
boundary. Protected mappings remain the boundary; guest username does not prove
the active WSB hash. The proposed lifecycle lease excludes cooperating Read/Write
launchers and workers, but not arbitrary editors/Git commands or legacy launchers. All target
users must be quiescent. Remote refs, filesystem paths and registrations can race
after checks. Metadata/status comparison detects ordinary main edits without
reading secrets; it cannot prove byte identity against same-size/restored-mtime
edits or verify untouched bytes throughout every other worktree. The only destructive operation is native Git's target removal; the helper
may also create a file in the existing Codex lock directory. Preservation
against concurrent or malicious writers is not guaranteed. Trusted Git executable/configuration and a
quiet environment are prerequisites. The original exact-workdir Write lease had
a P2 child-workdir/Read launch race; the local interlock proposal below addresses
cooperating launchers only. Operator quiescence and reviewed, verified launcher
rollout are still required before live use.
The separately authorized pilot remains unexecuted; destructive and remote
tests were mocked.

Local validation uses `unittest` with mocked filesystem/registry/remote/removal,
Ruff, in-memory Python compilation and `git diff --check`. No real
worktree, branch, cache or registration was removed by the initial design task.
This initial 2026-11-06 snapshot predates the reviewed PR #508 publication;
the newer exact-head status and acceptance gates are stated above.

Local proposal verification (2026-11-06, base
`0787b5e794827a1ff55b31db50a3bf9b38abda58`, branch
`work/504-sandbox-worktree-guard-20261106`): 23 offline unit tests passed using
the existing main venv Python; Ruff passed for the helper and its tests.
Tests cover path/link rejection, registration/admin anomalies, hidden
index flags, tracked/untracked and ignored state, SHA/branch/ancestry and
remote mismatch, nested Codex workdir registry states, lease API contract,
preflight races, dry-run, native refusal, and postflight
registration/branch/main changes. Windows API calls, network and
all destructive boundaries were mocked. A later supervising, real-target
DRY-RUN completed successfully without a removal or remote query. An initial
attempt correctly refused the host-mapped Git checkout until per-command
safe.directory was added; no Git global setting or credential was changed.

#### Local shared-worktree lifecycle interlock proposal (PR #508 follow-up)

Initially an uncommitted follow-up based on `20a1573ad8fce69184388ec03ecf78c115a3cac3`
on 2026-11-06; since 2026-11-07 it is published at PR #508 head
`5771ee638b82b78130c04168ceb3736e58a5df90`. The initial implementation
task itself performed no remote operation, live apply or worktree removal.
The effective Sandbox entrypoint still hardcodes the older
`C:\Work\home-hub-project\main\scripts\CodexSandboxTask.ps1` and is **not**
updated by a GitHub PR merge alone. This code is implementation evidence for
review, not live safety or an active policy change.

Both implementations use the existing, required `codex-run-locks` directory and
`lifecycle-<sha256>.lock`, hashing UTF-8 lowercase Windows-normalized absolute
root `c:\work\home-hub-project\worktrees\<name>`. Only ASCII-named direct
Sandbox siblings participate. Root and child workdirs share a case-insensitive
key. Every accepted workspace path, including main, OSRS, audit and TEMP, must
use an absolute ASCII C: spelling with canonical components: UNC/device paths,
ADS, short-name tildes, Unicode, dot traversal, duplicate/trailing separators,
trailing dots/spaces and reserved device components are refused before path I/O.
After allowed-root validation, all ancestors are inspected from volume root
down for reparse points before leaf existence checks or lifecycle classification.
Other permitted Sandbox locations omit the lifecycle lease only after these checks. Missing sibling roots cannot silently
fall back to that behavior. Missing/access-denied paths, reparse ancestry,
invalid names, missing registrations, nested repositories and wrong Git
common/root directories fail closed. No lifecycle directory is auto-created.
Participating launcher validation refuses inherited `GIT_*` variables to prevent
repository redirection; use a clean launcher environment.

Start and Resume acquire `FileAccess.Read` / `FileShare.Read` before target
validation, snapshots, queued-record writes or worker spawn, releasing in
`finally`. Worker independently acquires the same shared handle in both modes
before task-exclusive and legacy Write-workdir-exclusive handles. Acquisition
is immediate/nonblocking, in that order, with no wait/retry cycle. Worker reloads
state.json under the task lock and requires both queued status and the exact
launch generation token before marking running. Start and every Resume mint a
new token; delayed workers from older attempts and legacy tokenless queued
records fail closed. Resume and Supersede acquire the same task-exclusive lock
before reading or changing state. Supersede takes only that lock; Resume takes
lifecycle then task. Resume releases task ownership after persisting the token
and before spawning; a Supersede in this gap invalidates the child at admission.
There are no automatic retries or force transitions. Worker holds all handles
through Codex and postflight; an outer finally also covers initial state saves,
attempt-directory creation and failing result/postflight writes. After acquisition, every path verifies workdir
existence, exact registration, Git top-level and common directory. Worker cannot
mark `running` or invoke Codex before admission, including exact-thread Resume.

Retirement holds `ReadWrite` / `FileShare.None` through validation, repeated
registry/preflight, native removal and postflight. Registry is checked under
exclusive ownership and again before final full preflight. Cooperating launchers
cannot queue target tasks during this interval. Global queued, running,
unverified, or unknown task states block retirement regardless of workdir.
Historical `failed` records are terminal **only when their lexical workdirs
are outside the exact target and descendants**; failed target/child records
remain blockers for possible unique work. The live registry previously contained
30 failed task records, none lexically under the #507 pilot target, so rejecting
all failures globally would permanently prevent useful cleanup. Legacy alias
records are not canonically resolved, and a failed record outside the target
could conceal an old aliased workdir; review that historical uncertainty and
ensure all target users are quiescent before any separately approved apply.
Previously queued tasks block retirement; even if delayed or superseded out of band, a worker
cannot acquire during retirement and must reject a removed root after release.
Admission failure leaves it queued/unresolved, never falsely running. Do not
auto-resume or supersede it without existing process inspection.

Rollout gate: review/merge and separately authorized integration must establish
which script the main entrypoint actually invokes. Drain/inspect existing
workers and queued tasks, including child workdirs and Read mode. Old queued
records without generation tokens cannot be launched by the new Worker: inspect
process trees and explicitly supersede or recover through the existing gates;
never add tokens by hand or automatically retry. Verify all
Start/Resume/Worker paths use the protocol before separately authorized removal.
Older script copies, direct Codex launches, orphaned Codex children after worker
death, manual user/editor activity and uncooperative filesystem/Git writers
bypass this cooperative lock. Terminal records alone do not prove migration.
Operator quiescence, trusted lock-directory ancestry and fresh remote/target
authorization remain mandatory. Malicious concurrent path replacement is outside
this protocol. The host-only mandatory removal rule remains active.

`tests/test_codex_sandbox_lifecycle_lock.py` extracts functions using PowerShell
5.1 AST parsing without invoking the launcher or Codex. It covers case/root/child
keys, foreign locations, actual read-only registration validation, missing
workdirs, injected link/access failures and admission order. A disposable fixture
inside this worktree probes real Windows interoperability: two launcher shared
handles coexist and exclude Python exclusive acquisition; release permits later
exclusive acquisition; Python exclusive ownership excludes launcher admission;
simulated removed-registration validation fails after acquisition and releases
the handle. No real target lock or removal is used. Existing guard tests mock
all destructive/network operations.

P2 closure follow-up to independent read-only review
`1ee5635be05448d2af2043548e2283fe` (2026-11-06), originally local and
now published at `5771ee638b82b78130c04168ceb3736e58a5df90`: the alias
policy and global registry drain address P2 #1; locked state reload,
launch generation identity, serialized Resume/Supersede and exception-safe handle disposal address P2 #2. Deterministic
PowerShell fixtures execute extracted action blocks with launch/process stubs,
exercise Resume/Supersede contention and ordered transitions, reject completed,
superseded and older-generation queued workers, and check real task/lifecycle/
workdir handle release after setup/result-write failures. Reparse ancestry is
injected, without creating junctions or accessing aliased destinations.

Validation on 2026-11-06: Python 3.13.15 passed 23 guard unit tests and 10
launcher tests (33 total), including real Windows FileShare interop and task
exclusion. Ruff 0.15.10 and the Windows PowerShell 5.1.26100.9818 parser passed;
`git diff --check` passed. Fixtures never invoke the launcher entrypoint or Codex.
The initial five-file test task did not itself integrate the launcher or perform
any destructive action. The follow-up was published in PR #508 on 2026-11-07;
independent read-only reviews found no P0–P2 blockers for **review-only**
publication. Hosted Linux CI passed at exact head `5771ee638b82b78130c04168ceb3736e58a5df90`.
Neither fixture success nor GitHub review status proves effective launcher
integration or safe live removal. Reverify path-policy compatibility,
lock/generation admission, exceptional release and legacy migration before apply.
Residual TOCTOU: separate path-attribute checks are not handle-pinned
filesystem identity; hostile concurrent rename/reparse replacement
and noncooperating/legacy launchers remain outside this cooperative protocol.
A global registry scan is a conservative snapshot, not a global transaction;
new unrelated tasks can appear afterward. Target-scoped lifecycle exclusion
protects cooperating target admissions, not arbitrary registry or filesystem
writers. No live deletion-safety claim follows from fixture success.

#### Pre-merge policy and effective launcher checkpoint — 2026-11-07

[PR #508](https://github.com/agatte/home-hub/pull/508) is review-ready with full
hosted CI success at `5771ee638b82b78130c04168ceb3736e58a5df90`.
Review-ready and mergeable do **not** mean approved for policy activation,
effective launcher replacement, or any real worktree removal. Independent
read-only rollout review `72220f8286e64fe1972222581aee0b83` identified
policy language that could incorrectly imply automatic activation at merge;
the proposed `AGENTS.md` text now explicitly requires a separate
owner-approved policy-activation decision **after** verified launcher rollout.

The actual Sandbox entrypoint
`C:\Work\PC-Performance-Audit\.rdc-sandbox-state\Invoke-CodexProjectTask.ps1`
hardcodes `C:\Work\home-hub-project\main\scripts\CodexSandboxTask.ps1`.
Its current file and `origin/master` have the same old Git blob
`5d7e9d7bb3f6cef7887ccf0ae677936b16ed4403`; PR #508 proposes
`d85a12ff8dec90178fce7f063d4f05e94310656f`. A GitHub merge does not
update that effective Sandbox script. At this read-only checkpoint `main`
was `41f8a1d1`, 149 commits behind local `origin/master=0787b5e7`,
with two unrelated, dirty monitor-brightness files also changed upstream.
Do not fast-forward or overwrite them as an incidental launcher rollout.

For a future **separately authorized** narrow Sandbox script rollout, first
stop new admissions and confirm no active/queued/orphaned legacy workers.
Take a verified exact-file backup, replace only the effective `main`
launcher, verify source and destination byte hashes, then perform separately
approved disposable Start/Worker/Resume Read+Write and child-workdir tests
through the actual external entrypoint. At this checkpoint the existing
launcher SHA-256 is
`652B4681AF3155D164308454F3BB8AD9793EA6820108CAC8CDD0976B06CD8A69`;
the reviewed PR file SHA-256 is
`682E70FDF8E6EC5A0C15250EE652529D852C02F38F831A3E994B3331018DB60C`.
No replacement, backup write, integration test or rollout occurred during
this review. Any rollback also requires quiescence and task-state inspection.
Only afterward may the owner separately consider policy activation and an
exact-target removal, with fresh remote evidence and operator quiescence.

### Current registered-worktree checkpoint — 2026-10-07

The 2026-09-20 recovery-era statement below that `main` was the only registered worktree is historical, not current. The bounded Project Admin reconciliation found multiple registered task/diagnostic worktrees in the writable Sandbox project root.

Do **not** bulk-clean them. Completed-task worktrees such as `away-off-convergence-324`, `lighting-final-write-authority-323`, and `project-admin-codex-recovery-20261007` were clean at this checkpoint, but their branch tips are not necessarily ancestors of `master` because accepted work was integrated through different PR commits; any later retirement still requires exact registration, cleanliness, tree/ancestry or unique-state proof, and the guarded `Safe-RemoveGitWorktree.ps1` path. `security-containment-285-v2` was also clean with its remote branch already gone and is a likely later cleanup candidate after the same proof.

Several other worktrees are explicitly **not cleanup candidates** at this checkpoint because they contain local state: `lighting-sunrise-ownership-322` has modified backend files plus an untracked ownership test; `control-plane` has substantial untracked Project Admin/control-plane material; `publication-readiness-20261002`, `replay-capture-operator`, `replay-capture-operator-v2`, `replay-isolation`, and `security-containment-285` also contain modified/deleted/untracked evidence or diagnostics. Preserve them. Clean replay slice worktrees may be assessed later, but no worktree or branch was deleted during this reconciliation.

Canonical `main` itself was at local `dae3cd5a818ee03d8bc368f0b5cf04cbc4745774` and diverged from `origin/master` by one local commit versus five remote commits after fetch; do not reset it casually. The reconciliation therefore uses a fresh `project-admin-status-20261007` worktree based on remote `master` instead of rewriting that checkout.


Create useful worktrees as siblings of `main`, for example:

```text
C:\Users\Anthony\Documents\home-hub-project\worktrees\<worktree-name>
```

Before creating one, inspect `git worktree list` and the intended branch.
Preserve active work and never overwrite or clean unrelated work.

At the 2026-09-20 recovery closeout, `main` was the **only registered
worktree**. Four recovery-time checkouts were safely retired after verification
that they were clean, 7-12 commits behind `master`, and had zero unique commits:

- `ambient-ownership-279`
- `ambient-start-verify-279`
- `audio-ownership-274`
- `tts-audio-ownership-280`

Their local branch refs and matching `origin/*` branches were deliberately
preserved; only the redundant worktree directories were removed through the
guarded `C:\RecoveryTools\Safe-RemoveGitWorktree.ps1` path.

The historical `worktree-projector-kasa` is **not** registered or present on
the rebuilt machine. Pre-failure evidence identifies its single unique local
commit `a075399` as undeployed projector smart-plug hardware/configuration that
was outside the approved production slice. The current repository no longer has
the commit object; recovered worktree metadata confirms the old ref, but its
49,057-byte index is TRIM-zeroed and the recovered pack indexes are corrupt.
Current product authority still marks projector smart-outlet shutdown as
research-needed and requires a safe normal shutdown/cooling sequence first, so
do not recreate this historical experiment merely because the worktree existed.

## Historical migration status

The following describes the prior Windows 10 workspace migration completed on
2026-08-18. It is retained as historical evidence, not as a statement that every
machine-local artifact survived the later SSD failure:

- canonical checkout moved to `main`;
- obsolete registered worktrees were retired;
- dirty `physical-context-relax` work was archived during migration; the saved patch was later proven malformed, but the clean patchcheck implementation commit `819794b` is integrated in current `master`;
- obsolete playoff worktree debris was removed;
- legacy Claude loop Scheduled Tasks were removed;
- Windows launcher paths were made relocation-safe;
- the unified `Home Hub Agent Supervisor` was established;
- the snapshot helper was installed;
- a user-global `deploy-home` skill and `worktree-projector-kasa` existed at
  that time.

## Windows 11 recovery status — 2026-09-21

The canonical repository, unified supervisor runtime, Windows desktop agents,
desktop notifier, snapshot workflow, SSH path, and Home Hub MCP target have been
re-established and verified. The OpenRGB/peripheral-RGB path was intentionally
retired on 2026-09-20 because it added polling/runtime complexity for little
reliable value; do not recreate it. Historical local-only artifacts are not
assumed recoverable merely because metadata survived: `physical-context-relax`
is accounted for by its integrated clean commit, while the undeployed
`projector-kasa` experiment is explicitly classified above as unrecoverable and
not part of the current product contract. Current recovery authority lives in
`docs/WINDOWS11_RECOVERY_STATUS.md`; do not use the historical migration list
above to recreate missing machine-local artifacts automatically.

Keep backups, installed runtime launchers, SSH configuration, and other
user-global tooling outside this workspace unless a separate recovery explicitly
covers them.
