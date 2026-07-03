# Codex Todo

Current branch: `refactor/engine-step5-light-applicator`

## Status

- [x] Add Codex repo guide in `AGENTS.md`.
- [x] Read existing Claude guide, project spec, test layout, CI workflow, and MCP config.
- [x] Read key global Claude agents: lighting curator, PR reviewers, GitHub triager, verifier, deploy verifier, and test coverage prospector.
- [x] Record external Claude agents, lighting references, and memory paths in `AGENTS.md`.
- [x] Verify active LightApplicator refactor with targeted automation tests.
- [x] Verify adjacent transit, desk-exit, and screen-sync tests.
- [x] Commit Codex docs separately from the LightApplicator refactor.
- [ ] Optional: port selected Claude checks into repo-native scripts or git hooks if we want automatic enforcement outside Claude.
- [ ] Connect Codex workflow to live GitHub Issues/PRs via `gh` when needed.
- [ ] Define an issue-to-test checklist for future feature work.

## Recommended Workflow

1. Use `AGENTS.md` as the Codex entry guide and `.claude/CLAUDE.md` for deeper project context.
2. For backend edits, run targeted pytest plus `python -m ruff check`.
3. For frontend edits, run `cd frontend-svelte && npm run check` and `npm run test`.
4. For lighting-state diffs, consult `C:\Users\antho\.claude\agents\lighting-curator.md` and the lighting reference `INDEX.md` before committing.
5. For broad backend/frontend diffs, mirror the static review rubrics from `pr-review-backend.md` or `pr-review-frontend.md`.
6. For live questions, prefer read-only MCP verification: `get_live_state` first, bounded `query_db` SELECTs for history.
7. Ignore `.claude/worktrees` during normal work unless doing archaeology on an old experiment.

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
