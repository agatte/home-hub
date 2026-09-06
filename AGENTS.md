# Home Hub Agent Guide

This file contains durable HomeHub rules that should always be in context. Use
repo-local skills for task-specific procedures instead of expanding this guide.

## Authority and source of truth

- `docs/PROJECT_SPEC.md` is authoritative for cross-system product direction,
  architecture, status boundaries, and roadmap.
- `docs/README.md` routes to subsystem specs. Read only the directly relevant
  current spec; dated audits/incidents are historical evidence unless current
  code or an authoritative spec confirms the claim.
- Keep `.env.example` and `backend/config.py` aligned when environment settings
  change. Never expose or overwrite `.env` secrets.
- Current code/runtime evidence decides whether a documented feature is actually
  shipped or healthy.

## Worktree safety

Before editing, inspect Git/worktree state and relevant diffs. Preserve unrelated
tracked/untracked work. Do not broadly clean, reset, replace, or reformat files
outside the task. Use an isolated worktree when substantial overlapping work or
branch isolation makes it useful.
## Workspace and runtime

- Canonical repo: `C:\Users\antho\Documents\home-hub-project\main`.
- Workspace/worktrees: `C:\Users\antho\Documents\home-hub-project\worktrees`.
- Preserve the canonical untracked root file `=`.
- Production host: Latitude; Windows is the development machine.
- Backend: FastAPI/Python/SQLite. Frontend: SvelteKit/Threlte/Three.js.
- Main runtime unit: `home-hub.service`. Never casually restart
  `home-hub-ambient.service`.

## Product and authority invariants

- User-facing house states are Away, Home, Winding Down, and Sleeping. `Idle`
  is not a user-facing house state; inactive maps to Away.
- Use `Likely: Getting Ready`, not `Guessing`.
- Physical evidence outranks weak software/process guesses. Software activity
  must never invent a physical room.
- Latitude person authority is YOLO-gated. MediaPipe localization supports room
  or posture only after person authority; blinded/unknown evidence abstains.
- Desktop bedroom camera evidence may localize desk/bed when source-qualified
  and fresh. Optional desktop signals may be absent and must age out cleanly.
- Sleeping wake authority is conservative: strong physical wake evidence may
  immediately set Home; trustworthy awake semantic activity may win; otherwise
  General/Home precedes stronger activity after normal dwell. PC/device wake
  alone must not exit Sleeping.
## Automation and lighting invariants

- `AutomationEngine` is the central activity-mode policy coordinator. Travel is
  a host lifecycle above activity modes, not another activity priority.
- Respect manual, transit, scene, away/external-off, screen-sync, and lifecycle
  ownership. Do not bypass established automation apply chokepoints without an
  explicitly owned write path.
- Preserve protected lights and fresh source-qualified ScreenSync targets; do
  not assume ScreenSync always owns only L2/L5.
- Kitchen lights L3/L4 match in functional modes and guest party scenes.
- Never mix CT and HSB fields in one Hue bridge payload.
- Preserve in-flight transition/event-stream reconciliation so stale echoes do
  not cause brightness pops or UI snapback.
- Sleeping, DND, arrival, away, manual override, and reacquisition have distinct
  semantics; do not collapse them into one generic override.

## Validation and review

Verify proportionally to risk and touched contracts. Start focused; broaden or
repeat only when shared behavior, new failures, unresolved concerns, or release
gates justify it.

- Python: focused pytest plus Ruff for changed Python surfaces.
- Svelte: `npm run check`, relevant unit tests, and build for changed frontend.
- UI/3D: browser/screenshot verification when rendered behavior changed.
- Lighting/central lifecycle: bounded evidence, ownership reasoning, targeted
  tests, and proportional review before production.
- Docs-only: validate factual claims/links/commands; avoid unrelated suites.
## Repo-local skills

Use the smallest applicable skill:

- `homehub-diagnose`: live health/API, mode/presence/ML, override, and log triage.
- `deploy-home`: publishing/deployment preparation and verified Latitude release.
- `ui-audit`: rendered dashboard/guest UI verification.
- `flag-queue`: durable follow-up capture/review when explicitly useful.

Ordinary issue implementation, GitHub CI inspection, and routine code search do
not need dedicated HomeHub skills.

## Publishing and live-system boundaries

Commit, push, merge, deploy, migration, service restart, hardware/device write,
credential change, and destructive actions are separate consequential steps.
Complete reversible preparation first. Perform a consequential step when it is
already explicitly authorized in the current session; otherwise ask only when a
concrete action/result is ready for approval.

Start production investigation read-only. Use bounded endpoints and SELECT-only
queries before live writes. Do not infer current health from committed code.

Authorized production deployment must use `scripts/deploy.sh`. Before deploying,
capture current build/state and lifecycle holds. Afterward confirm expected build
rollover, health, touched surfaces, required service state, and the post-restart
journal window. Never invent a parallel deployment path.
## Historical material

`.claude/` artifacts and dated agent/runbook material may help historical
investigation but are not current architecture, workflow, or live-system truth.
Do not load retired memories/loops unless the user explicitly asks for relevant
historical evidence.
