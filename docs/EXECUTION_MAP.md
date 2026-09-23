# HomeHub Execution Map

> **Status:** Living execution/orchestration guidance; not product authority.
> **Last reconciled:** 2026-09-23 against `master` at `f83d771`.
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
- #240's bounded navigation-replay architecture is accepted. Implementation is ready in small slices; the first real evidence-backed fixture remains capture-gated.

## Recommended near-term order

| Order | Work | Classification | Next action | Cheapest credible model |
|---|---|---|---|---|
| 1 | Sunrise ownership safeguard under #139 | EXECUTION_READY | Route the scheduled ramp through owned lighting application and cancel/recheck each delayed step | **Sol High** |
| 2 | #246 per-light manual ownership persistence | EXECUTION_READY | Persist narrowly scoped manual-owner metadata; restore before automatic reconciliation | **Sol Medium** |
| 3 | #283 Blue Yeti stream recovery / capability health | EXECUTION_READY | Add bounded resource recovery and separate worker-liveness from usable sensing health | **Sol Medium** |
| 4 | #276 Sonos writer/concurrency audit | EXECUTION_READY | Complete mutation manifest + fake-device adversarial matrix; state external-race limits honestly | **Sol High** |
| 5 | Stale docs/GitHub execution-contract reconciliation | EXECUTION_READY | Refresh #142/#149/#244/#247/#253/#254/#276 and Dashboard/Canvas status pointers without changing product decisions | **Luna Low** |
| 6 | #245 closeout verification | EXECUTION_READY | Verify current regression coverage/deployment evidence before deciding whether anything remains | **Luna Low** |
| 7 | #240 deterministic navigation replay | EXECUTION_READY / EVIDENCE_GATED | Slices 1-4 complete; implement Slice 5 deterministic scheduler + checkpoint model | **Sol High** |

The first four correctness items do not require #240. #240 should not be used as a reason to postpone small, already-understood safety/reliability fixes.

## Execution-ready packet index

Detailed implementation packets, validation, invariants, likely files, review risk, and escalation triggers are preserved in **Section 6** of the dated Astra audit.

### #246 — durable per-light manual ownership

- Preserve still-valid manual light holds across ordinary backend reconstruction.
- Restore metadata only; do not replay Hue state or persist the whole engine.
- Authority surfaces: `EngineState`, `LightOverrideManager`, `AutomationEngine._persist_override_state()/load_override_state()`, `LightApplicator.protected_light_ids()`, bootstrap ordering.
- Validate fresh/expired/malformed restore, clear-after-restore, delayed-save ordering, and protected-light behavior.
- **Worker:** Sol Medium.
- **Escalate if:** safe persistence requires changing mode-level ownership semantics, writing physical targets on restore, or cannot serialize mark/clear/expiry durably.

### #283 — microphone recovery and truthful capability health

- Recover closed/unavailable PyAudio streams with bounded retry/backoff.
- Distinguish worker alive, microphone usable, classifier permitted, and last successful observation.
- Reset partial sensing evidence after capture loss; never fabricate observations or widen Social authority.
- **Worker:** Sol Medium.
- **Escalate if:** recovery requires process-wide supervisor redesign, forced cross-thread termination, or new sensing authority.

### Sunrise ownership safeguard — bounded child of #139

- `MorningRoutineService.sunrise_ramp()` must no longer perform stale direct-Hue writes throughout a long loop.
- Each delayed step must re-evaluate lifecycle/DND/manual/protected/transit/scene/ScreenSync ownership and stop when authority is lost.
- This is a correctness fix, not the full Morning product implementation.
- **Worker:** Sol High.
- **Escalate if:** the accepted Morning contract intentionally requires overriding manual/Sleeping ownership or no existing owned apply path can express the request.

### #276 — remaining Sonos writer/concurrency audit

- Inventory every Sonos mutation path and map owner, dimensions, guard, final mutation boundary, cancellation, restart behavior, and tests.
- Add only missing fake-device concurrency cases; do not invent another ownership service.
- Distinguish HomeHub-lock guarantees from external-controller races and worker-thread settlement.
- **Worker:** Sol High.
- **Escalate if:** an unowned production writer, contradictory lease semantics, destructive cleanup, or absolute guarantee over an unavoidable external race is discovered.

### Contract reconciliation + #245 closeout

- Refresh stale execution/status prose without rewriting historical evidence.
- High-priority stale umbrellas: #142, #244, #247, #253, #254, #276, plus #149 and the #157/#192/#217/#270 Dashboard/Canvas chain.
- For #245, current code/test evidence suggests the original background-game arbitration premise may already be superseded; verify before implementing.
- **Workers:** Luna Low for prescribed docs/issue reconciliation and #245 deterministic code/test closeout.

## Architecture-ready work

| Work | Design question | Next model |
|---|---|---|
| #131 per-action autonomy | First action-specific outcome/provenance lifecycle; independent outcome evidence; reversal/demotion semantics | **Sol Medium** |
| #138 Winding Down | Durable lifecycle session/overlay preserving underlying Activity and ownership across restart/cancel/end | **Sol High** |
| #139 Morning | Separate accepted wake, confirmed Morning, optional brief, and overnight path assistance | **Sol Medium** |
| #19 outage recovery | Conservative context reacquisition from bounded outage facts; never blind output replay | **Sol Medium** |
| #74 healed-outage history | Durable bounded outage observations/classification uncertainty | **Sol Medium** |
| #262 command/intent layer | Small provider-neutral command envelope + dispatcher that cannot carry caller-asserted permission | **Sol Medium** |
| #132 suggestions | Pending suggestion lifecycle, expiry/context invalidation, explicit accept/reject/modify/defer | **Sol Medium** |
| #51 operational alerts | Fault identity, acknowledgement, recovery/clear, severity and per-surface delivery | **Sol Medium** |
| #140/#141 events/guests | Temporary event authority + guest capability queues beneath lifecycle/manual/privacy controls | **Sol Medium** |
| #134 weather ambience | Relax/context eligibility composed with shared audio ownership | **Sol Medium** |
| #116 fusion metrics | Lane-specific evaluation using independent labels/objectives rather than mode agreement | **Sol Medium** |
| #36 Scene Browser | Expose existing eligibility/provenance without creating a second curator | **Sol Medium** |
| #187 cloud semantics | Bounded weather taxonomy using current provider context | **Sol Medium** |

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

## #240 - accepted deterministic navigation-replay architecture

**Accepted design:** [`audits/REPLAY_ARCHITECTURE_2026_09_22.md`](audits/REPLAY_ARCHITECTURE_2026_09_22.md).

**Status:** Architecture resolved for the bounded profile; implementation ready. The first real fixture is **EVIDENCE_GATED** because no retained historical input stream/checkpoint is complete enough to claim deterministic reproduction of the July incident.

Supported v1 profile:

`normalized source-qualified physical observations -> PresenceFusion -> retained Working / House-State authority -> TransitLightingService -> LightOverrideManager -> recording adapter result -> Working/day restoration through LightApplicator`

Boundaries:
- target incident family: July 14-31 desktop-inactive repeated-transit behavior;
- first honest fixture: a new bounded natural daytime navigation capture, not a fabricated/reconstructed July sequence;
- one backend boot; explicit/retained Working intent; desktop sensing unavailable;
- no active scene/effect/ScreenSync owner;
- ScreenSync, DeskExit evening/corridor, Sonos, Game Day, raw inference, dashboard replay, and whole-home simulation are out of v1;
- replay starts after ingress timestamp normalization at `PresenceFusion.on_observation(PresenceReading)`;
- replay stops at final per-light request, recording adapter result, and resulting simulated owner/cache/navigation state.

Implementation order:
1. **COMPLETE (Luna Low)** - exact navigation-v1 consumption/state/clock/side-effect manifest: [`replay/NAVIGATION_V1.md`](replay/NAVIGATION_V1.md).
2. **COMPLETE** - versioned navigation-v1 bundle schema + strict validator/fixture-only reader (`4003d23`), including exact checkpoint-state enforcement, member/digest/order/session validation, explicit incomplete/unsupported errors, and raw-media rejection.
3. **COMPLETE** - replay-safe DecisionClock injection for PresenceFusion, TransitLightingService, and LightOverrideManager plus passive camera-threshold import cleanup. The replay-excluded legacy ScreenSync wall read in LightApplicator remains unchanged per the exact Slice 1 manifest. Independent Sol Medium review found no blockers; advancing-clock and exact-deadline tests cover separate read opportunities.
4. **COMPLETE** - narrow Activity/Working composition extraction with production-equivalence tests (`f83d771`). Passive shared policy/composition helpers now preserve strict expiry boundaries, property short-circuits, learner-await/read ordering, lux hysteresis continuity, and normal ScreenSync/application ownership. Independent Sol Medium review found no blockers.
5. **NEXT (Sol High)** - deterministic scheduler + checkpoint model.
6. **Sol High** - offline composition root + structural forbidden-I/O proof.
7. **Luna Medium** - trace/forensics + synthetic contract replay.
8. **Sol Medium** - bounded privacy-preserving capture/exporter.
9. **Sol Medium** - first real fixture + fixed-evidence semantic diff.
10. **Luna Low** - accepted handoff/status docs.

Important findings to preserve during implementation:
- Transit internal `active` state is not proof that a write succeeded; the manager may suppress or receive zero successful acknowledgements.
- Direct navigation writes through `LightOverrideManager` have different guards from normal `LightApplicator` writes. Replay must expose that distinction rather than normalize it away.
- Transit currently lacks DeskExit's explicit unknown-physical-authority gate. Treat this as a separate correctness finding, not a replay-extraction change.
- Missing required initial state/order must yield an incomplete/uncertain replay, never healthy/Home/empty defaults.
- Counterfactual output is explicitly **FIXED-EVIDENCE COUNTERFACTUAL**; it cannot infer changed human behavior or environmental feedback.

The accepted design contains the full bundle schema, virtual wall/monotonic time rules, initial-state matrix, trace schema, no-actuation proof, counterfactual limits, capture contract, implementation slices, landing order, and acceptance criteria.

## Model economy

- **Luna Low:** deterministic inventory/extraction, prescribed documentation reconciliation, mechanical edits, tests, and tightly specified small changes.
- **Luna Medium:** clear bounded implementation and ordinary multi-file work when the contract and validation are precise.
- **Sol Medium:** debugging, research, review, or implementation requiring meaningful engineering judgment.
- **Sol High/xhigh:** concurrency, lifecycle, ownership, cross-service, runtime, security, or meaningful data-risk work.
- **Astra:** exceptional only, with explicit pre-approval. #240's accepted bounded design no longer requires Astra for implementation; if Luna becomes insufficient, escalate directly to Sol.

## Update discipline

Whenever a packet is completed, materially re-scoped, or invalidated:

1. update the owning GitHub issue with the concrete current checkpoint;
2. update this map only if sequencing/readiness/model recommendation materially changed;
3. update `PROJECT_SPEC.md` only for accepted cross-system product-policy/status changes;
4. preserve dated audits as historical evidence rather than rewriting them;
5. stamp the next reconciliation date and SHA here.

Do not let this file become a second issue tracker. GitHub owns bounded work; this file owns **cross-issue execution orientation and handoff economy**.
