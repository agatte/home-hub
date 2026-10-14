# HomeHub #399 — app-open Obsidian refresh feasibility (Sandbox proposal)

**Status: CANDIDATE DESIGN / NO HOST AUTHORIZATION.** Primary owner: Project
Admin, issue [#399](https://github.com/agatte/home-hub/issues/399), parent
[#365](https://github.com/agatte/home-hub/issues/365). Current integrated
prototype: [PR #403](https://github.com/agatte/home-hub/pull/403), GitHub master
`235bf5a42f7e6a972894beae4c911e4f02c1e92b` at design start.

## Product invariant

Keep the permanent existing Windows `HomeHub Knowledge Vault` as a
read-oriented GitHub mirror. Preserve `HomeHub Source` as the stable visible
root, existing Obsidian navigation, all user-owned notes and the full
`.obsidian` subtree. Keep GitHub canonical. The intended end state is
automatic, verified updates after reviewed documentation changes; do NOT
silently replace that outcome with daily notification or operator approval.
No unrestricted real-host access, plugin installation, elevated task, or
automatic production/Git writes.

## External semantics and Windows limits

- Obsidian officially documents that it automatically refreshes its vault
  after external changes to Markdown files. This makes filewise publication
  *worth evaluating* while Obsidian is open; it is **not** a promise of
  exact watcher timing, cross-file consistency or crash recovery.
  https://help.obsidian.md/data-storage
- Microsoft `MoveFileEx` documents that replacing an **existing directory**
  with `MOVEFILE_REPLACE_EXISTING` reports an error. The current two
  directory-renames cannot be made a single atomic directory replacement
  by simply adding that flag.
  https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw
- Microsoft's `ReplaceFile` is for **individual files**; it has backup and
  access/share/DACL conditions. It is not a multi-file transaction.
  https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew

## Compared architectures

| Strategy | Benefit | Unaccepted failure/UX contract |
| --- | --- | --- |
| A — current two directory renames | Preserves an old complete directory outside the Vault | `HomeHub Source` is absent between moves; hard crash may strand it; app launch after a closed process poll is not excluded |
| B — file-by-file publication in stable managed directory | Visible `HomeHub Source` root, existing paths and links persist; potentially compatible with Obsidian's external-change watcher | Readers see a mixed old/new set; after interruption old manifest is invalid even though directory exists; individual file operations can fail on sharing/ACL; requires tested recovery |
| C — immutable snapshots + single navigation-page change | Completed per-generation content can remain immutable and a one-file navigation update can be atomic | Obsidian's search, wikilinks and already-open notes do not automatically resolve through the pointer; retained versions may duplicate search results; would change the accepted Vault layout |

**Provisional recommendation:** evaluate B in **disposable fixtures only**.
It is the only candidate of these three which keeps the existing layout and
avoids removal of the managed root. This is not approval to build or run a
real-host updater; a user/product decision is needed on the temporary
mixed-version window and after-crash recovery UX before an actuator exists.

## Non-actuating filewise planner

`scripts/obsidian_filewise_preview.py` validates exact-path sealed old
managed evidence, verified forward GitHub documents and their Git blob OIDs,
and generated `00-START-HERE.md` / `SNAPSHOT.md` bytes. It returns only
sorted `added`, `modified`, `retired`, `unchanged` path sets.
It excludes user-owned notes from planning and rejects unexpected content
under the existing managed root. `host_refresh_authorized=false` is
unconditional, and it contains **no filesystem write path**.

`tests/test_obsidian_filewise_preview.py` covers source divergence,
ref instability, old-source tampering, unexpected or Windows-reserved paths,
required-tree validation, no-op, exact diff, and personal-note/.obsidian
preservation. A synthetic filewise replace followed by a simulated
interruption demonstrates **managed root present, old manifest invalid,
and preserved sealed old backup**. This intentionally demonstrates a
failure mode, not a completed crash-safe updater.

## Required design and host gates BEFORE actuator development

1. Accept or explicitly reject the brief user-visible mixed-document
   window. No claim of cross-file atomicity while Obsidian runs.
2. Define exact old/new source and manifest transition, recoverable
   journal protocol **outside** the Vault, backup creation and
   verification before any managed-file changes, exact file-retirement
   semantics, lock ownership and idempotent restart.
3. Implement fixture-only replace/retire/manifest-last and injected
   failure at each operation; demonstrate outcomes after actual child
   process abort. If recovery needs restoration, it is also not atomic.
   Never silently delete backups or user notes.
4. Independently review actual host run-as token, exact Vault/ancestor
   effective ACLs, Windows reparse/handle identity, sharing modes and
   noncooperating writer races. Do not infer these from Sandbox.
5. Prove behavior with Obsidian open/closed, links, search, reboot and
   offline retries on a **separately authorized disposable host Vault**
   before evaluating the existing permanent Vault. No auto-enablement,
   no elevated/generic host administration, no new community plugin.
6. Obtain normal Git publication/CI/security review and **separate real
   Windows host task activation** authorization. Preserve #399 as OPEN
   until actual host acceptance; #358's old Vault durability evidence
   does not prove newer auto-refresh.

**No action here changes GitHub branches, the permanent Vault, an Obsidian
process, Windows tasks, services, ACLs, or deployment state.**

## 2026-10-14 operator decision and transaction-fixture checkpoint

The operator **accepted temporary mixed-version Markdown visibility**, strictly
conditional on implementing and verifying backup, interruption detection and
recovery **before** enabling automatic refresh. This removes only the product
ambiguity, not any security/host permission gate.

An additional uncommitted **synthetic-only** transaction candidate
(`scripts/obsidian_filewise_fixture_transaction.py`) was added. It rejects
targets except an exactly named `Synthetic Vault` inside a
`hh399-filewise-txn-*` directory directly beneath Python's TEMP root.
Its intended steps are: validate exact old/new source -> copy and verify an
entire sealed old backup outside the Vault -> seal new stage -> persist
a small exact-transaction journal -> write known Markdown paths file by file
-> retire only named old paths -> publish the sealed manifest last -> verify
the final source. The read-only inspector describes incomplete/mixed states
without repair; a separate operator-confirmed **fixture** function proposes
restoring the old set, again with a retained backup and a journal.

**NOT YET VERIFIED:** The initial Windows `pytest` launch for the new
fixture executor was blocked by tool execution safety controls. Source AST
parsing succeeded, but code execution/fault injection including abrupt child
process termination, stale lock management and restore tests have **not**
passed. The helper is *not* an accepted transaction/recovery implementation,
must not be installed, called on the real Vault or published as production
activation code. Final review/fixes and actual clean Windows and Linux
test evidence are required first. This note records the implementation
proposal, **not completion** of the operator's backup/recovery condition.

Security caveats unresolved: journal fsync and single-file replacement do not
prove power-loss durability or atomic multi-file visibility; backup and
journal remain sibling paths requiring effective ACL, handle-stable identity,
anti-reparse and writer-exclusion review. A manual recovery must not auto-clear
stale locks or erase unknown user modifications. No host account, task,
credential, Obsidian process, permanent Vault or production was touched.

## 2026-10-14 independent fixture code review and explicit blockers

Read-only Sandbox Codex review task
`831cd742a5d8491baa90a78e0ee46ec6` completed and found **two
high-severity** problems in the initially untested fixture publisher:
a forged journal could claim a drive-relative Windows path, and cross-
generation case-only/file-to-directory transitions could destroy an
unintended NTFS target. The new uncommitted code now validates journal
memberships with Windows-safe path rules and against the complete sealed
stage, validates lexical target containment, and refuses cross-generation
Windows case and namespace transitions. Three draft regression tests were
added for those scenarios.

The review also found a **still unresolved crash/recovery problem**:
an abrupt exit during copying can leave exactly named `.tmp` files
inside the managed source. These are safely treated as unexpected
content, but the current fixture recovery function refuses them rather
than completing restoration. A future exact-artifact preservation and
operator-confirmed recovery design must cover this case; no automatic
cleanup of unrecognized user files, backup deletion, or stale-lock
breakage is permitted.

**No execution acceptance:** the initial Windows test launch for the
new fixture publisher was blocked by safety controls. Subsequent
high-severity fixes and three draft regressions have only source-level
AST validation, not runtime verification. The old read-only planner
and existing suite previously passed **175 Windows tests**, but those
results do **NOT** cover this new transaction simulator. An actual
child-process crash in the filewise publisher, manifest-last durability,
interrupted restore, sharing/ACL error, power loss and concurrent Obsidian
handling remain unverified. There is no real-host actuation authority.

## 2026-10-14 later static review, artifact preservation and re-entrant recovery

Independent read-only Codex review `a74d0f4f4b2e43f781da3a38e539ad76`
identified **HIGH** risk of overwriting unexpected user edits at otherwise known
managed filenames, **MEDIUM** collisions on a second interrupted restore,
and **MEDIUM** false completion reporting if a stale lock or unresolved
artifact-evidence directory remained.

The still **unpublished/unverified fixture** was updated accordingly:

- Before an operator-confirmed restore mutates any known file, compare its
  actual contents to the exact complete old-backup and new-stage file bytes.
  Reject unexpected user edits, missing shared files, or unexpected manifest
  content. Repeat the check after obtaining the exclusive fixture lock.
- Require `restore_attempts` in the exact journal (bounded 0..10), increment
  and persist before restore, assign an independent evidence slot to each
  attempt and recognize only journal-bound exact transaction artifact names.
  Preserve earlier evidence rather than delete/overwrite it.
- Inspect the exact retained evidence directory and lock even when the managed
  hash seal verifies; separate `published/old_intact` file-integrity states
  from `requires_operator_review`, and refuse unknown evidence contents.
- Expanded unexecuted tests cover changed known old/new content, stale locks,
  unknown evidence, two recovery attempts, exact copy and manifest temp
  artifacts, and conflicts. These test sources have parsed successfully but
  HAVE NOT been run.

**Still unaccepted:** Windows runtime tests for these changes, actual child
process abort during file COPY and during RESTORE, journal writes or rename,
blocked/pending journal handling, Windows file sharing and effective ACLs,
power-loss durability and handle-stable anti-reparse validation. All
backup/evidence retention must be tested before operation on any nonfixture
Vault. This design continues to refuse real-host activation.
