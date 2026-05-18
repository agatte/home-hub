# CLAUDE.md

> This file provides guidance to Claude Code when working in this repository.
> **Source of truth:** `docs/PROJECT_SPEC.md` — read it for full architecture, schema, and feature details. This file is the working guide; the spec is authoritative.
> **ML specification:** `docs/ML_SPEC.md` — audio classification, behavioral prediction, camera presence, adaptive lighting, and phased rollout plan.
> **Lighting expansion wishlist:** `docs/LIGHTING_EXPANSION.md` — Hue/Zigbee hardware recommendations by category and price tier, with per-apartment placement and integration notes.
> **AI Personality Layer:** `docs/PERSONALITY_LAYER.md` — mood-vector inference, future mood-ring lamp, Claude vibe intent. Phase A live (shadow-log), B/C/D in GH#58/#59/#60.

---

## Project Overview

Home Hub is an always-on personal command center for one apartment. Philips Hue + Sonos Era 100, mode-aware animated dashboard (1080p dedicated Latitude), full-autopilot learning, Alexa voice control, Colts Game Day celebrations. **Core focus:** Lights and music seamlessly. Everything else builds on that.

Full vision and goals: `docs/PROJECT_SPEC.md` § "Vision" + "Goals".

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

8 hooks live in `.claude/settings.json` — full reference in `docs/AGENT_STRATEGY.md` Part 6. The non-obvious ones:

- **PostToolUse Edit/Write** (`post_edit_ruff.py`) — `backend/**/*.py` → `python -m ruff check --fix` (ruff via module, not on PATH). No frontend lint hook (`frontend-svelte` has no ESLint).
- **PostToolUse Edit/Write** (`post_edit_env_validate.py`) — `.env*` only: required keys + empty-value + FRONTEND_BUILD path + smart-quote check.
- **PostToolUse all-tools** (`post_tool_failure.py`) — logs failures to `~/.claude/data/tool_failures.jsonl`; consumed by `error-pattern-watcher`.
- **SessionStart** (`session_start_homehub.py`) — injects mode/source/override + anomaly-only fields via `additionalContext`. Healthy systems stay terse.
- **SubagentStop** (`subagent_stop_audit.py`) — logs every subagent completion to `~/.claude/data/subagent_audit.log`.
- **PostToolUse Bash** (`post_git_push.py`) — after a real `git push`, nudges `/deploy-home`.
- **PreToolUse Bash** (`pre_commit_lighting_curator.py`) — blocks `git commit` touching `light_state_calculator.py` / `scenes.py` / `celebration_orchestrator.py` + a design identifier (`ACTIVITY_LIGHT_STATES`, `EFFECT_AUTO_MAP`, `SCENE_PRESETS`, `SEQUENCES`, …) unless the message contains `[curator-reviewed]`. Override: spawn `lighting-curator`, address, re-commit.
- **PreToolUse Bash** (`pre_push_pr_review.py`) — blocks `git push` of Python/SvelteKit diffs unless PASS markers (`<git-dir>/.pr-review-{backend,frontend}-ok` = HEAD SHA) exist. Bypass: `SKIP_PR_REVIEW=1`. Docs/config-only pushes skip.

### Slash commands + subagents

Commands: `/home-hub-dev`, `/api-audit`, `/deploy-home`, `/ui-audit`, `/project-spec`, `/checkback-loop`.

Subagents (`~/.claude/agents/`, 28 total) — fleet table + trigger map in `docs/AGENT_STRATEGY.md` Parts 1 + 5. Single canonical source — don't re-enumerate here.

### Ambient verification loop

`/checkback-loop` invokes `/loop` (dynamic) against `~/.claude/runbooks/homehub-checkbacks.md` — hourly anomaly sweep + dated one-shot decisions. Writes per-fire markdown blocks to `~/.claude/runbooks/digests/YYYY-MM-DD.md`. MCP-down → `[skipped]` + 600s back-off. Warn/error blocks fire a system-tray balloon via `~/.claude/scripts/notify.ps1` (NotifyIcon, ~8s lifetime — modern toast API silently drops on this box); ok/skipped/specialist-self-writing blocks stay silent. Auto-starts via `home-hub-loop.cmd` (kills any prior `--name homehub-loop` claude.exe before launching, so skill edits take effect on relaunch).

Parallel `/watcher-loop` (separate session) polls the digests every 600s. Warn/error blocks without `**Diagnosis (` get a `homehub-investigator` subagent spawned (per-anomaly playbook in `~/.claude/runbooks/homehub-watcher.md`); root-cause diagnosis appended inline. Investigation-only — never mutates state.

---

## Architecture

### Current

```
Browser / Phone (PWA)
        |  WebSocket + REST
        v
   FastAPI Backend (port 8000, async)
   ├── HueService (v1/phue2) ──────> Hue Bridge (basic control, 0.5s polling; 5s when v2 stream active)
   ├── HueV2Service (CLIP v2) ─────> Hue Bridge (native scenes, effects, SSE EventStream push)
   ├── SonosService (SoCo/UPnP) ──> Sonos Era 100 (2s polling)
   ├── TTSService (edge-tts) ──────> generates MP3 → Sonos plays URL
   ├── AutomationEngine ───────────> time + activity → light state
   │   └── mode-change callbacks ──> MusicMapper, AmbientMonitor, MLLogger, ModeVolumeService, CameraService, BarApp
   ├── ML Services (shipped) ──────> see docs/ML_SPEC.md
   │   ├── AudioClassifier ────────> YAMNet audio scene classification
   │   ├── BehavioralPredictor ────> LightGBM mode prediction
   │   ├── LightingLearner ────────> adaptive per-light preferences
   │   ├── CameraService ──────────> MediaPipe presence (opt-in) + adaptive lux → brightness multiplier (working/relax)
   │   ├── EmotionService ─────────> FaceLandmarker blendshapes → mood vector (Phase A shadow, opt-in)
   │   └── MusicBandit ────────────> Thompson sampling playlist selection, context-aware (mode × period × weather_class)
   ├── MusicMapper ────────────────> mode change → smart Sonos auto-play
   ├── ScreenSyncService (mss) ────> dominant screen color → bedroom lamp
   ├── Scheduler ──────────────────> morning routine + nightly maintenance
   ├── LibraryImportService ───────> Apple Music XML → taste profile
   ├── RecommendationService ──────> Last.fm + iTunes → discovery feed
   ├── PiholeService (httpx) ──────> Pi-hole v6 API (stats, DNS, blocklists)
   ├── NotifierService ────────────> mode-flip + brightness-shift → WS "notification" event + ntfy.sh phone push
   ├── WebSocketManager ───────────> bidirectional real-time sync
   ├── SQLite (aiosqlite + SQLAlchemy async)
   └── Serves SvelteKit static build from frontend-svelte/build/

Pi-hole (Docker container, host networking, same machine)
   └── pihole/pihole:latest ───────> DNS on :53, admin on :8080

PC Agent (standalone processes, same machine)
   ├── activity_detector.py ───────> psutil → POST /api/automation/activity
   ├── ambient_monitor.py ────────> PyAudio RMS → POST /api/automation/activity
   └── desktop_notifier.py ────────> PyQt6 toast widget — subscribes to /ws, renders "notification" events bottom-right
```

### Target (upcoming work)

Key additions beyond current:
- **Database migration** — SQLite → PostgreSQL (Supabase) as event volume grows
- See `docs/PROJECT_SPEC.md` for full target architecture diagram

Tech stack: `docs/PROJECT_SPEC.md` § "Tech Stack". Import quirks / gotchas: see § "Technical Limitations" below.

---

## Backend Service Guide

Full service interface docs: `docs/PROJECT_SPEC.md` § "Service Interfaces" + "Additional Services". Non-obvious footguns only:

- **`sonos_service.py`** — Favorites always shuffled with random start via `_shuffle_and_play`.
- **`automation_engine.py`** — `_evaluate_zone_posture_rule` is env-gated by `ZONE_POSTURE_RULE_APPLY` (set false to shadow-log only). Late-night rescue + zone+posture rule + both attendance vetoes live in `run_loop`. Mode priority: gameday(6) > gaming(5) > social(4) > watching(3) > working(2) > idle(1) > sleeping(0).
- **`camera_service.py`** — **Re-run lux calibration after any resolution change.** `poll_loop` 5s watchdog; on timeout `_recover_capture()` reopens V4L2 handle. Pauses during sleeping. Heartbeat ticks only after `_cap` is non-None — `poll_loop` retries `_open_capture()` each iteration when `_cap is None`, so a transient V4L2 lock (post-sleep-resume race) can't leave the lane heartbeat-fresh while every frame short-circuits. Weak-face fallback has a low-lux floor: at `ema_lux < 300`, face conf < 0.25 returns absent (kills chair-back ghosts that defeated absent-dwell counters). Strong-face ≥0.70 and pose paths fire regardless of lux.
- **`transit_lighting_service.py` + `desk_exit_kitchen_service.py`** — sibling camera-driven overrides sharing `_transit_light_overrides`. Transit = L1+kitchen, 10-min auto-fade. DeskExit = kitchen-only, hold-until-return, time-of-day brightness (evening bri=120/ct=360, night+late_night bri=60/ct=375). Transit **cedes the kitchen pair** in productive evening/night (mode ∈ {working, gaming, watching, idle}, hour ≥ 18 or late_night) so the two don't fight. Both fire on sustained 10s desk-loss; DeskExit also requires `period ∈ TRIGGER_PERIODS` and uses `is_at_desk_fresh()` as the return signal. Distinguish via `light_adjustments.trigger` (`transit` vs `desk_exit_kitchen`). `"desk_exit_kitchen"` is in `PRESERVE_PER_LIGHT_OVERRIDE_SOURCES`. 4h hard timeout = wedged-camera failsafe only.
- **`pc_agent/activity_detector.py`** — `GAME_PROCESSES` excludes `javaw.exe` (JetBrains false positives). Media is foreground-gated. LoL champion resolved off `/liveclientdata/allgamedata` (Riot dropped `championName` from `/activeplayer` 2026-05-18); `_resolve_active_champion` cross-walks `activePlayer.riotId` → `allPlayers` roster, falls back to `summonerName` for spectator/replay.
- **`pc_agent/ambient_monitor.py`** — `speech_multiple→social` gate abandoned 2026-05-09 (max observed score 0.088 across 838k rows; structurally unreachable). Social is manual-override only. Never records audio.
- **`websocket_manager.py`** — `broadcast` fan-outs via `asyncio.gather` with a 2s per-client `wait_for`. A stalled client (mobile on bad wifi, paused tab) now disconnects itself instead of holding the loop; expect `Client disconnected` log lines in those cases rather than "broadcasts stopped firing."
- **`hue_v2_service.py`** — `event_stream_loop` is the SSE consumer for `/eventstream/clip/v2`; uses a second `_stream_client` (read timeout disabled). Broadcasts on/bri pushes via the existing `light_update` channel; intentionally drops color (CIE xy) + ct events because there's no gamut-aware converter to v1's hue/sat. Color/ct ride the v1 5s fallback. Application-level liveness probe: `asyncio.wait_for` on each `aiter_lines()` step with a 90s budget (`_STREAM_SILENT_RECONNECT_SECONDS`) — if the bridge stops sending keepalives the loop force-reconnects rather than trusting httpx to notice a silently-dead socket. 1s→30s exponential backoff on disconnect; v1 polling auto-resumes 0.5s cadence whenever the stream isn't healthy. Heartbeat threshold in `/health` is 100s (silence timeout + 1s backoff + ~10s reconnect handshake budget), so a quiet-then-reconnect cycle stays green; `/health` only goes degraded if the reconnect itself can't establish.

---

## Frontend

Full frontend component map: `docs/PROJECT_SPEC.md` § "Dashboard — Themed Backgrounds". Key layout: `src/lib/stores/` (WS → stores), `src/lib/ws.js` (reconnect), `src/lib/backgrounds/` (mode scenes), `src/routes/` (4 pages + hidden `/journal` + `/guest/*`). Typography: Bebas Neue (display) + Source Sans 3 (body). Lucide SVG icons.

**Gotcha — Game Day 3D field:** `<Canvas autoRender={false} toneMapping={NoToneMapping}>` is required; see `docs/GAMEDAY_SPEC.md` §11 + memory `project_gameday_3d_field_gotchas.md`. `postprocessing@6.35.4` peer dep must stay pinned.

**Gotcha — catch-all order:** Built frontend is served via `/{path:path}`; this must be registered in `main.py` AFTER all `/api/` routes or the API is shadowed.

**Gotcha — scene RAF + debounced derived:** Background scenes (`scene-utils.js` `createAnimationLoop` + bespoke handlers in `GenerativeCanvas` / `ParallaxScene`) pause on `document.visibilitychange` and resume on visible. `MoonScene` (Threlte `useTask`) is exempt — sleeping mode only. `stores/_debounce.js` exports `debounced(stores, fn, ms=150)` mirroring `derived`'s shape with a trailing-debounce; `constellationWithContext` + `sectorBoard` use it. `GenerativeCanvas`'s lights subscription is also 200ms-debounced + palette-capped at 8 — slider drags no longer trigger per-tick HSL recompute.

---

## WebSocket Protocol

**Endpoint:** `ws://host:8000/ws`. Full message-type reference: `docs/PROJECT_SPEC.md` § "WebSocket Protocol".

**build_id kiosk-reload:** `connection_status` carries the short git SHA. Frontend stashes the first per session; mismatch on reconnect triggers `window.location.reload()` — that's how the kiosk auto-refreshes after a deploy restart.

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
| Music | `/api/music` | Mode→playlist mapping, Apple Music import, taste profile, recommendations + feedback, iTunes preview playback (`POST /preview` with DIDL-Lite metadata), bandit arm landscape (`GET /bandit-status`) |
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
| Notification | `/api/notification` | `POST /test` fires a synthetic notification through NotifierService (WS broadcast + ntfy.sh push). Bypasses DND/coalesce/boot gating — verification harness for the desktop toast + phone push surfaces |
| Personality | `/api/personality` | `mood/current` + `mood/history`, `calibration` POST + history, `settings` GET/POST. Backs hidden `/personality` page. Spec: `docs/PERSONALITY_LAYER.md` |

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

**App settings (SQLite).** `await save_setting(db, key, value_dict)` / `await load_setting(db, key)`. Known keys: `morning_routine_config`, `time_schedule_config`, `mode_brightness_config`, `mode_volume_curves`, `watching_posture_config`, `camera_enabled`, `lux_calibration_config`.

**Source attribution on write endpoints.** Write routes that log to `activity_events` / `light_adjustments` / `sonos_playback_events` / `scene_activations` should pull caller identity via `source_from_request(request, fallback="...")` from `backend.api.auth`. The Alexa lambda sets `X-Source: alexa:<intent>`; absent header → route's existing default (`api:<ip>`, `rest`, `manual`, `preset`/`custom`/`bridge`).

---

## Automation Modes

| Mode | Detection | Lighting Strategy |
|------|-----------|-------------------|
| `gameday` | `GameDayService` ESPN polling, T-30 auto-flip, T+30 conditional clear | Colts blue L1 + warm-amber L2/L3/L4 baseline, kitchen pair preserved. `CelebrationOrchestrator` runs custom light + TTS sequences per scoring play (8s cooldown); TTS volume is WPA-driven with apartment-context suppressions. Spec: `docs/GAMEDAY_SPEC.md` |
| `gaming` | Specific game binaries in `game_list.py` (NOT `javaw.exe` — matches JetBrains IDEs) | Neutral fill + blue/purple peripheral accents, warm desk-lamp bias. Night: deep blue ambient. Screen sync on L2, glisten effect eve/night. While League is in an active match, L2 + L5 shift to the champion's signature color (`LoLChampionService` reads `champion` factor from activity report → `champion_color_map` app_setting → bypasses screen-sync on those lamps) |
| `working` | Terminals + IDEs (powershell, pwsh, bash, claude, code, cursor, devenv, JetBrains, wezterm, alacritty) | ct-mode clean whites, desk-dominant. IES 1:3 monitor-ambient contrast. Night: L2 130/2700K + L1 60/2270K + kitchen OFF |
| `watching` | Media players (VLC, Plex, Stremio) — foreground-gated | Projector default: warm, dim, L2 as soft bias. Kitchen OFF evening+. **Zone/posture-aware**: `zone=desk` lifts L2; `zone=bed + reclined` evening/night drops L1/L2; `zone=bed + upright` is mid-bright. Numeric vectors in `automation_engine.py` |
| `social` | Manual override only (YAMNet `speech_multiple` gate abandoned 2026-05-09 — structurally unreachable; replacement direction deferred) | "Velvet Speakeasy" static: L1 dusty rose, L2 cognac amber, L3/L4 matched burnt-orange. Saturation does the work, no effect. 1s snap |
| `relax` | Manual override | "Moss & Candlelight": L1/L2 warm ember/honey, L3/L4 moss/sage (pendants stay static). Late-night "Moss & Ember": deeper ember + hunter-green. opal day / **none eve** / fire night+late_night — fire scoped to L1/L2 only. Candle removed from auto-map 2026-05-09 (locked color state, persisted through mode changes). |
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

**In-flight window:** Per-light write deadlines suppress `light_update` broadcasts until transition+0.5s. Poll loop ticks every 0.5s (demotes to 5s when v2 EventStream is active — see `HueV2Service.event_stream_loop`); a 3s max-age clamp force-clears any deadline pushed further than that (unreachable bulb that ack'd the write but never transitioned). The v2 stream dispatcher honors the same inflight window so a stream echo from your own slider drag doesn't snap the UI back mid-drag. Mid-drag slider commands use `transitiontime=1`; release flush uses default 0.4s.

**Manual light overrides:** Slider drags stamp `_manual_light_overrides[light_id]`; reconcile + screen-sync skip stamped lights. `PRESERVE_PER_LIGHT_OVERRIDE_SOURCES` keeps stamps through autonomous pushes (late-night rescue, fusion, predictor, zone+posture, timeout_4h). User-initiated mode changes (`api:*`, `manual`, `guest`, `rule_suggestion_accept:*`) wipe stamps. 4h auto-expiry in `run_loop`.

**Mode → scene overrides:** Any mode+time slot can be mapped to a Hue bridge scene or curated preset via `mode_scene_overrides` table, overriding the default `ACTIVITY_LIGHT_STATES`.

**Late-night autopilot cascade:** (1) **22:00–06:00** — `ConfidenceFusion` weights down stale dev tools (`LATE_NIGHT_PROCESS_WEIGHT_FACTOR`). (2) **23:00+, no override, no Sonos, mode ∈ {working, idle}** — `run_loop` late-night-rescue auto-applies `relax`. **Attendance vetoes:** the rescue skips when `is_at_desk_fresh()` (camera zone=desk fresh) OR `is_recent_process_working()` (PC-agent reported working <10min ago) is True. `working` has its own `late_night` state for past-23:00 dev. (3) **late_night, mode=watching, zone=bed+reclined sustained 90min** — `_evaluate_watching_sleep_guard` flips watching→sleeping (catches "asleep with YouTube on the projector"; supersedes manual watching ≥90min old). Sleeping entry triggers "Good night" TTS via bootstrap `_sleeping_tts` and arms the PC sleep watcher (60min Windows suspend); the TTS is gated off when `override_source == "watching_sleep_guard"`.

---

## Dynamic Effects (Hue v2)

Available effects: `candle` (warm flicker), `fire` (shifting oranges/reds), `sparkle` (bright flashes), `prism` (slow color cycle), `glisten` (shimmer), `opal` (soft pastel). Activate via `POST /api/scenes/effects/{name}` (all lights) or `.../effects/{name}/light/{id}` (single). **Effects flatten per-light HSB** to the effect's own color base — custom-palette scenes must use `effect: None`.

**EFFECT_AUTO_MAP** entries `{"effect": name, "lights": [...] | None}` — `lights=None` = all, list scopes to v1 IDs. Mappings: relax → opal day / **none eve** / fire night+late_night (fire scoped to L1/L2 so moss pendants stay static); watching → glisten eve/night; social, gaming, working, cooking → none. Candle removed from auto-map 2026-05-09 (locked color values, persisted through mode changes); manual candle still callable via scene browser / guest UI / MCP.

**Time periods:** `_get_time_period()` returns `day`/`evening`/`night`/`late_night`. `late_night` runs from `DaySchedule.late_night_start_hour` (default 23) until `wake_hour`. Only relax defines a `late_night` state; other modes fall back to `night`.

**Weather effect fallback:** When a mode has no auto-effect, weather overlays one — thunderstorm→sparkle, snow→opal (evening/night only, sparkle any time). Same-effect cycles skipped to preserve the bridge's brightness base. Rain→candle removed 2026-05-09.

---

## Database Schema

Full schema with column types: `docs/PROJECT_SPEC.md` § "Database Schema". Live tables: `app_settings`, `scenes`, `mode_playlists`, `music_artists`, `taste_profile`, `recommendations`, `recommendation_feedback`, `mode_scene_overrides`. Event tables (Phase 3): `activity_events`, `light_adjustments`, `sonos_playback_events` (`weather_class` column added Phase B for bandit context), `scene_activations`, `learned_rules`, `ml_decisions`, `ml_metrics`. Personality: `mood_samples` (7-day rolling, pruned at boot), `mood_calibration`, `vibe_requests` (Phase C placeholder). Data retention: 90-day rolling (mood_samples is the 7-day exception).

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
MOMENTUM_WPA_THRESHOLD=0.15    # |WPA| swing that triggers a momentum celebration on non-scoring plays

# ML rule
ZONE_POSTURE_RULE_APPLY=true   # Zone+posture→relax actuation. Default True (live since 2026-04-27); set false to shadow-log only.

# Auth — write endpoints + Alexa Skill
HOME_HUB_API_KEY=<urlsafe random>  # Write-endpoint gate. Unset → 503. Localhost + RFC1918 LAN auto-bypass.
HOME_HUB_SKILL_TOKEN=<urlsafe random>  # Tunnel-origin auth (Alexa Skill), paired with API_KEY.
TRUSTED_LAN_IPS=               # Optional pin-list (comma-separated public IPs).

# Observability
SENTRY_DSN=                    # Optional — Sentry DSN from home-hub.sentry.io. Unset disables ingestion.

# Notifier (apartment-state nudges → desktop toast + iPhone push via ntfy.sh)
NTFY_TOPIC=                    # Treat as a secret — topic name IS the auth on hosted ntfy.sh. Unset → WS broadcast still works, ntfy push skipped.
NTFY_SERVER=https://ntfy.sh    # Override only when self-hosting (e.g. http://192.168.1.210:8085).

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
| `mode_volume_curves` | `{mode: {day, evening, night, fade_duration_s}}` — per-mode Sonos targets, smooth fade on mode change. `ModeVolumeService` callback. Sleeping forced 0; DND suppresses. PUT `/api/automation/mode-volume` |
| `watching_posture_config` | `{reclined_sync_cap, reclined_l1_night, upright_sync_cap}` — projector-in-bed sliders, live-patched via `PUT /api/automation/watching-posture` |
| `camera_enabled` | `{enabled: bool}` — opt-in toggle for the camera service |
| `lux_calibration_config` | `{exposure_value, target_lux, baseline_lux, calibrated_at}` — fixed-exposure baseline for adaptive brightness, written by `POST /api/camera/calibrate` |
| `guest_vibe_playlists` | `{hype, singalong, throwback}` → favorite_title — overrides `GUEST_VIBE_DEFAULTS` in `routes/guest.py`. Hand-edit; missing keys fall back |
| `screen_sync_laptop_enabled` | `{enabled: bool}` — laptop screen→bedroom-lamp sync toggle (independent of `camera_enabled`) |
| `dnd_state` | `{enabled, until, source}` — DND persistence; restored at boot, `run_loop` auto-clears past `until` |
| `override_state` | `{manual_override, override_mode, override_time, zone_posture_fire_stamp}` — survives deploys mid-override |
| `ambient_config` | Browser-side ambient sound config (volume, mode→sound map, weather reactivity); also stores Sonos mirroring sub-keys: `sonos_enabled`, `sonos_present_volume` (default 12), `sonos_away_volume` (default 28); written via `/api/ambient/*` |
| `champion_color_map` | `{ChampionName: {r, g, b}, ...}` — LoL champion → RGB palette driving bedroom-lamp color in `gaming` mode; consumed by `LoLChampionService`, seeded via `python -m scripts.seed_champion_colors` (idempotent re-seed) |
| `personality_enabled` | `{enabled: bool}` — master kill switch for the AI Personality Layer; gates all sub-toggles |
| `emotion_enabled` | `{enabled: bool}` — Latitude blendshape extraction. Requires `personality_enabled` + `camera_enabled` |
| `desktop_emotion_enabled` | `{enabled: bool}` — desktop pc_agent blendshape capture (GH#64). Supervisor polls 30s; EmotionService prefers desktop within 30s freshness, else Latitude |
| `desktop_presence_enabled` | `{enabled: bool}` — desktop pc_agent presence POSTs to `/api/camera/observation` (PresenceFusion). Independent of emotion (privacy split: occupancy vs mood inference). Same 30s settings poll |
| `mood_ring_enabled` | `{enabled: bool}` — Phase B preview toggle; no effect until MoodRingLight ships (GH#58) |
| `mood_ring_light_id` | `{light_id: str}` — which light the Phase B mood-ring drives (default `"1"`) |
| `mood_calibration_bias` | `{valence, arousal, focus: float}` — per-axis bias auto-fit from self-report (≥10 samples); loaded at boot |

---

## Network Devices

| Device | IP | Notes |
|--------|----|-------|
| **Latitude 7420 (production)** | **192.168.1.210** | **Ubuntu 24.04. Backend + ambient as systemd user services, Firefox kiosk via GNOME autostart, Pi-hole v6 Docker. Always-on. Static IP.** |
| Windows desktop (dev) | 192.168.1.30 | Code edits, `git push`, local testing. PC activity detector via Task Scheduler (`--server http://192.168.1.210:8000`). MCP uses `HOME_HUB_URL` env var. Desktop notifier autostarts via separate Task Scheduler entry `Home Hub Desktop Notifier` (At-Logon, exe at `%LOCALAPPDATA%\HomeHub\HomeHubNotifier.exe`, built via `scripts/build_desktop_notifier.ps1`). |
| Hue Bridge | 192.168.1.50 | Self-signed SSL cert |
| Sonos Era 100 | 192.168.1.157 | "Bedroom". `SONOS_IP` hardcoded in `.env` to defeat cold-boot SSDP race. |
| Android Tablet | 192.168.1.209 | Kiosk display (blank page deferred) |

**iOS WiFi-rejoin caveat:** Rejoining the home network on iPhone resets per-device settings. After any rejoin, restore in Settings → WiFi → (i): manual IP `192.168.1.148`, DNS → Pi-hole (`192.168.1.210`), Private WiFi Address → Fixed. iOS treats every fresh join as a clean profile (not a Pi-hole bug).

---

## Roadmap

| Phase | Status | Focus |
|-------|--------|-------|
| 1–2 | ✓ | Core foundation + dashboard. See `docs/PROJECT_SPEC.md` |
| 3: Intelligence & Voice | ✓ | Fauxmo + Custom Skill (Lambda→Tunnel→:8002→:8000). Rule engine + persistent suggestion UX shipped (rule_suggestions table + Home banner + 60min auto-expire + Settings history) |
| 4: Game Day | A+B+C ✓; preseason 2026-08-13, reg-season 2026-09-13 | See `docs/GAMEDAY_SPEC.md`. SEQUENCES iteration + preseason validation pending |
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

Non-goals + scope discussion: `docs/PROJECT_SPEC.md`.

