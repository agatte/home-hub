# Hue Expansion Plan — Apartment Lighting Buildout

## Context

Current setup is 4 lights (L1 living-room lamp, L2 bedroom desk lamp, L3/L4 kitchen pendants). The plan names new lights L5, L6 … in the order you'd likely add them. The apartment is a small open studio (bedroom → hallway → kitchen + living room), white walls, warm LVP floors, industrial ductwork in the kitchen, upper-floor city view from the living-room window, projector on the bedroom wall opposite the desk.

The gaps (biggest opportunities to make the space feel special):
- **Zero uplight or wall-wash anywhere** — every current emitter is either a diffused lamp (L1, L2) or a downpendant (L3, L4). Adding up/wall-washing light is the single biggest drama lever.
- **Bedroom is a one-emitter room** — L2 does everything (work bias, gaming bias, watching bias, ambient). Adds of spatial depth in the bedroom will be felt the most.
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

**Integration notes:** Play bars would register as L5/L6 — join the kitchen-style "pair" rule for gaming/working bias. Gradient strips appear as a single light to `hue_service` but as addressable segments to Hue entertainment areas — keep in `ACTIVITY_LIGHT_STATES` as one light, use entertainment group for screen-sync. Sync Box replaces `screen_sync.py` mss path entirely and fixes the "watching is dev-PC-HDMI only" limitation.

### B. Ambient & Mood (lamps, sculptural)
Fills out rooms. Replaces or complements existing fabric lamps.

| Light | Role | Where | Cost |
|---|---|---|---|
| **Hue Signe Gradient Floor Lamp (tall)** | Vertical wall-washer column, up to ~6ft tall gradient | Bedroom corner diagonal from desk (pointed at wall) *or* living room corner by window | $330 |
| **Hue Twilight Gradient Table Lamp** | Dual-emitter nightstand lamp with ColorCast gradient; sunrise simulation | Bedside nightstand | $280 |
| **Hue Iris Gen 3 Table Lamp** | Compact colored accent lamp, single color wash | Coffee table, kitchen counter corner, or nightstand | $100 |
| **Hue Go Gen 2 Portable** | Battery accent lamp, 24h battery, moveable | Floats — bathroom shelf, hallway floor, bed, living room coffee table | $160 |
| **IKEA Varmblixt Smart Donut** | Sculptural frosted-donut lamp, Matter-certified, pairs via Zigbee 3.0 (power-cycle reset). 12,000-color range. | Living room side table *or* kitchen island corner (its sculptural shape suits the loft aesthetic) | $90 |

**Integration notes:** Varmblixt has a narrower color gamut (12,000 colors vs Hue's ~16M) — test before relying on for fine HSB states. Go can be presence-triggered — great for the "arrival wave" sequence if you add a hallway/bathroom position.

### C. Architectural & Wall-Wash (transform surfaces)
Turn white walls into scenes. Highest drama-per-dollar.

| Light | Role | Where | Cost |
|---|---|---|---|
| **Hue Play Wall Washer** | Continuous multi-LED gradient bar that paints a wall | Behind the desk chair in the bedroom (faces the projection wall — bias for watching without hitting the image); or wall behind the couch | $220 |
| **Hue Dymera Wall Sconce (indoor)** | Two independently-controlled beams (up + down); hard-wired | Hallway (if there's a bare sconce box) or replacing a building-provided bathroom sconce | $260 |
| **Hue OmniGlow Lightstrip 3m/10ft** | Newest seamless CSP lightstrip, 2700 lm at 6500K — no visible LED dots | On top of upper kitchen cabinets, aimed at ceiling — uplight wash against the industrial ductwork (this is the single most transformative move for the kitchen); or cove behind the couch | $140 |
| **Hue OmniGlow Lightstrip 5m/16ft** | Longer version at 4500 lm | Same placements, runs further | $200 |
| **Hue Festavia String Lights 26ft (100 LED)** | Addressable string, individual LED control in entertainment scenes | Draped behind the living-room vertical blinds (pairs with the city night view); or across the kitchen ductwork | $220 |
| **Hue Festavia 65ft (250 LED)** | Bigger version, covers multiple surfaces | Same roles, longer runs | $300 |

**Integration notes:** Wall Washer behind the desk is the sharpest bedroom upgrade — it'd light the back wall during watching with warm CT and provide HSB gradient during gaming, without competing with the projector. Festavia in entertainment mode can become the "city skyline" effect during gaming/social. OmniGlow on top of kitchen cabinets turns the ductwork ceiling into a moody canvas — add a `cooking` uplight state and a dim-orange `relax` state.

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

### E. Decorative / Character
Makes the apartment visibly non-generic.

| Light | Role | Where | Cost |
|---|---|---|---|
| **IKEA Varmblixt Smart Donut** (repeat) | Sculptural statement piece | As above — arguably the single most "this is my apartment" object on this list | $90 |
| **Hue Festavia Globe** | Globe pendant with addressable LEDs | If you install a pendant hook over the coffee table or entry | $250+ |
| **Hue Go Gen 2** (repeat) | Movable character light | Any surface, battery, mobile | $160 |

---

## Price tiers

### Tier 1 — Budget foothold (~$150)
Fill the biggest functional gap without rewiring anything.
- **IKEA Skydrag under-cabinet Zigbee strip** — $35–60 — kitchen task light
- **2× IKEA Tradfri E26 color** — $20–30 — any dumb fixture you want Hue to control
- **Hue Iris Gen 3** — $100 — one colored accent on the coffee table or nightstand

**Biggest bang:** under-cabinet kitchen light makes cooking genuinely easier and gives `cooking` mode a pair of true task emitters.

### Tier 2 — Meaningful upgrade ($150–500)
Adds depth to the bedroom and one new emitter to the living room.
- **Hue Play Light Bar pair** — $130 — monitor bias
- **IKEA Varmblixt Smart Donut** — $90 — living room sculptural accent
- **Hue OmniGlow 3m** — $140 — top of kitchen cabinets, uplight against ductwork
- **Hue Go Gen 2** — $160 — flexible nightstand/bathroom light

**Biggest bang:** OmniGlow over the cabinets is a $140 line item that transforms the kitchen's visual identity at night. It's the closest thing on this list to "making the room special."

### Tier 3 — Premium redesign ($500–1500)
Real architectural changes. Room-level visual identity.
- **Hue Signe Gradient Floor Lamp** — $330 — bedroom or living room
- **Hue Play Wall Washer** — $220 — behind desk, wall-wash opposite projector
- **Hue Twilight Gradient Table Lamp** — $280 — nightstand
- **Hue Play HDMI Sync Box 8K** — $290 — replaces mss path, proper projector sync
- **Hue Gradient Lightstrip 55"** — $170 — monitor back
- **OmniGlow 5m** — $200 — longer kitchen cove run

**Biggest bang:** Wall Washer + Signe floor lamp together transform the bedroom from "one emitter" to "three spatial layers" (desk bias + corner column + back-wall wash). Also the Sync Box is a real quality-of-life upgrade for watching mode.

### Tier 4 — Flagship / full buildout (~$2000+)
Everything the apartment can reasonably hold without over-lighting.
- All of Tier 3 plus:
- **Hue Festavia 65ft (250 LED)** — $300 — living room window + kitchen ductwork
- **Hue Dymera Wall Sconce** — $260 — hallway if there's a sconce box
- **2× Hue Iris Gen 3** — $200 — kitchen counter + coffee table
- **Hue Play Gradient Light Tube 75"** — $240 — secondary bias behind desk

---

## Recommended placement (your apartment, L5 onward)

**Bedroom** — fills out the one-emitter problem
- **L5 — Signe floor lamp** in the corner diagonal from the desk, pointed at the wall behind the bed. During watching it backlights the viewer in warm CT; during gaming it becomes a gradient column; scene-drift loves it.
- **L6 — Play Wall Washer** on the wall behind the desk chair, aimed at the projection wall's adjacent side wall (NOT the projection wall itself). In watching mode: warm CT at ~200 bri, extends the projected image's ambient spread. In gaming: HSB gradient that bounces off the side wall and reaches peripheral vision.
- **L7 — Play Light Bar pair** flanking the primary monitor. Register as a "pair" like L3/L4. They'd replace a lot of what L2 is currently doing for bias and let you push L2 down to a softer fill role.
- **L8 — Twilight Gradient Table Lamp** on the nightstand. Plug into morning routine (sunrise simulation) and wind-down (candle fade). Replaces any dumb bedside lamp.

**Living room** — second emitter + window character
- **L9 — IKEA Varmblixt Smart Donut** on the coffee table or the side table beside L1. Two emitters in a small room is enough. Its frosted donut form against the city-window backdrop is the single most "designed space" move for the apartment.
- **L10 — Festavia 26ft** behind the vertical blinds, facing out toward the window. Pairs with the city night view — especially during `social` or `relax` evening/night states. Invisible when off, magic when on.

**Kitchen** — task + accent layering
- **L11 — OmniGlow 3m** on top of the upper cabinets, aimed at the ceiling. Uplight wash against the exposed ductwork. Deep oranges in evening `cooking`, warm amber `relax`, and a pulsing accent in `social`. This is the move that makes the kitchen photograph well.
- **L12 — Skydrag/Omlopp** under-cabinet task light. Strict `ct ≥ 333` in evening+. Auto-on during `cooking` at 4000K (food color accuracy within your post-sunset rule allows up to 333 mired = 3000K; 4000K only during daytime cooking). Complements L3/L4 which are island-focused.

**Hallway** — no fixture, easy wins
- **L13 — Hue Go Gen 2** on a small shelf or the floor. Motion/presence-activated welcome light (your presence service already does the choreographed wave — Go joins L3→L4→L1→L2). Also gives bathroom a battery-powered warm light that doesn't require permanent install.
- Or **L13 — Hue Dymera** if there's a bare sconce box you can wire. Up+down beams add vertical drama to the narrow hallway.

---

## Pairing third-party (IKEA Tradfri / Varmblixt / Innr) to the Hue Bridge

Your memory of "12 times" is in the right ballpark — the Zigbee Touchlink spec resets on rapid power cycles, and the exact count depends on firmware version. Practical rules:

- **IKEA Tradfri bulbs** — toggle power 6 times rapidly for a factory reset on modern firmware. Older firmware (pre-v1.2) may need more cycles or can't be paired at all without first updating via IKEA's hub. 12 rapid cycles is a "safety number" that works across most firmware revisions.
- **IKEA Varmblixt Smart (2025 revision)** — Matter-certified, but also Zigbee 3.0. Same power-cycle reset applies. Has a physical reset button per IKEA's setup guide — if the power-cycle reset doesn't work, use the button.
- **Tradfri drivers (Skydrag/Omlopp)** — have a physical reset button; hold it while the bridge searches.
- **Innr bulbs** — power-cycle 5–6 times, same Touchlink reset. Friends-of-Hue certified, so should pair cleanly.

**Use "Add Hue-compatible light" (not "Add Hue light")** in the Hue app during pairing. The bridge will discover any Zigbee LightLink / Zigbee 3.0 device in reset mode within ~1m range.

**Risks:**
- Non-Hue lights don't always fire at the same speed, so strict scene choreography (the `register_on_mode_change` wave) may look staggered.
- Varmblixt's 12,000 colors mean some HSB values will snap to nearest — avoid relying on it for precise scenes.
- Innr has a reputation for dropping off the mesh after months of use (per r/hue). If a light is critical to a mode's state, pay for Hue.

---

## Home Hub integration implications

Any of these additions would require backend changes in `backend/services/automation_engine.py`:

- **New light IDs** added to `ACTIVITY_LIGHT_STATES` for every mode × time period (follows Pattern 7 in `.claude/CLAUDE.md`). Each new light needs a considered state — don't `_uniform()`.
- **Kitchen-pair rule extension** — if L11 (OmniGlow cabinet uplight) and L12 (under-cabinet task) are added, they're a new functional pair for `cooking`. In `relax/social` they're free to diverge.
- **Bias-pair rule** — L5/L6 Play bars become a monitor-flanking pair; group with L2 for screen sync entertainment area.
- **`EFFECT_AUTO_MAP`** — new lights inherit mode effects automatically unless excluded (Wall Washer + Signe + Festavia are all Hue v2 effect-capable; OmniGlow supports effects too).
- **Screen sync service** — Play Sync Box would replace `screen_sync.py` entirely; if added, remove the mss path and route sync through the box's Entertainment API. Much lower latency, frees the dev PC from running mss.
- **Frontend theme** — `src/lib/theme.js` `LIGHT_COLOR_PRESETS` would need new entries for Varmblixt's limited gamut (snap presets to its supported range to avoid "color requested but not matched" artifacts).

**Scope ordering if executing:**
1. Add each new light's states to `ACTIVITY_LIGHT_STATES` for all 6 modes × 3 time periods.
2. Test via `mcp__home-hub__get_lights` → `set_light` per new ID.
3. Validate kitchen-pair rule holds (L11/L12 paired in functional modes).
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

- **Under $150**: **Hue OmniGlow 3m + Tradfri E26** above the kitchen cabinets — cheapest transformation, visibly changes the room's identity at night.
- **Under $300**: **Hue Play Wall Washer** behind the desk — turns a blank bedroom wall into the best-looking surface in the apartment during watching/gaming modes.
- **No budget limit**: **Signe Gradient Floor Lamp** for the bedroom corner — single most "this is a designed space" addition.

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
