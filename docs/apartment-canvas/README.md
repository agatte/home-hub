# Apartment Canvas Geometry v1

Status: **approved top-down geometry; 2.5D projection v0.1 is review-only**

Approved: 2026-08-19

## Authority

`apartment_geometry_v1.json` and `apartment_truth_map_v1.svg` freeze the user-approved
top-down Apartment Canvas geometry from iteration v0.10.

The approved baseline locks:

- architecture and wall footprints;
- room/opening relationships;
- object X/Y footprints and orientation relationships;
- the bedroom desk geometry, including the under-desk PC tower relationship.

The approved X/Y geometry must not drift during 2.5D or visual-design work. A future
geometry change requires explicit top-down re-review against real apartment evidence.

## Projection

`apartment_projection_v0_1.json` and `.svg` derive a deterministic axonometric view
from the approved geometry.

The projection is **not yet approved**. It introduces only reviewable presentation
parameters:

- orthographic camera transform;
- 60 GU provisional wall height;
- per-object Z positions and extrusion heights.

It does not alter approved X/Y coordinates.

Geometry SHA-256:

`aee59d54bb4a654978472e0a870a34749722dedbaea3b59af19a90534ca6049a`

## Review gate

Review the projection only for:

- camera/framing;
- wall/cutaway height;
- occlusion and room readability;
- object extrusion/height relationships.

Do not add materials, lighting, ambient events, causality traces, or Dashboard chrome
until the projected geometry is approved.
