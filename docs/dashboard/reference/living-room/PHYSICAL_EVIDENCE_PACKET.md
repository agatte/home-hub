# Living Room Physical Evidence Packet

Status: **Measured sofa envelope reconciled; other Living Room objects remain
unmeasured/review-required**
Room: Living Room
Snapshot: `C:\Users\antho\Documents\home-hub-project\snapshots\apartment-canvas-evidence-20260820`
Governing model: [`../../apartment_canvas/PHYSICAL_WORLD_MODEL.md`](../../apartment_canvas/PHYSICAL_WORLD_MODEL.md)

## Purpose and authority boundary

This packet records what the existing evidence establishes about stable Living
Room furniture, devices, lighting, and plants. It separates object identity,
visible material, and photo-supported relationships from exact dimensions and
coordinates that remain unknown.

Photographs establish visible structure, ordering, orientation, support,
adjacency, and qualitative near-gaps. They do not establish hidden rear/side
envelopes or exact clearances. Manufacturer dimensions and direct measurements
would own physical size if later indexed. Existing renderer recipes,
GeometryScene rectangles, collision solids, and whitebox dimensions are not
physical authority and are not promoted here.

## Evidence set

The packet points back to these original snapshot locations:

- `source\photos\livingroomSunset.JPEG`
- `source\photo_archives\lighting-curator.rar`, especially the
  `lighting-curator\` members named below;
- `source\photo_archives\apartment_views_lights_on.rar`, especially
  `apartment_views_lights_on\lights_on_straight_on_plant_stands_area.JPEG`;
- `source\photo_archives\night_photographs.rar`, especially the Living Room
  overview, plant, couch, and TV-wall members named below.
- `C:\Users\antho\Documents\home-hub-project\references\living-room\sofa\sofa-front-left.JPEG`
- `C:\Users\antho\Documents\home-hub-project\references\living-room\sofa\sofa-front-right.JPEG`
- `C:\Users\antho\Documents\home-hub-project\references\living-room\sofa\sofa-side-right.JPEG`

The wide evidence includes `livingRoom.JPEG`,
`cozyLookingKitchenAndLivingroom.JPEG`, and `livingroomSunset.JPEG`.
Detail evidence includes `couch.JPEG`, `rug.JPEG`, `coffeetable.JPEG`,
`whiteChair.JPEG`, `livingroomLampOnEndTable.JPEG`, and `plantsByCouch.JPEG`.
Night relationship evidence includes:

- `night_photographs\night_couch_to_kitchen_lights_off_2245.JPEG`;
- `night_photographs\night_couch_to_kitchen_relax_2245.JPEG`;
- `night_photographs\night_inside_doorway_facing_apartment_relax_2245.JPEG`;
- `night_photographs\night_living_room_from_kitchen_with_plants_2245.JPEG`;
- `night_photographs\night_tvwall_to_couch_left_relax_2245.JPEG`;
- `night_photographs\night_tvwall_to_couch_right_relax_2245.JPEG`.

## Object records

### Sofa

| Fact | Evidence | Confidence / authority | Qualification |
| --- | --- | --- | --- |
| Overall envelope is **94 in wide × 42 in deep × 32 in high**; seat/cushion height is **19.5 in** | Direct measurement supplied by Anthony | **Confirmed physical size authority** | The apartment-wide `3.39 GU/in` calibration derives all corresponding GU values; no sofa-specific scale is permitted. |
| Rear physical envelope is directly against the back wall | Explicit user confirmation; wide Living Room evidence | **Confirmed placement authority** | Rear edge is flush to the finished room-side east/back-wall plane, not a recessed/exterior host plane; do not invent rear clearance. |
| Chocolate-brown upholstery with a velvet-like appearance | `lighting-curator\\couch.JPEG`; wide living-room members | High for visible material/color | Hidden fabric construction and exact color under all lighting remain unresolved. |
| Broad, low silhouette has a gently arched/supportive upholstered back, substantial lower body, and **two** primary seat cushions | All three new sofa photographs | High for visible silhouette/layout | This does not identify a manufacturer or model. |
| Large traditional rolled arms and a dark carved wood front rail/ornate front feet are visible | All three new sofa photographs | High for visible silhouette/material traits | Simplified renderer carving is visual treatment, not product construction evidence. |
| Four plump muted olive woven back pillows have tan fringe/tassels; olive cylindrical bolsters sit inside both arms | All three new sofa photographs | High for visible soft-decor layout | Soft pillows may rise above the 32 in structural envelope without changing it. |
| Cream shag/fuzzy throw drapes over the right arm | `sofa-front-right.JPEG`; `sofa-side-right.JPEG` | High for visible stable decor | The renderer may simplify fibers and drape. |
| Broad orientation is along the Living Room east wall, facing the TV/media wall | Wide living-room and TV-wall/night members | High qualitative | This is a wall-relative/orientation relationship, not an absolute coordinate. |

Current authority: **physical dimensions and direct wall relationship are
reconciled**. `physical_world_v1.json` derives the structural envelope as
`318.66 × 142.38 × 108.48 GU` and seat height as `66.105 GU`, using the sole
apartment-wide `3.39 GU/in` calibration. Its rear edge is anchored to the
accepted finished room-side east/back-wall plane at `x = 981.29 GU`; the
along-wall start remains explicitly provisional because it is not measured.

The old GeometryScene inspection rectangle (`117.98 × 244.10 GU`) and old
renderer/blocker override (`142.38 × 311.88 GU`) are superseded as sofa size
authority. They remain frozen compatibility artifacts only; neither may be
used to restore or distort the measured sofa envelope.

#### Sofa identification-tag provenance

`C:\Users\antho\Documents\home-hub-project\references\living-room\sofa\sofa-id-tag.JPEG`
visually records the following identifiers for this actual sofa:

- Frame #: `A7467`
- Fabric: `7067-088`
- Finish: `349`
- Tag #: `0926146`
- ACK #: `F539067`

These are durable provenance identifiers only. They do not independently
establish, and are not used to claim, a manufacturer or model name.

### Rug

| Fact | Evidence | Confidence / authority | Qualification |
| --- | --- | --- | --- |
| Muted neutral rug with a subtle pattern and warm-neutral floor relationship | `lighting-curator\\rug.JPEG`; wide evening/day views | High for visible appearance | Pattern fidelity is not a measured property. |
| White swivel chair sits on the rug; rug stops before the sofa | `lighting-curator\\cozyLookingKitchenAndLivingroom.JPEG`; TV-wall/night views | High qualitative | Exact offsets and edge clearances are unresolved. |
| A whitebox note reports `108 in × 72 in` as user measurements | Existing whitebox documentation, not a packet source | **Not promoted** | Provenance, measurement method, tolerance, and orientation are not durably established here. Treat as a lead for re-verification, not physical truth. |

Current authority: **visual relationship ready; physical dimensions not ready**.
Do not use the whitebox recipe or current GU footprint as rug size authority.

### Coffee table

| Fact | Evidence | Confidence / authority | Qualification |
| --- | --- | --- | --- |
| Rectangular table with dark wood and patterned/inlaid top detail | `lighting-curator\\coffeetable.JPEG` | High for visible identity/material | Exact species, finish, and construction are unresolved. |
| Table is in front of and close to the sofa, between sofa and chair/rug area | Wide evening and TV-wall/night views | High qualitative | “Close” is not a measured clearance. |

Current authority: **visual fidelity/placement relationship ready; dimensions and
coordinates unresolved**.

### White swivel chair

| Fact | Evidence | Confidence / authority | Qualification |
| --- | --- | --- | --- |
| Cream/white bouclé upholstery and rounded swivel-chair form | `lighting-curator\\whiteChair.JPEG`; `source\\photos\\livingroomSunset.JPEG` | High | Hidden base and full operating envelope are not established. |
| Chair is in front of the left living-room window and clear of the balcony door | `lighting-curator\\livingroomSunset.JPEG`; wide room/night views | High qualitative | Exact window/door clearances are unresolved. |
| Chair is positioned on the living-room rug | Wide evening view and rug evidence | High qualitative | No exact rug-relative coordinate is established. |

Current authority: **visual fidelity and qualitative placement ready; physical
dimensions/clearance reconciliation not ready**.

### TV and media console

| Fact | Evidence | Confidence / authority | Qualification |
| --- | --- | --- | --- |
| TV and media console form the Living Room screen/wall cluster | `lighting-curator\\livingRoom.JPEG`; `night_photographs\\night_tvwall_to_couch_left_relax_2245.JPEG`; `...right...JPEG` | High | TV model, screen envelope, console identity, and console dimensions are unresolved. |
| TV is the Living Room screen; the bedroom projector is not part of this cluster | Existing Apartment Canvas design direction plus TV-wall photographs | Confirmed within current scope | This is a semantic room-role fact, not a screen measurement. |
| Console is at the approved wall position and TV is paired with it | Wide and TV-wall photographs | High qualitative | Do not turn the approved GeometryScene wall position into a measured furniture coordinate. |

Current authority: **cluster relationship ready; product dimensions and exact
physical placement unresolved**.

### Subwoofer

| Fact | Evidence | Confidence / authority | Qualification |
| --- | --- | --- | --- |
| Subwoofer is tucked immediately above/inside the media-console corner at the balcony-wall end | Living-room overview and both TV-wall/night views | High qualitative | Exact footprint, height, and support/contact relationship are unresolved. |

Current authority: **qualitative placement ready; physical envelope not ready**.

### End table, Sonos Era 100, and Alexa

| Object | Established evidence | Placement relationship | Open physical facts |
| --- | --- | --- | --- |
| End table | Visible as the living-room side-table cluster in wide and night views | Between the balcony/top wall and sofa, above/alongside the sofa; device support surface is visible qualitatively | Table identity, width/depth/height, shelf geometry, and wall/sofa clearances |
| Sonos Era 100 | Named audio device and visible within the end-table cluster | On the lower shelf of the end table | Exact model confirmation from a dedicated view, dimensions, orientation, and shelf clearance |
| Alexa | Named assistant and visible within the end-table cluster | On top of the end table | Exact model, dimensions, and top-surface offset |

Sources: `lighting-curator\\livingRoom.JPEG`,
`lighting-curator\\cozyLookingKitchenAndLivingroom.JPEG`, and
`night_photographs\\night_living_room_from_kitchen_with_plants_2245.JPEG`.

Current authority: **cluster-level visual relationship ready; device and table
physical reconciliation not ready**. Preserve Alexa and Sonos as contained
devices in this cluster until their support surfaces and product envelopes are
documented.

### L1 lamp

| Fact | Evidence | Confidence / authority | Qualification |
| --- | --- | --- | --- |
| L1 is the Living Room corner lamp associated with the end-table area | `lighting-curator\\livingroomLampOnEndTable.JPEG`; wide room views | High | Exact stand/shade dimensions and mounting relationship are unresolved. |
| Turquoise/teal cylindrical base is a distinctive visible identity trait | L1 close-up and sunset/wide views | High | Color under changing light is not a physical color calibration. |
| Lamp is on/at the end table in the Living Room corner | L1 close-up and wide views | High qualitative | Exact table-relative offset and cable/base footprint are unresolved. |

Current authority: **fixture identity and qualitative placement ready; physical
envelope not ready**.

### Snake plant and ZZ plant

| Fact | Evidence | Confidence / authority | Qualification |
| --- | --- | --- | --- |
| Snake plant and ZZ plant are the two stable Living Room plants | `lighting-curator\\plantsByCouch.JPEG`; living-room wide/night views | High | Species-level visual identity is sufficient for silhouette work; cultivar is unresolved. |
| Both use matched white pots on black metal stands | `lighting-curator\\plantsByCouch.JPEG`; `apartment_views_lights_on\\lights_on_straight_on_plant_stands_area.JPEG` | High | Exact pot/stand product identities and dimensions are unresolved. |
| They are staggered/tucked near the wall in the approved plant area, with the group near the sofa | Plant detail, wide, and night views | High qualitative | Exact group spacing, wall gap, pot centers, and foliage envelopes are unresolved. |
| Whitebox plant dimensions exist as visual treatment values | Existing whitebox documentation | **Not promoted** | Stored GU envelopes/recipes do not establish physical pot, stand, or foliage dimensions. |

Current authority: **species/material/group relationship ready for visual
fidelity; physical envelopes and coordinates not ready**.

## Cross-object placement constraints

These are the strongest current placement statements and remain qualitative
unless separately measured:

| Relationship | Evidence-backed statement | Status |
| --- | --- | --- |
| Sofa ↔ TV wall | Sofa broadly follows the east wall and faces the TV/media-console wall | Photo-supported, high qualitative |
| Sofa ↔ coffee table | Coffee table is close/in front of sofa | Photo-supported, qualitative near-gap |
| Rug ↔ sofa/chair | Chair is on rug; rug stops before sofa | Photo-supported, high qualitative |
| Chair ↔ openings | Chair is in front of left living window and clear of balcony door | Photo-supported, qualitative clearance |
| TV ↔ console | TV is paired with console at the approved wall cluster | Photo-supported, high qualitative |
| Subwoofer ↔ console | Subwoofer is immediately above/tucked into the console inside corner at balcony-wall end | Photo-supported, qualitative support/containment |
| End table ↔ sofa/balcony wall | End-table cluster lies between balcony/top wall and sofa, above/alongside sofa | Photo-supported, qualitative |
| Alexa ↔ end table | Alexa is on the end-table top | Photo-supported, qualitative support |
| Sonos ↔ end table | Sonos Era 100 is on the end-table lower shelf | Photo-supported, qualitative support |
| Plants ↔ wall/sofa | Snake and ZZ plants are staggered near the wall in the plant area by the sofa | Photo-supported, qualitative |

No row supplies an absolute x/y coordinate, a GU conversion, or an exact
clearance.

## Explicitly unresolved

- sofa-to-plant, sofa-to-coffee-table, and sofa-to-opening clearances;
- rug physical width/depth, orientation, thickness, and edge clearances;
- coffee-table width/depth/height and exact sofa/chair clearances;
- white-chair product identity or measured envelope, swivel/operating envelope,
  and exact window/balcony-door clearances;
- TV model, screen dimensions, mounting/support height, and console identity,
  dimensions, depth, and wall gap;
- subwoofer model/dimensions, elevation, and exact console support/tuck;
- end-table product identity, dimensions, shelf heights, and wall/sofa gaps;
- Sonos Era 100 and Alexa exact product envelopes, orientations, and offsets;
- L1 lamp complete envelope, shade/base dimensions, and end-table relationship;
- snake/ZZ pot, stand, and foliage envelopes and exact group spacing;
- all living-room object heights and a validated apartment-wide physical-to-GU
  transform/tolerance for any future coordinate derivation.

## Provisional implementation values explicitly not promoted

Current `geometry_v1.json` living-room rectangles, placement constraints, and
whitebox rug/plant values remain provisional compatibility or presentation
inputs. They may be useful for locating the current visual checkpoint, but they
do not establish physical dimensions, coordinates, collision bounds, or
heights. The sole exception is the accepted finished room-side wall face used
to anchor the sofa's explicitly confirmed direct-against-wall relationship.

## Reconciliation gate

The Living Room sofa is ready for bounded physical/visual reconstruction;
remaining objects are **not ready for coordinate or dimension reconciliation**.
Their later work still requires the unresolved envelopes above and the same
apartment-wide single-scale calibration described by the governing Physical
World model.
