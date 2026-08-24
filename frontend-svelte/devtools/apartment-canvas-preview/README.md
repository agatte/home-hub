# Apartment Canvas production preview

This isolated Vite harness is the visual-development surface for #182. It renders the accepted `GeometrySceneV1` and Camera v2 as a production-intent Apartment Canvas without wiring the renderer into the Home route.

## Current milestone

Architectural shell only:

- accepted apartment slab/wall/opening geometry;
- accepted Camera v2 + presentation reflection/chirality;
- accepted north cutaway and bedroom visibility treatment;
- accepted measured inspection verticals;
- restrained production-intent wall/floor/balcony/glass materials;
- neutral studio lighting and shadows;
- no furniture identity pass yet;
- no live Hue state, ambient-world events, causality animation, telemetry, or Home integration.

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
- Major furniture/form treatment is the next visual milestone after the architectural shell is reviewed.
