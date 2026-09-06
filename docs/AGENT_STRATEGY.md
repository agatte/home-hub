# Historical agent-strategy record

> **Legacy / historical:** This document records a past tooling strategy. It is
> not the active agent workflow or a required operating guide. Use
> [`AGENTS.md`](../AGENTS.md) for current repository operation and
> [`docs/PROJECT_SPEC.md`](PROJECT_SPEC.md) for product and architecture truth.

**Captured 2026-05-06. Last full tooling review 2026-05-11.** The material
below is retained as historical provenance for the former Claude Code tooling
layer, including agent fleets, hooks, skills, MCP servers, LSP plugins, data
files, and runbook integration.

## Fleet at the time of this strategy (31 agents)

| Agent | Tier | Status | Spawn mode |
|---|---|---|---|
| `homehub-verifier` | core | shipped, auto disabled 2026-07-13 | historical auto via checkback-loop + manual checklist |
| `homehub-investigator` | core | shipped, auto disabled 2026-07-13 | historical auto via watcher-loop; checklist only |
| `homehub-remediator` | core | shipped, auto disabled 2026-07-13 | historical watcher-loop handoff; no active Codex remediation path |
| `deploy-verifier` | core | shipped, auto disabled 2026-07-13 | checklist reference for Codex `$deploy-home` verification |
| `lighting-curator` | 1 | shipped | hook-gated (pre-commit) + manual |
| `lighting-shopper` | 1 | shipped | manual |
| `doc-drift-checker` | 1 | shipped | manual + monthly runbook entry 14 |
| `doc-curator` | 1 | shipped | manual + monthly runbook entry 15 |
| `roadmap-advisor` | 1 | shipped | manual (ad-hoc when picking next slice) |
| `backup-verifier` | 1 | shipped | manual (after backup-worthy surface change or strategy bootstrap) |
| `pr-review-backend` | 1 | shipped | hook-nudged (pre-push) |
| `pr-review-frontend` | 1 | shipped | hook-nudged (pre-push) |
| `analytics-narrator` | 1 | shipped | manual (ad-hoc daily glance, writes `data/analytics/daily/`) |
| `ml-model-evaluator` | 2 | shipped | auto (weekly Mon 10:00 ET, runbook entry #1) |
| `predictor-promotion-advisor` | 2 | shipped | manual via `/promotion-decision` skill |
| `override-rate-tracker` | 2 | shipped | auto (weekly Sun 16:00 ET, runbook entry #7) |
| `fusion-lane-auditor` | 2 | shipped | auto (weekly Mon 11:00 ET, runbook entry #23) |
| `rule-engine-misfire-auditor` | 2 | shipped | auto (weekly Fri 08:00 ET, runbook entry #24) |
| `ml-feature-importance-watcher` | 2 | shipped | manual (on-demand, feature drift) |
| `test-coverage-prospector` | 2 | shipped | manual (on-demand, post-diff) |
| `dependency-hygiene` | 2 | shipped | manual (monthly, on-demand) |
| `performance-regression-hunter` | 2 | shipped | auto (weekly Tue 09:00 ET, runbook entry #25) |
| `refactor-proposer` | 2 | shipped | manual (quarterly, on-demand) |
| `error-pattern-watcher` | 2 | shipped | auto (weekly Thu 09:00 ET, runbook entry #26) |
| `frontend-a11y-auditor` | 2 | shipped | manual (on-demand, requires dev server at localhost:8000) |
| `dead-code-finder` | 2 | shipped | manual (quarterly) |
| `flag-triager` | 2 | shipped | manual (on-demand when flag queue is overgrown) |
| `ci-health-watcher` | 2 | shipped | auto (daily 08:30 ET, runbook entry #33) + manual / `/ci-health` |
| `gh-backlog-triager` | 2 | shipped | manual (on-demand when GH backlog is overgrown) |
| `gameday-preflight` | 3 | shipped | auto (preseason + weekly Sun NFL) + manual T-90 |
| `gameday-postmortem` | 3 | shipped | auto (loop pre-fire detector) + manual on test fires |

Tier-4 orchestration is implicit (main session plays lead). Tier-3 runtime specialists (music librarian, routine scheduler advisor) remain unshipped — see Part 1.

> **Note on the Tier column:** the value above is the *value × cadence* tier from Part 1, **not** the model the agent runs on. Model tiering is a separate axis — see "Model tiering" below.

---

## Model tiering (reviewed 2026-05-31)

The fleet was authored May 2026 pinned flat to `model: sonnet` (which resolves to the latest Sonnet — currently 4.6). With Opus 4.8 (1M ctx) and Haiku 4.5 now available, a flat fleet leaves value on the table both ways. Guiding principle:

- **Opus 4.8 — rare fire + high judgment + costly-to-miss.** These fire seldom (per-commit, per-push, on-demand), so the per-token premium barely moves aggregate cost, but a miss is expensive (a bad lighting commit, a missed backend footgun, a wrong root-cause). The 1M context also lets the code-reasoning agents hold oversize files (`automation_engine.py` ~2500 LOC) + logs at once.
- **Haiku 4.5 — frequent fire + mechanical.** "Query → compute → format a digest block" jobs with little judgment. These are where token spend accumulates (hourly/weekly auto-fires), so the cheaper/faster model is a real saving with no quality loss.
- **Sonnet 4.6 — everything in the middle** (structured analysis, moderate judgment). The default; only deviate with a reason.

Net effect is roughly cost-neutral-or-cheaper while quality rises on the decisions that matter.

| Model | Agents | Why |
|---|---|---|
| **opus** | `lighting-curator`, `pr-review-backend`, `homehub-investigator`, `refactor-proposer` | Aesthetic/spatial reasoning; footgun-aware push gate; root-cause diagnosis (also gets Sentry MCP — see below); module-boundary reasoning on oversize files. All rare-fire. |
| **haiku** | `override-rate-tracker`, `performance-regression-hunter`, `backup-verifier`, `homehub-verifier` | Rolling-rate arithmetic; threshold compare; checklist walk; hourly state snapshot. `homehub-verifier` is a **trial** — it's the highest-frequency agent (biggest saving) but does some anomaly judgment; fall back to Sonnet if anomaly recall drops. |
| **sonnet** | all other 22 | Default — structured analysis, moderate judgment. Includes the Opus-*optional* set (`doc-curator`, `roadmap-advisor`, `pr-review-frontend`, `gh-backlog-triager`) — bump to opus only if their output quality disappoints. `ci-health-watcher` is a straight Sonnet (scan→cluster→format). |

**Sentry MCP access (2026-05-31):** Sentry SDK has been live since `8bd4b82` (backend errors → `home-hub.sentry.io`), but no agent referenced `mcp__sentry__*`. Two error-facing agents now do: `homehub-investigator` (search_issues / search_issue_events / get_issue_tag_values / analyze_issue_with_seer / find_projects — prefers Sentry over best-effort `ssh homehub` journalctl, which its sandbox often can't reach) and `error-pattern-watcher` (uses Sentry's server-side fingerprint grouping as a pre-clustered source instead of re-deriving clusters from journalctl by hand).

**GitHub-surface coverage (2026-05-31):** the fleet pointed almost entirely *inward* (live apartment + ML + code); the GitHub surface (Actions CI + the issue backlog) was a blind spot — a ~2-day CI red streak (5/29–5/31) went completely unnoticed. Two agents closed it: `ci-health-watcher` (daily, watches Actions runs via `gh` CLI — the github MCP has no workflow-run tool) and `gh-backlog-triager` (on-demand grooming of the open issue backlog: label normalization, dedup, priority/size, stale detection — advisory, read-only). `roadmap-advisor` was also extended to read the live GH backlog as a fourth source (was docs + memory only). Boundary: `flag-triager` grooms the pre-filing local queue, `gh-backlog-triager` grooms the post-filing GH backlog, `roadmap-advisor` prioritizes across all surfaces.

**Fleet observability (2026-05-31):** the SubagentStop audit hook (`subagent_stop_audit.py`) was rebuilt — it had been logging `unknown/chars=0` on every row (it probed payload keys that don't exist). It now parses each subagent's own transcript (`agent_transcript_path`) for token usage + agent name and writes structured rows to `subagent_audit.jsonl`; the `/fleet-usage` skill (weekly via runbook entry #34) reports fire-counts + output-token spend per agent so model-tiering stays data-driven.

**Issue→PR pipeline (2026-05-31, narrow v1):** the `/implement-issue <N>` skill carries ONE small / low-risk / single-concern / well-specified issue to a PR — eligibility-gate → plan (human-approved) → feature branch → existing review+CI gates → open PR (never merges, never batches). Deliberately narrow per the Part 2/4 review-bottleneck lesson; refuses M/L / multi-concern / high-risk / under-specified issues and points to the worktree-fleet playbook instead. `gh-backlog-triager`'s S/M sizing surfaces candidates. Still deferred: a general/batch pipeline (saved `Workflow` orchestrator) — revisit once v1 is proven on real issues.

---

## Verification note

Some Claude Code patterns referenced in research (notably a `/batch` skill that supposedly spawns 5–30 worktree agents) are NOT available in this project's skill set. Historical project-specific Claude skills lived under `~/.claude/skills/`; references to current tools should be resolved through `AGENTS.md`. The Claude `/checkback-loop`, `/watcher-loop`, `/fleet-usage`, `/digest-today`, `/promotion-decision`, and `/lsp-verify` flows are historical unless explicitly re-enabled or ported.

Historical multi-agent path on this machine: **git worktrees + manual coordination**, OR the **experimental Agent Teams** behind `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (enabled in `~/.claude/settings.json`). Treat any reference elsewhere to a `/batch` skill as aspirational, not actionable.

---

## Part 1 — Agent ideas, ranked by value × effort

### Tier 1 — Ship soon (high value, low complexity)

**Lighting curator.** **Shipped 2026-05-06. ✓** Review subagent that knows the apartment palette + the rules in `feedback_lighting_design_principles.md` (kitchen pair, post-sunset CT≥333 mirek, IES 1:3 contrast, HSB-vs-CT exclusivity, effects flatten per-light HSB). When you (or the main session) propose changes to `light_state_calculator.py` or curated scenes in `routes/scenes.py`, this agent reviews the diff against the rules before commit. Catches lighting-design rule violations the main session occasionally misses. Verified end-to-end: smoke test on `f1fac03` reported STATUS: ok with bonus structural insight; negative test against 3 contrived violations caught all 3 + 1 emergent finding (unreachable `wee_hours` period key). PreToolUse nudge hook live. **Effort:** small — one agent definition + a memory citation list.

**Lighting shopper.** **Shipped 2026-05-07. ✓** Read-only product-research agent for the Hue/Zigbee buildout. Researches current-gen Hue + Friends-of-Hue + Zigbee 3.0 + Matter-bridged products via `WebSearch`/`WebFetch`, evaluates each against the documented palette (`project_apartment_layout.md`) + fixture inventory (`docs/LIGHTING_EXPANSION.md`) + design rules (`feedback_lighting_design_principles.md`). Returns a structured fit report with citations. Manual spawn for shopping trips, wishlist refreshes, or evaluating an unfamiliar product. **Effort:** small.

**Memory hygiene auditor.** Quarterly read-only scan of `~/.claude/projects/.../memory/`. Flags: memories citing dates >60d old without recent verification, conflicting pairs (two memories taking opposite positions), orphan memories no longer referenced. Outputs a cleanup queue. Memory currently has 60+ entries and drift is real. **Status:** Deferred per Part 5 §6 — quarterly cadence is too slow; the Aug 1 remote agent already runs a broad memory pass. **Effort if revisited:** small — one agent + a runbook entry firing every 90 days.

**Doc drift checker.** **Shipped 2026-05-07. ✓** Walks a fixed set of authoritative-source-vs-doc comparisons: env vars in `config.py` vs CLAUDE.md `.env` block, route prefixes vs API Routes table, `app_settings` keys vs the SQLite Persisted Settings table, subagent fleet vs `~/.claude/agents/` filesystem, hook list vs `.claude/settings.json`, network device IPs vs `.env`, Tier shipped-status markers in this doc vs filesystem. Read-only — produces a drift report; caller decides which way to resolve (code is authoritative). The Aug 1 remote agent runs a similar audit quarterly; this agent is the on-demand variant. **Effort:** small-to-medium.

**Doc curator.** **Shipped 2026-05-07. ✓** Read-only auditor for the long-form spec docs (`PROJECT_SPEC`, `ML_SPEC`, `GAMEDAY_SPEC`, `CONFIDENCE_FUSION`, `GUEST_APP_BRAINSTORM`, `LIGHTING_EXPANSION`). Walks each doc against three sources of truth — current code, dated memory entries, and git history — and emits Edit-tool-ready `old_string`/`new_string` proposals for the caller to apply selectively. Special path for `LIGHTING_EXPANSION` reads lighting-curator's reference materials before reasoning. Complement to `doc-drift-checker` (which covers structural surfaces in CLAUDE.md / AGENT_STRATEGY tables). **Effort:** small-to-medium.

**Backup verifier.** **Shipped 2026-05-08. ✓** Read-only verifier that the home-hub system's irreplaceable state (Latitude SQLite + `.env` + `data/journal`; `~/.claude` memory + agents + runbooks; lighting-curator photo references; AWS Lambda deployed code) has fresh, complete offsite backups. Walks the documented strategy at `~/.claude/runbooks/backup-strategy.md` (created 2026-05-30; the PLANNED rows in its inventory are the known backlog) against actual offsite state and reports gaps. Read-only; never triggers backups. **Effort:** small.

**Roadmap advisor.** **Shipped 2026-05-08. ✓** Cross-doc backlog synthesizer. Reads all 9 docs in `docs/` (each with its own backlog convention — Future_Development's Priority Bands, AUDIT's "Open follow-ups" with deadlines, ML_SPEC's Phase gates, GAMEDAY_SPEC's v1/v2, GUEST_APP_BRAINSTORM's Tiers, AGENT_STRATEGY's Tier 1/2/3/4) plus tactical memory entries; filters out shipped items via Future_Development's "Completed" section + memory shipped markers + recent git log; emits a categorized menu (Security · Backend · Frontend · ML · Lighting · Ops · Voice · Game Day · Docs/Tooling) of 1-2 actionable items per category. Default balanced; optional direction hint ("focus on frontend, 2-hour block") biases output. Complements `doc-curator` (accuracy) and `doc-drift-checker` (sync) by surfacing prioritization. Read-only — never edits. **Effort:** small.

**PR review (backend + frontend).** **Shipped 2026-05-07. ✓** Two read-only specialist reviewers: `pr-review-backend` covers Python diffs against the global + project CLAUDE.md rules and the canonical memory footguns (current_mode field, camera-at-desk veto, manual-override preservation, refractory burn pattern, colorspace exclusivity); `pr-review-frontend` covers SvelteKit diffs against glass-card / Bebas Neue / Lucide / WS-into-stores / kitchen-pair-fusion conventions plus the build-warning hygiene list. On clean review each writes a marker file at `<git-dir>/.pr-review-{backend,frontend}-ok` containing the HEAD SHA. A pre-push hook (`pre_push_pr_review.py`) gates `git push` on the markers when the diff includes the relevant file types. Bypass: `SKIP_PR_REVIEW=1`. **Effort:** small — two agent files + one hook + settings.json wiring.

### Tier 2 — Ship when relevant (medium value, medium complexity)

**Test coverage prospector.** **Shipped 2026-05-11. ✓** For newly-changed code paths, suggests tests OR scaffolds them (using existing patterns from `tests/test_api_*.py`). Most useful on async/IO-heavy backend services where TDD is awkward. On-demand spawn.

**Performance regression hunter.** **Shipped 2026-05-11. ✓** Weekly Tue 09:00 ET (runbook entry #25). Benchmarks `/health`, `/api/automation/status`, `/api/lights`, `/api/learning/predictor`, + WS RTT. Trends stored in `~/.claude/data/perf_trends.jsonl`. Flags p95 regressions over configured thresholds.

**ML model evaluator.** **Shipped 2026-05-07. ✓** Owns offline accuracy evaluation on `ml_decisions` shadow rows across all 5 lanes (predictor, audio classifier, lighting learner, music bandit, camera lux). Surfaces drift, suggests retrain cadence, replaces the per-lane runbook check-backs (predictor validation, audio classifier checkpoints) with one consolidated weekly digest. Wired to runbook entry #1 — first scheduled fire 2026-05-11 10:00 ET. Read-only; findings advisory.

**Frontend a11y auditor.** **Shipped 2026-05-11. ✓** Playwright + axe-core (CDN inject) on 6 SvelteKit routes. Requires local dev server at localhost:8000. On-demand spawn.

**Refactor proposer.** **Shipped 2026-05-11. ✓** Quarterly / on-demand. Analyzes git log + LOC + concerns. `automation_engine.py` (2500+ lines) is the obvious first target.

**Error pattern watcher.** **Shipped 2026-05-11. ✓** Weekly Thu 09:00 ET (runbook entry #26). Clusters across `tool_failures.jsonl` + `subagent_audit.jsonl` + digest dir + journalctl + Sentry by fingerprint.

**Dead code finder.** **Shipped 2026-05-11. ✓** Quarterly. Pyright unused-symbol + grep cross-check. False-positive filter for route handlers, MCP tools, mode-change callbacks, ScheduledTask handlers, `__all__` exports.

**CI health watcher.** **Shipped 2026-05-31. ✓** Daily 08:30 ET (runbook entry #33). Watches GitHub Actions runs via the `gh` CLI (the github MCP has no run-list tool), clusters failures by job+step, computes the `master` consecutive-failure streak, and audits action versions. **Self-diagnoses** so the watcher loop never spawns the apartment `homehub-investigator` on a CI block. Read-only. Sister skill `/ci-health` for synchronous on-demand checks.

**GitHub backlog triager.** **Shipped 2026-05-31. ✓** On-demand. Grooms the *open* issue backlog at `agatte/home-hub` — label-taxonomy normalization, dedup/overlap clusters, priority + size inference, stale + already-shipped detection. Advisory; never mutates issues. Complements `flag-triager` (pre-filing local queue) and `roadmap-advisor` (which now also reads the live GH backlog for prioritization).

### Tier 3 — Future / aspirational

**Game Day specialist.** Owns ESPN polling, celebration cooldowns, play→light-color map, pre-game routines. Spawned only during football season. (Note: this is the *runtime* specialist, not the Game-Day-implementation fleet — those are different. See Part 3.)

**Music librarian.** Owns mode→playlist mapping refresh, vibe tag updates, taste profile rebuild on new XML imports.

**Routine scheduler advisor.** Analyzes past mode-transition + Sonos data; proposes schedule tweaks ("Fridays you hit relax 2h earlier — should winddown move?").

### Tier 4 — Meta / orchestration

**Lead engineer (for big features).** When something like Game Day kicks off, an agent that owns architecture, splits work into worker tasks, dispatches them, integrates results. **This is what enables the workflow described in Part 3.** Today the main session implicitly plays this role; specializing it surfaces "is the architecture sound?" as a separate concern from "did the worker do the work?"

**Capability watcher.** Monitors Anthropic API changelog + Hue/Sonos firmware notes for capabilities home-hub could exploit. Quarterly run.

---

## Part 2 — What multi-agent coding research actually says

### Well-supported findings (cite-able)

- **Tokens:** multi-agent burns **~7–15× the tokens** of a single-agent serial workflow. Anthropic's published number is ~15× for their Research feature. Subagent-heavy Claude Code workflows clock ~7×.
- **Worktrees scale to ~4 concurrent before review becomes the bottleneck** — every review feels like a new coworker because there's no continuity of trust.
- **Two agents editing the same file is universally an antipattern.** Anthropic, Claude Code docs, and external practitioners all sidestep merge conflicts via task decomposition (file-disjoint slices), not via conflict-resolution agents.
- **Anthropic explicitly warns:** "Most coding tasks involve fewer truly parallelizable subtasks than research." Research benefits from agent-fan-out far more than coding does.
- **Agent Teams (experimental, env-flag-gated)** support a shared task list + inter-agent messaging, but it's noted as buggy: no `/resume`, completion-marker lag, permissions can't be tightened post-spawn.

### Anecdotal but consistent

- Plan → implement → review pipelines are documented in blogs but no rigorous case studies. People do it; nobody's published numbers.
- The "scout" pattern (throwaway agent fails on purpose, its trace becomes the map for the real run) is HN-only — interesting but not battle-tested.
- ~40% of multi-agent production pilots fail within 6 months in production (single source — directional, not authoritative).

### Where this lands for a single-developer hobby project

Multi-agent coding is **worth the token spend for genuinely independent slices** (3+ truly disjoint modules in flight) and **net negative for sequential-dependent work** (ML pipeline that goes fetch → train → eval where each step needs the previous). Solo-scale also means review is your hardest constraint — 4 PRs landing at once is more than you can absorb. Stagger.

---

## Part 3 — Concrete Game Day workflow

Game Day is the canonical multi-agent target: ~5-week feature, ESPN polling + light orchestration + new SvelteKit page + Threlte 3D pixel field. These are mostly independent IF the interfaces are defined first.

### Phase A — Pre-work (just user + main session, sequential)

1. **Spec session.** Define the user-facing feature: kickoff, touchdown, field-goal, commercial, pre-game, end-of-game behaviors. Decisions, not pseudo-code.
2. **Interface contracts.** Define module boundaries with explicit inputs/outputs:
   - `GameDayService` — owns ESPN polling, exposes a single `app.state.gameday.current_state()` snapshot + `register_on_play_event(callback)` subscription. Other modules subscribe; they do NOT poll ESPN themselves.
   - `CelebrationOrchestrator` — subscribes to play events, owns light + TTS sequencing, has its own cooldown.
   - `/api/gameday/*` routes — read-only state queries.
   - SvelteKit `routes/gameday/+page.svelte` — subscribes via WebSocket, renders.
   - `Threlte FootballField.svelte` — pure component, accepts `{game, plays}` props.
3. **Mockup.** Static SvelteKit page with hardcoded data; no backend. Confirms visual language. Threlte field is a stub at this point.
4. **Refactor seam pass.** Anywhere existing code would conflict with the new modules, refactor first to make seams clean. Probably touches `bootstrap.py`, `main.py`, possibly `automation_engine.py` for mode-change interaction.

This phase is **not parallelizable** and is what determines whether Phase B succeeds.

### Phase B — Parallel implementation (4 worktree-isolated agents, staggered)

After Phase A, the four slices are mostly file-disjoint:

| Agent | Worktree | Owns | Files (no overlap) |
|---|---|---|---|
| **A** | `feature/gameday-service` | ESPN poller + game-state model + `/api/gameday/*` | `backend/services/gameday_service.py`, `backend/api/routes/gameday.py`, `tests/test_gameday_service.py` |
| **B** | `feature/celebration-orchestrator` | Light + TTS choreography subscribed to game events | `backend/services/celebration_orchestrator.py`, `tests/test_celebration_orchestrator.py` |
| **C** | `feature/gameday-frontend` | SvelteKit page + stores + WS subscription | `frontend-svelte/src/routes/gameday/+page.svelte`, `frontend-svelte/src/lib/stores/gameday.js` |
| **D** | `feature/threlte-football-field` | Threlte 3D field component | `frontend-svelte/src/lib/components/FootballField.svelte` and supporting helpers |

Stagger by 24-48h: spawn A first, then B once A's `register_on_play_event` interface is concrete, then C and D in parallel against the SvelteKit/Threlte boundary defined in Phase A. Each agent opens a PR; main session reviews and cherry-picks into main as they land. Run Codex `$homehub-diagnose` for targeted API/runtime verification after the merges, then `$deploy-home` when frontend + backend are both in.

### Phase C — Integration + smoke (main session)

Main session is the integrator. Run the full system end-to-end. Codex `$deploy-home` performs deploy-verifier-style structural checks. The old watcher loop is retired; use `$homehub-diagnose` for targeted post-deploy anomalies.

### Token cost reality check

Phase B at 4 worktree agents × ~2-3 days each ≈ **~12-15× tokens** vs. main-session-serial. That's real money. The trade is: ~4× wall-clock speed-up (assuming staggered review doesn't bottleneck) and a bunch of mostly-independent code authored in parallel. **Worth it for a 5-week feature; not worth it for a 2-day fix.**

---

## Where this could fail

1. **Phase A is rushed.** If interface contracts are vague, agents make incompatible assumptions and Phase C becomes "rewrite the integration glue", erasing the parallelism gain.
2. **Review bottleneck.** If 4 PRs land same-day, main session can't absorb them. Stagger or pre-bake review checklists.
3. **A new file you didn't anticipate.** E.g., agent B needs to edit `automation_engine.py` to register its callback at lifespan startup. Two agents touching one file = merge conflict. Phase A should explicitly designate which agent owns those shared touchpoints (typically the lead, i.e. main session).

---

## Part 4 — Phase B fleet experiment retrospective (2026-05-07)

The fleet ran end-to-end. Game Day Phase B Slices B + C + D were spawned in 3 parallel worktree-isolated `general-purpose` agents. Slice A had been done solo-serial earlier (correctly — A was the unblocking interface; parallelism gains nothing on sequentially-required work). Master session coordinated: pre-allocated file ownership (no overlap), wrote self-contained briefs per slice, spawned all three in a single message, waited for all three to return, ran lighting-curator on Slice B's diff, merged in dependency order, did the integration commits.

### What worked

- **File-disjoint plan held perfectly.** Zero merge conflicts across 4 branches (B/C/D + integration). The interface-pinning that Phase A spec §4 enforced was the load-bearing piece — none of the agents had to invent contracts.
- **Curator caught a real anti-pattern.** Slice B agent set `_COLTS_BLUE_SAT = 254` for the celebration pulse helper. Lighting-curator subagent flagged this as the same room-overload pattern the gaming retune (sat 240→180) addressed; we dropped it to 215 before merge. A static linter wouldn't have caught this — the curator reasoned about the apartment's textile palette and the time-window of all-lights-saturated-blue.
- **Agent continuity via SendMessage paid off** for the follow-up dynamic-volume work. The Slice B agent was resumed (not re-spawned) — retained context on the orchestrator's design (kitchen-pair invariant test, `_SafeFormatDict` template substitution, cooldown stamping, SEQUENCES dict structure), synced its worktree to current master, and shipped 199 tests + ruff-clean code in a single session.
- **Live verification end-to-end worked first try.** Synthetic touchdown fired through GameDayService → CelebrationOrchestrator → HueService + TTSService + WebSocketManager, all observed in journalctl with correct ordering. The historical deploy-verifier subagent caught no regressions after `/deploy-home`. Current Codex `$deploy-home` performs equivalent checklist verification inline.

### Token cost reality check (actual vs. predicted)

The strategy doc's Part 2 predicted "Phase B at 4 worktree agents × ~2-3 days each ≈ ~12-15× tokens." Actuals:

- 3 parallel Slice agents (B + C + D): ~385k tokens combined (~120-135k each).
- Lighting-curator review on Slice B: ~73k tokens.
- Slice B agent resumption for dynamic-volume work: ~236k tokens.
- Wall-clock: ~9 minutes for the parallel fleet (longest slice = D at 9.3min).

Roughly the predicted ~9-15× ratio vs. solo-serial main-session work. The token spend is real and worth being honest about — full fleet only pays off when you genuinely have 3+ disjoint slices ready to ship. Solo-serial is right for sequential work and small slices.

### What failed (or would have)

- The strategy doc predicted "review bottleneck if 4 PRs land same-day." We didn't hit this in practice because all three fleet agents finished within a 9-minute window and main session reviewed serially in the next ~30 minutes — but the integration commits + curator review easily would have stretched to a full hour if the slices had been more complex. For a longer feature, staggering would matter more.
- The pre-flight prep (Phase A spec + e6766c3 seam pass) was the load-bearing investment. A vague spec would have meant agents inventing contracts and diverging. The spec session was ~2 hours of main-session work; that's where the parallelism gain was earned.

### Updated thesis

Tier 1 specialists pay off (curator, deploy-verifier). The fleet pattern pays off for week-scale features WITH pre-pinned interfaces. Default recommendation pattern (memorialized in `feedback_recommend_agents_proactively.md`):
- Large tasks (3+ disjoint slices, week-scale): worktree fleet, file-ownership table, brief per slice, main-session orchestrates.
- Smaller precision tasks: spawn the relevant specialist subagent at planning time. Don't drift back to solo-serial.
- Follow-up work on a feature an agent already built: SendMessage to that agent (continuity) rather than spawn fresh.

---

## Part 5 — Fleet usage playbook (when each agent fires, 2026-05-11)

The fleet is 30 agents. Most fire automatically — the manual spawns left are deliberate one-shot specialist calls (a focused `homehub-verifier` recipe, a manual `gameday-postmortem` on a test fire, a `lighting-curator` review before a non-token commit, a `lighting-shopper` for product research, `doc-drift-checker` / `doc-curator` / `roadmap-advisor` for ad-hoc audits and planning, `backup-verifier` after irreplaceable-state changes, the PR reviewers when the pre-push hook denies, on-demand ML and dev-velocity agents, and `flag-triager` when the flag queue is overgrown).

### Trigger map

| Agent | Trigger | Cadence | Output sink |
|---|---|---|---|
| `homehub-verifier` | historical `/checkback-loop` dispatches | disabled 2026-07-13 | old digest blocks in `~/.claude/runbooks/digests/YYYY-MM-DD.md`; latest useful output stopped 2026-06-13 |
| `homehub-investigator` | historical `/watcher-loop` polls digests | disabled 2026-07-13 | checklist only unless Claude tasks are re-enabled |
| `homehub-remediator` | historical `/watcher-loop` post-diagnosis handoff | disabled 2026-07-13 | no active Codex remediation path; use read-only diagnosis and human-approved fixes |
| `ml-model-evaluator` | runbook entry #1 | weekly Mon 10:00 ET | digest block (agent writes its own) |
| `override-rate-tracker` | runbook entry #7 | weekly Sun 16:00 ET | digest block (agent writes its own) |
| `fusion-lane-auditor` | runbook entry #23 | weekly Mon 11:00 ET | digest block (agent writes its own) |
| `rule-engine-misfire-auditor` | runbook entry #24 | weekly Fri 08:00 ET | digest block (agent writes its own) |
| `performance-regression-hunter` | runbook entry #25 | weekly Tue 09:00 ET | digest block; trends to `~/.claude/data/perf_trends.jsonl` |
| `error-pattern-watcher` | runbook entry #26 | weekly Thu 09:00 ET | digest block (agent writes its own) |
| `ci-health-watcher` | historical runbook entry #33 | disabled 2026-07-13 | use ordinary GitHub Actions inspection on demand |
| `deploy-verifier` | historical `/deploy-home` step 7 | disabled 2026-07-13 | Codex `$deploy-home` performs equivalent checklist verification inline |
| `lighting-curator` | PreToolUse hook on `git commit` | per-commit when staged diff matches lighting files + design identifiers | blocks commit unless `[curator-reviewed]` token in message |
| `gameday-preflight` | runbook entry #12 (preseason T-7) + entry #13 (weekly Sun Aug-Jan) + manual T-90 game morning | once preseason + every Sunday in NFL season + ad-hoc | digest block (agent writes its own) |
| `gameday-postmortem` | loop pre-fire detector on `gameday:auto` close (per `homehub-checkbacks.md` § Pre-fire detectors) + manual for test fires | within ~1h of every real game close (auto), ad-hoc otherwise | appends to today's digest |
| `pr-review-backend` | manual spawn before push (often via the deny message from the pre-push hook) | per-push when diff contains Python under `backend/`, `tests/`, `scripts/` | inline conversation report + writes `<git-dir>/.pr-review-backend-ok` containing HEAD SHA on PASS |
| `pr-review-frontend` | manual spawn before push | per-push when diff contains SvelteKit changes under `frontend-svelte/` | inline report + writes `<git-dir>/.pr-review-frontend-ok` containing HEAD SHA on PASS |
| `predictor-promotion-advisor` | manual via `/promotion-decision` skill | on-demand (when override-rate gate passes) | inline PROMOTE/WAIT/DEMOTE verdict |
| `ml-feature-importance-watcher` | manual | on-demand (feature drift detection) | inline trend report |
| `test-coverage-prospector` | manual | on-demand (post-diff) | inline proposed test scaffolds |
| `dependency-hygiene` | manual | monthly, on-demand | inline CVE + version audit report |
| `refactor-proposer` | manual | quarterly, on-demand | inline refactor proposals (first target: `automation_engine.py`) |
| `frontend-a11y-auditor` | manual | on-demand (requires dev server at localhost:8000) | inline axe-core findings per route |
| `dead-code-finder` | manual | quarterly | inline unused-symbol report |
| `flag-triager` | manual | on-demand when flag queue is overgrown | inline label normalization + dedup + priority report (pre-filing local queue) |
| `gh-backlog-triager` | manual | on-demand when GH backlog is overgrown | inline canonical-label proposal + dedup + priority/size + stale report (post-filing GH backlog) — advisory, never mutates issues |
| `analytics-narrator` | manual | ad-hoc daily glance | writes `data/analytics/daily/YYYY-MM-DD.md`; default target is yesterday |
| `doc-drift-checker` | manual spawn (recommended after shipping a new agent / route / env var / app_setting key) | monthly first-Mon runbook entry 14 + ad-hoc | inline drift report — never mutates docs |
| `doc-curator` | manual spawn (recommended monthly third-Mon per runbook entry 15, or after a large feature ships) | monthly + ad-hoc | inline structured Edit-ready proposals — never mutates docs |
| `roadmap-advisor` | manual spawn (when planning the week, picking the next slice, "what should I work on today" moments) | ad-hoc | inline categorized backlog menu — 1-2 items per category, optional direction hint |
| `backup-verifier` | manual spawn (after a deploy that changed irreplaceable state, when adding a new backup-worthy surface, or for periodic offsite verification) | ad-hoc | inline gap report against `~/.claude/runbooks/backup-strategy.md` (created 2026-05-30) — never mutates state |
| `lighting-shopper` | manual spawn (shopping trips, LIGHTING_EXPANSION wishlist refresh, evaluating unfamiliar products) | ad-hoc | inline product-fit report with citations — never edits docs |

### Game Day vertical-slice timeline

```
T-7d   Sunday weekly preflight (entry #13) — apparatus check, no synthetic fire on bye weeks
T-90   Game-morning preflight — manual spawn for hard-go/no-go (synthetic kickoff fires)
T-30   AutomationEngine flips to gameday source="gameday:auto"  — no agent
in     CelebrationOrchestrator drives lights+TTS on play events  — no agent
T+30   AutomationEngine clears override source="gameday:auto"   — postmortem detector arms
T+30…+90  Loop's next tick runs the detector SQL, spawns gameday-postmortem
T+30…+120 Watcher loop notices the postmortem block; if STATUS: warn, spawns homehub-investigator
next day Curator review on any subsequent SEQUENCES tweak (advisory section K) before commit
```

### Hooks reference (all 8 hooks, project-scoped at `home-hub/.claude/hooks/`, wired in `.claude/settings.json`)

| Hook file | Event | Matcher | What it does |
|---|---|---|---|
| `session_start_homehub.py` | SessionStart | — | Injects mode/source/override + anomaly-only fields via `additionalContext`. Extended (Round 3): also injects `flags_pending=<n>` + `oldest=<n>d` when queue has ≥3 pending or oldest >7 days. Healthy systems stay terse. |
| `pre_commit_lighting_curator.py` | PreToolUse | Bash | Blocks `git commit` touching lighting files + design identifiers unless message contains `[curator-reviewed]`. See Pre-commit gate below. |
| `pre_push_pr_review.py` | PreToolUse | Bash | Blocks `git push` of Python/SvelteKit diffs unless PASS markers exist. See Pre-push gate below. |
| `post_edit_ruff.py` | PostToolUse | Edit\|Write | Runs `python -m ruff check --fix` on edited `backend/**/*.py`. No frontend lint hook. |
| `post_edit_env_validate.py` | PostToolUse | Edit\|Write | Filters to `.env*` files. Validates required keys (APP_ENV, LOCAL_IP, HUE_BRIDGE_IP, HUE_USERNAME, TIMEZONE), empty values, FRONTEND_BUILD path existence, smart-quote substitution. Prints `[env]` inline. |
| `post_git_push.py` | PostToolUse | Bash | Historical Claude hook: after a real `git push`, nudged `/deploy-home`. Codex uses `$deploy-home` directly. |
| `post_tool_failure.py` | PostToolUse | — (all tools) | Logs tool call failures to `~/.claude/data/tool_failures.jsonl`. 10s dedup window. Idempotent. |
| `subagent_stop_audit.py` | SubagentStop | — | Logs every subagent completion to `~/.claude/data/subagent_audit.jsonl` (structured row: agent + token usage parsed from the subagent's own transcript). Read by `error-pattern-watcher` + `/fleet-usage`. (Rebuilt 2026-05-31 — the old `.log` logged `unknown/chars=0` on every row.) |

### Pre-commit gate (lighting changes)

The PreToolUse hook on `git commit` (`.claude/hooks/pre_commit_lighting_curator.py`) blocks commits that touch one of the watched files (`light_state_calculator.py`, `routes/scenes.py`, `celebration_orchestrator.py`) AND contain a design identifier (`ACTIVITY_LIGHT_STATES`, `EFFECT_AUTO_MAP`, `SCENE_PRESETS`, `BED_RECLINED`, `BED_ZONE_ONLY`, `LUX_CURVE`, `SEQUENCES`).

Override path: spawn `lighting-curator`, address findings, then re-run `git commit -m "...[curator-reviewed]"`. The token is the deliberate sentinel — case-insensitive substring match against the bash command. Pure comment/whitespace edits skip the gate (the identifier filter rejects them).

### Pre-push gate (PR review)

The PreToolUse hook on `git push` (`.claude/hooks/pre_push_pr_review.py`) blocks pushes when the diff (`origin/master...HEAD` or upstream tracking branch if set) includes backend Python (`backend/`, `tests/`, `scripts/` `*.py`) or SvelteKit (`frontend-svelte/` `*.{svelte,ts,js,css,html}`) changes UNLESS a fresh PASS marker exists at `<git-dir>/.pr-review-{backend,frontend}-ok` recording the current `HEAD` SHA.

Override paths: (1) spawn `pr-review-backend` and/or `pr-review-frontend`, address findings if any are `block`, let the agent write the marker, push again. (2) Set `SKIP_PR_REVIEW=1` for hot-fix pushes you've decided to ship without review. Doc-only / config-only pushes (`docs/**/*.md`, `.claude/**/*.md`, top-level `*.md`, `.gitignore`) skip the gate entirely. The marker is per-worktree (`git rev-parse --git-dir` resolves the worktree's own git dir), so reviews don't leak across worktrees.

### Off-season behavior

The runbook's queue runs year-round. NFL-season-specific entries (#13 weekly Sunday preflight) are skipped Feb-July with a one-line `[skipped — off-season]` digest entry. The postmortem auto-fire detector also runs year-round but is effectively a no-op outside the season because no `gameday:auto` flips happen.

### Manual spawns that remain

- Focused `homehub-verifier` recipes for one-off health checks (e.g., "audit override-rate trends manually for this week" outside the regular Sunday cadence)
- `gameday-postmortem` on test fires (a `POST /api/gameday/test/touchdown` smoke test won't trigger the auto-fire because it carries `source=manual`, not `source=gameday:auto`)
- `lighting-curator` deliberately on a diff before staging (when you want a review before deciding whether to commit at all)
- Any specialist that doesn't have a runbook entry — most of the Tier 1/Tier 2 candidates from Part 1 still lack scheduled wiring

---

## Part 6 — Full tooling layer reference (2026-05-11)

### MCP servers (project `.mcp.json`)

Five MCP servers load when Claude Code opens this project. All five must be approved on first session start.

| Name | Command | Purpose |
|---|---|---|
| `home-hub` | `python -m backend.mcp_server` | Custom REST-API wrapper — the primary tool surface for live-system queries. Tools: `get_live_state`, `get_state_history`, `get_health`, `get_lights`, `set_light`, `get_weather`, `get_automation_status`, `set_mode`, `get_schedule`, `get_mode_brightness`, `get_scenes`, `activate_scene`, `get_effects`, `activate_effect`, `get_sonos_status`, `sonos_play`, `sonos_pause`, `sonos_volume`, `get_sonos_favorites`, `get_mode_playlists`, `get_routines`, `get_pihole_stats`, `query_db`. Requires backend running at `HOME_HUB_URL`. |
| `sqlite-home-hub` | `python -c "from mcp_server_sqlite import main; main()" --db-path data/home_hub.db` | Direct SQLite access (PyPI `mcp-server-sqlite`, Anthropic-maintained). Fallback when backend is down. |
| `sentry` | `npx -y @sentry/mcp-server@latest` | Sentry issue/event browser (home-hub.sentry.io org). Requires one-time `npx @sentry/mcp-server@latest auth login` in a terminal before first load; token caches at `~/.sentry/`. SDK already wired in `backend/main.py` (commit `8bd4b82`). Free tier: 10k events/month, traces off. |
| `git-home-hub` | `python -m mcp_server_git --repository .` | Read-only git ops on the repository (PyPI `mcp-server-git` v2026.1.14). |
| `time` | `python -m mcp_server_time --local-timezone America/Indiana/Indianapolis` | Current time + timezone conversions, timezone-aware (PyPI `mcp-server-time` v2026.1.26). |

User-global MCPs available in all projects (claude.ai integrations, not in `.mcp.json`): GitHub MCP, Playwright MCP, Notion MCP, Gmail/Calendar/Drive.

### LSP servers (`~/.claude/settings.json` `enabledPlugins`)

Two LSP plugins are enabled in the global settings. Both required a one-time `marketplace.json` patch (see `project_lsp_marketplace_patch_2026_05_11.md`) because Windows `uv_spawn` cannot execute `.cmd` shims (Node 22 BatBadBut) or find pip-installed `.exe` files that aren't on PATH.

| Plugin | Binary | Notes |
|---|---|---|
| `pyright-lsp@claude-plugins-official` | `pyright-langserver --stdio` | Python type-checking (v1.1.409). `pyrightconfig.json` at repo root: `typeCheckingMode: standard`, excludes `venv/` + `frontend-svelte/`. Prereq: `pip install pyright`. |
| `typescript-lsp@claude-plugins-official` | `typescript-language-server --stdio` | TS/JS type-checking. Prereq: `npm install -g typescript-language-server typescript`. |

**Maintenance note:** Both patches live in `~/.claude/plugins/marketplaces/claude-plugins-official/.claude-plugin/marketplace.json`, which Anthropic auto-updates under `"autoUpdatesChannel": "latest"`. Drift is detected + auto-reapplied by an idempotent Python script at `~/.claude/scripts/reapply_lsp_patches.py`, invoked either on-demand via `/lsp-verify` or automatically by runbook entry 27 (monthly second-Mon 11:00 ET). Script exit codes: 0=patches in place, 1=reapplied successfully, 2=unrecoverable error.

### Plugins (`~/.claude/settings.json` `enabledPlugins`)

| Plugin | Source | Purpose |
|---|---|---|
| `playwright@claude-plugins-official` | official marketplace | Browser automation (used by `frontend-a11y-auditor`) |
| `frontend-design@claude-plugins-official` | official marketplace | Frontend design tooling |
| `ui-ux-pro-max@ui-ux-pro-max-skill` | custom marketplace (`nextlevelbuilder/ui-ux-pro-max-skill`, auto-update on) | UI/UX review |
| `pyright-lsp@claude-plugins-official` | official marketplace | Python LSP (see above) |
| `typescript-lsp@claude-plugins-official` | official marketplace | TypeScript LSP (see above) |

### Data files (`~/.claude/data/`, cross-project)

| File | Created by | Contents |
|---|---|---|
| `tool_failures.jsonl` | `post_tool_failure.py` hook (PostToolUse all-tools) | Failed tool calls with 10s dedup. Consumed by `error-pattern-watcher`. |
| `subagent_audit.jsonl` | `subagent_stop_audit.py` hook (SubagentStop) | One structured row per subagent completion: `{ts, agent, agent_id, status, turns, output_chars, input/output/cache/total tokens, payload_keys}`. Tokens + agent name parsed from the subagent's own transcript (`agent_transcript_path`). Consumed by `error-pattern-watcher` (real `output_chars==0` signal) + the `/fleet-usage` reporter. **Rebuilt 2026-05-31** — the old `subagent_audit.log` logged `unknown/chars=0` on every row (field-name bug); that file is dead, ignore it. |
| `subagent_last_payload.json` | `subagent_stop_audit.py` hook | The most recent raw SubagentStop payload, overwritten each fire. Self-documenting guard against schema drift — if `/fleet-usage` shows no-parse rows, diff this against the expected keys. |
| `perf_trends.jsonl` | `performance-regression-hunter` agent | Route + WS benchmark results accumulated over time. Enables week-over-week trend comparison. |
| `flags.jsonl` | `/flag` skill | Append-only capture queue for follow-up items. Row shape: `{id, title, body, labels, repo, source, status, ts, gh_issue_url}`. Drained via `/flag-sync`; browsed via `/flag-list`. |

### Flag-capture workflow

The flag workflow (Round 3, 2026-05-11) solves topic-drift loss: when Claude surfaces an unrelated issue mid-task, it proactively offers to capture it via `/flag`. User confirms → row appended to `~/.claude/data/flags.jsonl` with `status=pending`. Batch-file to GitHub (`agatte/home-hub`) later via `/flag-sync` (interactive per-flag: file / dismiss / skip / quit). Browse queue via `/flag-list`. The `flag-triager` agent handles overgrown queues with label normalization + dedup (Jaccard ≥ 0.5 pairing).

The `session_start_homehub.py` hook injects `flags_pending=<n>` (and `oldest=<n>d`) into `additionalContext` when the queue has ≥3 pending or something has been sitting >7 days, so the next session opens with a terse reminder.

Drain reminders fire at four mid-session moments: after capturing another flag when total pending ≥ 3; when the user mentions a domain with pending flags in that label; at natural session-end signals ("done for today", "ship it") with pending count > 0; after `git push` / `$deploy-home` sequences with pending ≥ 5.

### Runbook cadence map

Entries in `~/.claude/runbooks/homehub-checkbacks.md` that dispatch specialist agents (vs. inline `homehub-verifier` recipes):

| Entry | Cadence | Agent dispatched |
|---|---|---|
| #0 (hourly anomaly sweep) | every ~60 min | `homehub-verifier` (inline recipe) |
| #1 (ML model evaluator) | weekly Mon 10:00 ET | `ml-model-evaluator` |
| #7 (override-rate trend) | weekly Sun 16:00 ET | `override-rate-tracker` |
| #12 (preseason readiness) | once, 2026-08-06 | `gameday-preflight` |
| #30 (regular-season Week 1 readiness) | once, 2026-09-11 | `gameday-preflight` |
| #13 (weekly game-day preflight) | weekly Sun 09:00 ET (Aug-Jan) | `gameday-preflight` |
| #14 (doc drift audit) | monthly first-Mon 11:00 ET | `doc-drift-checker` |
| #15 (doc curator audit) | monthly third-Mon 11:00 ET | `doc-curator` |
| #27 (LSP marketplace verify) | monthly second-Mon 11:00 ET | `~/.claude/scripts/reapply_lsp_patches.py` (loop runs directly, not via agent) |
| #23 (fusion-lane auditor) | weekly Mon 11:00 ET | `fusion-lane-auditor` |
| #24 (rule-engine misfire auditor) | weekly Fri 08:00 ET | `rule-engine-misfire-auditor` |
| #25 (performance-regression hunter) | weekly Tue 09:00 ET | `performance-regression-hunter` |
| #26 (error-pattern watcher) | weekly Thu 09:00 ET | `error-pattern-watcher` |
| #33 (ci-health watcher) | daily 08:30 ET | `ci-health-watcher` |
| #34 (fleet-usage report) | weekly Sun 18:00 ET | `/fleet-usage` skill (loop runs it inline — not a subagent) |
| Pre-fire detector (gameday auto-close) | every loop tick (SQL check) | `gameday-postmortem` |

All other entries dispatch to `homehub-verifier` with an inline recipe. `homehub-watcher.md` has matching diagnostic procedures for entries #7, #23, #24, #25, #26, #33 (#33 is self-diagnosed — the watcher skips the investigator; #34 is verdict-only, no watcher procedure).

---

## Recommended next move

The Tier 1 thesis is validated. The lighting curator (shipped 2026-05-06) caught a real Slice B anti-pattern during the fleet run. Per-commit feedback loop works. The fleet pattern itself is now battle-tested for this codebase.

Forward-looking candidates, in priority order:

1. ✓ **Game Day Phase C integration shipped 2026-05-07** — `gameday` added to FloatingNav, theme.js MODE_CONFIG, Alexa HOMEHUB_MODE slot + lambda VALID_MODES. Voice end-to-end verified ("set relax mode" → `activity_events.source=alexa:SetModeIntent`). The verification surfaced a latent source-attribution bug in `set_manual_override` (engine hardcoded `source="manual"` instead of threading the route's `caller`), fixed in commit `31a1edf`. Documented in memory `project_override_caller_telemetry.md`.
2. ✓ **β EventLogger wiring + agent fleet automation pass shipped 2026-05-07** — celebrations now write to `light_adjustments` with `trigger="celebration:<key>"` (commit `34fc550`); `gameday-preflight` + `gameday-postmortem` registered as spawnable; runbook entries #12 #13 + Pre-fire detector wired; lighting-curator hook elevated to required-ack via `[curator-reviewed]` token. Full trigger map in Part 5 above.
3. ✓ **ML autonomy + dev-velocity tooling rounds shipped 2026-05-11** — 15 new agents, 11 new skills, 3 new hooks, 4 new MCP servers, 2 LSPs, 5 plugins, 4 data files, 7 new runbook entries. See Part 6 above for the full reference.
4. **Lighting palette + TTS line iteration for SEQUENCES** — Slice B placeholders still in place. User-driven authoring with curator review (now required-ack via the elevated hook + curator's section K celebration rules) on each diff before preseason 2026-08-13. Not an agent task per se; iterative collaboration.
5. **Pre-game ambient mode design** — was Game Day v2 deferred. Continuous Colts-tinted lighting earlier than T-30 (or extended baseline behavior). Spec session needed before implementation; revisit post-preseason once real-game data informs whether the pre-game ambient adds value.
6. **Memory hygiene auditor** (Tier 1) — defer. Quarterly cadence is too slow; `doc-drift-checker` (shipped 2026-05-07) covers structural drift, `doc-curator` (shipped 2026-05-07) covers long-form prose drift, and the Aug 1 remote agent runs the broad audit quarterly.
