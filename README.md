# 🏠 Home Hub

A personal smart home OS that learns your lifestyle and adapts your environment automatically. Controls Philips Hue lighting and Sonos audio from a unified real-time dashboard — with intelligent automation, behavioral event logging, and a full **MCP server** that lets AI agents interact with the live system directly.

![Home Hub Dashboard](audit-home-full.png)

---

## Overview

Home Hub goes well beyond basic smart home control. Instead of manually adjusting lights and music, it monitors context — what you're doing on your PC, ambient sound levels, the time of day, your listening history — and makes adjustments automatically. It runs as a single server on your local network, accessible from any browser or installable as a PWA on mobile.

The standout feature: a [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that exposes the entire Home Hub API as AI-callable tools. Claude Code (or any MCP-compatible agent) can query system state, control lights, switch modes, manage Sonos, and run read-only database queries — all against the live running system.

---

## Features

### 🤖 MCP Server — AI-Native Control
Home Hub ships with a full MCP server (`backend/mcp_server.py`) built with FastMCP. It exposes 20 tools across every subsystem, registered in `.claude/mcp.json` for seamless Claude Code integration.

**Tool categories:**
- **System** — health check, Hue bridge + Sonos connectivity, WebSocket client count
- **Lights** — get all light states, set brightness/color/hue/saturation per light
- **Automation** — get current mode and source, override mode, get schedule, get per-mode brightness multipliers
- **Scenes & Effects** — list and activate presets, native Hue scenes (by UUID), and dynamic effects (candle, fire, sparkle, prism, glisten, opal)
- **Sonos** — playback state, play/pause, volume, list favorites
- **Music** — get mode-to-playlist mappings
- **Event Summary** — query behavioral data: mode transition counts, most-adjusted lights, most-played favorites over N days
- **Database** — read-only SELECT queries against the live SQLite database (non-SELECT statements raise a ValueError)

### 💡 Lighting
- Full Philips Hue control via dual API architecture — v1 (phue2) for polling and basic control, v2 (CLIP API) for native scenes and dynamic effects
- Time-based automation with 4-hour manual override timeout
- Optimistic UI updates for instant feel
- External changes (Hue app, Alexa) detected within 1 second via polling and broadcast to all WebSocket clients

### 🎵 Music
- Sonos control via SoCo (UPnP, zero authentication)
- Mode-aware playlist mapping — persisted to SQLite, manageable from the dashboard via `ModePlaylistMapper`
- On mode change: auto-plays mapped favorite if Sonos is idle, or broadcasts a `music_suggestion` WebSocket event if busy
- Apple Music / iTunes library XML import — parses play counts, genre distribution, and playlist signals to build a personal taste profile
- Music discovery via Last.fm `artist.getSimilar` + iTunes Search API for 30-second previews and artwork
- Recommendations scored by similarity, genre overlap, and user feedback; cached in SQLite with 30-day TTL

### 🤖 Automation & Event Logging
- PC activity detection via psutil — detects gaming, media playback, and idle states
- Ambient sound monitoring via Blue Yeti mic (PyAudio RMS) for party/event detection
- Both agents run as standalone processes, POSTing mode updates to `/api/automation/activity`
- `AutomationEngine` supports `register_on_mode_change` callbacks — MusicMapper and other services subscribe to mode changes
- `EventLogger` tracks every mode transition, light adjustment, and Sonos playback event to SQLite for behavioral analysis

### ⏰ Routines
- Morning routine fires at 6:40 AM weekdays — fetches weather (OpenWeatherMap) + traffic (Google Maps Directions), generates TTS via edge-tts, plays on Sonos
- Wind-down routine for evenings
- All routines triggerable manually from the dashboard

### 📱 Real-time Dashboard
- React 18 + Vite frontend served directly by FastAPI
- WebSocket for bidirectional communication — server pushes `light_update`, `sonos_update`, `mode_update`, `music_suggestion`, `music_auto_played` events
- Split context providers (Lights, Sonos, Automation, Music, Connection) for minimal re-renders
- Progressive Web App with service worker — installable on Android tablet as a kiosk display, works offline

---

## Tech Stack

| Layer | Technologies |
|---|---|
| Frontend | React 18, Vite, WebSocket, PWA + Service Worker |
| Backend | Python, FastAPI, SQLAlchemy (async), aiosqlite |
| MCP | FastMCP, Model Context Protocol |
| Hue | phue2 (v1 API) + httpx CLIP API (v2) |
| Sonos | SoCo (UPnP) |
| Music Discovery | Last.fm API, iTunes Search API |
| TTS | edge-tts → MP3 → Sonos |
| Scheduling | Custom async cron scheduler |
| PC Agent | psutil, PyAudio |

---

## Architecture

```
Browser / Android Tablet (kiosk) / Phone (PWA)
        |  WebSocket + REST
        v
   FastAPI Backend (port 8000)
   ├── HueService (v1/phue2) ──────► Hue Bridge  (basic control, 1s polling)
   ├── HueV2Service (CLIP API) ─────► Hue Bridge  (native scenes + dynamic effects)
   ├── SonosService (SoCo) ─────────► Sonos Era 100  (UPnP, zero-auth)
   ├── TTSService ──► edge-tts MP3 ──► Sonos fetches from LAN IP
   ├── AutomationEngine ──► time + activity → lighting mode
   ├── MusicMapper ──► mode change → smart Sonos auto-play
   ├── RecommendationService ──► Last.fm + iTunes → discovery feed
   ├── LibraryImportService ──► Apple Music XML → taste profile
   ├── EventLogger ──► mode/light/sonos events → SQLite
   ├── Scheduler ──► morning routine at 6:40 AM weekdays
   ├── SQLite (aiosqlite + SQLAlchemy async)
   └── Serves React static build from frontend/dist/

   Standalone processes (POST to /api/automation/activity):
   ├── pc_agent/activity_detector.py  (psutil — game/media/idle detection)
   └── pc_agent/ambient_monitor.py    (PyAudio — Blue Yeti RMS, party detection)

   AI Integration:
   └── mcp_server.py  (FastMCP — 20 tools, registered in .claude/mcp.json)
       ├── Lights, Scenes, Effects
       ├── Automation mode + schedule
       ├── Sonos playback + favorites
       ├── Behavioral event summary
       └── Read-only SQLite query tool
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Philips Hue Bridge on local network (physical button press required on first run)
- Sonos speaker on local network (auto-discovered via SSDP, or set `SONOS_IP` in `.env`)

### Installation

```bash
git clone https://github.com/agatte/home-hub.git
cd home-hub

# Create and activate virtual environment
python -m venv venv
venv/Scripts/activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt

# Build frontend
cd frontend && npm install && npm run build && cd ..

# Configure environment
cp .env.example .env
# Edit .env — at minimum set HUE_BRIDGE_IP and LOCAL_IP
```

### Running

```bash
# Start the main server
python run.py
# → http://localhost:8000

# Optional: PC activity detection (separate terminal)
python -m backend.services.pc_agent.activity_detector

# Optional: Ambient sound monitoring (requires Blue Yeti + PyAudio)
python -m backend.services.pc_agent.ambient_monitor

# Optional: MCP server for Claude Code integration
python -m backend.mcp_server

# Frontend hot-reload dev server (proxies API to :8000)
cd frontend && npm run dev
# → http://localhost:3000
```

---

## MCP Integration

Home Hub is registered as a Claude Code MCP server via `.claude/mcp.json`. With the MCP server running alongside the main server, Claude Code can inspect and control the live system directly — useful for verifying that code changes work against real hardware without manual testing.

Example interactions:
- "What mode is the system in right now?"
- "Turn on all the lights at 50% brightness"
- "What music has been playing most this week?"
- "Show me the mode transition history for the last 3 days"
- "Activate the movie night scene"

The `query_db` tool accepts any SELECT statement against the live SQLite database — only SELECT is permitted, non-SELECT statements raise a `ValueError`.

---

## Music Discovery Pipeline

1. **Import** — Upload an Apple Music library XML export → parses play counts, genre tags, and playlist names to build a `TasteProfile`
2. **Discovery** — Calls Last.fm `artist.getSimilar` for top artists → fetches 30-second iTunes preview URLs and artwork
3. **Scoring** — Recommendations ranked by Last.fm similarity × genre overlap × user feedback
4. **Caching** — Last.fm results stored in SQLite with 30-day TTL to minimize API calls

---

## Screenshots

| Dashboard | Music | Settings |
|---|---|---|
| ![Dashboard](audit-home-full.png) | ![Music](audit-music-full.png) | ![Settings](audit-settings-full.png) |

---

## Roadmap

- **Game Day Engine** — ESPN API polling for Colts games, play-type detection (touchdown, field goal, big play), celebration lighting sequences and TTS announcements
- **Pixel Art Scoreboard** — PixiJS retro football field with animated play sprites
- Expanded device support

---

## Notes

- Hue bridge uses a self-signed SSL cert — CLIP API calls use `verify=False`
- Sonos TTS requires `LOCAL_IP` in `.env` — Sonos fetches the MP3 directly from the server's LAN address
- Timezone is set to `America/Indiana/Indianapolis` (Indiana has unique DST rules)
- The React static build catch-all in `main.py` must be registered after all API routes
- PC agent scripts are standalone processes — they communicate via HTTP POST, not imported by the server

---

> Personal project — not affiliated with Philips, Sonos, Apple, Last.fm, or the Indianapolis Colts.
