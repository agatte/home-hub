# HomeHub Project Admin Hub

> **Purpose:** Find the right source quickly. This is a navigation and workflow guide, **not** a product specification, live health report, or second backlog.
> **Established:** 2026-10-08. Implementation tracker: [#339](https://github.com/agatte/home-hub/issues/339).
> **Verified dashboard:** [Private HomeHub GitHub Project #1](https://github.com/users/agatte/projects/1), created and linked to `agatte/home-hub` on 2026-10-08 after authenticated owner/repository inventory found no existing Project. See [#339](https://github.com/agatte/home-hub/issues/339) for setup and remaining follow-up gates.

## Start with the question

| Question | Where to look | Rule |
|---|---|---|
| What should HomeHub do, or what product decision was accepted? | [PROJECT_SPEC.md](PROJECT_SPEC.md), then the relevant subsystem specification | Cross-system product policy is authoritative in PROJECT_SPEC; do not elevate a brainstorm or old issue to policy. |
| What is the next bounded task, blocker, or acceptance gate? | [Open GitHub issues](https://github.com/agatte/home-hub/issues?q=is%3Aissue%20is%3Aopen) and the owning parent/child issue; [EXECUTION_MAP.md](EXECUTION_MAP.md) for dependencies and model/depth | Issue state and current evidence supersede dated execution snapshots. |
| What was implemented, reviewed, or merged? | Git commits, pull requests, CI, and the owning issue | A merged PR is not proof of deployment or physical acceptance. |
| What is actually deployed or healthy? | Direct Latitude/Windows version, health and operator evidence | Do not infer production state from a GitHub branch, release plan, or historical audit. |
| How should an agent operate safely? | [../AGENTS.md](../AGENTS.md), [LOCAL_WORKSPACE.md](LOCAL_WORKSPACE.md), and relevant runbooks | Observe the separate commit/push/merge/deploy/restart/device/credential gates. |
| Why was a decision made, or what was rejected? | Subsystem specs, owning issues/PRs, and dated [audits](audits/) | Preserve historical evidence; add current cross-references instead of rewriting conclusions. |
| Where do speculative ideas go? | [Future_Development.md](Future_Development.md) | Ideas are not approved product commitments or implementation-ready tickets. |

The [documentation index](README.md) routes to subsystem material. [Roadmap issue #142](https://github.com/agatte/home-hub/issues/142) is a portfolio index, **not** a parallel execution queue.

## Workstreams: one primary owner, linked dependencies

These are navigation routes, not a rewrite of existing issue ownership:

| Workstream | Helpful entry points |
|---|---|
| Project Admin | [AGENTS.md](../AGENTS.md), [LOCAL_WORKSPACE.md](LOCAL_WORKSPACE.md), [#339](https://github.com/agatte/home-hub/issues/339) |
| House State & Automation | [PROJECT_SPEC.md](PROJECT_SPEC.md), [PRESENCE_LIGHTING_SCENARIOS.md](PRESENCE_LIGHTING_SCENARIOS.md) |
| Lighting & Atmosphere | [LIGHTING_EXPANSION.md](LIGHTING_EXPANSION.md), [#244](https://github.com/agatte/home-hub/issues/244) |
| Sensing & Intelligence | [ML_SPEC.md](ML_SPEC.md), [CONFIDENCE_FUSION.md](CONFIDENCE_FUSION.md), [#240](https://github.com/agatte/home-hub/issues/240) |
| Devices & Integrations | [PROJECT_SPEC.md](PROJECT_SPEC.md), [audio ownership #276](https://github.com/agatte/home-hub/issues/276), [Blue Yeti acceptance #334](https://github.com/agatte/home-hub/issues/334) |
| Dashboard UI | [DASHBOARD_REDESIGN_VISION.md](DASHBOARD_REDESIGN_VISION.md), [#157](https://github.com/agatte/home-hub/issues/157) |
| Game Day & Sports | [GAMEDAY_SPEC.md](GAMEDAY_SPEC.md), [GAMING_EXPERIENCE_SPEC.md](GAMING_EXPERIENCE_SPEC.md) |
| Runtime & Infrastructure | [LOCAL_WORKSPACE.md](LOCAL_WORKSPACE.md), [security program #284](https://github.com/agatte/home-hub/issues/284) |

## Operational dashboard: private GitHub Projects board

[**Open HomeHub Project #1**](https://github.com/users/agatte/projects/1). Authenticated GitHub CLI/GraphQL inventory confirmed no personal or repository-linked Projects before creation. The board is **private**, explicitly linked to `agatte/home-hub`, and initially contains all **89 open issues** inventoried on 2026-10-08. This is a dated coverage snapshot, not a promise that future issues will automatically appear. Do not create a second HomeHub board.

Keep **one project across workstreams** using existing GitHub issues, with these verified minimal fields:

- **Status:** Backlog, Ready, In Progress, In Review, Waiting, Done. Closing an implementation issue means its implementation is done, **not** that physical or production verification happened.
- **Workstream:** exactly one of the eight workstreams above; record cross-boundary dependencies in linked issues, not two owners.
- **Next Gate:** None, Decision, Evidence, CI/Review, Approval, Deployment, Physical Acceptance, Dependency. This is the *next* gate, not a substitute for full acceptance criteria.
- Reuse existing issue labels for priority, horizon, type and effort. Do not create a second priority/effort taxonomy in project fields.

The board has seven **saved views**, verified from GitHub's live Projects API:

- **All Work** — unfiltered table across the linked issues.
- **Ready to Start** — `status:Ready`.
- **Active & Review** — board view, `status:"In Progress","In Review"`.
- **Needs Approval** — `next-gate:Approval`.
- **Release & Physical Acceptance** — `next-gate:Deployment,"Physical Acceptance"`.
- **Evidence/Dependency Blocked** — `status:Waiting next-gate:Evidence,Dependency`.
- **Parked/Research** — `status:Backlog`.

Initial conservative triage assigned a primary Workstream and Status to all 89 open issues (80 Backlog, 7 Waiting, 2 In Progress) and a specific Next Gate to 21. **No issue was marked Ready solely from horizon or priority labels.** Notable gates: [#334](https://github.com/agatte/home-hub/issues/334) Physical Acceptance, [#240](https://github.com/agatte/home-hub/issues/240) Evidence, and [#339](https://github.com/agatte/home-hub/issues/339) Approval for the remaining project-admin integration step. A merged PR is never itself proof of deployment or hands-on acceptance.

Future issues are **not yet automatically enrolled**; review project coverage periodically until an explicitly approved native GitHub workflow is configured. Verify saved-view behavior in the browser as part of regular use; API verification confirms each saved layout/filter, not a human visual rendering of every view.

### Direct GitHub issue searches (fallback and cross-check)

These remain useful live cross-checks, not replacements for the saved Project views:

- [All open issues](https://github.com/agatte/home-hub/issues?q=is%3Aissue%20is%3Aopen)
- [Current-horizon candidates](https://github.com/agatte/home-hub/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22horizon%3Anow%22) — inspect actual readiness before starting
- [Priority P1 candidates](https://github.com/agatte/home-hub/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22priority%3Ap1%22)
- [Recently updated issues](https://github.com/agatte/home-hub/issues?q=is%3Aissue%20sort%3Aupdated-desc)
- [Open pull requests](https://github.com/agatte/home-hub/pulls?q=is%3Apr%20is%3Aopen)

## Dated orientation checkpoint — 2026-10-08

These are **examples of current routing**, not a permanent priority list. Recheck the issues before working:

- [#246](https://github.com/agatte/home-hub/issues/246) per-light manual override persistence and [#283](https://github.com/agatte/home-hub/issues/283) Blue Yeti implementation are **closed**; don't carry them as new implementation tasks. [#334](https://github.com/agatte/home-hub/issues/334) separately owns the Blue Yeti *post-deploy physical unplug/replug* acceptance gate.
- [#276](https://github.com/agatte/home-hub/issues/276) remains the central Sonos ownership sprint. [#336](https://github.com/agatte/home-hub/issues/336) Away pause implementation is closed; [#337](https://github.com/agatte/home-hub/issues/337) assisted ShareLink authority remains open. [#274](https://github.com/agatte/home-hub/issues/274) and [#273](https://github.com/agatte/home-hub/issues/273) preserve related ownership and queue-release limitations.
- [#240](https://github.com/agatte/home-hub/issues/240) remains gated on real evidence, not another speculative replay implementation.
- [#284](https://github.com/agatte/home-hub/issues/284) and children [#287–#296](https://github.com/agatte/home-hub/issues/284) hold the staged security program; dependencies and safety gates are issue-owned.
- No production deployment, physical acceptance, or credential/device action is established by this **documentation checkpoint**. Verify live runtime separately.

## Maintenance contract

At each meaningful change of a decision or gate, update **only the owning authority** and link to it:

1. **Product decision:** PROJECT_SPEC or subsystem spec, with the governing issue/PR linked.
2. **Implementation or acceptance:** issue/PR/CI; separate operational follow-up if a hands-on or release gate survives closure.
3. **Cross-issue dependency/order:** EXECUTION_MAP; keep only a concise, dated checkpoint and links, not duplicate issue bodies.
4. **Historical audit:** leave evidence intact; add a short current-status link, never silently overwrite its original findings.
5. **Idea/research:** Future_Development until promoted with an owner and smallest evidence gate.

For a weekly or post-merge Project Admin reconciliation, compare live open/closed issues, PRs, the map's *dated* status references, and pending release/physical gates. Flag stale links, closed items presented as upcoming, duplicated owners, and missing gate follow-ups. Any future automation should initially be **read-only and report-only**; never auto-close issues, rewrite policy, or claim live deployment from a merged SHA.

### Read-only status drift check (pilot)

Run `python scripts/check_project_admin_drift.py --live` from the repository root for an **advisory** current-issue report. It reads only GitHub issue metadata via HTTPS; `GH_TOKEN` or `GITHUB_TOKEN` may be supplied by an authorized runner when the repository is private. No credential values are printed. For offline tests or disconnected operation, use `--snapshot path/to/issues.json` (a JSON list or `{"issues": [...]}` of issue number, state, and title). Add `--strict` only when the report should exit nonzero on drift.

This pilot checks open issue owners in the **current** execution-map routing table, historical packet headings explicitly marked `(closed implementation)`, and open issue titles beginning `Post-deploy physical acceptance:` that are missing from current hub/map navigation. Old reconciliation dates are advisory. This is **not** a whole-backlog completeness audit or a GitHub Projects configuration check; it never edits issues, assumes deployment, or claims a physical test passed. Keep scheduled delivery and any future CI enforcement as separately reviewed follow-ups.

**Optional knowledge browsing:** Obsidian or a private local docs site may read the same repo Markdown. Do not introduce a second editable backlog, enable automatic vault Git operations, or publish internal household/security/operations docs to a public site.
