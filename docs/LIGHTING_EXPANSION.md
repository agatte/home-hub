# Hue Expansion Plan — Apartment Lighting Buildout

## Context

Current setup is 5 lights (L1 living-room lamp, L2 bedroom desk lamp left, L3/L4 kitchen pendants, L5 bedroom desk lamp right — added 2026-05-11 as a Phase A mirror of L2). The plan names new lights L6, L7 … in the order you'd likely add them next. The apartment is a small open studio (bedroom → hallway → kitchen + living room), white walls, warm LVP floors, industrial ductwork in the kitchen, upper-floor city view from the living-room window, projector on the bedroom wall opposite the desk.

The gaps (biggest opportunities to make the space feel special):
- **Zero uplight or wall-wash anywhere** — every current emitter is either a diffused lamp (L1, L2) or a downpendant (L3, L4). Adding up/wall-washing light is the single biggest drama lever.
- **Bedroom has two emitters (L2 + L5 installed 2026-05-11)** — both desk-side. Spatial depth is still limited (no wall-wash or uplighting); adding a wall-wash layer is the biggest remaining bedroom upgrade.
- **Living room has one emitter (L1)** and a big window with a city view — the window is an untapped accent opportunity.
- **Kitchen has no task light** under the cabinets and no accent wash against the exposed ductwork.
- **Hallway is dark** — only L2 spill. Good welcome-home real estate.

Everything below respects your lighting design principles (kitchen pair, post-sunset ct≥333, HSB/CT never mix, IES contrast). For each light, I've noted: what it is, where it'd go, what role it'd play in modes, and realistic cost.

---

## Categories

### A. Bias & Sync (gaming, watching, working)
Extends screen light into the room. Works with the existing screen-sync service.

| Light | Role | Where | Cost |
|---|---|---|---|
| **Hue Play Light Bar pair** | Physical bias flanking the monitor; snappier than L2 alone for gaming | Behind primary monitor on desk | $130/pair |
| **Hue Gradient Lightstrip for monitor 55"** | Horizontal gradient behind the monitor | Adhered to back of primary monitor | $170 |
| **Hue Play HDMI Sync Box 8K** | Replaces mss screen-sync on the dev PC; low-latency projector sync | Between dev PC and projector HDMI | $290 |
| **Hue Play Gradient Light Tube 75"** | Bigger bar/tube form factor; mountable behind the desk or above projector | Vertical behind desk *or* horizontal above projector if projector is wall-mounted later | $240 |

**Integration notes:** Play bars would register as L8/L9 (L5 = Bedroom Lamp Right installed 2026-05-11; L6 = Signe floor lamp; L7 = Play Wall Washer per "Recommended placement" below) — join the kitchen-style "pair" rule for gaming/working bias. Gradient strips appear as a single light to `hue_service` but as addressable segments to Hue entertainment areas — keep in `ACTIVITY_LIGHT_STATES` as one light, use entertainment group for screen-sync. Sync Box replaces `screen_sync.py` mss path entirely and fixes the "watching is dev-PC-HDMI only" limitation.

### B. Ambient & Mood (lamps, sculptural)
Fills out rooms. Replaces or complements existing fabric lamps.

| Light | Role | Where | Cost |
|---|---|---|---|
| **Hue Signe Gradient Floor Lamp (tall)** | Vertical wall-washer column, up to ~6ft tall gradient | Bedroom corner diagonal from desk (pointed at wall) *or* living room corner by window | $363 (MSRP) |
| **Hue Twilight Gradient Table Lamp** | Dual-emitter nightstand lamp with ColorCast gradient; sunrise simulation | Bedside nightstand | $308 |
| **Hue Iris Gen 4 Table Lamp** | Compact colored accent lamp, single color wash; Gen 4 is 570 lm (up from Gen 3's 210 lm) | Coffee table, kitchen counter corner, or nightstand | $121 |
| **Hue Go Portable (latest model)** | Battery accent lamp, 24h battery, moveable | Floats — bathroom shelf, hallway floor, bed, living room coffee table | $99 |
| **IKEA Varmblixt Smart Donut** | Sculptural frosted-donut lamp. **2026 revision is Matter-over-Thread only — does NOT pair with the Hue Bridge.** Aesthetically perfect for this apartment but currently incompatible with Home Hub; defer pending Matter integration. The 2024 Zigbee variant is no longer sold. | Deferred (was: living room side table) | $99 |

**Integration notes:** Varmblixt's 2026 revision is Matter-over-Thread; until Home Hub adds a Matter actuator path, it can't sit in `ACTIVITY_LIGHT_STATES` and is effectively unusable for our setup. Hue Go can be motion-triggered via the Hue Motion Sensor (see Category D) — the in-app arrival-wave choreography was retired with home/away on 2026-04-27, but bridge-side motion rules still work.

### C. Architectural & Wall-Wash (transform surfaces)
Turn white walls into scenes. Highest drama-per-dollar.

| Light | Role | Where | Cost |
|---|---|---|---|
| **Hue Play Wall Washer** | Continuous multi-LED gradient bar that paints a wall | Behind the desk chair in the bedroom (faces the projection wall — bias for watching without hitting the image); or wall behind the couch | $220 |
| **Hue Dymera Wall Sconce (indoor)** | Two independently-controlled beams (up + down); hard-wired | Hallway (if there's a bare sconce box) or replacing a building-provided bathroom sconce | $242 |
| **Hue OmniGlow Lightstrip 3m/10ft** | Seamless CSP lightstrip, 2700 lm at 6500K — no visible LED dots. Cuttable, NOT extendable. (5m/16ft variant is EU-only as of May 2026.) | On top of upper kitchen cabinets, aimed at ceiling — uplight wash against the industrial ductwork (this is the single most transformative move for the kitchen); or cove behind the couch | $140 |
| **Hue Flux Gradient Lightstrip 10ft / 16ft** | Newer (US-released March 2026) gradient strip, 2000 lm. Cuttable AND extendable up to 20m total. ~half the price of Play Gradient at the same length. | Same placements as OmniGlow; better choice if you want to extend later | $70 / $100 |
| **Hue Festavia String Lights 26ft (100 LED)** | Addressable string, individual LED control in entertainment scenes; 2nd-gen indoor+outdoor | Draped behind the living-room vertical blinds (pairs with the city night view); or across the kitchen ductwork | $132 |
| **Hue Festavia 65ft (250 LED)** | Bigger version, covers multiple surfaces; 2nd-gen indoor+outdoor | Over-spec for a small studio — only worth it if covering both kitchen ductwork AND living-room window | $242 |

**Integration notes:** Wall Washer behind the desk is the sharpest bedroom upgrade — it'd light the back wall during watching with warm CT and provide HSB gradient during gaming, without competing with the projector. OmniGlow on top of kitchen cabinets turns the ductwork ceiling into a moody canvas — add a `cooking` uplight state in `ACTIVITY_LIGHT_STATES` and the kitchen ceiling lights up automatically the moment you tap the cooking tile, plus a dim-orange `relax` state for evenings. Festavia has two distinct use modes: (a) **static HSB preset** — running a fixed "city skyline" palette behind the blinds, safe and matches the relax/social color palettes; (b) **entertainment-area sync** — mirrors live screen content, which during gaming can pull greens/reds that fight the recently retuned teal-blue gaming palette and the room's olive/teal accents. Default to (a); only opt into (b) if Festavia is excluded from the gaming entertainment group.

### D. Functional & Task
Work and utility bulbs. Where task lighting matters more than mood.

| Light | Role | Where | Cost |
|---|---|---|---|
| **IKEA Skydrag / Omlopp** (Zigbee) | Under-cabinet task light; IKEA's wired Zigbee LED; pairs with Hue Bridge | Under kitchen upper cabinets | $35–60 |
| **Hue White Ambiance A19** | Tunable-white bulb (no color) — cheaper than color | Bathroom ceiling, hallway, any building fixture where color isn't needed | $22 |
| **Hue White & Color A19** | Full color bulb | Any existing E26 fixture | $50 |
| **Hue E12 Candelabra** | Candle-style bulb | If any fixture uses E12 sockets | $25 |
| **Innr A19 Color Bulb** | Budget third-party Zigbee bulb, pairs with Hue Bridge | Fill-in for secondary fixtures; known to be less reliable | $18–25 |
| **IKEA Tradfri E26 Color (latest firmware)** | Budget Zigbee bulb, pairs with Hue Bridge | Same as Innr | $10–15 |
| **Hue Recessed Downlight 5"/6"** | Retrofit can light | Living room recessed cans (the "sensor/thermostat hardware" circles you noted) if any are actual bulb sockets | $60 each |
| **Hue Motion Sensor (indoor)** | Battery-powered PIR sensor; bridge-native motion rules without backend changes. Pairs with Hue Go for hallway "welcome home" lighting. | Hallway shelf, entry, bathroom | $45 |
| **Hue Tap Dial Switch** | Kinetic-energy (battery-free) physical scene/dimmer with rotary dimmer + 4 buttons. Magnetic mount. Bridges the gap when voice and dashboard aren't reachable (cooking, controller in hand, guests). | Kitchen backsplash, desk side, or living-room end table | $50 |

### E. Decorative / Character
Makes the apartment visibly non-generic.

| Light | Role | Where | Cost |
|---|---|---|---|
| **Hue Festavia Globe (outdoor)** | NOT a pendant — outdoor-rated globe-bulb string lights (22ft / 45ft). Marketed for patios, balconies. | Defer pending balcony/patio (none in current apartment) | $176 / $220 |
| **Hue Go Portable** (repeat) | The only battery-powered option on this list — no permanent install, no rewiring. Movable character light. | Any surface, battery, mobile | $99 |

---

## Price tiers

### Tier 1 — Budget foothold (~$220)
Fill the biggest functional gaps without rewiring anything.
- **Hue OmniGlow 3m** — $140 — top of kitchen cabinets, uplight wash against the industrial ductwork — tracked in [#11](https://github.com/agatte/home-hub/issues/11)
- **IKEA Skydrag under-cabinet Zigbee strip** — $35–60 — kitchen task light (paired with OmniGlow as the kitchen completion kit) — tracked in [#12](https://github.com/agatte/home-hub/issues/12)
- **Hue Motion Sensor** — $45 — enables motion-triggered hallway lighting without code — tracked in [#13](https://github.com/agatte/home-hub/issues/13)

**Biggest bang:** OmniGlow + Skydrag together complete the kitchen — uplight ductwork above + task light below. The OmniGlow transforms the kitchen's visual identity at night; it's also the first wishlist item that integrates directly with an existing mode (add a `cooking` uplight state and the kitchen lights up automatically the moment you tap the cooking tile).

### Tier 2 — Meaningful upgrade ($200–500)
Add character to the living room, a flexible mobile light, and physical control.
- **Hue Iris Gen 4** — $121 — one colored accent on the coffee table or nightstand
- **Hue Go Portable** — $99 — flexible nightstand/bathroom/hallway light (combines with Tier 1 motion sensor for welcome-home)
- **Hue Tap Dial Switch** — $50 — physical scene/dimmer near the cooking station or desk
- **Hue Flux Gradient Lightstrip 16ft** — $100 — alternative to OmniGlow if you want extendability later
- **2× IKEA Tradfri E26 color** — $20–30 — any dumb fixture you want Hue to control

**Biggest bang:** Hue Go is the cheapest item on the list that visibly changes how the apartment feels — 24h battery, floats anywhere, and closes the dark hallway gap when paired with the Tier 1 motion sensor. Note: Varmblixt's 2026 revision dropped to Matter-only, so the original "living room sculptural accent" pick is unavailable for now.

### Tier 3 — Premium redesign ($500–1500)
Real architectural changes. Room-level visual identity.
- **Hue Play Wall Washer** — $220 — behind desk, wall-wash opposite projector. The foundational bedroom upgrade — closes the one-emitter gap directly.
- **Hue Signe Gradient Floor Lamp** — $363 (MSRP) — bedroom corner column. Premium layer on top of the Wall Washer; gradient palette assignment needs design work against the recently retuned ember/moss relax palette (curator review pre-purchase recommended).
- **Hue Twilight Gradient Table Lamp** — $308 — nightstand; integrates with morning_routine + winddown_routine schedulers.
- **Hue Play HDMI Sync Box 8K** — $290 — replaces mss path, proper projector sync.
- **Hue Play Light Bar pair** — $130 — monitor flank, snappier than L2 alone for gaming bias.
- **Hue Bridge Pro** — $99 — infrastructure prerequisite for the full buildout (150 lights / 50 accessories vs original Bridge's 50/12; MotionAware turns existing lights into motion sensors; SpatialAware scenes 2026).

**Biggest bang:** Wall Washer is the foundational bedroom upgrade — turns a blank back wall into the apartment's best surface during watching/gaming for $220. Signe is the premium layer on top. The Sync Box is a separate but real quality-of-life upgrade for watching mode.

### Tier 4 — Flagship / full buildout (~$2000+)
Everything the apartment can reasonably hold without over-lighting.
- All of Tier 3 plus:
- **Hue Festavia 26ft (100 LED)** — $132 — behind living-room vertical blinds, paired with city night view
- **Hue Festavia 65ft (250 LED)** — $242 — only if covering kitchen ductwork run AND living-room window (over-spec for a single surface)
- **Hue Dymera Wall Sconce** — $242 — hallway IF there's a sconce box (renter-friendliness caveat: hard-wired install)
- **2× Hue Iris Gen 4** — $242 — kitchen counter + coffee table second emitters
- **Hue Play Gradient Light Tube 75"** — $242 — secondary bias behind desk (sized for TV-back; check fit)

---

## Recommended placement (your apartment, L6 onward)

**Bedroom** — fills out the two-emitter room (L2 + L5 installed; spatial depth still limited)
- **L5 — Bedroom Lamp Right** (installed 2026-05-11): clear housing, desk-side. Differentiated from L2 in the Phase B/C curator-reviewed gameday SEQUENCES (shipped 2026-05-07); per-mode state differentiation for non-gameday modes is still ongoing as Tier 3 buildout proceeds.
- **L6 — Signe floor lamp** in the corner diagonal from the desk, pointed at the wall behind the bed. During watching it backlights the viewer in warm CT; during gaming it becomes a gradient column; scene-drift loves it.
- **L7 — Play Wall Washer** on the wall behind the desk chair, aimed at the projection wall's adjacent side wall (NOT the projection wall itself). In watching mode: warm CT at ~200 bri, extends the projected image's ambient spread. In gaming: HSB gradient that bounces off the side wall and reaches peripheral vision.
- **L8 + L9 — Play Light Bar pair** flanking the primary monitor. Two Hue IDs, registered as a "pair" like L3/L4 (each bar is a distinct light_id at the bridge). They'd replace a lot of what L2/L5 are currently doing for bias and let you push them down to a softer fill role.
- **L10 — Twilight Gradient Table Lamp** on the nightstand. Plug into morning routine (sunrise simulation) and wind-down (candle fade). Replaces any dumb bedside lamp.

**Living room** — second emitter + window character
- **L11 — Hue Iris Gen 4** on the coffee table or the side table beside L1. Two emitters in a small room is enough. Single colored wash; choose hue/sat that complements L1's teal base (avoid a second teal — the room is already teal-anchored). The original pick was the IKEA Varmblixt Smart Donut, but its 2026 revision dropped Zigbee for Matter-over-Thread and is no longer Hue-Bridge-compatible. Pending Matter integration in Home Hub, the Iris Gen 4 takes its slot.
- **L12 — Festavia 26ft** behind the vertical blinds, facing out toward the window. Pairs with the city night view — especially during `social` or `relax` evening/night states. Invisible when off, magic when on. Run as static HSB preset (not entertainment-sync) during gaming to avoid palette clash.

**Kitchen** — task + accent layering
- **L13 — OmniGlow 3m** on top of the upper cabinets, aimed at the ceiling. Uplight wash against the exposed ductwork. Deep oranges in evening `cooking`, warm amber `relax`, and a pulsing accent in `social`. This is the move that makes the kitchen photograph well.
- **L14 — Skydrag/Omlopp** under-cabinet task light. Strict `ct ≥ 333` in evening+. Auto-on during `cooking` at 4000K (food color accuracy within your post-sunset rule allows up to 333 mired = 3000K; 4000K only during daytime cooking). Complements L3/L4 which are island-focused.

**Hallway** — no fixture, easy wins
- **L15 — Hue Go Portable** on a small shelf or the floor. Battery-powered warm light that doesn't require permanent install — works as a bathroom or hallway accent. Pair with the **Hue Motion Sensor** (Tier 1) — bridge-side motion rules trigger the Go on entry without any backend changes. The in-app arrival-wave choreography was retired with home/away on 2026-04-27, but hardware-driven welcome lighting works fine.
- Or **L15 — Hue Dymera** if there's a bare sconce box you can wire. Up+down beams add vertical drama to the narrow hallway.

---

## Pairing third-party (IKEA Tradfri / Varmblixt / Innr) to the Hue Bridge

Your memory of "12 times" is in the right ballpark — the Zigbee Touchlink spec resets on rapid power cycles, and the exact count depends on firmware version. Practical rules:

- **IKEA Tradfri bulbs** — toggle power 6 times rapidly for a factory reset on modern firmware. Older firmware (pre-v1.2) may need more cycles or can't be paired at all without first updating via IKEA's hub. 12 rapid cycles is a "safety number" that works across most firmware revisions.
- **IKEA Varmblixt Smart (2026 revision)** — **Matter-over-Thread only.** The 2024 Zigbee variant the doc was originally drafted against is no longer sold. The 2026 unit retains a Zigbee radio for IKEA's BILRESA accessory but is NOT advertised or supported as Hue-Bridge-pairable, and requires a Thread Border Router (DIRIGERA, Apple TV 4K, Echo 4th-gen) for control. Until Home Hub adds a Matter actuator path, treat as incompatible.
- **Tradfri drivers (Skydrag/Omlopp)** — have a physical reset button; hold it while the bridge searches.
- **Innr bulbs** — power-cycle 5–6 times, same Touchlink reset. Friends-of-Hue certified, so should pair cleanly.

**Use "Add Hue-compatible light" (not "Add Hue light")** in the Hue app during pairing. The bridge will discover any Zigbee LightLink / Zigbee 3.0 device in reset mode within ~1m range.

**Risks:**
- Non-Hue lights don't always fire at the same speed, so strict scene choreography (the `register_on_mode_change` wave) may look staggered.
- Innr has a reputation for dropping off the mesh after months of use (per r/hue). If a light is critical to a mode's state, pay for Hue.
- IKEA Tradfri drivers have a similar (though less documented) mesh-drop risk and can't receive firmware updates over the Hue Bridge.

---

## Home Hub integration implications

Any of these additions would require backend changes in `backend/services/light_state_calculator.py` (where `ACTIVITY_LIGHT_STATES` and `EFFECT_AUTO_MAP` live — `automation_engine.py` re-exports both for back-compat but is no longer the edit target):

- **New light IDs** added to `ACTIVITY_LIGHT_STATES` for every mode × time period (see "New automation mode" pattern in `.claude/CLAUDE.md`). Each new light needs a considered state — don't `_uniform()`.
- **Kitchen-pair rule extension** — if L13 (OmniGlow cabinet uplight) and L14 (under-cabinet task) are added, they're a new functional pair for `cooking` + the 6 guest party scenes. In relax + custom non-party aesthetic scenes they're free to diverge.
- **Bias-pair rule** — L8/L9 Play bars become a monitor-flanking pair (L5 is installed Bedroom Lamp Right); group with L2/L5 for screen sync entertainment area.
- **`EFFECT_AUTO_MAP`** (also in `light_state_calculator.py`) — for effects scoped to specific lights (e.g. relax candle/fire is scoped to `["1", "2"]` so moss kitchen pendants stay static), new lights are **excluded by default**. You must explicitly add their IDs to the relevant scope list. Effects with `"lights": None` (e.g. watching glisten) will apply to all lights automatically. Wall Washer + Signe + Festavia + OmniGlow are all Hue v2 effect-capable, but which scope list they should join is a design decision, not an automatic one.
- **Screen sync service** — Play Sync Box would replace `backend/services/pc_agent/screen_sync_agent.py` (the mss capture loop that runs on the dev PC); the backend `screen_sync.py` receiver service stays. Route sync through the box's Entertainment API instead of the `POST /api/automation/screen-color` path. Much lower latency, frees the dev PC from running mss.
- **Frontend theme** — `src/lib/theme.js` `LIGHT_COLOR_PRESETS` would need new entries for Varmblixt's limited gamut (snap presets to its supported range to avoid "color requested but not matched" artifacts).

**Scope ordering if executing:**
1. Add each new light's states to `ACTIVITY_LIGHT_STATES` for all 7 modes × up to 4 time periods (`day`/`evening`/`night`/`late_night` — social is flat; cooking has no `late_night`; modes without a `late_night` entry fall back to `night` automatically).
2. Test via `mcp__home-hub__get_lights` → `set_light` per new ID.
3. Validate kitchen-pair rule holds (L13/L14 paired in functional modes).
4. Update `LIGHT_COLOR_PRESETS` if any light needs a special preset.
5. Add to screen-sync entertainment group if bias/sync role.
6. Update scenes in DB via `mode_scene_overrides` if a flagship preset should auto-apply.

---

## Verification (after any purchase)

1. Pair the light via Hue app (or power-cycle reset for IKEA/Innr).
2. `mcp__home-hub__get_lights` — confirm new light appears with reachable=True.
3. `mcp__home-hub__set_light` — test CT and HSB (if capable); confirm the bridge accepts values.
4. Add a draft `ACTIVITY_LIGHT_STATES` block for the new ID with one mode/time, `python run.py`, force the mode, verify the state applies.
5. Fill in remaining mode×period combinations with intentional values (never `_uniform`).
6. `mcp__home-hub__get_automation_status` after a mode change to confirm the new light shows in the applied state.
7. For Wall Washer / Signe / OmniGlow / Festavia: test `activate_effect` per light ID (candle, fire, sparkle, opal) — they're Hue v2 native, so effects work out of the box.
8. UI audit via `/ui-audit` if any presets or scene UI changed.

---

## Top picks if you only buy one thing

- **Under $200**: **Hue OmniGlow 3m + Hue Motion Sensor + Skydrag** ($140 + $45 + $35 ≈ $220) — completes the kitchen above and below, plus enables hallway welcome-home lighting. Cheapest path to "the apartment feels deliberately lit."
- **Under $300**: **Hue Play Wall Washer** behind the desk — turns a blank bedroom wall into the best-looking surface in the apartment during watching/gaming modes; adds the bedroom's second spatial layer for both modes.
- **No budget limit**: **Signe Gradient Floor Lamp** for the bedroom corner — single most "this is a designed space" addition. Caveat: gradient palette assignment (ember-vs-moss for relax, teal-blue for gaming) is a design-time decision that needs `lighting-curator` review before commit. The recently retuned relax palette (ember L1/L2, whisper-dim moss L3/L4) means Signe can't just inherit L2's state — the gradient must be designed for the column.

---

## Sources

- [Philips Hue new products 2025 overview — Hueblog](https://hueblog.com/2025/09/04/these-are-all-the-new-philips-hue-products-for-2025/)
- [Philips Hue OmniGlow Review — TechRadar](https://www.techradar.com/home/smart-lights/philips-hue-omniglow-review)
- [Philips Hue Play Wall Washer Review — Hueblog](https://hueblog.com/2025/06/17/review-of-the-new-philips-hue-play-wall-washer/)
- [Philips Hue Dymera Wall Light Review — Hueblog](https://hueblog.com/2024/02/01/philips-hue-dymera-wall-light-review/)
- [IKEA Varmblixt Smart Matter Compatibility — TechRadar](https://www.techradar.com/home/smart-lights/a-marriage-of-hue-and-form-ikeas-donut-shaped-varmblixt-smart-lamp-has-started-landing-in-stores-early-and-we-cant-wait-to-get-our-hands-on-it-again)
- [IKEA Tradfri pairing with Hue Bridge — return2.net](https://return2.net/how-to-connect-ikea-tradfri-to-philips-hue-bridge/)
- [Third-party bulbs compatible with Hue — The Smart Cave](https://thesmartcave.com/smart-bulbs-compatible-with-philips-hue/)
- [Philips Hue Gradient Signe Floor Lamp Review — T3](https://www.t3.com/reviews/philips-hue-gradient-signe-floor-lamp-review)
- [Philips Hue Go Gen 2 Review — TechRadar](https://www.techradar.com/reviews/philips-hue-go-2)
- [Philips Hue Festavia Review — Trusted Reviews](https://www.trustedreviews.com/reviews/philips-hue-festavia-string-lights-2nd-gen-indoor-and-outdoor)
- [Philips Hue Play HDMI Sync Box Review — TechHive](https://www.techhive.com/article/584116/philips-hue-play-hdmi-sync-box-review.html)
- [Hue Zigbee 3.0 support — Philips Hue Developer Program](https://developers.meethue.com/zigbee-3-0-support-in-hue-ecosystem/)
