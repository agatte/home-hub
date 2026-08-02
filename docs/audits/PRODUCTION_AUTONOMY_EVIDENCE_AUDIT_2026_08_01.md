# Home Hub Production/Autonomy Evidence Audit

**Audit window:** 2026-08-01, approximately 20:06–20:26 EDT; production clock observed at 20:25:55 EDT.  
**Scope:** read-only repository, deployment, GitHub issue, database, service, endpoint, process, scheduled-task, and bounded journal inspection.  
**Disclaimer:** This dated evidence snapshot is point-in-time evidence and an implementation handoff. It is not permanent proof of production health and does not replace `docs/PROJECT_SPEC.md`.

## 1. Executive verdict

Production is sufficiently understood to define and begin the next implementation gate, but not to enable new autonomous Scene Curator behavior. Existing low-consequence lighting paths are deployed and mostly operating; autonomous behavior as a whole is not yet trustworthy because capability health is not equivalent to backend health and process-derived activity can still outrank room evidence. The largest evidence gap is a durable, operator-visible capability/degraded-decision record: `/health` is green while audio has never reported, the ambient monitor is repeatedly restarting with no microphone, and current mode/explanation does not retain all stale inputs, owners, vetoes, and actuator results.

## 2. Revision and deployment alignment

| Revision | Evidence |
|---|---|
| Local `master` | `aa006aa75568eb742ff26e71f8a641871d73fee0` — `Reconcile Home Hub product direction` |
| Remote `origin/master` | Same hash from `git ls-remote origin refs/heads/master` |
| Production checkout | `ad1c5be19a18372c24910802f1cd1d9689f85166`; clean; `.last-deployed-sha` matched; `/health` build id `cb4318e` |
| Alignment | Local and remote align; production is behind local/remote. No drift was repaired. |

Deployment is documented in `.claude/CLAUDE.md:49-53` as Latitude (`192.168.86.210`), Git fast-forward deployment via `scripts/deploy.sh`, and `/health` verification. Active components include FastAPI, camera, Hue, Sonos, desktop agents, scheduler, Windows supervisor, and Latitude services. Retired Claude loops and disabled tasks are historical. Projector worktree `a075399` is not deployed.

## 3. Capability-health matrix

| Capability | Repository | Configured | Deployed | Live evidence | Classification | Main risk |
|---|---|---|---|---|---|---|
| FastAPI/backend | Present | Loaded | Yes (`ad1c5be`) | `/health` green at 20:12/20:21 EDT | VERIFIED HEALTHY | Aggregate health is incomplete |
| Latitude camera/couch | CameraService/PresenceFusion | Enabled, unpaused | Yes | 2 s polling; absence; lux 132.9; source ages <2 s; couch anchor ~95 min old | VERIFIED DEGRADED | Couch evidence/anchor can stale |
| Hue | Poll/apply paths | Configured | Yes | Connected, breaker closed, recent writes | VERIFIED HEALTHY | Manual replacement not fully reconciled |
| Desktop/desk | pc-agent/fusion | Enabled | Yes | Supervisor online; activity heartbeat 4 s; silence 176 s | VERIFIED DEGRADED | Process activity may outlive presence |
| Bedroom lux | LuxChannel | Calibrated | Yes | Fresh value | DEPLOYED — HEALTH UNKNOWN | No freshness in status |
| Screen sync | ScreenSyncService | Enabled | Yes | Watching sync current at 20:21:28Z | VERIFIED HEALTHY | Ownership not unified |
| Sonos | Service/MusicMapper | Connected; autoplay mostly off | Yes | Reachable/stopped/breaker closed | DEPLOYED — HEALTH UNKNOWN | `_connected` can be false-positive |
| Weather/time | Weather client | Configured; ambience off | Yes | GET `rain/OK`; no age | VERIFIED DEGRADED | Stale weather can influence lighting |
| Audio/ambient | Ambient/source trust | Autoplay off | Yes | 12 restarts; mic unavailable; audio never reported | VERIFIED DEGRADED | False-green/fail-open trust |
| PresenceFusion | Four-lane fusion | Active | Yes | Desktop/Latitude fresh but absent; zone null | VERIFIED DEGRADED | Authority hard to explain |
| Away/geofence | AwayManager | Home; suppression false | Yes | Home; no recent event | DEPLOYED — HEALTH UNKNOWN | Not exercised live |
| ML/rules/learner | Shadow/suggestion gates | Predictor shadow; rules suggestion-only | Yes | Shadow/learner rows; no promotion | DORMANT/DISABLED | Shadow is not autonomy health |
| Remediation | Watchdog | Enabled, autonomous false | Yes | Propose-only; no recent action | DORMANT/DISABLED | No self-healing |
| Projector | Separate worktree | Target/research | No | No master implementation | TARGET/RESEARCH NEEDED | Exclude from slice |
| Mood/Social | Manual/shadow | Mood ring off; Social manual | Manual only | No automatic inference | DORMANT/DISABLED | Signals not trusted |

## 4. Autonomy-path matrix

| Automatic path | Trigger | State owner | Gate/veto | Current enablement | Failure behavior | Classification |
|---|---|---|---|---|---|---|
| AutomationEngine lighting | Mode/activity; 60 s loop | AutomationEngine | DND/away/manual/freshness/priority/dwell | Enabled | Hold/defer/safe fallback | VERIFIED DEGRADED |
| Desktop/process mode | pc-agent report | Desktop/fusion | 300 s freshness/desk veto | Enabled | Reject stale; authority risk remains | VERIFIED DEGRADED |
| Camera room presence | Latitude frame/pose | Camera/PresenceFusion | 300 s freshness/hysteresis | Enabled | Absence/unknown | VERIFIED DEGRADED |
| Transit/path | Stationary-zone transition | TransitLightingService | 10 s absence/edge/latch/protected lights | Enabled | Dedup/neutral CT | CODED — DEPLOYMENT UNVERIFIED |
| Desk-exit kitchen | Desk departure | Automation/transit | Zone/debounce/protected lights | Enabled | Skip/dedup | DEPLOYED — HEALTH UNKNOWN |
| Screen sync | Fresh desktop frames | ScreenSyncService | 8 s freshness; L2/L5 owner | Enabled | Stop/restore caps | VERIFIED HEALTHY |
| Weather lighting | Weather/time | AutomationEngine | Mode/time/multiplier | Code enabled; ambience off | Defaults | VERIFIED DEGRADED |
| Ambient-relax | Idle/absence 600 s | Automation/Ambient | DND/Sonos/attendance/suppression | Dormant | No playback | DORMANT/DISABLED |
| MusicMapper playback | Mode callback | MusicMapper/Sonos | Away/DND/autoplay/favorite | Social only | Skip/log | DORMANT/DISABLED |
| Away/arrival | Authenticated geofence | AwayManager/VibeRouter | Auth/suppression/pending vibe/DND | Enabled; no pending vibe | Persist/apply home | DEPLOYED — HEALTH UNKNOWN |
| Late-night rescue | Late-night idle/absence | AutomationEngine | DND/away/fresh replacement | Enabled | Veto/restore gap | VERIFIED DEGRADED |
| Sleep/wake | Mode/time/input | Sleep watcher/routines | 600 s local-input veto; morning off | Sleep active; morning off | Hold/skip | DEPLOYED — HEALTH UNKNOWN |
| GameDay/celebration | Game state | GameDay | Schedule/state | No current game | Skip | DORMANT/DISABLED |
| Learned rules | Idle evaluation | RuleEngine | Suggestion-only/cooldown | Reachable | Suggest/log | DORMANT/DISABLED |
| Remediation | Trust failure | Remediation | Whitelist/propose-only | Propose-only | Record proposal | DORMANT/DISABLED |
| TTS/chime/Alexa | Explicit/arrival/game | TTS/notifications | Auth/DND/gates | Available; not triggered | Error/log | DEPLOYED — HEALTH UNKNOWN |
| Projector/guest/Social | Manual/target | Separate routes | Auth/target | Projector target; others manual | No automatic actuation | TARGET/RESEARCH NEEDED / DORMANT |

This distinguishes reversible lighting from higher-consequence music, speech, sleep/shutdown, projector, and explicit-away behavior. No apartment effect was triggered.

## 5. Current-state ownership map

- **Room presence:** Latitude owns couch evidence; desktop owns desk; PresenceFusion arbitrates fresh lanes. Physical evidence must outrank process activity (`docs/PROJECT_SPEC.md:79-94`).
- **Apartment away/home:** AwayManager owns authenticated iOS geofence; current state home.
- **Activity/mode:** AutomationEngine; final sample `watching`, source `process`.
- **Lighting:** Hue applies bridge state; AutomationEngine, transit, and screen sync are separate owners.
- **Music:** Sonos reachability/playback; MusicMapper mapping; playback stopped.
- **Mood:** Manual/opt-in shadow; no trusted automatic authority.
- **Social:** Explicit/manual routes; automatic inference target-only.
- **Arrival:** AwayManager plus pending-arrival-vibe/VibeRouter; none pending.
- **Sleep/wake:** Sleep watcher/scheduler; morning disabled; sleeping has local-input veto.

## 6. Degraded-context findings

Camera and desktop signals use 300 s freshness, but no complete capability snapshot is exposed. Camera polled while couch/zone evidence was absent and the face anchor was ~95 minutes old. Desktop activity was fresh, but supervisor silence was 176 s and agent heartbeats uneven. Ambient repeatedly restarted without a microphone while health remained green; audio was trusted only because it had insufficient samples. Weather returned `rain/OK` without age. Sonos reachability can be falsely positive because `_connected` is not identical to successful status polling.

DND, stale semantic replacement, screen-sync freshness, transit latching, neutral CT fallback, and propose-only remediation fail safely. Process-derived mode, stale weather, and incomplete actuator/manual explanations can silently continue. `/health`, pipeline, agent-health, and state APIs expose fragments, not all stale inputs, owners, vetoes, skipped reasons, or applied results.

## 7. July incident reconciliation

`docs/INCIDENT_2026_07_DESKTOP_INACTIVE_LIGHTING.md` records P0 completion on 2026-07-31: semantic freshness gate; defer user-mode expiry without fresh replacement; suspend/restart idle dwell; transit edge/latch; neutral CT fallback. Evidence is commit `cb4318e`, tests `TestDesktopUnavailableLightingPolicy` and `tests/test_transit_lighting_service.py`, and post-deployment rows. No current P0 regression was found.

P1 remains capability health/degraded-context observability: desktop activity/desk/lux/audio/screen-sync/living-room freshness, room sensors over PC activity, actor/intent normalization, and freshness/owner/veto explanations. Related issues #74, #81, #109, #110, #116, #117. Green backend health can conceal failed audio; process evidence can outweigh fresh physical absence. #109’s structural fix is shipped; stationary validation remains.

## 8. Living-room slice blockers

1. A room-local capability/authority gate must distinguish fresh Latitude couch evidence, stale/unknown camera state, desktop activity, and physical absence before Scene Curator actuation.
2. A durable operator-visible degraded/explainability record must include owner, freshness, confidence, veto/suppression, skipped reason, last actuator result, and manual replacement.

These are the only hard blockers. Hue and camera polling are not blockers; projector, arbitrary Apple Music, Social, and future mood classification are outside the slice.

## 9. Parallel supporting work

Continue #81 desktop freshness, #109 transit stationary validation, #110 late-night rescue observability, #116/#117 fusion/predictor semantics, #74 healed-outage observability, and #79 ambient stream health in parallel. Music Curator, Winding Down, mornings, Social/events, guest systems, kitchen fallback, and projector remain later/target work.

## 10. Existing issue mapping

Reuse/refine #81, #109, #110, #116, #117, #74, and #79. #107 away/welcome is substantially shipped; remaining walk test/NL scope is separate. #36/#40 overlap later scene/music work. #120 is watcher-specific historical phantom-playing diagnosis, not current Sonos proof; #93 is closed historical override-rate work. #125/#124 are closed; #35 is speculative/manual Social. Do not create an umbrella issue until scope is non-duplicative.

## 11. Recommended next implementation gate

Implement one **shadow-only living-room `CapabilitySnapshot → DecisionContext` gate** aggregating camera zone/posture/lux freshness, desktop/desk freshness, screen-sync freshness, Hue/Sonos reachability, weather age, DND/away/manual vetoes, and ownership without changing actuation.

Acceptance criteria: deterministic fresh/stale fixtures; physical evidence outranks stale process evidence; optional weather/audio absence explicit; each shadow/skipped decision records reason, owner, ages, confidence, vetoes, intended actuator; no light/music/TTS/projector calls; degraded state visible. Likely symbols: `AutomationEngine`, `PresenceFusion`, `CameraService`, `lux_channel.py`, health/status routes, decision logging. Validate focused tests and read-only endpoint/DB samples. Deploy separately later, then observe 24–48 hours before new auto-apply.

## 12. Unverified items

Not established safely: long-window uptime; full camera history or physical couch occupancy; production secret values; complete topology; every Hue acknowledgement after manual replacement; Sonos error transitions; microphone recovery; real arrival/away and sleep/wake exercises; projector, arbitrary Apple Music, Social inference, and future mood classification. Exact evidence requires a subsequent bounded read-only production window with capability heartbeats and actuator acknowledgements.

## 13. Commands executed

Repository/Git: `git branch --show-current`, `git status --short`, `git log -1 --oneline`, `git diff --check`, `git worktree list`, `git ls-remote origin refs/heads/master`, `git show`, `git diff`, `rg`, and bounded reads. Production: documented SSH alias; read-only Git revision/status/clock; GET `/health`, automation status/pipeline/agent-health, camera, weather, ambient, Sonos, away, remediation, personality/settings; bounded `journalctl`; process and scheduled-task status; bounded SQLite `SELECT` counts/newest timestamps/samples. GitHub: `gh issue list --state all` and relevant `gh issue view`. No POST/PUT/PATCH/DELETE, deploy, restart, repair, migration, database write, GitHub write, or apartment actuation occurred.

## 14. Git/state confirmation

At 2026-08-01 20:25:55 EDT, local `master` was clean at `aa006aa`; diff check was clean; worktrees unchanged; remote `master` resolved to `aa006aa75568eb742ff26e71f8a641871d73fee0`. Production remained clean at `ad1c5be19a18372c24910802f1cd1d9689f85166`. No repository file, Git state, production state, database, or GitHub state changed during the audit.