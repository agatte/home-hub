# Apartment Canvas Physical Evidence Inventory

Status: **Apartment-wide evidence/status index for #192**
Scope: Major physical objects, architectural anchors, evidence provenance, and room readiness
Relationship: The Bedroom packet is the first detailed worked example; this inventory is the apartment-wide index before further room reconciliation.

## How to read this inventory

This is an evidence map, not a renderer specification and not a new geometry
contract. It indexes facts already present in repository docs, GeometryScene
data, whitebox diagnostics, and the known workspace reference workflow.

The physical authority rules in
[`PHYSICAL_WORLD_MODEL.md`](PHYSICAL_WORLD_MODEL.md) apply to every row:

- `AUTH-MFR` — authoritative manufacturer/product dimension recorded;
- `DIRECT-RECORDED` — direct measurement is stated in repository evidence;
- `KNOWN-NOT-INDEXED` — a dimension or identity is claimed in code/docs but
  lacks a durable room evidence record;
- `APPROXIMATE` — nominal, visual, or measured-looking value without a durable
  physical calibration/tolerance;
- `UNKNOWN` — no authoritative physical dimension is recorded;
- `PHOTO` — placement/relationship supported by real-room photography;
- `USER` — explicit user confirmation or correction;
- `PROV-GEO` — current GeometryScene/blocker/renderer placement only;
- `UNPLACED` — existence is known, but placement is intentionally unresolved.

Every `geometry_v1.json` furniture/device record currently has
`placement_status: review_required`. Its GU rectangle is therefore indexed as
provisional compatibility geometry, never as a physical measurement. The
whitebox contains additional derived visuals; those are called out separately.

Reference status is deliberately separate from evidence existence:

- `REPO-MANIFEST` — the object/reference is named in a tracked manifest or
  packet;
- `REPO-DOC` — evidence is described in a tracked document but not in a room
  manifest;
- `KNOWN-OUTSIDE` — evidence is known in the workspace or prior inspection but
  is not Git-tracked/indexed;
- `MISSING/UNKNOWN` — no reliable reference location is currently recorded.

Photographs establish adjacency, ordering, orientation, facing, support, and
qualitative near-gap relationships. They do not establish exact clearances or
dimensions without independent measurement.

## Inventory coverage

| Area | Geometry records | Additional indexed groups | Current evidence position |
| --- | ---: | ---: | --- |
| Bedroom | 12 | 0 | First detailed packet; major product dimensions are known for bed and desk, but placement derivation is not ready. |
| Living | 11 | 3 whitebox representations (rug + 2 plant groups) | Several photo-supported relationships; rug and plant measurements are present only in whitebox code. |
| Kitchen | 12 | 4 upper-cabinet subgroups | Fixed shell is protected; appliance/product dimensions and durable photo indexing are incomplete. |
| Balcony | 0 | 1 unplaced seasonal plant | Architectural footprint is known; furnished evidence is incomplete. |
| Bath | 3 | 0 | Placement/blockers exist; fixture identity and dimensions are not durably recorded. |
| Entry | 1 | 0 | One user/annotation-based furniture anchor; product evidence absent. |
| Closet | 1 | 0 | One user-corrected furniture anchor; product evidence absent. |
| Laundry | 1 | 0 | Washing/drying presence is owner-verified; exact arrangement/form factor is unresolved. |
| Water heater | 1 | 0 | Enclosure/object exists as a blocker; physical equipment evidence is absent. |
| **Total** | **42** | **7 whitebox representations** | One rug treatment and two plant groups overlap conceptual GeometryScene objects; four upper-cabinet groups are additional IDs. Only Bedroom has a durable product-reference manifest. |

## Architectural anchors (protected, separate from furnished placement)

These are not furniture dimensions. They are the architectural foundation used
to constrain later object placement and global physical calibration.

| Anchor group | Current source/status | What is known | What remains open |
| --- | --- | --- | --- |
| Apartment shell and wall topology | Accepted floor-plan/topology/GeometryScene artifacts; `REPO-DOC` | Protected wall polygons, room boundaries, circulation, and semantic wall edges | Survey-grade accuracy and global physical calibration tolerance |
| Bedroom openings | Aperture registry, leasing plan, photos; `REPO-DOC` + `PHOTO` | Window spans, bedroom door, divider/projector wall relationship | Finished-face offsets, sill/head heights, and some vertical dimensions |
| Living windows and balcony door | Aperture registry, floor plan, photos; `REPO-DOC` + `PHOTO` | Named openings and balcony relationship | As-built trim/threshold and exact vertical dimensions |
| Kitchen shell | Floor plan and GeometryScene; `REPO-DOC` | Kitchen footprint, cabinet-run region, island/sink context | As-built finished faces, appliance recesses, and tolerance |
| Bath, laundry, water-heater, closet, entry boundaries | Floor plan/topology/GeometryScene; `REPO-DOC` | Room/enclosure boundaries and registered openings | Field verification and finished-face dimensions |
| Balcony footprint | Accepted closed semantic footprint; `REPO-DOC` | Architectural balcony boundary and shared living edge | Outdoor furnishing/plant placement evidence |

Architecture remains protected under #192. A furnishing conflict may reopen a
review-required object placement, but not the shell or opening geometry without
new architectural evidence and explicit approval.

## Bedroom

The detailed facts and unresolved placement questions live in the
[Bedroom Physical Evidence Packet](../reference/bedroom/PHYSICAL_EVIDENCE_PACKET.md).
The rows below are its apartment-wide index view.

| ID | Identity / dimensions status | Placement / references | Current geometry and unresolved work |
| --- | --- | --- | --- |
| `bedroom.bed` | Braya Queen; `AUTH-MFR` `64.10" × 84.00"`; product identity high | `PHOTO`; product evidence `REPO-DOC`/`KNOWN-OUTSIDE` (not in bedroom README); headboard orientation and nonzero window/HVAC/baseboard strip supported | `PROV-GEO` review-required rect; old flush-to-window note conflicts with #192 packet. Measure/confirm side strip, bed-to-return, and finished-wall clearances. |
| `bedroom.desk_main` | Burgener main; `AUTH-MFR` `62.99" × 31.49" × 29.52"`; durable desk spec and manifest | `PHOTO`; `REPO-MANIFEST` product images; main follows lower/clear desk wall | `PROV-GEO` rect has ~5.12:1 aspect, not product ~2:1. Reconcile only after global scale and desk envelope review. |
| `bedroom.desk_return` | Burgener return; `AUTH-MFR` `39.37" × 15.74" × 29.52"`; ratio ~0.625 length / ~0.500 depth | `PHOTO`; `REPO-MANIFEST`; perpendicular seam, cabinet face roomward, near bed | `PROV-GEO` return is overlong in GU. Exact bed/return gap and seam coordinates unresolved. |
| `bedroom.chair` | HomeZeer identity; `UNKNOWN` dimensions in durable packet | `PHOTO`; `REPO-MANIFEST`; faces main from open-room side | `PROV-GEO` review-required. Need product dimensions or direct envelope measurement and operating/tuck clearance. |
| `bedroom.monitor` | Samsung Odyssey G5 G50F 27-inch; `KNOWN-NOT-INDEXED` official envelope `614 × 517.8 × 250.2 mm` recorded in audit | `PHOTO`; model is `REPO-MANIFEST`/`REPO-DOC`; centered rear/wall-side main desk | `PROV-GEO` review-required; current vertical blocker is known wrong. Preserve identity while deriving above-desk placement. |
| `bedroom.pc` | PC tower model/dimensions `UNKNOWN` | `PHOTO`/`USER` under-desk and opposite/left side relationship; no product reference | `PROV-GEO` associated with desk only. Need model/measurements only if hero-readable; do not use blocker bounds as physical size. |
| `bedroom.projector` | Epson H421A / Home Cinema 3010; `KNOWN-NOT-INDEXED` `16.6" × 14.4" × 5.5"` in audit | `PHOTO`; `REPO-DOC`; on bed-side return, aimed at divider wall | `PROV-GEO` review-required and known vertically buried/wrong aim in audit. Need supported footprint, horizontal aim, rear cable and bed clearance. |
| `bedroom.microphone` | Blue Yeti; `KNOWN-NOT-INDEXED` `4.72" × 4.92" × 11.61"` extended in audit/PDF | `PHOTO`; `REPO-MANIFEST`/`REPO-DOC`; rear desk near monitor, user-right in seated composition | `PROV-GEO` review-required. Need exact desk-relative offset only if product is hero-readable. |
| `bedroom.headphones` | Product/model/dimensions `UNKNOWN` | `PHOTO`; rear desk near monitor | `PROV-GEO` review-required. Index a stable product/reference photo or keep Tier 3; no numeric GU inference. |
| `bedroom.lamp_l2` | Distinctive left lamp; identity `UNKNOWN`, dimensions `UNKNOWN`; form described in manifest | `PHOTO`; `REPO-MANIFEST` local lamp reference known outside Git; rear-left desk anchor | `PROV-GEO` review-required. Index dimensions or direct envelope if needed for scale/readability. |
| `bedroom.lamp_l5` | Distinctive right lamp; identity `UNKNOWN`, dimensions `UNKNOWN`; form described in manifest | `PHOTO`; `REPO-MANIFEST` local lamp reference known outside Git; rear-right desk anchor | `PROV-GEO` review-required. Index dimensions or direct envelope if needed for scale/readability. |
| `bedroom.alexa` | Assistant model/dimensions `UNKNOWN` | `PHOTO`; desk near door-side/right lamp relationship in packet/manifest | `PROV-GEO` review-required. Keep a subtle device node unless a durable model reference becomes necessary. |
| `bedroom.workstation.secondary` | Laptop/side stand appears in audit photos but has no canonical object ID; identity/dimensions `UNKNOWN` | `KNOWN-OUTSIDE` photo evidence; persistence explicitly needs confirmation | Not in `geometry_v1` as a physical object. Confirm persistence before adding any evidence packet row or geometry. |

### Bedroom evidence conclusion

Bedroom is **partially ready**, not coordinate-ready. Product dimensions are
strong for the bed and desk; placement relationships are strong in photos;
the global calibration, exact clearances, and several accessory dimensions are
not ready. The old arithmetic chain and old GU endpoints must not close those
gaps.

## Living room

| ID | Identity / dimensions status | Placement / references | Current geometry and unresolved work |
| --- | --- | --- | --- |
| `living.couch` | Brown couch; identity/dimensions `UNKNOWN` | `PHOTO`; inside shell, shortened, east-edge relationship described in geometry | `PROV-GEO` review-required. Need product/direct envelope and as-built wall/plant clearances. |
| `living.rug` | Rug; `KNOWN-NOT-INDEXED` whitebox declares `108" × 72"` from user measurements; geometry note says approximate | `PHOTO`/`KNOWN-OUTSIDE`; chair-on-rug and rug-stops-before-couch relationship | `PROV-GEO` plus separate non-blocking measured visual treatment. Consolidate source, units, and tolerance into a living packet before using dimension. |
| `living.coffee_table` | Identity/dimensions `UNKNOWN` | `PHOTO`; close/in front of couch | `PROV-GEO` review-required. Need direct/product envelope only if clearance or hero scale requires it. |
| `living.white_chair` | Identity/dimensions `UNKNOWN` | `PHOTO`; in front of left window and clear of balcony door | `PROV-GEO` review-required; relationship is useful, exact window/door clearance unresolved. |
| `living.tv_stand` | Media furniture identity/dimensions `UNKNOWN` | `PHOTO`; approved wall cluster relationship | `PROV-GEO` review-required. Need product/reference indexing and wall-face relationship. |
| `living.tv` | Model/dimensions `UNKNOWN` | `PHOTO`; paired with TV stand; TV is living-room screen | `PROV-GEO` review-required. Product research needed if silhouette/size is hero-readable. |
| `living.subwoofer` | Model/dimensions `UNKNOWN` | `PHOTO`; `PHOTO`/`USER`-like relation immediately above/tucked at TV stand inside corner | `PROV-GEO` review-required; relation is known, exact bounds unknown. |
| `living.end_table_cluster` | End table plus Alexa/Sonos cluster; furniture/model/dimensions `UNKNOWN` | `PHOTO`; between balcony/top wall and couch, above couch; cluster intentionally grouped | `PROV-GEO` review-required. Need a wide and side photo to separate table shelf geometry from device support. |
| `living.audio_assistant` | Sonos Era 100 and Alexa are named in design docs; device dimensions/serial models `UNKNOWN` | `PHOTO` within end-table cluster; `REPO-DOC` identity only | No independent geometry ID; preserve as contained devices until product/reference indexing and support surfaces are documented. |
| `living.lamp` | L1 identity/dimensions `UNKNOWN` | `PHOTO`; associated with end table | `PROV-GEO` review-required. Product/photo indexing needed if persistent visual anchor. |
| `living.snake_plant` | Snake plant; physical dimensions `KNOWN-NOT-INDEXED` (whitebox says user measurements but stores GU envelope) | `PHOTO`; staggered/tucked near wall with ZZ | `PROV-GEO` review-required plus visual-only measured plant group. Record physical pot/stand/foliage envelope and placement photo in living packet. |
| `living.zz_plant` | ZZ plant; physical dimensions `KNOWN-NOT-INDEXED` (same whitebox limitation) | `PHOTO`; staggered/tucked near wall with snake plant | `PROV-GEO` review-required plus visual-only measured plant group. Need physical envelope and exact plant-group placement evidence. |

Living room is **partially ready** for a focused evidence pass: broad placement
relationships exist, but no durable living-room reference manifest or product
dimension packet exists. The rug/plant measurement claims need provenance
packaging before they can support physical derivation.

## Kitchen

| ID / group | Identity / dimensions status | Placement / references | Current geometry and unresolved work |
| --- | --- | --- | --- |
| `kitchen.island` | Fixed island; dimensions `UNKNOWN` as durable physical fact | `PHOTO`/floor-plan context; central island relationship | `PROV-GEO` review-required. Direct finished-envelope measurement or architectural calibration needed. |
| `kitchen.sink` | Sink; model/dimensions `UNKNOWN` | `PHOTO`/architectural context; on island | `PROV-GEO` review-required. Treat as island-contained fixture, not independent calibrated anchor yet. |
| `kitchen.stool_1`, `kitchen.stool_2` | Stool identity/dimensions `UNKNOWN` | `PHOTO`; paired at island | `PROV-GEO` review-required. Need one representative product/direct envelope and spacing photo. |
| `kitchen.pendant_1`, `kitchen.pendant_2` | Pendant identity/dimensions `UNKNOWN` | `PHOTO`; pair distributed symmetrically along island long axis | `PROV-GEO` review-required; v1.6 symmetry is a relationship, not product dimension authority. |
| `kitchen.cabinet_run` | Fixed cabinet run; dimensions `APPROXIMATE` from floor plan plus photos | `PHOTO` + canonical floor plan; includes appliance wall | `PROV-GEO` review-required. Finished-face and cabinet/appliance recess evidence need durable indexing. |
| `kitchen.microwave` | Over-range microwave; model/dimensions `UNKNOWN` | `PHOTO`; over stove, wall-side edge relationship documented | `PROV-GEO` nested footprint is top-down readability aid, not shared elevation/physical proof. Product model and vertical placement needed. |
| `kitchen.stove` | Range/oven; model/dimensions `UNKNOWN` | `PHOTO`; primary appliance footprint in cabinet run | `PROV-GEO` review-required. Product/reference research and finished niche measurements needed. |
| `kitchen.fridge` | Refrigerator; model/dimensions `UNKNOWN` | `PHOTO`/cabinet-run context | `PROV-GEO` review-required. Product identity and recess/door-swing evidence needed. |
| `kitchen.pantry` | Pantry/cabinet segment; identity/dimensions `UNKNOWN` | `PHOTO`/cabinet-run context | `PROV-GEO` review-required. Confirm whether it is a separate object or fixed-run subdivision. |
| `kitchen.runner` | Runner; dimensions `UNKNOWN`, shape explicitly approximate | `PHOTO`; room-relative only | `PROV-GEO` approximate visual treatment. Not a physical calibration anchor. |
| `kitchen.upper_cabinet_set` | Four whitebox groups claim `KNOWN-NOT-INDEXED` recipes: `24×13×42`, `29.5×13×23.5`, `27×13×42`, `36×13×23.5` | `PHOTO` and `user measurements` are cited only in `frontend-svelte/devtools/apartment-whitebox/main.js`; no room packet/manifest | Derived visual blockers, not durable object authority. Re-measure/index finished cabinet faces and source before using these values. |
| `kitchen.countertop_appliances` | Air fryer and coffee machine are named as persistent design-language examples; model/dimensions/IDs `UNKNOWN` | `KNOWN-OUTSIDE` design-doc mention; placement photos not indexed in a kitchen packet | No current `geometry_v1` object IDs. Confirm persistence and index wide/detail photos before modeling or sizing. |

Kitchen is **dimensions needed / placement evidence needs indexing**. The shell
and major relationships are usable for an evidence pass, but the renderer's
“user measurements + kitchen photo” comments are not yet a durable packet and
must not silently become global physical anchors.

## Balcony

| ID / group | Identity / dimensions status | Placement / references | Current geometry and unresolved work |
| --- | --- | --- | --- |
| `balcony.footprint` | Architectural footprint; physical calibration `APPROXIMATE` until global fit | `REPO-DOC` accepted closed semantic footprint; shared living edge/openings known | Protected architecture; no furniture dimensions inferred. Need wide balcony/through-living placement photos for furnished reconciliation. |
| `balcony.monstera` | Monstera; identity known, dimensions `UNKNOWN` | `UNPLACED`; warm-season existence is accepted, exact coordinate intentionally not invented | Explicitly unplaced in GeometryScene. Need seasonal wide photo and pot/envelope measurement only if it becomes a physical anchor. |
| `balcony.furniture_and_planters` | No supported current object IDs; identity/dimensions `UNKNOWN` | `MISSING/UNKNOWN` reference status; do not infer from the empty footprint | Confirm whether any persistent furniture/planters exist before adding inventory rows. |

Balcony is **evidence inventory incomplete**. The architectural footprint is
ready as a protected boundary, not as proof of furnished placement.

## Bath

| ID | Identity / dimensions status | Placement / references | Current geometry and unresolved work |
| --- | --- | --- | --- |
| `bath.vanity` | Fixed vanity; identity/dimensions `UNKNOWN` | `PHOTO`; west/left-wall relationship; v1.6 shortened spacing revision | `PROV-GEO` review-required. Need finished width/depth and wall/toilet clearance evidence. |
| `bath.toilet` | Toilet; model/dimensions `UNKNOWN` | `PHOTO`; wall-adjacent; v1.6 spacing revision | `PROV-GEO` review-required. Need bowl/tank envelope and clearances if physical blocking matters. |
| `bath.shower` | Fixed shower/tray/enclosure; identity/dimensions `UNKNOWN` | `PHOTO`/architecture context | `PROV-GEO` review-required. Need enclosure/fixture evidence; do not infer glass or exact height from blocker. |

Bath is **dimensions needed**. The room shell and qualitative fixture placement
are present, but there is no durable fixture-reference manifest or measured
finished envelope.

## Entry, closet, and service areas

| ID | Room | Identity / dimensions status | Placement / references | Current geometry and unresolved work |
| --- | --- | --- | --- | --- |
| `entry.dresser` | Entry | Entry cubby/furniture identity and dimensions `UNKNOWN` | `USER`/floor-plan annotation reference; divider-wall side relationship recorded | `PROV-GEO` review-required. Exact wall-edge statement is a legacy annotation, not a product measurement; need photo and envelope. |
| `closet.dresser` | Closet | Dresser identity/dimensions `UNKNOWN` | `USER`; moved by correction while staying at divider wall | `PROV-GEO` review-required. Need product/reference photo and finished wall/door clearance. |
| `service.laundry` | Laundry | Washer/dryer presence `USER`-confirmed; model/dimensions/arrangement `UNKNOWN` | `PHOTO`/owner-verified existence in GeometryScene notes; exact arrangement provisional | `PROV-GEO` review-required. Need one clear service-area photo and model/stacking/envelope confirmation. |
| `service.water_heater` | Water heater enclosure | Identity/model/dimensions `UNKNOWN` | `PHOTO`/architectural context only | `PROV-GEO` review-required. Need enclosure and service-clearance evidence only if represented as a meaningful physical anchor. |

Entry/closet/service areas are **evidence inventory incomplete**. Their
architectural enclosures are known; object identity and dimensions are not.

## Reference-photo and product-evidence coverage

### Durable repository coverage

The tracked Bedroom reference manifest names product/model references for the
Burgener desk, HomeZeer chair, Samsung monitor, Blue Yeti, both lamps, and Epson
projector. The Bedroom packet and fidelity audit also preserve bed/product and
additional product-source details. Local product screenshots and lamp/room
archives are intentionally workspace references and are not copied into Git.

No equivalent tracked room manifest currently exists for Living, Kitchen,
Balcony, Bath, Entry, Closet, Laundry, or Water Heater.

### Known but not durably indexed

- Real-room wide and lighting/reference photography is known to exist from the
  project, and the Bedroom audit records the inspected sets, but not every
  source path is represented in a tracked manifest.
- Whitebox code cites user measurements for the living rug, two living plant
  groups, and kitchen upper cabinets. These claims need room-packet provenance,
  units, and tolerance before physical reconciliation.
- The design language names kitchen countertop appliances (air fryer and coffee
  machine), but they have no current GeometryScene IDs or room evidence packet.
- Several audit/product PDFs and product pages are described in tracked docs but
  are not uniformly indexed per object in a room manifest.

This is an indexing gap, not proof that the photographs or references do not
exist. No third-party image should be copied into Git to close it.

## Minimum evidence packet for each future room

Before a room enters physical reconciliation, create a lightweight packet with:

1. floor-plan context and named architectural anchors;
2. at least one wide establishing photograph showing multiple major objects;
3. supplemental view(s) for occluded sides, support, cabinet faces, or object
   relationships;
4. product/reference imagery for high-identity furniture or devices;
5. dimensions where available, labeled as manufacturer, direct measurement, or
   nominal-plan evidence with tolerance;
6. explicit unresolved relationships and the next evidence action.

Wide photos are placement evidence, not merely appearance inspiration. Do not
require measurements that add no value when known object dimensions, photos,
and protected architecture already establish a sufficiently truthful
visualization relationship. Do require measurement when a clearance, scale,
collision, or global-calibration decision depends on it.

## Room readiness summary

| Room/area | Readiness | Why / gate before reconciliation |
| --- | --- | --- |
| Bedroom | **Partially ready** | First packet exists; bed/desk dimensions and many placement relationships are strong. Needs global calibration, exact clearances, and accessory evidence before coordinates. |
| Living | **Partially ready** | Wide relationship evidence is reflected in current docs; needs a durable photo/product manifest and provenance for rug/plant measurements. |
| Kitchen | **Evidence inventory incomplete; dimensions needed** | Architecture and object list exist, but appliance/cabinet identity, dimensions, finished faces, and photo indexing are incomplete. |
| Balcony | **Evidence inventory incomplete** | Protected footprint exists; seasonal plant is intentionally unplaced and no furnished reference packet exists. |
| Bath | **Dimensions needed** | Fixture blockers and qualitative placement exist; no durable product/finished-envelope evidence. |
| Entry | **Evidence inventory incomplete** | One annotation/user-corrected cubby exists; no product/placement packet. |
| Closet | **Evidence inventory incomplete** | One user-corrected dresser exists; no product/placement packet. |
| Laundry | **Dimensions needed** | Washer/dryer existence is owner-verified, but arrangement/form factor is unresolved. |
| Water heater | **Architecture needs verification / evidence incomplete** | Enclosure is modeled, but equipment identity and service envelope are not documented. |

No room is marked `ready`: “ready” requires both durable evidence coverage and
an apartment-wide physical calibration path, not merely a plausible blocker.

## Recommended evidence-collection order

1. Complete the apartment-wide calibration anchors and finish Bedroom's
   unresolved bed/return/desk clearances; it is the highest-value pilot and
   already has the strongest product evidence.
2. Build the Living packet, including wide couch/window/balcony-door views,
   media cluster sides, rug and plant source measurements, and audio/end-table
   product identities.
3. Build the Kitchen packet, prioritizing finished cabinet/appliance faces,
   island/stool/pendant relationships, and durable indexing of the existing
   “user measurements + kitchen photo” claims.
4. Capture Balcony and through-living seasonal plant/furniture evidence.
5. Capture Bath fixture envelopes and finished clearances.
6. Finish Entry/Closet and Laundry/Water-Heater service-area packets where
   object identity or clearance affects the visualization.

This order is an evidence dependency order, not a renderer implementation
order. Every room remains subject to the same single-scale, no-independent-
distortion rule and the Apartment Canvas presentation goals.
