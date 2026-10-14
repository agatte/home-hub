# HomeHub #399 — Filewise backup/recovery acceptance matrix

**Owner:** Project Admin · **Status:** Windows Sandbox synthetic-fixture testing passed; real-host acceptance NOT complete (2026-10-14) · **Authority:** GitHub issue #399, `AGENTS.md` and merged `master`.

The operator permits brief mixed-version Obsidian documentation only if a complete backup, interruption detection and recovery have first been **implemented and physically tested**. This matrix is not such evidence. It covers a **disposable system-TEMP Synthetic Vault** only; it never authorizes a real Windows Vault, a scheduled worker, deployment, or deletion of snapshots.

## Acceptance invariants

1. At all times, `HomeHub Source` remains present at its existing path. Existing personal Markdown outside that subtree, `.obsidian`, and source checkout are byte-for-byte unchanged.
2. Before **any** managed mutation, a complete old sealed source backup and complete new sealed stage exist, verified against the exact old/new SHA and allowlisted membership. The journal identity is validated; no path supplied by an untrusted journal escapes its exact fixture.
3. The old backup, staged source, journal and any interrupted-copy evidence survive every outcome. Never silently delete, overwrite or purge evidence; stale locks require separate exact-owner confirmation.
4. When a run is interrupted, the read-only inspector must not authorize host writes. A valid content seal alone does not mean the transaction is complete if a lock, unfinished journal or preserved evidence remains.
5. **Operator-approved fixture recovery**, not automatic recovery, must restore the exact old files without overwriting unexpected human edits, unknown files or unknown evidence. Multi-file restoration itself is not atomic. Every actual restore attempt must be journaled before mutation.
6. Source hash checks, path checks, reparse and ACL checks remain stable for every file operation. The current path-based prototype does not yet establish stable Windows handle ownership or exclude noncooperating writers.
7. Any check returning unknown, corrupt, conflicting or incomplete evidence **stops**; no automatic retry or cleanup by age, wildcard or broad recursion.

## Interruption and adversarial matrix

| Phase or condition | Expected safe behavior | Current evidence |
|---|---|---|
| No-op / source ancestry diverges / master changes | No backup or managed mutation | Prior read-only planner fixtures passed; executor untested |
| Backup copy interrupted or backup fails verification | Never touch managed subtree; leave incomplete backup for review | Not tested |
| New stage copy/seal interrupted or fails | Keep old managed source intact; preserve and report partial stage | Not tested |
| Initial journal file write interrupted (`.json.tmp`) | Refuse update/recovery while pending journal exists; preserve it | Test source only; unexecuted |
| Prepared journal written but applying phase not recorded | Diagnose old seal intact, incomplete phase; no automatic resumption | Not tested |
| Crash mid changed-file temp copy | Preserve exact `.filewise-` temp bytes outside Vault during explicitly confirmed recovery; unknown temp stops | Fixture tests passed (copy-phase-specific crash injection still incomplete) |
| Crash between file replace and journal update | Old backup remains valid; managed source may be mixed; report recovery required | Fixture tests passed (copy-phase-specific crash injection still incomplete) |
| Crash during a single-file retirement | Only known managed exact path affected; unknown data retained; recovery checked | Not tested |
| Manifest temp write interrupted / before manifest replace | Old manifest fails to match mixed files; retain manifest-temp evidence | Fixture tests passed (copy-phase-specific crash injection still incomplete) |
| Crash immediately after new manifest replace, before journal says published | Verify new content seal but continue to require review until journal reconciled | Fixture inspection passed |
| Human edits a known managed Markdown filename | Refuse restore before touching any file; preserve unexpected bytes | Fixture tests passed (copy-phase-specific crash injection still incomplete) |
| Human adds an unknown managed filename / symlink / junction | Refuse and preserve; do not delete or overwrite | Unknown-file tests drafted; handle/junction tests missing |
| Forged journal path, changed source SHA, changed stage or backup | Refuse with no mutation; only exact verified membership eligible | Fixture tests passed (copy-phase-specific crash injection still incomplete) |
| Case-only Windows renames, file↔directory namespace transition | Reject before backup and any managed mutation | Preview fixtures passed earlier; executor run untested |
| Crash during artifact quarantine in recovery | Preserve earlier evidence, bounded journal-bound new attempt slot; resume only after inspection | Actual disposable child exit after preserving evidence + separate operator-confirmed recovery passed; reboot durability unknown |
| Crash during restore file copy or manifest | Preserve known temp evidence; journal records attempt; a subsequent attempt uses unique slot | Actual child exit after restore file write and second-attempt recovery passed; crash during manifest copy untested |
| Attempt counter malformed, out of bounds, or future evidence appears | Fail closed; inspect unknown; no restore | Fixture cases passed |
| Stale/altered refresh lock | Refuse lock reuse/removal; no silent recovery | Fixture tests passed (copy-phase-specific crash injection still incomplete) |
| Windows open-file sharing conflict, actual host run-as/DACL and reparse ancestor changes | Preserve backup and stop with clear operator status | **No Windows host or fixture runtime acceptance** |
| Abrupt child termination during publication and restoration | On next process, detect correct journal/backup/evidence state, restore with operator confirmation | Publisher and two restore child-exit tests passed on system-TEMP fixtures; restart/power loss untested |
| Reboot/power loss/directory fsync and persistent journal | Correctly identify and preserve incomplete state, no data loss | **Not tested; cannot infer from Python fsync alone** |
| Actual Obsidian open/watcher/search/link navigation | Brief mixed documents only, eventual full visible recovery; no personal-note/settings changes | **Separately authorized disposable host acceptance needed** |

## Current test evidence and outstanding gate

On October 14, 2026, the protected Windows Sandbox ran all 27 initial transaction
cases in two narrowly scoped selections (26 + 1 passed), including an actual
disposable publisher child-process abort. Two new tests then performed real
child exit after a restore file write and after artifact preservation;
both passed after a test-harness newline error was fixed. The full 15-module
Obsidian fixture regression subsequently passed 204 tests, 1 skipped and
66 subtests. No actual host, permanent Vault, service, network or credentials
were touched. The old tool refusal is historical, not an active Python test
block. Real-host activation, reboot/power loss, handle-stable filesystem
identity, non-cooperating writers, actual Obsidian watcher and host ACL
acceptance are still UNKNOWN.

## Next acceptance sequence

Obtain an expressly permitted **protected Windows Sandbox** test route. Prove all already drafted fault cases; add real child-process termination during restore and interruption within copy/journal writes without touching the actual Vault. After deterministic Windows green, obtain independent review, separately authorized source publication and full Linux CI. Real-host ACL/handle/watcher and task activation remain further independent gates. Until the user’s condition is fully demonstrated, keep #399 OPEN and automatic refresh OFF.

## 2026-10-14 local integrity amendment (NOT in draft PR #404)

PR #404 at commit 3ec181c6124b31d35292880f72d4e14aa5e2d17c
remains unchanged. Independent read-only Codex review identified three
MEDIUM fixture limitations: noncooperating concurrent edits, missing original
old/new manifest digest binding, and phase/content contradiction reporting.

A **new unpublished Sandbox-only candidate** updates the fixture transaction
journal to schema 2, records SHA-256 of the exact old-backup and new-stage
manifest bytes before managed mutation, refuses independently resealed
backup/stage manifests at inspection, and requires review for terminal
phase/content contradictions. Four new fixture regressions cover both
reseal attacks and both contradictory terminal phases.

**Runtime evidence on the unpublished amendment:** targeted transaction tests
33 passed, 5 subtests passed, exit 0; complete 15-module Obsidian regression
208 passed, 1 skipped, 66 subtests passed, exit 0. These results do NOT apply
to the published PR #404 head until separately reviewed/published/CI-verified.

**Still a blocking gap:** a noncooperating writer can modify a known
Markdown file between a prior byte-hash validation and subsequent replace/
unlink. The existing cooperative lock does not exclude Obsidian or human
writers. Path-based rechecks only narrow, not eliminate, this TOCTOU race.
A real-host least-privilege ACL/handle/share-mode and process-ownership
contract must be independently reviewed before any activation. Likewise,
journal hashes are self-contained evidence for accidental tamper, not a
cryptographic signature against an adversary able to change the journal.
No real Vault testing, scheduled task, merge or deployment is authorized.

## 2026-10-14 terminal managed-seal follow-up — local only

Independent read-only review of the 208-test amendment found that completed
managed content itself was not bound to the recorded original manifest
digest, even though the old backup and new stage now were. The unpublished
fixture inspector now compares the exact managed manifest SHA-256 to the
journal's expected NEW digest when the managed seal is NEW, and to the
expected OLD digest when the managed seal is OLD. On any mismatch it
returns UNKNOWN with operator review required and no host-write authority.
Two new tests reseal a successfully published/restored managed snapshot
under the same named source commit and assert rejection without changing
the stored journal or the personal Obsidian fixture notes.

Full 15-module protected Windows Sandbox suite: **210 passed, 1 skipped,
66 subtests passed**, exit 0. This result applies to the unpublished
local six-file amendment, NOT draft PR #404 at older head
3ec181c6124b31d35292880f72d4e14aa5e2d17c (whose three Linux CI jobs
were green). Journal/manifest digest evidence detects accidental changes
when the journal is intact; it does NOT cryptographically authenticate a
coordinated malicious change to content and journal, nor eliminate
noncooperating-writer TOCTOU. No real-host activation is permitted.
