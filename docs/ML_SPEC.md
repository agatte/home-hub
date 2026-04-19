# Home Hub ML Specification

> Machine learning capabilities for anticipatory ambient intelligence.
> This document specifies how ML integrates into the Home Hub system to replace
> hardcoded rules with learned behavior, add new sensing capabilities (camera,
> audio classification), and evolve toward autonomous operation.
>
> **Parent document:** `docs/PROJECT_SPEC.md` (system architecture, schema, API)
> **Status:** Phase 1 complete, Phase 2 complete, Phase 3 started (confidence fusion shipped)
> **Last updated:** April 15, 2026

---

## Table of Contents

1. [Vision & Goals](#1-vision--goals)
2. [Architecture](#2-architecture)
3. [Feature Specifications](#3-feature-specifications)
   - 3.1 [Audio Intelligence](#31-audio-intelligence)
   - 3.2 [Behavioral Prediction](#32-behavioral-prediction)
   - 3.3 [Adaptive Lighting Preferences](#33-adaptive-lighting-preferences)
   - 3.4 [Camera Presence & Posture](#34-camera-presence--posture)
   - 3.5 [Smart Screen Sync](#35-smart-screen-sync)
   - 3.6 [Music Selection](#36-music-selection)
4. [Data Pipeline](#4-data-pipeline)
5. [Model Selection & Rationale](#5-model-selection--rationale)
6. [Integration Architecture](#6-integration-architecture)
7. [Decision Explainability](#7-decision-explainability)
8. [Privacy & Security](#8-privacy--security)
9. [Performance Budget](#9-performance-budget)
10. [Cold Start & Bootstrapping](#10-cold-start--bootstrapping)
11. [Training & Retraining](#11-training--retraining)
12. [Frontend Integration](#12-frontend-integration)
13. [Testing Strategy](#13-testing-strategy)
14. [Deployment](#14-deployment)
15. [Phased Rollout](#15-phased-rollout)
16. [Metrics & Monitoring](#16-metrics--monitoring)
17. [Hardcoded Thresholds Reference](#17-hardcoded-thresholds-reference)

---

## 1. Vision & Goals

Home Hub today is a **reactive** system. It detects what you're doing via process
names and RMS volume, matches it to hardcoded rules, and applies lighting. Every
threshold is hand-tuned, every mode transition is rule-based, and the system has
no memory of what worked and what didn't.

The goal of ML is to transform Home Hub from reactive rule-following into
**anticipatory ambient intelligence** — a system that learns your patterns,
predicts what you need, and adapts over time until manual intervention becomes
rare.

### Phase Roadmap

| Phase | Timeline | Focus | Success Metric |
|-------|----------|-------|----------------|
| **Phase 1: Lightweight Classifiers** | ✓ Complete (April 2026) | Behavioral prediction (LightGBM, shadow mode), adaptive lighting (EMA), ML decision logging, model manager + nightly retraining, feature builder, full REST API | Collecting data; predictor needs 500+ events to train |
| **Phase 2: Computer Vision & Learning** | ✓ Complete (April 2026) | ✓ Smart screen sync (K-means), ✓ music selection bandit (Thompson sampling), ✓ audio scene classification (YAMNet, shadow mode on Blue Yeti), ✓ camera presence detection (MediaPipe FaceDetector on Latitude webcam, 15s away detection). Remaining for Phase 2b: posture classification (BlazePose upgrade) | Camera presence: 15s away detection (vs 10-min idle timer). Audio: shadow mode collecting data for RMS comparison. |
| **Phase 3: Autonomous Operation** | In progress (April 2026+) | ✓ Confidence fusion (5-signal weighted ensemble, auto-apply at 95%+, stale override at 92%+). ✓ Live pipeline dashboard with per-signal gauges. ✓ Accuracy-driven weight learning (nightly `fusion_weight_tuning` cron). ✓ Shadow-logged fusion decisions + windowed `actual_mode` backfill. ✓ Override-rate metric (`/api/learning/override-rate`) + A/B comparison (`/api/learning/compare`). Remaining: analytics-page dashboard UI, threshold tuning on live FP data | Fewer than 2 manual overrides per day |

### Design Principles

1. **Every ML feature has a non-ML fallback.** ML never makes things worse — it
   either improves on the baseline or stays silent. The fallback is always the
   current production behavior.

2. **Local-only processing.** No cloud ML services, no telemetry, no external
   API calls for inference. All models run on the Latitude 7420's CPU.

3. **Conservative autonomy.** ML auto-applies mode changes only at 95%+
   confidence. At 70-95%, it suggests via toast. Below 70%, it stays silent.
   The user always has final say.

4. **Shadow before promote.** Every ML feature runs in shadow mode for 1-2 weeks
   (predicting without acting, logging accuracy) before being promoted to active.

5. **Privacy by architecture.** Camera frames never leave memory. Audio is
   reduced to mel-spectrograms immediately. Only derived labels persist.

### Non-Goals

- Gesture control (hand wave, swipe) — deferred until camera basics are validated
- Cloud ML / external inference APIs — everything stays local
- Multi-user / collaborative filtering — single-user system by design
- Real-time voice commands — Alexa/Fauxmo handles voice; ML handles sensing

---

## 2. Architecture

### Service Model: Embedded, Not Microservice

ML services follow the same pattern as every other Home Hub service: Python
classes initialized in `main.py` lifespan, attached to `app.state`, with async
methods called from the automation loop or on schedule.

**Why not a separate process?** The Latitude 7420 has 2-4 cores and 8-16GB RAM
shared with Pi-hole (Docker), Firefox kiosk, and the ambient monitor. A separate
ML process would waste RAM on duplicate imports and complicate deployment. The
existing single-process async architecture handles 23 services already — ML adds
a few more with minimal overhead.

### New Package Structure

```
backend/services/ml/
    __init__.py
    audio_classifier.py      # Phase 2: YAMNet audio scene classification (shadow mode, runs on desktop)
    behavioral_predictor.py  # Phase 1: LightGBM mode prediction (shadow mode)
    confidence_fusion.py     # Phase 3: Weighted ensemble of all signal sources
    lighting_learner.py      # Phase 1: Adaptive per-light preferences
    music_bandit.py          # Phase 2: Thompson sampling playlist selection
    feature_builder.py       # Shared: Feature engineering from event tables
    model_manager.py         # Shared: Model loading, versioning, health checks
    ml_logger.py             # Shared: Decision logging with explainability
```

### Model Storage

```
data/models/                           # gitignored, persists on each machine
    yamnet.tflite                      # YAMNet audio classifier (16MB, auto-downloaded)
    yamnet_class_map.csv               # YAMNet 521 class names (auto-downloaded)
    blaze_face_short_range.tflite      # MediaPipe face detection (230KB, auto-downloaded)
    mode_predictor.lgb                 # LightGBM trained from activity_events
    lighting_prefs.json                # Learned per-light brightness/color preferences
    music_bandit.json                  # Thompson sampling Beta parameters
    model_meta.json                    # Version, last trained, accuracy metrics
```

### Fallback Chain

When the automation engine needs to determine what mode to apply, it consults
sources in priority order. Each layer only fires if the layer above has no
confident prediction:

```
1. Manual override          → Always wins (4h timeout)
2. Confidence fusion        → Weighted ensemble of all signals below (Phase 3)
   - Can auto-apply at 95%+ when idle/away
   - Can override stale process detection at 98%+ with 80%+ agreement
3. Activity detection       → Process-based (gaming, working, watching)
   + Camera presence        → Absent/present (Phase 2)
   + Audio classification   → Speech, music, silence (Phase 2)
4. ML behavioral prediction → LightGBM mode prediction (Phase 1)
5. Rule engine              → Frequency-based day+hour rules
6. Time-based rules         → Hardcoded schedule defaults
```

**Confidence fusion** (Phase 3, `confidence_fusion.py`) combines 5 signal sources
into a weighted ensemble: process detection (wt 0.35), camera presence (0.20),
behavioral predictor (0.20), audio classifier (0.15), rule engine (0.10). Weights
start at these defaults and update nightly from measured per-signal accuracy.
Stale signals (>5 min) are excluded and their weight redistributed.

### Data Flow Diagram

```
Sensing Layer                    ML Layer                     Action Layer
=============                    ========                     ============

PC Agent ─────────┐
  (psutil, 5s)    │
                  ├──> /api/automation/activity
Ambient Monitor ──┤        │
  (PyAudio, 1s)   │        ├──> AutomationEngine
                  │        │       │
Camera Service ───┘        │       ├──> MLService.predict_mode()
  (MediaPipe, 5s)          │       │       │ features from FeatureBuilder
                           │       │       │ model from data/models/
                           │       │       └──> prediction + confidence
Audio Classifier ──────────┘       │
  (YAMNet, 2-3s)                   ├──> RuleEngine.check_rules()
                                   │       └──> frequency-based fallback
                                   │
                                   ├──> time_rules (hardcoded fallback)
                                   │
                                   ├──────> Confidence gate
                                   │        >=95%: auto-apply
                                   │        70-95%: suggest via toast
                                   │        <70%: silent
                                   │
                                   ├──> HueService.set_light()
                                   ├──> MusicMapper.on_mode_change()
                                   ├──> MLLogger.log_decision()
                                   └──> WebSocket.broadcast()

Training Loop (nightly at 4 AM)
================================
EventQueryService ──> FeatureBuilder ──> train models ──> data/models/
  (activity_events,     (pandas DF)       (LightGBM,      (versioned
   light_adjustments,                      EMA stats)       with timestamp)
   sonos_events)
```

---

## 3. Feature Specifications

### 3.1 Audio Intelligence

**Phase:** 1 (Priority 1 — highest ROI, lowest risk)

**Problem:** The ambient monitor (`ambient_monitor.py`) uses binary RMS volume
thresholds to detect social mode. It cannot distinguish conversation from TV
audio, music, or game sounds. The 2-minute sustained noise requirement causes
delayed detection, and the 800 RMS threshold is environment-dependent.

**Solution:** Replace RMS-only analysis with a pretrained audio scene classifier
that identifies what kind of sound is occurring.

| Attribute | Value |
|-----------|-------|
| **Input** | 16kHz mono PCM from Blue Yeti (existing PyAudio pipeline in `ambient_monitor.py`) |
| **Preprocessing** | Log-mel spectrogram: 128 mel bins, 25ms window, 10ms hop. Computed via `scipy.signal` or `librosa`. Produces a 2D feature map from each 0.96s audio clip. |
| **Model** | YAMNet (Google AudioSet, TensorFlow Lite) or custom ONNX classifier. YAMNet covers 521 AudioSet classes; we collapse to 9 relevant classes. |
| **Output classes** | `silence`, `speech_single`, `speech_multiple`, `music`, `tv_dialog`, `game_audio`, `doorbell`, `cooking`, `mechanical_noise` |
| **Inference frequency** | Every 2-3 seconds (aggregate 2-3 chunks of existing 1s reads) |
| **Integration point** | Replace `AmbientMonitor.check()` return. Emit classified scene + confidence to `AutomationEngine.report_activity(source="audio_ml")` |
| **Cold start** | Ship with pretrained YAMNet weights. No user data needed. Optional fine-tuning after 2+ weeks of labeled corrections. |
| **Expected accuracy** | 85%+ on silence/speech/music distinction (pretrained). Social detection improves from "sustained RMS >800 for 2 min" to "multiple voices for 30s". |
| **CPU cost** | 15-30ms per inference |
| **RAM** | 50-200MB (model dependent) |
| **Privacy** | Audio processed as mel-spectrograms in memory. Raw PCM overwritten each read cycle. Only classification labels and confidence scores persist in the database. No audio is ever recorded, stored, or transmitted. |

**Mode mapping from audio classes:**

| Audio Class | Mode Signal | Confidence Required |
|-------------|------------|---------------------|
| `speech_multiple` (sustained 30s+) | social | 80% |
| `speech_single` (sustained 60s+) | (no mode change, informational) | — |
| `game_audio` + no game process | watching (likely streaming) | 75% |
| `music` (loud, sustained) | (could be social if combined with speech) | — |
| `silence` (sustained 60s+) | idle (exit social) | 70% |

**Rollout plan:**
- Phase 1a: Run classifier alongside RMS in shadow mode. Log both outputs, compare.
- Phase 1b: When classifier agrees with RMS >90% of the time AND catches cases RMS misses, switch automation to classifier.
- Phase 1c: Shorten social detection window from 2 minutes to 30 seconds using `speech_multiple` confidence.

**Files touched:**
- `backend/services/pc_agent/ambient_monitor.py` — Major refactor: add spectrogram pipeline, load ONNX model, emit classified results
- New `backend/services/ml/audio_classifier.py` — Model loading, inference, class collapsing
- New model file: `data/models/audio_scene.onnx`

---

### 3.2 Behavioral Prediction

**Phase:** 1 (Priority 2)

**Problem:** The existing `RuleEngineService` uses frequency counting on
(day_of_week, hour) slots over 30 days of `activity_events`. It produces rules
like "Friday 8pm = gaming (85% confidence, 7 samples)." This is effective for
strong patterns but cannot incorporate richer context: weather, mode duration,
sequences, or cross-feature interactions.

**Solution:** Replace the frequency counter with a gradient boosting classifier
that learns from richer features.

| Attribute | Value |
|-----------|-------|
| **Input** | `activity_events` table + time features + optional weather |
| **Feature engineering** | `day_of_week`, `hour`, `minute_bucket` (15-min bins), `is_weekend`, `minutes_since_last_mode_change`, `previous_mode`, `previous_mode_duration`, `time_since_wake` (first non-away event), `weather_condition` (from cache), `season`, `manual_override_rate_7d` |
| **Model** | LightGBM (`GradientBoostingClassifier`). Trains in seconds on CPU. Model file <1MB. scikit-learn fallback if LightGBM dep is unwanted. |
| **Output** | Multi-class probabilities: gaming, working, watching, relax, social, cooking. Top class + confidence score. |
| **Inference frequency** | Every 60 seconds (piggyback on automation loop). Only consulted when current mode is idle/away (same gate as `check_rules`). |
| **Integration point** | New `BehavioralPredictor` class called from `AutomationEngine.run_loop()`. Shares the same interface as `RuleEngineService.check_rules()`: returns `Optional[dict]` with `predicted_mode` and `confidence`. |
| **Training schedule** | Nightly at 4 AM via `AsyncScheduler`. Scans all activity_events within 60-day rolling window. Training completes in <5 seconds. |
| **Cold start** | First 2 weeks: rule engine runs as-is. Week 2: begin training in shadow mode (predict but don't act, log accuracy). Week 4: if shadow accuracy > rule engine accuracy on held-out 7-day window, promote to primary. Rule engine becomes the fallback. |
| **Minimum data** | 500+ activity events (~1 week of normal use with 60s heartbeats) |
| **Expected accuracy** | 75-85% on mode prediction for active modes (excluding idle/away). Baseline (rule engine): ~60-70%. |
| **Concept drift** | Retrain nightly. If accuracy on last 7 days drops below rule engine baseline for 3 consecutive evaluations, auto-demote and log warning. |

**Feature engineering details:**

```python
# Temporal features (from timestamp)
features = {
    "hour": 20,                        # 0-23
    "minute_bucket": 2,                # 0-3 (15-min bins within hour)
    "day_of_week": 4,                  # 0=Monday, 6=Sunday
    "is_weekend": False,
    "season": "spring",                # Derived from month
    "minutes_since_wake": 900,         # Since first non-away event today
}

# Behavioral features (from recent activity_events)
features.update({
    "previous_mode": "working",        # Categorical
    "previous_mode_duration_min": 120, # How long in previous mode
    "mode_transitions_today": 4,       # Number of transitions so far
    "manual_override_count_7d": 3,     # Overrides in last week
})

# Environmental features (optional, from weather cache)
features.update({
    "weather_condition": "cloudy",     # Categorical
    "temperature_f": 68,
})
```

**Files touched:**
- New `backend/services/ml/behavioral_predictor.py`
- New `backend/services/ml/feature_builder.py` — Shared feature engineering
- `backend/services/automation_engine.py` — Call predictor in `run_loop()`, after time rules, before applying state
- `backend/services/rule_engine_service.py` — Add shadow mode comparison logging

---

### 3.3 Adaptive Lighting Preferences

**Phase:** 1 (Priority 3)

**Problem:** `ACTIVITY_LIGHT_STATES` in `automation_engine.py` contains 
hand-tuned brightness/color values for every (light, mode, time_period) 
combination. When the user manually adjusts a light, that preference is lost on
the next mode change. The `light_adjustments` table captures every manual tweak
but the data is never used to improve future automation.

**Solution:** Learn per-light preferred values from manual adjustment history and
apply them as an overlay on the hardcoded defaults.

| Attribute | Value |
|-----------|-------|
| **Input** | `light_adjustments` table: `bri_after`, `hue_after`, `sat_after`, `ct_after`, `mode_at_time`, timestamp. Only rows where `trigger IN ('ws', 'rest', 'all_lights')` — user-initiated changes only. |
| **Model** | Exponential moving average (EMA) per (light_id, mode, time_period) combination. For each combo with 5+ manual adjustments, compute decay-weighted average of the "after" values (more recent adjustments weighted higher). No ML library needed — pure math. |
| **Output** | Adjusted light state values that overlay `ACTIVITY_LIGHT_STATES`. Example: if the user consistently sets bedroom lamp to bri=180 during working/night (vs hardcoded 150), the learner outputs `{"2": {"bri": 180}}` for that slot. |
| **Inference frequency** | Recalculated daily at 4 AM. Applied on every mode change via the existing `_resolve_activity_state()` path. |
| **Integration point** | New `LightingPreferenceLearner` produces an overlay dict matching the `ACTIVITY_LIGHT_STATES` structure. `AutomationEngine._apply_mode()` checks for learned preferences first, falls back to hardcoded values for any missing slots. **Colorspace safety:** if a mode's hardcoded state uses `ct`, any learner-overlayed `hue`/`sat` is silently dropped at the `hue_service.set_light` layer (CT and HSB are mutually exclusive on the Hue bridge). This was the root cause of the April 2026 "greenish bedroom" bug — a learner that had seen the user set warm amber values during relax was re-applying `hue`/`sat` to working-mode CT commands, and the bridge was merging them into tinted "white". The fix lives in the set_light layer, so learner output never needs to know about colorspace. |
| **Cold start** | Hardcoded `ACTIVITY_LIGHT_STATES` remain the defaults. Learned values only override when 5+ manual changes exist for a given (light, mode, period). |
| **Storage** | `data/models/lighting_prefs.json` — simple JSON dict of learned values |
| **Expected improvement** | Fewer manual corrections over time. Measurable as: manual light adjustments per day trending downward. |

**EMA formula:**

```python
# For each (light_id, mode, time_period) with 5+ adjustments:
alpha = 0.3  # Recent adjustments weighted ~3x more than older ones
for adjustment in sorted_by_timestamp:
    learned_bri = learned_bri * (1 - alpha) + adjustment.bri_after * alpha
```

**Files touched:**
- New `backend/services/ml/lighting_learner.py`
- `backend/services/automation_engine.py` — `_apply_mode()` merges the learner overlay on top of `ACTIVITY_LIGHT_STATES`
- `backend/services/hue_service.py` — `set_light` enforces CT/HSB exclusivity so learner-overlayed hue/sat never contaminates a CT command (prevents the "greenish bedroom" tint)

---

### 3.4 Camera Presence & Posture

**Phase:** 2 (Priority 4)

**Problem:** "Away" detection currently requires 10 minutes of keyboard/mouse
inactivity (Win32 `GetLastInputInfo` in `activity_detector.py`). This is slow
and only works on the Windows dev machine. The Latitude has a built-in camera
that could detect room occupancy instantly.

**Solution:** Use MediaPipe BlazePose for real-time presence and posture
detection from the Latitude's 720p webcam.

| Attribute | Value |
|-----------|-------|
| **Input** | 720p webcam frames from Dell Latitude built-in camera via OpenCV `VideoCapture`. Captured at 640×480 for inference (bumped from 320×240 on 2026-04-19 after observing marginal face-detection gains and better future-feature headroom — requires lux recalibration on any change). |
| **Preprocessing** | Capture one frame every 2 seconds (not continuous video). `cv2.resize()` downsample is a safety no-op when the webcam honors the capture-resolution hint. No image enhancement. |
| **Model** | MediaPipe BlazePose (lite variant, shipped 2026-04-19 as a fallback signal). Runs alongside full-range BlazeFace: face first (~15ms at 640×480), pose as fallback on face-miss (~60ms). Presence declared if either detector hits. |
| **Output classes** | `present_upright`, `present_reclined`, `present_unknown_posture`, `absent` |
| **Inference frequency** | Every 2 seconds (one frame capture + inference). Triggers "absent" after 7 consecutive absent frames (~14 seconds). |
| **Integration point** | New `CameraService` reports to `AutomationEngine.report_activity(source="camera")`. |
| **CPU cost** | 30-50ms per inference every 5 seconds = <2% CPU sustained |
| **RAM** | 50-100MB (MediaPipe + OpenCV) |
| **Cold start** | MediaPipe is pretrained. Works immediately. Posture thresholds may need one-time calibration (30-second "sit normally, then recline" flow in Settings). |

**Posture classification logic:**

```python
# From MediaPipe BlazePose landmarks
shoulder_y = (left_shoulder.y + right_shoulder.y) / 2
hip_y = (left_hip.y + right_hip.y) / 2
torso_angle = abs(shoulder_y - hip_y)  # Normalized 0-1

if torso_angle > UPRIGHT_THRESHOLD:    # ~0.15 (calibrated)
    posture = "present_upright"        # Working, gaming
elif torso_angle > RECLINE_THRESHOLD:  # ~0.08
    posture = "present_reclined"       # Watching, relaxing
else:
    posture = "present_unknown_posture"
```

**Mode disambiguation from posture:**

| Current Detection | + Posture | Refined Mode |
|-------------------|-----------|-------------|
| gaming (process) | upright | gaming (confirmed) |
| watching (process) | reclined | watching (confirmed) |
| idle (no process) | upright at desk | likely working (browser) |
| idle (no process) | reclined | likely watching/relaxing |
| any | absent (3 frames) | away (within 15s, not 10min) |

**Ambient light measurement — adaptive brightness (shipped April 18 2026):**

The same webcam frame used for face detection produces a grayscale-mean
reading that drives a brightness multiplier for `working` and `relax`
modes. Implementation details:

```python
# Per-frame in camera_service.py
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
raw_lux = gray.mean()                          # 0-255 scale
self._ema_lux = α*raw + (1-α)*self._ema_lux    # α = 0.3, 2s polling → ~20s to 95%

# Per-tick in automation_engine.py
effective = ema_lux - baseline_lux + 90        # shift curve by calibrated baseline
multiplier = piecewise_linear(                 # LUX_CURVE anchors:
    effective,                                 #   40  → 1.15 (dark room, lift)
    [(40, 1.15), (90, 1.00), (180, 0.85)]      #   90  → 1.00 (at calibrated baseline)
)                                              #   180 → 0.85 (bright room, dim)
state[light]["bri"] *= multiplier              # per-light, post mode_brightness_config
```

**Calibration:** auto-exposure must be off — otherwise the sensor
compensates and `gray.mean()` becomes a constant. `POST /api/camera/calibrate`
iteratively picks a fixed exposure in `[-12, 0]` whose steady-state
reading lands in `[60, 180]`, then records that reading as `baseline_lux`.
The measurement cadence intentionally mirrors `poll_loop` (sleep, single
frame) so auto-gain control (AGC) reaches its idle state — a prior
burst-mode binary search inflated readings by ~5× because AGC wound up
high during rapid frame reads but settled down between sparse live polls.

**Guardrails:**
- Only `working` and `relax` modes modulate (`LUX_MODES`). Functional
  modes (gaming, watching, cooking, social) stay predictable.
- Mode-scene overrides (`activate_scene` path) bypass the multiplier
  entirely — explicit intent wins over adaptation.
- Manual light overrides (4h timeout) are filtered downstream of the
  multiplier, so hand-set lamps aren't re-modulated.
- Hysteresis: skip re-apply if multiplier change < 3%.
- Stale readings (> 30s old) ignored — protects against paused camera.
- Kitchen-pair rule preserved (multiplier is a scalar, scales both L3/L4
  identically).
- Post-sunset CT cutoff (`ct ≥ 333`) untouched — multiplier only affects
  `bri`, never color.

**Config:** `lux_calibration_config` in `app_settings` —
`{exposure_value, target_lux, baseline_lux, calibrated_at}`. Missing
`baseline_lux` (legacy configs from before Apr 18) falls back to the
default curve center of 90, preserving old behavior until recalibration.

**Privacy (critical):**
- Frames are `numpy.ndarray` objects in the camera thread. Never serialized to
  disk, network, or log. Never exposed via any API or WebSocket endpoint.
- Only derived labels (`present_upright`, `absent`, etc.) and ambient lux values
  are stored in the database.
- Explicit opt-in toggle required in Settings. Camera is disabled by default.
- Dell Latitude hardware camera LED activates when capturing — provides physical
  indicator that cannot be bypassed by software.
- A `CAMERA_ENABLED` env var / app_setting controls the feature. The service
  does not initialize if disabled.

**Files (shipped Phase 2a + Adaptive Lux):**
- `backend/services/camera_service.py` — face detection, calibration, EMA lux, poll loop
- `backend/api/routes/camera.py` — status, enable, calibrate endpoints (no image streaming)
- `backend/services/automation_engine.py` — `_apply_lux_multiplier`, `lux_to_multiplier`, camera activity reports
- `frontend-svelte/src/routes/settings/+page.svelte` — Camera toggle + Calibrate button + live lux/baseline/multiplier readout
- `frontend-svelte/src/lib/stores/camera.js` + `init.js` — camera store, WS handler
- `tests/test_camera_service.py` + `tests/test_lux_multiplier.py` — 55 tests

---

### 3.5 Smart Screen Sync

**Phase:** 2 (Priority 5)

**Problem:** `screen_sync_agent.py` averages all pixels in the center 60% of the
screen. This produces washed-out colors — a game with a bright UI bar and dark
gameplay area averages to muddy brown instead of picking the dominant mood color.

**Solution:** Use K-means clustering to find the dominant aesthetic color rather
than the arithmetic mean.

| Attribute | Value |
|-----------|-------|
| **Input** | Screen capture frames from `mss` (existing pipeline). Already downsampled to ~100x60 pixel grid, center 60% cropped. |
| **Algorithm** | `MiniBatchKMeans(n_clusters=5)` from scikit-learn. Cluster the pixel colors, then select the cluster with highest saturation and reasonable luminance (0.15-0.85 range). Falls back to largest cluster if no saturated cluster found. |
| **Inference frequency** | Every 2.5 seconds (existing `CAPTURE_INTERVAL`) |
| **Integration point** | Replace `capture_dominant_color()` in `screen_sync_agent.py` |
| **CPU cost** | <10ms for MiniBatchKMeans on 6000-pixel grid (negligible increase over current average) |
| **RAM** | <1MB additional |

**Color selection logic:**

```python
from sklearn.cluster import MiniBatchKMeans

kmeans = MiniBatchKMeans(n_clusters=5, batch_size=100)
kmeans.fit(pixels)  # pixels: Nx3 RGB array

# Score each cluster: prefer saturated, reasonably bright colors
best_score = -1
for center in kmeans.cluster_centers_:
    h, s, v = colorsys.rgb_to_hsv(*(center / 255.0))
    if 0.15 < v < 0.85 and s > 0.2:
        score = s * 0.7 + (1.0 - abs(v - 0.5)) * 0.3
        if score > best_score:
            best_score = score
            dominant_color = center

# Fall back to largest cluster if no good candidate
if best_score < 0:
    largest = np.argmax(np.bincount(kmeans.labels_))
    dominant_color = kmeans.cluster_centers_[largest]
```

**Files touched:**
- `backend/services/pc_agent/screen_sync_agent.py` — Replace average-RGB with K-means

---

### 3.6 Music Selection

**Phase:** 2 (Priority 6)

**Problem:** `MusicMapper.pick_playlist()` uses a hardcoded time-of-day vibe
preference to choose between playlists mapped to each mode. It doesn't learn
from the user's actual play/skip behavior.

**Solution:** Multi-armed bandit with Thompson sampling. Each (mode, time_period,
favorite_title) is an "arm." Plays and accepted suggestions are rewards; skips
and dismissed suggestions are penalties. The bandit explores naturally while
exploiting known preferences.

| Attribute | Value |
|-----------|-------|
| **Input** | `sonos_playback_events` (event_type, favorite_title, mode_at_time, triggered_by), `mode_playlists` (mode-to-favorite mappings with vibe tags) |
| **Algorithm** | Thompson sampling with Beta distribution priors. Each arm has parameters (alpha, beta). Reward increments alpha; penalty increments beta. Sample from Beta(alpha, beta) to rank arms. |
| **Inference frequency** | On every mode change that triggers auto-play |
| **Integration point** | Replace `_TIME_VIBE_PREFERENCE` heuristic in `MusicMapper.pick_playlist()` |
| **CPU cost** | <1ms (sampling from Beta distributions) |
| **RAM** | <1KB (Beta parameters per arm) |
| **Cold start** | Start with informative priors from existing vibe preferences: Beta(3,1) for the currently-preferred vibe, Beta(1,1) for others. The bandit explores from there. |
| **Storage** | `data/models/music_bandit.json` — dict of `{(mode, period, title): [alpha, beta]}` |

**Reward/penalty mapping:**

| Event | Effect |
|-------|--------|
| Auto-play → user keeps playing (no skip for 60s+) | alpha += 1 |
| User manually plays this favorite during this mode | alpha += 2 |
| Suggestion accepted | alpha += 1 |
| Auto-play → user skips within 30s | beta += 1 |
| Suggestion dismissed | beta += 0.5 |

**Exploration:** 10% permanent exploration rate (sample uniformly instead of
from Beta) to prevent premature convergence and discover new preferences.

**Files touched:**
- New `backend/services/ml/music_bandit.py`
- `backend/services/music_mapper.py` — Replace vibe heuristic with bandit selection

---

## 4. Data Pipeline

### Training Data Sources

All training data comes from SQLite event tables already being populated by
`EventLogger`. No new data collection is needed for Phase 1.

| Table | Records Per Day | Training Use | Retention |
|-------|-----------------|-------------|-----------|
| `activity_events` | 5-20 (mode transitions) | Behavioral predictor, rule engine | 90 days |
| `light_adjustments` | 10-50 (manual changes) | Lighting preference learner | 90 days |
| `sonos_playback_events` | 10-50 (play/skip/volume) | Music bandit rewards | 90 days |
| `scene_activations` | 2-10 | Scene preference analysis | 90 days |

### Feature Engineering

A shared `FeatureBuilder` class queries SQLite and produces pandas DataFrames:

```python
class FeatureBuilder:
    """Builds feature matrices from event tables for ML training."""

    async def build_mode_features(self, days: int = 60) -> pd.DataFrame:
        """Build features for behavioral predictor training."""
        # Queries activity_events, joins weather cache, computes temporal features
        # Returns DataFrame with columns: hour, day_of_week, is_weekend,
        #   previous_mode, previous_duration, weather, season, etc.
        # Target column: mode

    async def build_lighting_features(self, days: int = 90) -> pd.DataFrame:
        """Build features for lighting preference learning."""
        # Queries light_adjustments where trigger IN ('ws', 'rest', 'all_lights')
        # Returns DataFrame: light_id, mode, time_period, bri_after, ct_after, etc.

    async def build_music_features(self, days: int = 90) -> pd.DataFrame:
        """Build reward/penalty signals for music bandit."""
        # Queries sonos_playback_events with event timing analysis
        # Returns DataFrame: mode, time_period, favorite_title, reward (0 or 1)
```

### Model Versioning

Models are stored in `data/models/` with a metadata file:

```json
// data/models/model_meta.json
{
    "mode_predictor": {
        "version": "2026-04-20T04:00:00",
        "accuracy_7d": 0.82,
        "training_rows": 1847,
        "training_window_days": 60,
        "status": "active"  // or "shadow", "demoted"
    },
    "lighting_prefs": {
        "version": "2026-04-20T04:00:00",
        "lights_with_learned_values": 3,
        "total_adjustments_used": 234,
        "status": "active"
    },
    "audio_classifier": {
        "version": "pretrained-yamnet-v1",
        "status": "active"
    }
}
```

### No External Data

All training data comes from the system itself. The only optional external
augmentation is weather conditions from the cached OpenWeatherMap response
(already fetched every 10 minutes by `WeatherService`).

---

## 5. Model Selection & Rationale

| Feature | Model | Size | Inference (CPU) | Why This Model | Why Not Alternatives |
|---------|-------|------|-----------------|----------------|----------------------|
| Audio classification | YAMNet (TFLite/ONNX) | 50-200MB | 15-30ms | Pretrained on AudioSet (2M+ clips, 521 classes). Covers all needed audio types. No user data needed for cold start. | Whisper: 1.5GB+, 1-2s inference, designed for speech-to-text not classification. Custom CNN: needs labeled training data we don't have. |
| Mode prediction | LightGBM | <1MB | <1ms | Handles tabular data with mixed types (categorical + numeric). Trains in seconds. Natively handles missing features. | Neural nets: overfit on small tabular data (<10K rows). Random forest: works but slower training and larger model. |
| Lighting preferences | EMA (not ML) | <1KB | <1ms | The signal is simple: "user keeps setting this light to X." A weighted average is the mathematically correct estimator for a slowly-drifting preference. | Any ML model is overkill. Linear regression works but EMA adapts to drift naturally. |
| Presence detection | MediaPipe BlazePose | ~30MB | 30-50ms | Google's production on-device pose estimation. Runs on CPU. Pretrained, no user data needed. Outputs 33 body landmarks for posture analysis. | YOLO: 100MB+, heavier, designed for multi-object detection (overkill for single-room). Custom model: needs thousands of labeled images. |
| Screen sync | MiniBatchKMeans | <1MB | <10ms | Finds color clusters in pixel data. Picks the most visually dominant saturated color. Algorithmic, not statistical. | Deep saliency models: 100MB+, need GPU for real-time. Histogram peak detection: simpler but misses multi-modal distributions. |
| Music selection | Thompson sampling | <1KB | <1ms | Natural exploration/exploitation balance for single-user preference learning. Converges quickly with ~20 plays per arm. No training step needed. | Collaborative filtering: impossible (single user). Content-based: needs audio features we don't have. |

### Total Resource Overhead

| Resource | Budget | Breakdown |
|----------|--------|-----------|
| CPU (sustained) | <10% | Audio 5% + Camera 2% + others <1% each |
| RAM (peak) | ~200-400MB | Audio model 50-200MB + MediaPipe 50-100MB + rest <10MB |
| Disk | <250MB | Model files + metadata |

---

## 6. Integration Architecture

### Integration Patterns

ML components integrate with the existing codebase using five patterns that
match the established service conventions:

**Pattern 1: Activity Source**
ML components that detect what the user is doing report to the automation engine
via the existing activity report interface:

```python
# Camera and audio classifier use this pattern
await automation.report_activity(mode="social", source="audio_ml")
await automation.report_activity(mode="away", source="camera")
```

The existing `MODE_PRIORITY` dict arbitrates between sources. Camera "absent"
overrides idle (faster away detection). Audio "social" uses the same priority=4
as the current ambient monitor. Activity reports also feed into `ConfidenceFusion`
as signal inputs (Pattern 5).

**Pattern 2: Prediction Replacement**
The behavioral predictor replaces the rule engine's `check_rules()` with a
richer prediction:

```python
# In AutomationEngine.run_loop(), where check_rules() is called today:
prediction = await ml_predictor.predict_mode(context)
if prediction and prediction["confidence"] >= 0.70:
    # Suggest or auto-apply based on confidence threshold
    ...
elif rule_prediction := await rule_engine.check_rules():
    # Fallback to frequency-based rules
    ...
```

**Pattern 3: Overlay**
The lighting learner produces values that override hardcoded defaults without
replacing the entire system:

```python
# In AutomationEngine._resolve_activity_state():
hardcoded = ACTIVITY_LIGHT_STATES[mode][period]
learned = lighting_learner.get_preferences(mode, period)
# Merge: learned values override hardcoded, missing slots keep defaults
final = {**hardcoded}
for light_id, prefs in learned.items():
    if light_id in final:
        final[light_id] = {**final[light_id], **prefs}
```

**Pattern 4: Callback**
ML services register for mode changes to capture training signals:

```python
# In main.py lifespan:
automation.register_on_mode_change(ml_logger.on_mode_change)
automation.register_on_mode_change(music_bandit.on_mode_change)
```

**Pattern 5: Fusion Signal Reporting**
Signal sources that produce mode predictions with confidence scores report to
the confidence fusion service, which computes a weighted ensemble across all
active signals:

```python
# In AutomationEngine.report_activity() — any activity source:
fusion.report_signal("process", mode, confidence=1.0)
fusion.report_signal("camera", mode, confidence=0.9)
fusion.report_signal("audio_ml", mode, confidence=0.8)

# In AutomationEngine.run_loop() — behavioral predictor:
fusion.report_signal("behavioral", prediction["mode"], prediction["confidence"])

# Rule engine reports matched rules:
fusion.report_signal("rule_engine", rule.predicted_mode, rule.confidence)
```

Each cycle, `fusion.compute_fusion()` returns a `FusionResult` with fused mode,
fused confidence, per-signal breakdown, and action flags (`auto_apply`,
`can_override`). The automation engine acts on high-confidence results and
broadcasts the full result in every pipeline state update so the dashboard can
render signal gauges in real-time.

### WebSocket Events

New event types for ML status and predictions:

| Type | Trigger | Data |
|------|---------|------|
| `ml_prediction` | On prediction (auto-applied or suggested) | `{predicted_mode, confidence, source, factors, applied}` |
| `ml_status` | On model health change | `{model_name, status, last_trained, accuracy}` |
| `ml_decision` | On any mode switch | `{mode, decision_chain, factors}` (see Explainability) |
| `pipeline_state` | On state change (throttled to 1s) | Now includes a `fusion` field with `{fused_mode, fused_confidence, agreement, auto_apply, can_override, signals: {process, camera, audio_ml, behavioral, rule_engine}}` for each active signal |

### Confidence-Gated Actions

Applies to both individual ML predictions and the fused ensemble score:

```
>=98% fused confidence  →  Can override stale process detection
                            (requires 80%+ signal agreement)
>=95% fused confidence  →  Auto-apply mode when idle/away. Log decision.
70-95% confidence       →  Show ModeSuggestionToast with reasoning.
                            User accepts or dismisses. Log outcome.
<70% confidence         →  Silent. Log prediction for shadow evaluation.
                            Fall through to rule engine or time rules.
```

---

## 7. Decision Explainability

Every mode switch — whether from ML, rule engine, time rules, or manual
override — gets a decision log entry explaining why.

### Decision Log Schema

New SQLAlchemy model in `backend/models.py`:

```python
class MLDecision(Base):
    """Records every mode decision with reasoning chain."""

    __tablename__ = "ml_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, index=True)
    predicted_mode = Column(String(50), nullable=False)
    actual_mode = Column(String(50), nullable=True)  # Filled on next transition
    applied = Column(Boolean, nullable=False)         # Was the prediction acted on?
    confidence = Column(Float, nullable=True)
    decision_source = Column(String(30), nullable=False)  # "ml", "rule", "time", "manual", "fusion"
    factors = Column(JSON, nullable=True)             # Reasoning chain
```

### Factors Structure

```json
{
    "factors": [
        {
            "source": "process_detection",
            "signal": "LeagueofLegends.exe detected",
            "weight": 0.95
        },
        {
            "source": "behavioral_model",
            "signal": "Friday 8pm: gaming 82% (47 historical Fridays)",
            "weight": 0.82
        },
        {
            "source": "camera_posture",
            "signal": "present_upright (desk posture)",
            "weight": 0.70
        },
        {
            "source": "audio_classifier",
            "signal": "game_audio detected",
            "weight": 0.75
        }
    ],
    "final_confidence": 0.95,
    "decision": "auto_applied",
    "fallback_used": false
}
```

### Frontend Display

- **Analytics page:** Timeline of decisions with expandable reasoning per entry.
  Each entry shows: timestamp, mode, source, confidence, and a collapsible
  list of contributing factors.
- **ModeSuggestionToast:** Enhanced with a brief reason string:
  "Gaming suggested: League detected + Friday 8pm pattern" (truncated to 
  most significant 2 factors).
- **Settings page:** "Recent Decisions" card showing last 10 decisions with
  accuracy (predicted vs actual).

---

## 8. Privacy & Security

### Camera

| Guarantee | Implementation |
|-----------|---------------|
| Frames never touch disk | `numpy.ndarray` in camera thread, overwritten each cycle |
| Frames never leave process | No API endpoint, no WebSocket stream, no network I/O with frame data |
| Only labels persist | `"present_upright"`, `"absent"`, `ambient_lux=47` stored in DB |
| Explicit opt-in required | `CAMERA_ENABLED` in `app_settings` table, default `false`. Toggle in Settings UI. |
| Physical indicator | Dell Latitude hardware camera LED activates on capture (hardware-enforced) |
| Service gating | `CameraService.__init__()` checks setting; does not open `VideoCapture` if disabled |

### Microphone

| Guarantee | Implementation |
|-----------|---------------|
| No audio recording | Raw PCM chunks overwritten each 1s read cycle (existing behavior) |
| Mel-spectrograms are one-way | Spectrograms cannot be inverted to intelligible audio |
| Only labels persist | `"speech_multiple"`, `"silence"`, etc. with confidence scores in DB |
| Same guarantees as current RMS | Current system already processes mic data in memory; ML adds spectrogram step but same lifecycle |

### Model Data

- Trained models contain aggregate statistical patterns (e.g., "Friday 8pm is
  usually gaming"), not individual data points or PII.
- LightGBM model weights are split thresholds on numerical features — no
  reconstructable personal information.
- Music bandit stores Beta distribution parameters per playlist — no listening
  history in the model itself.

### Data Retention

- Event tables pruned to 90 days (configurable via `app_settings`).
- `ml_decisions` table follows same 90-day retention.
- User can trigger full ML data wipe from Settings page:
  - Deletes all models in `data/models/`
  - Clears `ml_decisions` and `ml_metrics` tables
  - Resets music bandit to uniform priors
  - Resets lighting learner to hardcoded defaults
  - Does NOT delete event tables (those are system data, not ML-specific)

### No Cloud Processing

All inference runs locally on the Latitude 7420. No model weights, training
data, predictions, or telemetry are ever transmitted to external services. The
system operates identically with no internet connection (except weather features
degrade gracefully without NWS API access).

---

## 9. Performance Budget

### Per-Component CPU and RAM

| Component | CPU Budget | RAM Budget | Frequency | Notes |
|-----------|-----------|-----------|-----------|-------|
| Audio classifier | <30ms, ~5% sustained | 50-200MB (model) | Every 2-3s | Runs on Latitude (ambient monitor) |
| Behavioral predictor | <5ms, negligible | <10MB | Every 60s | Piggybacks automation loop |
| Lighting learner | <1ms | <1MB | On mode change | Simple dict lookup |
| Camera service | <80ms, ~2% sustained | 50-100MB (MediaPipe) | Every 5s | Only when enabled |
| Screen sync (K-means) | <10ms | <1MB | Every 2.5s | Runs on Windows dev machine |
| Music bandit | <1ms | <1KB | On mode change | Beta sampling |
| ML logger | <5ms | <1MB | On every decision | Async DB write |
| Feature builder | <2s burst | <50MB | Nightly at 4 AM | Pandas DataFrame ops |
| **Total ML overhead** | **<10% sustained** | **~200-400MB** | | |

### System Total with ML

| Component | RAM Estimate |
|-----------|-------------|
| Ubuntu 24.04 + desktop | ~1-2GB |
| FastAPI backend + services | ~100-200MB |
| Firefox kiosk (full dashboard) | ~400-600MB |
| Pi-hole Docker container | ~100MB |
| ML services (Phase 1 only) | ~100-250MB |
| ML services (Phase 1+2) | ~200-400MB |
| **Total** | **~2-3.5GB of 8-16GB** |

### Latency Targets

| Metric | Current | With ML | Improvement |
|--------|---------|---------|-------------|
| Mode change reaction | ~5s (process poll) | ~5s (no change) | — |
| Away detection | 10 minutes (idle timer) | 15 seconds (camera) | **40x faster** |
| Social detection | 2 minutes (sustained RMS) | 30 seconds (speech classification) | **4x faster** |
| Lighting preference application | 0 (no learning) | <1ms on mode change | New capability |
| Music selection | Instant (heuristic) | Instant (bandit) | Better choices over time |

---

## 10. Cold Start & Bootstrapping

The system must work perfectly on Day 1 with zero training data. ML features
activate gradually as data accumulates.

### Timeline

| Week | Audio Classifier | Behavioral Predictor | Lighting Learner | Camera | Music Bandit |
|------|-----------------|---------------------|------------------|--------|-------------|
| 0 | Shadow mode (pretrained) | Off (collecting data) | Off (<5 adjustments) | Off (opt-in) | Off (uniform priors) |
| 1 | Shadow mode, logging | Collecting events | Collecting adjustments | Opt-in available | Collecting plays/skips |
| 2 | Promote if >90% agreement with RMS | Begin shadow training | Still collecting | Shadow mode | Begin exploring |
| 3 | Active | Shadow predictions logged | Activate (if 5+ per combo) | Active (if opted in) | Active with high exploration |
| 4 | Active | Evaluate vs rule engine | Active | Active | Normal exploration (10%) |
| 5+ | Active | Promote if better than rules | Active, improving | Active | Converging on preferences |

### Bootstrapping Principles

1. **Pretrained models work immediately.** Audio classifier (YAMNet) and camera
   (MediaPipe) ship with pretrained weights. No user data needed.

2. **Learned models need data first.** Behavioral predictor needs 500+ events
   (~1 week). Lighting learner needs 5+ adjustments per combo (~2-3 weeks for
   common combos). Music bandit needs ~20 plays per arm (~2-4 weeks).

3. **Shadow mode validates before promotion.** Every learned model runs in
   shadow mode first (predicting without acting, comparing to ground truth).
   Only promoted when it demonstrably outperforms the baseline.

4. **Graceful degradation.** If an ML model crashes, throws an exception, or
   returns invalid output, the fallback chain catches it and uses the next
   layer (rule engine → time rules → hardcoded defaults). ML failures are
   logged but never block the automation loop.

---

## 11. Training & Retraining

### Schedule

| Model | Schedule | Data Window | Duration | Trigger |
|-------|----------|-------------|----------|---------|
| Audio classifier | Not retrained (pretrained) | N/A | N/A | Optional monthly fine-tune if labeled corrections accumulate |
| Behavioral predictor | Nightly at 4 AM | 60-day rolling | <5 seconds | `AsyncScheduler` task |
| Lighting preferences | Daily at 4 AM | 90-day decay-weighted | <1 second | `AsyncScheduler` task |
| Music bandit | Online (continuous) | All history | N/A | Updated on each play/skip event via callback |
| Camera (MediaPipe) | Not retrained | N/A | N/A | Pretrained weights |

### Concept Drift Detection

User behavior changes over time (new job schedule, seasonal patterns, new
hobbies). The system must detect and adapt.

**Behavioral predictor:**
- After each nightly retrain, evaluate on the most recent 7 days (held out from
  training).
- Compare accuracy to the rule engine's predictions on the same window.
- If ML accuracy < rule engine accuracy for 3 consecutive nights:
  - Auto-demote predictor to shadow mode
  - Log warning: `"Behavioral predictor demoted: accuracy {ml_acc} < baseline {rule_acc}"`
  - Broadcast `ml_status` WebSocket event
  - Rule engine resumes as primary

**Lighting preferences:**
- Track manual adjustment rate per week.
- If adjustments are trending upward (user is correcting ML more), flag for
  review and widen the learning window.

**Music bandit:**
- Natural drift handling via Thompson sampling: recent rewards/penalties shift
  the Beta distribution. Old preferences naturally decay as new data accumulates.
- Permanent 10% exploration rate ensures the bandit doesn't get stuck.

### Training Implementation

All training runs as `AsyncScheduler` tasks using the existing scheduler
pattern (`backend/services/scheduler.py`):

```python
training_task = ScheduledTask(
    name="ml_nightly_training",
    hour=4, minute=0,
    weekdays=[0, 1, 2, 3, 4, 5, 6],  # Every day
    callback=ml_service.retrain_all,
    enabled=True,
)
scheduler.add_task(training_task)
```

Training uses `asyncio.to_thread()` to run synchronous ML library calls
(LightGBM, pandas) without blocking the event loop.

---

## 12. Frontend Integration

### New WebSocket Messages

| Type | Data | Consumer |
|------|------|----------|
| `ml_prediction` | `{predicted_mode, confidence, source, factors, applied}` | `modeSuggestion` store (enhanced) |
| `ml_status` | `{model_name, status, last_trained, accuracy}` | New `mlStatus` store |
| `ml_decision` | `{mode, decision_chain, factors}` | Analytics page |

### Enhanced ModeSuggestionToast

Current toast: "Friday 8pm? Gaming mode? (93% confidence)"

Enhanced toast: "Gaming suggested: League detected + Friday 8pm pattern (93%)"

The toast now includes a brief natural-language summary of the top 2 factors
that contributed to the prediction, built from the `factors` array in the
decision log.

### Settings Page — ML Section

New card in Settings with:
- **Per-feature toggles:** Audio classification (on/off), camera (on/off with
  first-time consent dialog), behavioral prediction (on/off), lighting learning
  (on/off), music learning (on/off)
- **Camera calibration:** "Calibrate Posture" button → 30-second flow: "Sit
  normally... now recline..." to set thresholds
- **Model health:** Per-model status card showing: status (active/shadow/demoted),
  last trained timestamp, accuracy metric, data points used
- **Data wipe:** "Reset ML Data" button with confirmation dialog

### Analytics Page — ML Metrics

New section showing:
- **Decision timeline:** Chronological list of mode decisions with source
  (ML/rules/time/manual) and expandable factors
- **Accuracy chart:** 7-day rolling accuracy of ML predictions vs actual outcomes
  (line chart, ML accuracy vs rule engine baseline)
- **Override analysis:** How often ML predictions were manually overridden
  (percentage over time, trending down = ML improving)
- **Feature importance:** Which factors matter most for mode predictions
  (from LightGBM feature importance, updated nightly)

### Mode Confidence Indicator

Subtle visual indicator on mode cards showing prediction confidence:
- Manual override: solid ring (100%)
- ML auto-applied (95%+): nearly-full ring
- ML suggested: partial ring matching confidence
- Time-based default: no ring (rule-based, no confidence score)

---

## 13. Testing Strategy

### Shadow Mode Testing

Every ML feature runs alongside the existing system for 1-2 weeks before
promotion. During shadow mode:

1. ML makes predictions but doesn't act on them
2. Predictions are logged to `ml_decisions` with `applied=false`
3. Actual outcomes (what mode the user actually used) are captured
4. Shadow accuracy is computed nightly and stored in `ml_metrics`

### Primary Metric

**Manual overrides per day** — tracked via `activity_events` where
`source='manual'`. This is the North Star metric. If ML is working, users
override less.

Establish baseline in Week 0 (before any ML features are active). Track
weekly average. Target: 30% reduction by end of Phase 1.

### Unit Tests

```python
# test_feature_builder.py
async def test_temporal_features():
    """Feature builder produces correct time features."""
    events = [make_event(hour=20, day=4, mode="gaming")]
    features = await builder.build_mode_features(events)
    assert features["hour"].iloc[0] == 20
    assert features["day_of_week"].iloc[0] == 4
    assert features["is_weekend"].iloc[0] is False

# test_behavioral_predictor.py
def test_prediction_output_format():
    """Predictor returns mode + confidence dict."""
    predictor = BehavioralPredictor()
    predictor.load_model("tests/fixtures/test_model.lgb")
    result = predictor.predict(test_features)
    assert "predicted_mode" in result
    assert 0.0 <= result["confidence"] <= 1.0

# test_audio_classifier.py
def test_silence_classification():
    """Silent audio correctly classified."""
    classifier = AudioClassifier()
    spectrogram = make_silent_spectrogram()
    result = classifier.classify(spectrogram)
    assert result["class"] == "silence"
    assert result["confidence"] > 0.8
```

### Integration Tests

```python
async def test_ml_prediction_in_automation_loop():
    """ML prediction flows through automation engine correctly."""
    # 1. Insert synthetic activity_events
    # 2. Trigger model training
    # 3. Set mode to idle
    # 4. Run one automation loop tick
    # 5. Verify ML prediction was generated
    # 6. Verify confidence gate was applied
    # 7. Verify decision was logged to ml_decisions
```

### Regression Tests

After each nightly retrain:
1. Run the new model against a frozen test set (last 30 days, sampled)
2. Compute accuracy and compare to previous model
3. If accuracy drops >5%, log warning (don't auto-demote for single drops)
4. If accuracy drops >5% for 3 consecutive retrains, auto-demote

### A/B Comparison

During shadow mode, log both ML prediction and rule engine prediction for
every time slot. Compare:
- How often ML agrees with rules (baseline alignment)
- How often ML predicts correctly when rules are wrong (ML advantage)
- How often ML predicts wrong when rules are correct (ML regression)

Promotion requires: ML advantage > ML regression over the evaluation window.

---

## 14. Deployment

### Dependencies

**Phase 1 additions to `requirements.txt`:**
```
# ML — Phase 1
onnxruntime>=1.17.0        # Audio classifier inference
lightgbm>=4.0.0            # Behavioral predictor
scipy>=1.12.0              # Mel-spectrogram computation (lighter than librosa)
numpy>=1.26.0              # Array operations (implicit dep of many packages)
pandas>=2.2.0              # Feature engineering DataFrames
```

**Phase 2 additions:**
```
# ML — Phase 2
mediapipe>=0.10.0           # Camera pose estimation
opencv-python-headless>=4.9 # Camera capture (headless = no GUI deps)
scikit-learn>=1.4.0         # MiniBatchKMeans for screen sync
```

### Deployment Workflow

Same `scripts/deploy.sh` workflow. ML models are NOT in git — they persist on
the Latitude in `data/models/`. Code changes deploy via git; models regenerate
on the machine via scheduled training tasks.

```bash
# Standard deploy (code changes)
ssh anthony@192.168.1.210 "cd ~/home-hub && ./scripts/deploy.sh"

# First-time ML setup (downloads pretrained models)
ssh anthony@192.168.1.210 "cd ~/home-hub && python -m backend.services.ml.model_manager --setup"
```

### Startup Sequence

```python
# In main.py lifespan, after existing services:

# ML services (Phase 1)
from backend.services.ml.model_manager import ModelManager
from backend.services.ml.behavioral_predictor import BehavioralPredictor
from backend.services.ml.lighting_learner import LightingPreferenceLearner
from backend.services.ml.ml_logger import MLDecisionLogger

model_manager = ModelManager(data_dir="data/models")
await model_manager.load_all()  # Loads available models, logs warnings for missing

behavioral_predictor = BehavioralPredictor(model_manager)
lighting_learner = LightingPreferenceLearner(model_manager)
ml_logger = MLDecisionLogger(ws_manager)

app.state.model_manager = model_manager
app.state.behavioral_predictor = behavioral_predictor
app.state.lighting_learner = lighting_learner
app.state.ml_logger = ml_logger

# Register callbacks
automation.register_on_mode_change(ml_logger.on_mode_change)

# ML services (Phase 2, conditional)
camera_enabled = await load_setting(db, "camera_enabled")
if camera_enabled:
    from backend.services.ml.camera_service import CameraService
    camera = CameraService(model_manager)
    await camera.start()
    app.state.camera_service = camera
    automation.register_on_mode_change(camera.on_mode_change)

# Add ML training to scheduler
scheduler.add_task(ScheduledTask(
    name="ml_nightly_training",
    hour=4, minute=0,
    callback=model_manager.retrain_all,
    enabled=True,
))
```

### Graceful Degradation

If ML dependencies fail to import (e.g., `onnxruntime` not installed), the
system logs a warning and continues without ML features. The fallback chain
(rule engine → time rules → hardcoded defaults) handles everything.

```python
try:
    from backend.services.ml.behavioral_predictor import BehavioralPredictor
    behavioral_predictor = BehavioralPredictor(model_manager)
except ImportError:
    logger.warning("ML dependencies not installed — behavioral predictor disabled")
    behavioral_predictor = None
```

---

## 15. Phased Rollout

### Phase 1: Lightweight Classifiers (✓ Complete — April 14, 2026)

**Implemented:**
- ✓ `MLDecisionLogger` — logs every mode decision (ML, rule, time, manual) with reasoning chain to `ml_decisions` table. Backfills actual_mode on next transition for accuracy tracking.
- ✓ `BehavioralPredictor` — LightGBM model, starts in shadow mode. Predicts mode from temporal + behavioral features. Auto-apply at 95%+ confidence, suggest at 70-95%, silent below. Needs 500+ activity events to train (collecting now).
- ✓ `LightingPreferenceLearner` — EMA-based (α=0.3) learned per-light preferences from manual adjustments. Overlays on top of hardcoded `ACTIVITY_LIGHT_STATES`. Needs 5+ adjustments per (light, mode, period) combo.
- ✓ `FeatureBuilder` — temporal features (hour, day, season, time period) + behavioral features (mode transitions, wake time) for both training and real-time prediction.
- ✓ `ModelManager` — model persistence to `data/models/`, metadata versioning, nightly retraining at 4 AM via scheduler.
- ✓ Full `/api/learning/` REST API — status, decisions, accuracy, lighting prefs, predictor promote/demote, retrain, reset.
- ✓ `ml_decisions` + `ml_metrics` database tables with indexes.
- ✓ Automation engine integration — lighting learner overlay applied during mode transitions, predictor consulted during idle/away, ML logger registered as mode-change callback.

**Current state (as of 2026-04-18):**
- **Behavioral predictor — BLOCKED**: `lightgbm` is not installed on the Latitude. `main.py:320` logs "lightgbm not installed — behavioral predictor disabled" at startup and the predictor writes zero rows to `ml_decisions`. There's sufficient training data in principle (765 activity events across 8 days, above the 500 threshold) but no inference is happening until `pip install lightgbm` lands on the Latitude. Re-evaluate ~7 days after that change.
- **Lighting learner**: active on production. Overlay applications are now logged to `ml_decisions` with `decision_source="lighting_learner"`.
- **Audio classifier (YAMNet)**: shadow mode on Windows desktop (Blue Yeti mic). 17,922 predictions logged to date. Of the 81 rows with `actual_mode` backfilled, only **2 are correct (2.5%)** — the classifier is predicting "idle" for "silence" almost every cycle and missing mode transitions. The 521→9 → user-mode mapping needs rework before promotion is meaningful. Kept in shadow.
- **Camera presence (MediaPipe)**: active on Latitude webcam with 15s away detection.

**Phase 1 exit criteria:** ~~Audio classifier active,~~ behavioral predictor
outperforming rules (blocked on lightgbm install), lighting learner active for 2+ lights. Manual overrides
down 30% from baseline.

### Phase 2: Computer Vision & Learning (✓ Complete)

**Implemented (April 14, 2026):**
- ✓ **Smart Screen Sync** — K-means color clustering (`MiniBatchKMeans(n_clusters=5)`) replaces naive pixel averaging in `screen_sync_agent.py` and `screen_sync.py`. Scores clusters by saturation (0.7 weight) and luminance balance (0.3 weight) to pick the most visually dominant color. ~50x30 pixel grid, ~80ms per capture at 2.5s intervals. Falls back to averaging if scikit-learn not installed. Screen sync agent added to Windows Task Scheduler for auto-start.
- ✓ **Music Bandit** — Thompson sampling playlist selection (`backend/services/ml/music_bandit.py`). Each (mode, time_period, favorite_title) arm has Beta(α, β) parameters. 10% forced uniform exploration. Cold start: Beta(3,1) for preferred vibes, Beta(1,1) for others. Rewards from play/skip behavior in `sonos_playback_events`. Nightly retrain at 4 AM. API: `GET /api/learning/bandit`, `DELETE /api/learning/bandit/reset`. Integrated into `MusicMapper.pick_playlist()` — falls back to time-of-day heuristic when bandit has no data or only one candidate.
- ✓ **Audio Scene Classification (YAMNet)** — TFLite-based YAMNet classifier (`backend/services/ml/audio_classifier.py`) maps 521 AudioSet classes to 9 Home Hub scene classes (silence, speech_single, speech_multiple, music, tv_dialog, game_audio, doorbell, cooking, mechanical_noise). Runs in shadow mode on the Windows desktop alongside the existing RMS detector, using the Blue Yeti mic via `ambient_monitor.py --classifier --shadow`. Auto-downloads model (~16MB) from Google's audioset GCS bucket. 521→9 class mapping built dynamically from `yamnet_class_map.csv` at load time. Temporal smoothing (10-frame EMA). Sustained-detection gating: `speech_multiple` ≥80% for 30s → social, `silence` ≥70% for 60s → exit social. Shadow logs throttled to class changes or every 30s. API: `POST /api/learning/audio-decision`. Registered as Task Scheduler job on desktop (`pythonw.exe`, auto-start on logon).
- ✓ **Camera Presence Detection (MediaPipe)** — `CameraService` (`backend/services/camera_service.py`) uses MediaPipe Tasks API `FaceDetector` (blaze_face_short_range.tflite, ~230KB) on the Latitude's built-in 720p webcam. Captures one frame every 2s, downsampled to 320×240, runs face detection (~5ms CPU). 7 consecutive absent frames (~14s) triggers `away` mode — 40× faster than 10-minute idle timer. Opt-in via `camera_enabled` in app_settings (toggle in Settings UI). Pauses during sleeping mode (camera LED off). Camera source priority: `away` does not override process-detected gaming/working/watching; `idle` (present) does not downgrade higher-priority modes. API: `GET /api/camera/status`, `POST /api/camera/enable`. WebSocket broadcasts `camera_update` events.
- ✓ **Adaptive Lux Brightness (shipped April 18, 2026)** — Same camera frames feed a per-poll grayscale mean (`ambient_lux`), EMA-smoothed (α=0.3, 2s poll → ~20s to 95% response), that drives a piecewise-linear brightness multiplier for `working` and `relax` modes only. `POST /api/camera/calibrate` picks a fixed exposure in `[-12, 0]` and records steady-state `baseline_lux` (typical value 80–150). The multiplier curve is anchored at the calibrated baseline: `(baseline−50 → 1.15×, baseline → 1.00×, baseline+90 → 0.85×)`, clamped outside. Integrated into `AutomationEngine._apply_lux_multiplier` between `_apply_brightness_multiplier` and `_weather_adjust`, skipping mode-scene-override paths and functional modes. Kitchen-pair and post-sunset CT rules preserved (multiplier is scalar, only affects `bri`). 39 unit tests under `tests/test_lux_multiplier.py`.

**Remaining (Phase 2b, deferred):**
```
Camera posture classification (BlazePose upgrade)
  - Posture feeds mode disambiguation (upright vs reclined)
  - Calibration flow in Settings (30s sit/recline)

Audio classifier promotion from shadow to active
  - After 7+ days of shadow data, compare ML vs RMS accuracy
  - If ML > RMS + 10pp, switch ambient_monitor to --active
```

**Phase 2 exit criteria:** ✓ Camera presence working reliably (opt-in). ✓ Away detection under 30 seconds (achieved 15s). Posture and audio promotion deferred to Phase 2b.

### Phase 3: Autonomous Operation (In Progress — April 2026+)

**Shipped (April 15, 2026):**
- ✓ `ConfidenceFusion` service — 5-signal weighted ensemble (228 LOC)
- ✓ Fusion integrated into automation loop — computes every 60s cycle
- ✓ Auto-apply at 95%+ confidence when idle/away
- ✓ Stale process override at 98%+ confidence with 80%+ signal agreement
- ✓ Live pipeline dashboard — SVG confidence ring, per-signal gauge cards
- ✓ Decision logging with `decision_source="fusion"`

**Shipped (April 18, 2026):**
- ✓ **Accuracy-driven weight learning** — `fusion_weight_tuning` ScheduledTask at 3:30 AM daily. `MLDecisionLogger.compute_accuracy_by_source(days=14)` walks fusion rows with `factors.signal_details`, derives per-source accuracy, hands it to `ConfidenceFusion.update_weights_from_accuracy()`. Manual trigger at `POST /api/learning/retune-weights`. Full `signals` dict now persisted in `MLDecision.factors` so historical decisions carry the per-source vote context.

**Shipped (April 19, 2026):**
- ✓ **Fusion shadow logging** — every 60s tick writes an `applied=False, broadcast=False` row to `ml_decisions` with full `signal_details`. Previously only acting decisions were logged (1 row ever), so weight tuning had nothing to learn from. Shadow rows persist to SQLite but don't broadcast — keeps the pipeline WebSocket quiet.
- ✓ **Windowed `actual_mode` backfill** — `MLDecisionLogger.on_mode_change` tracks `_last_mode` and `_last_transition_at` and bulk-UPDATEs every row in the just-ended session window. Capped at 2h so system-start / overnight gaps can't mislabel. Was single-row before, which left 99%+ of shadow rows without ground truth.
- ✓ **Override-rate metric** — `GET /api/learning/override-rate` returns 7d + 30d rates. An "override" is a `source='manual'` event whose mode differs from the nearest prior `activity_events` row within `window_minutes` (default 5). Cold manual switches (no differing prior event) don't count. Primary Phase 3 autonomy gate metric.
- ✓ **A/B comparison endpoint** — `GET /api/learning/compare` computes fusion vs rule-engine-only vs process-priority accuracy on the same fusion-decision row set (where `actual_mode` is backfilled). All three strategies read from the same `factors.signal_details` rows, so the comparison is apples-to-apples.

**Remaining:**
- Analytics-page dashboard UI (frontend Svelte card) surfacing `/override-rate` and `/compare`
- Threshold tuning based on observed false positive rate once ≥30 days of shadow+backfill data accrues

```
Current:    Shadow logging + backfill now live. By 2026-04-22 cron,
            expect hundreds of fusion rows with actual_mode filled.
            /override-rate and /compare answer immediately.

Next:       Analytics card surfacing override rate + strategy A/B.
            Lower auto-apply threshold if false positives < 1/day.

Target:     Fewer than 2 manual overrides per day, sustained
            over 30 days.
```

**Phase 3 exit criteria:** Fewer than 2 manual overrides per day, sustained
over 30 days.

### Dependencies Between Features

```
Audio Classifier ──────────────────────── (independent, start immediately)
Behavioral Predictor ──────────────────── (needs 1-2 weeks of event data)
Lighting Learner ──────────────────────── (needs manual adjustment history)
Camera Presence ───────────────────────── (independent of Phase 1)
Camera Posture ────── depends on ──────── Camera Presence
Smart Screen Sync ─────────────────────── ✓ SHIPPED (K-means, April 2026)
Music Bandit ──────────────────────────── ✓ SHIPPED (Thompson sampling, April 2026)
Decision Explainability ── depends on ─── Any ML prediction source
Autonomous Operation ──── depends on ──── Behavioral Predictor validated
```

---

## 16. Metrics & Monitoring

### Primary Metric

**Manual overrides per day** — tracked via `activity_events` where
`source='manual'`.

Establish baseline in Week 0. Track as a 7-day rolling average. This is the
single metric that determines whether ML is helping.

### Secondary Metrics

| Metric | Source | Purpose |
|--------|--------|---------|
| Mode prediction accuracy | `ml_decisions` (predicted vs actual) | Model quality |
| Time-to-correct-mode | `activity_events` timestamps | Reaction speed |
| Manual light adjustments/day | `light_adjustments` where trigger='ws'/'rest' | Lighting learner effectiveness |
| Music skip rate after auto-play | `sonos_playback_events` | Music bandit effectiveness |
| Away detection latency | Camera → mode change timestamp delta | Camera value |
| Social detection latency | Audio → mode change timestamp delta | Audio classifier value |

### New Database Tables

```python
class MLMetric(Base):
    """Daily aggregate ML performance metrics."""

    __tablename__ = "ml_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    metric_name = Column(String(50), nullable=False)  # e.g., "manual_overrides"
    value = Column(Float, nullable=False)
    metadata = Column(JSON, nullable=True)  # Additional context
```

### Auto-Demote Mechanism

If ML predictions lead to more manual overrides than the rule engine baseline
for 3 consecutive daily evaluations:

1. Demote the offending model to shadow mode
2. Log warning with details
3. Broadcast `ml_status` WebSocket event (frontend shows alert)
4. Rule engine resumes as primary predictor
5. Continue shadow logging for diagnosis
6. Re-promote only after manual review or if shadow accuracy recovers

### Dashboard Widget

New card on the Analytics page:

```
ML Health
─────────
Audio Classifier:      Active   (pretrained)
Behavioral Predictor:  Active   (82% accuracy, trained 4h ago)
Lighting Learner:      Active   (3 lights learned)
Camera:                Disabled (opt-in in Settings)
Music Bandit:          Active   (exploring 10%)

Overrides this week: 8  (baseline: 14, ↓43%)
```

---

## 17. Hardcoded Thresholds Reference

These are all the hardcoded values across the codebase that ML can learn or
replace dynamically. Each entry includes the current value, file location, and
which ML feature addresses it.

### Activity Detector (`backend/services/pc_agent/activity_detector.py`)

| Threshold | Current Value | Line | ML Feature |
|-----------|--------------|------|------------|
| Poll interval | 5 seconds | 67 | — (keep as-is, good balance) |
| Idle → away | 600 seconds (10 min) | 70 | Camera presence (15s detection) |
| Late night working cutoff | 21:00 (9 PM) | 73 | Behavioral predictor (learns actual patterns) |
| Sleep detection hour | 22:30 (10:30 PM) | 76-77 | Behavioral predictor + camera (posture=reclined + eyes closed) |
| Sleep idle threshold | 900 seconds (15 min) | 78 | Camera presence (asleep posture) |

### Ambient Monitor (`backend/services/pc_agent/ambient_monitor.py`)

| Threshold | Current Value | Line | ML Feature |
|-----------|--------------|------|------------|
| RMS noise threshold | 800 | 46 | Audio classifier (replaces RMS entirely) |
| Sustained noise for social | 120 seconds | 43 | Audio classifier (speech_multiple for 30s) |
| Quiet exit from social | 60 seconds | 44 | Audio classifier (silence for 30s) |
| Calibration formula | floor x 2 | ~214 | Audio classifier (pretrained, no calibration needed) |
| RMS averaging window | 5 seconds | 42 | Audio classifier (2-3s inference window) |

### Automation Engine (`backend/services/automation_engine.py`)

| Threshold | Current Value | Line | ML Feature |
|-----------|--------------|------|------------|
| Mode priority mapping | Fixed 0-5 scale | 92-99 | — (keep, but ML confidence modulates) |
| Time period: day | 8:00-18:00 | 433 | Behavioral predictor (learns actual transitions) |
| Time period: evening | 18:00-21:00 | 435 | Behavioral predictor |
| Time period: night | 21:00-8:00 | 437 | Behavioral predictor |
| Winddown ramp duration | 30 minutes | 111 | Behavioral predictor (learns preferred ramp) |
| Manual override timeout | 4 hours | 519 | Behavioral predictor (learns override duration patterns) |
| Scene drift interval | 30 minutes | 531 | Adaptive (could learn acceptable drift frequency from overrides) |
| Per-light brightness values | Hardcoded per mode/period | 170-296 | Lighting preference learner |
| Mode brightness multipliers | Static per-mode | 526 | Lighting preference learner (per time-of-day too) |
| EMA smoothing alpha | 0.3 | screen_sync.py:53 | Smart screen sync (adaptive alpha) |

### Screen Sync (`backend/services/screen_sync.py`)

| Threshold | Current Value | Line | ML Feature |
|-----------|--------------|------|------------|
| Max brightness: gaming | 200 | 30 | Lighting preference learner |
| Max brightness: watching | 80 | 31 | Lighting preference learner |
| Default max brightness | 80 | 33 | Lighting preference learner |
| Min brightness | 15 | 35 | — (keep as safety floor) |
| Smoothing alpha | 0.3 | 53 | — (could adapt based on content type) |

### Rule Engine (`backend/services/rule_engine_service.py`)

| Threshold | Current Value | Line | ML Feature |
|-----------|--------------|------|------------|
| Minimum confidence | 70% | 38 | Behavioral predictor (replaces entire engine) |
| Minimum samples | 3 | 39 | Behavioral predictor (uses richer features) |
| Generation interval | 6 hours | 29 | Behavioral predictor (retrains nightly) |
| Data window | 30 days | 62 | Behavioral predictor (60-day window) |

---

## Appendix: New Database Tables Summary

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `ml_decisions` | Decision log with reasoning | timestamp, predicted_mode, actual_mode, applied, confidence, decision_source, factors (JSON) |
| `ml_metrics` | Daily aggregate performance | date, metric_name, value, metadata (JSON) |

These tables follow the existing pattern in `backend/models.py` and use the same
`async_session` factory for database access.
