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

**Lighting curator.** **Shipped 2026-05-06. ✓** Review subagent that knows the apartment palette + the rules in `feedback_lighting_design_principles.md` (kitchen pair, post-sunset CT≥333 mirek, IES 1:3 contrast, HSB-vs-CT exclusivity, effects flatten per-light HSB). When you (or the main session) propose changes to `light_state_calculator.py` or curated scenes in `routes/scenes.py`, this agent reviews the diff against the rules before commit. Catches lighting-design rule violations the main session occasionally misses. Verified end-to-end: smoke test on `f1fac03` reported STATUS: ok with bonus structural insight; negative test against 3 contrived violations caught all 3 + 1 emergent finding (unreachable `wee_hours` period key). PreToolUse nudge hook live. **Effort:** small — one agent definition + a memory citation list.

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

## Part 4 — Phase B fleet experiment retrospective (2026-05-07)

The fleet ran end-to-end. Game Day Phase B Slices B + C + D were spawned in 3 parallel worktree-isolated `general-purpose` agents. Slice A had been done solo-serial earlier (correctly — A was the unblocking interface; parallelism gains nothing on sequentially-required work). Master session coordinated: pre-allocated file ownership (no overlap), wrote self-contained briefs per slice, spawned all three in a single message, waited for all three to return, ran lighting-curator on Slice B's diff, merged in dependency order, did the integration commits.

### What worked

- **File-disjoint plan held perfectly.** Zero merge conflicts across 4 branches (B/C/D + integration). The interface-pinning that Phase A spec §4 enforced was the load-bearing piece — none of the agents had to invent contracts.
- **Curator caught a real anti-pattern.** Slice B agent set `_COLTS_BLUE_SAT = 254` for the celebration pulse helper. Lighting-curator subagent flagged this as the same room-overload pattern the gaming retune (sat 240→180) addressed; we dropped it to 215 before merge. A static linter wouldn't have caught this — the curator reasoned about the apartment's textile palette and the time-window of all-lights-saturated-blue.
- **Agent continuity via SendMessage paid off** for the follow-up dynamic-volume work. The Slice B agent was resumed (not re-spawned) — retained context on the orchestrator's design (kitchen-pair invariant test, `_SafeFormatDict` template substitution, cooldown stamping, SEQUENCES dict structure), synced its worktree to current master, and shipped 199 tests + ruff-clean code in a single session.
- **Live verification end-to-end worked first try.** Synthetic touchdown fired through GameDayService → CelebrationOrchestrator → HueService + TTSService + WebSocketManager, all observed in journalctl with correct ordering. The deploy-verifier subagent (already auto-fires after `/deploy-home`) caught no regressions.

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

## Recommended next move

The Tier 1 thesis is validated. The lighting curator (shipped 2026-05-06) caught a real Slice B anti-pattern during the fleet run. Per-commit feedback loop works. The fleet pattern itself is now battle-tested for this codebase.

Forward-looking candidates, in priority order:

1. **Game Day Phase C integration** — small main-session work: add `gameday` to FloatingNav nav array, add `gameday` MODE_CONFIG entry in `theme.js`, update `HOMEHUB_MODE` Alexa slot + lambda + interaction model. Solo-serial; ~1-2 hour task. Gates on no concrete need until preseason approaches but worth knocking out anytime.
2. **ML model evaluator** (Tier 2) — consolidates 3+ recurring runbook entries (predictor validation, audio classifier checkpoints, override-rate trend, retention sweep) into one specialist that owns ML observability. Per-week feedback rather than quarterly. Medium effort. Already specified in memory `project_ml_evaluator.md` with first fire 2026-05-11.
3. **Lighting palette + TTS line iteration** for Game Day SEQUENCES — Slice B agent shipped placeholders. User-driven authoring with curator review on each diff before preseason 2026-08-15. Not an "agent" task per se; more an iterative collaboration.
4. **Memory hygiene auditor / doc drift checker** (Tier 1) — defer. Quarterly cadence is too slow; doc drift overlaps with the Aug 1 remote agent.
