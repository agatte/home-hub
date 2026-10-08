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
