# HomeHub Execution Map

> **Status:** Living execution/orchestration guidance; not product authority.
> **Last reconciled:** 2026-10-08 (issue/gate routing update; deployment and physical state not reverified). See [PROJECT_ADMIN_HUB.md](PROJECT_ADMIN_HUB.md) and [#339](https://github.com/agatte/home-hub/issues/339) for navigation and the proposed Projects dashboard.
> **Evidence baselines:** [`audits/ARCHITECTURE_ORCHESTRATION_AUDIT_2026_09_22.md`](audits/ARCHITECTURE_ORCHESTRATION_AUDIT_2026_09_22.md) and [`audits/LIGHTING_AUTHORITY_AUDIT_2026_10_04.md`](audits/LIGHTING_AUTHORITY_AUDIT_2026_10_04.md). Security remediation is tracked under #284 and canonical children #285-#296.
> **Product authority:** [`PROJECT_SPEC.md`](PROJECT_SPEC.md).
>
> **2026-10-08 issue/gate checkpoint:** #246 and #283 implementation issues are closed; #334 separately owns Blue Yeti post-deployment physical unplug/replug acceptance. #276's Sonos audit/concurrency PR #335 is merged; #336 Away pause implementation is closed and #337 assisted ShareLink authority remains open, with #276/#274 preserving broader acceptance. #240 is evidence-gated; #284's staged security program remains active. Project Admin navigation/board design is tracked in #339. These are issue/merge findings only: do **not** infer that the corresponding Windows/Latitude code has been deployed or physically verified. Consult live issues and the operating runtime before selecting work.
>
> **Historical 2026-10-07 release checkpoint (not a current queue or deploy claim):** #285/#286, #322–#324 and Project Admin recovery PR #329 had been merged through `0f4b2c2`; no supported production rollout was established at that checkpoint. The former #246 → #283 → #276 implementation order is superseded. Durable per-change proof remains in Git/PRs and the owning issues; current runtime evidence must still be checked.

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
- **IMPLEMENTATION_COMPLETE** — accepted implementation work is complete; only an explicit operational/evidence gate remains.
- **PARKED** — valid retained work, but not worth detailed planning now.

## Current architectural checkpoint

The 2026-09-22 Astra audit found that HomeHub's main execution risk is **uneven enforcement and stale contracts**, not the absence of another whole-home framework.

Important current facts:

- Existing ownership/lifecycle chokepoints should be extended, not bypassed with new parallel frameworks.
- Scene Curator foundations, shared music intelligence, central Sonos ownership, and cross-Activity desk comfort already exist in code; future work must reconcile/extend them rather than rebuild them.
- Existing mode-match/fusion accuracy is not independent user-outcome evidence and must not be used as #131 autonomy-graduation proof.
- Sonos ownership serializes participating HomeHub writers, but read-then-write device operations are not atomic against an external Sonos controller.
- #240's bounded navigation-replay architecture is implemented through bounded capture/export and fixed-evidence semantic diff. The first real evidence-backed fixture remains capture-gated; no synthetic fixture satisfies that gate.
- The 2026-10-04 security audit is preserved under #284. Canonical implementation packets are #285-#296; later duplicate batches #297-#321 were closed as duplicates during reconciliation. #322 is the unique sunrise/lighting correctness child.
- The 2026-10-04 lighting audit found a strong central transition/applicator architecture but several delayed/transient semantic-authority gaps. #323 owns shared final-write revalidation for Try-It/ScreenSync/Rust/native-scene waits; #324 separately owns per-light Away/off convergence after partial Hue failures.
- Authentication/security identity must remain separate from lighting ownership: valid credentials never override DND, Away/Sleeping, manual, scene/effect, ScreenSync, transit, fixture-comfort or registered external-owner authority.

## Current gate-aware routing (2026-10-08)

This is **not a universal ranked backlog**. The owning issue and [Project Admin Hub](PROJECT_ADMIN_HUB.md) provide the live route; inspect dependencies, existing active work and authorization gates before selecting the next task.

| Work / owner | Current gate | Narrow next step / model |
|---|---|---|
| [#337](https://github.com/agatte/home-hub/issues/337) assisted Sonos ShareLink; [#276](https://github.com/agatte/home-hub/issues/276) sprint | Open implementation contract | Continue bounded queue/transport authority and concurrency validation, **Sol High**; later merge and device acceptance remain separate gates. |
| [#334](https://github.com/agatte/home-hub/issues/334) Blue Yeti | Deployment/version proof **then physical evidence** | During a separately approved release and operator-present test, verify unplug/replug without made-up microphone health. No new #283 implementation. |
| [#240](https://github.com/agatte/home-hub/issues/240) navigation replay | **EVIDENCE_GATED** | Obtain one eligible natural capture before historical-reproduction claims; Luna-class evidence bookkeeping, Sol only for a real divergence. |
| [#284](https://github.com/agatte/home-hub/issues/284), [#287–#296](https://github.com/agatte/home-hub/issues/284) security | Dependency-ordered, task-specific approval/rollout gates | Recheck canonical child and current exposure; Sol Medium/High according to risk, without prematurely enforcing trust migration. |
| [#339](https://github.com/agatte/home-hub/issues/339) Project Admin | Board inventory/configuration and reversible documentation | Reuse an existing GitHub Project if suitable; keep docs as links/authority map rather than a separate manually updated queue. |

[#246](https://github.com/agatte/home-hub/issues/246), [#283](https://github.com/agatte/home-hub/issues/283), and [#336](https://github.com/agatte/home-hub/issues/336) are closed implementation tasks. #286, #285, and #322–#324 are also merged/closed. Their release/physical state must be checked from live evidence and separate gates, **not** inferred from issue closure or the historical checkpoint below.

These correctness/security tasks are not blocked by #240's real-world capture. Do not expand replay merely to unblock unrelated bounded work.

## Implementation packet references (historical and open)

Detailed implementation contracts and current status belong to the owning GitHub issues and dated audits. **Some packets below are completed historical references, not permission to reimplement them.** Re-check current code, issue state and operational gates before execution.

### Security program — #284 / canonical children #285-#296

- #285 immediate containment and #286 safe source exports are merged/closed. #285 remains inside the merged-but-not-deployed production boundary; #286 is Project Admin export tooling and does not itself require a Latitude rollout.
- #287-#293 define the staged identity/browser/native/gateway/WebSocket migration. Preserve additive support before enforcement; retire private-IP/loopback/shared-key trust only after legitimate clients are ready.
- #294-#296 own camera lifecycle, constrained media/SSRF surfaces, and evidence-backed Hue identity verification.
- Duplicate planning issues #297-#321 are closed as duplicates; do not reopen them unless new evidence invalidates the canonical split.
- **Workers:** Sol Medium/High per remaining #287-#296 owning issue. Use Astra only for a genuinely unresolved architecture/review need, not routine implementation.

### #322 — sunrise final-write ownership

- **Status:** MERGED/CLOSED at `c251c18560fcbe2eb9843f2bbd1e73437d88b68b`; production rollout/physical acceptance remain within the current merged-but-not-deployed release boundary.
- Every delayed ramp step must re-check DND, Away/external-off, manual, scene/effect, transit, ScreenSync/protected-light and lifecycle authority at the final write boundary.
- No catch-up/replay after cancellation or restart; do not create new wake/occupancy authority.
- **Historical implementation model:** Sol High.
- **Reopen only if:** new evidence shows the existing owned lighting paths cannot express the accepted Morning behavior without changing product semantics.

### #323 — delayed/transient final-write authority

- **Status:** MERGED/CLOSED at `6b221ac9304340afc1e2eda445afac8db3ab2dc1`; production rollout/physical acceptance remain within the current merged-but-not-deployed release boundary.
- Extend the existing Hue transition/ownership architecture with one semantic generation/lease revalidation seam; do not create a universal device lease manager.
- First migrations: scene Try-It reversion, ScreenSync write-after-wait, Rust flinch restore, native-scene acknowledgement.
- A stale writer that loses authority must not mutate Hue or refresh its ownership/freshness.
- **Historical implementation model:** Sol High.
- **Reopen only if:** new evidence shows contradictory ownership precedence or that the seam weakens Game Day/manual/Away/ScreenSync/external-owner behavior.

### #324 — Away/off convergence

- **Status:** MERGED/CLOSED via PR #330 at `0f4b2c2326d082d434678de937088a3641b4d7f8`; production rollout/real-Hue acceptance remain within the current merged-but-not-deployed release boundary.
- Preserve Away suppression while tracking per-light OFF acknowledgements and bounded unresolved-light retry/reconnect behavior.
- A stale Away retry must not survive a newer Home lifecycle generation.
- Reuse structured per-light success/failure discipline rather than another boolean-only whole-home API.
- **Historical implementation model:** Sol High.
- **Reopen only if:** new evidence shows safe convergence would require weakening Away suppression or replaying historical lighting state.

### #246 — durable per-light manual ownership (closed implementation)

- **Status 2026-10-08:** Closed. The following is retained as historical implementation guidance, not an actionable task. Verify any release/physical claim separately.
- Preserve still-valid manual light holds across ordinary backend reconstruction.
- Restore metadata only; do not replay Hue state or persist the whole engine.
- Authority surfaces: `EngineState`, `LightOverrideManager`, `AutomationEngine._persist_override_state()/load_override_state()`, `LightApplicator.protected_light_ids()`, bootstrap ordering.
- Validate fresh/expired/malformed restore, clear-after-restore, delayed-save ordering, and protected-light behavior.
- **Worker:** Sol Medium.
- **Escalate if:** safe persistence requires changing mode-level ownership semantics, writing physical targets on restore, or cannot serialize mark/clear/expiry durably.

### #283 — microphone recovery and truthful capability health (closed implementation)

- **Status 2026-10-08:** Closed after PR #333. Post-deployment physical unplug/replug acceptance belongs to [#334](https://github.com/agatte/home-hub/issues/334); the following is historical guidance.
- Recover closed/unavailable PyAudio streams with bounded retry/backoff.
- Distinguish worker alive, microphone usable, classifier permitted, and last successful observation.
- Reset partial sensing evidence after capture loss; never fabricate observations or widen Social authority.
- **Worker:** Sol Medium.
- **Escalate if:** recovery requires process-wide supervisor redesign, forced cross-thread termination, or new sensing authority.

### #276 — Sonos writer audit (merged), remaining sprint gates

- **Status 2026-10-08:** Writer audit and two concurrency fixes merged via PR #335. #336 is closed; [#337](https://github.com/agatte/home-hub/issues/337) remains the open bounded ShareLink task. #276/#274 retain wider physical and ownership acceptance. The bullets below describe the earlier audit packet, not remaining unimplemented audit work.
- Inventory every Sonos mutation path and map owner, dimensions, guard, final mutation boundary, cancellation, restart behavior, and tests.
- Add only missing fake-device concurrency cases; do not invent another ownership service.
- Distinguish HomeHub-lock guarantees from external-controller races and worker-thread settlement.
- **Worker:** Sol High.
- **Escalate if:** an unowned production writer, contradictory lease semantics, destructive cleanup, or absolute guarantee over an unavoidable external race is discovered.

### Remaining contract reconciliation + #245 closeout

- The October 4 security duplicate batches are reconciled: #285-#296 are canonical and #297-#321 are closed as duplicates.
- Older stale umbrellas still worth a cheap reconciliation pass include #142, #244, #247, #253, #254, #276, plus #149 and the #157/#192/#217/#270 Dashboard/Canvas chain.
- For #245, current code/test evidence suggests the original background-game arbitration premise may already be superseded; verify before implementing.
- **Workers:** Luna-class for prescribed docs/issue reconciliation and #245 deterministic code/test closeout.

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

**Status:** The bounded navigation-v1 implementation is complete through deterministic trace/forensics, privacy-preserving capture/export, and fixed-evidence semantic diff. Slice 6 operational isolation is accepted: the real-host E2E on 2026-10-02 passed (`1 passed, 44 deselected in 31.57s`, pytest exit `0`, clean post-test Sandbox inventory). Slice 9's diff machinery is implemented, but its real-fixture half remains **EVIDENCE_GATED** because no eligible bounded natural capture has been obtained and no retained July input stream/checkpoint is complete enough to claim historical reproduction.

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
5. **COMPLETE** - deterministic scheduler + checkpoint model. Replay now has an offline virtual UTC/monotonic clock, stable deadline/enqueue ordering, same-time append semantics, cancellation and exception behavior, recorded-input delivery without synthesized cadence, and typed quiescent checkpoint continuation. Non-empty wall-clock adjustments are rejected until their capture semantics are explicitly defined. Sol High implementation plus independent review found no blockers; 32 replay scheduler/bundle tests, Ruff, and diff-check are green.
6. **COMPLETE / OPERATIONAL ISOLATION ACCEPTED (Sol High)** - offline composition root wires the bounded production decision participants to data-only recording light/event sinks, restores exact checkpoint state, preserves mode/per-light expiry and Working restoration ordering, rejects unmapped acknowledgement timing, and locks the reviewed project/external import closure. The operational runner now uses a fresh transient Windows Sandbox plus a broker-created zero-capability AppContainer child; the stage is read-only, networking/device-facing channels are disabled, no production/Home/credential/database mapping is exposed, and no writable host export path exists while the replay child runs. Guest completion is positively proven before a fresh writable export mapping is added. The controlled real-host E2E passed on 2026-10-02 with pytest exit `0` and clean post-test Sandbox inventory; focused validation is `44 passed, 1 skipped` and the broader replay suite is `90 passed, 1 skipped`.
7. **COMPLETE** - deterministic trace/forensics + synthetic contract replay (`8b5b9d4`), with explicit certainty classes, causal/evidence links, reason codes, and gate states.
8. **COMPLETE** - bounded privacy-preserving capture/exporter (`e0da717`), opt-in only, quiescent-cut guarded, field-allowlisted, and bounded to 15 minutes / 16 MiB by default.
9. **DIFF COMPLETE / REAL FIXTURE EVIDENCE_GATED** - `backend/replay/diff.py` performs deterministic FIXED-EVIDENCE COUNTERFACTUAL alignment and rejects changed FACT streams; one eligible real capture is still required for evidence-backed golden assertions.
10. **COMPLETE** - accepted handoff/status and usage documentation. Residual work is an evidence acquisition gate, not another implementation slice.

Important findings to preserve during implementation:
- Transit internal `active` state is not proof that a write succeeded; the manager may suppress or receive zero successful acknowledgements.
- Direct navigation writes through `LightOverrideManager` have different guards from normal `LightApplicator` writes. Replay must expose that distinction rather than normalize it away.
- Transit currently lacks DeskExit's explicit unknown-physical-authority gate. Treat this as a separate correctness finding, not a replay-extraction change.
- Missing required initial state/order must yield an incomplete/uncertain replay, never healthy/Home/empty defaults.
- Counterfactual output is explicitly **FIXED-EVIDENCE COUNTERFACTUAL**; it cannot infer changed human behavior or environmental feedback.

The accepted design contains the full bundle schema, virtual wall/monotonic time rules, initial-state matrix, trace schema, no-actuation proof, counterfactual limits, capture contract, implementation slices, landing order, and acceptance criteria.

## Model economy

- **Luna-class:** deterministic inventory/extraction, prescribed documentation reconciliation, tests, mechanical edits, and tightly specified bounded implementation.
- **Sol-class:** substantive default for implementation, debugging, research, review, and multi-file engineering judgment.
- **Higher Sol effort:** concurrency, lifecycle, ownership, cross-service, architecture, performance, security/data-integrity, or deep verification.
- **Astra-class:** exceptional only when its specific strengths or genuinely independent/high-end review materially justify the extra cost. Do not add a separate approval gate when the current task authorization already covers its use.
- **Terra/legacy-class:** fallback only.

## Update discipline

Whenever a packet is completed, materially re-scoped, or invalidated:

1. update the owning GitHub issue with the concrete current checkpoint;
2. update this map only if sequencing/readiness/model recommendation materially changed;
3. update `PROJECT_SPEC.md` only for accepted cross-system product-policy/status changes;
4. preserve dated audits as historical evidence rather than rewriting them;
5. stamp the next reconciliation date and SHA here.

Do not let this file become a second issue tracker. GitHub owns bounded work; this file owns **cross-issue execution orientation and handoff economy**.
