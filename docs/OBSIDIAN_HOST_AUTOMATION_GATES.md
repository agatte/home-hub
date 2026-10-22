# #399 automatic Obsidian refresh — host safety acceptance gates

**Status:** REVIEW DRAFT, NOT AUTHORIZED FOR HOST USE. Implementation and tests
are in a disposable protected Windows Sandbox clone, not merged or deployed.
GitHub is authoritative; the permanent Windows Obsidian Vault is a read-only
mirror, not a write source or assistant memory. No unattended task exists.

## Observations available in the current candidate

- A complete Windows Toolhelp process snapshot can report `obsidian.exe`
  present, absent, or unknown, across sessions. Names can be spoofed or
  renamed, and a snapshot does **not** prevent later process startup.
- The Windows access-token user SID and elevation flag can be read with
  `OpenProcessToken` and `GetTokenInformation`, and exact fixture-directory
  owner SIDs via `GetNamedSecurityInfoW`. The probe refuses elevation, SID
  mismatch, path links, missing directories, or unknown observations. It
  does **not** evaluate effective DACL rights, deny ACEs, inheritance, or
  handle-stable file identity. Ownership equality is necessary evidence in
  this draft, never sufficient evidence for actual host write rights.
- The read-only dry-run consults identity, process presence, sealed snapshot,
  and authenticated GitHub documentation provenance. It explicitly returns
  `host_automation_authorized=false` for every result, including success
  and no-op. It never stages files or creates a refresh lock.

## Required host acceptance before ANY unattended activation

1. **Run-as and exact target:** user-approved immutable target path and
   intended interactive user SID; ordinary unelevated token; explicit
   checked owner/DACL/inherited ACL for Vault, managed subtree and sibling
   staging/backup/lock parent. No authority to change ACLs or accounts.
2. **Path stability:** reject symlink/junction/reparse in every ancestor.
   Establish stable, handle-level target identity against renames during
   the transaction, with exact-target recovery on ambiguity. Path.getstat
   and a preflight `Path.resolve()` alone are subject to TOCTOU.
3. **Closed-app coordination:** **critical unresolved design gate.**
   A Toolhelp observation just before swap cannot exclude a new Obsidian
   launch between check and the first/second rename. An accepted design
   needs a cooperating launcher/plugin or another independently reviewed,
   enforceable mechanism that covers app starts across relevant sessions.
   Alternatively retain manual operator-assisted refresh while app closed.
   Do not infer automatic write permission merely from repeated polling.
4. **Crash/restart and backup:** two renames are *not an atomic exchange*.
   Test interruption after old managed subtree moves to backup, before new
   is installed, after new is installed, and rollback failure. Never erase
   unknown backups, refuse ambiguous recovery, and preserve exact old
   snapshot and notes even when Vault managed directory is temporarily
   absent. Define explicit audit, retry/backoff and backup retention.
5. **Source and automation:** bounded GitHub HTTPS SHA/blob/tree verification;
   expected docs changes and ancestry, no checkout alignment; no tokens
   or new generic host access. Choose a narrowly scoped per-user trigger
   and document its interval/offline behavior/credentials. Review source
   dependency provenance and import boundaries before host installation.
6. **Integration evidence:** independent security review, Ruff/full Linux CI,
   Windows actual host dry-run, owner/ACL evidence, Obsidian open/close race,
   reboot/offline tests, user-note and .obsidian hash preservation, explicit
   publication and **separate host activation authorization**.

## Current test boundary

The protected Windows Sandbox tests exercise Python functions and synthetic
Vaults. They do **not** prove the real host SID, ACL, target identity, Obsidian
installation, Scheduled Task state, or persistent Vault safety. Native Git,
Pydantic extension and Ruff remain blocked by Windows Smart App Control;
the pinned Dulwich guest-TEMP clone is a temporary read-only development
fallback. #401 tracks native Git recovery separately.

**Decision to resolve:** agree on enforceable Obsidian launch coordination
versus the existing assisted manual refresh fallback. Until then, keep the
automatic updater unactivated and #399 OPEN.


## 2026-10-13 crash and launch-race evidence (not acceptance)

The separate `obsidian_refresh_recovery.py` is a **read-only**
exact-suffix recovery inspector. For a sealed, intact managed tree it can
distinguish prepared-only, completed-with-retained-backup, and old-intact
states. For missing managed targets, unexpected commits, stale locks,
tampered files or ambiguous backup/stage combinations it returns a
stop-and-review observation. It never restores/deletes a backup, clears a
lock or authorizes a refresh. In disposable Windows tests a distinct
child Python process performed the first exact rename then exited via
`os._exit(73)`; the parent observed the interrupted state and preserved
both staged and backup targets. A **host reboot/power-loss test was not
performed**.

An adversarial fixture also makes Obsidian 'start' after the last
`app_probe() == closed` observation but before the old managed tree is
renamed. The fixture-only `swap_only_after_rechecks` still completes
because this callback checks process presence but does NOT own the
application launch protocol. It always returns
`authorized_host_automation=false`. **Do not treat this behavior as a
successful safety acceptance test**. Repeated checks, matching SID/owner,
and even a retained sibling refresh lock cannot prevent an unrelated
Obsidian startup. Before unattended host activation require a reviewed
cooperating app-start protocol or a distinct explicit risk/product decision;
otherwise stick to assisted final replacement only.


## 2026-10-13 independent review and staged membership integrity

A separate **read-only Sandbox Codex** static review (task
d2fe41d1df5e4d2a9dd2ecad363ac848) inspected the 29-file candidate and
the existing Vault manager. It confirmed the Obsidian startup race and
identified a stage-trust gap: verifying a locally resealed manifest and
expected GitHub source files alone allowed extra Markdown files or changed
generated pages to pass. A bounded fix now shares deterministic generated
pages between stage creation and swap, compares exact staged manifest
membership to the verified Git tree plus only those two generated pages,
and compares generated-page bytes. Synthetic Windows tests demonstrate
rejection of an injected Markdown page and both altered generated pages
even after a fresh local reseal.

A second read-only independent follow-up (task
0934630954e14eecbdd90464cc4c924f) found that a later app/head-probe
callback could reseal the stage *after* the first validation. The candidate
now calls the same strict stage validation a second time after those
callbacks and immediately before the first rename. Adversarial tests
tamper and reseal within each callback; the swap now refuses while leaving
the old managed snapshot and personal settings untouched.

**Critical limitation remains:** repeated path-based validation is still
racy after the final check and before/during the two Windows renames.
A local writer with sufficient rights, a replaced ancestor/reparse target,
or newly launched Obsidian can still cause a data-integrity/lifecycle
hazard. The design does not own handle-stable stage identity, restrictive
DACLs, an all-launch-path Obsidian coordination contract, or an atomic
directory exchange. No unattended real-host actuator may rely on this
prototype. Other review limitations: commit/tree provenance is trusted
through the authenticated GitHub metadata service rather than recomputing
tree object hashes; the source code verifies individual Git blobs. That
is a documented trust boundary, not cryptographic self-authentication.

Live read-only Sandbox transport acceptance: all **52** allowlisted
source files at pinned master SHA 3eadfa547cc3810414d0388269d32e5d2c59bfdc
were fetched and Git-object-verified, 1,435,536 source bytes, using
3 REST commit/tree metadata requests for the already-pinned SHA, and
zero REST blob requests. A normal unpinned refresh needs 6 REST calls
because of master/ancestry checks. The final Windows focused suite
(including the new reseal and callback-time tests) was **160 passed,
1 skipped, 61 subtests passed**, with **26 Python modules compiled**.
This is **not** a full Linux CI/Ruff run or real host verification.
