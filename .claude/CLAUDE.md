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
   ├── ML Services (shipped) ──────> see docs/ML_SPEC.md
   │   ├── AudioClassifier ────────> YAMNet audio scene classification
   │   ├── BehavioralPredictor ────> LightGBM mode prediction
   │   ├── LightingLearner ────────> adaptive per-light preferences
   │   ├── CameraService ──────────> MediaPipe presence (opt-in) + adaptive lux → brightness multiplier (working/relax)
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
- **`automation_engine.py`** — Background loop (60s). Combines time rules + activity reports → per-light state with per-light variation (not uniform). Supports CT (mirek) and HSB color modes. `EFFECT_AUTO_MAP` auto-activates effects by mode+time; weather effects (rain→candle, storm→sparkle) overlay when no mode effect is set. Effects are only stopped/restarted on change — same-effect cycles are skipped to preserve brightness base. `MODE_TRANSITION_TIME` gives each mode a different transition feel. Scene drift applies subtle variation during long sessions. Mode → scene overrides (from DB) checked before hardcoded states. `register_on_mode_change` callbacks. Manual overrides have 4h auto-timeout. Mode priority: gaming (5) > social (4) > watching (3) > working (2) > idle (1) > away (0). Late-night rescue (23:00+, no override, mode ∈ {working, idle}, Sonos not playing) auto-applies relax to cover the edge after winddown's override expires.
- **`weather_service.py`** — NWS API (api.weather.gov) with 5-minute cache. Returns temp, feels_like, description, humidity, wind, icon, sunrise/sunset. Active severe weather alerts checked every 2 min — alert descriptions override stale observation data so automation catches storms immediately. Sunrise/sunset from sunrise-sunset.org (24h cache). No API key needed.
- **`music_mapper.py`** — Maps activity modes to Sonos favorites (persisted to SQLite). On mode change: auto-plays if idle, broadcasts `music_suggestion` if busy. Registered as mode-change callback.
- **`presence_service.py`** — WiFi presence detection. Pings iPhone (192.168.1.148) every 30s. 10-min timeout → gradual departure fade → Sonos pause → away. Arrival → choreographed light wave (L3→L4→L1→L2, 1s staggers) + adaptive TTS greeting + weather-aware effect + music auto-play. ARP fallback for DHCP IP changes. Config in `app_settings` key `presence_config`.
- **`screen_sync.py`** — mss screen capture → dominant color → bedroom lamp. EMA smoothing (α=0.3), 2.5s interval, 2s transitions. Auto-starts in watching/gaming mode.
- **`scheduler.py`** — Async cron scheduler (no external deps). Drives morning + wind-down routines.
- **`morning_routine.py`** — Fetches weather (via shared WeatherService) + commute (Google Maps), generates TTS, plays on Sonos.
- **`winddown_routine.py`** — Evening relax: activates candlelight + dims lights + lowers volume + brief TTS. Current config fires at 22:00 weekdays. `_ACTIVE_MODES = {gaming, watching, social}` is what *delays* the routine (via `skip_if_active`) — "working" is intentionally NOT in the set so late-night dev sessions don't block it. TTS says "Unwinding for the night..." (not "Wind-down", which neural TTS mispronounces as moving air).
- **`library_import_service.py`** — Parses Apple Music/iTunes XML (plistlib). Extracts artist play counts, genre distribution.
- **`recommendation_service.py`** — Last.fm `artist.getSimilar` for discovery. Caches in DB (30-day TTL). Mode-specific seed selection with cross-mode dedup.
- **`pihole_service.py`** — Pi-hole v6 API client with session-based auth. Stats (60s cache), DNS host CRUD, blocklist CRUD. Auto-re-authenticates on 401.
- **`camera_service.py`** — MediaPipe face + pose detection on the Latitude webcam, opt-in via `camera_enabled`. Polls every 2s at 640×480 (bumped from 320×240 on 2026-04-19 for more pixel detail — **lux calibration must be re-run after any resolution change**, since `gray.mean()` varies with pixel count). Face (full-range BlazeFace, `MIN_FACE_CONFIDENCE=0.2`) runs first (~15ms); if it misses, pose landmarker (lite) runs (~60ms) — "present" is declared if ≥3 of {nose, left/right shoulder, left/right hip} have visibility ≥0.5. Either hit wins. `detection_source` (`"face"` | `"pose"` | `None`) flows through `/api/camera/status`, the `camera_update` WebSocket event, and the ML logger. 7 absent frames across both paths (~14s) → `report_activity(mode="away", source="camera")`. Pose fallback exists because the corner-position Latitude puts Anthony in deep profile during working sessions, where face scores unreliably. **Zone mapping (expose-only)**: every detection also produces a `zone` label (`desk` if detected center-X < `ZONE_DESK_THRESHOLD=0.40` of frame width, else `bed`). Source is face bbox center when face fires; pose torso midline (average of visible shoulder `.x`) as fallback. A 15-second hysteresis (`ZONE_HYSTERESIS_SECONDS`) gates commits — a new candidate must hold steadily across polls before replacing `self._last_zone`, which absorbs transient detections when Anthony walks through the accent-chair region. Brief absence preserves the committed zone. Zone is published via `/api/camera/status` (as `zone` + `candidate_zone`), the WS `camera_update` event, and ML logger factors (as `zone` for committed + `frame_zone` for raw per-poll). No automation behavior consumes zone yet — signal-only, actuation rule is a follow-up. `GET /api/camera/snapshot?annotate=true` returns a JPEG annotated with face box + torso skeleton + vertical zone-threshold line + DESK/BED labels + lux readout; shares the capture handle with the poll loop via `_cap_lock`. Same frames produce an EMA-smoothed ambient lux reading (α=0.3, ~20s to 95%) that feeds `AutomationEngine._apply_lux_multiplier` for working/relax modes (±15% bri swing, anchored at the user's calibrated baseline). `POST /api/camera/calibrate` picks a fixed exposure in `[-12, 0]` and records `baseline_lux` using a poll-cadence measurement (burst reads inflate the baseline because auto-gain winds up high — don't remove the sleeps). Pauses during sleeping mode (camera LED off).
- **`transit_lighting_service.py`** — Brightens the navigation path (L1 living-room + L3/L4 kitchen) when Anthony steps out of the bedroom with his phone still on Wi-Fi. Trigger: camera absent ≥10s + presence="home" + current mode ∈ {working, gaming, watching, relax}. Applies a per-light override (bri=120 / 80 daytime, 60 / 40 at late-night ≥23:00) via `AutomationEngine.apply_transit_override`, which populates `_transit_light_overrides` (the reconciliation loop skips these lights the same way it skips `_manual_light_overrides`). Reverts via `clear_transit_override` → `_apply_mode` when camera sees him again for ≥2s, or on hard 10-minute timeout, or when phone leaves Wi-Fi, or when mode exits the trigger set. L2 (bedroom bias lamp) stays on the current mode's state throughout. No WebSocket surface, no event-log entry — intentionally invisible UX.
- **`pc_agent/activity_detector.py`** — Standalone. psutil process detection every 5s. Gaming, working, watching, sleeping, away detection. POSTs to `/api/automation/activity`. `GAME_PROCESSES` in `game_list.py` is intentionally narrow — `javaw.exe` was removed because it matched every JVM process (JetBrains IDEs, Gradle, build tools), silently forcing "gaming" over working since gaming has priority 5. OSRS is still caught via `runelite.exe` / `osclient.exe`. **Media classification requires foreground context** (fixed 2026-04-19, commit eb6b2ea) — a running MEDIA_PROCESSES entry alone no longer returns "watching"; the foreground window must be the media app, OR a browser with a watching-title keyword, OR there must be no work tools running. This prevents lingering Stremio background services (`stremio service.exe`, `stremio-runtime.exe`) from trumping foreground VS Code after the main window is closed.
- **`pc_agent/ambient_monitor.py`** — Standalone. Blue Yeti RMS + YAMNet classification. RMS produces only the "idle" edge (60s of below-threshold quiet) and the heartbeat. **Social is YAMNet-gated** — requires `speech_multiple` class at ≥0.80 confidence sustained 30s (see `MODE_THRESHOLDS` in `backend/services/ml/audio_classifier.py`). Requires `--classifier --active` flags; in `--shadow` or default mode, social is manual-only. RMS alone cannot distinguish conversation from HVAC + typing, and previously latched social on any sustained background noise. Never records audio.

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
| Camera | `/api/camera` | Status (detection, detection_source, lux, baseline, multiplier, pose_available), snapshot (JPEG, optional annotation), enable/disable, calibrate exposure |

### Future Routes (do not implement until planned)
- `/api/actions/` — Quick actions (movie_night, bedtime, leaving, game_day)
- `/api/learning/` — Learning engine rules, patterns, predictions
- `/api/events/` — Activity/playback history
- `/api/gameday/` — Game state, schedule, celebrations
- `/api/widgets/` — External app widget status

---

## Developer Patterns

Conventions for this codebase — only what's non-obvious. Standard Python/FastAPI/asyncio scaffolding is assumed.

**Mode-change callback.** `automation.register_on_mode_change(async_fn)` in `main.py` lifespan after the engine is created. Callbacks run async in registration order — keep them fast; dispatch long work as background tasks.

**New backend service.** Shape: `_connected: bool` + `connected` property, `async connect()` / `async poll_state_loop(ws_manager)` / `async close()`. Wire-up in `main.py` lifespan: create → `await service.connect()` → `app.state.new_service = service` → add poll loop to `tasks` list → register mode-change callback if relevant.

**API route.** Prefix `/api/{domain}/`. GET reads, POST actions, PUT updates, DELETE removals. Return `{"status": "ok"}` or `{"status": "error", "detail": "..."}`. Register in `main.py` **before** the `/{path:path}` frontend catch-all.

**WebSocket.** `await self._ws_manager.broadcast("{domain}_{event}", {...})` — e.g. `light_update`, `game_update`. Handle client→server messages in `main.py` websocket handler.

**Activity detector (standalone script).** POST `{mode, source}` to `/api/automation/activity`. Engine enforces priority: gaming (5) > social (4) > watching (3) > working (2) > idle (1) > away (0).

**Scheduled routine.** Build a `ScheduledTask` (from `backend.services.scheduler`) with `name, hour, minute, weekdays, callback, enabled` and call `scheduler.add_task(task)`. Persist config in `app_settings` under `{routine_name}_config`. Expose `POST /api/routines/{name}/test`.

**New automation mode.** Add per-light states in `automation_engine.py` → `ACTIVITY_LIGHT_STATES` under `day` / `evening` / `night` (+ `late_night` if needed). Each light should differ (spatial depth) — avoid `_uniform()`. Engine checks `mode_scene_overrides` DB table first, then falls through to `ACTIVITY_LIGHT_STATES`. Mode brightness multipliers applied on top; `MODE_TRANSITION_TIME` controls per-mode speed.

**Event logging (future).** `event_logger.log_mode_change(...)`, `.log_light_adjustment(...)`, `.log_interaction(...)` on every POST/PUT that changes state. Buffered, flushes every 5s or 50 items.

**App settings (SQLite).** `await save_setting(db, key, value_dict)` / `await load_setting(db, key)`. Keys in use: `morning_routine_config`, `winddown_routine_config`, `time_schedule_config`, `mode_brightness_config`, `presence_config`, `camera_enabled`, `lux_calibration_config`.

---

## Automation Modes

| Mode | Detection | Lighting Strategy | Notes |
|------|-----------|-------------------|-------|
| `gaming` | LeagueofLegends.exe, RuneLite, 20+ specific game binaries (NOT `javaw.exe` — too generic, used by JetBrains IDEs etc.) | Per-light: neutral fill + blue/purple accents on peripherals, warm bias on desk lamp (sync overrides). Night: deep blue ambient glow. | Screen sync on L2, glisten effect eve/night |
| `working` | windowsterminal, powershell, pwsh, bash, claude, code, cursor, devenv, JetBrains IDEs, modern terminals (wezterm, alacritty, etc.) | ct-mode clean whites, desk-dominant. Night: L2 desk bri=130/2700K + L1 ambient bri=60/2270K + kitchen OFF. | IES 1:3 monitor-ambient contrast |
| `watching` | VLC, Plex, Stremio, media players | Projector-friendly: warm throughout (no D65), dim, L2 as soft bias from across the room. Kitchen OFF evening+. | Screen sync on L2 — projector on HDMI from dev PC, so mss captures the projected frames |
| `social` | YAMNet `speech_multiple` ≥0.80 confidence for 30s (requires supervisor `--active`) or manual override | "Velvet Speakeasy" — single static palette: L1 dusty rose (statement), L2 cognac amber, L3/L4 matched burnt-orange pair. Dim but visible for faces and drinks. | No effect (static) — saturation does the work. 1s snap |
| `relax` | Manual override | "Moss & Candlelight" biophilic: L1/L2 warm ember/honey, L3/L4 muted moss/sage (foliage-shadow canopy). Kitchen free to diverge; pair the sage values by day, deepen through evening. Late-night ("Moss & Ember") after 23:00: deeper ember + hunter-green shadow. | opal (day, all lights), candle (eve) / fire (night + late_night) scoped to **L1/L2 only** so moss pendants stay static |
| `cooking` | Manual override | L3+L4 paired peak (3500K for accurate food colors), L1 warm ambient, L2 dim | 1s snap transition |
| `sleeping` | 10:30pm + 15min idle → psutil | Apply dim initial (bri=20 deep ember) BEFORE stopping the active effect to prevent the bridge's brightness-to-100% pop, then fade. Manual trigger: ~24s fade to off. Auto-detected: 10-min gradual stepwise fade. | Persistent override — no 4h timeout; must be cleared manually. Also pauses media |
| `idle` | No process detected | Falls through to time-based rules | |
| `away` | Win32 idle >10min | Falls through to time-based | |

**Mode priority (engine enforces):** gaming (5) > social (4) > watching/cooking (3) > working (2) > idle (1) > away (0). `report_activity` applies this as a universal guard: a lower-priority mode from a *different* source can't displace a fresh higher-priority current mode; same-source updates always go through. `SOURCE_STALE_SECONDS = 300` — an owning source that hasn't reported in 5 min is considered dead and yields to lower-priority reports, preventing stale-lock.

**Mode transition speeds:** gaming 0.5s (snappy), working 2s, watching 3s (cinematic), cooking 1s (snappy), relax 4s (gentle), sleeping 5s (gradual)

**Scene drift:** After 30min in **relax** mode, subtle random perturbation (±15 bri, ±1500 hue) with 10s transitions prevents staleness. Scoped to relax only — functional modes (working, gaming, watching, cooking) need stable, paired values; independent per-light drift there made L3/L4 look randomly unequal.

**Kitchen pair rule:** L3 (kitchen front) and L4 (kitchen back) must match `bri` and on/off in functional modes (working, gaming, watching, cooking). Free to diverge in relax/social.

**Post-sunset warmth cutoff:** No CT-mode light drops below `ct=333` (~3000K) in evening/night. Watching's D65 bias is a daytime-only exception.

**Colorspace exclusivity:** `hue_service.set_light` forces `sat=0` and drops stray `hue` when `ct` is in the payload, and emits them in `sat`-before-`ct` JSON order. The bridge is order-sensitive; `{ct, sat: 0}` leaves residual tint, `{sat: 0, ct}` produces clean white. Prevents the "greenish bedroom" bug from a stale bridge state or a LightingPreferenceLearner overlay that mixed colorspaces.

**Effect reconciliation:** `_reconcile_effect` runs AFTER `_apply_state` so the bridge has the target brightness before the old effect stops. Stopping an effect first would pop brightness to 100% (the old mode-switch flash). 0.5s guard separates stop and start.

**In-flight window:** `hue_service` tracks per-light deadlines; the polling loop skips broadcasting `light_update` for a light that was just written until transition time + 0.5s buffer elapses. Prevents the UI from bouncing back to stale mid-transition bridge reads.

**Mode → scene overrides:** Any mode+time slot can be mapped to a Hue bridge scene or curated preset via `mode_scene_overrides` table, overriding the default `ACTIVITY_LIGHT_STATES`.

**Late-night autopilot cascade:** Three layers stack so no manual override is needed at night:

1. **22:00 weekdays** — `winddown_routine` fires, sets manual override to `relax`, lowers Sonos volume, plays brief TTS. Skipped only if actively in gaming/watching/social (not working — dev sessions shouldn't block it).
2. **22:00–06:00** — `ConfidenceFusion` applies a `LATE_NIGHT_PROCESS_WEIGHT_FACTOR = 0.6` multiplier to the process-detection lane. Stale dev tools left open no longer lock the fused mode to "working"; behavioral + rule + audio lanes carry more weight.
3. **23:00+ (late_night period), no override, no Sonos playback, detected mode ∈ {working, idle}** — `run_loop` auto-applies `relax` as a safety net for when winddown's 4h override expires. Real gaming/watching/social/sleeping are respected.

Fusion override threshold is `0.92` (was 0.98) — 0.98 was so tight it never tripped in practice. 80% agreement is the safety net.

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

**EFFECT_AUTO_MAP** entries are `{"effect": name, "lights": [...] | None}` — `lights=None` means all mapped lights, a list scopes the effect to specific v1 light IDs so some bulbs stay static while others flicker. Weather-driven fallbacks still pass as bare strings (applied to all lights).
- `relax`: opal day (all), candle evening and fire night + late_night — **candle/fire scoped to L1/L2 only** so the moss-shadow kitchen pendants (L3/L4) stay on their static sage/green color
- `watching`: none (day), glisten (evening, all), glisten (night, all)
- `social`: no entry — Velvet Speakeasy is intentionally static, no cycling
- `gaming`, `working`, `cooking`: none (all periods) — gaming previously ran glisten but it competed with screen sync and read as "RGB gamer strip"

**Time periods:** `_get_time_period()` returns `day` / `evening` / `night` / `late_night`. The `late_night` slot runs from `DaySchedule.late_night_start_hour` (default 23) until `wake_hour` the next day. Only relax defines a `late_night` state ("Moss & Ember" cave/den variant); other modes fall back to their `night` state via `_resolve_activity_state`.

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
| `time_schedule_config` | `{weekday: {wake_hour, ramp_start_hour, ..., late_night_start_hour}, weekend: {...}}` |
| `mode_brightness_config` | `{gaming: 1.0, working: 1.0, watching: 0.8, ...}` (range 0.3–1.5) |
| `presence_config` | `{enabled, phone_ip, phone_mac, ping_interval, away_timeout, short_absence_threshold, arrival_volume, departure_fade_seconds}` |
| `camera_enabled` | `{enabled: bool}` — opt-in toggle for the MediaPipe camera service |
| `lux_calibration_config` | `{exposure_value, target_lux, baseline_lux, calibrated_at}` — fixed-exposure calibration + baseline for adaptive brightness (working/relax). Written by `POST /api/camera/calibrate`. |

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

