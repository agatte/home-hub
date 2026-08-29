# Gaming Experience / Gaming Director Spec

- **Status:** DECIDED TARGET; implementation pending
- **Updated:** 2026-08-29
- **Umbrella:** GitHub #105
- **Implementation children:** #203, #204, #205

This document owns detailed Gaming presentation policy under the cross-system authority of `PROJECT_SPEC.md`. It does not make Gaming a new house state or create a top-level mode per game.

## Product goal

Gaming should feel aware of **what game is being played** and **when it is being played** while remaining comfortable and useful as apartment lighting.

The target is not an RGB showcase. It is a layered lighting director:

1. enough functional light for the current context;
2. a stable authored game identity;
3. optional short game-event accents when telemetry is trustworthy;
4. final lifecycle, manual, comfort, and fixture safety boundaries.

A game may influence personality. It may not erase ordinary room usability, especially during the day.

## Current baseline evidence

Canonical `master` at the design checkpoint is `7477ca4` (`Add Red Dead Redemption 2 gaming detection`).
Read-only code/live inspection on 2026-08-29 established:

- `AutomationEngine.current_game` already tracks a subordinate game slug and forces one repaint when game identity changes while Activity stays `gaming`.
- `light_state_calculator.GAME_LIGHT_PROFILES` already exists; Rust is currently the only complete profile in that registry.
- Rust already has a separate fixed ember/luma path and bounded damage/under-fire reactions.
- League already has champion-color ownership sourced from Riot's local Live Client Data API.
- Generic Gaming/day is CT-only neutral white (`ct=286`, about 3500K); the historical saturated daytime blue/teal problem is not the current base.
- During a live RDR2 session the pipeline reported `gaming`, period `day`, schedule type `weekend`, no manual override, and active Desktop ScreenSync.
- That session's generic base was L1=130, L2=240, L3/L4=30, L5=75, L6=90 at `ct=286`.

The current daytime weakness is therefore primarily **functional light budget and fixture composition**, not a current green tint.

Current-local AMD Adrenalin `GameSessions` evidence showed RDR2 as the dominant recorded title (29 sessions, about 16.6 hours) and League next (2 sessions, about 2.6 hours). This is useful prioritization evidence, not guaranteed lifetime playtime.

## Semantic model

`Gaming` remains one authoritative Activity. Individual titles are subordinate context.

Conceptually:

```text
GamingContext
  game_slug
  period
  schedule_type
  ambient_context
  optional telemetry_state
```
Game identity must never become a peer lifecycle/activity authority. If a game profile is missing or an integration fails, HomeHub falls back to normal Gaming.

## Composition order

Gaming lighting resolves in this order:

1. **Functional envelope** — establishes minimum useful visibility for schedule/time context.
2. **Game signature** — authored stable color/CT/brightness composition for the active game.
3. **Optional event accent** — bounded transient reaction from trustworthy game telemetry.
4. **Final authority and safety boundaries** — manual per-light ownership, DND, Away/Sleeping/lifecycle rules, external-off intent, protected-light ownership, fixture limits, and physical comfort caps.

No lower layer may bypass a stronger later boundary.

The functional envelope is especially important during daytime. A dark or saturated game palette must not be allowed to make the apartment hard to use.

## Day-type and time policy

| Context | Functional-light budget | Game-expression budget | Target feel |
| --- | --- | --- | --- |
| Weekday daytime | highest | minimal | bright, neutral, focused |
| Weekend daytime | high | moderate | usable room with a clear game signature |
| Evening | medium | high | atmospheric but comfortable |
| Night | lower | high | cinematic depth and color contrast |
| Late night | low/comfort-capped | moderate | immersive without flooding the apartment |

### Daytime guardrail

Daytime Gaming should be predominantly neutral white or very low-saturation functional light. Saturated game colors belong primarily on architectural/accent fixtures.
A game's theme must not create room-wide saturated green/blue daytime lighting simply because those colors are present in the game's art direction.

## Fixture roles

- **L1 Living room lamp:** functional/visual anchor. Prefer neutral or warm support; do not make it a saturated game-color point by default.
- **L2 Bedroom Lamp Left:** primary bedroom/desk functional contributor. It may participate in ScreenSync or game-specific dynamic brightness only through explicit ownership.
- **L3/L4 Kitchen pendants:** remain paired in Gaming. They carry useful open-plan visibility and should not become two independent accent colors.
- **L5 Bedroom Lamp Right:** subordinate accent. Its clear seeded-glass housing reads brighter than numeric Hue brightness suggests, so glare limits remain important.
- **L6 Plant Wash:** preferred strongest architectural game-signature fixture. Real-room calibration shows useful wall/plant color generally becomes meaningful around the 65–80% region, depending on hue and saturation.

L6 is not automatically a ScreenSync target. Stable game-specific architectural color is the default role unless a later audited integration proves dynamic ownership is useful.

## Stable profile policy

A game's resting lighting must be stable and intentional.

Do **not** add continuous pulse, color cycling, random drift, or per-frame room-wide hue changes merely to make Gaming feel active.

Dynamic behavior should be earned by either:

- an explicitly accepted ScreenSync policy; or
- a trustworthy semantic game event.

Every event reaction must define eligible fixtures, duration, cooldown/deduplication, authority gates, and deterministic return to the **current** stable profile.

## Profile resolution

The generalized implementation should prefer one profile registry/resolver over game-specific conditionals scattered across engine, routes, and ScreenSync.

A profile may define schedule-aware period variants and fall back safely:

```text
(schedule_type, period) -> period-only -> generic Gaming
```

Candidate model:

```text
GameLightingProfile
  game_slug
  base_by_schedule_and_period
  fixture_roles
  screen_sync_policy
  event_reactions
```

Changing game identity, period, or schedule type may trigger one intentional recomposition. Repeated unchanged heartbeats/context must not generate repeated Hue writes.

## ScreenSync policy

ScreenSync is a tool, not the identity of Gaming.

- Generic Gaming currently holds canonical L2/L5 state rather than following sampled RGB; preserve a stable fallback.
- Rust uses screen luminance to shape brightness while holding a fixed ember color; this is an accepted special behavior to preserve.
- League champion ownership may temporarily exclude owned lights from generic ScreenSync.
- New profiles should choose `off`, `brightness-only`, `bounded-color`, or another explicit policy rather than inheriting dynamic color accidentally.

## Initial game art direction

These are simulation/calibration starting points, not accepted final Hue values.

| Game | Stable signature direction | Integration direction |
| --- | --- | --- |
| RDR2 | copper, campfire amber, dusty red, restrained moon blue | profile first; optional passive cues later |
| League of Legends | active champion palette | official local Live Client Data API events |
| Rust | ember + muted moss | preserve luma and damage/under-fire behavior |
| OSRS / RuneLite | parchment/gold + rune blue/amethyst | RuneLite plugin events for bounded level-up/loot/death reactions |
| Planet Zoo | savanna gold + warm botanical neutrals | static profile |
| Oxygen Not Included | oxygen cyan + industrial amber | static profile; mod only if justified later |
| High On Life | cyan + magenta + violet | static profile |
| Strange Horticulture | candle amber + muted botanical + plum | static profile |
| Overcooked | coral + aqua + gold | bright playful profile |
| RotMG Exalt | jewel purple + cyan + gold | static profile |
| NBA 2K19 | arena white + configured team accents | team configuration before telemetry |

All daytime versions remain function-first regardless of the game's signature.

## RDR2 first-profile direction

RDR2 is the first new generalized calibration target under #204.

Working palette references:

- copper/campfire `#C06A2B`;
- dusty red/leather `#A9432F`;
- subordinate moon blue `#365B8C`.
Weekday day should keep those colors mostly off the functional fixtures; L6 is the preferred place for a restrained copper signature. Weekend day may strengthen L6 and add one low-saturation echo. Evening/night may use the warm family more broadly, with moon blue only as a counter-accent.

Do not install ScriptHook/injected RDR2 mods solely for HomeHub lighting. Stable authored composition is sufficient for V1.

## Telemetry adapters

#205 owns normalized game-event integration.

High-value source classes:

- official/local game APIs where available;
- narrowly scoped local plugins with clear user consent;
- passive screen-derived signals when replay demonstrates they are stable.

Avoid process-memory scraping/injection as a default lighting strategy.

An adapter failure must degrade to the current stable game profile. It must never leave a transient event color latched or break ordinary Gaming.

### Current precedents

- **League:** champion identity from Riot local Live Client Data API. Candidate later events include match start/end and major objectives, subject to bounded replay/design acceptance.
- **Rust:** red-vignette damage detector, under-fire hold/release, and luma-driven brightness. Preserve these semantics while reducing duplicate ownership logic only if worthwhile.
- **OSRS / RuneLite:** RuneLite exposes rich event subscribers; prefer a small privacy-bounded plugin adapter for selected level-up/notable-loot/death semantics. Do not react to every tick/XP/chat event.

## Simulation and calibration

Before enabling a new profile in production, simulate at minimum:

- weekday daytime;
- weekend daytime;
- evening;
- night;
- late night.
For each candidate review:

- room readability and functional brightness;
- monitor contrast and direct glare;
- L3/L4 pairing;
- L5 perceptual glare;
- L6 plant/wall wash presence;
- transition smoothness;
- stable-state idempotence;
- event reaction duration/release where applicable.

Phone photographs are supporting evidence, not absolute color truth. Direct lived-room judgment outranks phone white-balance/exposure artifacts.

Simulation values are proposals until accepted through real-room review. Do not promote a palette merely because its RGB/HSB values look mathematically coherent.

Detailed 2026-08-29 profile priority and candidate-state evidence lives in `GAMING_PROFILE_CALIBRATION_2026_08_29.md`.

## Safety and ownership invariants

Gaming presentation may not weaken:

- Away or Sleeping lifecycle authority;
- DND/privacy behavior;
- explicit manual mode or per-light ownership;
- external physical-off intent;
- protected-light ownership;
- future source-qualified bed comfort ceilings;
- fixture-specific glare/brightness constraints.

L3/L4 pairing remains a hard Gaming presentation invariant.

## Work sequence

1. **#203 foundation:** generalized GamingContext/profile resolver, schedule-type participation, functional envelopes, idempotence, observability.
2. **#204 RDR2:** first new per-game profile, simulation, and real-room calibration.
3. Migrate/align Rust only where the generalized boundary improves maintainability without changing proven behavior.
4. Expand League champion/event behavior through #205 only after the stable-profile boundary is clear.
5. Prototype RuneLite event inventory/replay without lighting actuation before selecting V1 reactions.
6. Add static profiles for other games only when actual play evidence makes them useful; Rocket League remains a later static/integration candidate.

Do not pre-build a huge catalog of unused profiles.

## Observability

Diagnostics should make it possible to answer:

- what game HomeHub thinks is active;
- which Gaming profile/fallback was selected;
- schedule type and time period;
- stable base state;
- ScreenSync/telemetry ownership by light;
- active event accent and its expiry/cooldown;
- final applied state after safety/comfort/manual boundaries;
- why a light was skipped or capped.

This observability must distinguish stable profile selection from transient event reaction so future light churn is diagnosable.

## Implementation/review gate

#203 changes production lighting policy and crosses activity, schedule, per-game state, ScreenSync, and Hue ownership. It requires high-confidence implementation and separate review before deployment.

No production write, deploy, migration, or service restart is authorized by this document.

## Related

- #105 Gaming Director umbrella
- #203 schedule-aware Gaming foundation
- #204 RDR2 Frontier profile
- #205 Gaming telemetry adapters
- #47 evening ScreenSync envelope evidence gate
- #136 desk-light perceived balance
- #147 L6 Plant Wash integration/calibration
- #202 future late-night bed comfort envelope
