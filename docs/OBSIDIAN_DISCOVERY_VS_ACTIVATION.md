# HomeHub #399 — split discovery from Vault replacement (proposed)

**Status: reviewed proposal needed, not accepted or active.** Primary owner: Project Admin.
The current GitHub issue is #399; previous Vault persistence #358 is complete.
This file is a local, uncommitted prototype in protected Windows Sandbox.

## Why separate the operations?

The candidate previously required Obsidian to appear closed before even
checking GitHub. This unnecessarily prevents safe documentation discovery.
GitHub-to-Vault freshness has two distinct responsibilities:

1. **Read-only discovery (safe to evaluate while Obsidian is open):** verify
   the existing sealed manifest without reading personal notes; pin the current
   reviewed GitHub `master` SHA through authenticated HTTPS; check ancestry,
   allowlisted documentation Git blobs, hashes and branch-ref stability;
   compute a bounded added/modified/removed path report. No Vault writes,
   staging, schedule, elevation, credentials, Git checkout update or replacement.
2. **Final managed-subtree replacement (not yet unattended-safe):** requires an
   independently approved exact Vault identity, stable target and permissions,
   exclusive updater coordination, an enforceable policy for Obsidian
   launch/startup across all relevant sessions, preservation of old snapshots,
   crash recovery and separately approved real-host operation.

`scripts/obsidian_refresh_discovery.py` implements only (1). It uses existing
sealed-manifest, GitHub source and policy modules. Possible results:
`no_change`, `update_discovered`, `blocked`, `unknown`. Every result
unconditionally sets `host_automation_authorized=false` and
`stage_authorized=false`. Even `update_discovered` is **not** approval to
stage outside or inside the real Vault. On failure it refuses before any write.

## Launch-coordination design constraint

Windows Toolhelp process snapshots answer only whether an exact process name
was present at one instant. The adversarial Sandbox test proves that an
Obsidian start after a reported-closed snapshot and before the first rename
can overlap replacement. Neither repeated polls, matching SID/owner, nor a
sibling updater mutex blocks a separate Obsidian launch.

Obsidian documents `obsidian://open` requests that open or focus a vault:
https://help.obsidian.md/Extending+Obsidian/Obsidian+URI
A wrapper around one Start Menu/Desktop shortcut therefore cannot alone
enforce the required all-entrypoint startup exclusion. A plugin that starts
only after a vault is opened also needs an independently demonstrated
early-startup protocol. **Neither approach is approved or proven.**

**Product decision still required:** either identify and independently
review a minimally scoped, enforceable cooperative startup/refresh
contract, or allow automatic discovery/reporting while retaining
operator-assisted final snapshot replacement. Do not silently substitute
the latter for the user's desired end state of an unattended mirror.

## Security gates before any real-host use

- Read-only analysis on the *actual Windows user* and approved exact target,
  including SID/elevation, owner and effective DACL, reparse/ACL identity,
  and non-overlap with source checkout; never infer from the Sandbox SID.
- Consider app startup from shortcuts, URI links, file associations, sign-in,
  restarts, other sessions, and second windows. A process polling loop is
  not an enforceable exclusion mechanism.
- Crash simulation beyond Python subprocess abort: target-handle stability,
  first/second rename windows, persistent old backup, stale lock, interrupted
  rollback, reboots and offline retries. No wildcard backup cleanup.
- Package provenance, complete Linux CI/Ruff, independent security review,
  approved publication, and later **separate real-host task activation**.
- A read-only dry-run alone is never a token/capability to write the Vault.

No host Scheduled Task, Obsidian plugin, service, ACL change, process action,
Vault modification, deployment or Git publication is authorized here.


## 2026-10-13 API quota and raw-content path

Live GitHub commit `3eadfa547cc3810414d0388269d32e5d2c59bfdc`
contains 51 `docs/**/*.md` regular blobs plus `AGENTS.md` = **52**
read-only snapshot source files. The original candidate performs two master
reads, a compare, a commit metadata lookup, root-tree and docs-tree reads,
plus one REST blob request per file: **58 unauthenticated REST API
requests** per full forward discovery. GitHub documents a default
**60/hour/IP** unauthenticated REST API budget:
https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
and https://github.com/github/docs/blob/main/data/reusables/rest-api/primary-rate-limit-unauthenticated-users.md
This is a serious reliability problem and must not be addressed by embedding
personal API credentials in the Windows updater.

Proposed bounded source path: use GitHub REST only for the 6 trusted
master/compare/commit/tree metadata requests; request exact SHA-pinned
allowlisted Markdown URLs from `raw.githubusercontent.com`, strictly
bounded by expected Git blob size with no redirects and TLS validation;
verify **every** returned file's size and Git SHA-1 blob OID from the
previously verified tree. The raw-content host is a second explicit
allowed HTTPS origin, not a general-purpose arbitrary URL downloader.
The new `obsidian_raw_blob_transport.py` is a prototype and not deployed.

The existing offline GitHub fixture transport remains injectable for
deterministic tests. Production-default discovery and preflight use the
raw transport when given their default trusted GitHub HTTPS client;
injected custom fetchers retain the older REST-shaped fixture path.
No fallback from a failed pinned raw blob to mutable content or unsigned
local mirrors is permitted. GitHub's raw-content traffic can still have
its own availability/rate constraints; success is not guaranteed merely
because the REST request count is lower.

Verification: 155 focused Windows tests passed, 59 subtests passed, one
non-Windows skip, 26 Python modules compiled; a real read-only
`AGENTS.md` fetch at the exact master SHA matched the Git tree OID
`90e4e9a1bd88b77f9f84a4d6f7228ac0304a462f` with 10,684 bytes.
No actual permanent Vault, host task, Git publication, source checkout
or app coordination was changed. No full-source live ingestion, Windows
real-host evidence, full Linux CI, Ruff or independent security review yet.
