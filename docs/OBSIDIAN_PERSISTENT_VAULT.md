# Persistent HomeHub Knowledge Vault — staged design (#358)

**Status:** implementation candidate, not installed on the real host. Preserve
GitHub Issues/Projects and tracked HomeHub Markdown as the authorities. This
Vault is a *local read-oriented mirror* of one named Git commit, not a task board.

## Layout (approved proposed location)

The real Windows user will use this stable private root, **only after explicit
host-side setup and verification that the target is unused**:

    C:\Users\Anthony\Documents\HomeHub Knowledge Vault\
      .obsidian\                         # Owned by Obsidian; never managed
      My Notes.md                        # Any personal notes are untouched
      HomeHub Source\                    # Managed read-only Markdown snapshot
        00-START-HERE.md                 # Open/pin this note in Obsidian
        SNAPSHOT.md                      # Source commit provenance
        .homehub-snapshot-manifest.json  # Hash integrity guard
        AGENTS.md
        docs\...

The new Vault is never stored in Windows Sandbox or within the Git project.
Obsidian and Vault data must both live on the **real Windows host**. Sandbox
installation and guest-local previews disappear upon Sandbox closure.

## Installation and initial setup (real host, operator-directed only)

1. Download the Windows Obsidian installer through
   <https://obsidian.md/download>, verify the publisher/signature, and perform
   an ordinary **per-user installation** on the real host. Do not run an
   installation through an unrestricted host agent, extra drive mapping, or
   elevated generic bridge action.
2. Confirm the exact proposed Vault root is **absent**. If it already exists,
   stop; do not overwrite, clean, or repurpose it.
3. From an up-to-date, trusted HomeHub checkout, run the script below with
   native Git and Python 3.13 (or another supported modern Python). Verify
   the source HEAD is **the intended GitHub master commit**. The tool refuses
   mismatched expected SHA; do not reset or force Git just to match.
4. Open Obsidian → **Open folder as vault** → select the permanent root.
   Open and pin `HomeHub Source/00-START-HERE.md`. Keep Obsidian Sync,
   Publish, community plugins, and automatic Git writes disabled.
5. Confirm reading/navigation/search, add a harmless personal note outside
   `HomeHub Source`, close/reopen Obsidian, and ultimately verify persistence
   through a normal host reboot and a Sandbox close.

Example **host-operator-run** PowerShell commands (not for real-host RDC or
an unrestricted control plane):

~~~powershell
$repo = 'C:\Users\Anthony\Documents\home-hub-project\main'
$vault = 'C:\Users\Anthony\Documents\HomeHub Knowledge Vault'
$script = Join-Path $repo 'scripts\manage_obsidian_vault.py'

# Confirm these point to ordinary installed Git/Python, not a Sandbox-only shim.
Get-Command git.exe, py.exe -ErrorAction Stop
Test-Path -LiteralPath $vault  # MUST be False for --initialize
git -C $repo status --short --branch
$sourceHead = (git -C $repo rev-parse HEAD).Trim()
$sourceHead  # Independently verify against the intended GitHub master SHA.

# Replace this literal with the independently verified intended 40-char SHA:
$expectedHead = '<exact-approved-source-commit-sha>'
py -3 $script --initialize --repo $repo --vault $vault --expected-head $expectedHead
~~~

**Stop** if the host lacks Python/Git, cannot independently verify the intended
source SHA, or the Vault already exists; do not silently install more tools or
update local Git. The required implementation must already be merged into
the source checkout before running it. The initial export intentionally leaves
any failed/partial result in place for inspection, not automatic deletion.

## Manual refresh (no background task)

Close Obsidian first. Verify that the Git checkout is at the intended,
up-to-date commit before using `--refresh`:

~~~powershell
$expectedHead = '<new-intended-40-char-source-commit-sha>'
py -3 $script --refresh --repo $repo --vault $vault --expected-head $expectedHead
~~~

The tool rejects altered/added/deleted files, symlinks, or junctions in the
managed subtree and refuses to overwrite an unrelated existing Vault. On
successful refresh, only the *sealed managed subtree* is replaced; Obsidian's
own settings and personal notes outside it remain untouched. The previous
snapshot is **moved to a uniquely named sibling backup directory outside the
Vault**; it is never automatically deleted. Failed stages and backups are also
preserved for safe investigation. Do not clean them with broad wildcard
commands; handle retention later with exact target review and separate
authorization.

There is a brief handoff interval while the managed folder is renamed.
Obsidian should be **closed** during refresh; a locked file should make the
operation refuse/rollback rather than bypass access controls. If any error
occurs, inspect the managed folder and reported staging/backup paths before
retrying. Refreshing from the same commit is a no-op.

## Constraints

- Source selection is exactly Git-tracked regular Markdown from `AGENTS.md`
  and `docs/**/*.md`, plus generated navigation/provenance; no arbitrary
  repo files, non-Markdown attachments, untracked files, symlinks, or
  credentials. This is **not** a scan for secrets *inside tracked Markdown*.
- No automatic Git fetch/push, no HomeHub deployment, no production writes,
  no host service/restart, no auto-updater, no remote Obsidian Sync/Publish.
- A local Git source SHA may differ from GitHub `master`; confirm explicitly.
- Managed docs are snapshots. Edit canonical HomeHub docs through normal
  GitHub PR/review workflows, not by editing this mirror.
- The helper is not a general backup of the Vault or `.obsidian`. Protect
  personal notes through the user's ordinary host backup practices.

**Acceptance remains pending** until the host installation, initial local
Vault, actual UI use, manual refresh, and durability after restart are proven.
