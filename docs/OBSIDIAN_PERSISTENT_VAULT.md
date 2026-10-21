# Persistent HomeHub Knowledge Vault — operating guide (#358)

**Status (2026-10-11):** The permanent real-PC Vault is installed and survived
a normal Windows reboot with expected managed files, preferences, navigation,
links and search confirmed by the operator. The prior guarded refresh to
`dcacfc7eda54acad016b4a5ddf95479b43cf10aa` retained a sealed manifest,
inherited Windows permissions and a preserved previous managed snapshot.
The successful [#358 acceptance](https://github.com/agatte/home-hub/issues/358#issuecomment-6110337423)
did **not** rehash the full post-reboot manifest or inspect personal notes.

> **Current GitHub issue:** #358 closed

GitHub Issues/Projects and tracked Markdown remain authoritative; this is a
*local read-oriented snapshot*, not an independently editable task board.

## Layout (installed real-host location)

The stable real-Windows Vault root is already in use. **Do not reinitialize,
overwrite, or remove it**; a new root would require a separate operator decision:

    C:\Users\Anthony\Documents\HomeHub Knowledge Vault\
      .obsidian\                         # Owned by Obsidian; never managed
      My Notes.md                        # Any personal notes are untouched
      HomeHub Source\                    # Managed read-only Markdown snapshot
        00-START-HERE.md                 # Open/pin this note in Obsidian
        SNAPSHOT.md                      # Source commit provenance
        .homehub-snapshot-manifest.json  # Hash integrity guard
        AGENTS.md
        docs\...

The permanent Vault is outside the Git project and outside Windows Sandbox.
Sandbox guest-local previews disappear upon Sandbox closure; they do not replace
the installed real-host Vault.

## Original installation/setup procedure (historical; do not rerun on the existing Vault)

These steps apply only to a **separately authorized, absent target** in a future
recovery/reinstallation scenario. The existing permanent Vault is already
installed, and `--initialize` must not be run over it.

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

## Historical manual refresh (not the scheduled-task procedure)

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

## Scheduled synchronization — enabled but not operationally accepted (2026-10-21)

The exact user-local Windows Task Scheduler task `HomeHub Obsidian Mirror Refresh`
was enabled with the operator's separate approval under [#399](https://github.com/agatte/home-hub/issues/399).
A physical 11:00 ET scheduled run occurred but returned result **2**; the managed
manifest still named `4156e2d93a7cdc991783d3831bb74ecd0e243aa5`, and
no completed automatic refresh has been verified. This supersedes the older
no-task status in historical sections. The task being **enabled** is not the
same as successful end-to-end synchronization.

The pinned launcher from the installed original bundle has a reproducible
Windows `ctypes.ArgumentError` in token acquisition. The reviewed corrective
source and replacement release are tracked in #399. **Do not change the installed
versioned bundle in place, run the task manually, or retarget the enabled task**
without separate reviewed host installation/action-change authorization. Keep
the previous bundle, task definition, and managed snapshots as evidence.
See [the synchronization design](OBSIDIAN_SYNC_DESIGN.md).

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

**Acceptance checkpoint:** Host installation, guarded manual refresh, inherited
Windows access, post-reboot Vault navigation/search/preferences and continued
availability without a running Sandbox have passed per #358. Full post-reboot
manifest-file rehashing and personal-note content retention were not inspected.
There is still **no** automatic Vault refresh. Do not infer that `HomeHub Source`
follows GitHub `master`; a new separately approved guarded refresh is required
for a newer source SHA. [#365](https://github.com/agatte/home-hub/issues/365)
owns optional future synchronization.
