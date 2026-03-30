# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Hub is a unified home automation dashboard controlling Philips Hue lights and a Sonos Era 100 speaker. It runs as a single FastAPI server that also serves the React frontend. The system includes intelligent lighting automation based on time of day and PC activity detection, a morning routine with weather/traffic TTS, native Hue bridge scene/effect support, mode-aware music playlists with smart auto-play, and a planned game-day mode for Colts games with dynamic light celebrations.

## Commands

```bash
# Start the server
python run.py

# Start with uvicorn directly
python -c "import uvicorn; uvicorn.run('backend.main:app', host='0.0.0.0', port=8000)"

# PC activity detector (separate terminal)
python -m backend.services.pc_agent.activity_detector

# Ambient noise monitor (separate terminal, requires Blue Yeti + PyAudio)
python -m backend.services.pc_agent.ambient_monitor

# Frontend dev server (hot reload, proxies API to :8000)
cd frontend && npm run dev

# Build frontend (outputs to frontend/dist/, served by FastAPI)
cd frontend && npm run build

# Install Python dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd frontend && npm install

# First time setup
python -m venv venv
venv/Scripts/pip install -r requirements.txt
cp .env.example .env  # Edit with your values
cd frontend && npm install && npm run build
```

Server runs at http://localhost:8000. Frontend dev server: `cd frontend && npm run dev` on port 3000 (proxies API to 8000).

## Claude Code Tooling

### MCP Server (`backend/mcp_server.py`)

A custom MCP server that wraps the Home Hub REST API as Claude tools. When the main server is running, Claude can call these directly to verify changes without manual testing.

```bash
# The MCP starts automatically when Claude Code opens this project.
# To test it manually:
python -m backend.mcp_server
```

**Available tools:**
- `get_health()` — system status + device connectivity
- `get_lights()` / `set_light(id, on, bri, hue, sat)` — light control
- `get_automation_status()` / `set_mode(mode)` — automation state
- `get_schedule()` / `get_mode_brightness()` — schedule + brightness config
- `get_scenes()` / `activate_scene(id)` — scenes
- `get_effects()` / `activate_effect(name)` — dynamic effects
- `get_sonos_status()` / `sonos_play()` / `sonos_pause()` / `sonos_volume(vol)` — Sonos
- `get_sonos_favorites()` / `get_mode_playlists()` — music
- `get_routines()` — routine configs
- `query_db(sql)` — read-only SQLite queries (SELECT only)

**Registered in:** `.claude/mcp.json`

### Hooks (`.claude/settings.json`)

Hooks fire automatically after file edits:

- **Python files (`backend/**/*.py`):** Runs `ruff check --fix` after every edit. Auto-fixes imports, style, and common issues.
- **Frontend files (`frontend/src/**/*.{js,jsx,svelte}`):** Runs ESLint after every edit.

### Skills

| Skill | Command | Purpose |
|-------|---------|---------|
| `home-hub-dev` | `/home-hub-dev` | Start dev environment, verify Hue/Sonos connectivity |
| `api-audit` | `/api-audit` | Smoke test all API endpoints via MCP |
| `ui-audit` | `/ui-audit` | Playwright screenshots at desktop + mobile widths |
| `project-spec` | `/project-spec` | Create or update `docs/PROJECT_SPEC.md` |

## Architecture

```
Browser / Android Tablet (kiosk) / Phone (PWA)
        |  WebSocket + REST
        v
   FastAPI Backend (port 8000)
   ├── HueService (v1/phue2) ──> Hue Bridge (basic light control, 1s polling)
   ├── HueV2Service (CLIP API) ──> Hue Bridge (native scenes, dynamic effects)
   ├── SonosService (SoCo) ──> Sonos Era 100 (UPnP, zero-auth)
   ├── TTSService ──> edge-tts generates MP3 ──> Sonos plays URL
   ├── AutomationEngine ──> time + activity → light state
   ├── MusicMapper ──> mode change → smart Sonos auto-play
   ├── Scheduler ──> morning routine (weather + traffic TTS)
   ├── SQLite (aiosqlite + SQLAlchemy async)
   └── Serves React static build from frontend/dist/
```

### Backend (FastAPI + async)

- **`backend/main.py`** — App lifespan initializes all services, registers routes, starts background tasks (Hue polling, Sonos polling, automation loop, scheduler). WebSocket endpoint at `/ws` handles bidirectional light/sonos commands and broadcasts state changes.
- **Two Hue APIs**: `hue_service.py` (v1/phue2) for basic light control + polling; `hue_v2_service.py` (CLIP API v2/httpx) for native scenes and dynamic effects. Both talk to the same bridge. v2 uses UUIDs, v1 uses integers — a mapping cache bridges them.
- **`automation_engine.py`** — Background loop (60s interval) applies time-based lighting rules. Accepts activity reports from PC agent and ambient monitor. Manual overrides from dashboard have 4-hour auto-timeout. Supports `register_on_mode_change` callbacks for extensibility (used by MusicMapper).
- **`music_mapper.py`** — Maps activity modes to Sonos favorites/playlists (persisted to SQLite). On mode change: auto-plays if Sonos is idle, broadcasts a WebSocket suggestion if Sonos is busy. Registered as a mode-change callback on the AutomationEngine.
- **`library_import_service.py`** — Parses Apple Music/iTunes library XML exports (plistlib). Extracts artist play counts, genre distribution, playlist name signals. Builds a TasteProfile with mode-genre mapping.
- **`recommendation_service.py`** — Uses Last.fm `artist.getSimilar` API for discovery and iTunes Search API for 30-second preview URLs + artwork. Generates per-mode recommendations scored by similarity, genre overlap, and user feedback. Caches Last.fm results in DB (30-day TTL).
- **`scheduler.py`** — Async cron scheduler (no external deps). Drives the morning routine at 6:40 AM weekdays.
- **`morning_routine.py`** — Fetches weather (OpenWeatherMap) + traffic (Google Maps Directions), generates TTS, plays on Sonos.
- **`pc_agent/`** — Standalone scripts that POST mode changes to `/api/automation/activity`. `activity_detector.py` uses psutil for game/media process detection. `ambient_monitor.py` uses PyAudio for Blue Yeti mic RMS measurement (party detection).

### Frontend (React 18 + Vite)

- **`context/HubContext.jsx`** — Split context providers (Lights, Sonos, Automation, Music, Connection) for minimal re-renders. WebSocket connection handles real-time updates including `music_suggestion` and `music_auto_played` events. Exposes `setLight`, `sonosCommand`, `activateScene`, `setManualMode`, `useMusic`.
- **`pages/Home.jsx`** — Main dashboard: Mode indicator/override → Lights grid → Scene presets → Native Hue scenes → Effects → Sonos player → Routines → MusicSuggestionToast.
- **`pages/Music.jsx`** — Music page: Taste profile (genre donut, top artists, library import), mode-to-playlist mapping, and discovery feed (recommendations with preview/like/dismiss).
- **`components/lights/NativeSceneGrid.jsx`** — Fetches bridge scenes (deduplicated by name across rooms) and dynamic effects. Clicking a scene activates it in all rooms.
- Built frontend is served by FastAPI via `/{path:path}` catch-all (must come after API routes).

### WebSocket Protocol

Server pushes `light_update`, `sonos_update`, `connection_status`, `mode_update`, `music_suggestion`, `music_auto_played` events. Clients send `light_command`, `sonos_command` messages. All JSON with `type` + `data` fields.

### Key Patterns

- **Optimistic updates**: Light commands update local state immediately, then send via WebSocket.
- **Polling + WebSocket hybrid**: Hue polled every 1s, Sonos every 2s. Changes detected by polling are broadcast to all WebSocket clients. This catches external changes (Alexa, Hue app).
- **API route prefix**: All REST endpoints use `/api/` prefix. Health is at `/health` (no prefix).
- **Scene routing**: `POST /api/scenes/{id}/activate` checks if ID is a preset name or UUID, routes to v1 or v2 API accordingly.
- **Music auto-play**: `MusicMapper` is registered as a mode-change callback. On mode change, it checks Sonos state — plays the mapped favorite if idle, or broadcasts `music_suggestion` via WebSocket if Sonos is busy. Mappings persist to `mode_playlists` SQLite table.
- **Config**: All settings via `pydantic-settings` loading from `.env`. See `.env.example`.

## Important Notes

- The Hue bridge uses a self-signed SSL cert — httpx calls use `verify=False`.
- `phue2` pip package imports as `from phue import Bridge` (not `from phue2`).
- Sonos TTS requires the server's LAN IP (`LOCAL_IP` in .env) because Sonos fetches the MP3 from the server.
- Sonos auto-discovers via SSDP; override with `SONOS_IP` in `.env`.
- The `/{path:path}` frontend catch-all in main.py MUST be registered after all API routes.
- PC agent scripts are standalone processes, not part of the FastAPI server — they communicate via HTTP POST.
- Timezone is `America/Indiana/Indianapolis` (Indiana has unique DST rules).
- `aiosqlite` is required at runtime for SQLAlchemy async SQLite.
- Hue bridge first-time pairing requires pressing the physical bridge button.

## Future Phases

- **Game Day Engine** (~August pre-season): ESPN API polling, play detection (touchdown, field goal, big play), celebration orchestration (lights + TTS), GameDay.jsx live scoreboard.
- **Pixel Art Field**: PixiJS/Canvas retro football field with animated sprites showing plays.
