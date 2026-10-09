# Sonos writer and concurrency audit (#276)

Code baseline: `171abe5f844f278d08f4fc15479f8e6871137fd9`, isolated
`sonos-concurrency-audit-276` worktree. This is static code and disposable fake-device
evidence, not a deployment or physical-acceptance claim. No issue status is changed.
Product authority: PROJECT_SPEC shared audio contract; execution packet:
EXECUTION_MAP #276 and #273/#274 residual guarantee.

## Scope and guarantee

Reviewed production `backend/**/*.py` device calls, property assignments, raw
AVTransport actions, Snapshot/ShareLink helpers, their callers, and bootstrap wiring.
Read-only status, queue/evidence/media URI, favorites/playlists, discovery, snapshot
capture, polling and catalog/trust/learning reads are not playback writers.
`AudioOwnershipService` persists provenance and invalidation; it does not write
Sonos. `run_manual`, `run_if_valid`, and `run_if_opportunistic` hold its one internal
lock through their participating operations. This serializes participating HomeHub
writers only. An external Sonos controller can still race any read-then-write proof;
there is no general conditional/CAS Play, Pause, Stop, Clear, source or volume write.
The conditional helper names describe preflight checks, not device atomicity.
Ambiguous cleanup stays no-op: never add Stop/Clear or positional append deletion
to MusicMapper retirement, Ambient abandonment or assisted failure.

All references below are exact file/function identifiers relative to the repo.
Abbreviations: Q = queue/source, T = transport, V = volume, I = interruption.
S = `backend/services/sonos_service.py:SonosService`; A =
`backend/services/audio_ownership.py:AudioOwnershipService`; M =
`backend/services/music_mapper.py:MusicMapper`; B =
`backend/services/ambient_sound_service.py:AmbientSoundService`; TTS =
`backend/services/tts_service.py:TTSService`. Test references are under `tests/`.

Settlement **S** means `_safe_mutation_call -> _settled_thread_call`: timeout or
cancellation waits for the sync worker to exit before returning/raising. A caller's
shared lock consequently stays held if it actually wraps that call. This is not a
hard wall-clock timeout. Settlement **F** is assisted final bounded synchronous
UPnP work on the event-loop thread with no await between final async guard and
Play (3-second transaction budget); it blocks in-process task interleaving there,
but does not protect earlier/later awaits. **Local** state/tasks/tokens do not
survive restart. Durable leases need fresh device proof; reload is not permission.

## Production source/caller matrix

Each row lists its last device mutation boundary, rather than treating a route or
lease acquisition as the boundary. Lifecycle semantics in this table are
code-confirmed; concurrency guarantees are limited to the named tests.

| Source / exact caller | Operations / dimensions / intent | Proof and authority | Last mutation boundary / cancellation | Startup or restart | Existing evidence / gap disposition |
|---|---|---|---|---|---|
| `backend/api/routes/sonos.py:sonos_play` | Play / T + invalidate Q,I / manual | `_run_manual_sonos -> A.run_manual` | `S.play -> device.play`; S settlement | No replay | `test_audio_ownership_ingress.py:test_rest_play_invalidates_before_transport_write`; covered |
| Same file `sonos_smart_play` / `_manual_smart_play` | Resume or favorite replacement / Q,T,I / manual | Entire status/favorites/actuation inside `_run_manual_sonos` | `S.play` or favorite sequence below; S | No replay | Same ingress suite establishes wrapper; smart-play branching not independently adversarially tested |
| Same file `sonos_pause` | Pause / T + invalidate Q,I / manual | `_run_manual_sonos` | `S.pause -> device.pause`; S | No replay | Ingress suite; UPnP 701 already stopped is idempotent success |
| Same file `sonos_next`, `sonos_previous` | Next/Previous / T + invalidate Q,I / manual | Capture eligible learning session before locked invalidation | `S.next_track/previous_track -> device.next/previous`; S | No replay | `test_rest_next_captures_session_before_manual_invalidation`; previous shares wrapper |
| Same file `set_sonos_volume`, `adjust_sonos_volume` / `_manual_volume_step` | Absolute/relative volume / V,I / manual | Relative read and write inside `_run_manual_sonos` | `S.set_volume -> setattr(device, volume)`; S | No replay | `test_rest_volume_invalidates_only_volume_before_write`; queue lease survives |
| Same file `play_favorite` | Replace queue, shuffle, play / Q,T,I / manual | `_run_manual_sonos` | `S.play_favorite` sequence below; S | No replay | `test_rest_favorite_invalidates_queue_before_write`, favorite shuffle/reset suites |
| Same file `speak_text` | Clip/restore / Q,T,V,I / manual interruption | Passes manual source/reason to TTS interruption acquisition; does not hold authority during audible wait | TTS boundaries below; S | Stale interruption retired without restore | `test_rest_tts_serializes_full_manual_interruption` (individual authority transactions, not whole audible duration) |
| `backend/api/routes/guest.py:activate_guest_vibe` | Favorite replacement / Q,T,I / manual guest | `_run_guest_audio -> A.run_manual`; guest cooldown and social override | `S.play_favorite`; S | No replay | Ingress guest tests + favorite suites; social override is policy, not a second writer |
| Same file `guest_sonos_volume` / `_manual_guest_volume` | Bounded relative volume / V,I / guest | Read and write under `_run_guest_audio` | `S.set_volume`; S | No replay | Shared ingress contract; exact bounded arithmetic not concurrency-specific |
| Same file `guest_sonos_transport` / `_manual_guest_transport` | Play/Pause/Next / Q,T,I invalidation / guest | `_run_guest_audio` | `S.play/pause/next_track`; S | No replay | `test_guest_transport_invalidates_before_write` |
| Same file `speak_guest_toast` | Clip/restore / Q,T,V,I / guest interruption | TTS manual source/reason, cooldown; sparkle is not Sonos authority | TTS boundaries; S | No replay/restore at restart | `test_guest_toast_serializes_full_manual_interruption` |
| `backend/main.py:_handle_sonos_command` | Play/Pause/Next/Previous or volume / manual WebSocket | `A.run_manual`; transport vs volume dimensions; learning session capture before skip invalidation | Corresponding S primitive; S | No replay | `test_websocket_volume_invalidates_before_write`, `test_websocket_next_captures_session_before_manual_invalidation` |
| `M.on_mode_change` (including Social mappings), `on_mode_change_wrapper` | Neutral-start favorite queue replacement / Q,T / autonomous | Mode request check, DND at entry, neutral fresh queue proof, exclusive lease; `A.run_if_valid` | `S._replace_queue_if_unchanged_sync`: final full queue fingerprint before Clear/Add/SHUFFLE/queue Play; S | Durable provenance reloaded; no automatic stale queue cleanup | `test_music_mapper_ownership.py` neutral/stale/manual/restart/retention cases. No fresh lifecycle check inside the final sync favorite transaction: slow setup DND/lifecycle change remains an untested policy gate |
| `M.dispatch_pregame_audio -> _play_pregame_hype_owned` | Favorite replacement then optional startup volume / Q,T,V / autonomous Game Day | Reserve before TTS; refresh only proven TTS-caused queue generations; lifecycle after gap, final lease/preflight; volume dimension independently checked | Favorite final fingerprint; `S.set_volume_if_playback_unchanged` final rendering proof; S | Pending intent not replayed | `test_music_mapper_ownership.py:test_pregame_*` source/manual/DND/lifecycle/gap-cancel/failed-volume cases; covered internal boundaries |
| `backend/services/celebration_orchestrator.py:CelebrationOrchestrator._run_tts` | Celebration clip / Q,T,V,I / autonomous | Viewer/event authority and current volume/DND policy reread after prepared audio; delegates to TTS | TTS clip/restore boundaries; S | No speech replay | `test_celebration_orchestrator.py`, TTS suites; synthesis/authority timing beyond handoff is not a general lifecycle guarantee |
| `backend/bootstrap.py:_sleeping_tts`, `backend/services/morning_routine.py:MorningRoutine.execute`, `backend/services/away_manager.py:AwayManager._run_arrival_effects_unlocked` | Good-night/morning/welcome clips / Q,T,V,I / autonomous | Caller-specific policy; welcome `_welcome_tts_allowed`; TTS interruption authority | TTS boundaries; S | Tasks not replayed by TTS recovery; routine/lifecycle orchestration separate | TTS suite covers executor, not every caller policy race; no parallel raw Sonos write here |
| `TTS._speak_with_ownership -> _restore_owned_interruption` | Clip (volume, NORMAL/source/Play); restore source/track/seek/mode/transport/volume / Q,T,V,I / interruption | Speak lock, interruption overlay, shutdown generation, before/snapshot/preflight equality; `A.run_if_valid`; manual takeover strips only relevant restore dimensions | `S._play_uri_if_unchanged_sync` final proof; `S._restore_tts_snapshot_if_unchanged_sync -> _prepare_tts_snapshot_source_sync` and final prior-source proof adjacent to Play/Stop; volume proof before restore; S | `recover_stale_interruption` and `close` abandon without device restore | `test_tts_duck_resume.py` manual song/volume/pause, failed start, queue rebase, close/restart; `test_sonos_playback_ownership.py` prepare mismatch/direct seek/cloud refusal. Stop here is exact interrupted-state restoration, not stale-queue cleanup; external race remains |
| `backend/api/routes/ambient.py:play_sound/pause_sound/resume_sound/stop_sound`, `B.play/pause/resume/stop` | Explicit Ambient intents / Q,T,V / manual Ambient owner | Command lock; neutral-start acquisition, exact process-local paused claim for resume; not generic manual lease invalidation | Owned B boundaries below; S | Paused claim not reconstructed; retained physical URI is not authority | `test_ambient_audio_ownership.py` pause/resume and pending cleanup replay races; explicit Ambient Play also respects stronger lifecycle policy |
| Same route file `set_volume/update_config -> B.set_volume/update_config` | Configured volume/enable changes, may sync volume or stop owner / V or T / explicit config | Delegates to Ambient owned synchronization/stop; does not acquire generic manual volume authority | `_write_owned_volume` or `_stop_sonos_ambient` boundaries below; S | Config persists; no ownership reconstructed | Ambient suites; config is not permission to override yielded manual V |
| `B._evaluate`, `on_mode_change`, `weather_watch_loop`, `_start_sonos_ambient` | Automatic mode/weather source start / Q,T,V | Neutral proof, exclusive lease, eligibility/shutdown checked in physical fence; pending-start monitor retains ambiguous claims | `S.play_uri_if_unchanged -> _play_uri_if_unchanged_sync -> _play_uri_sync`; final proof/guard then volume/mode/source/Play; S | `load_from_db` retires old claim; no startup source inference | Ambient tests: stopped residue, late PLAYING, stale preflight, terminal progress, takeover during settle; covered |
| `B._swap_sonos_ambient`, `_replace_pending_start_locked` | Source replacement/replay / Q,T; optional V | Existing exact source claim; lease and physical fence; source-only fallback after volume yield | `S.play_uri_if_unchanged` or `play_uri_if_source_unchanged`; final respective proof + eligibility guard; S | Local replay intent only | Ambient tests: swap source-only, mute takeover, new Play/Resume during pending cleanup; covered |
| `B._stop_sonos_ambient`, `_pause_pending_start_exact`, `_pause_for_policy` | Pause owned source / Q,T; retire/paused claim / manual or policy | Exact source/transport claim + lease + fence; no Clear/Stop | `S.pause_if_playback_unchanged -> _pause_if_playback_unchanged_sync`; final proof and allowed guard; S | Shutdown uses abandonment instead of pause; paused claim local | Ambient tests: policy DND/Away, queue change during pause, shutdown/fence, pending cleanup barrier; covered |
| `B._sync_sonos_volume`, `_ramp_owned_volume`, `_write_owned_volume` (config/presence/loop callers) | Rendering steps / V with Q,T proof / autonomous owner | Exact playback evidence, surviving volume dimension, eligibility each step + fence | `S._set_volume_if_playback_unchanged_sync` full final fingerprint/guard then volume assignment; S | No ramp replay | Ambient tests: manual volume/mute and Away during ramp; no writes after yielded V |
| `backend/services/mode_volume_service.py:ModeVolumeService.on_mode_change -> _run_owned_ramp` | Music curves; Sleeping zero even stopped / V / autonomous opportunistic | Original request V epoch retained across setup/defer and compared with final lease-free `A.capture_opportunistic`; epoch + generation checked per step under `A.run_if_opportunistic`; TTS/Ambient leases block capture | `S.set_volume`; S; sleeps between steps outside lock | Tokens/generation local, no replay | `test_mode_volume_service.py`; new `test_sonos_writer_concurrency.py` uses actual authority and sync fake device. DND computed at setup, not each step; external app volume is not freshly fingerprinted: open policy/device-proof gate |
| `backend/services/music_assisted_playback.py:MusicAssistedPlaybackService.play_exact -> M.play_verified_candidate` | Exact ShareLink append, select source/track, Play / Q,T / explicit assisted request; never V | Durable idempotency claim and private request lock; trust/capability and lifecycle/device preflight reread, post-enqueue `_before_play` | `S._add_apple_music_share_link_sync` (ShareLink helper can AddURIToQueue); then `_play_queue_item_if_unchanged_sync` SetAVTransportURI/Seek/final queue object+generation/source/transport/mode/mute/volume proof/Play; S enqueue, F final | Pending retry becomes indeterminate; no replay or fabricated learning | `test_music_assisted_playback.py`, `test_sonos_apple_music_sharelink.py` enqueue guard/final setup source race/manual verification takeover. **Open central authority gap:** private lock is not A lock; no central lease/invalidation around append; final no-await transaction does not cover enqueue/verification awaits |
| `backend/services/away_manager.py:AwayManager._on_leave` | Pause if PLAYING / T / autonomous lifecycle | Durable Away persisted and suppression armed before status read; **no A lock or invalidation** | `S.pause`; S settles its own worker but does not serialize with A writers | Away restore arms suppression, not ownership | **Open unowned writer:** manual/TTS can interleave between read and Pause; decide lifecycle priority/lease invalidation contract before adoption |
| `M.on_mode_change` Away branch | Pause if PLAYING / T / autonomous lifecycle | DND entry gate; **no A lock or invalidation** | `S.pause` under wait_for; S settlement | No resume on Home; retirement remains non-destructive | **Open unowned writer:** duplicates lifecycle pause responsibility; decide owner and priority before changing; no new Stop/Clear |

## Side-effecting helpers and paths excluded from live guarantees

`S.play`, `pause`, `set_volume`, `next_track`, `previous_track` do not acquire A
themselves: safe use depends on the caller. `S.ramp_volume` likewise has no lease
or fingerprint and continues steps unless cancelled. Production ModeVolume uses
its own guarded ramp instead. `S.play_uri` validates a URI allowlist, which is
source validation, not ownership. `_play_uri_sync` may write volume and NORMAL
play mode before `device.play_uri`; the conditional wrappers prove the relevant
fields first but cannot undo a partially accepted command atomically.

`S.play_favorite` has two live queueable resolutions: saved Sonos playlists and
cloud favorite references with resources. With expected evidence both use
`_replace_queue_if_unchanged_sync`; without it, manual callers hold A around the
whole Clear/Add/`_shuffle_and_play` sequence and its saved-playlist retry
(retry Add/Play can duplicate an accepted append). `_shuffle_and_play` writes
SHUFFLE and selects a random index before `device.play_from_queue`. Unsupported
resource-less artist/station shortcuts return false with no playback fallback.
This is initial explicit replacement, not permission for destructive release.

`S.restore_playback` invokes third-party `Snapshot.restore`: hidden writes may
include Pause, source/queue reconstruction, track/time Seek, play mode, volume,
mute/EQ and Play/Stop. Its only repository caller is
`TTS._speak_without_ownership`; production bootstrap attaches A before starting
runtime tasks. The owned TTS path deliberately implements narrower explicit
restore actions; snapshot capture itself is a read. Do not assume compatibility
Snapshot restore has takeover protection merely because its worker settles.

Other non-production compatibility fallbacks when ownership is absent:
`TTS._speak_without_ownership` (play_uri, set_volume, Snapshot restore),
`B._start_sonos_ambient` (play_uri), `B._stop_sonos_ambient` (pause),
`ModeVolumeService._apply` (S.ramp_volume), M ordinary auto-play/pregame
(unguarded favorite), REST/guest/WebSocket wrappers (direct operation).
`S.play_apple_music_share_link` without expected queue size uses unguarded
`device.play_from_queue`; the live assisted caller always supplies expected size.
These are code-present mutation paths, not independently safe standalone APIs.
`backend/bootstrap.py` injects A into MusicMapper, Ambient, TTS and ModeVolume and
exposes it for ingress. No independent mute/group/join/unjoin writer was found.

`M._release_mode_audio_lease`, `M.close`, Ambient `shutdown`/abandonment,
TTS restart/close and assisted failure never earn destructive stale-source cleanup
authority. Weather MusicMapper suggestions, catalog/discovery/requests/curator,
learning, scene orchestration and AutomationEngine Sonos busy checks do not write
Sonos. GameDayService's audio executes through pregame mapper or celebration TTS;
no parallel Game Day device writer. Guest gateway/tunnel, MCP and Alexa are endpoint
clients/relays, not raw SoCo writers. Direct device calls were found only in S;
third-party Snapshot and ShareLink calls were traced separately above.

## Missing-test selection and bounded correction

Existing deterministic coverage already exercises manual song during TTS, manual
volume restore, Ambient takeover/pause/replay/settling, stale queue restart,
stopped residue, pregame lifecycle/DND/manual gap, exact learning session identity,
post-enqueue authority rejection, final Play source/transport takeover and manual
during assisted verification. Repeating those would add little evidence.

New `test_sonos_writer_concurrency.py` adds seven cases:

- Real A + ModeVolume + fake synchronous Sonos: manual volume between ramp steps
  prevents remaining writes and preserves an unrelated Q/T lease. Older ramp
  tests mocked `run_if_opportunistic` rather than exercising invalidation end to end.
- Initial asynchronous status-read barrier using real A and S with a fake device:
  dashboard manual V=7, stronger V owner acquired/released, newer mode, and an
  unchanged-request control. The first two failed before the bounded ModeVolume
  fix: manual writes were `[7, 25]` and the released stronger owner allowed `[25]`.
  Both now abandon setup; newer mode also abandons, while the control reaches 25.
  The request retains the epoch returned by its original invalidation, including
  across TTS defer. Final capture still proves lease freedom and per-step checks
  still hold the central lock; releasing stronger ownership cannot revive an old
  request. Compatibility without A and generation/DND/Sleeping/defer policy remain.
- Repeated task cancellation with a blocked fake worker, successful settlement.
- The same interleaving with worker failure after cancellation. Both prove manual
  entry remains blocked until settlement and cancellation reaches the caller.

The last case initially failed: `_settled_thread_call` let the shielded worker
exception escape before consuming `worker.result()`, so `S.play` converted deferred
cancellation to false. The minimal correction catches the settled exception at
the shield await and uses the existing result/cancellation path. It does not
change lease policy, timeout budget or external-controller guarantees, and never
releases a mutation boundary while its worker is still writing.

## Outstanding decisions and review gates

Do not adopt the two direct Away pauses or assisted enqueue into a guessed generic
lease policy in this candidate. #274/#276 need a decision on lifecycle ownership,
manual precedence, duplicate pause responsibility, assisted append participation
and cancellation/recovery after an accepted append. These are code-confirmed
decision-gated gaps; no assertion that they caused a live incident. The confirmed
ModeVolume setup epoch gap is closed in this candidate. Other ordinary mapper
policy changes during setup remain outside this bounded fix.
External-controller volume during mode ramps also needs a fresh-proof policy if
that guarantee is required. A central lock cannot make external read/write atomic.

#273 stale queue release and #274 broader physical authority tests remain gated;
retain the deliberate no-cleanup limitation. Previously accepted #279/#280/#281/
#9/#275 behavior is not reaccepted physically by these tests. Review the scoped
diff and authority findings before any separately authorized commit/merge/release;
deployment must use the release procedure and live acceptance separately.

## Validation

Using only `C:\Work\home-hub-project\main\.venv\Scripts\python.exe`:

- `-m pytest tests/test_sonos_writer_concurrency.py
  tests/test_sonos_mutation_serialization.py tests/test_audio_ownership.py
  tests/test_audio_ownership_ingress.py tests/test_sonos_playback_ownership.py
  tests/test_sonos_apple_music_sharelink.py tests/test_music_mapper_ownership.py
  tests/test_ambient_audio_ownership.py tests/test_tts_duck_resume.py
  tests/test_mode_volume_service.py tests/test_music_assisted_playback.py
  tests/test_learning_audio_source_trust.py tests/test_sonos_skip_detection.py
  tests/test_celebration_orchestrator.py -q`: **359 passed**, 117.67 seconds.
- Focused concurrency/service/policy suite: **57 passed**, 3.64 seconds.
- `-m ruff check backend/services/sonos_service.py
  backend/services/mode_volume_service.py tests/test_sonos_writer_concurrency.py`: **passed**.
- In-memory Python compilation of all three changed Python files: **passed**.
- Native Git `diff --check` plus no-index whitespace checks of both untracked files: **passed**.

Only the audit, focused new test module, ModeVolume setup epoch propagation/check,
and preserved four-line settlement correction are candidate changes. No app lifespan,
network/device call, production database,
tool installation, commit/push/merge/deploy or restart was used.


## #336 bounded departure adoption (uncommitted candidate)

This section supersedes the two Away matrix gaps above for this candidate only;
#337 assisted Apple Music central participation remains separate and unchanged.
No live/device acceptance or deployment is claimed.

Entry-path evidence: `/api/presence/geofence` and host Travel call
`AwayManager.handle_event("leave", ...)`. House State is projected from the
hard occupancy hold (`navigation_activity_policy.project_house_state`), rather
than an independent departure writer. Sleeping has its own override/TTS path;
weather music only suggests. Legacy `report_activity` and manual overrides can
still deliver a raw `away` activity callback through AutomationEngine. That
callback is not physical absence evidence: MusicMapper delegates **audio only**
to `AwayManager.on_audio_mode_change`, without persisting occupancy, arming the
lighting hold, issuing lights-off, or notifying. Its existing DND entry gate
remains. Thus no software activity gains new occupancy authority.

AwayManager uses independent process-local physical and semantic pause generations.
A physical departure captures explicit Q/T intent before the event lock or durable
write, commits Away, arms engine suppression, then asserts the full audio lifecycle
fence. Duplicate physical LEAVE shares only that physical transition's attempt.
Semantic Away retains a separate one-off conditional pause; it never establishes
occupancy, retires leases, changes durable provenance, or asserts the lifecycle
fence. A physical LEAVE invalidates pending semantic work and always creates its
own physical attempt: semantic Away -> manual Play -> physical LEAVE pauses the
music, because that Play predates departure. New explicit Q/T intent after physical
LEAVE starts cancels pending physical pause. Semantic mode exit cancels only its
own generation and cannot clear physical Away. Home ends the physical transition
without Play. Restore with a fresh ownership instance re-arms full transport
suppression and marks the physical attempt consumed without pause replay.
MusicMapper preserves leases at semantic Away entry and marks its requested mode
Away to cancel older auto-play setup. Bootstrap injects authority before tasks start.

`AudioOwnershipService.set_lifecycle_away` serializes activation against admitted
Sonos workers, retires only T from existing durable leases, and fences subsequent
autonomous T operations. Q/V/I remain independent. There is no new departure
lease, queue rewrite, Stop, Clear, retry, or elapsed-time/STOPPED ownership guess.
Transport retirement prevents pre-departure TTS restore even if Home arrives
before the clip finishes, including with `pause_music_on_leave=false`; volume
restore remains subject to its existing V/device proof. A failed audio provenance
save is logged while the in-memory fence stays active and lights-off continues;
restart re-arms from durable occupancy. Existing TTS abandonment/release handles
the interruption; no TTS architecture change is required.

Only `run_manual` with Q or T increments the event-loop-local explicit intent
revision before waiting for the shared lock, including before invalidation
persistence. V/I-only intentional adjustments do not cancel transport pause.
All current `invalidate_manual` callers are evidence-driven Sonos polling or TTS
surrender; these still invalidate leases/learning provenance but do not claim
explicit user intent. Ambiguous natural track advancement is not an explicit
Play; fresh preflight and final live source/transport proof decide pause eligibility. Departure evidence reads run outside both occupancy and audio locks.
`run_departure_pause` compares that original revision and the lifecycle revision
under the authority lock, ahead of ordinary autonomous leases. The settled
`pause_if_playback_unchanged` worker re-reads the full source/transport fingerprint
and checks the current intent/lifecycle guard immediately before Pause. A Home
transition cancels an old pending read; a subsequent Away cannot revive it.
A manual request during final proof can veto Pause before its own device write
is admitted. If Pause is already physically admitted, the worker settles before
manual Play runs, so the later manual write wins. Only bounded Sonos proof/write
work runs inside the departure authority operation; config, notifications, Hue,
and initial evidence reads remain outside it. There is no reverse acquisition
of the occupancy lock inside an authority operation.

These are participating HomeHub ordering guarantees. External Sonos apps do not
enter this lock or revision counter, and the final read/Pause is not device CAS.
The standalone AwayManager compatibility path without injected authority retains
its older best-effort behavior; production bootstrap always injects authority.

Deterministic coverage in `tests/test_away_audio_ownership.py` uses the actual
AudioOwnershipService and settled Sonos conditional helper with fake synchronous
devices, plus the existing TTS fake. It covers playing/paused/stopped/unavailable,
disabled setting, duplicate geofence/mode entries, manual Play during occupancy
persistence/initial read/authority admission/final synchronous proof, manual Play
while Away, Home and a newer Away while an old read waits, final transport
mismatch, failed reads, real worker timeout/cancellation/failure settlement,
provenance-store failure, restart no-replay, DND/Sleeping separation, independent
Q/V ownership, opportunistic T fencing, and TTS overlap with/without departure
pause and with Home before TTS completion. No app lifespan or production resources
are used. Validation runs disable DotEnvSettingsSource file reads before importing
application modules, so tests do not read `.env`.


Prior candidate validation (historical; insufficient to resolve the four review blockers):

- Related Away, authority/ingress, mapper, TTS, Sonos concurrency/serialization/
  playback proof, Ambient, ModeVolume, presence reconciliation and host Travel
  suites: **326 passed, 6 skipped**, 125.29 seconds. This run included 26 new
  departure cases; the final focused run after the delayed-claim guard and three
  additional cases: **29 passed**, 2.41 seconds.
- Final focused departure plus host Travel rerun: **39 passed, 6 skipped**,
  103.25 seconds. Five skips are existing Windows Git Bash teardown exclusions;
  one is the unavailable Bash hostctl transaction harness. No tool was installed
  or fetched. The shell harness needs the supported Linux/CI environment.
- Ruff across all five changed Python files, in-memory compilation, native
  `git diff --check`, and no-index whitespace check for the untracked test:
  **passed**. The existing FastAPI/httpx deprecation warning remains unrelated.
- HEAD remains `f64e295b0db670d97b7a5cbc0f1cccaa2fa96b40` on
  `sonos-away-pause-336`. Only four runtime Python files, this audit, and the new
  departure test module are changed; all remain uncommitted.


## #336 corrective bounded write

The earlier shared semantic/physical transition and global intent revision were
review blockers. The corrected behavior above supersedes those earlier candidate
claims. Added negative coverage proves independent semantic/physical cancellation,
semantic idle lease/provenance preservation, semantic TTS source and volume restore,
V/I-only adjustments at slow persistence/preflight, evidence-driven ambiguous track
surrender with fresh proof, and fresh-instance restart fencing. Existing physical
Home race, final proof takeover refusal, settlement and physical TTS tests remain.

No external Sonos CAS is claimed: a device/app command can still win in the gap
between final evidence read and Pause. No live/device validation was authorized.


Independent corrective review also found setup gaps beyond the original four:
REST/WebSocket Next/Previous now record explicit intent before learning-session
capture, passing the recorded revision into `run_manual` without counting twice.
MusicMapper publishes a per-callback revision at entry and rejects superseded
setup after initial awaits, queue preflight and authority admission. The revision
guard reaches the actual conditional Sonos playlist/cloud worker, after fresh
fingerprint proof and before the first queue write. Gated regressions exercise
learning capture, callback entry, queue/admission and real favorite lookup.
Semantic pause skips active I leases: otherwise pausing the TTS clip would
indirectly create external-paused evidence and invalidate transport restore.
Physical Away continues to outrank those leases and retires T as before.

The previous worker's "no remaining blockers" assessment was superseded by
external independent review bdd87f54b2d84d9aa69474172a99fdf7, which demonstrated
two P2 races still present after the prior write completed. The final bounded
correction below addresses those findings. This is code/fake-device evidence,
not commit or deployment authorization.
The corrective changed-file set consists of the existing candidate files plus
bounded Sonos REST/WebSocket ingress, the Sonos conditional favorite worker, and
the corresponding ingress/mapper test fakes. All changes remain uncommitted.


Corrective file audit (11 files total, including the preserved candidate):

- `backend/bootstrap.py`
- `backend/main.py`
- `backend/api/routes/sonos.py`
- `backend/services/audio_ownership.py`
- `backend/services/away_manager.py`
- `backend/services/music_mapper.py`
- `backend/services/sonos_service.py`
- `tests/test_away_audio_ownership.py` (untracked candidate test module)
- `tests/test_audio_ownership_ingress.py` (fake supports recorded ingress revision)
- `tests/test_music_mapper_ownership.py` (fake supports final worker guard)
- `docs/audits/SONOS_WRITER_AUTHORITY_2026_10_08.md`


Final corrective validation (existing main `.venv` interpreter; DotEnvSettingsSource
file reads disabled before pytest imports):

- Focused corrective Away/ingress/mapper run: **119 passed**, 23.16 seconds,
  before the final service-worker guard. The final related run below includes
  that guard and both new real-service favorite-lookup regressions.
- Final related Away, audio authority/ingress, mapper, TTS, Sonos concurrency,
  mutation serialization, playback proof, skip detection, favorite shuffle,
  play-mode reset, Ambient, ModeVolume, presence reconciliation and host Travel:
  **403 passed, 6 skipped**, 123.17 seconds. Includes all 49 focused departure
  regression cases. Five skips are existing Windows Git Bash teardown exclusions;
  one is the unavailable Bash hostctl transaction harness. No tool was installed.
- Ruff on all 10 changed Python files, in-memory compilation of those files,
  `git diff --check`, and the untracked test's no-index whitespace check: **passed**.
  The no-index check returns Git's normal difference exit code 1 without whitespace
  diagnostics. One existing FastAPI/Starlette httpx deprecation warning remains.
- Final HEAD: `f64e295b0db670d97b7a5cbc0f1cccaa2fa96b40`; branch:
  `sonos-away-pause-336`. The 11-file set above is the entire changed-file set.
  All changes remain uncommitted. No secrets, network fetch, live device action,
  commit/push/PR/merge/deploy, service/task restart, or cleanup was performed.

## #336 final bounded correction after external review

External review bdd87f54b2d84d9aa69474172a99fdf7 demonstrated two P2 races
in the preceding completed candidate. The earlier 403-pass result is a baseline,
not proof those races were absent.

- `AudioOwnershipService.run_manual` now compares a supplied explicit Q/T
  ingress revision to the current revision under the shared lock after loading,
  before lease invalidation, and again after awaited invalidation persistence,
  before calling the device operation. It never substitutes the current revision
  for the caller's captured revision. Superseded REST skips return False (route
  response `status=error`); WebSocket supplies `(False, None)` to preserve unpacking
  and suppress event/skip-learning logging. The optional failure shape defaults
  to False; generic callers without a supplied revision retain their behavior.
  V/I-only writes and evidence invalidation revision semantics are unchanged.
- The conditional favorite worker checks its guard immediately before
  `play_from_queue`, after queue append, queue-size lookup, SHUFFLE write, and
  random-index preparation. Both Sonos playlist and playable cloud-favorite
  branches use this worker. Unsupported cloud shortcuts return False without
  a Play URI fallback; the current implementation has no such fallback write.
  Direct manual favorite playback still shuffles and plays normally. Accepted
  queue contents remain retained on refusal; there is no rollback/delete.
  Existing settled-thread cancellation behavior remains intact.
- Twenty added deterministic, no-network fake-device cases cover REST/WS
  Next/Previous against newer Play/Pause at learning capture and persisted
  settings barriers (16), plus actual SonosService playlist/cloud workers blocked
  inside queue append or play-mode preparation while semantic Away completes
  with STOPPED evidence (4). They assert no old transport write, correct caller
  response shape, no stale success/skip event, no stale auto-play learning tasks
  or mode lease, and retained queue preparation. Capture-stage cases also prove
  the stale caller does not advance lease invalidation generation.

Final validation, using the existing main `.venv` interpreter and disabling
DotEnvSettingsSource file reads before pytest import, with cacheprovider disabled:

- Focused Away/ingress/favorite shuffle run: **89 passed**, 21.23 seconds.
- Final rerun of all 20 new race cases after adding generation/learning-task
  assertions: **20 passed, 49 deselected**, 18.35 seconds.
- Same related suite as the prior 403-pass baseline: **423 passed, 6 skipped**,
  128.28 seconds. Suites: Away, audio authority/ingress, MusicMapper, TTS
  duck/resume, Sonos writer concurrency/mutation serialization/playback proof/
  skip detection/favorite shuffle/play-mode reset, Ambient ownership/sound,
  ModeVolume, presence reconciliation, and host Travel. Five existing Windows
  Git Bash teardown exclusions and the unavailable Bash hostctl transaction
  harness remain skipped. The existing Starlette/httpx deprecation warning
  remains. The full repository suite was not run; this is the broad related run.
- Final Ruff check of all 10 changed Python files and in-memory compilation:
  **passed**. Tracked `git diff --check` and the untracked test's no-index
  whitespace check: **passed**, without whitespace diagnostics.

The final bounded diff inspection found no additional demonstrated P1/P2 blocker.
This is the worker's source/fake-device assessment, not a new independent external
review or live-health claim. An external app/device command may still race a
final guard and UPnP Play; external Sonos atomic CAS is not claimed. Linux/CI shell
harness validation remains a platform gate; no live-device validation was allowed.
#337 assisted ShareLink authority work remains outside this correction.

Final file audit remains exactly the same 11-file set listed above (10 tracked
modifications plus the preserved untracked departure test). HEAD remains
`f64e295b0db670d97b7a5cbc0f1cccaa2fa96b40`, branch `sonos-away-pause-336`.
All candidate changes remain uncommitted. No secret reads, network fetches,
tool installs, device APIs/physical actions, host administration, commit/push/PR/
merge/deployment, service/task restarts, or destructive cleanup were performed.


## #337 bounded Sandbox candidate (uncommitted, 2026-10-08)

Baseline: merged master `443f3ae0ee6d09b832605b248c93c81b0333b528`, branch
`sonos-sharelink-authority-337`, initially clean. This section supersedes the
ShareLink central-participation gap for this candidate only; it is not a deployed
or physical-acceptance claim. #337 remains open, as do #276/#274/#273. Existing
#272/#278 physical acceptance and the no-destructive-cleanup boundary remain.

Assisted requests now capture the explicit manual Q/T revision and MusicMapper
callback revision synchronously before their first await. After durable request
claim, candidate/trust re-resolution and neutral device/volume preflight, they
capture a shared lease-free Q/T epoch claim. Claiming advances only those epochs,
fencing older opportunistic continuations, and refuses existing Q/T owners,
including TTS overlays, Ambient, Game Day and MusicMapper. This is bounded
process-local transaction authority, not a durable playback lease, a manual
invalidation, or V/I authority. No claim is rehydrated on restart; the durable
assisted ledger still terminalizes interrupted requests without replay.

`MusicAssistedPlaybackService -> MusicMapper -> SonosService` remains the sole
handoff. The assisted mutation runner uses `A.run_if_opportunistic` for one
linearized setup operation: fresh admission preflight, settled ShareLink append,
accepted-item fingerprint, post-enqueue device/mode/manual fence, and bounded
synchronous source/track selection and final Play proof. The shared lock remains
held until the append worker actually finishes, including timeout/cancellation.
Post-enqueue callbacks do not reacquire A. Manual Q/T intent can still enter
synchronously while that lock is held, so the pending assisted Play is vetoed
before the later manual device operation obtains the lock. Explicit manual TTS
interruption acquisition also records Q/T intent before waiting for A; autonomous
TTS acquires normal interruption authority in lock order without manual privilege.

After setup, the lock is released for advancing-stream verification. Subsequent
manual intent, callback supersession, lease acquisition/release or Q/T invalidation
prevents stale success even if device verification reports an advancing stream.
Current physical Away, semantic inactive/Away, Sleeping, DND, Travel/Return,
TTS and Ambient policy is rechecked. Canonical played completion/learning uses a
separate short shared-authority operation and checks the original token/intent
again. There is no long verification lock, durable assisted lease, cleanup,
volume write, wake/resume, or software-derived physical occupancy. Autonomous
MusicMapper retains its existing neutral-start and guarded-favorite authority.

Side-effect recovery remains no-op: an accepted append, including append followed
by exception, is retained. Neither refusal, timeout, cancellation, unverifiable
Play nor takeover permits positional deletion, Clear, Stop or guessed restore.
A command already physically admitted may settle before a newer manual write;
that later participating write wins. External Sonos apps do not enter A or its
revision counters: neutral/final/stream proof remains best-effort read-then-write,
not atomic device CAS. Verification failure can leave already accepted Play
running; the request reports failure without destructive rollback. Current policy
checks do not introduce a general historical DND/event journal. TTS retains its
existing cloud-source restore refusal and exact eligible snapshot restore rules.

Deterministic device-free evidence uses actual A, MusicMapper dispatch, settled
Sonos mutation workers and synchronous fake SoCo, with in-memory SQLite only.
Added cases cover replacement/Play/Pause during enqueue, post-enqueue and stream
verification; worker timeout/cancellation settlement; verification cancellation;
queued autonomous/manual TTS admission and surviving interruption operations;
physical/semantic Away, Sleeping, DND, TTS, Ambient and Game Day transitions;
Away-to-Home callback supersession; accepted append plus exception; shared-owner
admission priority; older autonomous token fencing with V preservation; missing
authority; and idempotent retries with no replay or fabricated learning. Existing
ShareLink suites retain exact-link, play-mode, mute/volume, external setup race and
advancing-stream proof coverage. Existing TTS suites validate playback/restore.

Validation uses the existing main `.venv` interpreter. DotEnvSettingsSource file
reads are disabled before pytest import; cacheprovider is disabled. No app lifespan,
network/device calls, tool installation, secret reads or environment changes:

- Broad related run: **487 passed, 0 skipped**, 74.01 seconds. Includes assisted,
  ShareLink, authority/ingress, Away, TTS, MusicMapper, Sonos writer concurrency,
  mutation serialization, playback proof, favorite shuffle, play-mode reset,
  skip detection, URI allowlist, Ambient and ModeVolume policy/service suites.
- Two final added cases: **2 passed, 78 deselected**, 2.49 seconds. Thus all
  **489 selected test cases** passed across these runs. One existing
  Starlette/httpx deprecation warning remains in the broad run.
- Ruff on all five changed Python files, UTF-8/BOM-aware in-memory compilation,
  and `git diff --check`: passed. The full repository suite was not run.

Exact candidate file set (six tracked modifications):
`backend/services/audio_ownership.py`,
`backend/services/music_assisted_playback.py`,
`backend/services/music_mapper.py`, `backend/services/sonos_service.py`,
`tests/test_music_assisted_playback.py`, and this audit. Source review checked
manual precedence, lock/callback acquisition, verification separation, authority
retirement/restart and no-cleanup paths. No commit, push, PR, merge, deployment,
service/task restart, real device action, host administration, issue mutation or
cleanup was performed. No external independent review or live-health claim.

## #337 corrective follow-up (uncommitted, 2026-10-08 Sandbox)

Fresh source reconfirmed all three reviewer findings. Prior writer
`b532080b6728466bb30ecfffdd4e88ac` was verified `completed`, exit 0,
`worker_alive=false`, including its saved attempt result. The registry's only
active writer for this workspace is this corrective task
`b684c5cfd43b41d6b2ec9b252ba4f979`; its thread matches `CODEX_THREAD_ID` and
its worker PID is an ancestor of this shell. No duplicate worker was launched.
HEAD remains base `443f3ae0ee6d09b832605b248c93c81b0333b528`; the existing six-file
uncommitted candidate was preserved. This section supersedes the earlier
candidate's claims about autonomous queued TTS and completion-await fencing.

- P1 interruption ingress: `acquire_interruption` advances process-local
  monotonic epochs for exactly its requested dimensions synchronously before
  awaiting A. Autonomous TTS does not advance manual intent. No pending count,
  reservation or durable lease is created by the announcement; refused/cancelled
  acquisition invalidates old tokens but does not block future tokens. The
  assisted `still_current` checks the original Q/T epochs after post-enqueue
  preflight, immediately before the synchronous final setup/Play transaction.
  There is no event-loop yield between this check and Play. Existing established
  overlays, reserved-owner refusal/manual preemption and lifecycle semantics
  remain intact. Epoch ingress does not itself invalidate durable owners.
- P1 completion linearization: advancing-stream verification is the physical
  history boundary. If authority changes during completion SELECT, a played
  ledger row is retained with `played_learning_suppressed_authority_changed`
  and no candidate learning event is staged. If intent changes during commit or
  refresh, a narrow compensating transaction deletes only the newly inserted
  canonical event by its retained ORM primary-key identity and updates this
  exact assisted request's reason. Checks run directly after commit and again
  after refresh. Unrelated events, including same-title/same-mode evidence,
  survive. Uninterfered success still commits ledger and learning atomically;
  verification failure never enters played completion. Duplicate retries return
  the terminal result without replay or new learning.
- P2 reporting: request-local admission/verification rejection takes precedence
  over queue-size inference and reports `playback_authority_changed`. Manual
  Pause can finish while stream verification is blocked; a verifier returning
  success cannot fabricate preference learning or change this reason to
  `playback_start_unverified`. Accepted append and idempotent retry are preserved.

`claim=True` remains lease-free Q/T epoch supersession: it fences older autonomous
tokens while preserving V authority, durable TTS/manual priority and restart
behavior. Verification runs outside A. Existing worker cancellation/timeout tests
prove A remains held until the append actually settles and later manual work can
progress, without deadlock or positional queue cleanup. Physical and semantic
Away, Sleeping/DND, lifecycle callbacks, Ambient/Game Day, startup volume/mute,
external queue/source/transport proof and #336 regression suites remain selected.

New deterministic tests use real `TTSService._speak_with_ownership` and central
interruption acquisition with fake prepared speech while the real settled
ShareLink append is blocked. They never set `is_speaking` manually, assert TTS
is waiting before that flag changes, and cover snapshot refusal, reserved-owner
acquisition refusal, cancellation, ordinary/Ambient/Game Day transitions, retained
append, no assisted Play/learning, unchanged autonomous manual revision and no
leaked claims. Completion SELECT/commit/refresh barriers assert one assisted row,
no attributed learning, preservation of unrelated same-candidate evidence and
stable repeat results. A successful-verifier/Pause test asserts the precise P2
reason. Earlier queued-TTS tests now require zero assisted Play before verification
for autonomous as well as explicit manual TTS.

Accepted boundaries: this is event-loop-local HomeHub authority, not external
Sonos CAS. A nonparticipating app may race final UPnP reads/Play. The learning
compensation is bounded completion-time correction, not a crash-atomic second
transaction: process death/cancellation or DB failure between first commit and
compensation can leave the initial event, and an independent reader/cache could
observe it transiently. Crash-proof attribution or downstream cache retraction
would require a separately gated product/storage decision; no schema migration,
generalized evidence deletion or stronger guarantee is claimed here. No speaker
rollback, Clear/Stop, positional deletion, volume write or guessed restore was
added. No physical acceptance, Linux/CI harness or independent follow-up review
is claimed; those remain release gates where applicable.

Final corrective validation uses the existing main `.venv`, with
`DotEnvSettingsSource._read_env_files=lambda self:{}` installed before pytest
import and cacheprovider disabled:

- Focused assisted suite: **93 passed**, 11.07 seconds.
- Final wide relevant suite: **502 passed, 0 skipped**, 53.26 seconds. The 19
  modules cover assisted, Apple ShareLink, audio authority/ingress, Away audio,
  TTS duck/resume, MusicMapper and ownership, Sonos writer concurrency, mutation
  serialization, playback ownership, favorite shuffle, play-mode reset, skip
  detection, URI allowlist, Ambient ownership/sound, ModeVolume policy/service.
  One existing Starlette/httpx deprecation warning remains.
- Ruff on all five candidate Python files, UTF-8/BOM-aware in-memory Python
  compilation and `git diff --check`: **passed**. Full repository suite not run.

Final tracked diff is exactly the existing six-file set:
`backend/services/audio_ownership.py`,
`backend/services/music_assisted_playback.py`,
`backend/services/music_mapper.py`, `backend/services/sonos_service.py`,
`tests/test_music_assisted_playback.py`, and this audit. The prior MusicMapper
edit is preserved without additional corrective edits. No untracked project files
were added. All changes remain uncommitted. No secrets/.env reads, network fetches,
installs, host administration/Host Bridge mutation, service/task restarts, real
speaker actions, commit/push/PR/merge/deploy or destructive cleanup occurred.

### Bounded post-review corrective write: P2 resolved, P1 remains blocking

This section supersedes the preceding completion-safety and readiness claims.
Before editing, registry Status confirmed both former Write
`b684c5cfd43b41d6b2ec9b252ba4f979` and independent Read
`a5b73b2daf3241cabe972298787cdf41` completed, exit 0, worker_alive=false.
The independent final review was read. HEAD remains
`443f3ae0ee6d09b832605b248c93c81b0333b528`, with the same six-file candidate.

P2 is corrected: SonosService now evaluates verification_guard after a false
stream-verification result, before returning failure. New authority rejection
therefore takes precedence over retained-append inference. Deterministic tests
exercise the real `_verify_queue_playback_started` with a blocked fake physical
sample, manual Pause while verification is outside the authority lock, and a
PAUSED_PLAYBACK sample returning false. The accepted queue append remains,
learning is absent, and duplicate retry does not enqueue again. A companion
case without HomeHub manual ingress retains playback_start_unverified; the
existing successful-verifier takeover case remains covered.

P1 is **UNRESOLVED / BLOCKING**. Two strict expected-failure acceptance tests
persist completion transaction 1, then inject (a) manual ingress during commit
and a failed compensating commit, or (b) manual ingress plus failed refresh.
Both check same-service and recreated-service duplicate retries, historical
played status, one request row and exactly one enqueue before checking absence
of false positive evidence. Running with --runxfail fails exactly the final
no-positive-event assertion in both cases. These are known failures, not passes.
The previous completion implementation is preserved; no durable safety fix is
claimed. The candidate is **not ready for acceptance**.

Storage gate: inspection of models.py, database.py migrations, async session
handling, idempotency and MusicTaste's event aggregation shows the ledger has
no learning-event link/attribution state; MusicTaste accepts every manual play
event without consulting that ledger. The existing session_id/ownership_lease_id
columns describe #275 owned playback, not assisted-request attribution. Merely
adding an exact request identifier or first committing a neutral pending event
does not close the promotion-commit race: synchronous ingress can still arrive
during the awaited commit that makes the event positive. Retrying compensation
also cannot prevent readers observing the original durable positive event when
the database continues failing or the process dies.

The exact next gate is approval of an attribution/linearization contract that
keeps unresolved evidence ineligible for every learning consumer while preserving
uninterrupted successful positive learning and historical played status. This
may use explicitly specified new semantics in existing columns plus coordinated
reader changes, or a request-scoped storage relation/migration; a pending marker
alone is insufficient. A durable authority-ordering or serialized persistence
boundary must define how promotion is made safe. This exceeds this six-file
write's existing product/storage contract and is intentionally not invented here.
No schema migration was added or executed, and no unrelated event deletion or
Sonos rollback was introduced. External Sonos remains outside HomeHub CAS.

Post-review validation: final focused assisted suite **95 passed, 2 xfailed**,
14.68 seconds. The same 19 affected modules listed in the preceding
corrective validation completed with **504 passed, 2 xfailed**, 60.73 seconds,
and the existing Starlette/httpx deprecation warning. Explicit --runxfail on
the two P1 acceptance cases yielded **2 failed**, both at durable positive
evidence after retry, confirming the unresolved blocker. Ruff on all five
candidate Python files, UTF-8/BOM-aware in-memory compilation and git diff
--check passed. DotEnvSettingsSource._read_env_files was disabled before pytest
import; bytecode writes and pytest cacheprovider were disabled. No full-suite,
Linux CI, independent new review or physical acceptance is claimed.
Only sonos_service.py, test_music_assisted_playback.py and this audit received
additional post-review edits. Exact final status is the original six modified
tracked files, with no untracked files. No commit, network fetch, install,
device/service action, secrets/.env read or other prohibited action occurred.


### Approved #337 verification boundary corrective write (2026-10-08)

This section supersedes the preceding P1 storage blocker, strict-xfail acceptance
claims, and completion-time learning compensation semantics. Anthony explicitly
approved confirmed advancing-stream playback under current authority as the
positive preference-learning boundary. A takeover before or during verification
suppresses played success and learning; manual Play/Pause/queue replacement after
verification controls future transport without erasing that historical choice.

`play_exact` checks authority synchronously on successful verifier return, before
any completion DB await. The positive observation is frozen there. Completion
SELECT, commit and refresh no longer consult future authority. The played ledger
and canonical manual `play` SonosPlaybackEvent persist in one SQLAlchemy commit;
request-specific compensating deletion and second commit are removed. Completion
does not hold the Q/T authority lock across DB awaits, so later manual transport
can finish immediately. No persistent Q/T lease, resume, queue deletion, or
provider/app rollback is introduced. MusicTaste event categories remain unchanged,
including legacy manual play evidence without session_id.

The two strict xfails are replaced by passing acceptance cases covering a single
commit despite late manual ingress and durable positive history despite failed
refresh. A first completion commit failure leaves the pre-existing pending claim
and no partial positive event; duplicate recovery becomes indeterminate without
device replay. Same-service and recreated-service retries are checked. Completion
SELECT/commit/refresh barriers cover actual fake manual Pause, Play and queue
replacement, unchanged unrelated evidence, exactly one append/event, no forced
resume or positional deletion, and no leaked lease. Existing before/during-proof,
false-verifier manual Pause, cancellation/settled worker and real pending TTS
pre-lock fence coverage is retained.

Residual boundary: DB/process crash after real verification but before commit may
leave pending/no positive evidence. Recovery must not invent an event or replay
the device operation. Sonos and the DB do not share a durable atomic transaction;
external apps remain outside HomeHub CAS. No schema migration is needed or added.
Linux CI, physical acceptance and the subsequent independent review remain
separate gates; no production health or physical acceptance is claimed.

Approved-boundary validation: final focused assisted module **104 passed**
(14.30s). The 19 affected audio modules **513 passed, no xfails** (56.67s),
with the existing Starlette/httpx deprecation warning. The final focused rerun
strengthened first-commit failure by flushing ledger and evidence before injected
failure, then checking durable pending/no-event state before retry. Ruff on all
five modified Python files and BOM-aware in-memory compilation passed after that
change; `git diff --check` passed. `.env` loading was disabled before pytest
import; Python bytecode and pytest cacheprovider were disabled. Only assisted
service, assisted tests and this audit received additional edits in this write;
the other three preserved Python candidates remain unchanged. Final Git state
is the same six modified tracked files, no untracked files, original branch/HEAD.
Local self-review found no remaining blocker under the approved contract.
All work remains uncommitted; no network, installs, secrets reads, production DB,
physical devices, Host Bridge, restart, merge/rebase, publish or cleanup actions.


### Review-blocker follow-up: synchronous proof freeze (2026-10-08)

This section supersedes the preceding self-review claim: independent Read
`a5cbea23614c49818f2298954a9e6b81` identified an awaited shared-lock guard
between successful stream verification and authority acceptance. Registry Status
confirmed that Read and Write `1b802783dad84d13b3c50722c8da4bf3` completed,
exit 0, worker_alive=false. Git confirmed original HEAD and six modified files.

P1: SonosService now accepts an opt-in synchronous verification_boundary_guard,
forwarded by MusicMapper. Immediately after the production verifier returns,
with zero intervening await/suspension, assisted playback captures Q/T epochs,
manual ingress revision, mode request revision and synchronous lifecycle/mode/
DND/TTS/Ambient policy predicates. The result is frozen there; successful
completion never rereads future authority. A false verifier still invokes the
synchronous callback to distinguish manual takeover from unverified playback,
but cannot report played. Existing async verification_guard remains supported
when the boundary callback is absent. The opt-in callback replaces that awaited
gate; it never reacquires the shared lock. Append/final Play continue under the
shared authority lock with settled enqueue and existing physical fingerprints,
volume/mute checks and trust policy. No storage schema or authority privilege
was expanded; played ledger and positive event remain one atomic DB commit.

P2: completion SELECT/commit/refresh barriers and first-commit/refresh-failure
cases now use the production _verify_queue_playback_started and production
_playback_start_sample_sync on the existing fake SoCo device, rather than an
unconditional successful verifier. Exact queue object/generation/count, selected
queue source/track, NORMAL, guarded volume, mute, PLAYING and position advancement
are read by production code. A new deterministic sample barrier holds a real
volume-only V/I authority transaction while advancing proof completes. Pause
ingress after synchronous acceptance but before volume-lock release preserves
historical played and exactly one learning event; Pause remains effective after
the lock releases. The mirror ingress during proof rejects success and learning
even if physical advancing samples remain valid while Pause waits for the lock.
Both retain the accepted append, issue only one Play, avoid Clear/deletion and
check idempotent retry. Legacy async guard success and false-source verification
are checked separately. Existing false-verifier Pause classification and
physical nonadvancement/source/queue/volume rejection tests remain passing.

The Sonos/DB crash gap remains: proof followed by a failed first commit leaves
pending/no event; failed refresh after commit leaves durable played/evidence.
Recovery never fabricates learning or replays playback. External controllers
remain outside HomeHub conditional authority. Independent final read-only
review and physical acceptance remain separate gates.


Follow-up validation: focused assisted + exact ShareLink **130 passed** (23.60s);
the same 19 related audio modules **517 passed** (79.63s), no xfails, with the
existing Starlette/httpx deprecation warning. Ruff on the five candidate Python
files, UTF-8/BOM-aware in-memory compilation and final git diff --check passed.
Both pytest runs disabled DotEnvSettingsSource._read_env_files before importing
pytest, disabled bytecode writes and disabled cacheprovider. Full repository
suite, Linux CI, production health and physical acceptance are not claimed.

Additional follow-up edits are limited to assisted service, MusicMapper,
SonosService, assisted tests and this audit. The existing audio_ownership.py
candidate is preserved. Final state is exactly the original six modified tracked
files, no untracked additions, branch/HEAD unchanged. All changes remain
uncommitted. No secrets/.env reads, network fetches, installs, production/device
writes, host administration/Host Bridge mutation, restarts, reset/rebase,
commit/push/PR/merge/deploy or destructive cleanup occurred. No remaining blocker
was found in local validation under the approved contract; independent final
read-only review follows.
