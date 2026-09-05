# Home Hub Codex Guide

This is the primary repo-local operating guide for Codex work in HomeHub. The
repository is a personal smart-apartment system with a FastAPI backend,
SvelteKit dashboard, Hue and Sonos integrations, optional context agents,
ML-assisted automation, and production tooling for the Latitude host.

## Source of truth

- `docs/PROJECT_SPEC.md` is authoritative for cross-system product direction,
  architecture, status boundaries, and roadmap.
- `docs/README.md` explains document ownership and routes to subsystem docs.
- Read `docs/ML_SPEC.md` for ML work, `docs/GAMEDAY_SPEC.md` for Game Day,
  `docs/PERSONALITY_LAYER.md` for mood/personality work, and
  `docs/PRESENCE_LIGHTING_SCENARIOS.md` for presence/lighting history.
- Treat dated incidents, audits, cleanup plans, and delivery notes as historical
  evidence unless current code or an authoritative spec confirms the claim.
- Keep `.env.example` and `backend/config.py` aligned when environment settings
  change. Never overwrite or expose `.env` secrets.

Do not duplicate large product specifications here. Resolve conflicts in favor
of `docs/PROJECT_SPEC.md`, then verify shipped claims in current code when
needed.

## Working model

ChatGPT is the lead/orchestrator. Codex performs only the bounded task it was
dispatched for. Zero Codex workers is the normal state; use one only when the
task genuinely benefits from delegation, and a second only for independent,
collision-free, implementation-ready work where parallelism materially saves
time. Do not launch subagents merely because capacity exists.

Before delegated work, prefer direct evidence gathering and narrow the task to
the smallest useful files/symbols/tests. Reuse known context instead of broad
rediscovery. Prefer targeted validation and stop once the requested acceptance
criteria are proven.

Before editing:

1. Run `git status --short`, identify the current branch/worktree, and inspect
   relevant diffs.
2. Preserve unrelated tracked and untracked work. Do not clean, reset, replace,
   or reformat files outside the requested scope.
3. Use an isolated branch/worktree for substantial changes or issue work.
4. Read the governing spec and map the request to concrete files and tests.
5. Prefer the smallest change that satisfies the accepted contract.

Use targeted validation proportional to the blast radius. Live checks are
read-only first. Commits, pushes, issue/PR mutations, merges, deployments,
service restarts, migrations, hardware writes, and destructive actions remain
separate steps and require explicit user authorization. Authorization for code
changes alone does not authorize those operations.

Do not add AI-generated, co-author, or tool attribution boilerplate to commits
or pull requests.

## Stack and runtime

- Backend: Python, FastAPI, async services, SQLite via SQLAlchemy/aiosqlite.
- Frontend: SvelteKit 2, Svelte 4, Vite 5, Threlte/Three.js, WebSocket stores.
- Devices/services: Philips Hue v1/v2, Sonos via SoCo, optional camera,
  microphone, desktop activity, screen-sync, and peripheral agents.
- Current primary host/server role: Latitude at `192.168.86.210`, now designated
  as always-home infrastructure under #145. Routine laptop travel should use
  the older MacBook instead of removing the Latitude. Shipped `TRAVEL` remains
  a contingency/maintenance lifecycle, not the normal availability model.
  Windows remains the development machine and can provide optional desktop
  context.
- The backend serves `frontend-svelte/build/` on port 8000. Vite normally runs
  on port 3001 and proxies the API/WebSocket to port 8000.

## Common commands

```bash
python run.py
python -m backend.services.pc_agent.activity_detector
python -m backend.services.pc_agent.ambient_monitor
python -m backend.services.pc_agent.monitor_brightness --detect
python -m pip install -r requirements.txt
python -m pytest tests -v
python -m ruff check backend

cd frontend-svelte
npm ci
npm run dev
npm run build
npm run check
npm run test:unit
npm run test:e2e
```

Use `npm install` only when intentionally changing dependencies or the lockfile.
Playwright requires a running local stack or an explicit
`PLAYWRIGHT_BASE_URL`.

## Repository map

- `backend/main.py` — FastAPI app, router ordering, WebSocket endpoint, static
  frontend catch-all.
- `backend/bootstrap.py` — service composition, callbacks, lifecycle, and
  background-task startup/shutdown.
- `backend/api/routes/` — REST endpoints, normally under `/api/{domain}`.
- `backend/services/` — automation, integrations, context, routines, Game Day,
  ML, and operational services.
- `backend/services/pc_agent/` — optional desktop/Latitude observation agents.
- `frontend-svelte/src/lib/stores/` — client state and WebSocket dispatch.
- `frontend-svelte/src/lib/components/` — shared dashboard components.
- `frontend-svelte/src/routes/` — home, music, analytics, Game Day, settings,
  journal, personality, and guest routes.
- `tests/` and `frontend-svelte/src/**/*.test.*` — backend and frontend tests.
- `scripts/` — existing operational, setup, migration, and deployment helpers.

## GitHub issue workflow

Use GitHub read-only first. Before implementing an issue:

1. Read the issue body and comments and inspect linked branches or PRs.
2. Identify the subsystem and governing spec.
3. Locate the smallest relevant implementation and existing tests with `rg`.
4. State acceptance criteria as observable API shapes, state transitions,
   events, WebSocket messages, UI states, or verification results.
5. Choose the narrowest validation set that covers the change.

Do not mutate issues, labels, comments, PRs, or releases unless the user has
authorized that GitHub write. Record validation commands/results in PR or issue
text only when that write is in scope.

## Issue-to-test mapping

- Backend route: happy path, authorization/write gate, bad input, and source
  attribution when events are logged.
- Service or automation engine: focused unit tests with fake Hue/Sonos/WS;
  assert side effects, deduplication, callbacks, ownership, and event logging.
- ML/fusion/source trust: deterministic fixtures, stale-signal behavior,
  diversity/accuracy guardrails, authority boundaries, and persistence.
- Scheduler/background task: registration, manual trigger, idempotency,
  heartbeat/health visibility, and failure logging.
- Frontend store/WebSocket: message dispatch, store updates, API helpers, and
  error paths.
- Frontend component/layout: Svelte checks, relevant unit tests, and browser
  verification at desktop and mobile sizes.
- Lighting state/palette: targeted automation tests, protected-light and
  kitchen-pair checks, plus real-room visual review only when authorized.
- Ops/deploy: dry-run or read-only inspection first, then an explicit live plan
  naming endpoints, commands, rollback, and expected evidence.
- Docs only: validate links and factual claims; do not run unrelated runtime
  suites unless commands or configuration examples changed.

## Backend patterns

- Services generally expose `_connected`, `connected`, `async connect()`,
  `poll_state_loop(...)`, and `close()`, then are composed in
  `backend/bootstrap.py`.
- Register API routers in `backend/main.py` before the Svelte catch-all and
  preserve the documented Pi-hole proxy ordering.
- WebSocket broadcasts use
  `WebSocketManager.broadcast("{domain}_{event}", data)`.
- Persisted settings use `load_setting(key)` and `save_setting(key, value)`;
  those helpers open their own sessions.
- Write endpoints use `source_from_request(...)` where event attribution is
  required.
- Mode-change callbacks registered through
  `automation.register_on_mode_change(async_fn)` must stay fast.
- Keep external I/O failure-tolerant and preserve existing circuit-breaker,
  lifecycle, and observability patterns.

## Automation and lighting invariants

- `AutomationEngine` is the central activity-mode policy coordinator. Travel is
  a HOME/TRAVEL host state above activity modes, not another mode priority.
- Physical room evidence outranks process/activity guesses. Latitude person
  authority is YOLO-gated; `couch` is supporting MediaPipe localization only
  after YOLO confirms a real person. Blinded/unknown Latitude evidence abstains.
  The desktop bedroom camera may localize `desk` or `bed`; ambiguous evidence
  abstains. Software/process activity must never invent a physical room.
- Optional desktop signals may be absent. Consumers must honor freshness and
  degrade authority rather than retain stale context.
- Do not bypass automation apply chokepoints unless the feature explicitly owns
  bridge writes, such as screen sync or celebration sequences.
- Respect manual, transit, scene, away/external-off, and screen-sync ownership.
  Preserve protected lights and the fresh source-qualified ScreenSync target set;
  do not assume ScreenSync always owns only L2/L5.
- Kitchen lights L3/L4 match in functional modes and guest party scenes.
- Never mix CT and HSB fields in a Hue bridge payload.
- Preserve in-flight transition/event-stream reconciliation to avoid stale
  echoes, brightness pops, and UI snapback.
- Sleeping, DND, arrival, away, manual override, and reacquisition behavior have
  distinct lifecycle semantics; do not collapse them into a generic override.

## Frontend patterns

- `frontend-svelte/src/lib/stores/init.js` is the central WebSocket dispatcher.
- Reuse established stores, API helpers, Lucide icons, live cards, and mode
  visual language before introducing new patterns.
- Root layout owns kiosk chrome: `FloatingNav`, `VitalStrip`, `ModeOverlay`,
  `NowPlayingChip`, and `MusicPlayerOverlay`. Guest routes intentionally remove
  that chrome.
- The now-playing chip opens the overlay; `/music` remains the deeper discovery
  and settings page.
- For Three.js/Threlte changes, verify rendering, cleanup, reduced-motion
  behavior, and desktop/mobile viewport layouts.

## Review and validation

For Python changes, run the focused tests and `python -m ruff check backend`.
For Svelte changes, run `npm run check`, relevant unit tests, and `npm run build`.
Use broader suites only when shared contracts or blast radius justify them.

Backend review should check API contracts, auth/source attribution, event
logging, service lifecycle, async failure handling, scheduler registration,
database compatibility, and Hue/Sonos ownership. Frontend review should check
store dispatch, loading/error states, accessibility, responsive layout, kiosk
behavior, and subscription cleanup.

GitHub #151 is historical and resolved; do not assume an inherited red backend
baseline. If a broad current suite is red, reproduce and report the actual
failure rather than dismissing it as the old #151 baseline.

## Model and effort policy

Use the cheapest credible path: ChatGPT direct -> Luna -> Terra -> Sol -> Astra.
Terra Medium is the normal Codex implementation/debugging choice when a worker
is actually needed; do not default to High. Use Sol only for judgment-heavy
ownership/lifecycle, cross-service ambiguity, difficult architecture, or
meaningful high-risk runtime/security/data work.

Astra is never automatic. Before any Astra dispatch, explain why it is
justified, warn that it uses materially more Codex/Work allowance than Sol,
name the cheapest credible alternative and bounded Astra task, and wait for
Anthony's explicit approval. Requests to investigate, research, fix, review,
continue, or use the best model are not Astra approval.

## Live and operational safety

- Start live verification with read-only health/state endpoints and bounded
  `SELECT` queries. Never infer current health from committed code alone.
- Hardware-dependent behavior should use fakes/tests unless live access is
  explicitly requested.
- Use `scripts/deploy.sh` for an authorized production deployment; do not invent
  a parallel deployment path.
- Before an authorized deploy, capture the current build ID and relevant state.
  Afterward, confirm build rollover when expected, health, touched API/UI
  surfaces, and the post-restart event window.
- `HOME_HUB_API_KEY` gates writes unless the configured localhost/LAN bypass
  applies. Do not broaden trusted origins casually.
- `LOCAL_IP` must be a reachable LAN address for Sonos TTS; `localhost` will not
  work for the speaker.
- Pi-hole admin is loopback-only in production. Behind Google Wifi, `.lan`
  records are unreliable; `homehub-dashboard.local:8000` is the zero-config
  dashboard name.
- Database migrations, production restarts, device writes, and `.env` edits
  require explicit authorization, a bounded plan, and rollback awareness.

## Legacy reference

`.claude/CLAUDE.md` and other Claude-era repository artifacts may contain useful
historical operational detail, but they are optional references rather than the
active workflow or a prerequisite for normal work. Retired external memories,
agent directories, and scheduled monitoring loops are not sources of current
architecture or live-system truth. Do not access machine-local legacy settings
or memories unless the user explicitly requests a relevant historical inquiry.
