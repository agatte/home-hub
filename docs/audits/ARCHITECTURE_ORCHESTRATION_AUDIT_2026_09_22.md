# HomeHub Architecture & Execution-Orchestration Audit — 2026-09-22

> **Status:** Dated architecture/orchestration evidence. Not product authority and not a live-health claim.
> **Audit model:** GPT-6 Astra, low reasoning effort.
> **Repository baseline:** `17810d670c9c1d7b05fc1a7fc4aedfbfb8ce0c3e` (`master`) on 2026-09-22.
> **Scope:** Read-only reconciliation of HomeHub authority docs, relevant implementation surfaces, and all 77 open GitHub issues.
> **Current execution guidance:** See [`../EXECUTION_MAP.md`](../EXECUTION_MAP.md).
> **Product authority:** [`../PROJECT_SPEC.md`](../PROJECT_SPEC.md) remains authoritative for cross-system product decisions.

This file preserves the final synthesis from the approved Astra audit. It intentionally excludes model reasoning and raw tool traces. Re-check current code, issue state, and live evidence before executing any packet below.

---
# 1. Executive summary

**HomeHub’s main architecture problem is uneven enforcement and stale execution contracts—not a missing whole-home orchestration framework.**

This read-only audit inspected local `master` at `17810d6`, authoritative documentation, relevant implementation surfaces, and **77 currently open GitHub issues**. GitHub’s connected reader returned the same inventory in ascending and descending searches. No files, Git state, issues, services, or devices were changed.

Material findings:

1. **A scheduled lighting path bypasses established ownership.** `MorningRoutineService.sunrise_ramp()` writes directly to Hue throughout a 30-minute loop, with only an initial DND check. It does not recheck manual ownership or lifecycle changes between steps. Fix this independently of the larger #139 Morning experience.
2. **#246 and #283 are genuine bounded implementation tasks.** Per-light manual ownership is process-local; microphone read failures can leave a heartbeating but nonfunctional worker.
3. **Several “future” foundations already exist.** Scene Curator’s initial path, shared music intelligence, central audio ownership, and cross-Activity fixture comfort must be extended or validated—not rebuilt.
4. **Audio ownership has two different guarantees that the contracts blur.** HomeHub’s lock serializes participating HomeHub writers. A fresh Sonos fingerprint followed by an unconditional device command is not atomic against an external Sonos controller.
5. **#131 cannot use existing mode-match accuracy as graduation evidence.** Current metrics compare predictions with HomeHub’s eventual mode, which is partly produced by the same evidence being evaluated. That measures agreement, not independent correctness or user satisfaction.
6. **#240 is the highest-leverage architecture investment**, provided its first boundary stays narrow: normalized evidence, explicit initial state and clocks, actual decision logic, and recorded non-actuating output.
7. **The issue graph needs reconciliation before more orchestration work.** #142, #244, #247, #253, #254, and the Dashboard/Canvas chain contain superseded execution instructions.

The cheapest useful next sessions are bounded correctness work and contract reconciliation. Living-room expansion, visual calibration, sleep graduation, and provider-dependent audio cleanup remain evidence-gated.

# 2. Architecture conflicts / stale contracts

“Fact” below means observed code or retrieved documentation. Issue statements about deployment are historical evidence, not this audit’s verification of production.

| Finding | Evidence | Architectural consequence |
|---|---|---|
| **Scheduled sunrise bypasses lighting ownership** | [`morning_routine.py`](../../backend/services/morning_routine.py), `MorningRoutineService.sunrise_ramp()`: direct `hue.set_light("2", …)` inside the loop; initial DND check only. [`bootstrap.py`](../../backend/bootstrap.py:798) registers the callback. | A manual adjustment or stronger policy arriving during the ramp need not stop subsequent writes. This is a concrete code-path defect; whether the schedule is enabled live was not checked. |
| **Per-light ownership disappears across reconstruction** | `EngineState.manual_light_overrides` and `manual_light_targets`; `LightOverrideManager.mark_manual()/clear_manual_stamps()/expire_manual_stamps()`. `AutomationEngine._persist_override_state()` persists mode/lifecycle fields, not these per-light records. [#246](https://github.com/agatte/home-hub/issues/246). | Restore ownership metadata before automation starts. Do not recreate it by replaying Hue commands or serializing the whole engine. |
| **Thread liveness is mistaken for sensing capability** | [`ambient_monitor.py`](../../backend/services/pc_agent/ambient_monitor.py:308), `_read_rms()` catches read errors and returns `None`; `run_monitor()` continues heartbeating. [#283](https://github.com/agatte/home-hub/issues/283). | Health needs separate “worker alive,” “microphone usable,” “classifier permitted,” and “last successful observation” facts. |
| **Audio “conditional” operations are preflight-guarded, not device CAS** | `AudioOwnershipService.run_manual()/run_if_valid()` serialize local operations. `SonosService._pause_if_playback_unchanged_sync()` reads then calls `pause()`; `_replace_queue_if_unchanged_sync()` reads then clears/replaces. [#274](https://github.com/agatte/home-hub/issues/274), [#276](https://github.com/agatte/home-hub/issues/276). | Do not extend claims about local serialization into an absolute guarantee against simultaneous external-controller writes. #273’s no-cleanup fallback correctly recognizes this limitation. |
| **Scene Curator status is internally contradictory** | [`PROJECT_SPEC.md:308`](../../docs/PROJECT_SPEC.md:308) says the target curator/ranking contract is absent. `living_room_atmosphere.py` contains `rank_atmospheres()`, `LivingRoomAtmosphereCurator.decide()` and application history. [#129](https://github.com/agatte/home-hub/issues/129)/[#130](https://github.com/agatte/home-hub/issues/130) explicitly describe the shipped first slice. Config defaults `LIVING_ROOM_ATMOSPHERE_ENABLED=False`. | Reconcile the spec to “initial foundation implemented; broader target incomplete; enablement/lived acceptance gated.” Do not change the product target or enable it as a documentation correction. |
| **House State is still a projection over legacy mode state** | [`AutomationEngine.house_state/activity`](../../backend/services/automation_engine.py:714) currently projects Away, Sleeping, and Home; its comment explicitly defers Winding Down to #138. | #138 needs a real session/overlay design preserving underlying Activity. Adding another override-mode value would perpetuate the collision. |
| **Autonomous couch intent uses manual-override machinery** | `AutomationEngine._evaluate_physical_context_relax()` calls `set_manual_override("relax", source="physical_context_relax")`; #129 already records the misleading presentation. | Preserve source distinction in status/UI now; do not count this as explicit human acceptance in #131. A wholesale override rewrite is unnecessary for that correction. |
| **#139 has weaker wording than current wake authority** | [#139](https://github.com/agatte/home-hub/issues/139) says continued activity/PC/phone activity may confirm awake. [`PROJECT_SPEC.md:797`](../../docs/PROJECT_SPEC.md:797) requires source-qualified intentional interaction and separates Home-after-wake from confirmed Morning. | Morning consumes an accepted wake decision; it must not introduce a second, weaker wake detector. A 03:00 Home transition is not permission for a morning routine. |
| **#149 retains an unsafe superseded Return Home recipe** | Its current-status preamble recognizes transactional V1, but older body steps say remove the Travel marker before starting services. The spec and `scripts/homehub-hostctl.sh` use `RETURNING_HOME`, prepare/activation fencing, and delayed HOME publication. [#149](https://github.com/agatte/home-hub/issues/149). | Replace the obsolete execution recipe with the current transaction reference before a cheap worker follows it. Remaining scope is contingency acceptance, not a lifecycle reimplementation. |
| **#254’s assisted-playback wording overstates authority** | Its progression says approved/proven candidates can play “automatically in narrow contexts.” The newer spec and `MusicAssistedPlaybackService` describe explicit request identity, exact provider identity, fresh guards, and no contextual DJ authority. [#254](https://github.com/agatte/home-hub/issues/254). | Distinguish explicit assisted playback from earned autonomous playback. Provider approval, taste confidence, and playback capability are separate permissions. |
| **#245’s original implementation premise is superseded** | Current `activity_detector.py` treats background games as context; foreground playback can win. `tests/test_activity_detector.py::test_gaming_alt_tab_grace_is_bounded_but_foreground_playback_wins_fast` covers the central case. [#245](https://github.com/agatte/home-hub/issues/245). | Reconcile acceptance and deployment evidence before writing another arbitration fix. Code coverage exists; this audit did not run it or verify the desktop deployment. |

### Stale umbrellas that materially affect execution

- **#142:** its September 7 “current” SHA, open prerequisite list, and broader sequence predate substantial September work. Treat it as an index needing refresh, not current execution authority.
- **#244:** the body still lists #251 implementation as outstanding. #251 is closed; current code shares `get_fixture_comfort_brightness_ceiling()` across engine, League, and ScreenSync. Its September 12 comment says remaining work is lived acceptance. Preserve that boundary.
- **#247:** the original hard-coded-provider and composition audit remains in the body, while comments record #248/#249 completion. Current `_compose_general_state()` also disproves the old assertion that General simply lacks the newer desk composition. #187’s coarse cloud classification remains separately visible in code.
- **#253:** its body calls implementation complete, but September 21 comments record additional quarter-sync work and deployment. A future worker must reconcile the latest acceptance findings, not assume the September 16 checklist is final.
- **#254:** its active list still presents #272/#278 as immediate unfinished gates; #276’s September 21 body records them and several ownership adopters as complete.
- **#276:** its current checkpoint is substantially newer than its “no single ownership authority” rationale and some unchecked audit items. Keep the remaining audit matrix, but do not rebuild the authority.
- **#157/#192/#217:** old bodies prescribe an active physical-reconstruction/rendering sequence. Later comments explicitly park it; #270 owns a future application-wide design pass. [`DASHBOARD_REDESIGN_VISION.md`](../../docs/DASHBOARD_REDESIGN_VISION.md) still reads as active Canvas-centered direction and needs an execution-status qualification.

Sources: [#142](https://github.com/agatte/home-hub/issues/142), [#244 closeout checkpoint](https://github.com/agatte/home-hub/issues/244#issuecomment-5647021119), [#247](https://github.com/agatte/home-hub/issues/247), [#253](https://github.com/agatte/home-hub/issues/253), [#157 latest direction](https://github.com/agatte/home-hub/issues/157#issuecomment-5718935539), [#192 park decision](https://github.com/agatte/home-hub/issues/192#issuecomment-5534410663).

### Circular evidence: a concrete measurement problem

`MLDecisionLogger.on_mode_change()` backfills `actual_mode` from the engine’s mode history. `compute_per_source_metrics()` then scores source votes against that label; those metrics feed adaptive fusion weights.

**Inference:** because the engine’s chosen mode is influenced by those sources, this is endogenous agreement evidence—not independent ground truth. The camera lane also answers a different question from semantic Working/Watching correctness. #116 already identifies that mismatch.

This is not proof of a current autonomous inference loop: **ConfidenceFusion is shadow-only**. It becomes dangerous if #131 treats these scores as evidence that an action has earned autonomy.

The music work contains a useful counterexample: #266 avoids counting the derived bandit posterior again as independent preference evidence, and `music_learning_provenance.py` ties passive outcomes to an owned session. Reuse those principles, not the music schema wholesale.

# 3. Missing/shared primitives and consolidation opportunities

| Primitive | Reuse / owner | Recommended boundary |
|---|---|---|
| **Action outcome identity** | #131; precedents in `music_feedback.py`, `music_trust.py`, `music_learning_provenance.py` | Identify action, context, policy version, originating decision, owner/session, user response, reversal, and uncertainty. Domain-specific evaluation remains separate. |
| **Versioned incident evidence envelope** | #240; reuse `CapabilitySnapshotV1`, `DecisionContextV1`, decision recorder, event provenance | Shared vocabulary for evidence/time/reasons. Do not turn the living-room snapshot into a universal mutable state object. |
| **Durable lifecycle/outage observation** | #74 supplies facts; #19 consumes them | Record startup identity, planned intent, last-known-good/recovery bounds, affected components, classification confidence. Recovery must not replay historical outputs. |
| **Suggestion lifecycle** | #132, consumed through #262 | Pending/accepted/rejected/deferred/expired, context identity, deduplication, and explicit action handoff. Ignoring remains non-action. |
| **Operational alert lifecycle** | #51 | Can share correlation IDs and delivery adapters with suggestions; must retain separate severity, acknowledgement, recovery, and interruption policy. |
| **Writer authority manifest** | #276 immediately; useful later for #240 | Map every writer to owner, dimensions, guard, final mutation boundary, cancellation behavior, restart behavior, and test. This can begin as a table, not a framework. |
| **Narrow clock/tick seam** | #240 | Wall time for persisted timestamps; monotonic elapsed time for deadlines; deterministic timer ordering. Introduce only at selected replay participants first. |
| **Command envelope and dispatcher** | #262 | Domain/action/validated parameters, authenticated provenance, request ID, query/action distinction. Dispatch into existing owners. Never carry caller-asserted permission. |

**Consolidations worth making**

- #254 owns shared music intelligence; #39 is diagnostics, #134 ambience policy, #40 source-delivery research, and #262 transport-independent commands.
- #74 records outage facts; #51 delivers alerts; #19 safely reacquires context; #14 displays history; #240 evaluates decisions offline.
- #129 owns lived couch value; #130 owns selection/evolution mechanics; #36 exposes existing scene policy. They should not each invent eligibility or feedback state.
- #138/#139 own experience semantics; #25 displays their session history.

**Abstractions to defer**

- **#16 generic executor:** wait for two accepted experiences with demonstrably duplicated sequencing. Cancellation semantics alone do not make projector shutdown, lighting transitions, and Sonos restore interchangeable.
- **Universal device lease manager:** lighting and Sonos have materially different observations and mutation guarantees.
- **Generic AI runtime:** `AI_SEMANTIC_LAYER.md` correctly waits for a second real consumer.
- **Universal physical-source model:** #192 geometry provenance is not permission to infer live occupancy. Preserve independent measured geometry and source-qualified sensing.
- **Whole-engine persistence:** #246 requires durable manual ownership, not restoration of transient detector/cache/task state.

# 4. Dependency and sequencing corrections

1. **Correct unsafe existing writers before expanding experiences.** The sunrise ownership defect should not wait for all of #139.
2. **#246 before relying on restart-safe lighting acceptance**, including #19 and later Winding Down sessions.
3. **#283 before audio-based sensing experiments**, including #20/#35 evidence collection. It is not a #254 music-curation blocker.
4. **#276’s remaining writer/concurrency audit before broader music actuation.** Do not require the general #240 harness to exist first; bounded fake-Sonos tests are sufficient.
5. **Resolve #273’s residual-risk/closure contract explicitly.** An unavailable device CAS primitive must not become an endless “implementation” task. Do not silently waive the existing #276 gate.
6. **#262 query and suggestion adapters can proceed independently of autonomous music.** The suggestion-only music domain contract already exists; do not wait for a session DJ.
7. **#129 lived validation before #130 expansion.** L6 satisfies the old hardware prerequisite. #148 is not another mandatory blocker.
8. **#131 outcome semantics before graduation thresholds.** Instrument a real bounded action first; do not promote from fusion confidence or absence of recorded complaints.
9. **#138 state/session design before #25 UI or a generic executor.** Projector shutdown remains separately evidence-gated.
10. **#139 consumes wake authority; #236 does not bypass calibration.**
11. **#74’s observation contract before #19’s outage-specific branching.** Neither needs a whole-home simulator.
12. **#270 design selection before broad route restyling.** #192 remains preserved physical truth, not an active prerequisite for every useful UI improvement.

# 5. Execution map

Owner means architectural responsibility, not a GitHub assignee. Model recommendations apply to the **next action**, not the entire issue. Grouped rows inventory every one of the 77 open issues.

| Issue / work item | Owner | Classification | Next action | Cheapest credible model |
|---|---|---|---|---|
| #3 Social L1 palette | Lighting | EVIDENCE_GATED | Reproduce current nighttime sightline | Terra Low |
| #7 celebration volume | Game Day/audio | EVIDENCE_GATED | Observe representative real-game intelligibility/level | Terra Medium |
| #13 motion sensor fallback | Sensing | PARKED | Await #137 trial | Luna Low |
| #14 history/time-machine | Observability/UI | ARCHITECTURE_READY | Define truthful historical reconstruction and gaps | Terra Medium |
| #15 ambient kiosk | Dashboard | PARKED | Await selected #270 composition | Luna Low |
| #16 sequence executor | Domain orchestration | PARKED | Require demonstrated duplication | Luna Low |
| #19 safe outage recovery | Lifecycle | ARCHITECTURE_READY | Design reacquisition from #74 facts and current owners | Sol Medium |
| #20 audio anomaly context | Sensing | EVIDENCE_GATED | Obtain class-specific local/media false-positive evidence | Terra Medium |
| #23 choreography; #24 transition learning | Lighting | PARKED | Await stable experience and measurable need | Luna Low |
| #25 overnight/session UI | Lifecycle/UI | PARKED | Await #138/#139 session contracts | Luna Low |
| #29 schema drift | Persistence | ARCHITECTURE_READY | Choose bounded fresh-create/upgrade authority | Terra Medium |
| #32 route parity | Dashboard | PARKED | Fold verification into #270 migration | Luna Low |
| #33 predictor zone change; #34 Sonos/weather features | ML | PARKED | Await #117 and a demonstrated error hypothesis | Luna Low |
| #35 Social detection/privacy | Sensing/privacy | EVIDENCE_GATED | Measure hybrid evidence; retain manual Social | Sol Medium |
| #36 Scene Browser policy | Lighting/UI | ARCHITECTURE_READY | Map current eligibility/provenance, avoid duplicate curator | Terra Medium |
| #39 bandit diagnostics | Music/UI | PARKED | Use current #254/#275 evidence shapes when promoted | Luna Low |
| #40 long-form ambience | Audio/provider | EVIDENCE_GATED | Prove source quality, continuity, supported delivery | Terra Medium |
| #41 kiosk performance | Frontend/runtime | EVIDENCE_GATED | Capture current representative performance trace | Terra Medium |
| #51 operational alerts | Operations | ARCHITECTURE_READY | Define alert lifecycle and silent-first delivery slice | Terra Medium |
| #55 CSP | Frontend/security | EVIDENCE_GATED | Inspect current served policy and built application | Terra Medium |
| #56 Desk posture | Sensing | EVIDENCE_GATED | Demonstrate current posture error and useful consumer | Terra Medium |
| #68 Latitude microphone | Sensing | PARKED | Await a physical-context gap | Luna Low |
| #74 healed outage history | Operations | ARCHITECTURE_READY | Define durable bounded outage facts | Terra Medium |
| #80 legacy Bed/posture cleanup | Sensing/lifecycle | EXECUTION_READY | Inventory consumers, remove only obsolete assumptions | Terra Medium |
| #83 controller idle | Desktop sensing | EVIDENCE_GATED | Reproduce controller-only false Idle | Terra Medium |
| #97 legacy NAS | Infrastructure | PARKED | No architecture dependency justifies promotion | Luna Low |
| #105 Gaming umbrella | Gaming | ARCHITECTURE_READY | Reconcile shipped foundation and bounded children | Terra Medium |
| #107 arrival | Lifecycle/interaction | ARCHITECTURE_READY | Separate arrival transaction from suggestion experience | Terra Medium |
| #116 fusion metric objective | ML | ARCHITECTURE_READY | Define lane-specific evaluation and independent labels | Sol Medium |
| #117 predictor quality | ML | EVIDENCE_GATED | Export recent serving/training comparison | Terra Medium |
| #129 everyday couch | Living-room experience | EVIDENCE_GATED | Post-L6 lived validation; separate autonomous provenance | Terra Medium |
| #130 curator expansion | Lighting | PARKED | Expand only for gaps found by #129 | Luna Low |
| #131 outcome/provenance contract | Autonomy | ARCHITECTURE_READY | Design first action-specific evidence lifecycle | Sol Medium |
| #131 graduation policy | Product/autonomy | DECISION_NEEDED | Choose first action/context and acceptable reversal policy | Sol Medium |
| #132 suggestions | Interaction | ARCHITECTURE_READY | Define pending suggestion and feedback lifecycle | Terra Medium |
| #133 Mood Context | Interaction/context | ARCHITECTURE_READY | Specify explicit temporary state and expiry transitions | Terra Medium |
| #134 weather ambience | Audio/experience | ARCHITECTURE_READY | Compose Relax/context eligibility with shared ownership | Sol Medium |
| #136 desk balance | Lighting | EVIDENCE_GATED | Remaining evening/night perceived balance | Terra Medium |
| #137 kitchen inference | Sensing/lighting | EVIDENCE_GATED | Bounded missed-visit/false-activation trial | Terra Medium |
| #138 Winding Down | Lifecycle | ARCHITECTURE_READY | Session overlay and authority transition design | Sol High |
| #139 Morning | Lifecycle | ARCHITECTURE_READY | Separate accepted wake, morning confirmation, and brief | Sol Medium |
| Sunrise ownership safeguard, under #139 | Lighting/lifecycle | EXECUTION_READY | Replace direct unguarded ramp writes | Terra High |
| #140 event orchestration | Events | ARCHITECTURE_READY | One event record, activation/pause/end ownership | Sol Medium |
| #141 event guest experience | Guest/events | ARCHITECTURE_READY | Request queues/leases behind guest capability boundary | Sol Medium |
| #142 portfolio | Architecture/docs | EXECUTION_READY | Reconcile superseded checkpoints | Luna Low |
| #148 cabinet cove | Physical lighting | EVIDENCE_GATED | Real dry-fit/wash acceptance before final installation | Terra Medium |
| #149 Travel contingency | Host lifecycle | EVIDENCE_GATED | Hardened Return Home round-trip acceptance | Terra High |
| #154 nighttime Watching | Lighting/sensing | EVIDENCE_GATED | Current Couch/projector/path-light acceptance | Terra Medium |
| #157 Dashboard | Product/UI | PARKED | Resume through #270, not old Canvas sequence | Luna Low |
| #160 frontend advisories | Frontend/security | EVIDENCE_GATED | Refresh exact lockfile findings/exposure | Terra Medium |
| #184 synthetic Canvas | Dashboard | PARKED | Preserve existing work | Luna Low |
| #187 cloud semantics | Weather/lighting | ARCHITECTURE_READY | Define bounded taxonomy using shipped provider context | Terra Medium |
| #191 browser/work continuity | Desktop sensing | EVIDENCE_GATED | Current labeled browser-use examples | Terra Medium |
| #192 physical-world authority | Physical model | PARKED | Preserve evidence; no speculative reconstruction | Luna Low |
| #202 Bed comfort | Lighting | EVIDENCE_GATED | Per-fixture evening/night/late-night calibration | Terra Medium |
| #204 RDR2; #208 OSRS profiles | Gaming/lighting | EVIDENCE_GATED | Reconcile resolver, then real-room palette acceptance | Terra Medium |
| #205 telemetry adapters | Gaming | EVIDENCE_GATED | No-lighting event/privacy/rate feasibility | Terra Medium |
| #207 workstation visualization; #217 premium render | Dashboard | PARKED | Await explicit visual-program promotion | Luna Low |
| #231 DNS filtering | Infrastructure | EVIDENCE_GATED | Current coverage/breakage comparison | Terra Medium |
| #236 Apple Health | Sensing/lifecycle | EVIDENCE_GATED | Representative latency/false-positive nights | Terra Medium |
| #240 replay | Sensing/architecture | ARCHITECTURE_READY | Dedicated brief in section 9 | Astra |
| #241 backend advisories | Backend/security | EVIDENCE_GATED | Refresh installed/pinned versions and exposure | Terra Medium |
| #243 ScreenSync color | Lighting | EVIDENCE_GATED | Remaining evening/night perceived relevance | Terra Medium |
| #244 comfort sprint | Lighting | EVIDENCE_GATED | Reconcile completed engineering; lived matrix only | Terra Medium |
| #245 background game hold | Desktop sensing | EXECUTION_READY | Verify existing regression/coverage and closeout scope | Terra Low |
| #246 manual light persistence | Lighting/lifecycle | EXECUTION_READY | Persist bounded owner metadata | Terra Medium |
| #247 weather umbrella | Weather/lighting | ARCHITECTURE_READY | Reconcile #248/#249; scope #187/#134 residuals | Terra Medium |
| #253 Game Day sprint | Game Day | EVIDENCE_GATED | Reconcile latest game findings and remaining acceptance | Terra High |
| #254 broader music playback | Music | ARCHITECTURE_READY | Design only after #276 residual gate is resolved | Sol Medium |
| #262 command layer | Interaction | ARCHITECTURE_READY | Small schema/dispatcher coexistence design | Terra Medium |
| #270 application-wide UX | Product/UI | PARKED | Await capability stabilization and visual selection | Sol High |
| #273 safe stale-queue release | Audio/provider | EVIDENCE_GATED | Stronger device proof; retain no-cleanup fallback | Sol High |
| #274 remaining guarantee contract | Audio | DECISION_NEEDED | Define external-controller race guarantees precisely | Sol High |
| #276 writer/concurrency audit | Audio | EXECUTION_READY | Complete manifest and fake-device matrix | Terra High |
| #276 release/physical closure | Audio | EVIDENCE_GATED | Resolve residual gates and verify real takeover cases | Terra High |
| #283 microphone recovery | Desktop sensing | EXECUTION_READY | Bounded stream recovery plus semantic health | Terra Medium |

# 6. Detailed FUTURE SESSION PACKETS

These are reusable task briefs. They authorize nothing in this session; later publishing, deployment, restart, and physical tests retain their normal gates.

## Packet A — #246: durable per-light manual ownership

- **Goal:** Preserve still-valid per-light manual ownership through ordinary backend reconstruction.
- **Product/acceptance contract:** Restart does not release a human hold; expired/released holds stay released; restoring ownership causes no device write.
- **Authority surface:** `EngineState`; `LightOverrideManager`; `AutomationEngine._persist_override_state()/load_override_state()`; `LightApplicator.protected_light_ids()`; bootstrap before automation tasks.
- **Dependencies/order:** Independent correctness fix. Restore before any automatic reconciliation.
- **Recommended approach:** Add a versioned, narrowly scoped persisted record containing light ID, original stamp/expiry information, and held target only where existing owner consumers require it. Centralize persistence on mark, clear, and expiry. Serialize mutations so a delayed save cannot resurrect a cleared hold. Reuse `app_settings` conventions.
- **Invariants/non-goals:** No whole-engine snapshot; no persistence of dedup cache or transient transit claims; no startup Hue replay; no new expiry semantics.
- **Likely files:** `engine_state.py`, `light_override_manager.py`, `automation_engine.py`, `bootstrap.py`, existing settings persistence and lighting tests.
- **Validation:** Reconstruct with fresh/expired/malformed records; clear after restore; delayed-save ordering; automatic apply skips restored light; kitchen pair and ScreenSync/transit composition remain intact. Later: one authorized restart with an active hold.
- **Integration/review risk:** Startup ordering and synchronous mark APIs becoming asynchronous or fire-and-forget.
- **Done when:** Metadata restoration precedes automation, targeted tests prove behavior, and the later restart acceptance is recorded separately.
- **Cheapest credible worker:** **Terra Medium**—bounded state/persistence change with established owner.
- **Exact escalation triggers:** Conflicting clear semantics; need to restore physical targets by writing devices; changes to mode-level persistence; inability to order durable writes safely.

## Packet B — #283: microphone recovery and truthful capability health

- **Goal:** Recover closed/unavailable PyAudio streams without a permanently healthy-looking dead sensor.
- **Product/acceptance contract:** Bounded retries, no duplicate streams, no log storm, no fabricated observations, truthful configured/healthy/disabled/recovering states.
- **Authority surface:** `AmbientMonitor._init_audio()/_read_rms()/close()`, `run_monitor()`, PC-agent supervisor heartbeat and backend audio-health ingress.
- **Dependencies/order:** No dependency on Music Intelligence. Complete before interpreting missing audio observations as behavioral evidence.
- **Recommended approach:** A small recovery state machine in the existing worker; release both stream and PyAudio resources before reopening; monotonic retry deadline; reset partial classifier buffers and quiet-duration evidence after capture loss. Preserve Blue Yeti preference/default fallback.
- **Invariants/non-goals:** No raw audio persistence; no new Social authority; recovery cannot override classifier privacy/policy disablement.
- **Likely files:** `pc_agent/ambient_monitor.py`, existing supervisor/health reporting, audio ingress schemas only if necessary.
- **Validation:** Inject stream-closed error, repeated unavailable device, recovery, shutdown during backoff, disabled classifier, and partial-buffer interruption. Assert one active stream and fresh observations only after successful reads. Later: authorized unplug/reconnect test.
- **Integration/review risk:** Resource ownership and stale buffered evidence after reconnect.
- **Done when:** Fault injection recovers deterministically and capability health distinguishes liveness from usable sensing; physical verification remains explicit.
- **Cheapest credible worker:** **Terra Medium**—small worker lifecycle with deterministic fault cases.
- **Exact escalation triggers:** Recovery requires process-wide supervisor changes, cross-thread forced termination, device-selection policy changes, or new sensing authority.

## Packet C — Morning sunrise ownership safeguard

- **Issue/workstream:** Bounded safety child of #139; no new issue was created.
- **Goal:** Eliminate the direct-Hue scheduled ramp bypass.
- **Product/acceptance contract:** Every autonomous ramp step respects current lifecycle, DND, manual/protected/transit/scene/ScreenSync ownership. A newer owner prevents subsequent stale writes.
- **Authority surface:** `MorningRoutineService.sunrise_ramp()`, `AutomationEngine` lighting verbs, `LightApplicator`, `LightingTransitionBoundary`, scheduler registration.
- **Dependencies/order:** Can precede the full Morning design. First inventory existing engine ramp verbs and their exact protections.
- **Recommended approach:** Route a bounded per-light request through the existing owned application path. Use a session/generation cancellation check and re-evaluate eligibility immediately before each step. Stop on lost authority; release by current-policy reconciliation, not an old snapshot.
- **Invariants/non-goals:** Do not change schedule defaults, establish wake, add morning speech, choose new brightness values, or implement #138/#139 wholesale.
- **Likely files:** `morning_routine.py`, a narrow engine-facing eligibility/application seam, focused routine tests.
- **Validation:** Manual L2 hold before start and mid-ramp; Away/Sleeping/DND during delay; stronger light owner; cancellation; unavailable Hue; zero writes after authority loss.
- **Integration/review risk:** Accidentally giving a scheduled request explicit-user authority, or assuming `_apply_state()` alone enforces every lifecycle rule.
- **Done when:** No direct sunrise device writes remain and each delayed step is demonstrably subordinate to current owners.
- **Cheapest credible worker:** **Terra High**—bounded task, but delayed operations and multiple ownership layers interact.
- **Exact escalation triggers:** Existing schedule semantics deliberately require overriding Sleeping/manual intent; fixing it requires changing the wake contract; no existing owned path can express the bounded request.

## Packet D — #276: complete the audio writer/concurrency evidence matrix

- **Goal:** Account for every Sonos mutation and prove the implemented local ownership guarantees.
- **Product/acceptance contract:** Each writer has an explicit classification; manual invalidation, lease dimensions, restart and cancellation behavior are test-covered; unsupported external atomicity is stated honestly.
- **Authority surface:** `AudioOwnershipService`; `SonosService`; MusicMapper, Ambient, TTS, mode-volume, Game Day, assisted playback; REST, guest, WebSocket and Alexa ingress.
- **Dependencies/order:** Use the existing foundation and adopter tests. Does not depend on #240. Does not itself unblock broader #254 autonomy.
- **Recommended approach:** First produce a call-site manifest. Map existing tests to the sprint’s cases; add only missing adversarial schedules using controllable fake Sonos operations. Distinguish HomeHub-lock races from external-device races and from worker-thread settlement.
- **Invariants/non-goals:** No new ownership service; no speculative Stop/Clear rollback; no live playback; no relaxation of lifecycle or explicit-playback gates.
- **Likely files:** Existing audio services and `tests/test_audio_ownership.py`, `test_audio_ownership_ingress.py`, `test_ambient_audio_ownership.py`, relevant TTS/mapper/assisted tests.
- **Validation:** Manual mutation during TTS/ramp/preflight; restart after ownership acquisition; delayed sync write after timeout; post-Play takeover; passive reward after pause/skip/takeover; Away/Sleeping/DND for each writer.
- **Integration/review risk:** Treating fake-device serialization as proof of physical Sonos atomicity.
- **Done when:** Every mutation has a mapped owner and evidence; missing guarantees become explicit residuals; physical acceptance and policy decisions remain separately open.
- **Cheapest credible worker:** **Terra High**—mechanical inventory plus bounded concurrency testing.
- **Exact escalation triggers:** Unowned production writer, contradictory lease dimensions, an unavoidable external race covered by an absolute guarantee, or a proposed destructive cleanup.

## Packet E — stale-contract reconciliation and #245 closeout preparation

- **Goal:** Stop future sessions from rebuilding shipped work or executing obsolete lifecycle recipes.
- **Product/acceptance contract:** Preserve historical evidence while making current status, remaining scope, and dependencies unambiguous.
- **Authority surface:** `PROJECT_SPEC.md`, `README.md`, `Future_Development.md`, Dashboard vision; #142/#149/#244/#247/#253/#254/#276 and #157/#192/#217/#270.
- **Dependencies/order:** Use this audit as a checklist, then reread current issue bodies/comments and code. No new product choices.
- **Recommended approach:** Replace stale “next implementation” instructions with bounded remaining gates. Mark old snapshots historical. For #245, inspect current regression coverage, run the appropriate tests in a later writable test session, and identify any genuinely uncovered acceptance criterion.
- **Invariants/non-goals:** No claim that code proves deployment or physical acceptance; no automatic closure of a parent merely because children shipped; no enabling dormant features.
- **Likely files/subsystems:** Documentation and issue contracts only.
- **Validation:** Every status statement links to code, current child state, or explicitly dated acceptance evidence; all dependency arrows remain consistent.
- **Integration/review risk:** Turning a chronology cleanup into a roadmap decision.
- **Done when:** A worker can identify exactly what remains without reading historical comments; #245 has either closeout evidence or a concrete residual.
- **Cheapest credible worker:** **Luna Low** for prescribed reconciliation; **Terra Low** for #245 code/test verification.
- **Why sufficient:** Architecture judgment has been removed; the work is evidence-backed extraction and precise editing.
- **Exact escalation triggers:** Conflicting accepted product decisions, missing deployment evidence required for closure, or proposed changes to roadmap priority.

# 7. ARCHITECTURE_READY / DECISION_NEEDED / EVIDENCE_GATED briefs

## #131 — per-action autonomy

**ARCHITECTURE_READY:** Design an outcome contract around one real action. Recommended first candidate: a bounded living-room lighting selection, after #129 can supply useful observations.

Record decision/action identity, context and policy version, actual application result, ownership, explicit response, quick reversal, later correction, and censoring reasons such as Away or device failure. Reuse music provenance principles. Do not interpret “no override recorded” as positive feedback without proving the action occurred and remained observable.

**DECISION_NEEDED:** Which action/context is first, what counts as a meaningful reversal, and what evidence permits graduation/demotion? Numerical thresholds cannot be derived from the existing broad issue.

**Next design pass:** **Sol Medium**. Output one action-specific state machine and evidence table, not a universal autonomy engine.

## #262 — command/intent layer

**ARCHITECTURE_READY.** The domain boundary is already decided.

Design a small versioned command envelope and dispatcher that coexist with current Alexa handlers. Start with a House State/Activity query and one existing bounded manual action. Preserve `X-HomeHub-Source`, authentication and request attribution. Music suggestion commands can call the existing suggestion-only request contract.

Avoid a generic payload that permits raw domain method names, device URIs, caller-supplied trust, or inferred permissions. Query commands must be incapable of dispatching writes.

**Next design pass:** **Terra Medium**. After the schema and two mappings are fixed, adapters/tests should be **Terra Low** work.

## #132 and #51 — separate interaction contracts

**ARCHITECTURE_READY.**

- **#132:** one pending contextual suggestion, expiry/context invalidation, chime deduplication, “what is it?” lookup, explicit accept/reject/modify/defer, and frequency feedback.
- **#51:** persistent operational fault identity, consequence, acknowledgement, deduplication, recovery/clear, and per-surface delivery result.

Use `NotifierService.emit_suggestion()/emit_alert()` as existing surfaces to inspect, not proof that the target lifecycle exists. Chime/TTS delivery remains an audio-owned action.

**Smallest unresolved decisions:** whether any exceptional safety class may interrupt Sleeping, and its exact scope. V1 can remain silent/dashboard/ntfy without inventing such a class.

**Next design pass:** **Terra Medium**.

## #138/#139 — lifecycle sessions

**ARCHITECTURE_READY.**

For #138, model Winding Down as a session with identity, start/extend/cancel/end, underlying Activity, owned effects, deadlines, and restart semantics. Its visible House State does not erase the activity being enjoyed.

For #139, distinguish:

1. overnight movement/path assistance;
2. accepted wake establishing Home;
3. sustained/explicit Morning confirmation;
4. optional brief delivery.

**EVIDENCE_GATED:** projector normal shutdown/cooling and controllable power sequence; Apple Health latency/reliability.

**Next design passes:** **Sol High** for #138’s first session/ownership design; **Sol Medium** for #139. Neither needs a general sequence executor first.

## #140/#141 — events and guests

**ARCHITECTURE_READY**, but lower priority.

One event record should hold identity, time bounds, editable plan, activation state and host controls. “Dominates Social” means atmosphere/experience precedence beneath lifecycle/privacy/manual constraints—not global authority.

Guest music requests and lighting requests need separate queue semantics. A guest request is not ordinary host manual intent. Preserve the dedicated guest gateway’s allowlisted capabilities; do not expose a generic command dispatcher through it.

**Next design pass:** **Sol Medium**, limited to event lifecycle plus one request type. Defer complete event planning automation.

## #19/#74 — recovery versus history

**ARCHITECTURE_READY.**

The durable record should distinguish observations from classification:

- last confirmed healthy;
- first observed failure, when available;
- first confirmed recovery;
- host/process identity;
- planned lifecycle/deploy intent;
- affected component;
- classification and uncertainty.

A backend cannot observe the exact beginning of its own total outage. Without independent evidence, record a bounded interval—not a fabricated timestamp or certain “power failure.”

#19 should use these facts to select conservative reacquisition, not historical device replay.

**Smallest decision:** meaningful duration/consequence threshold for user-visible outage history. Exact root-cause attribution is not required for safe recovery.

**Next design pass:** **Terra Medium** for #74, then **Sol Medium** for #19.

## Audio residual: #273/#274/#276

**EVIDENCE_GATED:** safe destructive stale-queue cleanup requires a device/provider mechanism stronger than the current read-then-write proof.

**DECISION_NEEDED:** define the supported external-controller concurrency guarantee. In particular, determine whether the existing bounded preflight semantics for start/pause/restore are accepted while destructive stale cleanup remains prohibited.

Do not silently redefine “manual always wins” to mean only HomeHub API calls. Conversely, do not promise an external atomicity guarantee the adapter cannot provide.

**Next design pass:** **Sol High**. Keep the no-cleanup fallback and broader-autonomy gate intact pending that decision.

## Evidence gates that should not become speculative engineering

| Work | Exact missing evidence |
|---|---|
| #129/#130 | Post-L6 quiet/listening/settled couch sessions: composition quality, repetition, corrections, and autonomous-versus-manual presentation |
| #136/#243/#244 | Remaining evening/night and cross-Activity perceived comfort/color relevance |
| #137 → #13 | Missed dark visits, false activations, premature fades, correction rate on current inference |
| #202 | Fixture-specific Bed comfort ceilings across evening/night/late-night, including ScreenSync and non-bedroom lights |
| #236 | Several representative nights of native delivery latency, freshness, brief wakes, interaction vetoes and source differences |
| #117 | Recent labeled serving rows, feature distributions, model version and per-class confusion |
| #253/#7 | Current real-game timing, no-spoiler behavior, volume/intelligibility and end-to-end acceptance |
| #149 | Hardened Return Home transaction, restoration ordering and fresh post-return sensing |
| #40/#134 | Acceptable long-form source quality and supported Sonos continuity |
| #160/#241/#55 | Current package/advisory exposure and actual built/served CSP; old counts are not current findings |

# 8. Items that still justify Sol/Astra

- **Astra Medium: #240’s dedicated boundary design.** It spans source freshness, engine state, navigation ownership, output composition, asynchronous timing and structural no-actuation guarantees. After this pass, most slices should be Terra work.
- **Sol High: audio residual guarantees.** The difficult part is reconciling local ownership with external-controller races and accepted device limitations.
- **Sol High: initial #138 architecture.** It must preserve Activity while introducing a durable lifecycle session across lighting, audio and projector behavior.
- **Sol Medium: #131.** Independent outcome evidence and consequence-specific graduation require judgment; implementing a settled ledger does not.
- **Sol Medium: #19 and event/guest authority design.** These cross ownership boundaries but can remain bounded.
- **Sol High: #270 when promoted.** Product composition and responsive interaction need judgment and user-visible acceptance. It does not presently justify Astra or implementation.

No other audited task currently requires Astra. Mechanical reconciliation, manifests and extraction should default to Luna Low.

# 9. Dedicated #240 Astra Medium follow-up brief

**Role:** GPT-6 Astra, MEDIUM effort. Read-only architecture pass. No implementation, repository/GitHub writes, runtime access that mutates state, device calls, or service changes.

**Objective:** Produce an implementation-ready design for the smallest deterministic HomeHub incident replay, using this audit’s authority map. Do not design a whole-home simulator.

### Exact questions to answer

1. Which concrete recent incident has enough retained normalized input and initial-state evidence to reproduce an accepted outcome?
2. Which state predates the capture window and must be exported rather than reconstructed?
3. Which existing decision functions can run independently, and which narrowly scoped seams are necessary?
4. Where does the first replay stop: requested per-light output, ownership filtering, or adapter acknowledgement?
5. Which outputs are facts, deterministic derived decisions, requested actions, and observed device responses?
6. What is the minimum clock/scheduler interface that preserves freshness, dwell, timeout and same-time ordering?
7. How can the composition root make access to real adapters impossible?
8. Which counterfactuals are valid with fixed recorded observations, and which require unknown environmental feedback?

### Minimum replay boundary

Choose **one incident-driven vertical chain**:

`normalized source-qualified observations → PresenceFusion → relevant Activity/House State arbitration → DeskExit/navigation decision → owned lighting request`

Include ScreenSync context/brightness resolution only if the chosen incident requires it. Use already-derived color/luma evidence; do not rerun screen capture or vision models.

Do not require Sonos, Game Day, every engine branch, or full renderer replay in v1.

### Incident-bundle schema concerns

Specify:

- schema version, bundle identity and integrity hash;
- code/build identity, relevant configuration and policy versions;
- bounded start/end and timezone;
- source/session/boot identity;
- observed/captured time, received time, sequence and clock domain;
- present/absent/unknown, source health, freshness and abstention;
- accepted versus merely reported semantic activity;
- initial lifecycle/owner state and relevant pre-window dwell history;
- manual stamps/targets, transit deadlines, scene/effect ownership;
- ScreenSync source/fixture ownership and freshness;
- Away, external-off, DND, Sleeping, host-return suppression and awake latch;
- light/device observations only where decisions consume them;
- expected trace assertions and explicitly missing fields.

Retain normalized evidence, not credentials, raw camera/audio/screen content, or an unrestricted production database dump. Missing required initial state should make the fixture incomplete, not silently default healthy.

### Deterministic time and freshness

Audit `datetime.now()`, `time.time()`, monotonic clocks, `asyncio.sleep()`, delayed tasks and timeout paths in selected participants.

Define:

- virtual UTC wall time;
- virtual monotonic elapsed time;
- deterministic timer/event ordering;
- ties and duplicate observations;
- late/out-of-order and future-dated input handling;
- restart/boot boundaries;
- seeded randomness where actually required.

Advancing replay time must expire evidence and trigger dwell/deadline behavior without real sleeping. Do not replace timestamps with event-list position.

### Ownership/suppression capture

Capture enough state to explain **why no action occurred**, not just emitted writes.

The trace should distinguish:

- proposal;
- eligibility result;
- stronger-owner suppression;
- final bounded request;
- fake adapter result;
- resulting simulated internal state.

Do not treat confidence, an event overlay, a physical geometry model, or an existing snapshot as write permission.

### No-actuation proof strategy

Prefer a dedicated offline composition root that never imports/starts production bootstrap and receives only fixture stores, virtual clocks and recording sinks.

Require structural tests proving:

- no real Hue/Sonos/Kasa/projector/notification/shutdown adapter is constructed;
- no network/subprocess/device operation is reachable;
- no production settings/database path is opened for writing;
- all outputs terminate in recording sinks;
- attempts to wire a forbidden adapter fail loudly.

A `replay=True` flag around production bootstrap and no-op methods alone are insufficient proof.

### Counterfactual comparison boundary

Run the same immutable bundle through baseline and candidate code/config in isolated contexts. Compare ordered decisions, decisive evidence, reason codes, owner transitions and requested outputs.

Label the result **fixed-evidence counterfactual**. A different light request may have changed camera lux or human behavior in reality; replay cannot invent those downstream observations.

Separate:

- historical reproduction against the recorded build/config;
- current-code interpretation of old evidence;
- candidate-versus-baseline comparison.

### Incremental slices and cheaper workers

| Slice | Deliverable | Worker |
|---|---|---|
| 1 | Exact input/state/clock/side-effect manifest for selected incident | Luna Low |
| 2 | Versioned bundle validator and fixture-only reader | Terra Low |
| 3 | Clock/tick seams for selected participants | Terra Medium |
| 4 | Offline composition root and forbidden-I/O tests | Terra High |
| 5 | First incident replay with golden assertions and reason trace | Terra Medium |
| 6 | Baseline/candidate semantic diff | Terra Medium |
| 7 | Bounded export adapter, only after schema proves sufficient | Terra Medium |

### Acceptance criteria

- One real incident has an evidence-backed bounded fixture.
- Repeated runs produce identical semantic output.
- Initial-state and evidence gaps are explicit.
- Freshness, unknown/abstention, dwell and owner suppression are explainable.
- A meaningful candidate change produces an intelligible diff.
- Forbidden live I/O is structurally excluded and tested.
- Existing production behavior remains unchanged by extraction seams.
- The design identifies exact files, interfaces, test cases and escalation triggers for each implementation slice.

### Explicit non-goals

Whole-home simulation; synthetic human behavior; raw ML inference; device firmware emulation; production recovery; automatic fixes; policy graduation; visual dashboard replay; AI Analyst implementation; a universal event bus; general event sourcing; replaying old commands into the apartment.

HomeHub Analyst may later consume the bounded trace. It must not become replay’s causal authority.

# 10. Uncertainties / evidence not accessed

- Public GitHub/API attempts failed. The connected GitHub reader supplied the **77-issue inventory**, issue bodies and selected relevant comment threads.
- No live HomeHub state, production database, physical room, Sonos firmware behavior, or deployed desktop build was verified.
- Tests were inspected but not executed. No new current test-pass claim is made.
- Local Git status showed no changes, with a permission warning for `.pytest_cache`; one registered worktree was reported.
- This was a targeted architecture audit, not exhaustive verification of every writer or every issue comment. The proposed #276 manifest closes that specific coverage gap.
- #245 is a **code-supported closeout candidate**, not an assertion that its deployed acceptance is complete.
- The execution map is delivered here as the reusable artifact; nothing was persisted because the task prohibited writes.
