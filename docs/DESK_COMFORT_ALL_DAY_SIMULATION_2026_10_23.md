# #370 all-day offline desk simulation and gap report

Local, uncommitted evidence on `work/370-all-day-simulation-20261023`, starting
HEAD `fbd48c5f3f767ec8f1cc53b411f1a769cd3a2006`, tree
`724f91e0d20e85df9e903e3e22148fa7a1180e0f`. Worktree:
`C:/Work/home-hub-project/worktrees/desk-all-day-sim-370-20261023`.
This report supersedes only the matrix methodology in the
[October 10 handoff](DESK_COMFORT_SIMULATION_2026_10_10.md); its historical
observations and validation remain historical. No publication or live acceptance.

Authority: [PROJECT_SPEC.md desk visual comfort](PROJECT_SPEC.md) (2026-09-08 decision)
and the supplied bounded task. The live #370 acceptance body was unavailable
offline; no network fetch was attempted. This is a pure candidate simulation and
gap report, not a product policy change or proof of physical comfort.

## What executes

`tests/test_desk_comfort_simulation.py` executes production functions:

- `resolve_activity_state`, General-only `apply_general_desk_lux_balance`,
  `apply_functional_weather_brightness`, `apply_zone_overlay`,
  `apply_weather_adjust` using production `WEATHER_SKIP_MODES`, then final
  `enforce_fixture_comfort_invariants` from `light_state_calculator.py`.
- `ScreenSyncService.get_floor/get_cap` for Watching and Gaming L2/L5, with
  no Hue service, neutral ambient multiplier 1 and the selected weather.
- `is_neutral_page` on explicit representative RGB values; this now executes
  the screen axis. No RGB-to-brightness or frame-luminance equation is invented.
- Monitor `resolve_target` with ambient inputs disabled, plus the separate
  **offline, unwired** `twilight_monitor_target` hook at assumed sunset+1800s
  during evening. Import logs are isolated before collection.

This is an explicitly ordered subset, not an AutomationEngine replay. General
composition, Working/day composition, Gaming Director variants, learner overlays,
configured scenes, ownership leases, transition echoes, real frame dispatch/EMA,
and true Hue writes are not reconstructed by concatenating these functions.
Generic Gaming runtime ignores screen RGB; its authored table/envelope must not
be mistaken for the game-aware runtime. Existing targeted tests exercise those
boundaries separately, with mocks.

## Scenario and mathematical assumptions

The measured count is **44,352 labelled rows**:
`7 Activities × 4 periods × 6 sample cases × 4 zones × 3 screens × 2 weather × 11 owners`.
The expensive production projections run **4,032** times before expansion by
owner label. This is a period grid covering an all-day range, not a chronological
trajectory or dwell/transition simulation. Owner expansion adds no independent
production execution or decision authority.

Activities are General, Working, Watching, Gaming, Relax, Social and Cooking.
Periods are day/evening/night/late_night. Weather `clear` means assumed sunny and
`clouds` means assumed cloudy; no weather service or wall clock is consulted.
Learner preference set is empty; user brightness multiplier is implicitly 1.
Generic living-room lux is deliberately not applied to bedroom fixtures.

Bedroom samples assume calibration baseline 90 and camera-proxy values 20/180,
**not measured physical lux**. Six cases separate value, age and provenance:
fresh bedroom low/high at age 0; stale bedroom low/high at age 301; missing
value/age; fresh but unqualified generic-camera low. Static input eligibility
uses the production `LUX_EMA_STALE_RESET_SECONDS=300` constant. Its harness gate
also conservatively rejects negative/nonfinite values/ages; this is not proof
that every upstream ingestion path rejects them. The monitor hook independently
requires finite age 0–30s and dark ratio at most 0.5. Its ramp is
`round(base + (min(base, night) - base) × clamp(elapsed/1800, 0, 1))` after
the hook's eligibility gates. Static freshness and monitor freshness differ.

Desk assumes already-fresh, source-qualified Desktop physical evidence. Unknown
represents absent/stale/unqualified zone; Couch and Bed assume independently
qualified physical observations, with posture unknown. Lux does not establish
Desk. The simulation does not itself run PresenceFusion freshness arbitration.
The source group in JSON describes **lux provenance**, not frame/device ownership.
Screens use white `(245,245,245)`, dark `(20,20,20)`, colored `(255,190,190)`;
only white classifies neutral. All three share the same static candidate and
lookup envelope; content-dependent dispatched output remains outside this grid.

`supported_pure_target_subset` means the candidate was calculated and checked,
not that an owner authorizes it. `supported_input` means the assumed lux sample
passed the harness input gate; most Activities do not consume that sample.
`guarded_abstain` means no General lux adaptation from that sample, not lights
off. `manual_strong_veto` records per-light manual/scene intent, not executed
suppression. Every row is also `unsupported_end_to_end` for owner dispatch.

## Measured coverage and gaps

All rows passed L3/L4 equality, unmixed CT/HSB, cap-only L5 non-uplift,
applicable L5 ceilings, ordered ScreenSync envelopes and non-increasing monitor
twilight candidates. Dedicated patterns test off L5 stays off, low L5 is never
raised by the cap, input immutability, rejected lux matching the neutral
projection, non-Desk lux independence and real functional cloudy-weather effect.
Watching/Gaming L5 envelope caps do not rise with ambient multipliers 0.6/1/1.5
or clear/clouds weather and stay within Desk ceilings 90/75/60/40.
This does **not** claim ScreenSync always equals or dims the static L5 target:
Watching/night static L5=12 whereas its envelope floor is 18.

The following tables are transcribed from the final JSON. Counts include owner
label replication; totals within each axis sum to 44,352. All rows have an
unsupported end-to-end owner decision. Missing JSON counter keys mean zero.

| Period | Rows / owner gaps | Lux input supported | Lux abstain | Watching floor review |
| --- | ---: | ---: | ---: | ---: |
| day | 11,088 | 3,696 | 7,392 | 396 |
| evening | 11,088 | 3,696 | 7,392 | 396 |
| night | 11,088 | 3,696 | 7,392 | 396 |
| late_night | 11,088 | 3,696 | 7,392 | 396 |

| Activity | Rows / owner gaps | Lux input supported | Lux abstain | Watching floor review |
| --- | ---: | ---: | ---: | ---: |
| General | 6,336 | 2,112 | 4,224 | 0 |
| Working | 6,336 | 2,112 | 4,224 | 0 |
| Watching | 6,336 | 2,112 | 4,224 | 1,584 |
| Gaming authored | 6,336 | 2,112 | 4,224 | 0 |
| Relax | 6,336 | 2,112 | 4,224 | 0 |
| Social | 6,336 | 2,112 | 4,224 | 0 |
| Cooking | 6,336 | 2,112 | 4,224 | 0 |

| Lux source | Rows / owner gaps | Lux input supported | Lux abstain | Watching floor review |
| --- | ---: | ---: | ---: | ---: |
| bedroom | 29,568 | 14,784 | 14,784 | 1,056 |
| missing | 7,392 | 0 | 7,392 | 264 |
| unqualified camera | 7,392 | 0 | 7,392 | 264 |

Each of the six sample cases has 7,392 rows. Each screen case has 14,784;
white produces 14,784 neutral classifications, dark/colored together 29,568
non-neutral classifications. There are 14,784 supported lux input labels and
29,568 guarded abstentions overall. Pure target checks cover all 44,352 rows;
there are **zero end-to-end owner decisions proven by this grid**.

## Explicit owner gap matrix and separate integration evidence

Each owner below has **4,032 unsupported grid rows**, including 1,344 supported
lux inputs, 2,688 lux abstentions and 144 Watching floor-review labels.
Per-light manual and scene together account for 8,064 `manual_strong_veto`
intent labels. Candidates are retained for comparison even when actual ownership
would veto; do not treat them as proposed writes.

| Owner label | Missing composition | Separate mocked evidence run |
| --- | --- | --- |
| auto | detector arbitration/final apply | `TestDeskProcessAuthorityPolicy` |
| manual_activity | selection retained versus physical context | `test_manual_watching_keeps_mode_and_physical_comfort_context`; route `test_manual_watching_uses_fresh_desktop_desk_authority` |
| manual_light | strong per-light veto | route `test_manual_override_on_one_light_skips_only_that_one`; final-write parameter cases |
| scene | configured scene/native scene ownership | `test_native_scene_delayed_acknowledgement`; `test_trial_cannot_adopt_new_intent_during_scene_safety` |
| screen_sync | fresh leases/dispatch/acknowledgement | route `test_acknowledged_desk_page_loses_ownership_but_media_resumes` |
| away | invalidation and off convergence | `test_away_convergence_rejects_queued_screensync_and_keeps_failed_off_suppressed` |
| sleeping | current state/strong ownership | final-write `test_try_it_waiting_restore_cannot_overwrite_new_authority[sleeping]`; desk `test_mode_and_owner_guards` |
| dnd | policy-specific veto, not universal off | desk `test_dnd_abstains` |
| transit | per-light ownership/timers | `test_rust_final_restore_respects_real_engine_owners[transit]`; ownership transit-clear regressions |
| protected | applicator protected light set | `test_screen_sync_protection_tracks_fresh_lights_not_capability_list` |
| external_off | external hold and partial failures | `test_bridge_loss_preserves_external_off_and_hard_hold`; ownership external-off regressions |

These names belong to `tests/test_automation_engine.py`,
`test_screen_sync_route.py`, `test_lighting_final_write_authority.py` and
`test_lighting_ownership_regressions.py`. They validate narrow real code paths
against fakes, not every cross-product combination above. In particular, DND
abstention is proven for desk process authority; Sleeping replacement protection
and Away stale-write suppression are proven in the named paths. No universal
DND/Away/Sleeping all-light suppression claim follows from this simulation.
`TestDeskFixtureComfortIntegration` separately tests learner uplift capped at L5
and retained physical-context protections through actual engine composition.

## Actionable counterexamples and remaining gates

**ANALYTIC ONLY:** the review predicate compares Watching Desk L2 floor with
its static L2 candidate (`floor < static`), using ordinal Hue brightness units.
It is not a deployed floor, physical contrast equation, safety violation or
eye-health claim. It finds **1,584 labels / 144 physical-content projections**.
The optional L2-below-L5 ordinal review predicate excludes intentionally low-light
Relax/Cooking; it finds zero rows among the remaining Activities. That absence
does not certify comfort. No magic absolute brightness threshold is introduced.

Measured clear-weather, assumed fresh dark-bedroom, qualified Desk examples:

| Scenario | Static L2/L5 | ScreenSync L2 floor–cap | ScreenSync L5 floor–cap |
| --- | --- | --- | --- |
| Watching evening | 110/15 | 15–140 | 15–50 |
| Watching night | 70/12 | 30–110 | 18–50 |

These are two concrete counterexamples to treating the static Desk target as a
shared ScreenSync lower bound. Calibrate dark-content usefulness with real L2
surround measurements and agree eligible owners before proposing a shared floor.
The numerical gaps of 95/40 are target-space differences, not measured deficits.
White-page classification does not predict an exact output within those ranges.

Relax evening remains 55/75 and night 28/38 in this scenario; the report does not
call intentional low-light atmosphere unsafe or raise L5 to resolve a ratio.
Any comfort concern needs physical review and an Activity/owner contract first.
Future acceptance also needs Gaming Director/learner compositions, transition
reconciliation, calibrated room/screen measurements and authorized physical
comfort review. Runtime changes, live inspection and hardware actuation remain
outside this task. #370 shared all-Activity L2 policy and #371 monitor wiring are
still gated; this report creates no new floor or device-write path.

## Reproduction and validation

Use the existing interpreter only. The command disables dotenv file loading
**before** conftest/config import, isolates monitor logs before collection,
disables plugin autoload/cache and bytecode writes, blocks file databases and
real HTTP transport, and blocks external socket connections. Loopback sockets
remain available for Windows asyncio setup; no HTTP request transport is allowed.
Existing mock fixtures use in-memory SQLite only. No package install is needed.

```powershell
$py = 'C:/Work/home-hub-project/main/.venv/Scripts/python.exe'
$env:LOCALAPPDATA = Join-Path $env:TEMP ('desk-local-' + [guid]::NewGuid().ToString('N'))
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$base = Join-Path $env:TEMP ('desk-sim-' + [guid]::NewGuid().ToString('N'))
$code = @'
import sys
from unittest.mock import patch
from pydantic_settings.sources import DotEnvSettingsSource
patch.object(DotEnvSettingsSource, '_read_env_files', return_value={}).start()
import httpx
patch.object(httpx.Client, 'send', side_effect=AssertionError('offline HTTP blocked')).start()
patch.object(httpx.AsyncClient, 'send', side_effect=AssertionError('offline HTTP blocked')).start()
def audit(event, args):
    if event == 'sqlite3.connect' and args[0] != ':memory:':
        raise AssertionError('file database blocked')
    if event == 'socket.connect' and args[1][0] not in ('127.0.0.1', '::1'):
        raise AssertionError('external network blocked')
sys.addaudithook(audit)
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
'@
& $py -B -c $code -p no:cacheprovider -p pytest_asyncio.plugin --basetemp $base -q -s tests/test_desk_comfort_simulation.py
& $py -B -m ruff check tests/test_desk_comfort_simulation.py
git diff --check
```

For the adjacent validation, use the same guarded command with a new unique
`$base` and these test arguments instead of the single simulation path:

```text
tests/test_desk_comfort_simulation.py
tests/test_light_state_calculator.py
tests/test_screen_sync_route.py
tests/test_screen_sync_multi.py
tests/test_lighting_final_write_authority.py
tests/test_lighting_ownership_regressions.py
tests/test_automation_engine.py::TestDeskFixtureComfortIntegration
tests/test_automation_engine.py::TestDeskProcessAuthorityPolicy
```

Run in a disposable PowerShell session so environment isolation is process-local.
The simulation prints its unique guest TEMP JSON path; sorted keys and fixed
inputs produce deterministic JSON content. The tracked report contains measured
counts, not a tracked copy of the disposable output. Final artifact:
`C:/Users/WDAGUtilityAccount/AppData/Local/Temp/desk-reviewed-4478f33bf4df4dbe8ec6a3fbbf9f151a/test_complete_offline_matrix0/desk-all-day-summary.json`.

Measured validation on 2026-10-23:

- Six suites (simulation, calculator, ScreenSync route/multi, final-write
  authority, ownership regressions) plus automation classes
  `TestDeskFixtureComfortIntegration` and `TestDeskProcessAuthorityPolicy`:
  **704 passed in 21.98s**, under the guards above.
- After self-review corrected saved example selection to require Desk and added
  example regression assertions/owner-intent counters: simulation **61 passed
  in 9.96s**. Other production/tests were unchanged after the broad run.
- Ruff and `git diff --check` passed. Git emits the existing Windows LF-to-CRLF
  normalization advisory; there is no whitespace failure.

Initial validation caught a fixture assertion assuming cloudy Working/day could
lift already-saturated L2=254; it now uses evening. An attempted blanket socket
guard disrupted Windows asyncio setup and was stopped; a route-only rerun passed
65 tests, followed by the guarded 704-test run above. Self-review also caught
non-Desk rows overwriting saved Desk examples; final JSON and regression checks
now require `zone=desk`. These failed/interrupted experiments are not acceptance
evidence. The initial no-autoload run warned about the missing asyncio plugin;
final runs explicitly load it and emitted no warnings.

Changed paths are only this report and `tests/test_desk_comfort_simulation.py`.
No runtime code, secrets/configuration, production DB, devices, Host Bridge,
services/tasks or Obsidian mirror were changed. No commit, push, PR, merge,
deploy, installation, cleanup or worktree removal was performed. Handoff remains
local and uncommitted; publishing and physical acceptance need separate authority.
