# Apartment Canvas Design Language

## Status

Draft v1

## Purpose

Apartment Canvas is the visual heart of HomeHub. It is not a floor plan viewer and it is not a generic smart-home dashboard. It is a living digital twin of the apartment: a faithful spatial representation of the real home, elevated through cinematic rendering, intentional lighting, and calm contextual intelligence.

This document defines the visual design language for Apartment Canvas so future implementation stays aligned across modeling, rendering, camera behavior, lighting, and UI presentation.

Apartment Canvas should feel like:

- a premium, living architectural experience
- a true representation of the apartment
- a calm and intelligent interface
- a cinematic expression of what the home feels like

Apartment Canvas should not feel like:

- a developer preview
- a top-down floor plan tool
- a sci-fi command center
- an over-designed smart-home gimmick

## Core Design Statement

HomeHub presents the apartment as a living architectural experience: a faithful digital twin enhanced with cinematic materials, intentional lighting, and contextual intelligence. The experience should feel less like controlling a house and more like the house naturally adapting around its occupant.

## Visual North Star

The north star for Apartment Canvas is:

- Apple-level polish
- real apartment warmth
- minimal, premium visual restraint
- subtle JARVIS-like intelligence in behavior, not sci-fi aesthetics

The JARVIS influence should come through in how the system responds, reveals context, and highlights meaningful activity. It should not rely on holographic, futuristic, or overtly science-fiction visual language.

A useful shorthand is:

> Apple designed the operating system for this apartment.

## Foundational Principles

### 1. The apartment is real

Apartment Canvas is grounded in the actual apartment geometry, layout, and major objects. The geometry work already completed is the source of truth and should not be replaced by a generic or approximate model.

Must remain true to reality:

- apartment geometry
- room proportions
- sight lines
- window and door placement
- major furniture placement
- primary appliances and fixtures
- notable persistent countertop appliances and room objects

This includes keeping the kitchen appliances and persistent objects true to the real apartment, including countertop items such as the air fryer and coffee machine.

### 2. The presentation is elevated

While the apartment must stay true to itself, its presentation should be enhanced so the digital twin feels beautiful, cinematic, and alive.

Allowed enhancements include:

- richer materials
- improved texture quality
- tasteful small decor accents
- subtle plants or styling touches
- refined hardwood/material rendering
- improved nighttime depth and contrast
- beautiful lighting interpretation

Not allowed:

- major layout changes
- new large furniture
- turning the apartment into a different space
- over-stylization that breaks recognition

### 3. Intelligence should be calm

Apartment Canvas should feel aware, not loud.

The home should communicate intelligence through:

- camera focus
- lighting response
- subtle environmental emphasis
- state-aware framing
- restrained UI overlays

It should avoid:

- noisy visual effects
- constant motion
- excessive data overlays
- obvious AI theatrics

### 4. The home should feel cinematic, not literal

Apartment Canvas is magic-first in presentation, but truth-first in structure.

That means:

- the apartment remains recognizable and real
- the render can idealize or soften the presentation
- lighting can be artistically interpreted
- scenes should communicate how the home feels, not just what a bulb literally looks like

## Realism Target

Apartment Canvas should use a moderate realism/idealization blend.

A useful rule is:

> The apartment should look like itself on its best day.

This means:

- faithful geometry
- true object identity where important
- slightly enhanced materials
- slightly elevated decor/styling
- more beautiful rendering than a literal raw copy of reality

The final target is premium, cinematic, clean, warm, believable, and recognizable. It should feel closer to a premium architectural visualization or Apple product-demo environment than a rough 3D planner, while avoiding both sterile photorealism and overt stylization.

## Material Philosophy

### Overall material language

The apartment should read as:

- minimal
- premium
- soft-modern
- clean
- restrained
- subtly warm
- quietly futuristic

The visual language should avoid both extremes: it should not feel sterile and showroom-cold, but it should also not become cluttered or over-decorated.

### Floors

The hardwood can be artistically improved, but it should remain recognizably similar to the real apartment flooring.

Desired qualities:

- believable tone
- richer grain
- subtle reflectance
- premium finish without looking fake

### Counters and surfaces

Countertops should remain true to the real apartment. Surface rendering should emphasize quality and realism through texture, reflections, and subtle lighting response rather than changing the fundamental material identity.

### Walls and trim

Walls should remain clean and understated, functioning as a calm backdrop that allows lighting and furniture to carry the atmosphere.

### Furniture

Furniture should stay true in placement and general identity. Minor enhancement to material richness or finish is acceptable, but large substitutions are not.

### Appliances and persistent room objects

Appliances should remain true to the real apartment. Countertop appliances and persistent household items that shape the identity of the apartment should be represented accurately where feasible.

Examples include:

- coffee machine
- air fryer
- other stable countertop appliances

If recognizable product identity can be represented tastefully, that is desirable.

### Decor philosophy

Small decor additions are allowed if they improve the atmosphere and still feel plausibly part of the real apartment.

Good examples:

- tasteful plant accents
- a subtle decorative object
- soft styling touches
- premium but restrained detail

Bad examples:

- dramatic new furniture
- showroom staging that changes the apartment character
- excessive styling that feels fake

## Lighting Philosophy

Lighting is one of the most important differentiators of Apartment Canvas.

### Core rule

Real lighting state should inform the scene, but the render should interpret that state beautifully for screen presentation.

Each relevant light should:

- be represented individually
- retain its role and identity in the scene
- contribute to the mood of the room
- be rendered with artistically tuned softness, hue, brightness, diffusion, and spill

Apartment Canvas should not attempt a harsh 1:1 simulation of how every light literally appears in real life. Real-world lighting states may need to be softened, balanced, or visually translated so they look premium on screen while preserving the meaning of the state.

### Lighting source truth vs visual interpretation

Source truth should preserve:

- which lights are on
- which zones are active
- the relevant scene or room state
- contextual mode, such as desk active, projector active, or evening ambiance

The renderer may adjust:

- softness
- glow falloff
- diffusion
- color balance
- saturation
- brightness balance
- bounce and environmental spill

For example, an ember-style light may be too saturated or visually aggressive when rendered literally. Apartment Canvas may retain the ember character while tuning hue, softness, brightness, and falloff so the on-screen result feels natural and premium.

### Daytime

Daytime should feel like a realistic sunlit apartment.

Priorities:

- natural light
- architectural clarity
- soft daylight
- believable sun and shadow behavior
- calm, clean atmosphere

### Sunset / transition

The home should feel like it is moving from daylight into evening.

Priorities:

- warmth
- subtle contrast
- gentle transition
- a sense of the apartment settling in

### Evening

Evening should lean into Hue-style layered ambiance.

Priorities:

- warm and comfortable mood
- visible fixture contribution where it helps
- layered pools of light
- depth and contrast
- intentional atmospheres rather than flat illumination

### Cinema / projector mode

This is one of the strongest transformation states in the system.

Priorities:

- projector glow
- room transformation
- intentional dimming
- supporting ambient accent lighting
- a more cinematic and immersive emotional tone

### Sleeping / night quiet

Night states should feel restful and restrained.

Priorities:

- darkness with purpose
- soft low-level accents only when needed
- quiet, low-energy atmosphere

### Color philosophy

Apartment Canvas should avoid equating smart-home lighting with oversaturated RGB visuals. The lighting language should favor warmth, restraint, color with intent, elegant contrast, and fewer but stronger choices.

## HomeHub Visual Identity

Apartment Canvas should embody HomeHub identity through the apartment itself, not through decorative interface chrome.

Desired traits:

- premium
- calm
- modern
- architectural
- personal
- warm
- subtly futuristic
- intelligently alive

For HomeHub, futuristic does not mean sci-fi. It means seamless, context-aware, elegant, quietly advanced, and polished in a way that feels slightly ahead of today.

Good futuristic cues include:

- purposeful camera behavior
- state-aware environmental transitions
- refined screen and projector moments
- clean visual responsiveness
- subtle spatial emphasis

Bad futuristic cues include:

- holographic overlays everywhere
- spaceship aesthetics
- neon overload
- exaggerated AI effects

## Camera Philosophy

### Core philosophy

Camera movement should feel slow, deliberate, and purposeful, like an Apple product demo.

The camera should not wander randomly. It should move because the home has something meaningful to show.

### Whole-apartment presentation and scale

The whole apartment remains an important primary composition. Apartment Canvas should not solve readability by abandoning the wider apartment view or by defaulting to close room shots.

Instead, the rendering and camera system should make the apartment itself feel larger, more present, and easier to read while preserving its proportions and overall composition.

This may include:

- using more of the available canvas area
- reducing unnecessary empty background around the model
- adjusting camera distance and field of view while preserving believable proportions
- choosing a stronger perspective that gives rooms more visual presence
- ensuring lighting, materials, and active areas remain legible from the wider view

The goal is to preserve the feeling of seeing the home as a whole while making it feel substantial rather than small or distant.

### Focused room states

When a meaningful event needs emphasis, the camera may move closer or bias toward one room or feature. This should be a temporary directed moment rather than the default presentation language.

If a full-apartment angle cannot give enough prominence to the active feature, a room-focused composition is acceptable as long as the transition remains intentional and the camera returns to a satisfying wider state afterward.

### Directed focal fly-bys

A preferred behavior is a focal fly-by tied to meaningful activity.

Example: projector activation

1. Projector state becomes active.
2. Camera begins a deliberate approach toward the projector wall or projection area.
3. Motion slows as the projector becomes the focal point.
4. The projector screen or projection surface performs an elegant reveal or activation animation.
5. Supporting lighting transitions reinforce the cinema state.
6. Camera pulls back or resolves into a wider apartment composition where the projector remains visually important.

The same philosophy can be used for other meaningful zones, such as:

- desk activation
- living-room relaxation or media activation
- bedroom transition
- kitchen activity
- other significant state changes

The principle is:

> Briefly highlight the meaningful aspect of the home, then return to a stable, beautiful composition.

### Movement qualities

All movement should feel:

- smooth
- calm
- intentional
- elegant
- premium

Avoid:

- fast pans
- dramatic spins
- erratic zooms
- game-like camera motion
- device-driven movement without meaningful context

## Director Board Relationship

The Director Board defines intentional camera and story moments. It is not a prescription for constant motion.

This design language extends that approach by clarifying how those moments should look and feel.

The Director Board should continue to be driven by:

- physical evidence
- contextual meaning
- state relevance
- emotional tone

Random device-driven movement should remain avoided.

## UI Overlay Philosophy

The UI overlay should support the apartment, not compete with it.

Overlay goals:

- calm
- minimal
- readable
- non-intrusive
- premium
- contextually useful

Information should appear when it adds meaning. The home itself should remain the main visual object.

The overlay should privilege:

- state/context summary
- minimal labels
- subtle mode indicators
- relevant status only when helpful

The overlay should avoid:

- dashboard clutter
- dense telemetry
- excessive cards
- heavy framing chrome

The apartment is the hero. The overlay is a whisper.

## Room-by-Room Emotional Targets

### 1. Bedroom / Desk

This is the highest-priority identity zone.

Emotional role:

- personal command center
- intelligent but calm
- focused
- private
- lived-in but premium

Desk-active behavior should provide the strongest JARVIS-like intelligence moment without sci-fi styling. It should communicate that the home understands work or focus is happening, that the space is active and personalized, and that lighting and display behavior are supporting concentration.

The result should read as a beautiful workspace, not a command bunker.

### 2. Bedroom / Projector / Cinema

This is one of the strongest transformation moments in the product.

It should communicate:

- environment change
- immersive mode
- a room becoming an experience
- Apple-like cinema transformation, not merely projector on

The projector should be a strong candidate for directed camera fly-by behavior and for a signature visual transition.

### 3. Living Room

Emotional role:

- relaxation
- social comfort
- quiet elegance
- media without media obsession

The living room should not only communicate that a television or device is active. It should communicate that the home has entered a relaxation or gathering mode.

### 4. Kitchen

Emotional role:

- daily life
- clean architecture
- quiet utility
- warmth and routine

The kitchen should feel real and grounded, with accurate appliances and a premium rendering of everyday life.

### 5. Balcony

Emotional role:

- threshold
- atmosphere
- exterior connection
- special-view potential

The balcony is important both as a real space and as a cinematic threshold into the apartment.

### 6. Entry / Welcome View

Emotional role:

- arrival
- orientation
- calm welcome

This is lower priority for everyday storytelling but remains important in guided experiences and guest-facing flows.

## Story Layer Philosophy

Apartment Canvas should not only show rooms. It should show what the home is communicating.

Examples:

- desk active = focus / personal intelligence
- projector active = cinematic transformation
- living media active = relaxation / leisure
- evening lights = settled comfort
- sleeping transition = quiet retreat

The apartment should feel like it is telling a story about the state of the home.

## Guest Experience and Signature Reveal

A special guided cinematic reveal should exist for guest-facing experiences, especially when a guest joins the guest network and opens the HomeHub experience on their phone.

This is not the default persistent kiosk behavior. It is a special introduction sequence for the guest experience.

Preferred reveal:

1. begin with a drone-like exterior approach to the apartment building
2. move around the building toward the apartment
3. approach the balcony
4. enter through the balcony into the apartment
5. transition naturally into the guest-facing HomeHub experience

The exact path should depend on what is technically feasible and visually convincing. The goal is not realism for its own sake; the sequence should feel premium, welcoming, memorable, and connected to the real location.

The kiosk remains free to use whatever steady-state Apartment Canvas view is best for everyday HomeHub operation. The guest reveal is a separate, intentional cinematic experience optimized for a phone-sized entry point.

## Realism vs Enhancement Rules

Preserve where identity matters:

- apartment geometry
- room layout
- major furniture
- core appliances
- persistent countertop items
- key object identity

Enhance where it improves feeling:

- material richness
- decor accents
- small atmospheric details
- hardwood finish
- lighting softness
- nighttime beauty
- screen-friendly color interpretation
- spatial drama through camera work

A useful implementation rule is:

> If a change makes the space more beautiful but less recognizably this apartment, it should be rejected or reduced.

## Implementation Priorities

The current implementation priority is to establish the visual language first, then execute room-by-room design passes.

Recommended sequence:

1. bedroom / desk design pass
2. projector / cinema design pass
3. living room design pass
4. kitchen design pass
5. balcony detail pass
6. Story Board v1
7. camera rigs
8. final cinematic transitions

This order reflects the apartment emotional priorities rather than generic room importance.

## Acceptance Criteria

Apartment Canvas is visually aligned when:

- it clearly reads as the real apartment
- the completed geometry remains the physical source of truth
- the whole-apartment composition feels substantial and legible rather than small or distant
- it feels premium, calm, warm, and intentional
- it does not feel like a floor plan viewer
- it does not feel like a sci-fi dashboard
- individual lights are represented meaningfully while their screen rendering is artistically tuned
- camera movement feels purposeful rather than random
- meaningful events can receive brief focal fly-bys before returning to a strong wider composition
- the desk and projector zones feel like distinct signature experiences
- the apartment feels cinematic without becoming fake
- major appliances and persistent household objects remain recognizable
- the UI overlay remains restrained and secondary

## Summary

Apartment Canvas is a faithful but elevated digital twin of the apartment.

Its job is not merely to show where things are. Its job is to make the home feel alive.

It should combine:

- real spatial truth
- premium architectural rendering
- beautifully interpreted lighting
- calm contextual intelligence
- purposeful camera direction

The result should feel like a living, cinematic home experience: unmistakably the real apartment, but presented with the polish and intention of a world-class product.
