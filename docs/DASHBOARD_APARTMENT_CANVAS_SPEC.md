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

## Approved deterministic geometry baseline

The geometry-first review is complete for the top-down apartment layout.

Anthony explicitly approved the **v1 top-down geometry baseline on 2026-08-19** after iterative correction against the canonical floor plan, annotated furniture plan, and apartment photographs.

Durable artifacts:
- `docs/dashboard/apartment_canvas/geometry_v1.json` — canonical normalized coordinate model;
- `docs/dashboard/apartment_canvas/truth_map_v1.svg` — approved plain top-down truth map rendered from that model.

The coordinate system uses **Apartment Geometry Units (GU)** with the traced apartment width normalized to `1000 GU`; x and y use the same uniform scale so the floor plan cannot be stretched independently.

From this point forward:
- approved x/y coordinates and wall polygons are spatial truth, not a styling suggestion;
- camera projection, wall height/cutaway, z-height, object extrusion, occlusion, and materials may be iterated without changing x/y geometry;
- any future x/y geometry change requires new real-world evidence and explicit approval;
- image generation must not be used to reconstruct or reinterpret apartment geometry.

Important 3D semantics preserved by the approved model:
- the PC tower is on the opposite/left side of the bedroom desk and physically **under the desk**;
- the monitor is centered along the main desk at the wall-side edge;
- microphone, headphones, and both desk lamps sit toward the rear of the desk near the monitor line;
- the microwave is an **over-range unit above the stove/oven**, despite sharing that footprint in the top-down representation.

## Camera / framing

Desktop Home uses a fixed elevated 3/4 roofless-diorama camera from the **upper/desk-side corner of the bedroom**, looking outward across the apartment. This is a cinematic architectural viewpoint, not a literal first-person view from the chair and not a generic showroom angle.

The framing should keep the bedroom desk/sleep zones, doorway, living room, kitchen, and balcony/exterior edge legible without altering floor-plan geometry.

Mobile uses context-aware framing rather than shrinking the full desktop view: desk/bedroom for Gaming or Working, sleep side for Sleeping/Winding Down, living room for Watching/Relax/Social, kitchen for Cooking, with an explicit whole-apartment view available.

## Bedroom

The bedroom has dual semantic identity: **desk/PC/Gaming/Working** and **Sleeping/Winding Down**.

Canonical anchors:
- bed flush to the real upper/window-side and west-wall position from the approved coordinate model;
- **L-shaped desk** hard-anchored along the lower bedroom wall near the doorway;
- thin desk return against the side wall with only a very small gap before the bed;
- chair facing the main desk section; when seated, the bedroom door is to the left;
- monitor centered along the rear/wall-side edge of the main desk;
- microphone and headphones on the rear part of the desk beside the monitor;
- both bedroom lamps on the rear part of the desk;
- desk Alexa near the lamp closest to the door;
- PC tower on the opposite/left side of the desk and physically **under the desk**;
- **projector hardware on the thin desk return**, aimed diagonally toward the projector wall area in front of the bed.

There are **no bedroom plants** in the current physical model.

The projector wall should remain understated when inactive and become a strong illuminated rectangular projection surface only while the projector is active.

## Living room

Canonical anchors:
- brown sofa in its approved real orientation and shortened footprint;
- rectangular coffee table close to/in front of the couch;
- simplified living-room rug under the seating group;
- white rounded chair in front of the left living-room window, clear of the balcony door;
- TV and TV stand/media console at the approved wall position;
- subwoofer tucked into the inside corner at the TV-stand / balcony-wall end;
- living-room lamp;
- snake plant + ZZ plant staggered and tucked near the wall in the approved plant area;
- living-room end-table cluster **between the balcony wall and couch**, with Alexa on top and Sonos Era 100 on the lower shelf.

Treat Alexa + Sonos as one visual furniture/device cluster. The **TV**, not the projector, is the living-room screen state.

## Plants

Plant geometry should be species-recognizable by silhouette rather than botanically detailed.

Current plant truth:
- snake plant — inside in the living-room plant grouping;
- ZZ plant — inside in the living-room plant grouping;
- monstera — on the balcony during warm season and brought indoors during fall/winter.

The exact warm-season balcony coordinate for the monstera remains intentionally unplaced until supported by trustworthy placement evidence.

Seasonal plant placement may eventually become real apartment state rather than static decoration.

## Kitchen

The floor plan strictly owns kitchen geometry.

Recognizable anchors:
- island with sink;
- perimeter white/gray cabinetry;
- refrigerator;
- stove/oven;
- **over-range microwave above the stove/oven**;
- two stools;
- pendant lights;
- simplified kitchen runner rug.

Countertop clutter is not required.

## Bathroom / closet / laundry / mechanical / entry

These support spatial recognition but stay lower-detail than bedroom/living/kitchen.

Preserve canonical geometry and simplified recognizable anchors:
- bathroom vanity/sink flush to its wall and extending toward the toilet;
- toilet against its approved wall position;
- shower;
- closet footprint;
- closet dresser flush against the closet/entry dividing wall;
- laundry area;
- water-heater/mechanical enclosure;
- entry/front door;
- elongated **entry cubby** flush against the opposite side of the closet/entry dividing wall.

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

The top-down geometry portion of this gate is now satisfied by the approved v1 coordinate model and truth map.

The next gate is the **deterministic 2.5D projection**. Until that projection is accepted:
- do not add dashboard sidebars or surrounding Home layout;
- do not add fake telemetry or confidence values;
- do not add causality traces or decorative machine UI;
- do not add Hue/live-state lighting, ambient events, or final materials;
- do not alter the approved top-down x/y geometry to make a camera angle look better.

Reject a 2.5D candidate if camera, wall cutaway, z-height, or occlusion makes the apartment spatially misleading even when the underlying x/y coordinates are correct.

Only after the projected geometry is visually accepted should live lights, device state, ambient events, causality, or surrounding Home UI be layered in.

## Still-open visual questions

These are design explorations, not top-down geometry uncertainties:
- exact wall height/cutaway depth;
- object z-heights and degree of extrusion/simplification;
- exact camera pitch/yaw needed to preserve visibility without distortion;
- object/wall occlusion strategy;
- inactive/active Alexa-node treatment;
- projector-wall active visual strength;
- final wall/floor/material palette.
