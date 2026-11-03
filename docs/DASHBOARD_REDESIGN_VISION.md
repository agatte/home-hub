# Dashboard Redesign Vision

Status: **active design authority for Dashboard UI/UX under `docs/PROJECT_SPEC.md`**  
Owner: Dashboard UI workstream  
Umbrella: #157  
Established: 2026-08-19

## Purpose and authority

This document preserves the product and visual direction for the HomeHub Dashboard redesign so the redesign does not drift back toward incremental card polishing or depend on chat history.

`docs/PROJECT_SPEC.md` remains authoritative for cross-system product policy, lifecycle semantics, automation authority, and roadmap. This document owns Dashboard-specific information architecture, visual language, interaction principles, and design explorations for #157. Current code is evidence of shipped behavior, not visual precedent.

The August audit remains historical evidence in `DASHBOARD_UX_AUDIT_2026_08_18.md`. This document describes the **target design direction** established after that audit and after visual review of the first redesign experiment.

## Design thesis

HomeHub should feel like a **living instrument for the apartment**, not a collection of smart-home cards.

The primary interface should reveal relationships between:

1. the physical apartment;
2. sensed evidence;
3. interpreted House State and Activity;
4. HomeHub decisions;
5. resulting device/environment behavior;
6. what changed over time.

The UI should answer, without requiring a hunt through integrations:

- What is happening at home right now?
- What does HomeHub believe the context is?
- Why does it believe that?
- What is HomeHub doing because of it?
- What just changed?
- Is anything unusual or degraded?
- What control is relevant now?

The design should feel technical, clean, advanced, spatial, and alive without becoming cyberpunk, game-themed, or visually noisy.

## Core design principles

### Context before integrations

Home is not an inventory of APIs. Weather, plants, network, guest Wi-Fi, bar inventory, Sonos, lighting, and other integrations should not receive permanent equal-weight panels merely because data exists.

Normal healthy or irrelevant information should recede. Contextually important information should gain prominence.

Examples:

- Network becomes prominent when degraded, not because Pi-hole has statistics.
- Plants appear when care is due, not to permanently report that the plant app is unavailable.
- Now Playing appears when media exists.
- Guest controls appear when guests/social context makes them useful.
- Weather expands when it materially affects daylight, atmosphere, or plans.

### The apartment is a primary information surface

The physical apartment should become a central visual and interaction model rather than a small utility card.

The canvas may represent rooms, furniture anchors, light positions, presence/context, projector/PC/Sonos/device state, environmental readings, and other meaningful physical context. It should make HomeHub feel attached to a real place.

The canvas is not merely decoration. It is a navigable representation of current state and a source of contextual controls.

### Motion communicates causality, state, confidence, or change

Motion is semantic.

Use animation to explain what the system is doing or what changed: a signal travels, a selector changes, a confidence indicator settles, a gate opens, a state transition crosses a rail, a light responds, or a recent event pulses into history.

Avoid continuous motion whose only purpose is to make the screen look busy. The user should be able to answer, "Why did that move?"

Reduced-motion support must preserve the information communicated by animation through static state changes, labels, or other non-motion cues.

### Progressive disclosure replaces permanent control walls

Home should emphasize current context and relevant controls. Full control sets should appear through intentional interaction: selecting a room, device, activity, context block, or compact global control.

All important controls remain reachable, but not all controls remain visible all the time.

### House State and Activity remain distinct

Dashboard presentation must preserve the accepted model:

- House State: Away, Home, Winding Down, Sleeping.
- Activity: General plus stronger semantic activities such as Working, Gaming, Watching, Cooking, Relax, Social, etc.
- Internal detector `idle` is not a peer user-facing Activity.
- Inferred secondary context uses softer language such as `Likely: Getting Ready`.
- Automatic detected Activity must not be presented as though it were a manual override.

### Desktop and mobile are different compositions

Mobile is not desktop cards stacked vertically.

Both experiences use the same state and component language, but the hierarchy, navigation, canvas framing, control placement, and amount of simultaneous information may differ substantially.

Desktop/kiosk can show apartment, context, and time/history concurrently. Mobile should prioritize immediate context, the apartment, and the next relevant action, with deeper information progressively disclosed.

## Mobile-first completion and release sequence — accepted 2026-11-02

**Accepted priority:** Complete a genuinely designed iPhone/mobile UI first, finish the rest of the Quiet Atlas × Daylight app-wide redesign second, verify the combined product on real phone and desktop/kiosk third, and only then propose a separately approved Latitude release. **After** that release, proceed to smarter HomeHub notifications (existing #51/#291 security dependencies), followed by iPhone Shortcuts and possible native widgets. This is **development sequencing**, not permission to merge, deploy, restart production, change credentials or send device commands.

Mobile is a distinct composition, not desktop components scaled or stacked into a phone. The user's current most frequent phone task is changing lighting, but future use can include house status, history, music, and other activities. The first phone screen should therefore feature source-qualified House State/Activity and immediately discoverable lighting groups and presets without making unrelated functionality disappear.

**Mobile acceptance requirements:**

- No forced horizontal **page** scroll at 320, 360 or 390 CSS pixels; accommodate iPhone portrait, landscape, notches/home indicator, dynamic text, safe areas, and the installed web-app experience. Vertical scrolling may be natural and intentional.
- Readable text and appropriately sized, finger-friendly controls; primary tap targets approximately 44 CSS pixels or greater. No cramped desktop-style settings tables, micro-buttons or horizontally scrolling control strips.
- Phone-native information architecture across Home, Control, scenes/presets, Settings, Music, Insights/history and More. Advanced diagnostics remain easy to find but never dominate the primary Home screen.
- Context and lights/scenes must be truthfully labeled by freshness, evidence and authority. A REST receipt is not proof of bridge freshness, physical room presence, bulb reachability or permission to actuate.
- Robust loading, empty, disconnected, stale, failed, DND/Sleeping/Travel/protected-control, reduced-motion, focus, VoiceOver and keyboard behavior; no silent failures.
- **Usable functional lighting** is an acceptance gate for replacing the everyday production interface. Read-only group/scene previews are insufficient on their own. No direct UI-side group fan-out or optimistic write: resolve the separately proposed `docs/QUIET_ATLAS_CONTROL_ACTUATION_PLAN.md` writer, ownership, transition, idempotency and freshness contracts with Lighting & Atmosphere / House State before enabling any new one-shot action. Bedroom L2/L5 must remain individually governed.
- Real mounted Svelte application tests, visual review on the user's actual iPhone and kiosk/desktop, accessibility/performance, and an explicit release candidate review are required. Green Linux unit tests and static responsive fixtures cannot substitute for physical acceptance.

**Integration boundaries:** Maintain the separately evidence-controlled Apartment Canvas (#192) and the ongoing desk lighting comfort work (#244/#370). Do not silently absorb Apple Music #431, music policy #254, notifications or Shortcut external-action authentication into a pure redesign slice. Existing functional pages remain available until deliberately migrated and verified.

**Release gate:** Before a separate deployment authorization, compare the exact reviewed GitHub source to the Latitude's actual deployed SHA and inventory every intervening change, including unrelated master commits, configuration/migrations and startup effects. Prepare rollback and acceptance checks; use only `scripts/deploy.sh` for an authorized rollout. “Deploy the redesign when finished” is a roadmap choice, not standing authority to deploy an unknown future revision.

**Current implementation status:** The opt-in Quiet Atlas routes are design studies. Mobile-first Home/lighting design slices must be treated as reversible proposals until real-device review. A genuinely mobile Home layout may place direct room and preset navigation ahead of the full desktop Apartment stage while preserving access to #192; this particular composition is still subject to visual and functional acceptance.

## Visual references and what they mean

These references describe **principles**, not artwork to reproduce.

### Visible machine / process mechanism

Reference: the animated machine-like illustration at the top of ESPN's Bracketology feature discussed during #157 design exploration.

What matters:

- many distinct components participate in a process;
- components feel mechanically related rather than independently animated;
- travelling motion communicates that something is moving through the system;
- selectors, rails, chambers, indicators, gates, and status lights make an outcome feel produced by inputs;
- playful motion can coexist with serious information;
- the mechanism is understandable enough that motion helps explain the process.

HomeHub adaptation:

Imagine small rotating selectors, travelling pulses, sliding rails, confidence rings, gates opening/closing, little status lights, and traces that illuminate when fresh evidence arrives. The motion explains the system.

This language is especially promising for **Analytics/Insights**, where HomeHub can expose how evidence becomes context and automation.

### Living miniature world / animated island

Reference: the user-supplied photograph of a floating pixel-art/island desktop wallpaper that had long-standing appeal because the scene moved and felt alive. The visual reference is useful for the sense of a compact, self-contained world; HomeHub should not reproduce the source artwork or game style.

What matters:

- one coherent world carries the visual identity;
- many small independent details can change without requiring card chrome;
- the composition remains interesting while at rest;
- spatial relationships make the scene memorable;
- subtle local animation can make the whole environment feel alive.

HomeHub adaptation:

The apartment canvas becomes HomeHub's living miniature world: a premium cinematic digital twin whose lights, occupied areas, devices, environment, and context subtly respond to real state.

**Accepted visual-target update ? 2026-09-01:** the living/cinematic apartment is now the Home direction, not merely an experiment. Architectural/whitebox/schematic renderers remain inspection and validation tools, not the Home quality target. #217 owns the first premium static Hero frame before broad Story/live-state polish.

### Relationship between the two references

The references solve different design problems:

- **Home** presents the physical world: the living apartment.
- **Analytics/Insights** opens the casing and presents the mechanism underneath: evidence, confidence, fusion, decisions, and outcomes.

The two surfaces should share visual DNA so Analytics can explain why the Home world changed.

## Home composition

The target Home composition is built from six systems. Their exact geometry is still design work; their roles are accepted.

### A. Live Apartment Canvas

The canvas is the dominant physical-state surface on desktop and an important early surface on mobile.

Potential content includes:

- room geometry and labels;
- meaningful furniture anchors such as desk, couch, bed, projector wall/screen;
- Hue/light positions and actual on/brightness/color state;
- physical presence/room context where trustworthy;
- PC/desk, projector, Sonos, and other relevant device state;
- environmental context when useful;
- subtle state/event traces.

Interaction can progressively reveal room controls, light controls, device controls, context explanation, or deeper apartment detail.

#### Visual treatment exploration

Three treatments remain legitimate design explorations:

1. **Architectural schematic** — top-down, precise, highly legible.
2. **Living isometric/2.5D apartment diorama** — miniature spatial world with restrained depth and animation.
3. **Technical systems/cutaway map** — more abstract node-and-system presentation.

The accepted Home direction is the **living cinematic apartment/digital twin**. Architectural schematic and whitebox views remain development/diagnostic surfaces rather than competing product aesthetics. The technical systems treatment remains more appropriate for Analytics than for Home.

#### At-rest behavior

At rest, the apartment should remain visually coherent and calm. Live state can be conveyed through illumination, restrained presence fields, device indicators, daylight/environment tone, and other low-motion signals.

#### Change behavior

When meaningful events occur, brief motion may show causality:

- desk/PC evidence pulses;
- an activity transition travels into context;
- automation responds;
- affected lights or devices visibly settle into the new state;
- the event enters the Recent timeline.

Do not continuously animate every sensor or connection.

### B. Current Context

Current Context is the concise statement of what HomeHub believes and how it is operating.

Normal presentation should emphasize the conclusion rather than engineering diagnostics. For example:

```text
HOME
Gaming
Automatic · Desk + PC activity
```

Optional explanation/drill-down can expose richer provenance:

```text
WHY GAMING?
PC game process           strong
Desk physical context     strong
Recent desktop input      fresh
Sonos                      neutral
Confidence                 94%
```

Confidence should not dominate the primary view unless uncertainty is itself important.

State transitions may briefly gain additional presentation, for example a rail showing `General -> Gaming` with the evidence responsible for the change. It then collapses back to normal context.

### C. Recent Timeline

Home needs a compact, readable answer to "what just happened?"

The target is a visual event rail rather than a log viewer. Events may include:

- House State or Activity transitions;
- meaningful lighting/scene adjustments;
- presence/context changes;
- media changes;
- overrides and returns to automatic control;
- relevant degraded/recovery events.

A compact example:

```text
11:54  Gaming detected
       PC activity + desk context
11:54  Lighting adjusted
       Evening Gaming · 62%
11:48  Desk occupied
11:37  General
```

The timeline should eventually align naturally with #14 Replay / Time Machine. A strong long-term interaction is that scrubbing history rewinds the apartment canvas and contextual state rather than presenting history as detached text.

### D. Environment

Environment is compact instrumentation, not a permanent weather card.

Normal presentation may be a telemetry rail such as temperature, condition, wind, sunset/daylight, and indoor comfort when trustworthy. It should expand in visual prominence when environmental conditions materially affect HomeHub behavior or deserve attention.

Weather/daylight may later influence the visual rendering system itself, but presentation must remain truthful and not imply automation that does not exist.

### E. Contextual Controls

Controls emerge from the object or context the user interacts with.

Examples:

- select a room -> room controls;
- select a light -> light controls;
- select Sonos -> media controls;
- select a projector/device -> device details where supported;
- select current Activity -> explanation and override;
- select environment -> richer environment detail.

Automation override controls should distinguish:

- Auto;
- manual Activity override;
- House lifecycle actions such as Winding Down/Sleep where appropriate;
- quick/safety actions such as All Lights Off.

`All Off` is not conceptually a peer Activity and should not be visually grouped as though it were equivalent to Gaming or Cooking.

### F. Global Navigation

Navigation is being reconsidered from first principles. Existing routes do not automatically deserve primary navigation.

Potential everyday destinations include Home, Music, Game Day when relevant, History/Insights, or other intentional surfaces. Settings and diagnostics may move to secondary navigation. Apartment may not require a separate primary destination if the apartment canvas becomes Home's central interaction model.

Do not lock the final destination set until Home composition and the role of Analytics/Insights are clearer.

## Analytics / Insights: the HomeHub machine

Analytics should not default to a page of generic chart cards.

A signature top-level surface can expose the HomeHub inference/automation mechanism:

```text
CAMERA -----\
DESKTOP -----+--> CONTEXT / FUSION --> ACTIVITY --> AUTOMATION
AUDIO -------+          |                  |             |
PRESENCE ----/      confidence          GAMING       LIGHTING
```

The rendered experience may use original mechanical/instrumentation motifs such as:

- moving signal pulses;
- rotating or stepped selectors;
- sliding rails;
- confidence rings/chambers;
- gates opening or closing as evidence gains/loses authority;
- status lights;
- traces that briefly illuminate with fresh evidence;
- outcome components that visibly react when a decision changes.

The mechanism must remain truthful to actual source authority and confidence. It must not imply deterministic causality where the backend only provides correlation or weak evidence.

Below or around the mechanism, deeper analysis can include House State/Activity timelines, evidence contributions, automation decisions, lighting changes, overrides, detector corrections, weather/time relationships, and autonomy performance.

The design goal is that Analytics feels like **opening HomeHub's brain**, while Home remains the living physical world.

## Background and atmosphere direction

The current mode-specific animated backgrounds are transitional legacy implementation and are not target visual identity.

Long-term background/atmosphere work should use a unified technical rendering language that may include:

- architectural grids or spatial depth;
- restrained procedural gradients;
- real daylight/weather influence where truthful;
- environmental traces;
- subtle vector/particle behavior tied to state or change;
- smooth state interpolation rather than swapping unrelated wallpapers.

Different House States and Activities may alter density, contrast, luminance, tempo, or instrumentation behavior while remaining recognizably one design system.

Sleeping and idle/ambient behavior should become especially calm and low-luminance. #15 owns the bounded ambient idle surface after the main awake visual language is established.

## Desktop and mobile composition

### Desktop / kiosk

Desktop can present multiple related surfaces simultaneously. A likely composition direction is:

- compact global/context header;
- large apartment canvas;
- Current Context and automation behavior adjacent to the canvas;
- Recent rail visible without navigation;
- compact environment telemetry;
- contextual media/suggestions only when relevant.

The exact grid is not yet locked.

### Mobile

Mobile should prioritize:

1. current House State/Activity;
2. a simplified/pannable apartment canvas;
3. current automation behavior and one relevant action;
4. recent changes;
5. compact environment/media context.

Mobile controls may use sheets/drawers and mobile-specific bottom navigation. Desktop/kiosk navigation may use a different treatment.

Do not implement mobile by simply stacking every desktop region vertically.

## Component language

The redesign should reduce reliance on generic rounded cards. Different visual structures should carry different meanings.

Candidate language:

- **canvas** — physical apartment/world;
- **panels** — major functional regions;
- **rails** — history, transitions, or signal flow;
- **nodes** — devices/evidence/sources;
- **instrument readouts** — measurements and confidence;
- **drawers/sheets** — controls and explanation;
- **chips/pills** — small statuses only;
- **overlays** — temporary contextual detail.

A rounded rectangle should not be the automatic wrapper for every piece of data.

## Explicitly rejected precedents

The redesign should not regress toward:

- a permanent grid of integration cards;
- a dashboard whose visual identity depends on animated wallpaper;
- the same desktop layout merely stacked vertically on mobile;
- every integration receiving permanent Home real estate;
- Mode as the single organizing concept;
- raw internal enum/source strings as consumer copy;
- nine permanent equal-weight mode/action buttons;
- All Off presented as a peer Activity;
- engineering rollout terminology as consumer UI;
- motion whose only function is decoration;
- generic charts as the entire Analytics experience.

Current route/component structure is not a constraint on the target information architecture.

## #167 experiment and lessons

PR #167 / issue #166 implemented a deliberately bounded contextual-header experiment after the August audit. It established useful evidence but is **not the target Home redesign**.

Useful lessons to carry forward:

- House State + Activity should replace raw legacy Mode as user-facing truth;
- automatic vs manual control needs explicit visual distinction;
- internal source values such as `PROCESS` need consumer-friendly provenance;
- empty Sonos chrome should not dominate Home;
- permanent mode cards should collapse into contextual/expandable control;
- moving the header alone is insufficient because the remaining card grid still reads as the same product.

The experiment should be preserved as historical/prototyping evidence rather than merged as the design foundation unless a later accepted design explicitly reuses individual pieces.

## Accessibility and performance

The redesign's visual ambition does not override usability.

- keyboard and focus behavior must remain intentional;
- reduced-motion users must receive equivalent state/causality information;
- color cannot be the sole carrier of state or confidence;
- high-density canvas interactions need accessible alternate controls/labels;
- mobile touch targets must remain usable;
- animation must pause or reduce when hidden/inactive where appropriate;
- performance decisions, especially 3D/2.5D rendering, must be measured on the actual Latitude/kiosk rather than guessed;
- #41 remains the evidence gate for compositor/performance-specific changes.

## Accepted decisions vs open explorations

### Accepted now

- Complete rehaul: the existing dashboard is functional source material, not visual foundation.
- Home is a living apartment/context experience, not an integration-card grid.
- The apartment becomes a primary visual/interaction surface.
- Current Context, Recent Timeline, Environment, Contextual Controls, and intentional Navigation are core systems.
- Motion communicates system behavior or change.
- Home represents the physical world; Analytics/Insights can represent the mechanism underneath.
- Permanent card walls and mode-button walls are rejected.
- Desktop and mobile receive deliberately different compositions.
- Current animated backgrounds will eventually be replaced by a unified cleaner technical/atmospheric system.
- #167 is an experiment, not the target redesign.

### Still open / explore before implementation lock

- top-down architectural canvas vs isometric/2.5D living diorama (current preference: explore diorama first);
- exact desktop grid and relative canvas size;
- amount of information rendered inside the apartment vs adjacent to it;
- exact device/presence/light visual grammar;
- final primary navigation destinations;
- whether Analytics is branded/named `Analytics`, `Insights`, or another term;
- exact machine/instrument visual mechanics;
- final typography, color system, depth, and background rendering technique;
- which parts of #167, if any, are worth reusing.

## Design and implementation sequence

Do not jump directly from this vision document into a full-page implementation.

The next design work should deepen the **Apartment Canvas** first because its spatial language strongly influences Home composition, contextual controls, navigation, mobile treatment, and later background rendering.

Before implementation lock for a major surface:

1. work out composition and interaction in design discussion/prototypes;
2. mark newly accepted decisions in this document or an appropriate child spec/handoff;
3. create a bounded GitHub issue with observable acceptance criteria;
4. implement in an isolated branch/worktree;
5. validate with code checks and real desktop/narrow visual evidence;
6. keep experiments disposable when they do not improve the product.

Experimentation and rejected prototypes are expected. The goal of #157 is to make HomeHub look and behave like a different, more coherent product rather than cautiously reskinning the current dashboard.
