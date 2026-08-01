# Repository Cleanup — July 31, 2026

## Outcome

The initial repository-wide hygiene pass removed 326.9 MiB across 110 exact
targets. A tracked-file pass removed another 13.24 MiB of verified-dead media,
bringing the total to approximately 340.1 MiB. The cleanup focused on
unreferenced visual evidence, obsolete generated-only trees, build output,
caches, and unreachable shipped assets. Source, secrets, runtime evidence,
dependency environments, and active worktrees were preserved.

The removed untracked files were permanently deleted and are not recoverable
from Git. Every target was inspected or reference-checked before deletion.

## Removed

| Group | Reason |
|---|---|
| 80 root PNG/JPG UI captures (21.5 MiB) | Old audit iterations from April–May; no tracked references |
| `frontend/` (77.85 MiB) | Retired React tree contained only a generic README, compiled `dist`, and `node_modules`; no source remained |
| `experiments/` (68.17 MiB) | Contained only generated dependency/build state; no experiment source remained |
| Root `build/`, `dist/`, and `HomeHubNotifier.spec` (86.85 MiB) | PyInstaller output; installed notifier was verified byte-identical under `%LOCALAPPDATA%\HomeHub` and remains rebuildable |
| Browser/test/frontend/TTS caches (64.1 MiB) | Playwright captures, pytest/ruff caches, `.svelte-kit`, static frontend build, test output, bundle stats, and generated TTS |
| `docs/baseline-screenshots/` and `frontend-svelte/.backups/` (0.36 MiB) | Unreferenced April visual baselines and a superseded May settings-page copy |
| 15 project Python `__pycache__` directories (8.11 MiB) | Interpreter bytecode, regenerated automatically |
| `CODEX_TODO.md` | All tasks completed; its July 3 GitHub snapshot was stale and workflow guidance already lives in `AGENTS.md` |

## Tracked-file pass

A second pass reviewed every tracked root file and top-level document rather
than using reference count alone as a deletion signal. The following changes
were made:

| Change | Reason |
|---|---|
| Moved `docs/AUDIT_2026_05_05.md` to `docs/archive/` | Completed historical audit; useful evidence, but not an active design/spec document |
| Corrected MCP tool count `20 -> 31` in `README.md` | Counted directly from `@mcp.tool()` registrations |
| Corrected `.claude/mcp.json -> .mcp.json` in `backend/mcp_server.py` | The root `.mcp.json` is the current registration file |
| Removed three Game Day grass textures (~12.5 MiB) | Explicitly unused since HDRI ground projection replaced the PBR grass plane |
| Removed `backgrounds/working/buildings-near.png` and `sky.png` (~0.8 MiB) | Working mode uses only `street.png` plus a code-drawn gradient |
| Removed `getSkyVariant` and `TILE_WIDTH` exports | No imports or call sites; the helper also named three nonexistent sky variants |
| Removed unit assertions for those exports | Tests were preserving unreachable behavior rather than a runtime contract; live `LAYER_CONFIGS` coverage remains |

The following low-reference documents were deliberately retained:

- `CONFIDENCE_FUSION.md` is the shipped algorithm deep dive and complements,
  rather than duplicates, `ML_SPEC.md`.
- `PRESENCE_LIGHTING_SCENARIOS.md` is still a draft, but contains unresolved
  architectural decisions directly relevant to the July lighting incident.
- `Future_Development.md` is an ideation pool; GitHub Issues remain the active
  backlog.
- `AGENT_STRATEGY.md` is a historical tooling reference with an explicit Codex
  transition note, not an active always-on-agent claim.
- Root configuration files with few textual references (`pyproject.toml`,
  `.gitattributes`, `pyrightconfig.json`, and requirements files) are consumed
  implicitly by their tools and are not orphaned.

The in-app browser was unavailable for the tracked frontend-media pass, so no
before/after screenshots could be captured. Static import tracing established
that the removed exports and images were unreachable; Svelte validation was
used as the executable guardrail.

## Preserved intentionally

- `.env` and machine-specific settings
- `data/` and `logs/` because they contain operational evidence
- `venv/` and `frontend-svelte/node_modules/` for the active development setup
- `.claude/` settings, hooks, and worktrees
- Tracked PWA icons, 3D assets, backgrounds, and ambient audio
- `frontend-svelte/static/icon-192.png` and `icon-512.png`, which are ignored
  locally but referenced by the app manifest and HTML
- `docs/GUEST_APP_BRAINSTORM.md`, which remains an intentional local brain-vault
- `start.txt`, a small personal helper

## Regeneration and operational impact

The production Latitude was not modified.

The local FastAPI backend serves `frontend-svelte/build/`. After this cleanup,
rebuild that directory before expecting `python run.py` to serve the dashboard:

```powershell
cd C:\Users\antho\Desktop\home-hub\frontend-svelte
npm run build
```

`npm run dev` does not require the static build. The normal deployment script
also runs the frontend build automatically.

The desktop notifier remains installed. To recreate repository packaging
output later:

```powershell
.\scripts\build_desktop_notifier.ps1
```

Python bytecode, test caches, SvelteKit state, Playwright output, and generated
TTS files recreate themselves when their respective tools run.

## Cleanup policy going forward

- Keep temporary screenshots outside the repository root or delete them after
  the associated UI audit is complete.
- Do not commit generated builds, tool caches, local databases, logs, secrets,
  or dependency directories.
- A document should be indexed in `docs/README.md`, intentionally local and
  ignored, or removed once superseded.
- Prefer Git history over manual source-file backup folders.
- Never use broad `git clean -x` here: ignored paths include secrets, runtime
  data, logs, dependency environments, and active worktrees.
