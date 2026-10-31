# Lighting comfort shadow diagnostic — October 31, 2026

**Status: isolated, uncommitted, not deployed, no actuator caller.** Primary issue #244; dependencies #136/#370/#243/#131/#130. This is technical evidence triage, not a new lighting mode, policy, autonomous brightness floor, or comfort measurement.

## Purpose and evidence

The user reports evening/night darkness across the apartment and rejects the burden of manually testing every Activity, scene, and period. A dated October 23 read-only live observation found Home, process-detected Watching, active Desktop ScreenSync, Night; L1=76, L2=30, kitchen off, L5=18 and L6=20. Physical Desk was not positively established at that snapshot. Neither the values nor camera data measure subjective comfort.

## First available capabilities

1. Offline mode/period table screening: run `python scripts/lighting_comfort_shadow.py --matrix`. Canonical General, Working, Watching, Gaming, Relax, Social, Cooking x day/evening/night/late-night (28 contexts). Thresholds L1=65 and L2=75 Hue units screen for review, not targets or safe measured lux levels. Social is a flat palette. This is NOT final-dispatch simulation.
2. Operator-supplied offline snapshot: run `python scripts/lighting_comfort_shadow.py --snapshot local.json`. Expected JSON keys correspond to existing GETs: automation_status, automation_pipeline, screen_sync_status, camera_status, bedroom_lux and lights. Output includes only whitelisted mode/period/house/activity context, source readiness booleans, reported stronger ownership, on/brightness, coarse relative camera-proxy bucket, and reason codes. Unexpected source fields (names, titles, face data) are dropped.
3. Optional, explicitly operator-invoked ONE-SHOT read-only collection: `python scripts/lighting_comfort_shadow.py --base-url http://192.168.86.210:8000` when the LAN IP and read route are approved. Six fixed GET paths: /api/automation/status, /api/automation/pipeline, /api/automation/screen-sync/status, /api/camera/status, /api/camera/desktop/lux, /api/lights. Numeric private HTTP LAN IP, 3s timeout, response-size limit, proxies disabled, no redirects, credentials, POST/PUT, retries, daemon, database or disk persistence. No live GET occurs by default; failures report source/error type without leaking URLs or response contents.

The analyzer maps the internal detector term *idle* to the user-facing *General* lighting fallback without inferring Away. It compares actual fixture readings to **uncomposed** authored mode brightness. It flags low authored values and below-static actual values for technical review only. A proposed human-review record may appear only for an already-on L2, Home, positively fresh physically qualified Desktop Desk, without known stronger manual/scene/DND/ScreenSync owner. Unknown manual Activity ownership, disabled/unknown automation, other missing ownership, off/manual/scene/ScreenSync and non-Home states prevent review proposals. ScreenSync low-output technical findings are emitted only after dark. This does NOT authorize a brightness increase. Even the source gate is diagnostic; actual final write leases and source identity require independent checks.

## Limitations and non-negotiable guards

- Hue brightness and camera gray-frame EMA/baseline are NOT measured eye-level illuminance or subjective comfort; proxy buckets may be stale or cross-room.
- Mode table is not final actual dispatch. Weather, learner, manual settings, configured scenes, Gaming Director, ScreenSync, DND, effect ownership, transition logic and per-light final accepted writes can override it.
- ScreenSync status does not guarantee the exact frame, age, lease or bridge ACK. Reported source readings are not device-authenticated here.
- Do not auto-relight off lights, assert presence from process-only Watching, affect projector/Couch, Bed/Winding Down/Sleeping, manual scenes or DND, or violate L5 glare ceiling, transit/protected ownership and kitchen L3/L4 pairing.
- No new runtime route, service, periodic surveillance, private camera/screen capture, background monitor, persistent history, new UI or autonomous retune was added.

## Next gates

1. Independently review source qualification/privacy and real final owner attribution before an opt-in, bounded, retention-governed sampling pipeline. Prefer existing EventLogger enrichment, not a shadow database.
2. Run deterministic replay against actual static and ScreenSync final dispatch, weather/learner, Activity changes, manual/scene/DND/Away/bed/couch transitions and all L1-L6.
3. Add optional concise user feedback (Too dark / Comfortable / Too bright) with frozen *preceding* context. Reuse #131 per-action learning rather than infer a global preference from one correction.
4. Compare with physical evening/night L2/L5/L1/L6 and projector usage; confirm visually and with user feedback. Then separate independent review, CI, commit/push/merge, deployment, and any live device write authorizations.

## Verification

Run tests/test_lighting_comfort_shadow.py and affected existing tests plus Ruff, git diff --check. No offline result counts as real-room comfort acceptance.
