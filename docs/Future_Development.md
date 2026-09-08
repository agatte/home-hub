# Home Hub Future Development Index

> **Status:** Non-authoritative future-idea, research, and GitHub-issue index.
> **Last reviewed:** September 7, 2026.

Cross-system product policy and accepted product direction live in
[PROJECT_SPEC.md](PROJECT_SPEC.md). This file is the durable place to retain
future possibilities without pretending they are already product commitments.
Current GitHub issue contracts own bounded work; committed code and live
verification are required for claims that something is shipped or healthy.

## The three future-research jobs

Future-development research should deliberately do all three of these jobs:

1. **Make HomeHub smarter with what we already own.** Find new intelligence in
   existing cameras, phone/OS context, audio, media, network state, event history,
   and other already-available data before proposing another physical sensor.
2. **Make HomeHub more beautiful, theatrical, and enjoyable.** Look for design,
   lighting, Game Day, guest, dashboard, and interaction ideas that create better
   moments even when they do not solve an architecture problem.
3. **Find the “wait, our existing hardware can do what?” opportunities.** Explore
   capabilities hidden in hardware already installed, underused hardware such as
   the Blue Yeti, and hardware Anthony owns but HomeHub may not know about yet.

**Existing-hardware-first rule:** the repository is not a complete household
hardware inventory. Before recommending a purchase for an experimental capability,
first ask Anthony whether he already owns a suitable unused or underused device.
New hardware remains a valid answer when evidence shows it is genuinely the best
solution, but it is not the default research direction.

## Registry status vocabulary

- **TRACKED** — a dedicated GitHub issue already owns the idea.
- **FOLDS INTO #N** — keep the richer idea here, but do not create a duplicate;
  if selected, extend the existing issue/owner.
- **CANDIDATE** — Anthony wants the idea retained, but it has no dedicated issue
  and is not active backlog yet.
- **LAB** — deliberately speculative, shadow/read-only experiment; interesting
  enough to remember, not enough evidence to become product direction.
- **PARKED** — an existing issue is valid but gated on evidence, timing, hardware,
  calibration, or another prerequisite.

Presence in this file does **not** grant automation authority. Software/process
signals must not invent physical rooms, and experimental sensing begins shadow-only.

## Promotion flow

When Anthony selects an idea to pursue:

1. check this index and GitHub for an existing owner before creating anything;
2. decide whether it extends an existing issue or needs a dedicated issue;
3. update `PROJECT_SPEC.md` only if accepted cross-system product policy changes;
4. define the smallest evidence/validation gate before implementation;
5. keep speculative or hardware experiments shadow-only until real evidence earns
   any stronger authority.

## Research execution contract

The repo-local `homehub-research` skill is the standard Codex entrypoint for future-direction research. It reads this registry as the durable brief, checks current specs/code/issues for reality and dedupe, uses fresh external evidence when needed, and returns findings to the main session for synthesis.

Use one of four research modes:

- **Broad horizon scan:** cover all three research jobs; a user example is a search seed, not the scope boundary.
- **Focused idea probe:** test one candidate deeply for feasibility, novelty, HomeHub fit, evidence, and the smallest useful experiment.
- **Hardware-opportunity scan:** inspect installed/underused surfaces and ask targeted questions about possibly-unrecorded owned hardware before proposing a purchase.
- **Registry refresh:** reconcile this document against current code, issues, research, and accepted decisions; update it only when a durable refresh is requested.

Research starts read-only. Separate fact from hypothesis, classify immature ideas as `LAB`, preserve physical/automation authority boundaries, and check for an existing issue owner before proposing a new track. The main session remains the integrator; one bounded Codex worker is normally enough for delegated source gathering or synthesis, and multiple workers are reserved for genuinely independent research lanes.

A research finding may be retained here without becoming backlog. Do not create a GitHub issue or change `PROJECT_SPEC.md` merely because an idea is interesting; promotion still follows the selection flow above.

AI/LLM/multimodal candidates also use [`AI_SEMANTIC_LAYER.md`](AI_SEMANTIC_LAYER.md) as the non-authoritative architecture brief. Its core boundary is AI as a semantic/analytical layer around deterministic HomeHub authority, not a new whole-home decision owner.

### Candidate entry shape

When a research run retains or materially refreshes an idea, keep enough structure that a later session can evaluate it without repeating the whole discovery pass:

- **Registry status / owner:** `TRACKED`, `FOLDS INTO`, `CANDIDATE`, `LAB`, or `PARKED`, plus the owning issue/workstream when known.
- **Cost class:** zero-purchase, uses hardware Anthony may already own, or new hardware required.
- **HomeHub leverage:** the existing device, data, service, or experience that makes the idea unusually relevant here.
- **What it unlocks:** the user-facing capability or engineering advantage, not just the technology name.
- **Evidence / uncertainty:** what current sources establish and what remains hypothesis.
- **Smallest next gate:** the cheapest read-only probe, replay, shadow experiment, design mock, or lived observation that would make the idea more or less credible.

Do not force every speculative thought into a full record. Apply this shape to ideas strong enough to retain or revisit.

## Current tracked roadmap anchors

| Workstream | Current issue coverage | Boundary |
|---|---|---|
| Portfolio / current sprint | [#142](https://github.com/agatte/home-hub/issues/142), [#239](https://github.com/agatte/home-hub/issues/239) | #142 is the product-roadmap index. #239 coordinates the September stabilization + corrected broad future-research pass. |
| Replay / forensics | [#240](https://github.com/agatte/home-hub/issues/240) | First selected future-intelligence item: deterministic, non-actuating evidence replay and counterfactual decision comparison. |
| AI semantic / analysis layer | [#240](https://github.com/agatte/home-hub/issues/240), [#130](https://github.com/agatte/home-hub/issues/130), [#131](https://github.com/agatte/home-hub/issues/131), [#132](https://github.com/agatte/home-hub/issues/132), [#107](https://github.com/agatte/home-hub/issues/107) | `AI_SEMANTIC_LAYER.md` holds the provider-neutral research architecture. AI may explain, interpret, discover, or emit bounded shadow evidence; existing owners retain lifecycle/device authority. |
| Everyday living room / Scene Curator | [#129](https://github.com/agatte/home-hub/issues/129), [#130](https://github.com/agatte/home-hub/issues/130), [#131](https://github.com/agatte/home-hub/issues/131), [#134](https://github.com/agatte/home-hub/issues/134), [#135](https://github.com/agatte/home-hub/issues/135) | #129 is the lived vertical slice; #130 scene selection/evolution; #131 per-action autonomy; #134 weather support; #135 Music Curator. |
| Intelligence evidence / diagnostics | [#116](https://github.com/agatte/home-hub/issues/116), [#117](https://github.com/agatte/home-hub/issues/117), [#131](https://github.com/agatte/home-hub/issues/131) | #116/#117 remain focused evidence/measurement work; #131 owns any consequence-specific autonomy. Re-read current issue bodies before using older predictor/camera assumptions. |
| Music / ambience support | [#39](https://github.com/agatte/home-hub/issues/39), [#40](https://github.com/agatte/home-hub/issues/40), [#79](https://github.com/agatte/home-hub/issues/79), [#135](https://github.com/agatte/home-hub/issues/135) | #39 contextual-bandit diagnosis, #40 dependable long-form ambience research, #79 stream-health recovery, #135 Music Curator. |
| Mood Context | [#133](https://github.com/agatte/home-hub/issues/133) | Explicit/temporary Mood Context owner; do not revive retired multi-day mood/personality drift under another name. |
| Winding Down / Morning | [#138](https://github.com/agatte/home-hub/issues/138), [#139](https://github.com/agatte/home-hub/issues/139), [#25](https://github.com/agatte/home-hub/issues/25), [#80](https://github.com/agatte/home-hub/issues/80) | Winding Down, confirmed Morning, lifecycle/session observability, and dormant legacy posture cleanup remain separate. |
| Sleeping wake authority | [#235](https://github.com/agatte/home-hub/issues/235) | Reopened on fresh September 7 regression evidence. Trusted intentional desk-input qualification is deployed; keep open through one lived overnight acceptance before treating the regression as closed again. |
| Social / guests / events | [#35](https://github.com/agatte/home-hub/issues/35), [#107](https://github.com/agatte/home-hub/issues/107), [#140](https://github.com/agatte/home-hub/issues/140), [#141](https://github.com/agatte/home-hub/issues/141) | Social/privacy, arrival, event orchestration, and per-event guest experience have distinct owners. |
| Kitchen / blind-space awareness | [#137](https://github.com/agatte/home-hub/issues/137), [#13](https://github.com/agatte/home-hub/issues/13) | Use bounded inference first; dedicated motion/occupancy hardware is a fallback only after evidence says inference is inadequate. |
| Watching / nighttime acceptance | [#143](https://github.com/agatte/home-hub/issues/143), [#154](https://github.com/agatte/home-hub/issues/154), [#200](https://github.com/agatte/home-hub/issues/200), [#202](https://github.com/agatte/home-hub/issues/202) | These are current reliability/calibration gates, not a reason to redesign future architecture around Watching. |
| Apple Health sleep lane | [#236](https://github.com/agatte/home-hub/issues/236) | Shadow/parked observation and graduation program; it has no automatic lifecycle authority yet. |
| Host lifecycle / reliability | [#145](https://github.com/agatte/home-hub/issues/145), [#149](https://github.com/agatte/home-hub/issues/149) | #145 is completed around the accepted always-home Latitude/DNS contract. #149 remains the parked HOME/TRAVEL/RETURNING_HOME contingency lifecycle with bounded lived return-home acceptance, not ordinary daily host behavior. |
| Game Day | [#5](https://github.com/agatte/home-hub/issues/5), [#7](https://github.com/agatte/home-hub/issues/7), [#10](https://github.com/agatte/home-hub/issues/10), [#153](https://github.com/agatte/home-hub/issues/153) | Celebration palette, live-game volume/TTS, observation-driven 3D field tuning, and provider health remain separate from new experiential ideas below. |
| Physical lighting | [#147](https://github.com/agatte/home-hub/issues/147), [#148](https://github.com/agatte/home-hub/issues/148) | L6 / Plant Wash is complete. #148 remains the next audited cabinet-cove hardware addition, not an automatic software priority. |

Completed stabilization items such as #144, #146, #198, #199, #201, #237, and #238 should not be reopened as “future work” without fresh regression
evidence.

#235 is intentionally excluded from that completed list because fresh September 7 regression evidence reopened it for lived overnight acceptance.

# Job 1 — Make HomeHub smarter with what we already own

## TRACKED — Deterministic evidence replay + decision forensics (#240)

Capture bounded real incidents and replay them through current/candidate decision
logic with fake/no-op writers. Explain decisive evidence, freshness, dwell,
ownership, suppression, and the final requested action. Compare candidate changes
against the exact same evidence before another physical-room test when possible.

This also absorbs the older retained idea of a compact presence-conflict diagnostic.
A separate scene-rehearsal/preview surface may later reuse the harness, but should
not turn #240 into a whole-home simulator before the first useful replay exists.

## CANDIDATE — HomeHub Analyst / grounded incident explainer

Use generative AI as a read-only explanation layer over bounded HomeHub evidence:
ordered event history, source freshness, override provenance, ownership/suppression,
requested light/media actions, and build/config identity. The result should answer
"why is HomeHub in this state?", "why did this change happen?", and "what conflicted
during this window?" with explicit evidence references, conflicts, and unknowns.

**Owner if promoted:** #240 owns the deterministic evidence/replay substrate; the
Analyst consumes that trace rather than replacing it. **Cost class:** zero-purchase
for the first prototype, with local/cloud model choice benchmarked separately.
**Smallest gate:** use the September 7 Sleeping-vs-Watching incident as a fixed gold
fixture and require zero unsupported critical causal claims plus a proven no-write
path. See `AI_SEMANTIC_LAYER.md`.

## CANDIDATE — Cross-camera transition/topology learning

Learn apartment movement topology from the two existing camera zones and timing
between source-qualified observations. Examples: Desk disappears then Latitude
sees a person; Couch disappears and returns without Desktop arrival; repeated
transition-time distributions that suggest a likely kitchen/path trip.

**Owner if promoted:** primarily #137 for blind-space/kitchen usefulness, with
Sensing & Intelligence support. This predicts movement/context; it must not claim
a physical room without evidence that earns that semantics.

## CANDIDATE — iPhone Context Bridge

Use opt-in iOS/Shortcuts events as semantic context rather than physical-location
authority: Focus changes, charger events, Wi-Fi join/leave, alarm lifecycle,
headphone/Bluetooth events, selected app events, Sound Recognition, and similar
signals that can improve Morning, Winding Down, arrival, suggestion timing, or
media behavior.

**Fold where possible:** #107 arrival, #139 Morning, #132 suggestions, #131
autonomy. Avoid creating a parallel lifecycle owner merely because the phone can
emit more events.

## CANDIDATE — Windows Context Bus

Treat Windows itself as a rich semantic source alongside the camera: user/session
presence, display on/off/dim, native media sessions, foreground/app context,
audio-session state, power/session transitions, and tightly allowlisted
notification context where useful and explicitly permitted.

This should improve Working/Gaming/Watching/interruption semantics without
turning software telemetry into physical room evidence.

## CANDIDATE — Household Sound Context / Apartment Sound Atlas

Expand the underused Blue Yeti lane from the failed “multiple speakers = Social”
question toward easier, action-specific household sounds: water, dishes, cooking,
footsteps, vacuum, door/knock, appliance/fan signatures, sustained quiet, crowd
roar, and other locally distinguishable events.

Deduplication/ownership:

- [#20](https://github.com/agatte/home-hub/issues/20) already owns evidence-gated
  disruptive audio anomaly/corroboration consequences.
- [#35](https://github.com/agatte/home-hub/issues/35) owns Social/privacy and any
  multi-person guest inference.
- [#68](https://github.com/agatte/home-hub/issues/68) is specifically a parked
  **Latitude microphone** fallback experiment; it is not the owner of Blue Yeti
  expansion and should stay parked unless a concrete gap justifies that mic.
- #137 may consume useful kitchen/path corroboration, but audio alone must not
  manufacture physical occupancy.

AI/audio embeddings may help label or cluster these narrow events, but the output is
shadow evidence, not room truth. Prefer a small confusion matrix over a grand generic
"understand the apartment" audio model.

## CANDIDATE — Routine mining, not another generic mode predictor

Mine recurring sequences already present in HomeHub history: arrival → kitchen →
Relax, playback end → movement → Sleeping, repeated weather/time lighting
corrections, common music/scene sequences, and other habits we did not explicitly
program.

Use AI only to label/summarize candidate sequences where that adds semantic value;
frequency/support still comes from real HomeHub event data. Candidate routines should
first be tested against #240 replay/counterfactual evidence, then explain or suggest
rather than silently actuate. Any consequence graduates action-by-action through
#131; uncertain suggestions use #132. This is explicitly different from resurrecting
the old collapsed generic predictor.

## FOLDS INTO #132 — Interruption Budget

Go beyond binary DND and decide whether **now is a good moment** for a low-priority
suggestion: after video pauses/ends, at activity boundaries, after leaving the
desk, on arrival, or during quiet transitions. Important warnings keep their own
urgency.

Do not create a second notification/suggestion system. #132 owns the interaction;
[#51](https://github.com/agatte/home-hub/issues/51) remains operational warnings.

## CANDIDATE — Conversational HomeHub concierge

Provide a HomeHub-native natural-language interface for read questions ("why are
these lights on?", "what happened while I was gone?") and explicit bounded commands
("make this a little warmer"). Read paths should consume task-specific evidence,
not expose unrestricted developer SQL/MCP access. Write requests must map to existing
allowlisted action/mode/scene contracts and pass normal authority/ownership gates.

**Fold where possible:** `VibeRouter` is the shipped bounded-command precedent; #132
owns uncertain suggestion interaction and #107 owns arrival use cases. A dedicated
issue is only justified if the broader conversational surface is selected after the
Analyst proves the shared task runtime useful.

## CANDIDATE — Media Director / content-phase understanding

Use transient screen/media features already available to HomeHub to understand
phases rather than only average RGB: fullscreen vs windowed, playing vs paused,
scene-cut rate, static menu/UI, dark cinematic content, credits/end patterns,
loading/static screens, and broadcast game/commercial/studio phases.

A multimodal model may emit a deliberately small structured phase such as
`content`, `pause/menu`, `credits/end`, `commercial`, `studio/halftime`, or `unknown`;
start shadow-only and benchmark against cheaper deterministic visual/media features.
Possible consequences include smarter ScreenSync envelopes, gentle pause/credits
lighting, and the Game Day Broadcast Director below. Do not retain screenshots or
make content-phase evidence a physical-presence source.

## RETAINED — Calendar-aware focus protection

Keep the earlier idea of calendar-aware focus protection without break reminders.
If revisited, combine calendar context with current Working/interaction evidence
and #132 interruption timing rather than creating a calendar-driven mode owner.

## FOLDS INTO #130 — Album-art/media-poster palette extraction

Retain album-art/media-poster palette extraction as a Scene Curator input while
preserving functional kitchen/path lighting and manual ownership. It chooses or
influences atmosphere; it does not bypass #130 scene policy.

# Job 2 — Make HomeHub more beautiful, theatrical, and enjoyable

## FOLDS INTO #23 — Cinematic house transitions

The richer version of [#23](https://github.com/agatte/home-hub/issues/23): make
an already-authorized transition feel spatial and intentional. Example:
Working → Relax can let desk functionality recede, carry useful path light through
the apartment, bring the living room forward, then settle the final scene.

[#24](https://github.com/agatte/home-hub/issues/24) owns any later learned
preference among transition styles. Do not create a duplicate “cinematic
transitions” issue.

## CANDIDATE — Camera-based physical lighting calibration

During an explicit calibration session, use existing cameras as temporary room
photometers while fixtures are exercised one at a time across a few brightness,
CT, and color points. Build a perceptual contribution map: room fill, local glare,
architectural depth, useful task contribution, and asymmetric response.

Goal: scene design should reason about how fixtures actually affect the room,
not assume equal Hue `bri` values produce equal perceived light. Calibration is
explicit/test-only and must preserve camera privacy expectations.

## FOLDS INTO #130/#131 — AI lighting feedback interpreter / Scene Critic

Translate subjective feedback such as "the kitchen is competing," "L1 feels too
dim," or "a little moodier, not darker" into a validated preference delta: fixture
role, relative hierarchy, warmth/saturation direction, contrast, and uncertainty.
The model does **not** generate/apply arbitrary Hue payloads; #130's Scene Curator
turns accepted intent into legal targets and existing ownership remains authoritative.

A later explicit calibration session may add a room snapshot plus requested/actual
light states for multimodal critique. #131 owns any learning/autonomy from repeated
feedback. The first useful gate is post-#129 daylight acceptance when #130 resumes.

## CANDIDATE — Unified HomeHub visual language

Define recurring motion/graphic motifs across kiosk UI, lighting transitions, and
small sound cues so modes feel like one designed product: Home opens/expands,
Away contracts, Winding Down descends, Sleeping removes depth, Game Day uses
field/grid language, Watching uses cinematic framing, Working uses ordered
structure, Relax uses organic motion.

This is a design system, not another state machine.

## CANDIDATE — Ambient Canvas

Create an abstract/generative idle canvas driven by real HomeHub context such as
time, weather, sun position, house/activity state, current light palette, music
energy, recent movement, season, and Game Day state.

Do **not** revive the failed requirement that the dashboard must be a literal
photoreal/3D reconstruction of the apartment. The canvas should be expressive
rather than pretending to be physical-world truth.

## FOLDS INTO #130/#134 — Directional real-world sunlight

Use location/date/time plus weather to make artificial light feel connected to
outside daylight: directional golden-hour/sunset movement, cloud suppression,
and seasonal variation. Keep it as a Scene Curator/weather composition input,
not a global seasonal modifier like retired #18.

## CANDIDATE — HomeHub title cards

Give major moments a restrained 2–4 second fullscreen treatment that melts back
into the dashboard: GAME DAY, WELCOME HOME, WINDING DOWN, FIRST SNOW, etc.
These are presentation moments, not modal alerts or new lifecycle states.

## CANDIDATE — Scene Morphing

Explore continuous aesthetic axes such as Relax ↔ Movie Night, Warm ↔ Moody,
Colts ↔ Neutral, or Focused ↔ Atmospheric. A request like “a little moodier”
could move along a bounded axis rather than generate a completely unrelated
scene.

Ownership spans #130 scene selection and #23 transition/application; #24 only
enters if HomeHub later learns a preference for the morph behavior.

## CANDIDATE — Rare-event rituals

Let genuinely uncommon events earn one-off atmosphere: first snow, first warm
spring evening, first thunderstorm after winter, season opener, playoff clinch,
holiday/birthday, unusually notable sunset, or another event Anthony explicitly
cares about.

These are transient rituals, not permanent modes. Weather-based rituals should
reuse #134/#130; planned social events belong with #140/#141.

## CANDIDATE — Memory Postcards + House Signature

Extend the Apartment Logbook with occasional aesthetic summaries rather than
wellness scores: a storm night, a memorable game, a guest night, or a monthly
“house signature” showing dominant atmosphere/time/music/weather patterns and a
generative visual derived from them.

AI may generate the prose/visual treatment, but factual inputs must remain grounded
in HomeHub history and the output should distinguish remembered events from creative
styling. Avoid physiological/psychological claims. This is creative reflection on
HomeHub state and activity history.

## CANDIDATE — HomeHub Easter eggs

Rare, non-authoritative unlocks can make the system playful: first snow animation,
season/playoff artifact, long-running uptime anniversary, a hidden scene after a
meaningful milestone, etc. They must not affect safety or automation behavior.

## FOLDS INTO #140/#141 — Guest voting + live event board

Let guests vote between bounded scene/music choices rather than individually
fighting controls. For planned gatherings, make the guest mini-app event-specific:
current vibe, music, Home Bar suggestion, food/status, voting, and a small recap.
[#140](https://github.com/agatte/home-hub/issues/140) owns event orchestration;
[#141](https://github.com/agatte/home-hub/issues/141) owns per-event guest UX.

# Game Day experiential candidate pool

These extend the shipped Game Day engine; they do **not** reopen completed #45,
overload #10, or replace #153 provider-health work.

## CANDIDATE — Broadcast Director / commercial-phase detection

Infer live game → commercial → studio/halftime → live game locally from existing
screen/audio evidence. During a break, briefly relax Game Day intensity and make
kitchen/path lighting more useful; restore the game atmosphere when play returns.
This is a Media Director specialization and should degrade safely when uncertain.

## CANDIDATE — Pressure Field

Make the room subtly reflect game tension continuously instead of reacting only
to scores: possession, red zone, third/fourth down, clock/margin, and reliable
win-probability or stakes context can tighten/relax contrast and Colts identity.
Keep it restrained; celebrations remain special events.

## CANDIDATE — Rare Comeback / impossible-moment sequence

Reserve one spectacular choreography for truly rare momentum swings or comeback
wins. The point is scarcity: ordinary touchdowns must not exhaust the system's
maximum expressive range.

## CANDIDATE — Apartment-as-field territorial lighting

Experiment with extremely subtle spatial emphasis that advances through bedroom,
living-room, and kitchen fixture groups as a Colts drive advances. Treat it as
playful atmosphere, never a requirement for readable game state.

## CANDIDATE — Opponent identity + rivalry treatment

Give the opponent a bounded architectural accent while the Colts remain the
primary room identity. Rival/division/playoff games may earn stronger treatment,
provided it remains aesthetically coherent rather than becoming generic RGB.

## CANDIDATE — Halftime Intermission

Treat halftime as a real phase: loosen Game Day lighting, improve kitchen utility,
surface a concise halftime summary, and stage the return into the second half.
Do not rely on unsolicited long TTS.

## CANDIDATE — Season Memory Wall / game posters

Create an abstract post-game artifact from score, opponent, scoring/momentum
timeline, turning point, and HomeHub celebration events. Build a season history
without retaining copyrighted broadcast screenshots/video.

## CANDIDATE — Crowd Energy

Use the Blue Yeti shadow lane to estimate notable crowd/room reaction energy and
pair it with confirmed ESPN events. Potential output is retrospective (“loudest
game/moment”), not an automatic claim about number of guests or physical room.

[#10](https://github.com/agatte/home-hub/issues/10) remains only the
observation-driven 3D-field tuning issue. New theatrical features require their
own selection/owner decision if Anthony promotes them.

# Job 3 — “Wait, our existing hardware can do what?”

## Hardware discovery rule

Before a lab idea becomes “buy a sensor/device,” perform an **owned-hardware
inventory check**. Ask Anthony about relevant unused/underused gear because the
repo cannot know everything in the apartment. Useful categories to ask about
when a concrete experiment warrants it include old phones/tablets/computers,
webcams/mics/speakers, routers/extenders, smart speakers/displays, wearables,
streaming boxes/TVs, game/VR peripherals, SBCs/microcontrollers, smart plugs,
and other networked electronics.

Do not ask for a giant inventory up front just to fill a spreadsheet. Ask when a
promising capability would materially change if suitable hardware already exists.

## Known underused / latent hardware surfaces

| Existing surface | Current use | Underused opportunity |
|---|---|---|
| Blue Yeti on Windows | YAMNet/audio shadow lane | Apartment Sound Atlas, household-event corroboration, appliance/fan signatures, Game Day crowd energy; current failed multi-speaker Social gate should not define the mic's future. |
| Windows desktop / OS | agents, process/media state, screen capture, Brio sensing | Richer OS context bus, audio-session semantics, display/session state, Media Director, local analysis/calibration. |
| Desktop + Latitude cameras | source-qualified Desk/Bed/Couch presence/localization and lux | Transition/topology learning, explicit physical light calibration, diagnostics/replay fixtures; never weaken current physical-authority rules. |
| iPhone / Shortcuts | vibe/geofence/tunnel actions | Semantic context bridge for alarm/Focus/charger/Wi-Fi/headphones/app/sound events where opt-in and useful. |
| Apple Watch / Health | #236 shadow sleep evidence direction | Keep parked behind its real delivery/development constraints; do not let it block other no-purchase ideas. |
| Google Wifi / local network | routing/DNS infrastructure | Probe what local client/RSSI/association telemetry is actually accessible before assuming phone XY location or requiring new RF hardware. |
| Hue bridge / EventStream | lighting control + push state | Better calibration/feedback, richer scene choreography, precise manual-intervention evidence; still an actuator system, not physical presence authority. |
| Sonos | playback/TTS/ambience | Playback/context evidence and experiential integration; only use acoustic probing if timing/processing characteristics are proven suitable. |
| Latitude built-in microphone | currently not the active audio source | [#68](https://github.com/agatte/home-hub/issues/68) keeps this as a parked fallback because prior real-room behavior was poor; availability alone is not a reason to revive it. |

## LAB — Acoustic room fingerprinting

Investigate whether a phone/laptop speaker+microphone can emit a brief inaudible or
near-inaudible probe and classify the room from echo/reverberation. This is a
research experiment only: measure audibility, repeatability, media interference,
privacy, and whether our apartment geometry is distinguishable before considering
any semantic use.

## LAB — Commodity Wi-Fi RSSI sensing / trajectory experiments

Keep the original Wi-Fi-location idea, but frame it correctly: first inventory
what RSSI/client telemetry current Google Wifi, Windows, phones, or other owned
network hardware can expose locally. Shadow-log repeatability before imagining
position or presence authority. IEEE/Wi-Fi sensing research does not imply the
current consumer router already exposes a reliable XY API.

## LAB — Acoustic gesture controls

Explore whether existing speakers/microphones can detect a tiny set of deliberate
contactless gestures around a stable area. This is novelty research, not a
replacement for reliable UI/voice/manual control. It must be opt-in and robust to
TV/music before any live command is considered.

## LAB — Appliance / equipment acoustic signatures

Test whether the Blue Yeti or phone can reliably distinguish stable local
signatures such as projector fan, vacuum, water, HVAC, kitchen appliances, PC fan
ramp, or other equipment Anthony actually owns. Prefer a small “sound atlas” and
confusion matrix over a grand generic classifier.

## LAB — Other owned-hardware surprises

Keep a standing research question: **what capability becomes possible because
Anthony already owns a device HomeHub is not using?** Examples are intentionally
not commitments. A spare phone/tablet might become a temporary calibration node;
a second microphone/webcam might close a blind spot; a smart speaker/display or
network peripheral might expose useful local telemetry; old computing hardware
might host a shadow experiment. Inventory first, then research the specific device.

# Retained lower-specificity ideas

These remain valid possibilities but are not detailed enough to deserve active
issues yet:

- local voice processing if it provides a clear benefit beyond the existing Alexa
  and iOS control surfaces;
- additional device categories only when they create a concrete HomeHub experience;
- multi-room audio if additional owned/installed audio hardware makes it relevant;
- generic composable automation only after repeated real experiences demonstrate
  duplication that a shared composition layer would actually remove;
- a non-actuating scene rehearsal/preview surface, potentially reusing #240's
  no-op/counterfactual infrastructure.

# Existing open-work index and dedupe guardrails

Keep these older issues separate; do not reinvent them under new brainstorm names:

- [#3](https://github.com/agatte/home-hub/issues/3) — verify the historical Social
  L1 violet-wall-flood concern in the current room before retuning.
- [#10](https://github.com/agatte/home-hub/issues/10) — only observation-driven
  Game Day 3D-field tuning; not a bucket for every new Game Day effect.
- [#16](https://github.com/agatte/home-hub/issues/16) — shared sequence executor
  only if accepted experiences demonstrate duplicated sequencing logic.
- [#19](https://github.com/agatte/home-hub/issues/19) — safe context reacquisition
  after outage, never blind replay of stale modes/lights/music.
- [#20](https://github.com/agatte/home-hub/issues/20) — audio anomaly
  corroboration/suppression consequences, not a generic audio intelligence owner.
- [#23](https://github.com/agatte/home-hub/issues/23) / [#24](https://github.com/agatte/home-hub/issues/24)
  — transition choreography and later bounded preference learning.
- [#30](https://github.com/agatte/home-hub/issues/30), [#31](https://github.com/agatte/home-hub/issues/31),
  [#32](https://github.com/agatte/home-hub/issues/32), [#36](https://github.com/agatte/home-hub/issues/36),
  [#41](https://github.com/agatte/home-hub/issues/41), [#53](https://github.com/agatte/home-hub/issues/53),
  and [#55](https://github.com/agatte/home-hub/issues/55) — require current
  implementation inventories/measurements before prescribing changes.
- [#51](https://github.com/agatte/home-hub/issues/51) — operational notification
  delivery, separate from #132 contextual suggestion timing.
- [#56](https://github.com/agatte/home-hub/issues/56) — desktop-only desk posture
  calibration. [#68](https://github.com/agatte/home-hub/issues/68) — parked
  Latitude-microphone fallback only if a physical-context gap justifies it.
- [#74](https://github.com/agatte/home-hub/issues/74) — durable recovered-outage
  observability, not an external watcher.
- [#105](https://github.com/agatte/home-hub/issues/105) — current Gaming
  color/screen-tracking design pass, separate from already-solved brightness floors.

# Historical / superseded ideas

- [#18](https://github.com/agatte/home-hub/issues/18) global seasonal sine modifier
  is closed/not planned; seasonal context belongs with Scene Curator/weather.
- [#21](https://github.com/agatte/home-hub/issues/21) generic override classifier
  is closed/not planned and superseded by #131/#132.
- [#22](https://github.com/agatte/home-hub/issues/22) multi-day mood drift is
  closed/not planned and superseded by temporary Mood Context.
- [#45](https://github.com/agatte/home-hub/issues/45) Game Day stakes enrichment is
  completed; new Pressure Field/comeback ideas may consume reliable stakes/WPA data
  but do not reopen #45 merely to host them.
- [#63](https://github.com/agatte/home-hub/issues/63) is a closed historical
  brainstorm/source-of-truth artifact.
- [#72](https://github.com/agatte/home-hub/issues/72) is closed/not planned,
  superseded by #137 and #13's evidence-gated hardware fallback.
- [#77](https://github.com/agatte/home-hub/issues/77) is closed/not planned; its
  Nixeus-specific prescription is obsolete for the current monitor.
- [#94](https://github.com/agatte/home-hub/issues/94) and [#95](https://github.com/agatte/home-hub/issues/95)
  are closed/not-planned workflow migrations.
- [#120](https://github.com/agatte/home-hub/issues/120) is closed historical
  watcher false-positive evidence.

## Research checkpoint rule

Do not let this document become a graveyard or a second backlog. During future
roadmap reviews:

- keep selected ideas linked to their issue/owner;
- merge duplicate wording into one retained concept;
- delete an idea only when it is explicitly rejected/superseded and the reason is
  recorded here or in the owning issue;
- keep LAB ideas clearly below CANDIDATE/TRACKED work;
- periodically ask the three research-job questions again, including whether newly
  known or newly acquired hardware changes what is possible.
