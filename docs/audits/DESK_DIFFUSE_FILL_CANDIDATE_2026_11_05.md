# #370 diffuse fill - local integration resume point

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
