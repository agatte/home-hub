# Apartment Canvas production preview

This isolated Vite harness is the visual-development surface for #182. It renders the accepted `GeometrySceneV1` and Camera v2 as a production-intent Apartment Canvas without wiring the renderer into the Home route.

## Current milestone

Static Apartment v1:

- accepted apartment slab/wall/opening geometry;
- accepted Camera v2 + presentation reflection/chirality;
- accepted north cutaway and bedroom visibility treatment;
- accepted measured inspection verticals;
- production-intent wall/floor/balcony/glass materials;
- neutral studio lighting and shadows;
- bedroom carpet plus major furniture/form identity;
- apartment-specific static details such as bedroom lamps, desk objects, and living-room plant silhouettes;
- final static contrast/readability polish for bed, chair, media, kitchen, and secondary service forms;
- bedroom workstation fidelity pass: Burgener L-shaped desk, HomeZeer chair, Samsung monitor, Blue Yeti, and the two real desk lamps are custom static geometry; no physical projection screen is rendered;
- hero presentation: the Camera v2 responsive solver is retained, with its static preview margin tightened from 1.14 to 1.06 so desktop frames use roughly 12.5% more apartment area while retaining all GeometryScene corners;
- no live Hue state, projector image, ambient-world events, causality animation, telemetry, or Home integration yet.

The renderer intentionally imports `../apartment-whitebox/adapter.js` and the generated GeometryScene artifact instead of copying plan-space coordinates.

## Run

From `frontend-svelte`:

```bash
npm run dev:apartment-canvas
```

Open `http://127.0.0.1:4175/`.

Append `?debug=1` to enable orbit controls and a GeometryScene/camera provenance readout. Normal preview mode remains locked to the accepted camera and contains no inspector labels or metadata chrome over the apartment.

Build without serving:

```bash
npm run build:apartment-canvas
```

## Guardrails

- GeometryScene fingerprint must remain `ba9270ddd772aa859dca2e155e14a54c8d1eccb3daeb869e6301780bbdd4cf43`.
- Do not change plan-space XY, openings, Camera v2 policy, accepted presentation reflection, or accepted cutaway selectors to improve styling.
- Neutral studio illumination is presentation-only and must not imply live HomeHub/Hue lighting state.
- Bedroom workstation geometry is neutral and static; it does not represent Hue, projector, lifecycle, or device-control state.
- The presentation fit margin is a bounded compositor choice only. Camera v2's perspective, 45-degree horizontal FOV, viewpoint family, target, responsive aspect behavior, reflection, and all-corner containment remain unchanged.
- Static Apartment v1 is the accepted visible-apartment baseline; subsequent work should add bounded live-state rendering without reopening accepted geometry merely for styling.
