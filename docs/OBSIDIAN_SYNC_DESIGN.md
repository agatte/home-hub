# HomeHub Obsidian Mirror Synchronization — Proposal

> **Status:** design only, tracked by [#365](https://github.com/agatte/home-hub/issues/365). No recurring task, automatic Git update or host refresh is enabled.
> **Source:** [KNOWLEDGE_WORKFLOW.md](KNOWLEDGE_WORKFLOW.md), [OBSIDIAN_PERSISTENT_VAULT.md](OBSIDIAN_PERSISTENT_VAULT.md), and the reviewed `scripts/manage_obsidian_vault.py` implementation.
> **Authority:** GitHub tracked Markdown and issues, not Obsidian. [#358](https://github.com/agatte/home-hub/issues/358) owns normal Windows reboot durability acceptance.

## Existing verified boundary

The real Windows Vault at `C:\Users\Anthony\Documents\HomeHub Knowledge Vault` was refreshed manually to verified source commit `dcacfc7eda54acad016b4a5ddf95479b43cf10aa` on 2026-10-10. A user-confirmed Obsidian reopen, search and navigation passed. Its managed `HomeHub Source` is a **sealed snapshot of one named SHA**, with `.homehub-snapshot-manifest.json` and a SHA-256 hash per tracked file. The previous snapshot remains preserved outside the Vault. The normal Windows host reboot, Vault navigation/search and preferences were subsequently operator-confirmed on 2026-10-11 and #358 closed; a newer GitHub `master` still does not update this mirror by itself.

Existing `--refresh` requires the host repo HEAD to equal an explicit expected 40-character SHA, validates the old sealed source, rejects symlinks/junctions or local edits, stages a new snapshot, and renames the old managed source to a unique sibling backup before swapping it. It does not fetch GitHub, update the host checkout, delete backups, schedule work, or prove Obsidian is closed.

## Progressive proposal

1. **Phase A: optional read-only freshness report.** Compare the Vault manifest SHA, Windows checkout SHA and current GitHub `master` SHA, with an explicit finding when unknown, unavailable, non-ancestor, or divergent. Check the approved identity of each surface. This must not traverse other host directories, inspect Vault notes, fetch credentials, update Git refs, or change any files.
2. **Phase B: explicitly authorized assisted refresh.** Present source SHA and exact changed tracked Markdown paths; stop if GitHub and host checkout are not at the same intended reviewed commit, if the repository is dirty/in a separate legitimate release state, or if the mirror integrity check fails. The operator closes Obsidian and approves the existing `--refresh --expected-head <SHA>` on the precise known Vault target. Preserve generated backup paths; never auto-delete them.
3. **Phase C: potential scheduled event/notification only after approval and real-host acceptance.** Prefer low-frequency *notification* of a new approved documentation SHA (e.g. after a merge or at interactive Windows sign-in), not a continuously polling service or an hourly background task. Do not introduce generic real-host shell, a new unrestricted Host Bridge action, an elevated task, or persistent GitHub credentials. Prove ordinary reboot and closed-app detection first.
4. **Phase D: unattended refresh only if a distinct product/security decision establishes a safe source-acquisition method, reliable closed-app detection, concurrency exclusion, bounded permission/run-as identity, backup retention policy and rollback.** A GitHub `master` SHA alone is insufficient: Windows may intentionally lead or lag, and the checked-out code may differ from production. Never force checkout alignment merely to refresh Obsidian.

## Safety acceptance matrix

| Situation | Required response |
| --- | --- |
| Vault not yet verified after reboot | Do not enable unattended refresh; leave #358 open |
| Github unavailable, SHA ambiguous, Git checkout on different commit | Report stale/unknown; no checkout, download, or refresh |
| Obsidian open or closed-state cannot be proven | Refuse unattended refresh; ask operator to close it for assisted refresh |
| Managed manifest missing, tampered or contains unexpected entries | Abort; preserve target and evidence, never overwrite |
| `.obsidian` or user notes exist outside `HomeHub Source` | Preserve unchanged; never enumerate, edit or delete them as part of refresh |
| Symlink/junction, unexpected target ACL/identity, backup/stage collision | Refuse; no generic path traversal or broad recursive cleanup |
| Refresh fails after archive rename | Preserve old snapshot backup and report exact known paths; apply existing narrow rollback semantics |
| Two refresh attempts overlap | Only one operation may own the exact target; no silent overlapping work |
| Snapshot backup count increases | Retain it; propose exact-target retention review, not a wildcard deletion |
| New docs commit on GitHub, no matched host source checkout | Report an available update; do not pull/reset/rebase host or Sandbox just to match |

## Phase A — merged read-only helper, no automatic host rollout

A merged scoped Python helper, [`scripts/check_obsidian_freshness.py`](../scripts/check_obsidian_freshness.py), compares the local checkout HEAD and the existing **fully hash-verified managed snapshot** against an *explicitly supplied* 40-character GitHub `master` SHA. Manifest hashes are **self-consistency checks, not an authenticated signature**. The caller must independently obtain/verify that SHA through an authorized GitHub read; the helper itself **does not fetch, authenticate or assume remote freshness**. Do not use a chat recollection or stale issue checkpoint as that input. Missing remote SHA produces `unknown`, not a green result.

Illustrative syntax (synthetic fixtures or a separately authorized read-only operator session; **not** approval to operate on the real Windows host):

~~~powershell
py -3 scripts/check_obsidian_freshness.py --repo 'C:\Users\Anthony\Documents\home-hub-project\main' --vault 'C:\Users\Anthony\Documents\HomeHub Knowledge Vault' --github-head '<independently-verified-exact-40-character-master-sha>'
~~~

Output is a single bounded JSON report with `checkout_head`, `vault_snapshot`, supplied `github_master` provenance, managed integrity, explicit pairwise `same`/`different`/`unknown`, and `refresh_authorized: false`. Exit 0 means three SHA values match **only the supplied reference**, 1 means mismatch or unknown, and 2 means a refused/error state (missing/tampered Vault, invalid SHA, unsafe path, unavailable Git). It checks neither Git ancestry nor worktree cleanliness, runtime deployment, Obsidian app closure, real Windows ACLs or reboot persistence; equal SHAs do not grant permission to refresh. Hash verification reads only `HomeHub Source`, never personal notes or `.obsidian`. No Git fetch/write, logging of credentials, background service, Vault mutation or retention action is included.

## Phase B — proposed assisted refresh preview (Sandbox candidate only)

Extend the **existing** `check_obsidian_freshness.py` with opt-in `--plan-refresh` for a **read-only, reviewable path list**. It must receive an independently verified GitHub SHA, require the checkout to equal that supplied SHA and be clean (including untracked files), confirm the sealed managed snapshot is hash-consistent, and verify the snapshot commit is an ancestor of checkout HEAD. Only compare `AGENTS.md` and regular `docs/**/*.md` tracked Git tree blobs. Output added/modified/removed paths and counts, never document contents or personal notes; do not open a network connection or update Git/Windows/Vault. A plan is **not** permission to run `manage_obsidian_vault.py --refresh`, even when labeled reviewable.

Example **synthetic fixture or separately authorized host operator** use (not authority to touch the real host):

~~~powershell
py -3 scripts/check_obsidian_freshness.py --plan-refresh --repo '<already-verified-checkout>' --vault '<already-verified-existing-vault>' --github-head '<independently-verified-GitHub-master-SHA>'
~~~

Exit 0 means either a reviewable proposed diff or no change; exit 1 means blocked/unknown; exit 2 means the helper refused to evaluate a corrupt/unsafe/unavailable source. The `refresh_authorized` field remains `false` always. Do not use this assistant CLI as an unattended refresh gate; operator still closes Obsidian, inspects the specific preview, approves a guarded exact-target refresh separately, and preserves all old backups. The script cannot prove Obsidian is closed or verify source authenticity beyond the explicitly supplied remote SHA.

**2026-10-11 lifecycle checkpoint:** [#358](https://github.com/agatte/home-hub/issues/358) was completed following operator-confirmed normal Windows reboot survival of the real Vault, post-reboot link navigation, search and preferences. [#376](https://github.com/agatte/home-hub/issues/376) records a separate recovered Sandbox startup failure; neither closure authorizes automatic sync or any host action.

## Implementation constraints / evidence gate

Test the Phase A report with synthetic manifest/checkout/SHA fixtures in protected Windows Sandbox and review its read-only behavior before publishing or authorizing real-host use. Its output should record the manifest SHA, proposed intended commit, whether source and target are verified, and a reason for any abstention. Inputs must be allowlisted and secrets excluded; no raw production DB, app settings, personal notes or logs. A later trigger would need independent authorization, host review, per-user scheduling/no elevation, strict concurrency and failure tests, and post-run Vault/GUI validation.

No unattended host refresh, scheduled task, model installation or Windows automation is authorized by this proposal. The accepted existing manual refresh remains the fallback until a specifically reviewed and approved mechanism is proven. Avoid implying that ChatGPT runs continuously between conversations.
