# Navigation v1 consumption, state, clock, and side-effect manifest

Status: Slice 1 implementation manifest for accepted #240 architecture. This
is an inventory of current code, not a new policy or a historical replay claim.
It is scoped to the evidence-gated profile:

`daytime + retained explicit Working + desktop sensing unavailable + one
backend boot/session + Transit navigation + normal Working/day restoration
through LightApplicator + no active scene/effect/ScreenSync owner`.

The supported path is:

`normalized source-qualified observations -> PresenceFusion -> narrow
House-State/Activity projection -> TransitLightingService ->
LightOverrideManager -> recording adapter result -> Working/day restoration
through LightApplicator`.

ScreenSync, DeskExit evening/corridor, Sonos, Game Day, raw inference,
dashboard replay, whole-home simulation, bootstrap, HTTP application, database
logging, host lifecycle, and recovery are out of scope. A first real fixture is
not available: the profile is implementation-ready but evidence-gated.

## 1. Participant inventory

| Participant / exact symbol | Current path and consumption | Boundary |
|---|---|---|
| `PresenceReading`, `PresenceFusion` | `backend/services/presence_fusion.py`; `on_observation()`, `latest_zone()`, `is_strongly_present_any()`, desk/absence/reacquisition getters | Include actual fusion ingest/getters and checkpoint state; do not construct `CameraService`. |
| `AutomationEngine` narrow projection | `backend/services/automation_engine.py`; `current_mode`, `house_state`, `activity`, `effective_mode`, `_has_fresh_mode_replacement()`, `_override_is_user_owned()`, manual-expiry path in `run_loop()`, `is_recent_desktop_interaction()` | Extract/delegate only retained Working, House State/Activity, expiry, idle-dwell suspension, and restoration inputs. Do not import the whole engine into replay. |
| `EngineState` | `backend/services/engine_state.py`; shared per-light dedup cache plus manual/transit stamps and held targets | Capture only the five per-light fields listed in Section 2; lifecycle/activity state remains owned by `AutomationEngine`. |
| `TransitLightingService` | `backend/services/transit_lighting_service.py`; `_check()`, `_navigation_states()`, `_activate()`, `_deactivate()`, `poll_loop()` | Actual daytime navigation branch, including arming, absence dwell, return sustain, timeout and cooldown. |
| `LightOverrideManager` | `backend/services/light_override_manager.py`; transit apply/clear, ownership, suppression, manual kitchen-pair protection, acknowledgement cache | Direct navigation path, with its narrower guards preserved. |
| `LightApplicator` | `backend/services/light_applicator.py`; normal Working/day apply, `protected_light_ids()` and dedup/ack cache | Restoration only; preserve parallel request and result semantics. |
| `LightingTransitionBoundary` | `backend/services/lighting_transition_boundary.py`; serialized lock, task-local ownership, settle delegation | Capture only quiescent ownership/in-flight state and deterministic ordering. |
| Pure lighting helpers | `backend/services/light_state_calculator.py` and the existing Working composition helpers in `automation_engine.py` | Reuse exact transformation order; provide explicit period/time where helpers default to wall time. |
| Ingress normalization/provenance | Desktop: `backend/api/routes/camera.py:post_observation()` uses `backend/api/_guards.py:clamp_client_timestamp()` before `PresenceFusion.on_observation()`; Latitude: `backend/bootstrap.py` wires the in-process CameraService observation callback directly to fusion | Capture at the resulting normalized `PresenceReading` boundary with source/session and backend receipt/dispatch order. Never replay route/bootstrap/CameraService inference. |
| Recording adapter | Proposed replay fake sink at the final adapter boundary | Records requests and supplies explicitly labeled simulated acknowledgements/failures; never reaches Hue/network/device. |

### Existing test anchors

The current anchors are `tests/test_presence_fusion.py`; `tests/test_transit_lighting_service.py::TestRefireCooldown`, `TestActivateGuards.test_initial_continuous_absence_never_activates`, and `TestStickyDeskGate`; `tests/test_automation_engine.py::TestDesktopUnavailableLightingPolicy`; the engine tests `test_apply_skips_kitchen_pair_when_l4_manual`, `test_apply_skips_kitchen_pair_when_l3_manual`, `test_apply_proceeds_when_neither_kitchen_manual`, `test_expired_user_override_waits_for_fresh_replacement`, `test_protection_unions_manual_transit_sync`, and `test_prune_expired_pops_dedup_cache`; `tests/test_lighting_ownership_regressions.py`; and `tests/test_effect_transition_boundary.py`.

## 2. Consumption/state manifest

`MUST_CAPTURE` means required in the bundle/checkpoint or event stream;
`DERIVE` means recomputed by shared current code from complete captured facts;
`NOT_CONSUMED` means outside this profile and must not be silently defaulted.
Unknown is a value, not absence. Missing required state makes the bundle
`INCOMPLETE_INITIAL_STATE`.

| Field / state | Owner / population path | Read | Class | Initial/pre-window requirement | Missing/unknown, timing, and effect |
|---|---|---|---|---|---|
| `PresenceReading` fields: `source`, `captured_at`, `face_present`, `face_confidence`, `detection_source`, `zone`, `posture`, `posture_confidence`, `pose_visible_landmarks` | `backend/services/presence_fusion.py:PresenceReading`; populated before `PresenceFusion.on_observation()` | Every ingest and fusion query | MUST_CAPTURE | Exact latest per-source reading at checkpoint plus every later normalized reading, source/session identity, receipt/dispatch order and normalization provenance | `None` is abstention/unknown, not absence. Freshness and accepted physical authority are derived by current fusion code. |
| Fusion `_readings`, including dict insertion order | `PresenceFusion.on_observation()` / `invalidate_source()` | `latest_zone()`, `is_strongly_present_any()`, `seconds_since_at_desk()` and related getters | MUST_CAPTURE | Capture the exact latest per-source map at the checkpoint. It may be recomputed instead only from a complete pre-window history reaching that checkpoint. | Do not demand or invent unretained pre-window history when a checkpoint is available. Equal-timestamp/tie behavior must preserve source-map order. |
| Fusion `_last_at_desk_at`, `_last_at_desk_source` | Positive desk high-water mark in `on_observation()`; cleared by source invalidation when applicable | `seconds_since_at_desk()` and desk-sticky/fixture-comfort consumers | MUST_CAPTURE | Exact value or known-empty | A later negative frame cannot reconstruct a prior Desk confirmation. |
| Fusion `_last_global_absence_observed_at`, `_last_strong_reacquisition_at`, `_last_strong_reacquisition_source` | Explicit negative/reacquisition edge bookkeeping in `on_observation()` | Fusion internal state and `is_strong_presence_reacquisition()` | MUST_CAPTURE | Exact values or known-empty | Startup silence is not an absence edge. These preserve exact fusion state; they are **not** a substitute for Transit’s separate `_presence_armed` latch. |
| Winning zone, strong-presence result, desk recency and freshness ages | `PresenceFusion` getters | Transit `_check()` and Working fixture/zone composition | DERIVE | Complete fusion checkpoint + events + virtual wall time | Preserve current 8 s strong-presence and 300 s default-zone freshness semantics and the 15 s Transit desk-sticky threshold. |
| Engine `_current_mode`, `_mode_source`, `_mode_source_key`, `_last_mode_source_report_at` | `AutomationEngine` accepted Activity/source reporting | House State/Activity projection, expiry evaluation and restoration mode | MUST_CAPTURE | Retained `Working` must be explicit and source-qualified | Missing is unsupported; never default Home/Working. A fresh semantic report that could change accepted Activity makes this bounded profile unsupported. |
| Engine `_last_process_observation_by_device`, `_last_process_semantic_by_device` | Raw report and accepted-semantic paths | `is_recent_desktop_interaction()` and narrow authority diagnostics | MUST_CAPTURE | Relevant entries, including known-empty, timestamps and source/device provenance | “Desktop unavailable” must be an attested missing/stale source condition, not fabricated physical absence. |
| Engine `_manual_override`, `_override_mode`, `_override_source`, `_override_time`, `_override_expiry_deferred`, `_override_timeout_hours` | `AutomationEngine` override lifecycle | Retained-Working expiry decision and effective restoration mode | MUST_CAPTURE | Exact source, owner class, start time and deferred state | Explicit user Working survives expiry without a fresh semantic replacement; preserve current strict `>` timeout comparison. |
| Engine `_idle_entered_at` | Activity transitions / override maintenance | Manual-expiry idle-dwell suspension | MUST_CAPTURE | Exact timestamp or known-empty | Derive only from complete prior transition history. |
| Engine `_away_hold`, `_host_return_hold`, `_external_off_detected`, `_home_awake_confirmed`, `_enabled` | Lifecycle/external-off/wake state | Projection and write/reapply gates | MUST_CAPTURE | Explicit values plus provenance where available | Unknown lifecycle state blocks certified replay; never substitute Home/healthy. |
| Engine `_dnd` evaluated state (`is_dnd_active()`, active-until/source data needed to reproduce it) | `DndManager` owned by `AutomationEngine` | Profile eligibility / checkpoint contract | MUST_CAPTURE | First profile requires known inactive DND | Do not infer inactive from omission. |
| Transit `_enabled`, `_active`, `_presence_armed` | `TransitLightingService.__init__()` and `_check()` | Every Transit tick | MUST_CAPTURE | Exact values | `_presence_armed` is the actual fresh-present edge latch; it cannot be inferred from current presence level alone. |
| Transit `_camera_absent_since`, `_presence_during_absent_since`, `_camera_present_since` | `TransitLightingService._check()` / `_record_block()` | Absence dwell, flap suppression and active-return dwell | MUST_CAPTURE | Exact timestamps or known-empty | Preserve 10 s absence dwell and 2 s sustained-return semantics; block transitions can clear timers. |
| Transit `_strong_absent_streak`, `_last_block_reason` | Per-poll strong-presence accounting / `_record_block()` | Stationary-zone bypass and timer-reset/log transition behavior | MUST_CAPTURE | Exact integer/reason or known-empty | `BED_EXIT_ABSENT_FRAMES=5` is five observed polls, not a substituted elapsed duration. `_last_block_reason` matters because a reason transition triggers timer clearing. |
| Transit `_transit_start`, `_last_deactivated_at`, `_owned_lights` | `_activate()` / `_deactivate()` | Hard timeout, cooldown and scoped release | MUST_CAPTURE | Exact values | Service-owned lights are not proof of acknowledged writes; preserve this distinction from `EngineState.transit_light_overrides`. |
| Transit camera view: `get_status().enabled`, `last_detection`, `detection_source`, `confidence`, `zone`, `posture` | Held `CameraService` status, read by Transit | Every `_check()` | MUST_CAPTURE | Exact consumer view at each relevant tick/change | **Current behavior has no explicit authority-readiness gate in Transit.** With `enabled=true`, unknown/weak detection can behave as “not strongly present” and advance absence/streak logic. Replay must reproduce that behavior, not silently make unknown block activation. |
| Transit lux view used by `_navigation_states()`: camera `enabled`, `_paused`, `ema_lux`, `last_lux_update`, `baseline_lux` | `AutomationEngine._read_fresh_camera_lux()` | On Transit activation target calculation | MUST_CAPTURE | Exact values/timestamps or explicit unavailable state | Freshness is derived with current `LUX_STALE_SECONDS`; unavailable/stale lux falls back to the current fixed navigation values. |
| Transit mode/period/target calculation | `current_mode`, local wall hour, `_navigation_states()`, `path_light_brightness()`, code constants | Each tick/activation | DERIVE | Capture wall time and dynamic lux inputs; code/build identity supplies constants | Daytime Working must remain outside evening/late-night DeskExit yield behavior. |
| `EngineState.manual_light_overrides`, `manual_light_targets` | `LightOverrideManager.mark_manual()/clear/expire` | Direct navigation kitchen-pair guard and normal restoration protected set | MUST_CAPTURE | Relevant stamps and authoritative held targets, including known-empty | Manual ownership can suppress the kitchen pair; do not reconstruct from bridge state. |
| `EngineState.transit_light_overrides`, `transit_light_targets` | Successful navigation writes, prune/clear | Normal restoration protected set and scoped release | MUST_CAPTURE | Deadlines/targets with producer provenance | These advance only for acknowledged `True` writes. Distinguish Transit from any other producer sharing the map. |
| `EngineState.last_applied_per_light` | Successful normal/direct writes and explicit invalidation | Direct write before-values, dedup and timeout restoration | MUST_CAPTURE | Exact relevant per-light cache | This is an acknowledged-request cache, not current physical Hue truth. |
| Scene/effect/external-owner state: `_scene_overrides["working"]["day"]`, `_active_scene_override_key`, effect-manager active/desired ownership, `_external_light_owners` advertisements | `AutomationEngine` / `EffectManager` | Working restoration branch selection and protection | MUST_CAPTURE | Supported profile requires explicit “no active/selected scene or effect; no external owner” attestation | Active/selected ownership makes this v1 profile unsupported rather than being silently disabled. |
| ScreenSync ownership/object state needed to prove no fresh owner | `AutomationEngine._screen_sync` / `LightApplicator.protected_light_ids()` | Restoration protected-light calculation | MUST_CAPTURE | Explicit inactive/not-owning attestation | ScreenSync behavior itself is REPLAY_EXCLUDED. If fresh ownership exists, this profile is unsupported. |
| Hue/recording-adapter availability and per-request result policy | Direct manager and applicator adapter dependency | Request/success/failure handling | MUST_CAPTURE | Explicit connected/available input and result policy; no real adapter | Direct manager returns without ownership if adapter missing/disconnected. Applicator cache advances only on `True` results. |
| Transition-boundary ownership and pending adapter completions | `LightingTransitionBoundary` | Before direct/reapply writes | MUST_CAPTURE | Quiescent cut: boundary unheld by another task, no unknown in-flight write, known next evaluations | Unknown in-flight work makes the checkpoint incomplete. |
| Routes/bootstrap, raw CameraService inference, raw images/audio/screen, DeskExit evening/corridor, Sonos, Game Day, dashboard, recovery | Excluded modules | Never executed by replay root | NOT_CONSUMED | Their **absence/ownership preconditions** are captured separately where required above | Do not import or default these systems into v1. |

### Working/day restoration: exact consumed inputs

Timeout/deactivation restoration calls `LightOverrideManager.clear_transit_override()`, which removes only the selected transit stamps/targets, forgets their dedup entries, reads the override-aware current mode, and calls the engine’s reapply path. For the accepted `Working/day` profile, the later shared extraction must preserve the following current inputs and order without importing the whole engine:

| Current step | Exact consumed state/input | Slice 1 class |
|---|---|---|
| `AutomationEngine._now()` + `_get_time_period(now)` | local wall time; `_schedule_config`; cached weather `sunset` when available | MUST_CAPTURE dynamic values; period DERIVE |
| Desired effect/profile gate | `EffectManager.get_desired_effect("working","day")`; current effect state | MUST_CAPTURE enough weather/effect state to prove desired/current effect is none for the supported profile |
| Scene gate | `_scene_overrides.get("working", {}).get("day")` | MUST_CAPTURE; must be absent for supported profile |
| Base palette | `_get_mode_state_table("working", _current_game)` then `_resolve_activity_state("working","day", _current_game)` | DERIVE from code/build; `_current_game` is captured/known non-relevant for Working |
| Learner overlay | presence/absence of `_lighting_learner`; resolved `current_weather_class`; `_current_zone_posture()`; returned `get_overlay("working","day", weather, zone)` payload | MUST_CAPTURE resolved consumed inputs/overlay result and provenance; do not replay learner training/DB |
| Mode brightness | `_mode_brightness["working"]` | MUST_CAPTURE |
| Lux multiplier call | `_last_lux_multiplier`, `_last_weather_class` plus camera/weather reads made by the wrapper | MUST_CAPTURE the two hysteresis fields for exact internal-state continuity. Output state is currently unchanged because `LUX_MODES=frozenset(("relax",))`; Transit lux is still independently consumed for navigation targets. |
| Functional weather brightness | `_get_current_weather_condition()`; `lighting_learner.has_weather_pref("working","day", condition)` result | MUST_CAPTURE resolved condition and learned-light set; transformation DERIVE |
| Gaming-day surround helper | Called by the common pipeline but `mode!="gaming"` makes it a pure no-op | NOT_CONSUMED for output; do not widen v1 into Gaming |
| Zone/posture overlay | `_current_zone_posture()`; `_bed_reclined_l1_night` only if the current pure Working branch can consume it | MUST_CAPTURE physical zone/posture provenance; transformation DERIVE |
| Weather adjustment | `_get_current_weather_condition()` | MUST_CAPTURE resolved condition/provenance; transformation DERIVE |
| Fixture comfort | `_fixture_comfort_zone()`, which consumes current fused zone and `seconds_since_at_desk()` | DERIVE from captured fusion state/time |
| Post-sunset warmth | current `period` | DERIVE; daytime is normally a no-op but the helper/order remains shared |
| ScreenSync prime | Current engine may call `prime_from_mode_state()`, but ScreenSync is excluded from replay and must be explicitly non-owning | NOT_CONSUMED by v1 output; preserve production-equivalence tests around the extracted composition |
| Final write | mode-default `MODE_TRANSITION_TIME["working"]`, `LightApplicator.apply_state()`, protected sets and dedup cache | transition constant DERIVE; owner/cache/result inputs MUST_CAPTURE |

This table is the consumption contract for Slice 4’s narrow Working-composition extraction. It is not permission to snapshot all settings, weather state, learner history, or the whole `AutomationEngine`.


### Important current differences to expose

`TransitLightingService._activate()` sets internal `_active` after calling the
manager even when the manager suppresses the proposal or gets zero successful
writes. `LightOverrideManager` advances ownership/cache only for results equal
to `True`. Direct Transit writes do not use
`LightApplicator.protected_light_ids()`; they have external-off and kitchen-pair
guards but not the applicator's complete protection union. Transit also lacks
DeskExit's explicit `_presence_authority_ready()` gate. These are recorded
behavior differences, not fixes or new replay guards.

## 3. Clock and async manifest

| Reached source | Current semantics | Later seam from accepted design | Slice 1 |
|---|---|---|---|
| `PresenceFusion` UTC `datetime.now(timezone.utc)` calls | Freshness, out-of-order/future-stamp replacement, reacquisition and high-water age decisions; separate calls may observe different wall times | Inject `Clock.utc_now()` at the selected participant without changing comparison semantics | Capture observation timestamps and evaluation opportunities; record the dependency, do not implement the seam here. |
| Transit local `datetime.now(tz=TZ)` in `_check()`, `_navigation_states()`, `_activate()`, `_deactivate()` | Absence/return dwell, hard timeout, cooldown, daytime/evening/late-night target choice and service timestamps | Shared virtual wall clock/local conversion | Capture every Transit evaluation tick and its wall time. |
| Transit `asyncio.sleep(POLL_INTERVAL_SECONDS)` in `poll_loop()` | Creates two-second evaluation opportunities; poll count also drives `_strong_absent_streak` | Deterministic scheduler drives `_check()` opportunities; production loop remains unchanged | Capture tick opportunity/order, not merely elapsed duration. |
| `AutomationEngine._now()`, `_get_time_period(now)` and narrow expiry/input predicates | Retained-Working expiry, House State/Activity projection, schedule/day period and recent-desktop age | Inject explicit `now` into extracted narrow evaluators; keep production defaults | Capture engine evaluation ticks, schedule inputs, source report times and wall time. |
| `AutomationEngine._read_fresh_camera_lux()` UTC wall read | Transit target lux freshness; common Working pipeline also invokes it even though Working is outside `LUX_MODES` | Explicit wall time for freshness | Capture `last_lux_update` and tick time. |
| `LightOverrideManager.apply_transit_override()` / `prune_expired_transit()` wall time | Transit ownership deadline and restoration-time expiry pruning | Inject clock into manager in Slice 3 | Capture deadline-producing time and restoration evaluation time. |
| `LightOverrideManager` and `LightApplicator` `asyncio.gather()` | Per-light requests are dispatched together; success/failure identity controls owner/cache mutation | Recording adapter + deterministic completion records | Capture request identity and completion/result ordering; do not collapse to one aggregate success. |
| `LightingTransitionBoundary.serialized()` | Async lock + task-local ownership serializes direct and restoration writes | Keep an in-memory deterministic serialization primitive | Checkpoint must be quiescent or have known ownership. **`wait_for_settle()` is not reached in the accepted no-scene/no-effect Working/day path.** |
| LightApplicator legacy ScreenSync freshness fallback | May call UTC wall time only when an older ScreenSync shape lacks `fresh_owned_light_ids()` | None in v1; ScreenSync is excluded and explicitly non-owning | REPLAY_EXCLUDED for the supported profile; do not create a ScreenSync clock dependency. |
| HueService `time.monotonic()` transition bookkeeping | Lives below the selected adapter boundary after a real Hue write | Recording adapter result policy replaces it | REPLAY_EXCLUDED; the replay stops before Hue firmware/transition tracking. |
| Scene drift/randomness and unrelated delayed tasks | Outside the supported Working/day restoration path | None | NOT_CONSUMED. |

No selected **policy** decision uses `time.time()` or monotonic time today.
The replay scheduler may use virtual monotonic time for deterministic ordering, but
must keep existing wall-time comparisons intact. Do not collapse separate current
wall reads into one timestamp unless an equivalence test proves that change is
behavior-neutral.

## 4. Side effects and output boundaries

| Boundary | Classification | Manifest rule |
|---|---|---|
| `LightOverrideManager.apply_transit_override()` -> Hue `set_light` | RECORDING_SINK_REQUIRED | Record final per-light payload, transition time, request identity, external-off/manual-pair suppression, simulated result and completion order. Never construct real Hue. |
| `LightOverrideManager.clear_transit_override()` -> override-map mutation + `reapply_mode(effective_mode)` | PURE/IN_MEMORY plus downstream recording writes | Record exactly which stamps/targets/dedup entries are cleared before the Working reapply. |
| `LightApplicator.apply_state()` / per-light dispatch -> Hue `set_light` | RECORDING_SINK_REQUIRED | Record protected set, dedup decision, request/result identity and acknowledgement-backed cache mutation. |
| `EventLogger.log_light_adjustment()` from direct Transit successes and Applicator successes | RECORDING_SINK_REQUIRED | Replace with an in-memory event/trace sink; preserve trigger/mode and before/after fields without opening production SQLite. |
| `ml_logger.log_decision()` for a non-empty Working learner overlay | RECORDING_SINK_REQUIRED if that branch occurs | Record the derived learner-delta event in memory; do not construct the production ML logger/database. |
| `LightingTransitionBoundary.serialized()` | PURE/IN_MEMORY | Retain ordering/ownership semantics. No physical settle wait is needed in this profile. |
| Transit heartbeat `HeartbeatRegistry.tick("transit_lighting")` | REPLAY_EXCLUDED | Replay drives recorded evaluation opportunities, not the production poll-loop health side effect. |
| ScreenSync `clear_accepted_gaming_state()`, `prime_from_mode_state()`, `invalidate_sent_state()` | REPLAY_EXCLUDED | The profile requires explicit no-fresh-ownership. Slice 4 equivalence tests must prove excluding these non-authoritative side effects does not change v1 light requests. |
| Scene activation, effect release/start, Hue v2, Sonos, Game Day, notifications, shutdown, host lifecycle, routes/bootstrap, production settings/database writes, subprocess/network/device access | REPLAY_EXCLUDED | Any attempted construction/reachability is a containment failure; active scene/effect/external ownership makes the bundle unsupported before replay. |
| PresenceFusion, policy/calculator functions, EngineState and Transit state transitions | PURE/IN_MEMORY | Trace state deltas and reason/gate outcomes; no external side effects. |

The stop boundary is the final adapter-bound request, its explicitly supplied
recording-adapter result, and the resulting in-memory owner/cache/navigation
state. No optical output, camera feedback, human response, Hue transition
tracking, or other device behavior is simulated.


## 5. Ordering and checkpoint manifest

* Replay ingress begins **after timestamp normalization**, at the normalized,
  source-qualified observation/callback boundary. Each envelope retains original
  timestamp, normalized timestamp, receipt UTC/monotonic time, source/session,
  provenance, and backend dispatch sequence.
* Deliver by recorded backend receipt/consumption order, not capture time.
  Equal-time queue entries use stable enqueue order. Duplicates remain distinct
  unless current code deduplicates them. Late and future-dated observations go
  through the real fusion behavior.
* Capture every fusion ingest/invalidation, engine/navigation evaluation tick,
  two-second Transit poll opportunity, timeout/cooldown/deadline opportunity,
  restoration evaluation, adapter request, and adapter completion. Silence does
  not stop virtual time; expiry is lazy where production reads it lazily.
* A request is ordered as proposal -> manager/applicator guards -> final request
  or suppression -> adapter acknowledgement/failure -> ownership/cache update.
  `asyncio.gather()` request identities and completion order remain explicit.
* The initial cut must be quiescent: one boot/session, no in-flight adapter or
  callback mutation, known transition-boundary ownership, known pending ticks,
  explicit retained Working/House State/lifecycle fields, fusion high-water
  marks, Transit state, relevant light observations/cache, and explicit absence
  of scene/effect/ScreenSync/DeskExit owners.
* Missing required state, unknown consumption order, dropped/overflowed capture,
  a write in flight at the cut, unsupported activity/lifecycle/period change,
  boot/restart without a new checkpoint, active excluded owner, or unbounded
  adapter/bootstrap import makes the bundle unsupported/incomplete. Never
  substitute empty maps, Home, healthy, or inactive defaults.
* V1 is one backend boot/session. Monotonic deadlines never cross a restart;
  a restart requires a new checkpoint/segment.

## 6. Traceability

### Manifest row to code path

| Row | Exact current path/symbol |
|---|---|
| Fusion readings/high-water | `backend/services/presence_fusion.py:PresenceReading`; `PresenceFusion.on_observation()`, `invalidate_source()`, `latest_zone()`, `latest_posture()`, `is_strongly_present_any()`, `seconds_since_at_desk()` |
| Desktop ingress normalization | `backend/api/routes/camera.py:post_observation()`; `backend/api/_guards.py:clamp_client_timestamp()`; replay begins at the resulting `PresenceReading`, not in the route |
| Latitude ingress provenance | `backend/bootstrap.py` registration of `camera_service.register_observation_callback(presence.on_observation)`; capture normalized `PresenceReading` at the fusion boundary, do not run `CameraService` |
| Narrow authority/expiry | `backend/services/automation_engine.py:AutomationEngine.current_mode`, `house_state`, `activity`, `effective_mode`, `_has_fresh_mode_replacement()`, `_override_is_user_owned()`, `is_recent_desktop_interaction()`, and the manual-expiry block in `run_loop()` |
| Transit state/output | `backend/services/transit_lighting_service.py:TransitLightingService._check()`, `_record_block()`, `_record_unblock()`, `_navigation_states()`, `_activate()`, `_deactivate()`, `poll_loop()` |
| Direct ownership/apply | `backend/services/light_override_manager.py:LightOverrideManager.apply_transit_override()`, `clear_transit_override()`, `prune_expired_transit()`, `forget_dedup_light()` |
| Restoration | `backend/services/automation_engine.py:AutomationEngine._apply_mode()` selected Working/day branch -> `backend/services/light_applicator.py:LightApplicator.apply_state()`, `protected_light_ids()`, `_apply_per_light_locked()` |
| Shared per-light state | `backend/services/engine_state.py:EngineState` five fields listed in Section 2 |
| Serialization | `backend/services/lighting_transition_boundary.py:LightingTransitionBoundary.serialized()`; physical settle is below/outside this v1 path |
| Working/day composition | `backend/services/light_state_calculator.py` plus the exact wrappers listed in Section 2's Working/day table |

### Manifest row to tests

| Concern | Existing tests |
|---|---|
| Fusion ordering/high-water/freshness | `tests/test_presence_fusion.py::test_future_stamped_reading_replaced_by_honest_report`, `test_future_stamped_high_water_mark_heals`, `test_genuine_out_of_order_still_dropped`, `test_latitude_zone_desk_is_at_desk`, `test_both_sources_stale_means_not_at_desk` |
| Transit dwell/guards/rearm | `tests/test_transit_lighting_service.py::TestActivateGuards.test_initial_continuous_absence_never_activates`, `TestStickyDeskGate`, `TestRefireCooldown`, `test_deactivate_stamps_cooldown`, `test_cooldown_blocks_immediate_refire`, `test_fresh_presence_rearms_after_cooldown` |
| Working/desktop unavailable | `tests/test_automation_engine.py::TestDesktopUnavailableLightingPolicy`; `test_expired_user_override_waits_for_fresh_replacement`; `test_apply_skips_kitchen_pair_when_l4_manual`; `test_apply_skips_kitchen_pair_when_l3_manual`; `test_protection_unions_manual_transit_sync`; `test_prune_expired_pops_dedup_cache` |
| Recent desktop predicate | `tests/test_lighting_ownership_regressions.py::test_recent_desktop_interaction_requires_fresh_low_idle_evidence`, `test_recent_desktop_interaction_ignores_other_devices` |
| Transition ordering | `tests/test_effect_transition_boundary.py` |
| Lux inputs | `tests/test_camera_lux_ema.py::test_update_ema_lux_initializes_on_first_call`, `test_update_ema_lux_blends_when_recent`, `test_update_ema_lux_resets_when_stale` |

### Accepted architecture statement to coverage

| Accepted statement | Manifest coverage |
|---|---|
| Daytime retained Working, desktop unavailable, one boot | Profile header; Section 2 engine/camera rows; Section 5 boot/session rule |
| Transit only; DeskExit evening/corridor and ScreenSync excluded | Participant inventory; Section 2 NOT_CONSUMED/profile-precondition rows; Section 4 side-effect table |
| Restoration must use normal Working/day path | Section 2 Working/day restoration table; Section 6 restoration symbols |
| Capture versus derive must remain distinct | Section 2 classification contract and every consumption row's Class |
| Wall time remains policy time; monotonic only orders replay | Section 3 clock/async table |
| Internal Transit active is not successful actuation | Section 2 current-differences note; Section 4 request/result boundary |
| Direct navigation and normal applicator guards differ | Section 2 ownership rows/current-differences note; Section 4 separate output boundaries |
| Missing checkpoint/order is incomplete | Section 2 missing-state contract; Section 5 unsupported/incomplete rules |
| No-actuation offline root | Section 4 recording sinks/exclusions; production adapters are outside the v1 closure |
| First real fixture remains evidence-gated | Status/profile header; no historical fixture is claimed |

## 7. Slice 1 conclusion and escalation

No unresolved causal dependency currently requires architecture escalation. The
remaining implementation risk is the accepted capture-consistency gate:
checkpointing must align mutable callbacks, evaluation opportunities, and
adapter acknowledgements at a quiescent cut. If that cannot be established
without importing the full engine/bootstrap or changing production interleaving,
escalate before Slice 2 rather than inventing state. Otherwise Slice 1 is ready
for Terra Low Slice 2.
