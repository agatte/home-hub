# Apartment Canvas whitebox inspector

This is an isolated Vite/Three.js inspection tool, not a Dashboard route. Its
only spatial input is `generated/geometry-scene.json`, generated immediately
before startup by `scripts/compile_apartment_canvas_geometry_scene.py`.

From `frontend-svelte`, after dependencies are installed:

```powershell
npm run inspect:apartment
```

Open the printed `http://127.0.0.1:4174/` URL. The initial view is the accepted
Camera v2 bedroom-side family with its eye, distance, and vertical FOV derived
for the current viewport. `Top-down truth view` maps
GeometryScene as plan-left/right and plan-top/bottom through a named,
presentation-only Y reflection about the plan midpoint; this compensates for
the right-handed Z-up camera basis without changing GeometryScene coordinates.
`Legacy camera` retains the preserved `camera_v1.json` eye for comparison only.
None of these inspection controls changes GeometryScene or the accepted XY
contracts.

The exact presentation values remain provisional:

- The north cutaway inspection lip comes from the current Visibility v2 payload
  forwarded through GeometryScene; the inspector does not own a duplicate value.
- Bedroom C solid base: `92 GU`
- Bedroom C upper opacity: `0.34`

They are provisional inspection values; they do not alter accepted XY.

## Cutaway candidates

The accepted north selector is authority while its lip remains provisional;
comparison choices use the same current payload value. `Legacy Cutaway B` targets only
`wall_volume.exterior.south_entry` / `wall_face.exterior.south_entry.exterior_south`.
`Bedroom-side north` targets only `wall_volume.exterior.bedroom_north` /
`wall_face.exterior.bedroom_north.exterior_north` and
`wall_volume.living.balcony_north` /
`wall_face.living.balcony_north.balcony_north`. `North + west` is disabled:
current accepted semantic authority has no stable west-exterior wall/face pair.
The selector does not use camera depth, nearest-wall detection, or alter the
visibility contract. Bedroom Treatment C remains a separate treatment.

## Physical blocking preview

The initial accepted perspective opens with **Primary blockers** on and
secondary devices, object labels, room labels, fixture debug aids, opening
labels, and architecture IDs off. The top-down truth view may re-enable room
and fixture diagnostics; it does not change any GeometryScene coordinate.

Every blocker reads its rectangle from the forwarded accepted object annotation.
`blocking-profiles.js` is the single inspector-only profile table for its
recipe, normalized sub-shapes, and provisional z range. It contains no object
x/y coordinates and does not apply `orientation_deg`: the accepted rectangle
is already the occupied plan footprint. The inspector always states:

> Object XY accepted / blocker Z + silhouette provisional

Hover or click a blocker to inspect its object ID, accepted source footprint,
recipe, primitive, and provisional z range. These are visual massing aids, not
accepted 3D furniture models. `balcony.monstera`, rugs/runners, lamps, Alexa
nodes, microphones, headphones, plants, and other tiny decor are intentionally
not modeled in this pass.

## Readability overlays

Room labels are forwarded from the accepted `geometry_v1.json` room label
positions. Fixture debug aids are available for the accepted baseline
`bath.shower`, `bath.vanity`, and `bath.toilet` placements only. They are
explicitly marked accepted approximate XY / provisional 3D debug aids, never
architectural geometry.

Opening labels and Architecture IDs default off. Hover or click a wall or
opening to read its GeometryScene/source metadata. A dissolved Slice 1 wall
can report its source polygon and contour provenance, but does not receive an
invented semantic wall-volume binding; registered openings retain their named
wall-volume and face IDs.
