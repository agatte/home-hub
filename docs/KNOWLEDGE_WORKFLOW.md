# HomeHub Agent Knowledge Workflow

> **Status:** active repository workflow merged by [PR #367](https://github.com/agatte/home-hub/pull/367); optional read-only link checks merged by [PR #368](https://github.com/agatte/home-hub/pull/368). Remaining audits and mirror synchronization are tracked by [#365](https://github.com/agatte/home-hub/issues/365).
> **Authority:** [PROJECT_SPEC.md](PROJECT_SPEC.md) and subsystem specifications for product behavior; GitHub issues/PRs and Git/runtime for implementation, delivery and evidence. This page is an assistant workflow, not a second memory store or backlog.

## Purpose and limits

Every substantive ChatGPT/Codex task should **retrieve the minimum relevant current knowledge, preserve new durable discoveries, and leave a verifiable resume point**. The repo is the durable record across new conversations and agent sessions. Neither chat memory nor a model's recollection replaces source evidence. No daemon, always-running agent, new embedding database, privileged background sync or unrestricted access is implied.

The Windows `HomeHub Knowledge Vault` is a **read-oriented Obsidian snapshot** of a single reviewed Git commit. Only the source repository and owning GitHub issues should be edited. Vault refresh remains user-authorized and guarded via [OBSIDIAN_PERSISTENT_VAULT.md](OBSIDIAN_PERSISTENT_VAULT.md) and `scripts/manage_obsidian_vault.py`. Do not edit `HomeHub Source` directly or treat a local mirror's SHA as evidence of today's GitHub state.

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

Read a **specific** issue/spec or code surface rather than indexing the entire repo by default. On a new chat, confirm the current GitHub `master`, local branch/worktree, issue/PR head and applicable gates before resuming an old handoff. If source material is stale, mark the discrepancy and verify rather than silently treating it as current.

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

- Git/issue updates follow existing reviewed authority; **commit, push, merge, deploy, host writes, restart and credential changes are separate gates**.
- Automatic Obsidian refresh is a **distinct future design** ([review proposal](OBSIDIAN_SYNC_DESIGN.md)). No scheduled task, host agent, blind Git update, Vault backup cleanup or wider real-host bridge authority is authorized by this workflow.
- A future sync must verify exact source commit, sealed manifest, target identity, ACLs and preservation of `.obsidian`, personal notes and previous snapshots. On unexpected state, refuse and retain evidence.
- Repo changes can be made while a host mirror is stale. Report the mirror's verified SHA, never suggest it is always current.
