# Context-to-Lighting Ownership Audit — August 28, 2026

Status: immediate regressions implemented on `audit/context-lighting-regressions`;
Plant Wash and bed-context actuation deliberately deferred pending calibration.

## Scope and authority contract

This audit follows the current product contract:

- physical room evidence outranks software activity guesses;
- accepted device-qualified media evidence selects the matching ScreenSync
  source;
- manual per-light ownership remains above autonomous writers;
- Relax and Watching are static modes unless a user explicitly requests a Hue
  effect;
- L6 is an architectural wash, not a generic full-amplitude RGB lamp;
- bed is a physical-context brightness overlay, not an activity mode or a
  sleep inference.

## Immediate root causes and corrections

### Watching dynamic-writer conflict

`EFFECT_AUTO_MAP` still selected Hue `glisten` for Watching in evening/night.
At the same time, `/api/automation/screen-color` was writing sampled HSB state.
Both writers therefore owned the same lamps during one semantic mode.

Correction: Watching now resolves to no automatic Hue effect in every period,
including weather effects. Explicit `/api/scenes/effects/{effect}` commands are
unchanged and remain available.

### Latitude activity request latency

The `/activity` route awaited `laptop_loopback.start()` after accepting a
Latitude Watching report. `LaptopLoopbackCapture.start()` currently only sets
state and creates its capture task, so it is not itself the expensive capture
operation. The same request did, however, also wait for the automation engine's
Watching light/effect transition; the former glisten release/start sequence
included transition settling and a stop/start guard and could consume the
detector client's five-second timeout budget.

Correction: automatic loopback start is now scheduled as a tracked background
task and duplicate starts are suppressed. Its ownership proof is the accepted,
fresh `process:latitude` Watching context returned by the engine, not the raw
Latitude playback packet or synthetic `latitude_streaming` presence. Failure
clears the auto-start owner and is logged. The mode decision remains synchronous
so `/activity` continues to return the engine's truthful semantic disposition.
Removing automatic glisten also removes the observed expensive dynamic-effect
transition from the first Watching report. Losing accepted Latitude ownership
cancels an in-flight start and stops only a loopback this automatic path started.

Laptop frames are additionally rejected during desktop Gaming/Rust before the
generic or Rust luma paths run. This prevents a rejected Latitude packet from
turning the tracked background capture into a second dynamic writer for a
desktop game.

### Wrong ScreenSync source during Watching

The route gated only on the global mode, then selected targets from the
untrusted `report.source`. Consequently a desktop frame arriving during
Latitude-owned Watching could write L2/L5 while laptop loopback simultaneously
wrote L1/L3/L4.

Correction: Watching now resolves one source owner from accepted, fresh,
device-qualified activity context:

- `process:latitude` Watching → `laptop` frames → L1/L3/L4;
- `process:desktop` Watching → `desktop` frames → L2/L5;
- an explicit/manual Watching mode may fall back to fresh source-qualified
  physical desk/couch evidence;
- no trustworthy owner → abstain;
- a non-owner frame is accepted at the HTTP layer but produces no Hue write.

Desktop Gaming and Rust retain their existing dispatch and profile behavior;
only laptop frames are rejected outside Latitude-owned Watching. Per-light
manual overrides and other existing light owners are still checked after
source authority and before every ScreenSync write.

`GET /api/automation/screen-sync/status` now exposes the authoritative source,
reason, target set, and whether the last accepted source matches current
authority.

## Deferred proposal: Plant Wash (L6)

### Existing physical/calibration facts to preserve

- L6 is horizontal on the rear/taller plant stand, aimed upward with a slight
  left bias toward the couch and plant mass.
- Couch, kitchen/island, and entry glare checks passed; partial housing
  visibility is accepted.
- Teal/blue-violet at about 70–75 percent is an accepted architectural
  reference. Saturated deep blue is too dominant for ordinary use.
- Amber/burgundy is accepted after dark, and L1 remains the warm anchor.
- Current Watching static baselines are `bri=65` by day, `35` in evening, and
  `20` at night.

### Proposed ownership

L6 should participate only as a subordinate layer when all of these are true:

1. effective mode is Watching;
2. ScreenSync authority is `laptop`/Latitude;
3. L6 has no fresh manual owner and no higher-priority scene/transit/away owner;
4. a calibrated L6-specific period envelope exists.

Desktop Watching, generic Gaming, Rust, and an authority abstention must not
route sampled color to L6.

### Explicit envelope contract (values require room calibration)

Add a dedicated configuration rather than letting L6 fall through
`DEFAULT_MAX_BRIGHTNESS`:

```text
PLANT_WASH_WATCHING_ENVELOPE = {
  day:        static_only,
  evening:    {floor: current_static_evening, cap: calibrated_evening_cap},
  night:      {floor: current_static_night,   cap: calibrated_night_cap},
  late_night: {floor: calibrated_late_floor,  cap: calibrated_late_cap},
}
```

Required invariants:

- every enabled period has both an explicit floor and cap;
- `floor <= cap`, and missing/invalid calibration means static-only;
- night cap does not exceed evening cap; late-night cap does not exceed night;
- no period may fall back to the generic `80` cap or full Hue amplitude;
- the accepted 70–75 percent architectural reference is a calibration bound
  to test, not an automatic runtime value;
- use a slower L6 EMA/transition than L1/L3/L4 so it reads as a stable wall
  wash rather than a fourth screen pixel;
- reduce chroma excursions that land in the rejected dominant-deep-blue look;
- when frames stop or authority changes, return L6 to its calculated static
  Watching state through the normal transition boundary.

### Calibration pass before implementation

Run a read-only/video-observation plus explicitly authorized light-preview pass
at evening, night, and late-night. For each period, compare the current static
floor, several bounded lift points, bright/cool content, dark/warm content,
seated couch glare, entry view, kitchen view, plant readability, and projector
competition. Record the accepted numeric floor/cap and transition speed in the
L6 calibration document, then add L6 to the ScreenSync capability inventory
and route target atomically with the dedicated envelope and tests.

## Deferred proposal: trustworthy desktop-derived bed context

### Geometry available today

`emotion_capture.py` already has the inputs needed for a calibration study:

- the full local FaceLandmarker result (normalized face landmarks are produced
  but currently not consumed);
- normalized pose landmarks for nose, shoulders, and hips with visibility;
- derived head-drop and head-above-shoulders ratios;
- frame dimensions and explicit, opt-in diagnostic snapshots;
- face confidence, posture candidate/confidence, and capture timestamp.

Today the agent discards landmark geometry after posture classification and
sets `zone="desk"` on every positive desktop face. The backend schema accepts
`zone="bed"`, but no current producer earns that assertion. In addition,
`PresenceFusion._is_at_desk()` and `_desktop_at_desk_fresh()` treat any positive
desktop face as desk presence, so merely changing the posted zone would not be
enough.

### Smallest evidence-gated route

1. Add optional, privacy-preserving geometry telemetry to the desktop
   observation: normalized face box center/size, pose box/anchor coordinates,
   required landmark visibilities, and the existing derived posture ratios.
   Do not persist raw frames during ordinary operation.
2. Add an explicit calibration workflow that records user-labelled `desk`,
   `bed`, and `empty/other` samples across representative lighting, posture,
   occlusion, and distance conditions. Existing opt-in snapshots can support
   review, but labels and extracted geometry—not images—should be the durable
   training evidence.
3. Fit or derive a per-install calibrated decision boundary from those samples.
   Run it shadow-only as `zone_candidate`, with model/calibration version,
   confidence, freshness, and reason fields. Do not emit `zone="bed"` yet.
4. Measure false-bed assertions, missed bed sessions, desk/bed conflicts,
   coverage, and stability across sustained windows. Promotion requires a
   separately accepted evidence threshold and dwell/hysteresis values derived
   from the collected data—not a fixed geometry constant invented in code.
5. On promotion, emit mutually exclusive `zone="desk"` or `zone="bed"` from
   the calibrated classifier and update PresenceFusion so desktop desk
   authority requires `zone == "desk"`; a positive desktop face remains strong
   presence but no longer automatically means desk.

The classifier establishes room geometry only. It must not infer Sleeping,
Watching, Working, or intent from bed location.

## Deferred proposal: bed brightness overlay

Implement a `BedBrightnessOverlay` only after the calibrated bed candidate is
promoted. It should be the final autonomous brightness composition step for
both static mode states and ScreenSync envelopes.

Contract:

- active only for fresh, promoted, source-qualified `zone=bed` evidence during
  evening/night/late-night;
- cap-only: never turn on an off light, never raise brightness, and never alter
  hue/CT/saturation;
- applies across semantic modes, including Watching, Working, Gaming, Relax,
  Cooking, and General; Sleeping keeps its own lifecycle;
- covers L1, L2, L5, paired kitchen L3/L4, and L6 with per-fixture calibrated
  ceilings;
- L3/L4 use the same ceiling and retain any required path/task minimum;
- L6 uses its own architectural-wash ceiling and never inherits a generic lamp
  cap;
- ScreenSync clamps its dynamic cap to the same bed ceiling, so a later frame
  cannot bypass the static overlay;
- fresh manual per-light ownership wins and is never rewritten by entry,
  refresh, or release of the overlay;
- stale/ambiguous/conflicting evidence abstains and exposes the reason.

Represent the calibration explicitly:

```text
BED_BRIGHTNESS_CEILINGS[period][light_id]
BED_PATH_MINIMA[period][light_id]  # only where a safety/path floor is required
```

No default numeric ceiling should exist. An absent light/period calibration is
an abstention for that light. Calibrate the kitchen pair and L6 in the real
room before enabling them, because their functional/architectural roles differ
from the bedside fixtures.

## Recommended next implementation slices

1. Plant Wash calibration and L6-specific envelope, then focused fake-Hue and
   real-room verification.
2. Desktop geometry telemetry plus labelled calibration capture, shadow-only.
3. Bed classifier evaluation and explicit promotion decision.
4. BedBrightnessOverlay with static-state and ScreenSync integration, manual
   ownership regressions, paired-kitchen tests, and L6 calibration tests.

These slices should remain separate from the immediate Watching/source fixes
so the regression correction can be reviewed and deployed independently.
