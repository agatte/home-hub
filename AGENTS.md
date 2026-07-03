# Home Hub Codex Guide

This repository is a personal smart-home control system for one apartment. It
runs a FastAPI backend, a SvelteKit frontend, Hue/Sonos integrations, local
agents, ML-assisted automation, and operational tooling for the production
Latitude machine.

## Source Of Truth

- `docs/PROJECT_SPEC.md` is the authoritative product and architecture spec.
- `.claude/CLAUDE.md` is the most complete day-to-day agent guide. Treat it as
  relevant project documentation even though it is Claude-branded.
- For ML work, read `docs/ML_SPEC.md`.
- For game-day work, read `docs/GAMEDAY_SPEC.md`.
- For personality/mood work, read `docs/PERSONALITY_LAYER.md`.
- Keep `.env.example` and `backend/config.py` in sync for environment changes.

## External Claude Resources

These live outside the repo and require explicit filesystem approval before
Codex can read them:

- `C:\Users\antho\.claude\agents\` - global Claude subagent specs. Use these as
  checklists, not as code to copy. Especially relevant:
  - `lighting-curator.md` for static review of lighting palette/state diffs.
  - `pr-review-backend.md` and `pr-review-frontend.md` for pre-push review
    rubrics.
  - `gh-backlog-triager.md` for read-only GitHub issue hygiene.
  - `homehub-verifier.md` for read-only live-system verification via MCP.
  - `deploy-verifier.md` for post-deploy semantic checks.
  - `test-coverage-prospector.md` for deciding what tests to add.
- `C:\Users\antho\.claude\agents\reference\lighting-curator\INDEX.md` -
  captioned apartment/light reference photos. Read the index first, then only
  the specific image relevant to a lighting diff.
- `C:\Users\antho\.claude\projects\C--Users-antho-Desktop-home-hub\memory\` -
  project memories and footguns. Read only the memory files relevant to the
  touched subsystem.

Do not read `.claude/settings.local.json` or other local settings unless the
user explicitly asks; they may contain private machine-specific data.

## Stack

- Backend: Python, FastAPI, async services, SQLite via SQLAlchemy/aiosqlite.
- Frontend: SvelteKit 2, Svelte 4, Vite 5, Threlte/Three.js, WebSocket stores.
- Hardware/services: Philips Hue v1/v2 APIs, Sonos via SoCo, Pi-hole/Unbound,
  desktop pc_agent processes, optional camera and microphone sources.
- Production server: Latitude at `192.168.86.210`; dev machine is Windows.

## Common Commands

```bash
python run.py
python -m backend.services.pc_agent.activity_detector
python -m backend.services.pc_agent.ambient_monitor
python -m backend.services.pc_agent.monitor_brightness --detect
pip install -r requirements.txt
pytest
python -m ruff check
python -m ruff check --fix
cd frontend-svelte && npm install
cd frontend-svelte && npm run dev
cd frontend-svelte && npm run build
cd frontend-svelte && npm run check
cd frontend-svelte && npm run test
cd frontend-svelte && npm run test:e2e
```

The backend serves `frontend-svelte/build/` on port 8000. The frontend dev
server proxies API calls to port 8000 and normally runs on port 3001.

## Editing Rules

- Preserve user work. This repo may have active uncommitted refactors; inspect
  `git status --short` and relevant diffs before editing.
- Do not overwrite secrets in `.env`.
- Avoid broad refactors unless the requested change requires them.
- Add or adjust tests when touching shared services, automation policy, route
  contracts, WebSocket behavior, or frontend stores.
- Prefer existing service and component patterns over introducing new ones.
- Keep comments useful and sparse. Many files already document non-obvious
  hardware or operational constraints.

## Backend Patterns

- New services generally expose `_connected`, `connected`, `async connect()`,
  `poll_state_loop(...)`, and `close()`, then get wired in `backend/bootstrap.py`.
- API routers live in `backend/api/routes/` and must be registered in
  `backend/main.py` before the Svelte catch-all.
- REST endpoints use `/api/{domain}` except `/health` and `/ws`.
- WebSocket broadcasts use `WebSocketManager.broadcast("{domain}_{event}", data)`.
- Persisted app settings use `load_setting(key)` and `save_setting(key, value)`;
  these helpers open their own sessions.
- Write endpoints should use `source_from_request(...)` when logging events.
- Mode-change callbacks are registered through
  `automation.register_on_mode_change(async_fn)` and should stay fast.

## Automation And Lighting Footguns

- `AutomationEngine` is the central mode policy coordinator. It combines time,
  activity, overrides, ML, DND, away suppression, scene overrides, brightness
  multipliers, weather, screen sync, and event logging.
- Do not bypass the automation apply chokepoints unless the feature explicitly
  owns bridge writes, as screen sync and celebration sequences do.
- Respect protected lights: manual per-light overrides, transit overrides, and
  screen-sync-owned L2/L5 while sync is fresh.
- Kitchen lights L3/L4 must match in functional modes and guest party scenes.
- CT and HSB color spaces must not be mixed in bridge payloads.
- The SvelteKit catch-all in `main.py` must remain after all API routers and
  after the Pi-hole proxy ordering rules documented there.

## Frontend Patterns

- Main source is `frontend-svelte/src/`.
- Stores live in `src/lib/stores/`; `stores/init.js` dispatches WebSocket events
  into domain stores.
- Shared components live in `src/lib/components/`.
- Routes live in `src/routes/`: home, music, analytics, gameday, settings,
  journal, personality, and guest pages.
- Use existing visual language: dense smart-home dashboard, live cards, mode
  backgrounds, Lucide icons, and established store/API helpers.
- For Three.js/Threlte work, verify the scene renders in browser-sized desktop
  and mobile viewports.

## Validation

- Backend targeted tests are usually faster and safer than full-suite runs for
  narrow changes, for example `pytest tests/test_automation_engine.py`.
- Run `python -m ruff check` for Python edits.
- Run `cd frontend-svelte && npm run check` for Svelte edits.
- Run `cd frontend-svelte && npm run test` for frontend logic edits.
- Hardware-dependent behavior should be verified with mocks/tests unless the
  user explicitly asks to hit live devices.

## Review Checklists

- Backend changes: use the `pr-review-backend.md` rubric when touching
  automation, API routes, scheduler tasks, source attribution, event logging,
  Hue/Sonos calls, DB schema, or service lifecycle.
- Frontend changes: use the `pr-review-frontend.md` rubric when touching
  Svelte routes/components/stores, WebSocket dispatch, theme/mode config, or
  responsive dashboard layout.
- Lighting-state changes: use `lighting-curator.md` plus the visual reference
  index before committing changes to `light_state_calculator.py`, `scenes.py`,
  or `celebration_orchestrator.py`.
- Live verification: use read-only Home Hub MCP checks first. Start with
  `get_live_state`; use bounded `query_db` SELECTs for event/history questions.
- Deploy verification: capture pre-deploy `build_id`, deploy, then confirm
  build rollover, health, live state shape, API smoke endpoints, and the
  post-restart event window.

## Operational Cautions

- Production deployment is documented in `.claude/CLAUDE.md`; use the existing
  `scripts/deploy.sh` flow rather than inventing a new one.
- Pi-hole admin runs loopback-only on production; `.lan` records are unreliable
  behind Google Wifi. `homehub-dashboard.local:8000` is the zero-config name.
- `HOME_HUB_API_KEY` gates write endpoints unless LAN/localhost bypass applies.
- `LOCAL_IP` must be a LAN IP for Sonos TTS; `localhost` will not work.
