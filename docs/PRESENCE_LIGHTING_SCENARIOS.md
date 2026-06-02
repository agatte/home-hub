# Presence & Lighting Scenarios — Strawman

> **Status:** DRAFT for a design sit-down (created 2026-06-01). Not a spec, not committed behavior. Its job is to put the whole presence→lighting picture on one page, name the decisions only Anthony can make, and propose a target shape — so we stop bolting local patches onto a layer that grew organically.
>
> **Why now:** the 2026-05-31 warm↔gaming strobe (transit + desk_exit fighting the gaming palette for 5.5h) was *exhibit A*. The fix shipped (`392d187`), but it was — by Anthony's own framing — the 7th local patch on a presence layer where ~6 services each independently interpret the same flickery raw signals, several of them dormant since the Latitude moved to the living room. This doc is the "design first" half of the agreed "ship fix now, then design."

---

## Project Tracker — everything in flight

> Living checklist for the whole presence/lighting initiative + adjacent threads. Update as we decide/ship. `[x]` done · `[~]` in progress / decided-not-built · `[ ]` open.

**A. Shipped this session (done)**
- [x] Transit/desk-exit warm-strobe fix — release hysteresis + re-fire cooldown (`392d187`, deployed, live-verified: 1 warm fire/16min)
- [x] Gaming kitchen → real teal hue 39500 (`1961621`, deployed, live-verified)

**B. Ops / connectivity (Google Wifi migration fallout)**
- [~] Latitude migrated to `192.168.86.210`, build `1f20ba7` — healthy (concurrent session owns the migration)
- [ ] **Restore home-hub MCP:** set `HOME_HUB_URL=http://192.168.86.210:8000` + restart Claude Code (subprocess froze on old IP)
- [x] Desktop pc-agent supervisor reconciled — running on `--server http://192.168.86.210:8000` (verified 2026-06-01)
- [ ] Kiosk, Sonos `LOCAL_IP`, hardcoded `SONOS_IP`/`HUE_BRIDGE_IP` reconciled to `86.x` (verify)
- [ ] iPhone Wi-Fi per-device static/DNS re-set for the new subnet (the documented rejoin caveat, now on `86.x`)

**C. Presence/Lighting design — decisions (this doc, Part 7)**
- [x] **D1 — desk-exit lux-adaptive path lighting** — DECIDED: fire on real exit, scale kitchen+L1 brightness by Latitude (room-correct) lux, measure-then-hold, **baseline-relative per room** (each path measured against its own room's baseline — see D4). Sub-q closed 2026-06-01.
- [~] **D2 — phone presence → away/home (WANTED, signal reframed)** — Anthony wants away + welcome-home (see D6). **Signal: NOT the Google Wifi API** (unofficial, largely removed on app-managed GWifi; LAN-polling an iPhone is what shelved the ARP attempt — sleep+MAC-randomization). Use the **iPhone geofence → iOS Shortcut webhook** to the hub (push, reliable). Phone-keyed (iPhone confirmed visible in Google Home, but app≠API). Reuse `signal_presence()` + `_check_external_off()` + Hue Home/Away. Build = formalize an explicit away/home STATE + behaviors.
- [~] **D3 — bed signals.** Anthony's biggest miss = the **late-night bed-watching DIM** (old `_apply_zone_overlay` bed branch). Auto-sleep (`watching_sleep_guard`) = nice-to-have, not a priority. **Revive bed-dim with NO camera-zone / NO hardware:** trigger on **projector ON (bedroom watching) + not-at-desk + evening/night** as the "in bed watching" proxy (deeper dim at late_night). **Depends on the projector Kasa integration landing** (`worktree-projector-kasa`, deploy pending — it provides the watching-in-bedroom signal). True reclined-vs-upright posture stays unavailable but isn't needed for "watching in bed → dim."
- [x] **D4 — per-room lux / two baselines (audit H2) — DESIGN-LOCKED 2026-06-01** — Anthony's bedroom reads dim in *daytime* (his room is darker than the blinds-open living room). Root cause: only the Latitude/living-room camera has a baseline (~74); the desktop webcam reports presence but NO lux, and `LUX_MODES={relax}` means gaming/working/watching get zero lux lift. Fix = **two baselines, one per camera/room** (`living_room←latitude`, `bedroom←desktop`), mode tagged with its room, re-expand `LUX_MODES`. **Couples with D1** (each path uses its own room's baseline → "baseline-relative"). **Exposure spike PASSED 2026-06-01 (P1 viable, no buy):** webcam honors manual exposure via DSHOW (sweep -4→-10 gave mean 149→17). Path = pin exposure for lux sampling. Build plan in **Part 7.5**. Key finding: the synced-lamp half is already scaffolded — `screen_sync._scale_for_ambient()` already scales L2/L5 caps/floors by a `lux_multiplier`, today gated to gaming-*day* only and fed the (bedroom-blind) Latitude lux. D4 swaps in the bedroom lux source + extends the gate to the dark periods, so both lamp groups (L1+kitchen via the engine multiplier, L2/L5 via sync caps) ride ONE bedroom darkness factor. Lux sampling = periodic flip-sample-flip (auto-exposure for faces; brief pinned exposure for one lux sample, presence POST suppressed during the flip).
- [x] **D5 — couch vs desk authority (decided)** — **single-occupant model** (Anthony lives alone; guests are almost always with him in the same room). Rare both-fresh conflict resolved **freshness-first, activity breaks the tie ONLY when both presence signals are genuinely fresh**: a *background* game must NOT pin "desk" after the desk face goes stale + couch commits → couch wins. Common real "conflict" = phantom desk face-FP while on couch → no foreground game → couch wins (feature). Guest-sleepover (guest on couch, him in bedroom) = out of scope for auto-tracking → manual scene / future guest mode.
- [x] **D6 — away/home behaviors (decided via D2)** — LEAVE: lights off + suppress autonomous setters (already what `_check_external_off` does) → **no brightness-churn → no spam** (NOT a mute); emit ONE "away" notification; genuine events still notify. **Notifications stay fully ON when home — Anthony wants the visibility.** ARRIVE: welcome-home sequence (lights ± TTS/music). FUTURE: NL "coming home with friends → set the mood".
- [ ] Fill in the state→lighting matrix (Part 6)
- [ ] Sign off strawman → commit the doc

**D. Implementation (after design sign-off)**
- [x] **D1 — lux-adaptive desk-exit/transit/corridor path brightness** — SHIPPED + DEPLOYED 2026-06-01 (`9163c39`, curator + pr-review + deploy-verifier GO). `path_light_brightness()` helper + measure-then-hold; camera-down → pre-D1 fixed fallback. Live-verified: first post-deploy activation scaled to bri=55 (room at 125 lux vs 74 baseline → lands on `lo`). **Perceptual follow-up:** watch a genuinely dark evening desk-exit to confirm the dark-end (`hi`) caps feel right.
- [ ] **D4 — bedroom lux channel** (full plan in Part 7.5) — next build: webcam flip-sample-flip + settings-flag self-calibrate + per-room `LuxChannel` + re-expand `LUX_MODES` + screen-sync gate extension.
- [ ] `PresenceResolver` — shadow build (log-only), validate vs reality
- [ ] Migrate transit + desk_exit onto resolver transitions (delete local dwell/sustain/cooldown)
- [ ] Migrate relax setters (`ambient_relax`, `late_night_rescue`) onto `on_afk`/`on_away`
- [ ] Light up new states (Google Wifi → `away`; bed source → revive `watching_sleep_guard` + zone+posture + overlay bed branch)
- [ ] Retire dead code once each dormant feature's fate is decided

**E. Gaming-palette eval (open, low priority — needs live gaming)**
- [ ] L5 brightness on blue/cool game frames — reads present now?
- [ ] Stage 3: raise late_night L5 cap above 50 if late-night still reads dim
- [ ] (optional, your hands) phone snap of teal kitchen @ 39500 → add to curator `INDEX.md`

**F. Notification hygiene (separate thread — "another time")**
- [ ] Most of the leave-the-house spam is fixed by D2 away-detection (removes the *cause* — autonomous churn while it thinks he's home).
- [ ] Independent of presence: **brightness-change notification throttle** — if a light write changed ONLY `bri` and `|Δbri| < N`, suppress the notification (`NotifierService`). Builds on the known bri-write-spam causes in `project_notifier_spam_2026_05_17` (lux dead-band / transit desk-flap / scene drift).
- [ ] Keep notifications ON when home — only trim *noise*, never blanket-mute.

---

## Part 1 — The problem in one picture

Today there is **no single answer to "where is Anthony and what is he doing."** Instead, every consumer re-derives it from raw signals, with its own ad-hoc debounce (or none):

```
   RAW SIGNALS                       CONSUMERS (each interprets independently)
   ───────────                       ─────────────────────────────────────────
   Latitude camera ─┐                ┌─ TransitLightingService  (desk-loss → path light)
   desktop face     ├─ PresenceFusion├─ DeskExitKitchenService  (desk-loss → warm kitchen)
   process/idle     │  (last-write-  ├─ ambient_relax            (idle → relax)
   audio (YAMNet)   │   wins, no      ├─ late_night_rescue        (23:00 idle → relax)
   Sonos state      │   debounce)     ├─ watching_sleep_guard     (DORMANT)
   [Google Wifi?] ──┘                 ├─ zone+posture rule        (DORMANT)
                                       ├─ _apply_zone_overlay      (watching desk-lift; bed branch dormant)
   engine helpers:                     ├─ ScreenSyncService        (owns L2/L5 in gaming/watching)
     is_at_desk_fresh() ───────────────┤  ← consumed raw by several of the above
     is_recent_process_working() ──────┤
     is_present_in_room() ─────────────┤
     signal_presence() ────────────────┘
```

**Consequences we've actually hit:**
- **Fights:** transit/desk_exit vs the mode-apply loop → the warm-strobe (2026-05-31); the 2026-05-12 watching incident (107 transit fires/30min on face-flutter). Each was patched locally (zone gates, posture gates, dwell tuning, sustain, cooldown).
- **Drift:** `watching_sleep_guard`, the `zone+posture` rule, and the `_apply_zone_overlay` bed branch all went **dormant** when the Latitude moved living-room (no `zone=bed` source) — but they still live in the engine.
- **Mismatched debounce:** `is_at_desk_fresh()` is last-write-wins with **no** hysteresis; transit has a 10s dwell + 2s release sustain; desk_exit now has 3s sustain + 45s cooldown; the corridor has its own 1s streak. Same question ("is he at the desk?"), four different smoothing rules.
- **Vetoes as spackle:** `is_recent_process_working()` exists *only* because the camera signal is brittle — and it's scoped to `mode=working` only, so it's useless during gaming (the strobe's root gap).

---

## Part 2 — Signal inventory (what we actually have)

| Signal | Source / path | Tells us | Freshness | Reliability / quirks |
|---|---|---|---|---|
| **Latitude camera** | `CameraService` poll 2s → in-proc | couch presence (`ZONE_COUCH`), posture, lux, detection | 15-frame absent (~30s); zone 15s commit hysteresis | Living-room since 2026-05-27. Weak-face-only at night (conf ~0.3–0.45). Sees couch only — **no desk, no bed**. baseline_lux ~74. |
| **Desktop face** | `emotion_capture` → `POST /api/camera/observation` → `PresenceFusion` | at-desk (`face_present`, conf, zone=desk, posture) | POSTed ~2s | **Last-write-wins, NO debounce** — a single missed FaceLandmarker frame flips `face_present` false. Root of the desk-flicker. |
| **Process / activity** | `pc_agent/activity_detector` → `POST /api/automation/activity` | mode + `source=process` + factors; Win32 idle | per-report; `SOURCE_STALE_SECONDS=300` | Game/IDE/media foreground detection. Win32 idle >10min → `idle` (so `mode=gaming` *implies* input within ~10min). |
| **PresenceFusion** | combines Latitude + desktop | `is_at_desk_fresh(300s)`, `is_strongly_present_any(8s)`, `latest_zone(300s)`, `_latitude_says_bed` veto | 300s default | The closest thing to a fusion layer today — but it's a getter bag, not a smoothed state machine; consumers still poll raw. |
| **Audio (YAMNet)** | `ambient_monitor` | `audio_class` | per-report | `speech_multiple→social` gate **abandoned** (structurally unreachable). Latitude-mic path **parked**. |
| **Sonos** | `SonosService` | is music playing (used as a "someone's here / active" hint by relax setters) | 2s | — |
| **Google Wifi** 🆕 | router (post-2026-06-01 migration) | connected devices → phone home/away | TBD | **Candidate new lane.** The reliable LAN-presence the `away_mode_shelved` work wanted but couldn't get from Hue/ARP/Pi-hole. See Part 7. |

---

## Part 3 — Canonical states (the vocabulary we're missing)

Propose the system commit to **one** resolved estimate = **Location × Occupancy × Activity**, with a confidence and a `committed_at`.

**Location:** `desk` · `couch` · `kitchen` · `bed` · `in_transit` · `away` · `unknown`
**Occupancy:** `present` · `afk` (here-ish but not engaged — e.g. game running, no face) · `absent`
**Activity** (≈ today's mode, authoritative from process/override): `gaming` · `working` · `watching` · `cooking` · `relax` · `social` · `sleeping` · `idle`

The unit that's missing today is **`afk`** — "the game is running but no face at the desk." Right now that collapses to "absent," which is what fired the warm strobe. Naming it lets every consumer make the right call explicitly (see Part 6).

---

## Part 4 — Who acts on presence today (the consumers to migrate)

| Consumer | Trigger (raw signal it reads) | Action | Status |
|---|---|---|---|
| `TransitLightingService` | sustained 10s camera desk-loss | L1 (+kitchen) path light, 10min fade | live; just patched (cooldown) |
| `DeskExitKitchenService` | sustained 10s desk-loss, evening/night | warm kitchen, hold-until-return; late_night corridor | live; just patched (sustain+cooldown) |
| `ambient_relax` | `idle` ≥180s + `not is_present_in_room()` + no Sonos | push `relax` | live |
| `late_night_rescue` | 23:00+ `idle/working` + no override/Sonos + `not is_at_desk_fresh()` + `not is_recent_process_working()` | push `relax` | live |
| `watching_sleep_guard` | late_night watching + `zone=bed+reclined` 90min | push `sleeping` | **DORMANT** (no bed source) |
| `_evaluate_zone_posture_rule` | `zone=bed+reclined` | mode/overlay | **DORMANT** (env-gated off) |
| `_apply_zone_overlay` | watching `zone=desk` (lift L2); `bed+reclined` (dim L1/L2) | per-light overlay | desk-lift live; bed branch dormant |
| `ScreenSyncService` | mode ∈ {gaming, watching} | drives L2/L5 to screen color | live |
| `ConfidenceFusion` | process/camera/audio_ml/rule_engine | resolves the active **mode** | live |
| external-off / `signal_presence()` | Hue "leaving home" all-off; camera absent→present | suppress/resume autonomy | live |

Note the overlap: transit *and* desk_exit *and* ambient_relax *and* late_night_rescue all fundamentally key off the same "is he at/near the desk, right now, sustained?" question — answered four different ways.

---

## Part 5 — Proposed target shape: one authoritative resolver

Introduce a single **`PresenceResolver`** (evolve `PresenceFusion` into it) that owns *all* smoothing and exposes a stable estimate + transition events.

```
  all raw signals ─► PresenceResolver ─► PresenceState{ location, occupancy, activity,
                       (hysteresis +        confidence, committed_at }
                        per-signal          + transition events:
                        trust weights        on_enter(location), on_leave_sustained(location),
                        in ONE place)        on_return(location), on_away, on_afk
                                                    │
                          consumers SUBSCRIBE to transitions, they don't poll raw signals
                          ────────────────────────────────────────────────────────────
                          transit  ◄ on_leave_sustained(desk)/on_return(desk)
                          desk_exit ◄ same
                          relax/rescue ◄ on_afk / on_away / on_idle-dwell
                          overlays  ◄ location + posture
```

**Design principles:**
1. **One place for hysteresis.** The 10s dwell, 3s sustain, 45s cooldown, face-flicker debounce — all collapse into the resolver's smoothing. Consumers get clean, debounced transitions. (Today's strobe fix becomes a *property of the resolver*, not a patch in two services.)
2. **Commit + confidence semantics**, like the camera's zone commit: a location is "committed" only after it survives N frames; brief flicker never flips it. `afk` is a first-class committed state.
3. **Consumers react to transitions, not levels.** `on_leave_sustained(desk)` fires once; `on_return(desk)` fires once. No more polling `is_at_desk_fresh()` raw and racing the mode-apply loop.
4. **Signals are pluggable lanes with trust weights** (mirrors `ConfidenceFusion`): camera, desktop-face, process, Google-Wifi-device each contribute; the resolver fuses. Adding Google Wifi = adding a lane, not rewiring consumers.
5. **Dormant pieces become explicit config**, not dead code: a location source either exists (and the consumer is enabled) or doesn't.

---

## Part 6 — State → lighting matrix (strawman to argue over)

This is the artifact the sit-down should fill in / correct. Time-of-day (day/evening/night/late_night) modifies brightness on top. **Bold = where today's behavior is ambiguous or fights.**

| Location · Occupancy | gaming | working | watching | relax/idle |
|---|---|---|---|---|
| **desk · present** | gaming palette (teal kitchen 39500, blue L1/L2, sync L2/L5) | working ct whites | watching warm + desk L2 lift | relax / idle rules |
| **desk · afk** (game/app running, no face) | gaming palette holds at the desk; on a *sustained exit* → lux-adaptive path light (kitchen+L1), brightness scaled by Latitude room lux | same | same | same |
| **couch · present** | n/a | n/a | watching (couch is the watching seat now) | relax |
| **kitchen · present** | cooking palette (manual) | — | — | — |
| **in_transit** (left desk, walking) | transit path-light L1+kitchen | transit | transit | transit |
| **bed · present** | — | — | **reclined → dim (DORMANT — needs bed source)** | wind to sleeping? |
| **away** (nobody home) | **off / minimal? ← shelved away-mode question** | off | off | off |

**Decisions this table forces:**
- **desk·afk:** the strobe's real question. Hold gaming warmth-free until a *sustained* away, then go warm? Dim after X min of afk? (Today: fires warm immediately on face-loss — now damped by sustain+cooldown, but the *policy* is still implicit.)
- **bed row:** only lights up if we revive a bed-location source (Part 7).
- **away row:** only meaningful if we adopt a reliable "nobody home" signal (Google Wifi).

---

## Part 7 — Open decisions for the sit-down (Anthony's calls)

1. **`desk·afk` / desk-exit policy** — ✅ **DECIDED 2026-06-01 (walk-through):** Anthony genuinely gets up mid-gaming (kitchen/bathroom), and plays some games that run in the *background* — so a "long-AFK = still here, hold gaming" assumption is wrong. Instead: **desk-exit fires on a genuine sustained exit (existing trigger, debounced), and the path-light brightness is LUX-ADAPTIVE from the Latitude camera** — room already bright → little/no boost; room dark → raise kitchen (+L1) enough to navigate, brighter the darker it is, up to a cap. This **replaces the fixed `BRI_EVENING=120 / BRI_NIGHT=60`** in `desk_exit_kitchen_service.py` (and the analogous transit nav brightness).
   - **Why this is room-correct (and NOT the bug we fixed):** the bug was scaling *bedroom* gaming lamps by *living-room* lux. Here the lights being boosted (L1 living-room + kitchen) are **in the Latitude camera's own room**, so its lux reading matches the room being lit. Clean two-camera split: desktop webcam = "did he leave the desk?" (trigger); Latitude = "how dark is the destination room?" (brightness).
   - **Feedback handling:** L1 contributes to the lux the Latitude reads, so use **measure-then-hold** — sample lux at the moment of exit (before boosting), pick brightness, hold it until return (no re-evaluation while boosted → no oscillation).
   - **Open sub-question:** dark-threshold relative to calibrated baseline (~74) vs a fixed floor. Lean: baseline-relative.
   - Note: this needs only the *living-room* lux we already have — distinct from H2 (#4), which is about *bedroom* lux for the gaming desk lamps.
2. **Phone presence → away/home (WANTED — signal reframed 2026-06-01).** Goal: detect *Anthony* leaving/arriving (phone-keyed — kiosk/Sonos/bridge are always-on, so "any device" is useless). **Do NOT depend on the Google Wifi device API** — it's unofficial and largely removed on the app-managed version; and LAN-polling an iPhone is precisely what shelved the original away-mode (WiFi sleep + MAC randomization → false "away"). **Use an iOS Shortcut geofence automation** ("arrive/leave home → `POST` the hub") — push-based, instant, sidesteps the iOS-on-LAN problems. Google Home *showing* the iPhone confirms it's identifiable but is the app, not a query API. Reuse existing scaffolding: `signal_presence()`, `_check_external_off()`, and the Hue app's Home/Away geofence (already integrated). Net build = an explicit `away`/`home` state the hub owns, + the D6 behaviors.
3. **Bed signals — REFRAMED 2026-06-01.** Anthony's biggest regression isn't auto-sleep (parked, low priority) — it's the **late-night bed-watching DIM** (`_apply_zone_overlay` bed branch). Key insight: we don't need to *see* him in bed; we need "watching in the bedroom, not at the desk, late." **Trigger on projector-ON + not-at-desk + evening/night** (projector = bedroom-watching signal) → dim L1/L2, deeper at late_night. No camera-zone, no hardware, no posture needed. **Dependency:** the projector Kasa integration (`worktree-projector-kasa`, deploy pending). `watching_sleep_guard` + the zone+posture rule stay dormant (need true posture / a sensor — revisit only if one lands). **Confirmed 2026-06-01: Anthony watches in bed ONLY via the projector, at night** → projector-on + not-at-desk + night is sufficient; scope bed-dim to evening/night/late_night.
4. **Per-room lux / two baselines (audit H2) — ELEVATED.** Symptom: bedroom dim in daytime (his room darker than the blinds-open living room) because the only lux source is the living-room camera and `LUX_MODES={relax}` left bedroom modes with no adaptation. Fix: desktop `emotion_capture` adds a `gray.mean()` brightness sample to its observation POST → backend per-room lux map (`living_room←latitude`, `bedroom←desktop`) + two calibrated baselines + mode→room tagging → re-expand `LUX_MODES` to {relax(LR), gaming/working/watching(bedroom)}. Each consumer (incl. D1 path lighting) goes baseline-relative against *its own room*. **Spike result 2026-06-01 (code read):** `emotion_capture` opens `cv2.VideoCapture(0)` with NO exposure control → runs auto-exposure → naive `gray.mean()` lux would be auto-compensated and unreliable. Deeper conflict: FaceLandmarker wants auto-exposure (find the face); lux wants pinned exposure (honest darkness) — the one webcam can't do both well.
  **Two paths:**
  - **P1 webcam double-duty — ✅ VIABLE (spike passed 2026-06-01, no purchase).** `scripts/probe_webcam_exposure.py` via DSHOW: exposure sweep -4/-6/-8/-10 → frame mean 149.7/83.0/36.5/17.1 — brightness tracks the setting cleanly, so manual exposure IS honored (auto-exposure overridden). Quirk: `CAP_PROP_AUTO_EXPOSURE` readback is unreliable (-1.0) but setting `CAP_PROP_EXPOSURE` directly forces manual anyway. **Design caveat:** a pinned low exposure darkens the image → can hurt FaceLandmarker in a dark room. Likely mitigation: keep auto-exposure for face detection, and every N seconds flip to a fixed exposure for ONE lux sample then flip back. **(Chosen path — Anthony prefers no buy.)**
  - **P2 Philips Hue motion sensor in bedroom (~$40, fallback if P1's face/lux flip proves too fiddly):** built-in lux + motion presence, native Hue, also a partial **D3** answer. Route via `lighting-shopper` + `LIGHTING_EXPANSION.md`.
5. **Couch vs desk authority — DECIDED 2026-06-01.** **Single-occupant model** (Anthony lives alone; guests are almost always co-located with him). Tiebreak when both fresh: **freshness-first; activity adjudicates ONLY a genuine simultaneous-fresh conflict** — a *background* game must not pin "desk" once the desk face goes stale and the couch commits (→ couch wins). Bonus: the common phantom desk face-FP (chair/picture) while on the couch is correctly rejected (no foreground game → couch). Guest-sleepover (guest on couch, him in bedroom) is explicitly **out of scope** for auto-tracking → manual scene / future guest mode, not resolver cleverness.
6. **Away/home behaviors — DECIDED (via D2).** Confirmed spam source = the hub's own ntfy + desktop toasts. **Root cause is presence, not the notifier:** with no away-detection the hub thinks Anthony's home, autonomous setters keep nudging brightness, and each nudge notifies. So LEAVE: lights off + suppress autonomous setters (already `_check_external_off`'s behavior) → nothing happening → no churn notifications; emit ONE "away" notification; a genuine event would still notify. **Do NOT blanket-mute — full notifications stay ON when home (he values the visibility).** ARRIVE: welcome-home sequence (lights ± TTS / music), the inverse of the Hue "Leaving home" all-off. FUTURE: NL "coming home with friends → set the mood" via Alexa skill / text endpoint (deferred).

---

## Part 7.5 — D1 + D4 build plan (DESIGN-LOCKED 2026-06-01)

The lead build. Decisions resolved in the sit-down: **(a)** synced lamps (L2/L5) DO scale with bedroom lux — that's the whole point, the bedroom is consistently dark while gaming/watching; **(b)** bedroom calibration via settings-flag self-calibrate; **(c)** sequence D1 → D4.

**Why two lux sources.** Both decisions are "baseline-relative per room," but they read *different* cameras:
- **D1** boosts L1 + kitchen — **living-room** fixtures the **Latitude already** measures (`ema_lux` + baseline ~74, via `automation._read_fresh_camera_lux()`). No new plumbing → ships first.
- **D4** is the new plumbing — a **bedroom** lux channel off the desktop webcam (flip-sample-flip), a second baseline, mode→room tagging, re-expanded `LUX_MODES`.

The bedroom's lamps split into two ownership groups, both driven by ONE bedroom darkness factor:
- **L1 + kitchen** (static palette) → engine's `apply_lux_multiplier` (re-expanded `LUX_MODES`).
- **L2 + L5** (screen-synced) → `screen_sync._scale_for_ambient()`, which *already* scales caps/floors by a `lux_multiplier` — today gated to gaming-day + fed the bedroom-blind Latitude lux. D4 swaps the source + extends the gate.

### Phase 1 — D1 (existing Latitude lux)
1. New curator-gated pure helper `path_light_brightness(lux, baseline, period, *, fallback)` in `light_state_calculator.py` — baseline-relative darkness `clamp((baseline−lux)/baseline,0,1)` → interpolate into `[min,max]` per period (evening brighter, night gentler); `lux is None` → return the existing fixed constant.
2. `desk_exit_kitchen_service.py` — sample Latitude lux **once at `_activate`** (**measure-then-hold**: stash the sample, recompute from it on the evening→night repaint, never re-sample while boosted — L1 feeds back into Latitude lux → re-eval oscillates). Kitchen-only path + late-night corridor (L1 + kitchen). CT unchanged.
3. `transit_lighting_service.py` — same helper in `_navigation_states` for L1 (+ kitchen when it owns it).
4. `BRI_EVENING=120 / BRI_NIGHT=60` (+ transit 60/120/40/80) become **fallback anchors**, not deletions.
5. Re-spawn `lighting-curator` on the real diff before commit (helper lives in a hook-gated file) — the anchors below are curator-proposed but the full D-section checks run against concrete code.

**Locked CURVE anchors** (lighting-curator design pass 2026-06-01 — `(lo, hi)` = bri at room-bright `d→0` / pitch-black `d→1`; CT unchanged):

| kind · period | (lo, hi) | note |
|---|---|---|
| desk-exit kitchen (L3/L4) · evening | (55, 140) | hi matches working/day kitchen baseline |
| desk-exit kitchen (L3/L4) · night | (30, 70) | pendant lo-floor 25; dark-end held sub-lighthouse (was 75) |
| corridor L1 · late_night | (48, 100) | hi = validated comfortable L1 (the 80→100 user bump); lo +3 off the 45 threshold |
| corridor kitchen (L3/L4) · late_night | (25, 45) | pendant lo-floor 25 |
| transit L1 · evening | (55, 130) | fabric-shade wash, lower ceiling than the kitchen downlights |
| transit L1 · night | (45, 70) | **lo floor-corrected 30→45** (L1 ≥45 night-visibility floor, `project_apartment_layout`) |
| transit kitchen (L3/L4) · evening | (40, 90) | path-light flood, sub-cooking |
| transit kitchen (L3/L4) · night | (25, 45) | pendant lo-floor 25 |

Curator rules carried into the build: compute the ramped `bri` **once** then assign to both L3+L4 (kitchen-pair stays matched by construction); keep the evening>night `hi` gap distinct (evening tolerates flood, night is sleep-adjacent); `late_night→night` already collapses for the desk-exit *kitchen* path, so only the corridor needs true late_night anchors.

### Phase 2 — D4 (bedroom lux channel)
1. `emotion_capture.py` — open cam with `CAP_DSHOW` (default MSMF ignores exposure); every ~25s flip to the calibrated fixed exposure, average `gray.mean()`, restore auto-exposure; **suppress the presence POST during the ~1.5s flip** (hold prior `face_present`) so dark frames never flip the desk-flicker signal. POST lux separately.
2. **Calibration — settings-flag self-calibrate** (mirrors the snapshot-request pattern): `desktop_lux_calibrate_requested` flag picked up on the 30s settings poll → exposure sweep to `gray.mean()≈100` at "comfortable bright" bedroom light → POST `{exposure, baseline_lux}` → persisted to `app_settings.desktop_lux_calibration_config`, flag cleared. Agent pins that exposure for every sample thereafter.
3. Transport + store — new `POST /api/camera/desktop/lux {ambient_lux, captured_at}` → a small `LuxChannel` (ema + baseline + last_update + staleness) on `app.state` for `bedroom`. Living-room stays on `camera_service`.
4. Engine — `MODE_ROOM = {relax: living_room, gaming|working|watching: bedroom}`; `_apply_lux_multiplier` selects `(ema, baseline)` by the mode's room; re-expand `LUX_MODES → {relax, gaming, working, watching}`. Scope the engine multiplier to L1+kitchen in gaming/watching (L2/L5 owned by sync).
5. Screen-sync — feed the **bedroom** lux_multiplier into `apply_color` for gaming/watching (swap the source at `automation.py:273`); **extend `_scale_for_ambient`'s gate** from gaming-day to evening/night/late_night + watching. **Curator-validate the L5 clear-housing ceiling** at evening/night — the code comment flags this lift was never validated (`feedback_clear_housing_perceptual_luma`).

### D4 implementation breakdown (locked 2026-06-01)

**Foundation already shipped tonight** (`347e684`): `emotion_capture._ensure_cap` opens the Brio via `CAP_DSHOW` + forces auto-exposure on every open. So D4's two riskiest unknowns are answered — exposure control works (spike) and auto-restore works (mean 10→91). See [[project_desktop_webcam_dshow]].

Component-level changes (file → what):
- **C. Store + endpoints** — new `LuxChannel` helper (`ema_lux` via `LUX_EMA_ALPHA`, `baseline_lux`, `last_update`, staleness; factored from `camera_service._update_ema_lux` so living-room is untouched). `app.state.bedroom_lux`. `POST /api/camera/desktop/lux {ambient_lux, captured_at}` → `bedroom_lux.update()` (LAN-bypass auth like `/observation`). `POST /api/camera/desktop/lux/calibration {exposure, baseline_lux, target_lux}` → persists `app_settings.desktop_lux_calibration_config`, sets channel baseline, clears the request flag.
- **B. Calibration** — `desktop_lux_calibration_config` + a `desktop_lux_calibrate_requested` flag surfaced on the `/api/personality/settings` poll. Agent routine mirrors `camera_service.calibrate_exposure` (binary-search exposure → `gray.mean()≈100` at comfortable-bright bedroom → POST → clear flag).
- **A. Sampling** (`emotion_capture.py`) — flip-sample-flip every ~25s: set manual exposure → settle → average `gray.mean()` → **restore auto on the SAME handle** (the agent only force-autos on *open*, so a same-handle restore is mandatory — pr-review constraint) → settle → POST lux. Skip the presence POST that tick. Gated on `calibrated`.
- **D. Engine** — `LUX_MODES → {relax, gaming, working, watching}`; `MODE_ROOM = {relax: living_room, gaming|working|watching: bedroom}`. `automation_engine._read_fresh_room_lux(room)` picks the source; `_apply_lux_multiplier` selects by mode's room; multiplier scoped to L1+kitchen in gaming/watching.
- **E. Screen-sync** — bedroom lux_multiplier into the screen-color route; extend `_scale_for_ambient` gate to gaming/watching × evening/night/late_night; curator-validate the L5 ceiling.

**Build order** (each a deployable increment): **C → B → A → shadow-log bedroom lux ~1 day → D → E.**

Micro-decisions: (1) **shadow-log before flipping `LUX_MODES`** — yes (cross-room-contamination history). (2) **full-frame `gray.mean()` v1**, zone-weighting later if it reads off. (3) D4 lux sampler restores auto on the same handle (see A).

### Risks tracked
- **L5 perceptual overdrive** (clear housing) at evening/night — the one genuinely unvalidated piece; curator gates it.
- **Flip-sample vs face-flicker** — mitigated by suppressing the POST during the flip; non-negotiable given this whole initiative came from the warm↔gaming strobe.
- **Bedroom calibration drift** — re-measure if the webcam moves or its resolution changes (same rule as the Latitude).

---

## Part 8 — Migration path (incremental, not big-bang)

1. **Shadow the resolver.** Build `PresenceResolver` read-only; log what location/occupancy/activity it *would* commit, alongside what the live consumers actually did. Validate against a few days of real behavior (esp. the desk-flicker windows). No behavior change.
2. **Migrate the worst offenders first.** Point `transit` + `desk_exit` at resolver transitions; delete their local dwell/sustain/cooldown bookkeeping. Verify the strobe stays dead with *less* code.
3. **Migrate the relax setters** (`ambient_relax`, `late_night_rescue`) to `on_afk`/`on_away`/idle-dwell transitions; retire the `is_recent_process_working()` veto if the resolver's `afk` state subsumes it.
4. **Light up new states as sources arrive** — Google Wifi lane → `away`; bed source → revive the three dormant consumers.
5. **Retire dead code** once its source is decided (delete or formally revive the bed-zone features).

---

### Appendix — grounding references
Memories: `project_apartment_layout`, `project_camera_position`, `project_zone_posture_checkback`, `project_watching_sleep_guard`, `project_away_mode_shelved`, `project_latitude_audio_parked`, `project_process_attendance_veto`, `project_camera_at_desk_veto`, `project_transit_lighting_cache_pop_churn`, `feedback_lighting_design_principles`.
Code: `presence_fusion.py`, `automation_engine.py` (`is_at_desk_fresh`/`is_recent_process_working`/`is_present_in_room`/`signal_presence`/`_apply_zone_overlay`/`run_loop`), `transit_lighting_service.py`, `desk_exit_kitchen_service.py`, `camera_service.py`, `confidence_fusion.py`, `light_state_calculator.py` (`ACTIVITY_LIGHT_STATES`).
