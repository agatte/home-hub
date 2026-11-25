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

## Project continuity across conversations (#365)

This owner-approved expansion (2026-11-24) captures the meaning of substantive work sessions, not verbatim transcripts. It extends the existing workflow; neither the existing scoped continuity acceptance nor merging these instructions proves this expanded outcome. See [owner-approved trial and baseline](https://github.com/agatte/home-hub/issues/365#issuecomment-7141844469).

### Anchor the objective and limit drift

Before a milestone or a new conversation, recover the owning issue's original owner goal, latest explicit changes to that goal, user-visible acceptance criteria, primary workstream, current bounded milestone, excluded work and exact next gate. Record a compact anchor in the owning issue if missing; reuse an existing current anchor instead of copying the entire roadmap. A generic "continue" retains the objective and approvals; it does not authorize a different goal.

For every newly discovered dependency, classify it as a **demonstrated blocker**, **independent important finding**, or **idea/hypothesis**. A blocker record must identify the acceptance criterion at risk, reproducible evidence, smallest safe remedy or reason no safe alternative exists, owner and exit condition. Unknown severity is not evidence of a blocker. Preserve and route independent findings to their owning issues or future-development notes without silently promoting them to the critical path. Never bypass security or safety to meet an objective; if no safe bounded alternative exists, hold at the documented gate. Material scope/risk/priority changes require the owner's decision. Recheck the anchor before delegating, expanding scope, publishing, or declaring completion.

### Incremental session checkpoint

Persist a compact checkpoint in the owning issue/PR when substantive decisions, implementation progress, failed approaches, new dependencies or authorization gates change; also before delegation or handoff and after a meaningful worker/test/review result. In long active sessions, check for unsaved material progress roughly every 15–20 minutes or before a context-heavy step, whichever comes first; no unattended timer or guaranteed end-of-chat hook is implied. Avoid no-change comments and duplicate evidence. Before a worker launch record intent and scope; immediately after launch capture the durable registry ID and recovery route. Use an existing source-controlled local artifact only if publishing is not authorized, and explicitly record the local recovery location where permitted.

Use this compact format (omit irrelevant fields; never omit unresolved gates):

- **Date / owner / objective:** owning issue and acceptance criterion; link the controlling owner decision.
- **Change / why:** concise decisions, user preferences, evidence and material findings; mark proposal versus accepted decision, hypothesis versus verified result.
- **Recovery:** exact Git base/head/PR, worktree and task ID where applicable; verified tests and review links, failed approaches and unresolved risks. Re-read live refs/registry before resuming; a recorded PID is historical.
- **State:** implemented / technically verified / operationally validated / owner-accepted, or unknown, separately. No inferred authorization or acceptance.
- **Next:** one executable step, dependency or approval gate; route side discoveries to the existing owner, or mark as unaccepted ideas in the existing future-development notes.

A conversation with a material product decision but no code also warrants capture. Routine acknowledgements, duplicate test logs and generic progress need no durable entry. Keep public repository records sanitized and project-relevant; no raw chats, account exports, unrelated personal details, credentials, private data or hidden reasoning. An owner's idea is not permission for account/host/device actions or implementation outside the selected scope.

### Journal, consolidation and selective retrieval

Owning issue/PR comments are the detailed chronological session journal. Reviewed Markdown (this workflow, existing project/admin and subsystem docs, dated notes as appropriate) is the compact Vault-readable view; issue comments are not mirrored directly. Promote accepted durable decisions/preferences to their owning spec, meaningful rejected approaches to dated evidence, and unaccepted ideas to the existing future-development home. Link sources instead of copying them into a competing backlog. A rolling summary can supersede an older summary without changing the historical evidence or erasing unresolved findings.

At every meaningful user-visible milestone closure and before an anticipated chat/context handoff, reconcile material changes into the relevant [DEVELOPMENT_JOURNAL.md](DEVELOPMENT_JOURNAL.md) entry. If context ends unexpectedly, do this on first safe recovery after checking the owning issue/PR and live work; capture current evidence before resuming. Record accepted versus pending outcomes, durable preferences and discoveries, source links/revisions, and the next gate. Keep exact technical recovery evidence in the owning issue/PR; do not copy its comment stream. Batch journal changes with already-authorized documentation/milestone work when practical, otherwise use a narrow reviewed docs change within the owner's scope. If publication is unavailable or not authorized, record the outstanding reconciliation and exact recovery location in the owning checkpoint; do not imply the Vault is current. A weekly review during active work is a backstop, not a replacement. No new PR for routine/no-change updates, no automatic transcript hook, and no new feature prerequisite solely for journal publication. The first genuine cutoff trial [#365 evidence](https://github.com/agatte/home-hub/issues/365#issuecomment-7153197996) demonstrated successful task recovery but a stale Vault-readable summary; this rule addresses that specific gap. Aim for 100–300 words per checkpoint, a 300–500 word weekly summary when useful, and a concise monthly milestone history; these are targets, not truncation rules. Consolidate repeated facts and progress; after roughly 30 days prefer summaries over detailed recent-session reading, and after roughly 90 days prefer monthly milestone history over weekly summaries unless needed for evidence. Preserve active tasks, unique failures/evidence, decisions, permissions and unresolved ideas regardless of age. Do not delete issues/comments, raw exports, Git history, Vault snapshots or backups under this policy. Historical import remains a separate opt-in, locally filtered and privacy-reviewed task; automatic full-chat collection is not established.

Fresh session retrieval order: current AGENTS/workflow/admin hub → relevant journal entry → owning issue's compact current anchor → linked active PR metadata and latest issue/PR checkpoints → live Git/runtime and worker registry as needed → targeted spec/evidence/history. Resolve contradictory dates/status before presenting one coherent status or acting.

**Context budget:** Start with the anchor and about three recent material comments per active owner/PR; expand only to answer a specific unresolved question or establish required review/acceptance evidence. Prefer metadata-only PR reads, specific file ranges or functions, compact CI/job results, and bounded failing log excerpts. When an authorized connector fetches entire histories/diffs by design, project to needed fields and selected records inside the tool orchestration before returning content to the model; do not mistake model-side projection for reduced server retrieval. Where an approved read-only route supports it, use paged GitHub REST issue/PR conversation comments: get current count and revision, request the last page (e.g. five per page), fetch at most one preceding page if needed, and recheck count/revision if concurrent changes are possible. Use a known checkpoint timestamp with bounded `since` reads to detect edits/new comments beyond a saved anchor; exact linked comments and relevant review threads still need inspection. Example verified against public HomeHub metadata in positively identified protected Sandbox: #461 had 424 comments, four retrieved to inspect the latest three; #580 had 13, three retrieved. Do not use this public route for private data or invent credentials; on access failure use the connected tool with narrow projection, and report any unavailable evidence. No new client/daemon or privilege change is required.

Reuse prior test results, source inventories and review findings when their exact relevant inputs/refs and assumptions still hold; recheck changed head/base, live runtime state, review/authorization, safety-critical gates and any uncertainty. Do not repeat stable investigations merely because a new chat started. Use compact progress/output summaries rather than repeated full diffs, giant file dumps or unchanged CI polls; expand when risk or a concrete failure requires it. A small context target never permits skipping safety evidence. Record recovery elapsed time, records/bytes surfaced where measurable, duplicate investigations and prompts; do not infer token cost from comment counts.

**Current anchor maintenance:** At meaningful slice closure, a changed decision, changed next gate, or anticipated handoff, replace the compact current section at the top of the owning issue (and relevant active PR if its opening status is materially stale). Preserve dated prior requirements, comments and unique evidence; label older status historical. Link exact refs, accepted/pending outcomes, important decisions and next gate. Reconcile the journal at the same meaningful boundary or first safe recovery after cutoff, not for every test/comment. Check issue AND active PR discussion: a PR can contain newer evidence without changing the owning issue revision. If publication is blocked, leave an exact pending reconciliation pointer. Never promote a dated summary above current authoritative evidence or relax approval boundaries.

### Real acceptance trial

Use remaining #461/#254 work rather than inventing a test change. The [latest #461 checkpoint](https://github.com/agatte/home-hub/issues/461#issuecomment-7141601367) reports #568 merged but not deployed/owner-accepted; the [#254 recovery checkpoint](https://github.com/agatte/home-hub/issues/254#issuecomment-7141611534) identifies the actual non-actuating music session planner Write task to recover. These are dated source pointers, not fresh task/runtime proof. Keep Dashboard UI primary; admin trial is not a release blocker.

Record in #365 at least two genuine fresh-session recoveries, including one interrupted/in-flight task, one captured incidental discovery, and a real blocker classification if encountered. Measure retrieval elapsed time, duplicated reads/investigation, avoidable owner prompts, scope changes, checkpoint size and missing or stale evidence; explicitly mark unavailable metrics. Historical baseline is the Nov 14–15 #461 scope correction, not an invented time/cost estimate. Coordinate overlapping delivery metrics with #504. Acceptance requires evidence of usable recovery, preserved original intent and idea retrieval, plus independently witnessed natural delivery of reviewed Markdown to the existing Vault through a permitted read-only path. Do not claim ongoing coverage of every chat or physical acceptance from a docs merge.

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

For the continuity journal, add `--check-journal` to that existing advisory command. This checks only the recent-session section for valid dated headings, missing source/next-step links, exact repeated paragraphs, relative link problems, and age or later issue-update notices. A notice is a prompt for human/assistant review, not proof that a decision is stale, an idea is redundant, or a task is complete. For frequently changing work, record a compact `**Source revisions:** #461 @ 2026-11-24T19:28:05Z` line in the journal entry, using the exact observed GitHub issue `updated_at` value after retrieving its decision/checkpoint (semicolon-separated for multiple linked owners). Never invent timestamps. The checker compares these optional markers against supplied issue metadata, including same-day changes; missing metadata is an advisory unknown, not a pass. A matching timestamp does not establish semantic freshness, comment coverage, or authorization, and an unrelated update can trigger a notice. Always read the latest owning issue body and relevant comments before resuming; older entries without revision markers retain the date-only advisory. No automatic compaction, write, background schedule or deletion occurs. When a real session changes, update its existing summary rather than append repetitive progress; preserve unique discoveries, evidence links, and unresolved gates.

For model-assisted knowledge review, use bounded, sanitized evidence with source links, distinguish `supported`/`conflicted`/`unknown`, and reject invented current-status claims. A local LLM is optional: benchmark it against deterministic extraction and a cloud baseline before introducing a runtime, model downloads or system services. The bounded [local-model evaluation #366](https://github.com/agatte/home-hub/issues/366) belongs to Sensing & Intelligence, not Project Admin's knowledge authority. Follow the authority classes and provider-neutral policy in [AI_SEMANTIC_LAYER.md](AI_SEMANTIC_LAYER.md). AI output must not directly command HomeHub devices or claim physical presence.

## Independent synchronization and authorization gates

- Git/issue updates follow reviewed authority. **Commit, push and merge are distinct guarded operations**; an owner-selected low-risk milestone conditionally authorizes all three when the final scope, exact-head checks, review and mergeability pass, as detailed in [AGENTS.md](../AGENTS.md) and [PROJECT_ADMIN_HUB.md](PROJECT_ADMIN_HUB.md). **Deployment, migrations/live DB writes, host/device/lighting changes, restarts, credentials/private data and destructive work remain separately authorized**, as does high-risk integration. No general auto-merge or historical draft-only permission is inferred.
- **Last recorded Windows acceptance (October 22–31, 2026):** the existing hourly-plus-login task delivered a reviewed GitHub Markdown note naturally on October 22 under [#422](https://github.com/agatte/home-hub/issues/422). On October 31, an owner-run read-only deep check verified all 65 current managed file hashes, exact membership, the latest previous backup seal, and source-commit alignment at that checkpoint. A paired 13:00/14:00 scheduled no-change observation verified no new matching backup; the second observation did not rehash the full snapshot. #399 and #422 are now **closed**. These dated results do **not** establish today's source SHA, Vault freshness, continuous future stability or an uninspected personal-note/settings content guarantee. Do not refresh or modify the host merely to update this documentation.
- Any replacement bundle installation or Task Scheduler action change requires **separate explicit host authorization**; the existing task may not be manually started, overwritten, or repaired on this development approval. No generic host agent, blind Git update, Vault backup cleanup or wider real-host bridge authority is granted.
- Any new refresh mechanism must verify exact source commit, sealed manifest, target identity, ACLs and preservation of `.obsidian`, personal notes and previous snapshots. On unexpected state, refuse and retain evidence.
- Repo changes can be made while a host mirror is stale. Report the mirror's verified SHA, never suggest it is always current.
