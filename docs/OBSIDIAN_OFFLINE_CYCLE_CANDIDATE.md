# HomeHub #399 — offline filewise cycle integration candidate

**Status (October 16, 2026):** uncommitted, **Synthetic Vault only**, not a real-host updater. Project Admin owns #399. The source is in the detached `obsidian-assisted-399-master-20261015` Windows Sandbox worktree, based on GitHub `master` commit `b6efd44b3b2f4789dbeb5ca49f02a792e2b022e4`. Do not infer publication, deployment, installation, or assistant memory from these files.

## Source and entry points

- `scripts/obsidian_disposable_cycle.py`: `run_fixture_cycle` accepts an already authenticated offline `PreparedDocs`, exact Synthetic Vault paths, an unused transaction suffix, and a **complete ordered retained transaction history**. It returns a structured `CycleStatus` for published, up to date, blocked, or recovery required. Every outcome has `host_refresh_authorized=False`.
- `scripts/obsidian_cycle_lease.py`: cooperative per-Vault cycle lease, held across transaction inventory, prior evidence verification, preview, filewise publisher (with its existing nested refresh lock), no-change decision and postflight. Existing/stale/modified lease files cause refusal and are never automatically cleared.
- `tests/test_obsidian_disposable_cycle.py`: 22 new integration/lease/history cases, plus 35 existing imported fixture transaction cases when this test module is selected. The integration also exercises a real independent child **under the same Sandbox Windows SID**, not distinct user-principal isolation.
- Existing `scripts/obsidian_filewise_fixture_transaction.py` still owns exact synthetic-only backed-up, staged and journaled manifest-last filewise publication. Its target guard is unchanged. This candidate does **not** fetch GitHub online, inspect the permanent Vault or schedule a Windows task.

## Verification

Windows Sandbox Python 3.13.15, from the HomeHub venv, executed:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
C:\Work\home-hub-project\main\.venv\Scripts\python.exe -m unittest discover -s C:\Work\home-hub-project\worktrees\obsidian-assisted-399-master-20261015\tests -p 'test_obsidian*.py' -q
```

Result: **258 tests, 1 skipped, exit 0**, after a detected test-order regression was corrected and the suite rerun. The targeted module includes the 35 existing fixture transaction cases; the 258 count is not 258 independent new #399 checks. Ruff/full Linux CI have **not** been run on this uncommitted change.

Observed behavior: exact verified forward source publishes into a disposable stable managed directory, retains full old sealed backup/new sealed stage/journal and publishes the new manifest last; identical source is a no-op; unknown source/evidence and interrupted transactions refuse. Three successive completed publications succeed when the **entire ordered historical transaction chain** is supplied and each historical backup/stage/journal is reverified; omitting an older transaction, tampering with its retained backup, or providing a broken chain prevents a new publication. Personal-note and `.obsidian` fixture bytes remain unchanged.

A cleanup failure after a successful fixture publication returns `recovery_required`, the old/new commit identities, and the pre-cleanup outcome, while leaving the ambiguous lease for review. An injected descriptor inspection failure closes its file descriptor and preserves the partial lock. These are synthetic failure-injection tests, not evidence of power-loss durability.

The history interface is **caller-supplied**, explicitly ordered and limited to 4,096 entries in this experimental implementation. It is not a durable transaction registry or discovery mechanism and is not yet suitable for automatic retention over an unlimited service lifetime. **No backup retention deletion is authorized.**

## Required gates before unattended refresh

1. A trustworthy persistent inventory of all transactions, protected journal/stage/backup storage, owner and effective DACL checks, and stable ancestor/file identity. No silent permission escalation, namespace rebinding or user-note/settings access.
2. Actual separately unelevated Windows reader/updater processes, protection against other writers with open writable handles, and a defensible owner/share-mode and race-resolution policy. The cooperative lock **does not** exclude uncooperative writers and its final path check then unlink remains racy when another user can write the parent.
3. Disposable real Windows Obsidian watcher/search/navigation while open, physical interruption/reboot/offline recovery, retained backup verification and explicit operator decision on ambiguous restores.
4. Normal source publication approval, Linux CI/independent review, bounded real-host read-only preflight, separately authorized disposable Vault pilot, and **separate real-host Scheduled Task installation and permanent Vault activation**.

The permanent Windows Vault remains a manually accepted read-oriented snapshot. #399 stays OPEN, automatic synchronization OFF. Repository metadata were inspected with a read-only Git index parser because native Windows Git is blocked by #401; 800 existing tracked paths matched their index SHA-1 after Windows CRLF normalization, but the full untracked Git status and normal Git publication remain unverified. No changes to production, Windows accounts/ACLs, credentials, services, tasks, real user notes, or actual Obsidian files occurred.
