# Desktop comfort candidate simulation — #244 / #370 / #371 / #243

Sandbox coding handoff; branch `fix/desk-comfort-370-371`, starting SHA
`dcacfc7eda54acad016b4a5ddf95479b43cf10aa`. No publication or live acceptance.
No Hue, DDC, network, service, or task operations were performed by the simulation.

## Evidence and assumptions

The task supplied the physical observation: Home, fresh qualified Desktop Desk,
manual Watching, white ChatGPT page in a dark room; evening targets
L1=55/L2=110/L3=L4=off/L5=15/L6=35. It also supplied G50F native
12/50=24% at 20:46, RGB gains 50/44/36, a 38% Evening target after sunset,
and the late transition to Night. These observations were **not independently
reverified** here. #242 remains outside this change.

Code establishes a Watching Desk overlay, separate ScreenSync envelopes, and
the final #251 L5 cap. The monitor's `LuxProvider` reads generic
`/api/camera/status` EMA/baseline without bedroom qualification or sample age.
That endpoint is not a trusted bedroom ambient input for this proposal.

Simulated dark/bright samples are camera-proxy values 20/180 against assumed
calibrated baseline 90. They are not measured physical lux. The physical Desk
axis assumes already-qualified fresh upstream evidence; lux freshness is a
separate axis. Bed posture is unknown. Hue brightness units and normalized DDC
percentages do not establish illuminance, glare, contrast, or eye comfort.

## Reproduction and coverage

Use the existing project interpreter, `-B`, no pytest cache, and a new guest TEMP
directory each run. From this worktree:

```powershell
$py = 'C:/Work/home-hub-project/main/.venv/Scripts/python.exe'
& $py -B -m pytest -p no:cacheprovider --basetemp "$env:TEMP/desk-comfort-sim-<unique>" -q -s tests/test_desk_comfort_simulation.py
```

The harness enumerates 7 activities × 4 periods × 2 ambient levels × 3 bedroom
lux freshness states × 4 physical zones × 3 screen compositions × 7 ownership
labels × 2 cloud/clear contexts = **28,224 rows**.

| Available model | Coverage / limitation |
| --- | --- |
| Static target candidates | Production resolver → zone overlay → General-only fresh bedroom-lux balance → final fixture caps |
| Watching ScreenSync | Production floor/cap lookup, cloud/clear context, neutral lux multiplier; frame luminance/EMA is not simulated by these envelope rows |
| Monitor defaults | Production `resolve_target` with ambient disabled; separate offline twilight hook at an assumed sunset+30 minutes |
| Auto / manual Activity | 8,064 rows marked `pipeline_subset`; label does not resolve detector arbitration or final ownership |
| Per-light / scene / ScreenSync / Away / Sleeping | 20,160 rows marked `owner_dispatch`; targets are candidates only, not authorized writes |
| White / dark / media | Labels for matrix coverage; real frame dispatch and smoothing are checked separately with fake-Hue route tests |
| General fresh bedroom lux | Uses assumed calibration; stale/missing means no adaptation |
| Other transformations | Learner, weather aesthetics, gaming composition/game exceptions, transition reconciliation, DND, transit, external-off, protected fixtures and dynamic scenes are not composed in this matrix |

The matrix checks paired L3/L4, unmixed CT/HSB, valid Watching envelopes, and
bounded monitor candidate output. Existing integration tests cover real owner
chokepoints with disposable fixtures; matrix ownership labels alone are not proof.

## Baseline lookup targets

Authored candidate plus Desk overlay and final cap; **no bedroom-lux scaling**,
learner, weather, gaming composition, or owner dispatch. Cells are L2/L5 in Hue
brightness units. This table remains unchanged by this slice.

| Activity | Day | Evening | Night | Late night |
| --- | --- | --- | --- | --- |
| General | 190/90 | 130/55 | 90/35 | 70/25 |
| Working | 254/90 | 180/75 | 105/60 | 95/40 |
| Watching | 160/70 | 110/15 | 70/12 | 50/12 |
| Gaming authored table | 240/90 | 150/75 | 105/45 | 80/35 |
| Relax | 85/85 | 55/75 | 28/38 | 26/26 |
| Social | 120/90 | 120/75 | 120/60 | 120/40 |
| Cooking | 80/80 | 50/50 | 20/18 | 20/18 |

Watching Desk ScreenSync envelopes, neutral ambient/weather:

| Period | L2 floor–cap | L5 floor–cap | Static Desk L2 |
| --- | --- | --- | --- |
| Day | 15–180 | 15–50 | 160 |
| Evening | 15–140 | 15–50 | 110 |
| Night | 30–110 | 18–50 | 70 |
| Late night | 25–80 | 14–40 | 50 |

Day frames use the existing separate neutral CT policy. The #251 Desk L5
ceilings remain **90/75/60/40, cap-only**. Some authored activity candidates
have L5 numerically above L2; that is a balance review gap, not grounds to
infer perceived brightness from these numbers or raise L5.

## Changes and unresolved gates

| Finding | Result / remaining gate |
| --- | --- |
| Non-media white ChatGPT page perpetually renews unrelated media color | Fresh qualified Desktop Desk + representative RGB channels ≥180 and spread ≤24 releases that hold and enters the existing ScreenSync write path. Manual Activity remains selected. Unknown, stale, Couch and Bed revoke acknowledged page-only claims; true media holds retain prior behavior. Chromatic non-media at qualified Desk retains the existing hold. |
| White composition retains saturation through EMA | Qualified Desktop Desk non-media neutral pages immediately lower stored/output saturation to the current neutral target; brightness keeps its existing easing and caps. Existing picker prevalence tests preserve tiny-accent rejection. |
| Desk changes while frame queues | Physical Desk freshness and fused zone are rechecked at final write; losing Desk causes abstention. Existing ownership leases/validators remain authoritative. |
| Shared static illumination across seven activities | **Unresolved #370:** no new cross-Activity floor. A safe numeric floor requires physical L2 surround calibration and an agreed eligible-owner contract. #251 cannot supply that guarantee. |
| ScreenSync floor below static Desk overlay | **Unresolved #370:** dark-frame usefulness needs physical calibration. White-page frames now drive the existing bounded diffuse-light envelope instead of holding unrelated video. No new blind floor or actuator path. |
| G50F twilight waits until sunset+90m | Offline hook only: calibrated dark bedroom (sample/baseline ≤0.5), explicit qualified Desk, finite sample age 0–30s; ramp from supplied Evening to Night target over sunset+0–30m. Unknown/bright/stale/missing evidence returns the original target. Thresholds/ramp are assumptions for evaluation, not resolved product decisions. |
| Trusted monitor bedroom input | Require source/room provenance, calibration identity, sample timestamp/age and validity, plus fresh physical Desk. Reuse a proven bounded bedroom channel only after its exposure/calibration and delivery contract is verified. No new endpoint or generic camera-lux wiring was invented. |
| Physical monitor acceptance | Validate G50F native readback, contrast during twilight, warmth/gains, and external button override/backoff before enabling the candidate hook. Existing native VCP and manual override implementation is unchanged. |

No PROJECT_SPEC decision or issue status was changed. The hook has no runtime
caller; deploying this slice would not change monitor twilight timing.

## Validation evidence

Baseline command used the four suites below and TEMP suffix `baseline-20261010`:
**435 passed**, no baseline failures. Source inspection identified the behavioral
white-page gap; existing baseline tests expected a generic non-media hold.

```powershell
& $py -B -m pytest -p no:cacheprovider --basetemp "$env:TEMP/desk-comfort-baseline-20261010" tests/test_light_state_calculator.py tests/test_screen_sync_picker.py tests/test_screen_sync_route.py tests/test_monitor_brightness.py -q
& $py -B -m pytest -p no:cacheprovider --basetemp "$env:TEMP/desk-comfort-broad-20261010" tests/test_desk_comfort_simulation.py tests/test_light_state_calculator.py tests/test_automation_engine.py tests/test_screen_sync_picker.py tests/test_screen_sync_route.py tests/test_screen_sync_multi.py tests/test_monitor_brightness.py tests/test_lighting_final_write_authority.py tests/test_lighting_ownership_regressions.py tests/test_lighting_authority.py -q
```

Broad check: **1,033 passed** before the additional queued Desk-loss regression
and expanded monitor matrix. Final rerun of the same ten suites with TEMP suffix
`broad-final-20261010`: **1,040 passed**. The final matrix includes monitor
candidates; route regressions include manual Watching over detector Working.
Ruff passed on all five changed Python files; `git diff --check` passed.
Initial new-test failures (missing explicit cap posture argument,
legacy presence adapter, residual saturation) were corrected; no baseline
failure was hidden.

## Changed files and review anchors

| File | Review anchor |
| --- | --- |
| `backend/api/routes/automation.py` | `receive_screen_color`: final guard near line 750; white-page eligibility near line 827 |
| `backend/services/screen_sync.py` | Neutral composition saturation history near line 1273 |
| `backend/services/desk_visual_comfort.py` (new) | `is_neutral_page` line 5; offline `twilight_monitor_target` line 10 |
| `tests/test_screen_sync_route.py` | Physical-zone/manual Activity regressions near line 254; queued Desk-loss near line 298 |
| `tests/test_desk_comfort_simulation.py` (new) | `scenarios` line 24; matrix verification near line 70; twilight contract tests below |
| This report (new) | Candidate/gap tables and exact validation commands |

Final Git status contains only these six intended files (three modified, three
new). Branch/HEAD remain the starting values above; no commit was created.

Publication, deployment, production inspection, service/task restart and all
Hue/monitor hardware writes remain lead-controlled gates.

## Follow-up to independent Astra REWORK

The prior durable Write `b368aa1fb3294c3cb9575f50d7f5a5ab` and independent
Astra Read `dc3ec32ef8a34fbbaf6daea050dd4884` were supplied as completed.
The confirmed P2 post-acknowledgement ownership blocker is addressed in this
uncommitted follow-up; no new independent Astra review has been run here.

The route now separates qualified physical Desktop Desk from page composition.
The existing leased frame context carries page provenance into
`_record_source_write`, inside serialized acknowledgement publication (including
valid dedup refreshes). Per-light source provenance marks successfully accepted
page output, including daytime CT output, and is cleared by accepted real media
or physical-claim removal. It is not inferred from white video RGB.

When Desk becomes absent/stale/Bed/Couch/unknown, the next authoritative desktop
Watching frame revokes only those page claims through `supersede_light` before
non-media hold refresh. This invalidates ownership leases, cancels pending work,
and drops `_last_sent_state`, daylight cache, per-light freshness/frame kind and
`_hold_refreshed_at`. Revocation issues no Hue write and cannot energize off lamps.
`fresh_owned_light_ids` therefore no longer lends page protection to
`LightApplicator.protected_light_ids`, used by camera commit's normal
`_apply_mode(..., force_resend=True)` reconciliation. Independent manual/transit
and external protections remain on that established pipeline; no new actuator
or reconciliation bypass is introduced. Real media remains eligible to resume
under the existing non-Desk caps and pause/seek/tab hold behavior.

Immediate neutral desaturation now uses the same explicit qualified page context,
not all white desktop Watching video frames. A Bed neutral-video regression
checks ordinary saturation easing and later chromatic recovery. Post-ACK tests
cover all five loss cases at day/night with manual Watching and desktop semantic
authority retained, repeated non-media frames, invalidated old leases, actual
applicator protection including a surviving manual light, fresh media resume and
media hold. A mixed per-light regression ensures page revocation preserves a
separate real-media light. The original pre-ACK queued-loss test remains.

Monitor import side effect (nonblocking): `tests/test_desk_comfort_simulation.py`
imports `resolve_target` from the monitor agent, whose module initializes
`LOCALAPPDATA/home-hub/logs` (fallback: home directory) and a rotating
`monitor_brightness.log` handler at collection. Pytest `--basetemp` does **not**
isolate that initialization. The earlier assertion of no Hue/DDC/HTTP operations
still holds; it must not be read as zero filesystem side effects. A pure-policy
split would require additional monitor-agent files/callers beyond this narrow
six-file repair, so it is deferred and no environment redirection was added.

The **28,224-row matrix remains PARTIAL**. #370 shared static L2 fill still needs
physical calibration; #371 runtime twilight remains gated on trusted calibrated
bedroom lux and physical acceptance. No gate was relaxed.

### Follow-up validation

Final focused run: **142 passed** (route, multi-light service, simulation).
Final broad run: **1,052 passed** in the same ten lighting/automation/picker/
monitor/ownership suites listed above. Both used the existing project Python
with `-B`, `-p no:cacheprovider`, and a new GUID-based guest TEMP basetemp:

```powershell
& $py -B -m pytest -p no:cacheprovider --basetemp "$env:TEMP/desk-review-focused-$([guid]::NewGuid().ToString('N'))" tests/test_screen_sync_route.py tests/test_screen_sync_multi.py tests/test_desk_comfort_simulation.py -q
& $py -B -m pytest -p no:cacheprovider --basetemp "$env:TEMP/desk-review-broad-$([guid]::NewGuid().ToString('N'))" tests/test_desk_comfort_simulation.py tests/test_light_state_calculator.py tests/test_automation_engine.py tests/test_screen_sync_picker.py tests/test_screen_sync_route.py tests/test_screen_sync_multi.py tests/test_monitor_brightness.py tests/test_lighting_final_write_authority.py tests/test_lighting_ownership_regressions.py tests/test_lighting_authority.py -q
& $py -B -m ruff check backend/api/routes/automation.py backend/services/screen_sync.py backend/services/desk_visual_comfort.py tests/test_screen_sync_route.py tests/test_desk_comfort_simulation.py
git diff --check
```

Ruff passed on the five candidate Python files; `git diff --check` passed.
Initial follow-up test failures were fixture errors: treating manual overrides
as a set rather than a dictionary, validating a lease outside the final boundary,
and injecting a retrograde stale observation that fusion correctly discarded.
These were corrected and the affected focused suites rerun before the broad run.
No production endpoints or secrets were inspected. No publication, tool install,
service/agent restart, environment change, Host Bridge operation or physical
Hue/DDC action was performed. All work remains uncommitted on the same branch
and HEAD, with only the original six candidate files changed.
