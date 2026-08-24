# Apartment Canvas production preview

This isolated Vite harness is the visual-development surface for #184. It renders the accepted `GeometrySceneV1`, Camera v2, and Static Apartment v1 baseline without wiring the renderer into the production Home route.

## Current milestone

Synthetic Live State v1:

- Static Apartment v1 from merged #183 remains the accepted visible-apartment baseline;
- `rest` is the quiet baseline with no synthetic live-state effects;
- `desk` adds preview-only illumination from the two modeled bedroom lamp positions plus restrained monitor emission;
- synthetic state is renderer data, not HomeHub lifecycle/mode policy;
- preview colors/intensities are visual-review fixtures only and are not production Hue policy;
- no real device reads/writes, projector image, Ambient World events, causality animation, telemetry, or Home integration.

The renderer intentionally imports `../apartment-whitebox/adapter.js` and the generated GeometryScene artifact instead of copying plan-space coordinates.

## Run

From `frontend-svelte`:

```bash
npm run dev:apartment-canvas
```

Review the two required synthetic states:

- `http://127.0.0.1:4175/?state=rest`
- `http://127.0.0.1:4175/?state=desk`

Unknown or omitted `state` values fall back to `rest`.

Append `&debug=1` to a state URL to enable orbit controls and the GeometryScene/camera/state provenance readout. Normal preview mode remains locked to the accepted camera and contains no inspector metadata over the apartment.

Build without serving:

```bash
npm run build:apartment-canvas
```

## Guardrails

- GeometryScene fingerprint must remain `ba9270ddd772aa859dca2e155e14a54c8d1eccb3daeb869e6301780bbdd4cf43`.
- Do not change plan-space XY, openings, Camera v2 policy, accepted presentation reflection, accepted cutaway selectors, or accepted Static Apartment v1 placement to improve a live-state effect.
- Synthetic preview light colors/intensities must not be promoted into production Hue policy.
- This milestone proves visualization semantics only; production Home/runtime integration is deferred.
