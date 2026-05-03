# Future Development Ideas

> Feature ideas beyond the current roadmap — large and small.
>
> **Last updated:** 2026-05-03

---

## Completed (April 2026)

Major work that landed during April 2026, roughly chronological. Tracked here so this doc reflects what's shipped vs. what's still planned. Cross-references to numbered ideas below where applicable.

### ML & automation
- **2026-04-15 — Phase 3 confidence fusion shipped.** Initial 5-signal weighted ensemble (`confidence_fusion.py`); auto-apply at 95%+ when idle, stale-process override at 98%+ with 80%+ agreement.
- **2026-04-18 — Accuracy-driven fusion weight learning.** `fusion_weight_tuning` ScheduledTask at 3:30 AM walks 14 days of fusion rows and retunes per-source weights. Manual trigger at `POST /api/learning/retune-weights`.
- **2026-04-19 — Fusion shadow logging + windowed `actual_mode` backfill.** Every 60s tick writes a shadow `ml_decisions` row; mode transitions bulk-update `actual_mode` across the just-ended session window (2h cap). Override-rate metric and A/B comparison endpoints landed alongside.
- **2026-04-19 — Watching-posture sliders.** Three live-patchable sliders backed by `watching_posture_config` in `app_settings`; `PUT /api/automation/watching-posture`.
- **2026-04-21 — Analytics constellation v2 (`0a8c220`, `1089523`).** Force-directed SVG with voter inner ring and context outer ring. Camera tuning (`MIN_FACE_CONFIDENCE` 0.2→0.15, `ABSENT_THRESHOLD` 7→15) shipped in the same change to fix low-light bed flapping.
- **2026-04-26 — Gaming lock bug fix.** Stacked foreground+idle gate stops stale gaming processes from holding mode. Symmetric night working↔watching stickiness (`DWELL_LEAVE_WORKING_NIGHT=300s`) and `DWELL_DEFAULT` 30s→60s.
- **2026-04-26 — Transit lighting fix (`6122cd2`).** `clear_transit_override` reverts against `self.current_mode` (not `_current_mode`); `STATIONARY_ZONES` gate prevents transit firing when `zone=bed`. Closed the bed-watching-TV light chaos.
- **2026-04-27 — Zone+posture rule promoted to live (`6122cd2`).** `ZONE_POSTURE_RULE_APPLY` default flipped True; dwell lowered 300s→120s. Override applied via `set_manual_override("relax", source="zone_posture_rule")`. Item #20 below; the carve-outs listed there remain open.
- **2026-04-27 — Behavioral predictor diversity gate (`abe6343`).** `/api/learning/predictor/promote` refuses to load a model whose label encoder targets only one class. Retired the degenerate `away`-only model post-presence-retirement.
- **2026-04-27 — Behavioral predictor lane stripped from fusion (`c0b50ad`).** Single-class collapse audit found 898/898 → one class at 0.64% real accuracy. Predictor still runs as a standalone service (`/api/learning/predictor`); no longer votes.
- **2026-04-27 — Predictor train/serve feature parity (`82c72ed`).** Inference builds features through the same code path as training, closing a divergence that masked real prediction quality.
- **2026-04-28 — rule_engine fusion lane wiring (`7b64644`).** Dropped retired-mode rows in `regenerate_rules`; wired `ml_logger.log_decision(decision_source="rule_engine", ...)`; defensive `VALID_MODES` guard at vote time; M-F 8am-4:59pm office-hours blackout to suppress generation/voting outside genuine at-home hours. Closes audit `[H]` "rule_engine fusion lane silent in prod."
- **2026-05-03 — rule_engine fusion lane verified end-to-end + bootstrap WARN guardrail (`7282b11`).** After the 4/29 fix, prod still showed `never_reported=["rule_engine"]` on the old PID. Added DIAG logs at the call site + `check_rules` body and inserted a test rule into the live slot — saw `entry → MATCH → report_signal ok → log_decision ok` on the new PID, confirming the wiring is sound. The silence on the older process remains unexplained but is no longer reproducible. DIAG logs replaced with a single WARN at the MATCH point that fires only if `_fusion is None or _ml_logger is None`, so any future bootstrap wiring drift surfaces immediately in journalctl instead of silently parking the lane in `never_reported`.
- **2026-05-03 — Zone+posture rule social-supersede (`b2061d9`, item #20 carve-out).** Original `ELIGIBLE_MODES = {idle, working}` plus Gate 1's blanket "any override bails" meant the rule could never catch the bed-reclined-after-social pattern. 30 days of `activity_events` showed 6 social→relax manual press sequences where the override outlived its context (guest left, host went to bed); the 5/02 21:07 social → 5/03 04:22 manual relax press was the seventh. Three coordinated changes: `ELIGIBLE_MODES` now includes `social`; Gate 1 bypasses for a social override only if `(now - _override_time) ≥ 30min` (`ZONE_POSTURE_RULE_SOCIAL_MIN_AGE_SECONDS`); dwell extends 120s → 180s when `effective_mode == 'social'` (`ZONE_POSTURE_RULE_DWELL_SOCIAL_SECONDS`). Gate 4 now evaluates `effective_mode = override_mode if override else current_mode`. `factors` dict gains `effective_mode` + `dwell_required` so `ml_decisions` shows which path triggered. 4 new tests in `TestZonePostureRule` (non-social blocks, fresh social blocks, old social superseded, longer dwell respected); 93/93 pass. Misfire surface narrow — fresh sub-30-min social, headboard-upright posture, and the 4h refractory all carve out the obvious failure modes.
- **2026-05-03 — YAMNet shadow Checkpoint 1 finding (`7f3d8e0` rolled out 5/01).** 36h / 90,978 rows: silence 83.5% / `speech_single` 16% / music 0.3% / **`speech_multiple` 0 fires** including the Sat 5/02 guest-visit ground-truth window. Avg `speech_single` confidence during the guest visit was 0.838. The `speech_multiple ≥ 0.80` social gate is structurally unreachable on this hardware. Checkpoint 2 (2026-05-09) reframed from "flip-or-not" to picking among: (a) retarget the social gate to sustained `speech_single` + an RMS floor, (b) retrain YAMNet with multi-speaker examples, (c) abandon audio-driven social detection on this hardware.

### Architecture
- **2026-04-27 — `presence_service` and home/away retired (`b8fdbfe`).** Phone-WiFi presence (iOS Shortcut + ARP probing) was too unreliable on its own. Fusion drops the phone-WiFi lane; `/api/automation/presence/*` routes removed; `mode='away'` no longer in `VALID_MODES`. Camera presence (face/pose) and Hue's native geofencing carry the home/away signal now.
- **Camera-at-desk veto pattern.** Four push-toward-relax pathways (winddown, late-night rescue, behavioral predictor consumer, fusion `can_override`) gate on `is_at_desk_fresh()` so the system doesn't force relax while Anthony's actively at the desk.
- **Override caller telemetry source kwarg.** `set_manual_override` / `clear_override` accept + log a `source` kwarg on all 7 callers — diagnose mysterious override flips via `journalctl`.
- **2026-04-28 — mcp_server presence cleanup (`dcb3e30`).** Dead-code deletion of the standalone `get_presence_status` MCP tool and the 404'ing presence call in `get_live_state`'s aggregator.
- **2026-05-01 — Override persistence across restarts (`ac1c8ed`).** `_manual_override` / `_override_mode` / `_override_time` and the zone+posture rule fire-stamp now persist to `app_settings["override_state"]` via `_persist_override_state()` on every set/clear/rule-fire; `load_override_state()` restores at boot, dropping anything past the 4h timeout (sleeping exempt). Mirrors the existing `dnd_state` pattern. Surfaced when a deploy mid-`relax` snapped to `working` for ~6 minutes until the rule re-dwelled — the in-memory override was wiped, the PC agent's `working` report flowed through unguarded.

### Documentation
- **2026-04-28 — `docs/PROJECT_SPEC.md` updated for home/away retirement + predictor calibration (`683f483`).**
- **2026-04-28 — `docs/ML_SPEC.md` updated to v3 4-lane fusion shape (`23a9f03`).** Removed 5/6-lane descriptions; added v3 retirement block; updated Phase 3 dependency diagram.
- **2026-04-29 — fusion vote stays fresh during manual overrides (`b8c285a`).** Removed redundant `not self._manual_override` guard at the rule_engine call site so the lane keeps voting through sleeping/winddown/late-night-rescue overrides; `check_rules()` already gates the user-nudge path on `current_mode==idle` internally.
- **2026-04-29 — full doc audit & refresh.** Closed remaining 4/28 partial-update drift in `ML_SPEC.md` (header date, fallback chain, fusion code example, WS signals shape, `ml_metrics` table, `compute_accuracy_by_source`, late-night decay). Refreshed `CONFIDENCE_FUSION.md` worked examples to v3 4-lane shape. Added `auto-demote 2026-05-04` callout to PROJECT_SPEC + ML_SPEC. Archived `Audit_Summary.txt` to `docs/archive/`.

### Near-term polish
- **2026-04-29 — DND Mode shipped (item #4).** `AutomationEngine.is_dnd_active()` gates autonomous mode-setters; user-source overrides (`api:<ip>`) still pass. Persisted to `app_settings["dnd_state"]`, restored on boot, auto-clears once expiry tick fires in `run_loop`. Endpoints `POST/DELETE /api/automation/dnd`, status fields appended to `GET /api/automation/status`. Frontend: subtle `DND • Xh Ym` chip on `ModeIndicator`, full toggle + duration picker on Settings. Gated paths: `report_activity`, `set_manual_override`, `clear_override`, late-night rescue, zone+posture rule, behavioral-predictor toast, music auto-play / weather suggestion, morning routine, sunrise ramp, winddown.
- **2026-04-29 — Apartment Logbook shipped (item #19).** New `JournalService` (`backend/services/journal_service.py`) reads activity / light / sonos / scene events for the previous local calendar day and writes Markdown to `data/journal/YYYY-MM-DD.md`. ScheduledTask `journal_nightly` at 02:00 daily. Endpoints `GET /api/journal/entries`, `GET /api/journal/{date}`, `POST /api/journal/generate/{date}`. Frontend route `/journal` (date rail + markdown render); intentionally excluded from `FloatingNav`. Pure read; no actuation.
- **2026-04-29 — Vital Signs Strip shipped (item #15).** Always-visible 22px strip at the kiosk bottom. New `GET /api/vitals` aggregator (`backend/api/routes/vitals.py`) re-projects already-shipped surfaces (Hue / Sonos circuit-breaker state, fusion `_last_fusion_result`, Pi-hole `get_summary`, `psutil` mem/disk/CPU temp, `ws_manager.connection_count`) into per-metric `{value, status: ok|warn|error}` chips with a roll-up status. Frontend `VitalStrip.svelte` polls every 30s, collapsed → just an overall dot, expanded → all chips with mode-aware tinting (orange-warn, red-error). `FloatingNav` shifted up `bottom: 20px → 36px` (mobile `8px → 28px`) to clear the strip.

---

## Priority Bands (April 2026)

Phase 3 (autonomous operation) is finishing — auto-demote on 2026-05-04 closes the predictor lifecycle loop, then the 30-day override-rate window starts ticking. Phase 4 (Game Day) targets July–August. The backlog below is grouped into three bands by **what's worth picking up next** given that sequencing.

### Near-term (next 4–6 weeks, before Phase 4 prep)

Small, high-leverage, low-risk items that consume only shipped infrastructure. Good "fill" work between Phase 3 closure and Phase 4 kickoff. (#4 DND, #15 Vital Signs Strip, and #19 Logbook all shipped 2026-04-29 — see Completed → Near-term polish.)

- **#6 Screensaver Mode** — pure frontend, reads existing WS broadcasts
- **#14 Seasonal Lighting** — slow-burn polish, no dependencies

### Mid-term (after Phase 3 exit, parallel to Phase 4 Game Day)

Real ML work; depends on enough live data to justify the model, or pairs naturally with Game Day's cadence.

- **#7 Mood Drift Detection** — pairs with #16 override-reason classifier
- **#16 Override Reason Classifier (shadow first)** — needs more override data to cluster meaningfully; ship as shadow before any fusion-lane promotion
- **#9 Anomaly-Triggered Pause** — YAMNet ready; needs one gate in `automation_engine`
- **#13 Power Outage Recovery** — startup hook + event log restore; safe because it only fires on cold boot
- **#3 Sleep Analytics** + **#10 Sleep Quality** — pair these for the `/sleep` page

### Slow-burn (genuine R&D, defer until earlier items shake out)

Worth doing eventually but don't have a clear forcing function yet. Each has a "needs more data" or "needs more design" gate.

- **#2 Macro Engine** — overlaps with future Game Day quick-actions; let that shape the macro API first
- **#5 Sonos Volume Curves** — Sonos doesn't model state the way Hue does, so the abstraction is lossy; think harder before building
- **#8 Contextual Music Memory** — needs more bandit data to justify expanding arm key
- **#11 Adaptive Transition Choreography** — small but tempting to over-engineer; wait until #17 transition-curve learning has data
- **#17 Transition Curve Learner** — needs more nudge-during-transition data
- **#18 Focus Envelope** — heaviest UX cost in the list; design before building
- **#21 (slimmed) Pose Landmarks Visualization** — debugging widget, nice-to-have

Phase 4 (Game Day, July–August) and Phase 5 (custom Alexa, Apple Music, full autopilot, bar app) timelines stand.

---

## Large Ideas

### 1. Dashboard "Replay" / Time Machine

**Status:** API ready, UI deferred. The 6 endpoints under `/api/events/` (aggregation, filtering, pagination, mode timeline) ship today via `event_query_service.py`. What remains is the frontend: horizontal timeline with color-coded mode blocks, time-scrubber, expandable per-light detail, weekly/monthly heatmaps.

Scrub through any day to see what the apartment looked like at any point — mode, light states, music playing. All event data already logged — pure frontend visualization on top of the existing API.

**Touches:** New route (`/timeline`), new Svelte components (heatmap, time-scrubber, per-light row).

---

### 2. Contextual Quick Actions (Macro Engine)

Orchestrate multi-step sequences with configurable delays. Example "Cooking": kitchen lights bright → cooking playlist → volume 18 → kitchen-timer TTS pings every 5 min. Macro builder UI in Settings — no code for new macros.

**Touches:** New `MacroEngine` service, new DB table (`macros`), Settings page builder UI

---

### 3. Sleep Analytics Dashboard

Dedicated sleep insights page: bedtime consistency, fade duration, overnight overrides, morning routine timing, "sleep score" trend charts. The 3D moon scene could encode last night's data. All data already in event tables.

**Touches:** New route (`/sleep`), `event_query_service.py`, new Svelte components

---

### 4. "Do Not Disturb" Mode

Toggle that locks current state — no mode changes, no auto-play, no TTS, no routines. Auto-expires after 2 hours. Subtle DND indicator on dashboard. Useful when you have someone over.

**Touches:** `automation_engine.py` (check flag before transitions), dashboard toggle component

---

### 5. Sonos Volume Curves Per Mode

Per-mode volume targets (gaming: 25, working: 12, relax: 18, sleeping: 0). Mode transitions smoothly adjust volume alongside lighting. Pairs with existing mode brightness multipliers.

**Touches:** `music_mapper.py`, new `mode_volume_config` in `app_settings`, Settings UI

---

### 6. Dashboard Screensaver Mode

After 60s idle auto-hide, cycle through ambient info: clock, weather, next routine, now playing art. Smart clock overlay on top of the mode backgrounds.

**Touches:** New `ScreensaverOverlay.svelte` component, `activity.js` store integration

---

## ML Ideas

### 7. Mood Drift Detection

Track the *derivative* of lighting preferences — if manual overrides consistently trend warmer/dimmer over a week, detect a seasonal mood shift and proactively adjust baselines. Operates on multi-day override patterns, not per-event EMA.

**Touches:** `lighting_learner.py`, new drift analysis module

---

### 8. Contextual Music Memory

Extend MusicBandit arms to include (mode, day_of_week, weather) context. "Rainy Friday relax" maps to different playlists than "sunny Saturday relax." Hierarchical priors from parent mode+period arms for cold start.

**Touches:** `music_bandit.py` (expand arm key), `weather_service.py` integration

---

### 9. Anomaly-Triggered Automation Pause

Use YAMNet's doorbell/alarm/glass-break classifications to auto-pause mode transitions for 5 minutes when anomalous sounds are detected. Prevents awkward automation during unusual situations.

**Touches:** `audio_classifier.py` (new callback), `automation_engine.py`

---

### 10. Sleep Quality Inference

Fuse sleeping mode times + camera presence (restless vs. still) + ambient audio (quiet vs. disrupted) + morning override behavior into a nightly sleep quality score. No wearable needed — purely from existing sensors. Trend chart on analytics page.

**Touches:** New `sleep_quality.py`, analytics page components

---

## General Ideas

### 11. Adaptive Transition Choreography

Stagger light transitions room-to-room on mode change. Morning: bedroom → living room. Evening: reverse. Purely a timing layer with `asyncio.sleep()` offsets between `set_light()` calls.

**Touches:** `automation_engine.py` (transition sequencer), new config in `app_settings`

---

### 12. Guest Mini-App — substantially shipped 2026-05-02

What started as a thin "WiFi QR + Welcome page" grew into a full visitor surface with its own bottom-tab nav, four sub-pages, a curated party-scene picker, and a music-vibe nudge. Guests get something to *do*; the host stays in control via tightly-scoped safelists and per-surface cooldowns.

**Shipped (foundation, 2026-05-01):**
- `GuestWifiWidget` on the home dashboard. Opens a fullscreen modal with the big WiFi QR plus a smaller "then scan for tonight's info" QR that points at `/guest` — two-scan flow (join WiFi, then load page). Modal intentionally hides the password text (kiosk lives in the living room); the QR still encodes it for phones to read.
- Backend `GET /api/guest/wifi` returns the standard `WIFI:T:<security>;S:<ssid>;P:<password>;H:false;;` URI for `qrcode.toDataURL()`. Credentials live in `.env` as `GUEST_WIFI_SSID` / `GUEST_WIFI_PASSWORD` / `GUEST_WIFI_SECURITY` (default `WPA`); special chars escaped per spec.
- Mobile `NowPlayingChip` lifted above `FloatingNav` on small screens (≤768px: `bottom: 76px → 104px`; ≤480px: `64px → 92px`) so the chip sits clearly above the nav pill instead of sliding underneath it. Chip's `z-index: 45` was below nav's `z-index: 50`, so the math, not the stacking, was the bug.
- Mobile reconnect: three-layer fix. (1) `connectionLost` derived store in `connection.js` debounces the banner 3s so sub-3s flickers don't paint. (2) `run.py` passes `ws_ping_interval=30, ws_ping_timeout=60` to uvicorn — was the 20s default, which was killing sockets during phone screen-sleep cycles. (3) `ws.js` registers a `visibilitychange` handler that calls `retryNowIfDead()` on tab resume — cancels pending backoff, resets delay, and reconnects immediately so the banner doesn't outlast the time it takes to glance at the screen.

**Shipped (mini-app expansion, 2026-05-02):**
- **Stripped kiosk chrome from `/guest/*`.** The first cut only hid `FloatingNav` + `NowPlayingChip`; everything else (`ModeBackground`, `ModeOverlay`, `NowPlayingIdle`, idle hint, `VitalStrip`) still leaked onto visitors' phones, dominating the screen with a kiosk-style "I D L E" overlay and "Tap anywhere to wake" hint. Root `+layout.svelte` now gates the entire kiosk surface behind `{#if !isGuestRoute}` — only `<slot/>` + `<ErrorToast/>` survive on guest paths.
- **`GuestBottomNav` (`$lib/components/`).** Fixed-bottom 5-tab thumb-zone nav (Home / WiFi / Bar / Plants / Vibe) with Lucide icons, safe-area-aware via `env(safe-area-inset-bottom)`, ≥56px touch targets. Active-state reactivity gotcha worth knowing about: the first cut hid `pathname` inside `isActive(href)` and Svelte's compiler couldn't track it through the function call, so Home stayed lit on every page — fix is to pass pathname as an explicit arg (`isActive(href, pathname)`) so the template expression sees the dependency.
- **Sub-pages.** `/guest/wifi` (re-renders `GuestWifiWidget` so a guest can re-share the QR), `/guest/bar` (`/api/bar/status` summary + deep link to the external bar app, friendly "not set up here yet" empty state on 503), `/guest/plants` (`/api/plants/status` snapshot — total / thirsty count / next watering, same 503 fallback). Each sub-page is its own `+page.svelte` under `routes/guest/`.
- **`/guest/vibe` — the centerpiece.** Three sections.
  - *Right Now*: real Lucide icon mapped per `automation.mode` (Sparkles for idle, PartyPopper for social, Flame for relax, etc.) tinted with the mode color, the big mode label, and a horizontal row of 4 colored circles built from the live `lights` store via `lightStateToCSS` (`$lib/utils/lightColor.js`). No labels — the dots are a status snapshot, not a control. Off lights render as outlined dashed rings.
  - *Set the Mood*: 6 party-curated scenes loaded from `GET /api/guest/scenes`, each rendered as a card with a 4-dot color preview pulled from the actual preset states (the colors *are* the icon — a deliberate visual-first call rather than per-scene Lucide icons). Tap → `POST /api/guest/scene/{name}` → 15s cooldown returns 429 + `Retry-After`. Safelist (`GUEST_SCENE_WHITELIST` in `routes/guest.py`): `party→house_party`, `neon→neon_tokyo`, `miami→miami_vice`, `arcade→arcade`, `aurora→northern_lights`, `sunset→sunset_strip`. Activation tags `set_manual_override(target, source="guest")` (party→social, others→relax) so the next automation tick doesn't immediately revert.
  - *Pick the Music*: 3 vibe tiles loaded from `GET /api/guest/vibes` (Hype / Sing-along / Throwback), each showing the vibe label + the currently-mapped Sonos favorite title underneath. Tap → `POST /api/guest/vibe/{name}` → calls `SonosService.play_favorite` (case-insensitive title match), tags override `social`, independent 15s vibe-cooldown (separate from scene cooldown — lights and music are unrelated controls). Vibe→favorite mapping is `app_settings["guest_vibe_playlists"]` over `GUEST_VIBE_DEFAULTS` (hype→`It's Lit!`, singalong→`2000s Hits Essentials`, throwback→`Replay-all-time`).
- **Auth model unchanged.** Both POST endpoints live behind `require_api_key`, but the existing RFC1918 LAN bypass means visitors on the WiFi never present a header. The trust boundary is "if you're on the apartment LAN, you're in." No per-IP rate limiting — global cooldown is enough.
- **House Notes** at `/guest` updated with the welcome message Anthony writes for guests.

**Still open:**
- `guest.homehub.local` Pi-hole DNS entry — currently reachable only as `http://192.168.1.210:8000/guest`.
- Captive-portal-style auto-redirect — infeasible without router-level DNS control (guest's phone uses router DHCP DNS, not Pi-hole). Documented in CLAUDE.md so future-Anthony doesn't relitigate.
- Settings UI for `guest_vibe_playlists` (currently hand-edit `app_settings`) — small but worth it if the vibe→favorite mapping needs tuning often.
- Optional "Tell the host" free-text channel — not yet built. Would need a small kiosk-side notification component to surface inbound requests; vibe-nudge covers the common case so this stays deferred.

---

### 13. Power Outage Recovery

Detect cold boot (uptime < 5min + no clean shutdown event), restore exact pre-outage state from event log — mode, light colors, music. Outage > 30min falls through to normal time-based.

**Touches:** `main.py` (startup check), `event_query_service.py`

---

### 14. Seasonal Lighting Profiles

Day-of-year sine wave modifier on color temperature and hue ranges. Winter: cooler whites, blue accents. Summer: warmer tones, golden hour emphasis. Imperceptible day-to-day, noticeable season-to-season.

**Touches:** `automation_engine.py` (seasonal modifier function)

---

### 15. Dashboard Vital Signs Strip

Always-visible 20px strip at kiosk bottom: Hue latency, Sonos status, ML fusion confidence, WiFi devices, Pi-hole blocks today, CPU temp. Turns red on anomalies.

**Touches:** New `VitalStrip.svelte`, new `/api/vitals` endpoint

---

## ML Ideas (April 16 additions)

### 16. Override Reason Classifier with Soft Counterfactuals

Train a lightweight sequence classifier on the 90s of sensor state leading up to every manual override (time-of-day, prior 3 modes, weather, last playback, camera presence, ambient audio). Model output: a cluster label for *why* the user overrode — "too bright for evening screen time", "relax-mode picked wrong music for my mood", "winddown too early while guests present".

On the NEXT occurrence of a matching reason-cluster context, do **not** auto-apply — surface a soft counterfactual toast: *"Last Tuesday at 9pm raining, you switched working → relax. Try that now, or stay working?"*

**Distinct from #7 Mood Drift Detection:** Mood Drift tracks the multi-day *derivative* of preferences. This tracks the *reason* for single overrides and drives surgical interventions, not seasonal baselines.

**Touches:** new `override_reason_classifier.py`, `ml_logger.py`, `ModeSuggestionToast.svelte`, `confidence_fusion.py` (new signal lane)

---

### 17. Per-User Transition-Curve Preference Learning

Learn not just WHICH mode but HOW each mode should transition: bri-first-then-color vs. crossfade vs. snap, at what speed, personalized by time and mode. Data source: mid-transition manual light adjustments already captured in `light_adjustments`. If the user consistently nudges brightness up during a 4s crossfade (keeps wanting it brighter sooner), the model learns to lead with brightness next time.

Autonomously updates `MODE_TRANSITION_TIME` and transition *order* per (mode, time-of-day) bucket. Graceful degradation: falls back to hardcoded defaults when N < 20 transitions observed.

**Why novel:** Every existing ML feature personalizes the destination *state* (what color, what mode, what playlist). This personalizes the *trajectory*.

**Touches:** new `transition_curve_learner.py`, `automation_engine.py` (pre-`_apply_state` hook), new `transition_preferences` column

---

## General Ideas (April 16 additions)

### 18. Focus Envelope

A *pomodoro-by-lights* mode. During focus sessions the ambient lights smoothly constrict toward desk-dominant (kitchen fades, L1 dims, L2 desk stays solid); during breaks they diffuse back outward. The brightness envelope *itself IS the pomodoro timer* — no clock, no sound, no overlay.

Auto-triggers when Cursor / VSCode / `claude` is focused for >25 min with no `alt-tab` >18 min. Break envelope: 5 min diffuse + ambient noise shift. User sets session:break ratio (25:5, 50:10).

**Distinct from #11 Adaptive Transition Choreography:** Choreography is a staggered wave on mode *change*. Focus Envelope is continuous low-amplitude modulation *during* a mode with semantic meaning (focus vs break). Distinct from the existing `working` mode, which is static.

**Touches:** new `focus_envelope.py`, Settings toggle, `FocusChip.svelte` surface indicator

---

### 19. Apartment Logbook — Nightly Auto-Journal

A silent nightly (2am) job writes a single-file Markdown journal entry summarizing the day in narrative prose: *"Worked 4h12m (9:14am–2:05pm, paused at 11:30 for kitchen). Gaming 1h48m. Rain rolled in at 2:14pm, which triggered candle effect twice and shifted winddown 12 min early. Overrode the winddown routine once (stayed on watching until 11:52pm)."*

Pure read over existing `event_logger` tables — no new data sources. Writes to `data/journal/YYYY-MM-DD.md`. Surfaced behind a `/journal` route (hidden from main nav). Also primes any future LLM-backed features: the journal file is ready-made grounding context.

**Distinct from #1 Dashboard Replay:** Replay is real-time visual scrubbing. Logbook is compact, searchable, linkable prose. **Distinct from #3 Sleep Analytics:** Sleep is focused on sleep quality. Logbook covers the whole day as narrative.

**Touches:** new `journal_service.py` (scheduled at 2am), new `/journal` frontend route

---

### 20. Zone-Driven Mode Transitions — remaining carve-outs

**Base rule shipped 2026-04-27**, **social-supersede shipped 2026-05-03** (both in Completed section above). The zone+posture → relax actuation rule lives at `backend/services/automation_engine.py::_evaluate_zone_posture_rule` and is the first sensor signal that drives a mode *transition* (not just an overlay). Eligible modes are `{idle, working, social}`; dwell is 120s for idle/working and 180s for social; a fresh (<30min) social override is preserved.

This idea now tracks the remaining open carve-outs:

- **Late-night-working carve-out.** `zone=desk + process=working + after 22:00` should bypass the late-night-rescue path (keep Anthony in working when he's actively at the keyboard past 22:00). The current rule only handles `zone=bed`.
- **Fusion integration.** Today the rule calls `set_manual_override` directly. Future option: publish zone+posture as a new signal lane in `confidence_fusion.py` so it votes alongside process/camera/audio/rule_engine instead of acting unilaterally. Worth considering once shadow data confirms the rule fires correctly — fusion gives finer-grained tuning. (Rule rather than fusion is the right primitive for now because the rule is high-confidence and binary; fusion adds value once the signal is probabilistic.)
- **Morning lounge nudge.** The current time gate blocks mornings globally. If Anthony lies back down for a post-wake rest, we may eventually want a specific "morning lounge" nudge rather than nothing.
- **Social-supersede checkback 2026-05-17.** Query `ml_decisions WHERE decision_source='zone_posture_rule' AND timestamp > date('now','-14 days')` and inspect `factors.effective_mode == 'social'` rows. Confirm at least one fired on a real "guest left" pattern (not a misfire). If misfires appear → bump `SOCIAL_MIN_AGE` to 60min or remove `social` from `ELIGIBLE_MODES`.

**Touches:** `automation_engine.py` (new gate in `_evaluate_zone_posture_rule` for the late-night-working carve), `confidence_fusion.py` (new signal lane if we go that route).

---

### 21. Pose Landmark Visualization (Frontend follow-up)

**Status:** Pose detection itself is shipped — `camera_service.py` runs MediaPipe BlazePose and the derived labels (`zone`, `posture`, `detection_source`) flow over `camera_update` WebSocket events today. What remains is the **kiosk debug widget**: a mini stick-figure rendered in a corner showing what the Latitude sees, useful for verifying camera angle and detection quality without curl'ing annotated snapshots.

Gated behind a config flag for privacy (pose coordinates are more informative than presence). Default off. When enabled, extends `camera_update` with a `pose_landmarks` payload (normalized 0–1 coordinates + visibility) and a new `<PoseWidget.svelte>` consumer draws the skeleton.

**Distinct from annotated snapshots:** Snapshot is a one-shot image, includes full frame. Pose widget is continuous, landmarks-only, no image data.

**Touches:** `camera_service.py` (optional `publish_pose_landmarks` setting), WebSocket payload extension, new `PoseWidget.svelte`, Settings toggle.
