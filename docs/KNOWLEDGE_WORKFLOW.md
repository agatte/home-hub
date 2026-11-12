# HomeHub Agent Knowledge Workflow

> **Status:** active repository workflow merged by [PR #367](https://github.com/agatte/home-hub/pull/367); read-only link checks merged by [PR #368](https://github.com/agatte/home-hub/pull/368). Core knowledge continuity passed under [#365](https://github.com/agatte/home-hub/issues/365), and hourly Obsidian mirror delivery was operationally verified October 22, 2026 under [#399](https://github.com/agatte/home-hub/issues/399)/[#422](https://github.com/agatte/home-hub/issues/422); both issues were completed and closed October 31, 2026 after additional dated acceptance. Today's host snapshot remains unverified.
> **Authority:** [PROJECT_SPEC.md](PROJECT_SPEC.md) and subsystem specifications for product behavior; GitHub issues/PRs and Git/runtime for implementation, delivery and evidence. This page is an assistant workflow, not a second memory store or backlog.

## Purpose and limits

Every substantive ChatGPT/Codex task should **retrieve the minimum relevant current knowledge, preserve new durable discoveries, and leave a verifiable resume point**. The repo is the durable record across new conversations and agent sessions. Neither chat memory nor a model's recollection replaces source evidence. No daemon, always-running agent, new embedding database, privileged background sync or unrestricted access is implied.

The Windows `HomeHub Knowledge Vault` is a **read-oriented Obsidian snapshot** of reviewed GitHub Markdown. Only the source repository and owning GitHub issues should be edited. The existing guarded scheduled refresh has dated operational acceptance under [#399](https://github.com/agatte/home-hub/issues/399)/[#422](https://github.com/agatte/home-hub/issues/422). New manual refreshes or host configuration changes still follow the separately authorized procedure in [OBSIDIAN_PERSISTENT_VAULT.md](OBSIDIAN_PERSISTENT_VAULT.md); do not edit managed `HomeHub Source` directly or treat a local mirror's SHA as evidence of today's GitHub state.

## Entry points by question

| Need | Consult, then verify |
| --- | --- |
| Accepted behavior or cross-system decisions | [PROJECT_SPEC.md](PROJECT_SPEC.md), then owning subsystem spec and live code |
| Current task state, next gate, ownership | Owning GitHub issue and PR, [EXECUTION_MAP.md](EXECUTION_MAP.md) for dependencies; verify status live |
| Safe tools, Sandbox, release policy | [../AGENTS.md](../AGENTS.md), [LOCAL_WORKSPACE.md](LOCAL_WORKSPACE.md), relevant runbook |
| What actually runs on Windows or Latitude | Approved live runtime/version/health evidence; never infer from a merged commit |
| Historical causes or rejected directions | Relevant dated incident/audit and its newer issue/PR links |
| Unaccepted future ideas | [Future_Development.md](Future_Development.md) and [AI_SEMANTIC_LAYER.md](AI_SEMANTIC_LAYER.md) for AI research |
| Finding current project navigation and search | [PROJECT_ADMIN_HUB.md](PROJECT_ADMIN_HUB.md), then GitHub issues and repository search |

Read a **specific** issue/spec or code surface rather than indexing the entire repo by default. At the start of substantive HomeHub work, retrieve current GitHub `AGENTS.md`, this workflow and `PROJECT_ADMIN_HUB.md`, then only task-relevant specs, owning issues/PRs and newest relevant comments. On a new chat, confirm GitHub `master`, local branch/worktree, issue/PR head and applicable gates before resuming an old handoff. Resolve dated status conflicts using newer primary evidence; an open issue can mean residual acceptance after functional success. Do not ask the user to repeat retrievable history before attempting connected GitHub retrieval. If access fails, identify the failed read and uncertainty. Before a new Sandbox worker, inspect its persistent registry per [LOCAL_WORKSPACE.md](LOCAL_WORKSPACE.md). At handoff, preserve decisions/evidence and next steps in the owning authority. Merely reading this guidance does not prove fresh-chat recovery or host acceptance.

## Three checkpoints for substantive tasks

### 1. Before work — orient
- Read `AGENTS.md` and the relevant **current** authority docs/issues/PRs; include `EXECUTION_MAP.md` for cross-issue planning.
- Check Git branch/worktree status and live facts needed for this task; protect unrelated work and intentional Windows/Latitude version differences.
- Name the **primary workstream**, current fact/hypothesis boundary, acceptance evidence, and next authorization gate. Avoid duplicate issue owners.

### 2. During work — capture
- When discovering a failure cause, design tradeoff, rejected hypothesis, invariant or dependency, note its evidence, consequence and unresolved uncertainty.
- Keep **reversible implementation and tests** in scoped Git changes. Record tests, precise SHA/PR, review findings and actual device/production observations in the owning issue.
- Check existing canonical docs before adding notes. No parallel `memory.md` issue queue, unsourced summaries, or general model-generated status claims.

### 3. Before handoff — reconcile
- Update the **smallest owning authority** when something material changes (subject to commit/push/merge/deploy gates).
- In the owning issue/PR, record what is verified, what was only tested offline, what remains blocked, and the exact next action/gate. Link the relevant commit, test, trace or runtime proof.
- Cross-link an affected specification or execution-map route if the accepted decision/dependency changed; keep dated audits historically intact.
- A new chat must be able to resume from GitHub/repo without relying on a long chat handoff. If publishing is not authorized, explicitly identify the local worktree and uncommitted evidence; never imply it is durable on GitHub.

## Where new knowledge belongs

| New information | Durable home |
| --- | --- |
| New cross-system accepted product policy | `docs/PROJECT_SPEC.md` through reviewed change |
| Accepted subsystem semantics/invariants | Owning subsystem spec + regression tests |
| Implementation bug, remediation, PR review and CI | Owning GitHub issue/PR, code/tests |
| Next gate, coordination or dependency across issues | Owning issues and concise dated `EXECUTION_MAP.md` pointer |
| Host workflow or runbook corrections | Relevant runbook / `LOCAL_WORKSPACE.md`, with authorization and evidence |
| Research or proposed model experiment | `Future_Development.md` or `AI_SEMANTIC_LAYER.md` and a bounded owner, clearly non-authoritative |
| Historical observation | Dated incident/audit plus newer status link, not rewritten history |

Update docs proportionally. A routine code change doesn't require touching every index. A factual contradiction does require a focused correction or tracked gate; do not silently resolve uncertain product behavior.

## Deterministic checks before an AI index

Use the existing **advisory** `python scripts/check_project_admin_drift.py --live` where live authenticated issue metadata is available, or `--snapshot <fixture.json>` for offline tests. It checks current issue routing, explicit closed packets and missing links to open physical acceptance gates. It does **not** prove board completeness, deployment or physical acceptance. Future enhancements should be read-only/report-first with fixed tests and reviewed corrections, not an LLM silently rewriting specs.

For model-assisted knowledge review, use bounded, sanitized evidence with source links, distinguish `supported`/`conflicted`/`unknown`, and reject invented current-status claims. A local LLM is optional: benchmark it against deterministic extraction and a cloud baseline before introducing a runtime, model downloads or system services. The bounded [local-model evaluation #366](https://github.com/agatte/home-hub/issues/366) belongs to Sensing & Intelligence, not Project Admin's knowledge authority. Follow the authority classes and provider-neutral policy in [AI_SEMANTIC_LAYER.md](AI_SEMANTIC_LAYER.md). AI output must not directly command HomeHub devices or claim physical presence.

## Independent synchronization and authorization gates

- Git/issue updates follow reviewed authority. **Commit, push and merge are distinct guarded operations**; an owner-selected low-risk milestone conditionally authorizes all three when the final scope, exact-head checks, review and mergeability pass, as detailed in [AGENTS.md](../AGENTS.md) and [PROJECT_ADMIN_HUB.md](PROJECT_ADMIN_HUB.md). **Deployment, migrations/live DB writes, host/device/lighting changes, restarts, credentials/private data and destructive work remain separately authorized**, as does high-risk integration. No general auto-merge or historical draft-only permission is inferred.
- **Last recorded Windows acceptance (October 22–31, 2026):** the existing hourly-plus-login task delivered a reviewed GitHub Markdown note naturally on October 22 under [#422](https://github.com/agatte/home-hub/issues/422). On October 31, an owner-run read-only deep check verified all 65 current managed file hashes, exact membership, the latest previous backup seal, and source-commit alignment at that checkpoint. A paired 13:00/14:00 scheduled no-change observation verified no new matching backup; the second observation did not rehash the full snapshot. #399 and #422 are now **closed**. These dated results do **not** establish today's source SHA, Vault freshness, continuous future stability or an uninspected personal-note/settings content guarantee. Do not refresh or modify the host merely to update this documentation.
- Any replacement bundle installation or Task Scheduler action change requires **separate explicit host authorization**; the existing task may not be manually started, overwritten, or repaired on this development approval. No generic host agent, blind Git update, Vault backup cleanup or wider real-host bridge authority is granted.
- Any new refresh mechanism must verify exact source commit, sealed manifest, target identity, ACLs and preservation of `.obsidian`, personal notes and previous snapshots. On unexpected state, refuse and retain evidence.
- Repo changes can be made while a host mirror is stale. Report the mirror's verified SHA, never suggest it is always current.
