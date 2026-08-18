# Home Hub Local Workspace

This document describes the Windows development-machine layout and ChatGPT
snapshot workflow. It is operational guidance, not product behavior; the
cross-system product contract remains `docs/PROJECT_SPEC.md`.

## Canonical workspace

The Windows Home Hub workspace is:

```text
C:\Users\antho\Documents\home-hub-project\
├── main\       # canonical Home Hub Git checkout
├── snapshots\  # lean ZIPs created for ChatGPT; not part of Git
└── worktrees\  # isolated Git worktrees for substantial changes
```

`main` is the canonical checkout. Substantial implementation/review work should
use sibling worktrees under `worktrees\` rather than scattered Desktop clones.

The canonical checkout moved from
`C:\Users\antho\Desktop\home-hub` on 2026-08-18. Windows agent launchers now
derive the checkout root from their own location, and the
`Home Hub Agent Supervisor` Scheduled Task has been re-registered against the
new `main` path.

## Project-adjacent machine state

Not every Home Hub-related path belongs inside the workspace. Keep these
outside unless a separate migration explicitly covers them:

- `C:\Users\antho\HomeHubBackups` — offsite restic scripts/secrets and scheduled
  backup dependencies. Contains secret material and must never enter ChatGPT
  snapshots or Git.
- `%LOCALAPPDATA%\HomeHub` — installed desktop-notifier/runtime files.
- `%USERPROFILE%\.codex\skills\deploy-home` — user-global Codex skill, not repo
  content. Any checkout path inside the skill must follow the canonical `main`
  path.
- `%USERPROFILE%\.ssh` — user-global SSH configuration and keys.
- Windows Scheduled Tasks and environment variables — machine configuration,
  not repository content.

The unrelated untracked root file named `=` is machine-local debris. Do not
stage it; the snapshot helper explicitly excludes it.

## Windows PC-agent runtime

The unified `Home Hub Agent Supervisor` Scheduled Task launches the supervisor
from the canonical checkout. The task action is expected to use:

```text
wscript.exe
"C:\Users\antho\Documents\home-hub-project\main\scripts\start-supervisor-hidden.vbs"
```

with working directory:

```text
C:\Users\antho\Documents\home-hub-project\main
```

The long-lived supervisor is a detached `C:\Python313\pythonw.exe` child. The
Scheduled Task may therefore show `Ready` while the supervisor process is
healthy and running.

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
C:\Users\antho\Documents\home-hub-project\worktrees\<worktree-name>
```

Before creating one, inspect `git worktree list` and the intended branch.
Preserve active work and never overwrite or clean unrelated work.

The preserved `worktree-projector-kasa` branch may be recreated under this
directory when needed.

## Migration status

Completed on 2026-08-18:

- canonical checkout moved to `main`;
- obsolete registered worktrees retired;
- dirty `physical-context-relax` work archived as a validated UTF-8 patch;
- obsolete playoff worktree debris removed;
- legacy Claude loop Scheduled Tasks removed;
- Windows launcher paths made relocation-safe and pushed;
- `Home Hub Agent Supervisor` recreated from the new checkout;
- all seven PC-agent threads started successfully;
- activity reporting reached the backend with HTTP 200;
- OpenRGB was relaunched and reconnected by the peripheral RGB agent.

Remaining local workspace follow-up:

1. install and test the ChatGPT snapshot helper;
2. update the user-global `deploy-home` skill to the canonical checkout path;
3. recreate only useful worktrees under `worktrees\`;
4. keep backups/notifier/SSH/global tooling outside the workspace.
