# Home Hub Agent Guide

Keep only durable HomeHub rules here. Load task-specific docs or repo skills when
their subject is actually involved.

## Authority and workspace

- `docs/PROJECT_SPEC.md` is authoritative for cross-system product direction,
  architecture, status boundaries, and roadmap. `docs/README.md` routes to
  subsystem specs; read only what the task needs.
- Current code/runtime evidence decides whether documented behavior is shipped or
  healthy. Dated audits/incidents are historical evidence unless reconfirmed.
- Keep `.env.example` and `backend/config.py` aligned when environment settings
  change. Never expose or overwrite `.env` secrets.
- Before editing, inspect relevant Git/worktree state and diffs. Preserve unrelated
  tracked/untracked work; avoid broad resets, cleanup, rewrites, or reformatting.
- Canonical repo: `C:\Users\antho\Documents\home-hub-project\main`; worktrees:
  `C:\Users\antho\Documents\home-hub-project\worktrees`. Preserve root file `=`.
- Use an isolated worktree when overlap or branch isolation materially helps.
- Production is the Latitude. Windows is the development/desktop-agent machine.
  Do not casually restart `home-hub-ambient.service`.

## Product and sensing invariants

- User-facing house states are Away, Home, Winding Down, and Sleeping. `Idle` is
  not user-facing; inactive maps to Away. Use `Likely: Getting Ready`, not
  `Guessing`.
- Physical evidence outranks weak software/process guesses. Software activity must
  not invent a physical room.
- Latitude person authority is YOLO-gated. MediaPipe localization may refine room
  or posture only after person authority; blinded/unknown evidence abstains.
- Desktop bedroom camera evidence may localize desk/bed only when source-qualified
  and fresh. Optional desktop signals may be absent and must age out cleanly.
- Sleeping wake authority is conservative: strong physical wake evidence may set
  Home immediately; trustworthy awake semantic activity may win; otherwise use
  General/Home before stronger activity after normal dwell. PC wake alone cannot
  exit Sleeping.

## Automation and lighting invariants

- `AutomationEngine` coordinates activity-mode policy. Travel is a host lifecycle,
  not another activity priority.
- Respect manual, transit, scene, away/external-off, ScreenSync, protected-light,
  and lifecycle ownership. Do not bypass established apply chokepoints without an
  explicitly owned write path.
- Preserve fresh source-qualified ScreenSync targets; do not assume it owns only
  L2/L5. Kitchen L3/L4 match in functional modes and guest party scenes.
- Never mix CT and HSB fields in one Hue bridge payload.
- Preserve transition/event-stream reconciliation so stale echoes do not cause
  brightness pops or UI snapback.
- Sleeping, DND, arrival, away, manual override, and reacquisition have distinct
  semantics; do not collapse them into one generic override.

## Completion and validation

For an approved bounded task, continue through investigation, reversible
implementation, proportional validation, and integration preparation until the
acceptance criteria are met. Do not stop after the first successful implementation
merely to ask for review.
Stop when the task is complete, a consequential action needs authorization, or
unresolved ambiguity would change the product contract.

Local tests use disposable fixtures and have no production authority. Run the
checks needed to prove touched contracts, fix failures caused by the requested
change, and rerun affected checks without asking at each step. Broaden testing
only when shared behavior, failures, or a release gate justify it.

Use a repo-local skill only when its description matches the task. Ordinary issue
implementation, CI inspection, and code search do not require a skill.

## Publishing and live-system boundaries

Commit, push, merge, deploy, migration, service restart, hardware/device write,
credential change, and destructive actions are consequential steps. Perform one
when already explicitly authorized in the current session; otherwise complete
reversible preparation first and ask only at the concrete action gate.

Start production investigation read-only. Prefer bounded read endpoints and
SELECT-only queries before live writes; never infer live health from committed
code alone.

Authorized production deployment must use `scripts/deploy.sh`; the `deploy-home`
skill owns the detailed release procedure. Never invent a parallel deploy path.

`.claude/` artifacts and dated agent/runbook material are historical only. Do not
load retired memories/loops unless the task specifically needs that evidence.
