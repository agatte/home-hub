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

# Monitor brightness agent (Windows; DDC/CI brightness + color temp); --detect probes hardware
python -m backend.services.pc_agent.monitor_brightness --detect

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

### Production deploy (Latitude at 192.168.86.210)

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

**Key tools** (full list discoverable via the MCP itself):
- `get_live_state()` — one-shot snapshot (mode+lights+screen-sync+camera+presence+weather+multipliers); first call for any "what's happening" question
- `get_state_history(minutes=30)` — timeline from event tables
- `query_db(sql)` — read-only SQLite (SELECT only)
- Plus per-domain getters/setters: lights, scenes, effects, sonos, weather, automation, routines, pihole.

**Registered in:** `.mcp.json` (project root, auto-loaded).

### Hooks (`.claude/settings.json` + `.claude/hooks/`)

8 hooks live in `.claude/settings.json` — full reference in `docs/AGENT_STRATEGY.md` Part 6. The non-obvious ones:

- **PostToolUse Edit/Write** (`post_edit_ruff.py`) — `backend/**/*.py` → `python -m ruff check --fix` (ruff via module, not on PATH). No frontend lint hook (`frontend-svelte` has no ESLint).
- **PostToolUse Edit/Write** (`post_edit_env_validate.py`) — `.env*` only: required keys + empty-value + FRONTEND_BUILD path + smart-quote check.
- **PostToolUse all-tools** (`post_tool_failure.py`) — logs failures to `~/.claude/data/tool_failures.jsonl`; consumed by `error-pattern-watcher`.
- **SessionStart** (`session_start_homehub.py`) — injects mode/source/override + anomaly-only fields via `additionalContext`. Healthy systems stay terse.
- **SubagentStop** (`subagent_stop_audit.py`) — logs every subagent completion to `~/.claude/data/subagent_audit.jsonl` (structured: agent + token usage parsed from the subagent's own transcript). Read by `error-pattern-watcher` + the `/fleet-usage` reporter.
- **PostToolUse Bash** (`post_git_push.py`) — after a real `git push`, nudges `/deploy-home`.
- **PreToolUse Bash** (`pre_commit_lighting_curator.py`) — blocks `git commit` touching `light_state_calculator.py` / `scenes.py` / `celebration_orchestrator.py` + a design identifier (`ACTIVITY_LIGHT_STATES`, `EFFECT_AUTO_MAP`, `SCENE_PRESETS`, `SEQUENCES`, …) unless the message contains `[curator-reviewed]`. Override: spawn `lighting-curator`, address, re-commit.
- **PreToolUse Bash** (`pre_push_pr_review.py`) — blocks `git push` of Python/SvelteKit diffs unless PASS markers (`<git-dir>/.pr-review-{backend,frontend}-ok` = HEAD SHA) exist. Bypass: `SKIP_PR_REVIEW=1`. Docs/config-only pushes skip.

### Slash commands + subagents

Commands: `/home-hub-dev`, `/api-audit`, `/deploy-home`, `/ui-audit`, `/project-spec`, `/checkback-loop`.

Subagents (`~/.claude/agents/`, 31 total) — fleet table + trigger map in `docs/AGENT_STRATEGY.md` Parts 1 + 5. Single canonical source — don't re-enumerate here.

### Ambient verification loop

`/checkback-loop` runs `~/.claude/runbooks/homehub-checkbacks.md` (hourly sweep + dated one-shots), writes blocks to `~/.claude/runbooks/digests/YYYY-MM-DD.md`. MCP-down → `[skipped]` + 600s back-off. Warn/error blocks fire a system-tray balloon via `~/.claude/scripts/notify.ps1`.

Parallel `/watcher-loop` polls digests every 600s; warn/error blocks without `**Diagnosis (` get a `homehub-investigator` subagent spawned (playbook: `~/.claude/runbooks/homehub-watcher.md`). Investigation-only.

**Autostart (both loops):** Windows Scheduled Tasks `Home Hub Checkback Loop` + `Home Hub Watcher Loop` (triggers: logon + unlock + resume; idempotent ensure-running), run hidden via `start-homehub-loop.ps1` through the `start-homehub-loop-hidden.vbs` shim. `Home Hub Loops Daily Relaunch` recycles both at 04:00 to shed `/loop` context before auto-compaction. Re-register: `register-homehub-loop-tasks.ps1`; status: `homehub-loops-status.ps1` (all in `~/.claude/scripts/`).

---

## Architecture

Full current + target ASCII diagrams: `docs/PROJECT_SPEC.md` § "Current Architecture" / "Target Architecture". Tech stack: § "Tech Stack". Import quirks: see § "Technical Limitations" below. At-a-glance:

**FastAPI backend** (port 8000, async) serves the SvelteKit static build (`frontend-svelte/build/`) + WS/REST. Devices: `HueService` (v1/phue2, 0.5s poll; 5s when v2 active) + `HueV2Service` (CLIP v2 scenes/effects/SSE) → Hue Bridge; `SonosService` (SoCo, 2s) → Era 100; `TTSService` (edge-tts) → MP3 → Sonos. `AutomationEngine` maps time+activity → light state and fires mode-change callbacks (MusicMapper, AmbientMonitor, MLLogger, ModeVolumeService, CameraService, BarApp). ML services (`docs/ML_SPEC.md`): AudioClassifier, BehavioralPredictor, LightingLearner, CameraService, EmotionService, MusicBandit. Plus MusicMapper, ScreenSyncService (mss), Scheduler, Library/RecommendationService, PiholeService, NotifierService (→ WS + ntfy.sh), WebSocketManager, SQLite (aiosqlite + SQLAlchemy async).

**Pi-hole** — Docker (host networking), same machine; DNS :53 (LAN-wide), admin :8080 **(loopback-only since 2026-06-01 — reach via `ssh -L 8080:localhost:8080 homehub`)**; upstream is a local **Unbound** recursive + DNSSEC resolver (`127.0.0.1#5335`, separate `mvance/unbound` container, loopback-only) — no third-party DNS in path. **Footgun:** `docker/pihole/.env` (holds `PIHOLE_PASSWORD`) must exist before any `docker compose up` that recreates the pihole container, or the admin password blanks + Pi-hole admin auth breaks. **PC agents** (standalone, dev desktop): `activity_detector.py` + `ambient_monitor.py` → `POST /api/automation/activity`; `desktop_notifier.py` subscribes `/ws` for toast events. **Target:** SQLite → PostgreSQL (Supabase) as event volume grows.

---

## Backend Service Guide

Full service interface docs: `docs/PROJECT_SPEC.md` § "Service Interfaces" + "Additional Services". Non-obvious footguns only:

- **`sonos_service.py`** — Favorites always shuffled with random start via `_shuffle_and_play`.
- **`automation_engine.py`** — `_evaluate_zone_posture_rule` is env-gated by `ZONE_POSTURE_RULE_APPLY` (**dormant since 2026-05-27** — no camera produces `zone=bed` after the Latitude→living-room move; kept pending future bed-zone source). Late-night rescue + ambient_relax + zone+posture rule + both attendance vetoes live in `run_loop`. `is_present_in_room()` (added with the move) gates `ambient_relax` so a fresh committed couch zone vetoes the auto-flip. Mode priority: pregameday(6) = gameday(6) > gaming(5) > social(4) > watching(3) = cooking(3) > working(2) > idle(1) > sleeping(0). Away mode + dedicated detection service shelved 2026-05-21 after Hue/ARP/Pi-hole paths all hit dead ends — see `project_away_mode_shelved.md` before designing another presence layer. The Hue iOS app's native Home & Away automations integrate via the existing `_check_external_off` mechanism.
- **`camera_service.py`** — **Latitude relocated to living room 2026-05-27** (sees couch only — emits a single `ZONE_COUCH`; the bedroom desk/bed left-right split is retired; baseline_lux recalibrated to ~74). Desktop pc_agent owns `zone=desk` via PresenceFusion. Off-host ingest (observation/lux/blendshape routes) clamps client `captured_at` to server now (+2s tolerance, `clamp_client_timestamp` in `api/_guards.py`) — journal warning `clamped future timestamp` = the posting agent's clock is skewed; stored future stamps self-heal on the next honest report. **Re-run lux calibration after any resolution change OR camera relocation.** All V4L2 open/release runs off-loop + time-bounded (`_open_capture_async`); poll_loop's 5s frame watchdog → `_recover_capture()`. An orphaned fd can wedge `/dev/video0` intra-process (respawn can't reclaim it) → watchdog escalates to a systemd restart after 3 failed respawns, rate-limited via `camera_wedge_last_restart`; see `project_camera_v4l2_fd_wedge_self_heal.md`. Pauses during sleeping; heartbeat ticks only after `_cap` is non-None. Weak-face low-lux floor: `ema_lux<300` + conf<0.25 → absent; strong-face ≥0.70 and pose fire regardless. Couch posture is suppressed (no consumer).
- **`transit_lighting_service.py` + `desk_exit_kitchen_service.py`** — sibling camera-driven overrides sharing `_transit_light_overrides`. Transit = L1+kitchen, 10-min auto-fade. DeskExit = kitchen-only, hold-until-return, time-of-day brightness. Transit **cedes the kitchen pair** in productive evening/night (mode ∈ {working, gaming, watching, idle}, hour ≥ 18 or late_night). Both fire on sustained 10s desk-loss; DeskExit also needs `period ∈ TRIGGER_PERIODS` and uses `is_at_desk_fresh()` to return. Distinguish via `light_adjustments.trigger`. `desk_exit_kitchen` is in `PRESERVE_PER_LIGHT_OVERRIDE_SOURCES`. 4h hard timeout = wedged-camera failsafe. **D1 (lux-adaptive path brightness):** both set corridor/kitchen `bri` via `light_state_calculator.path_light_brightness(lux, baseline, period)` against the **Latitude** room lux + measure-then-hold (sample once at activation, hold — avoids the L1-brightens-room feedback loop); camera-down → pre-D1 fixed fallback.
- **`screen_sync.py`** — L2+L5 bedroom lamps mirror screen color (gaming/watching). **Ambient lux lift** (`_scale_for_ambient`): scales cap+floor by `bedroom_lux × weather` for `{gaming, watching}` × ALL periods, ceiling 1.40×; **L5 excluded** (`_AMBIENT_LIFT_EXCLUDE_LIGHTS`) — clear-housing point source = glare, so L2 (fabric, diffuse) carries the room-light lift. Lux source is `app.state.bedroom_lux` (desktop Brio `LuxChannel` in `lux_channel.py`), NOT the living-room Latitude — cross-room contamination was dimming bedroom floors when the living room was bright. The screen-color route (`automation.py:receive_screen_color`) sources zone/posture from `app.state.presence` (PresenceFusion `latest_zone()`), NOT `camera_service` — else the watching-at-desk L2 cap (180) silently stops firing post Latitude→living-room move. `bedroom_lux` is fed by `emotion_capture.py`'s flip-sample-flip sampler (restore auto-exposure on the SAME handle; DSHOW). Calibrate: `POST /api/camera/desktop/lux/calibrate/request`. Plan/history: `docs/PRESENCE_LIGHTING_SCENARIOS.md` Part 7.5.
- **`pc_agent/activity_detector.py`** — `GAME_PROCESSES` excludes `javaw.exe` (JetBrains FPs). Media foreground-gated. LoL champion resolved off `/liveclientdata/allgamedata` via `_resolve_active_champion` cross-walking `activePlayer.riotId` → `allPlayers` roster (fallback `summonerName` for spectator/replay).
- **`pc_agent/ambient_monitor.py`** — YAMNet `speech_multiple→social` gate abandoned (structurally unreachable). Social is manual-override only. Never records audio.
- **`websocket_manager.py`** — `broadcast` uses `asyncio.gather` with a 2s per-client `wait_for`. A stalled client disconnects itself; expect `Client disconnected` log lines.
- **`hue_v2_service.py`** — `event_stream_loop` is the SSE consumer for `/eventstream/clip/v2`. Broadcasts on/bri via `light_update`; intentionally drops color (CIE xy) + ct events (no gamut-aware v1 converter) — those ride the v1 5s fallback. Liveness: `asyncio.wait_for` on each `aiter_lines()` step, 90s budget (`_STREAM_SILENT_RECONNECT_SECONDS`); 1s→30s backoff on disconnect; v1 polling resumes 0.5s when the stream isn't healthy. `/health` heartbeat threshold 100s.

---

## Frontend

Full frontend component map: `docs/PROJECT_SPEC.md` § "Dashboard — Themed Backgrounds". Key layout: `src/lib/stores/` (WS → stores), `src/lib/ws.js` (reconnect), `src/lib/backgrounds/` (mode scenes), `src/routes/` (4 pages + hidden `/journal` + `/guest/*`). Typography: Bebas Neue (display) + Source Sans 3 (body). Lucide SVG icons.

**Gotcha — Game Day 3D field:** `<Canvas autoRender={false} toneMapping={NoToneMapping}>` is required; see `docs/GAMEDAY_SPEC.md` §11 + memory `project_gameday_3d_field_gotchas.md`. `postprocessing@6.35.4` peer dep must stay pinned.

**Gotcha — catch-all order:** Built frontend is served via `/{path:path}`; this must be registered in `main.py` AFTER all `/api/` routes or the API is shadowed.

**Gotcha — scene RAF + debounced derived:** Background scenes pause on `document.visibilitychange`, resume on visible (`MoonScene` exempt; sleeping only). `stores/_debounce.js` exports a `debounced()` mirror of `derived` with trailing-debounce; used by `constellationWithContext` + `sectorBoard`. `GenerativeCanvas`'s lights subscription is 200ms-debounced + palette-capped at 8.

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

**Prefix:** REST endpoints use `/api/`; `/health` + `/ws` are unprefixed. **All routes must register BEFORE the `/{path:path}` frontend catch-all** in `main.py` or the API is shadowed. One module per group in `backend/api/routes/`; full endpoint signatures there + `docs/PROJECT_SPEC.md` § "API Routes".

| Group | Prefix | Module · note |
|-------|--------|------|
| System | `/health`, `/ws` | `health.py` — status/devices/breakers/ml/tasks/`scheduler_tasks`/`build_id`; WS sync |
| Lights | `/api/lights` | `lights.py` — per-light + bulk set (on/bri/hue/sat/ct) |
| Scenes | `/api/scenes` | `scenes.py` — curated/custom/bridge scenes + effects (per-light or all) |
| Weather | `/api/weather` | `weather.py` — NWS conditions (5-min cache), alerts |
| Automation | `/api/automation` | `automation.py` — mode status/override, schedule, brightness mult, social styles, screen sync, mode→scene, DND, watching-posture + `rust-lighting` (GET/PUT live Rust luma-bri envelope tuning, no redeploy → `rust_lighting_config`) |
| Sonos | `/api/sonos` | `sonos.py` — transport, volume, TTS, favorites |
| Music | `/api/music` | `music.py` — mode→playlist, import, recs+feedback, iTunes `POST /preview` (DIDL-Lite), `GET /bandit-status` |
| Routines | `/api/routines` | `routines.py` — morning routine config/toggle/test |
| Pi-hole | `/api/pihole` | `pihole.py` — stats, top-blocked, DNS + blocklist + allowlist CRUD |
| Camera | `/api/camera` | `camera.py` — status (lux/baseline/zone/posture/pose), snapshot, enable, calibrate |
| Guest | `/api/guest` | `guest.py` — wifi QR, scene/vibe/effect/brightness(±10%), handback, toast(≤120c) |
| Journal | `/api/journal` | `journal.py` — list/read/regenerate; nightly 02:00 task → `data/journal/`; at `/journal` |
| Vitals | `/api/vitals` | `vitals.py` — kiosk-strip chips `{value, status}` + roll-up; VitalStrip polls 30s |
| Game Day | `/api/gameday` | `gameday.py` — `/state`, `/schedule`, `/test/{event}`; spec GAMEDAY_SPEC |
| Rules | `/api/rules` | `rules.py` — view/toggle/regenerate learned rules; rule + brightness suggestion accept/dismiss |
| Learning | `/api/learning` | `learning.py` — predictor status, override-rate, A/B, fusion retune, promote/demote |
| Remediation | `/api/remediation` | `remediation.py` — `status` (mode + 24h auto-fix count + recent proposals) / `action`; propose-only unless `REMEDIATION_AUTONOMOUS`; backs RemediationStatusCard + `homehub-remediator`. DND suppresses push, keeps audit. Memory: `project_source_trust_watchdog` |
| Events | `/api/events` | `events.py` — activity/playback/light/scene aggregation, mode timeline (backs journal + analytics) |
| Plants | `/api/plants` | `plants.py` — external plant app summary (10-min TTL); 503 when unset |
| Bar | `/api/bar` | `bar.py` — Home Bar app summary; 503 when `BAR_APP_URL` unset |
| Ambient | `/api/ambient` | `ambient.py` — browser ambient audio state/volume/map/weather config |
| Notification | `/api/notification` | `notification.py` — `POST /test` synthetic notification; bypasses DND/coalesce/boot gating |
| Personality | `/api/personality` | `personality.py` — mood current/history, calibration, settings; backs `/personality`; spec PERSONALITY_LAYER |
| Analytics | `/api/analytics` | `analytics.py` — digest entries/daily/highlights/{date} for `/analytics` |
| Debug | `/api/debug` | `debug.py` — ad-hoc read-only SQL + event-summary (LAN/localhost gated) |

> `pihole_proxy.py` registers an unprefixed reverse proxy (`/admin/*`, `/api/*` → Pi-hole), mounted LAST in `main.py` after every API route + the frontend catch-all.

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

**Activity detector.** POST `{mode, source, factors?}` to `/api/automation/activity` — `factors` = optional sub-signal detail for the analytics constellation. Engine enforces priority.

**Scheduled routine.** Build a `ScheduledTask` (from `backend.services.scheduler`) and call `scheduler.add_task(task)`. Persist config in `app_settings` under `{routine_name}_config`. Expose `POST /api/routines/{name}/test`.

**New automation mode.** Add per-light states in `automation_engine.py` → `ACTIVITY_LIGHT_STATES` under `day`/`evening`/`night` (+ `late_night` if needed). Each light should differ (spatial depth) — avoid `_uniform()`. Engine checks `mode_scene_overrides` DB table first. Mode brightness multipliers apply on top.

**App settings (SQLite).** `await save_setting(key, value_dict)` / `await load_setting(key)` (each opens its own session — no `db` arg). Sample keys (non-exhaustive — full list in `docs/PROJECT_SPEC.md` § "Database Schema → app_settings"): `morning_routine_config`, `time_schedule_config`, `mode_brightness_config`, `mode_volume_curves`, `watching_posture_config`, `camera_enabled`, `lux_calibration_config`.

**Source attribution on write endpoints.** Routes logging to `activity_events`/`light_adjustments`/`sonos_playback_events`/`scene_activations` pull caller identity via `source_from_request(request, fallback="...")` (`backend.api.auth`). Alexa lambda sets `X-Source: alexa:<intent>`; absent → route default (`api:<ip>`, `rest`, `manual`, etc.).

---

## Automation Modes

| Mode | Detection | Lighting Strategy |
|------|-----------|-------------------|
| `pregameday` | `GameDayService` ESPN polling, T-60 flip ahead of `gameday`; same priority (6) as gameday, flips to it at T-30 from the same source | Colts-tinted pre-game ambient + hype audio (TTS then Sonos). Spec: `docs/GAMEDAY_SPEC.md` |
| `gameday` | `GameDayService` ESPN polling, T-30 auto-flip, T+30 conditional clear | Colts blue L1 + warm-amber L2/L3/L4, kitchen pair preserved. `CelebrationOrchestrator` runs light + TTS sequences per scoring play (8s cooldown); WPA-driven TTS volume with apartment-context suppressions. Spec: `docs/GAMEDAY_SPEC.md` |
| `gaming` | Game binaries in `game_list.py` (NOT `javaw.exe` — JetBrains FP) | Neutral fill + blue/purple peripheral accents, warm desk-lamp bias. Night: deep blue ambient. Screen sync on L2, glisten eve/night. In an active League match, L2 + L5 shift to the champion's color (`LoLChampionService` → `champion_color_map`, bypassing screen-sync on those lamps) |
| `working` | Terminals + IDEs (powershell, pwsh, bash, claude, code, cursor, devenv, JetBrains, wezterm, alacritty) | ct-mode clean whites, desk-dominant. IES 1:3 monitor-ambient contrast. Night: L2 130/2700K + L1 60/2270K + kitchen OFF |
| `watching` | Media players (VLC, Plex, Stremio) — foreground-gated | Projector default: warm, dim, L2 as soft bias. Kitchen OFF evening+. **Zone/posture-aware**: `zone=desk` lifts L2 (now sourced from desktop pc_agent since 2026-05-27); `zone=bed` branches (reclined dim L1/L2; upright reading-bright) are **dormant** post Latitude→living-room move — no camera produces `zone=bed` |
| `social` | Manual override only (YAMNet `speech_multiple` gate abandoned 2026-05-09 — structurally unreachable; replacement direction deferred) | "Velvet Speakeasy" static: L1 dusty rose, L2 cognac amber, L3/L4 matched burnt-orange. Saturation does the work, no effect. 1s snap |
| `relax` | Manual override | "Moss & Candlelight": L1/L2 warm ember/honey, L3/L4 moss/sage (pendants stay static). Late-night "Moss & Ember": deeper ember + hunter-green. opal day / **none eve** / fire night+late_night — fire scoped to L1/L2 only |
| `cooking` | Manual override | L3+L4 paired peak 3500K (accurate food colors), L1 warm, L2 dim. 1s snap |
| `sleeping` | Manual only | "Good night" TTS on entry. Dim (bri=20 ember) BEFORE stopping the active effect to avoid 100% pop, then fade. Manual 24s fade off. Persistent override — no 4h timeout. **Sleeping floor** (`report_activity`): non-override *detected* sleeping (sleep-watcher `source=process`) is protected from idle-sensor displacement — only a foreground process report above idle (working/watching/gaming) wakes it; audio_ml/camera/ambient can't. Pauses media. PC sleep watcher suspends 60min after entry; cancels if mode leaves sleeping. |
| `idle` | No process detected, OR Win32 idle >10min, OR camera absent ≥30s | Falls through to time-based rules. After 180s of continuous idle (no Sonos, no fresh desk/process attendance), `ambient_relax` autonomous setter pushes to `relax` as the soft default |

**Mode priority:** `report_activity` guards against lower-priority cross-source displacement of a fresh higher-priority mode; same-source updates always pass. `SOURCE_STALE_SECONDS=300` — an owning source that hasn't reported in 5 min yields to lower-priority reports (prevents stale-lock).

**Mode transition speeds:** gaming 0.5s, gameday 1s, working 2s, watching 3s, cooking 1s, relax 4s, sleeping 5s.

**Scene drift:** After 30min in **relax**, subtle perturbation (±15 bri, ±1500 hue, 10s transitions) prevents staleness. Relax-only — functional modes need stable paired values.

**Kitchen pair rule:** L3 + L4 must match `bri` + `hue/sat` + on/off in functional modes (working, gaming, watching, cooking) and in the 6 guest party scenes — identical pendants shouldn't read as different colors. Free to diverge in relax + custom non-party scenes. Dashboard fuses them into a single "Kitchen" card via `LightCard`'s `linkedIds` prop; ApartmentViz shows them as distinct bulbs.

**Post-sunset warmth cutoff:** No CT-mode light drops below `ct=333` (~3000K) in evening/night. Watching's D65 bias is a daytime-only exception.

**Colorspace exclusivity:** `hue_service.set_light` forces `sat=0`, drops stray `hue` when `ct` is in the payload, and emits `sat` before `ct` (bridge is order-sensitive). Prevents the "greenish bedroom" bug.

**Effect reconciliation:** `_reconcile_effect` runs AFTER `_apply_state` so brightness is at target before the old effect stops (otherwise pops to 100%). 0.5s guard between stop+start.

**In-flight window:** Per-light write deadlines suppress `light_update` broadcasts until transition+0.5s. Poll loop 0.5s (demotes to 5s when v2 EventStream active); 3s max-age clamp clears stuck deadlines. v2 dispatcher honors the same window so echoes don't snap the UI mid-drag. Mid-drag uses `transitiontime=1`; release flush 0.4s.

**Manual light overrides:** Slider drags stamp `_manual_light_overrides[light_id]`; reconcile + screen-sync skip stamped lights. `PRESERVE_PER_LIGHT_OVERRIDE_SOURCES` keeps stamps through autonomous pushes (late-night rescue, fusion, predictor, zone+posture, timeout_4h). User-initiated mode changes (`api:*`, `manual`, `guest`, `rule_suggestion_accept:*`) wipe stamps; 4h auto-expiry in `run_loop`.

**Mode → scene overrides:** Any mode+time slot maps to a Hue bridge scene or curated preset via `mode_scene_overrides`, overriding default `ACTIVITY_LIGHT_STATES`.

**Late-night autopilot cascade:** (1) **22:00–06:00** — `ConfidenceFusion` weights down stale dev tools (`LATE_NIGHT_PROCESS_WEIGHT_FACTOR`). (2) **23:00+, no override, no Sonos, mode ∈ {working, idle}** — `run_loop` late-night-rescue → `relax`; skips when `is_at_desk_fresh()` OR `is_recent_process_working()` (PC-agent <10min). `working` has its own `late_night` state. (3) **DORMANT since 2026-05-27** — `_evaluate_watching_sleep_guard` (late_night watching + `zone=bed+reclined` 90min → sleeping) requires a bed-zone source no camera now produces. Kept (not deleted) pending light-touch desktop bed-detection; original behavior preserved in docstring + memory for revival.

**Ambient-relax soft default:** When `_current_mode == "idle"` continuously ≥180s (`IDLE_AMBIENT_RELAX_DWELL_SECONDS`) with no Sonos and both attendance vetoes negative, `run_loop` pushes `set_manual_override("relax", source="ambient_relax")`. Day-agnostic; catches the "stepped away after dinner" gap.

**Apartment-empty handling (no `away` mode):** When the Hue iOS app's "Leaving home" automation recalls a bridge_home all-off recipe, `_check_external_off` detects the all-off state, sets `_external_off_detected = True`, and `run_loop` `continue`s past every autonomous setter. Lights stay off until either `report_activity` fires a non-idle mode or `automation.signal_presence(source)` is called. **CameraService** calls `signal_presence("camera")` on absent→present so walking in releases the suppression before any PC activity. `away` mode shelved 2026-05-21 — see `project_away_mode_shelved.md` (a Latitude-mic audio source is parked: `project_latitude_audio_parked.md`).

---

## Dynamic Effects (Hue v2)

Effects: `candle`, `fire`, `sparkle`, `prism`, `glisten`, `opal`. Activate via `POST /api/scenes/effects/{name}` (all lights) or `.../effects/{name}/light/{id}` (single). **Effects flatten per-light HSB** to the effect's own color base — custom-palette scenes must use `effect: None`.

**EFFECT_AUTO_MAP** entries `{"effect": name, "lights": [...] | None}` — `lights=None` = all, list scopes to v1 IDs. Mappings: relax → opal day / **none eve** / fire night+late_night (fire scoped to L1/L2 so moss pendants stay static); watching → glisten eve/night; social, gaming, working, cooking → none. Candle removed from auto-map (color-lock persists through mode changes); manual candle still callable.

**Time periods:** `_get_time_period()` returns `day`/`evening`/`night`/`late_night`. `late_night` runs from `DaySchedule.late_night_start_hour` (default 23) until `wake_hour`. Only relax defines a `late_night` state; other modes fall back to `night`.

**Weather effect fallback:** When a mode has no auto-effect, weather overlays one — thunderstorm→sparkle, snow→opal (evening/night only, sparkle any time). Same-effect cycles skipped.

**Weather-aware brightness:** `LUX_WEATHER_BASELINE_SHIFT` raises effective baseline (POSITIVE values — counter-intuitive); `FUNCTIONAL_WEATHER_BRIGHTNESS` `(mode, period, cond)` grid spans gaming/working/watching × day/evening/night. `LightingPreferenceLearner` keyed `mode:period:weather`. `brightness_scan_loop` surfaces `kind="brightness"` suggestions via NotifierService. Memory: `project_weather_aware_brightness_2026_05_18.md`.

---

## Database Schema

Full schema with column types: `docs/PROJECT_SPEC.md` § "Database Schema". Live tables: `app_settings`, `scenes`, `mode_playlists`, `music_artists`, `taste_profile`, `recommendations`, `recommendation_feedback`, `mode_scene_overrides`. Event tables (Phase 3): `activity_events`, `light_adjustments`, `sonos_playback_events` (`weather_class` column added Phase B for bandit context), `scene_activations`, `learned_rules`, `ml_decisions`, `ml_metrics`. Personality: `mood_samples` (7-day rolling, pruned at boot), `mood_calibration`, `vibe_requests` (Phase C placeholder). Data retention: per-table via nightly `retention_sweep` — 90-day rolling, with `mood_samples` 7-day and `ml_decisions` 21-day exceptions (ml_decisions logs ~75k rows/day; 21d plateau ≈ 1.1–1.2 GB).

---

## Configuration Reference

### .env Variables

**Full list + inline docs:** `.env.example` (repo root). **Source of truth:** `backend/config.py` (pydantic `BaseSettings`). Keep those two in sync — don't re-enumerate the vars here (this block kept drifting).

Non-obvious runtime behavior worth knowing without opening the files:
- `HOME_HUB_API_KEY` — gates every write endpoint; **unset → writes 503**. Localhost (kiosk) + RFC1918 LAN auto-bypass; `TRUSTED_LAN_IPS` pins extra public IPs. `HOME_HUB_SKILL_TOKEN` is the tunnel-origin pair for the Alexa Skill (requires BOTH).
- `NTFY_TOPIC` — the topic name **IS** the auth on hosted ntfy.sh; treat as a secret. Unset → desktop toast still fires via WS, phone push skipped.
- `ZONE_POSTURE_RULE_APPLY` — DORMANT since 2026-05-27 (no `zone=bed` source post Latitude→living-room move); kept for a future bed-zone source.
- `PLANT_APP_ALLOW_INSECURE` — default false **rejects `http://` at boot**; only flip if upstream lacks TLS.
- `LOCAL_IP` — server LAN IP; Sonos fetches the TTS MP3 from here, so `localhost` won't work.

### SQLite Persisted Settings (`app_settings` table)

**Full key reference** (all ~22 keys with shapes + write paths): `docs/PROJECT_SPEC.md` § "Database Schema → app_settings". Access via `await save_setting(key, value)` / `load_setting(key)` (each opens its own session — no `db` arg).

Keys you **hand-edit** (no UI; edit the row directly):
- `guest_vibe_playlists` — `{hype, singalong, throwback}` → Sonos favorite_title; missing keys fall back to `GUEST_VIBE_DEFAULTS` in `routes/guest.py`.
- `ambient_streams` — curated internet-radio nature streams `{wclass: [{id, label, url}]}`; weather-class keys auto-play (file fallback when down), others manual-pick. Seeded from `DEFAULT_STREAM_LIBRARY`; play via `play_uri(force_radio=True)`.
- `champion_color_map` — `{ChampionName: {r, g, b}}` → bedroom lamp in `gaming` mode. Seed: `python -m scripts.seed_champion_colors`.

---

## Network Devices

| Device | IP | Notes |
|--------|----|-------|
| **Latitude 7420 (production)** | **192.168.86.210** | **Ubuntu 24.04. Backend + ambient as systemd user services, Firefox kiosk via GNOME autostart, Pi-hole v6 Docker. Always-on. Static IP.** |
| Windows desktop (dev) | 192.168.86.30 | Code edits, `git push`, local testing. PC activity detector via Task Scheduler (`--server http://192.168.86.210:8000`). MCP uses `HOME_HUB_URL`. Desktop notifier autostarts via Task Scheduler `Home Hub Desktop Notifier` (At-Logon, `%LOCALAPPDATA%\HomeHub\HomeHubNotifier.exe`). Nightly backup pulls via Task Scheduler `Home Hub Pihole Backup` (04:30) + `Home Hub Data Backup` (04:40) → `C:\Users\antho\HomeHubBackups\`, then `Home Hub Offsite Backup` (04:55) pushes encrypted snapshots offsite via restic → Backblaze B2; strategy in `~/.claude/runbooks/backup-strategy.md`. |
| Hue Bridge | 192.168.86.50 | Self-signed SSL cert |
| Sonos Era 100 | 192.168.86.157 | Living room. `SONOS_IP` hardcoded in `.env` to defeat cold-boot SSDP race. |
| Android Tablet | 192.168.86.209 | Kiosk display (blank page deferred) |

**Network (post-2026-06 Google Wifi migration):** Apartment runs behind a personal Google Wifi (`192.168.86.0/24`, double-NAT behind the ISP router). Network-wide Pi-hole DNS is set on the router, so devices use Pi-hole automatically — **no per-device DNS needed**. Google Wifi proxies DNS (clients see `.86.1`), so per-device Pi-hole attribution is lost and local `.lan` names don't resolve through the router. Guests join the **main** network — full-trust "trust the room" by design (`auth.py` trusts all LAN callers, so an admitted guest can drive the apartment + read the behavioral DB; `GET /api/camera/snapshot` is the one exception, locked to localhost+key). iOS: only set Private WiFi Address → Fixed (+ optional DHCP reservation `192.168.86.148`) for a stable IP.

---

## Roadmap

| Phase | Status | Focus |
|-------|--------|-------|
| 1–2 | ✓ | Core foundation + dashboard. See `docs/PROJECT_SPEC.md` |
| 3: Intelligence & Voice | ✓ | Fauxmo + Custom Skill (Lambda→Tunnel→:8002→:8000). Rule engine + persistent suggestion UX shipped |
| 4: Game Day | A+B+C ✓; preseason 2026-08-13, reg-season 2026-09-13 | See `docs/GAMEDAY_SPEC.md`. SEQUENCES iteration + preseason validation pending |
| 5: Polish & Expand | Future | Apple Music API, full autopilot, bar app widget |

---

## Technical Limitations

- **Hue bridge SSL** — self-signed cert; httpx calls require `verify=False`.
- **Sonos TTS** — needs server LAN IP (`LOCAL_IP`); Sonos fetches the MP3 over the network, `localhost` won't work.
- **Sonos Apple Music** — SoCo plays tracks by URI (v0.26.0+) but can't browse the catalog ($99/yr Apple Music API).
- **phue2 import quirk** — pip package `phue2` imports as `from phue import Bridge`.
- **Screen sync Windows-only** — mss capture is Windows-only; breaks on headless Linux.
- **edge-tts needs internet** — falls back to gTTS (also internet). No offline TTS.
- **SQLite concurrency** — single-writer; high-frequency event logging may need batching.
- **Indiana timezone** — `America/Indiana/Indianapolis` DST rules; scheduling must set it explicitly.
- **Fauxmo** — on/off per virtual device; complex commands use the Custom Skill.
- **1080p landscape primary** — backgrounds designed for it; degrade gracefully on mobile.
- **Android tablet blank page** — deferred.

Non-goals + scope discussion: `docs/PROJECT_SPEC.md`.

