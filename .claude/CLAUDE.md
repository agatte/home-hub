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
- `get_live_state()` — **one-shot snapshot**: mode+lights+screen-sync+camera+presence+weather+multipliers; use first for any "what's happening" question
- `get_state_history(minutes=30)` — timeline from event tables: mode transitions, light adjustments, scene activations, sonos events
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
- **`automation_engine.py`** — Background loop (60s). Combines time rules + activity reports → per-light state with per-light variation (not uniform). Supports CT (mirek) and HSB color modes. `EFFECT_AUTO_MAP` auto-activates effects by mode+time; weather effects (rain→candle, storm→sparkle) overlay when no mode effect is set. Same-effect cycles are skipped to preserve brightness base. `MODE_TRANSITION_TIME` per mode; scene drift adds subtle variation during long relax sessions. `mode_scene_overrides` DB table checked before hardcoded states. `register_on_mode_change` callbacks. Manual overrides have 4h auto-timeout. Mode priority: gaming (5) > social (4) > watching (3) > working (2) > idle (1) > away (0). Late-night rescue (23:00+, no override, mode ∈ {working, idle}, Sonos not playing) auto-applies relax. `_evaluate_zone_posture_rule` runs each tick: auto-applies `relax` when camera reports `zone=bed + posture=reclined` ≥5min (gates: no active override, mode ∈ {idle, away, working}, evening or weekend afternoon). Gated by `ZONE_POSTURE_RULE_APPLY` env var — default False logs `ml_decisions` in shadow mode. Projector-from-bed stays `upright` so this rule doesn't fire then.
- **`weather_service.py`** — NWS API (api.weather.gov) with 5-minute cache. Returns temp, feels_like, description, humidity, wind, icon, sunrise/sunset. Active severe weather alerts checked every 2 min — alert descriptions override stale observation data so automation catches storms immediately. Sunrise/sunset from sunrise-sunset.org (24h cache). No API key needed.
- **`music_mapper.py`** — Maps activity modes to Sonos favorites (persisted to SQLite). On mode change: auto-plays if idle, broadcasts `music_suggestion` if busy. Registered as mode-change callback.
- **`presence_service.py`** — Two-signal WiFi presence; ICMP retired (iOS gates ICMP in WiFi power-save → phantom `away` events). (1) **iPhone Shortcut webhooks (primary)** — iOS Personal Automations POST `/api/automation/presence/arrived` and `/departed` on home-WiFi connect/disconnect, authed via `X-Presence-Token` header against `PRESENCE_WEBHOOK_TOKEN` in `.env`. Arrival bypasses ARP debounce and `short_absence_threshold`; departure bypasses the manual-override guard. Routed through `on_shortcut_arrival` / `on_shortcut_departure` with `force_ceremony=True`. (2) **Active ARP probing (backup)** — `arping -c 1 -w 2 -I <iface>` every 20s; survives iOS power-save. Falls back to ICMP only on non-Linux or if `arping` isn't installed. Away timeout 180s. Away→home via ARP requires 2 consecutive probes (debounce); departing→home fires immediately. **Flap filters**: `/departed` webhooks are debounced (fade sequence only starts if no `/arrived` lands in the window); `_arrival_sequence` has a source-aware flap gate (Shortcut threshold tighter than ARP's, since iOS power-save can hide the phone 3–5 min while physically home). `_away_since` is back-dated to `_last_seen` so `duration_away` reflects true absence, not commit time. Arrival ceremony: choreographed light wave (L3→L4→L1→L2, 1s staggers) + TTS + weather-aware effect + music auto-play. MAC→IP re-lookup via `ip neigh` after 3 misses. Config in `app_settings` key `presence_config`; Latitude needs `iputils-arping`. Known iOS caveats handled: `/departed` often fails with `-1001` as WiFi dies (ARP catches it ~180s later); iOS walk-outs can fire `/departed`+`/arrived` in the same second (flap gate cancels); WiFi rejoin after walk-in lags 10–60s. **Also a fusion voter** (weight 0.18) — `_report_to_fusion` piggybacks on `_broadcast_state` to keep the lane fresh; `away` at conf 0.95, `home` at a low-conf `idle` (0.30) so the lane shows up without drowning process/camera.
- **`screen_sync.py`** — mss screen capture → dominant color → bedroom lamp. EMA smoothing (α=0.3), 2.5s interval, 2s transitions. Auto-starts in watching/gaming mode. Per-mode brightness caps in `MODE_MAX_BRIGHTNESS` (gaming=240, watching=80, default=80); overrides in `MODE_ZONE_MAX_BRIGHTNESS` keyed by `(mode, zone)` or `(mode, zone, posture)` — 3-tuple wins over 2-tuple. Current: `("watching","desk")=180` (desk-YouTube not capped at projector-safe dim), `("watching","bed","reclined")=25` (projector + lying back), `("watching","bed","upright")=60` (projector + sitting up). `apply_color(..., zone=..., posture=...)` takes optional camera zone/posture pulled in the route handler.
- **`scheduler.py`** — Async cron scheduler (no external deps). Drives morning + wind-down routines.
- **`morning_routine.py`** — Fetches weather (via shared WeatherService) + commute (Google Maps), generates TTS, plays on Sonos.
- **`winddown_routine.py`** — Evening relax at 22:00 weekdays: candlelight + dims + lowers volume + TTS. `_ACTIVE_MODES = {gaming, watching, social}` *delays* via `skip_if_active` — working is intentionally excluded so late-night dev doesn't block it.
- **`library_import_service.py`** — Parses Apple Music/iTunes XML; extracts artist play counts + genre distribution.
- **`recommendation_service.py`** — Last.fm `artist.getSimilar` discovery. 30-day DB cache, mode-specific seeds with cross-mode dedup.
- **`pihole_service.py`** — Pi-hole v6 API client with session-based auth. Stats (60s cache), DNS host CRUD, blocklist CRUD. Auto-re-authenticates on 401.
- **`camera_service.py`** — MediaPipe face + pose detection on the Latitude webcam, opt-in via `camera_enabled`. Polls every 2s at 640×480 — **lux calibration must be re-run after any resolution change** since `gray.mean()` varies with pixel count. Face (full-range BlazeFace, `MIN_FACE_CONFIDENCE=0.15`) runs first (~15ms); if it misses, pose landmarker (lite) runs (~60ms) — "present" is declared if ≥3 of {nose, left/right shoulder, left/right hip} have visibility ≥0.5. `detection_source` (`"face"`/`"pose"`/`None`) flows through `/api/camera/status`, the `camera_update` WS event, and the ML logger. 15 absent frames (~30s) → `report_activity(mode="away", source="camera")` — thresholds loosened for low-light bed scenarios (old 0.2/7-frame values flapped). Pose fallback exists because corner-position Latitude puts Anthony in deep profile during working, where face scores unreliably. **Zone** (`desk` if center-X < `ZONE_DESK_THRESHOLD=0.40`, else `bed`): face bbox center, or pose shoulder midline fallback. 15-second hysteresis gates commits; brief absence preserves the committed zone. **Posture** (`upright`/`reclined`): pose path derives from `mean(hip_y) - mean(shoulder_y)`, delta ≥ `POSTURE_UPRIGHT_MIN_DELTA=0.12` is upright. Face-only sessions emit `posture=None`; hysteresis preserves last commit. Both fields published on `/api/camera/status` (`zone`/`candidate_zone`, `posture`/`candidate_posture`), WS `camera_update`, and ML logger factors. **Actuation**: `_apply_zone_overlay` has two branches — (a) `zone=desk + watching` lifts L2 (lift-only), (b) `zone=bed + posture=reclined` (any mode except sleeping) at evening/night/late_night lowers L1/L2 (lower-only) — bed+reclined is a physical fact, not a mode label, so a watching→working flip while still in bed shouldn't snap L2 to working's bright ambient. Screen-sync cap likewise keyed by `(mode, zone, posture)` when available. `zone=bed + posture=upright` (football/sitting up) takes a middle cap. Face-only sessions (posture=None) fall through to baseline. `GET /api/camera/snapshot?annotate=true` returns a JPEG with face box + skeleton + zone line + lux readout; shares the capture handle with the poll loop via `_cap_lock`. Same frames produce an EMA-smoothed ambient lux reading (α=0.3) that feeds `AutomationEngine._apply_lux_multiplier` for working/relax (±15% bri swing, anchored at calibrated baseline). `POST /api/camera/calibrate` picks a fixed exposure in `[-12, 0]` and records `baseline_lux` — uses poll-cadence measurement, don't remove the sleeps (burst reads inflate baseline via auto-gain). Pauses during sleeping mode (camera LED off).
- **`transit_lighting_service.py`** — Brightens the navigation path (L1 + L3/L4) when Anthony leaves the bedroom with phone still on Wi-Fi. Trigger: camera absent ≥10s + presence=home + mode ∈ {working, gaming, watching, relax}. Applies a per-light override via `AutomationEngine.apply_transit_override` (populates `_transit_light_overrides`, skipped by reconciliation like `_manual_light_overrides`). Reverts when camera sees him again ≥2s, hard 10-min timeout, phone leaves Wi-Fi, or mode exits the trigger set. L2 stays on current mode's state. No WebSocket surface, no event-log entry — intentionally invisible UX.
- **`pc_agent/activity_detector.py`** — Standalone. psutil process detection every 5s → POST `/api/automation/activity`. `GAME_PROCESSES` in `game_list.py` is intentionally narrow — `javaw.exe` is excluded because it matches every JVM process (JetBrains IDEs, Gradle), which would silently force gaming over working. OSRS is caught via `runelite.exe` / `osclient.exe`. **Media classification requires foreground context**: a running MEDIA_PROCESSES entry alone does not return "watching" — the foreground window must be the media app, or a browser with a watching-title keyword, or no work tools running. Prevents lingering Stremio background services from trumping foreground VS Code.
- **`pc_agent/ambient_monitor.py`** — Standalone. Blue Yeti RMS + YAMNet classification. RMS produces only the "idle" edge (60s of below-threshold quiet) and the heartbeat. **Social is YAMNet-gated** — requires `speech_multiple` class at ≥0.80 confidence sustained 30s (see `MODE_THRESHOLDS` in `backend/services/ml/audio_classifier.py`). Requires `--classifier --active` flags; in `--shadow` or default mode, social is manual-only. RMS alone cannot distinguish conversation from HVAC + typing, and previously latched social on any sustained background noise. Never records audio.

---

## Frontend

- **`src/lib/stores/{lights,sonos,automation,music,connection,activity}.js`** — Svelte writable stores. WebSocket dispatches into them. `activity.js` tracks user idle state (60s timeout for auto-hide).
- **`src/lib/ws.js`** — Shared WebSocket client + reconnect logic. Dispatches messages into the stores.
- **`src/routes/+layout.svelte`** — App shell: ModeBackground + ModeOverlay + FloatingNav + NowPlayingChip + ErrorToast. No sidebar.
- **`src/routes/+page.svelte`** — Home: SonosCard strip + QuickActions + widget grid (Mode, Weather, Lights, Scenes, Routines) + MusicSuggestionToast.
- **`src/routes/music/+page.svelte`** — Taste profile, mode→playlist mapping, discovery feed. Glass card grid.
- **`src/routes/settings/+page.svelte`** — Device status, automation config, light schedule, mode brightness sliders, mode→scene overrides, morning/wind-down routine config, TTS test. Glass card grid.
- **`src/lib/backgrounds/`** — Mode-specific scenes: `PixelScene` (gaming, code-drawn pixel art), `ParallaxScene` (working, scrolling PNG sprite sheets + weather/time-aware sky), `AuroraScene` (relax, simplex-noise aurora), `MoonScene` (sleeping, Threlte/Three.js), `GenerativeCanvas` (fallback: blobs + flow-field particles, 15fps). `layer-config.js` holds per-mode PNG layer defs; `scene-utils.js` shared drawing helpers.
- **`src/lib/components/ModeBackground.svelte`** — Routes `$automation.mode` to the appropriate scene.
- **`src/lib/components/{SceneBrowser,WeatherCard}.svelte`** — Scene browser (tabbed) and NWS weather widget.
- **`src/lib/theme.js`** — MODE_CONFIG, LIGHT_COLOR_PRESETS, LIGHT_CT_PRESETS, SCENE_CATEGORIES, VIBE_COLORS.
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
| Automation | `/api/automation` | Mode status/override, schedule, brightness multipliers, activity reports, social styles, screen sync, mode→scene overrides, presence status/config, presence Shortcut webhooks (`/presence/arrived`, `/presence/departed` — `X-Presence-Token` auth) |
| Sonos | `/api/sonos` | Transport (play/pause/next/prev), volume, TTS, favorites |
| Music | `/api/music` | Mode→playlist mapping, Apple Music import, taste profile, recommendations + feedback |
| Routines | `/api/routines` | Morning + winddown config, toggle, test |
| Pi-hole | `/api/pihole` | Stats, top-blocked, DNS host CRUD, blocklist CRUD |
| Camera | `/api/camera` | Status (detection, detection_source, lux, baseline, multiplier, pose_available, zone, posture), snapshot (JPEG, optional annotation), enable/disable, calibrate exposure |

### Future Routes (do not implement until planned)
- `/api/actions/` — Quick actions (movie_night, bedtime, leaving, game_day)
- `/api/learning/` — Learning engine rules, patterns, predictions
- `/api/events/` — Activity/playback history
- `/api/gameday/` — Game state, schedule, celebrations
- `/api/widgets/` — External app widget status

---

## Developer Patterns

Conventions for this codebase — only what's non-obvious. Standard Python/FastAPI/asyncio scaffolding is assumed.

**Mode-change callback.** `automation.register_on_mode_change(async_fn)` in `main.py` lifespan. Runs async in registration order — keep callbacks fast; dispatch long work as background tasks.

**New backend service.** Shape: `_connected` + `connected` property, `async connect()` / `poll_state_loop(ws_manager)` / `close()`. Wire up in `main.py` lifespan: create → await connect → `app.state.x = service` → add poll loop to `tasks` → register mode-change callback if relevant.

**API route.** Prefix `/api/{domain}/`. Return `{"status": "ok"}` or `{"status": "error", "detail": "..."}`. Register in `main.py` **before** the `/{path:path}` frontend catch-all.

**WebSocket.** `await self._ws_manager.broadcast("{domain}_{event}", {...})`. Client→server handled in `main.py` websocket handler.

**Activity detector.** POST `{mode, source, factors?}` to `/api/automation/activity` — `factors` is optional sub-signal detail surfaced to the analytics constellation. Engine enforces priority.

**Scheduled routine.** Build a `ScheduledTask` (from `backend.services.scheduler`) and call `scheduler.add_task(task)`. Persist config in `app_settings` under `{routine_name}_config`. Expose `POST /api/routines/{name}/test`.

**New automation mode.** Add per-light states in `automation_engine.py` → `ACTIVITY_LIGHT_STATES` under `day`/`evening`/`night` (+ `late_night` if needed). Each light should differ (spatial depth) — avoid `_uniform()`. Engine checks `mode_scene_overrides` DB table first. Mode brightness multipliers apply on top.

**App settings (SQLite).** `await save_setting(db, key, value_dict)` / `await load_setting(db, key)`. Known keys: `morning_routine_config`, `winddown_routine_config`, `time_schedule_config`, `mode_brightness_config`, `watching_posture_config`, `presence_config`, `camera_enabled`, `lux_calibration_config`.

---

## Automation Modes

| Mode | Detection | Lighting Strategy |
|------|-----------|-------------------|
| `gaming` | Specific game binaries in `game_list.py` (NOT `javaw.exe` — matches JetBrains IDEs) | Neutral fill + blue/purple peripheral accents, warm desk-lamp bias. Night: deep blue ambient. Screen sync on L2, glisten effect eve/night |
| `working` | Terminals + IDEs (powershell, pwsh, bash, claude, code, cursor, devenv, JetBrains, wezterm, alacritty) | ct-mode clean whites, desk-dominant. IES 1:3 monitor-ambient contrast. Night: L2 130/2700K + L1 60/2270K + kitchen OFF |
| `watching` | Media players (VLC, Plex, Stremio) — foreground-gated | Projector default: warm, dim, L2 as soft bias. Kitchen OFF evening+. **Zone/posture-aware**: `zone=desk` → L2 lifts to 160/110/70 (day/eve/night) + sync cap 180; `zone=bed + posture=reclined` at evening/night/late_night → L1/L2 drop further (45/18, 25/8, 15/5) + sync cap 25; `zone=bed + posture=upright` → sync cap 60 (football/sitting up) |
| `social` | YAMNet `speech_multiple` ≥0.80 for 30s (supervisor `--active`), or manual | "Velvet Speakeasy" static: L1 dusty rose, L2 cognac amber, L3/L4 matched burnt-orange. Saturation does the work, no effect. 1s snap |
| `relax` | Manual override | "Moss & Candlelight": L1/L2 warm ember/honey, L3/L4 moss/sage (pendants stay static). Late-night "Moss & Ember": deeper ember + hunter-green. opal day / candle eve / fire night — candle/fire scoped to L1/L2 only |
| `cooking` | Manual override | L3+L4 paired peak 3500K (accurate food colors), L1 warm, L2 dim. 1s snap |
| `sleeping` | 22:30 + 15min idle (psutil) | Dim initial (bri=20 ember) BEFORE stopping the active effect to prevent 100% pop, then fade. Manual: 24s fade off. Auto: 10-min stepwise. Persistent override — no 4h timeout. Pauses media |
| `idle` | No process detected | Falls through to time-based rules |
| `away` | Win32 idle >10min | Falls through to time-based rules |

**Mode priority:** `report_activity` guards against lower-priority cross-source displacement of a fresh higher-priority mode; same-source updates always pass. `SOURCE_STALE_SECONDS=300` — an owning source that hasn't reported in 5 min yields to lower-priority reports (prevents stale-lock).

**Mode transition speeds:** gaming 0.5s (snappy), working 2s, watching 3s (cinematic), cooking 1s (snappy), relax 4s (gentle), sleeping 5s (gradual)

**Scene drift:** After 30min in **relax** mode, subtle random perturbation (±15 bri, ±1500 hue) with 10s transitions prevents staleness. Scoped to relax only — functional modes (working, gaming, watching, cooking) need stable, paired values; independent per-light drift there made L3/L4 look randomly unequal.

**Kitchen pair rule:** L3 (kitchen front) and L4 (kitchen back) must match `bri` and on/off in functional modes (working, gaming, watching, cooking). Free to diverge in relax/social.

**Post-sunset warmth cutoff:** No CT-mode light drops below `ct=333` (~3000K) in evening/night. Watching's D65 bias is a daytime-only exception.

**Colorspace exclusivity:** `hue_service.set_light` forces `sat=0`, drops stray `hue` when `ct` is in the payload, and emits `sat` before `ct` in JSON order (bridge is order-sensitive; `{ct, sat:0}` leaves tint). Prevents the "greenish bedroom" bug from mixed colorspaces.

**Effect reconciliation:** `_reconcile_effect` runs AFTER `_apply_state` so brightness is already at target before the old effect stops (otherwise brightness pops to 100%). 0.5s guard between stop and start.

**In-flight window:** `hue_service` tracks per-light write deadlines; polling skips broadcasting `light_update` until transition time + 0.5s elapses. Prevents UI bouncing back to stale mid-transition reads.

**Mode → scene overrides:** Any mode+time slot can be mapped to a Hue bridge scene or curated preset via `mode_scene_overrides` table, overriding the default `ACTIVITY_LIGHT_STATES`.

**Late-night autopilot cascade:** Three stacked layers so no manual override is needed at night. (1) **22:00 weekdays** — `winddown_routine` sets manual override to `relax`, lowers Sonos volume, plays brief TTS. Skipped only if in gaming/watching/social (not working). (2) **22:00–06:00** — `ConfidenceFusion` applies `LATE_NIGHT_PROCESS_WEIGHT_FACTOR=0.6` to the process-detection lane so stale dev tools don't lock the fused mode to "working". (3) **23:00+, no override, no Sonos playback, mode ∈ {working, idle}** — `run_loop` auto-applies `relax` as a safety net for when winddown's 4h override expires. Real gaming/watching/social/sleeping are respected. Fusion override threshold `0.92`.

---

## Dynamic Effects (Hue v2)

Available effects: `candle` (warm flicker), `fire` (shifting oranges/reds), `sparkle` (bright flashes), `prism` (slow color cycle), `glisten` (shimmer), `opal` (soft pastel). Activate via `POST /api/scenes/effects/{name}` (all lights) or `.../effects/{name}/light/{id}` (single).

**EFFECT_AUTO_MAP** entries are `{"effect": name, "lights": [...] | None}` — `lights=None` applies to all, a list scopes to specific v1 IDs. Mappings: relax → opal day / candle eve / fire night+late_night, candle/fire scoped to L1/L2 only so moss pendants stay static; watching → glisten eve/night; social, gaming, working, cooking → none (gaming's glisten competed with screen sync).

**Time periods:** `_get_time_period()` returns `day`/`evening`/`night`/`late_night`. `late_night` runs from `DaySchedule.late_night_start_hour` (default 23) until `wake_hour`. Only relax defines a `late_night` state; other modes fall back to `night`.

**Weather effect fallback:** When a mode has no auto-effect, weather overlays one — rain→candle, thunderstorm→sparkle, snow→opal (evening/night only, sparkle any time). Same-effect cycles skipped to preserve the bridge's brightness base.

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
GOOGLE_MAPS_API_KEY=...
HOME_ADDRESS=...
WORK_ADDRESS=...
MORNING_ROUTINE_HOUR=6
MORNING_ROUTINE_MINUTE=40
MORNING_VOLUME=10
LASTFM_API_KEY=...
SONOS_IP=192.168.1.157         # Optional; auto-discovers via SSDP if unset
PRESENCE_WEBHOOK_TOKEN=<urlsafe random>  # Shared secret for iPhone Shortcut presence webhooks; unset disables the /api/automation/presence/{arrived,departed} endpoints
ZONE_POSTURE_RULE_APPLY=false  # Zone+posture→relax actuation. Default false: logs shadow ml_decisions only. Flip to true after reviewing shadow data.
PLANT_APP_ALLOW_INSECURE=false # Escape hatch for plain-HTTP Plant App API. Default false rejects http:// at boot. Setting true emits a WARNING on every login. Never enable in normal operation.
```

### SQLite Persisted Settings (`app_settings` table)

| Key | Content |
|-----|---------|
| `morning_routine_config` | `{hour, minute, enabled, volume}` |
| `winddown_routine_config` | `{hour, minute, enabled, volume, candlelight, weekdays_only}` |
| `time_schedule_config` | `{weekday: {wake_hour, ramp_start_hour, ..., late_night_start_hour}, weekend: {...}}` |
| `mode_brightness_config` | `{gaming: 1.0, working: 1.0, watching: 0.8, ...}` (range 0.3–1.5) |
| `presence_config` | `{enabled, phone_ip, phone_mac, probe_interval, away_timeout, short_absence_threshold, arrival_volume, departure_fade_seconds}` — defaults `probe_interval=20, away_timeout=180` post-ARP switch. `ping_interval` key is auto-promoted to `probe_interval` on load for back-compat. |
| `watching_posture_config` | `{reclined_sync_cap, reclined_l1_night, upright_sync_cap}` — settings-page sliders for projector-in-bed brightness. Loaded at boot + live-patched via `PUT /api/automation/watching-posture`. |
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
| Phases 1–2 | ✓ Complete | Core foundation + dashboard redesign — see `docs/PROJECT_SPEC.md` |
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
- **SQLite concurrency** — Single-writer. Event logging at high frequency may need batching.
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

