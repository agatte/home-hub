# HomeHub AI Semantic Layer — Research Architecture Proposal

> **Status:** Non-authoritative future architecture proposal.
> **Reviewed:** September 7, 2026.
> **Registry:** [`Future_Development.md`](Future_Development.md).
> **Product truth:** [`PROJECT_SPEC.md`](PROJECT_SPEC.md) remains authoritative.

## Decision

HomeHub should use generative/multimodal AI as a **semantic and analytical layer
around the deterministic automation core**, not as a new whole-home authority.
AI is best suited to language interpretation, evidence synthesis, multimodal
classification, pattern discovery, and creative presentation. Existing lifecycle,
ownership, safety, room-authority, and device-application code remains decisive.

This deliberately separates generative AI from the ML already in HomeHub: YOLO /
MediaPipe presence, YAMNet, LightGBM, the lighting learner, and the music bandit
remain their own bounded inference systems with their existing authority rules.

The existing `VibeRouter` is the useful precedent: deterministic phrase handling
runs first; optional LLM parsing is constrained to known modes/scenes and validated
before existing application code acts. Future AI work should generalize that
**bounded interpreter** pattern instead of adding provider calls throughout the
codebase.

## Authority classes

Every AI task declares an authority class before it is implemented:

1. **READ_ONLY_ANALYSIS** — explain, summarize, compare, or answer from bounded
   HomeHub evidence. No write tools.
2. **ADVISORY_STRUCTURED** — translate subjective or natural-language input into
   a validated structured suggestion. Existing owners decide what to do with it.
3. **SHADOW_EVIDENCE** — produce one bounded semantic signal such as media phase
   or sound event. It may be logged/evaluated but has no direct consequence.
4. **USER_INTENT_BOUNDED** — interpret an explicit user request into an allowlisted
   existing action/scene/mode contract, then hand it to normal authority gates.

There is intentionally no generic **AI autonomous authority** class. If an action
later earns automation, #131 graduates that consequence independently; the AI
output itself does not become privileged evidence merely because a model is
confident.

AI must never independently establish Away/Home/Sleeping, manufacture a physical
room, bypass manual/DND/transit/ScreenSync/external-off ownership, or write raw
Hue/Sonos/projector/Kasa commands outside existing validated application paths.

If model/provider/schema validation is unavailable, the task abstains or uses its
explicit deterministic fallback. Failure must not silently widen authority.

## Shared task runtime

Do not build a large framework before one task proves useful. The first Analyst
prototype may use a thin provider wrapper, but once a second real consumer exists,
extract a shared `AITaskService`/semantic-task runtime with these contracts:

- task name/version and correlation ID;
- authority class;
- bounded input bundle and privacy class;
- explicit JSON-schema output contract;
- provider policy (`local_preferred`, `cloud_allowed`, or task-pinned);
- latency/token/cost budget and timeout;
- deterministic fallback or abstention behavior;
- model/provider/version metadata;
- validated structured result plus evidence references;
- cache policy and retention policy.

The runtime should support different providers per task. Frequent/private/simple
classification can prefer a local model; rare difficult synthesis can use an
approved cloud provider. Provider choice is a benchmark decision, not product
semantics, and changing model vendors must not change authority.

Deterministic parsing should still run before AI where it is cheap and reliable.
For example, `VibeRouter` should keep obvious phrase matches fast and free even if
its fallback later moves behind the shared runtime.

Do not expose unrestricted MCP/SQL/device tools to the model. Build task-specific
evidence bundles and narrow action adapters instead.

## Evidence and observability contract

AI explanations must be grounded in **named HomeHub evidence**, not model memory.
A result should be able to point to event IDs, timestamps, source-qualified
observations, ownership decisions, build/config identifiers, or replay-step IDs
that support each material claim.

Persist concise rationale and evidence references; do not request, depend on, or
store model chain-of-thought. A future `ai_task_runs` record may include task/model,
input hash, evidence refs, structured output, status, latency, estimated cost,
cache hit, and user acceptance/correction where useful.

Prefer normalized derived evidence over raw camera/audio/screen content. Raw media
is allowed only for a task that genuinely needs multimodal interpretation, should
be transient by default, and must preserve current camera/Sleeping/privacy rules.
Do not retain screenshots or microphone clips merely because a model consumed them.

AI-produced claims use explicit uncertainty: `supported`, `conflicted`, `unknown`,
or a bounded confidence field where the task benefits from it. Missing evidence is
not permission to fill in a plausible story.

## Provider / local-compute policy

HomeHub should remain provider-neutral. Structured-output and tool-calling patterns
are available across cloud and local runtimes; the implementation should target the
HomeHub task schema rather than a vendor-specific response shape.

The Desktop's current Ryzen 5 5600 / RX 5700 XT / ~16 GB RAM makes small quantized
local-model experiments credible, but not guaranteed. Benchmark representative
HomeHub fixtures before promising GPU acceleration, latency, or model size. Local
inference is attractive for privacy/frequency; cloud inference is attractive for
rare harder reasoning. Either path must fail closed.

## Ranked HomeHub use cases

### 1. HomeHub Analyst / grounded incident explainer

**Authority:** `READ_ONLY_ANALYSIS`. **Foundation:** #240.

Turn a bounded window of event history, mode provenance, source health/freshness,
light/media writes, ownership gates, and build/config state into a concise causal
explanation. It should answer “why is HomeHub in this state?”, “why did this change
happen?”, and “what conflicted during this window?” without actuating anything.

The model is not the forensic engine. #240 owns deterministic capture/replay and
the authoritative trace; the Analyst consumes that trace/evidence and makes it
easier to understand. A useful first prototype can begin against existing history
before all of #240 is complete, provided its evidence bundle is explicit and
read-only.

### 2. Lighting feedback interpreter / Scene Critic

**Authority:** `ADVISORY_STRUCTURED`. **Owners:** #130, then #131 for learning.

Translate feedback such as “the kitchen is competing,” “a little moodier,” or
“L1 needs to feel intentional” into a structured preference delta: fixture role,
relative hierarchy, warmth/saturation direction, contrast, and confidence. The
Scene Curator still generates legal targets and existing lighting ownership still
controls application.

A multimodal calibration variant may compare an explicit room snapshot with the
requested/actual light states, but it remains advisory and test-session-only.

### 3. Routine Miner / habit discovery

**Authority:** `READ_ONLY_ANALYSIS` first. **Graduation:** #240 → #131/#132.

Use historical HomeHub episodes to propose recurring sequences we did not program.
AI may label/summarize candidate patterns, but frequency/support should be computed
from real event data. Candidate routines should be replayed/counterfactually tested
before they become suggestions, and each eventual action graduates independently.

### 4. Media Director / content-phase understanding

**Authority:** `SHADOW_EVIDENCE` first.

Classify transient media state into a small schema such as `content`, `pause/menu`,
`credits/end`, `commercial`, `studio/halftime`, or `unknown`. Downstream Watching,
ScreenSync, and Game Day owners decide whether that evidence is useful. Media-phase
AI must never become physical-presence authority and should not retain screenshots.

### 5. Conversational HomeHub concierge

**Authority:** read-only questions plus `USER_INTENT_BOUNDED` for explicit commands.

Provide a HomeHub-native interface for questions such as “why are these lights on?”
or “what happened while I was gone?”, and for semantic commands such as “make this
a little warmer.” Reuse task-specific evidence and existing action adapters rather
than giving the model the developer MCP's unrestricted query/write surface.

The existing `VibeRouter` is the first bounded natural-language command precedent.
`#132` owns uncertain suggestion interaction; `#107` owns arrival use cases.

### 6. Apartment Sound Atlas

**Authority:** `SHADOW_EVIDENCE`.

Use the Blue Yeti for narrow household-event semantics that fit the hardware:
water/dishes, vacuum, door/knock, appliance signatures, sustained quiet, crowd
energy, and similar bounded classes. AI or embeddings may help label/correlate
these events, but audio cannot manufacture a physical room or guest count.

### 7. Creative reflection and presentation

**Authority:** presentation-only.

Memory Postcards, House Signature summaries, rare-event copy, title cards, and
other creative surfaces can use AI because small stylistic variation is desirable
and failure has no lifecycle/device consequence. Keep factual inputs grounded in
HomeHub history and avoid physiological/psychological claims.

## First prototype — HomeHub Analyst

Use the September 7 overnight Sleeping-vs-Watching incident as the first gold
fixture. The accepted human investigation already provides a strong reference
answer and exposed exactly the kind of cross-source causal chain the Analyst should
make cheap.

The prototype is on-demand only. It receives a bounded evidence bundle for a
requested window and has **no write tools, no device adapters, no notifications,
and no raw camera/audio requirement**.

Initial evidence bundle:

- bounded `activity_events` / light adjustments / relevant mode changes;
- current and historical override/source provenance;
- source-qualified process/presence observations and freshness;
- ownership/suppression events relevant to the incident;
- service/build/config identifiers needed to interpret behavior;
- deterministic #240 trace/replay output as soon as that surface exists.

Initial structured result:

- `summary` — concise answer to the question;
- `timeline[]` — ordered material events with evidence IDs;
- `claims[]` — claim, support status, evidence IDs, confidence;
- `conflicts[]` — evidence that disagreed or changed authority;
- `unknowns[]` — questions the bundle cannot answer;
- `recommended_checks[]` — read-only next evidence to gather if useful.

Acceptance for the gold incident:

- reproduces the known Sleeping → process Watching/Working conflict accurately;
- distinguishes the lifecycle defect from the later wireless-input explanation;
- identifies the Hue external-off ownership interaction without inventing writes;
- every material causal claim cites evidence present in the bundle;
- unsupported critical claims are zero in human review;
- uncertainty remains explicit when evidence is missing;
- tests prove the Analyst path cannot actuate HomeHub.

## Sequencing

1. **Evidence first:** continue #240's deterministic capture/replay work; define the
   Analyst evidence bundle against one real incident.
2. **Analyst prototype:** benchmark a deterministic summary baseline, one credible
   local model, and one approved cloud model against fixed fixtures. Select per
   evidence quality, unsupported-claim rate, latency, privacy, and cost.
3. **Scene Critic:** after #129 daylight acceptance and when #130 resumes, add the
   second structured AI task. If both consumers share real runtime needs, extract
   the common `AITaskService` instead of pre-building it.
4. **Routine Miner:** discover patterns, then require #240 replay and #131/#132
   graduation before suggestions or automation.
5. **Media/Sound:** pursue shadow multimodal/audio tasks only where existing
   ScreenSync/Game Day/kitchen evidence shows a concrete benefit.
6. **Concierge/creative layer:** reuse the proven task runtime for natural-language
   querying and low-risk presentation rather than building a separate AI stack.

This AI research does not displace current lived acceptance work (#129/#235) or
turn the future registry into an active sprint. Promotion still follows the normal
GitHub/product flow.

## External precedents / feasibility references

These are research references, not HomeHub product authority:

- Home Assistant AI Task: task-specific provider abstraction, structured output,
  and optional multimodal attachments: https://www.home-assistant.io/integrations/ai_task
- Home Assistant's 2025 AI architecture discussion: AI for generative/open-ended
  tasks while preserving normal smart-home control paths:
  https://www.home-assistant.io/blog/2025/09/11/ai-in-home-assistant/
- OpenAI Structured Outputs: strict JSON-schema response contracts for supported
  models: https://platform.openai.com/docs/guides/structured-outputs
- Ollama structured outputs and tool support for local task experiments:
  https://docs.ollama.com/capabilities/structured-outputs and
  https://ollama.com/blog/tool-support
- Ollama hardware/Vulkan support changes continue to evolve; benchmark the actual
  Desktop rather than assuming RX 5700 XT acceleration from a compatibility list:
  https://docs.ollama.com/gpu

The external ecosystem supports the architecture pattern; HomeHub's own evidence,
privacy, ownership, and lived acceptance determine whether any individual task is
worth shipping.
