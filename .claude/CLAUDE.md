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
- **Voice control** — Alexa via Fauxmo (7 WeMos) + Custom Skill (`command center` via Lambda+Tunnel)
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

Use the `/deploy-home` skill — it commits/pushes/SSHes/spawns deploy-verifier end-to-end. Direct CLI shorthand: `ssh homehub "cd ~/home-hub && ./scripts/deploy.sh"` (passwordless via `id_ed25519_homehub` + `~/.ssh/config` Host alias).

`scripts/deploy.sh` does `git pull --ff-only`, conditionally reinstalls deps / rebuilds frontend / restarts `home-hub.service`, then health-checks `/health`. Backend restarts emit a new `build_id` on `connection_status`, the kiosk WebSocket reloads within ~1s.

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

### Hooks (`.claude/settings.json` + `.claude/hooks/`)

- **PostToolUse Edit/Write** (`post_edit_ruff.py`) — `backend/**/*.py` → `python -m ruff check --fix` (ruff via module, not on PATH). No frontend lint hook (`frontend-svelte` has no ESLint).
- **SessionStart** (`session_start_homehub.py`) — injects mode/source/override + anomaly-only fields via `additionalContext`. Healthy systems stay terse.
- **PostToolUse Bash** (`post_git_push.py`) — after a real `git push`, nudges `/deploy-home`.
- **PreToolUse Bash** (`pre_commit_lighting_curator.py`) — blocks `git commit` touching `light_state_calculator.py` / `scenes.py` / `celebration_orchestrator.py` + a design identifier (`ACTIVITY_LIGHT_STATES`, `EFFECT_AUTO_MAP`, `SCENE_PRESETS`, `SEQUENCES`, …) unless the message contains `[curator-reviewed]`. Override: spawn `lighting-curator`, address, re-commit.
- **PreToolUse Bash** (`pre_push_pr_review.py`) — blocks `git push` of Python/SvelteKit diffs unless PASS markers (`<git-dir>/.pr-review-{backend,frontend}-ok` = HEAD SHA) exist. Bypass: `SKIP_PR_REVIEW=1`. Docs/config-only pushes skip.

### Slash commands + subagents

Commands: `/home-hub-dev`, `/api-audit`, `/deploy-home`, `/ui-audit`, `/project-spec`, `/checkback-loop`.

Subagents (`~/.claude/agents/`) — full trigger map in `docs/AGENT_STRATEGY.md` Part 5. Active fleet: `homehub-verifier`, `deploy-verifier`, `lighting-curator`, `lighting-shopper`, `gameday-preflight`, `gameday-postmortem`, `ml-model-evaluator`, `homehub-investigator`, `pr-review-backend`, `pr-review-frontend`, `doc-drift-checker`, `doc-curator`, `roadmap-advisor`, `backup-verifier`.

### Ambient verification loop

`/checkback-loop` invokes `/loop` (dynamic) against `~/.claude/runbooks/homehub-checkbacks.md` — hourly anomaly sweep + dated one-shot decisions. Writes per-fire markdown blocks to `~/.claude/runbooks/digests/YYYY-MM-DD.md`. MCP-down → `[skipped]` + 600s back-off. Warn/error blocks fire `PushNotification` (Windows toast + phone push if Remote Control connected); ok/skipped/specialist-self-writing blocks stay silent. Auto-starts via `home-hub-loop.cmd`.

Parallel `/watcher-loop` (separate session) polls the digests every 600s. Warn/error blocks without `**Diagnosis (` get a `homehub-investigator` subagent spawned (per-anomaly playbook in `~/.claude/runbooks/homehub-watcher.md`); root-cause diagnosis appended inline. Investigation-only — never mutates state.

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
   │   └── mode-change callbacks ──> MusicMapper, AmbientMonitor, MLLogger, CameraService, BarApp
   ├── ML Services (shipped) ──────> see docs/ML_SPEC.md
   │   ├── AudioClassifier ────────> YAMNet audio scene classification
   │   ├── BehavioralPredictor ────> LightGBM mode prediction
   │   ├── LightingLearner ────────> adaptive per-light preferences
   │   ├── CameraService ──────────> MediaPipe presence (opt-in) + adaptive lux → brightness multiplier (working/relax)
   │   └── MusicBandit ────────────> Thompson sampling playlist selection
   ├── MusicMapper ────────────────> mode change → smart Sonos auto-play
   ├── ScreenSyncService (mss) ────> dominant screen color → bedroom lamp
   ├── Scheduler ──────────────────> morning routine + nightly maintenance
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
- **`automation_engine.py`** — 60s background loop. Time rules + activity reports → per-light state (per-light variation, not uniform). Supports CT + HSB. Drives effects via `EFFECT_AUTO_MAP` + weather overlays. `mode_scene_overrides` consulted before hardcoded states. `register_on_mode_change` callbacks. Manual overrides have 4h auto-timeout (sleeping exempt). Mode priority: gameday(6) > gaming(5) > social(4) > watching(3) > working(2) > idle(1) > sleeping(0). `report_activity` force-resends the per-light dedup cache only on real mode changes; same-source heartbeats ride the cache. Late-night rescue + zone+posture rule + attendance vetoes live here. `_evaluate_zone_posture_rule` env-gated by `ZONE_POSTURE_RULE_APPLY`.
- **`weather_service.py`** — NWS API, 5-min cache. Returns temp/feels_like/description/humidity/wind/icon/sunrise/sunset. Severe alerts polled every 2 min — descriptions override stale observations so storms surface immediately. No API key.
- **`music_mapper.py`** — Maps activity modes to Sonos favorites (persisted to SQLite). On mode change: auto-plays if idle, broadcasts `music_suggestion` if busy. Registered as mode-change callback.
- **`screen_sync.py`** — mss capture → dominant color → bedroom lamp. EMA smoothed, ~2.5s. Auto-starts in watching/gaming. Per-mode caps in `MODE_MAX_BRIGHTNESS`; zone/posture overrides via `MODE_ZONE_MAX_BRIGHTNESS` (3-tuple wins). `apply_color(zone=, posture=)` from route handler.
- **`scheduler.py`** — Async cron scheduler (no external deps). Drives morning routine + nightly ML retrain / journal / fusion-tuning / retention sweep.
- **`morning_routine.py`** — Fetches weather (via shared WeatherService) + commute (Google Maps), generates TTS, plays on Sonos.
- **`library_import_service.py`** — Parses Apple Music/iTunes XML; extracts artist play counts + genre distribution.
- **`recommendation_service.py`** — Last.fm `artist.getSimilar` discovery. 30-day DB cache, mode-specific seeds with cross-mode dedup.
- **`pihole_service.py`** — Pi-hole v6 API client with session-based auth. Stats (60s cache), DNS host CRUD, blocklist CRUD. Auto-re-authenticates on 401.
- **`camera_service.py`** — MediaPipe face+pose on the Latitude webcam, opt-in via `camera_enabled`. 2s polls @ 640×480 — **re-run lux calibration after any resolution change**. Face (BlazeFace) first; pose fallback declares present when ≥3 torso landmarks pass visibility. `detection_source` ∈ {face, pose, None}. ~30s absence → `report_activity(idle, "camera")`. **Zone** (`desk`/`bed`) + **posture** (`upright`/`reclined`) on `/api/camera/status`, hysteresis-gated. `_apply_zone_overlay`: `desk+watching` lifts L2; `bed+reclined` evening+ lowers L1/L2 (any mode except sleeping). Screen-sync cap keyed by `(mode, zone, posture)`. EMA lux (α=0.3) → `_apply_lux_multiplier` for working/relax/gaming/watching vs calibrated baseline. Pauses during sleeping. `poll_loop` 5s watchdog; on timeout `_recover_capture()` reopens V4L2 handle.
- **`transit_lighting_service.py`** — Brightens nav path (L1 + L3/L4) on camera absence + non-stationary zone in functional modes. Per-light overrides via `apply_transit_override` (reconcile-skipped). Reverts on re-presence ≥2s, 10-min timeout, or mode exit. Invisible UX.
- **`pc_agent/activity_detector.py`** — psutil 5s → POST `/api/automation/activity`. `GAME_PROCESSES` excludes `javaw.exe` (JetBrains/Gradle false positives). Media is foreground-gated.
- **`pc_agent/ambient_monitor.py`** — Blue Yeti RMS + YAMNet. RMS produces only "idle" edge + heartbeat. YAMNet runs in shadow for analytics; `silence→quiet` and `game_audio→watching` gates are live, the `speech_multiple→social` gate was abandoned 2026-05-09 (structurally unreachable). Social-mode is manual-override only. Never records audio.

---

## Frontend

- **`src/lib/stores/{lights,sonos,automation,music,connection,activity}.js`** — Svelte writable stores. WebSocket dispatches into them. `activity.js` tracks user idle state (60s timeout for auto-hide).
- **`src/lib/ws.js`** — Shared WebSocket client + reconnect logic. Dispatches messages into the stores.
- **`src/routes/+layout.svelte`** — App shell: ModeBackground + ModeOverlay + FloatingNav + NowPlayingChip + ErrorToast. No sidebar.
- **`src/routes/+page.svelte`** — Home: SonosCard strip + QuickActions + widget grid (Mode, Weather, Lights, Scenes, Routines) + MusicSuggestionToast.
- **`src/routes/music/+page.svelte`** — Taste profile, mode→playlist mapping, discovery feed. Glass card grid.
- **`src/routes/settings/+page.svelte`** — Device status, automation config, light schedule, mode brightness sliders, mode→scene overrides, morning routine config, TTS test. Glass card grid.
- **`src/lib/backgrounds/`** — Mode scenes: `PixelScene` (gaming), `ParallaxScene` (working, sprite layers + weather/time sky), `AuroraScene` (relax), `MoonScene` (sleeping, Threlte), `GenerativeCanvas` (fallback). `layer-config.js` per-mode PNG defs.
- **`src/lib/components/footballfield/`** — `/gameday` 3D scene. `FieldScene` composes `BroadcastCamera` + `SkyDome` (HDRI + `GroundedSkybox`) + `StadiumModel` (Awbmegames GLB, name-substring mesh-hide) + `FieldSurface` (markings only) + `BallMarker` + `LightTowers` + `PostFX` (Bloom+ACES, `postprocessing@6.35.4`). Parent `<Canvas autoRender={false} toneMapping={NoToneMapping}>`. Spec: `docs/GAMEDAY_SPEC.md` §11.
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

`build_id` is the short git SHA from backend startup. Frontend stashes the first per session; mismatch on later `connection_status` triggers `window.location.reload()` — that's how the kiosk auto-refreshes after deploy restarts.

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
| System | `/health`, `/ws` | Health check (status, devices, breakers, ml, tasks, `scheduler_tasks`, `build_id`), WebSocket sync |
| Lights | `/api/lights` | CRUD per-light state (on, bri, hue, sat, ct), bulk set |
| Scenes | `/api/scenes` | Curated + custom + bridge scenes, activate, effects (per-light or all) |
| Weather | `/api/weather` | Current conditions (5-min cache, NWS), alerts |
| Automation | `/api/automation` | Mode status/override, schedule, brightness multipliers, activity reports, social styles, screen sync, mode→scene overrides, DND (POST/DELETE/GET `/dnd`) |
| Sonos | `/api/sonos` | Transport (play/pause/next/prev), volume, TTS, favorites |
| Music | `/api/music` | Mode→playlist mapping, Apple Music import, taste profile, recommendations + feedback |
| Routines | `/api/routines` | Morning routine config, toggle, test |
| Pi-hole | `/api/pihole` | Stats, top-blocked, DNS host CRUD, blocklist CRUD |
| Camera | `/api/camera` | Status (detection, detection_source, lux, baseline, multiplier, pose_available, zone, posture), snapshot (JPEG, optional annotation), enable/disable, calibrate exposure |
| Guest | `/api/guest` | `GET /wifi` (WIFI: QR from `.env`); `GET/POST /scene/{name}` over 6 safelist scenes (15s cooldown, party→social/others→relax); `POST /scene/{name}/reset`; `GET/POST /vibe/{name}` (Sonos favorite, 15s cooldown, overrides social); `POST /effect/{name}` (candle/sparkle/stop, 3s cooldown); `POST /brightness/{up\|down}` (±10% mult, mode-ceiling-clamped, stamps `_manual_light_overrides`); `POST /handback`; `POST /toast` (≤120 char TTS + sparkle, 60s cooldown). Vibe map: `app_settings["guest_vibe_playlists"]`. `/guest/*` is a layout-reset visitor mini-app via `GuestBottomNav`. |
| Journal | `/api/journal` | List entries / read markdown / regenerate. Backed by `journal_service.py`; nightly ScheduledTask at 02:00 writes `data/journal/YYYY-MM-DD.md`. Surfaced at `/journal` (hidden from FloatingNav) |
| Vitals | `/api/vitals` | Aggregator for the always-visible kiosk strip. One GET re-projects hue/sonos breaker, fusion `_last_fusion_result`, pihole summary, psutil mem/disk/CPU-temp into `{value, status: ok\|warn\|error}` chips with a roll-up status. Polled by `VitalStrip.svelte` every 30s |
| Game Day | `/api/gameday` | `GET /state`, `GET /schedule`, `POST /test/{event}`. WS: `gameday_state`/`gameday_play`/`gameday_celebration`. Spec: `docs/GAMEDAY_SPEC.md` |
| Rules | `/api/rules` | View / enable-disable / regenerate learned RuleEngine rules; rule-suggestion accept endpoint |
| Learning | `/api/learning` | Predictor status, override-rate metric, A/B comparison, fusion weight retune trigger, predictor promote/demote |
| Events | `/api/events` | Activity/playback/light/scene event aggregation, filtering, mode timeline (backs `/journal` + analytics) |
| Plants | `/api/plants` | `GET /status` summary from external plant-care app (10-min TTL cache); 503 when `PLANT_APP_*` unset |
| Bar | `/api/bar` | `GET /status` summary from Home Bar app (inventory, party mode, cocktail suggestion); 503 when `BAR_APP_URL` unset |
| Ambient | `/api/ambient` | Browser-side ambient audio: playback state, volume, mode→sound map, weather-reactive config |

### Future Routes (do not implement until planned)
- `/api/actions/` — Quick actions (movie_night, bedtime, leaving, game_day)
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

**App settings (SQLite).** `await save_setting(db, key, value_dict)` / `await load_setting(db, key)`. Known keys: `morning_routine_config`, `time_schedule_config`, `mode_brightness_config`, `watching_posture_config`, `camera_enabled`, `lux_calibration_config`.

**Source attribution on write endpoints.** Write routes that log to `activity_events` / `light_adjustments` / `sonos_playback_events` / `scene_activations` should pull caller identity via `source_from_request(request, fallback="...")` from `backend.api.auth`. The Alexa lambda sets `X-Source: alexa:<intent>`; absent header → route's existing default (`api:<ip>`, `rest`, `manual`, `preset`/`custom`/`bridge`).

---

## Automation Modes

| Mode | Detection | Lighting Strategy |
|------|-----------|-------------------|
| `gameday` | `GameDayService` ESPN polling, T-30 auto-flip, T+30 conditional clear | Colts blue L1 + warm-amber L2/L3/L4 baseline, kitchen pair preserved. `CelebrationOrchestrator` runs custom light + TTS sequences per scoring play (8s cooldown); TTS volume is WPA-driven with apartment-context suppressions. Spec: `docs/GAMEDAY_SPEC.md` |
| `gaming` | Specific game binaries in `game_list.py` (NOT `javaw.exe` — matches JetBrains IDEs) | Neutral fill + blue/purple peripheral accents, warm desk-lamp bias. Night: deep blue ambient. Screen sync on L2, glisten effect eve/night |
| `working` | Terminals + IDEs (powershell, pwsh, bash, claude, code, cursor, devenv, JetBrains, wezterm, alacritty) | ct-mode clean whites, desk-dominant. IES 1:3 monitor-ambient contrast. Night: L2 130/2700K + L1 60/2270K + kitchen OFF |
| `watching` | Media players (VLC, Plex, Stremio) — foreground-gated | Projector default: warm, dim, L2 as soft bias. Kitchen OFF evening+. **Zone/posture-aware**: `zone=desk` lifts L2; `zone=bed + reclined` evening/night drops L1/L2; `zone=bed + upright` is mid-bright. Numeric vectors in `automation_engine.py` |
| `social` | Manual override only (YAMNet `speech_multiple` gate abandoned 2026-05-09 — structurally unreachable; replacement direction deferred) | "Velvet Speakeasy" static: L1 dusty rose, L2 cognac amber, L3/L4 matched burnt-orange. Saturation does the work, no effect. 1s snap |
| `relax` | Manual override | "Moss & Candlelight": L1/L2 warm ember/honey, L3/L4 moss/sage (pendants stay static). Late-night "Moss & Ember": deeper ember + hunter-green. opal day / candle eve / fire night — candle/fire scoped to L1/L2 only |
| `cooking` | Manual override | L3+L4 paired peak 3500K (accurate food colors), L1 warm, L2 dim. 1s snap |
| `sleeping` | Manual only | "Good night" TTS on entry. Dim initial (bri=20 ember) BEFORE stopping the active effect to prevent 100% pop, then fade. Manual: 24s fade off. Persistent override — no 4h timeout. Pauses media. PC sleep watcher (Windows desktop) suspends 60min after entry; cancels if mode leaves sleeping. |
| `idle` | No process detected, OR Win32 idle >10min, OR camera absent ≥30s | Falls through to time-based rules |

**Mode priority:** `report_activity` guards against lower-priority cross-source displacement of a fresh higher-priority mode; same-source updates always pass. `SOURCE_STALE_SECONDS=300` — an owning source that hasn't reported in 5 min yields to lower-priority reports (prevents stale-lock).

**Mode transition speeds:** gaming 0.5s (snappy), gameday 1s (snap — celebrations are time-sensitive), working 2s, watching 3s (cinematic), cooking 1s (snappy), relax 4s (gentle), sleeping 5s (gradual)

**Scene drift:** After 30min in **relax**, subtle random perturbation (±15 bri, ±1500 hue) with 10s transitions prevents staleness. Scoped to relax only — functional modes need stable, paired values.

**Kitchen pair rule:** L3 + L4 must match `bri` + `hue/sat` + on/off in functional modes (working, gaming, watching, cooking) and in the 6 guest party scenes — identical pendants shouldn't read as different colors. Free to diverge in relax + custom non-party scenes. Dashboard fuses them into a single "Kitchen" card via `LightCard`'s `linkedIds` prop; ApartmentViz shows them as distinct bulbs.

**Post-sunset warmth cutoff:** No CT-mode light drops below `ct=333` (~3000K) in evening/night. Watching's D65 bias is a daytime-only exception.

**Colorspace exclusivity:** `hue_service.set_light` forces `sat=0`, drops stray `hue` when `ct` is in the payload, and emits `sat` before `ct` (bridge is order-sensitive). Prevents the "greenish bedroom" bug.

**Effect reconciliation:** `_reconcile_effect` runs AFTER `_apply_state` so brightness is at target before the old effect stops (otherwise pops to 100%). 0.5s guard between stop+start.

**In-flight window:** Per-light write deadlines suppress `light_update` broadcasts until transition+0.5s. Polling is sole post-write arbiter. Mid-drag slider commands use `transitiontime=1`; release flush uses default 0.4s.

**Manual light overrides:** Slider drags stamp `_manual_light_overrides[light_id]`; reconcile + screen-sync skip stamped lights. `PRESERVE_PER_LIGHT_OVERRIDE_SOURCES` keeps stamps through autonomous pushes (late-night rescue, fusion, predictor, zone+posture, timeout_4h). User-initiated mode changes (`api:*`, `manual`, `guest`, `rule_suggestion_accept:*`) wipe stamps. 4h auto-expiry in `run_loop`.

**Mode → scene overrides:** Any mode+time slot can be mapped to a Hue bridge scene or curated preset via `mode_scene_overrides` table, overriding the default `ACTIVITY_LIGHT_STATES`.

**Late-night autopilot cascade:** (1) **22:00–06:00** — `ConfidenceFusion` weights down stale dev tools (`LATE_NIGHT_PROCESS_WEIGHT_FACTOR`). (2) **23:00+, no override, no Sonos, mode ∈ {working, idle}** — `run_loop` late-night-rescue auto-applies `relax`. **Attendance vetoes:** the rescue skips when `is_at_desk_fresh()` (camera zone=desk fresh) OR `is_recent_process_working()` (PC-agent reported working <10min ago) is True. `working` has its own `late_night` state for past-23:00 dev. Manual `sleeping` mode triggers a "Good night" TTS via the bootstrap `_sleeping_tts` callback and arms the PC sleep watcher (Windows desktop suspends after 60min in sleeping).

---

## Dynamic Effects (Hue v2)

Available effects: `candle` (warm flicker), `fire` (shifting oranges/reds), `sparkle` (bright flashes), `prism` (slow color cycle), `glisten` (shimmer), `opal` (soft pastel). Activate via `POST /api/scenes/effects/{name}` (all lights) or `.../effects/{name}/light/{id}` (single). **Effects flatten per-light HSB** to the effect's own color base — custom-palette scenes must use `effect: None`.

**EFFECT_AUTO_MAP** entries `{"effect": name, "lights": [...] | None}` — `lights=None` = all, list scopes to v1 IDs. Mappings: relax → opal day / candle eve / fire night+late_night (candle/fire scoped to L1/L2 so moss pendants stay static); watching → glisten eve/night; social, gaming, working, cooking → none.

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
# App
APP_ENV=development
LOCAL_IP=192.168.1.30          # Server LAN IP — Sonos fetches TTS MP3 from here
FRONTEND_BUILD=frontend-svelte/build  # Relative path from repo root to the SvelteKit build dir
TIMEZONE=America/Indiana/Indianapolis  # Scheduling timezone (Indiana DST rules)
LOG_LEVEL=INFO

# Hue + Sonos
HUE_BRIDGE_IP=192.168.1.50
HUE_USERNAME=<bridge token>    # From bridge pairing
SONOS_IP=192.168.1.157         # Optional; auto-discovers via SSDP if unset

# TTS
TTS_VOICE=en-US-GuyNeural
TTS_VOLUME=10

# Routines + music discovery
GOOGLE_MAPS_API_KEY=...
HOME_ADDRESS=...
WORK_ADDRESS=...
MORNING_ROUTINE_HOUR=6
MORNING_ROUTINE_MINUTE=40
MORNING_VOLUME=10
LASTFM_API_KEY=...

# Plant App (optional widget integration)
PLANT_APP_API_URL=
PLANT_APP_EMAIL=
PLANT_APP_PASSWORD=
PLANT_APP_ALLOW_INSECURE=false # Escape hatch for plain-HTTP Plant App API. Default false rejects http:// at boot.

# Bar App (optional widget integration)
BAR_APP_URL=

# Pi-hole (optional — enables network stats widget)
PIHOLE_API_URL=
PIHOLE_API_KEY=

# Voice (Phase 3 — Fauxmo virtual WeMos)
FAUXMO_ENABLED=false

# Game Day (Phase 4 — Colts celebrations)
OPENAI_API_KEY=                # Optional — TTS celebration line generator
ESPN_POLL_INTERVAL=5           # ESPN polling cadence in seconds
BIG_PLAY_YARD_THRESHOLD=20     # Yards for "big play" celebration trigger
FIELD_GOAL_YARD_THRESHOLD=40   # Yards for "long field goal" celebration trigger

# ML rule
ZONE_POSTURE_RULE_APPLY=true   # Zone+posture→relax actuation. Default True (live since 2026-04-27); set false to shadow-log only.

# Auth — write endpoints + Alexa Skill
HOME_HUB_API_KEY=<urlsafe random>  # Write-endpoint gate. Unset → 503. Localhost + RFC1918 LAN auto-bypass.
HOME_HUB_SKILL_TOKEN=<urlsafe random>  # Tunnel-origin auth (Alexa Skill), paired with API_KEY.
TRUSTED_LAN_IPS=               # Optional pin-list (comma-separated public IPs).

# Guest WiFi (surfaces QR on home dashboard + /guest)
GUEST_WIFI_SSID=               # Empty = "not configured"
GUEST_WIFI_PASSWORD=
GUEST_WIFI_SECURITY=WPA        # WPA | WEP | nopass
```

### SQLite Persisted Settings (`app_settings` table)

| Key | Content |
|-----|---------|
| `morning_routine_config` | `{hour, minute, enabled, volume}` |
| `time_schedule_config` | `{weekday: {wake_hour, ramp_start_hour, ..., late_night_start_hour}, weekend: {...}}` |
| `mode_brightness_config` | `{gaming: 1.0, working: 1.0, watching: 0.8, ...}` (range 0.3–1.5) |
| `watching_posture_config` | `{reclined_sync_cap, reclined_l1_night, upright_sync_cap}` — projector-in-bed sliders, live-patched via `PUT /api/automation/watching-posture` |
| `camera_enabled` | `{enabled: bool}` — opt-in toggle for the camera service |
| `lux_calibration_config` | `{exposure_value, target_lux, baseline_lux, calibrated_at}` — fixed-exposure baseline for adaptive brightness, written by `POST /api/camera/calibrate` |
| `guest_vibe_playlists` | `{hype, singalong, throwback}` → favorite_title — overrides `GUEST_VIBE_DEFAULTS` in `routes/guest.py`. Hand-edit; missing keys fall back |
| `screen_sync_laptop_enabled` | `{enabled: bool}` — laptop screen→bedroom-lamp sync toggle (independent of `camera_enabled`) |
| `dnd_state` | `{enabled, until, source}` — Do Not Disturb persistence; `load_override_state()` restores at boot, `run_loop` auto-clears past `until` |
| `override_state` | `{manual_override, override_mode, override_time, zone_posture_fire_stamp}` — survives restarts so a deploy mid-`relax` doesn't snap to `working`. Mirrors `dnd_state` pattern |
| `ambient_config` | Browser-side ambient sound config (volume, mode→sound map, weather reactivity); written via `/api/ambient/*` |

---

## Network Devices

| Device | IP | Notes |
|--------|----|-------|
| **Latitude 7420 (production)** | **192.168.1.210** | **Ubuntu 24.04. Backend + ambient as systemd user services, Firefox kiosk via GNOME autostart, Pi-hole v6 Docker. Always-on. Static IP.** |
| Windows desktop (dev) | 192.168.1.30 | Code edits, `git push`, local testing. PC activity detector via Task Scheduler (`--server http://192.168.1.210:8000`). MCP uses `HOME_HUB_URL` env var. |
| Hue Bridge | 192.168.1.50 | Self-signed SSL cert |
| Sonos Era 100 | 192.168.1.157 | "Bedroom". `SONOS_IP` hardcoded in `.env` to defeat cold-boot SSDP race. |
| Android Tablet | 192.168.1.209 | Kiosk display (blank page deferred) |

**iOS WiFi-rejoin caveat:** Rejoining the home network on iPhone resets per-device settings. After any rejoin, restore in Settings → WiFi → (i): manual IP `192.168.1.148`, DNS → Pi-hole (`192.168.1.210`), Private WiFi Address → Fixed. iOS treats every fresh join as a clean profile (not a Pi-hole bug).

---

## Roadmap

| Phase | Status | Focus |
|-------|--------|-------|
| 1–2 | ✓ | Core foundation + dashboard. See `docs/PROJECT_SPEC.md` |
| 3: Intelligence & Voice | Voice ✓; rules pending | Fauxmo (7 WeMos) + Custom Skill (Lambda→Tunnel→:8002→:8000; see `alexa_skill/`). Rule engine next |
| 4: Game Day | A+B+C ✓; preseason 2026-08-15 | See `docs/GAMEDAY_SPEC.md`. SEQUENCES iteration + preseason validation pending |
| 5: Polish & Expand | Future | Apple Music API, full autopilot, bar app widget |

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
- **Fauxmo device limits** — Simple on/off per virtual device. Complex voice commands use the Custom Skill.
- **1080p landscape primary** — Animated backgrounds designed for this. Must degrade gracefully on mobile.
- **Android tablet blank page** — Known issue, deferred.

## Non-Goals

- Not a multi-user platform (no auth, no user accounts)
- Not a generic smart home hub (Hue + Sonos only, by design)
- Not replacing Home Assistant or HomeKit
- Not a general sports tracker (Game Day is Colts-specific)
- Not a music streaming service (Sonos/Apple Music handle playback; Home Hub orchestrates)

