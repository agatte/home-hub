# CLAUDE.md

> This file provides guidance to Claude Code when working in this repository.
> **Source of truth:** `docs/PROJECT_SPEC.md` — read it for full architecture, schema, and feature details. This file is the working guide; the spec is authoritative.
> **ML specification:** `docs/ML_SPEC.md` — audio classification, behavioral prediction, camera presence, adaptive lighting, and phased rollout plan.
> **Lighting expansion wishlist:** `docs/LIGHTING_EXPANSION.md` — Hue/Zigbee hardware recommendations by category and price tier, with per-apartment placement and integration notes.

---

## Project Overview

Home Hub is an always-on personal command center built for one apartment and one person. It controls Philips Hue lights and a Sonos Era 100 speaker from a single, visually striking dashboard running on a dedicated laptop display. The system detects what you're doing, adjusts lighting and music to match, and learns patterns over time until it can run on full autopilot.

The dashboard is a living interface with bold, mode-aware themed backgrounds — a retro pixel art landscape during gaming, a scrolling pixel city during working, flowing aurora borealis for relax, a 3D moon scene while sleeping, and gradient blobs with particles as a fallback. It shows everything at a glance: current mode, light colors, now playing, weather, upcoming routines. It's also the home screen for other personal projects (plant app, bar app) via animated widget cards.

**Core focus:** Lights and music working seamlessly. Everything else builds on that.

### Goals
- **Always-on command center** — 24/7 on a dedicated foldable laptop (1080p landscape), also works cleanly on mobile
- **Invisible automation** — Detects activity, adjusts lights and music, manages routines without manual input
- **Full autopilot learning** — Observes interactions, starts with simple rules, evolves toward autonomous decision-making
- **Bold, living UI** — Animated backgrounds that change with mode and time of day
- **Voice control** — Alexa via Fauxmo locally, custom skill later
- **Game day magic** — Colts games: synchronized lights, TTS celebrations, live scoreboard, pixel art field
- **Personal, not generic** — Every rule, mode, animation, and routine tuned for one person's apartment

### Current State (as of PROJECT_SPEC.md)

**Lighting:** Full Hue control, time-based automation, activity-driven modes, native Hue scenes and dynamic effects, social sub-styles, screen sync for gaming, manual override (4h timeout), per-mode brightness multipliers.

**Audio:** Sonos Era 100 control, mode-to-playlist mapping, smart auto-play, Apple Music library import + taste profile, Last.fm music discovery, TTS with duck-and-resume.

**Automation:** PC activity detection (psutil), ambient noise monitoring (Blue Yeti), mode priority system, morning routine (weather + commute TTS), evening wind-down, weather-reactive lighting (NWS alerts for real-time storm detection) + weather-driven music suggestions, all config persisted to SQLite.

**Dashboard:** Three pages (Home, Music, Settings), real-time WebSocket sync, PWA for phone/tablet, optimistic updates.

**Known Pain Points:** see `docs/PROJECT_SPEC.md` § "Known Issues & Pain Points" for the live list — that file gets updated as items ship.

---

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
cd frontend-svelte && npm run dev

# Build frontend (outputs to frontend-svelte/build/, served by FastAPI)
cd frontend-svelte && npm run build

# Install Python dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd frontend-svelte && npm install

# First time setup
python -m venv venv
venv/Scripts/pip install -r requirements.txt
cp .env.example .env  # Edit with your values
cd frontend-svelte && npm install && npm run build
```

Server runs at http://localhost:8000. Frontend dev server: `cd frontend-svelte && npm run dev` on port 3001 (proxies API to 8000).

### Production deploy (Latitude at 192.168.1.210)

```bash
# After git push from the dev machine, ship to production:
ssh anthony@192.168.1.210 "cd ~/home-hub && ./scripts/deploy.sh"
```

`scripts/deploy.sh` runs on the Latitude — `git pull --ff-only`,
diffs HEAD, reinstalls Python deps / rebuilds frontend / restarts
`home-hub.service` based on what changed, then health-checks via
`/health`. Verify via MCP tools (`mcp__home-hub__get_health`) without
leaving the dev machine.

When the backend restarts, the kiosk dashboard's WebSocket reconnects,
sees a new `build_id` in the `connection_status` message, and reloads
itself within ~1s — no manual F5 needed. Frontend rebuilds also trigger
a backend restart so the kiosk picks up the new `build_id`.

---

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
- `get_lights()` / `set_light(id, on, bri, hue, sat, ct)` — light control
- `get_weather()` — current weather conditions
- `get_automation_status()` / `set_mode(mode)` — automation state
- `get_schedule()` / `get_mode_brightness()` — schedule + brightness config
- `get_scenes()` / `activate_scene(id)` — scenes
- `get_effects()` / `activate_effect(name)` — dynamic effects
- `get_sonos_status()` / `sonos_play()` / `sonos_pause()` / `sonos_volume(vol)` — Sonos
- `get_sonos_favorites()` / `get_mode_playlists()` — music
- `get_routines()` — routine configs
- `get_pihole_stats()` — Pi-hole DNS stats (queries, blocked, blocklist size)
- `query_db(sql)` — read-only SQLite queries (SELECT only)

**Registered in:** `.mcp.json` (project root — Claude Code auto-loads this on startup and prompts to approve on first run)

### Hooks (`.claude/settings.json`)

Hooks fire automatically after file edits:

- **Python files (`backend/**/*.py`):** Runs `ruff check --fix` after every edit. Auto-fixes imports, style, and common issues.
- **Frontend files (`frontend-svelte/src/**/*.{js,svelte}`):** Runs ESLint after every edit.

### Skills

| Skill | Command | Purpose |
|-------|---------|---------|
| `home-hub-dev` | `/home-hub-dev` | Start dev environment, verify Hue/Sonos connectivity |
| `api-audit` | `/api-audit` | Smoke test all API endpoints via MCP |
| `ui-audit` | `/ui-audit` | Playwright screenshots at desktop + mobile widths |
| `project-spec` | `/project-spec` | Create or update `docs/PROJECT_SPEC.md` |

---

## Architecture

### Current

```
Browser / Phone (PWA)
        |  WebSocket + REST
        v
   FastAPI Backend (port 8000, async)
   ├── HueService (v1/phue2) ──────> Hue Bridge (basic control, 1s polling)
   ├── HueV2Service (CLIP v2) ─────> Hue Bridge (native scenes, effects)
   ├── SonosService (SoCo/UPnP) ──> Sonos Era 100 (2s polling)
   ├── TTSService (edge-tts) ──────> generates MP3 → Sonos plays URL
   ├── AutomationEngine ───────────> time + activity → light state
   │   └── mode-change callbacks ──> MusicMapper, MLLogger, [future: GameDayEngine]
   ├── ML Services (planned) ──────> see docs/ML_SPEC.md
   │   ├── AudioClassifier ────────> YAMNet audio scene classification
   │   ├── BehavioralPredictor ────> LightGBM mode prediction
   │   ├── LightingLearner ────────> adaptive per-light preferences
   │   ├── CameraService ──────────> MediaPipe presence/posture (opt-in)
   │   └── MusicBandit ────────────> Thompson sampling playlist selection
   ├── MusicMapper ────────────────> mode change → smart Sonos auto-play
   ├── ScreenSyncService (mss) ────> dominant screen color → bedroom lamp
   ├── Scheduler ──────────────────> morning routine, evening wind-down
   ├── LibraryImportService ───────> Apple Music XML → taste profile
   ├── RecommendationService ──────> Last.fm + iTunes → discovery feed
   ├── PiholeService (httpx) ──────> Pi-hole v6 API (stats, DNS, blocklists)
   ├── WebSocketManager ───────────> bidirectional real-time sync
   ├── SQLite (aiosqlite + SQLAlchemy async)
   └── Serves SvelteKit static build from frontend-svelte/build/

Pi-hole (Docker container, host networking, same machine)
   └── pihole/pihole:latest ───────> DNS on :53, admin on :8080

PC Agent (standalone processes, same machine)
   ├── activity_detector.py ───────> psutil → POST /api/automation/activity
   └── ambient_monitor.py ────────> PyAudio RMS → POST /api/automation/activity
```

### Target (upcoming work)

Key additions beyond current:
- **EventLogger** — Middleware that intercepts all state changes → event tables (for learning)
- **LearningEngine** — Separate process, reads events, generates rules, exposes `/predict` API
- **FauxmoService** — WeMo emulation for Alexa voice control (local UPnP)
- **GameDayEngine** — ESPN polling, play detection, celebration orchestration
- **Database migration** — SQLite → PostgreSQL (Supabase) as event volume grows
- See `docs/PROJECT_SPEC.md` for full target architecture diagram

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.8+, FastAPI, uvicorn, async/await |
| Database | SQLite via aiosqlite + SQLAlchemy 2.0 async ORM |
| Frontend | SvelteKit 2 + Svelte 4, Threlte 7 (Three.js), Vite 5, Svelte writable stores |
| Hue v1 | phue2 library (imports as `from phue import Bridge`) |
| Hue v2 | CLIP API via httpx (self-signed cert, `verify=False`) |
| Sonos | SoCo library (UPnP, zero-auth, SSDP discovery) |
| TTS | edge-tts (Microsoft neural voices), gTTS fallback |
| Screen Sync | mss (screen capture), RGB→HSB conversion |
| PC Agent | psutil (process detection), PyAudio (ambient noise) |
| Config | pydantic-settings, python-dotenv |
| Timezone | America/Indiana/Indianapolis |

---

## Backend Service Guide

- **`backend/main.py`** — App lifespan initializes all services, registers routes, starts background tasks (Hue polling, Sonos polling, automation loop, scheduler). WebSocket at `/ws`.
- **`hue_service.py`** — v1/phue2: basic light control + 1s polling. Broadcasts changes via WebSocket.
- **`hue_v2_service.py`** — CLIP API v2/httpx: native bridge scenes and dynamic effects. Maintains v1↔v2 UUID mapping cache.
- **`sonos_service.py`** — SoCo wrapper: playback control, favorites, duck-and-resume snapshot.
- **`tts_service.py`** — edge-tts → MP3 → Sonos play_uri. Duck-and-resume wraps playback.
- **`automation_engine.py`** — Background loop (60s). Combines time rules + activity reports → per-light state with per-light variation (not uniform). Supports CT (mirek) and HSB color modes. `EFFECT_AUTO_MAP` auto-activates effects by mode+time; weather effects (rain→candle, storm→sparkle) overlay when no mode effect is set. Effects are only stopped/restarted on change — same-effect cycles are skipped to preserve brightness base. `MODE_TRANSITION_TIME` gives each mode a different transition feel. Scene drift applies subtle variation during long sessions. Mode → scene overrides (from DB) checked before hardcoded states. `register_on_mode_change` callbacks. Manual overrides have 4h auto-timeout. Mode priority: gaming (5) > social (4) > watching (3) > working (2) > idle (1) > away (0).
- **`weather_service.py`** — NWS API (api.weather.gov) with 5-minute cache. Returns temp, feels_like, description, humidity, wind, icon, sunrise/sunset. Active severe weather alerts checked every 2 min — alert descriptions override stale observation data so automation catches storms immediately. Sunrise/sunset from sunrise-sunset.org (24h cache). No API key needed.
- **`music_mapper.py`** — Maps activity modes to Sonos favorites (persisted to SQLite). On mode change: auto-plays if idle, broadcasts `music_suggestion` if busy. Registered as mode-change callback.
- **`presence_service.py`** — WiFi presence detection. Pings iPhone (192.168.1.148) every 30s. 10-min timeout → gradual departure fade → Sonos pause → away. Arrival → choreographed light wave (L3→L4→L1→L2, 1s staggers) + adaptive TTS greeting + weather-aware effect + music auto-play. ARP fallback for DHCP IP changes. Config in `app_settings` key `presence_config`.
- **`screen_sync.py`** — mss screen capture → dominant color → bedroom lamp. EMA smoothing (α=0.3), 2.5s interval, 2s transitions. Auto-starts in watching/gaming mode.
- **`scheduler.py`** — Async cron scheduler (no external deps). Drives morning + wind-down routines.
- **`morning_routine.py`** — Fetches weather (via shared WeatherService) + commute (Google Maps), generates TTS, plays on Sonos.
- **`winddown_routine.py`** — Evening relax: activates candlelight + dims lights + lowers volume + brief TTS.
- **`library_import_service.py`** — Parses Apple Music/iTunes XML (plistlib). Extracts artist play counts, genre distribution.
- **`recommendation_service.py`** — Last.fm `artist.getSimilar` for discovery. Caches in DB (30-day TTL). Mode-specific seed selection with cross-mode dedup.
- **`pihole_service.py`** — Pi-hole v6 API client with session-based auth. Stats (60s cache), DNS host CRUD, blocklist CRUD. Auto-re-authenticates on 401.
- **`pc_agent/activity_detector.py`** — Standalone. psutil process detection every 5s. Gaming, working, watching, sleeping, away detection. POSTs to `/api/automation/activity`.
- **`pc_agent/ambient_monitor.py`** — Standalone. Blue Yeti RMS measurement. Party detection: sustained noise >2min + no game = "social". Never records audio.

---

## Frontend

- **`src/lib/stores/{lights,sonos,automation,music,connection,activity}.js`** — Svelte writable stores. WebSocket dispatches into them. `activity.js` tracks user idle state (60s timeout for auto-hide).
- **`src/lib/ws.js`** — Shared WebSocket client + reconnect logic. Dispatches messages into the stores.
- **`src/routes/+layout.svelte`** — App shell: ModeBackground + ModeOverlay + FloatingNav + NowPlayingChip + ErrorToast. No sidebar.
- **`src/routes/+page.svelte`** — Home: SonosCard strip + QuickActions + widget grid (Mode, Weather, Lights, Scenes, Routines) + MusicSuggestionToast.
- **`src/routes/music/+page.svelte`** — Taste profile, mode→playlist mapping, discovery feed. Glass card grid.
- **`src/routes/settings/+page.svelte`** — Device status, automation config, light schedule, mode brightness sliders, mode→scene overrides, morning/wind-down routine config, TTS test. Glass card grid.
- **`src/lib/backgrounds/PixelScene.svelte`** — Gaming: code-drawn pixel art landscape (480×270 scaled 4×) with parallax, sprites, stars.
- **`src/lib/backgrounds/ParallaxScene.svelte`** — Working: JS-driven parallax scroll of PNG sprite sheets + code-drawn sky gradient (weather/time aware).
- **`src/lib/backgrounds/AuroraScene.svelte`** — Relax: simplex noise aurora borealis curtains with stars and treeline.
- **`src/lib/backgrounds/MoonScene.svelte`** — Sleeping: Threlte/Three.js (GLSL sky shader, moon orbit, star field, city silhouette with flickering windows).
- **`src/lib/backgrounds/GenerativeCanvas.svelte`** — Fallback (idle, social, watching, etc.): three-layer system (gradient mesh blobs + flow-field particles + geometric overlay). 15fps cap.
- **`src/lib/backgrounds/layer-config.js`** — Per-mode layer definitions for ParallaxScene (PNG paths, scroll speeds, heights).
- **`src/lib/backgrounds/scene-utils.js`** — Shared drawing utilities (stars, rain, snow, canvas init).
- **`src/lib/components/ModeBackground.svelte`** — Routes `$automation.mode` to the appropriate scene component.
- **`src/lib/components/SceneBrowser.svelte`** — Categorized scene browser with tabs (functional, cozy, moody, vibrant, nature, entertainment, social, effects, bridge scenes).
- **`src/lib/components/WeatherCard.svelte`** — NWS weather conditions widget with SVG weather icons.
- **`src/lib/theme.js`** — MODE_CONFIG with generative params + Lucide icon names, LIGHT_COLOR_PRESETS, LIGHT_CT_PRESETS, SCENE_CATEGORIES, VIBE_COLORS.
- Typography: Bebas Neue (display/mode) + Source Sans 3 (body). Lucide SVG icons.
- Built frontend served by FastAPI via `/{path:path}` catch-all (must come after all API routes).

---

## WebSocket Protocol

**Endpoint:** `ws://host:8000/ws`
All messages: JSON with `type` + `data` fields.

### Server → Client

| Type | Trigger | Data |
|------|---------|------|
| `connection_status` | On connect | `{hue: bool, sonos: bool, build_id: str}` |
| `mode_update` | On connect + mode change | `{mode, source, manual_override}` |
| `light_update` | Polling detects change | `{light_id, name, on, bri, hue, sat, reachable}` |
| `sonos_update` | Polling detects change | `{state, track, artist, album, art_url, volume, mute}` |
| `music_auto_played` | Auto-play triggered | `{mode, title}` |
| `music_suggestion` | Sonos busy, playlist available | `{mode, title, message}` |
| `presence_update` | Presence state change | `{state, phone_ip, last_seen, away_since, away_duration_minutes}` |

`build_id` is the short git SHA the backend computed at startup. The frontend (`frontend-svelte/src/lib/ws.js`) stashes the first one it sees per page session and calls `window.location.reload()` if a later `connection_status` reports a different value — that's how the kiosk dashboard auto-refreshes after `scripts/deploy.sh` restarts the backend, no F5 required.

### Client → Server

| Type | Data |
|------|------|
| `light_command` | `{light_id, on?, bri?, hue?, sat?, transitiontime?}` |
| `sonos_command` | `{action: play\|pause\|next\|previous\|volume, volume?}` |

---

## API Routes

**Prefix:** All REST endpoints use `/api/`. Health is at `/health` (no prefix). All routes must be registered BEFORE the `/{path:path}` frontend catch-all. See route files in `backend/api/routes/` for full endpoint details.

| Group | Prefix | Key endpoints |
|-------|--------|---------------|
| System | `/health`, `/ws` | Health check, WebSocket sync |
| Lights | `/api/lights` | CRUD per-light state (on, bri, hue, sat, ct), bulk set |
| Scenes | `/api/scenes` | Curated + custom + bridge scenes, activate, effects (per-light or all) |
| Weather | `/api/weather` | Current conditions (5-min cache, NWS), alerts |
| Automation | `/api/automation` | Mode status/override, schedule, brightness multipliers, activity reports, social styles, screen sync, mode→scene overrides |
| Sonos | `/api/sonos` | Transport (play/pause/next/prev), volume, TTS, favorites |
| Music | `/api/music` | Mode→playlist mapping, Apple Music import, taste profile, recommendations + feedback |
| Routines | `/api/routines` | Morning + winddown config, toggle, test |
| Pi-hole | `/api/pihole` | Stats, top-blocked, DNS host CRUD, blocklist CRUD |

### Future Routes (do not implement until planned)
- `/api/actions/` — Quick actions (movie_night, bedtime, leaving, game_day)
- `/api/learning/` — Learning engine rules, patterns, predictions
- `/api/events/` — Activity/playback history
- `/api/gameday/` — Game state, schedule, celebrations
- `/api/widgets/` — External app widget status

---

## Developer Patterns

> These patterns are the conventions for this codebase. Follow them precisely when adding features.

### Pattern 1: Mode-Change Callback

```python
# Define async callback in your service
async def on_mode_change(mode: str) -> None:
    if mode == "gaming":
        await do_something()

# Register in main.py lifespan, AFTER automation engine is created
automation.register_on_mode_change(my_service.on_mode_change)
```
Callbacks are async, called in registration order. Keep fast — dispatch long work as background tasks.

### Pattern 2: New Backend Service

```python
# backend/services/new_service.py
class NewService:
    def __init__(self, ws_manager, hue_service=None):
        self._ws_manager = ws_manager
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        try:
            self._connected = True
            logger.info("NewService connected")
        except Exception as e:
            logger.error("NewService connection failed: %s", e, exc_info=True)
            self._connected = False

    async def poll_state_loop(self, ws_manager) -> None:
        while True:
            try:
                # detect changes, broadcast via ws_manager
                pass
            except Exception as e:
                logger.error("NewService poll error: %s", e)
            await asyncio.sleep(2)

    async def close(self) -> None:
        self._connected = False
```

Register in `main.py` lifespan: create → connect → `app.state.new_service = service` → add to `tasks` list → register mode-change callback.

### Pattern 3: API Route

```python
# backend/api/routes/new_feature.py
from fastapi import APIRouter, Request
router = APIRouter(prefix="/api/new-feature", tags=["new-feature"])

@router.get("/")
async def get_status(request: Request):
    service = request.app.state.new_service
    return {"status": "ok", "data": service.get_state()}

@router.post("/{id}/action")
async def perform_action(id: str, body: RequestModel, request: Request):
    result = await request.app.state.new_service.do_action(id, body)
    return {"status": "ok" if result else "error"}
```

- Prefix: `/api/{domain}/`
- GET for reads, POST for actions, PUT for updates, DELETE for removals
- Always return `{"status": "ok"}` or `{"status": "error", "detail": "..."}`
- Register in `main.py` BEFORE the `/{path:path}` frontend catch-all

### Pattern 4: WebSocket Broadcast

```python
# Server → Client
await self._ws_manager.broadcast("event_type", {"key": "value"})

# Client → Server (in main.py websocket handler)
elif data["type"] == "new_command":
    result = await app.state.new_service.handle(data["data"])
    await ws_manager.broadcast("new_command_result", result)
```
Naming: `{domain}_{event}` — e.g., `light_update`, `game_update`.

### Pattern 5: Activity Detector (standalone script)

```python
# backend/services/pc_agent/new_detector.py
SERVER_URL = "http://192.168.1.30:8000"  # Laptop IP

def detect_mode() -> str:
    return "idle"  # or gaming, working, etc.

def main():
    while True:
        mode = detect_mode()
        requests.post(f"{SERVER_URL}/api/automation/activity",
                      json={"mode": mode, "source": "new_detector"}, timeout=5)
        time.sleep(15)
```
Mode priority enforced by engine: gaming (5) > social (4) > watching (3) > working (2) > idle (1) > away (0).

### Pattern 6: Scheduled Routine

```python
from backend.services.scheduler import ScheduledTask

task = ScheduledTask(
    name="new_routine",
    hour=12, minute=0,
    weekdays=[0, 1, 2, 3, 4],  # 0=Monday
    callback=routine_service.execute,
    enabled=True,
)
scheduler.add_task(task)
```
Routine config persisted in `app_settings` table (key: `{routine_name}_config`). Expose test endpoint: `POST /api/routines/{name}/test`.

### Pattern 7: New Automation Mode Light States

Define per-light states in `automation_engine.py` → `ACTIVITY_LIGHT_STATES`. Each light should have **different** brightness/color to create spatial depth — avoid `_uniform()` for new modes:

```python
"new_mode": {
    "day": {
        "1": {"on": True, "bri": 200, "ct": 220},     # Living room: bright neutral
        "2": {"on": True, "bri": 254, "ct": 200},     # Bedroom/desk: max brightness
        "3": {"on": True, "bri": 170, "ct": 233},     # Kitchen front: fill
        "4": {"on": True, "bri": 150, "ct": 250},     # Kitchen back: warmer fill
    },
    "evening": { ... },  # Warmer ct values, reduced brightness
    "night": { ... },     # Dim ambient fill + adequate desk light
}
```
Engine checks `mode_scene_overrides` table first (user-mapped Hue scenes), then falls through to `ACTIVITY_LIGHT_STATES`. Mode brightness multipliers applied on top. `MODE_TRANSITION_TIME` controls transition speed per mode.

### Pattern 8: Event Logging (future)

```python
event_logger = request.app.state.event_logger
await event_logger.log_mode_change(mode="gaming", previous="idle", source="manual")
await event_logger.log_light_adjustment(light_id="1", state={"on": True, "bri": 200}, trigger="manual")
await event_logger.log_interaction(action="quick_action", detail={"name": "movie_night"}, page="home")
```
Every POST/PUT that changes state should log. EventLogger buffers + flushes every 5s or 50 items.

### Pattern 9: App Settings (SQLite persistence)

All service config is stored in the `app_settings` key-value table:

```python
# Save
await save_setting(db, "my_service_config", {"key": "value"})

# Load
config = await load_setting(db, "my_service_config")
```
Keys in use: `morning_routine_config`, `winddown_routine_config`, `time_schedule_config`, `mode_brightness_config`, `presence_config`.

---

## Automation Modes

| Mode | Detection | Lighting Strategy | Notes |
|------|-----------|-------------------|-------|
| `gaming` | LeagueofLegends.exe, javaw.exe (OSRS), 20+ game processes | Per-light: neutral fill + blue/purple accents on peripherals, warm bias on desk lamp (sync overrides). Night: deep blue ambient glow. | Screen sync on L2, glisten effect eve/night |
| `working` | windowsterminal, powershell, pwsh, bash, claude, code, cursor, devenv, JetBrains IDEs, modern terminals (wezterm, alacritty, etc.) | ct-mode clean whites, desk-dominant. Night: L2 desk bri=130/2700K + L1 ambient bri=60/2270K + kitchen OFF. | IES 1:3 monitor-ambient contrast |
| `watching` | VLC, Plex, Stremio, media players | Projector-friendly: warm throughout (no D65), dim, L2 as soft bias from across the room. Kitchen OFF evening+. | Screen sync on L2 — projector on HDMI from dev PC, so mss captures the projected frames |
| `social` | Blue Yeti ambient noise >2min + no game | Sub-modes: color_cycle, club, rave, fire_and_ice | Party lighting |
| `relax` | Manual override | HSB warm amber gradient. Kitchen L3/L4 free to diverge for depth. | opal (day), candle (eve), fire (night) |
| `cooking` | Manual override | L3+L4 paired peak (3500K for accurate food colors), L1 warm ambient, L2 dim | 1s snap transition |
| `sleeping` | 10:30pm + 15min idle → psutil | 10-min fade → off | Also pauses media |
| `idle` | No process detected | Falls through to time-based rules | |
| `away` | Win32 idle >10min | Falls through to time-based | |

**Mode priority (engine enforces):** gaming (5) > social (4) > watching/cooking (3) > working (2) > idle (1) > away (0)

**Mode transition speeds:** gaming 0.5s (snappy), working 2s, watching 3s (cinematic), cooking 1s (snappy), relax 4s (gentle), sleeping 5s (gradual)

**Scene drift:** After 30min in **relax** mode, subtle random perturbation (±15 bri, ±1500 hue) with 10s transitions prevents staleness. Scoped to relax only — functional modes (working, gaming, watching, cooking) need stable, paired values; independent per-light drift there made L3/L4 look randomly unequal.

**Kitchen pair rule:** L3 (kitchen front) and L4 (kitchen back) must match `bri` and on/off in functional modes (working, gaming, watching, cooking). Free to diverge in relax/social.

**Post-sunset warmth cutoff:** No CT-mode light drops below `ct=333` (~3000K) in evening/night. Watching's D65 bias is a daytime-only exception.

**Colorspace exclusivity:** `hue_service.set_light` forces `sat=0` and drops stray `hue` when `ct` is in the payload, and emits them in `sat`-before-`ct` JSON order. The bridge is order-sensitive; `{ct, sat: 0}` leaves residual tint, `{sat: 0, ct}` produces clean white. Prevents the "greenish bedroom" bug from a stale bridge state or a LightingPreferenceLearner overlay that mixed colorspaces.

**Effect reconciliation:** `_reconcile_effect` runs AFTER `_apply_state` so the bridge has the target brightness before the old effect stops. Stopping an effect first would pop brightness to 100% (the old mode-switch flash). 0.5s guard separates stop and start.

**In-flight window:** `hue_service` tracks per-light deadlines; the polling loop skips broadcasting `light_update` for a light that was just written until transition time + 0.5s buffer elapses. Prevents the UI from bouncing back to stale mid-transition bridge reads.

**Mode → scene overrides:** Any mode+time slot can be mapped to a Hue bridge scene or curated preset via `mode_scene_overrides` table, overriding the default `ACTIVITY_LIGHT_STATES`.

---

## Dynamic Effects (Hue v2)

| Effect | Description |
|--------|-------------|
| `candle` | Warm flickering candle |
| `fire` | Shifting oranges and reds |
| `sparkle` | Random bright flashes |
| `prism` | Slow color cycling |
| `glisten` | Gentle shimmering glow |
| `opal` | Soft pastel transitions |

Activated via `POST /api/scenes/effects/{name}` (all lights) or `POST /api/scenes/effects/{name}/light/{id}` (single light).

**EFFECT_AUTO_MAP** (auto-activated by mode+time):
- `relax`: opal (day), candle (evening), fire (night)
- `watching`: none (day), glisten (evening), glisten (night)
- `gaming`, `working`, `cooking`: none (all periods) — gaming previously ran glisten but it competed with screen sync and read as "RGB gamer strip"

**Weather effect fallback:** When a mode has no auto-effect, weather can overlay one — rain→candle, thunderstorm→sparkle, snow→opal (evening/night only, except sparkle fires any time). Effects are only stopped/restarted when switching to a different effect — same-effect cycles are skipped to preserve the brightness base on the bridge.

---

## Database Schema (Current Tables)

| Table | Purpose |
|-------|---------|
| `app_settings` | Key-value JSON config store (key, value, updated_at) |
| `scenes` | User-created light presets (name, light_states JSON) |
| `mode_playlists` | Mode → Sonos favorite mapping (mode, favorite_title, vibe_tags, auto_play, priority) |
| `music_artists` | Library import data (name, genres, play_count, similar_artists) |
| `taste_profile` | Aggregated music profile singleton (genre_distribution, top_artists, mode_genre_map) |
| `recommendations` | Music recommendations (artist, track, preview_url, source_mode, status) |
| `recommendation_feedback` | Like/dismiss actions on recommendations |
| `mode_scene_overrides` | Mode+time → Hue scene mapping (mode, time_period, scene_id, scene_source, scene_name) |

**Event tables (Phase 3, live):** `activity_events`, `light_adjustments`, `sonos_playback_events`, `scene_activations`, `learned_rules`. See `docs/PROJECT_SPEC.md` for full schema.

**Data retention:** 90-day rolling window; older data aggregated into weekly summaries.

---

## Configuration Reference

### .env Variables

```
APP_ENV=development
LOCAL_IP=192.168.1.30          # Server LAN IP — Sonos fetches TTS MP3 from here
HUE_BRIDGE_IP=192.168.1.50
HUE_USERNAME=<bridge token>    # From bridge pairing
TTS_VOICE=en-US-GuyNeural
TTS_VOLUME=10
LOG_LEVEL=INFO
# OPENWEATHER_API_KEY=...        # No longer needed (switched to NWS API)
GOOGLE_MAPS_API_KEY=...
HOME_ADDRESS=...
WORK_ADDRESS=...
MORNING_ROUTINE_HOUR=6
MORNING_ROUTINE_MINUTE=40
MORNING_VOLUME=10
LASTFM_API_KEY=...
SONOS_IP=192.168.1.157         # Optional; auto-discovers via SSDP if unset
```

### SQLite Persisted Settings (`app_settings` table)

| Key | Content |
|-----|---------|
| `morning_routine_config` | `{hour, minute, enabled, volume}` |
| `winddown_routine_config` | `{hour, minute, enabled, volume, candlelight, weekdays_only}` |
| `time_schedule_config` | `{weekday: {wake_hour, ramp_start_hour, ...}, weekend: {...}}` |
| `mode_brightness_config` | `{gaming: 1.0, working: 1.0, watching: 0.8, ...}` (range 0.3–1.5) |
| `presence_config` | `{enabled, phone_ip, phone_mac, ping_interval, away_timeout, short_absence_threshold, arrival_volume, departure_fade_seconds}` |

---

## Network Devices

| Device | IP | Notes |
|--------|----|-------|
| **Latitude 7420 (production)** | **192.168.1.210** | **Ubuntu 24.04 LTS, `homehub-dashboard`. Runs FastAPI backend + ambient monitor as systemd user services, Firefox kiosk via GNOME autostart, Pi-hole v6 Docker container (DNS on :53, admin on :8080). Always-on 24/7. Static IP via NetworkManager.** |
| Windows desktop (dev) | 192.168.1.30 | Code editing, `git push`, local testing. Runs PC activity detector via Task Scheduler (hidden `pythonw.exe`, `--server http://192.168.1.210:8000`). Claude Code's MCP server uses `HOME_HUB_URL` Windows user env var to point at the Latitude. |
| Hue Bridge | 192.168.1.50 | Self-signed SSL cert |
| Sonos Era 100 | 192.168.1.157 | "Bedroom" speaker. `SONOS_IP` hardcoded in `.env` on the Latitude to defeat cold-boot SSDP discovery race. |
| Android Tablet | 192.168.1.209 | Kiosk display (blank page issue deferred) |

---

## Roadmap

| Phase | Timeline | Focus |
|-------|----------|-------|
| **Phase 1: Core Fix & Foundation** | ✓ Complete | Gradual evening transitions, vibe tagging, event logging tables |
| **Phase 2: Dashboard Redesign** | ✓ Complete | Themed mode backgrounds (pixel art gaming, parallax city working, aurora relax, 3D moon sleeping), glass cards, floating nav, weather widget, 20 curated scenes, CT support, custom scene CRUD + builder UI, effect auto-activation, plant app widget, kiosk auto-reload on backend deploys |
| **Phase 3: Intelligence & Voice** | June 2026 | Simple rule engine from events, Fauxmo Alexa integration, override pattern analysis, nudge system |
| **Phase 4: Game Day** | July–August 2026 | ESPN API, GameDay page, celebration orchestration, pixel art field, pre-game mode |
| **Phase 5: Polish & Expand** | September 2026+ | Custom Alexa Skill, Apple Music API, full autopilot, bar app widget |

---

## Technical Limitations

- **Hue bridge SSL** — Self-signed cert; httpx calls require `verify=False`. Cannot be changed.
- **Sonos TTS** — Requires server's LAN IP (`LOCAL_IP` in .env); Sonos fetches the MP3 over the network. `localhost` won't work.
- **Sonos Apple Music** — SoCo can play tracks by URI (v0.26.0+) but cannot browse the catalog. Catalog browsing requires $99/year Apple Music API.
- **phue2 import quirk** — pip package is `phue2` but imports as `from phue import Bridge`.
- **Screen sync Windows-only** — mss capture only works on Windows. Will break if server moves to headless Linux.
- **edge-tts requires internet** — Falls back to gTTS (also internet). No offline TTS currently.
- **SQLite concurrency** — Single-writer. Event logging at high frequency may need batching. Migration to PostgreSQL (Supabase) planned.
- **Indiana timezone** — `America/Indiana/Indianapolis` has unique DST rules. All scheduling must use this timezone explicitly.
- **Fauxmo device limits** — Simple on/off per virtual device. Complex voice commands require the custom Alexa Skill (Phase 3).
- **1080p landscape primary** — Animated backgrounds designed for this. Must degrade gracefully on mobile.
- **Android tablet blank page** — Known issue, deferred.

## Non-Goals

- Not a multi-user platform (no auth, no user accounts)
- Not a generic smart home hub (Hue + Sonos only, by design)
- Not replacing Home Assistant or HomeKit
- Not a general sports tracker (Game Day is Colts-specific)
- Not a music streaming service (Sonos/Apple Music handle playback; Home Hub orchestrates)

