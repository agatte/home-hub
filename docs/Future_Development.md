# Future Development Ideas

> Feature ideas beyond the current roadmap — large and small.
>
> **Last updated:** 2026-04-16

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
