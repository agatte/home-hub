#> **Visual-target update ? 2026-09-01:** #217 owns the premium cinematic Home renderer. This harness is a validation/comparison scaffold and must not be treated as the product aesthetic or quality ceiling.

 Apartment Canvas validation/scaffold preview

> **Authority update — 2026-08-30:** this harness preserves the pre-#192 static-render/projection baseline for visual comparison. GitHub #192 is now authoritative for physical-world size, placement, anchors, provenance, and evidence-backed corrections. The old GeometryScene fingerprint/XY guardrails below apply only to this preserved baseline; they must not veto an accepted #192 physical-model correction.

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

- For the preserved pre-#192 baseline, the GeometryScene fingerprint remains `ba9270ddd772aa859dca2e155e14a54c8d1eccb3daeb869e6301780bbdd4cf43`; an accepted #192 physical-model correction may intentionally regenerate a different fingerprint.
- Do not hand-edit generated plan-space XY/openings to improve styling. Physical corrections belong in the #192 evidence-backed source model; Camera v2, presentation reflection, and cutaway remain presentation concerns where compatible.
- Neutral studio illumination is presentation-only and must not imply live HomeHub/Hue lighting state.
- Static Apartment v1 remains the accepted **visual comparison baseline**; #192 may supersede its physical geometry when stronger evidence is reconciled.
