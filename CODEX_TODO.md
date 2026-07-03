# Codex Todo

Current branch: `refactor/engine-step5-light-applicator`

## Status

- [x] Add Codex repo guide in `AGENTS.md`.
- [x] Read existing Claude guide, project spec, test layout, CI workflow, and MCP config.
- [x] Read key global Claude agents: lighting curator, PR reviewers, GitHub triager, verifier, deploy verifier, and test coverage prospector.
- [x] Record external Claude agents, lighting references, and memory paths in `AGENTS.md`.
- [x] Connect Codex workflow to live GitHub Issues/PRs via `gh`.
- [x] Verify active LightApplicator refactor with targeted automation tests.
- [x] Verify adjacent transit, desk-exit, and screen-sync tests.
- [x] Commit Codex docs separately from the LightApplicator refactor.
- [ ] Optional: port selected Claude checks into repo-native scripts or git hooks if we want automatic enforcement outside Claude.
- [x] Define an issue-to-test checklist for future feature work.
- [ ] Decide how to handle issue #87 after pushing/PRing this branch: comment with local validation, link PR, or close after merge.

## Recommended Workflow

1. Use `AGENTS.md` as the Codex entry guide and `.claude/CLAUDE.md` for deeper project context.
2. For backend edits, run targeted pytest plus `python -m ruff check`.
3. For frontend edits, run `cd frontend-svelte && npm run check` and `npm run test`.
4. For lighting-state diffs, consult `C:\Users\antho\.claude\agents\lighting-curator.md` and the lighting reference `INDEX.md` before committing.
5. For broad backend/frontend diffs, mirror the static review rubrics from `pr-review-backend.md` or `pr-review-frontend.md`.
6. For live questions, prefer read-only MCP verification: `get_live_state` first, bounded `query_db` SELECTs for history.
7. For GitHub issue work, read the issue body/comments first, map it to files/tests, then edit.
8. Ignore `.claude/worktrees` during normal work unless doing archaeology on an old experiment.

## GitHub Snapshot

Checked with `gh` on 2026-07-03:

- Authenticated as `agatte` for `github.com`; token has `repo` scope.
- Open issues: 73.
- Open PRs: 4.
- Current branch matches issue #87: `automation_engine.py decomposition steps 4-5 (light_override_manager + light_applicator) -- HIGH risk, deferred`.
- Open PRs at snapshot:
  - #104 `fix(a11y): silence LightCard composite-widget warnings with reason (#31)` (`issue-31-build-warnings` -> `master`)
  - #103 `feat(health): expose engine weather/lux state on /health (#67)` (`issue-67-health-weather-lux` -> `master`)
  - #102 `feat(source-trust): wire the audio_ml sanity predicate (#98)` (`issue-98-audio-ml-source-trust` -> `master`)
  - #101 `test(ml-logger): DST-boundary regression guard for backfill window` (`issue-30-dst-backfill-guard-test` -> `master`)

Useful read-only commands:

```bash
gh issue list --limit 30 --json number,title,labels,state,updatedAt,url
gh issue view <number> --json number,title,body,labels,state,url,comments
gh pr list --limit 20 --json number,title,headRefName,baseRefName,state,updatedAt,url
gh pr checks <number>
```

## Issue-To-Test Checklist Summary

For each GitHub issue, read the issue first, classify the subsystem, map likely
files and existing tests, define concrete acceptance criteria, then choose the
smallest validation set that covers the blast radius.

Default mapping:

- Backend route: happy path, auth/write gate, bad input, source attribution.
- Service/automation: fake hardware/unit tests for side effects, callbacks,
  dedup/override state, and event logging.
- ML/fusion/source-trust: deterministic fixtures, stale-signal behavior,
  accuracy/diversity guardrails, persistence where relevant.
- Scheduler/background task: registration, manual trigger, idempotency, failure
  logging.
- Frontend store/WS: dispatch, store update, API helper, error path tests.
- Frontend UI/3D: Svelte check, unit test where useful, browser/screenshot
  verification for layout-heavy or Three.js changes.
- Lighting palette/state: targeted automation tests plus lighting-curator review.
- Ops/deploy/live-system: dry-run/read-only commands first, then MCP verification
  plan with exact endpoints or queries.
- Docs-only: no runtime tests unless commands/config examples changed.

Record validation commands and results in the PR body or issue comment before
closing an issue.
## External Claude Resources Found

- `C:\Users\antho\.claude\agents\` contains 31 global agents.
- `C:\Users\antho\.claude\agents\reference\lighting-curator\INDEX.md` indexes the apartment lighting reference photos.
- `C:\Users\antho\.claude\projects\C--Users-antho-Desktop-home-hub\memory\` contains Home Hub-specific memory/footgun files.
- `.claude/settings.local.json` was intentionally not read; treat it as sensitive unless explicitly approved.

## Current Validation

- `python -m pytest tests/test_automation_engine.py -q`
  - Result: `198 passed`
  - Note: existing pending `_sleep_fade()` task cleanup warnings appeared after test completion.
- `python -m pytest tests/test_transit_lighting_service.py tests/test_desk_exit_kitchen_service.py tests/test_screen_sync_multi.py -q`
  - Result: `85 passed`
- `python -m ruff check backend/services/automation_engine.py backend/services/light_applicator.py backend/services/engine_state.py backend/services/light_override_manager.py`
  - Result: passed
