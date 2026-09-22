# HomeHub Execution Map

> **Status:** Living execution/orchestration guidance; not product authority.
> **Last reconciled:** 2026-09-22 against `master` at `17810d670c9c1d7b05fc1a7fc4aedfbfb8ce0c3e`.
> **Evidence baseline:** [`audits/ARCHITECTURE_ORCHESTRATION_AUDIT_2026_09_22.md`](audits/ARCHITECTURE_ORCHESTRATION_AUDIT_2026_09_22.md).
> **Product authority:** [`PROJECT_SPEC.md`](PROJECT_SPEC.md).

This file exists so a future ChatGPT/Codex session can answer **what should we do next, what is actually ready, and what model/depth is appropriate** without rediscovering the whole architecture.

## How to use this map

1. Read `AGENTS.md` and the relevant portion of `PROJECT_SPEC.md` first.
2. Use this file for sequencing, readiness, dependencies, and handoff depth.
3. Before executing any packet, cheaply re-check its named code files, owning GitHub issue, and current Git status. This map is guidance, not proof that nothing changed after the reconciliation SHA.
4. Current code/runtime evidence outranks stale status prose. Production/deployment/physical claims still require live evidence.
5. If current evidence contradicts a packet's architecture assumption, stop that packet and escalate rather than forcing the old plan.

Readiness vocabulary:

- **EXECUTION_READY** — architecture/product decision is resolved enough for a bounded worker.
- **ARCHITECTURE_READY** — direction is resolved but a bounded design pass remains.
- **DECISION_NEEDED** — a real product/authority choice is still missing.
- **EVIDENCE_GATED** — current real-world/runtime evidence is required first.
- **PARKED** — valid retained work, but not worth detailed planning now.

## Current architectural checkpoint

The 2026-09-22 Astra audit found that HomeHub's main execution risk is **uneven enforcement and stale contracts**, not the absence of another whole-home framework.

Important current facts:

- Existing ownership/lifecycle chokepoints should be extended, not bypassed with new parallel frameworks.
- Scene Curator foundations, shared music intelligence, central Sonos ownership, and cross-Activity desk comfort already exist in code; future work must reconcile/extend them rather than rebuild them.
- Existing mode-match/fusion accuracy is not independent user-outcome evidence and must not be used as #131 autonomy-graduation proof.
- Sonos ownership serializes participating HomeHub writers, but read-then-write device operations are not atomic against an external Sonos controller.
- #240 remains the highest-leverage architecture investment after the bounded correctness work below.

## Recommended near-term order

| Order | Work | Classification | Next action | Cheapest credible model |
|---|---|---|---|---|
| 1 | Sunrise ownership safeguard under #139 | EXECUTION_READY | Route the scheduled ramp through owned lighting application and cancel/recheck each delayed step | **Terra High** |
| 2 | #246 per-light manual ownership persistence | EXECUTION_READY | Persist narrowly scoped manual-owner metadata; restore before automatic reconciliation | **Terra Medium** |
| 3 | #283 Blue Yeti stream recovery / capability health | EXECUTION_READY | Add bounded resource recovery and separate worker-liveness from usable sensing health | **Terra Medium** |
| 4 | #276 Sonos writer/concurrency audit | EXECUTION_READY | Complete mutation manifest + fake-device adversarial matrix; state external-race limits honestly | **Terra High** |
| 5 | Stale docs/GitHub execution-contract reconciliation | EXECUTION_READY | Refresh #142/#149/#244/#247/#253/#254/#276 and Dashboard/Canvas status pointers without changing product decisions | **Luna Low** |
| 6 | #245 closeout verification | EXECUTION_READY | Verify current regression coverage/deployment evidence before deciding whether anything remains | **Terra Low** |
| 7 | #240 deterministic replay architecture | ARCHITECTURE_READY | Run the bounded Astra Medium design pass below | **Astra Medium** |

The first four correctness items do not require #240. #240 should not be used as a reason to postpone small, already-understood safety/reliability fixes.

## Execution-ready packet index

Detailed implementation packets, validation, invariants, likely files, review risk, and escalation triggers are preserved in **Section 6** of the dated Astra audit.

### #246 — durable per-light manual ownership

- Preserve still-valid manual light holds across ordinary backend reconstruction.
- Restore metadata only; do not replay Hue state or persist the whole engine.
- Authority surfaces: `EngineState`, `LightOverrideManager`, `AutomationEngine._persist_override_state()/load_override_state()`, `LightApplicator.protected_light_ids()`, bootstrap ordering.
- Validate fresh/expired/malformed restore, clear-after-restore, delayed-save ordering, and protected-light behavior.
- **Worker:** Terra Medium.
- **Escalate if:** safe persistence requires changing mode-level ownership semantics, writing physical targets on restore, or cannot serialize mark/clear/expiry durably.

### #283 — microphone recovery and truthful capability health

- Recover closed/unavailable PyAudio streams with bounded retry/backoff.
- Distinguish worker alive, microphone usable, classifier permitted, and last successful observation.
- Reset partial sensing evidence after capture loss; never fabricate observations or widen Social authority.
- **Worker:** Terra Medium.
- **Escalate if:** recovery requires process-wide supervisor redesign, forced cross-thread termination, or new sensing authority.

### Sunrise ownership safeguard — bounded child of #139

- `MorningRoutineService.sunrise_ramp()` must no longer perform stale direct-Hue writes throughout a long loop.
- Each delayed step must re-evaluate lifecycle/DND/manual/protected/transit/scene/ScreenSync ownership and stop when authority is lost.
- This is a correctness fix, not the full Morning product implementation.
- **Worker:** Terra High.
- **Escalate if:** the accepted Morning contract intentionally requires overriding manual/Sleeping ownership or no existing owned apply path can express the request.

### #276 — remaining Sonos writer/concurrency audit

- Inventory every Sonos mutation path and map owner, dimensions, guard, final mutation boundary, cancellation, restart behavior, and tests.
- Add only missing fake-device concurrency cases; do not invent another ownership service.
- Distinguish HomeHub-lock guarantees from external-controller races and worker-thread settlement.
- **Worker:** Terra High.
- **Escalate if:** an unowned production writer, contradictory lease semantics, destructive cleanup, or absolute guarantee over an unavoidable external race is discovered.

### Contract reconciliation + #245 closeout

- Refresh stale execution/status prose without rewriting historical evidence.
- High-priority stale umbrellas: #142, #244, #247, #253, #254, #276, plus #149 and the #157/#192/#217/#270 Dashboard/Canvas chain.
- For #245, current code/test evidence suggests the original background-game arbitration premise may already be superseded; verify before implementing.
- **Workers:** Luna Low for prescribed docs/issue reconciliation; Terra Low for #245 code/test closeout.

## Architecture-ready work

| Work | Design question | Next model |
|---|---|---|
| #240 replay/forensics | Minimum deterministic replay boundary, clocks, initial state, suppression trace, structural no-I/O | **Astra Medium** |
| #131 per-action autonomy | First action-specific outcome/provenance lifecycle; independent outcome evidence; reversal/demotion semantics | **Sol Medium** |
| #138 Winding Down | Durable lifecycle session/overlay preserving underlying Activity and ownership across restart/cancel/end | **Sol High** |
| #139 Morning | Separate accepted wake, confirmed Morning, optional brief, and overnight path assistance | **Sol Medium** |
| #19 outage recovery | Conservative context reacquisition from bounded outage facts; never blind output replay | **Sol Medium** |
| #74 healed-outage history | Durable bounded outage observations/classification uncertainty | **Terra Medium** |
| #262 command/intent layer | Small provider-neutral command envelope + dispatcher that cannot carry caller-asserted permission | **Terra Medium** |
| #132 suggestions | Pending suggestion lifecycle, expiry/context invalidation, explicit accept/reject/modify/defer | **Terra Medium** |
| #51 operational alerts | Fault identity, acknowledgement, recovery/clear, severity and per-surface delivery | **Terra Medium** |
| #140/#141 events/guests | Temporary event authority + guest capability queues beneath lifecycle/manual/privacy controls | **Sol Medium** |
| #134 weather ambience | Relax/context eligibility composed with shared audio ownership | **Sol Medium** |
| #116 fusion metrics | Lane-specific evaluation using independent labels/objectives rather than mode agreement | **Sol Medium** |
| #36 Scene Browser | Expose existing eligibility/provenance without creating a second curator | **Terra Medium** |
| #187 cloud semantics | Bounded weather taxonomy using current provider context | **Terra Medium** |

## Decision-needed boundaries

### #131 graduation policy

Before thresholds are designed, choose the first action/context and define what counts as a meaningful correction/reversal. Do not derive graduation from broad confidence or the absence of complaints.

### #273/#274/#276 audio residual guarantee

Safe destructive stale-queue cleanup remains blocked by the lack of a device/provider primitive stronger than read-then-write preflight. A future architecture decision must state precisely what guarantee HomeHub claims against **external** Sonos-controller races. Preserve the current no-cleanup fallback meanwhile.

## Major evidence gates

| Work | Missing evidence before implementation/expansion |
|---|---|
| #129/#130 living room | Post-L6 quiet/listening/settled couch sessions: composition, repetition, corrections, autonomous-vs-manual presentation |
| #136/#243/#244 desk comfort | Remaining evening/night perceived balance and ScreenSync relevance |
| #137 → #13 kitchen | Missed dark visits, false activations, premature fades, correction rate on current inference |
| #202 Bed comfort | Fixture-specific evening/night/late-night ceilings including ScreenSync/non-bedroom lights |
| #236 Apple Health | Representative nights of latency, freshness, brief wakes, interaction vetoes and source differences |
| #117 predictor | Recent labeled serving rows, feature distributions, model version and per-class confusion |
| #253/#7 Game Day | Current real-game timing/no-spoiler behavior plus volume/intelligibility/end-to-end acceptance |
| #149 Travel | Hardened Return Home round-trip, restoration ordering and fresh post-return sensing |
| #40/#134 ambience | Acceptable long-form source quality and supported Sonos continuity |
| #160/#241/#55 security | Current dependency/CSP exposure; historical advisory counts are not current evidence |

Other evidence-gated or parked work is fully classified in **Section 5** of the dated audit. Consult that table before creating new backlog or purchasing hardware.

## Shared primitives worth reusing

- **Action outcome identity (#131):** action/context/policy/decision/session plus explicit response, reversal, correction and uncertainty. Music provenance is a precedent, not a universal schema.
- **Versioned incident evidence envelope (#240):** normalized source-qualified evidence/time/reasons; do not turn a living-room snapshot into global mutable state.
- **Durable outage observation (#74 → #19):** startup/host identity, bounded failure/recovery observations, affected components and classification uncertainty.
- **Suggestion lifecycle (#132):** pending/accepted/rejected/deferred/expired with context identity and dedupe.
- **Operational alert lifecycle (#51):** share delivery plumbing where useful but keep severity/ack/recovery distinct from suggestions.
- **Writer authority manifest (#276):** owner/dimensions/guard/final mutation/cancellation/restart/test.
- **Narrow clock/tick seam (#240):** wall time for persisted timestamps; monotonic time for deadlines/dwell.
- **Command envelope (#262):** domain/action/validated params/authenticated provenance/request ID/query-vs-action; never caller-supplied trust.

## Abstractions intentionally deferred

- #16 generic action-sequence executor until at least two accepted experiences demonstrably duplicate sequencing semantics.
- A universal device lease manager: Hue and Sonos have different observation/mutation guarantees.
- A generic AI task runtime until a second real task proves common needs.
- A universal physical-source model: #192 geometry truth must not become live occupancy authority.
- Whole-engine persistence: #246 only needs narrow manual-owner durability.

## #240 — next Astra Medium architecture brief

**Model/effort:** GPT-6 Astra, Medium. **Mode:** read-only architecture pass; no implementation or live writes.

**Goal:** Produce an implementation-ready design for the smallest deterministic HomeHub incident replay, using current code and the 2026-09-22 authority audit. Do not design a whole-home simulator.

Minimum v1 chain:

`normalized source-qualified observations → PresenceFusion → relevant Activity/House-State arbitration → DeskExit/navigation decision → owned lighting request`

Include ScreenSync only if the chosen incident requires it. Do not include Sonos, Game Day, raw camera/ML inference, dashboard replay, or general event sourcing in v1.

The design must answer:

- which real incident has enough retained normalized evidence and pre-window state;
- what initial lifecycle/ownership/dwell state must be exported instead of reconstructed;
- which current decision functions can run unchanged and which narrow seams are required;
- where replay stops and how requested actions differ from observed device responses;
- how virtual UTC wall time + monotonic elapsed time preserve freshness, dwell, deadlines and deterministic ordering;
- how suppressed proposals/eligibility/stronger-owner decisions appear in the trace;
- how an offline composition root structurally prevents Hue/Sonos/Kasa/projector/network/notification/shutdown actuation;
- what fixed-evidence counterfactuals are valid and where environmental feedback becomes unknowable.

Expected implementation decomposition after design:

1. Luna Low — exact selected-incident input/state/clock/side-effect manifest.
2. Terra Low — versioned bundle validator and fixture reader.
3. Terra Medium — narrow clock/tick seams.
4. Terra High — offline composition root + forbidden-I/O structural tests.
5. Terra Medium — first real incident replay + golden reason trace.
6. Terra Medium — baseline/candidate semantic diff.
7. Terra Medium — bounded export adapter only if the proven schema needs it.

Full schema concerns, no-actuation criteria, acceptance tests and explicit non-goals are preserved in **Section 9** of the dated Astra audit.

## Model economy

- **Luna Low:** deterministic inventory/extraction, prescribed documentation reconciliation, mechanical edits, tightly specified small tasks.
- **Terra Low:** small implementation once architecture and acceptance are explicit.
- **Terra Medium:** default bounded implementation/debugging/multi-file work.
- **Terra High:** tricky bounded concurrency, ownership, delayed operations and interactions.
- **Sol Medium/High:** unresolved cross-system architecture/authority judgment.
- **Astra:** only exceptional cross-system ambiguity where a high-quality architecture pass can manufacture cheaper downstream work. At this checkpoint, #240 is the only clearly justified Astra task.

## Update discipline

Whenever a packet is completed, materially re-scoped, or invalidated:

1. update the owning GitHub issue with the concrete current checkpoint;
2. update this map only if sequencing/readiness/model recommendation materially changed;
3. update `PROJECT_SPEC.md` only for accepted cross-system product-policy/status changes;
4. preserve dated audits as historical evidence rather than rewriting them;
5. stamp the next reconciliation date and SHA here.

Do not let this file become a second issue tracker. GitHub owns bounded work; this file owns **cross-issue execution orientation and handoff economy**.
