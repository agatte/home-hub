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

- Full Philips Hue control via dual APIs (v1/phue2 for basic control + 0.5s polling, CLIP v2 for native scenes, dynamic effects, and server-sent EventStream push). v2 EventStream delivers on/brightness changes from the Hue app + wall dimmers in ~150ms; while the stream is healthy, v1 polling demotes to 5s and covers color/CT plus bridge reachability.
- **Color temperature (CT/mirek) support** — first-class parameter alongside HSB for precise Kelvin control (2000K–6500K)
- Time-based automation: wake, daytime, evening, night periods with separate weekday/weekend schedules
- Activity-driven modes: gaming, working, watching, relax, cooking, social — each with per-light state definitions
- **Colorspace exclusivity** — CT and HSB are never mixed in the command sent to the bridge. `hue_service.set_light` emits `sat=0` before `ct` (bridge is JSON-order-sensitive) and drops any stray `hue`/`sat` in the payload when `ct` is present. Prevents residual HSB on the bridge (or a learner overlay) from tinting "white" CT commands — the fix for the "greenish bedroom" bug.
- **Kitchen pair rule** — L3 (kitchen front) and L4 (kitchen back) always match `bri` + `hue/sat` + on/off in **functional** modes (working, gaming, watching, cooking) and in the 6 **guest party scenes** (`house_party`, `neon_tokyo`, `arcade`, `miami_vice`, `northern_lights`, `sunset_strip`) — identical pendants over a shared island shouldn't read as two different colors. **Relax** and custom non-party aesthetic scenes may diverge for intentional depth.
- **Post-sunset warmth cutoff** — no CT-mode light drops below `ct=333` (~3000K) in evening/night across any mode. Watching loses true D65 bias-light color accuracy after sunset in favor of room-wide evening consistency; gaming HSB tightens brightness caps progressively.
- **Science-based per-mode lighting** — each mode uses distinct per-light variation: working uses ct-mode clean whites with IES 1:3 monitor-ambient contrast at night (desk lamp at 2700K/bri=130 + warm ambient fill); gaming uses blue/purple HSB accents; relax uses warm amber gradients; watching is projector-friendly (warm throughout, no D65 — cool light washes projected blacks — with L2 as soft bias from the wall opposite the projection surface); cooking uses neutral 3500K kitchen peak for accurate food color.
- **Mode-specific transition speeds** — gaming snaps (0.5s), relax fades gently (4s), watching cinematic (3s), cooking quick (1s), sleeping gradual (5s) via MODE_TRANSITION_TIME
- **Scene drift** — subtle random perturbation (±15 bri, ±1500 hue) every 30min during long sessions with 10s imperceptible transitions. **Relax-only**: drift is aesthetic variation and would make paired lights in functional modes look randomly unequal, so it's gated to relax.
- **Effect reconciliation** — `_reconcile_effect` helper applies state FIRST, then stops/starts v2 effects with a 0.5s bridge-processing guard. Order matters: stopping an effect before the new brightness target is on the bridge produces a brightness pop to 100% (the old mode-switch "flash" bug).
- **Polling in-flight window** — `hue_service` tracks per-light deadlines; the polling loop skips broadcasting `light_update` for a light that was just written until its transition + 0.5s buffer elapses. Prevents the UI from bouncing back to stale mid-transition reads. A 3s max-age clamp inside the poll loop force-clears any deadline that ends up further in the future than that — covers the "bridge ack'd the write but the bulb is unreachable so it never transitioned" case, which otherwise would mute polling on that light until the natural deadline expired. The same inflight check is honored by the v2 EventStream dispatcher so a stream echo from the user's own slider drag doesn't snap the UI back mid-drag.
- **v2 EventStream push** — `HueV2Service.event_stream_loop` subscribes to `/eventstream/clip/v2` (a separate `httpx.AsyncClient` with `read=None` timeout) and dispatches `type=="light"` events back through the existing `light_update` WebSocket path. Merges `on` + `bri` (scaled from v2's 0-100 float to v1's 1-254 int) into the v1 cached dict so the frontend store needs zero changes; color (CIE xy) and CT changes are intentionally NOT translated because the codebase has no gamut-aware xy→hue/sat converter. Color/CT ride the 5s v1 polling fallback. Reconnect loop with 1s→30s exponential backoff handles the bridge's ~24h SSE drops + firmware reboots. Gated on `hue_v2.connected` + non-empty `_v2_to_v1` at boot; otherwise the task isn't spawned and the system runs Phase 1 behavior (0.5s polling).
- **Mode → scene overrides** — any mode+time slot can be mapped to a Hue bridge scene or curated preset via `mode_scene_overrides` table, checked before hardcoded ACTIVITY_LIGHT_STATES
- **20 curated scenes** across 7 categories (functional, cozy, moody, vibrant, nature, entertainment, social) using color harmony theory — each scene defines per-light states with varied hue, saturation, and brightness for depth
- **Custom scene CRUD** — user-created scenes persisted to SQLite with category and optional paired effect
- **Effect auto-activation** — EFFECT_AUTO_MAP: opal (relax/day), candle (relax/eve+night). Gaming no longer auto-runs effects (they compete with screen sync and read as "RGB gamer strip").
- Native Hue scenes and dynamic effects (candlelight, fireplace, sparkle, prism, glisten, opal) with 5-min cache on bridge scene fetches
- Social mode — "Velvet Speakeasy" single static palette (dusty rose statement on L1 + cognac amber L2 + matched burnt-orange kitchen pendants). Sub-styles removed in favor of a grown-up cocktail-lounge aesthetic tuned for small hangouts.
- Relax mode — "Moss & Candlelight" biophilic palette: warm ember on living-room lamps (L1/L2) with muted moss/sage kitchen pendants (L3/L4) that echo the plants and olive/sage/teal accents in the room. Candle/fire effects are scoped to L1/L2 so the moss pendants stay static. Late-night variant ("Moss & Ember") kicks in after 23:00 — deeper ember + hunter-green shadow for the cave/den feel.
- Screen sync for gaming and watching (bedroom lamp mirrors dominant screen color via mss capture on the dev PC; the projector runs off HDMI from the dev PC, so mss captures the same frames that are being projected). Gaming-night minimum brightness floor of `bri=85` so L2 never drops to cave-dark against a bright monitor. Watching cap at `bri=80` keeps L2 subtle so mirrored colors don't wash the projected image — but zone-aware: when the camera says `zone=desk` (YouTube-on-monitor, projector not running), watching's L2 base lifts to `bri=160` day / 110 eve / 70 night and the screen-sync cap rises to 180 so a bright monitor can push L2 well above the projector-safe default.
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
- Camera-based presence (MediaPipe face + pose) is the sole "is the user here" signal in-app. Home/away as a concept was retired 2026-04-28; arrivals/departures are now handled by Hue's native geofencing outside Home Hub.
- Mode priority system: gameday (6) > gaming (5) > social (4) > watching (3) = cooking (3) > working (2) > idle (1) > sleeping (0)
- Morning routine: weather (NWS API) + commute (Google Maps) TTS at configurable time
- Evening wind-down: dims lights, activates candlelight, lowers volume, TTS announcement
- All routine config persisted to SQLite, hot-reloadable
- Do Not Disturb (`POST/DELETE /api/automation/dnd`, default 2h) locks autonomous changes for a finite window. `AutomationEngine.is_dnd_active()` gates `report_activity`, `set_manual_override`/`clear_override` (autonomous sources only — user-source `api:<ip>` still passes), late-night rescue, zone+posture rule, behavioral predictor toast, music auto-play / weather suggestion, and morning + sunrise + winddown routines. Persisted to `app_settings["dnd_state"]`, restored on boot, auto-cleared in `run_loop` once expiry passes
- Apartment Logbook (`backend/services/journal_service.py`, scheduled at 02:00 daily) reads activity / light / sonos / scene events for the previous local calendar day and writes Markdown to `data/journal/YYYY-MM-DD.md`. Surfaced at `/journal` (date rail + markdown render); intentionally excluded from `FloatingNav`. Pure read; no actuation. Endpoints: `GET /api/journal/entries`, `GET /api/journal/{date}`, `POST /api/journal/generate/{date}`

### ML Operational Status

The ML layer has landed in code (`backend/services/ml/`, ~2,092 LOC across 8 services), but components sit in three distinct states. Spec entries elsewhere use these labels consistently.

**Active** (running, affecting behavior today):
- `LightingPreferenceLearner` — EMA-based (α=0.3) per-light preference overlay on `ACTIVITY_LIGHT_STATES`. Overlay applications are logged as `ml_decisions` rows with `decision_source="lighting_learner"` so the Analytics dashboard can audit when the learner is actually changing a value
- `MusicBandit` — Thompson sampling for mode → Sonos favorite selection
- `CameraService` — MediaPipe FaceDetector on the Latitude webcam, 15-frame (~30s) idle detection vs the 10-min PC-idle timer. Also captures a calibrated ambient-lux signal (fixed exposure, EMA-smoothed) feeding an adaptive brightness multiplier in working/relax/gaming/watching modes (+30%/-15%, anchored at the calibrated baseline) so lights adapt to real room conditions (clouds, sunset, lamps)
- `ScreenSyncService` K-means — 5-cluster dominant color extraction (saturation-weighted 0.7 + luminance balance 0.3)
- `MLDecisionLogger` — every mode decision logged to `ml_decisions` with source + factors. Live `decision_source` values: `fusion`, `ml`, `rule_engine`, `process`, `camera`, `audio_ml`, `lighting_learner`, `zone_posture_rule`, `manual`. Each fusion voter writes its own per-arrival shadow row (`applied=False, broadcast=False`); `compute_per_source_metrics` and the analytics constellation read from those rows directly. **Truth-tagging** (`on_mode_change` callback): two-pass backfill — non-predictor rows tagged with the *leaving* mode (the mode that was active during the just-ended window); `decision_source='ml'` predictor rows tagged with the *entering* mode on idle → predictable-mode transitions (since predictor logs only during idle and forecasts the next non-idle mode). Both backfills cap at 2h to avoid mislabeling overnight gaps
- `ConfidenceFusion` — **4-signal** weighted ensemble (process / camera / audio_ml / rule_engine) computing every automation tick and broadcasting to the analytics dashboard; auto-applies mode at 95%+ confidence, and can override an active detected mode at `OVERRIDE_THRESHOLD = 0.92` + 80% agreement. The behavioral lane was removed 2026-04-27 after the LightGBM predictor collapsed to a single output class (898/898 over 9 days, 0.64% real accuracy); the presence lane was removed 2026-04-28 alongside the home/away retirement. Default weights renormalized to preserve relative ratios: process 0.438, camera 0.250, audio_ml 0.187, rule_engine 0.125. During 22:00–06:00 local, the process-detection lane is decayed by `LATE_NIGHT_PROCESS_WEIGHT_FACTOR = 0.6` so stale dev tools left open don't dominate the ensemble. Rule-engine vote stays fresh during manual overrides (`b8c285a`, 2026-04-29) — the prior `not self._manual_override` call-site guard had silenced the lane through any override (sleeping, winddown's relax, late-night rescue), permanently parking it in fusion's `never_reported` list; `check_rules()` already gates the nudge path on `current_mode==idle` internally, so the outer guard was redundant for nudges and wrong for the fusion-voter contract
- **Nightly fusion weight tuning** — `fusion_weight_tuning` ScheduledTask runs daily at 3:30 AM (30 min before `ml_nightly_training` at 4:00 AM). `MLDecisionLogger.compute_accuracy_by_source(days=14)` walks fusion decisions where `factors.signal_details` is present and computes per-source accuracy; `ConfidenceFusion.update_weights_from_accuracy()` normalizes those values into new weights. Sources without usable samples fall back to `DEFAULT_WEIGHTS`. Manual trigger via `POST /api/learning/retune-weights` returns before/after weights for validation

**Shadow** (running, logging predictions, not yet authoritative):
- `BehavioralPredictor` (LightGBM, 7-class: gaming / working / watching / relax / social / cooking / idle) — runs in shadow on the Latitude, writes to `ml_decisions` with `decision_source="ml"`. Idle-gated: predictor logs only when `automation_engine._current_mode == "idle"`; each row's `predicted_mode` is a forecast of the next non-idle mode out of idle. Promotion is gated on `compute_prediction_diversity()` — the saved model must produce diverse outputs (≥2 modes, top-mode share ≤95% over the last 7 days) before `POST /api/learning/predictor/promote` returns 200. Calibration shipped 2026-04-28 (commit `82c72ed`): closed a train/serve feature-parity bug, lowered `SUGGEST_THRESHOLD` 0.70→0.30 to surface diverse predictions, plumbed full per-class probability distribution into shadow-log `factors.distribution`, added a stale-label-encoder gate. Class-balanced training shipped 2026-05-06 (`d3e1c7f`): `_train_sync` now computes inverse-frequency sample weights via sklearn's "balanced" formula and passes them to `lgb.Dataset(weight=...)` so minority modes don't get starved by working-class dominance; also logs per-class val accuracy to journalctl. Predictor-specific truth-tagging shipped same day (`80e8db7`): `MLDecisionLogger.on_mode_change` now tags `decision_source='ml'` rows with the *entering* mode on idle → predictable-mode transitions (instead of the leaving mode = always `idle`), so the standard `predicted_mode == actual_mode` accuracy query produces correct numbers. Historical backlog re-tagged via `scripts/migrations/2026-05-06-backfill-ml-predictor-actual-mode.py`. Auto-demote logic for a promoted-then-degenerate predictor is live (4/27 audit follow-up). 2026-05-06 smoke test against the next-mode JOIN against `activity_events` showed 72% accuracy at conf≥0.8 across 129 samples — well above the 28.3% no-skill baseline; minority classes (watching/relax) still at 0% pre-tuning, watching the next nightly retrain to see if class weights move them.
- `AudioClassifier` (YAMNet, 521 AudioSet classes → 9 Home Hub scenes) — **Social-gate abandoned 2026-05-09 (option C).** 14-day re-evaluation across 838,629 production rows confirmed the 5/03 36h finding: `speech_multiple` MAX observed 0.088 (never close to the 0.80 threshold), 0 firings including the 5/02 + 5/06 guest-visit ground-truth windows. Option A (retarget to `speech_single` + RMS floor) was rejected — `speech_single ≥ 0.80` fires ~7,000/day with 3.4% overlap into solo working windows, and RMS doesn't disambiguate 1-vs-2 speakers. Option B (retrain YAMNet) was rejected — wrong tool architecturally. The `speech_multiple` entry was removed from `MODE_THRESHOLDS` in `audio_classifier.py`; the score is still emitted into `all_scores` for analytics. Audio_ml lane stays in v3 fusion for `silence→quiet` and `game_audio→watching` gates. Replacement direction (deferred — separate plan): camera multi-face detection extending the existing MediaPipe pipeline; SpeechBrain embeddings + clustering as a fallback if camera coverage gaps surface.

### Dashboard — Themed Backgrounds

- **Per-mode themed backgrounds** — each mode has a distinct visual scene:
  - **Gaming**: `PixelScene.svelte` — code-drawn retro pixel art landscape (480×270 scaled 4×) with parallax mountains, walking sprites, twinkling stars, floating particles, shooting stars
  - **Working**: `ParallaxScene.svelte` — AI-generated pixel art city street (PNG sprite sheet) with JS-driven parallax scroll, code-drawn sky gradient synced to weather/time of day
  - **Relax**: `AuroraScene.svelte` — simplex noise-driven aurora borealis curtains with twinkling stars and treeline silhouette
  - **Sleeping**: `MoonScene.svelte` — Three.js/Threlte 3D scene with orbiting moon, GLSL sky shader, procedural city silhouette with flickering windows, star field
  - **Other modes**: `GenerativeCanvas.svelte` — three-layer system (gradient mesh blobs + flow-field particles + geometric overlay) as fallback
- All scenes react to music (Sonos playing = faster motion, brighter effects)
- `ModeBackground.svelte` routes the active mode to its scene component; only one scene renders at a time
- **Scene RAF loops pause on `document.visibilitychange`** — `scene-utils.js` `createAnimationLoop` (Aurora, Pixel, City) + bespoke handlers in `GenerativeCanvas.svelte` and `ParallaxScene.svelte` cancel their `requestAnimationFrame` when the tab is hidden / kiosk screen blanks, and re-prime on resume so `dt` doesn't jump. `MoonScene` (Threlte `useTask`) is the one exception — only mounts in sleeping mode where the kiosk is dark anyway
- **No sidebar** — floating glassmorphic bottom pill bar (Home, Music, Analytics, Settings) + mode overlay (Bebas Neue 36px all-caps mode name with character-stagger animation) + Now Playing chip
- **Glass cards** — all widgets use `backdrop-filter: blur(12px)` with staggered entrance animations
- **Auto-hide on idle** — after 60s of no interaction, cards fade out leaving just the background scene + mode name. Tap anywhere to wake.
- **Weather widget** — NWS API current conditions with 5-minute cache + active severe weather alerts
- **Vital Signs Strip** — always-visible 22px strip at the kiosk bottom. `VitalStrip.svelte` polls `GET /api/vitals` every 30s, which re-projects already-shipped surfaces (Hue / Sonos circuit-breaker state, fusion `_last_fusion_result`, Pi-hole `get_summary`, `psutil` mem/disk/CPU-temp, WS client count) into per-metric `{value, status: ok|warn|error}` chips with a roll-up status. Collapsed → overall dot only; expanded → all chips with mode-aware tinting (orange = warn, red = error). `FloatingNav` shifted up to `bottom: 36px` (mobile `28px`) to clear the strip
- Four pages: Home (controls + weather + scenes), Music (discovery + mapping), Analytics (live decision pipeline with fusion ring + per-signal gauge cards + collapsible historical analytics), Settings (configuration). Plus a hidden `/journal` route (Apartment Logbook — date rail + Markdown render of the nightly summaries; excluded from `FloatingNav`). Guest WiFi credentials surface via the `GuestWifiWidget` tile on Home, which opens a fullscreen modal with the WiFi `WIFI:` URI QR plus a smaller URL QR pointing at `/guest` (two-scan flow — join then info)
- **Guest mini-app** at `/guest/*` — a separate visitor surface with its own bottom-tab nav (`GuestBottomNav`: Home / WiFi / Bar / Plants / Vibe), independent of the kiosk. Root `+layout.svelte` strips all kiosk chrome (`ModeBackground`, `ModeOverlay`, `NowPlayingIdle`, idle hint, `FloatingNav`, `NowPlayingChip`, `VitalStrip`, reconnect banner) on `/guest/*` paths — only `<slot/>` + `<ErrorToast/>` survive. Pages: `/guest` (Welcome + Now Playing + House Notes), `/guest/wifi` (re-share GuestWifiWidget), `/guest/bar` (`/api/bar/status` summary + deep link), `/guest/plants` (`/api/plants/status` snapshot), `/guest/vibe` (live mode icon + 4 colored room swatches + 6 party-scene picker with live color previews + 3 music-vibe tiles). Guest writes go through `POST /api/guest/scene/{name}` and `POST /api/guest/vibe/{name}` with independent 15s cooldowns; both tagged `source="guest"` for journalctl traceability. RFC1918 LAN bypass keeps the auth surface zero for visitors on the WiFi.
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
- ~~Evening wind-down triggers at fixed time regardless of activity~~ — fixed: delays 30 min and retries up to 4x if gaming/watching/social. "working" was later removed from the skip set (April 19) — late-night dev sessions are exactly when winddown should fire, not when it should defer
- ~~Clearing override at 12:45 AM left lights in gaming/night's deep-blue ambient glow because gaming has no `late_night` state — forced manual relax every night~~ — fixed: three-layer autopilot cascade. (1) `javaw.exe` removed from `GAME_PROCESSES` (it had been silently forcing "gaming" on any JVM process). (2) Winddown enabled at 22:00 weekdays so the transition is proactive. (3) Late-night rescue in `run_loop` auto-applies relax after 23:00 when no override is set, detected mode is working/idle, and Sonos isn't playing — covers the edge after winddown's 4h override expires. Plan at `.claude/plans/let-s-look-at-the-serene-leaf.md`
- ~~Mode detection has noticeable lag between activity start and mode switch~~ — fixed: dropped PC agent POLL_INTERVAL from 15s to 5s (worst-case 5s, average ~2.5s). The backend processes activity reports synchronously on POST, so the polling interval was the entire lag budget.
- ~~Welcome-home sequence reliability (multiple rounds: ICMP retired April 19; Shortcut webhooks + ARP debounce April 19; sleeping-mode veto April 27)~~ — **superseded by retirement**: the entire home/away concept was removed 2026-04-28 (commit `b8fdbfe`). Three rounds of mitigation against iOS Shortcut + ARP flap couldn't fully suppress overnight phantom `away` events; iOS power-save makes phone-presence fundamentally unreliable. `presence_service.py` deleted, `away` mode removed from priority/encoding/UI, presence lane removed from ConfidenceFusion. Hue's native geofencing now handles arrivals/departures outside Home Hub.

**Lighting mode-switch quality (April 2026):**
- ~~"Greenish bedroom" in working mode~~ — fixed: Hue bridge stored residual HSB on CT-mode lights (either cached from a prior HSB mode or injected by the LightingPreferenceLearner overlay). `hue_service.set_light` now always emits `sat=0` before `ct` in the JSON body and drops any stray `hue`/`sat` when `ct` is present — the bridge is key-order-sensitive and rejects `sat=0` that follows `ct`.
- ~~Kitchen lights drifted to random different brightness~~ — fixed: scene drift is now relax-only (was applied to all active modes, producing independent ±15 bri deltas on paired L3/L4). Kitchen pairing is the baseline expectation in working/gaming/watching/cooking.
- ~~Brightness pop/flash when effects stop/start on mode change~~ — fixed: new `_reconcile_effect` helper applies state to the bridge FIRST (establishing the brightness target), then stops the old effect and starts the new one with a 0.5s guard. Previously the effect was stopped before the target was on the bridge, so the bridge defaulted to 100% brightness until the next command landed.
- ~~UI bounces back to old light values mid-transition~~ — fixed: `hue_service` tracks per-light in-flight deadlines (transition time + 0.5s buffer); the polling loop skips broadcasting `light_update` for a light that was just written so the frontend doesn't receive stale mid-transition reads.
- ~~Monitor-ambient contrast too aggressive for eyes during gaming at night~~ — fixed: raised screen-sync `MODE_MIN_BRIGHTNESS` for gaming from 50 to 85 so L2 (bedroom lamp) never drops below a comfortable bias level regardless of screen content. Gaming-night L2 fallback bumped to 140 for non-sync moments. **Follow-up 2026-05-06:** floor raised again 85 → 130 after a heavy-rain day with persistent dim-screen scenes. Same pass extended `LUX_CURVE` with a (20.0, 1.30) low anchor and lifted (40.0, 1.15) → (40.0, 1.20) so overcast rooms get +20–30% brightness instead of saturating at +15%.
- ~~Per-mode lighting felt arbitrary and inconsistent~~ — fixed: full ACTIVITY_LIGHT_STATES redesign anchored on IES 1:3 monitor-ambient contrast for work, D65 bias for daytime watching, kitchen functional pairing, post-sunset ct≥333 strict cutoff. Plan at `.claude/plans/let-s-take-a-look-foamy-ripple.md`.

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
- ~~Weather widget shows current temp as high/low~~ — fixed: fetches daily range from NWS 7-day forecast
- ~~No structured logging~~ — fixed: python-json-logger (JSON to file for machine parsing, text to console for humans)
- ~~No uptime monitoring~~ — fixed: Uptime Kuma on port 3002 monitoring Home Hub backend + Pi-hole health, with alerting
- ~~No bundle analysis~~ — fixed: vite-plugin-visualizer (`npm run analyze` generates interactive treemap)
- ~~No authentication on API endpoints~~ — fixed: `X-API-Key` required on every write endpoint via `require_api_key` FastAPI dep (`backend/api/auth.py`), with auto-bypass for localhost + any RFC1918/loopback/link-local/ULA caller (the apartment LAN). `HOME_HUB_API_KEY` env var holds the secret; unset = fail-closed 503

**Structural / tech debt:**
- `automation_engine.py` is a 1,944-LOC single-file monolith. Mode rules, effect reconciliation, fusion wiring, learner overlay application, and the 60s loop all live in one module. Refactor candidate — split into `mode_resolver`, `light_applicator`, `effect_reconciler`, `engine_loop`
- Apple Music XML upload (`POST /api/music/import`) has no enforced size limit. A multi-GB library file could OOM the backend before the parser rejects it
- ~~Zero authentication middleware anywhere~~ — fixed: `require_api_key` is a global write-endpoint gate (see "No authentication on API endpoints" above). The LAN auto-bypass keeps friction at zero for the kiosk and Anthony's devices; a future Cloudflare Tunnel for Phase 5 Alexa would route through a non-private IP and naturally hit the header check
- ~~`EventLogger` swallows exceptions silently~~ — fixed: `_drop_count` dict tracks per-family (mode/light/scene/sonos) drop counts, surfaced in `/health` JSON under `event_logger_drops` so Uptime Kuma can alert on growth
- ~~Automation-triggered light changes aren't logged to `light_adjustments`~~ — fixed: `_apply_uniform` and `_apply_per_light` in `automation_engine.py` now call `log_light_adjustment(trigger="automation")` with before/after values when state actually changes (dedup check prevents hot-path spam)
- ~~Celebration light steps bypass EventLogger~~ — fixed: `CelebrationOrchestrator._run_light_steps` now mirrors successful `set_light` to `log_light_adjustment(trigger=f"celebration:{sequence_key}")` (commit `34fc550`). DB primary, journalctl corroboration. Closed memory: `project_celebration_no_event_log.md`
- ~~`LightingPreferenceLearner.get_overlay` merges learned deltas invisibly~~ — fixed: when the overlay actually changes a value, an `ml_decisions` row is written with `decision_source="lighting_learner"` and the per-light deltas in `factors`

**Open bugs (from April 2026 audit):**
- ~~GenerativeCanvas store subscriptions may leak memory~~ — false positive: subscriptions are manual `subscribe()` calls with proper `onDestroy` cleanup (lines 218-224)
- ~~Silent API error swallowing~~ — fixed: `api.js` now uses `safeFetch()` wrapper that pushes errors to an `errors` store. `ErrorToast.svelte` renders red toasts in bottom-left with 5s auto-dismiss
- ~~Per-light manual override has no per-entry expiration~~ — fixed: the 60s automation loop now sweeps `_manual_light_overrides`, dropping entries older than `_override_timeout_hours` (same 4h window as the mode-level override). Expiration logs at INFO
- ~~Scene override silent failure~~ — fixed: both the v2 `activate_scene` path and the preset fallback are wrapped in try/except. On total failure the engine emits a `scene_failed` WebSocket event (`{mode, time_period, scene_id, source, reason}`) and falls through to the hardcoded `ACTIVITY_LIGHT_STATES` path instead of leaving lights stale
- ~~WebSocket unknown-type messages silently dropped~~ — fixed: the frontend dispatcher in `stores/init.js` now has a `default` branch that `console.warn`s the unknown type + payload so mismatched server/frontend builds are visible in DevTools

**Ambient intelligence features (April 2026):**
- ~~Now Playing Ambient Typography~~ — shipped: `NowPlayingIdle.svelte` fills kiosk with giant song title/artist when idle + Sonos playing; album art as blurred ambient glow
- ~~Sunrise Alarm Light Ramp~~ — shipped: 30-min bedroom lamp warm-up (CT 500→250, bri 1→150) before morning routine via ScheduledTask
- ~~Weather-Reactive Lighting~~ — shipped: noticeable light adjustments across all active modes (thunderstorm=purple+sparkle, rain=cool+candle, golden_hour=warm, overcast=dim+warm, snow=bright+cool+opal). NWS alert override ensures storms are detected even when observation stations lag. Weather-driven music suggestions broadcast via WebSocket during rain/storm/snow

---

## System Architecture

### Current Architecture

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
   │   └── mode-change callbacks ──> MusicMapper, AmbientSound, MLLogger, CameraService, BarApp, LoLChampionService
   ├── ML Services ────────────────> see docs/ML_SPEC.md
   │   ├── MLDecisionLogger ───────> logs every mode decision with reasoning
   │   ├── ConfidenceFusion ───────> 4-lane weighted ensemble (process/camera/audio_ml/rule_engine)
   │   ├── BehavioralPredictor ────> LightGBM mode prediction (shadow mode, 7-class)
   │   ├── AudioClassifier ────────> YAMNet audio scene classification (shadow mode)
   │   ├── CameraService ──────────> MediaPipe face + pose + zone + posture + lux
   │   ├── LightingPreferenceLearner > EMA-based adaptive per-light prefs
   │   ├── MusicBandit ────────────> Thompson-sampling playlist selection
   │   ├── FeatureBuilder ─────────> temporal + behavioral feature extraction (training + runtime)
   │   └── ModelManager ───────────> model persistence + nightly retraining (4 AM)
   ├── FauxmoService ──────────────> Alexa voice control (7 WeMo virtual devices)
   ├── MusicMapper ────────────────> mode change → smart Sonos auto-play
   ├── EventQueryService ──────────> aggregation over event tables (patterns, timeline)
   ├── RuleEngineService ──────────> learns time-based mode patterns → nudge suggestions
   ├── WeatherService ─────────────> NWS API (5-min cache) + severe weather alerts (2-min cache)
   ├── ScreenSyncService (mss) ────> dominant screen color → bedroom lamp
   ├── LoLChampionService ─────────> League of Legends champion → bedroom lamp color (gaming mode only)
   ├── TransitLightingService ─────> camera absent → brief L1 navigation brightness (kitchen pair ceded to DeskExitKitchen in productive evening/night)
   ├── DeskExitKitchenService ─────> productive evening/night + sustained desk-loss → kitchen pair (L3/L4) brightens, holds until return
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

PC Agent (supervised on the dev machine only, 2026-04-19+)
   ├── activity_detector.py  ON dev machine (192.168.1.30) ──> POST http://192.168.1.210:8000/api/automation/activity
   │                         (psutil process detection)
   ├── ambient_monitor.py    ON dev machine (192.168.1.30) ──> POST http://192.168.1.210:8000/api/learning/audio-decision
   │                         (Blue Yeti PyAudio RMS + YAMNet shadow classifier — --classifier --shadow.
   │                          Social-gate abandoned 2026-05-09; mode-report POSTs to /api/automation/activity
   │                          removed 2026-05-16 after the rogue source=ambient idle reports were displacing
   │                          rescue overrides via the priority guard. Service now publishes ML decisions only.)
   └── screen_sync_agent.py  ON dev machine (192.168.1.30) ──> POST http://192.168.1.210:8000/api/automation/screen-color
                             (Three agents managed by supervisor.py; Latitude built-in mic no longer runs
                              ambient_monitor — systemd unit disabled because RMS in the corner environment
                              was false-latching social mode. Blue Yeti is the sole audio source.)
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
   ├── NWS API (weather + alerts, api.weather.gov)
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

Keys in use: `morning_routine_config`, `winddown_routine_config`, `time_schedule_config`, `mode_brightness_config`, `mode_volume_curves`, `watching_posture_config`, `camera_enabled`, `lux_calibration_config`, `dnd_state`, `override_state`, `guest_vibe_playlists`, `champion_color_map` (League champion → RGB palette consumed by `LoLChampionService`; seeded via `scripts/seed_champion_colors.py`). The middle pair carries runtime state across restarts: `dnd_state` is `{enabled, expiry_utc, duration_minutes}`, and `override_state` is `{manual_override, override_mode, override_time_utc, zone_posture_last_fired_utc}` — restored at boot by `automation.load_dnd_state()` / `load_override_state()`, with override drops past the 4h timeout (sleeping exempt). `mode_volume_curves` is `{mode: {day, evening, night, fade_duration_s}}` driving `ModeVolumeService`'s per-mode Sonos fade on transition. `guest_vibe_playlists` is `{hype, singalong, throwback}` → Sonos favorite title; missing keys fall back to `GUEST_VIBE_DEFAULTS` in `routes/guest.py`.

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
| mode | String(50) | gaming, working, watching, social, relax, cooking |
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
| timestamp | DateTime | UTC, indexed — when the transition was logged |
| mode | String(50) | Mode that was activated |
| previous_mode | String(50) | Mode before transition |
| source | String(30) | What triggered: time, process, ambient, manual, alexa, learned |
| duration_seconds | Integer | Filled in when the *next* event arrives |
| zone | String(20) | Camera-derived zone at the moment of the transition (`desk`/`bed`/null). Populated by `EventLogger` from `camera_service`; backfilled historically from nearby `ml_decisions` camera rows. |
| posture | String(20) | Camera-derived posture (`upright`/`reclined`/null). Same source as zone. |
| audio_class | String(40) | YAMNet top class from the most recent `audio_ml` `ml_decisions` row within ±60s (`silence`/`speech_single`/`speech_multiple`/`music`/`mechanical_noise`/`doorbell`/`game_audio`/null). |
| lux | Float | Camera EMA lux at the moment of the transition. Backfill source = `ambient_lux` from the same camera frame; live writes use `camera_service.ema_lux`. |

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
| event_type | String(30) | play, pause, skip, volume, auto_play, suggestion |
| triggered_by | String(30) | manual, auto, suggestion_accepted |
| mode_at_time | String(50) | Active mode when playback started |
| started_at | DateTime | UTC |
| ended_at | DateTime | UTC, nullable |
| duration_seconds | Integer | Computed on end |
| skipped | Boolean | Was track skipped before finishing |
| weather_class | String(20) | Nullable — Phase B (2026-05-12). Weather class at log time (thunderstorm/rain/snow/clouds/golden_hour/clear/any). Used by bandit nightly retrain to rebuild weather-aware arms. None on pre-migration rows |

### Additional Live Tables (Phase 3 + ML)

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

UniqueConstraint on (day_of_week, hour). Rules regenerated every 6 hours from 30 days of activity_events. Minimum thresholds: 70% confidence, 3 samples. Idle is excluded as a prediction target ("you're usually idle" isn't a useful nudge).

**rule_suggestions** — Persistent record of every rule-suggestion fire (Phase 3c.2)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| rule_id | Integer | FK → learned_rules.id, no CASCADE (history outlives rule deletion) |
| fired_at | DateTime | UTC, indexed |
| predicted_mode | String(50) | Captured at fire time |
| confidence | Float | 0.0-1.0, captured at fire time |
| sample_count | Integer | Captured at fire time |
| current_mode_at_fire | String(50) | Nullable — typically `idle` (today's only gate) |
| status | String(20) | `pending`, `accepted`, `dismissed`, `expired`, `superseded` |
| resolved_at | DateTime | Nullable, UTC; set on status transition out of `pending` |
| resolved_source | String(100) | `user_accept:<remote-ip>`, `user_dismiss:<remote-ip>`, `auto_expire`, `superseded_by:<new_id>` |

Composite index on (status, fired_at) for "latest pending" lookup + history queries. Pending rows older than 60min are auto-expired on the 60s automation tick. Boot-time `restore_pending_on_boot()` re-broadcasts an unresolved pending suggestion so a deploy mid-banner doesn't drop the kiosk's Home card.

**ml_decisions** — ML decision log (every mode decision with reasoning)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| timestamp | DateTime | UTC, indexed |
| predicted_mode | String(50) | Mode the system chose |
| actual_mode | String(50) | Nullable, backfilled on next mode change |
| applied | Boolean | Whether the prediction was acted upon |
| confidence | Float | Nullable, prediction confidence |
| decision_source | String(30) | One of: `fusion`, `ml`, `rule_engine`, `process`, `camera`, `audio_ml`, `lighting_learner`, `zone_posture_rule`, `manual` |
| factors | JSON | Nullable, reasoning chain for explainability |

**ml_metrics** — Daily aggregate ML performance metrics
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, auto-increment |
| date | Date | Indexed |
| metric_name | String(50) | e.g. `accuracy_process`, `accuracy_camera`, `accuracy_audio_ml`, `accuracy_rule_engine` |
| value | Float | Metric value |
| extra | JSON | `{samples, correct, window_days}` for accuracy rows |

Written nightly by `MLDecisionLogger.persist_accuracy_metrics()` from the
3:30 AM `fusion_weight_tuning` cron (`backend/bootstrap.py:493-515`). One
row per source per UTC day; idempotent via delete-then-insert on
(date, metric_name).

### Future Database Tables

Not yet in `backend/models.py`. Listed here so the schema shape is decided when they land.

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

*(Phase 4 Game Day shipped 2026-05-07 without new DB tables — `GameDayService` is in-memory + ESPN polling, `CelebrationOrchestrator` is callback-driven. The `game_schedule` and `celebration_log` tables originally projected here weren't built. Celebration writes DO land in `light_adjustments` as of commit `34fc550` with `trigger="celebration:<key>"`, queryable via `WHERE trigger LIKE 'celebration:%'`.)*

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
| `notification` | NotifierService threshold-cross — mode flip OR average per-light brightness Δ ≥ 15%. Suppressed during DND, within 10s coalesce window, and on user-initiated mode flips (`api:*` / `manual` / `alexa:*` / `guest:*`). Consumed by `desktop_notifier.py` on the Windows desktop and by `httpx` POST to `https://ntfy.sh/{NTFY_TOPIC}` for iOS push. | `{title, subtitle, factors[{lane, label, value, impact}], output_delta, mode_changed, brightness_shifted, old_mode, new_mode, timestamp, correlation_id}` |

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
| GET | `/health` | System status, `build_id` (running SHA), device connectivity, circuit breakers, ML predictor health, heartbeat tasks, scheduler tasks (cron-style: `retention_sweep`, `fusion_weight_tuning`, `predictor_auto_demote_check`, `journal_nightly`, `morning_routine`, `winddown_routine`, `sunrise_ramp`, `ml_nightly_training` with `last_run`, `last_status`, `last_error`), event logger drops, WebSocket client count |

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
| GET | `/api/automation/mode-volume` | Per-mode Sonos volume curves (defaults + persisted overrides) |
| PUT | `/api/automation/mode-volume` | Update per-mode volume curves (`{mode: {day, evening, night, fade_duration_s}}`) |
| POST | `/api/automation/activity` | Report activity (`{mode, source}`) |
| POST | `/api/automation/override` | Manual mode override |

#### Sonos — `/api/sonos/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sonos/status` | Current playback state |
| POST | `/api/sonos/play` | Resume playback |
| POST | `/api/sonos/smart-play` | Resume if track loaded, else play first favorite (used by Fauxmo) |
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
| GET | `/api/music/bandit-status` | Music bandit arm landscape — arm counts + top picks grouped by `(mode, weather_class)` (Phase B, 2026-05-12) |

#### Weather — `/api/weather/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/weather` | Current weather conditions (cached 5 min from NWS API) |
| GET | `/api/weather/alerts` | Active NWS severe weather alerts for Indianapolis |

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

#### Learning — `/api/learning/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/learning/status` | ML model health, lighting learner + behavioral predictor status |
| GET | `/api/learning/decisions` | Recent ML decisions with reasoning (`?limit=20`) |
| GET | `/api/learning/accuracy` | Prediction accuracy over time window (`?days=7`) |
| GET | `/api/learning/override-rate` | User override rate (7d + 30d). Primary Phase 3 autonomy gate metric (<2/day, 30d). `?window_minutes=5` tunes the "override" window |
| GET | `/api/learning/compare` | A/B accuracy of fusion vs rule-engine vs process-priority on the same backfilled row set (`?days=14`) |
| GET | `/api/learning/lighting` | Current learned lighting preferences |
| POST | `/api/learning/lighting/recalculate` | Trigger immediate lighting preference recalculation |
| GET | `/api/learning/predictor` | Behavioral predictor detailed status |
| POST | `/api/learning/predictor/promote` | Promote predictor from shadow to active |
| POST | `/api/learning/predictor/demote` | Demote predictor back to shadow mode |
| POST | `/api/learning/retrain` | Trigger immediate retrain of all ML models |
| POST | `/api/learning/retune-weights` | Manually trigger the fusion weight-tuning job (normally 3:30 AM cron) |
| DELETE | `/api/learning/reset` | Wipe all ML models and decision/metric tables |

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
| GET | `/api/rules/status` | Engine status + latest pending suggestion (DB-backed) |
| GET | `/api/rules/suggestions?status=&limit=` | Recent rule-suggestion fires (history), newest first, limit ≤ 200 |
| POST | `/api/rules/regenerate` | Force rule regeneration from event data |
| PATCH | `/api/rules/{id}` | Enable/disable a learned rule |
| DELETE | `/api/rules/{id}` | Delete a learned rule |
| POST | `/api/rules/suggestion/accept` | Accept latest pending suggestion → set_manual_override. Returns 410 Gone when the row was auto-expired/superseded between WS broadcast and click (UI dismisses silently) |
| POST | `/api/rules/suggestion/dismiss` | Dismiss latest pending suggestion (idempotent; 200 on no-op) |

#### Camera — `/api/camera/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/camera/status` | Enabled flag, last detection, `detection_source` (face/pose/None), confidence, `pose_available`, `zone` (`desk`/`bed`/None — committed after 15s hysteresis) + `candidate_zone` (pending commit), `posture` (`upright`/`reclined`/None — same 15s hysteresis) + `candidate_posture`, EMA lux, baseline, current multiplier, exposure value |
| GET | `/api/camera/snapshot?annotate=<bool>` | Returns a single JPEG frame from the webcam. When `annotate=true`, overlays the face bounding box, torso pose skeleton, and current lux/multiplier readout. Opt-in (requires camera enabled); never persists frames to disk |
| POST | `/api/camera/enable` | Toggle camera on/off (`{enabled: bool}`); persists to `camera_enabled` setting |
| POST | `/api/camera/calibrate` | Iteratively pick a fixed exposure in [-12, 0], record steady-state `baseline_lux`; persists to `lux_calibration_config` |

#### Guest — `/api/guest/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/guest/wifi` | Returns `{configured, ssid, password, security, qr_payload}` or `{configured: false}` when env vars unset. `qr_payload` is the standard `WIFI:T:<security>;S:<ssid>;P:<password>;H:false;;` URI consumed by `qrcode.toDataURL()`. Credentials live in `.env` as `GUEST_WIFI_SSID` / `GUEST_WIFI_PASSWORD` / `GUEST_WIFI_SECURITY` (default `WPA`); the route escapes `\;,":` per the WiFi-URI spec. Read-only; no auth — the LAN already gates this |
| GET | `/api/guest/scenes` | Lists the 6 safelisted party scenes (`party|neon|miami|arcade|aurora|sunset`) with their `display_name` + per-light states pulled straight from `SCENE_PRESETS` so the frontend can render a 4-dot color preview via `lightStateToCSS` (no Python-side color math). Single source of truth for the picker; missing keys silently filtered |
| POST | `/api/guest/scene/{name}` | Activates the curated preset mapped to `name` via `GUEST_SCENE_WHITELIST` (party→house_party, neon→neon_tokyo, miami→miami_vice, arcade→arcade, aurora→northern_lights, sunset→sunset_strip). Reuses `_activate_per_light` + `_activate_effect_if_needed` from `routes/scenes.py`. Sets a manual override tagged `source="guest"` (party→social, others→relax). Global 15s scene-cooldown returns 429 with `Retry-After`; 400 on unknown name; 503 on disconnected Hue bridge. RFC1918 LAN bypass keeps writes auth-free for visitors |
| GET | `/api/guest/vibes` | Lists the 3 music tiles (`hype|singalong|throwback`) with their friendly labels + currently-resolved Sonos favorite title (read via `_resolve_vibe_mapping` which merges `app_settings["guest_vibe_playlists"]` over `GUEST_VIBE_DEFAULTS`). Frontend renders these on the Vibe page below "Set the Mood" |
| POST | `/api/guest/vibe/{name}` | Switches Sonos to the favorite mapped to this vibe via `SonosService.play_favorite` (case-insensitive title match). Sets a `source="guest"` override of `social`. Independent 15s vibe-cooldown (separate from scene cooldown — lights and music are unrelated controls). 400 on unknown name; 502 if the favorite isn't found on the speaker; 503 on disconnected Sonos |
| POST | `/api/guest/scene/{name}/reset` | Re-applies the baseline preset for an already-active guest scene (`_activate_per_light` + `_activate_effect_if_needed`), stopping any v2 effect overlay first. Skips the 15s scene-cooldown — this isn't a new pick. Used by the frontend's "Reset" button to undo guest tuning (effect/kitchen/brightness) without changing the scene |
| POST | `/api/guest/effect/{name}` | Layer a v2 effect overlay on the active scene (`name ∈ {candle, sparkle, stop}`). All-lights only; calls `hue_v2.set_effect_all` (or `stop_effect_all` for `stop`). Bypasses `EffectManager` so the engine's reconciliation state lags — that's the established guest-route pattern. 3s cooldown returns 429+`Retry-After`; mutual exclusivity is enforced client-side. Frontend's `+Candle` / `+Sparkle` chips |
| POST | `/api/guest/brightness/{direction}` | Bumps every on-light's brightness ±10% multiplicatively (`max(20, round(current × 0.10))` floor for perceptibility). Clamped to `min(254, floor(254 × mode_brightness_config[current_mode]))`. Off-lights skipped — guests can't turn lights on via this knob. Stamps `_manual_light_overrides` so engine reconciliation respects the change. 0.8s throttle returns 429. Empty `updated[]` means every on-light hit ceiling/floor — frontend toasts "Already at max/min" rather than incrementing the level indicator |
| POST | `/api/guest/handback` | Clears any guest-set manual override and returns to host automation via `automation.clear_override(source="guest_handback")`. No cooldown — pressing twice is a harmless no-op on an already-cleared override. The source tag distinguishes "guest pressed Hand It Back" from `source=api:<LAN-IP>` (host kiosk Auto button) in journalctl |
| POST | `/api/guest/toast` | Speaks a guest-submitted toast (`message ≤120 chars` + optional `name ≤30 chars`) through Sonos with a sparkle flourish. Composes `"From {name}: {message}"` if name provided. Wraps `TTSService.speak` (which already duck-and-resumes Sonos); starts sparkle before speak, stops it in `finally`. Trust-the-room v1: no profanity filter, no host-approval gate — just 60s global cooldown and the length cap. 422 on Pydantic validation; 429 with `Retry-After` on cooldown; 503 if TTS or Sonos can't run. Edge case: if a guest had +Sparkle as a scene overlay before the toast, the post-toast stop will end their overlay (re-tap +Sparkle to restore) |

#### Game Day — `/api/gameday/` **(shipped 2026-05-07)**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/gameday/state` | Current `GameDayState` snapshot or `{"status": "no-game"}` |
| GET | `/api/gameday/schedule` | Next 5 scheduled / in-progress Colts games |
| POST | `/api/gameday/test/{event}` | Auth-gated. Fires a synthetic `PlayEvent` through `register_on_play_event` subscribers — exercises the full pipeline (orchestrator → lights + TTS + WS). `event ∈ {touchdown, field_goal, kickoff, end_of_game_win, end_of_game_loss}` |

WS broadcasts: `gameday_state` (every poll cycle when there's an active game), `gameday_play` (per new scoring play), `gameday_celebration` (when CelebrationOrchestrator fires a sequence). Mode-flip auto-fires at T-30 pre-kickoff via `automation.set_manual_override("gameday", source="gameday:auto")`; T+30 post-game auto-clear conditional on `automation.override_source` still being `gameday:auto` (skips if user overrode mid-game). Originally projected `/status`, `/mode`, `/celebrations`, `/config` endpoints weren't needed — mode flips ride the standard `/api/automation/override`, celebration history is journalctl-only (see retention note above), config is hardcoded in `CelebrationOrchestrator.SEQUENCES`.

#### Widgets — `/api/widgets/` **(future)**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/widgets` | All registered external app widgets |
| GET | `/api/widgets/{app}/status` | Current status from external app (plant, bar) |
| PUT | `/api/widgets/{app}/config` | Widget display config (polling URL, refresh interval) |

### Service Interfaces

#### HueService
Controls lights via phue2 (v1 API). Polls bridge every 0.5s (or 5s when the v2 EventStream is delivering pushes), broadcasts changes via WebSocket.

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
Native scenes, dynamic effects, and EventStream push via CLIP API v2. Maintains v1↔v2 UUID mapping cache. Uses two `httpx.AsyncClient` instances: one for REST (`/clip/v2/resource/*`, 10s timeout) and a second for SSE (`/eventstream/clip/v2`, no read timeout).

| Method | Signature | Purpose |
|--------|-----------|---------|
| `connect` | `() → None` | Initialize both clients, build ID mapping |
| `get_scenes` | `() → list[dict]` | List bridge scenes |
| `activate_scene` | `(scene_id: str) → bool` | Activate by UUID |
| `set_effect` | `(v1_light_id: str, effect: str) → bool` | Apply to one light |
| `set_effect_all` | `(effect: str) → bool` | Apply to all lights |
| `stop_effect` | `(v1_light_id: str) → bool` | Stop on one light |
| `stop_effect_all` | `() → bool` | Stop all effects |
| `v1_to_v2_id` | `(v1_id: str) → Optional[str]` | ID conversion |
| `event_stream_loop` | `(ws_manager, hue_v1_service) → None` | SSE consumer — broadcasts on/bri changes via `light_update` at ~150ms latency, ignores color/ct events (v1 polling covers them) |

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
| `report_activity` | `(mode: str, source: str, factors=None) → None` | Process activity report |
| `set_manual_override` | `(mode: str, source: str = "internal") → None` | Override (4h timeout, except `sleeping`); persists to `app_settings["override_state"]`. Wipes `_manual_light_overrides` only when `source` is user-initiated (api/manual/guest/rule_suggestion_accept); autonomous sources in `PRESERVE_PER_LIGHT_OVERRIDE_SOURCES` (winddown, late-night rescue, fusion, predictor, zone+posture rule) keep manual brightness stamps so user slider drags survive routine mode pushes |
| `clear_override` | `(source: str = "internal") → None` | Clear manual override; persists cleared state. Same preserve gate as `set_manual_override`: `timeout_4h` keeps per-light stamps; user-initiated `api:*` clears them |
| `mark_light_manual` | `(light_id: str) → None` | Stamp `_manual_light_overrides[light_id]` so reconcile and screen-sync skip this light. Called from REST `PUT /api/lights/{id}` and the WS `light_command` handler. 4h auto-expiry sweep runs in `run_loop` |
| `load_override_state` | `() → None` | Restore override + zone+posture fire-stamp at boot; called from `bootstrap.py` |
| `register_on_mode_change` | `(callback: async (str) → None) → None` | Subscribe to mode changes |
| `run_loop` | `() → None` | Background loop (60s interval) |
| `update_schedule_config` | `(config) → None` | Hot-reload schedule |
| `update_mode_brightness` | `(brightness: dict) → None` | Hot-reload brightness |

**Late-night rescue** — inside `run_loop`, after the external-off check and before time-based application: if `_get_time_period() == "late_night"` (23:00+), no manual override is active, `_current_mode ∈ {"working", "idle"}`, and `_sonos_is_playing()` returns False, the engine auto-applies `set_manual_override("relax")`. Respects real entertainment modes (gaming, watching, social, sleeping) and music playback as intentional signals. Complements the winddown routine (which runs at 22:00 and sets a 4h override) by covering the 02:00+ edge after that override expires.

**Rescue priority floor** (added 2026-05-16) — `RESCUE_OVERRIDE_SOURCES = {"late_night_rescue", "zone_posture_rule", "watching_sleep_guard"}`. These sources push manual-only target modes (`relax`, `sleeping`) whose default `MODE_PRIORITY` is 0. The displacement guard in `report_activity` computes the override's effective priority as `max(MODE_PRIORITY.get(target, 0), MODE_PRIORITY["idle"])` when the source is in this set — so an `idle (p=1)` sensor report can't silently undo the rescue (`1 > 1` is False), while real activity (`working` p=2, `watching` p=3, `gaming` p=5) still displaces. Bug fixed by this floor: 2026-05-15 night, a rogue `source=ambient` idle POST every 60s displaced the `late_night_rescue → relax` override 47 times across 47 minutes (4-h apartment-stuck-in-idle). The ambient-monitor mode-POST path was the trigger and is gone (see PC Agent section); the floor exists for defense-in-depth against any future source that might post idle/sleeping.

**Override persistence** — `_manual_override` / `_override_mode` / `_override_time` and the zone+posture rule's `_zone_posture_last_fired_at` stamp are written to `app_settings["override_state"]` on every set/clear/rule-fire and restored at boot. Before this fix (2026-05-01), a deploy mid-relax would briefly snap to whatever the PC agent was reporting until the rule re-fired after its 120s dwell. On restore, the engine drops anything past `override_timeout_hours` (sleeping exempt — no timeout by design); the rule stamp is always restored so gate 2's post-expiry refractory window survives intact.

#### LoLChampionService
Drives the bedroom lamps (L2 fabric-shade, L5 clear-glass) to the active League of Legends champion's signature color while gaming mode is in an in-match window. PC agent's `activity_detector` polls the LoL Live Client Data API at `https://127.0.0.1:2999/liveclientdata/activeplayer` when a LoL process is running (5s tick, 30s cache) and appends a `champion` factor to the activity report; the backend service maps champion → RGB via the `champion_color_map` app_setting, converts to Hue HSB via the shared `color_utils.rgb_to_hue_hsb` helper (same per-light sat boost + L5 luma compensation as `ScreenSyncService`), and writes directly through `HueService.set_light`. Skips screen-sync on owned lights via `is_owning(light_id)` consulted in the screen-color route. Clears on mode change leaving gaming (registered callback).

| Method | Signature | Purpose |
|--------|-----------|---------|
| `on_activity_report` | `(report: ActivityReport) → None` | Hooked from `/api/automation/activity`; resolves champion factor + applies color when mode is gaming |
| `apply` | `(champion_name: str) → None` | Look up color in `champion_color_map`, write to L2+L5 |
| `clear` | `() → None` | Drop ownership stamps; screen-sync resumes |
| `on_mode_change` | `(mode: str) → None` | Mode-change callback registered in bootstrap; clears when leaving gaming |
| `is_owning` | `(light_id: str) → bool` | Consulted by the screen-color route to skip champion-owned lights |
| `active_lights` | `() → set[str]` | All light ids currently driven |

#### MusicMapper
Maps modes to Sonos favorites with vibe-based matching and smart auto-play logic.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `load_from_db` | `() → None` | Load persisted mappings |
| `set_mapping` | `(mode, favorite_title, auto_play, vibe_tags) → None` | Upsert with vibe tags |
| `remove_mapping` | `(mode: str) → bool` | Delete |
| `get_best_match` | `(mode: str) → Optional[str]` | Pick highest-priority matching favorite for mode |
| `on_mode_change` | `(mode: str) → Optional[dict]` | Smart play/suggest — plays if idle, suggests if busy |

### Additional Services

#### EventLogger (live)
Middleware service that intercepts all state changes and writes to event tables. Wired into `routes/lights.py` and `routes/music.py`. `log_routine` and `log_interaction` are designed but unused — the `routine_executions` and `user_interactions` tables don't exist yet (see Future Database Tables). Exception handling at `event_logger.py:83-84` is fire-and-forget and currently silent on DB errors — tracked in Known Issues.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `log_mode_change` | `(mode, previous, source) → None` | Write to activity_events |
| `log_light_adjustment` | `(light_id, state, trigger) → None` | Write to light_adjustments |
| `log_playback` | `(track_info, trigger, mode) → None` | Write to sonos_playback_events |
| `log_routine` | `(name, status, error?) → None` | Write to routine_executions |
| `log_interaction` | `(action, detail, page) → None` | Write to user_interactions |
| `flush` | `() → None` | Batch-write buffered events to DB |

**Implementation note:** Events are buffered in memory and flushed every 5 seconds or when buffer exceeds 50 items. This avoids write contention on SQLite and reduces Postgres round-trips.

#### RuleEngineService (live) + LearningEngine (future separate process)
`RuleEngineService` is live in-process: regenerates `LearnedRule` rows every 6 hours from 30 days of `activity_events` (70%+ confidence, 3+ samples), drives the nudge WebSocket messages, exposes 7 endpoints under `/api/rules/`. As of 2026-04-28 (`7b64644`) it also feeds the confidence fusion ensemble: each `check_rules` match calls `fusion.report_signal("rule_engine", ...)` and writes a per-vote `ml_decisions` row with `decision_source="rule_engine"` (`applied=False, broadcast=False`). The process lane got the same per-vote `ml_decisions` row treatment on 2026-04-29 (`86aa880`): `AutomationEngine.report_activity()` now calls `ml_logger.log_decision(decision_source="process", ...)` immediately after `fusion.report_signal("process", ...)`, so per-source accuracy and the analytics constellation see the process voter directly instead of having to reconstruct it from `factors.signal_details` on fusion rows. Two safety layers on rule_engine: row-level filter on `mode in VALID_MODES` so retired modes can't seed rules; an `_BLACKOUT_SLOTS` constant covering M-F 8am-4:59pm (Anthony's TQL office hours) suppresses both rule generation and voting in those slots. Defensive `VALID_MODES` guard in `check_rules` for future bridge-mode retirements.

The table below is the **target separate-process design** — still aspirational; kept as a north star for when event volume justifies splitting out of the main process.

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

#### FauxmoService (live)
Manages Alexa virtual device registration and command handling. 7 virtual WeMo devices, deterministic port allocation for stable Alexa discovery across restarts. Enabled via `FAUXMO_ENABLED=true` in `.env`.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `start` | `() → None` | Register virtual devices, start UPnP listener |
| `stop` | `() → None` | Deregister devices, stop listener |
| `register_device` | `(name, on_callback, off_callback) → None` | Add virtual device |
| `_handle_command` | `(device, state) → None` | Route command to API |

**Virtual devices:** "gaming mode", "relax mode", "cooking mode", "bedtime", "music play", "music pause"

#### GameDayService + CelebrationOrchestrator (shipped 2026-05-07)
ESPN polling, play detection, and celebration orchestration. See `docs/GAMEDAY_SPEC.md` for the full interface contracts (`GameDayService`, `CelebrationOrchestrator`, `PlayEvent`, `GameDayState`) and the "Game Day Engine — shipped 2026-05-07" section below for the architecture summary.

#### NotifierService (shipped 2026-05-17)
Pushes "what just changed and why" through two surfaces: a `notification` WS broadcast consumed by `backend/services/pc_agent/desktop_notifier.py` (PyQt6 frameless toast on the Windows desktop, click-to-expand) AND an `httpx` POST to `https://ntfy.sh/{NTFY_TOPIC}` for iOS native push. The two surfaces share a single payload composed inside the service, so what you see on the desktop matches what lands on the phone.

Triggers: any mode flip (via `register_on_mode_change`), or an effective per-light brightness shift `|Δ| / last ≥ 0.15` (computed by averaging `bri` across the engine's `_last_applied_per_light` — captures camera lux mult, mode-brightness slider, posture overlays, zone overrides in one canonical signal). A 5s `poll_loop` catches brightness drift between mode flips. **Shift semantics are per-poll, not cumulative** — every check (firing or not) updates the snapshot so slow drift across many polls can't accumulate into a false-positive shift notification (2026-05-17 fix — pre-fix, non-firing checks returned without updating `last_brightness`).

The "why" — top-3 factors — comes from flattening `engine._last_fusion_result.signals[].factors[]` across lanes and re-sorting by `impact` desc. No new reasoning logic; the fusion lanes were already computing those factors for analytics, the notifier is just the surface that puts them in front of a human.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `on_mode_change` | `(new_mode, **kwargs) → None` | Registered callback — fires the threshold-check path |
| `poll_loop` | `() → None` | 5s loop; catches brightness shifts between mode flips |
| `emit_synthetic` | `(title, body) → dict` | Verification path used by `POST /api/notification/test` — bypasses gating, exercises full dispatch |
| `close` | `() → None` | Releases the httpx client on shutdown |

**Suppression rules:** DND active (consults `engine.is_dnd_active()`); inside the 10s coalesce window after a previous emit (next emit collapses into the most recent state); first 30s after backend boot (skip fusion-settling noise); mode flips whose source starts with `api:` / `alexa:` / `guest:` or equals `manual` (Anthony pressed it — no toast).

**Config:** `NTFY_TOPIC` doubles as the auth boundary on hosted ntfy.sh (topic name = secret). Unset → desktop toast still works, phone push silently skipped. `NTFY_SERVER` defaults to `https://ntfy.sh`; override for self-hosting.

**Desktop wiring (2026-05-17).** The `desktop_notifier.py` widget is PyInstaller-built (`--onefile --windowed`) via `scripts/build_desktop_notifier.ps1` and installed to `%LOCALAPPDATA%\HomeHub\HomeHubNotifier.exe`. Autostart is a dedicated Task Scheduler entry `"Home Hub Desktop Notifier"` (At-Logon for the desktop user, `RestartCount=3` on crash, working-directory pinned to the install path so `logs\desktop_notifier.log` lives alongside the exe rather than in the repo). Kept separate from the PC Agent Supervisor because PyQt6 requires the main thread — the supervisor's thread-per-agent model can't host it.

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
        mode: One of gaming, watching, working, social, idle, relax, cooking, sleeping
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

**Mode priority (engine enforces automatically):** gameday (6) > gaming (5) > social (4) > watching (3) = cooking (3) > working (2) > idle (1) > sleeping (0)

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

Define per-light states in `automation_engine.py` → `ACTIVITY_LIGHT_STATES`. A few invariants from the April 2026 lighting redesign must hold:

1. **One colorspace per state dict.** Functional modes (working, watching, cooking) use `ct` only. Aesthetic modes (gaming, relax, social) use `hue`/`sat` only. Never mix — `hue_service.set_light` will drop stray `hue`/`sat` from CT commands anyway (colorspace exclusivity), but keeping it clean in the state dict avoids confusion.
2. **Kitchen pair in functional modes and party scenes.** L3 (kitchen front) and L4 (kitchen back) must have matching `bri` + `hue/sat` + on/off state in working, gaming, watching, cooking, and in the 6 guest party scenes (`house_party`, `neon_tokyo`, `arcade`, `miami_vice`, `northern_lights`, `sunset_strip`). They may have slight `ct` variance for depth in functional modes. In relax and custom non-party aesthetic scenes, they're free to diverge.
3. **Post-sunset warmth cutoff.** Evening and night periods must not emit `ct<333` (cooler than ~3000K). Watching's D65 (6500K) bias is a daytime-only exception; evening and night warm to 3000K or warmer.
4. **Night working contrast target.** If the mode is meant to co-exist with an active monitor at night, keep ambient visible enough to hit IES 1:3 contrast (desk lamp at ~2700K/bri=130, living room ambient at ~2200K/bri=60 for the current apartment).

```python
"new_mode": {
    "day": {
        "1": {"on": True, "bri": 180, "ct": 233},    # Living room: ambient fill (4300K)
        "2": {"on": True, "bri": 254, "ct": 210},    # Bedroom/desk: dominant (4800K)
        "3": {"on": True, "bri": 140, "ct": 250},    # Kitchen front (4000K)
        "4": {"on": True, "bri": 140, "ct": 250},    # Kitchen back: PAIRED with L3
    },
    "evening": { ... },  # ct>=333 (strict cutoff), reduced bri
    "night":   { ... },  # Dim ambient + adequate desk, kitchen often OFF
}
```

**How it works:** The engine first checks `mode_scene_overrides` table for user-mapped Hue scenes, then falls through to `ACTIVITY_LIGHT_STATES`. Time period (day/evening/night from schedule config) + current mode determines the per-light states. `LightingPreferenceLearner.get_overlay` merges learned per-property values on top (but CT-vs-HSB exclusivity is enforced at the `set_light` layer, so learner overlays can't tint a CT command). Brightness multipliers apply on top of that. `MODE_TRANSITION_TIME` controls fade speed per mode. Scene drift (relax-only) adds ±15 bri / ±1500 hue perturbation every 30min during long sessions. `_reconcile_effect` runs AFTER `_apply_state` so effect changes don't pop brightness.

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
- All other modes (idle, social, watching, cooking) → GenerativeCanvas
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
- ✓ **Weather widget** — NWS API current conditions (temp, feels-like, humidity, wind, hi/lo) + active severe weather alerts.
- ✓ **Scene browser** — 20 curated scenes organized by category tabs (functional, cozy, moody, vibrant, nature, entertainment, social) + Effects tab + Hue Scenes tab.
- ✓ **One-tap quick actions** — Lucide icon pill buttons for Movie, Relax, Party, Bedtime, Auto, All Off.
- ✓ **Now Playing chip** — Fixed bottom-right, shows album art + track, pulses when playing.
- ✓ **Plant app widget** — polls the external Vercel-hosted plant care app, shows total / needs-water / overdue counts + next watering. Tapping "View Plants" opens the full plant app inside a fullscreen iframe modal layered over the dashboard (no new tab — the kiosk Firefox stays on the dashboard).
- ✓ **Recommendation card QR modal** — on the music page, the "Open in Apple Music" action on each recommendation card opens an in-dashboard modal showing a client-side-generated QR code for the track's `itunes_url`. Anthony scans with his phone; iOS opens it in the native Apple Music app where Add-to-Library actually works. No `target="_blank"`, no kiosk lockout.
- ✓ **Auto-reload on backend deploys** — the WebSocket `connection_status` message carries a `build_id` (short git SHA). When `scripts/deploy.sh` restarts the backend, the kiosk's WS reconnects, sees a new `build_id`, and calls `window.location.reload()`. Eliminates the manual F5 dance after every deploy. Override state (manual mode + zone+posture rule fire-stamp) also persists to `app_settings["override_state"]` so a deploy mid-`relax` doesn't briefly flip to the raw PC-agent mode while the engine re-derives.
- ✓ **Custom scene builder UI** — `CustomSceneEditor.svelte` opens from the scene browser's "New" button; per-light color and effect picker, save/update/delete via the existing `/api/scenes/custom` CRUD endpoints.
- **Remaining:** Bar app widget (future).

### Lighting Improvements (Mostly Complete)

- ✓ **Gradual transitions** — 30-minute evening→night lerp, morning ramp
- ✓ **Activity-aware evening** — Wind-down delays and retries if gaming/watching/social/working
- ✓ **CT (color temperature) support** — mirek values (153=6500K → 500=2000K) as first-class parameter
- ✓ **20 curated scenes** — per-light color harmony (analogous, complementary, triadic), paired effects
- ✓ **Custom scene CRUD** — save/load/update/delete with category and effect
- ✓ **Effect auto-activation** — candle for relax nights, opal for relax days, glisten for watching eve/night. Party scenes use static palettes only (bridge effects flatten per-light HSB to their own color base — incompatible with custom palettes).
- ✓ **Science-based night work** — desk lamp at 3200K + dim ambient fill (contrast-optimized)
- **Remaining:** per-room mode overrides

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
- Alexa discovers virtual devices: "gaming mode", "relax mode", "cooking mode"
- Each device calls the corresponding API endpoint (override, play favorite, activate scene)
- Sub-second latency, $0 cost, runs alongside the server
- Limitation: simple on/off per device, no parameters

**Phase 2 — Custom Alexa Skill + Cloudflare Tunnel (✓ shipped):**
- Invocation: `home hub` (since 2026-05-16). Originally `command center` from 2026-05-05 launch because `home hub` appeared to collide with Alexa's smart-home category — confirmed 2026-05-16 that this was an Alexa+ side-effect, not the literal phrase. Fallback if voice routing ever regresses: `the home hub` → `home hub apartment` → `command home` → revert to `command center`. See `alexa_skill/README.md` §"Invocation name history"
- AWS Lambda (`home-hub-skill` in `us-east-1`) → Cloudflare Tunnel (`home-hub.gatte-home.com`) → tunnel proxy (`backend/api/tunnel_proxy.py` on `127.0.0.1:8002`) → main backend on `127.0.0.1:8000`
- Tunnel-origin auth: `X-Tunnel-Origin: cloudflare` header injected by tunnel proxy forces require_api_key to demand BOTH `X-API-Key` AND `X-Skill-Token` (skips loopback/RFC1918 bypass)
- Source attribution: lambda sets `X-Source: alexa:<intent>` on every API call (set by a `ContextVar` in the dispatcher, read by `_call_homehub`). Backend write routes call `source_from_request(request, fallback=...)` from `backend.api.auth` and tag the resulting `activity_events` / `light_adjustments` / `sonos_playback_events` / `scene_activations` row accordingly. Without this, tunneled Alexa traffic was indistinguishable from any other LAN write — every row landed as `api:127.0.0.1`. **Latent gap closed 2026-05-07 (commit `31a1edf`):** `set_manual_override` accepted a `source` kwarg for journalctl + cooldown logic but its `log_mode_change` call hardcoded `source="manual"`, flattening every override write in `activity_events` to `"manual"` regardless of caller. Pre-fix `activity_events` rows where `source="manual"` are unreliable — they could be Alexa, guest, dashboard, or autonomous (winddown / late_night_rescue / fusion). See memory `project_override_caller_telemetry.md`
- Intents shipped: `SetModeIntent`, `PlayMusicIntent`, `PauseMusicIntent`, `ReleaseOverrideIntent` (auto override clear — carved out because single-token slot values misroute reliably), `AdjustBrightnessIntent` (±10% relative bump via new `/api/lights/brightness/{up\|down}`), `SetEffectIntent` + `StopEffectIntent` (candle/fire/sparkle/prism/glisten/opal), `ActivateSceneIntent` (6-scene safelist mirroring `/guest`: party/neon/miami/arcade/aurora/sunset), `EnableDNDIntent` + `DisableDNDIntent` (default 2h window), `AdjustVolumeIntent` (±5 Sonos volume via new `/api/sonos/volume/{up\|down}`), `NextTrackIntent` + `PreviousTrackIntent`, `WhatModeIntent` + `WhatsPlayingIntent` (read-only status queries), plus built-ins (`AMAZON.HelpIntent`, `AMAZON.CancelIntent`, `AMAZON.StopIntent`). See `alexa_skill/` for code + manifest + setup README
- **Critical: requires Alexa+ (Amazon's generative-AI tier) to be DISABLED.** Alexa+'s LLM routing intercepts custom skills and falls back to smart-home. See `alexa_skill/README.md` "Critical prerequisite" section
- Routing gotchas (sample collisions): when two custom intents could plausibly share a verb pattern (e.g. "turn on {X}"), the same shape must exist on every colliding intent so NLU disambiguates by slot-type validity — otherwise the lone owner raw-fills the slot and the handler hits a dead-end clarify prompt. SetModeIntent therefore mirrors SetEffectIntent's "turn on {Mode}" pattern
- Slot id vs value: when a slot type's `id` differs from its `name.value` (currently HOMEHUB_SCENE: spoken "party" → id "house_party"), Lambda must read the resolved id for backend lookups. `_resolved_slot()` in `lambda_function.py` returns `(id, value)` for that path; `_slot_value()` is fine for slot types where id == value name (HOMEHUB_MODE, HOMEHUB_EFFECT, HOMEHUB_DIRECTION, HOMEHUB_VOLUME_DIRECTION)
- Slot names are globally unique to one type: a slot **name** can bind to only one slot type across the whole skill model. AdjustBrightnessIntent's `Direction → HOMEHUB_DIRECTION` forced AdjustVolumeIntent to use the distinct name `VolumeDirection → HOMEHUB_VOLUME_DIRECTION`; reusing `Direction` failed Build Model
- Volume token hijack (unfixable from the skill side): Alexa's wake-word router intercepts "louder", "quieter", "softer", "volume up", "volume down", "make it louder" before any custom skill receives the utterance. AdjustVolumeIntent samples must use up/down + a music/song anchor ("turn the music up", "music down", "bump the song up"). Lambda also raw-maps the louder/quieter family to up/down for utterances that *do* slip through inside longer skill-directed phrases
- Future intents (deferred): absolute volume ("set volume to 5"), DND/weather status queries, missing-slot reprompts, routine triggers, favorite-by-name play, custom-scene-by-name activation

### Game Day Engine — shipped 2026-05-07

See `docs/GAMEDAY_SPEC.md` for the full spec; this section is the architecture summary.

- ✓ **ESPN API integration** — `GameDayService` polls `site.api.espn.com/apis/site/v2/sports/football/nfl/...` (no auth, no key) for the Colts schedule (15-min cache) and live play-by-play (10s during in-progress, 60s during pregame/final).
- ✓ **Play detection** — Diffs `summary.scoringPlays[]` per tick; emits `PlayEvent` for new TDs/FGs/kickoffs through `register_on_play_event` subscribers. Best-effort regex parse of player/kicker/yards from ESPN play text (validated against real 2025 Colts game data — handles both canonical and abbreviated formats).
- ✓ **Celebration orchestration** — `CelebrationOrchestrator` subscribes; runs custom light sequences (Colts blue/white pulse rotation for TD, single-pulse-flash for FG, baseline activation for kickoff, win/loss split for end-of-game) with 8s cooldown. Lighting-curator-reviewed palette.
- ✓ **GameDay page** — Edge-to-edge field-bleed layout, scoreboard + last-play HUDs floating over the field via existing glass-card chrome. Subscribes to `gameday_state`/`gameday_play`/`gameday_celebration` WS broadcasts via the new `gameday` Svelte store.
- ✓ **3D Threlte field** — Pure prop-driven `FootballField` component: top-down low-poly mesh, vertical yard lines, Colts-blue + neutral endzone tints, ball marker easing toward possession-derived position.
- ✓ **Mode auto-flip** — T-30 pre-kickoff sets gameday override (`source="gameday:auto"`); T+30 post-game conditionally clears only if user didn't override mid-game (verified via `automation.override_source`, a property added in Slice A).
- ✓ **Dynamic celebration TTS volume** — `celebration_volume_policy.py` reads game state (WPA primary, margin+time fallback) × apartment context (sleeping/DND/late-night/camera-absent) to scale Sonos volume `5-50` or suppress entirely. See GAMEDAY_SPEC.md §9.
- **Pre-game ambient mode** — deferred to v2 (continuous Colts-tinted lighting before kickoff).
- **Commercial-break detection** — deferred to v2 (would require a separate ESPN signal not currently exposed).

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

- **PC Agent Supervisor** via Windows Task Scheduler (`"Home Hub Agent
  Supervisor"`, hidden `pythonw.exe`, **two triggers**: at-logon with
  30s delay + 5-min watchdog repetition trigger added 2026-05-16) plus
  `RestartCount=999 / RestartInterval=1m` on observed failure. Manages
  the three agents (activity_detector, ambient_monitor,
  screen_sync_agent) as child processes. Pointed at the Latitude via
  `--server http://192.168.1.210:8000`. The watchdog catches the class
  of failure where the supervisor dies but Task Scheduler doesn't see
  a launcher failure (e.g. a Bash background subprocess reaped along
  with its parent session — observed 2026-05-15→16, 17h apartment
  stuck in idle). `MultipleInstancesPolicy=IgnoreNew` plus the
  supervisor's PID-file mutex prevent duplicate spawns during the
  5-min polls. Install/reinstall via
  `scripts/setup-supervisor-task.ps1` (elevated).
- **Desktop Notifier** via Windows Task Scheduler (`"Home Hub Desktop
  Notifier"`, At-Logon trigger for the dev-machine user,
  `RestartCount=3 / RestartInterval=1m`). Runs the PyInstaller-built
  `HomeHubNotifier.exe` from `%LOCALAPPDATA%\HomeHub\` and subscribes
  to `ws://192.168.1.210:8000/ws` for `notification` events. Kept
  separate from the PC Agent Supervisor (PyQt6 must own the main
  thread; the supervisor's thread-per-agent model can't host it).
  Restart via `Start-ScheduledTask -TaskName 'Home Hub Desktop
  Notifier'`; rebuild via `scripts/build_desktop_notifier.ps1`.
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

**Code changes** flow from dev → production via the `/deploy-home`
Claude Code skill, which handles the full lifecycle end-to-end:

1. Edit code on the Windows dev machine
2. `git commit` + `git push` happen inside the skill
3. SSH to the Latitude runs automatically — passwordless via the
   `id_ed25519_homehub` keypair and `~/.ssh/config` Host alias
   `homehub` (set up 2026-05-06). Direct CLI shorthand:
   `ssh homehub "cd ~/home-hub && ./scripts/deploy.sh"`
4. The `deploy-verifier` subagent auto-spawns post-deploy: confirms
   `build_id` rolled forward (the SHA is now exposed on `/health`),
   runs an API smoke across every major endpoint group, and scans
   the post-restart event window for regressions before reporting
   STATUS

`scripts/deploy.sh` handles the remote side: `git pull --ff-only`,
diffs `HEAD` to detect what changed, reinstalls Python deps if
`requirements.txt` changed, runs `npm install` if
`frontend-svelte/package*.json` changed, rebuilds the frontend if
source files changed, restarts `home-hub.service` if backend code
changed, health-checks the backend via `/health` after restart, and
restarts `home-hub-ambient.service` if the ambient monitor changed.
Exits non-zero if the health check fails.

**`.env` updates** (new secrets, API keys, etc.) are not git-tracked
and must be nano-edited directly on the Latitude via SSH, followed by
`systemctl --user restart home-hub.service`.

### Secondary access

Mobile phone (PWA) or any browser on the LAN can hit
`http://192.168.1.210:8000` for the full dashboard. Same dashboard as
the kiosk. Writes are gated by `X-API-Key`, but the auth dep
auto-bypasses any RFC1918 / loopback / link-local caller — so LAN
devices see no auth friction. External callers (e.g. a future
Cloudflare Tunnel) would need to present the header.

### Cloud services used

NWS API (weather + severe alerts, api.weather.gov — free, no key),
sunrise-sunset.org (astronomical data — free, no key), Google Maps
(commute), Last.fm (music discovery), iTunes Search (previews), ESPN
(future, game data). All are free-tier or no-cost APIs. Core features
(lights, music, automation) work without internet — the Hue bridge
and Sonos speaker are LAN-only.

---

## Roadmap

### Phase 1: Core Fix & Foundation (Now — April 2026)

- ✓ Fix automation timing: gradual evening transitions (30-min lerp before winddown_start_hour)
- ✓ Activity-aware wind-down: delays 30 min and retries up to 4x if gaming/watching/social/working
- ✓ Add vibe tagging to mode-playlist mapping (multiple favorites per mode with vibe column)
- ✓ Event logging tables live: `activity_events`, `light_adjustments`, `sonos_playback_events`, `scene_activations`, plus `learned_rules` / `ml_decisions` / `ml_metrics` added alongside the Phase 3 + ML work. `EventLogger` service wired into `routes/lights.py` and `routes/music.py`
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
- ✓ **Weather widget** — NWS API current conditions (5-min cache) + severe weather alerts (2-min cache) + sunrise/sunset from sunrise-sunset.org
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
- ✓ **Nudge Notification System** (Phase 3c) — `mode_suggestion` WebSocket message when idle and a rule matches. `ModeSuggestionToast.svelte` with accept/dismiss buttons.
- ✓ **Persistent Suggestion Surface + History** (Phase 3c.2, May 2026) — `rule_suggestions` table records every fire (`pending`/`accepted`/`dismissed`/`expired`/`superseded`); `ModeSuggestionCard.svelte` renders an inline banner on the Home dashboard above the widget grid until resolved (toast suppresses on `/` to avoid duplication, stays for cross-page coverage). 60-minute server-side auto-expiry on the 60s automation tick; boot-time `restore_pending_on_boot()` re-broadcasts so deploys don't drop the active card. Settings page surfaces a `RuleSuggestionHistoryCard` showing the last 50 fires with status pills.
- ✓ **Analytics Dashboard Page** (Phase 3d) — `/analytics` route. Originally mode distribution donut, quick stats, hourly patterns, learned rules, recent activity, top Sonos/scenes. Redesigned April 15 as a live decision pipeline dashboard: SVG confidence ring at top showing fused confidence (0-100%), 5 signal cards (process, camera, audio ML, behavioral predictor, rule engine) with animated confidence bars and agreement indicators, output card showing effective mode + lights, decision history. Historical analytics moved to a collapsible section below.
- ✓ Fauxmo Alexa integration — 7 virtual WeMo devices (cooking mode, relax mode, arcade mode, party mode, bedtime, music, all lights). Deterministic port allocation for stable Alexa discovery across restarts. Smart-play endpoint (`/api/sonos/smart-play`) for music command: resumes if track loaded, else plays first favorite. Fauxmo status exposed in `/health` endpoint. Enabled via `FAUXMO_ENABLED=true` in `.env`
- ~~**WiFi Presence Detection**~~ (Phase 3e) — **Retired 2026-04-28** (`b8fdbfe`). iOS Shortcut webhooks flapped despite three rounds of mitigation; ARP probing alone wasn't worth the plumbing. Home/away as a concept is gone — Hue native geofencing handles arrivals/departures outside Home Hub. See git history for the original implementation.
- Override pattern analysis tracked via `override_rate` in patterns API. v1 was nudge-only; auto-apply shipped April 15 via confidence fusion (Phase 4.5 ML Phase 3)

### Phase 4: Game Day (May 2026, ahead of schedule)

Originally targeted July–August 2026. Phase A + Phase B both shipped in early May; preseason 2026-08-13 is now a tuning-and-validation window rather than a build window.

- ✓ **Phase A complete (2026-05-06)** — spec, interface contracts, mockup placeholder. See `docs/GAMEDAY_SPEC.md`. v1 scope: TD + FG + kickoff + end-of-game. Pre-game ambient + commercial deferred to v2. Mode trigger: auto-flip 30 min pre-kickoff via ESPN schedule + manual override. Mode integration: first-class, priority 6 (top auto-detected slot).
- ✓ **Phase B complete (2026-05-07)** — full worktree-fleet experiment validated end-to-end (see `docs/AGENT_STRATEGY.md` Part 4 for retrospective):
  - Slice A: `GameDayService` with ESPN polling, `/api/gameday/*` routes, T-30 pre-kickoff auto-flip, T+30 post-game auto-clear that no-ops if user manually overrode mid-game, real-fixture parser test against 2025-09-07 Colts game.
  - Slice B: `CelebrationOrchestrator` with custom light + TTS sequences for TD/FG/kickoff/end-of-game; 8s cooldown; lighting-curator-reviewed Colts-blue palette; `_COLTS_BLUE_SAT=215` matching gaming-retune precedent.
  - Slice C: SvelteKit `/gameday` page + Svelte store + WS subscription; preserved field-bleed layout; in-game and no-game branches.
  - Slice D: pure Threlte `FootballField` component — top-down low-poly field, vertical yard lines, Colts-blue + neutral endzone tints, ball marker easing toward possession-derived position, HTML scoreboard overlay.
  - Integration: `bootstrap.py` wires both services + registers callbacks; `init.js` central WS dispatcher routes `gameday_state`/`gameday_play`/`gameday_celebration` into the store; `+page.svelte` imports the FootballField component.
  - **Dynamic celebration TTS volume** (Decision 1.8, also 2026-05-07): `celebration_volume_policy.py` is a pure function that scales Sonos volume by WPA (when ESPN's win-probability has indexed the play) or margin+time fallback, with apartment-context modifiers (sleeping/DND/late-night/camera-absent suppressions or caps) and silent on losing blowouts. WPA is sourced from ESPN's `summary.winprobability[]` array, sign-flipped for away games. See GAMEDAY_SPEC.md §9.
- ✓ **Phase C complete (2026-05-07)** — `gameday` added to FloatingNav (Trophy icon between Music and Analytics), MODE_CONFIG entry in `theme.js` with Colts blue (#003594) + silver/gold generative palette, `HOMEHUB_MODE` Alexa slot + lambda `VALID_MODES` + disambiguation prompt. Synonyms: "game day", "colts", "colts game", "football", "football mode". Verified end-to-end via Alexa: "set relax mode" round-tripped to `activity_events` with `source=alexa:SetModeIntent` (the verification surfaced and led to fixing a latent source-attribution bug in `set_manual_override` — see commit `31a1edf`).
- **Live preseason validation 2026-08-13** — first real Colts game. Synthetic test endpoint (`POST /api/gameday/test/{event}`) exercises the full pipeline today; preseason is for iterating on palette/TTS/timings against reality with the lighting-curator subagent.

### Phase 4.5: Machine Learning (April-September 2026)

ML capabilities to replace hardcoded rules with learned behavior and add new
sensing (camera, audio classification). Full specification in **`docs/ML_SPEC.md`**.

- ✓ **ML Phase 1 (Code complete):** Behavioral mode prediction (LightGBM, **shadow mode — not yet promoted, pending ~500 activity events**), adaptive lighting preferences (EMA — **active**), ML decision logger, model manager (nightly retraining at 4 AM), feature builder, full `/api/learning/` REST API, `ml_decisions` + `ml_metrics` DB tables. Original Phase 1 exit criteria ("audio classifier active, behavioral outperforming rules") are not yet met — both predictors sit in shadow mode
- ✓ **ML Phase 2 (Code complete):** Smart screen sync K-means (**active**), music selection bandit Thompson sampling (**active**), YAMNet audio scene classification (**shadow mode** — promotion gated on ML > RMS + 10pp accuracy), MediaPipe camera presence detection (**active**, 15-frame ~30s idle) with pose fallback, zone mapping (desk/bed, expose-only), and posture classification (upright/reclined, expose-only — shipped April 19) all on the same 2s poll cadence, adaptive lux brightness for working + relax modes (**active** — shipped April 18: calibrated fixed exposure, baseline-anchored piecewise-linear curve, EMA α=0.3 at 2s poll, ±15% bri swing, kitchen-pair-preserving)
- ✓ **Zone+posture → relax actuation rule** (**live** — shipped April 19, promoted April 27, social-supersede added May 3): first sensor signal that drives a mode *transition*. Fires `set_manual_override("relax")` when the camera sustains `zone=bed + posture=reclined`. Eligible modes are `{idle, working, social}`; dwell is 120s for idle/working and 180s for social. Gated on (a) no active manual override **OR** an active social override that's ≥30min old (`ZONE_POSTURE_RULE_SOCIAL_MIN_AGE_SECONDS`), (b) `effective_mode ∈ ELIGIBLE_MODES` (override_mode if override else current_mode), (c) evening-hour or weekend-afternoon (≥13:00 Sat/Sun), (d) 4h refractory since last fire. `ZONE_POSTURE_RULE_APPLY=true` by default. The May 3 change closes the architectural gap surfaced by the 5/02 guest-visit pattern (social override outliving its context after guest left + Anthony went to bed). Projector-from-bed still carves itself out because the sit-up-against-headboard posture stays `upright`. Misfire surface narrow: requires social override ≥30min old + sustained reclined ≥180s + evening/weekend afternoon — worst case is one tap to correct during in-bedroom socializing.
- **ML Phase 3 (In Progress):** ✓ Confidence fusion — **4-signal** weighted ensemble (`ConfidenceFusion`) combining process detection, camera, audio classifier, and rule engine. Behavioral predictor lane stripped 2026-04-27 after a single-class collapse audit; presence lane removed 2026-04-28 with the home/away retirement. Weights renormalized to `process 0.438 / camera 0.250 / audio_ml 0.187 / rule_engine 0.125`. Auto-apply at 95%+ when idle, stale process override at 98%+ with 80%+ agreement. ✓ Live pipeline dashboard with SVG confidence ring and per-signal gauge cards. ✓ **Nightly accuracy-driven weight-learning shipped** — `fusion_weight_tuning` ScheduledTask at 3:30 AM derives per-source accuracy from `MLDecision.factors.signal_details` over 14 days, calls `update_weights_from_accuracy()`, and persists per-source rows to `ml_metrics` (`561d4f1`, 2026-04-28). Manual trigger at `POST /api/learning/retune-weights`. ✓ **Override rate + A/B comparison endpoints shipped** — `/api/learning/override-rate` (7d + 30d windows) is the primary autonomy gate metric; `/api/learning/compare` runs fusion vs rule-engine-only vs priority-only on the same backfilled rows. ✓ **Predictor calibration shipped 2026-04-28** (`82c72ed`) — train/serve feature parity (4 features no longer default to 0 at inference), `SUGGEST_THRESHOLD` 0.70→0.30, full-class softmax distribution logged into `MLDecision.factors.distribution`, stale-encoder gate refuses to load models whose `label_encoder` references retired modes. ✓ **Rule-engine fusion vote stays fresh during manual overrides** (`b8c285a`, 2026-04-29). ✓ **Rule-engine fusion lane verified end-to-end and bootstrap guardrail added** (`7282b11`, 2026-05-03) — after the 4/29 fix, prod still showed `never_reported=["rule_engine"]` on the old PID. A test rule inserted into the live slot fired correctly on the new PID (DIAG entry → MATCH → `report_signal ok` → `log_decision ok`), confirming the wiring is sound; the silence on the older process remains unexplained but is no longer reproducible. The DIAG logs were replaced with a single WARN at the MATCH point that fires only if `_fusion is None or _ml_logger is None`, so any future bootstrap wiring drift surfaces immediately in journalctl instead of silently parking the lane in `never_reported`. ✓ **Predictor class-balanced training shipped 2026-05-06** (`d3e1c7f`) — inverse-frequency sample weights in `_train_sync` so minority classes (watching/relax/gaming) aren't starved by working-class dominance; per-class val accuracy logged to journalctl per retrain. ✓ **Predictor truth-tagging architectural fix shipped 2026-05-06** (`80e8db7`) — predictor is idle-gated, so the prior "tag with leaving mode" semantic produced `actual_mode='idle'` for every predictor row, making the standard accuracy query report 0% on a 72%-accurate model. New predictor-specific path in `MLDecisionLogger.on_mode_change` tags ml-source rows with the entering mode on idle → predictable-mode transitions; historical backlog re-tagged via one-shot SQL migration. **Remaining:** analytics-page Svelte card surfacing override-rate + A/B comparison; threshold tuning once ≥30 days of shadow+backfill data accrues; predictor lane re-add to fusion gated on 5/11 weekly evaluator's per-class accuracy report (≥30% on watching/relax with sample size ≥10).
- All inference local (CPU-only on Latitude), privacy-first, every ML feature has a non-ML fallback

### Phase 5: Polish & Expand (September 2026+)

- Remaining mode backgrounds (social/club, watching/drive-in) + improved art assets (transparent layers, wider tiles)
- Custom Alexa Skill (full voice control)
- Apple Music API integration ($99/year) — catalog browsing (search by genre/mood, dynamic playlists). Phase A (DIDL-Lite Now Playing metadata for HTTP streams), Phase A.5 (always-shuffle + random queue start via `play_favorite`), and Phase B (weather-aware bandit arm key `(mode, period, weather_class, title)` with legacy 3-tuple migration + warm-start) all shipped 2026-05-12
- Bar app widget integration
- Seasonal lighting adjustments
- Guest mode polish (mini-app shipped 2026-05-02 — bottom nav + WiFi/Bar/Plants/Vibe pages, 6 party scenes with live color previews, 3 music vibe tiles via Sonos favorites; remaining: Pi-hole DNS for `guest.homehub.local`, settings UI for `guest_vibe_playlists` mapping, optionally a free-text "tell the host" channel)

## Technical Limitations & Constraints

- **Hue bridge self-signed SSL** — httpx calls require `verify=False`. Cannot be changed.
- **Sonos UPnP** — No authentication, but also no encryption. LAN-only by design.
- **SoCo Apple Music support** — Can play individual tracks and queue cloud favorites via `add_to_queue` (v0.26.0+). Apple Music *shortcut* favorites (artist/station containers) have no static URI and cannot be queued via SoCo — those are flagged in the mode→playlist mapper UI. Cannot browse the Apple Music catalog; that requires the $99/year Apple Music API. Now Playing metadata for plain HTTP streams (iTunes previews, TTS MP3s) is populated via DIDL-Lite envelope (shipped Phase A, 2026-05-12).
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
