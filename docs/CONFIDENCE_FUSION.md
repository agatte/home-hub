# Confidence Fusion Deep Dive

> How Home Hub combines multiple detection signals into a single mode decision.
> This document is for reference — it explains what fusion actually does, why it
> exists, and how the math works under the hood.
>
> **Shipped:** April 15, 2026
> **Implementation:** `backend/services/ml/confidence_fusion.py`
> **Last updated:** 2026-04-15

---

## Why This Exists

Before fusion, Home Hub's ML layer was 8 independent specialists, each operating in its own lane with no knowledge of what the others were saying.

The process detector would see `LeagueofLegends.exe` and declare "gaming." The camera might detect an empty room and think "away." The behavioral predictor might predict "working" based on time-of-day patterns. But **none of these signals talked to each other**. Whichever fired first in the decision cascade won, regardless of what the others thought.

The pipeline page showed this as a static flow: activity detection → resolution → output. Two input cards. No sense of signals competing or agreeing.

Fusion changes the fundamental model: instead of a sequential cascade where the first confident signal wins, **all signals vote together with weights**, and an ensemble confidence score emerges from the combination.

---

## The Pre-Fusion ML Layer (8 Specialists, Each In Its Lane)

| Service | Its Job | Did It Act Directly? |
|---------|---------|----------------------|
| Behavioral Predictor (LightGBM) | Predict next mode from time + behavior patterns | Shadow mode only |
| Audio Classifier (YAMNet) | Classify ambient sound (speech, silence, game, doorbell, etc.) | Reported mode via activity |
| Lighting Preference Learner | Learn per-light brightness/color preferences | **Yes** — overlays on light states |
| Music Bandit (Thompson Sampling) | Pick best playlist per mode | **Yes** — used by music_mapper |
| Camera Presence (MediaPipe) | Detect if you're in front of the webcam | Reported mode via activity |
| Rule Engine | Frequency patterns ("Friday 8pm = gaming 85%") | Suggestion only — never auto-applied |
| Smart Screen Sync (K-Means) | Extract dominant screen color | **Yes** — drove bedroom lamp |
| ML Decision Logger | Record every mode decision with reasoning | Pure logging |

Three of them (lighting learner, music bandit, screen sync) were already acting autonomously in their own lanes. The others fed the automation engine as isolated inputs.

---

## The Pre-Fusion Decision Flow

When the automation engine asked "what mode should I be in right now?":

```
1. Manual override active?
   → YES: Use that mode. Done.
   → NO: continue...

2. Is an activity detected via report_activity()?
   (process detection, ambient monitor, camera, audio_ml)
   → YES: That's the mode. Use MODE_PRIORITY to resolve conflicts.
           gaming=5 > social=4 > watching=3 > working=2 > idle=1 > away=0
   → NO (idle/away): continue...

3. Behavioral predictor has a confident prediction?
   → YES at 95%+: auto-apply as manual override
   → YES at 70-95%: show suggestion toast (don't act)
   → NO: continue...

4. Rule engine has a matching time-based pattern?
   → YES: show suggestion toast (never auto-apply)
   → NO: continue...

5. Fall through to time-based schedule (morning ramp, evening, etc.)
```

The signals never talked to each other. Each layer ran sequentially, and if one didn't produce a result, the next got its turn. There was no ensemble.

---

## What Fusion Adds

Fusion takes the independent signals and makes them **vote together**:

**Before:** 5 separate specialists, each running in their own lane. Decisions cascaded — behavioral predictor first, then rules, then time. Only the first one to produce a high-confidence result mattered.

**After:** All 5 signals report their current best guess + confidence into a shared pool. The fusion service weights them, groups votes by mode, computes an ensemble confidence score, and asks "do enough signals agree?"

**New capability:** Fusion can **override stale process detection**. If you close a game but the client is still running, pre-fusion the system would keep saying "gaming" forever. Now, if camera says absent + audio says silence + WiFi says phone gone, fusion can hit 98%+ confidence and override the stale process state.

**The key conceptual shift:**

- Old ML: "Does any one signal know what's happening?" (OR gate, sequential)
- Fusion: "Do multiple signals agree on what's happening?" (weighted consensus, parallel)

---

## How the Math Actually Works

### Starting Weights (Static Defaults)

Every signal has a weight representing "how much I trust this signal's opinion":

| Signal | Weight | Why |
|--------|--------|-----|
| Process detection | **0.35** | Most reliable — if `LeagueofLegends.exe` is running, you're gaming |
| Camera presence | 0.20 | Good but can be fooled by sitting still outside frame |
| Behavioral predictor | 0.20 | Useful but new, needs training data |
| Audio classifier | 0.15 | Still in shadow mode, less trusted |
| Rule engine | 0.10 | Simple frequency patterns, lowest trust |

These sum to exactly 1.0. That matters for the math later.

### Step 1: Filter Stale Signals

Each signal has a timestamp from when it last reported. If a signal hasn't reported in 5 minutes (`STALE_SIGNAL_SECONDS = 300`), it gets marked stale and is excluded from the vote entirely.

**Example:** You're at your desk. Process reports "working" (just now), camera reports "present" (2s ago), behavioral predicted "working" (1min ago), audio reports "silence" (30s ago). Rule engine hasn't run in 6 hours — **stale, excluded.**

- Active signals: 4 (process, camera, audio, behavioral)
- Stale: 1 (rule_engine)

### Step 2: Redistribute Stale Weights

Rule engine contributed 0.10 to the total weight. When it goes stale, you can't just ignore it — then the remaining weights only sum to 0.90, and your fused confidence would cap at 90%.

So we normalize. Each active signal's weight becomes `weight / sum_of_active_weights`:

```
Active sum = 0.35 + 0.20 + 0.20 + 0.15 = 0.90

process:    0.35 / 0.90 = 0.389   (bumped up from 0.35)
camera:     0.20 / 0.90 = 0.222   (bumped up from 0.20)
behavioral: 0.20 / 0.90 = 0.222   (bumped up from 0.20)
audio:      0.15 / 0.90 = 0.167   (bumped up from 0.15)
────────────────────────────────
Total:                    1.000
```

The stale signal's weight (0.10) gets spread across the active ones proportionally. Normalized weights sum to 1.0 again.

### Step 3: Score Each Mode

For every active signal, multiply its normalized weight × its confidence. Group by what mode it's voting for.

**Example:** Process says "working" at 100% confidence. Camera says "idle" at 92%. Behavioral says "working" at 82%. Audio says "working" at 78%.

```
working votes:
  process:    0.389 × 1.00 = 0.389
  behavioral: 0.222 × 0.82 = 0.182
  audio:      0.167 × 0.78 = 0.130
  ─────────────────────────
  working total:              0.701

idle votes:
  camera:     0.222 × 0.92 = 0.204
  ─────────────────────────
  idle total:                 0.204
```

### Step 4: Pick Winner + Compute Final Score

- **Fused mode** = whichever mode has the highest total. In this case: **working** at 0.701
- **Fused confidence** = the winner's total. In this case: **70.1%**
- **Agreement** = (signals voting for winner) / (total active signals). In this case: 3/4 = **75%**

The 70.1% confidence is below the 95% auto-apply threshold, so fusion won't act. The UI would show "working 70% · 3/5 agree" and the existing priority system continues handling the decision.

---

## Action Thresholds

Fusion only acts when specific conditions are met:

| Threshold | Meaning | Requires |
|-----------|---------|----------|
| `auto_apply = True` | Fused confidence ≥ 95% | Just a high score |
| `can_override = True` | Fused confidence ≥ 98% **AND** agreement ≥ 80% | Near-unanimous signal agreement |

The difference matters:

- **`auto_apply`** is used when you're idle/away and fusion is confident enough to set a mode. This is the normal "I think you're about to game, let me set the lights" case.

- **`can_override`** is the dramatic one — it can override an **active** process detection. This is the "you left a game running but everything else says you left the apartment" case. Because it's overriding what the PC is actively reporting, the bar is much higher.

---

## Why Process Detection Matters Most

Notice process detection has weight 0.35 — almost twice any other signal. That's because process detection is **binary and reliable**. If your PC agent sees `LeagueofLegends.exe`, you are objectively gaming. There's no interpretation.

Everything else is probabilistic:

- **Camera** can see empty frames (you leaned out) or confuse a plant for a face
- **Audio** can be fooled by TV, music from another room, or open windows
- **Behavioral predictor** is pattern-matching from history, doesn't know *today*
- **Rule engine** is just "usually at this time, you're gaming"

So process detection's high weight is saying "trust the hard evidence first."

---

## Worked Examples

### Example 1: All Signals Strongly Agree (Ideal Case)

You're working at your desk on a Tuesday afternoon:

- Process: "working" at 100%
- Camera: "idle" (present) at 92% — but this reports as "idle" not "working" so **disagrees**
- Audio: "keyboard/typing" mapped to "working" at 78%
- Behavioral: "working" at 82%
- Rules: "working" at 71%

```
working votes:
  process:    0.35 × 1.00 = 0.350
  behavioral: 0.20 × 0.82 = 0.164
  audio:      0.15 × 0.78 = 0.117
  rules:      0.10 × 0.71 = 0.071
  working total:              0.702  (70.2%)

idle votes:
  camera:     0.20 × 0.92 = 0.184
  idle total:                 0.184  (18.4%)
```

**Result:** working at 70% · 4 of 5 signals agree. **Below auto-apply threshold** — fusion doesn't act. Process detection's priority-based decision stands.

### Example 2: Stale Process Override (The Dramatic Case)

You finish a gaming session, close the game but leave the launcher open, and go to bed:

- Process: "gaming" at 100% **(but stale — PC agent reported 10 minutes ago before the game closed)**
- Camera: "away" (no face) at 95%
- Audio: "silence" at 90%
- Behavioral: "sleeping" at 88%
- Rules: "sleeping" at 82%

With process stale and excluded:

```
Active weight sum = 0.20 + 0.15 + 0.20 + 0.10 = 0.65

Normalized:
  camera:     0.20 / 0.65 = 0.308
  audio:      0.15 / 0.65 = 0.231
  behavioral: 0.20 / 0.65 = 0.308
  rules:      0.10 / 0.65 = 0.154

Votes:
  away:     0.308 × 0.95 = 0.293   (camera only)
  silence:  0.231 × 0.90 = 0.208   (audio only)
  sleeping: 0.308 × 0.88 + 0.154 × 0.82 = 0.271 + 0.126 = 0.397
```

Wait — 3 different modes from 4 signals. No consensus. Let's say camera actually maps to "away" and audio "silence" also suggests "away" or "sleeping" depending on thresholds. The point is **without process detection dominating**, the remaining signals get to speak.

### Example 3: Can_override Triggering

You're gaming, PC agent reports "gaming" (active, not stale), but you've walked away:

- Process: "gaming" at 100% (still active)
- Camera: "away" at 95%
- Audio: "silence" at 92%
- Behavioral: "away" at 90%
- Rules: "away" at 80%

```
gaming votes:
  process: 0.35 × 1.00 = 0.350

away votes:
  camera:     0.20 × 0.95 = 0.190
  audio:      0.15 × 0.92 = 0.138
  behavioral: 0.20 × 0.90 = 0.180
  rules:      0.10 × 0.80 = 0.080
  away total:                0.588
```

Wait — "gaming" wins at 0.350 vs "away" at 0.588? No, **away wins at 0.588**. Process's single vote isn't enough.

- **Fused mode:** away (0.588)
- **Agreement:** 4/5 = 80% ← meets override threshold
- **Fused confidence:** 0.588 = 58.8%

That's below 98% `can_override` threshold, so fusion doesn't override. The system continues saying "gaming" because of the MODE_PRIORITY hierarchy. This shows why `can_override` requires near-unanimous high-confidence agreement — you don't want single noisy signal to override the hard evidence.

For `can_override` to actually trigger, you'd need something like:

- Camera: "away" at 99%
- Audio: "silence" at 98%
- Behavioral: "away" at 98%
- Rules: "away" at 95%

Now away total ≈ 0.19 × 4 ≈ ~0.76 which is still not 98%. **The 98% override threshold is extremely conservative by design** — it's meant for cases where basically every other signal is screaming in unison.

---

## Accuracy-Driven Weight Learning (Shipped)

The static weights above are the starting point. Accuracy-driven tuning runs nightly at **3:30 AM** (30 min before `ml_nightly_training` at 4:00 AM — the gap ensures yesterday's fusion decisions are weighted before the models that produce today's decisions get retrained).

**How it works:**

1. Every fusion auto-apply or override writes an `ml_decisions` row with `decision_source="fusion"`. The automation engine stamps `factors.signal_details` with a per-source dict (each source's voted mode + confidence + stale flag) at log time.
2. `MLDecisionLogger.compute_accuracy_by_source(days=14)` walks those rows where `actual_mode` has been backfilled, and for each non-stale signal source, computes `correct / total` (correct = the source's vote matched the eventual `actual_mode`).
3. `ConfidenceFusion.update_weights_from_accuracy()` normalizes those accuracies so the active weights sum to 1.0. Sources with zero usable samples in the window fall back to `DEFAULT_WEIGHTS`.
4. The `fusion_weight_tuning` ScheduledTask wires steps 2–3 into the 30-second scheduler loop. `POST /api/learning/retune-weights` is the manual-trigger equivalent — returns `weights_before` + `weights_after` + the derived `accuracy_by_source` so you can validate without waiting for the cron.

Example after 14 days of observation:

```
process:     95% accurate  →  raw weight 0.95
camera:      80% accurate  →  raw weight 0.80
behavioral:  70% accurate  →  raw weight 0.70   (lower — it's new)
audio:       60% accurate  →  raw weight 0.60   (often wrong about ambient)
rules:       75% accurate  →  raw weight 0.75

sum = 3.80

New normalized weights:
  process:    0.95 / 3.80 = 0.250
  camera:     0.80 / 3.80 = 0.211
  behavioral: 0.70 / 3.80 = 0.184
  audio:      0.60 / 3.80 = 0.158
  rules:      0.75 / 3.80 = 0.197
```

Notice process detection's weight drops from 0.35 → 0.25 because accuracy-weighted math treats all signals more equally. Signals that consistently predict the right mode earn more trust. Signals that fire on stale or bad data lose trust.

**Rollout note:** Meaningful weight updates only begin once enough fusion decisions with the expanded `signal_details` factor have accumulated *and* enough of them have `actual_mode` backfilled (which happens on the next mode transition). Expect weights to keep falling back to defaults for the first few days after the factor-payload change ships, then start drifting as data builds.

---

## What You'd See On the Pipeline Dashboard

Every pipeline state broadcast includes the full fusion result. The frontend renders:

- **SVG confidence ring** at the top — arc length = fused confidence, color transitions from gray (<70%) → amber (70-90%) → green (90-95%) → bright green with pulse (95%+)
- **5 signal cards** showing each source's mode, confidence bar, weight, and agreement indicator
- Cards dim to 30% opacity and show "STALE" when a signal expires
- Cards show "No data" when a signal has never reported
- Winner highlight on the highest-weighted agreeing signal

The whole thing updates in real-time via the existing `pipeline_state` WebSocket message (throttled to 1s). No polling.

---

## Why This Matters

Fusion is the piece that makes Home Hub's ML actually *feel* intelligent. Before, each specialist knew part of the story. Now the system has a shared view of what's happening and can catch cases no individual signal could catch on its own — like realizing you've left even when a game process is still running.

It's also the foundation for Phase 3 full autonomy. With accuracy-driven weight learning shipped, the remaining gate is: override rate sustained below 2/day for 30 days → the system has earned the right to run on autopilot. Rate is tracked at `GET /api/learning/override-rate` (7d + 30d windows). A/B accuracy of fusion vs rule-engine vs process-priority on the same backfilled row set lives at `GET /api/learning/compare`.
