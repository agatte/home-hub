# Home Hub — Project Spec

> A personal command center that runs your apartment — lights, music, routines — learns how you live, and comes alive for the moments that matter.

## Vision

Home Hub is an always-on personal command center built for one apartment and one person. It controls Philips Hue lights and a Sonos Era 100 speaker from a single, visually striking dashboard that's always running on a dedicated laptop display. The system is deeply integrated into daily life — it detects what you're doing, adjusts lighting and music to match, and learns your patterns over time until it can run on full autopilot.

The dashboard isn't a boring control panel. It's a living interface with bold, mode-aware themed backgrounds — a retro pixel art landscape during gaming, a scrolling pixel city during working, flowing aurora borealis for relax, a 3D moon scene over a city silhouette while sleeping. It shows everything at a glance: current mode, light colors, now playing, weather, upcoming routines. It's also a hub for other personal projects (plant tracking app, future bar app) with animated widget cards that link out to each one.

The core focus is getting lights and music working seamlessly. Everything else builds on that foundation — voice control via Alexa, game day celebrations for the Colts, and an intelligence layer that observes everything (mode changes, manual overrides, music choices, light adjustments, routine interactions) and gradually takes over.

## Goals

- **Lights and music first** — These are the foundation. Everything else builds on getting light control and mode-aware music playback working flawlessly
- **Always-on command center** — Runs 24/7 on a dedicated foldable laptop (1080p landscape), always displaying the dashboard. Also works cleanly on mobile
- **Invisible automation** — The system detects activity, adjusts lights and music, and manages routines without manual input. Gradual transitions, activity-aware timing
- **Full autopilot learning** — Observes all interactions and behavior patterns, starts with simple rules ("Friday 8pm = gaming"), evolves toward autonomous decision-making with subtle nudge notifications
- **Bold, living UI** — Animated backgrounds that change with mode and time of day. Not a generic dashboard — a visual experience that reflects what's happening in the apartment
- **Voice control** — Alexa integration (Fauxmo locally first, custom skill later) for hands-free mode switching, music control, and routine triggers
- **Game day magic** — Colts games become a synchronized experience: lights, sound, TTS celebrations, live scoreboard, pixel art field
- **Hub for everything** — Widget cards for plant app, future bar app, and other projects. The dashboard is the home screen for your digital life
- **Personal, not generic** — Every rule, mode, animation, and routine is tuned for one person's actual apartment and habits

## Current State

### Lighting

- Full Philips Hue control via dual APIs (v1/phue2 for basic control + 1s polling, CLIP v2 for native scenes and dynamic effects)
- **Color temperature (CT/mirek) support** — first-class parameter alongside HSB for precise Kelvin control (2000K–6500K)
- Time-based automation: wake, daytime, evening, night periods with separate weekday/weekend schedules
- Activity-driven modes: gaming, working, watching, relax, movie, social — each with per-light state definitions
- **Science-based per-mode lighting** — each mode uses distinct per-light variation (not uniform): working uses ct-mode clean whites, gaming uses blue/purple accents, relax uses warm gradients, watching uses SMPTE-inspired neutral bias. Night working: desk lamp at 3200K (bri=150) + dim ambient fill to reduce monitor contrast to ~3:1
- **Mode-specific transition speeds** — gaming snaps (0.5s), relax fades gently (4s), watching/movie cinematic (3s), sleeping gradual (5s) via MODE_TRANSITION_TIME
- **Scene drift** — subtle random perturbation (±15 bri, ±1500 hue) every 30min during long sessions with 10s imperceptible transitions
- **Mode → scene overrides** — any mode+time slot can be mapped to a Hue bridge scene or curated preset via `mode_scene_overrides` table, checked before hardcoded ACTIVITY_LIGHT_STATES
- **20 curated scenes** across 7 categories (functional, cozy, moody, vibrant, nature, entertainment, social) using color harmony theory — each scene defines per-light states with varied hue, saturation, and brightness for depth
- **Custom scene CRUD** — user-created scenes persisted to SQLite with category and optional paired effect
- **Effect auto-activation** — EFFECT_AUTO_MAP: opal (relax/day), candle (relax/eve+night), glisten (gaming/eve+night)
- Native Hue scenes and dynamic effects (candlelight, fireplace, sparkle, prism, glisten, opal) with 5-min cache on bridge scene fetches
- Social mode sub-styles (color cycle, club, rave, fire & ice)
- Screen sync for gaming (bedroom lamp mirrors dominant screen color via mss capture)
- Manual override with 4-hour auto-timeout
- Configurable per-mode brightness multipliers

### Audio & Music

- Sonos Era 100 control: play/pause, volume, next/prev, favorites
- Mode-to-playlist mapping — each activity mode can auto-play a Sonos favorite
- Smart auto-play: plays mapped favorite when Sonos is idle on mode change, suggests via toast if busy
- Apple Music library import with taste profile generation (genre distribution, top artists)
- Music discovery via Last.fm similar artists + iTunes Search 30s previews
- Recommendation feedback system (like/dismiss with scoring)
- TTS via edge-tts with duck-and-resume (pauses music, plays speech, resumes)

### Automation

- PC activity detection (psutil process monitoring for games/media)
- Ambient noise monitoring (Blue Yeti mic RMS for party detection)
- Mode priority system: gaming (5) > social (4) > watching (3) > working (2) > idle (1) > away (0)
- Morning routine: weather (OpenWeatherMap) + commute (Google Maps) TTS at configurable time
- Evening wind-down: dims lights, activates candlelight, lowers volume, TTS announcement
- All routine config persisted to SQLite, hot-reloadable

### Dashboard — Themed Backgrounds

- **Per-mode themed backgrounds** — each mode has a distinct visual scene:
  - **Gaming**: `PixelScene.svelte` — code-drawn retro pixel art landscape (480×270 scaled 4×) with parallax mountains, walking sprites, twinkling stars, floating particles, shooting stars
  - **Working**: `ParallaxScene.svelte` — AI-generated pixel art city street (PNG sprite sheet) with JS-driven parallax scroll, code-drawn sky gradient synced to weather/time of day
  - **Relax**: `AuroraScene.svelte` — simplex noise-driven aurora borealis curtains with twinkling stars and treeline silhouette
  - **Sleeping**: `MoonScene.svelte` — Three.js/Threlte 3D scene with orbiting moon, GLSL sky shader, procedural city silhouette with flickering windows, star field
  - **Other modes**: `GenerativeCanvas.svelte` — three-layer system (gradient mesh blobs + flow-field particles + geometric overlay) as fallback
- All scenes react to music (Sonos playing = faster motion, brighter effects)
- `ModeBackground.svelte` routes the active mode to its scene component; only one scene renders at a time
- **No sidebar** — floating glassmorphic bottom pill bar (Home, Music, Analytics, Settings) + mode overlay (Bebas Neue 36px all-caps mode name with character-stagger animation) + Now Playing chip
- **Glass cards** — all widgets use `backdrop-filter: blur(12px)` with staggered entrance animations
- **Auto-hide on idle** — after 60s of no interaction, cards fade out leaving just the background scene + mode name. Tap anywhere to wake.
- **Weather widget** — OpenWeatherMap current conditions with 10-minute cache
- Four pages: Home (controls + weather + scenes), Music (discovery + mapping), Analytics (mode distribution, patterns, rules, activity feed), Settings (configuration)
- Real-time WebSocket sync — changes from Alexa, Hue app, or physical switches reflected instantly
- PWA-capable for phone/tablet kiosk mode
- Optimistic updates for responsive feel
- Music suggestion toasts on mode change
- Typography: Bebas Neue (display/mode headlines) + Source Sans 3 (body/UI)

### Network & DNS

- **Pi-hole v6** running in Docker (host networking) on the Latitude for network-wide DNS ad blocking
- 2M+ domains blocked across 10 curated blocklists (ads, malware, phishing, tracking, Windows telemetry)
- Local DNS records for all network devices: `homehub.local`, `pihole.local`, `hue.local`, `sonos.local`, `desktop.local`, `tablet.local`
- Dashboard Network widget showing real-time stats (block percentage, total queries, blocklist size, active clients)
- Settings page management for local DNS records and blocklists (add/remove, one-click bulk add)
- Per-device DNS configuration (apartment router is locked — no DHCP DNS control)
- Pi-hole admin UI at `http://192.168.1.210:8080/admin`

### Known Issues & Pain Points

**Automation timing:**
- ~~Evening transition is too abrupt~~ — fixed: 30-minute gradual lerp before winddown_start_hour
- ~~Evening wind-down triggers at fixed time regardless of activity~~ — fixed: delays 30 min and retries up to 4x if gaming/watching/social/working
- ~~Mode detection has noticeable lag between activity start and mode switch~~ — fixed: dropped PC agent POLL_INTERVAL from 15s to 5s (worst-case 5s, average ~2.5s). The backend processes activity reports synchronously on POST, so the polling interval was the entire lag budget.

**Music:**
- ~~Mode-to-playlist mapping is too rigid~~ — fixed: vibe tagging supports multiple favorites per mode with energetic/focus/mellow/background/hype tags
- ~~Auto-play is unreliable — sometimes doesn't trigger, sometimes plays when unwanted~~ — fixed: queue-based playback for cloud favorites with DIDL metadata, graceful failure for unsupported "shortcut" favorites (Apple Music artist/station containers without playable URIs), and the music page UI now flags those unsupported favorites in the mode→playlist mapper so they can't be silently mapped
- Sonos favorites are limiting — can't express "high energy electronic" as a vibe, only specific playlists
- Last.fm recommendations aren't useful — poor relevance to actual taste

**UI:**
- ~~Too many taps for common actions~~ — fixed: quick action pill buttons + scene browser with category tabs
- ~~Visual design feels generic and unpolished~~ — fixed: themed mode backgrounds (pixel art, parallax city, aurora, 3D moon), glass cards, Bebas Neue typography
- ~~Hard to read at a glance~~ — fixed: mode overlay with large mode name, weather widget, Now Playing chip
- Mobile experience could use more polish
- ~~Three-page layout doesn't serve command center vision~~ — fixed: full-screen layout with floating nav, no sidebar

**Infrastructure (from April 2026 audit):**
- ~~CORS allows all origins~~ — fixed: locked to specific LAN IPs (localhost, Latitude, dev machine, tablet)
- ~~No tests~~ — fixed: pytest suite with 101 tests across 8 files (automation engine, music mapper, scheduler, weather, pihole, API routes, WebSocket). GitHub Actions CI runs full suite on push
- ~~No rate limiting~~ — fixed: slowapi (120/min default, 10/min on override/TTS, 5/min on file import)
- ~~No log rotation~~ — fixed: RotatingFileHandler (5MB per file, 3 backups, 20MB max)
- ~~WebSocket crashes on malformed JSON~~ — fixed: try-catch guard around json.loads()
- ~~No database backup automation~~ — fixed: daily SQLite backup cron on Latitude (4 AM, 7-day retention)
- ~~Systemd service files not version-controlled~~ — fixed: `deployment/` dir with service units + kiosk desktop entry
- ~~Dead frontend code (Sidebar, Header, modeIcon)~~ — fixed: deleted
- ~~Weather widget shows current temp as high/low~~ — fixed: fetches daily range from OWM forecast API
- ~~No structured logging~~ — fixed: python-json-logger (JSON to file for machine parsing, text to console for humans)
- ~~No uptime monitoring~~ — fixed: Uptime Kuma on port 3002 monitoring Home Hub backend + Pi-hole health, with alerting
- ~~No bundle analysis~~ — fixed: vite-plugin-visualizer (`npm run analyze` generates interactive treemap)
- No authentication on API endpoints (acceptable for LAN-only, revisit if Cloudflare Tunnel added)

**Open bugs (from April 2026 audit):**
- ~~GenerativeCanvas store subscriptions may leak memory~~ — false positive: subscriptions are manual `subscribe()` calls with proper `onDestroy` cleanup (lines 218-224)
- ~~Silent API error swallowing~~ — fixed: `api.js` now uses `safeFetch()` wrapper that pushes errors to an `errors` store. `ErrorToast.svelte` renders red toasts in bottom-left with 5s auto-dismiss

**Ambient intelligence features (April 2026):**
- ~~Now Playing Ambient Typography~~ — shipped: `NowPlayingIdle.svelte` fills kiosk with giant song title/artist when idle + Sonos playing; album art as blurred ambient glow
- ~~Sunrise Alarm Light Ramp~~ — shipped: 30-min bedroom lamp warm-up (CT 500→250, bri 1→150) before morning routine via ScheduledTask
- ~~Weather-Reactive Lighting~~ — shipped: subtle light adjustments during idle modes (thunderstorm=purple, rain=cool, sunset=golden, overcast=dim, snow=bright+cool)

---

## System Architecture

### Current Architecture

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
   │   └── mode-change callbacks ──> MusicMapper, RuleEngine check
   ├── MusicMapper ────────────────> mode change → smart Sonos auto-play
   ├── EventQueryService ──────────> aggregation over event tables (patterns, timeline)
   ├── RuleEngineService ──────────> learns time-based mode patterns → nudge suggestions
   ├── WeatherService ─────────────> OpenWeatherMap (10-min cache)
   ├── ScreenSyncService (mss) ────> dominant screen color → bedroom lamp
   ├── Scheduler ──────────────────> morning routine, evening wind-down
   ├── LibraryImportService ───────> Apple Music XML → taste profile
   ├── RecommendationService ──────> Last.fm + iTunes → discovery feed
   ├── WebSocketManager ───────────> bidirectional real-time sync
   ├── PiholeService (httpx) ────────> Pi-hole v6 API (DNS stats, blocklists, local DNS)
   ├── SQLite (aiosqlite + SQLAlchemy async)
   └── Serves SvelteKit static build from frontend-svelte/build/ (via FRONTEND_BUILD env)

Pi-hole (Docker container, host networking, same machine)
   └── pihole/pihole:latest ───────> DNS on :53, web admin on :8080
       ├── Network-wide ad/malware/tracking blocking (2M+ domains)
       └── Local DNS (homehub.local, pihole.local, hue.local, etc.)

Uptime Kuma (Docker container, port 3002, same machine)
   └── louislam/uptime-kuma:1 ─────> monitors Home Hub :8000/health + Pi-hole :8080
       └── Alerting via Telegram/Pushover on downtime

PC Agent (split across two machines, parallel-forever architecture)
   ├── activity_detector.py  ON dev machine (192.168.1.30) ──> POST http://192.168.1.210:8000/api/automation/activity
   │                         (psutil process detection only useful where Anthony games/works)
   └── ambient_monitor.py    ON Latitude (192.168.1.210) ────> POST http://localhost:8000/api/automation/activity
                             (PyAudio RMS via built-in mic near the apartment living space)
```

**Deployment note:** As of 2026-04-11 the "dedicated laptop" from the
Target Architecture is real — a Dell Latitude 7420 running Ubuntu
24.04 LTS at 192.168.1.210. The FastAPI backend, ambient monitor, and
Firefox kiosk all run there as systemd user services + GNOME
autostart. The Windows dev machine (192.168.1.30) stays as a
workstation for code editing + `git push`, and runs the PC activity
detector pointed at the Latitude. See the Deployment section below
and `CLAUDE.md` for operational details.

### Target Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Dedicated Laptop (always-on, 1080p landscape)                      │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  FastAPI Server (port 8000)                                   │  │
│  │  ├── Device Services (Hue, Sonos, TTS, ScreenSync)           │  │
│  │  ├── AutomationEngine (time + activity + learned rules)       │  │
│  │  ├── MusicMapper (vibe-based, multi-playlist)                 │  │
│  │  ├── Scheduler (routines)                                     │  │
│  │  ├── EventLogger → writes all events to DB                    │  │
│  │  ├── Fauxmo (Alexa virtual devices, UPnP)                    │  │
│  │  ├── WebSocketManager                                         │  │
│  │  └── Serves SvelteKit static build                            │  │
│  └──────────────┬────────────────────────────────────────────────┘  │
│                 │ shared database                                    │
│  ┌──────────────▼────────────────────────────────────────────────┐  │
│  │  Learning Engine (separate process)                            │  │
│  │  ├── Reads event tables (activity, lights, playback, etc.)    │  │
│  │  ├── Pattern detection (time, day-of-week, sequences)         │  │
│  │  ├── Rule generator (auto-apply when >90% confidence)         │  │
│  │  ├── Internal API (main server queries for predictions)       │  │
│  │  └── Writes learned_rules + predictions back to DB            │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  Full-screen browser → SvelteKit + Threlte (Three.js) dashboard    │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ LAN (WiFi)
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
   ┌──────▼──────┐    ┌───────────▼────────┐    ┌──────────▼───────┐
   │ Gaming PC   │    │ Hue Bridge         │    │ Sonos Era 100    │
   │ (ethernet)  │    │ (Zigbee → lights)  │    │ (UPnP)          │
   │ PC Agent ───┼──> │                    │    │                  │
   │ POST /api/  │    └────────────────────┘    └──────────────────┘
   └─────────────┘
          │
   ┌──────▼──────┐         ┌───────────────────┐
   │ Phone (PWA) │         │ Alexa Echo         │
   │ Mobile view │         │ ← Fauxmo (UPnP)   │
   └─────────────┘         │ ← Custom Skill     │
                           └───────────────────┘

External APIs (cloud):
   ├── OpenWeatherMap (weather)
   ├── Google Maps (commute)
   ├── Last.fm (music discovery)
   ├── iTunes Search (previews)
   ├── ESPN (game day, future)
   ├── Apple Music API (dynamic playlists, future, $99/yr)
   └── PostgreSQL (cloud-hosted, Supabase free tier)
```

### Key Architecture Decisions

- **Two-process model:** Main server handles real-time control. Learning engine runs separately, reads events from the shared DB, computes patterns, and exposes an internal API for predictions. Main server queries the learning engine before making automation decisions.
- **Database migration path:** SQLite now → cloud PostgreSQL (Supabase free tier) when event volume grows. SQLAlchemy abstraction makes the switch straightforward. Event data uses 90-day rolling window with older data aggregated into daily/weekly summaries.
- **Frontend rewrite (complete):** React 18 → SvelteKit + Threlte (Three.js). Parity-pass rewrite landed in commit `b96d062` as part of Phase 2a; the React tree was deleted after a clean burn-in cycle. Subsequently redesigned as "Living Ink" — generative canvas background, glassmorphic cards, floating nav, Bebas Neue + Source Sans 3 typography. Backend serves the static build via the `FRONTEND_BUILD` env var (default `frontend-svelte/build`).
- **PC Agent over network:** Gaming PC (wired ethernet) POSTs to laptop (WiFi). Same router, same subnet. Static IP or mDNS for discovery.
- **Alexa two-phase:** Fauxmo (local UPnP, free) for immediate voice control. Custom Alexa Skill + Cloudflare Tunnel for full flexibility later.

### Tech Stack

**Current:**

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.8+, FastAPI, uvicorn, async/await |
| Database | SQLite via aiosqlite + SQLAlchemy 2.0 async ORM |
| Frontend | SvelteKit 2 + Svelte 4, Threlte 7 (Three.js), Vite 5, Svelte writable stores, Lucide icons, simplex-noise |
| Hue (v1) | phue2 library (imports as `from phue import Bridge`) |
| Hue (v2) | CLIP API via httpx (self-signed cert, `verify=False`) |
| Sonos | SoCo library (UPnP, zero-auth, SSDP discovery) |
| TTS | edge-tts (Microsoft neural voices), gTTS fallback |
| Screen Sync | mss (screen capture), RGB→HSB conversion |
| PC Agent | psutil (process detection), PyAudio (ambient noise) |
| DNS / Ad Blocking | Pi-hole v6 (Docker, host networking), session-based REST API |
| Config | pydantic-settings, python-dotenv |
| Timezone | America/Indiana/Indianapolis |

**Target (additions/changes):**

| Layer | Technology | Notes |
|-------|-----------|-------|
| Database | PostgreSQL (Supabase) | Migration from SQLite for event volume |
| Voice Control | Fauxmo (phase 1), Custom Alexa Skill + Lambda (phase 2) | Local UPnP → cloud skill |
| Tunnel | Cloudflare Tunnel (free) | For Alexa Skill → local API |
| Learning | Separate Python process, scikit-learn or rule-based | Reads events, writes predictions |
| External Widgets | HTTP polling or WebSocket to plant app / bar app | Status data for dashboard cards |

### Database Schema

**app_settings** — Key-value config store
| Column | Type | Notes |
|--------|------|-------|
| key | String(100) | PK. Config key identifier |
| value | JSON | Serialized config object |
| updated_at | DateTime | UTC, auto-updated |

**scenes** — User-created light presets
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| name | String(100) | Unique scene name |
| light_states | JSON | Per-light state objects (supports hue/sat/bri and ct) |
| category | String(50) | Scene category: custom, functional, cozy, moody, vibrant, nature, entertainment, social |
| effect | String(50) | Optional paired Hue effect (candle, fire, glisten, etc.) |
| created_at | DateTime | UTC |

**mode_playlists** — Activity mode → Sonos favorite mapping
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| mode | String(50) | gaming, working, watching, social, relax, movie |
| favorite_title | String(200) | Sonos favorite name |
| vibe | String(50) | Single vibe tag: energetic, focus, mellow, background, hype |
| vibe_tags | JSON | Array of vibe descriptors e.g. `["high energy", "electronic", "instrumental"]` |
| auto_play | Boolean | Auto-start on mode change |
| priority | Integer | Playback priority — higher wins when multiple favorites match a vibe (default 0) |
| created_at | DateTime | UTC |

**music_artists** — Library import data
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| name | String(200) | Unique artist name |
| genres | JSON | Array of genre tags |
| play_count | Integer | From Apple Music library |
| track_count | Integer | Tracks in library |
| rating_avg | Float | User rating average |
| source | String(20) | "import" or "discovery" |
| similar_artists | JSON | Array of similar artist names |
| similar_fetched_at | DateTime | Last.fm sync timestamp |
| created_at | DateTime | UTC |

**taste_profile** — Aggregated music profile (singleton)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| genre_distribution | JSON | Genre → percentage mapping |
| top_artists | JSON | Top N artists by play count |
| mode_genre_map | JSON | Mode → genre list mapping |
| import_track_count | Integer | Total tracks imported |
| import_artist_count | Integer | Total unique artists |
| last_import_at | DateTime | Last library import |
| created_at | DateTime | UTC |

**recommendations** — Music recommendations
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| artist_name | String(200) | Artist |
| track_name | String(300) | Nullable |
| album_name | String(300) | Nullable |
| preview_url | String(500) | iTunes 30s preview |
| artwork_url | String(500) | Album artwork |
| itunes_url | String(500) | iTunes link |
| source_mode | String(50) | Mode this rec is for |
| reason | String(500) | Why recommended |
| score | Float | Confidence score |
| status | String(20) | pending, liked, dismissed |
| created_at | DateTime | UTC |

**recommendation_feedback** — User feedback on recs
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| recommendation_id | Integer | FK → recommendations.id |
| action | String(20) | "liked" or "dismissed" |
| created_at | DateTime | UTC |

**activity_events** — Mode transition log (learning input)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| mode | String(50) | Mode that was activated |
| previous_mode | String(50) | Mode before transition |
| source | String(50) | What triggered: time, process, ambient, manual, alexa, learned |
| started_at | DateTime | UTC, when mode began |
| ended_at | DateTime | UTC, nullable — filled when mode ends |
| duration_seconds | Integer | Computed on end |
| day_of_week | Integer | 0=Monday, for pattern analysis |
| hour_of_day | Integer | 0-23, for pattern analysis |

**light_adjustments** — Manual light change log
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| light_id | String(10) | Which light |
| trigger | String(20) | manual, automation, scene, override |
| on | Boolean | Nullable |
| bri | Integer | Nullable |
| hue | Integer | Nullable |
| sat | Integer | Nullable |
| mode_at_time | String(50) | Active mode when change happened |
| created_at | DateTime | UTC |

**sonos_playback_events** — Playback session log
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| artist | String(200) | Nullable |
| track | String(300) | Nullable |
| favorite_title | String(200) | Nullable — which favorite was playing |
| trigger | String(20) | auto_play, manual, alexa, suggestion_accepted |
| mode_at_time | String(50) | Active mode when playback started |
| started_at | DateTime | UTC |
| ended_at | DateTime | UTC, nullable |
| duration_seconds | Integer | Computed on end |
| skipped | Boolean | Was track skipped before finishing |

### Future Database Tables

**routine_executions** — Routine run log
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| routine_name | String(50) | morning_routine, winddown_routine |
| status | String(20) | success, partial_failure, skipped, error |
| error_message | String(500) | Nullable |
| executed_at | DateTime | UTC |

**user_interactions** — Dashboard action log
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| action | String(50) | page_view, mode_override, light_tap, quick_action, etc. |
| detail | JSON | Action-specific data |
| page | String(50) | Which page/section |
| created_at | DateTime | UTC |

**mode_scene_overrides** — Maps mode+time to a Hue scene, overriding default ACTIVITY_LIGHT_STATES
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| mode | String(50) | Activity mode (gaming, working, etc.) |
| time_period | String(20) | day, evening, or night |
| scene_id | String(200) | Preset name or bridge UUID |
| scene_source | String(20) | "preset" or "bridge" |
| scene_name | String(200) | Display name |
| created_at | DateTime | UTC |

**learned_rules** — Frequency-based rules learned from activity event patterns
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| day_of_week | Integer | 0=Monday, 6=Sunday |
| hour | Integer | 0-23, local time (Indiana) |
| predicted_mode | String(50) | Mode to suggest (gaming, working, etc.) |
| confidence | Float | 0.0-1.0, percentage of events matching this mode at this slot |
| sample_count | Integer | Total events at this time slot |
| enabled | Boolean | User can disable individual rules |
| created_at | DateTime | UTC |
| updated_at | DateTime | UTC |

UniqueConstraint on (day_of_week, hour). Rules regenerated every 6 hours from 30 days of activity_events. Minimum thresholds: 70% confidence, 3 samples. Idle/away modes excluded as predictions.

**Data retention policy:** 90-day rolling window for raw events. Older data aggregated into daily/weekly summaries stored in a separate `event_summaries` table. Aggregation runs as a scheduled task in the learning engine.

### WebSocket Protocol

**Endpoint:** `ws://host:8000/ws`

All messages are JSON with `type` + `data` fields.

#### Server → Client

| Type | Trigger | Data |
|------|---------|------|
| `connection_status` | On connect | `{hue: bool, sonos: bool, build_id: str}` |
| `mode_update` | On connect + mode change | `{mode, source, manual_override}` |
| `light_update` | Polling detects change | `{light_id, name, on, bri, hue, sat, ct, colormode, reachable}` |
| `sonos_update` | Polling detects change | `{state, track, artist, album, art_url, volume, mute}` |
| `music_auto_played` | Auto-play triggered | `{mode, title}` |
| `music_suggestion` | Sonos busy, playlist available | `{mode, title, message}` |
| `mode_suggestion` | Rule engine nudge (idle + rule matches) | `{rule_id, predicted_mode, confidence, sample_count, message}` |
| `mode_suggestion_dismissed` | User dismissed nudge | `{}` |

`build_id` is the short git SHA of the running backend, computed once at startup. The frontend stashes the first one it sees per page session and reloads `window.location` if a later `connection_status` (after a WS reconnect, e.g. post-deploy) reports a different value. This is what makes the kiosk dashboard auto-refresh after `scripts/deploy.sh` instead of needing a manual F5.

#### Client → Server

| Type | Data |
|------|------|
| `light_command` | `{light_id, on?, bri?, hue?, sat?, transitiontime?}` |
| `sonos_command` | `{action: play\|pause\|next\|previous\|volume, volume?}` |

#### Future Message Types

**Server → Client (new):**

| Type | Trigger | Data |
|------|---------|------|
| ~~`learning_nudge`~~ | Shipped as `mode_suggestion` above | — |
| `alexa_command` | Voice command received | `{command, source: "fauxmo"\|"skill", result}` |
| `game_update` | ESPN poll detects change | `{score_home, score_away, quarter, clock, possession, down, distance}` |
| `celebration` | Scoring play detected | `{play_type: "touchdown"\|"field_goal"\|"big_play"\|"turnover", description}` |
| `game_status` | Game state change | `{status: "upcoming"\|"active"\|"halftime"\|"final", opponent, kickoff_time}` |
| `widget_data` | External app status update | `{app: "plant"\|"bar", data: {...}}` |
| `animation_trigger` | Backend triggers a visual event | `{animation: "celebration_burst"\|"mode_transition", params: {...}}` |

**Client → Server (new):**

| Type | Data |
|------|------|
| `quick_action` | `{action: "movie_night"\|"bedtime"\|"leaving"\|"game_day"}` |
| `nudge_response` | `{nudge_id, accepted: bool}` |
| `interaction_log` | `{action, detail, page}` — for learning system |

### API Routes

**Prefix:** All REST endpoints use `/api/` (flat, no versioning — single client, single developer). Health at `/health` (no prefix).

#### System

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | System status, device connectivity, WebSocket client count |

#### Lights — `/api/lights/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/lights` | All light states |
| GET | `/api/lights/{id}` | Single light state |
| PUT | `/api/lights/{id}` | Set light state (`on, bri, hue, sat, ct, transitiontime`) |
| POST | `/api/lights/all` | Set all lights to same state |

#### Scenes & Effects — `/api/scenes/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/scenes` | List all scenes (curated presets + custom + bridge native) |
| POST | `/api/scenes/{id}/activate` | Activate scene (routes curated, custom, or bridge by ID) |
| POST | `/api/scenes/custom` | Create custom scene |
| GET | `/api/scenes/custom` | List custom scenes |
| PUT | `/api/scenes/custom/{id}` | Update custom scene |
| DELETE | `/api/scenes/custom/{id}` | Delete custom scene |
| GET | `/api/scenes/effects` | List available dynamic effects |
| POST | `/api/scenes/effects/{name}` | Apply effect to all lights |
| POST | `/api/scenes/effects/{name}/light/{id}` | Apply effect to single light |

#### Automation — `/api/automation/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/automation/status` | Current mode, source, override state |
| GET | `/api/automation/config` | Automation toggles |
| PUT | `/api/automation/config` | Update automation config |
| GET | `/api/automation/schedule` | Time-based schedule (weekday/weekend) |
| PUT | `/api/automation/schedule` | Update schedule |
| GET | `/api/automation/mode-brightness` | Per-mode brightness multipliers |
| PUT | `/api/automation/mode-brightness` | Update multipliers |
| POST | `/api/automation/activity` | Report activity (`{mode, source}`) |
| POST | `/api/automation/override` | Manual mode override |
| GET | `/api/automation/social-styles` | List social sub-styles |
| POST | `/api/automation/social-style` | Set active sub-style |

#### Sonos — `/api/sonos/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sonos/status` | Current playback state |
| POST | `/api/sonos/play` | Resume playback |
| POST | `/api/sonos/pause` | Pause playback |
| POST | `/api/sonos/next` | Next track |
| POST | `/api/sonos/previous` | Previous track |
| POST | `/api/sonos/volume` | Set volume (`{volume: 0-100}`) |
| POST | `/api/sonos/tts` | Text-to-speech (`{text, volume?}`) |
| GET | `/api/sonos/favorites` | List Sonos favorites |
| POST | `/api/sonos/favorites/{title}/play` | Play favorite by name |
| GET | `/api/sonos/queue` | **(future)** Current play queue |
| POST | `/api/sonos/queue/reorder` | **(future)** Reorder queue items |

#### Music — `/api/music/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/music/mode-playlists` | All mode→vibe mappings + favorites |
| PUT | `/api/music/mode-playlists/{mode}` | Set mapping (`{favorite_title, auto_play, vibe_tags}`) |
| DELETE | `/api/music/mode-playlists/{mode}` | Remove mapping |
| POST | `/api/music/import` | Upload Apple Music XML (multipart) |
| GET | `/api/music/profile` | Taste profile |
| GET | `/api/music/recommendations?mode=` | Get pending recommendations |
| POST | `/api/music/recommendations/generate?mode=` | Generate new recs |
| POST | `/api/music/recommendations/{id}/feedback` | Like/dismiss (`{action}`) |

#### Weather — `/api/weather/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/weather` | Current weather conditions (cached 10 min from OpenWeatherMap) |

#### Routines — `/api/routines/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/routines` | All routine configs |
| PUT | `/api/routines/morning/config` | Update morning config |
| PUT | `/api/routines/winddown/config` | Update winddown config |
| POST | `/api/routines/morning/test` | Test morning routine |
| POST | `/api/routines/winddown/test` | Test winddown routine |
| POST | `/api/routines/morning/toggle` | Toggle morning on/off |

#### Quick Actions — `/api/actions/` **(future)**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/actions` | List available quick actions |
| POST | `/api/actions/{name}/execute` | Execute quick action (movie_night, bedtime, leaving, game_day) |
| PUT | `/api/actions/{name}` | Configure what a quick action does (mode + lights + music combo) |

#### Learning — `/api/learning/` **(future)**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/learning/status` | Learning engine status, stats, data freshness |
| GET | `/api/learning/rules` | Active learned rules with confidence scores |
| PUT | `/api/learning/rules/{id}` | Enable/disable a learned rule |
| GET | `/api/learning/patterns` | Detected patterns (for display on dashboard) |
| GET | `/api/learning/prediction` | What would the engine do right now? (debug endpoint) |
| POST | `/api/learning/nudge/{id}/respond` | Accept/dismiss a learning suggestion |

#### Events — `/api/events/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/events/summary` | Aggregated stats across all event tables (mode counts, light/sonos/scene breakdown) |
| GET | `/api/events/activity` | Paginated activity history with mode/source filters |
| GET | `/api/events/patterns` | Time-based pattern analysis (dominant mode by hour, day+hour, override rate) |
| GET | `/api/events/timeline` | Chronological mode timeline for visualization |
| GET | `/api/events/lights` | Light adjustment history with light_id/trigger filters |
| GET | `/api/events/sonos` | Sonos event history with event_type filter |

#### Rules — `/api/rules/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/rules/` | List all learned rules |
| GET | `/api/rules/status` | Engine status + active suggestion |
| POST | `/api/rules/regenerate` | Force rule regeneration from event data |
| PATCH | `/api/rules/{id}` | Enable/disable a learned rule |
| DELETE | `/api/rules/{id}` | Delete a learned rule |
| POST | `/api/rules/suggestion/accept` | Accept suggestion → set_manual_override |
| POST | `/api/rules/suggestion/dismiss` | Dismiss current suggestion |

#### Game Day — `/api/gameday/` **(future)**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/gameday/status` | Current game state (or next upcoming) |
| GET | `/api/gameday/schedule` | Upcoming Colts games |
| POST | `/api/gameday/mode` | Activate/deactivate game day mode |
| GET | `/api/gameday/celebrations` | Celebration history log |
| PUT | `/api/gameday/config` | Celebration preferences (which plays trigger what) |

#### Widgets — `/api/widgets/` **(future)**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/widgets` | All registered external app widgets |
| GET | `/api/widgets/{app}/status` | Current status from external app (plant, bar) |
| PUT | `/api/widgets/{app}/config` | Widget display config (polling URL, refresh interval) |

### Service Interfaces

#### HueService
Controls lights via phue2 (v1 API). Polls bridge every 1s, broadcasts changes via WebSocket.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `connect` | `() → None` | Establish bridge connection |
| `get_all_lights` | `() → list[dict]` | All light states |
| `get_light` | `(light_id: str) → Optional[dict]` | Single light |
| `set_light` | `(light_id: str, state: dict) → bool` | Set light state |
| `set_all_lights` | `(state: dict) → bool` | Set all lights |
| `flash_lights` | `(hue, sat, bri, duration, flash_count) → bool` | Celebration flash |
| `poll_state_loop` | `(ws_manager) → None` | Background polling coroutine |

#### HueV2Service
Native scenes and effects via CLIP API v2. Maintains v1↔v2 UUID mapping cache.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `connect` | `() → None` | Initialize, build ID mapping |
| `get_scenes` | `() → list[dict]` | List bridge scenes |
| `activate_scene` | `(scene_id: str) → bool` | Activate by UUID |
| `set_effect` | `(v1_light_id: str, effect: str) → bool` | Apply to one light |
| `set_effect_all` | `(effect: str) → bool` | Apply to all lights |
| `stop_effect` | `(v1_light_id: str) → bool` | Stop on one light |
| `stop_effect_all` | `() → bool` | Stop all effects |
| `v1_to_v2_id` | `(v1_id: str) → Optional[str]` | ID conversion |

#### SonosService
UPnP control via SoCo. Polls every 2s, broadcasts changes.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `discover` | `() → None` | SSDP or IP connect |
| `get_status` | `() → dict` | Playback state |
| `play/pause/next_track/previous_track` | `() → bool` | Transport controls |
| `set_volume` | `(volume: int) → bool` | 0-100 |
| `play_uri` | `(uri: str, volume?: int) → bool` | Play HTTP URL |
| `play_favorite` | `(title: str) → bool` | Play by name |
| `get_favorites` | `() → list[dict]` | List favorites |
| `get_current_playback_snapshot` | `() → Optional[dict]` | For duck-and-resume |
| `restore_playback` | `(snapshot: dict) → None` | Resume from snapshot |

#### AutomationEngine
Core brain — combines time rules with activity detection.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `report_activity` | `(mode: str, source: str) → None` | Process activity report |
| `set_manual_override` | `(mode: str) → None` | Override (4h timeout) |
| `clear_override` | `() → None` | Clear manual override |
| `register_on_mode_change` | `(callback: async (str) → None) → None` | Subscribe to mode changes |
| `run_loop` | `() → None` | Background loop (60s interval) |
| `update_schedule_config` | `(config) → None` | Hot-reload schedule |
| `update_mode_brightness` | `(brightness: dict) → None` | Hot-reload brightness |

#### MusicMapper
Maps modes to Sonos favorites with vibe-based matching and smart auto-play logic.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `load_from_db` | `() → None` | Load persisted mappings |
| `set_mapping` | `(mode, favorite_title, auto_play, vibe_tags) → None` | Upsert with vibe tags |
| `remove_mapping` | `(mode: str) → bool` | Delete |
| `get_best_match` | `(mode: str) → Optional[str]` | Pick highest-priority matching favorite for mode |
| `on_mode_change` | `(mode: str) → Optional[dict]` | Smart play/suggest — plays if idle, suggests if busy |

### Future Services

#### EventLogger
Middleware service that intercepts all state changes and writes to event tables.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `log_mode_change` | `(mode, previous, source) → None` | Write to activity_events |
| `log_light_adjustment` | `(light_id, state, trigger) → None` | Write to light_adjustments |
| `log_playback` | `(track_info, trigger, mode) → None` | Write to sonos_playback_events |
| `log_routine` | `(name, status, error?) → None` | Write to routine_executions |
| `log_interaction` | `(action, detail, page) → None` | Write to user_interactions |
| `flush` | `() → None` | Batch-write buffered events to DB |

**Implementation note:** Events are buffered in memory and flushed every 5 seconds or when buffer exceeds 50 items. This avoids write contention on SQLite and reduces Postgres round-trips.

#### LearningEngine (separate process)
Reads event data, detects patterns, generates rules, serves predictions.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `analyze_patterns` | `() → list[Pattern]` | Scan recent events for recurring behavior |
| `generate_rules` | `(patterns) → list[Rule]` | Convert patterns to actionable rules |
| `evaluate_rules` | `() → None` | Update confidence scores based on new data |
| `predict` | `(context: dict) → Optional[Action]` | What should happen given current context? |
| `get_active_rules` | `() → list[Rule]` | Rules with confidence > 0.9 |

**Internal API (FastAPI, separate port e.g. 8001):**
- `GET /predict?mode=idle&hour=20&day=5` → `{action: "set_mode", value: "gaming", confidence: 0.93}`
- `GET /rules` → list of learned rules
- `GET /patterns` → detected patterns for dashboard display
- `GET /status` → engine health, last analysis time, data freshness

#### FauxmoService
Manages Alexa virtual device registration and command handling.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `start` | `() → None` | Register virtual devices, start UPnP listener |
| `stop` | `() → None` | Deregister devices, stop listener |
| `register_device` | `(name, on_callback, off_callback) → None` | Add virtual device |
| `_handle_command` | `(device, state) → None` | Route command to API |

**Virtual devices:** "gaming mode", "relax mode", "movie night", "bedtime", "music play", "music pause"

#### GameDayEngine (future)
ESPN polling, play detection, celebration orchestration.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `start_monitoring` | `(game_id?) → None` | Begin polling ESPN for active/upcoming Colts game |
| `stop_monitoring` | `() → None` | Stop polling |
| `get_game_state` | `() → dict` | Current score, quarter, clock, possession |
| `on_play_detected` | `(play) → None` | Trigger celebration if scoring play |
| `get_schedule` | `() → list[Game]` | Upcoming Colts games |

**Registers as mode-change callback:** When mode switches to "game_day", starts ESPN polling. Orchestrates HueService, TTSService, and WebSocket broadcasts on scoring plays.

---

## Developer Guide

> **Audience:** This guide is primarily for Claude Code to follow when implementing new features. Patterns must be precise and consistent so automated code generation follows the established architecture.

### Pattern 1: Adding a Mode-Change Listener

The `AutomationEngine` exposes a callback system for reacting to mode changes. MusicMapper uses this for auto-play. GameDayEngine and FauxmoService will register the same way.

```python
# 1. Define an async callback in your service
async def on_mode_change(mode: str) -> None:
    """Called by AutomationEngine whenever the active mode changes.

    Args:
        mode: One of gaming, watching, working, social, idle, away, relax, movie, sleeping
    """
    if mode == "gaming":
        await do_something()

# 2. Register in main.py lifespan, AFTER automation engine is created
automation.register_on_mode_change(my_service.on_mode_change)
```

**Important:** Callbacks are async and called in registration order. Keep them fast — long-running work should be dispatched as background tasks.

### Pattern 2: Adding a New Backend Service

All services follow the same lifecycle pattern. Here's the complete template:

```python
# backend/services/new_service.py
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class NewService:
    """One-line description of what this service does."""

    def __init__(self, ws_manager, hue_service=None, sonos_service=None):
        """Accept only the dependencies this service actually needs."""
        self._ws_manager = ws_manager
        self._hue = hue_service
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Initialize connections. Called once during app lifespan startup."""
        try:
            # Setup logic here
            self._connected = True
            logger.info("NewService connected")
        except Exception as e:
            logger.error("NewService connection failed: %s", e, exc_info=True)
            self._connected = False

    async def poll_state_loop(self, ws_manager) -> None:
        """Background loop that polls for state changes and broadcasts via WebSocket.

        Only implement if this service needs to detect external changes.
        """
        while True:
            try:
                new_state = await self._check_state()
                if new_state != self._last_state:
                    await ws_manager.broadcast("new_service_update", new_state)
                    self._last_state = new_state
            except Exception as e:
                logger.error("NewService poll error: %s", e)
            await asyncio.sleep(2)  # Poll interval in seconds

    async def close(self) -> None:
        """Cleanup. Called during app lifespan shutdown."""
        self._connected = False
```

**Registration in `main.py` lifespan:**

```python
# In the lifespan() async context manager:

# 1. Create service
new_service = NewService(ws_manager=ws_manager, hue_service=hue_service)
await new_service.connect()
app.state.new_service = new_service

# 2. Start background poll (if applicable)
if new_service.connected:
    tasks.append(asyncio.create_task(new_service.poll_state_loop(ws_manager)))

# 3. Register mode-change callback (if applicable)
automation.register_on_mode_change(new_service.on_mode_change)
```

### Pattern 3: Adding API Routes

All routes go in `backend/api/routes/` as separate files per domain. Follow this template:

```python
# backend/api/routes/new_feature.py
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/new-feature", tags=["new-feature"])


class NewFeatureRequest(BaseModel):
    """Use Pydantic models for all request/response bodies."""
    name: str
    value: int


@router.get("/")
async def get_status(request: Request):
    """GET endpoints return current state."""
    service = request.app.state.new_service
    return {"status": "ok", "data": service.get_state()}


@router.post("/{id}/action")
async def perform_action(id: str, body: NewFeatureRequest, request: Request):
    """POST endpoints perform actions. Return result."""
    service = request.app.state.new_service
    result = await service.do_action(id, body.name, body.value)
    return {"status": "ok" if result else "error"}
```

**Registration in `main.py`:**
```python
from backend.api.routes.new_feature import router as new_feature_router
app.include_router(new_feature_router)
# MUST be registered BEFORE the frontend catch-all route
```

**Conventions:**
- Prefix: `/api/{domain}/`
- GET for reads, POST for actions, PUT for updates, DELETE for removals
- Always return `{"status": "ok"}` or `{"status": "error", "detail": "..."}`
- Access services via `request.app.state.{service_name}`
- Use Pydantic models for request/response validation

### Pattern 4: Adding WebSocket Message Types

**Server → Client broadcast:**
```python
# In any service that needs to push updates:
await self._ws_manager.broadcast("new_event_type", {
    "key": "value",
    "timestamp": datetime.utcnow().isoformat()
})
```

**Client → Server handling in `main.py` WebSocket handler:**
```python
# In the websocket_endpoint function:
elif data["type"] == "new_command":
    result = await app.state.new_service.handle_command(data["data"])
    # Optionally broadcast result to all clients
    await ws_manager.broadcast("new_command_result", result)
```

**Naming convention:** `{domain}_{event}` — e.g., `light_update`, `sonos_update`, `game_update`, `learning_nudge`.

### Pattern 5: Adding an Activity Detector

Standalone scripts that POST mode changes. Can run on any machine on the LAN.

```python
# backend/services/pc_agent/new_detector.py
import requests
import time
import logging

logger = logging.getLogger(__name__)

SERVER_URL = "http://192.168.1.XXX:8000"  # Laptop IP
POLL_INTERVAL = 15  # seconds


def detect_mode() -> str:
    """Return detected mode or 'idle' if nothing detected."""
    # Detection logic here
    return "idle"


def main():
    while True:
        try:
            mode = detect_mode()
            requests.post(
                f"{SERVER_URL}/api/automation/activity",
                json={"mode": mode, "source": "new_detector"},
                timeout=5,
            )
        except Exception as e:
            logger.error("Failed to report activity: %s", e)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
```

**Mode priority (engine enforces automatically):** gaming (5) > social (4) > watching (3) > working (2) > idle (1) > away (0)

### Pattern 6: Adding a Scheduled Routine

```python
# 1. Create the routine service in backend/services/
class NewRoutineService:
    async def execute(self) -> bool:
        """Run the routine. Return True on success."""
        try:
            # Routine logic
            return True
        except Exception as e:
            logger.error("Routine failed: %s", e, exc_info=True)
            return False

# 2. Register in main.py lifespan:
from backend.services.scheduler import ScheduledTask

routine = NewRoutineService(sonos_service, tts_service)  # inject deps

task = ScheduledTask(
    name="new_routine",
    hour=12, minute=0,
    weekdays=[0, 1, 2, 3, 4],  # Mon-Fri (0=Monday)
    callback=routine.execute,
    enabled=True,
)
scheduler.add_task(task)
```

**Conventions:**
- Routine configs persisted in `app_settings` table (key: `{routine_name}_config`)
- Always log execution to `routine_executions` table (via EventLogger)
- Expose test endpoint: `POST /api/routines/{name}/test`

### Pattern 7: Adding Light States for a New Mode

Define per-light states in `automation_engine.py` → `ACTIVITY_LIGHT_STATES`. Each light should have **different** values to create spatial depth — avoid `_uniform()`:

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

**How it works:** The engine first checks `mode_scene_overrides` table for user-mapped Hue scenes, then falls through to `ACTIVITY_LIGHT_STATES`. Time period (day/evening/night from schedule config) + current mode determines the per-light states. Brightness multipliers applied on top. `MODE_TRANSITION_TIME` controls fade speed per mode.

### Pattern 8: Adding Event Logging

All user-facing actions should be logged for the learning system. Use the EventLogger service:

```python
# In any route or service:
event_logger = request.app.state.event_logger

# Log a mode change
await event_logger.log_mode_change(
    mode="gaming",
    previous="idle",
    source="manual"  # or "process", "ambient", "alexa", "learned"
)

# Log a light adjustment
await event_logger.log_light_adjustment(
    light_id="1",
    state={"on": True, "bri": 200},
    trigger="manual"  # or "automation", "scene", "override"
)

# Log a user interaction
await event_logger.log_interaction(
    action="quick_action",
    detail={"action_name": "movie_night"},
    page="home"
)
```

**Convention:** Every POST/PUT route that changes state should log the action. The EventLogger buffers writes and flushes in batches.

### Pattern 9: Adding a Dashboard Widget for an External App

External apps expose a status endpoint. Home Hub polls it and displays the data as a widget card.

**Backend:**
```python
# Widget config stored in app_settings:
{
    "app": "plant",
    "status_url": "http://localhost:3001/api/status",
    "poll_interval_seconds": 300,  # 5 minutes
    "display": {
        "title": "Plants",
        "icon": "leaf",
        "link": "http://localhost:3001"
    }
}
```

The widget poller fetches status from each registered app and broadcasts via WebSocket:
```python
await ws_manager.broadcast("widget_data", {
    "app": "plant",
    "data": {"needs_water": 3, "healthy": 8, "next_care": "Water the fern"}
})
```

**Frontend (SvelteKit):**
Widget cards on the home page subscribe to `widget_data` WebSocket events and render app-specific cards with animated icons. Tapping opens the full external app in a new tab.

### Pattern 10: Themed Mode Backgrounds

Each mode has a dedicated background scene. `ModeBackground.svelte` routes the active mode to the appropriate component — only one scene renders at a time.

```
frontend-svelte/src/lib/backgrounds/
├── PixelScene.svelte           ← Gaming: code-drawn pixel art (480×270 scaled 4×)
├── ParallaxScene.svelte        ← Working: AI-generated PNG with JS parallax scroll
├── AuroraScene.svelte          ← Relax: simplex noise aurora curtains
├── MoonScene.svelte            ← Sleeping: Threlte 3D moon + city scene
├── GenerativeCanvas.svelte     ← Fallback: gradient blobs + particles + geometric overlay
├── scene-utils.js              ← Shared: stars, rain, snow, canvas init
└── layer-config.js             ← ParallaxScene layer definitions per mode
```

**How routing works:**
- `ModeBackground.svelte` checks `$automation.mode` and renders the matching scene
- Sleeping → MoonScene (Three.js), Gaming → PixelScene, Working → ParallaxScene, Relax → AuroraScene
- All other modes (idle, social, watching, movie, away) → GenerativeCanvas
- All scenes subscribe to `sonos` store for music reactivity (speed boost, brightness pulse)
- Scene components are destroyed on mode change (Svelte lifecycle), so only one runs at a time

**Adding a new mode scene:**
1. Create `NewScene.svelte` in `backgrounds/` — standalone component with its own canvas/animation
2. Add routing in `ModeBackground.svelte`: `{:else if mode === 'newmode'} <NewScene />`
3. For sprite-sheet scenes: add PNG to `static/backgrounds/newmode/`, define layers in `layer-config.js`

---

## Target Features

### Dashboard Redesign — "Living Ink" (Complete)

The dashboard has been redesigned as a living, data-reactive interface:

- ✓ **Full-screen layout** — No sidebar. Floating glassmorphic bottom pill bar (3 Lucide icons). Mode overlay with Bebas Neue 36px all-caps mode name + character-stagger animation.
- ✓ **Themed mode backgrounds** — per-mode illustrated scenes: pixel art landscape (gaming), parallax city street (working), aurora borealis (relax), 3D moon scene (sleeping), gradient blobs + particles fallback (other modes). All react to music playback.
- ✓ **Glass card widgets** — `backdrop-filter: blur(12px)`, staggered entrance animations, hover states. Home page: Now Playing strip, Quick Actions, Mode, Weather, Lights, Scenes, Routines.
- ✓ **Auto-hide on idle** — Cards fade out after 60s, leaving just generative art + mode name. "Tap to wake" hint.
- ✓ **Weather widget** — OpenWeatherMap current conditions (temp, feels-like, humidity, wind, hi/lo).
- ✓ **Scene browser** — 20 curated scenes organized by category tabs (functional, cozy, moody, vibrant, nature, entertainment, social) + Effects tab + Hue Scenes tab.
- ✓ **One-tap quick actions** — Lucide icon pill buttons for Movie, Relax, Party, Bedtime, Auto, All Off.
- ✓ **Now Playing chip** — Fixed bottom-right, shows album art + track, pulses when playing.
- ✓ **Plant app widget** — polls the external Vercel-hosted plant care app, shows total / needs-water / overdue counts + next watering. Tapping "View Plants" opens the full plant app inside a fullscreen iframe modal layered over the dashboard (no new tab — the kiosk Firefox stays on the dashboard).
- ✓ **Recommendation card QR modal** — on the music page, the "Open in Apple Music" action on each recommendation card opens an in-dashboard modal showing a client-side-generated QR code for the track's `itunes_url`. Anthony scans with his phone; iOS opens it in the native Apple Music app where Add-to-Library actually works. No `target="_blank"`, no kiosk lockout.
- ✓ **Auto-reload on backend deploys** — the WebSocket `connection_status` message carries a `build_id` (short git SHA). When `scripts/deploy.sh` restarts the backend, the kiosk's WS reconnects, sees a new `build_id`, and calls `window.location.reload()`. Eliminates the manual F5 dance after every deploy.
- ✓ **Custom scene builder UI** — `CustomSceneEditor.svelte` opens from the scene browser's "New" button; per-light color and effect picker, save/update/delete via the existing `/api/scenes/custom` CRUD endpoints.
- **Remaining:** Bar app widget (future).

### Lighting Improvements (Mostly Complete)

- ✓ **Gradual transitions** — 30-minute evening→night lerp, morning ramp
- ✓ **Activity-aware evening** — Wind-down delays and retries if gaming/watching/social/working
- ✓ **CT (color temperature) support** — mirek values (153=6500K → 500=2000K) as first-class parameter
- ✓ **20 curated scenes** — per-light color harmony (analogous, complementary, triadic), paired effects
- ✓ **Custom scene CRUD** — save/load/update/delete with category and effect
- ✓ **Effect auto-activation** — candle for relax nights, glisten for relax days, prism for party
- ✓ **Science-based night work** — desk lamp at 3200K + dim ambient fill (contrast-optimized)
- **Remaining:** per-room mode overrides

### Display Auto-Switching (Monitor ↔ Projector)

**Status: spec only — deferred to Phase 1.5 / Phase 2. Not implemented.**

**Problem:** The desktop has two displays physically connected at all times — a DisplayPort monitor at native 2560x1440 (used for normal desktop work) and an HDMI projector at 1920x1080 (used in bed for movie/TV watching). Switching between them today is fully manual: turn projector on, switch its input to HDMI, turn the monitor off, then change the Windows display resolution by hand. The Windows resolution step is the part Home Hub can automate.

**Goal:** When `movie` mode activates, drop the projector display to 1920x1080 automatically. When leaving that mode, restore it to 2560x1440 (or whatever default was captured at startup).

**Architectural placement — desktop pc_agent, not in-process backend.** The projector is physically connected to the **desktop**, not the dashboard laptop where the FastAPI server runs. The Windows API call has to execute on the machine that owns the display, so this work belongs in a standalone pc_agent on the desktop — same pattern as `activity_detector.py`, `ambient_monitor.py`, and the upcoming `screen_sync_agent.py`. The agent polls `GET /api/automation/activity` and flips resolution locally on `movie` mode entry/exit. No new server endpoint needed.

**Feasibility — confirmed yes, no admin required.** Windows exposes `ChangeDisplaySettingsEx` (Win32) reachable from Python via `pywin32`. With the `CDS_UPDATEREGISTRY` flag, resolution changes are a per-user setting and do **not** require elevation. `EnumDisplayDevices` lets us target the projector specifically without touching the monitor. Both displays stay enumerable even when the monitor is physically powered off, since they're still electrically connected.

**Why not the alternatives:**
- **In-process backend service on the laptop** — Original spec recommended this, but the laptop server can't reach the desktop's display devices. Wrong architecture.
- **QRes / NirCmd / DisplaySwitch.exe** — external binaries, weaker per-display targeting, extra moving parts. Skip.
- **Separate elevated helper process** — unnecessary since admin isn't required. Adds complexity for no gain.
- **Switching the active display via Win+P / `DisplaySwitch.exe /external`** — out of scope. Anthony handles "which screen is on" physically (powering the monitor off, switching projector input). Resolution-only is the right scope.

**Recommended implementation (when this work starts):**

1. **New standalone agent** `backend/services/pc_agent/display_agent.py` following the `activity_detector.py` template. Runs on the desktop. Polls `GET /api/automation/activity` every ~5 seconds. On transitions into/out of `movie` mode, calls `win32api.ChangeDisplaySettingsEx` to swap projector resolution. Skips cleanly on non-Windows (`sys.platform != "win32"`).
2. **Identify displays by friendly name** (`DeviceString`, e.g., "Dell U2719D" / "BenQ HT2050A"), not by `\\.\DISPLAY1` / `\\.\DISPLAY2` — those aren't stable across driver reinstalls. Resolve friendly name → current device name at runtime.
3. **Snapshot the monitor's current refresh rate at agent startup** and restore it when leaving movie mode. Critical if the monitor runs >60 Hz, otherwise it'll silently drop.
4. **Trigger on `movie` mode only** (manual override) — **not** `watching`, since that auto-detects whenever VLC opens at the desk.
5. **No-op early-return** when already at target resolution to avoid double-flicker on repeated triggers.
6. **Force-restore on agent startup** in case the agent died while in projector mode and the monitor was left at 1080p. Config flag controls this.
7. **Local config file** in the agent's working directory (e.g., `display_config.json`):
   ```json
   {
     "monitor": {"friendly_name": "...", "default_width": 2560, "default_height": 1440, "default_refresh": null},
     "projector": {"friendly_name": "...", "default_width": 2560, "default_height": 1440, "movie_width": 1920, "movie_height": 1080, "refresh": 60},
     "trigger_mode": "movie",
     "restore_on_startup": true,
     "enabled": true
   }
   ```
   No server-side persistence needed — the agent owns its own state.
8. **Optional later:** a `POST /api/automation/display/notify` endpoint so the agent can push current resolution to the dashboard for display. Defer until the dashboard actually wants to show it.
9. **Dependencies:** `pywin32>=305` — added to a new `backend/services/pc_agent/requirements.txt` (desktop-only deps), not to the main backend requirements.

**Verification when built:**
- Run `python -m backend.services.pc_agent.display_agent` on the desktop → log shows current detected displays + friendly names.
- `POST /api/automation/override {"mode":"movie"}` (against the laptop server) → desktop agent picks up the change on next poll → projector flips to 1920x1080 within ~5s, monitor untouched. Reverse on switching back.
- Toggle movie mode twice in a row — confirm no second flicker (early-return path).
- Kill agent while in projector mode, restart — confirm restore-on-startup works.
- If monitor runs >60 Hz — confirm refresh rate is preserved across the round trip.

**Out of scope on purpose:** active-display switching, primary-display changes, multi-monitor topology rearrangement, per-application resolution profiles, anything non-Windows.

### Music Overhaul

- **Vibe-based mapping** — Replace single-favorite-per-mode with vibe tags per mode (e.g., gaming = "high energy, electronic, instrumental"). Multiple Sonos favorites tagged per vibe, system picks or rotates.
- **Smarter auto-play** — Fix reliability issues. Clear rules: play on mode change if idle AND auto-play enabled, never interrupt active listening unless told to.
- **Queue management** — View and reorder the Sonos play queue from the dashboard
- **Apple Music API integration** (future, $99/year) — Search catalog by genre/mood, build dynamic playlists, play via SoCo Apple Music URI support. Replaces manual favorite curation.
- **Better recommendations** — Improve relevance by weighting actual listening behavior over Last.fm similarity scores

### Intelligence & Learning System

The system observes everything and evolves from rules to autopilot:

**Data collection (new event tables):**
- `activity_events` — Mode transitions with timestamp, source, duration
- `light_adjustments` — All manual light changes (who changed what, when, in what mode)
- `sonos_playback_events` — What was played, how long, was it skipped
- `routine_executions` — When routines ran, success/failure, user overrides
- `user_interactions` — Dashboard actions, feature usage, page visits

**Phase 1 — Simple rules (quick wins):**
- Time + day patterns: "Friday 8pm usually means gaming mode"
- Override analysis: "You always override to relax at 9:30pm on weeknights"
- Auto-apply rules that have >90% historical accuracy

**Phase 2 — Pattern detection:**
- Correlate mode transitions with time, day-of-week, season
- Track which vibe/playlist choices stick vs get skipped
- Identify when automation gets it wrong (frequent manual overrides)

**Phase 3 — Full autopilot:**
- Proactive mode switching based on learned patterns
- Subtle nudge notifications: "Switching to relax mode" (brief toast, not interruptive)
- Self-adjusting schedules that evolve with behavior changes
- Learns from Alexa voice commands as another input signal

### Voice Control (Alexa)

**Phase 1 — Fauxmo (free, local, immediate):**
- Python library emulating WeMo devices on LAN
- Alexa discovers virtual devices: "gaming mode", "relax mode", "movie night"
- Each device calls the corresponding API endpoint (override, play favorite, activate scene)
- Sub-second latency, $0 cost, runs alongside the server
- Limitation: simple on/off per device, no parameters

**Phase 2 — Custom Alexa Skill + Cloudflare Tunnel:**
- Full flexibility: "Alexa, tell Home Hub to set gaming mode and play my playlist"
- AWS Lambda (~100 lines Python) → Cloudflare Tunnel (free) → local API
- Supports complex commands with parameters
- $0-5/month
- Every voice command logged as a learning signal for the intelligence system

### Game Day Engine

- **ESPN API integration** — Poll for live Colts game data (score, play-by-play, game state)
- **Play detection** — Identify touchdowns, field goals, big plays, turnovers, game start/end
- **Celebration orchestration** — Synchronized light shows + TTS on scoring plays (blue/white flash for TD, pulse for FG, alert for turnovers)
- **GameDay page** — Live score, game clock, down & distance, drive summary on the dashboard
- **Pixel art field** — Threlte/Three.js retro football field with animated sprites showing recent plays (consistent with the rest of the animation stack)
- **Pre-game mode** — Auto-activate Colts lighting and hype playlist before kickoff
- **Commercial break detection** — Dim celebration mode during breaks, re-engage on play resume

#### Game Day Architecture

```
ESPN API (polling) → GameDayEngine service
                      ├── game state tracking (score, quarter, possession)
                      ├── play detection (TD, FG, big play, turnover)
                      ├── CelebrationOrchestrator
                      │   ├── HueService.flash_lights() (blue/white sequences)
                      │   ├── HueV2Service.set_effect_all() (dynamic effects)
                      │   ├── TTSService.speak() ("Touchdown Colts!")
                      │   └── cooldown timer (prevent overlapping celebrations)
                      └── WebSocket broadcasts
                          ├── game_update (score, clock, drive)
                          ├── celebration (type, metadata)
                          └── game_status (active/inactive/upcoming)
```

New database tables:
- `game_schedule` — Upcoming Colts games (date, opponent, channel)
- `celebration_log` — History of triggered celebrations

Registers as a mode-change callback + runs its own ESPN polling loop. No changes to existing services needed.

### External Project Integration

- **Plant app widget** — Shows live status from the plant tracking web app (needs water count, next care action). Animated card on dashboard. Tapping "View Plants" opens the full plant app in a fullscreen iframe modal portaled to `document.body` — the dashboard SPA stays loaded underneath, and a fixed close button (plus ESC and backdrop click) always returns to it. This avoids the kiosk-Firefox lockout that `target="_blank"` would cause.
- **Bar app widget** (future) — Recipe/inventory app. Widget shows tonight's cocktail suggestion based on current inventory. "Hosting mode" button sets mood lighting + playlist + shows recipe cards. Deeply tied to Home Hub for the hosting experience.

---

## Deployment

### Production (as of 2026-04-11)

**Primary host:** Dell Latitude 7420 (service tag 81FPDB3), running
**Ubuntu 24.04 LTS Desktop**, hostname `homehub-dashboard`, static LAN
IP `192.168.1.210`. Always-on 24/7, lid-close configured to ignore
via `/etc/systemd/logind.conf`, display never sleeps via `gsettings`.
Auto-login enabled so power-on → desktop with no keystrokes.

**Running services** on the Latitude:

- `home-hub.service` (systemd user unit) — FastAPI backend via
  `venv/bin/python run.py`, `Restart=on-failure`, `loginctl enable-linger`
  for boot-time start without login
- `home-hub-ambient.service` (systemd user unit) — ambient noise
  monitor via laptop built-in mic, `ExecStartPre` polls `/health`
  until backend ready before starting
- **Pi-hole** (Docker container, host networking) — DNS ad blocker on
  port 53, web admin on port 8080. Compose file at
  `docker/pihole/docker-compose.yml`, config persisted in
  `docker/pihole/etc-pihole/`. Requires `PIHOLE_PASSWORD` env var for
  `docker compose up`. systemd-resolved DNS stub disabled
  (`DNSStubListener=no`) to free port 53.
- **Firefox kiosk** — auto-launches on GNOME login via
  `~/.config/autostart/home-hub-kiosk.desktop`, displays
  `http://localhost:8000` fullscreen on the built-in laptop display.
  Uses deb Firefox from Mozilla's official apt repo, **not** the
  Ubuntu snap (snap Firefox + Wayland + `--kiosk` produces a black
  screen)

**Parallel-forever architecture.** The Windows gaming/dev machine
(192.168.1.30) stays as Anthony's workstation — code editing, tests,
`git push`. It's not a production host. It runs:

- **PC activity detector** via Windows Task Scheduler (hidden
  `pythonw.exe`, at-logon trigger with 30s delay, restart-on-failure),
  pointed at the Latitude via `--server http://192.168.1.210:8000`.
  Dev-machine process detection is only useful where Anthony actually
  games and works, so this belongs on the dev machine, not the
  Latitude.
- **Claude Code MCP server** with `HOME_HUB_URL` set via Windows user
  environment variable (`setx HOME_HUB_URL http://192.168.1.210:8000`)
  so Claude sessions on the dev machine can query and control the
  production backend via MCP tools without a local FastAPI running.
  The `HOME_HUB_URL` env var support was added in commit `11e3798`.

Each machine has its own `data/home_hub.db`; the Latitude's DB is
canonical, the dev machine's is disposable (local testing only). The
Latitude is never edited directly except for `.env` (secrets,
gitignored).

### Deployment workflow

**Code changes** flow from dev → production via git:

1. Edit code on the Windows dev machine
2. `git commit` + `git push` from the dev machine
3. On the Latitude (via SSH from the dev machine): run
   `~/home-hub/scripts/deploy.sh`
4. Verify production state via Claude Code MCP tools
   (`mcp__home-hub__get_health`, etc.) without leaving the dev
   machine

`scripts/deploy.sh` (added in commit `3821cb2`) handles the full
deploy: `git pull --ff-only`, diffs `HEAD` to detect what changed,
reinstalls Python deps if `requirements.txt` changed, runs
`npm install` if `frontend-svelte/package*.json` changed, rebuilds
the frontend if source files changed, restarts `home-hub.service` if
backend code changed, health-checks the backend via `/health` after
restart, and restarts `home-hub-ambient.service` if the ambient
monitor changed. Exits non-zero if the health check fails.

**`.env` updates** (new secrets, API keys, etc.) are not git-tracked
and must be nano-edited directly on the Latitude via SSH, followed by
`systemctl --user restart home-hub.service`.

### Secondary access

Mobile phone (PWA) or any browser on the LAN can hit
`http://192.168.1.210:8000` for the full dashboard. Same dashboard as
the kiosk, no authentication (single-user home network only).

### Cloud services used

OpenWeatherMap (weather), Google Maps (commute), Last.fm (music
discovery), iTunes Search (previews), ESPN (future, game data). All
are free-tier or low-cost APIs. Core features (lights, music,
automation) work without internet — the Hue bridge and Sonos speaker
are LAN-only.

---

## Roadmap

### Phase 1: Core Fix & Foundation (Now — April 2026)

- ✓ Fix automation timing: gradual evening transitions (30-min lerp before winddown_start_hour)
- ✓ Activity-aware wind-down: delays 30 min and retries up to 4x if gaming/watching/social/working
- ✓ Add vibe tagging to mode-playlist mapping (multiple favorites per mode with vibe column)
- ✓ Event logging tables live: activity_events, light_adjustments, sonos_playback_events + EventLogger service
- ✓ Fix music auto-play reliability
- ✓ Deploy server to dedicated laptop, confirm always-on stability (Dell Latitude 7420, Ubuntu 24.04, 2026-04-11 — systemd user services, Firefox kiosk auto-launch, parallel-forever dev→prod workflow via `scripts/deploy.sh`)

### Phase 2: Dashboard Redesign (Complete — April 2026)

- ✓ Sidebar navigation layout → replaced by floating bottom nav in Living Ink redesign
- ✓ Widget-based home page (mode, lights, music, routines, weather, scenes)
- ✓ Quick action buttons (Lucide icon pills)
- ✓ Mobile-responsive layout
- ✓ Sleeping-mode Threlte animated background (stack validator)
- ✓ SvelteKit + Threlte frontend rewrite (Phase 2a parity pass — commit `b96d062`)
- ✓ **Living Ink frontend redesign** — generative canvas background (Perlin noise, data-reactive to Hue lights + Sonos), glassmorphic cards, Bebas Neue typography, mode overlay with character-stagger animation, Now Playing chip, 60s auto-hide on idle
- ✓ **Weather widget** — OpenWeatherMap current conditions with 10-min cache
- ✓ **20 curated scenes** — color harmony theory (analogous, complementary, triadic), per-light states, 7 categories
- ✓ **Custom scene CRUD** — save/load/delete user scenes with category + effect
- ✓ **CT (color temperature) support** — mirek parameter throughout stack for precise Kelvin control
- ✓ **Effect auto-activation** — EFFECT_AUTO_MAP by mode + time period
- ✓ **Science-based night work lighting** — per-light variation with 3200K desk lamp + ambient fill, mode-specific transitions, scene drift, mode→scene overrides
- ✓ **Plant app widget** — polls the external Vercel-hosted plant care app, shows total / needs-water / overdue counts + next watering, and opens the full app in an in-dashboard iframe modal
- ✓ **Pi-hole DNS ad blocker** — Pi-hole v6 in Docker (host networking) on the Latitude, 2M+ domains blocked across 10 curated blocklists, Network widget on dashboard, local DNS for all devices (homehub.local, etc.), Settings page management for DNS records and blocklists, per-device DNS config (apartment router locked)
- ✓ **Test suite expansion** — 101 tests across 8 files (automation, music mapper, scheduler, weather, pihole, API routes, WebSocket). GitHub Actions CI runs full suite on push
- ✓ **Observability tooling** — python-json-logger (structured JSON to file), Uptime Kuma monitoring on port 3002 (Home Hub + Pi-hole health checks with alerting), vite-plugin-visualizer for bundle analysis
- ✓ **Ops tooling** — py-spy for production profiling, httpie for readable API testing (requirements-ops.txt on Latitude)

### Phase 2a: Post-Cutover Cleanup (Complete)

The SvelteKit parity pass shipped in commit `b96d062` and the React tree
was retained briefly as rollback insurance. After a clean burn-in window
(2026-04-07 evening → 2026-04-08 morning) crossing both the 22:00
winddown routine and the 06:40 morning routine — automation, WebSocket,
Sonos, Hue, and the Threlte sleeping background all verified — the
cleanup landed:

- `frontend/` deleted (entire React tree)
- `experiments/threlte-sleeping/` deleted (`MoonScene.svelte` lives in
  `frontend-svelte/src/lib/backgrounds/` now)
- `backend/main.py` `/assets` mount branch dropped; only `/_app` remains
- `FRONTEND_BUILD` defaults flipped to `frontend-svelte/build` in
  `backend/config.py` and `.env.example`
- `CLAUDE.md` + `README.md` refreshed: commands, tech stack table,
  file-structure tree, architecture diagram
- Bonus fixes bundled in: `sw.js` precache shell (`/index.html` → `/`),
  `Slider.svelte` a11y label association, and `winddown_routine.py`'s
  stale `sonos.speaker` attribute (now uses `await sonos.set_volume()`)

### Phase 3: Intelligence & Voice (Complete — April 2026)

- ✓ **Event Query API** (Phase 3a) — 6 endpoints under `/api/events/` for aggregation, pattern detection, filtering, and timeline visualization over all 4 event tables
- ✓ **Rule Engine v1** (Phase 3b) — `RuleEngineService` learns time-based mode patterns from 30 days of activity events (70%+ confidence, 3+ samples). Regenerates every 6h. `LearnedRule` table with day_of_week + hour → predicted_mode. 7 REST endpoints under `/api/rules/`
- ✓ **Nudge Notification System** (Phase 3c) — `mode_suggestion` WebSocket message when idle and a rule matches. `ModeSuggestionToast.svelte` with accept/dismiss buttons, 20s auto-dismiss
- ✓ **Analytics Dashboard Page** (Phase 3d) — `/analytics` route with mode distribution donut, quick stats, hourly pattern bars, learned rules list with enable/disable toggles, recent activity feed, top Sonos favorites and scenes
- ✓ Fauxmo Alexa integration (already working — 7 virtual devices: movie night, relax, arcade, party, bedtime, music, all lights)
- Override pattern analysis tracked via `override_rate` in patterns API — auto-apply deferred to future (v1 is nudge-only)

### Phase 4: Game Day (July-August 2026)

- ESPN API integration + game state polling
- GameDay page with live scoreboard
- Celebration orchestration (light flash + TTS)
- Game Day animated background
- Pixel art field with animated plays
- Pre-game mode automation
- Test during pre-season games

### Phase 4.5: Machine Learning (June-September 2026)

ML capabilities to replace hardcoded rules with learned behavior and add new
sensing (camera, audio classification). Full specification in **`docs/ML_SPEC.md`**.

- **Phase 1 (months 1-3):** Audio scene classification (YAMNet), behavioral mode prediction (LightGBM), adaptive lighting preferences (EMA from manual adjustments)
- **Phase 2 (months 3-6):** Camera presence/posture detection (MediaPipe), smart screen sync (K-means), music selection learning (Thompson sampling)
- **Phase 3 (months 6+):** Autonomous mode switching with confidence-gated actions (95%+ auto-apply, 70-95% suggest via toast)
- All inference local (CPU-only on Latitude), privacy-first, every ML feature has a non-ML fallback

### Phase 5: Polish & Expand (September 2026+)

- Remaining mode backgrounds (social/club, watching/drive-in) + improved art assets (transparent layers, wider tiles)
- Custom Alexa Skill (full voice control)
- Apple Music API integration ($99/year)
- Bar app widget integration
- Seasonal lighting adjustments
- Guest mode

## Technical Limitations & Constraints

- **Hue bridge self-signed SSL** — httpx calls require `verify=False`. Cannot be changed.
- **Sonos UPnP** — No authentication, but also no encryption. LAN-only by design.
- **SoCo Apple Music support** — Can play individual tracks by URI (v0.26.0+), but cannot browse the Apple Music catalog. Browsing requires the $99/year Apple Music API.
- **Fauxmo device limits** — Each virtual device is simple on/off. Complex commands (set brightness to 50%) require the custom Alexa skill.
- **SQLite concurrency** — Single-writer. Fine for one user, but event logging at high frequency (every light poll) may need batching or a write queue.
- **Screen sync requires mss** — Only works on Windows. If the server moves to a headless Linux device, screen sync breaks.
- **Edge-tts requires internet** — TTS falls back to gTTS (also internet). No offline TTS option currently.
- **1080p landscape primary** — Animated backgrounds and layout designed for this resolution. Must degrade gracefully on mobile.
- **Indiana timezone** — America/Indiana/Indianapolis has unique DST rules. All scheduling must use this timezone explicitly.
- **Apartment router locked** — UISP Fiber router has no admin access; DNS must be configured per-device. Hue Bridge and Sonos cannot be configured for custom DNS (they use DHCP DNS from the router).
- **Pi-hole on same machine** — Pi-hole Docker runs on the Latitude alongside Home Hub. If Docker or the container goes down, DNS resolution fails for devices using Pi-hole. Fallback DNS (1.1.1.1) configured on desktop and phone.

## Non-Goals

- **Not a multi-user platform** — No auth, no user accounts, no multi-tenant support
- **Not a generic smart home hub** — No support for arbitrary device types, protocols, or brands beyond Hue and Sonos
- **Not a full smart home OS** — Not replacing Home Assistant, HomeKit, or SmartThings. This is a personal dashboard and automation layer.
- **Not an Alexa replacement** — Alexa handles general voice commands. Home Hub extends it for custom automation via Fauxmo/custom skill.
- **Not a sports app** — Game Day is for the Colts experience, not a general sports tracker
- **Not a music streaming service** — Sonos and Apple Music handle playback. Home Hub orchestrates what plays and when.
- **Not a music streaming service** — Sonos and Apple Music handle playback. Home Hub orchestrates what plays and when.
