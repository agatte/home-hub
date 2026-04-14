# Future Development Ideas

> Brainstormed feature ideas beyond the current roadmap. Mix of large architectural changes and smaller quality-of-life improvements.
>
> **Last updated:** 2026-04-13

---

## Large Ideas

### 1. Weather-Reactive Lighting

Layer weather conditions on top of the current mode-based lighting. The weather service already polls OpenWeatherMap every 10 minutes — use that data to subtly influence light states.

- **Thunderstorm:** Shift to deep blue/purple with occasional sparkle effects simulating lightning
- **Sunny morning:** Push CT warmer and brighter
- **Rainy evening:** Soft amber candle tones
- **Snow:** Cool white with gentle brightness pulses

Weather influence layers *on top of* the active mode rather than replacing it. Background scenes could react too — rain particles on the parallax city, darker skies on the pixel scene, storm clouds on the aurora.

**Touches:** `automation_engine.py`, `weather_service.py`, background scene components

---

### 2. Dashboard "Replay" / Time Machine

A visual timeline page where you can scrub through your day and see exactly what the apartment looked like at any point — what mode was active, what lights were set to, what was playing.

- Horizontal timeline with color-coded mode blocks
- Expandable to show individual light states and track changes per block
- Weekly/monthly heatmaps showing when you game, work, relax
- Foundation for the learning engine — visually *see* patterns before the system starts predicting them

The event data (activity_events, light_adjustments, sonos_playback_events) is already being logged. This is a frontend visualization layer on top of existing data.

**Touches:** New route (`/timeline`), `event_query_service.py`, new Svelte components

---

### 3. Ambient Sound Layer

Add a software-based ambient sound layer that plays independently of Sonos — rain on a window, coffee shop murmur, fireplace crackle, lo-fi static, forest sounds.

- Local audio files served from the backend, played through the Latitude's speakers
- Creates background texture underneath whatever Sonos is playing
- Mode-mapped: rain for working, fireplace for relax, crowd noise for social
- Weather-reactive: real rain outside triggers rain sounds inside
- Volume independent of Sonos, controllable from dashboard

**Touches:** New `AmbientSoundService`, new API routes, new dashboard widget, audio file management

---

### 4. Contextual Quick Actions (Macro Engine)

Replace one-dimensional quick actions with a macro engine where a single action orchestrates a *sequence* of steps with configurable delays.

Example "Movie Night" macro:
1. Dim lights over 5 seconds
2. Activate bias lighting scene
3. Switch Sonos to movie soundtrack playlist
4. Set volume to 15
5. Enable screen sync
6. TTS: "Movie night, enjoy"

- Macro builder UI in Settings page — no code needed for new macros
- Each step has a configurable delay, action type, and parameters
- Atomic execution with rollback on failure
- Turns Home Hub from a control panel into a choreography engine

**Touches:** New `MacroEngine` service, new DB table (`macros`), Settings page builder UI, updated quick action components

---

### 5. Sleep Analytics Dashboard

Extend sleeping mode detection into a dedicated sleep insights page.

- When you went to bed, how long the fade took
- Whether you manually overrode anything during the night
- When the morning routine triggered
- "Sleep score" based on consistency (bedtime regularity, override frequency)
- Trend charts over weeks/months
- The 3D moon scene could subtly encode last night's data (brighter stars = better consistency)

The sleeping mode transition and morning routine events are already logged. This is aggregation + visualization.

**Touches:** New route (`/sleep`), new query methods in `event_query_service.py`, new Svelte components

---

## Smaller Ideas

### 6. Presence Detection via Network Ping

Ping your phone's IP on the LAN every 30 seconds. Phone present = home, phone gone for 5+ minutes = away. Replaces the Win32 idle timer for away detection, works even when the PC is off. No new hardware needed.

**Touches:** New detector in `pc_agent/`, or a lightweight service in the backend

---

### 7. "Do Not Disturb" Mode

A toggle that locks the current state — no mode changes, no auto-play, no TTS, no routine triggers. Useful when you have someone over and don't want the apartment randomly shifting. Auto-expires after 2 hours or until manually cleared. Subtle DND indicator on the dashboard.

**Touches:** `automation_engine.py` (check flag before transitions), dashboard toggle component

---

### 8. Light Color History / Favorites

Track which manual light colors you set most often from the dashboard. Surface a "recent colors" and "favorite colors" palette in the light controls. The light_adjustments event log already captures hue/sat/bri — just aggregate and surface the top 10.

**Touches:** New query in `event_query_service.py`, updated `LightGrid` component

---

### 9. Morning Routine Outfit Suggestion

The morning routine already fetches weather and generates TTS. Add a simple outfit layer:
- < 50°F → mention a jacket
- Rain forecasted → mention an umbrella
- \> 85°F → mention it's shorts weather

Three lines of logic on top of existing weather data. Makes the morning TTS feel genuinely useful.

**Touches:** `morning_routine.py` (TTS script generation)

---

### 10. Mode Streak / Stats Widget

A small home page widget showing fun stats:
- "You've been in working mode for 3h 12m"
- "Gaming streak: 4 days in a row"
- "Most used mode this week: working (62%)"

Gamifies productivity. Event data is already there — pure frontend work.

**Touches:** New widget component, queries against `activity_events`

---

### 11. Sonos Volume Curves Per Mode

Configurable volume targets per mode (gaming: 25, working: 12, relax: 18, sleeping: 0). Mode transitions smoothly adjust volume alongside lighting. Evening working could auto-lower to 8. Pairs naturally with the existing mode brightness multipliers.

**Touches:** `music_mapper.py`, new `mode_volume_config` in `app_settings`, Settings UI

---

### 12. Scene Scheduling

Let users schedule specific scenes to activate at specific times, independent of mode. "Every Friday at 6pm, activate Golden Hour" or "Every morning at 7am, activate Energize." Extends the existing scheduler with user-created entries.

**Touches:** `scheduler.py`, new DB table (`scheduled_scenes`), Settings UI

---

### 13. Dashboard Screensaver Mode

After the 60-second idle auto-hide, instead of just showing the background, cycle through useful ambient info: current time (big, minimal), weather, next routine, now playing art. A smart clock / ambient display overlay. The background animations are already beautiful — layer minimal info on top during idle.

**Touches:** New `ScreensaverOverlay.svelte` component, `activity.js` store integration

---

### 14. Pi-hole "Who's Busy" Widget

Show which devices on your network are most active right now by DNS query volume. A simple bar chart of device hostnames. Useful for spotting devices phoning home excessively or forgotten devices being chatty.

**Touches:** `pihole_service.py` (new query), updated `PiholeCard` component
