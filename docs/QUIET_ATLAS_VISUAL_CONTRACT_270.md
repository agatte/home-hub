# Quiet Atlas × Daylight — accepted visual direction and first Home slice (#270)

**Status:** The user visually accepted the refined spatial composition on October 31, 2026. This document specifies the accepted visual direction, not evidence of physical phone/kiosk acceptance or deployment.

**Authority:** #270 under Dashboard #157; DASHBOARD_REDESIGN_VISION.md retains Dashboard principles, PROJECT_SPEC.md controls product behavior, and #192 owns actual Apartment geometry/placement/rendering.

## Composition and navigation
- **Home** is a living-apartment editorial stage rather than equal-weight card panels. House State and Activity are separate qualified concepts. Recent context/explanation is a side rail on kiosk and progressive disclosure on mobile.
- **Lighting** is reachable on the first narrow Home screen: Living L1, Bedroom L2/L5, Kitchen L3/L4, Plant L6, and scene/preset library access. Grouping is for navigation only, never permission to issue collective room writes. Real preset names must come from validated source, not the mockup.
- **Apartment** remains a distinct destination with #192 authoritative measured geometry and cinematic view. A Home spatial placeholder is neither measured geometry, sensor evidence nor live 3D.
- **Other route archetypes** share typography/material hierarchy without collapsing into one template: Control for light/scene specifics, Music for listening, Insights for evidence and decisions, Settings for advanced choices, Game Day for sports attention, Guest for visitor tasks.
- **Mobile vs kiosk:** mobile gets compact context and immediate lighting access, not stacked desktop cards. Kiosk gives the spatial stage visual primacy with a contextual side rail. Preserve usable navigation at 320/360/390/507 and 1440/2048 CSS px.

## Visual system
- Quiet Atlas is the dark green-black/night-capable calm foundation; Daylight adds soft warm cream/linen and gold/terracotta accents. Signal's crowded diagnostic chrome is rejected.
- Stage, rail, sheet, readout and status have different jobs. Avoid generic rounded-card grids.
- Motion should explain meaningful causality and have a reduced-motion alternative. Day/night presentation should not claim real time/weather authority without evidence. Test contrast, touch sizes, focus, motion and physical kiosk luminance before release.

## Truth and control
- House States: Away, Home, Winding Down, Sleeping. Activity is distinct; inferred context gets soft copy such as “Likely: Getting Ready”. Detected Activity is not a manual hold; internal idle is not user-facing.
- Never invent presence, scene inventory, bulb power, room location, confidence or automation effects. Label loading/unavailable/stale/empty/degraded/high-attention states explicitly. Stale lights do not change unrelated House State/Activity. Preserve source-qualified lighting snapshot provenance.
- No device writes are authorized by visual approval. Manual, transit, scene, Away/external-off, ScreenSync, protected-light, freshness, transition reconciliation and write ownership remain untouched.

## Source rollout status and limits (November 1, 2026)

The October 31 opt-in Home prototype originally used illustrative states and made no API calls. That description is **historical**; it no longer describes the current committed source.

After [merged PR #445](https://github.com/agatte/home-hub/pull/445) (master `9761301d878ccd716e117b16dde24a50cc153946`):
- `/quiet-atlas/home` remains **opt-in and read-only**, but uses bounded **GET** reads of `/api/automation/status` and `/api/events/activity`. House State, Activity and recent history are qualified as HomeHub-reported or logged, not underlying sensor freshness, person presence, room position or actual lighting ownership.
- Desktop and mobile Home context default to recent qualified HomeHub REST reports or explicitly unavailable/stale/disconnected/unverified states; examples appear only after an explicit review toggle.
- The separately opted-in `/quiet-atlas/control` uses `GET /api/lights` and `GET /api/scenes` for read-only groups and declared scene previews. It **does not** actuate lights or scenes; `QUIET_ATLAS_CONTROL_ACTUATION_PLAN.md` remains proposed, not approved. All lighting owners and write chokepoints are unchanged.
- The Home spatial stage remains a labeled placeholder; real physical geometry and an independent Apartment destination belong to #192. The existing `/` route and Guest/Game Day layouts are not replaced.

The next proposed design-only slice coordinates manually selected Home Day view with the immediate Quiet Atlas shell/nav chrome. It is a manual preview, **not** a persisted preference, automatic time/weather theme, source of room knowledge, or device action; it requires its own reviewed source/test change.

**Remaining gates:** Responsive browser checks, full Linux CI, physical phone/kiosk and after-dark luminance acceptance, and independent commit/push/merge/deploy/device authorizations remain distinct. #270 stays open for broader page-archetype migration.
