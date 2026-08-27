# Dashboard Apartment Canvas Spec

Status: **accepted architectural + projection authority, with evidence-backed object review under #192**
Owner: Dashboard UI workstream
Parent vision: `docs/DASHBOARD_REDESIGN_VISION.md`
Established: 2026-08-19

## Purpose

### 2026-08-22 visual authority update

First real whitebox inspection invalidated the fixed entry/kitchen-side
`camera_v1.json` and legacy Cutaway B; both remain superseded history.
`camera_v2.json` is the current responsive bedroom-side/right-shoulder camera
family: 20° right yaw, 36° down pitch, 45° horizontal FOV, target
`[499.60, 633.85, 118.00]`, and deterministic bounds-corner containment with
a 1.14 margin. Eye/distance and vertical FOV derive per viewport; no universal
eye is authoritative. `visibility_contract_v2.json` accepts only the named
bedroom-north and living-balcony-north shell selectors; no west cutaway is
required. Its 72 GU inspection lip remains provisional. Bedroom Treatment C
is conceptually unchanged. The corrected top-down truth view validates display
orientation only (+X right, +Y down); its presentation transform is not
geometry authority. Hidden wall-band/preflight decomposition remains deferred.

This document protects the architectural and desktop hero-projection contract
for Home Apartment Canvas while the Physical World model distinguishes verified
architecture from review-required furnished placement. It exists to prevent
future concepts from inventing a different apartment, distorting physical
geometry for composition, or silently changing the accepted camera while
pursuing the living-instrument / 2.5D-diorama direction.

## Source-of-truth hierarchy

Authority is fact-specific. See
[`dashboard/apartment_canvas/PHYSICAL_WORLD_MODEL.md`](dashboard/apartment_canvas/PHYSICAL_WORLD_MODEL.md)
for the durable evidence, scale, anchor, derivation, and presentation model.

1. **Verified architecture** — accepted shell/topology, room boundaries,
   registered openings, balcony, and fixed architectural features remain
   protected. The canonical/leasing floor plan is strong architectural
   evidence, subject to its stated nominal precision; new real-world evidence
   and explicit approval are required to reopen accepted architecture.
2. **Product/object physical truth** — direct measurements and manufacturer
   specifications own physical object dimensions and structure. They outrank
   provisional furniture rectangles, blockers, and procedural geometry.
3. **As-built/as-furnished placement** — real-room photographs, direct
   measurements, and explicit user confirmations establish where furniture
   and devices actually sit and how they relate to walls, objects, seams, and
   clearances. Photos are primary placement evidence, not merely appearance
   references, but they do not silently rewrite protected architecture or
   establish exact hidden distances.
4. **Annotated furniture plans and accepted rendering checkpoints** — useful
   placement evidence and compatibility baselines only to the precision and
   status recorded. Objects marked `review_required` remain reviewable when
   stronger physical evidence conflicts.
5. **Derived geometry** — physical coordinates, GU/world footprints,
   collision bounds, and renderer anchors derive from accepted facts,
   constraints, and one apartment-wide calibration. They are not independent
   physical authority.
6. **Presentation** — design language, Camera/Director Board framing, cutaway,
   uniform presentation scaling, materials, lighting, idealization, and the
   Story Layer may improve legibility and emotional impact without changing
   relative physical scale or placement.

A future render is wrong if it is attractive but violates protected
architecture, supported product dimensions, or evidence-backed placement. It
is also wrong if it sacrifices Apple-level polish, meaningful whole-apartment
framing, or the living HomeHub experience merely to expose reconstruction
detail.

## Approved deterministic geometry baseline

The geometry-first review is complete for the top-down apartment layout.

Anthony explicitly approved the top-down geometry baseline on 2026-08-19 after iterative correction against the canonical floor plan, annotated furniture plan, and apartment photographs.

Durable artifacts:
- `docs/dashboard/apartment_canvas/geometry_v1.json` — original approved normalized coordinate model;
- `docs/dashboard/apartment_canvas/geometry_v1_6_patch.json` — consolidated approved x/y refinements plus stable semantic wall-edge, balcony, provenance, and placement-status metadata;
- `docs/dashboard/apartment_canvas/aperture_registry_v1.json` — semantic registry for four windows and seven architectural doors;
- `docs/dashboard/apartment_canvas/truth_map_v1.svg` — approved plain top-down truth map;
- `docs/dashboard/apartment_canvas/projection_contract_v1.json` — topology-safe 2D→3D conversion and z-model rules;
- `docs/dashboard/apartment_canvas/camera_v2.json` — current accepted responsive desktop camera family;
- `docs/dashboard/apartment_canvas/visibility_contract_v2.json` — current accepted bedroom-side north cutaway selectors and Bedroom Treatment C;
- `docs/dashboard/apartment_canvas/camera_v1.json` and `visibility_contract_v1.json` — superseded historical presentation artifacts retained for provenance and debug comparison only, not simultaneous current authority.
- `docs/dashboard/apartment_canvas/topology_authority_v1.json` — accepted additive physical-XY topology authority for the future ArchitectureTopologyV1 layer.
- `docs/dashboard/apartment_canvas/physical_family_authority_v1.json` — accepted physical-only cross-void paired-rail continuation authority.

The effective **architectural** baseline is `geometry_v1.json + geometry_v1_6_patch.json + aperture_registry_v1.json`. `truth_map_v1.svg` is its human-readable top-down representation, including the v1.6 object checkpoint. Furniture/device records marked `review_required` remain provisional placement/compatibility data rather than immutable physical truth.

The coordinate system uses **Apartment Geometry Units (GU)** with the traced apartment width normalized to `1000 GU`; x and y use the same uniform scale so the floor plan cannot be stretched independently. GU remains a compatibility/render boundary, not the source of product dimensions. Future physical migration requires one apartment-wide calibration from multiple independent architectural dimensions/anchors with explicit tolerance; it may not introduce per-room, per-object, or per-axis scale corrections.

## TopologyAuthorityV1 boundary

`TopologyAuthorityV1` is additive physical-XY authority: one continuous apartment slab (excluding the balcony), one even-odd dissolved physical wall-body owner, and fail-closed semantic-face/aperture resolution policies. It does not alter `SemanticSceneV1`, its six-source manifest, or its canonical serialization. Room zoning remains intentionally deferred; this is not room-floor or mesh authority.

The slab retains the provenance breakpoint at `[441.01, 222.13]`. Its adjacent `[440.20, 222.13]` junction is a frozen support-line intersection: the 0.81 GU endpoint reconciliation is a source-trace mismatch, not a physical notch. The accepted balcony footprint is referenced rather than copied.

The next geometry milestone is `GeometrySceneV1`: a deterministic extruded 3D whitebox built directly from accepted visible wall-body polygons, registered openings/apertures, and the accepted camera/cutaway/visibility contracts. Wall-band/family decomposition is not a prerequisite for that milestone and remains outside this contract slice.

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

## GeometrySceneV1 decision boundary

The accepted Slice 1 exact wall-body geometry remains authoritative, as do the accepted openings/apertures, semantic-face metadata, and camera/cutaway/visibility contracts. `PhysicalFamilyAuthorityV1` remains valid frozen metadata; this decision does not alter it or delete historical authority/research artifacts.

The previous physical-family / wall-band investigation established that hidden decomposition of filled wall junctions into paired rails, internal seams, local strip families, or junction-port continuations is **not required** to build `GeometrySceneV1`. The floor plan does not uniquely encode those invisible seams, and they do not affect the intended Apartment Canvas whitebox when it produces the same accepted visible wall volume. Historical 27/54 local-component and 16/32 family counts are therefore provisional research results, not acceptance targets.

`PhysicalWallBandAuthorityV1` and `PhysicalFamilyPreflight` are deferred unless a future concrete feature demonstrates a need for them. `GeometrySceneV1` must not guess geometry: it consumes the accepted 2D wall-body polygons plus accepted openings/apertures and camera/cutaway/visibility contracts to produce a deterministic extruded 3D whitebox.

The next-phase acceptance question is visual and physical: “Does this look like Anthony’s apartment in 3D?” Review remains focused on the correct wall footprint, openings, room proportions, sightlines/cutaway, and—when introduced—furniture/device blocking.

From this point forward:
- accepted wall polygons, semantic wall edges, balcony footprint, and registered aperture spans remain protected architectural spatial truth;
- furniture/device x/y/orientation marked `review_required` is a reviewable rendering checkpoint, not immutable physical authority; stronger product and as-furnished evidence may reopen it without reopening architecture;
- wall height/cutaway, provisional aperture z-heights, object z-heights, extrusion, occlusion, and materials may be refined without changing x/y geometry;
- any future architectural x/y change requires new real-world evidence and explicit approval; any object-placement change requires evidence-backed constraint derivation and explicit review;
- image generation must not be used to reconstruct, reinterpret, or compare apartment geometry or camera visibility.

## GeometrySceneV1 artifact

`backend/apartment_canvas/geometry_scene.py` now compiles the isolated renderer-neutral `homehub.apartment-geometry-scene.v1` whitebox artifact. It consumes the accepted Slice 1 even-odd dissolved visible wall-body polygons, the accepted apartment slab and balcony footprints, registered aperture descriptors, and the accepted camera and visibility contracts. Its provenance keeps physical XY, aperture semantics, camera, and visibility sources separate. It does not consume `PhysicalFamilyAuthorityV1`, `PhysicalWallBandAuthorityV1`, or `PhysicalFamilyPreflight`, and it creates no hidden wall-family, paired-rail, or junction-seam geometry.

The artifact preserves exact plan-space XY as reduced rational GU tokens alongside source rings/segments where applicable. It emits one vertical extrusion per accepted visible wall-body polygon and leaves all registered apertures as exact named cutter/opening descriptors for a later renderer; no boolean solid realization, trim, furniture, device, material, or frontend work is part of this boundary.

No accepted wall height or slab thickness exists. GeometrySceneV1 therefore declares, rather than implies, provisional whitebox defaults: floor slabs span `-4` to `0 GU`, and wall bodies span `0` to `240 GU`. The registry's window sill/head and door head values remain provisional, as do the bedroom-side north cutaway lip height, bedroom solid-base height, and bedroom upper-wall opacity. These z choices may be changed without changing accepted XY authority.

Important 3D relationships preserved by current evidence (without promoting provisional object footprints to physical authority):
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

Desktop Home uses the accepted elevated roofless-diorama **perspective** family from the **bedroom/northwest right shoulder**, defined by `docs/dashboard/apartment_canvas/camera_v2.json`:
- yaw: **20° right**;
- pitch: **36° down**;
- horizontal field of view: **45°**;
- target: **`[499.60, 633.85, 118.00] GU`**;
- deterministic GeometryScene bounds-corner fit margin: **1.14**.

Camera v2 has no universal fixed eye, radius, or distance. Vertical FOV derives from horizontal FOV and viewport aspect ratio; distance derives by fitting every current GeometryScene bounds corner; eye derives from the accepted target, direction, and solved distance. The family/direction, target, horizontal FOV, and fit policy are accepted authority. Each viewport's derived eye, distance, and vertical FOV are responsive results rather than new camera authority.

`camera_v1.json` records the superseded fixed entry/kitchen-side camera and remains historical evidence only. Its fixed eye, radius, and target may be exposed in an explicitly labeled legacy comparison mode, but they are not current normative values and must not influence Camera v2 fitting.

The v2 camera is a **projection contract, not an open styling suggestion**. Do not reopen broad camera exploration unless new real-world geometry evidence materially invalidates the accepted composition. Future context-aware crops must preserve the v2 authority boundary and accepted XY.

## Accepted desktop visibility / cutaway treatment

The current accepted visibility treatment is defined by `docs/dashboard/apartment_canvas/visibility_contract_v2.json`.

- **Bedroom-side north cutaway:** lower only `wall_volume.exterior.bedroom_north` / `wall_face.exterior.bedroom_north.exterior_north` and `wall_volume.living.balcony_north` / `wall_face.living.balcony_north.balcony_north`.
- Select cutaway architecture only through those exact named stable wall/face pairs. There is no current south-entry selector, west-shell selector, camera-depth selector, or nearest-wall heuristic.
- The current **72 GU** cutaway lip is a provisional inspection value, not accepted physical z authority.
- **Bedroom wall treatment C:** preserve the desk-facing bedroom wall as a **solid lower base plus translucent upper wall**. The wall must still read as the boundary separating bedroom from bathroom/hall while allowing the desk, monitor, chair, and desk-device cluster to remain legible.
- The translucent bedroom upper wall is a **dollhouse/dashboard visibility treatment**, not a claim that the real apartment has a glass wall.
- Preserve the bedroom-door aperture through the translucent treatment; never glaze across the registered door opening.
- Bedroom-door posts, corners, header, and threshold remain opaque architecture; bathroom boundaries and the bedroom/living projector divider are explicitly excluded from treatment C.
- Keep the bedroom/living divider / projector wall as normal physical architecture. Do not remove it or invent a double-sided projector surface solely to make the bedroom-facing projection directly visible from the accepted camera.
- Exact cutaway-lip height, bedroom solid-base height, and translucent opacity remain provisional visual-model parameters.

`visibility_contract_v1.json` and its south-entry Cutaway B remain superseded historical evidence. The inspector may retain Cutaway B and no-cutaway as explicitly labeled historical/debug comparisons, but neither is simultaneous current authority.

Renderer correctness is part of this contract: the floor is an underlay and may not painter-sort over wall faces; wall caps must depth-sort with the rest of the scene rather than being painted as a final overlay.

## Bedroom

The bedroom has dual semantic identity: **desk/PC/Gaming/Working** and **Sleeping/Winding Down**.

Evidence-backed anchors and relationships are recorded in
[`dashboard/reference/bedroom/PHYSICAL_EVIDENCE_PACKET.md`](dashboard/reference/bedroom/PHYSICAL_EVIDENCE_PACKET.md).
At current evidence precision:
- the bed preserves its photographed headboard/wall orientation and has a nonzero window/HVAC/baseboard-side strip; its exact clearance is unresolved;
- the **L-shaped desk** main follows the clear/lower bedroom wall near the doorway, but its current absolute GU footprint and zero-gap note are provisional;
- the thin desk return is perpendicular to the main and near-adjacent to the bed with a narrow gap; exact clearance is unresolved;
- Braya bed and Burgener desk manufacturer dimensions own their physical sizes and outrank the old review-required blocker rectangles;
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

The architectural top-down geometry, topology-safe converter contract, desktop camera selection, and conceptual cutaway/bedroom visibility direction are satisfied by the approved artifacts above. Review-required furniture/device x/y, physical footprints, and derived anchors remain open where stronger evidence conflicts; uncertainty must stay explicit until a coherent apartment-wide physical calibration and placement derivation exist.

The current gate is **Physical World evidence and derivation before further renderer refinement**, while preserving the accepted camera and visibility treatment. During this stage:
- do not add dashboard sidebars or surrounding Home layout;
- do not add fake telemetry or confidence values;
- do not add causality traces or decorative machine UI;
- do not add Hue/live-state lighting, ambient events, or final material polish;
- do not alter protected architectural x/y geometry or distort review-required objects to improve the view;
- do not alter the accepted desktop camera merely to hide modeling/occlusion defects;
- do not replace the accepted cutaway/bedroom treatment with generated or composition-driven geometry.

Reject a candidate if wall treatment, z-height, extrusion, or occlusion makes the apartment spatially misleading even though the underlying x/y coordinates are correct.

Only after the affected Physical World evidence and derived geometry are reviewed should renderer refinement resume. Once the projected physical-world model is visually accepted, live lights, device state, ambient events, causality, and surrounding Home UI remain first-class goals rather than optional polish.

## Still-open visual questions

These are visual-model explorations, not geometry, desktop-camera, or broad cutaway uncertainties:
- exact full-wall height, bedroom-side north cutaway-lip height, and bedroom solid-base height;
- exact translucent-bedroom-wall opacity / visual material treatment;
- final provisional sill/lintel/window-glass z-heights;
- object z-heights and degree of extrusion/simplification;
- furniture silhouette fidelity needed for recognition at hero scale;
- object/wall occlusion strategy within the accepted visibility treatment;
- inactive/active Alexa-node treatment;
- projector-wall active visual strength;
- final wall/floor/material palette.
