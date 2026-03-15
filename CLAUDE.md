# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Hub — a unified local web app that controls Philips Hue lights and a Sonos Era 100 speaker, with a game-day mode (Phase 2) that will show a retro pixel-art football field during Colts games with dynamic light celebrations and TTS announcements.

## Architecture

```
Browser / Android Tablet (kiosk)
        |  WebSocket + REST
        v
   FastAPI Backend (port 8000)
   ├── HueService ──> Hue Bridge (192.168.1.50, phue2 library)
   ├── SonosService ──> Sonos Era 100 (SoCo library, UPnP :1400)
   ├── TTSService ──> edge-tts generates MP3 ──> Sonos plays URL
   ├── SQLite (scenes, settings, play tracking)
   └── Serves React static build from frontend/dist/
```

Single command to start: `cd home-hub && python run.py` (or `venv/Scripts/python run.py`)

## Tech Stack

- **Backend**: FastAPI + Uvicorn (async), Python 3.13
- **Frontend**: React 18 + Vite
- **Hue**: phue2 package (imports as `from phue import Bridge`)
- **Sonos**: SoCo package (zero-auth local UPnP)
- **TTS**: edge-tts (free Microsoft voices), fallback gTTS
- **Database**: SQLite via aiosqlite + SQLAlchemy async
- **Config**: pydantic-settings reading `.env`

## Running Locally

```bash
cd home-hub

# First time setup
python -m venv venv
venv/Scripts/pip install -r requirements.txt
cp .env.example .env  # Edit with your values

# Start server
venv/Scripts/python run.py
# or with venv activated:
python run.py
```

Server runs at http://localhost:8000. Frontend dev server (with HMR): `cd frontend && npm run dev` on port 3000 (proxies API to 8000).

## Key Endpoints

- `GET /health` — device connectivity status
- `GET /api/lights` — all light states
- `PUT /api/lights/{id}` — set light state (on, bri, hue, sat)
- `POST /api/lights/all` — set all lights at once
- `GET /api/scenes` — list scene presets
- `POST /api/scenes/{name}/activate` — activate a scene
- `GET /api/sonos/status` — now playing info
- `POST /api/sonos/play|pause|next|previous` — playback control
- `POST /api/sonos/volume` — set volume `{"volume": 50}`
- `POST /api/sonos/tts` — speak text `{"text": "Hello", "volume": 80}`
- `ws://localhost:8000/ws` — real-time state sync

## WebSocket Protocol

Server pushes `light_update`, `sonos_update`, `connection_status` events. Clients send `light_command`, `sonos_command` messages. All JSON with `type` + `data` fields.

## Project Structure

All application code lives in `home-hub/`:
- `backend/services/` — device control (hue_service, sonos_service, tts_service)
- `backend/api/routes/` — REST endpoints
- `backend/api/schemas/` — Pydantic request/response models
- `frontend/src/` — React app (pages, components, hooks, context)
- `backend/api/routes/scenes.py` — `SCENE_PRESETS` dict defines built-in scenes

## Important Notes

- phue2 pip package imports as `from phue import Bridge` (not `from phue2`)
- `.env` contains all secrets (Hue username, bridge IP) — never committed (public repo)
- Sonos auto-discovers via SSDP; override with `SONOS_IP` in `.env`
- TTS generates MP3 in `backend/static/tts/`, served at `http://{LOCAL_IP}:8000/static/tts/`, Sonos fetches it. `LOCAL_IP` must be the PC's LAN IP (not localhost).
- Frontend build (`npm run build` in `frontend/`) outputs to `frontend/dist/`, served by FastAPI catch-all route
- Hue bridge first-time pairing requires pressing the physical bridge button

## Phase 2 (Not Yet Built)

Game-day mode: local ESPN API poller replaces the old Lambda+ngrok+DynamoDB system. Celebration orchestration (lights + TTS) for touchdowns, sacks, INTs, etc. Retro pixel-art football field UI.
