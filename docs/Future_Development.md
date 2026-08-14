# Home Hub Future Development Index

> **Status:** Non-authoritative idea and GitHub-issue index.
> **Last reviewed:** August 14, 2026.

Cross-system product policy and product direction live in the
[Product Experience Contract](PROJECT_SPEC.md#product-experience-contract--august-14-2026).
This file is an index, not a second specification or a priority mechanism.
Current GitHub issue contracts describe the bounded work; committed code and
live verification are required for claims that something is shipped or healthy.
Historical issue bodies, external memories, and retired watcher runbooks are
not authoritative inputs.

Open issues use `priority:p0` through `priority:p3`, `horizon:now`, `next`,
`later`, or `parked`, and `effort:small`, `medium`, or `large`. Legacy Tier
priority semantics are historical only.

## Canonical issue map

| Workstream | Current issue coverage | Current boundary |
|---|---|---|
| Production and autonomy | [#131](https://github.com/agatte/home-hub/issues/131), [#116](https://github.com/agatte/home-hub/issues/116), [#117](https://github.com/agatte/home-hub/issues/117) | #131 owns action-specific autonomy and feedback; #116/#117 are focused camera-metric and predictor evidence work. |
| Everyday living room | [#129](https://github.com/agatte/home-hub/issues/129), [#130](https://github.com/agatte/home-hub/issues/130), [#131](https://github.com/agatte/home-hub/issues/131), [#134](https://github.com/agatte/home-hub/issues/134), [#135](https://github.com/agatte/home-hub/issues/135) | #129 is the vertical slice; Scene Curator and feedback are #130/#131, with weather and music support under #134/#135. |
| Winding Down and Morning | [#138](https://github.com/agatte/home-hub/issues/138), [#139](https://github.com/agatte/home-hub/issues/139), [#25](https://github.com/agatte/home-hub/issues/25), [#80](https://github.com/agatte/home-hub/issues/80) | #138 is deliberate Winding Down, #139 is conservative wake confirmation, #25 is automation/session observability, and #80 removes dormant bed paths. |
| Music and ambience | [#135](https://github.com/agatte/home-hub/issues/135), [#39](https://github.com/agatte/home-hub/issues/39), [#40](https://github.com/agatte/home-hub/issues/40), [#79](https://github.com/agatte/home-hub/issues/79) | Music Curator is #135; #39 diagnoses the current contextual bandit, #40 researches dependable long-form ambience delivery without preselecting a YouTube/proxy architecture, and #79 owns stream-health recovery. |
| Social and events | [#35](https://github.com/agatte/home-hub/issues/35), [#107](https://github.com/agatte/home-hub/issues/107), [#140](https://github.com/agatte/home-hub/issues/140), [#141](https://github.com/agatte/home-hub/issues/141) | Social/privacy, arrival, event orchestration, and per-event guest experience have distinct owners. |
| Reliability and lifecycle | [#142](https://github.com/agatte/home-hub/issues/142), [#143](https://github.com/agatte/home-hub/issues/143), [#144](https://github.com/agatte/home-hub/issues/144), [#145](https://github.com/agatte/home-hub/issues/145), [#146](https://github.com/agatte/home-hub/issues/146), [#149](https://github.com/agatte/home-hub/issues/149) | #142 is the portfolio index. #143 requires credible current playback intent for Watching; #145 owns portable-host/DNS architecture; #149 owns persistent HOME/TRAVEL lifecycle; #146 is FaceLandmarker suspend/resume recovery. RustDesk is completed administration convenience, not availability architecture. |
| Physical lighting | [#147](https://github.com/agatte/home-hub/issues/147), [#148](https://github.com/agatte/home-hub/issues/148), [#137](https://github.com/agatte/home-hub/issues/137), [#13](https://github.com/agatte/home-hub/issues/13) | First add the Play Light Bar plant/wall wash (#147), then the Flux cabinet cove (#148). #13 is a motion-sensor fallback only if #137's bounded inference evidence warrants it; high-CRI under-cabinet task lighting is later and separate. |

## Reframed open work

- [#3](https://github.com/agatte/home-hub/issues/3) verifies the historical
  Social L1 violet-wall-flood concern in the current room before any retune.
- [#10](https://github.com/agatte/home-hub/issues/10) is a post-preseason,
  observation-driven Game Day 3D-field pass; it is not an effects backlog.
- [#16](https://github.com/agatte/home-hub/issues/16) may provide a small
  shared sequence executor only after accepted experiences demonstrate real
  duplicated sequencing logic.
- [#19](https://github.com/agatte/home-hub/issues/19) is safe context
  reacquisition after outage, never blind replay of stale modes, lights, or
  music. [#20](https://github.com/agatte/home-hub/issues/20) is an
  evidence-gated audio-anomaly context/suppression experiment.
- [#23](https://github.com/agatte/home-hub/issues/23) is optional transition
  choreography based on current fixtures and experiences; [#24](https://github.com/agatte/home-hub/issues/24)
  is a bounded preference experiment under #131.
- [#30](https://github.com/agatte/home-hub/issues/30), [#31](https://github.com/agatte/home-hub/issues/31),
  [#32](https://github.com/agatte/home-hub/issues/32), [#36](https://github.com/agatte/home-hub/issues/36),
  [#41](https://github.com/agatte/home-hub/issues/41), [#53](https://github.com/agatte/home-hub/issues/53),
  and [#55](https://github.com/agatte/home-hub/issues/55) require current
  implementation inventories or measurements before prescribing a change.
- [#45](https://github.com/agatte/home-hub/issues/45) is optional Game Day
  stakes enrichment only if reliable current upstream data exists. The ESPN
  schedule-refresh 403 was fixed on `master` by `c2e60a4`; it is not a current
  known defect without fresh evidence.
- [#51](https://github.com/agatte/home-hub/issues/51) owns operational
  notification delivery, separate from #132's contextual suggestions.
- [#56](https://github.com/agatte/home-hub/issues/56) is desktop-only desk
  posture calibration. [#68](https://github.com/agatte/home-hub/issues/68) is
  a microphone fallback experiment only if physical-context gaps justify it.
- [#74](https://github.com/agatte/home-hub/issues/74) is durable recovered-
  outage observability, not an external hourly watcher. [#105](https://github.com/agatte/home-hub/issues/105)
  is the current Gaming color/screen-tracking design pass, separate from the
  solved brightness floors.

## Current product boundaries

- Physical room evidence outranks software activity guesses. The Latitude is
  a living-room/couch sensor, not an authoritative bed sensor; #80 removes
  dormant `zone=bed` assumptions. Watching requires credible current media
  playback/viewing intent, not an open browser, streaming site, or media
  process alone.
- Travel Mode (#149) is a persistent HOME/TRAVEL **host state** above ordinary
  activity modes. It survives reboot/login, requires fresh post-return physical
  evidence, and coordinates planned backend absence with the Windows desktop-
  agent lifecycle. It does not replace #145's always-home-host/DNS work.
- Winding Down (#138) is not proof of sleep; Sleeping remains separate. Mood
  Context (#133) is temporary and explicit-first, superseding broad automatic
  multi-day personality/mood drift.

## Historical or superseded items

- [#18](https://github.com/agatte/home-hub/issues/18), the global seasonal
  sine modifier, is closed/not planned; seasonal context belongs with Scene
  Curator.
- [#21](https://github.com/agatte/home-hub/issues/21), the generic override
  classifier, is closed/not planned and superseded by #131/#132.
- [#22](https://github.com/agatte/home-hub/issues/22), multi-day mood drift,
  is closed/not planned and superseded by temporary Mood Context.
- [#63](https://github.com/agatte/home-hub/issues/63) is a closed historical
  brainstorm/source-of-truth artifact. [#72](https://github.com/agatte/home-hub/issues/72)
  is closed/not planned, superseded by #137 and the #13 sensor fallback.
- [#77](https://github.com/agatte/home-hub/issues/77) is closed/not planned:
  its Nixeus-specific prescription is obsolete for the Samsung Odyssey G50F.
- [#94](https://github.com/agatte/home-hub/issues/94) and [#95](https://github.com/agatte/home-hub/issues/95)
  are closed/not planned Claude-centric workflow migrations. [#120](https://github.com/agatte/home-hub/issues/120)
  is closed historical watcher false-positive evidence.

## Retained uncommitted ideas

These are not commitments and must be promoted through `PROJECT_SPEC.md` before
they become product direction:

- Calendar-aware focus protection without break reminders.
- Album-art/media-poster palette extraction as a Scene Curator input, while
  preserving kitchen/path protection.
- A compact presence-conflict diagnostic and a scene-rehearsal surface.
- Local voice, additional device categories, multi-room audio, and generic
  composable automation.
