# Dashboard Apartment Canvas Spec

Status: **accepted geometry/content authority for the #157 Apartment Canvas exploration**  
Owner: Dashboard UI workstream  
Parent vision: `docs/DASHBOARD_REDESIGN_VISION.md`  
Established: 2026-08-19

## Purpose

This document locks the physical/spatial contract for the Home Apartment Canvas before additional visual rendering or implementation. It exists specifically to prevent future concepts from inventing a different apartment while still pursuing the accepted living-instrument / 2.5D-diorama design direction.

## Source-of-truth hierarchy

1. **Canonical floor plan** is absolute authority for walls, room footprints, doors/openings, balcony, kitchen footprint, bath/closet/laundry/mechanical geometry, entry, and circulation.
2. **Annotated furniture floor plan** is authority for approximate furniture/device positions and orientation inside those canonical rooms.
3. **Apartment photographs** are authority for object appearance, relative scale, material cues, device relationships, and lighting appearance. Photos do not override canonical geometry.
4. **Dashboard design language** may simplify or exaggerate objects for readability, but must preserve truthful room/object relationships.

A future render is wrong if it looks attractive but violates this hierarchy.

## Camera / framing

Desktop Home uses a fixed elevated 3/4 roofless-diorama camera from the **upper/desk-side corner of the bedroom**, looking outward across the apartment. This is a cinematic architectural viewpoint, not a literal first-person view from the chair and not a generic showroom angle.

The framing should keep the bedroom desk/sleep zones, doorway, living room, kitchen, and balcony/exterior edge legible without altering floor-plan geometry.

Mobile uses context-aware framing rather than shrinking the full desktop view: desk/bedroom for Gaming or Working, sleep side for Sleeping/Winding Down, living room for Watching/Relax/Social, kitchen for Cooking, with an explicit whole-apartment view available.

## Bedroom

The bedroom has dual semantic identity: **desk/PC/Gaming/Working** and **Sleeping/Winding Down**.

Canonical anchors:
- bed at the real photographed/annotated orientation;
- **L-shaped desk** along the lower bedroom wall near the doorway;
- chair facing the main desk section; when seated, the bedroom door is to the left;
- the thinner desk return extends close to the bed;
- monitor/PC setup;
- microphone;
- headphones;
- both bedroom lamps;
- desk Alexa near the lamp closest to the door;
- **projector hardware on the thin desk return**.

There are **no bedroom plants** in the current physical model.

The projector aims at the opposite bedroom wall. The projector wall should remain understated when inactive and become a strong illuminated rectangular projection surface only while the projector is active.

## Living room

Canonical anchors:
- brown sofa in its real orientation;
- rectangular coffee table close to/in front of the couch;
- simplified living-room rug under the seating group;
- white rounded chair near the balcony/window side;
- TV and TV stand/media console at the real location;
- subwoofer immediately next to the TV stand;
- living-room lamp;
- plant grouping at the annotated location;
- living-room end-table cluster with **Alexa on top and Sonos Era 100 on the lower shelf**.

Treat Alexa + Sonos as one visual furniture/device cluster. The **TV**, not the projector, is the living-room screen state.

## Plants

Plant geometry should be species-recognizable by silhouette rather than botanically detailed.

Current plant truth:
- snake plant — inside in the living-room plant grouping;
- ZZ plant — inside in the living-room plant grouping;
- monstera — on the balcony during warm season and brought indoors during fall/winter.

Seasonal plant placement may eventually become real apartment state rather than static decoration.

## Kitchen

The floor plan strictly owns kitchen geometry.

Recognizable anchors:
- island with sink;
- perimeter white/gray cabinetry;
- refrigerator;
- stove/oven;
- microwave;
- two stools;
- pendant lights;
- simplified kitchen runner rug.

Countertop clutter is not required.

## Bathroom / closet / laundry / mechanical / entry

These support spatial recognition but stay lower-detail than bedroom/living/kitchen.

Preserve canonical geometry and simplified recognizable anchors:
- bathroom vanity/sink, toilet, shower;
- closet footprint;
- laundry area;
- water-heater/mechanical enclosure;
- entry/front door;
- annotated entry dresser.

## Balcony / exterior band

Preserve exact balcony geometry from the floor plan. The balcony/exterior edge becomes the restrained ambient-world boundary for daylight, weather, seasonal monstera placement, and confidence-gated outside audio micro-events such as birds, sirens, rain, or traffic.

Do not invent exact outdoor localization that sensing does not support.

## Device representation

Primary live-state anchors include:
- monitor/PC;
- both bedroom lamps;
- projector + projector-wall result;
- TV;
- Sonos;
- living-room lamp;
- kitchen lighting;
- front door where state is trustworthy.

Alexa devices should be subtle ambient-system nodes rather than detailed miniature smart speakers or permanently labeled icons. Exact visual treatment remains open; a quiet neutral node that turns Alexa-blue while active is the current preferred exploration.

## Rendering density

The canvas is an **architectural instrument**, not a Sims-like reconstruction.

Model for recognition/state/interaction, not completeness:
- furniture silhouettes should resemble the real anchors;
- rugs preserve shape/color family, not pattern fidelity;
- plants preserve species silhouette, not leaf-level detail;
- omit most desk clutter, cables, countertop clutter, tiny decor, detailed closet contents, and permanently exposed sensor hardware;
- live light should illuminate nearby geometry rather than be represented primarily by floating circles.

## Four visual layers

1. **Physical World** — architecture, anchor furniture, meaningful devices.
2. **Live State** — illumination, active devices, room/context emphasis.
3. **Causality** — temporary evidence/decision/automation traces shown on event or Explain.
4. **Ambient World** — exterior weather/daylight/audio micro-events.

Home normally emphasizes layers 1–2. Layer 3 is mostly dormant; Analytics/Insights exposes the machinery much more aggressively.

## Geometry-first concept gate

Before another polished Home dashboard composition is attempted, create and review a **geometry-first Apartment Canvas concept** with:
- no dashboard sidebars;
- no fake telemetry or confidence values;
- no causality traces;
- no decorative machine UI;
- no invented room geometry;
- only canonical architecture, accepted furniture/device anchors, camera/framing, and basic architectural materials.

Reject the concept if the apartment itself is spatially wrong, even if the styling is attractive. Only after geometry/content is visually accepted should live lights, device state, ambient events, causality, or surrounding Home UI be layered in.

## Still-open visual questions

These are design explorations, not geometry uncertainties:
- exact wall height/cutaway depth;
- degree of furniture simplification;
- inactive/active Alexa-node treatment;
- projector-wall active visual strength;
- exact camera pitch/yaw needed to preserve visibility without distortion;
- final wall/floor/material palette.
