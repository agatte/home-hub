# #370 diffuse fill - local integration resume point

## Independent P2 twilight correction (2026-11-05; local, uncommitted)

**Result: corrected and verified offline, NOT published or physically accepted.**
The independent read-only Codex review task `e3a940873c2c45d5b769537ae956d08f`
completed (exit 0) and identified one P2 defect in the 16-file receipt
candidate: in `AutomationEngine._compose_desk_camera_fill`, the
manual-Activity no-dimming check ran **before** General's twilight interpolation.
General's lux-adjusted interpolation starting point can be below the authored
L2 brightness, so the twilight stage reintroduced a dimming command despite
the earlier clamp. The reviewer reproduced an L2 `136 -> 122` example
without changing source files.

A real `desk_fill_rig` regression in `tests/test_screen_sync_route.py`
then proved the defect before correction: manual General L2 authored at
`bri=200`, fresh calibrated bedroom lux, valid physical Desk/Activity
receipt, and twilight progress `0.0/0.5/1.0` yielded **160/180/200**
respectively (**2 failures, 1 pass**). No light hardware was operated.
The narrow fix moves the *existing* manual L2 no-dimming clamp to after
the twilight interpolation, ensuring the comfort overlay cannot lower its
**input L2 state** or change L5. General's pre-existing baseline lux
composition is unchanged; the fix is specifically for the additional
physical/lux comfort overlay. There is no new Hue writer or broader manual
fixture authority.

**Verification:** new focused regression **3 passed** (previously 2 failed);
full affected **14-suite total 1,505 passed** in 130.13s (previously
1,502 before this correction); Ruff on all 15 modified Python files
**passed**; `git diff --check` **passed**. Tests include
physical Hue owner/final-write, manual Activity, continuous Gaming frames,
LuxChannel publication/expiry, camera correctness, transition and the
historical 28,224-row simulation. Its `pipeline_subset=8064` and
`owner_dispatch=20160` gaps remain *historical simulation coverage labels*,
not physical room acceptance. Prior independent reviewer found no further
source, deadlock, stale replay, cross-room or ownership blockers in the
inspected paths, but the review predates this narrow relocation; tests confirm
the new code. This was direct scoped editing/testing, not another Codex
Write task. The worktree still has 16 intentionally modified, uncommitted files
on `work/370-general-sunset-comfort-20261105` at base `0badf883`.

**Release gates remain:** independent integration/PR review and green CI
once commit/push are separately authorized; separately authorized deployment
using `scripts/deploy.sh`; real-room sunset/night/late-night L2 usefulness,
colored Gaming comfort, L5 glare, lux update cadence and manual/unknown-zone
behavior must be observed before #370 physical acceptance. No deployment,
restart, credential, production database or Hue/monitor/device writes occurred.

## Latest per-light receipt completion (2026-11-05; local, uncommitted)

**A/B/C implemented and exercised offline; physical acceptance and release remain
open.** This section supersedes the scope-blocked/manual/Gaming/lux-at-acceptance
gaps in the historical sections below. The supplied task explicitly authorized
existing boundary modules. No scope clarification remains outstanding. Work is
only in `C:/Work/home-hub-project/worktrees/desk-370-diffuse-fill-20261105`, branch
`work/370-general-sunset-comfort-20261105`, HEAD
`0badf883a66ce119e10769768237ed91e37f6bd6`; the original seven modified files
are preserved. GitHub issue/master freshness was not checked: network fetches
were prohibited. This is local implementation evidence, not published issue or
production state. No second Sandbox worker was launched.

### Lux publication and final acceptance

`LuxChannel` now serializes publication, calibration and reads with an RLock.
Each accepted sample and every baseline recalibration advances a monotonic
publication generation (including identical values); rejected invalid or
out-of-order samples neither refresh freshness nor publish a generation. Legacy
properties, EMA, stale reset, naive timestamp normalization and future-stamp
recovery remain compatible. `snapshot(room, max_age_s)` returns a frozen room,
generation, finite nonnegative EMA, finite positive baseline, capture timestamp,
maximum age and original monotonic deadline. Wrong-room, future, expired and
uncalibrated snapshots abstain. Lux cannot supply physical presence.

`DeskAcceptanceGuard.with_lux` derives a separate L2 guard with that exact channel
identity, frozen lux snapshot and original per-light intent lease. Final commit
checks the original physical publications/generations, Activity epoch, authority
lease/owner generation, channel identity, lux generation/calibration and both
wall-clock age and original monotonic expiry. Recalibration away and back cannot
resurrect a plan. Lock order is **PresenceFusion physical gate, then LuxChannel
lock**; both release before bridge IO. The immutable acceptance receipt is the
outbound linearization point; later source loss cannot retract a command already
accepted there. Ownership/dedup publication revalidates separately after ACK.

### Manual Activity and independent fixtures

`_capture_mode_physical_validator` still returns None in manual Activity. A
separate physical capture supplies only the incremental L2 receipt, scoped to
the current mode apply through `mode_light_receipts`. It requires Home/awake,
enabled, fresh qualified desktop face at Desk, no strong contrary physical
presence, matching Activity epoch, real fresh calibrated bedroom lux and no
stronger L2 owner. Missing permission retains the existing conservative manual
composition (including Watching's 70/50 fallback). The new manual correction
only adds brightness; it cannot dim an authored target or turn Off into On.

LightApplicator attaches the lux receipt only to L2, validates it at dedup and
in the real Hue worker, and leaves L1/L3/L4/L5 normal manual writes independent.
A regression exposed the old apartment-wide worker preflight snapshot vetoing
unrelated fixtures on an L2 takeover. Static writes now carry their original
immutable per-light intent lease through preflight; global policy changes still
revoke all relevant work. Same-light takeover/release ABA still revokes L2.
No whole-mode manual physical fence, manual toggle or additional Hue writer was
introduced. Original automatic whole-mode physical behavior remains intact.

### Continuous generic Gaming

Desktop generic Gaming frames keep the accepted canonical game-composed target,
then compute a detached bounded L2 brightness increment from the frame's frozen
bedroom lux snapshot and physical receipt. Hue/saturation or CT stay canonical;
RGB never selects Gaming colors or brightness. This uses the existing leased
frame, final Hue acceptance and post-ACK ownership path. Dedup ownership also
requires an atomic physical/lux receipt. Frame identity, age, original source
expiry, Activity/game and stronger owners are checked again. The canonical cache
never stores the source-only increment; missing lux or physical Desk falls back
to the canonical target, and loss while pending rejects that L2 command. The
previous skipped/unaccepted-target cache fix remains in place.

Frame comfort preserves the thirty-minute sunset easing and nighttime floor
handoffs, never dims a brighter authored target, and does not touch L5. Named
games (including Rust/League), Game Day and scenes do not enter this increment.
No sampled-RGB Gaming contract, scene authority or second writer was added.

### Verification and review

- Focused five-suite run: **835 passed in 112.58s**, exit 0 (LuxChannel,
  ScreenSync route, automation engine, physical Hue worker, owner dispatch).
- First complete fourteen-suite run: **1,500 passed in 151.36s**, exit 0.
  Review then added an explicit brighter warm-CT/HSB Gaming no-dimming clamp,
  widened the named-game exclusion to CT too, and two regression cases.
- Focused final no-dimming/input gate check: **14 passed, 164 deselected in
  13.06s**, exit 0.
- Final complete fourteen-suite run: **1,502 passed in 138.67s**, exit 0,
  covering the final production code and the two added no-dimming regressions.
- The continuous-frame fixture was then strengthened from fake transport to the
  actual HueService memory worker (no production change): **1 passed, 177
  deselected in 12.16s**, exit 0. This separately verifies repeated ACK/dedup,
  source-loss baseline restoration and recalibration through real worker leases.
- Ruff passes all fifteen changed Python files. The existing AST owner fixture
  needed the new receipt context; ten pre-existing E701 one-line statements in
  that touched test were expanded without changing behavior. `git diff --check`
  passes. No tests remain intentionally RED.

The fourteen suites are `test_automation_engine.py`,
`test_light_state_calculator.py`, `test_lux_multiplier.py`, `test_lux_channel.py`,
`test_camera_lux_ema.py`, `test_desk_diffuse_fill.py`, `test_screen_sync_route.py`,
`test_hue_worker_physical_owner.py`, `test_desk_v2_effect_acceptance.py`,
`test_desk_owner_dispatch.py`, `test_screen_sync_multi.py`,
`test_lighting_final_write_authority.py`, `test_lighting_ownership_regressions.py`
and `test_desk_comfort_simulation.py`, all under `tests/`. Commands use
`C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m pytest -q
-p no:cacheprovider` (with `--tb=short` for concise failure output).

New deterministic memory-Hue tests pause the actual worker after composition,
then publish source loss/ABA, identical-value lux updates, calibration ABA,
lux expiry, manual Activity ABA, L2 owner takeover/release or explicit Off.
They prove only extra L2 fails for source/lux/per-light loss while normal manual
L1/L3/L4/L5 and the kitchen pair continue. Separate thread-publication races
change lux after the final on-loop validation and before the primitive receipt.
Bridge callbacks assert neither source nor lux lock is held. Existing physical
expiry/conflict/ACK tests continue to pass. All seven manual Activities also run
through the actual engine/applicator and memory Hue pipeline; independent target
values remain normal (Gaming's initial versus repeated apply can legitimately
use different existing transition times).

Continuous black/white/chromatic Gaming frames preserve canonical HSB and L5,
recompute brightness from recalibrated lux, dedup safely, and revert to the
canonical baseline on source loss. Input gates cover missing, uncalibrated,
wrong-room, future/stale lux, contrary presence, DND, scene, transit, manual
per-light, Sleeping and explicit Off. Earlier sunset/handoff, owner release,
ScreenSync white/dark/chromatic and fixture-cap regressions remain included.
Initial RED runs identified missing scoped/AST fixture dependencies, overly
broad worker snapshots and an assertion comparing Gaming transition cadence;
those were corrected and are superseded by the final full run.

### Exact file scope and remaining gates

Production edits: `backend/services/automation_engine.py`,
`light_state_calculator.py`, `lux_channel.py`, `lighting_authority.py`,
`lighting_transition_boundary.py`, `light_applicator.py`, `screen_sync.py`, plus
`backend/api/routes/automation.py`. Tests: the existing
`tests/test_automation_engine.py`, `test_light_state_calculator.py`,
`test_lux_multiplier.py`, `test_lux_channel.py`, `test_screen_sync_route.py`,
`test_hue_worker_physical_owner.py` and `test_desk_owner_dispatch.py`. This audit
is the sixteenth changed file. Bootstrap and configuration are unchanged.

The historical simulation still reports 8,064 pipeline-subset and 20,160
owner-dispatch gaps in 28,224 rows; this pass adds concrete integration proofs,
not a claim that its entire historical matrix is closed. Sensor publication
churn deliberately rejects pending receipts rather than adopting a newer source;
subsequent normal composition/frames may try again. Candidate Hue floors and
127/37 bedroom samples are synthetic calibration inputs, not measured lux or
perceived-brightness proof. Physical L2 room fill, colored-light adequacy, L5
glare, monitor contrast and update cadence still require room acceptance under
#370/#244/#136. No current device/Latitude health is asserted.

Next gate is review of this uncommitted candidate and separately authorized
physical acceptance/integration. No commit, push, merge, deploy, service/task
restart, device/monitor write, installation/download, credential action, Host
Bridge mutation, other-worktree edit or cleanup occurred. No permission question
is pending; the authorized local implementation and verification are complete.

## Latest bounded safety pass (2026-11-05; supersedes readiness claims below)

**PARTIAL / NOT RELEASE READY. A (continuous Gaming frame comfort) and B
(manual Activity per-light physical comfort acceptance) remain BLOCKED.**
This pass preserves the existing seven-file candidate on
`work/370-general-sunset-comfort-20261105` at `0badf883`. Only the engine,
its existing test suite and this audit received additional edits. No network
fetch or current GitHub verification was performed; the supplied issue context
and local source are the evidence boundary. No new worker was launched.

### Implemented: do not publish skipped Gaming fixtures

The preceding candidate treated `LightApplyResult(failed=set(), skipped=...)`
as permission to publish every composed target. That was unsafe: L2 could be
protected during the static apply, yet releasing its owner later exposed an
unaccepted L2 plan to generic Gaming frames. Publication now includes only
`successful | deduplicated`, excluding `skipped`. The detached cache is replaced,
so an older game's target for that skipped fixture disappears too. Other accepted
fixtures remain independent. An absent target makes frame replay abstain until
a subsequent accepted static apply establishes it. This deliberately favors
abstention when ScreenSync itself caused a static skip; no cached target is
adopted merely because a stronger owner released it.

The existing camera-only Gaming increment is still removed before publication.
Generic Gaming remains canonical HSB/CT replay with exact accepted colors, not
RGB conversion. No new frame brightness floor or manual Activity lift is enabled.

Six new cases cover skipped L2/L5, successful versus exact-dedup independent
fixtures, older cache replacement, black/white/colored replay, and manual/transit
L2 owner release. Two use the real `HueService`, actual engine/applicator and an
in-memory bridge: explicit Off receives no L2 command during the protected apply
or after release via frames; the next accepted static apply restores replay.
The initial memory fixture omitted the Hue transition-boundary binding and
failed two cases; binding it corrected the fixture. Focused final run: **6 passed,
596 deselected in 13.48s**. This is actual offline command evidence, not device
or perceived-brightness acceptance.

Final unchanged fourteen-suite run: **1,450 passed in 162.74s, exit 0** using
`C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m pytest -q
-p no:cacheprovider` with `tests/test_automation_engine.py`,
`test_light_state_calculator.py`, `test_lux_multiplier.py`, `test_lux_channel.py`,
`test_camera_lux_ema.py`, `test_desk_diffuse_fill.py`, `test_screen_sync_route.py`,
`test_hue_worker_physical_owner.py`, `test_desk_v2_effect_acceptance.py`,
`test_desk_owner_dispatch.py`, `test_screen_sync_multi.py`,
`test_lighting_final_write_authority.py`, `test_lighting_ownership_regressions.py`
and `test_desk_comfort_simulation.py` (all under `tests/`). An earlier broad run
had 1,448 passed / 2 failed because it collected the memory fixture before its
boundary binding was fixed; the complete final rerun supersedes that result.
Ruff passed all six modified Python files; `git diff --check` passed. The
simulation still reports 8,064 pipeline-subset and 20,160 owner-dispatch gaps
in its historical 28,224-row matrix; passing tests do not close those gates.
Existing delayed-worker and physical-source ABA tests passed; there is no new
final-acceptance proof for either requested lift, since neither was implemented.

### Remaining insertion contracts; no cached-boolean workaround

Source inspection reconfirmed these concrete boundaries:

- `screen_sync._leased_frame` can carry `physical_acceptance` through a final
  Hue receipt, but `_apply_accepted_gaming_state` has no separate canonical
  baseline / incremental comfort target contract. Its dedup path calls
  `_record_source_write`; any future comfort receipt must also validate that
  path and post-await ownership, not just an outbound write. The route currently
  captures the Desk receipt only for Watching, and explicitly checks Watching.
- `LightApplicator._write_many` captures one `mode_physical_validator` and one
  acceptance guard for the entire batch. Enabling the manual mode validator
  globally would also fence authored L1/L3/L4/L5 and scene/effect work. It still
  returns None for manual Activity. Manual Watching retains legacy 70/50 fallback;
  manual Working/Gaming do not acquire physical Desk permission from selection.
- `LuxChannel` stores mutable EMA, baseline and timestamp independently. It has
  no synchronized publication generation / immutable acceptance snapshot.
  `DeskAcceptanceGuard` freezes PresenceFusion source generations and deadlines,
  not bedroom lux publication, calibration or its 30-second expiry. Thus the
  existing static candidate checks bedroom lux at composition, **not final lux
  acceptance after an arbitrary Hue-worker delay**. That limitation also remains
  a release gate for the earlier static candidate; its prior physical-source
  tests do not prove lux-at-commit safety.

A safe continuation needs narrowly scoped changes to the existing receipt,
LuxChannel publication, frame/route contract and per-light applicator boundary,
with frozen mode/game/source identity and a lux deadline/generation checked at
final acceptance. The task lists seven candidate files and permits only expressly
allowed files/actions, while also directing work through these boundaries. Scope
clarification was requested before editing additional modules; they remain
untouched pending that answer. This is an implementation gate, not proof that
the architecture cannot support a safe receipt.
No second writer, runtime monkeypatch, temporary manual-mode toggle, mutable
cached eligibility bit or whole-mode manual physical fence was introduced.
There is consequently **no claim that both eligible paths now read and adjust
from bedroom lux**: the automatic static calculator does; the two requested
remaining lift paths remain disabled. Latitude lux never substitutes for L2.

Required next gates: review the scoped boundary extension, implement/test its
per-light immutable receipt including lux/source ABA and expiry, manual/automatic
owner crossover, dedup and acknowledgment; then independent review and physical
room/glare/cadence verification under #370/#244/#136. Sleeping, projector,
named-game, Game Day, explicit Off and L5 policy remain unchanged. No commit,
push, merge, deployment, service/task restart, live device write, installation,
credential action, Host Bridge mutation or cleanup occurred.

## Next bounded integration (2026-11-05, local only; supersedes gaps below)

Workspace `desk-370-diffuse-fill-20261105`, branch
`work/370-general-sunset-comfort-20261105`, HEAD
`0badf883a66ce119e10769768237ed91e37f6bd6`. The starting five-file
uncommitted candidate is preserved. Registry inspection confirmed task
`2f79a38362b34c0bacfaf5f16464795a` completed, exit 0, worker not alive;
it was not relaunched. No network fetch was authorized: current GitHub #370
and master were not refreshed. The supplied task constraints, local authority
and code are this task's evidence boundary. No live camera reading was taken;
127 baseline / 37 EMA bedroom and 74 / 120 Latitude are supplied inputs,
reproduced as calibrated synthetic samples, not measured lux claims.

### Static colored correction and final authority

`apply_desk_camera_fill` now accepts well-formed HSB L2 for generic Gaming,
Relax and Social. It changes brightness only; hue/saturation remain exact,
mixed CT/HSB targets abstain, and explicit Off stays Off. Colored candidate
floors are Evening/Night/Late Night **160/120/95**, with existing bedroom-only
EMA/baseline bands 1.10/1.00/0.90 and ratio deadband. New colored increments
cap at 176; brighter authored targets remain untouched. Unlike the warm CT
branch, colored targets are never scaled down in a bright room. These are
bounded tuning values, not an assertion that saturated color provides the
same useful illumination as warm white at a given Hue brightness.

The normal engine composition additionally requires a matching `mode_apply_epoch`
and the captured automatic Desktop Desk physical validator, Home/awake/enabled,
no manual Activity/DND/scene/effect/scene transition/external-off/away/host-return,
and no manual or transit L2 owner. Named Gaming profiles are excluded wholesale,
including Rust and League of Legends; no game-director or Game Day policy is
changed. Lux never locates a person. Existing final LightApplicator/Hue physical
acceptance and stronger per-light/ScreenSync ownership still decide dispatch.
L5 retains its existing glare cap and receives no new lift; surround colors and
the kitchen pair are unchanged by this floor. General's warm CT policy, sunset
30-minute ramp and both nighttime handoffs remain in place. Colored floor
handoffs use the existing shared schedule easing, without changing HSB.

### ScreenSync Gaming explicitly GATED

The premise that generic Gaming currently runs its sampled RGB through
`get_floor/get_cap` is false at this HEAD. `ScreenSyncService.apply_color`
returns immediately through `_apply_accepted_gaming_state` for Gaming, before
RGB conversion, the ambient floor, or Watching's diffuse-fill branch. It
replays the engine's accepted composed target. Existing
`test_generic_gaming_full_spectrum_samples_keep_canonical_state_and_bri` and
`test_generic_gaming_report_applies_canonical_target_states` explicitly require
that behavior. `_AMBIENT_LIFT_MODES` is not proof that Gaming uses that pipeline.
Adopting dark/white/colored RGB frames would change this established contract;
merely broadening the Watching guard or passing its boolean does not engage
the floor or a new physical receipt. No new Gaming frame floor, lux modulation,
RGB behavior or Hue writer was introduced.

A second authority gap was found during this investigation: publishing a newly
raised static Gaming target would let generic frames replay its physical-only
increment after Desk source loss. The engine therefore publishes the preceding
composed L2 brightness into Gaming's existing replay cache when a colored
camera increment raised it. The static write retains its physical fence; frame
replay retains the prior composed brightness and final fixture caps, with exact
colors and L5 unchanged. This is an intentional conservative fallback: a later
Gaming frame can restore that prior brightness, so continuous Gaming comfort is
**NOT accepted**. A follow-up must choose the Gaming frame contract and carry
its immutable source/lease/receipt through the actual replay path, including
deduplication and source ABA, before a persistent frame lift can be enabled.

### Evidence and remaining gates

- Existing suites were extended, without a new test framework. Pure tests cover
  all three colored Activities/periods, dark/neutral/bright/missing samples,
  exact HSB, brighter targets, Off and malformed/mixed targets.
- Engine tests exercise actual authored mode composition, bedroom versus
  Latitude input, stale/missing and invalid/future/wrong-room/naive samples,
  manual/per-light/transit/effect/scene ownership, named-game exclusion,
  epoch loss, physical loss and Desk/Bed/Couch/projector/unknown contexts.
- Real HueService with memory bridge and real LightApplicator tests compose
  automatic Gaming/Relax/Social with calibrated 127/37 bedroom samples, then
  pause the Hue worker, invalidate Desktop before acceptance and prove no
  command is sent. Unchanged-source controls write exact HSB and unchanged L5.
  Existing manual Watching fallback coverage is retained and expanded with
  unchanged-source controls; this does not repair its physical fence.
- Watching ScreenSync real-memory final acceptance tests now exercise black,
  white and colored reports against unchanged source, source loss and Latitude
  ABA. Gaming route tests inject even `desk_diffuse_fill=True`, with fresh or
  lost Desktop, and prove only the preceding accepted plan can be written.
  Engine-to-ScreenSync tests prove a static night lift of 132 does not escape
  into frame replay (prior L2 brightness 105). This is gating evidence, not a
  new Gaming physical receipt.
- The original **5,376-row composition matrix** remains intact; its synthetic
  predicate without an epoch does not authorize colored increments. New colored
  tests supply the matching epoch separately. The historical **28,224-row**
  matrix still has **20,160 owner_dispatch gaps**. Neither matrix proves physical
  comfort or complete cross-Activity acceptance.

**UNSOLVED:** manual Activity's physical per-light final-acceptance fence.
No manual colored increment is enabled. Manual Watching retains its legacy
fallback. Native scenes, special game profiles, ongoing generic Gaming frame
comfort, perceived warm-white versus saturated usefulness, and real-room glare/
lux/cadence acceptance remain release gates. No independent reviewer or physical
acceptance occurred. This is a local bounded static correction with explicitly
gated Gaming ScreenSync, not full cross-Activity acceptance or release readiness.

Validation checkpoint: the fourteen-suite broad run listed at the end of this
audit passed **1,438 tests in 179.22 seconds, exit 0**. A subsequent stronger
authored-composition assertion caught Social bypassing the common pipeline:
**2 failed / 19 passed**, with Social still at 120 instead of the candidate
176/132 evening/night floors. Social's existing `_apply_social_style` now calls
the same calculator before its unchanged final fixture cap/applicator. The
strengthened authored-composition and colored/Watching boundary cases then
passed **29/29 in 13.60 seconds**. Earlier effect-context failures were a test
fixture writing the wrong EffectManager field, corrected to `_active_name`;
they were not evidence of a production effect-owner bypass. The focused
calculator/engine/route/memory checks passed **126/126 in 20.25 seconds** before
the stronger assertions. After the Social production correction and final
test additions, **781 passed in 44.33 seconds, exit 0**, across
`tests/test_automation_engine.py`, `tests/test_desk_owner_dispatch.py`,
`tests/test_screen_sync_route.py`, `tests/test_lighting_final_write_authority.py`
and `tests/test_lighting_ownership_regressions.py`. All runs used
`C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m pytest -q
-p no:cacheprovider`. Ruff **0.15.10** passed on both production modules and
all four changed Python test files; `git diff --check` passed. There are no
remaining failing checks. The broad run predates the final Social correction;
the affected final run covers it and all new authored/boundary assertions.
The rest of the broad suite was unchanged. No
commit/push/merge/deploy, live Hue/monitor write, service/task restart, dependency
installation, Host Bridge mutation, credential action or destructive cleanup
was performed. The two added changed files are existing test suites
`tests/test_light_state_calculator.py` and `tests/test_screen_sync_route.py`;
all five starting files remain in the local diff.

## Independent final check (2026-11-05, local only)

Additional source-freshness bug found and fixed in the same bounded change.
`PresenceFusion.latest_zone()` can retain Desk with its 300-second default
window, long after the short `AutomationEngine._capture_mode_physical_validator`
write-evidence window expires. The previously added `not _manual_override`
condition alone allowed the *new* static 90/70 lift from such stale Desk context
without an active per-write physical validator. `AutomationEngine._apply_zone_overlay`
now requires the captured `mode_physical_validator` to exist and still validate
when composing the increased night/late-night Watching L2 target; otherwise
it keeps the previously shipped 70/50 target. The existing mode write checks
continue to verify that same physical validator at dispatch.

A 3-case regression in `tests/test_screen_sync_route.py` verifies fresh
automatic Desk = 90 at night, 15-second-old fused Desk = prior 70, and
manual Watching = prior 70; L5 remains untouched. Before the code correction,
the stale case failed **RED (90 vs expected 70)**; afterward all three
passed **GREEN**. The final unchanged ten-suite offline run after this
correction passed **718/718 tests in 106.77s, exit 0** via
`C:\Work\home-hub-project\main\.venv\Scripts\python.exe -B -m pytest -q
-p no:cacheprovider` with the ten files enumerated below. `git diff --check`
also passed (exit 0). This is offline ownership proof, not observed brightness
or authorization for real Hue actions. Manual static higher-floor acceptance
remains blocked; the ScreenSync qualified Desktop Desk improvement remains wired.

## P2 follow-up status (2026-11-05, local only)

**Safe partial candidate; the complete static increment is NOT release ready.**
P2 (1), ScreenSync final physical acceptance, is fixed locally. P2 (2), the
manual Watching static increment, is blocked and withdrawn from that path:
manual Watching retains its prior night=70 / late-night=50 L2 overlay targets.
Automatic Watching retains the candidate targets and its existing mode physical
validator. The earlier implementation/test history below predates this follow-up.

ScreenSync now passes the frozen `DeskAcceptanceGuard` from the route through
the existing leased-frame validator's `accept_command`. It freezes source
identity/generations (including Desktop and Latitude ABA), original monotonic
source deadline and future conflict deadline. Acceptance uses the exact current
frame lease under the existing source gate. Loop frame/owner checks still run;
the guard supplies a one-use atomic receipt for the real Hue worker. No new
writer, transport, smoothing, RGB/HSB, deadband or L5 policy was introduced.

The manual static blocker is precise: `_capture_mode_physical_validator()` must
still return None under manual override, and LightApplicator's existing physical
validator covers a whole mode apply. Enabling it globally would fence independent
manual scenes/effects and other fixtures. A targeted physical-only L2 increment
would need separately scoped per-light composition/acceptance. This bounded pass
uses the task-authorized fallback instead: an explicit calculator option selected
by the engine for manual applies retains the old floors without reducing brighter
targets or changing explicit Off. No claim that the manual static race has a new
physical fence is made. Restoring its 90/70 increment remains blocked on that fence
and independent verification; no full-release readiness claim is authorized.

Real HueService + memory-bridge regressions reproduce ScreenSync source loss
and Latitude ABA after final `validate_dispatch` returns True and before atomic
acceptance: **RED 2 failed / 1 unchanged-source control passed**, then **GREEN**.
The source publication uses a joined thread barrier. Manual static tests compose
with Desk present, pause the real Hue worker after loop validation, remove the
source, and inspect actual memory-bridge commands through real LightApplicator.
Re-enabling the unsafe increment reproduces **RED 2 failed** (90 vs 70 and 70 vs
50); the fallback passes both and preserves L5=14. This proves withdrawal of the
new increment, not physical fencing of the legacy static targets.

Final expanded offline validation: **715 passed in 107.59s**, using the absolute
interpreter and `-B -m pytest -q -p no:cacheprovider`, across
`test_desk_diffuse_fill.py`, `test_screen_sync_route.py`,
`test_hue_worker_physical_owner.py`, `test_desk_v2_effect_acceptance.py`,
`test_desk_owner_dispatch.py`, `test_light_state_calculator.py`,
`test_screen_sync_multi.py`, `test_lighting_final_write_authority.py`,
`test_lighting_ownership_regressions.py`, and `test_desk_comfort_simulation.py`.
ChatGPT independently reran these exact ten suites from the unchanged local
worktree: **715 passed in 115.93s; exit 0**. Git `diff --check` independently
passed with exit 0. GitHub master and issue #370 were also rechecked read-only
in the owning session; the verified remote master was the same `bfbc558f` base.
This includes the existing independent manual scene/effect cases. The historical
matrix still reports its unchanged 20,160 owner_dispatch gaps. `git diff --check`
passes. The nine starting modified/untracked files remain; the only additional
file touched is `backend/services/automation_engine.py` for the manual-only
fallback option. Branch and HEAD remain as supplied. No network, production,
device, service, Git publishing or host administration action was performed.

Uncommitted work in `C:\Work\home-hub-project\worktrees\desk-370-diffuse-fill-20261105`,
based on `bfbc558f5b978b3a07fa5017a125863dedbece11`. The bounded Watching
integration is now wired and tested offline. This is not deployment, physical
acceptance, or a reviewed cross-Activity policy. No network fetch was authorized;
the owning session later rechecked #370, #244 and GitHub master read-only. Local code and the supplied
task contract are the evidence boundary. All four starting changes were retained.

## Implemented and scope

- `backend/services/desk_visual_comfort.py`: immutable shared
  `DESK_WATCHING_FILL` evening/night/late-night values 110/90/70 Hue bri. The
  broader warm-CT `desk_diffuse_fill_candidate` remains an offline policy only;
  its 30-second/cross-Activity rules do not authorize this integration.
- `backend/services/light_state_calculator.py`: existing Watching Desk overlay
  uses those shared floors, preserving day=160, brighter targets, explicit Off,
  L5 and kitchen L3/L4. Existing caller zone/freshness/owner handling is retained;
  the new ScreenSync qualification does not replace the static caller contract.
- `backend/api/routes/automation.py`: after resolving zone and period, capture
  the immutable Desktop reading and its source generation for targeted L2.
  Require report source desktop, Watching, a supported nighttime period, Home,
  enabled, no DND, and fresh <=8-second face-present Desktop Desk evidence with
  detection_source None/face (the existing accepted Desktop provenance set).
  Require fused latest_zone(max_age_s=8)=desk. Explicitly reject a fresh strong
  Latitude Couch/Bed reading even if the newer Desktop Desk wins fusion.
  Manual Activity Watching is allowed; manual L2 is excluded. External-off,
  Away/host return, scene/scene transition and effects cannot qualify.
- The L2 final_frame_guard rechecks reading object identity, source revision
  (including both Desktop and Latitude removal/reinsert ABA), freshness,
  fused zone, conflicts, period,
  Home/awake/enabled/DND and the above owners. PresenceFusion instance replacement
  also rejects. No raised frame falls back to an unguarded retry.
  Existing @leased_frame and validate_screen_sync_lease still validate their
  current lease under the final transition boundary, protecting transit,
  external/protected owners, unknown effect authority and all normal leases.
  Lease validation must not be called before acquiring that boundary; the first
  synthetic integration run exposed that restriction and the implementation
  retains owner lease validation exclusively in the established leased writer.
- `backend/services/screen_sync.py`: a literal True flag can raise only Watching
  desktop Desk L2 for those three periods, clamped to the existing resolved cap.
  Default get_floor is unchanged. RGB->HSB, EMA, max-step, smoothing, deadband,
  transition and final leased Hue transport are preserved. No CT is added.
  First frames ease toward the input floor; 110/90/70 are settled targets, not
  forced first-frame output. Gaming/Rust paths, L5, laptop/Couch/Bed envelopes,
  day behavior, kitchen and other Activities gain no new floor.

## Exact test changes and evidence

Modified tests:
- `tests/test_desk_diffuse_fill.py`: preserve prior candidate/explicit-Off tests;
  update static integration expectation; add literal-flag/context fallback and
  cap clamp checks using memory Hue transport and existing smoothing.
- `tests/test_screen_sync_route.py`: real AutomationEngine/PresenceFusion and
  ScreenSyncService with synthetic reconciled effect state and memory Hue.
  Cover all three positive floors with manual Watching, missing/stale/pose or
  non-Desk evidence, older strong Latitude conflict, manual L2, DND, Away,
  Sleeping, disabled, scene, external-off, host return, effect and laptop.
  Queue-wait tests reject replaced/missing/stale/ABA source, conflict, DND,
  manual L2, scene and Away. Another test invalidates source immediately before
  bridge dispatch and proves L2 is not written.
- `tests/test_desk_owner_dispatch.py`: supply the shared floor import to its
  existing AST-only calculator fixture; no production owner policy changed.
- `tests/test_light_state_calculator.py`: update only the two expected nighttime
  Desk L2 values in the existing L5-preservation parametrization.

Interpreter: `C:\Work\home-hub-project\main\.venv\Scripts\python.exe`.
All pytest runs use `-B -m pytest -q -p no:cacheprovider`.
The five requested files passed **253 tests in 22.44 seconds**:
`test_desk_diffuse_fill.py`, `test_screen_sync_route.py`,
`test_screen_sync_multi.py`, `test_desk_owner_dispatch.py`,
`test_desk_comfort_simulation.py`.
Initial red runs caught the boundary-only lease check, the AST fixture's missing
import and old static expectations, and test assumptions that bypassed retained
EMA easing. These were corrected without changing the existing smoothing rules.
The existing 28,224-row matrix still reports 20,160 owner_dispatch gaps; that
historical broader simulation is not physical acceptance or a reason to widen
this integration. Additional calculator verification passed **361 tests in 10.41 seconds**
(`tests/test_light_state_calculator.py`). Final `git diff --check` with the exact
worktree safe.directory passed. Initial integrated checks: **614 passed**. Independent review found a missing
Latitude-source revision fence: a strong Couch/Bed observation followed by source
invalidation during an L2 queue wait (Latitude ABA) still allowed the lifted L2
frame. The new `latitude_aba` regression reproduced this **RED** (1 failure),
then passed **GREEN** after capturing and rechecking both Desktop and Latitude
physical source generations. The full expanded offline run — the original six
suites plus `tests/test_lighting_ownership_regressions.py` and
`tests/test_lighting_final_write_authority.py` — passed **665/665** (27.03s)
using the same interpreter. There have been no live lighting writes.

## Remaining gates

The ScreenSync fix and manual static fallback are available for independent
owner verification offline; the full static increment remains blocked as above.
No physical adequacy claim:
separately authorized evening/night/late-night tests must assess diffuse L2 fill,
L5 glare, dark/bright content, smoothing, source loss and real owner protection.
The previous automatic process resolver/manual-Activity physical-fence concern
still applies to any future cross-Activity candidate integration; this pass uses
the existing ScreenSync route physical/final-write boundary and existing automatic
mode physical guard; manual static targets fall back to the prior 70/50. It does
not weaken that process resolver.

No commit, push, PR, merge, deploy, restart, real Hue/DDC/device write, host action,
installation, secrets access or unrelated-worktree change was performed. Release
and real-device calibration require separate explicit authorization. This note
and implementation remain local and uncommitted, not durable GitHub evidence.


## Cross-Activity sunset correction follow-up (2026-11-05, local only)

**Acceptance remains incomplete; do not release this as the full #370 fix.**
This follow-up is on `work/370-general-sunset-comfort-20261105`, HEAD
`0badf883a66ce119e10769768237ed91e37f6bd6`, in the named Sandbox worktree.
The three intentional starting modifications were retained and extended.
The preceding sections describe earlier work and do not describe this HEAD's
entire cross-Activity behavior. No network retrieval was authorized: #370,
#244 and #136 were not freshly fetched. The supplied task's incident/room lux
observations and local source are the evidence boundary, not new live readings.

### Camera data flow and authority

- Desktop `POST /api/camera/desktop/lux` in `backend/api/routes/camera.py`
  calls the application bedroom `LuxChannel.update`, with the existing client
  timestamp clamp. `backend/bootstrap.py` creates that calibrated channel and
  injects the SAME object as `AutomationEngine.bedroom_lux`. The composition
  tests use real `LuxChannel` objects, not a second brightness estimate.
- Bedroom L2/L5 read only that channel. Both room readers now require finite,
  nonnegative EMA, finite positive calibrated baseline and an aware timestamp
  aged 0..30 seconds. Missing, future, stale, malformed, or explicitly wrong-room
  samples abstain. Bedroom's old 300-second EMA-reset interval was not a suitable
  actuation freshness window. No timestamp/store/ingestion changes were made.
- Latitude `CameraService` is a separate living-room source. Its enabled/paused
  gates remain. Relax's old scalar is now restricted to L1 and kitchen L3/L4;
  it cannot modulate bedroom L2/L5 or L6. The Working/day camera read now names
  the bedroom channel. **Working/day's existing pure lux stage is still a no-op**
  because Working is outside `LUX_MODES`; changing the source alone is not a
  claim of new Working/day brightness adaptation. Gaming/day surround's Latitude
  read remains correct for its existing L1/L3/L4 policy.
- Lux never establishes Desk presence. New static increments require Home,
  enabled, awake, no manual Activity override/DND/away/host-return/external-off/
  scene, a Desk zone, AND the existing captured automatic physical validator.
  That validator freezes source epochs/deadlines and is rechecked by the existing
  LightApplicator/Hue acceptance path. General scheduling now carries BOTH its
  mode epoch and physical validator; a physical validator alone would not engage
  LightApplicator's final physical acceptance. A source-loss regression covers
  this distinction. No independent Hue writer or relaxed process resolver exists.
- `_room_lux_diagnostics` records room source, age, and freshness/skip reason;
  `_desk_fill_diagnostic` records eligibility, lux availability, application and
  policy skip reason. These are testable internal diagnostics, not a new API or
  image/camera-data log.

### Bounded targets and compact acceptance matrix

New policy only accepts an already-on, warm CT L2 (333..500 mirek), under the
above automatic Desk lease. Neutral floors reuse 110/90/70 Hue brightness for
Evening/Night/Late Night. Bedroom EMA/baseline <0.5 applies 1.10; >1.5 applies
0.90; otherwise neutral. A 0.10 ratio deadband plus existing camera EMA and target
deduplication limits jitter. Missing/stale data is neutral. The target is the
larger of the scaled floor and scaled authored brightness; new increments cap
at 200, while brighter authored targets are not cut to that ceiling. This does
not change CT, author Off, or author L5. These numbers are tuning candidates,
not preferred user values or photometric safety claims.

| Activity | Evening / Night / Late Night static L2 | Camera effect / gap |
| --- | --- | --- |
| General | Authored 170 / 90 / 70; eligible dark example 187 / 99 / 77 | Bedroom only; legacy desk balance retained when no new lease; no double lux stage |
| Working | Authored 180 / 105 / 95; eligible dark example 198 / 116 / 105 | Bedroom only; daylight stage still unchanged/no-op |
| Watching | Existing Desk overlay then bounded shared fill | Bedroom dark/bright affects static CT; shipped qualified ScreenSync remains unchanged |
| Cooking | Eligible neutral minimum 110 / 90 / 70 | Bedroom input affects L2 only; kitchen pair retains its independent plan |
| Gaming | Shipped HSB L2 preserved | Warm-CT policy refuses colored targets; **unmet warm fill** |
| Relax | Shipped HSB L2 preserved | Latitude affects living-room/kitchen only; **unmet bedroom warm fill** |
| Social | Existing static social route/palette preserved | Its HSB L2 remains outside new fill; **unmet warm fill** |

Examples assume default mode brightness, no weather/learner changes, settled
period and valid automatic Desk authority. Stronger per-light owners still win
at the ordinary apply boundary. L5's existing final Desk ceilings remain
90/75/60/40 for Day/Evening/Night/Late Night; no new L5 lift is introduced.

`TestNightComfort370.test_room_source_context_matrix` parameterizes seven
Activities x four periods x four bedroom states x four Latitude states x four
physical contexts x three target/screen representations = **5,376 composition
rows** (28 pytest cases looping the remaining dimensions). Dark/bright are
real calibrated channel values; stale/missing abstain. Physical contexts are
Desk/unknown/Couch/Bed. White/dark cases represent CT targets; colored represents
HSB targets. **This is not a screen pixel/perception simulation or 5,376 final
Hue dispatch tests.** The predicate is supplied for this composition matrix.
Authored engine composition, real General source qualification/source loss,
per-light manual/transit protection, explicit Off, DND, house state, scene,
external-off, missing lease, invalid/future/naive samples, ratio jitter, and
transition checks are separate tests. Existing real-memory Hue, source ABA,
lease/effect and ScreenSync suites remain necessary final-owner evidence.
The historical 28,224-row simulation still has its documented 20,160
`owner_dispatch` gaps; this follow-up does not erase them.

### Transitions and remaining acceptance

The supplied 17:37:26 EST sunset regression now holds the General day brightness
at the boundary, then blends over 30 minutes to Evening (L2 190 -> 170, L1
140 -> 80, kitchen 90 -> 45). This avoids the incident's one-second across-room
dim without inventing unknown Desk presence. Wrong-day weather uses the fixed
schedule. Existing Evening -> Night wind-down remains. Compatible authored
Night -> Late Night targets now blend over the preceding 30 minutes. The new
minimum floor also blends across both nighttime boundaries so it cannot itself
introduce a 110 -> 90 -> 70 step. The existing Watching overlay uses that same
floor; leaving it at a fixed 110/90 would otherwise defeat the shared easing.
The lux policy itself also eases over twilight: General starts from its prior
daytime room-lux balance, other modes from their existing daytime brightness,
and Watching starts from its existing 160 Desk floor. Twelve authored pipeline
regressions cover dark/bright/missing bedroom lux across General, Working,
Watching and Cooking at sunset -1/0/+1 seconds. General retains the old L5
bedroom dimming even under the new L2 lease; L2 is adapted once. CT-mode output after sunset remains >=333;
no CT+HSB mixed payload is added.

The shared handoff composes each fixture independently. Authored On -> Off fades
brightness toward zero using the On endpoint's color space; explicit user Off
still belongs to its stronger owner. CT <-> HSB handoffs are skipped per fixture
and listed in `_period_handoff_diagnostic`; they are **not claimed seamless**.
Existing profile-specific Gaming plans and Game Day exemptions are retained.

**Unmet acceptance / gates:**

1. Full cross-Activity warm fill is not achieved for shipped colored Gaming,
   Relax and Social L2 targets. A reviewed decision is needed for warm-CT versus
   colored atmosphere/ScreenSync composition; this pass does not strip color or
   convert a fresh owned frame to CT. Daylight adaptation across all seven
   Activities is also not implemented.
2. Manual Activity static increments remain blocked by the exact per-light
   physical-acceptance issue described above: the existing automatic validator
   intentionally returns None for manual override and fences whole applies.
   It cannot be enabled globally without affecting independent manual scenes
   and fixtures. No new manual/per-light physical fence is claimed.
3. ScreenSync keeps the deployed Watching-only qualified floor and existing
   source/lease/final acceptance. This patch adds no camera-lux modulation or
   cross-Activity floor to ScreenSync. White/dark/colored live frame adequacy
   and all cross-Activity ScreenSync combinations therefore remain unmet.
4. Unknown physical General receives the conservative authored/ramped Home
   fallback, not a camera-authorized Desk lift. Lux cannot distinguish Desk,
   projector or Bed. No claim that the unknown-state fallback meets the user's
   perceived nighttime task-light need is justified without physical acceptance.
5. Compatible synthetic brightness ramps do not prove perceived comfort, source
   cadence resilience, glare, or device interpolation in the room. Existing
   stronger period-specific L5 caps may still step when a cap tightens, and the
   required post-sunset CT >=333 clamp is not claimed to be a seamless warmth
   transition. Lux freshness is checked at composition; lux alone does not gain
   a separate final-write lease or authority. No live
   camera/device/service/production action, publishing, or deployment occurred.

Validation evidence is recorded below after the final offline runs. Resume from
the local uncommitted diff; none of this new evidence has been published to GitHub.


Final offline validation: **1,317 passed in 139.33 seconds, exit 0**. Interpreter
`C:/Work/home-hub-project/main/.venv/Scripts/python.exe`, flags
`-B -m pytest -q -p no:cacheprovider`, with these fourteen test files under
`tests/`: `test_automation_engine.py`, `test_light_state_calculator.py`,
`test_lux_multiplier.py`, `test_lux_channel.py`, `test_camera_lux_ema.py`,
`test_desk_diffuse_fill.py`, `test_screen_sync_route.py`,
`test_hue_worker_physical_owner.py`, `test_desk_v2_effect_acceptance.py`,
`test_desk_owner_dispatch.py`, `test_screen_sync_multi.py`,
`test_lighting_final_write_authority.py`, `test_lighting_ownership_regressions.py`,
and `test_desk_comfort_simulation.py`. The final run includes the 5,376-row
composition matrix and the additional authored twilight/night-boundary tests.
Ruff **0.15.10** check passed on both touched production modules and both touched
Python test files. `git diff --check` passed. The only later edit renamed and
clarified the missing-baseline test without changing its assertions, plus this
documentation; its earlier combined assertions passed and the final targeted
renamed check is recorded by the local verification command. No tools were
installed or updated.

Earlier RED runs found an outdated timestamp-less bedroom fixture, an extra
composition clock sample, the General scheduler's missing mode epoch, and a
synthetic composition harness observing the wrong effect-reconciliation path.
Those were corrected; the real General source-loss/manual/transit checks and
single-clock regression pass in the final combined run. The new Watching floor
handoff and twilight policy tests cover the additional layering risks described
above. No independent review or real-room acceptance has occurred in this task.
