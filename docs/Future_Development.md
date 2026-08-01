# Home Hub Future Development Index

> **Status:** Non-authoritative idea and GitHub-issue index.
> **Last reviewed:** August 1, 2026.

Cross-system product policy and priority live only in the
[Product Experience Contract](PROJECT_SPEC.md#product-experience-contract--august-1-2026)
and [Roadmap](PROJECT_SPEC.md#roadmap). This file helps find existing issues and
preserves ideas that have not been committed to the product contract. Issue
bodies are planning evidence, not proof of shipped behavior; code and live
verification take precedence for current-state claims.

## Canonical roadmap issue map

| Canonical workstream | Existing issue coverage | Coverage note |
|---|---|---|
| Production/autonomy evidence audit | [#93](https://github.com/agatte/home-hub/issues/93) (closed historical override-rate snapshot), [#116](https://github.com/agatte/home-hub/issues/116) (camera-lane metric), [#117](https://github.com/agatte/home-hub/issues/117) (predictor collapse) | **Missing umbrella issue.** Existing issues cover individual failures, not the complete action/feedback audit. |
| Incident P1 capability health and degraded context | [#74](https://github.com/agatte/home-hub/issues/74) (healed outages), [#81](https://github.com/agatte/home-hub/issues/81) (desktop logs), [#109](https://github.com/agatte/home-hub/issues/109) (room-source consumer), [#110](https://github.com/agatte/home-hub/issues/110) (veto observability), [#120](https://github.com/agatte/home-hub/issues/120) (Sonos false-positive health) | **Missing umbrella issue.** Reuse these for their narrow fixes; the full capability matrix/ownership surface is untracked. |
| Everyday living-room intelligence | [#36](https://github.com/agatte/home-hub/issues/36) (scene visibility), [#40](https://github.com/agatte/home-hub/issues/40) (quality ambient research), [#79](https://github.com/agatte/home-hub/issues/79) (stream health), [#107](https://github.com/agatte/home-hub/issues/107) (arrival foundation) | **Missing umbrella issue.** None owns quiet/listening/settled couch, Scene Curator feedback, or the action-specific trust ladder end to end. |
| Winding Down and mornings | [#16](https://github.com/agatte/home-hub/issues/16) (macro executor), [#25](https://github.com/agatte/home-hub/issues/25) (sleep analytics), [#51](https://github.com/agatte/home-hub/issues/51) (additional prompt surfaces), [#80](https://github.com/agatte/home-hub/issues/80) (dormant bed paths) | **Missing product-slice issue.** Older “Bedtime macro” and inferred-sleep assumptions are superseded where they conflict with the Winding Down contract. |
| Music Curator | [#39](https://github.com/agatte/home-hub/issues/39) (bandit visibility), [#40](https://github.com/agatte/home-hub/issues/40) (ambient YouTube path) | **Missing umbrella/research issue** for gentle discovery plus arbitrary Apple Music catalog-to-Sonos playback. |
| Social and events | [#3](https://github.com/agatte/home-hub/issues/3) (Social palette defect), [#35](https://github.com/agatte/home-hub/issues/35) (multi-face/audio research), [#51](https://github.com/agatte/home-hub/issues/51) (audible prompts), [#107](https://github.com/agatte/home-hub/issues/107) (arrival with friends) | **Missing umbrella issue** for hybrid Social policy, event records, Tonight at Anthony’s, guest music/lighting queues, Showcase Mode, and Home Bar event planning. |

## Reusable focused work

These issues remain useful, but their old priority labels do not set the
current roadmap.

### Atmosphere and lighting

- [#18 Seasonal lighting profile modifiers](https://github.com/agatte/home-hub/issues/18)
  — useful input to Scene Curator ranking; the fixed sine-wave implementation
  is not yet a product decision.
- [#23 Adaptive transition choreography](https://github.com/agatte/home-hub/issues/23)
  — compatible with evolving atmosphere when slow crossfades and task-light
  protection are preserved.
- [#24 Transition-curve preference learning](https://github.com/agatte/home-hub/issues/24)
  — deferred until feedback scope and action-specific graduation exist.
- [#36 Hue scene discovery and mode-mapping visibility](https://github.com/agatte/home-hub/issues/36)
  — a useful library/diagnostic surface, not the Scene Curator itself.
- [#77 Stronger night warming](https://github.com/agatte/home-hub/issues/77)
  and [#105 gaming bedroom lighting](https://github.com/agatte/home-hub/issues/105)
  — fixture-specific tuning, subordinate to the perceptual desk-lamp policy.

### Intelligence, feedback, and observability

- [#14 Dashboard replay/time-machine](https://github.com/agatte/home-hub/issues/14)
  — useful forensic visualization; not a near-term product vertical slice.
- [#20 Anomaly-triggered automation pause](https://github.com/agatte/home-hub/issues/20)
  — potentially valuable safety behavior, subject to consequence-based trust.
- [#21 Override-reason classifier](https://github.com/agatte/home-hub/issues/21)
  — keep suggestion-only unless a later action policy earns graduation.
- [#33 Zone-change predictor feature](https://github.com/agatte/home-hub/issues/33)
  and [#34 speculative predictor context](https://github.com/agatte/home-hub/issues/34)
  — model research, not proof that the predictor should be promoted.
- [#69 face-anchor TTL](https://github.com/agatte/home-hub/issues/69),
  [#72 kitchen-audio measurement](https://github.com/agatte/home-hub/issues/72),
  and [#83 controller-aware activity](https://github.com/agatte/home-hub/issues/83)
  — narrow evidence-quality work.

### Interface and orchestration

- [#15 Screensaver mode](https://github.com/agatte/home-hub/issues/15) — kiosk
  polish; no longer a priority claim.
- [#16 Contextual quick-actions/macros](https://github.com/agatte/home-hub/issues/16)
  — a possible executor for Winding Down or event operations, but those
  experiences must remain overlays with the confirmation rules in the
  canonical contract.
- [#39 Music bandit matrix UI](https://github.com/agatte/home-hub/issues/39)
  — useful Music Curator observability.
- [#51 System-wide nudge surfaces](https://github.com/agatte/home-hub/issues/51)
  — reuse for the three-chime vocabulary and opt-in Alexa flow; its original
  urgency mapping is not canonical.

### Hardware and resilience

- [#13 Hue motion sensor](https://github.com/agatte/home-hub/issues/13) — a
  possible hardware fallback after the bounded kitchen-inference trial; its
  current hallway-only scope would need revision.
- [#19 Power-outage recovery](https://github.com/agatte/home-hub/issues/19) —
  retained resilience idea.
- [#65 desktop camera as a second lux source](https://github.com/agatte/home-hub/issues/65)
  and [#106 engine per-room lux wiring](https://github.com/agatte/home-hub/issues/106)
  — partially or intentionally not completed; inspect current code and issue
  comments before treating either title as current truth.
- [#80 Dormant bed automation paths](https://github.com/agatte/home-hub/issues/80)
  — keep as historical implementation cleanup/research. The canonical target
  now starts with manual Winding Down and a safe visible projector timer, not a
  silent bed-zone shortcut.

## Superseded or reframed ideas

- **“Full autopilot” and one confidence threshold:** superseded by the
  consequence-based, action-specific trust ladder.
- **Permanent AI “Personality” or silent emotional claims:** reframed as
  temporary, usually explicit **Mood Context**. Issues
  [#58](https://github.com/agatte/home-hub/issues/58),
  [#59](https://github.com/agatte/home-hub/issues/59), and
  [#60](https://github.com/agatte/home-hub/issues/60) retain useful subsystem
  work, but their original phase sequence is not the current product roadmap.
  `VibeRouter` portions of #59 are already present in committed code; passive
  suggestions and Alexa interaction must follow the Product Experience
  Contract.
- **Multi-day “mood drift” automation:** [#22](https://github.com/agatte/home-hub/issues/22)
  is superseded as written. A temporary Mood Context may observe recent
  outcomes, but it must expire and must not infer a durable emotional identity.
- **Audio-only Social:** superseded. [#35](https://github.com/agatte/home-hub/issues/35)
  must require hybrid guest evidence and distinguish calls/gaming chat.
- **Direct guest last-write-wins lighting:** superseded by leases, queues,
  task-light protection, host controls, and explicit Showcase Mode.
- **One-step morning or silent inferred sleep:** superseded by staged waking
  and manual Winding Down first; inferred sleep is a later, multi-signal phase.
- **Old priority bands and dated phase calendars:** historical only. The sole
  current ordering is the canonical Roadmap.

## Uncommitted ideas worth retaining

These have no current umbrella issue and are not commitments:

- Calendar-aware focus context that protects a confirmed work session without
  adding break reminders.
- Album-art or media-poster palette extraction as an input to the Scene
  Curator, with kitchen/path protection.
- A compact presence-conflict diagnostic showing each room source, freshness,
  chosen authority, and actuator owner.
- A lightweight scene rehearsal tool for reviewing candidate Scene Curator
  pools before allowing automatic selection.
- Local voice, additional device categories, multi-room audio, and generic
  composable automation remain **DEFERRED** unless promoted through
  `PROJECT_SPEC.md`.

Issue [#63](https://github.com/agatte/home-hub/issues/63) is the broader May
2026 brainstorm archive. Re-evaluate its ideas against the canonical contract
instead of treating that issue’s ranking as current priority.
