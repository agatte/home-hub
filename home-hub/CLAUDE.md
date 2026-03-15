# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Hub is a unified home automation dashboard controlling Philips Hue lights and a Sonos speaker. It runs as a single FastAPI server that also serves the React frontend. The system includes intelligent lighting automation based on time of day and PC activity detection, a morning routine with weather/traffic TTS, and native Hue bridge scene/effect support.

## Commands

```bash
# Start the server (production)
cd home-hub && python run.py

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
```

## Architecture

### Backend (FastAPI + async)

- **`backend/main.py`** — App lifespan initializes all services, registers routes, starts background tasks (Hue polling, Sonos polling, automation loop, scheduler). WebSocket endpoint at `/ws` handles bidirectional light/sonos commands and broadcasts state changes.
- **Two Hue APIs**: `hue_service.py` (v1/phue2) for basic light control + polling; `hue_v2_service.py` (CLIP API v2/httpx) for native scenes and dynamic effects. Both talk to the same bridge. v2 uses UUIDs, v1 uses integers — a mapping cache bridges them.
- **`automation_engine.py`** — Background loop (60s interval) applies time-based lighting rules. Accepts activity reports from PC agent and ambient monitor. Manual overrides from dashboard have 4-hour auto-timeout.
- **`scheduler.py`** — Async cron scheduler (no external deps). Drives the morning routine at 6:40 AM weekdays.
- **`morning_routine.py`** — Fetches weather (OpenWeatherMap) + traffic (Google Maps Directions), generates TTS, plays on Sonos.
- **`pc_agent/`** — Standalone scripts that POST mode changes to `/api/automation/activity`. `activity_detector.py` uses psutil for game/media process detection. `ambient_monitor.py` uses PyAudio for Blue Yeti mic RMS measurement (party detection).

### Frontend (React 18 + Vite)

- **`context/HubContext.jsx`** — Single context provider manages all state (lights, sonos, automation mode). WebSocket connection handles real-time updates. Exposes `setLight`, `sonosCommand`, `activateScene`, `setManualMode`.
- **`pages/Home.jsx`** — Main dashboard: Mode indicator/override → Lights grid → Scene presets → Native Hue scenes → Effects → Sonos player → Routines.
- **`components/lights/NativeSceneGrid.jsx`** — Fetches bridge scenes (deduplicated by name across rooms) and dynamic effects. Clicking a scene activates it in all rooms.
- Built frontend is served by FastAPI via `/{path:path}` catch-all (must come after API routes).

### Key Patterns

- **Optimistic updates**: Light commands update local state immediately, then send via WebSocket.
- **Polling + WebSocket hybrid**: Hue polled every 1s, Sonos every 2s. Changes detected by polling are broadcast to all WebSocket clients. This catches external changes (Alexa, Hue app).
- **API route prefix**: All REST endpoints use `/api/` prefix. Health is at `/health` (no prefix).
- **Scene routing**: `POST /api/scenes/{id}/activate` checks if ID is a preset name or UUID, routes to v1 or v2 API accordingly.
- **Config**: All settings via `pydantic-settings` loading from `.env`. See `.env.example`.

## Important Notes

- The Hue bridge uses a self-signed SSL cert — httpx calls use `verify=False`.
- `phue2` pip package imports as `from phue import Bridge` (not `from phue2`).
- Sonos TTS requires the server's LAN IP (`LOCAL_IP` in .env) because Sonos fetches the MP3 from the server.
- The `/{path:path}` frontend catch-all in main.py MUST be registered after all API routes.
- PC agent scripts are standalone processes, not part of the FastAPI server — they communicate via HTTP POST.
- Timezone is `America/Indiana/Indianapolis` (Indiana has unique DST rules).
- `aiosqlite` is required at runtime for SQLAlchemy async SQLite.
