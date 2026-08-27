# Apartment Canvas Physical World Model

Status: **Durable design authority for future Physical World work**
Issue: [#192](https://github.com/agatte/home-hub/issues/192)
Scope: Physical truth, evidence, placement constraints, derived geometry, and presentation boundaries
Implementation: Documentation only; no runtime schema is defined here

## Purpose and product boundary

Apartment Canvas is the faithful physical substrate for a polished, living
HomeHub experience. It represents the actual apartment well enough that live
state, lighting and atmosphere, explanation, recent change, Director Board
framing, and later replay all happen in a recognizable place.

It is a cinematic consumer visualization, not architecture, CAD, surveying,
renovation, space planning, or a measurement product. Physical fidelity is a
means to make HomeHub believable; it does not displace Apple-level polish,
intentional framing, calm intelligence, or the Story Layer.

The product stack is:

1. **Physical World** — the evidence-backed apartment, furnishings, and
   meaningful devices.
2. **Director Board** — intentional framing and transitions driven by the
   home's story.
3. **Story Layer** — live state, atmosphere, causality, recent change, and
   later replay.

Debug, measurement, provenance, and reconstruction tools belong in explicit
review surfaces, not the normal user experience.

## Core rules

1. Physical size and physical placement are separate facts. Knowing an
   object's dimensions does not determine its room coordinates.
2. The entire apartment uses one coherent real physical unit and scale across
   architecture, furniture, devices, clearances, and heights.
3. A room, object, or axis must never receive an independent scale or stretch
   to improve composition.
4. Manufacturer or measured dimensions outrank a provisional blocking
   rectangle for the object's physical size.
5. Real-room photographs are first-class evidence for as-built/as-furnished
   placement and relationships. They do not silently rewrite protected
   architectural shell or opening geometry.
6. Unknown placement remains an explicit constraint or unresolved fact; it
   does not become a precise coordinate through arithmetic or visual taste.
7. Coordinates, GU footprints, collision bounds, renderer anchors, and mesh
   extents are derived outputs. Repetition or prior approval for a rendering
   checkpoint does not promote them to independent physical authority.
8. Presentation may make the whole apartment feel larger, closer, or more
   legible only through camera/framing or one uniform presentation transform
   applied after physical geometry is solved.

## Authority model

Authority is evaluated per fact, not per file. A single artifact can contain
protected architecture, review-required furniture rectangles, derived GU
coordinates, and provisional visual defaults at the same time.

### 1. Physical source truth

Physical source truth has three distinct domains:

| Domain | What it owns | Typical evidence |
| --- | --- | --- |
| Architecture | Shell, wall topology, room boundaries, registered openings, and fixed architectural features | Accepted architectural artifacts, leasing plan, direct measurement, explicit confirmation |
| Product/object definition | Object identity, physical dimensions, module structure, support logic, and intrinsic orientation | Direct measurement, manufacturer specification, inspected product evidence |
| As-built/as-furnished placement | Where and how an object actually sits in the apartment, including wall/corner/object relationships and clearances | Real-room photographs, direct measurement, explicit user confirmation |

The domains do not substitute for one another. A product page cannot place a
desk in a room. A photograph cannot by itself establish an exact hidden
clearance. A floor-plan annotation cannot override a known product footprint.

### 2. Evidence and provenance

Every physical claim must retain its source type, source reference, scope,
confidence, and qualification. Supported source types are:

- `direct_measurement`
- `manufacturer_specification`
- `leasing_floor_plan`
- `real_room_photograph`
- `explicit_user_confirmation`
- `mathematical_derivation`
- `provisional_inference`

These labels are descriptive, not a universal numeric ranking. Authority
depends on the fact being decided. Direct measurement generally has the
strongest claim to a measured quantity; manufacturer specifications strongly
own product dimensions; photographs strongly own visible furnished
relationships; accepted architectural artifacts protect the shell.

Confidence describes how well the cited evidence supports the stated fact:

- **confirmed** — direct or explicitly accepted evidence establishes the fact;
- **high** — multiple compatible sources or one strong source establishes the
  relationship with little plausible ambiguity;
- **medium** — the relationship is supported, but exact extent, side, or
  tolerance remains uncertain;
- **low/provisional** — useful working inference that must remain reviewable.

Confidence must not add precision. A high-confidence statement such as
"near-adjacent with a narrow gap" is still not a measured clearance.

### 3. Placement constraints and anchors

Placement is expressed first as evidence-backed constraints. Supported anchor
families include:

| Anchor family | Meaning |
| --- | --- |
| Wall-relative | An edge, face, or orientation relates to a named wall or accepted wall segment |
| Corner-relative | An object relates to the intersection of two named architectural boundaries |
| Object-relative | Position or orientation is stated relative to another physical object |
| Seam/junction-relative | A module, device, or feature relates to a product seam or junction |
| Room-relative/free-standing | The object occupies a room region without a supported wall or object attachment |
| Photo-supported | One or more photographs establish a visible relationship, with the rationale stated |

A constraint records what is known and no more: named participants, relation,
direction/orientation when supported, source, confidence, and any tolerance or
unresolved degree of freedom. Qualitative constraints such as `near`,
`narrow_gap`, `aligned`, or `room_facing` remain qualitative until measured.

Conflicting constraints must be surfaced for review. A solver or renderer may
not resolve conflict by distorting an object, moving protected architecture,
or silently dropping the inconvenient source.

### 4. Derived geometry

Derived geometry includes:

- physical-model coordinates produced by satisfying accepted constraints;
- GU/world coordinates produced by the global physical-to-world transform;
- object footprints, oriented bounds, collision shapes, pivots, and anchors;
- mesh dimensions, simplified silhouettes, occlusion helpers, and interaction
  hit areas;
- renderer-specific offsets and compatibility adapters.

Each derived value must be reproducible from named physical facts, accepted
constraints, and an identified transform/version. It must remain replaceable
when higher-authority evidence changes. A derived value cannot be cited as the
sole evidence for the physical fact from which it was derived.

### 5. Presentation

Presentation is downstream of solved physical geometry and includes:

- Camera v2 and later Director Board framing;
- cutaway and visibility treatment;
- one uniform presentation scale/transform;
- materials, lighting interpretation, atmosphere, and idealization;
- live-state emphasis, causality, recent change, and Story Layer behavior.

Presentation can crop, frame, uniformly enlarge, shade, simplify, or reveal
the apartment. It cannot change one room, object, axis, clearance, or height
relative to another. The accepted Camera v2, cutaway selectors, reflection,
and fit behavior remain separate presentation authority and are not reopened
by this model.

## Units and the single apartment scale

The eventual physical model must store real dimensions in one coherent unit
(for example, inches or millimeters) across the entire apartment. The unit is
an implementation choice; consistency is the contract.

The existing GU system is a valid compatibility and renderer boundary during
migration, but GU is not the source of a product's physical dimensions. A
future global calibration must determine one uniform physical-to-GU/world
transform for the entire apartment:

```text
physical evidence + placement constraints
    -> solved apartment-wide physical geometry
    -> one uniform physical-to-world/GU transform
    -> renderer geometry
    -> one separate uniform presentation transform + camera/framing
```

Global calibration must use multiple independent architectural dimensions or
anchors where available, state its fitting method and tolerance, and report
residuals. The leasing plan's nominal bedroom dimension may contribute, but no
single room dimension may be treated as an exact apartment-wide calibration.
Independent x/y calibration, per-room calibration, and per-object correction
scales are prohibited.

Vertical geometry participates in the same physical scale. Provisional wall,
slab, sill, object, and cutaway heights remain provisional until physical
evidence supports them; a convenient GU height is not real-world evidence.

### Provisional apartment-wide calibration — Bedroom pilot

The first bounded implementation records one provisional apartment-wide
working transform in [`physical_world_v1.json`](physical_world_v1.json):

```text
GU = physical_inches × 3.39
```

It is supported by three confident architectural comparisons: Bedroom
horizontal (`122 in` over `413.35 GU`, `3.388115 GU/in`), Bedroom vertical
(`137 in` over `464.60 GU`, `3.391241 GU/in`), and Living horizontal
(`160 in` over `541.09 GU`, `3.381813 GU/in`). Their observed spread is
`0.278%`; the working tolerance is `±0.05 GU/in`. The leasing plan is nominal
rather than survey-grade, so the tolerance represents plan rounding,
wall-face interpretation, and trace uncertainty—not a range for independently
fitting rooms or objects.

The earlier approximately `3.53 GU/in` bedroom-only estimate is superseded. It
mistook the recessed/window-host line for the bedroom clear-inside boundary.
One scale applies apartment-wide on X, Y, and Z. Calibration converts known
physical size; it does not allocate uncertain placement or clearance.
Presentation scaling, Camera v2 framing, reflection, and fit remain downstream
and separate from this physical transform.

## Nominal dimensions and tolerances

Leasing-floor-plan labels are useful physical evidence, not survey/CAD
precision. Preserve the printed value, its source, the feature it describes,
and an explicit tolerance or uncertainty class before using it in calibration
or constraint solving.

Do not manufacture precision by combining rounded values. A sum that is close
to a nominal room dimension is a consistency check, not an exact placement
chain. Residual space remains unassigned until measurement, photographs, or
explicit confirmation establish where it belongs.

Validation should distinguish:

- **exact constraints** supported by exact accepted evidence;
- **toleranced constraints** supported by measurement or nominal-plan ranges;
- **qualitative constraints** supported by visible relationships;
- **unresolved degrees of freedom** that no current source decides.

## Coexistence with current GeometryScene

Migration is incremental and additive in design, with no runtime schema change
authorized by this document.

1. Keep accepted architectural shell, topology, aperture, Camera v2, and
   visibility artifacts protected.
2. Inventory existing object rectangles and renderer anchors by status. Values
   marked `review_required`, approximate, provisional, or inherited are
   compatibility inputs, not frozen furniture truth.
3. Create room evidence packets that separate object dimensions from placement
   constraints and identify unresolved facts.
4. Establish the multi-anchor apartment-wide physical calibration and its
   tolerance before producing replacement absolute GU coordinates.
5. Derive candidate physical placement, GU/world geometry, collision bounds,
   and renderer anchors from that model. Record provenance and residuals.
6. Compare candidates against protected architecture, product dimensions,
   real-room photographs, and all accepted placement constraints.
7. Only after explicit review should a later implementation update runtime
   geometry/contracts/fingerprints/tests. That is a separate authorized pass.

`GeometrySceneV1` remains the current renderer-neutral architectural whitebox
and compatibility boundary. Its architectural outputs stay authoritative in
their accepted scope. Existing furniture and device footprints do not become
immutable merely because render code or a prior top-down checkpoint consumed
them.

## Rules against stale absolute footprints

- Never preserve one stale GU axis while correcting the other from a physical
  dimension.
- Never scale modules independently to fit inherited endpoints.
- Never convert a product ratio into absolute coordinates without the global
  physical calibration and accepted placement constraints.
- Never use collision bounds or procedural helper dimensions as evidence for
  the object's real footprint.
- Never move a wall, opening, bed, or adjacent object merely to make a product
  fit an inherited rectangle.
- Never close a nominal room equation by inventing zero clearance or assigning
  all residual space to an unsupported side.
- When evidence invalidates a blocker, mark and replace the blocker in a later
  authorized migration; do not retain its silhouette as a second authority.

## Validation strategy

Future physical-model changes must be validated at four levels:

1. **Evidence audit** — every fact has a source, scope, confidence, and no more
   precision than the source supports.
2. **Constraint audit** — exact, toleranced, qualitative, conflicting, and
   unresolved constraints are reported separately.
3. **Scale and geometry audit** — one apartment-wide transform is used;
   product dimensions and ratios, wall/opening protection, collisions,
   clearances, heights, and transform residuals are checked.
4. **Visual audit** — repeatable overhead and room-side views are compared with
   real-room photographs. Camera, darkness, cutaway, or props cannot conceal a
   geometry failure.

Normal-product acceptance then verifies that the faithfully solved apartment
still achieves the Apartment Canvas design language: substantial whole-home
framing, Apple-level polish, legible live state, and intentional Director Board
and Story Layer behavior.

## Explicit non-goals

This model does not:

- provide survey, CAD, BIM, renovation, egress, or purchasing-grade accuracy;
- define a runtime schema, solver, migration, or renderer implementation;
- change current GeometryScene JSON, contracts, fingerprints, or tests;
- reopen protected architecture, openings, Camera v2, cutaway, reflection, fit
  margin, or production behavior;
- invent missing dimensions, coordinates, clearances, or hidden construction;
- require photorealism, exhaustive clutter, or visible debug instrumentation;
- subordinate cinematic presentation, HomeHub state, or story behavior to a
  measurement interface.

## First worked packet

The first application of this authority model is
[`../reference/bedroom/PHYSICAL_EVIDENCE_PACKET.md`](../reference/bedroom/PHYSICAL_EVIDENCE_PACKET.md).
It records the bedroom facts that may support a later coordinate derivation and
keeps the current unresolved clearances explicit.

The workflow is apartment-wide: every major room or service area eventually
gets its own physical evidence packet, and the apartment-wide inventory
[`PHYSICAL_EVIDENCE_INVENTORY.md`](PHYSICAL_EVIDENCE_INVENTORY.md) comes before
full room-by-room reconciliation. Bedroom is the first detailed worked example,
not a special scaling exception or the complete physical model. Each later
packet should index both furniture/device identity references and wide,
placement-oriented room photography; major furniture without authoritative
dimensions remains explicitly unresolved rather than inheriting a blocker
footprint.
