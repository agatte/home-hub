# Apartment Canvas Bedroom Fidelity Audit

Status: **read-first audit complete; rebuild-ready, with a fresh orbit-capture gate open**  
Date: 2026-08-24  
Branch/base: `design/apartment-bedroom-visual-pass` / `44448e8`  
Scope: bedroom object fidelity in the isolated Apartment Canvas preview

## Status

Read-first fidelity audit is complete and the static-object rebuild is implementation-ready. A fresh `?debug=1` orbit capture remains a required visual-acceptance gate because no controllable browser was available during this audit.

## Purpose

Determine whether the current Apartment Canvas bedroom reads as Anthony's real bedroom, not merely as a premium generic approximation, and define the smallest object rebuild required before more material, lighting, or cinema polish is worthwhile.

This audit does **not** reopen accepted room geometry, openings, room proportions, cutaway policy, presentation reflection/chirality, Camera v2, or the GeometryScene fingerprint. It separates accepted placement truth from provisional object identity, silhouette, material, and vertical modeling.

## Status and conclusion

The bedroom is **spatially recognizable but not object-faithful**. Its strongest assets are the accepted room shell, bed/desk footprints, L-shaped desk relationship, chair location, and projector-on-return relationship. Its high-identity objects are still boxes, ellipsoids, duplicated overlays, or invented treatments.

Do not start another ambiance pass. The minimum fidelity bar is not met because:

1. a fictional roll-down projection screen is placed across the real window wall;
2. the gray/black Burgener L-desk has been restyled as a brown/walnut main desk while its return remains a generic dark block;
3. the monitor stand and much of the monitor panel are below/intersecting the desktop;
4. the Epson projector is undersized, vertically buried in the return, and has a vertical lens axis;
5. the Braya bed, HomeZeer chair, Blue Yeti, and both distinctive lamps do not match their real silhouettes.

These failures can be fixed with replacement object meshes and materials without changing accepted architecture.

## Sources used

### Repository and accepted design sources

- `AGENTS.md`, `docs/PROJECT_SPEC.md`, and `docs/DASHBOARD_APARTMENT_CANVAS_SPEC.md`
- `docs/dashboard/APARTMENT_CANVAS_DESIGN_LANGUAGE.md`
- `docs/dashboard/APARTMENT_CANVAS_DIRECTOR_BOARD.md`
- `docs/dashboard/APARTMENT_CANVAS_BEDROOM_DESIGN_PASS.md`
- accepted GeometryScene, projection, aperture, Camera v2, and visibility artifacts under `docs/dashboard/apartment_canvas/`
- `frontend-svelte/devtools/apartment-whitebox/blocking-profiles.js`
- current preview README, compositor, furniture, detail, polish, and bedroom-pass files
- existing `apartment-canvas-before-settled.png` and `apartment-canvas-after.png`

### Real-apartment evidence inspected

- `apartmentFloorPlan.png`
- both named `apartment_views_lights_on` bedroom photos
- both named `night_photographs` bedroom photos
- all six named `lighting-curator` bedroom photos, plus `L5BedroomLampRightClearHousing.jpeg`
- `lamps/leftDeskLamp.JPEG` and `lamps/rightDeskLamp.JPEG`

These establish the desk/return arrangement, gray wood and black-frame finish, chair appearance, monitor/mic/lamp arrangement, gray upholstered bed, white blinds, real wall art, projector-on-return placement, and direct-to-wall projection.

### Product evidence inspected

- [Latitude Run Braya storage bed](https://www.wayfair.com/furniture/pdp/latitude-run-braya-hydraulic-lift-up-storage-upholstered-platform-bed-w010801433.html)
- [Latitude Run Burgener L-desk](https://www.wayfair.com/shop-product-type/pdp/latitude-run-burgener-l-shape-executive-desk-with-file-cabinet-w100541335.html?piid=1947809888): gray manufactured-wood top, black steel base, modular L arrangement, shelving/two-drawer storage
- [HomeZeer white mid-back chair](https://www.amazon.com/HomeZeer-Office-Computer-Leather-Adjustable/dp/B0D42B5G1Q?th=1): white padded upholstery/arms and chrome five-star caster base
- [Samsung Odyssey G5 G50F 27-inch](https://www.samsung.com/us/monitors/gaming/27-inch-odyssey-g5-g50f-qhd-fast-ips-180hz-gaming-monitor-sku-ls27fg502enxza/): flat black 16:9 panel; 614 x 517.8 x 250.2 mm with stand
- [Epson Home Cinema 3010](https://epson.com/For-Home/Projectors/Home-Cinema/PowerLite-Home-Cinema-3010-1080p-3LCD-Projector/p/V11H421020), corresponding to H421A: white/gray case, offset lens, front grilles, 16.6 x 14.4 x 5.5 inches including feet
- [Blue Yeti specification](https://www.logitech.com/assets/66310/blue-yeti-web-qsg.pdf): capsule body in side yoke on circular stand; 4.72 x 4.92 x 11.61 inches extended

### Access limits

The named `/mnt/data` mount does not exist in this Windows session. The room archives and lamp archive were found elsewhere and inspected; `bedframe.rar`, `desk.rar`, and `bedroomChair.rar` were not found. Product imagery and real-room photos are sufficient for the main silhouette decisions, but the missing archives remain useful for final detail confirmation.

The in-app browser exposed no controllable browser instance, and port 4175 was not running. A fresh `?debug=1` orbit session and eight-angle capture set could not be completed. Existing captures were inspected, but `apartment-canvas-after.png` shows an anomalous narrow slice and is not acceptance evidence. Hidden-side findings are therefore based on code/geometry and marked where a fresh orbit remains necessary.

## Confidence notes

- **High:** current code plus strong room/product evidence agree.
- **Medium:** photos/product information support the finding, but precise scale/side needs orbit or measurement.
- **Low:** partly occluded, no exact product reference, or below hero readability.
- Accepted annotation rectangles are placement authorities, not proof of correct product dimensions or vertical relationships. Their placement status and blocking silhouettes remain provisional/review-required.

## Git state before

Branch `design/apartment-bedroom-visual-pass`; `HEAD` and merge-base `44448e858175594e07845ed66731af0c742bf2ce`.

Tracked modifications already present:

- `frontend-svelte/devtools/apartment-canvas-preview/README.md`
- `frontend-svelte/devtools/apartment-canvas-preview/main-v2.js`
- `frontend-svelte/devtools/apartment-canvas-preview/main-v3.js`
- `frontend-svelte/devtools/apartment-canvas-preview/styles.css`

Untracked work already present:

- `frontend-svelte/devtools/apartment-canvas-preview/bedroom-v1.js`
- this audit document, which contained a prior incomplete draft and was preserved as input before revision

No work was cleaned, reset, committed, merged, or copied into canonical main.

## Current implementation map

| File | Responsibility | Finding |
|---|---|---|
| `blocking-profiles.js` | Provisional bed, desk, chair, monitor, PC, projector solids/z | Useful blocking authority; monitor/projector verticals are physically wrong for finished objects. |
| `furniture-v1.js` | Base carpet/materials/blocker primitives | Preserves placement but uses generic primitives/materials. |
| `furniture-v2.js` | Bed/pillows, L-desk top/bridge, monitor stand cues | L continuity is useful; monitor stand is below the desk; bed details are duplicated later. |
| `details-v1.js` | Desk edge, lamp proxies, mic, headphones, Alexa | Correct categories/rough anchors; weak or wrong silhouettes. |
| `polish-v1.js` | Bed runner/headboard face and apartment polish | Warm bed choices conflict with the gray bed and white/neutral bedding. |
| `bedroom-v1.js` | New carpet/textiles/desk/chair/monitor/task light/projector/screen | Main current fidelity regression; most contents need replacement. |
| `main-v3.js` | Adds the bedroom layer | Useful seam; preserve while replacing its contents. |
| `main-v2.js` | Render shell plus 1.06 fit margin/background changes | Fit margin is independently promising; background is unrelated to object fidelity. |
| `styles.css` | Background gradient | Park until neutral object fidelity passes. |

## Current-room summary

### Faithful now

- Accepted bedroom envelope, door, divider/projector wall, and window openings.
- Broad organization: bed at the window/headboard side, L-desk along the desk wall, chair centered at the main run, return between desk and bed, projector on the return.
- Main desk's open black support concept at blocking level.
- Existence of one monitor, two distinct desk lamps, mic, headphones, Alexa, under-desk PC, upholstered bed/headboard, white chair, and carpet.
- Bed's low base/mattress plus separate headboard relationship.
- Joined main/return top in `furniture-v2.js`.

### Missing or insufficiently specific

- Braya channels, wings/posts, gray upholstery, substantial rails, and lift-storage silhouette.
- Burgener gray/black construction, open shelving/drawers, and coherent main/return finish.
- HomeZeer stitched cushions, padded chrome arms, lift, five-star base, and casters.
- Correct Samsung scale/neck/base and above-desk placement.
- Epson body volume, grille/lens layout, feet, and physically aimed lens.
- Blue Yeti yoke, knobs, grille/body, and broad stand.
- Actual L2 drum/faceted lamp and L5 seeded-glass/marble/hook lamp.
- White blinds, real wall art, and confirmed projector-wall-side laptop stand.

### Invented or misleading

- Framed roll-down screen and roller over the windows.
- Brown/walnut cap only on the main desk.
- Green-black desk mat as invented identity.
- Taupe overlays on a white leather/chrome chair.
- Bordered inset carpet that reads as an area rug.
- Brown bed runner/throw and decorative seams unsupported by photos.
- Static warm point light that makes wrong objects appear more finished.

## Object-by-object audit

| Object / feature | Real reference | Current representation | Confidence | Rating | Issue class | Priority | Next action |
|---|---|---|---|---|---|---|---|
| Shell/openings | Floor plan, GeometryScene, photos | Accepted architecture | High | good | geometry/layout | Guardrail | Preserve byte-for-byte. |
| Bed placement/massing | Photos; Braya | Low deck/mattress, west headboard | High | acceptable | proportions | P1 | Preserve envelope/orientation; replace finished mesh. |
| Braya identity | Gray frame; two horizontal headboard bands; side wings; upholstered rails | Warm generic slab and tiny footboard | High | wrong | identity/material | P1 | Near-exact custom recreation. |
| Bedding | White puffy comforter; beige/cream sheets/pillows | Flat competing layers, repeated pillows, brown throw/runner | High | weak | identity/material | P1 | One coherent custom bedding set. |
| L-desk footprint | Product and wide room photo | Perpendicular accepted rectangles with bridge | High | acceptable | geometry/layout | Preserve | Keep footprint/junction. |
| Main desk | Gray top, black rectangular steel frame, rounded corners | Dark generic base plus brown main-only cap | High | wrong | identity/material | P0 | Reuse frame concept; rebuild gray top/edge/support. |
| Return/file cabinet | Gray top; visible cubbies/shelves/drawer/bin faces | Solid full-height block | High | wrong | identity | P0 | Build visible storage architecture in accepted envelope. |
| Chair | White padded mid-back, stitched panels, padded chrome arms/base/casters | Generic white primitives plus taupe duplicates | High | wrong | identity/material | P1 | One near-exact HomeZeer group. |
| Monitor | Flat black 27-inch panel and black stand | Duplicate generic slabs; stand z=61..70 below z=96..105 desktop | High | wrong | proportions/physics | P1 | One official-dimension assembly fully above desk. |
| Blue Yeti | Black yoke/body/round stand; user's right of monitor | Narrow cylinder/ellipsoid; missing recognition details | High identity; medium side | weak | identity/placement | P1 | Near-exact custom model; verify seated right side under accepted reflection. |
| L2 lamp | Cream cylinder drum, dark trim, faceted gray base | Thin stem/cone on circular base | High | wrong | identity/proportions | P1 | Faithful custom recreation at rear-left anchor. |
| L5 lamp | Marble rectangle, brass stem/hook, hanging seeded-glass cylinder/bulb | Circular base/straight stem/clear column/cone | High | wrong | identity/proportions | P1 | Faithful custom recreation at rear-right anchor. |
| Epson projector | White/gray 16.6 x 14.4 x 5.5-inch body, offset lens/front grilles, on return | Tiny thin bodies below/intersecting desk; vertical lens axis | High | wrong | placement/proportions/physics | P0 | Near-exact body entirely above return, aimed horizontally at real wall. |
| Projection destination | Direct 16:9 light on plain wall opposite bed | Real divider plus fictional physical screen on window wall | High | wrong | placement/identity | P0 | Delete screen/trim/roller; inactive state is bare wall. |
| Carpet | Gray wall-to-wall carpet | Beige base plus brown inset/band | High | wrong | material/identity | P1 | One restrained gray carpet surface. |
| White blinds | Wide white slatted blind/header | Missing | High | missing | identity | P1 | Custom blinds registered to existing apertures. |
| Wall art | Narrow vertical multicolor word-art panel | Missing | High | missing | identity | P2 | Add restrained flat recreation after screen removal. |
| PC | Dark under-desk object | Dark rectangular tower under desk | Medium | acceptable | identity | P2 | Preserve; refine only with clear reference/visibility. |
| Headphones | Black over-ear pair on desk/mat | Flat torus/pads | Medium | weak | identity/placement | P2 | Approximate real form/resting pose. |
| Alexa | Small dark/blue desk device | Generic cylinder | Medium | acceptable | identity | P2 | Low detail is sufficient unless hero-readable. |
| Laptop/side stand | Draped sculptural stand with laptop in daylight photos | Missing | Medium | missing | missing reference | P2 | Confirm persistence; faithful custom if retained. |
| Ceiling fan/vent | Visible in wide photos | Omitted by roofless presentation | High | acceptable | presentation | Low | Keep omitted unless a ceiling appears in a focused view. |
| Cables/clutter | Visible but variable | Mostly omitted | High | acceptable | presentation | Low | Tier 3 or omit. |

## Projection-surface/window issue

### Exact code source

`addProjectorIdentity()` in `bedroom-v1.js` creates:

- trim: `addBox(world, 178, 2.8, 137, 250, 67.2, 181, ...)`
- surface: `addBox(world, 168, 1.6, 127, 250, 65.0, 181, ...)`
- a 172-GU lower roller at `(250, 63.8, 116.5)`

Its comment says this is an inactive surface on the north wall chosen because it is readable from the overview. That intention conflicts with both the real room and the accepted visibility contract.

### Placement and overlap

The trim occupies about x `161..339`, y `65.8..68.6`, z `112.5..249.5`; the inner surface occupies x `166..334`, y `64.2..65.8`, z `117.5..244.5`. The accepted bedroom windows are on that same north wall at approximately x `119..223` and x `236..353`. The added screen therefore overlaps both window spans, explaining the canvas/screen artifact over the windows.

### Real condition and decision

The night photo shows the projector image cast directly on a plain painted wall opposite the bed. There is no frame, fabric screen, cassette, or roller. The accepted destination is the bedroom-facing side of `wall_volume.bedroom_living.projector_divider` at x `440.20`, spanning y `241.66..546.79`; the visibility contract prohibits a fake surface created for camera convenience.

**Remove the surface, trim, and roller. Do not relocate them.** Inactive state is the real bare wall. A later active state may add a luminous 16:9 rectangle and controlled spill on that wall, not an emissive television or roll-down screen.

## Desk-specific audit

The desk should be **partially reused at the authority/blocking level and rebuilt at the visible-object level**.

| Dimension | Real room/product | Current preview | Decision |
|---|---|---|---|
| L-shape/orientation | Main run plus perpendicular storage return between desk and bed | Accepted main/return footprints and bridge | Preserve footprint, junction, and chirality. |
| Return/file cabinet | Visible cubbies/shelf/drawer/bin faces; projector on top | Solid dark block | Rebuild visible cabinet architecture. |
| Desktop | Gray wood/laminate, restrained grain, rounded outer corners, black frame | Brown cap only on main run | Remove cap; one coherent gray surface across the system. |
| Thickness/support | Thin top on black open rectangular frame | Generic four-post/open-leg concept | Reuse concept; refine rails/corners. |
| Monitor | Centered with base on top | Panel/stand substantially below top | Rebuild vertical assembly. |
| Blue Yeti | Right of monitor on circular stand | Generic proxy; final side needs reflected-view check | Rebuild and verify seated composition. |
| Lamps | L2 far left, L5 far right/rear | Rough anchors right; shapes wrong | Preserve anchors; custom-recreate. |
| Chair | Centered at main run and able to tuck in | Centered blocker; bulky duplicate geometry | Preserve center; replace mesh and check return clearance. |
| Wall proximity | Main tight to wall; return tight to side wall with tiny bed gap | Accepted relationship | Preserve. |

Stop stacking corrective surfaces over the base desk. Build one `BurgenerDesk` group with main top, steel frame, return top, cabinet/open bays, and visible drawer/bin faces, using the accepted footprints as anchors and a single top-height authority.

## Bed-specific audit

The blocker gets the broad relationship right: low upholstered base, mattress, separate headboard, and low foot end. It does not read as the Braya.

The real bed has gray woven upholstery; two broad horizontal padded headboard bands; narrow raised side wings/posts; substantial upholstered side/foot rails; a low storage-platform silhouette; and white puffy bedding with beige/cream sheets and pillows. The preview has a warm single-slab headboard, simplified rails, and several flat decorative overlays. `furniture-v2.js` already adds two pillows; `bedroom-v1.js` adds another pair plus fold/throw/seams.

Preserve footprint, headboard side, and broad height. Replace the finished geometry with a near-exact custom Braya frame and one bedding assembly. Hidden hydraulic hardware does not need to animate; silhouette, upholstery, channels, rails, and mattress relationship do.

## Chair-specific audit

The HomeZeer chair is a recognizable white-and-chrome object: stitched white padded back/seat, chrome arms with white padded tops, chrome lift/five-star base, and casters. The base blocker uses boxes/ellipses; `bedroom-v1.js` adds taupe slabs and a flat dark base, duplicating and muddying it.

Preserve the accepted chair center/facing relationship. Replace all visible chair primitives with one near-exact group. At whole-apartment scale, the arm loops, white stitched back, chrome five-star base, and caster silhouette matter more than small adjustment controls.

## Projector-specific audit

The plan relationship is right: projector on the return near the bed, aimed toward the wall opposite the bed. The finished object is physically impossible:

- blocker z `82..98` is below desktop z about `100..103.5`;
- new body z about `97.1..100.5` remains inside/below the top;
- lens center z `90` is below the top;
- `rotateX(Math.PI / 2)` turns the cylinder's Y axis into the Z axis, so the lens barrel points vertically;
- the new body is only 3.4 GU high, unlike the substantial 5.5-inch Epson chassis;
- thin slab/jewel styling misses the large dark lens and paired front-grille character.

Create one near-exact Epson 3010/H421A group from official dimensions and the room photo. Put feet/body entirely above the worktop; aim the front face and horizontal lens axis toward the divider; leave credible bed and rear-cable clearance.

## Monitor, mic, and lamp audit

### Monitor

Use the official 614 mm width and 517.8 mm overall height-with-stand as scale authority. Keep the accepted center/orientation, but do not silently change fingerprinted annotation data if exact width conflicts; record any envelope correction for explicit approval. Base, neck, and panel must all be above the desk.

### Blue Yeti

The photos show an original-style black Yeti on Anthony's right of the monitor, directly on its broad circular stand. Its side yoke, knobs, capsule grille, and round base are the recognition features and are simple enough for a near-exact model.

Because presentation is reflected, judge side correctness from the seated/desk-facing debug view rather than raw x ordering alone. Final requirement: it must appear on Anthony's right of the monitor in the real-use composition.

### Left L2

Large cream cylindrical drum, dark trim, and large faceted gray base. Current conical shade/thin stem is wrong. Build a faithful custom recreation; no seeded/transparent material.

### Right L5

Long rectangular white marble base, thin brass stem, curved top hook, hanging seeded-glass cylinder, visible bulb. Current circular base/centered stem/cone is wrong. Marble slab, hook, glass cylinder, and bulb position are the minimum readable features.

## Exact vs custom vs generic

| Object | Tier/decision |
|---|---|
| Burgener desk/return | Tier 1 near-exact product match, custom-built; dominant known silhouette. |
| Braya bed | Tier 1 near-exact product match, custom-built; no hidden hydraulic internals required. |
| HomeZeer chair | Tier 1 near-exact custom geometry. |
| Samsung monitor | Tier 1 near-exact custom geometry from official dimensions. |
| Epson 3010/H421A | Tier 1 near-exact custom geometry and physical aim. |
| Blue Yeti | Tier 1 near-exact custom geometry and known placement. |
| L2/L5 lamps | Tier 2 faithful custom recreations; exact products unknown, close photos strong. |
| Bedding/blinds/wall art | Tier 2 faithful custom recreation. |
| PC/headphones/Alexa/laptop stand | Tier 2 if hero-readable; otherwise restrained Tier 3. |
| Cables, papers, bottles, remotes, variable clutter | Tier 3 or omit; never focal. |

## Minimum fidelity bar before more polish

1. Fictional window-wall screen is gone; inactive projection destination is bare wall.
2. Main desk/return read as one gray/black Burgener system with open frame and storage architecture.
3. Monitor and projector sit entirely above their supports with no buried parts.
4. Braya headboard bands/wings and gray upholstered rails are recognizable.
5. HomeZeer chair reads white leather/chrome with arms, five-star base, and casters.
6. Samsung, Blue Yeti, L2, and L5 are identifiable by silhouette from desk side.
7. Mic is on Anthony's right of the monitor in the seated view.
8. Room uses gray wall-to-wall carpet and real white blinds without opening changes.
9. All eight required orbit views show no collision, floating part, penetration, or false object.
10. Bedroom is recognizable in neutral light with display emissive, projector glow, and new point light disabled.

## Preserve, remove, rebuild

### Preserve

| Current item | Disposition/rationale |
|---|---|
| GeometryScene, architecture, cutaway, reflection | Preserve; highest-confidence spatial authority. |
| Existing centers and bed/desk/chair/projector relationships | Preserve as anchors. |
| `furniture-v2.js` L-top bridge concept | Preserve or absorb into new desk group. |
| Under-desk PC relationship | Preserve; owner-verified. |
| `main-v3.js` bedroom-layer seam | Preserve as bounded rebuild surface. |
| `?debug=1` OrbitControls | Preserve as developer/review tool only. |
| `PRESENTATION_FIT_MARGIN = 1.06` | Preserve independently as a candidate; accept only after clean all-corner normal-mode capture. |
| Background/stage/CSS tone changes | Park; do not use as fidelity evidence. |

The desktop scale/presence change is worth retaining independently. It preserves Camera v2's family, target, FOV, reflection, and responsive corner-fit algorithm. The anomalous `apartment-canvas-after.png` means 1.06 is **provisionally retained, not visually accepted** until a fresh normal-mode capture proves containment.

### Remove

- Projection surface, trim, and roller.
- Brown/walnut main-only desk cap and unsupported decorative edge.
- Generic desk mat unless verified after the desk is correct.
- Duplicate taupe chair overlays.
- Duplicate monitor slab/display line.
- Brown throw/runner, invented seams, and overlapping pillow/fold layers.
- Inset carpet border/band.
- Static warm desk point light until neutral object acceptance.
- README claims that the north-wall screen is valid.

### Rebuild

1. Epson support/placement and false-screen removal.
2. Coherent Burgener main/return group.
3. Braya frame and single bedding group.
4. HomeZeer chair.
5. Samsung and Blue Yeti.
6. L2 and L5.
7. Gray carpet and white blinds.
8. Only then, confirmed secondary identity objects.

## Missing references and verification gaps

Unavailable files:

- `/mnt/data/bedframe.rar`
- `/mnt/data/desk.rar`
- `/mnt/data/bedroomChair.rar`

Useful additional evidence:

- straight-on and three-quarter return photos with projector briefly removed;
- side/rear Epson photo showing feet, cables, clearance, and aim;
- measured desk height/top thickness for GU scale;
- confirmation that official 614 mm monitor width controls render scale;
- lamp heights/base dimensions or product names;
- confirmation that the draped laptop stand is persistent;
- PC case model/photo if expected to be visible.

Required debug capture set before visual acceptance:

- default hero;
- overhead bedroom;
- desk side;
- chair/monitor side;
- bed side;
- projector wall;
- window side;
- doorway into bedroom.

Record camera position/target for repeatable comparisons. Code-level collisions and false objects are already established; hidden-side craftsmanship cannot be signed off without these views.

## Prioritized next implementation plan

### P0 — false identity and physical impossibilities

1. Delete window-wall screen/trim/roller and revise README.
2. Rebuild Epson entirely above return with horizontal aim.
3. Replace brown overlays with coherent gray/black Burgener desk/return and visible storage.
4. Rebuild monitor entirely above desk.

Acceptance: neutral debug views show no window obstruction, buried hardware, false screen, or broken L identity.

### P1 — recognizable anchors

5. Rebuild Braya frame/headboard and consolidate bedding.
6. Rebuild HomeZeer chair.
7. Rebuild Samsung, Blue Yeti, and both lamps.
8. Replace carpet banding and add white blinds.

Acceptance: reviewer identifies all Tier 1 objects and both lamps without labels or lighting.

### P2 — personal identity with restraint

9. Add real wall art and only confirmed persistent objects.
10. Refine PC/headphones/Alexa to whole-apartment readability.
11. Capture eight fixed orbit views and correct collisions/scale without architecture changes.

After this gate, reassess background tones and 1.06 fit margin, resume neutral materials, then design desk-active lighting and projector-active wall luminance/spill.

## Do not do yet

- No broad lighting, bloom, ambiance, or cinematic state pass.
- No active projector image, animation, or device behavior.
- No invented physical screen.
- No Camera v2, reflection, cutaway, opening, proportion, or fingerprint changes.
- No generic replacement for a Tier 1 identity object.
- No prominent invented decor or attempts to hide defects with darkness/glow.
- No commit, merge, deployment, hardware write, or canonical-main edit.

## Cross-chat handoff

No cross-chat handoff is needed yet. The next pass is a bounded local static-object rebuild. Handoff becomes relevant only for projector/device state, production lighting policy, automatic camera triggers, or runtime behavior.
