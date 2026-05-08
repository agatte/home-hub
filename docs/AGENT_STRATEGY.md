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

**Doc drift checker.** **Shipped 2026-05-07. ✓** Walks a fixed set of authoritative-source-vs-doc comparisons: env vars in `config.py` vs CLAUDE.md `.env` block, route prefixes vs API Routes table, `app_settings` keys vs the SQLite Persisted Settings table, subagent fleet vs `~/.claude/agents/` filesystem, hook list vs `.claude/settings.json`, network device IPs vs `.env`, Tier shipped-status markers in this doc vs filesystem. Read-only — produces a drift report; caller decides which way to resolve (code is authoritative). The Aug 1 remote agent runs a similar audit quarterly; this agent is the on-demand variant. **Effort:** small-to-medium.

**PR review (backend + frontend).** **Shipped 2026-05-07. ✓** Two read-only specialist reviewers: `pr-review-backend` covers Python diffs against the global + project CLAUDE.md rules and the canonical memory footguns (current_mode field, camera-at-desk veto, manual-override preservation, refractory burn pattern, colorspace exclusivity); `pr-review-frontend` covers SvelteKit diffs against glass-card / Bebas Neue / Lucide / WS-into-stores / kitchen-pair-fusion conventions plus the build-warning hygiene list. On clean review each writes a marker file at `<git-dir>/.pr-review-{backend,frontend}-ok` containing the HEAD SHA. A pre-push hook (`pre_push_pr_review.py`) gates `git push` on the markers when the diff includes the relevant file types. Bypass: `SKIP_PR_REVIEW=1`. **Effort:** small — two agent files + one hook + settings.json wiring.

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

## Part 5 — Fleet usage playbook (when each agent fires, 2026-05-07)

The fleet is now substantially built. Most agents fire automatically — the only manual spawns left are deliberate one-shot specialist calls (a focused `homehub-verifier` recipe, a manual `gameday-postmortem` on a test fire, a `lighting-curator` review before a non-token commit).

### Trigger map

| Agent | Trigger | Cadence | Output sink |
|---|---|---|---|
| `homehub-verifier` | `/checkback-loop` dispatches | hourly anomaly sweep + dated entries (1, 3-11) | digest block in `~/.claude/runbooks/digests/YYYY-MM-DD.md` |
| `homehub-investigator` | `/watcher-loop` polls digests | always-on, ~30s polling for un-diagnosed warns | inline `**Diagnosis (HH:MM):**` subsection appended to the warn block |
| `ml-model-evaluator` | runbook entry #1 | weekly Mon 10:00 ET | digest block (agent writes its own) |
| `deploy-verifier` | `/deploy-home` skill step 7 | post-deploy, automatic | inline conversation report (no digest) |
| `lighting-curator` | PreToolUse hook on `git commit` | per-commit when staged diff matches lighting files + design identifiers | blocks commit unless `[curator-reviewed]` token in message |
| `gameday-preflight` | runbook entry #12 (preseason T-7) + entry #13 (weekly Sun Aug-Jan) + manual T-90 game morning | once preseason + every Sunday in NFL season + ad-hoc | digest block (agent writes its own) |
| `gameday-postmortem` | loop pre-fire detector on `gameday:auto` close (per `homehub-checkbacks.md` § Pre-fire detectors) + manual for test fires | within ~1h of every real game close (auto), ad-hoc otherwise | appends to today's digest |
| `pr-review-backend` | manual spawn before push (often via the deny message from the pre-push hook) | per-push when diff contains Python under `backend/`, `tests/`, `scripts/` | inline conversation report + writes `<git-dir>/.pr-review-backend-ok` containing HEAD SHA on PASS |
| `pr-review-frontend` | manual spawn before push | per-push when diff contains SvelteKit changes under `frontend-svelte/` | inline report + writes `<git-dir>/.pr-review-frontend-ok` containing HEAD SHA on PASS |
| `doc-drift-checker` | manual spawn (recommended after shipping a new agent / route / env var / app_setting key) | ad-hoc | inline drift report — never mutates docs |

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

## Recommended next move

The Tier 1 thesis is validated. The lighting curator (shipped 2026-05-06) caught a real Slice B anti-pattern during the fleet run. Per-commit feedback loop works. The fleet pattern itself is now battle-tested for this codebase.

Forward-looking candidates, in priority order:

1. ✓ **Game Day Phase C integration shipped 2026-05-07** — `gameday` added to FloatingNav, theme.js MODE_CONFIG, Alexa HOMEHUB_MODE slot + lambda VALID_MODES. Voice end-to-end verified ("set relax mode" → `activity_events.source=alexa:SetModeIntent`). The verification surfaced a latent source-attribution bug in `set_manual_override` (engine hardcoded `source="manual"` instead of threading the route's `caller`), fixed in commit `31a1edf`. Documented in memory `project_override_caller_telemetry.md`.
2. ✓ **β EventLogger wiring + agent fleet automation pass shipped 2026-05-07** — celebrations now write to `light_adjustments` with `trigger="celebration:<key>"` (commit `34fc550`); `gameday-preflight` + `gameday-postmortem` registered as spawnable; runbook entries #12 #13 + Pre-fire detector wired; lighting-curator hook elevated to required-ack via `[curator-reviewed]` token. Full trigger map in Part 5 above.
3. **ML model evaluator** — wired, awaiting first fire 2026-05-11 10:00 ET (runbook entry #1). Recommendation flips from "ship it" to "evaluate the first weekly digest's per-lane output, then decide whether to re-add the predictor lane to fusion or retarget the audio gate." Memory: `project_ml_evaluator.md`, `project_step5_predictor_validation.md`.
4. **α: Lighting palette + TTS line iteration for SEQUENCES** — Slice B placeholders still in place. User-driven authoring with curator review (now required-ack via the elevated hook + curator's section K celebration rules) on each diff before preseason 2026-08-15. Not an agent task per se; iterative collaboration.
5. **γ: Pre-game ambient mode design** — was Game Day v2 deferred. Continuous Colts-tinted lighting earlier than T-30 (or extended baseline behavior). Spec session needed before implementation; revisit post-preseason once real-game data informs whether the pre-game ambient adds value.
6. **Memory hygiene auditor / doc drift checker** (Tier 1) — defer. Quarterly cadence is too slow; doc drift overlaps with the Aug 1 remote agent.
