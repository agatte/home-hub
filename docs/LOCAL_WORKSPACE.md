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
run-codex.cmd uses persistent .rdc-sandbox-state\codex-home with established
separate codex-auth synchronization, sets Git safe.directory to the validated
task worktree only, and does not require codex on ordinary PATH. It deliberately
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

Recovery after chat, RDC or Sandbox loss:

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
5. If exact resume is impossible, preserve partial edits and logs, explicitly
   supersede the old task with -Action Supersede -TaskId <id>
   -VerifiedNoCodexProcess -Reason <specific-reason>, and only then consider
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
separate future diagnostic, not as a missing task/thread/result. A full
Sandbox-restart and forcibly interrupted-thread resume were NOT performed;
the recovery design is ready for those conditions but that branch remains
unexercised in this acceptance test.

**Follow-up Codex native-Git validation — 2026-10-06:** Inspection of the
legacy git-sac-wrapper.ps1 showed it temporarily changes Sandbox SAC policy.
It has **not** been edited or invoked for this fix. The current run-codex.cmd
removes git-shim from its PATH prefix and uses C:\Tools\Git\cmd directly,
with the selected worktree-specific safe.directory. A new no-edit Read task
(2c6fea68aa4e441aa0082c378f806f1c) exited zero, reported Git branch
master, and saved GIT_NATIVE_PROBE_OK in last-message.txt. This also resolves
the earlier Codex-internal git-command timeout in the tested case. The repo
engine additionally records per-attempt launcher stdout/stderr and holds
exclusive task/workdir file locks while Write workers run. PowerShell parsing
passed; intentional forced termination and Sandbox restart were not tested.

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

Create useful worktrees as siblings of `main`, for example:

```text
C:\Users\Anthony\Documents\home-hub-project\worktrees\<worktree-name>
```

Before creating one, inspect `git worktree list` and the intended branch.
Preserve active work and never overwrite or clean unrelated work.

As of the 2026-09-20 recovery closeout, `main` is the **only registered
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
