# AI Personality Layer

> **Status:** Phase A shipped 2026-05-18 (commits e57fdad → a2d0e2a → 9d6e534). Phase B gated on validation — **gate checked 2026-06-09: WAIT, insufficient data** (6/30 paired samples; see "Validation gate" below). Phase C v1 shipped 2026-07-06/07: `/api/personality/vibe` + iOS Shortcut natural-language vibe routing, including staged arrival vibes.
> **Plan origin:** 2026-05-17 brainstorm — user picked "AI Personality" as one cohesive big build over a menu of smaller ideas. Twitch/streaming explicitly dropped from scope.
>
> **Canonical policy note — August 14, 2026:** This document remains the subsystem design and historical record for the code named `personality`. The [Product Experience Contract](PROJECT_SPEC.md#product-experience-contract--august-14-2026) owns cross-system policy. In that contract, **Mood Context** is a temporary, user-confirmed context with six states; it is not a claim about enduring personality or a silently inferred emotional truth. The committed detector, calibration UI, and VibeRouter are `SHIPPED/CURRENT` capabilities whose production health still requires live verification. The current calibration form pairs a self-report with the detector reading available at submission time; the decided target instead freezes only the 20–30 minutes of evidence preceding the prompt. The Spearman gate below remains useful for evaluating this detector and the proposed mood-ring experiment, but it does not authorize other actions: autonomy graduates per action and consequence.

---

## Historical Subsystem Goal

> One accent light that quietly reflects the apartment's emotional state, plus a voice command that lets you describe how you want the room to feel and have Claude pick the mode + lights + music.

Home Hub today reacts to *what* you're doing (process detection, camera zone, audio class) but not *how you feel*. The LoL champion-color pattern works because the room reflects your in-the-moment state visually — this build extends that pattern from "what game you picked" to "what mood the room is in."

---

## Architecture overview

Three services in `backend/services/personality/`, one parallel detector added to `camera_service.py`, a shipped iOS Shortcut vibe entrypoint, a future Alexa intent, and three DB tables. One-directional pipeline:

```
camera_service ──face_blendshapes_cb──┐
                                       ├─> EmotionService ──mood_vector──┐
audio_classifier (prosody features)───┘                                   │
                                                                          ├─> MoodRingLight (passive: 1 light, EMA-smoothed)
                                                                          │
                                                                          ├─> MoodSuggestionService ──> NotifierService (toast + push)
                                                                          │       (divergence >5min from active mode target)
                                                                          │
                                                                          └─> vibe_requests log (ml_decisions mirror still future)

iOS Shortcut "Home Hub Vibe" ──tunnel──> VibeRouter ──rules first / Claude API fallback──> {mode, scene_id, acknowledgement}
                                                             ↓
                                            automation_engine.set_mode() + curated scene apply, or staged until arrival
```

The `mood_vector` is `{valence ∈ [-1,1], arousal ∈ [-1,1], focus ∈ [0,1], confidence, ts}`. Subscribers read from an in-memory last-value cache + asyncio.Event — same shape as `automation_engine._last_fusion_result` consumed by `NotifierService` today.

---

## Recommended approach

**Emotion model:** MediaPipe `FaceLandmarker` (Tasks API) with blendshapes + hand-tuned 52→3 linear map.

Rejected alternatives:
- FER+ TFLite — categorical "happy/sad/angry" output is the wrong shape; trained on posed lab faces, collapses at three-quarter webcam profiles.
- DeepFace — too heavy, MediaPipe is C++ kernels already in the dep tree.
- Cloud emotion APIs — breaks the on-device privacy contract `camera_enabled` already promises.

Why FaceLandmarker wins:
1. Same MediaPipe Tasks runtime as the BlazePose model `camera_service.py` already loads.
2. 52 ARKit-style blendshapes (`browDownLeft`, `mouthSmileRight`, `eyeBlinkLeft`, …) are interpretable, so V/A is a hand-tunable linear function, not a black box.
3. Degrades gracefully at three-quarter profile.
4. The 478-landmark output also gives `focus` via eye-gaze direction for free.

**Design change vs original plan:** Phase A added FaceLandmarker as a *parallel conditional detector* alongside the existing BlazeFace full-range model — NOT a swap. The project chose BlazeFace full-range specifically for the corner-view profile; swapping it would regress presence detection. FaceLandmarker only runs when `emotion_enabled` AND a face is already detected with ≥ `FACE_LANDMARKER_TRIGGER_CONFIDENCE` (0.30).

**Audio prosody** (energy + spectral centroid from the existing 0.975s YAMNet frames) was scoped to contribute additively to `arousal` weighted 0.3 vs face 0.7. Deferred from Phase A — `audio_classifier` doesn't yet expose raw RMS / spectral features; tracked as a separate follow-up. Every `mood_samples` row already includes `factors.audio_arousal=null` as the forward-compat marker.

**Claude API stays in the backend, not edge clients.** The shipped iOS Shortcut only captures text and POSTs it to `/api/personality/vibe`; deterministic rules handle common requests before any model call. Future Alexa `VibeIntent` should keep the same boundary: `alexa_skill/lambda_function.py` stays stdlib-only and forwards `{vibe}` through the tunnel, with the backend owning Anthropic calls and validation.

**Cost bounding:**
- Model: configured by `ANTHROPIC_MODEL` (default `claude-3-haiku-20240307`) — structured-output task, not reasoning. Deterministic rule hits cost $0; model fallback is expected to be around $0.001/request.
- Daily cap via `vibe_daily_cost_cap_usd` setting (default $0.50, ~500 requests/day — generously above ceiling).
- 24h SHA256 cache on normalized transcripts ("set my vibe to focus mode" hits cache on repeat).
- Anthropic prompt caching on the system prompt (mode list + light IDs + scene rules + current state, ~800 tokens cached).
- Per-source-IP rate limit at the endpoint: 30/hour.

**False-positive handling for this detector experiment:** Phase A uses a calibration loop rather than a generic confidence threshold. Once-daily calibration prompts ("rate your mood right now") accumulate self-report vs detector pairs. Phase B only ships if per-axis Spearman ρ > 0.4 over 30+ samples. Per-user bias vector (3 floats) is added at output time after calibration. The suggestion service has a 3-dismissals-in-24h kill switch as a runtime safety valve. This subsystem gate does not replace the canonical action-specific trust ladder.

---

## Phases

### Phase A — Emotion Service · SHIPPED 2026-05-18

What landed (commits `a2d0e2a` + `9d6e534`):

- `EmotionService` consumes blendshapes via a new camera callback; projects 52 blendshapes → (V, A, F) via hand-tuned coefficients; EMA-smooths at α=0.3; persists every 10s to `mood_samples` (rolling 7-day).
- `FaceLandmarker` added in parallel to `camera_service.py`, lazy-loaded on first `emotion_enabled=true` flip.
- 3 new tables: `mood_samples`, `mood_calibration`, `vibe_requests` (created forward-compatibly in Phase A, now used by Phase C v1).
- `/api/personality/*` routes: `mood/current`, `mood/history`, `calibration` POST + history, `settings` GET + POST.
- `/personality` SvelteKit page: live V/A/F gauges + HSV color swatch preview, slider self-report form, sub-toggles + master kill switch, 24h history strip. Hidden from FloatingNav (same pattern as `/journal`).
- Three new app_settings: `personality_enabled` (master), `emotion_enabled` (sub-toggle), `mood_ring_enabled` (Phase B preview), plus `mood_ring_light_id` + `mood_calibration_bias`.
- Auto-fit per-axis bias on POST `/calibration` once ≥10 self-report rows accumulate.

**Validation gate:** 2-week shadow log + once-daily calibration prompts. Phase B ships only if Spearman ρ > 0.4 on all three axes over 30+ samples.

**Gate status (checked 2026-06-09): WAIT — not evaluable yet.** Paired self-report-vs-detector accrual only began 2026-05-29 when `calibration_nudge.py` came online (the original 5/18 ship had the form but no prompt mechanism), so the effective clock started then, not at Phase A ship. 6/30 pairs accumulated; at the observed ~1 pair per 1.5 days the gate matures **~mid-July 2026**. Pipeline is healthy: ~26k `mood_samples` rows/7d, all toggles on, nudges firing on schedule. Provisional ρ on n=6 (statistically meaningless, recorded for trend): valence +0.06, arousal +0.20, focus −0.12. **Early warning:** detected valence is nearly flat (−0.19..−0.11) at calibration moments while self-report spans −0.15..+0.35 — if that persists at n=30, the valence axis fails the gate; suspect the blendshape→valence coefficients saturate near neutral on a working face.

### Phase B — Mood Ring Light (gated on Phase A validation)

`MoodRingLight` service. Subscribes to mood vector, maps `(valence, arousal)` → HSV via `mood_palette.py` (already shipped), EMA-smooths over 30s, only writes when `|Δ| > 5%`. Honors `_manual_light_overrides`. Disabled when `mode == sleeping`. Adds `_personality_light_overrides` set so the IES reconcile loop skips it — mirror of the existing transit-override pattern.

Also requires:
- Add `"personality"` trigger to the non-`USER_TRIGGERS` exclusion at `backend/services/ml/lighting_learner.py:37` so mood-ring writes don't poison the EMA learner.
- Promote `/personality` mood updates from 5s polling to a new `personality_update` WS message type so the lamp doesn't poll.

### Phase C — Vibe Routing v1 · SHIPPED 2026-07-06/07

`VibeRouter` service + `POST /api/personality/vibe` landed as a text/Siri control path. The first production client is the iOS Shortcut named `home hub vibe`; Alexa `VibeIntent` and passive mood suggestions remain future work.

Request shape:

```json
{
  "transcript": "coming home with friends, set a party mood",
  "timing": "arrival_if_away"
}
```

Auth over the Cloudflare tunnel requires `X-API-Key` + `X-Skill-Token`; the Shortcut also sends `X-Source: ios_shortcut:vibe` for attribution. `timing="arrival_if_away"` applies immediately when home and writes `app_settings.pending_arrival_vibe` when away. After a geofence-arrive event, `AwayManager._on_arrive()` reapplies the current mode with force, applies the staged vibe, logs the request, and clears the pending setting. Camera presence only reports presence through `AutomationEngine.signal_presence("camera")`.

Routing is intentionally constrained. Deterministic phrase rules handle the common paths first:
- party/friends/guests/pregame → `social` + `house_party`
- neon/tokyo/cyberpunk → `relax` + `neon_tokyo`
- miami/vice → `relax` + `miami_vice`
- arcade/retro/game night → `social` + `arcade`
- aurora/northern lights → `relax` + `northern_lights`
- sunset/golden hour → `relax` + `sunset_strip`
- chill/cozy/calm/relax → `relax`
- cook/dinner/kitchen → `cooking`

Ambiguous requests can call Anthropic if `ANTHROPIC_API_KEY` is configured; responses are validated against known modes/scenes and never generate arbitrary light payloads. v1 remains lights/mode only, but applying `social` can still trigger existing mode-change callbacks such as MusicMapper's Party-Jazz autoplay.

`MoodSuggestionService` poll loop still belongs to the remaining Phase C work: fire through `notifier.publish_suggestion(...)` when mood diverges from active mode for >5 min (max 1/hr, 3/day, suppressed during sleeping/cooking/DND).

### Phase D — Hardening + Cost Dashboard (after Phase C)

- Cost ledger UI on `/personality` showing daily Claude spend (`cost_usd` column already on `vibe_requests`).
- "3 dismissals → suppress for the day" kill switch on `MoodSuggestionService`.
- Stress-test the calibration bias term after 4+ weeks of personal use — does linear correction hold, or do we need per-axis quadratic / per-mode bias?
- Tighten audio-prosody weighting on arousal axis (once that ships).

---

## Critical files

**Created Phase A (✓ shipped):**
- `backend/services/personality/__init__.py`
- `backend/services/personality/emotion_service.py`
- `backend/services/personality/mood_palette.py`
- `backend/api/routes/personality.py`
- `frontend-svelte/src/routes/personality/+page.svelte`

**To create Phase B+:**
- `backend/services/personality/mood_ring_light.py` — passive light output, EMA + dead-zone, override-aware.
- `backend/services/personality/mood_suggestion_service.py` — divergence detector → `NotifierService`.
- `alexa_skill/lambda_function.py` patch — add `VibeIntent` handler (paste-in, same shape as existing `HOMEHUB_MODE` handler).
- `alexa_skill/interaction_model.json` — `VibeIntent` with `{vibe}` slot of type `AMAZON.SearchQuery`.

**Created Phase C v1 (✓ shipped):**
- `backend/services/personality/vibe_router.py` — deterministic rule router, optional Anthropic fallback, response validator, staged-arrival persistence, `vibe_requests` logging.

**Modified Phase A / Phase C v1 (✓ shipped):**
- `backend/services/camera_service.py` — added `FaceLandmarker` as parallel conditional detector + `register_blendshape_callback()` + `set_emotion_enabled()` hooks.
- `backend/models.py` — added `MoodSample`, `MoodCalibration`, `VibeRequest` tables.
- `backend/database.py` — 7-day prune of `mood_samples` at boot.
- `backend/bootstrap.py` — registers `EmotionService` after `camera_service`, safe-shutdown wired.
- `backend/main.py` — router registration.

**To modify Phase B+:**
- `backend/services/ml/confidence_fusion.py` — extend the `camera` lane's `factors[]` with `emotion_valence` + `emotion_arousal`. **No new fifth lane** — mood is cosmetic + suggestion-only in v1.
- `backend/services/automation_engine.py` — add `_personality_light_overrides: set[str]`, intersect into the IES reconcile skip-set.
- `backend/services/notifier_service.py` — add `publish_suggestion(...)` that reuses the existing `BOOT_SUPPRESS_S` (line 47) + `COALESCE_WINDOW_S` (line 52) + `is_dnd_active()` (line 164) gates.
- `backend/services/ml/lighting_learner.py:37` — add `"personality"` trigger to the non-`USER_TRIGGERS` exclusion.

---

## Reusable patterns

- **EMA shape** from `LightingPreferenceLearner` (α=0.3) — same constant for mood_ring smoothing, keeps the apartment's "personality time-constant" consistent.
- **Privacy contract** from `camera_service.py:1653` ("Pausing turns off the camera (LED goes dark) for sleep privacy") — re-state in personality module docstring; face crops obey the same in-memory-only rule pose landmarks already do.
- **Health mixin** (`backend/services/ml/health_mixin.py`) — `HealthTrackable` on EmotionService so `/health` surfaces its state for free.
- **Notifier gating** — call `notifier.publish_suggestion(...)`, don't duplicate the BOOT/COALESCE/DND checks.
- **Remaining analytics mirror** — VibeRouter currently logs to `vibe_requests`; a future hardening pass should also mirror model-backed parses into `ml_decisions` with `decision_source="vibe"`, `factors={transcript, mode, cost_usd, latency_ms}` if we want the analytics SectorBoard to show them.
- **Service shape** (`_connected` + `async connect()` / `poll_state_loop(ws_manager)` / `close()`) — copy `notifier_service.py`.
- **Alexa intent pattern** — paste-in addition next to `HOMEHUB_MODE` handler, same `_call_homehub` helper, `X-Source: alexa:vibe` header so backend attributes correctly.

---

## Verification

- **Phase A validation (historical plan; last checked 2026-06-09):** 2-week shadow log + once-daily calibration prompts. Phase B ships only if Spearman ρ > 0.4 on all three axes over 30+ samples. Current production data and gate health require fresh verification.
- **Phase B:** Playwright UI audit at the four V/A corners (happy-energized, happy-calm, sad-energized, sad-calm) — confirm L1 hue matches palette. Manual L1 override → confirm mood ring stops touching it. Sleeping mode → confirm mood ring disabled.
- **Phase C v1:** `tests/test_vibe_router.py`, `tests/test_away_manager.py`, and `tests/test_tunnel_proxy.py` cover deterministic phrase mapping, staged-arrival apply/clear, invalid outputs, tunnel allowlisting, and auth shape. Production smoke: iOS Shortcut `home hub vibe` POSTs through `https://home-hub.gatte-home.com/api/personality/vibe`; Siri result is made clean by ending the Shortcut with `Show Result`.
- **After each phase:** Codex `$homehub-diagnose` for targeted API/runtime regression checks. `$deploy-home` to ship.

---

## Resolved design questions

(from the original plan; locked in during Phase A)

1. **Mood ring light:** L1 (the living-room lamp — naturally accent-y).
2. **Vibe intent scope:** mode + lights only in v1; no music auto-queue.
3. **Suggestion frequency:** 1/hr max, 3/day cap, suppressed during sleeping/cooking/DND.
4. **Mood vector → ConfidenceFusion:** stay cosmetic-only in v1; no math change.
5. **Calibration cadence:** once-daily prompts in Phase A.
6. **Claude budget:** $0.50/day cap (Haiku at ~$0.001/req = ~500 req/day budget).
7. **Master kill switch:** yes — `personality_enabled` setting is separate from the three sub-toggles.

---

## Risks

- **Privacy:** face crops carry a stronger signal than pose landmarks. Module docstring + README must re-state the contract loudly; `emotion_enabled` must be a separate setting from `camera_enabled` so the user can have presence detection without emotion.
- **Claude cost runaway:** mitigated by Haiku + daily cap + 24h cache + prompt cache + 30/hr per-IP rate limit. A misconfigured Echo repeat-triggering the intent is the realistic worst case; the per-IP limit is the load-bearing defense.
- **Annoyance / false positives:** the suggestion service is the highest-risk surface. Three layered defenses: calibration bias term, 1/hr cap, NotifierService DND-aware. The 2-week Phase A shadow-log gate (Spearman ρ > 0.4) is the load-bearing decision point — do not ship Phase B if it fails.
- **FaceLandmarker performance:** 478 landmarks is heavier than the current FaceDetector. Measure against the existing `FRAME_READ_TIMEOUT_S=5.0` watchdog; if it exceeds budget, downgrade landmarker to every 4th frame (8s cadence) while keeping the lightweight detector at 2s for presence.
- **Mood ring vs lighting learner conflict:** L1 is in the EMA learner's history. Personality writes must filter out of the learner's window — handled by adding `"personality"` to the non-`USER_TRIGGERS` exclusion at `lighting_learner.py:37`. One line, but easy to miss.
- **Bootstrap ordering:** EmotionService depends on CameraService connected before its callback fires. `backend/bootstrap.py` owns this composition/lifecycle order; register personality services after camera there.

---

## App settings keys (Phase A)

| Key | Shape | Default |
|---|---|---|
| `personality_enabled` | `{enabled: bool}` | `false` — master kill switch for the whole layer |
| `emotion_enabled` | `{enabled: bool}` | `false` — face blendshape extraction toggle (requires personality_enabled + camera_enabled) |
| `desktop_emotion_enabled` | `{enabled: bool}` | `false` — desktop pc_agent capture toggle (GH#64). Polled every 30s by the desktop supervisor; runtime-toggleable without supervisor restart. Independent of `emotion_enabled` (the Latitude path) — both can run simultaneously, EmotionService prefers desktop when fresh within 30s |
| `mood_ring_enabled` | `{enabled: bool}` | `false` — Phase B preview toggle; no effect until Phase B ships |
| `mood_ring_light_id` | `{light_id: str}` | `"1"` — which light the mood-ring drives in Phase B |
| `mood_calibration_bias` | `{valence: float, arousal: float, focus: float}` | `{0, 0, 0}` — per-axis bias correction fit from self-report calibration; auto-updated on POST `/api/personality/calibration` after ≥10 samples |
