# Apartment Canvas Bedroom Desk Fidelity Specification

Status: **Canonical physical-fidelity blueprint — spec-ready**  
Product: **Latitude Run Burgener L-Shape Executive Desk with File Cabinet**  
Scope: Desk geometry, structure, materials, bedroom orientation, and desk-relative projector placement  
Implementation target: A future, separately authorized Apartment Canvas desk pass

## Purpose

This document is the physical source of truth for representing the real bedroom desk in Apartment Canvas. It reconciles the authoritative product images, known dimensions, accepted bedroom placement, and user corrections into an engineering specification.

This document does not authorize or implement renderer changes. In particular, it does not redefine room geometry, accepted wall/opening placement, camera behavior, or the projector's detailed geometry.

## Evidence and Authority

Evidence precedence for this desk is:

1. The two local authoritative product images listed below, as actually inspected for this specification.
2. The stated physical dimensions and user-accepted structural and room-placement corrections in this task.
3. The Wayfair product page and its product metadata.
4. Accepted Apartment Canvas bedroom placement evidence, only for room-relative orientation and anchors.
5. Current procedural geometry, only where it independently agrees with the higher-ranked evidence.

The current renderer is not a geometry authority for the desk. Reference imagery and physical dimensions outrank existing helpers, footprints, anchors, and procedural assumptions when describing the real product.

### Inspected product references

- `C:\Users\antho\Documents\home-hub-project\references\bedroom\desk-images\desk.PNG` — assembled three-quarter product view showing the L relationship, open main span, return cabinet, material regions, cubbies, drawers, and surface appearance.
- `C:\Users\antho\Documents\home-hub-project\references\bedroom\desk-images\desk1.PNG` — separated-module dimension view showing the main and return as distinct components and labeling their principal dimensions.
- [Wayfair product page](https://www.wayfair.com/shop-product-type/pdp/latitude-run-burgener-l-shape-executive-desk-with-file-cabinet-w100541335.html?piid=1947809888) — product identity and supporting metadata: Gray/Black option, manufactured-wood top, steel base, shelves, two drawers, and modular desk return.

The local images were visually inspected, not merely checked for existence.

## Terminology and Axes

- **Main module:** the 62.99-inch open-frame desk.
- **Return module:** the 39.37-inch storage-supported module perpendicular to the main.
- **Long axis:** the direction of the listed overall length for a module.
- **Depth axis:** the horizontal direction perpendicular to that module's long axis.
- **Junction or seam:** the boundary where the return's end meets the bed-wall end of the main module.
- **Bed-side end of return:** the return end opposite the junction and nearest the bed; this is the projector end.
- **Cabinet face:** the long, room-facing side of the return storage unit where cubbies and drawer fronts are visible.

Directions such as “parallel” and “perpendicular” below always refer to these physical module axes, not to screen space, camera orientation, or an unreflected renderer coordinate system.

## Canonical Physical Dimensions

| Component | Real dimension | Relative ratio | Required render relationship |
| --- | ---: | ---: | --- |
| Main length | 62.99" | 1.000 | Longest run |
| Main depth | 31.49" | 1.000 | Deepest work surface |
| Return length | 39.37" | 0.625 of main length | Visibly shorter than main |
| Return depth | 15.74" | 0.500 of main depth | Visibly half-depth |
| Overall height | 29.52" | Same for both | Tops align at the same desktop height |

Derived ratios:

- Return/main length: `39.37 / 62.99 = 0.62502`, approximately **0.625**.
- Return/main depth: `15.74 / 31.49 = 0.49984`, approximately **0.500**.
- Main length/depth: `62.99 / 31.49 = 2.00032`, approximately **2:1**.
- Return length/depth: `39.37 / 15.74 = 2.50127`, approximately **2.5:1**.

The representation fails physical fidelity if the main and return appear equal in either length or depth.

### Proposed future render ratios

No absolute Geometry Unit values are prescribed here because the accepted room scale and final desk envelope must be reconciled explicitly before implementation. Let `L` be the future main-module length in GU under a uniform physical scale:

| Component | Required GU expression | Normalized to main length |
| --- | ---: | ---: |
| Main length | `L` | 1.00000 |
| Main depth | `L × 31.49 / 62.99` | 0.49992 |
| Return length | `L × 39.37 / 62.99` | 0.62502 |
| Return depth | `L × 15.74 / 62.99` | 0.24988 |
| Overall height, if the same uniform scale is used vertically | `L × 29.52 / 62.99` | 0.46865 |

Equivalently, the return depth must be `0.49984 × main depth`. Both modules must terminate at one shared top height. A future pass must not distort one axis independently just to preserve existing footprints.

## Canonical Structural Model

The desk is an L assembled from **two physically distinct modules**. It is not one continuous equal-width L slab.

### Main module

The main module:

- is the longer, deeper component: `62.99" × 31.49" × 29.52"`;
- provides the primary seated work surface;
- has a large, unobstructed knee/work area beneath most of its span;
- is supported by a black steel leg/frame system with rectangular sled-like end support, legs, and apron/support members;
- has no cubby cabinet, pedestal, or file drawers beneath its open span;
- is structurally independent of the return cabinet rather than resting on it as a substitute for its own support.

Small frame and apron members may occupy the perimeter beneath the top. They must not visually close the main span or read as storage mass.

### Return / storage module

The return module:

- is the shorter, narrower component: `39.37" × 15.74" × 29.52"`;
- is approximately 62.5% of the main length and 50% of the main depth;
- is a storage cabinet with a lighter wood top, not a second open desk of equal stature;
- is supported by and integrated with the black cabinet directly beneath it;
- contains upper open cubby/shelf regions;
- contains lower drawer/storage regions;
- has lighter wood drawer fronts, black pulls, black outer shell, and black internal dividers;
- must read as a supported cabinet module from overhead, side, and room-facing views.

The supplied images establish two lower drawer fronts and multiple open upper storage regions. The upper area must read as divided cubby/shelf architecture rather than one empty void or a row of drawers. Exact hidden shelf joinery and rear construction are not identity-critical.

### Junction / seam

The modules meet perpendicularly at one end of each run:

- the bed-wall end of the main meets the return end farthest from the bed;
- the seam is a real module boundary and must remain visually and structurally legible;
- the return stops at that seam; it does not continue through the main's length or full depth;
- the cabinet remains entirely on the return side of the seam;
- the main retains its full-depth worktop and open knee span on its side of the seam;
- the two top surfaces align at `29.52"` overall height.

The junction may be tight, but it must not be disguised by turning the two modules into a single continuous black L or by extending cabinet mass under the main.

## Top-Down Structural Schematic

The schematic is oriented to the accepted room placement. It is relational, not an Apartment Canvas coordinate rewrite.

```text
                         BED / window side
                     (small accepted room gap)
                              PROJECTOR
                                  ▼
 bed wall                 bed-side end
    │                 ┌────────────────┐
    │                 │ LIGHT WOOD TOP │  RETURN
    │                 │ 39.37 x 15.74  │  long axis along bed wall
    │                 │ CABINET BELOW  │  cubbies + drawers face room
    │                 └───────┬────────┘
    │                         │ return end away from bed
    │                         │ JUNCTION / SEAM
    │                         ▼
    │                 ┌───────┬──────────────────────────────────┐
    │ clear wall  ─── │ light │  SUBSTANTIAL BLACK WORK AREA    │ light │
    │                 │ wood  │  bounded within the main top    │ wood  │
    │                 └───────┴──────────────────────────────────┴───────┘
    │                    MAIN DESK — 62.99 x 31.49
    │                    OPEN KNEE AREA BELOW; BLACK STEEL FRAME
    │                                  ▲
    │                           USER / CHAIR
    │                    seated in the open room side
```

The diagram is intentionally schematic. The authoritative numeric relationships are the dimension and ratio tables, not the character widths.

## Material and Color Regions

Geometry and material identity are separate requirements. Correct dimensions with the wrong material segmentation are not a faithful result.

### Lighter weathered wood

The light material is a weathered gray-brown / light brown manufactured-wood appearance with strong natural-looking markings. It appears on:

- the lighter portions at both sides/ends of the main worktop;
- the entire return top;
- both lower drawer fronts.

The markings are a surface finish. They must be implemented as texture, shader variation, or other non-relief surface treatment. They are not slats, boards, grooves, ribs, raised strips, or regularly spaced modeled bands.

### Bounded black central work section

The main top contains a large, substantial black central work-surface section. It is a primary product-identity feature.

Required reading:

- a bounded black rectangle integrated into the central/main working region;
- large enough to dominate the seated work zone rather than read as a small decorative inset or desk mat;
- surrounded along the main module by visible lighter wood areas;
- confined to the main module;
- separate in role from black legs, aprons, cabinet shell, and drawer pulls.

The dimension image visibly labels `19.68"` across the black section's depth axis. Treat that as the supported black-section depth where a uniform product scale is used. The supplied evidence does not label its exact long-axis length; a future implementation must report its proposed long-axis bounds and demonstrate that the result matches both product views before editing. This is a bounded pre-implementation review item, not permission to reduce the section to a small mat.

The return top remains lighter wood. There is no continuous black L-shaped worktop.

### Structural black

Black/dark material belongs to:

- the main steel frame and legs;
- apron and support members;
- the return cabinet shell;
- cubby dividers and shelf structure;
- drawer pulls;
- the separate bounded central main work surface.

These regions must remain visually distinguishable by geometry and material response. For example, the black work surface is manufactured worktop material, while the frame is dark steel and the cabinet is dark panel construction.

## Grain Direction

The product views establish these dominant directions:

| Surface | Required dominant direction | Notes |
| --- | --- | --- |
| Main desktop lighter-wood portions | Parallel to the main module's 62.99-inch long axis | Use irregular weathered grain/marking variation; do not draw repeated lines across the 31.49-inch depth. |
| Return top | Parallel to the return module's 39.37-inch long axis | This direction turns 90 degrees in room space relative to the main grain because the modules are perpendicular. |
| Drawer fronts | Mirrored diagonal/chevron surface pattern across each room-facing drawer front | The dominant marks angle inward toward a shallow V/chevron; they are not parallel slats and have no relief. |

“Vertical grain” and “horizontal grain” are prohibited descriptions unless accompanied by the physical module or drawer-face axis, because the screen orientation changes with camera and presentation reflection.

## Projector Relationship

The Epson H421A:

- sits on top of the return worktop;
- is supported by the return, entirely above its top surface;
- occupies the return end nearest the bed and opposite the main/return junction;
- remains next to the bed in the accepted room arrangement;
- is not beneath the desk, inside a cubby, inside a drawer, or floating;
- does not require detailed product geometry in this specification.

Its final anchor must preserve usable support area and remain inside the return-top footprint.

## Accepted Room Relationship

This specification preserves the accepted bedroom orientation without changing room geometry:

- The main module's long rear edge is against the bedroom's clear/lower desk wall.
- The return turns from the bed-wall end of the main and runs along the wall shared by the bed/headboard placement.
- The user/chair sits on the open-room side of the main, centered on the primary/black work zone, facing the main and clear wall.
- The user's knees and chair occupy the open span beneath/in front of the main, not cabinet space.
- The bed lies immediately beyond the return's bed-side end, separated by the existing small accepted gap.
- The projector occupies that bed-side end of the return; the opposite return end forms the junction with the main.

Presentation reflection may change left/right screen appearance. It must not change these physical adjacencies or move the cabinet to the main span.

## Fidelity Tiers

### Tier 1 — Must match closely

- Overall L silhouette and room chirality.
- Main and return as distinct modules.
- `0.625` return/main length relationship.
- `0.500` return/main depth relationship.
- Junction/seam location and termination.
- Cabinet restricted to and supporting the return.
- Large open main span with black steel support structure.
- Major lighter-wood / bounded-black / structural-black material split.
- Large bounded black central work section on the main only.
- Lighter wood return top.
- Projector supported on the bed-side end of the return.
- Shared desktop height.

### Tier 2 — Should match

- Multiple upper cubby/shelf regions and their major organization.
- Two lower lighter-wood drawer fronts and their broad proportions.
- Black pulls and major drawer/cubby spacing.
- Main frame/apron and rectangular sled/leg silhouette.
- Desktop and cabinet-panel thickness.
- Rounded main-top corner treatment visible in the reference.
- Dominant grain direction and drawer-front chevron appearance.
- Cabinet caster/foot cues when visible from normal review angles.

### Tier 3 — Can simplify

- Exact shelf contents and staged accessories.
- Tiny fasteners and assembly hardware.
- Subtle handle bevels.
- Hidden caster construction.
- Invisible rear cabinet construction and hidden shelf joinery.
- Microscopic laminate variation that does not affect dominant grain direction.

No Tier 3 simplification may alter the Tier 1 silhouette, support logic, seam, material split, or projector relationship.

## Current Renderer vs Fidelity Spec

Diagnostic target: `frontend-svelte/devtools/apartment-canvas-preview/bedroom-v1.js` at checkpoint `06468aa`. These findings do not authorize edits.

| Feature | Classification | Diagnostic finding |
| --- | --- | --- |
| Main length/depth relationship | **does not match** | The accepted main footprint used by the renderer is about `237.59 × 46.38 GU`, an aspect near `5.12:1`, rather than the physical `2.00:1`. |
| Return length | **does not match** | The rendered return uses about `253.05 GU` against a `237.59 GU` main, making it approximately `1.065×` the main length instead of `0.625×`. |
| Return depth | **matches** | Code explicitly derives return depth as `15.74 / 31.49` of main depth, approximately `0.500`. |
| Junction | **partially matches** | Distinct perpendicular tops meet at the accepted end, but the overlong return and inherited footprint prevent the product's correct module proportions. |
| Main open-underneath structure | **matches** | Main uses legs/aprons and does not add cabinet mass beneath its span. |
| Cabinet location | **matches** | Cabinet geometry is confined to the return side. |
| Cabinet footprint | **partially matches** | Cabinet supports the full rendered return, but inherits the seriously overlong return footprint. |
| Cubbies | **does not match** | Renderer reduces the front to three sequential bays with only one modeled open cubby rather than the product's multiple upper cubby/shelf regions. |
| Drawers | **partially matches** | Two lighter drawer faces and dark pulls exist, but their organization/proportions are derived from the incorrect three-bay procedural split. |
| Material split | **partially matches** | Lighter wood and structural black exist, but the defining main-top black/wood segmentation is absent. |
| Black central work section | **does not match** | No substantial bounded black work-surface section is created on the main top. |
| Wood grain direction | **does not match** | Main marks run perpendicular to the main long axis and are modeled as repeated raised strips; return strips happen to run along its long axis but still incorrectly create physical bands. |
| Projector-on-return relationship | **matches** | The Epson group is anchored above and within the thin return near the accepted bed-side location. |

The ratio calculations above use the current accepted rectangles and the current renderer's own `returnDepth` derivation. They describe the checkpoint implementation only; they do not promote those absolute GU footprints to desk authority.

## Implementation Guardrails

1. Reference imagery and physical dimensions outrank existing procedural geometry.
2. Do not make main and return equal-length.
3. Do not make main and return equal-depth.
4. Do not place storage cabinet geometry beneath the open main span.
5. Do not create an unsupported return slab.
6. Do not make the entire L-shaped worktop black.
7. Do not turn wood grain into physical slat geometry.
8. Do not move the projector under the desk.
9. Do not alter room geometry to make the desk implementation easier.
10. Before implementation, report intended main/return GU dimensions and ratios for review.
11. After implementation, manually inspect the desk from overhead and side views before acceptance.
12. An implementation should not proceed to material polish if the module geometry is wrong.

Additional guardrails:

- Do not treat an accepted placement rectangle as proof of correct product dimensions when it conflicts with this specification.
- Do not use camera angle, darkness, props, or accessories to conceal a wrong silhouette or unsupported structure.
- Do not merge the two modules into one helper merely for procedural convenience if that erases the seam or material boundaries.
- Do not begin projector-detail or desk-accessory polish until the two-module footprint passes ratio review.

## Required Pre-Implementation Report

Before a future Codex implementation edits `bedroom-v1.js`, it must report all of the following for review:

| Required report item | Minimum content |
| --- | --- |
| Intended main desk GU length | Absolute GU value and endpoints/axis |
| Intended main desk GU depth | Absolute GU value and endpoints/axis |
| Intended return GU length | Absolute GU value and endpoints/axis |
| Intended return GU depth | Absolute GU value and endpoints/axis |
| Resulting return/main length ratio | Calculation; target approximately `0.62502` |
| Resulting return/main depth ratio | Calculation; target approximately `0.49984` |
| Intended cabinet footprint | GU bounds, face direction, and confirmation it stays wholly under the return |
| Intended seam location | GU line/edge and named ends of both modules that meet there |
| Intended black-worktop bounds | GU rectangle, main-relative percentages, and comparison to both inspected product images; depth should reflect the supported `19.68"` callout |
| Intended projector anchor | GU position/footprint and confirmation it is on the bed-side end of the return and entirely supported |

The report must also explain how the proposed GU dimensions coexist with accepted room anchors without moving walls, openings, the bed, or the chair arbitrarily. If the current accepted desk rectangles cannot preserve the product ratios, the implementation plan must identify the desk-local footprint correction explicitly rather than distorting the modules.

No desk implementation should begin until the report has been reviewed against this specification. Material polish must wait until overhead and side views confirm the module geometry, seam, open span, cabinet support, and projector support.

## Acceptance Checklist

A future desk implementation is acceptable only when:

- the main unmistakably reads longer and twice as deep as the return;
- the return reads approximately 62.5% as long as the main;
- the two modules meet at the specified seam without one passing through the other;
- the main work area remains open underneath;
- all cabinet mass is confined to and supports the return;
- cubbies and two lower drawers read from the cabinet face;
- the bounded black central work section is substantial but does not consume the entire main or return;
- lighter weathered wood remains visible on the main ends, return top, and drawer fronts;
- grain is a correctly directed surface feature, never relief geometry;
- the projector is supported on the return end next to the bed;
- the room shell and accepted openings remain unchanged;
- overhead and side review frames expose no floating, penetration, or false-support condition.

## Unresolved, Non-Blocking Detail

- **UNRESOLVED:** The supplied evidence does not label the exact long-axis length of the bounded black main work section. The local views establish that it is large, central/integrated, and flanked by lighter wood, while the dimension image supports a `19.68"` depth. The future pre-implementation report must propose its long-axis GU bounds and compare them against both local images for approval.
- **UNRESOLVED:** Exact hidden shelf joinery, rear cabinet construction, and caster hardware are not visible enough to specify. These are Tier 3 and do not block the blueprint.

No critical physical relationship remains unresolved: module identity, dimensions, ratios, support logic, seam, material regions, grain direction, room orientation, and projector placement are sufficiently established for the required pre-implementation review gate.
