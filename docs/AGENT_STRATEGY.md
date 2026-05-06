# Agent Fleet Strategy + Multi-Agent Coding Workflow

**Captured 2026-05-06.** A menu of agents that could ship for this project (small to big), the research findings on multi-agent coding workflows that informed the menu, and a concrete playbook for using a parallel agent fleet to ship a large feature like Game Day.

This is a durable strategy document, not a plan-of-record. Shipping any individual agent listed here is a separate decision; shipping multi-agent Game Day is a separate decision. Read this first when proposing either.

---

## Verification note

Some Claude Code patterns referenced in research (notably a `/batch` skill that supposedly spawns 5–30 worktree agents) are NOT available in this project's skill set. As of capture date the available skills are: `/api-audit`, `/deploy-home`, `/home-hub-dev`, `/ui-audit`, `/project-spec`, `/checkback-loop`, `/watcher-loop` (project-specific) plus `/loop`, `/schedule`, `/simplify`, `/init`, `/review`, `/security-review`, `/update-config`, `/keybindings-help`, `/fewer-permission-prompts`, `/claude-api`, `/frontend-design`, `/ui-ux-pro-max` (user-global).

Canonical multi-agent path on this machine: **git worktrees + manual coordination**, OR the **experimental Agent Teams** behind `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`. Treat any reference elsewhere to a `/batch` skill as aspirational, not actionable.

---

## Part 1 — Agent ideas, ranked by value × effort

### Tier 1 — Ship soon (high value, low complexity)

**Lighting curator.** Review subagent that knows the apartment palette + the rules in `feedback_lighting_design_principles.md` (kitchen pair, post-sunset CT≥333 mirek, IES 1:3 contrast, HSB-vs-CT exclusivity, effects flatten per-light HSB). When you (or the main session) propose changes to `light_state_calculator.py` or curated scenes in `routes/scenes.py`, this agent reviews the diff against the rules before commit. Catches lighting-design rule violations the main session occasionally misses. **Effort:** small — one agent definition + a memory citation list.

**Memory hygiene auditor.** Quarterly read-only scan of `~/.claude/projects/.../memory/`. Flags: memories citing dates >60d old without recent verification, conflicting pairs (two memories taking opposite positions), orphan memories no longer referenced. Outputs a cleanup queue. Memory currently has 60+ entries and drift is real. **Effort:** small — one agent + a runbook entry firing every 90 days.

**Doc drift checker.** Diffs `PROJECT_SPEC.md` against actual route files / service file contents. Flags sections that lie. The Aug 1 remote agent partially does this but quarterly is too infrequent. PROJECT_SPEC is large (127k chars) and rots silently. **Effort:** small-to-medium.

### Tier 2 — Ship when relevant (medium value, medium complexity)

**Test coverage prospector.** For newly-changed code paths, suggests tests OR scaffolds them (using existing patterns from `tests/test_api_*.py`). Most useful on async/IO-heavy backend services where TDD is awkward. **Effort:** medium.

**Performance regression hunter.** Periodically benchmarks `/health`, `/api/automation/status`, `/api/lights`, the WS broadcast latency. Flags p95 regressions over a configurable threshold. **Effort:** medium — needs a baseline-storage scheme.

**ML model evaluator.** Owns offline accuracy evaluation on `ml_decisions` shadow rows. Surfaces drift, suggests retrain cadence, runs the predictor-collapse + audio-classifier checks that currently live as separate runbook entries. Consolidates ML observability into one specialist. **Effort:** medium.

**Frontend a11y auditor.** Playwright + axe on the SvelteKit pages. The existing `/ui-audit` is screenshot-only; a11y is a separate surface. **Effort:** small once the existing `/ui-audit` runner is reused.

**Refactor proposer.** Looks at files edited 3+ times in a sliding window, suggests consolidation/extraction. Catches slow drift toward unmaintainable modules (`automation_engine.py` is now 2500+ lines). **Effort:** medium.

### Tier 3 — Future / aspirational

**Game Day specialist.** Owns ESPN polling, celebration cooldowns, play→light-color map, pre-game routines. Spawned only during football season. (Note: this is the *runtime* specialist, not the Game-Day-implementation fleet — those are different. See Part 3.)

**Music librarian.** Owns mode→playlist mapping refresh, vibe tag updates, taste profile rebuild on new XML imports.

**Routine scheduler advisor.** Analyzes past mode-transition + Sonos data; proposes schedule tweaks ("Fridays you hit relax 2h earlier — should winddown move?").

**Backup verifier.** Confirms event tables, settings, lambda code are backed up offsite. Currently no backup story exists; this agent's first run would expose that gap.

**Dependency hygiene.** Pinned-version audit + security-advisory scan + breaking-change notes for proposed upgrades.

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

Stagger by 24-48h: spawn A first, then B once A's `register_on_play_event` interface is concrete, then C and D in parallel against the SvelteKit/Threlte boundary defined in Phase A. Each agent opens a PR; main session reviews and cherry-picks into main as they land. Run `/api-audit` after the merges, `/deploy-home` when frontend + backend are both in.

### Phase C — Integration + smoke (main session)

Main session is the integrator. Run the full system end-to-end. The deploy-verifier subagent catches structural regressions; the watcher loop catches anomalies in the post-deploy event window.

### Token cost reality check

Phase B at 4 worktree agents × ~2-3 days each ≈ **~12-15× tokens** vs. main-session-serial. That's real money. The trade is: ~4× wall-clock speed-up (assuming staggered review doesn't bottleneck) and a bunch of mostly-independent code authored in parallel. **Worth it for a 5-week feature; not worth it for a 2-day fix.**

---

## Where this could fail

1. **Phase A is rushed.** If interface contracts are vague, agents make incompatible assumptions and Phase C becomes "rewrite the integration glue", erasing the parallelism gain.
2. **Review bottleneck.** If 4 PRs land same-day, main session can't absorb them. Stagger or pre-bake review checklists.
3. **A new file you didn't anticipate.** E.g., agent B needs to edit `automation_engine.py` to register its callback at lifespan startup. Two agents touching one file = merge conflict. Phase A should explicitly designate which agent owns those shared touchpoints (typically the lead, i.e. main session).

---

## Recommended first move

If validating the agent-investment thesis cheaply: ship the **lighting curator** (Tier 1). Smallest scope, clearest payoff, shows whether reviewer agents catch what they're meant to catch.

If preparing for Game Day specifically: do **Phase A** with main session — spec + interface contracts + mockup. ~1-2 hour conversation, valuable regardless of whether Phase B goes parallel-fleet or solo-serial.

The two paths are complementary, not exclusive.
