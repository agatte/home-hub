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

## First source slice and its limits
The first review implementation is a standalone opt-in, read-only Home composition at frontend-svelte/src/routes/quiet-atlas/home/+page.svelte beneath the existing Quiet Atlas shell. It has **no API calls**, hard-coded live claims, scene activation or faux room geometry. Every sample state is explicitly a design example. Group links lead to the existing read-only /quiet-atlas lighting preview. The Apartment affordance links to existing legacy Home/Apartment tools until #192 has a dedicated real route. This **does not replace** the legacy / or current /quiet-atlas route, and avoids altering shell/navigation under separate draft PR #429.

Next gates: focused frontend tests and browser responsive/keyboard tests; phone/kiosk visual/night luminance and connected-state source review; then bounded shared primitives and further route-family migration. Commit, push, merge, deploy, restart and Hue/device actions remain separate authorization gates.
