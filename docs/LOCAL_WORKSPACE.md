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
  one.

Do not assume historical machine-local debris (including the old root file named
`=`) still exists. If encountered, preserve unrelated files until explicitly
classified rather than staging or deleting them casually.

## Windows PC-agent runtime

The unified `Home Hub Agent Supervisor` Scheduled Task is the only permanent
Windows Home Hub agent task. On the rebuilt Windows 11 machine it starts 30
seconds after Anthony logs on and has a 5-minute watchdog trigger. Its installed
task action is:

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
the rebuilt machine. Do not recreate it merely because older documentation says
it once existed.

## Historical migration status

The following describes the prior Windows 10 workspace migration completed on
2026-08-18. It is retained as historical evidence, not as a statement that every
machine-local artifact survived the later SSD failure:

- canonical checkout moved to `main`;
- obsolete registered worktrees were retired;
- dirty `physical-context-relax` work was archived as a validated UTF-8 patch;
- obsolete playoff worktree debris was removed;
- legacy Claude loop Scheduled Tasks were removed;
- Windows launcher paths were made relocation-safe;
- the unified `Home Hub Agent Supervisor` was established;
- the snapshot helper was installed;
- a user-global `deploy-home` skill and `worktree-projector-kasa` existed at
  that time.

## Windows 11 recovery status — 2026-09-20

The canonical repository, preserved historical branch refs, unified supervisor
runtime and Windows desktop agents have been re-established and verified. The
OpenRGB/peripheral-RGB path was subsequently retired on 2026-09-20 because it
added polling/runtime complexity for little reliable value; do not recreate it. The temporary recovery worktrees were retired once proven
redundant. Current recovery authority lives in
`docs/WINDOWS11_RECOVERY_STATUS.md`; do not use the historical migration list
above to recreate missing machine-local artifacts automatically.

Keep backups, installed runtime launchers, SSH configuration, and other
user-global tooling outside this workspace unless a separate recovery explicitly
covers them.
