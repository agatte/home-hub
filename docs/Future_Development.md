# Future Development Ideas

> Feature ideas beyond the current roadmap — large and small.
>
> **Last updated:** 2026-05-03

> 📌 **Active backlog now lives at https://github.com/agatte/home-hub/issues.** This doc remains the ideation pool — items here graduate to issues once concrete. Concrete trackable items from #1-#21 below were migrated to issues #14-#25 (Phase 5 milestone) on 2026-05-12; their entries are kept as long-form context but no longer the source of truth for "what's next."

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
- **2026-05-09 — YAMNet `speech_multiple` social-gate ABANDONED.** 14-day re-evaluation across 838,629 production rows confirmed the 5/03 finding: `speech_multiple` MAX 0.088 (never close to 0.80), 0 firings including the 5/06 guest visit. Option A rejected (`speech_single ≥ 0.80` fires ~7,000/day with 3.4% solo-working-mode overlap; RMS doesn't disambiguate 1-vs-2 speakers). Option B rejected (YAMNet is the wrong tool architecturally — scene classifier, not diarizer). Option C taken: `speech_multiple` removed from `MODE_THRESHOLDS` in `audio_classifier.py`; the score still flows into `all_scores` for analytics. Audio_ml lane stays in v3 fusion for `silence→quiet` + `game_audio→watching` gates. Social-mode now manual-override only. Replacement direction (deferred to a separate plan): camera multi-face detection extending the existing MediaPipe pipeline; SpeechBrain embeddings + clustering as a fallback. Memory: `project_audio_classifier_shadow_followup.md`.
- **2026-05-27 — Latitude camera relocated to living room; ZONE_COUCH + desktop owns desk (`02446bc`, `e96698a`).** The ambient-on-Sonos misfire (weather rain stream + relax fireplace auto-playing loudly while Anthony was home) root-caused to the Latitude only seeing desk + bed; couch/kitchen read as "absent" and `ambient_relax` force-flipped relax + auto-played the Sonos. Rather than chase a couch sensor we don't have, the Latitude moved to the living room. Code: `camera_service` now emits a single `ZONE_COUCH` (desk/bed left-right split retired — the X-threshold was bedroom-corner geometry); desktop pc_agent emits explicit `zone="desk"` via PresenceFusion (first-class desk authority); `automation_engine.is_present_in_room()` veto added to `ambient_relax` — strong presence OR a fresh committed couch zone (night couch detection is weak-face-only at conf ~0.3-0.45, so trust the committed zone, not just `is_strongly_present_any`); `transit_lighting.STATIONARY_ZONES` += `"couch"`; couch posture suppressed (no consumer); lux baseline recalibrated from the couch under evening lighting (143 → 74, multiplier back to ~1.0). Bed-zone features (`_evaluate_zone_posture_rule`, `_evaluate_watching_sleep_guard`) DORMANT — kept (not deleted) pending possible light-touch desktop bed detection (the desktop's wide FoV does include the bed in the background; pose-based bed presence is feasible but unbuilt). Living-room sensor sees couch only — no kitchen, no bedroom in frame. See `[[project_camera_position]]`. Section 20 below is blocked by this.

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

Phase 4 (Game Day, July–August) timeline stands. Phase 5: **Custom Alexa Skill shipped 2026-05-05** (invocation `home hub` since 2026-05-16, Lambda + Cloudflare Tunnel `home-hub.gatte-home.com`, see `alexa_skill/`) — Apple Music, full autopilot, bar app remain.

---

## Large Ideas

### 1. Dashboard "Replay" / Time Machine

→ Tracked in [#14](https://github.com/agatte/home-hub/issues/14).

---

### 2. Contextual Quick Actions (Macro Engine)

→ Tracked in [#16](https://github.com/agatte/home-hub/issues/16).

---

### 3. Sleep Analytics Dashboard

→ Tracked in [#25](https://github.com/agatte/home-hub/issues/25).

---

### 4. "Do Not Disturb" Mode — shipped 2026-04-29

`AutomationEngine.is_dnd_active()` gates autonomous mode-setters; user-source overrides (`api:<ip>`) still pass. Persisted to `app_settings["dnd_state"]`, restored on boot, auto-clears in `run_loop` once expiry tick fires. Endpoints `POST/DELETE /api/automation/dnd`; status fields appended to `GET /api/automation/status`. Frontend: subtle `DND • Xh Ym` chip on `ModeIndicator`, full toggle + duration picker on Settings.

**Gated paths:** `report_activity`, `set_manual_override`, `clear_override`, late-night rescue, zone+posture rule, behavioral-predictor toast, music auto-play / weather suggestion, morning routine, sunrise ramp, winddown.

---

### 5. Sonos Volume Curves Per Mode — shipped 2026-05-12

`ModeVolumeService` fades the speaker to a per-mode Sonos volume target on mode transitions. Registered as a mode-change callback in `bootstrap.py` alongside `MusicMapper`. Config persisted to `app_settings["mode_volume_curves"]` as `{mode: {day, evening, night, fade_duration_s}}`; defaults in `mode_volume_policy.py`. Endpoints: `GET /api/automation/mode-volume` (read merged config) + `PUT /api/automation/mode-volume` (update). TTS mid-speak defers the ramp 5s and retries once (TTS duck-and-resume snapshots volume; a concurrent ramp would be clobbered). Silent transport states (`STOPPED`, `NO_MEDIA_PRESENT`) skip the ramp — no point fading silence.

→ Tracked in [#17](https://github.com/agatte/home-hub/issues/17).

---

### 6. Dashboard Screensaver Mode

→ Tracked in [#15](https://github.com/agatte/home-hub/issues/15).

---

## ML Ideas

### 7. Mood Drift Detection

→ Tracked in [#22](https://github.com/agatte/home-hub/issues/22).

---

### 8. Contextual Music Memory — shipped 2026-05-12 (Phase B, weather dimension)

MusicBandit arm key extended to `(mode, time_period, weather_class, title)` — "thunderstorm relax evening" maps to different priors than "clear relax evening." Weather classes: thunderstorm / rain / snow / clouds / golden_hour / clear / any (sentinel). Legacy 3-tuple arms migrate to 4-tuple on load (idempotent). New weather-specific arms warm-start from the corresponding `any` arm's accumulated priors so they don't begin at a flat Beta(1,1). `sonos_playback_events` gains a `weather_class` column (Phase B) so the nightly retrain can rebuild weather-aware arms from 90 days of history.

Note: `day_of_week` was not included in Phase B — the arm key uses `time_period` (morning/day/evening/night) rather than a full day-of-week dimension. If day-of-week proves necessary, that would be a Phase C expansion.

**Touches:** `music_bandit.py`, `music_mapper.py`, `weather_service.py` integration (live via `bootstrap.py` threading `weather_service` into `MusicMapper`).

---

### 9. Anomaly-Triggered Automation Pause

→ Tracked in [#20](https://github.com/agatte/home-hub/issues/20).

---

### 10. Sleep Quality Inference

Fuse sleeping mode times + camera presence (restless vs. still) + ambient audio (quiet vs. disrupted) + morning override behavior into a nightly sleep quality score. No wearable needed — purely from existing sensors. Trend chart on analytics page.

**Touches:** New `sleep_quality.py`, analytics page components

---

## General Ideas

### 11. Adaptive Transition Choreography

→ Tracked in [#23](https://github.com/agatte/home-hub/issues/23).

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

→ Tracked in [#19](https://github.com/agatte/home-hub/issues/19).

---

### 14. Seasonal Lighting Profiles

→ Tracked in [#18](https://github.com/agatte/home-hub/issues/18).

---

### 15. Dashboard Vital Signs Strip — shipped 2026-04-29

Always-visible 22px strip at the kiosk bottom. `GET /api/vitals` aggregator (`backend/api/routes/vitals.py`) re-projects already-shipped surfaces — Hue / Sonos circuit-breaker state, fusion `_last_fusion_result`, Pi-hole `get_summary`, `psutil` mem/disk/CPU temp, `ws_manager.connection_count` — into per-metric `{value, status: ok|warn|error}` chips with a roll-up status. Frontend `VitalStrip.svelte` polls every 30s; collapsed → just an overall dot, expanded → all chips with mode-aware tinting (orange-warn, red-error). `FloatingNav` shifted up to clear the strip.

---

## ML Ideas (April 16 additions)

### 16. Override Reason Classifier with Soft Counterfactuals

→ Tracked in [#21](https://github.com/agatte/home-hub/issues/21).

---

### 17. Per-User Transition-Curve Preference Learning

→ Tracked in [#24](https://github.com/agatte/home-hub/issues/24).

---

## General Ideas (April 16 additions)

### 18. Focus Envelope

A *pomodoro-by-lights* mode. During focus sessions the ambient lights smoothly constrict toward desk-dominant (kitchen fades, L1 dims, L2 desk stays solid); during breaks they diffuse back outward. The brightness envelope *itself IS the pomodoro timer* — no clock, no sound, no overlay.

Auto-triggers when Cursor / VSCode / `claude` is focused for >25 min with no `alt-tab` >18 min. Break envelope: 5 min diffuse + ambient noise shift. User sets session:break ratio (25:5, 50:10).

**Distinct from #11 Adaptive Transition Choreography:** Choreography is a staggered wave on mode *change*. Focus Envelope is continuous low-amplitude modulation *during* a mode with semantic meaning (focus vs break). Distinct from the existing `working` mode, which is static.

**Touches:** new `focus_envelope.py`, Settings toggle, `FocusChip.svelte` surface indicator

---

### 19. Apartment Logbook — shipped 2026-04-29

`backend/services/journal_service.py` reads activity / light / sonos / scene events for the previous local calendar day and writes Markdown to `data/journal/YYYY-MM-DD.md`. ScheduledTask `journal_nightly` at 02:00 daily. Endpoints `GET /api/journal/entries`, `GET /api/journal/{date}`, `POST /api/journal/generate/{date}`. Frontend route `/journal` (date rail + markdown render); intentionally excluded from `FloatingNav`. Pure read; no actuation. Also primes any future LLM-backed features — the journal file is ready-made grounding context.

**Distinct from #1 Dashboard Replay:** Replay is real-time visual scrubbing. Logbook is compact, searchable, linkable prose. **Distinct from #3 Sleep Analytics:** Sleep is focused on sleep quality. Logbook covers the whole day as narrative.

---

### 20. Zone-Driven Mode Transitions — remaining carve-outs (BLOCKED 2026-05-27)

**Status: BLOCKED since 2026-05-27.** The base rule (shipped 2026-04-27) and the social-supersede extension (shipped 2026-05-03) are both **dormant** — the Latitude relocated to the living room, no camera now produces `zone="bed"`, and `_evaluate_zone_posture_rule` no-ops every tick. See the 2026-05-27 completed entry above for the relocation context.

The carve-outs below are kept on the shelf pending a future bed-zone source (the most feasible path is light-touch pose-based bed detection from the desktop pc_agent's wide FoV — confirmed feasible via snapshot, unbuilt). Original design intent preserved for revival:

- **Late-night-working carve-out.** `zone=desk + process=working + after 22:00` should bypass the late-night-rescue path (keep Anthony in working when he's actively at the keyboard past 22:00). Post-move, "desk" authority is the desktop pc_agent, so the carve-out would now consult `is_at_desk_fresh()` against that source rather than the Latitude.
- **Fusion integration.** Today the rule calls `set_manual_override` directly. Future option: publish zone+posture as a new signal lane in `confidence_fusion.py` so it votes alongside process/camera/audio/rule_engine instead of acting unilaterally. Worth considering once shadow data confirms the rule fires correctly — fusion gives finer-grained tuning. (Rule rather than fusion is the right primitive for now because the rule is high-confidence and binary; fusion adds value once the signal is probabilistic.)
- **Morning lounge nudge.** The current time gate blocks mornings globally. If Anthony lies back down for a post-wake rest, we may eventually want a specific "morning lounge" nudge rather than nothing.
- ~~**Social-supersede checkback 2026-05-17.**~~ Obsoleted — the rule is dormant; no fires to check.

**Touches:** `automation_engine.py` (would need bed-zone reactivation first, then the late-night-working carve), `confidence_fusion.py` (new signal lane if we go that route).

---

### 21. Pose Landmark Visualization (Frontend follow-up)

**Status:** Pose detection itself is shipped — `camera_service.py` runs MediaPipe BlazePose and the derived labels (`zone`, `posture`, `detection_source`) flow over `camera_update` WebSocket events today. What remains is the **kiosk debug widget**: a mini stick-figure rendered in a corner showing what the Latitude sees, useful for verifying camera angle and detection quality without curl'ing annotated snapshots.

Gated behind a config flag for privacy (pose coordinates are more informative than presence). Default off. When enabled, extends `camera_update` with a `pose_landmarks` payload (normalized 0–1 coordinates + visibility) and a new `<PoseWidget.svelte>` consumer draws the skeleton.

**Distinct from annotated snapshots:** Snapshot is a one-shot image, includes full frame. Pose widget is continuous, landmarks-only, no image data.

**Touches:** `camera_service.py` (optional `publish_pose_landmarks` setting), WebSocket payload extension, new `PoseWidget.svelte`, Settings toggle.
