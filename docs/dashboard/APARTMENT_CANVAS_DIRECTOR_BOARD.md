# Apartment Canvas Director Board

## Status

Version: v1  
Status: Accepted  
Owner: Dashboard UI  
Related: Apartment Canvas redesign

---

# Purpose

The Apartment Canvas is not intended to be a surveillance view or a device status dashboard.

It is a cinematic representation of the home's current story.

**Premium-render handoff ? 2026-09-01:** Director Board owns composition/story framing, not renderer quality. Whitebox/static previews may validate rigs, but production-facing camera acceptance must be rechecked on #217 Premium Render v1.

The camera system should:

- communicate how the home is being used
- highlight meaningful activity
- make HomeHub feel intelligent and intentional
- present the apartment as a designed product

The camera is a storyteller, not a sensor.

---

# Design Principles

## Camera as Presentation

Camera positions should feel like:

- architectural photography
- premium product visualization
- Apple-style product storytelling

Camera positions should not feel like:

- security cameras
- first-person viewpoints
- room navigation
- constant monitoring

---

## Exterior Observation

Primary camera rigs should remain:

- outside the apartment
- slightly elevated
- looking inward
- spatially aware of the whole environment

The apartment should feel like a physical object being presented.

---

## No Continuous Motion

Camera movement should not be constant.

The system should not:

- orbit continuously
- randomly fly around
- move because a single device changes state

Movement should happen only when:

- the current story changes
- a meaningful context transition occurs
- a user intentionally enters a presentation mode

---

## Story Before Device

The system prioritizes:

> What is happening in the home?

over:

> Which device changed?

Examples:

Good:
- Living room becomes active → present the living room story

Bad:
- TV turns on → zoom directly into the TV

Good:
- Desk becomes active → present the command center environment

Bad:
- Monitor wakes → camera follows the screen

---

# Core Camera Rigs

## Hero Overview

### Story

"This is your home."

### Purpose

Default apartment presentation.

### Used For

- Rest
- Neutral Home state
- Fallback presentation

### Personality

Calm. Architectural. Premium.

---

## Command Center

### Story

"Your personal control room."

### Purpose

Represent focused work, gaming, and personal computing.

### Used For

- Desk active
- Work sessions
- Gaming

### Visual Direction

This is where HomeHub intelligence can become visible.

Future possibilities:

- subtle wall displays
- contextual information panels
- system visualization

Avoid:

- excessive sci-fi
- distracting overlays
- unrealistic holograms

---

## Bedroom Cinema

### Story

"The room transformed."

### Purpose

Show the bedroom becoming an entertainment environment.

### Used For

- Projector active
- Bedroom viewing
- Cinema mode
- Evening relaxation

### Visual Direction

The projector should not behave like a normal television.

Future possibilities:

- realistic projection
- ambient wall illumination
- light spill
- projector effects

The goal:

The same room has changed purpose.

---

## Lounge

### Story

"The home is being enjoyed."

### Purpose

Represent relaxation, media, and social living.

### Used For

- Living media
- Couch relaxation
- Ambient entertainment
- Social activity

### Visual Direction

The TV is not the subject.

The scene is the subject.

The system should communicate:

- someone is relaxing
- the room is active
- entertainment is part of the environment

### Balcony

The balcony should initially share this camera rig.

Different compositions may emphasize:

- living room
- outdoor relaxation

Do not create a dedicated balcony camera initially.

---

## Threshold

### Story

"The home receives you."

### Purpose

Represent arrival and departure.

### Used For

- Arriving home
- Leaving home
- Away/Home transitions

### Personality

An emotional transition point.

---

# Special Cinematic Mode

## Guest / Party Tour

### Story

"Welcome to the home."

This is a presentation experience, not normal automation.

Do not trigger solely from guest WiFi connection.

Possible future sequence:

1. Exterior building reveal
2. Approach apartment
3. Enter through balcony transition
4. Cinematic apartment movement
5. End on social scene

This is the one acceptable use of a true fly-through.

---

# Camera Authority Rules

Individual devices do not directly control the camera.

## Allowed

- meaningful context transitions
- user-selected inspection mode
- presentation modes

## Not Allowed

- single Alexa event
- single light change
- one device wake event
- minor sensor fluctuations

Examples:

| Event | Camera Change |
| --- | --- |
| TV turns on | No direct camera control |
| Projector becomes active | May request Bedroom Cinema |
| Desk activity persists | May request Command Center |
| Alexa wake word | No |
| User selects room | Yes |
| Guest presentation mode | Yes |

---

# State Mapping

| Context | Camera |
| --- | --- |
| Rest | Hero Overview |
| Home neutral | Hero Overview |
| Desk active | Command Center |
| Gaming | Command Center |
| Projector active | Bedroom Cinema |
| Living media | Lounge |
| Couch relaxation | Lounge |
| Balcony relaxation | Lounge alternate |
| Arrival | Threshold |
| Departure | Threshold |
| Guest presentation | Cinematic Mode |

---

# Deferred Concepts

## Kitchen / Hearth

Future story:

"Making."

Potential use:

- cooking
- coffee
- morning routines

Not required for v1.

---

# Implementation Guidance

## v1 Requirements

Implement:

- named camera rigs
- state-to-camera mapping
- manual testing controls
- cinematic transitions

Do not implement yet:

- autonomous camera intelligence
- prediction
- complex storytelling engine
- normal-use fly-through mode

---

# Acceptance Criteria

Apartment Canvas succeeds when:

- the user understands the current home state visually
- camera movement feels intentional
- the apartment remains the hero
- devices enhance the story instead of controlling it
- transitions feel premium rather than mechanical

---

# Decision Status

Director Board v1: ACCEPTED

Future camera work should build from this document rather than inventing new camera behaviors ad hoc.