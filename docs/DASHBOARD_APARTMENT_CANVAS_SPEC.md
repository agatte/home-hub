# Dashboard Apartment Canvas Spec

Status: **accepted geometry + projection authority for the #157 Apartment Canvas exploration**  
Owner: Dashboard UI workstream  
Parent vision: `docs/DASHBOARD_REDESIGN_VISION.md`  
Established: 2026-08-19

## Purpose

This document locks the physical/spatial and desktop hero-projection contract for the Home Apartment Canvas before visual rendering or frontend implementation. It exists specifically to prevent future concepts from inventing a different apartment, moving approved objects for composition, or silently changing the accepted camera while pursuing the living-instrument / 2.5D-diorama direction.

## Source-of-truth hierarchy

1. **Canonical floor plan** is absolute authority for walls, room footprints, doors/openings, balcony, kitchen footprint, bath/closet/laundry/mechanical geometry, entry, and circulation.
2. **Annotated furniture floor plan** is authority for approximate furniture/device positions and orientation inside those canonical rooms.
3. **Apartment photographs** are authority for object appearance, relative scale, material cues, device relationships, and lighting appearance. Photos do not override canonical geometry.
4. **Dashboard design language** may simplify or exaggerate objects for readability, but must preserve truthful room/object relationships.

A future render is wrong if it looks attractive but violates this hierarchy.

## Approved deterministic geometry baseline

The geometry-first review is complete for the top-down apartment layout.

Anthony explicitly approved the top-down geometry baseline on 2026-08-19 after iterative correction against the canonical floor plan, annotated furniture plan, and apartment photographs.

Durable artifacts:
- `docs/dashboard/apartment_canvas/geometry_v1.json` — original approved normalized coordinate model;
- `docs/dashboard/apartment_canvas/geometry_v1_6_patch.json` — consolidated approved x/y refinements plus stable semantic wall-edge, balcony, provenance, and placement-status metadata;
- `docs/dashboard/apartment_canvas/aperture_registry_v1.json` — semantic registry for four windows and seven architectural doors;
- `docs/dashboard/apartment_canvas/truth_map_v1.svg` — approved plain top-down truth map;
- `docs/dashboard/apartment_canvas/projection_contract_v1.json` — topology-safe 2D→3D conversion and z-model rules;
- `docs/dashboard/apartment_canvas/camera_v1.json` — accepted desktop hero camera;
- `docs/dashboard/apartment_canvas/visibility_contract_v1.json` — accepted conceptual cutaway / bedroom visibility treatment.
- `docs/dashboard/apartment_canvas/topology_authority_v1.json` — accepted additive physical-XY topology authority for the future ArchitectureTopologyV1 layer.

The effective spatial baseline is `geometry_v1.json + geometry_v1_6_patch.json + aperture_registry_v1.json`. `truth_map_v1.svg` is its human-readable effective top-down representation, including every v1.6 object refinement.

The coordinate system uses **Apartment Geometry Units (GU)** with the traced apartment width normalized to `1000 GU`; x and y use the same uniform scale so the floor plan cannot be stretched independently.

## TopologyAuthorityV1 boundary

`TopologyAuthorityV1` is additive physical-XY authority: one continuous apartment slab (excluding the balcony), one even-odd dissolved physical wall-body owner, and fail-closed semantic-face/aperture resolution policies. It does not alter `SemanticSceneV1`, its six-source manifest, or its canonical serialization. Room zoning remains intentionally deferred; this is not room-floor or mesh authority.

The slab retains the provenance breakpoint at `[441.01, 222.13]`. Its adjacent `[440.20, 222.13]` junction is a frozen support-line intersection: the 0.81 GU endpoint reconciliation is a source-trace mismatch, not a physical notch. The accepted balcony footprint is referenced rather than copied.

Whitebox planar topology, wall-band resolution, polygonization, and mesh/extrusion are the next `ArchitectureTopologyV1` layer and are deliberately outside this contract slice.

From this point forward:
- approved approximate x/y/orientation, wall polygons, semantic wall edges, balcony footprint, and registered aperture spans are spatial truth, not styling suggestions;
- wall height/cutaway, provisional aperture z-heights, object z-heights, extrusion, occlusion, and materials may be refined without changing x/y geometry;
- any future x/y geometry change requires new real-world evidence and explicit approval;
- image generation must not be used to reconstruct, reinterpret, or compare apartment geometry or camera visibility.

Important 3D semantics preserved by the approved model:
- the PC tower is on the opposite/left side of the bedroom desk and physically **under the desk** (**owner-verified** relationship);
- the monitor is centered along the main desk at the wall-side edge;
- microphone, headphones, and both desk lamps sit toward the rear of the desk near the monitor line;
- the microwave is an **over-range unit above the stove/oven**, despite sharing that footprint in the top-down representation;
- the bed is a low base/mattress plus separate west-wall headboard rather than one tall prism;
- the shower is a low tray plus enclosure edges, not a solid block; only the intended front-facing enclosure span may be glass while fixed side/back architecture remains opaque;
- the vanity has a visible basin and an upright wall/back-side faucet facing into it;
- the bed has two pillows as separate later objects; their z/silhouette detail remains provisional;
- washing/drying equipment is present in the laundry area (**owner-verified**); exact arrangement/form factor remains provisional;
- the toilet uses contained tank/pedestal/bowl sub-shapes inside its approved footprint;
- kitchen pendants are suspended overhead objects.

## Accepted desktop camera / framing

Desktop Home uses a fixed elevated roofless-diorama **perspective** camera from the **front / entry-kitchen-bath side**, shifted to the right and looking back left into the apartment.

The accepted camera is defined by `docs/dashboard/apartment_canvas/camera_v1.json`:
- yaw: **20° right**;
- pitch: **36° down**;
- horizontal field of view: **45°**;
- approximate 35mm full-frame equivalent: **43.46 mm**;
- horizontal camera radius: **1040 GU**;
- eye: `[1005.70, 1532.28, 771.58] GU`;
- target: `[650, 555, 16] GU`.

This replaces the earlier bedroom-side / back-right-shoulder camera hypothesis and the older wording that described the desktop camera as coming from the upper/desk-side corner of the bedroom.

Why this camera won:
- the front-side family makes the whole apartment substantially more legible than the bedroom-side family;
- 20° yaw gives an intentional architectural three-quarter view without becoming too side-on;
- 36° pitch preserves a bird's-eye read while retaining visible 3D depth;
- 45° HFOV keeps the distant bedroom and balcony stronger than the wider tested fields of view and produces the calmest composition.

The camera is now a **projection contract, not an open styling suggestion**. Do not reopen broad camera exploration unless new real-world geometry evidence materially invalidates the composition.

Mobile may later use context-aware framing rather than shrinking the full desktop view: desk/bedroom for Gaming or Working, sleep side for Sleeping/Winding Down, living room for Watching/Relax/Social, kitchen for Cooking, with an explicit whole-apartment view available. Those mobile crops do not change desktop geometry or the accepted desktop camera.

## Accepted desktop visibility / cutaway treatment

The accepted conceptual visibility treatment is defined by `docs/dashboard/apartment_canvas/visibility_contract_v1.json`.

- **Global cutaway B:** lower only the true camera-facing south/front exterior shell. Rear walls and interior partitions remain architectural walls; do not use apartment-depth slicing to decide which walls exist.
- **Bedroom wall treatment C:** preserve the desk-facing bedroom wall as a **solid lower base plus translucent upper wall**. The wall must still read as the boundary separating bedroom from bathroom/hall while allowing the desk, monitor, chair, and desk-device cluster to remain legible.
- The translucent bedroom upper wall is a **dollhouse/dashboard visibility treatment**, not a claim that the real apartment has a glass wall.
- Preserve the bedroom-door aperture through the translucent treatment; never glaze across the registered door opening.
- Bedroom-door posts, corners, header, and threshold remain opaque architecture; bathroom boundaries and the bedroom/living projector divider are explicitly excluded from treatment C.
- Keep the bedroom/living divider / projector wall as normal physical architecture. Do not remove it or invent a double-sided projector surface solely to make the bedroom-facing projection directly visible from the accepted camera.
- Exact cutaway-lip height, bedroom solid-base height, and translucent opacity remain provisional visual-model parameters.

Renderer correctness is part of this contract: the floor is an underlay and may not painter-sort over wall faces; wall caps must depth-sort with the rest of the scene rather than being painted as a final overlay.

## Bedroom

The bedroom has dual semantic identity: **desk/PC/Gaming/Working** and **Sleeping/Winding Down**.

Canonical anchors:
- bed flush to the real upper/window-side and west-wall position from the approved coordinate model;
- **L-shaped desk** hard-anchored along the lower bedroom wall near the doorway;
- thin desk return against the side wall with only a very small gap before the bed;
- chair facing the main desk section; when seated, the bedroom door is to the left;
- monitor centered along the rear/wall-side edge of the main desk;
- microphone and headphones on the rear part of the desk beside the monitor;
- both bedroom lamps on the rear part of the desk;
- desk Alexa near the lamp closest to the door;
- PC tower on the opposite/left side of the desk and physically **under the desk**;
- **projector hardware on the thin desk return**, aimed diagonally toward the projector wall area in front of the bed.

There are **no bedroom plants** in the current physical model.

The projector wall should remain understated when inactive and become a strong illuminated rectangular projection surface only while the projector is active.

## Living room

Canonical anchors:
- brown sofa in its approved real orientation and shortened footprint;
- rectangular coffee table close to/in front of the couch;
- living-room rug places the white rounded chair on the rug but stops before the couch;
- white rounded chair in front of the left living-room window, clear of the balcony door;
- TV and TV stand/media console at the approved wall position;
- subwoofer tucked into the inside corner at the TV-stand / balcony-wall end;
- living-room lamp;
- snake plant + ZZ plant staggered and tucked near the wall in the approved plant area;
- living-room end-table cluster **between the balcony wall and couch**, with Alexa on top and Sonos Era 100 on the lower shelf.

Treat Alexa + Sonos as one visual furniture/device cluster. The **TV**, not the projector, is the living-room screen state.

## Plants

Plant geometry should be species-recognizable by silhouette rather than botanically detailed.

Current plant truth:
- snake plant — inside in the living-room plant grouping;
- ZZ plant — inside in the living-room plant grouping;
- monstera — on the balcony during warm season and brought indoors during fall/winter.

The exact warm-season balcony coordinate for the monstera remains intentionally unplaced until supported by trustworthy placement evidence.

Seasonal plant placement may eventually become real apartment state rather than static decoration.

## Kitchen

The floor plan strictly owns kitchen geometry.

Recognizable anchors:
- island with sink;
- perimeter white/gray cabinetry;
- refrigerator;
- stove/oven;
- **over-range microwave above the stove/oven**;
- two stools;
- two pendant lights distributed symmetrically along the island long axis at the accepted one-third/two-thirds positions;
- simplified kitchen runner rug.

Countertop clutter is not required.

## Bathroom / closet / laundry / mechanical / entry

These support spatial recognition but stay lower-detail than bedroom/living/kitchen.

Preserve canonical geometry and simplified recognizable anchors:
- bathroom vanity/sink flush to its wall with the accepted shortened footprint and meaningful toilet clearance;
- toilet against its approved west/left wall position with visually clear space from both vanity and fixed shower divider;
- shower architecture fixed to the approved footprint;
- closet footprint and double/folding closet-door semantics;
- closet dresser flush against the closet/entry dividing wall;
- laundry area with recognizable washing/drying equipment; exact arrangement/form factor remains provisional;
- water-heater/mechanical enclosure;
- entry/front door;
- elongated **entry cubby** flush against the opposite side of the closet/entry dividing wall.

## Balcony / exterior band

Preserve the closed semantic balcony footprint and its named shared living/balcony architectural edge exactly from the floor plan. The balcony/exterior edge becomes the restrained ambient-world boundary for daylight, weather, seasonal monstera placement, and confidence-gated outside audio micro-events such as birds, sirens, rain, or traffic.

Do not invent exact outdoor localization that sensing does not support.

## Device representation

Primary live-state anchors include:
- monitor/PC;
- both bedroom lamps;
- projector + projector-wall result;
- TV;
- Sonos;
- living-room lamp;
- kitchen lighting;
- front door where state is trustworthy.

Alexa devices should be subtle ambient-system nodes rather than detailed miniature smart speakers or permanently labeled icons. Exact visual treatment remains open; a quiet neutral node that turns Alexa-blue while active is the current preferred exploration.

## Rendering density

The canvas is an **architectural instrument**, not a Sims-like reconstruction.

Model for recognition/state/interaction, not completeness:
- furniture silhouettes should resemble the real anchors;
- rugs preserve shape/color family, not pattern fidelity;
- plants preserve species silhouette, not leaf-level detail;
- omit most desk clutter, cables, countertop clutter, tiny decor, detailed closet contents, and permanently exposed sensor hardware;
- live light should illuminate nearby geometry rather than be represented primarily by floating circles.

## Four visual layers

1. **Physical World** — architecture, anchor furniture, meaningful devices.
2. **Live State** — illumination, active devices, room/context emphasis.
3. **Causality** — temporary evidence/decision/automation traces shown on event or Explain.
4. **Ambient World** — exterior weather/daylight/audio micro-events.

Home normally emphasizes layers 1–2. Layer 3 is mostly dormant; Analytics/Insights exposes the machinery much more aggressively.

## Geometry / projection gate

The top-down geometry, topology-safe converter contract, desktop camera selection, and conceptual cutaway/bedroom visibility direction are now satisfied by the approved artifacts above. Approximate x/y/orientation is accepted; only z/appearance/silhouette detail explicitly marked provisional remains open.

The current gate is **deterministic visual-model refinement under the accepted camera and visibility treatment**. During this stage:
- do not add dashboard sidebars or surrounding Home layout;
- do not add fake telemetry or confidence values;
- do not add causality traces or decorative machine UI;
- do not add Hue/live-state lighting, ambient events, or final material polish;
- do not alter approved top-down x/y geometry to improve the view;
- do not alter the accepted desktop camera merely to hide modeling/occlusion defects;
- do not replace the accepted cutaway/bedroom treatment with generated or composition-driven geometry.

Reject a candidate if wall treatment, z-height, extrusion, or occlusion makes the apartment spatially misleading even though the underlying x/y coordinates are correct.

Only after the projected physical-world model is visually accepted should live lights, device state, ambient events, causality, or surrounding Home UI be layered in.

## Still-open visual questions

These are visual-model explorations, not geometry, desktop-camera, or broad cutaway uncertainties:
- exact full-wall height, south/front cutaway-lip height, and bedroom solid-base height;
- exact translucent-bedroom-wall opacity / visual material treatment;
- final provisional sill/lintel/window-glass z-heights;
- object z-heights and degree of extrusion/simplification;
- furniture silhouette fidelity needed for recognition at hero scale;
- object/wall occlusion strategy within the accepted visibility treatment;
- inactive/active Alexa-node treatment;
- projector-wall active visual strength;
- final wall/floor/material palette.
