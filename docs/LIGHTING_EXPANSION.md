# Hue Expansion Plan — Apartment Lighting Buildout

**Audited:** August 5, 2026  
**Fit update:** August 5, 2026 — plant-zone space confirmed, Flux cable route measured at 60 in, bedroom cabinet measured at 39 × 16 × 29 in.  
**Plant-wash calibration:** August 24, 2026 — installed and paired as Hue/HomeHub ID 6, `Plant Wash`.
**Status:** Current expansion plan with the completed plant-wash result recorded below.
**Price basis:** Regular US list prices observed on August 5, 2026. Temporary sales, coupon codes, tax, shipping, raceway, and small installation supplies are excluded unless noted.

---

## 1. Executive decision

The apartment does not need a large number of exposed smart-light fixtures. It needs a small number of deliberately placed **light layers**:

1. **A low wall/plant wash** at the right side of the living-room sofa, with
   partial fixture visibility accepted at the open-frame stand.
2. **A broad horizontal cabinet-top wash** across the kitchen.
3. **Two separate high-CRI task lights** over the useful kitchen counters.
4. **Physical scene control** that is faster than opening HomeHub or the Hue app.
5. **Low-level path lighting** in the entry/bathroom/closet areas.
6. A later **side-wall bedroom layer** that never spills onto the projector image.

The two primary visual scene families are:

- **`connor_color`** — coral/peach architectural wash, teal/blue-violet vertical accents, restrained magenta/cyan details, and one warm anchor.
- **`listening_bar`** — dark amber, burgundy, bronze, muted olive, warm picture/console light, and intentional negative space.

The first purchases should be the living-room plant wash and the kitchen cabinet cove. They correct the apartment's two largest nighttime imbalances: the dark right end of the sofa wall and the kitchen's two bright pendants floating in a dark volume.

---

## 2. Verified apartment constraints

These are the physical facts used by this audit.

### Existing Hue layout

- **L1** — living-room shaded lamp.
- **L2** — bedroom desk lamp left.
- **L3/L4** — kitchen pendants.
- **L5** — bedroom desk lamp right.
- **L6** — Plant Wash, Hue Play Light Bar on the rear living-room plant stand.

Future lights should not receive permanent L7/etc. labels until they are paired and their actual Hue IDs are known.

### Kitchen

- Upper-cabinet top run: **exactly 12 ft / 144 in**, uninterrupted.
- Cabinet top to ceiling: **9 in**.
- No outlet above cabinets.
- Useful backsplash outlets:
  - left outlet behind the Keurig;
  - right outlet behind the air fryer.
- Under-cabinet spans, left to right:
  - 22 in useful counter;
  - 30 in microwave/range;
  - 22 in useful counter;
  - 35 in above refrigerator;
  - stacked pantry cabinets.
- Only the two **22 in counter spans** need dedicated task bars.
- The microwave's built-in light should serve the range.
- The refrigerator span is not a useful work surface.

### Living-room plant bay

- Couch back sits firmly against the wall.
- Couch arm to cabinet: **36 in**.
- Bottom of couch arm: **20 in above floor**.
- Front plant stand: **23.5 in high × 9 in wide**.
- Rear stand: **27.5 in high × 10 in wide**.
- Two free receptacles are available in the plant area.
- A 4 × 4 in floor footprint exists inside a stand.
- The stands use thin, open black legs. A tall solid lamp body remains visible through them.

### Bedroom

- Headboard sits against the wall.
- Lifting/storage bed frame means cables must never cross the moving platform, hinge path, or lifting mechanism.
- There is no practical floor-lamp space beside the bed.
- Outlets exist on both sides.
- The projector image occupies most of the projection wall.
- Any new mood light must illuminate a side wall, headboard plane, furniture face, or rear/low plane — never the projection wall.

### Bathroom and closet

- Existing fixtures appear integrated rather than replaceable-bulb fixtures.
- Both closet doors are hinged and can remain open.
- The closet is commonly left open for extended periods, so a door contact sensor would not represent actual occupancy.

### Corrected apartment description

The prior plan contained outdated or inaccurate room assumptions:

- The kitchen has a clean white cabinet-top cove, **not exposed industrial ductwork** above the cabinets.
- The living-room window has **horizontal blinds**, not vertical blinds.
- The floor plan includes a balcony; it should not be described as an apartment with no outdoor zone.
- The projector wall cannot accept a general wall wash during watching.

---

## 3. Design direction

The inspiration images favor **illuminated planes rather than visible gadgets**:

- ceiling/cove wash;
- vertical wall or column wash;
- plants and artwork catching colored light;
- small pools of warm light;
- low visible “jewel” lights used sparingly;
- dark areas between lit surfaces;
- warm light retained even in colorful scenes.

This should remain a warm modern listening-lounge apartment, not become a gaming-room installation. The safeguards are:

- keep one warm anchor in colorful scenes;
- avoid making every light the same color;
- keep saturation lower on large architectural surfaces;
- reserve brighter saturation for smaller plant, pendant, or console accents;
- preserve the center sofa wall for oversized art;
- conceal wiring and light sources wherever possible;
- use no more than one deliberate visible accent lamp in the living room.

---

# 4. Where to start

## Phase 1 — Correct the open-plan room

**Current issue sequence:** [#147](https://github.com/agatte/home-hub/issues/147)
owns the Play Light Bar plant/wall wash, followed by
[#148](https://github.com/agatte/home-hub/issues/148) for the Flux cabinet
cove. A motion sensor is not a Phase-1 purchase: revisit
[#13](https://github.com/agatte/home-hub/issues/13) only if the bounded
[#137](https://github.com/agatte/home-hub/issues/137) kitchen/path inference
trial demonstrates that dedicated occupancy evidence is needed.

### 1A. Living-room plant wash

**Installed result:** one **Hue Play Light Bar single pack**, paired as Hue/v1 ID **6** and named **Plant Wash**.

- Regular price: **$109.99**
- Output: **500 lm**
- Size: approximately **10 in long × 1 7/16 in high**
- Cable: approximately **2 m / 6.6 ft**
- Can lie horizontally.
- Base kit includes a power supply that can support up to three Play bars.

Official product:  
https://www.philips-hue.com/en-us/p/hue-play-light-bar/7820130U7

**Why it wins here**

- Its very low height is easier to hide than an 8 in uplight can, a 24 in Play Table lamp, or a 53 in Play Floor lamp.
- It creates a broad wall wash and softer plant shadows.
- The 10 in length fits easily within the 36 in bay.
- The outlets are already within practical cable distance.
- Its power supply leaves an upgrade path for another Play bar later.

**Fit and calibration status: complete**

The bar is horizontal on the back edge of the rear/taller plant stand. Its broad face aims up the wall with a slight left bias toward the couch and plant mass. Full fixture concealment is not physically possible through the thin open stand frame; the remaining housing visibility is accepted.

- Couch sightline passed.
- Kitchen/island sightline passed.
- Entry sightline passed.
- The observed direct LED/glare level from all three views is accepted.

**Real-room color and brightness result**

- The original 10–20% starting assumption is disproven; it does not produce the intended architectural read.
- Teal/blue-violet at approximately 70–75% is a successful reference for the `connor_color` direction.
- Saturated deep blue is effective but too dominant for ordinary architectural scenes.
- Amber and burgundy are accepted after dark. Phone photos are not reliable evidence for their in-room appearance.
- L1 remains the warm anchor in colorful scenes.
- Entertainment/screen-sync membership remains deferred; L6 is not an automatic sync target.

### 1B. Kitchen cabinet-top cove

**Recommendation:** **Hue Flux strip light 16 ft**, cut only at the permitted cut mark nearest the 12 ft run.

- Regular price: **$99.99**
- Output: **2,000 lm**
- Actual listed length: approximately **196 7/8 in**
- Cuttable, reconnectable, reusable, and extendable.
- Designed for concealed indirect wall washing.
- Official Hue US store status during this audit: temporarily out of stock.

Official product:  
https://www.philips-hue.com/en-us/p/lightstrips-flux-strip-light-16ft/046677607814

Recommended supporting parts:

- **Flux 16 ft low-voltage extension cable** — $14.99  
  https://www.philips-hue.com/en-us/p/lightstrips-hue-flux-strip-light-extension-cable-16ft/046677606305
- **Flux bracket 10-pack** — $11.99  
  https://www.philips-hue.com/en-us/products/smart-light-strips?page=2

**List-price kitchen-cove package:** **$126.97**, before white raceway and tax.

**Placement**

- Start by dry-fitting the strip roughly **2–3 in behind the cabinet front edge**.
- Test it flat, then test a slight backward/upward aim.
- Do not permanently attach it until viewed from:
  - the couch;
  - the island;
  - the entry;
  - immediately in front of the kitchen.
- The preferred result is a broad ceiling halo, not a bright narrow line at the rear wall.
- Use brackets or a removable channel rather than trusting adhesive on the dusty cabinet top.

**Power route**

- Use the left outlet behind the Keurig.
- Keep the power supply/controller low near that outlet where practical.
- Run the official low-voltage extension cable vertically in a narrow white raceway at the far-left cabinet edge.
- Enter the cabinet-top area at the upper-left corner.
- Do not use a permanently routed thin household extension cord above the cabinets.

**Route status: confirmed**

The measured route from the Keurig outlet to the intended cabinet-top connection is **60 in / 5 ft**. The official 16 ft low-voltage extension cable is therefore comfortably long enough. Plan the raceway and controller location so the excess cable can be managed out of sight without tight coils, pinching, or heat buildup.

### Phase 1 cost

| Item | Regular price |
|---|---:|
| Hue Play Light Bar single | $109.99 |
| Hue Flux 16 ft | $99.99 |
| Flux low-voltage extension cable | $14.99 |
| Flux bracket 10-pack | $11.99 |
| Hue Tap Dial, added below | $54.99 |
| **Phase 1 total** | **$291.95** |

This total excludes tax, raceway, and any temporary Hue promotions.

---

## Phase 2 — Physical control and kitchen task light

### 2A. Hue Tap Dial

**Recommendation:** buy after the first two new light layers are installed.

- Regular price: **$54.99**
- Battery powered; uses a replaceable battery.
- It is **not kinetic and not battery-free**.
- Four buttons can control scenes/rooms/zones, and the dial adjusts brightness.

Official product:  
https://www.philips-hue.com/en-us/p/hue-tap-dial-switch/046677578800

Recommended button layout:

1. `cooking`
2. `connor_color`
3. `listening_bar`
4. `projector_night` or `all_off`

Recommended dial target:

- an **open-plan ambient zone** containing L1, the plant wash, cabinet cove, and kitchen pendants;
- task bars should remain separately controllable during cooking.

### 2B. Two IKEA SKYDRAG 18 in task bars

**Recommendation:** two 18 in bars, one centered under each 22 in useful cabinet.

Each bar:

- Regular price: **$32**
- Size: **18 × 1 × 1 in**
- Output: **260 lm**
- Power: **4 W**
- Cord: **11 ft 6 in**
- CRI: **>90**

Official product:  
https://www.ikea.com/us/en/p/skydrag-led-cntp-wrd-lght-strp-w-sensor-dimmable-white-00439595/

Supporting components:

- **TRÅDFRI 10 W driver** — $35
- **ANSLUTA 11 ft 6 in power cord** — $12

Official driver:  
https://www.ikea.com/us/en/p/tradfri-driver-for-wireless-control-smart-gray-10356189/

**Two-bar package:** **$111** before tax.

The two bars draw 8 W total, below the 10 W driver's limit. The driver supports up to three units provided total wattage remains at or under 10 W.

**Physical fit**

- Each 18 in bar leaves about **2 in of margin at each end** of a 22 in cabinet.
- Install behind the cabinet's front lip so the hardware is hidden and the light reaches the counter.
- Do not install a separate bar under the microwave.
- Do not install one above the refrigerator.

**Compatibility caution**

IKEA says smart-lighting products with software 1.2.x or later can pair directly to a Hue Bridge after a factory reset, but firmware level and behavior must be verified on the actual driver. Pair and test the driver near the Bridge before permanently routing its long cables.

IKEA Hue-Bridge guidance:  
https://www.ikea.com/us/en/customer-service/product-support/smart-lighting/how-to-use-smart-lighting-pub53d86412/

**Fallback if direct Hue pairing is unreliable**

Use fixed high-CRI task bars through a **Hue Smart Plug**.

- Hue Smart Plug regular price: **$37.99**
- Smart Plug provides on/off control only; it does not add dimming to a non-dimmable fixture.

Official product:  
https://www.philips-hue.com/en-us/p/hue-smart-plug/046677552343

### Phase 2 running total

- Phase 1: $291.95
- Two SKYDRAG bars + driver + ANSLUTA cord: $111
- **Running total: $402.95**

---

## Phase 3 — Entry/path automation

### Hue indoor motion sensor

**Recommendation:** add after the plant wash and cabinet cove create suitable arrival/path endpoints.

- Regular price: **$48.99**
- Battery powered.
- Can change behavior by time of day.
- Includes daylight sensing.
- Best initial location: entry/hall, aimed across the walking path rather than broadly into the living room.

Official product:  
https://www.philips-hue.com/en-us/products/all-products/product-page.hue_motion-sensor_indoor

**Initial bridge-native behavior**

- Daylight sufficient: no action.
- Evening entry: warm cabinet cove + very low plant wash.
- Overnight: only a low warm path layer.
- Do not let the sensor activate all living-room lights or overwrite a deliberate listening/projector scene.

**Running total with sensor:** **$451.94**

### Bathroom and closet

Do **not** buy a Hue motion sensor for these zones until there is a controllable light endpoint. Their integrated fixtures cannot be controlled merely by adding a sensor.

Immediate renter-friendly option:

- warm-white rechargeable motion bars;
- place low under the vanity/toe-kick and inside the closet;
- keep bathroom overnight output very low.

Longer-term integrated option:

- renter/landlord-approved smart switch or relay;
- separate implementation and electrical-safety review.

### Closet contact sensor

**Rejected.** Since the doors often remain open, door state is not occupancy state.

### Front-door contact sensor

**Deferred.** It can become useful later for arrival/departure intent, but HomeHub should first gain accessory-event ingestion and a clear authority policy.

Hue Secure contact sensor regular prices observed:

- 2-pack: **$69.99**

Official product:  
https://www.philips-hue.com/en-us/p/hue-secure-contact-sensor/046677580872

---

## Phase 4 — Bedroom side-wall layer

### Conditional recommendation: Hue Play Table lamp

- Regular price: **$79.99**
- Size: approximately **23 15/16 in tall × 3 9/16 in square**
- Output: **400 lm**
- Gradient RGBWWIC light.
- Cable: approximately **1.5 m / 4.9 ft**

Official product:  
https://www.philips-hue.com/en-us/p/hue-white-and-color-ambiance-hue-play-table-lamp/046677610791

**Rejected for the living-room plant bay**

Although its 3.56 in square base fits the measured 4 × 4 in footprint, its nearly 24 in solid black body would be obvious through the thin plant-stand legs.

**Possible bedroom role**

The top of the projector/cubby cabinet may support it, aimed toward:

- the desk-side wall;
- the headboard-side wall;
- the corner between those surfaces.

It must not face or spill onto the projection wall.

**Cabinet fit status**

The projector/cubby cabinet measures **39 in long × 16 in deep × 29 in high**. That overall top surface is physically large enough for the Play Table lamp's roughly 3.6 in square footprint.

Before purchase, only the exact usable portion of the top still needs to be checked against the projector itself:

- keep the lamp out of the projector's intake/exhaust path;
- keep it clear of controls, lens, and cable bends;
- aim it toward the side/headboard wall, never the projection wall;
- confirm the available outlet route does not cross the lifting bed mechanism.

The cabinet envelope is no longer a fit concern; projector clearance and aiming are the remaining placement checks.

**Running total if approved later:** **$531.93**

---

# 5. Living-room plant-zone three-way audit

## Option 1 — Hue Play Light Bar single

**Decision: installed and calibrated as L6 / Plant Wash**

| Attribute | Assessment |
|---|---|
| Price | $109.99 |
| Output | 500 lm |
| Physical form | 10 in long; very low when laid horizontally |
| Concealment | Partial; accepted with the thin open stand geometry |
| Beam | Broad, soft wash |
| Plant shadows | Softer, more diffuse |
| Cable | About 6.6 ft; outlets nearby |
| HomeHub/Hue support | Native Hue |
| Final placement | Horizontal on back edge of rear/taller stand, upward with slight left bias |
| Sightlines | Couch, kitchen/island, and entry glare tests passed |
| Calibrated use | Teal/blue-violet at ~70–75%; amber/burgundy after dark |

This is only about $7 more than the verified two-can GU10 package plus one Hue GU10 bulb, while being lower, easier to hide, and fully integrated.

## Option 2 — Compact black GU10 uplight + Hue GU10 bulb

**Decision: conditional alternative**

Hue GU10 bulb:

- Regular price: **$59.99**
- Output: **450 lm**
- Size: approximately **2 in diameter × 2.25 in high**
- 2000–6500 K, full color.

Official bulb:  
https://www.philips-hue.com/en-us/p/hue-white-and-color-ambiance-gu10-smart-spotlight/046677584658

Verified fixture example:

- SUNVIE two-pack black indoor uplights at Walmart
- Observed price: **$42.99**
- Each can: about **8 in high × 3.5 in wide**
- Includes GU10 bulbs, 5.9 ft cord, and foot switch.

Retail listing:  
https://www.walmart.com/ip/10565607413

Package using one Hue GU10:

- fixture two-pack: $42.99
- one Hue color GU10: $59.99
- **total: $102.98**

| Attribute | Assessment |
|---|---|
| Concealment | Better than a tall column, worse than horizontal Play Bar |
| Beam | Focused cone |
| Plant shadows | Stronger and more dramatic |
| Inspiration match | Excellent for a defined vertical column |
| Visual risk | 8 in can may remain visible through open stand |
| Value | Nearly same total as Play Bar; includes spare can/bulbs |
| Best placement | Behind rear stand, close to wall |

Choose this only when a flashlight/temporary spotlight test proves that the focused beam looks substantially better than the broad Play Bar wash.

A cheaper GU10 can may exist, but exact dimensions and heat/clearance must be verified before treating it as a fit.

## Option 3 — Hue Play Table lamp

**Decision: reject for plant bay; conditional bedroom option**

| Attribute | Assessment |
|---|---|
| Price | $79.99 |
| Footprint | Fits 4 × 4 in space |
| Height | Nearly 24 in |
| Concealment | Poor through thin open stands |
| Beam | Vertical gradient |
| Plant-bay result | Visible technological column |
| Better role | Bedroom furniture-top side-wall wash |

## Previously considered Play Floor lamp large

**Decision: reject for plant bay**

- Regular price: **$149.99**
- Height: approximately **53 in**
- The footprint fits, but the long solid black body would be obvious from couch and kitchen viewpoints.

Official product:  
https://www.philips-hue.com/en-us/p/hue-white-and-color-ambiance-hue-play-floor-lamp-large/046677610821

---

# 6. Kitchen strip decision

## Hue Flux 16 ft — selected

Why it matches the apartment:

- The run is exactly 12 ft.
- Flux is long enough to cut at a supported mark near 12 ft.
- It is designed for concealed indirect light.
- Its visible LED construction is irrelevant because the source will be hidden.
- It can be cut, reused, and extended.
- It costs less than OmniGlow.

## Hue OmniGlow 10 ft — rejected for the cabinet run

- Regular price: **$139.99**
- Length: approximately **10 ft / 118 in**
- Output: up to **2,700 lm**
- Dot-free direct or indirect light.
- Cuttable but non-extendable.

Official product:  
https://www.philips-hue.com/en-us/p/lightstrips-omniglow-strip-light-10ft/046677608170

Why it loses here:

- Centering it on a 12 ft run leaves about **12 in unlit at each end**.
- The cove is only 9 in high, so end falloff is more likely to be apparent.
- Its dot-free visible-light premium is wasted in a concealed installation.
- It cannot be extended to solve the missing length.

Official Hue comparison describes Flux as the concealed/indirect system and OmniGlow as suitable for visible direct light as well as concealed use:  
https://www.philips-hue.com/en-us/explore-hue/propositions/smart-strip-lights

## Do not reuse the leftover Flux under the cabinets

The remaining cut strip should be stored, not routed under the two counters.

Reasons:

1. The top and bottom pieces would remain one controller and one logical Hue light.
2. The cove and task layers could not independently use different colors/temperatures.
3. The 30 in microwave gap exceeds the official Flux flex connector's approximately 19 11/16 in span.
4. Flux has CRI 80, while SKYDRAG is rated above CRI 90.
5. The air-fryer area adds heat/grease exposure.
6. A visible LED strip reflected in glossy tile is less refined than a diffused linear task bar.

Official flex connector:

- $29.99
- approximately 19 11/16 in long

https://www.philips-hue.com/en-us/p/lightstrips-hue-flux-flex-connector-4-pack/046677606336

---

# 7. Room-by-room plan

## Living room

### Install now

- Existing L1 remains the warm anchor.
- Add one low concealed Play Bar in the right plant bay.
- Keep the center sofa wall relatively quiet for oversized artwork.

### Add after furniture/art decisions

- A warm picture light after the artwork's exact width, frame, and hanging height are known.
- One visible decorative “jewel” light on the future media console after the TV is wall-mounted and the current stand is removed.

### Do not use here now

- Iris on the coffee table: visible power cord and direct sightline.
- Hue Go on the floor as permanent architecture.
- Play Floor/Signe in the plant bay: visible tall column.
- Festavia behind the blinds: the horizontal blinds and small room make it likely to read as exposed string light rather than integrated architecture.

## Kitchen

### Install now

- 16 ft Flux cove, cut to supported mark near 12 ft.
- Two 18 in SKYDRAG task bars.
- Tap Dial accessible from cooking/open-plan area.

### Keep separate

- Cabinet cove = ambient/architectural layer.
- Task bars = functional food-prep layer.
- Pendants = island accents and functional fill.

### Later

- Reassess entry illumination after cove installation; reflected cove light may remove the need for a dedicated entry lamp.

## Bedroom

### Current priority

Lower than living-room and kitchen because the room already has two emitters.

### Conditional addition

- Play Table lamp on projector/cubby furniture only after fit measurements.
- Aim at side/headboard plane.
- During projector viewing, use 1–5% warm amber, deep red, or subdued violet.
- Never wash the projection wall.

### Under-bed

Only consider very low warm path light attached to the **stationary base**. Do not attach a strip or cable to the lifting platform.

### Reject/defer

- Signe floor lamp: no practical floor location.
- Wall Washer toward projector wall: harms image contrast.
- Twilight: too costly and requires a suitable bedside surface.
- Sync Box: major expense and not necessary while HomeHub's PC/projector path remains functional.

## Entry/hall

### Evidence-gated follow-up

- Revisit a Hue motion sensor only after #137 records missed visits or false
  activations that justify dedicated occupancy evidence.
- If warranted, use narrow, conservative arrival/path behavior with the
  cabinet cove and plant wash as endpoints; do not overwrite an established
  watching, listening, projector, or task-light atmosphere.

### Later

- Front-door contact sensor only after accessory events and intent precedence are designed in HomeHub.

## Bathroom

- Existing integrated fixtures are not controllable with a Hue bulb.
- Immediate solution: low warm rechargeable motion bar under vanity/toe-kick.
- Do not activate full ceiling/vanity light overnight unless needed.
- Smart-switch/relay integration requires authorization and a separate electrical-safety project.

## Closet

- Contact sensor rejected because doors remain open.
- Use an internal rechargeable motion/occupancy bar.
- A later smart-switch solution is possible if authorized.

## Balcony

The balcony is a legitimate future zone, but it should remain restrained:

- one warm portable/outdoor-rated lamp;
- or low plant/railing illumination;
- no dense string-light installation until outlet, weather, lease, and sightline details are documented.

---

# 8. Scene design

The broader scene families remain design targets. Plant Wash guidance below is
the completed real-room calibration boundary and supersedes the original paper
brightness assumptions.

## `connor_color`

| Layer | Starting role |
|---|---|
| L1 living-room lamp | Warm 2200–2500 K, 20–35% |
| L6 Plant Wash | Teal/blue-violet, approximately 70–75% reference; avoid ordinary saturated deep blue |
| Cabinet Flux | Muted coral/peach/red-orange, 20–35% |
| Kitchen pendants | Magenta/violet/cyan, 5–15% |
| Counter task bars | Off |
| Center sofa wall | Mostly dark |

Rule: retain the warm L1 anchor so the apartment does not become a gaming-room palette.

## `listening_bar`

| Layer | Starting role |
|---|---|
| L1 | Deep warm white/amber |
| L6 Plant Wash | Amber/burgundy accepted after dark; tune by eye in-room, not from phone photos |
| Cabinet Flux | 2200 K amber or subdued burnt orange at 15–25% |
| Pendants | Amber at 3–8%, or off |
| Future picture light | Focused warm white |
| Future console jewel | Very low amber |

Rule: objects and vertical surfaces should emerge from darkness; do not turn every light the same orange.

## `cooking`

- SKYDRAG bars: bright neutral/warm-neutral white.
- Flux: white or very low-saturation warm tone.
- Pendants: functional warm/neutral fill.
- L1/plant wash: low enough not to distort the work zone.
- Task bars may be brighter than all decorative lights.

## `relax`

- Warm anchor plus one subdued complementary color.
- Pendants should stop being the brightest objects in the kitchen after Flux is installed.
- Avoid identical hue/brightness across all lights.

## `projector_night`

- Bedroom lights at 1–5%.
- Warm amber, deep red, or subdued violet.
- No output on projection wall.
- New Play Table, if approved, should only illuminate a side/headboard plane.

## `night_path`

- Very low, very warm, low-plane light.
- Avoid ceiling fixtures.
- Motion timeout should be long enough to prevent darkness while stationary in the bathroom.

---

# 9. Updated product master list

Prices are regular US prices observed August 5, 2026 and may change.

## A. Buy / plan now

| Product | Regular price | Intended location | Fit status | Decision |
|---|---:|---|---|---|
| Hue Play Light Bar single | $109.99 | Behind rear living-room plant stand/baseboard | **Fit confirmed; stands can be repositioned** | **First purchase** |
| Hue Flux 16 ft | $99.99 | Top of 12 ft kitchen cabinets | Length/cove fit confirmed | **First purchase** |
| Flux extension cable 16 ft | $14.99 | Keurig outlet to cabinet top | Verify route length | **Buy with Flux** |
| Flux bracket 10-pack | $11.99 | Cabinet top | Fits | **Buy with Flux** |
| Hue Tap Dial | $54.99 | Open-plan physical control | Fits; mount location flexible | **Buy after first layers** |
| 2× SKYDRAG 18 in | $64 | Two 22 in counter bays | Fit confirmed | **Phase 2** |
| TRÅDFRI 10 W driver | $35 | Hidden above/in cabinetry | Electrical capacity confirmed | **Phase 2 pilot** |
| ANSLUTA cord | $12 | Driver power | Route to be planned | **Required** |
| Hue indoor motion sensor | $48.99 | Entry/hall | Endpoint dependent | **Phase 3** |

## B. Conditional alternatives

| Product | Regular/observed price | Possible role | Condition |
|---|---:|---|---|
| Hue GU10 color bulb | $59.99 | Focused plant uplight | Use only in verified safe GU10 can |
| SUNVIE GU10 uplight 2-pack | $42.99 observed | Focused plant uplight | Mock up 8 × 3.5 in can visibility |
| Hue Play Table lamp | $79.99 | Bedroom furniture-top side wash | Cabinet envelope fits; verify projector airflow/throw clearance |
| Hue Smart Plug | $37.99 | Fixed-white decorative/task fixture | On/off only |
| Hue Dimmer Switch | $30.99 | Lower-cost physical control | Choose only if Tap Dial's four-button layout is unnecessary |
| Hue Smart Button | $32.99 | One-scene/automation trigger | Less capable than Tap Dial |

## C. Future after furniture/art decisions

| Product | Regular price | Future role | Why deferred |
|---|---:|---|---|
| Hue Iris | $120.99 | Visible media-console jewel | Wait for wall-mounted TV and console |
| Hue Go portable accent | $98.99 | Temporary/mobile accent | Not permanent hallway architecture |
| Warm picture light + Hue-compatible control | TBD | Oversized sofa art | Artwork must be selected first |
| Festavia 100 LED / 26 ft | $139.99 | Balcony or special display | Poor current fit behind horizontal blinds |
| Festavia 250 LED / 65 ft | $259.99 | Large future installation | Over-scale for current indoor surfaces |

## D. Defer or reject for this apartment

| Product | Regular price | Decision |
|---|---:|---|
| Hue Play Floor lamp large | $149.99 | Reject plant bay; tall body remains visible |
| Signe gradient floor lamp | $379.99 | Defer/reject; no appropriate floor location |
| Hue Play Wall Washer single | $229.99 | Defer; too broad/bright/expensive for plant bay and unsafe for projection wall |
| Twilight | $319.99 | Defer; no suitable bedside surface and low value versus current needs |
| OmniGlow 10 ft | $139.99 | Reject for 12 ft cabinet run |
| Dymera hardwired wall light | $249.99 | Reject absent approved junction-box project |
| Play HDMI Sync Box 8K | $384.99 | Defer; expensive separate entertainment project |
| TV Play gradient strips | size-dependent | Defer until final TV and source path are known |
| PC Play gradient strip 24–27 in | $169.99 | Only after exact monitor size and desk bias goal are confirmed |
| Play gradient tube large | $249.99 | Designed for 60 in+ TV use; no current placement |
| Bridge Pro | $139.99 | Not needed at present scale |

### Bridge Pro note

Bridge Pro supports 150+ lights and 50+ accessories and enables MotionAware. MotionAware needs at least three compatible lights arranged through an area; a dedicated physical motion sensor remains more targeted for this small apartment.

Official Bridge Pro:  
https://www.philips-hue.com/en-us/p/hue-bridge-pro/046677582111

MotionAware requirements:  
https://www.philips-hue.com/en-ph/support/article/motionawaretm--transform-your-hue-lights-into-motion-sensors/000011

---

# 10. HomeHub integration implications

This audit is based on the supplied repository snapshot.

## Current source-of-truth locations

- Mode and period states:  
  `backend/services/light_state_calculator.py::ACTIVITY_LIGHT_STATES`
- Automatic effect scope:  
  `backend/services/light_state_calculator.py::EFFECT_AUTO_MAP`
- Color preset buttons currently live in:  
  `frontend-svelte/src/lib/components/LightCard.svelte`
- `theme.js` currently supplies CT presets and broader UI design tokens; the old document's instruction to add limited-gamut color presets to `theme.js::LIGHT_COLOR_PRESETS` is stale.

## Hue v2 event limitation

`backend/services/hue_v2_service.py::_dispatch_stream_events()` currently ignores any v2 resource update whose type is not `"light"`.

Consequences:

- Hue light-state changes can update HomeHub.
- Tap Dial button events, Hue motion events, and contact-sensor events are not yet ingested as HomeHub accessory intent.
- Bridge-native rules can work immediately, but HomeHub cannot yet attribute or arbitrate those accessory events.

## Safe rollout policy

### Initial stage

- Let Hue Bridge rules control a narrow, dedicated behavior.
- Do not let a bridge-native sensor rewrite every light in the open-plan room.
- Keep motion behavior limited to arrival/path endpoints.
- Use the Tap Dial primarily through Hue scenes until HomeHub accessory ingestion exists.

### Later HomeHub work

Add:

1. accessory event ingestion;
2. source tagging for each light change;
3. precedence among:
   - physical manual control;
   - active scene/mode;
   - motion;
   - presence;
   - time/daylight;
   - HomeHub automation;
4. explicit manual-override duration;
5. diagnostic logging showing why each light changed.

## Adding each new light

L6 is now integrated as `plant_wash` / **Plant Wash** using its stable Hue/v1
ID `"6"`; no Hue v2 UUID is stored. Hue v2 discovers the corresponding UUID
from the bridge's `/light` resources on each fresh connection.

- Global off, sleeping, away, and uniform all-light safety paths include L6.
- Automatic mode/weather effects remain explicitly scoped to L1–L5. L6 stays
  static unless a future room calibration deliberately opts it in.
- Curated presets give L6 an explicit conservative off target so effect release
  is safe after a clean restart and established L1–L5 appearances do not drift.
- Manual explicitly all-light effect endpoints retain their literal semantics
  and therefore include L6. Per-light effect endpoints can target it directly.
- Bedroom screen sync remains L2/L5; Latitude laptop sync remains L1/L3/L4.
  L6 is not in bootstrap, Entertainment, or screen-sync target configuration.

After pairing:

1. Record its actual Hue/v1 ID and name.
2. Test reachability and CT/HSB behavior.
3. Add intentional state coverage to every relevant mode and period.
4. Do not copy one uniform state across all new fixtures.
5. Review `EFFECT_AUTO_MAP`; scoped effects exclude new lights until deliberately added.
6. Keep cabinet cove and counter task lights as separate logical layers.
7. Add the plant light to entertainment/sync only after deciding whether screen color should override the curated scene.
8. Update UI grouping only after stable IDs are known.

---

# 11. Installation and validation

## Plant wash

Completed August 24, 2026:

1. Installed horizontally on the back edge of the rear/taller plant stand.
2. Aimed upward with a slight left bias toward the couch/plant mass.
3. Accepted partial housing visibility imposed by the thin stand frame.
4. Passed couch, kitchen/island, and entry sightline/glare checks.
5. Disproved the 10–20% paper assumption; teal/blue-violet reads
   architecturally at approximately 70–75%.
6. Confirmed saturated deep blue is too dominant for ordinary scenes and
   accepted amber/burgundy after dark.
7. Paired as Hue/v1 ID 6 and named Plant Wash. Entertainment/screen-sync
   remains deferred.

## Cabinet Flux

1. Measure outlet-to-top raceway route.
2. Dry-fit full strip before cutting.
3. Identify the nearest legal cut mark to 144 in.
4. Test front/back position and aim.
5. Photograph from couch and entry at night.
6. Cut only after the wash is accepted.
7. Install with brackets/channel.
8. Store the remaining reusable strip and connectors.

## SKYDRAG

1. Pair the TRÅDFRI driver near the Hue Bridge before installation.
2. Verify both bars dim together reliably.
3. Run a multi-day test for reconnect/restart behavior.
4. Center bars in the 22 in bays.
5. Hide driver and cord without blocking appliance ventilation.
6. Keep the air-fryer exhaust path clear.
7. Use the bars as neutral task light, not decorative color.

## Motion sensor

1. Add only after suitable path endpoints exist.
2. Aim across the path.
3. Set daylight threshold.
4. Test day/evening/night behaviors.
5. Confirm it does not overwrite `connor_color`, `listening_bar`, or projector modes unexpectedly.

---

# 12. Remaining information needed

No more broad apartment photo survey is needed.

## Plant Play Bar

No remaining physical information is required. Installation, pairing,
sightline review, and real-room color/brightness calibration are complete; the
results are recorded in sections 4, 5, 8, 10, and 11.

## Flux power route

No additional route measurement is required. The confirmed route is **60 in / 5 ft**, comfortably within the official 16 ft extension cable.

## Bedroom Play Table

The cabinet envelope is confirmed at **39 × 16 × 29 in** and is large enough for the lamp. Before purchase, verify only:

- the projector's actual occupied footprint on the cabinet;
- intake/exhaust clearance;
- lens, controls, and cable clearance;
- the exact side-wall aiming angle;
- a safe outlet route that does not cross the lifting bed mechanism.

## Only if choosing the GU10 alternative

- One mockup using an object about 8 in high × 3.5 in wide behind the rear plant stand.
- A nighttime flashlight/spotlight test from couch and kitchen viewpoints.

---

# 13. Corrections from the previous master list

The following recommendations or statements have been removed or corrected:

- OmniGlow 10 ft is no longer the kitchen recommendation.
- The kitchen cove does not contain exposed industrial ductwork.
- The apartment does have a balcony.
- The blinds are horizontal.
- Tap Dial is battery powered, not kinetic/battery-free.
- Wall Washer is not recommended toward the projection wall.
- Signe is not assigned a bedroom corner that does not physically exist.
- Play Floor lamp is rejected for the airy plant stands.
- Iris is not assigned to the coffee table.
- Hue Go is not treated as permanent hallway architecture.
- Closet contact sensor is rejected because doors remain open.
- Bathroom/closet sensors are not recommended without controllable light endpoints.
- Bridge Pro is not an infrastructure prerequisite for this build.
- The 55 in TV gradient strip is not described as a monitor strip.
- New products do not receive speculative L6/L7 IDs before pairing.
- HomeHub accessory events are not assumed to be ingested.
- UI color-preset changes are not directed to a nonexistent `theme.js::LIGHT_COLOR_PRESETS`.

---

# 14. Current regular-price reference

| Product | Regular price |
|---|---:|
| Hue Play Light Bar single | $109.99 |
| Hue Play Table lamp | $79.99 |
| Hue Play Floor lamp large | $149.99 |
| Hue GU10 color | $59.99 |
| Hue Flux 16 ft | $99.99 |
| Flux extension cable 16 ft | $14.99 |
| Flux bracket 10-pack | $11.99 |
| Flux flex connector 4-pack | $29.99 |
| OmniGlow 10 ft | $139.99 |
| Tap Dial | $54.99 |
| Dimmer Switch | $30.99 |
| Smart Button | $32.99 |
| Indoor motion sensor | $48.99 |
| Smart Plug | $37.99 |
| Bridge | $69.99 |
| Bridge Pro | $139.99 |
| Iris | $120.99 |
| Go | $98.99 |
| Signe floor | $379.99 |
| Twilight | $319.99 |
| Play Wall Washer single | $229.99 |
| Play HDMI Sync Box 8K | $384.99 |
| Play PC gradient strip 24–27 in | $169.99 |
| Play gradient tube large | $249.99 |
| Festavia 100 LED / 26 ft | $139.99 |
| Festavia 250 LED / 65 ft | $259.99 |
| SKYDRAG 18 in | $32 each |
| TRÅDFRI 10 W driver | $35 |
| ANSLUTA power cord | $12 |

Prices should be rechecked immediately before purchase.

---

# 15. Primary sources

## Philips Hue

- Play Light Bar: https://www.philips-hue.com/en-us/p/hue-play-light-bar/7820130U7
- Play Table lamp: https://www.philips-hue.com/en-us/p/hue-white-and-color-ambiance-hue-play-table-lamp/046677610791
- Play Floor lamp large: https://www.philips-hue.com/en-us/p/hue-white-and-color-ambiance-hue-play-floor-lamp-large/046677610821
- GU10 color bulb: https://www.philips-hue.com/en-us/p/hue-white-and-color-ambiance-gu10-smart-spotlight/046677584658
- Flux 16 ft: https://www.philips-hue.com/en-us/p/lightstrips-flux-strip-light-16ft/046677607814
- Flux extension cable: https://www.philips-hue.com/en-us/p/lightstrips-hue-flux-strip-light-extension-cable-16ft/046677606305
- Flux flex connector: https://www.philips-hue.com/en-us/p/lightstrips-hue-flux-flex-connector-4-pack/046677606336
- Strip comparison: https://www.philips-hue.com/en-us/explore-hue/propositions/smart-strip-lights
- OmniGlow: https://www.philips-hue.com/en-us/p/lightstrips-omniglow-strip-light-10ft/046677608170
- Tap Dial: https://www.philips-hue.com/en-us/p/hue-tap-dial-switch/046677578800
- Indoor motion sensor: https://www.philips-hue.com/en-us/products/all-products/product-page.hue_motion-sensor_indoor
- Smart Plug: https://www.philips-hue.com/en-us/p/hue-smart-plug/046677552343
- Bridge Pro: https://www.philips-hue.com/en-us/p/hue-bridge-pro/046677582111
- MotionAware requirements: https://www.philips-hue.com/en-ph/support/article/motionawaretm--transform-your-hue-lights-into-motion-sensors/000011
- Sync Box 8K: https://www.philips-hue.com/en-us/p/hue-philips-hue-play-hdmi-sync-box-8k/046677579753
- Wall Washer: https://www.philips-hue.com/en-us/p/hue-white-and-color-ambiance-hue-play-wall-washer/046677590161
- Twilight: https://www.philips-hue.com/en-us/p/sleep-and-wake-up-light-twilight-sleep-and-wake-up-light-black/046677585631
- Iris: https://www.philips-hue.com/en-us/p/hue-white-and-color-ambiance-iris-table-lamp/046677561796
- Go: https://www.philips-hue.com/en-us/p/hue-white-and-color-ambiance-go-portable-accent-light/7602031U7

## IKEA

- SKYDRAG 18 in: https://www.ikea.com/us/en/p/skydrag-led-cntp-wrd-lght-strp-w-sensor-dimmable-white-00439595/
- TRÅDFRI 10 W driver: https://www.ikea.com/us/en/p/tradfri-driver-for-wireless-control-smart-gray-10356189/
- Hue Bridge compatibility guidance: https://www.ikea.com/us/en/customer-service/product-support/smart-lighting/how-to-use-smart-lighting-pub53d86412/

## Retail fixture reference

- SUNVIE GU10 uplight example: https://www.walmart.com/ip/10565607413
