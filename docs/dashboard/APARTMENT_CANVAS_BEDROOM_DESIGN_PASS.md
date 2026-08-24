# Apartment Canvas Bedroom / Desk / Projector Design Pass

## Status

Version: v1  
Status: Draft design target  
Owner: Dashboard UI  
Related:

- `docs/dashboard/APARTMENT_CANVAS_DESIGN_LANGUAGE.md`
- `docs/dashboard/APARTMENT_CANVAS_DIRECTOR_BOARD.md`

---

## Purpose

This document defines the first room-level visual design pass for Apartment Canvas.

The bedroom is the highest-priority identity zone because it contains two of HomeHub's most distinctive experiences:

1. the desk as a calm personal command center
2. the projector as a cinematic room transformation

The goal of this pass is to establish the room's visual identity, material direction, lighting treatment, camera behavior, focal hierarchy, and acceptance criteria before implementation is treated as complete.

This is a visual design artifact. It does not redefine lifecycle semantics, sensing authority, device execution, or production lighting policy owned by other HomeHub workstreams.

---

# Design Intent

The bedroom should feel like a real, recognizable room that has been elevated into a premium architectural presentation.

It should preserve the apartment's actual geometry, proportions, major furniture, and meaningful objects while improving the visual finish through materials, lighting, atmosphere, and restrained decor.

The room should feel:

- personal
- minimal
- premium
- warm
- calm
- quietly futuristic
- intelligently responsive

It should not feel:

- like a sci-fi command center
- like a gaming showroom
- like a generic luxury render
- like a dollhouse viewed from too far away
- like a flat device-status dashboard

A useful shorthand is:

> A beautiful real bedroom that happens to understand what it is being used for.

---

# Spatial Truth

The completed Apartment Canvas geometry remains the physical source of truth.

This pass must preserve:

- actual bedroom geometry
- actual room proportions
- desk placement
- bed placement
- projector / projection-wall relationship
- windows and balcony relationship
- major furniture placement
- meaningful persistent objects

The design pass may improve presentation, but it must not redesign the room into a different apartment.

Major furniture should not be invented or relocated for aesthetics.

---

# Scale and Framing

## Core problem

The current Apartment Canvas can make the apartment feel visually small and distant even when the geometry itself is correct.

The preferred solution is **not** to make close-up room compositions the default.

The whole-apartment presentation remains important. The design goal is to make the apartment feel larger, more present, and more legible while preserving the established proportions and wider architectural composition.

## Preferred approach

Explore:

- using more of the available canvas area
- reducing unnecessary empty background around the apartment
- adjusting camera distance without flattening the model
- tuning field of view to increase visual presence while avoiding distortion
- refining camera elevation and perspective
- improving material contrast and lighting readability from the wider shot
- ensuring the bedroom can remain visually important even when the whole apartment is visible

## Room-focused fallback

A closer bedroom composition is acceptable when a meaningful state cannot be communicated clearly from the wider apartment view.

This should be a directed presentation state, not the everyday default.

The system should return to a satisfying wider apartment composition after the focal moment when appropriate.

---

# Room Personality

The bedroom has two primary personalities that share the same physical space.

## Desk / Command Center

### Story

> The home understands that focused personal activity is happening here.

### Emotional target

- focused
- personalized
- capable
- calm
- premium
- lived-in

The strongest JARVIS influence in Apartment Canvas may appear here, but it should be expressed through intelligence and responsiveness rather than sci-fi styling.

Good cues:

- purposeful emphasis on the desk zone
- subtle display contribution
- localized lighting support
- restrained contextual information
- a composed visual hierarchy

Avoid:

- holograms
- neon overload
- walls of data
- fake control panels
- excessive blue lighting
- command-bunker aesthetics

The desk should read as a beautiful workspace first and an intelligent workspace second.

## Projector / Cinema

### Story

> The same room has changed purpose.

### Emotional target

- immersive
- cinematic
- transformed
- comfortable
- intentional
- slightly magical

Projector activation should be one of Apartment Canvas's strongest transformation moments.

The goal is not merely to indicate that a projector device is on. The visual composition should communicate that the bedroom has entered a different experience.

---

# Visual Hierarchy

## Neutral / general bedroom state

Priority order:

1. room as a coherent whole
2. desk zone
3. bed and residential softness
4. projector wall / projection area
5. secondary decor and ambient detail

## Desk-focused state

Priority order:

1. desk and primary display area
2. task / desk lighting contribution
3. local environmental response around the desk
4. room context
5. bed and projector area as secondary background

The room should remain visible enough to feel residential rather than becoming a cropped workstation view.

## Projector-focused state

Priority order:

1. projection wall / screen area
2. projector-related light and screen behavior
3. cinema-supporting room lighting
4. bed / viewing environment
5. desk zone receding into the background

The projector should become the focal point without making the rest of the room visually disappear.

---

# Material Direction

## Overall material language

Materials should feel:

- clean
- believable
- refined
- warm
- minimal
- premium without looking synthetic

This pass should improve the perceived quality of the room without changing its identity.

## Hardwood

The hardwood is a strong candidate for visual improvement.

Keep the existing floor identity recognizable while improving:

- grain definition
- tone consistency
- subtle reflectance
- material depth
- response to warm and cool light

The floor should feel like a more beautiful version of the real floor, not a replacement floor.

## Walls and trim

Walls should remain understated and architectural.

They should provide a clean canvas for:

- daylight
- projector spill
- ambient light
- subtle shadow depth

Avoid making wall materials visually busy.

## Desk surfaces

The desk should feel intentional and premium but still real.

Target qualities:

- crisp edges
- believable surface finish
- restrained reflectance
- enough texture to avoid a placeholder-render appearance

The desk should not be unrealistically empty or showroom-perfect if persistent objects are part of the real setup.

## Bedding and textiles

The bed is important for keeping the room warm and residential.

Textiles should add:

- softness
- depth
- warmth
- realistic folds / material variation

The bed should visually counterbalance the technological identity of the desk and projector zones.

## Projection surface

When inactive, the projector wall / surface should remain calm and architectural.

When active, it should become visually important through:

- projection luminance
- subtle wall illumination
- believable spill
- controlled bloom / glow
- content or activation treatment when available

Avoid making it look like a conventional emissive television panel if the real experience is projection-based.

---

# Object Fidelity

Recognizable daily-life objects should remain true when they materially contribute to the identity of the space.

Bedroom priorities may include:

- desk
- primary monitor / display presence
- projector-related hardware
- bed
- persistent side furniture
- recognizable technology that is consistently present
- stable decor or objects that make the room feel specifically real

The design pass may simplify visual clutter where needed, but it should not sterilize the room into a generic render.

The broader Apartment Canvas rule remains:

> Keep meaningful real objects true; improve their presentation rather than replacing their identity.

---

# Lighting Design

## Core rule

Real lighting state informs the scene, but the renderer is responsible for making that state beautiful on screen.

Individual relevant lights should remain individually represented rather than collapsing into one generic room tint.

The renderer may tune:

- hue
- saturation
- brightness
- softness
- diffusion
- glow radius
- falloff
- bounce
- environmental spill

This allows the digital twin to preserve the meaning of the real lighting state without reproducing unattractive rendering artifacts or overly saturated color output.

For example, an ember-style real light may be represented with a softer, warmer, less saturated interpretation while remaining recognizably ember-like.

## Daytime

Target:

- realistic sunlit apartment
- open and calm
- clear material definition
- believable daylight direction
- soft shadows

Daylight should do most of the visual work when appropriate.

The desk may remain visually important through composition and material detail rather than artificial accent lighting.

## Evening ambient

Target:

- warm
- layered
- settled
- comfortable
- premium

Prefer:

- restrained color
- warm pools of light
- visible fixture contribution when visually useful
- controlled contrast
- soft environmental spill

Avoid:

- flat room-wide color washes
- oversaturated RGB
- multiple competing accent colors

## Desk active

Target:

- focused but cozy
- intelligent but calm
- locally emphasized without isolating the desk from the room

Potential visual treatment:

- stronger local task-light contribution
- display glow that subtly affects nearby surfaces
- surrounding room becoming slightly quieter
- controlled contrast around the desk zone

The result should feel like focused personal use, not theatrical technology lighting.

## Projector / cinema active

Target:

- one of the strongest visual transformations in HomeHub
- immersive without becoming dark for darkness's sake
- projector output as a major source of visual emphasis
- supporting lights serving the cinema experience rather than competing with it

Potential treatment:

- projection surface gains luminance and controlled bloom
- subtle projection spill reaches nearby surfaces
- supporting ambient lights dim, warm, or shift according to the real state and approved lighting policy
- desk area visually recedes
- room contrast increases enough to communicate transformation

The screen rendering may be artistically tuned beyond literal real-world appearance so long as the room still reads as a believable projection environment.

## Sleeping / night quiet

Target:

- restrained
- low-energy
- restful
- visually quiet

Use darkness intentionally. Do not add decorative glow simply because the renderer can.

Sleeping lifecycle behavior remains owned by House State & Automation; this document only defines the desired visual treatment once an appropriate state is presented.

---

# Camera Design

## General behavior

Camera movement should remain slow, deliberate, and motivated by meaningful home context.

This pass does not authorize camera movement for arbitrary device toggles.

The Director Board principle remains authoritative:

> Story before device.

## Default presentation

The preferred steady-state composition should preserve broader apartment context while making the bedroom sufficiently large and readable.

The exact camera solution should be determined experimentally through rendering rather than assumed to require a close crop.

## Desk emphasis

A desk-focused camera change should be subtle.

Possible sequence:

1. credible desk activity becomes meaningful to the home story
2. camera biases toward the desk zone
3. movement slows into a composed presentation
4. lighting / display contribution becomes easier to read
5. camera stabilizes without dramatic zoom or orbit behavior

The desk camera should feel like a product presentation, not a surveillance response to a monitor waking.

## Projector focal fly-by

Projector activation is the primary focal-fly-by candidate for this room.

Preferred sequence:

1. meaningful projector / bedroom-cinema context becomes active
2. camera begins a deliberate approach toward the projection wall
3. movement decelerates near the focal area
4. projector surface performs a refined activation / reveal treatment
5. supporting lighting visibly settles into cinema presentation
6. camera holds briefly on the transformation
7. camera pulls back or transitions to a strong wider composition
8. projector / cinema remains visually dominant in the final view

The goal is to create a memorable transformation moment while still returning the apartment to a useful steady-state presentation.

## Fallback if the full fly-by is too difficult

Use a smaller camera push or bedroom-biased composition while preserving the same storytelling order:

- approach
- reveal
- settle
- return / stabilize

Do not substitute fast zooms or abrupt cuts purely for spectacle.

---

# UI Overlay Direction

The apartment remains the hero.

Bedroom overlays should be minimal and contextual.

Potential examples:

- inferred activity wording such as `Likely: Getting Ready` when appropriate
- a restrained focus / media context label
- minimal projector or room-state indication when useful

Avoid:

- dense telemetry
- large control cards over the room
- persistent labels on every object
- information that duplicates what the room already communicates visually

The UI should explain only what the environment cannot communicate clearly by itself.

---

# Enhancement Budget

This room should use the same approximate 5–6 / 10 idealization target defined for Apartment Canvas overall.

Allowed:

- richer materials
- improved hardwood treatment
- better textiles
- small tasteful decor additions
- restrained plant / styling accents if plausible
- visual cleanup of minor clutter when it improves readability
- screen-friendly lighting interpretation

Not allowed:

- new major furniture
- changed room layout
- fictional architectural features
- overt sci-fi technology
- decor that makes the room feel like a different person's apartment

The room should remain unmistakably the real bedroom.

---

# Cross-Workstream Boundaries

The bedroom design pass is owned by **Dashboard UI**, but implementation must use the other HomeHub workstreams rather than silently redefining their behavior.

## Dashboard UI

Owns:

- rendering
- material presentation
- camera composition
- visual emphasis
- projector-screen visual treatment
- overlays
- cinematic transitions

## Lighting & Atmosphere

Consult / hand off when deciding:

- production Hue scene intent
- room palette choices
- physical fixture behavior
- actual evening / cinema atmosphere policy
- whether a rendered interpretation still represents the intended real lighting experience

Dashboard may artistically interpret lighting for the screen, but it should not redefine production lighting policy by itself.

## House State & Automation

Consult / hand off when deciding:

- which lifecycle or context transitions are meaningful enough to trigger presentation changes
- Winding Down / Sleeping visual transitions
- dwell / transition semantics
- whether projector or desk activity should affect the current home story

A camera effect must not become an implicit lifecycle rule.

## Sensing & Intelligence

Consult / hand off when deciding:

- whether desk activity evidence is trustworthy
- whether bedroom / physical activity context is credible
- confidence needed before a semantic activity drives a visual story

Physical evidence continues to outrank weak software guesses.

## Devices & Integrations

Consult / hand off when implementation touches:

- projector state / execution
- Hue device state
- Sonos or media-device adapters
- Kasa or other room-device execution

Dashboard should consume reliable device / context interfaces rather than implementing device control logic itself.

## Runtime & Infrastructure

Consult only when visual implementation requires deployment, service, networking, or runtime changes.

Do not couple the design pass to runtime operations prematurely.

---

# Validation Strategy

The first implementation should be validated visually before adding more cinematic behavior.

Recommended validation sequence:

1. confirm geometry and object placement remain unchanged
2. verify the wider apartment composition can make the bedroom feel large and legible enough
3. evaluate materials in neutral daylight
4. evaluate evening lighting without projector activity
5. evaluate desk-focused presentation
6. evaluate projector / cinema presentation
7. evaluate focal fly-by only after the static target looks correct
8. compare results against real apartment reference photos and accepted lighting references

Do not use camera motion to hide weak geometry, materials, or lighting.

Static frames should look intentional before transitions are considered successful.

---

# Acceptance Criteria

This design pass is visually successful when:

- the bedroom remains recognizably the real room
- established apartment geometry and proportions remain intact
- the bedroom feels substantial and legible from the preferred wider Apartment Canvas presentation
- the desk feels like a calm personal command center without sci-fi styling
- the bed and textiles keep the room warm and residential
- the projector state feels like a true room transformation rather than a device status change
- real lighting state can be represented individually while being artistically tuned for screen presentation
- evening lighting avoids harsh, oversaturated, or visually disconnected effects
- projector lighting and screen spill feel cinematic but believable
- camera behavior is motivated by meaningful context rather than arbitrary device changes
- the projector focal fly-by feels slow, deliberate, and premium
- the room can return to a strong wider apartment composition after focal emphasis
- material enhancement improves the real apartment rather than replacing its identity
- UI overlays remain restrained and secondary

---

# Implementation Order

Recommended order for this room:

1. inspect the current bedroom geometry, rendering code, and state interfaces
2. establish a stronger static default / wider composition
3. improve bedroom materials and object fidelity
4. establish neutral daylight presentation
5. establish evening ambient presentation
6. establish desk-active visual treatment
7. establish projector / cinema visual treatment
8. validate static screenshots against this document
9. implement the projector focal fly-by
10. implement desk camera emphasis if it remains useful after static validation
11. review cross-workstream behavior before wiring any new automatic triggers

---

# Done When

The bedroom pass is ready to move on when a reviewer can look at static and state-specific frames and say:

- this is clearly the real apartment
- the room no longer feels like a small developer model
- the desk feels intelligent without looking sci-fi
- the projector makes the room feel transformed
- the lighting looks intentionally designed for the screen
- the camera has a clear storytelling role
- future behavior can be implemented without guessing at the visual target

At that point, Bedroom / Desk / Projector becomes the reference implementation for later Apartment Canvas room passes.