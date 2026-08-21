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
- `docs/dashboard/apartment_canvas/physical_family_authority_v1.json` — accepted physical-only cross-void paired-rail continuation authority.

The effective spatial baseline is `geometry_v1.json + geometry_v1_6_patch.json + aperture_registry_v1.json`. `truth_map_v1.svg` is its human-readable effective top-down representation, including every v1.6 object refinement.

The coordinate system uses **Apartment Geometry Units (GU)** with the traced apartment width normalized to `1000 GU`; x and y use the same uniform scale so the floor plan cannot be stretched independently.

## TopologyAuthorityV1 boundary

`TopologyAuthorityV1` is additive physical-XY authority: one continuous apartment slab (excluding the balcony), one even-odd dissolved physical wall-body owner, and fail-closed semantic-face/aperture resolution policies. It does not alter `SemanticSceneV1`, its six-source manifest, or its canonical serialization. Room zoning remains intentionally deferred; this is not room-floor or mesh authority.

The slab retains the provenance breakpoint at `[441.01, 222.13]`. Its adjacent `[440.20, 222.13]` junction is a frozen support-line intersection: the 0.81 GU endpoint reconciliation is a source-trace mismatch, not a physical notch. The accepted balcony footprint is referenced rather than copied.

Whitebox planar topology, wall-band resolution, polygonization, and mesh/extrusion are the next `ArchitectureTopologyV1` layer and are deliberately outside this contract slice.

Registered aperture gaps are intentional semantic apertures, never missing wall geometry. A semantic wall face may span one or more registered aperture gaps even when its realized Slice 1 physical boundary rail is interrupted; the physical runs are derived around the apertures. Sixteen of the 22 accepted faces have this interruption.

`semantic_face_resolution.registered_aperture_boundary_transition` is global, derived exact face-continuity/jamb-event metadata only. Its candidate is a nonempty open complement interval strictly inside an accepted resolved semantic-face bearing interval, bounded by exactly one registered aperture endpoint and the first positive-area accepted physical Slice 1 wall remnant found monotonically away from that endpoint. The physical remnant must be parent-wall, registered-host-face, resolved-face, directed-host/opposite, and exact source-contour jamb/cap-provenance compatible. The open interior cannot contain physical wall, another aperture endpoint/interior, an accepted or derived junction, a semantic-face boundary, or a competing directed continuation. Missing, multiple, competing, or nearer incompatible evidence fails closed; no tolerance, epsilon, GU/pixel threshold, snapping, buffering, repair, or approximate adjacency is permitted. Each derived record carries the aperture and face identities, immutable segment endpoint and index, physical remnant event, exact open interval, and exact source-contour segment references for later Slice 2 only.

The transition is never positive-area physical wall, an owner, a Slice 1 modification, a `segment_gu` change, reconstruction evidence, evidence for another aperture/transition, or recursive geometry justification. It is selected after decisive accepted Slice 1 physical evidence and before—but independently of—registered-gap reconstruction within `segment_gu`; neither derived output may supply evidence to the other. `front_door` remains literal two-jamb traversal and requires no transition. The fully apertured `closet_opening` has no strict in-face transition interval (its low-side fact is outside the accepted face and high side is an exact source junction), so it remains in the existing same-nearest-event/junction proof family. Physical aperture overlap, including the bedroom-window-right and laundry-door high sides, is not a boundary transition; the later aperture cut accounts for it.

`semantic_face_resolution.registered_aperture_face_terminal_transition` is a distinct global, derived exact face-terminal family mechanism. Its candidate is a nonempty open terminal complement interval whose boundaries are exactly one accepted resolved semantic-face bearing-interval endpoint and exactly one immutable registered aperture endpoint (or its exact normal projection to the unique directed opposite face); the full interval must lie within the closed face interval. Its interior cannot contain physical Slice 1 wall, another aperture endpoint/interior, an accepted or derived junction, semantic-face boundary, or competing directed continuation. The first exact topological event at or beyond the face endpoint is decisive while searching monotonically outward away from the face interval. It must establish the same unique directed physical wall family from accepted physical Slice 1 wall-body topology, or from an already accepted exact junction proving exactly one Slice-1-compatible directed continuation. A nearer unrelated/incompatible event, absent/multiple/competing evidence, missing parent/host/resolved-face/tangent/normal/directed relationship or exact source-contour jamb/cap provenance, and every tolerance or recursive/derived-evidence need fail closed immediately.

The terminal record carries aperture, parent, registered-host-face, and resolved-face IDs; semantic-face and immutable segment endpoint indices and exact coordinates; its decisive outside physical-or-junction event; exact open interval; and exact source-contour segment references. It is face-terminal metadata only: never physical wall, owner, Slice 1 or coordinate mutation, registered-gap reconstruction evidence, boundary-transition evidence, evidence for another terminal transition/aperture, or recursive justification. The terminal mechanism first consumes only accepted Slice 1 physical/already-accepted-junction evidence, then independently emits qualifying metadata. Boundary transitions are independently resolved, and registered-gap reconstruction is independently performed only within `segment_gu`; no derived output from any of these three mechanisms may become evidence for another. The `bedroom_door` derives this family on both directed faces without an exception: its exact terminal interval is `(300.24,301.06)` at `y=534.58`, and accepted source-contour cap evidence immediately outward from `[300.24,534.58]` is its unique compatible wall family. `closet_opening` is excluded because its face and aperture are coextensive, so there is no nonempty terminal complement interval. `front_door` remains literal two-jamb traversal, with no terminal or boundary transition.

`unique_two_jamb_wall_band_traversal` remains the aperture policy. When an exact registered jamb trace lacks a local wall band, a future resolver must reconstruct only a virtual pre-aperture construction band from accepted physical Slice 1 wall-body topology. It searches monotonically outward from each open tangent side of `segment_gu`. The first positive-area physical Slice 1 wall remnant encountered is decisive and must itself be compatible with the registered `parent_wall_id`, `host_face_id`, and required directed host/opposite relationship; a nearer incompatible remnant fails closed immediately and can never be skipped for a farther compatible band. A registered-gap reconstruction, virtual pre-aperture band, derived semantic-face run, future construction topology, or inferred/guessed geometry can never supply reconstruction evidence. At a nearest topological event or junction contact, exactly one parent/host/direction-compatible directed continuation must remain; otherwise it fails closed. Both tangent sides are mandatory and must establish the same unique directed host/opposite continuation. The construction band is limited to the registered interval and is derived-only: it never writes physical XY wall topology, mutates Slice 1, becomes an owner, or changes the segment or registered identities. It also fails closed for absent physical evidence, degenerate bands, or any need for snapping, epsilon, coordinate repair, or overrides. Opposite rails may be exact tapered/non-parallel rails; no constant-thickness premise is permitted.

For registered windows, a planar Slice 1 gap is not by itself sufficient to decide a future vertical realization. Registered-gap reconstruction produces derived pre-aperture construction topology suitable as an input to a future `GeometrySceneV1`; its z-aware aperture/wall realization remains a separate `GeometrySceneV1` design and authority decision. This amendment does not make provisional sill/head metadata final and defines no z geometry, extrusion algorithm, mesh topology, sill/lintel/header construction, or rendering behavior.

## PhysicalFamilyAuthorityV1 boundary

`PhysicalFamilyAuthorityV1` is the physical-only authority for cross-void continuation of directed paired rails. It depends on the deterministic physical projection of accepted ArchitectureTopology Slice 1—its Slice 1 identity, complete arrangement audit, and complete wall body, with Slice 1 provenance excluded—and is independent of semantic-face and aperture authority. Its closed-world rule is strict: a missing certificate means there is no cross-gap continuation.

The directed physical frame is independently derived with exact Fractions from the accepted terminals. Each host/host and opposite/opposite endpoint bridge votes for its exact tangent line; each host-to-opposite cap chord votes for its exact perpendicular tangent line. Exactly one line must receive at least two independent raw-terminal votes, and the declared tangent must be that line with positive A→B rail displacement; the perpendicular normal must have positive host→opposite displacement at both terminals. This permits tapered/nonparallel rails and noisy caps without assuming that every rail is parallel or every cap is perpendicular. For an endpoint, exact junction authority is mandatory precisely when its cap contains a global physical branch event, or when none of its cap atoms and inward rail germs lies on the derived tangent or normal frame; the latter requires the exact host germ/first-cap source-incidence event. Declared junction metadata must equal this derived event set exactly, so it cannot be omitted, relocated, reprovenanced, or fabricated.

The eleven gap certificates are a closed-world set, not a semantic sequence. Authority fingerprinting canonicalizes only `gap_continuation_certificates` by complete physical certificate record before canonical JSON hashing; other array contracts retain their declared ordering.

Semantic faces and apertures may consume physical families produced by a future physical-family preflight, but they can never create, rename, merge, or supply evidence for those families. This amendment defines metadata and continuation only; it adds no z, mesh, extrusion, rendering, or `GeometrySceneV1` behavior.

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
