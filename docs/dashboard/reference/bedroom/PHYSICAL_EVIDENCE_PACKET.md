# Bedroom Physical Evidence Packet

Status: **First worked Physical World evidence packet; coordinate derivation not yet authorized**
Room: Bedroom
Issue: [#192](https://github.com/agatte/home-hub/issues/192)
Governing model: [`../../apartment_canvas/PHYSICAL_WORLD_MODEL.md`](../../apartment_canvas/PHYSICAL_WORLD_MODEL.md)

## Purpose

This packet records what is physically known about the bedroom before any new
Apartment Canvas coordinates are derived. It separates architecture, object
dimensions, furnished placement, derived observations, and unresolved facts.

It does not change the accepted architectural shell/openings, GeometryScene,
Camera v2, cutaway, reflection, fit margin, contracts, or fingerprints. The
pilot may add review-required preview detail from this packet; current GU
rectangles remain provisional compatibility evidence where relevant.

## Evidence set and interpretation

This packet relies on the accepted architectural artifacts and the evidence
already inspected and summarized in:

- [`../../../DASHBOARD_APARTMENT_CANVAS_SPEC.md`](../../../DASHBOARD_APARTMENT_CANVAS_SPEC.md)
- [`../../APARTMENT_CANVAS_BEDROOM_FIDELITY_AUDIT.md`](../../APARTMENT_CANVAS_BEDROOM_FIDELITY_AUDIT.md)
- [`DESK_FIDELITY_SPEC.md`](DESK_FIDELITY_SPEC.md)
- [`../../apartment_canvas/geometry_v1.json`](../../apartment_canvas/geometry_v1.json)
- the leasing plan and named real-room/product photographs referenced by those
  documents.

Source and confidence labels follow the governing Physical World model.
Photographs establish visible relationships, not hidden exact distances.

## Architectural evidence

| Fact | Source | Confidence | Qualification |
| --- | --- | --- | --- |
| The leasing plan labels the Bedroom `10'2" × 11'5"`. | Leasing floor plan | High for the printed label | Nominal physical evidence, not survey/CAD precision and not an exact single-source scale calibration. |
| The accepted shell, wall topology, bedroom door, window spans, divider/projector wall, and other registered openings are the current architectural foundation. | Accepted architectural artifacts and explicit approval | Confirmed in current scope | Protected unless new real-world architectural evidence explicitly reopens them. |
| The bedroom window wall is a flat, straight room-side vertical plane with window openings; there is no inward cove/recess below or around the sill. | Newly supplied real-room photographs and explicit user confirmation | Confirmed | The frozen window-host/source line must not be rendered as a recessed finished room-side wall. |
| `bedroom.window_sill` is a fixed, thin, elevated projecting architectural sill/ledge hosted by the bedroom window. | Newly supplied real-room photographs and explicit user confirmation | High qualitative | It projects outward into the bedroom from that flat wall; exact depth, vertical section, elevation, and overhang are not measured. |
| The sill is local to the window opening, extending only slightly beyond each window edge. | Newly supplied real-room photographs and explicit user confirmation | High qualitative | It is not a wall-length ledge/band. |
| The projector image lands directly on the bedroom-facing divider wall opposite the bed. | Real-room/night photographs and fidelity audit | High | There is no physical roll-down screen on the window wall; the accepted wall remains architecture. |

The `10'2" × 11'5"` label must not be used alone to derive a supposedly exact
GU-per-inch value. A later global calibration must use multiple independent
architectural dimensions/anchors across the apartment and publish tolerance
and residuals.

## Major object identities and dimensions

### Braya Queen bed

| Fact | Source | Confidence | Qualification |
| --- | --- | --- | --- |
| Product identity is the Braya Queen upholstered storage/platform bed. | Manufacturer/product evidence and prior evidence review | High | Detailed hidden hydraulic construction is outside this packet. |
| Physical footprint is `64.10" × 84.00"`. | Manufacturer specification | High | These dimensions own physical size; the old GU blocker does not. |
| The headboard/wall orientation matches the real-room photography. | Real-room photographs | High | This is an orientation/relationship fact, not an exact coordinate. |
| Gray upholstered frame/headboard identity and broad residential massing are supported. | Product imagery and real-room photographs | High | Mesh detail remains a later fidelity concern. |

Size and placement are deliberately separate. The `64.10" × 84.00"`
footprint does not decide the bed's precise distance from a window, baseboard,
HVAC feature, desk return, or wall.

The bed is directly adjacent to and may sit underneath the elevated projection
of `bedroom.window_sill`. Sill and bed may overlap in plan because the sill is
above the floor; this is not a floor-level collision rule or a claim of a
measured bed-to-wall clearance. The exact bed/sill XY overlap and sill depth
remain unresolved.

### Burgener L-desk

| Component/fact | Physical evidence | Source | Confidence |
| --- | ---: | --- | --- |
| Main module | `62.99" × 31.49" × 29.52"` | Manufacturer specification and inspected product dimension image | High |
| Return module | `39.37" × 15.74" × 29.52"` | Manufacturer specification and inspected product dimension image | High |
| Return/main length ratio | `39.37 / 62.99 ≈ 0.625` | Mathematical derivation from manufacturer dimensions | High, derived |
| Return/main depth ratio | `15.74 / 31.49 ≈ 0.500` | Mathematical derivation from manufacturer dimensions | High, derived |
| Main is open underneath | Product imagery and explicit desk specification | High | Perimeter frame/support members remain. |
| Cabinet/storage belongs under the return only | Product imagery and explicit desk specification | High | It must not migrate under the main. |
| Main and return are perpendicular, distinct modules meeting at a seam | Product imagery, dimensions, and explicit desk specification | High | A renderer helper must not merge them into an equal-width slab. |
| Cabinet face is toward the room | Real-room/product imagery and accepted orientation | High | Screen reflection must not reverse the physical relationship. |
| Projector is supported on the bed-side portion of the return | Real-room photographs and explicit confirmation | High | Exact projector footprint/clearance is not solved here. |

`bedroom.desk_return` is furniture: the perpendicular Burgener return/storage
module with cabinet support and the projector on its bed-side portion. It is
not the window sill/ledge. `bedroom.window_sill` is fixed architecture hosted
by the window and has no desk dimensions or storage role.

The complete desk structure, material segmentation, and fidelity tiers remain
owned by [`DESK_FIDELITY_SPEC.md`](DESK_FIDELITY_SPEC.md); this packet does not
duplicate them.

### Other major bedroom objects

| Object/fact | Source | Confidence | Qualification |
| --- | --- | --- | --- |
| Chair faces the main desk from the open-room side. | Real-room photographs and accepted relationship | High | Exact footprint and clearances require later evidence/review. |
| Monitor is centered along the rear/wall-side portion of the main desk. | Real-room photographs and accepted relationship | High | Manufacturer dimensions can own its size; no coordinate is set here. |
| PC tower is under the main desk on its return/junction side (the user's right when seated). | Explicit user confirmation, superseding the prior opposite/left-side wording | Confirmed relationship | It must not occupy the return cabinet; exact tower dimensions and clearances remain derived/provisional and unmeasured. |
| Microphone and headphones are toward the rear of the main desk near the monitor line. | Real-room photographs and accepted relationship | High | Exact offsets remain unresolved. |
| L2 and L5 occupy the rear part of the main desk; Alexa is near the door-side lamp. | Real-room photographs and accepted relationship | High | Object dimensions and exact anchors require their own evidence. |
| Epson H421A/3010 projector sits above the return and aims horizontally toward the divider wall. | Manufacturer specification, real-room photographs, and fidelity audit | High | Exact yaw, support clearance, and cable clearance remain unresolved. |

## Photo-supported placement constraints

These constraints are authoritative only at the precision stated:

| Relationship | Anchor family | Source | Confidence | Supported statement |
| --- | --- | --- | --- | --- |
| Bed headboard to room | Wall-relative/photo-supported | Real-room photographs | High | Preserve the photographed headboard/wall orientation. Do not infer zero window-side clearance. |
| Bed to elevated window sill | Architecture/object-relative/photo-supported | Newly supplied real-room photographs and explicit user confirmation | High qualitative | Bed is directly adjacent to / may sit underneath the sill projection. Exact XY overlap is unresolved and need not be non-overlapping. |
| Main desk to clear desk wall | Wall-relative/photo-supported | Real-room photographs and accepted orientation | High | Main rear edge follows the clear/lower desk wall. Exact wall gap is not newly measured here. |
| Return to main | Seam/junction-relative | Product and room photographs | High | Modules are perpendicular and meet at the product seam; return end away from bed meets the bed-wall end of main. |
| Return to bed | Object-relative/photo-supported | Real-room photographs | High qualitative | They are near-adjacent with a narrow, nonzero-looking gap, not separated by a large aisle. Exact clearance is unknown. |
| Return cabinet face | Room-relative/photo-supported | Real-room and product photographs | High | Cubbies/drawers face the open room. |
| Projector to return | Object-/seam-relative | Real-room photographs and explicit desk spec | High | Projector sits on the bed-side portion of the return, wholly supported above it. |
| Chair to main desk | Object-relative | Real-room photographs | High | Chair faces the main working region from the room side; precise tuck/turn clearance is unresolved. |

No row in this table supplies absolute x/y coordinates.

## Nominal-plan consistency observation

The following arithmetic may be recorded only as a dimensional consistency
observation:

```text
64.10 + 2.04 + 39.37 + 31.49 = 137.00 inches
```

It is **not** an accepted placement chain. In particular:

- `2.04"` is not an authoritative measured bed/return clearance;
- the sum does not establish where residual clearance belongs;
- it does not prove that the bed touches the window boundary;
- it does not override the photographed nonzero window/HVAC/baseboard-side
  strip;
- it cannot determine new coordinates or a global scale.

Rounded nominal room dimensions and product dimensions may agree closely while
their physical allocation remains underdetermined.

## Explicitly unresolved

The following facts must remain unresolved until better evidence is captured:

- exact window-sill projection depth, left/right overhang beyond the opening,
  vertical section, and elevation;
- exact bed/sill XY overlap and exact bed-to-window/wall-plane offset; the
  superseded edge-to-edge plan collision simplification must not be restored;
- exact bed-to-return clearance;
- exact wall gaps at the main and return, including baseboard effects;
- exact desk seam position in the room under corrected product dimensions;
- exact location of remaining room-width/room-length residuals;
- exact chair footprint, operating/tuck clearance, and relationship to the
  doorway under the corrected desk footprint;
- exact projector yaw, footprint offset, rear cable clearance, and bed
  clearance on the return;
- exact monitor, microphone, headphones, lamps, Alexa, and PC coordinates;
- physically accepted wall, slab, sill, head, object, and cutaway heights where
  current values are provisional;
- a validated apartment-wide physical-to-GU/world calibration and tolerance.

No unresolved item may be replaced with a visually convenient exact value.

## Provisional legacy GeometryScene/renderer values

The following current values are compatibility or diagnostic data, not
physical authority for the furnished bedroom:

| Current value | Why provisional |
| --- | --- |
| `geometry_v1.json` bed rect about `244.10 × 203.42 GU` and its note that the bed is flush to west and north/window edges | Object is `placement_status: review_required`; footprint conflicts with the manufacturer-defined Braya proportions, and photos show a nonzero side strip. |
| Main desk rect about `237.59 × 46.38 GU` | About `5.12:1`, conflicting with the physical main's approximately `2:1` footprint. |
| Return rect about `45.57 × 253.05 GU` | Rendered return length is about `1.065×` the main rather than the physical `0.625×`; its absolute bounds are not product authority. |
| Notes asserting zero-gap/hard-anchored desk placement | They are review-required checkpoint assumptions, not measurements. |
| Bed/desk/return placement constraints expressed as exact legacy pixel edges | They describe the approved v0.10 top-down rendering checkpoint; #192 reopens review-required furniture placement when better physical evidence exists. |
| Chair, monitor, PC, projector, lamps, microphone, headphones, and Alexa rectangles | All are `review_required`; they are blocking/compatibility anchors pending evidence-backed derivation. |
| Procedural blocking profiles, collision solids, and renderer offsets | Derived implementation aids; some are known to create wrong proportions or vertical relationships. |
| GeometryScene provisional z defaults and visibility heights | Declared visual-model defaults, not measured physical height authority. |

This packet does not modify those values. A future authorized migration must
replace affected derived geometry coherently rather than preserving a stale
absolute axis or endpoint.

## Required knowledge before deriving new coordinates

New absolute bedroom coordinates must wait for all of the following:

1. A defined apartment-wide physical unit and a single uniform
   physical-to-GU/world calibration fitted from multiple independent
   architectural dimensions/anchors, with tolerance and residuals.
2. Confirmation of which accepted architectural surfaces are the relevant
   finished interior faces for placement and clearance.
3. Sufficient measurement or explicit confirmation to allocate the unresolved
   bed/window-side and bed/return clearances without forcing a nominal equation.
4. A constraint solution showing that the Braya and both Burgener modules use
   their complete physical dimensions on both axes with no local distortion.
5. A named seam/junction anchor and cabinet-face direction that preserve the
   photographed room chirality.
6. A supported projector footprint/anchor on the return and a chair operating
   envelope adequate for collision review.
7. A report of every remaining unresolved degree of freedom, rather than a
   solver-selected value presented as evidence.

Accessory anchors may be derived later from their supporting object once the
bed and desk geometry is accepted; they must not be used to force the major
objects into the current blockers.

## Later validation gate

A later implementation proposal must report:

- the physical facts and constraints consumed;
- the single global transform and calibration residuals;
- candidate physical and GU/world dimensions for bed, main, and return;
- the desk ratios and seam/cabinet/projector relationships;
- exact, toleranced, qualitative, conflicting, and unresolved constraints;
- collision/clearance results without invented minima;
- repeatable overhead, desk-side, bed-side, window-side, projector-wall, and
  doorway views compared with the real-room photographs.

It fails if it changes protected architecture, uses independent scaling,
retains one stale GU axis, hides a mismatch with presentation, or claims more
placement precision than this evidence packet supports.
