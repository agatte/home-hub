# Future Development Ideas

> Feature ideas beyond the current roadmap — large and small.
>
> **Last updated:** 2026-04-28

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

### Architecture
- **2026-04-27 — `presence_service` and home/away retired (`b8fdbfe`).** Phone-WiFi presence (iOS Shortcut + ARP probing) was too unreliable on its own. Fusion drops the phone-WiFi lane; `/api/automation/presence/*` routes removed; `mode='away'` no longer in `VALID_MODES`. Camera presence (face/pose) and Hue's native geofencing carry the home/away signal now.
- **Camera-at-desk veto pattern.** Four push-toward-relax pathways (winddown, late-night rescue, behavioral predictor consumer, fusion `can_override`) gate on `is_at_desk_fresh()` so the system doesn't force relax while Anthony's actively at the desk.
- **Override caller telemetry source kwarg.** `set_manual_override` / `clear_override` accept + log a `source` kwarg on all 7 callers — diagnose mysterious override flips via `journalctl`.
- **2026-04-28 — mcp_server presence cleanup (`dcb3e30`).** Dead-code deletion of the standalone `get_presence_status` MCP tool and the 404'ing presence call in `get_live_state`'s aggregator.

### Documentation
- **2026-04-28 — `docs/PROJECT_SPEC.md` updated for home/away retirement + predictor calibration (`683f483`).**
- **2026-04-28 — `docs/ML_SPEC.md` updated to v3 4-lane fusion shape (`23a9f03`).** Removed 5/6-lane descriptions; added v3 retirement block; updated Phase 3 dependency diagram.

---

## Large Ideas

### 1. Dashboard "Replay" / Time Machine

Scrub through any day to see what the apartment looked like at any point — mode, light states, music playing. Horizontal timeline with color-coded mode blocks, expandable per-light detail, weekly/monthly heatmaps. All event data already logged — pure frontend visualization.

**Touches:** New route (`/timeline`), `event_query_service.py`, new Svelte components

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

### 12. Guest Wi-Fi Landing Page

`guest.homehub.local` landing page with Wi-Fi password, Party Mode QR code, now playing, "request a song" form, house rules. Pi-hole DNS already handles local domains.

**Touches:** New frontend route (`/guest`), Pi-hole DNS entry, new song queue API

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

### 20. Zone-Driven Mode Transitions

**Status: zone+posture → relax rule promoted to live 2026-04-27 (commit `6122cd2`).** Fires `set_manual_override("relax", source="zone_posture_rule")` when the camera sustains `zone=bed + posture=reclined` ≥120s (lowered from 300s on promotion), gated on eligible current_mode + no active override + evening/weekend-afternoon + 4h refractory. Projector-from-bed carves itself out because the sit-up-against-headboard pose keeps `posture=upright`. `ZONE_POSTURE_RULE_APPLY=true` by default; escape hatch via `.env` for shadow-only. Implementation lives in `backend/services/automation_engine.py::_evaluate_zone_posture_rule`.

**Remaining under this banner:**
- Second rule set candidate: `zone=desk + process=working + late-night` bypasses the 22:00 late-night-rescue (keep Anthony in working when he's actively at the keyboard past 22:00).
- Fusion integration — current rule calls `set_manual_override` directly. Future option: publish as a new signal lane in `confidence_fusion.py` so zone+posture can vote alongside process/camera/audio/behavioral/rule_engine instead of acting unilaterally. Worth considering once shadow data shows the rule is reliable — fusion gives finer-grained tuning.
- Morning-specific carve-outs: the current time gate blocks mornings globally. If Anthony lies back down for a post-wake rest, we may eventually want a specific "morning lounge" nudge rather than nothing.

**Touches (for the remaining items):** `automation_engine.py` (new gate in `_evaluate_zone_posture_rule` for the late-night-working carve), `confidence_fusion.py` (new signal lane if we go that route).

---

### 21. Pose Landmarks Over WebSocket (Kiosk Debug Widget)

Currently the camera service computes per-frame pose landmarks but only derived labels cross the wire (presence/absence, detection source, zone). A kiosk dashboard widget could visualize the pose landmarks live — a mini stick-figure rendered in a corner of the screen showing what the Latitude sees — useful for debugging camera angle and verifying detection quality without curl'ing snapshots.

Gated behind a config flag for privacy (pose coordinates are more informative than presence). Default off. When enabled, extends `camera_update` WebSocket event with a `pose_landmarks` payload (normalized 0–1 coordinates + visibility) and a new `<PoseWidget.svelte>` consumer draws the skeleton.

**Distinct from annotated snapshots:** Snapshot is a one-shot image, includes full frame. Pose widget is continuous, landmarks-only, no image data.

**Touches:** `camera_service.py` (optional `publish_pose_landmarks` setting), WebSocket payload extension, new `PoseWidget.svelte`, Settings toggle.
