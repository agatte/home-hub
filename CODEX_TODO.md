# Codex Todo

Current branch: `refactor/engine-step5-light-applicator`

## Status

- [x] Add Codex repo guide in `AGENTS.md`.
- [x] Read existing Claude guide, project spec, test layout, CI workflow, and MCP config.
- [x] Verify active LightApplicator refactor with targeted automation tests.
- [x] Verify adjacent transit, desk-exit, and screen-sync tests.
- [ ] Decide whether to commit the Codex guide and LightApplicator refactor together or separately.
- [ ] Connect Codex workflow to live GitHub Issues/PRs via `gh` when needed.
- [ ] Define an issue-to-test checklist for future feature work.

## Recommended Workflow

1. Finish the active LightApplicator refactor before starting new feature work.
2. Use `AGENTS.md` as the Codex entry guide and `.claude/CLAUDE.md` for deeper project context.
3. For backend edits, run targeted pytest plus `python -m ruff check`.
4. For frontend edits, run `cd frontend-svelte && npm run check` and `npm run test`.
5. Ignore `.claude/worktrees` during normal work unless doing archaeology on an old experiment.

## Current Validation

- `python -m pytest tests/test_automation_engine.py -q`
  - Result: `198 passed`
  - Note: existing pending `_sleep_fade()` task cleanup warnings appeared after test completion.
- `python -m pytest tests/test_transit_lighting_service.py tests/test_desk_exit_kitchen_service.py tests/test_screen_sync_multi.py -q`
  - Result: `85 passed`
- `python -m ruff check backend/services/automation_engine.py backend/services/light_applicator.py backend/services/engine_state.py backend/services/light_override_manager.py`
  - Result: passed
