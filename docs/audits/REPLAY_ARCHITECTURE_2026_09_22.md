# #240 Deterministic Replay Architecture — 2026-09-22

> **Status:** Accepted bounded architecture for GitHub #240. Implementation guidance, not product authority and not a live-health claim.
> **Design model:** GPT-6 Astra, medium reasoning effort.
> **Repository baseline:** `13a3b0a0079c5e4a0b396b26f4c8b114c3cd28ae` (`master`) on 2026-09-22.
> **Scope:** Read-only design for the smallest deterministic navigation replay, including evidence capture, virtual time, no-actuation proof, counterfactual limits, and implementation decomposition.
> **Current execution guidance:** See [`../EXECUTION_MAP.md`](../EXECUTION_MAP.md).
> **Product authority:** [`../PROJECT_SPEC.md`](../PROJECT_SPEC.md) remains authoritative for cross-system product decisions.

This file preserves the accepted final synthesis from the dedicated #240 Astra Medium architecture pass. It intentionally excludes model reasoning and raw tool traces.

---
## 1. Executive decision

Build a **small, offline navigation replay**, initially scoped to the July 2026 desktop-inactive lighting incident’s repeated-transit behavior.

**No historical fixture found is sufficiently evidenced to claim deterministic reproduction.** The first real fixture must therefore be evidence-gated. Do not convert the incident narrative or synthetic regression tests into purported historical observations.

The first supported capture should cover:

> Source-qualified physical observations → PresenceFusion → retained Working/House State authority → TransitLightingService → owned lighting requests → recorded adapter results, including timeout and attempted rearming.

Use the existing **TransitLightingService navigation branch**; DeskExit’s evening and corridor machines are unnecessary for this first slice. **ScreenSync is out.**

Scope the initial capture to daytime, desktop unavailable, explicit Working intent, one backend boot, and no active scene/effect/ScreenSync owner. These conditions must be **verified in the capture**, never supplied as convenient defaults.

This design was inspected against local `master` at **`13a3b0a0079c5e4a0b396b26f4c8b114c3cd28ae`**. [Issue #240](https://github.com/agatte/home-hub/issues/240) contained the current architecture checkpoint and **no comments**. No files, GitHub state, runtime state, or devices were changed. Tests were inspected, not executed.

## 2. Selected first incident — evidence-gated candidate

**Selected incident:** repeated transit activation during the **July 14–31, 2026 desktop-inactive lighting incident**.

The retained [incident report](../../docs/INCIDENT_2026_07_DESKTOP_INACTIVE_LIGHTING.md) records:

- Anthony remained home; desktop camera and agents were unavailable.
- Latitude sensing remained active.
- Continuous camera absence repeatedly produced transit activation, ten-minute timeout, restoration, and reactivation.
- L1 received 1,501 transit writes after July 15; 1,032 intervals were approximately 10–12 minutes.
- Separately, explicit modes expired without fresh semantic replacement.

These are **historical investigation findings**, not newly verified production facts.

Why this candidate:

- It exercises physical evidence, semantic-source unavailability, user-intent retention, navigation dwell, ownership, timeout, and suppression.
- Current regression tests directly encode its central contracts.
- It needs neither raw inference nor ScreenSync.
- A daytime Working capture avoids Gaming composition, overnight authority, audio-dependent Relax acquisition, and DeskExit’s staged corridor.

Other inspected candidates were less suitable:

| Candidate | Why not first |
|---|---|
| May 31 warm/Gaming strobe | Good DeskExit evidence, but broader Gaming/renderer interaction and no retained normalized timeline/checkpoint found |
| #109 source-zone mismatch | Useful diagnosis and regression provenance, but aggregate counts do not reconstruct a decision window |
| September 7 Sleeping/Watching conflict | Identified as an Analyst gold incident in `AI_SEMANTIC_LAYER.md`; broader wake/lifecycle arbitration and no complete replay bundle found |
| Existing Game Day fixtures | Real retained fixtures, but expressly outside #240 v1 |

**Missing historical evidence**

The July report does not retain:

- A particular transit cycle’s complete normalized observations.
- Capture versus receipt timestamps and consumed ordering.
- Initial fusion readings/high-water marks.
- Transit arming, streaks, dwell start, cooldown, and owned-light state.
- Concurrent engine tick ordering.
- Exact relevant configuration, owner maps, acknowledged cache, and adapter outcomes.
- A complete historical build/environment identity.

The documented July 31 Working-expiry timestamps must **not** be joined to an unspecified transit cycle and presented as one observed causal sequence.

Repository inspection found synthetic navigation tests, incident summaries, and current diagnostic logs, but no suitable July replay bundle. The truth-table capture script requests images and captures point-in-time status; it is neither the required exporter nor something this pass ran.

**First-capture gate:** retain one naturally occurring, fully observed daytime navigation interval, preferably up to 15 minutes, spanning initial strong presence, absence, one activation, timeout, cooldown, and continued absence. A successful modern capture can establish the no-refire contract; it must not be labeled a reproduction of July’s original failure.

## 3. Exact v1 replay boundary

### Start

The physical ingress is exactly:

`PresenceFusion.on_observation(PresenceReading)`

after upstream inference, source qualification, and timestamp normalization.

Capture the **actual normalized argument**, together with receipt metadata. Desktop’s route currently applies `clamp_client_timestamp()` before calling fusion; replay starts after that normalization and must not clamp it a second time.

Replay also requires immutable views of inputs consumed alongside fusion:

- Latitude camera status, including authority readiness and lux.
- Initial accepted Activity/override/lifecycle state.
- Source-health and invalidation events.
- Relevant cached light observations and configuration.
- Recorded navigation/engine evaluation opportunities.

These are separate inputs. A `PresenceReading` alone does not contain everything navigation consumes.

### Included decision path

1. Actual PresenceFusion ingest and getters.
2. Existing House State/Activity projection.
3. The existing manual-override expiry decision and idle-dwell suspension.
4. Existing recent-desktop-interaction predicate, against recorded source-qualified state.
5. Actual `TransitLightingService._check()`, activation, timeout, release, and rearm logic.
6. Actual `LightOverrideManager` application and release.
7. For release: the ordinary **Working/day static composition**, followed by actual `LightApplicator` protection/dedup logic.
8. Recording light adapter and simulated acknowledgement-driven state changes.

Relevant Activity arbitration is intentionally narrow: **preserve explicit Working when no fresh replacement exists**. This is not a replay of every `report_activity()` branch.

A fresh semantic report that could change accepted Activity, a period change, restart, or unsupported lifecycle transition makes this profile unsupported. Do not swallow such events.

### Stop

Stop at:

- The final per-light `set_light(light_id, payload)` request after the applicable existing guards.
- A recording adapter’s explicitly simulated result.
- Resulting owner-map, dedup-cache, and navigation-state changes.

Do not simulate optical output, camera feedback, human response, or Hue firmware.

The timeout release must produce real recomposed requests through the included Working path. Merely logging “reapply Working” would leave the selected cycle incomplete.

### Excluded composition participants

No production bootstrap, camera service, camera watchdog, desktop agents, raw ML, Sonos, Game Day, scene activation, effect execution, ScreenSync renderer, notifications, shutdown, host lifecycle executor, scheduler service, database logger, learner training, or HTTP application.

DeskExit need not run because the selected capture is daytime and its activation period gate excludes that interval. Its initial ownership must nevertheless be explicitly known absent.

## 4. Current code authority map

| Current authority | Observed behavior | Recommended seam |
|---|---|---|
| [presence_fusion.py](../../backend/services/presence_fusion.py), `PresenceReading`, `on_observation()`, `latest_zone()`, `is_strongly_present_any()` | Source-qualified readings; freshness; out-of-order handling; desk and reacquisition history | Inject clock; explicit versioned checkpoint codec |
| [automation_engine.py](../../backend/services/automation_engine.py), `current_mode`, `house_state`, `activity`, `effective_mode` | House State remains a projection over legacy mode/hold fields | Extract shared side-effect-free projection functions; preserve property facades |
| Same file, `_has_fresh_mode_replacement()`, `_override_is_user_owned()`, manual-expiry block in `run_loop()` | Explicit override survives expiry without fresh semantic replacement; override suspends idle dwell | Extract one shared expiry evaluator with explicit `now`; production applies its result as today |
| Same file, `is_recent_desktop_interaction()` | Navigation attendance veto consumes process observation age and idle time | Extract predicate taking evidence and `now`; do not substitute Sleeping wake rules |
| [transit_lighting_service.py](../../backend/services/transit_lighting_service.py), `_check()`, `_navigation_states()`, `_activate()`, `_deactivate()` | Two-second polling; arming latch; stationary/sticky gates; ten-second absence dwell; 600-second timeout; 45-second cooldown | Inject clock; preserve state machine and predicate order |
| [light_override_manager.py](../../backend/services/light_override_manager.py) | Direct navigation writes; suppression; kitchen manual-pair protection; successful-write ownership; release/reapply | Existing dependency injection largely sufficient; inject clock and trace sink |
| [light_applicator.py](../../backend/services/light_applicator.py) | Normal-mode protection, dedup, parallel requests, acknowledgement-based cache | Existing getters/fake adapter; clock for freshness; structured trace hook |
| `lighting_transition_boundary.py` | Async lock and task-local ownership; delegates settle to adapter | Retain serialization; recording adapter supplies any supported settle behavior |
| `light_state_calculator.py` | Mostly pure lighting calculations; some default wall-clock reads | Supply explicit time/period; share the existing Working composition order |
| `living_room_context.py` | Typed evidence, reason codes, snapshots, semantic fingerprint, recorder | Reuse vocabulary; do not import its ORM recorder into replay |
| `backend/api/routes/camera.py`, `bootstrap.py` | Current ingress/callback wiring, including additional downstream notifications | Capture boundary provenance; never execute these modules as offline bootstrap |

**Important implementation facts**

- `TransitLightingService._activate()` marks the service active after calling the manager, even if that manager suppressed the request or obtained no successful writes.
- `LightOverrideManager` advances transit ownership and cache only for results equal to `True`.
- Direct transit writes do **not** pass through `LightApplicator.protected_light_ids()`.
- The inspected direct manager path checks external-off suppression and kitchen-pair manual ownership; it does not contain the normal applicator’s complete protection union.
- Transit lacks DeskExit’s explicit `_presence_authority_ready()` gate.

Replay must reveal these distinctions. Adding guards or correcting policy is separate work, not a replay extraction change.

Existing useful regression anchors include:

- `tests/test_presence_fusion.py`
- `tests/test_transit_lighting_service.py::TestRefireCooldown`
- `TestActivateGuards.test_initial_continuous_absence_never_activates`
- `TestStickyDeskGate`
- `tests/test_automation_engine.py::TestDesktopUnavailableLightingPolicy`
- The engine tests for kitchen manual-pair protection, override-aware restoration, and protected-light union.
- `tests/test_effect_transition_boundary.py`

## 5. Incident bundle schema

Use a directory of **plain JSON/JSONL**, never pickle, executable configuration, or serialized service objects:

```text
manifest.json
initial.json
inputs.jsonl
expected.json
```

Proposed schema identifier: `homehub.incident.navigation.v1`.

| Component | Required contents |
|---|---|
| Identity | Schema version, profile version, bundle ID, capture provenance, completeness status |
| Integrity | SHA-256 for each exact member; canonical manifest digest excluding its own digest; reject duplicate members, traversal, unexpected files |
| Original implementation | Backend commit/build, source-agent build where known, dirty/unknown status, dependency/Python/tzdata identity |
| Configuration/policy | Allowlisted consumed values, source of each value, relevant policy/constants digest; no `.env` dump |
| Window | UTC start/end, original timezone `America/Indiana/Indianapolis`, checkpoint cut, inclusive/exclusive boundary convention |
| Sessions | Backend boot/session; logical source and source session; pseudonymous stable device identity |
| Time | Backend monotonic origin, wall-time anchor, clock-domain identity and any observed adjustments |
| Initial state | Explicit checkpoint described below, pending evaluation schedule, in-flight status |
| Inputs | Normalized evidence, camera/cache changes, invalidations, evaluation ticks, relevant adapter completions |
| Expected | Provenance-backed historical assertions, separately labeled product assertions and simulated expectations |
| Gaps | Field/event IDs, missing interval, reason, affected decisions, completeness consequences |

Each input envelope should contain:

```text
event_id, kind, source_id, source_session_id
source_sequence: known(value) | unknown(reason)
captured_at_original: known(value) | unknown(reason)
captured_at_normalized
received_at_utc, received_mono_ns
backend_dispatch_sequence
clock_domain, normalization_provenance
payload, evidence_refs
```

Source sequence may be unknown for legacy producers. **Backend consumption order may not be unknown** where it affects the selected replay.

### Evidence semantics

Keep distinct fields for:

- Detection: `present | absent | unknown`.
- Authority: `accepted | abstain`, with provenance/reason.
- Health: healthy/degraded/unavailable/disabled/unknown.
- Freshness inputs: timestamps and configured thresholds.
- Localization: known zone, explicit no localization, or unknown.
- Semantic activity: **reported observation versus accepted semantic evidence**.

`face_present=null` is not `false`; an unavailable source is not an absent person.

Capture the full allowlisted `PresenceReading` fields. Capture the camera status fields actually read by Transit, including `enabled`, `last_detection`, `detection_source`, `confidence`, `zone`, `posture`, and authority readiness. Camera lux requires `enabled`, paused state, EMA, baseline, and last-update time.

### Must capture versus derive

**Capture:**

- All initial state that cannot be reconstructed from the bounded inputs.
- Every consumed observation and evaluation opportunity.
- Relevant owner maps and target values.
- Actual acknowledgement/failure timing if claiming historical acknowledgement fidelity.
- Configuration and cached environmental inputs consumed by Working restoration.

**Derive:**

- Freshness age, effective House State/Activity, winning physical zone.
- Dwell elapsed, eligibility, brightness targets, protected sets.
- Output requests and post-result internal state.

Do not feed recorded derived decisions back into the replay as authority.

Use explicit field wrappers such as `known`, `unknown`, and `not_consumed`; plain omitted/null fields cannot distinguish “known empty” from “never captured.”

A hash proves bundle integrity, **not historical truth**.

## 6. Deterministic clock/scheduler design

### Audit result

| Participant | Current timing/concurrency |
|---|---|
| PresenceFusion | Multiple UTC `datetime.now()` calls |
| Transit | Local-zone `datetime.now()`; two-second `asyncio.sleep()` loop; poll-count streak |
| Override manager | Local wall timestamps for stamps/deadlines; `asyncio.gather()` |
| Applicator | Wall freshness fallback; lock; `asyncio.gather()` |
| Relevant engine paths | Wall time; 60-second loop; other excluded branches create delayed tasks and use randomness |
| Calculator | Explicit-time helpers plus wall-clock defaults |
| Transition boundary | Async lock, task-local ownership, adapter settle delegation |

No `time.time()`, monotonic clock, or randomness was found in the selected fusion/transit/manager/applicator implementation paths. Engine scene drift uses randomness and is outside the profile.

### Small interface

Proposed interfaces:

```text
Clock.utc_now() -> aware UTC datetime
Clock.monotonic_ns() -> integer

Scheduler.schedule(deadline_mono_ns, participant, continuation) -> handle
Scheduler.cancel(handle)
Scheduler.run_until(end_mono_ns)
```

The production clock delegates to current system behavior. Production loops keep their cadence and exception behavior. Offline replay drives shared tick functions without real sleeping.

**Do not migrate existing wall-time predicates to monotonic arithmetic in this work.** Current dwell/deadline behavior is wall-based; replacing its semantics would violate zero-behavior-change. Monotonic time orders execution; virtual wall time supplies existing comparisons.

### Ordering rules

- Deliver observations by recorded **receipt/consumption order**, not capture time.
- Order queue entries by monotonic deadline and stable enqueue sequence.
- Record actual ordering between ingress, polls, and completions that share a timestamp.
- Same-time continuations append deterministically; do not run recursively with unspecified order.
- Preserve per-request dispatch and completion identities across `gather()`.
- Sets may be canonically sorted for trace serialization, but never reorder production decisions merely to make output neat.

Duplicates remain distinct deliveries unless production already deduplicates them. Equal `captured_at` values currently can replace a reading; preserve that behavior.

Late observations pass through actual fusion logic. Older captures are normally rejected; the stored-future-reading recovery path must remain intact.

For future-dated evidence, preserve both original and normalized timestamps. Replay starts after ingress normalization. Do not add a stronger rejection policy inside the replay.

### Freshness and dwell

Time advances even during observation silence. Run all recorded evaluation opportunities.

Freshness usually expires **lazily on read**. Do not invent expiry callbacks where production only notices stale state on a later tick.

Preserve exact comparisons:

- Fusion strong presence: eight-second window.
- Default zone freshness: 300 seconds.
- Desk sticky: 15 seconds.
- Transit absence: ten seconds.
- Transit return sustain: two seconds.
- Timeout: 600 seconds.
- Cooldown: 45 seconds.
- Stationary bypass: five actual polls, not ten seconds substituted for the counter.
- Manual expiry currently uses `>`; transit deadline pruning uses `<=`.

For baseline/candidate runs, hold recorded external evaluation opportunities fixed; candidate internal timers use the deterministic scheduler. State clearly that this compares decisions under the recorded opportunity schedule, not hypothetical CPU scheduling.

**V1 is single boot.** A restart requires a new checkpoint/segment. Crossing a boot without one is incomplete; never transfer monotonic deadlines between boots.

## 7. Initial/pre-window state matrix

All field names below are current unless marked proposed.

| Participant/state | Current population | Bundle requirement / recomputation |
|---|---|---|
| Fusion `_readings`, including insertion order | `on_observation()` | Capture latest readings; recompute only from complete history reaching the checkpoint |
| Fusion `_last_at_desk_at`, `_last_at_desk_source` | Positive desk high-water mark; invalidation | Must capture: latest negative reading cannot reconstruct prior desk confirmation |
| Fusion `_last_global_absence_observed_at`, `_last_strong_reacquisition_at/source` | Explicit negative and reacquisition edges | Capture; startup silence is not equivalent |
| Engine `_current_mode`, `_mode_source`, `_mode_source_key`, `_last_mode_source_report_at` | Accepted activity and source reporting | Capture; stale logs are insufficient |
| Engine `_last_process_observation_by_device`, `_last_process_semantic_by_device` | Separate report/acceptance paths | Capture relevant entries, including age and source; known-empty is valid |
| Engine `_manual_override`, `_override_mode/source/time`, `_override_expiry_deferred`, `_override_timeout_hours` | Explicit/autonomous selection and expiry processing | Capture exact source and start time; do not infer user ownership from mode alone |
| Engine `_idle_entered_at` | Activity changes and override maintenance | Capture; derived only with complete prior transition history |
| Engine `_away_hold`, `_host_return_hold`, `_external_off_detected`, `_home_awake_confirmed`, `_enabled` | Lifecycle, external-light checks, explicit wake | Required checkpoint facts; no “Home by default” |
| Engine `_dnd` | DND manager state | Capture active-until/source state and evaluation result; first profile requires known inactive |
| Transit `_enabled`, `_active`, `_presence_armed` | Constructor and state machine | Capture, never infer from presence level or write rows |
| Transit `_camera_absent_since`, `_presence_during_absent_since`, `_camera_present_since` | Poll transitions | Capture dwell/streak origins |
| Transit `_strong_absent_streak`, `_last_block_reason` | Poll count and block transitions | Capture; block reason affects timer reset behavior |
| Transit `_transit_start`, `_last_deactivated_at`, `_owned_lights` | Activation/deactivation | Capture; service-owned lights are not identical to acknowledged owner-map entries |
| `EngineState.manual_light_overrides`, `manual_light_targets` | Manual marks/clear/expiry | Capture relevant stamps and targets, even if not durably persisted |
| `EngineState.transit_light_overrides`, `transit_light_targets` | Successful navigation writes, prune/clear | Capture deadlines and targets; distinguish other navigation producers |
| `EngineState.last_applied_per_light` | Successful writes, invalidation | Capture for exact restoration/dedup; it is an acknowledged request cache, not current physical truth |
| Engine `_scene_overrides`, `_active_scene_override_key`, effect manager state, external-owner advertisements | Scene/effect/owner lifecycle | Capture relevant ownership; first profile requires explicit absence |
| ScreenSync ownership | Source-qualified fresh owner state | Capture explicit inactive/not-owning attestation; active owner makes this profile unsupported |
| Working composition context | Schedule, brightness, learner overlay, weather, physical context | Capture raw allowlisted consumed values and their provenance; recompute composition |
| Camera/status/lux | Held camera service state | Capture exact consumer view and changes; do not construct CameraService |
| Hue connection/cached light observations | Adapter reads/cache | Capture only consumed fields; include full relevant light set for an all-off decision |
| Scheduler/transition boundary | Task execution and lock state | Start at a quiescent cut with known next evaluations; reject unknown in-flight writes |

For Working restoration, any applicable calculator state—such as lux dead-band state—must be included if the extracted path reads it. A manifest test should enumerate and guard these reads.

Missing required fields produce `INCOMPLETE_INITIAL_STATE`. An optional forensic inspection may continue with tainted/uncertain conclusions, but it cannot earn a deterministic-reproduction pass.

This is an **offline checkpoint**, not a proposal to persist the whole engine in production.

## 8. Trace/forensics schema and stable reason codes

Use one deterministic JSONL trace with:

```text
trace_version, run_id, record_id
virtual_utc, mono_ns, dispatch_sequence
participant, kind, cause_ids, evidence_ids
state_before_digest, relevant_state_delta
decision, reason_codes, gates
request_id, owner, light_ids, payload
result, certainty
```

Required record kinds:

| Kind | Meaning |
|---|---|
| `FACT` | Bundle observation, checkpoint fact, invalidation, or recorded external result |
| `DERIVED_DECISION` | Fusion selection, House State projection, expiry decision, timeout |
| `PROPOSAL` | Navigation target before guards |
| `SUPPRESSION` | Evaluated gate prevents or bounds a proposal |
| `REQUEST` | Final adapter-bound payload |
| `SIMULATED_RESULT` | Fake acknowledgement/failure and resulting internal state |

Every gate should distinguish `passed`, `blocked`, `not_evaluated`, and `unknown`. A gate absent from current code must not appear as “passed.”

Preserve existing reason values where supplied. `living_room_context.py` already uses codes such as `latitude_unavailable` and `sleeping_active`; reuse their meanings where applicable, without claiming that its shadow evaluator ran.

Transit mostly has human-readable log reasons rather than structured stable codes. Add proposed trace-only mappings:

| Current reason | Proposed code |
|---|---|
| `camera disabled` | `navigation.camera_disabled` |
| `refire cooldown` | `navigation.refire_cooldown` |
| `recent desktop interaction` | `navigation.recent_desktop_interaction` |
| `awaiting fresh presence before exit` | `navigation.awaiting_presence_edge` |
| `hard timeout` | `navigation.hard_timeout` |
| Kitchen pair skipped for manual stamp | `lighting.manual_kitchen_pair` |
| Away/external-off skipped | `lighting.external_off_suppressed` |
| No fresh semantic replacement | `activity.override_expiry_deferred` |

These are **new schema identifiers**, not existing code constants.

The trace must be able to show:

> Navigation proposed L1/L3/L4; manager suppressed the write; zero requests were emitted; Transit nevertheless became internally active.

That is materially different from “lights activated.”

Do not reuse `LivingRoomDecisionRecorder.semantic_fingerprint()` wholesale: it intentionally omits timing and some numeric evidence that replay needs. Store no chain-of-thought.

## 9. Offline composition root + no-actuation proof

Proposed entry point:

`backend/replay/navigation_v1.py`

It constructs only:

- Validated immutable bundle reader.
- Virtual clock/scheduler.
- PresenceFusion.
- Shared narrow Activity/lifecycle evaluators.
- TransitLightingService.
- Shared Working composition helper.
- EngineState, LightOverrideManager, LightApplicator.
- LightingTransitionBoundary with a recording adapter.
- In-memory trace/event/settings substitutes.

**It must not import `AutomationEngine` wholesale.** That module imports configuration and broad collaborators, and its methods reach database/persistence/bootstrap-adjacent paths.

Production delegates the extracted decisions to shared modules; the offline root calls the same functions. Do not copy their logic into a separate replay policy.

A specific import seam is necessary: Transit currently imports `FACE_TRUST_THRESHOLD` from `camera_service.py`. Move the constant to a passive constants module and re-export it from CameraService, preserving the value and compatibility.

### Structural controls

Use two complementary boundaries:

1. **Closed artifact/import graph:** package only allowlisted decision modules and fake sinks. No live adapter modules, production configuration loader, database module, routes, bootstrap, or dynamic plugin loader.
2. **Enforced execution sandbox:** no network, no device access, no subprocess/exec, no production filesystem mounts; immutable input/code mounts; output through a preopened result stream.

A supported runner must fail closed if these restrictions cannot be established. A normal unrestricted Python process with monkeypatches is not the promised safety boundary.

The root accepts bundle bytes/path through a constrained launcher, not arbitrary service objects or caller-supplied factories. Adapter types are closed; a request to configure “real Hue” fails validation.

### Proof tests

- Forbidden-import dependency test over the complete packaged closure.
- Attempted Hue/Sonos/Kasa/projector/notifier/shutdown wiring fails before construction.
- Runtime attempts at socket creation/connect, subprocess/exec, device open, production database/settings writes are denied.
- Malicious bundle paths, pickle payloads, dynamic imports, and executable configuration are rejected.
- Every request terminates at the recording sink.
- Failure, cancellation, exception, and release paths remain contained.
- No production `.env`, credentials, database, or home-directory state is available.

Python tripwires are useful test evidence, but the sandbox supplies the operational prohibition.

## 10. Counterfactual modes and semantic diff

Expose three explicit modes:

1. **Historical reproduction:** recorded build/config/dependencies, where available and safely runnable in the offline artifact. A compatibility extraction must have equivalence evidence. Otherwise report historical reproduction unavailable.
2. **Current-code interpretation:** old facts through the current supported decision profile. Never label this “what happened.”
3. **FIXED-EVIDENCE COUNTERFACTUAL:** immutable inputs/checkpoint/evaluation opportunities through baseline and candidate implementations/configurations.

Compare:

- Ordered decision transitions and their virtual times.
- Decisive evidence IDs, authority, freshness and reasons.
- Owner acquisition/release and deadlines.
- Suppression and gate-evaluation differences.
- Per-light requested payloads, transition times, dedup and failure outcomes.
- Resulting simulated state.

Align by causal input/tick identity, participant, and semantic transition—not raw trace row number. Display inserted/deleted decisions explicitly.

Example meaningful comparison:

> Baseline permits another transit request after timeout and cooldown without fresh presence; candidate retains the consumed-presence latch and emits no second request.

Until backed by a real bundle, that remains a **synthetic contract test**, not historical proof.

Keep fake-response policy identical across baseline/candidate. Recorded acknowledgements can be reused only for matching requests under an explicit matching rule; novel requests need labeled synthetic responses or stop with outcome unknown.

Different lights could have changed lux, camera detection, or human behavior. Fixed-evidence comparison cannot infer those downstream changes, energy savings, physical comfort, or future user satisfaction.

## 11. Evidence exporter

An exporter is needed.

Existing event logging records transitions and successful adjustments, with bounded retry/drop behavior. It does not preserve all normalized inputs and suppressed decisions. The living-room recorder persists semantic changes/checkpoints, not every timing-relevant observation.

### Smallest capture mechanism

Add an **opt-in bounded in-memory recorder** around the selected participant boundaries:

- Normalized fusion ingest and invalidation.
- Camera/status/lux updates consumed by navigation.
- Relevant engine authority/checkpoint changes.
- Navigation/authority tick start and ordering.
- Navigation and restoration requests/results.
- Ownership/cache transitions.

Start with a quiescent checkpoint before the window. If a write is in flight, wait for a safe capture cut without blocking policy, or mark the capture unsupported. Do not take an inconsistent sequential snapshot while callbacks mutate state.

Bound capture by duration and size—for example, **15 minutes and 16 MiB** initially. Overflow or dropped records explicitly invalidates completeness; never silently overwrite the checkpoint’s required continuation.

Export only allowlisted normalized fields. No raw images/audio/screen content, process command lines, window titles, media URLs, credentials, or unrestricted settings/database dumps.

The exporter observes existing traffic and in-memory state. It must not request a camera snapshot, trigger devices, force modes, or actuate a reproduction.

Existing database rows may be attached as bounded supporting evidence, with provenance and completeness limitations. They cannot fill missing source observations by inference.

Implementing/enabling capture is future authorized work; this architecture pass does not enable it.

## 12. Implementation slices with model assignments

Proposed filenames below are new, not claims that these modules exist.

| Slice | Goal and likely files/symbols | Dependencies | Tests / done-when | Worker / escalation |
|---|---|---|---|---|
| 1. Consumption manifest | `docs/replay/NAVIGATION_V1.md`; enumerate current fields, time reads, imports, output paths | Accepted design | Every included read/write has a source and scope rule | **Luna Low**; escalate unknown causal dependency |
| 2. Bundle contract | `backend/replay/schema.py`, `validate.py`; `IncidentBundleV1`, profile validator | 1 | Reject missing state, invalid ordering, bad hashes, unsupported owner/boot transitions; fixture-only reader complete | **Terra Low**; escalate schema requiring unrelated subsystems |
| 3. Clock and passive imports | `services/decision_clock.py`; fusion/transit/manager/applicator clock injection; passive camera threshold | 1 | Existing-time equivalence; boundary comparisons; no camera/config import from replay closure | **Terra Medium**; escalate changed clock semantics or callback timing |
| 4. Narrow engine extraction | `services/navigation_activity_policy.py`, `working_light_composition.py`; delegate existing projection/expiry/input predicates and Working composition | 1, 3 | Old-versus-delegated decision/state/payload equivalence; existing engine regressions | **Terra Medium**; escalate need for full engine, live services, or new authority |
| 5. Scheduler and checkpoints | `backend/replay/clock.py`, `scheduler.py`, `checkpoints.py` | 2–4 | Same-time ordering, late/duplicate evidence, missing ticks, cancellation, mixed acknowledgements, checkpoint continuation | **Terra High**; escalate unresolved production interleaving |
| 6. Offline root and containment | `backend/replay/navigation_v1.py`, `sinks.py`; isolated runner definition | 2–5 | Forbidden imports/I/O/wiring tests; all branches terminate offline | **Terra High**; escalate inability to enforce sandbox |
| 7. Trace and contract replay | `backend/replay/trace.py`; `tests/test_replay_navigation.py` | 5–6 | Explain expiry, dwell, timeout, no-refire, suppression, failure/cache distinction; synthetic fixtures labeled | **Terra Medium**; escalate unexplained divergence or product conflict |
| 8. Bounded capture/export | `services/navigation_incident_capture.py`; narrow hooks at mapped boundaries | 2, 7 | Coherent checkpoint; bounded memory; explicit drops; privacy allowlist; no extra device calls | **Terra Medium**; **Terra High** only if coherent capture needs concurrency redesign |
| 9. Real fixture and diff | `tests/fixtures/replay/navigation/`; `backend/replay/diff.py` | Real capture, 7–8 | Evidence-backed golden assertions; deterministic reruns; intelligible baseline/candidate diff | **Terra Medium**; escalate insufficient evidence instead of inventing data |
| 10. Accepted handoff docs | #240/EXECUTION_MAP updates and usage documentation | Accepted results | Accurate readiness and residual gates | **Luna Low**; escalate conflicting acceptance decisions |

No implementation slice currently requires Astra. Use **Sol Medium** only if a newly exposed product-authority conflict cannot be resolved from current contracts; Sol High is unnecessary for the settled replay mechanics.

## 13. Zero-behavior-change landing order

1. Land the manifest, schema, validator, and synthetic fixtures.
2. Introduce optional clock dependencies with system-clock defaults.
3. Remove passive-constant imports through live services.
4. Extract the narrow engine decisions; retain all existing method/property facades.
5. Extract Working composition without changing its transformation order.
6. Add trace sinks with a no-op production default.
7. Build the offline root and scheduler.
8. Prove structural containment and behavioral equivalence.
9. Add the bounded recorder.
10. Obtain a real capture, then add historical/current interpretation and diff assertions.

Compatibility requirements:

- Preserve production polling cadence, await boundaries, short-circuit order, and comparison operators.
- Preserve acknowledgement-only cache/ownership updates.
- Preserve override-aware restoration and kitchen-pair behavior.
- Preserve current House State projection; do not implement Winding Down.
- Keep production persistence and lifecycle loading outside offline constructors.
- Do not change unknown-evidence handling or repair guard gaps within extraction commits.
- Do not replace the engine, create an event bus, unify ownership systems, or refactor unrelated modes.

Clock injection must not accidentally collapse multiple current time reads into one timestamp unless equivalence is established. A timing cleanup is a behavioral change, even if aesthetically preferable.

## 14. Acceptance criteria

V1 is complete only when all applicable criteria pass:

1. **Determinism:** identical bundle/build/config/fake-response policy produces byte-identical canonical semantic traces over repeated runs and different hash seeds.
2. **Explicit gaps:** missing required checkpoint/input/order produces an incomplete result; no empty-map/Home/healthy defaults substitute for missing evidence.
3. **Time fidelity:** boundary tests cover freshness, sticky windows, dwell, poll counters, timeout, cooldown, wall adjustments, late arrivals, duplicates, and future-stamp recovery.
4. **Authority fidelity:** explicit Working survives stale semantic replacement; reported versus accepted activity remains distinct; software evidence never manufactures physical room.
5. **Ownership fidelity:** requests, suppressed proposals, service-active state, successful owner claims, dedup, and failures remain distinguishable.
6. **Restoration fidelity:** timeout release runs the shared Working composition and normal protected-light application, not a handcrafted replay approximation.
7. **Structural no-actuation:** the closed artifact and enforced sandbox prohibit live adapter construction and network/subprocess/device/production-write operations.
8. **Counterfactual value:** one bounded candidate change produces a causally aligned decision/output diff under identical evidence.
9. **Extraction parity:** relevant existing regressions plus old/delegated equivalence checks show zero production behavior change.
10. **Real evidence:** either one honestly evidence-backed real fixture passes, or the implementation remains explicitly **EVIDENCE_GATED** pending first capture. Synthetic tests do not satisfy this criterion.
11. **Scope fidelity:** ScreenSync, DeskExit corridor, audio, Game Day, raw inference, recovery, UI, and automatic fixes remain excluded.
12. **Policy honesty:** existing implementation/product discrepancies are surfaced separately; deterministic reproduction is not certified policy correctness.

## 15. Risks / unresolved questions

- **Historical loss:** July’s missing inputs/checkpoint may be unrecoverable. No architecture can reconstruct them from output counts.
- **First-capture availability:** the narrow Working/day profile may require waiting for a suitable natural interval. Expand only after evidence demonstrates a need.
- **Current guard discrepancies:** Transit lacks DeskExit’s explicit unknown-authority gate, and direct navigation writes have a narrower guard set than normal mode application. Record these as code findings; no live consequence was verified here.
- **Historical build feasibility:** source SHA alone may not recover dependencies, effective configuration, or runtime initialization.
- **Capture consistency:** initial snapshots must align with consumed event order and acknowledgements. This is the main concurrency risk.
- **Working restoration extraction:** learned overlays/weather/context must remain in the original order. If sharing this branch requires importing the full engine, the extraction is not yet sufficiently narrow.
- **No-actuation enforcement:** Windows development convenience must not weaken the isolated runner’s guarantee. Unsupported execution environments should refuse execution.
- **Ownership semantics:** service `_active` and `_owned_lights` are not proof of successful writes. Preserve that distinction throughout assertions.
- **Product versus reproduction:** an old build may reproduce behavior that violates today’s product contract. Label it as historical behavior, never current authority.

None of these requires a new whole-home architecture. Evidence insufficiency remains a capture gate, not permission to fabricate a fixture.

## 16. Recommended updates to #240 / EXECUTION_MAP after acceptance

Do not make these updates until this design is accepted:

- Replace the open incident-selection question with the **July desktop-inactive repeated-transit candidate** and an explicit evidence-gated first capture.
- Record the supported profile: **daytime retained Working, desktop unavailable, one boot, Transit navigation, static Working restoration**.
- State explicitly that **ScreenSync and DeskExit corridor are excluded from v1**.
- Separate **implementation readiness** from **real-fixture readiness**.
- Add the narrow shared extraction, clock/scheduler, containment, and exporter slices with the model assignments above.
- Replace any implied promise of recovered historical reproduction with: historical reproduction only where original evidence/build/config are sufficient.
- Record the direct-navigation versus normal-applicator guard distinction as a separate correctness-review item.
- Keep the original no-actuation and fixed-evidence limits prominent.
- Preserve July’s incident report as historical evidence; do not rewrite it to imply a replay bundle exists.

**Recommended status after acceptance: architecture resolved for the bounded profile; implementation ready; first real fixture evidence-gated.**
