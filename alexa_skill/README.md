# Home Hub Custom Alexa Skill

Phase 5 voice control. Bridges your Echo to the Home Hub backend through
AWS Lambda → Cloudflare Tunnel → tunnel proxy → FastAPI on the Latitude.

```
"Alexa, tell command center to set relax mode"
   → Alexa cloud (intent extraction)
   → AWS Lambda (lambda_function.py)
   → https://home-hub.gatte-home.com/api/automation/override
   → cloudflared (tunnel)
   → home-hub-tunnel.service on :8002
   → home-hub.service on :8000   (sets mode, lights flip)
```

Intents shipped:

| Intent | Try saying | What it does |
|---|---|---|
| `SetModeIntent` | "set relax mode", "make it gaming" | Manually overrides the activity mode |
| `ReleaseOverrideIntent` | "auto", "back to automatic" | Clears the manual mode override |
| `PlayMusicIntent` | "play the music" | Smart-play on Sonos |
| `PauseMusicIntent` | "pause the music" | Pauses Sonos |
| `AdjustBrightnessIntent` | "brighter", "make it dimmer" | ±10% on every on-light, mode-ceiling clamped |
| `SetEffectIntent` | "turn on the candle effect" | candle / fire / sparkle / prism / glisten / opal |
| `StopEffectIntent` | "stop the effect" | Stops any running dynamic effect |
| `ActivateSceneIntent` | "run the party scene" | Curated safelist: party, neon, miami, arcade, aurora, sunset |
| `EnableDNDIntent` | "enable do not disturb" | 2-hour DND window |
| `DisableDNDIntent` | "turn off do not disturb" | Clears DND |
| `AdjustVolumeIntent` | "turn the music up", "music down", "bump the song up" | ±5 on Sonos volume. **Must use up/down + music/song.** Alexa hijacks "louder"/"quieter" at the wake-word router so those words can't reach the skill |
| `NextTrackIntent` | "skip this song", "next track" | Sonos next |
| `PreviousTrackIntent` | "go back a song", "previous track" | Sonos previous |
| `WhatModeIntent` | "what mode am I in" | Speaks current mode + override status |
| `WhatsPlayingIntent` | "what's playing", "what song is this" | Speaks current track + artist |

**Printable cheat sheet:** `alexa_skill/voice_commands.pdf` — single-page,
two-column command reference. Re-generate after intent changes via
`python scripts/generate_voice_command_sheet.py`.

---

## Critical prerequisite — Alexa+ must be OFF

**If your Echo is on Alexa+ (Amazon's generative-AI tier), custom skills
do not route reliably.** Alexa+ uses LLM-based routing that intercepts
slot-based intents and routes them to its own smart-home executor instead
of your skill, even with explicit "ask command center" prefixes.

Check + disable: Alexa app → **More** → **Settings** → **Alexa+** →
disable. Wait ~60 seconds for propagation.

This was the single largest blocker during the initial setup. If voice
commands "Setting X mode" don't return verbal responses but the
simulator works, Alexa+ is the prime suspect.

## Why "command center" instead of something simpler

The invocation name MUST NOT collide with built-in Alexa concepts.
"home hub" was the obvious first choice but it collides with Alexa's
built-in smart-home hub category — Alexa interprets "ask home hub" as
"manage my smart home" and never invokes the skill. "command center"
is two distinct words that aren't an Alexa-reserved category.

Reserved/colliding names to avoid: `home hub`, `smart home`, `gaming`,
`movie`, `cinema` (any phrase Alexa uses for built-in features).

## One-time setup

### 1. AWS account + Lambda function (~10 min)

1. Sign up at https://aws.amazon.com (free tier covers everything we need —
   Lambda free tier is 1M invocations / 400 k GB-s per month; we'll use
   maybe 100/month).
2. Open the Lambda console: https://console.aws.amazon.com/lambda/home
3. Create function → **Author from scratch**
   - Function name: `home-hub-skill`
   - Runtime: **Python 3.11**
   - Architecture: x86_64
   - Permissions: "Create a new role with basic Lambda permissions" (default)
4. Click **Create function**.
5. In the **Code source** editor, replace the default `lambda_function.py`
   with the contents of `alexa_skill/lambda_function.py` from this repo.
   Click **Deploy**.
6. **Configuration → General configuration → Edit**:
   - Memory: 128 MB
   - Timeout: 5 sec
   - Save.
7. **Configuration → Environment variables → Edit → Add environment variable**:
   - `HOME_HUB_API_BASE` = `https://home-hub.gatte-home.com`
   - `HOME_HUB_API_KEY` = same value as the Latitude `.env`
   - `HOME_HUB_SKILL_TOKEN` = same value as the Latitude `.env`
   - Save.
8. Top-right of the function page: **copy the ARN**
   (`arn:aws:lambda:us-east-1:1234...:function:home-hub-skill`). You'll
   paste it into the Skill manifest in step 3.

### 2. Add the Alexa Skills Kit trigger to the Lambda

1. Still on the Lambda function page, click **Add trigger** (top-left
   diagram).
2. Select **Alexa Skills Kit**.
3. Skill ID verification: leave **Enable**, paste your Skill ID. (You'll
   get this from step 3 below — if you're going through this for the
   first time, do step 3 up to "create the skill," copy the Skill ID,
   then come back here.)
4. **Add**.

### 3. Alexa Developer Console — create the Skill (~10 min)

1. Sign up at https://developer.amazon.com/alexa/console/ask (free).
2. **Create Skill**:
   - Skill name: **Home Hub**
   - Primary locale: **English (US)**
   - **Choose a type to start with**: Custom
   - **Choose a method to host**: Provision your own (we use AWS Lambda)
   - Click **Create skill** → **Start from scratch** → **Continue with template**
3. **Invocation → Skill Invocation Name**: enter `command center` (lowercase, two words). The interaction model JSON ships this value too — keep them in sync.
4. **Interaction Model → JSON Editor**: paste the contents of
   `alexa_skill/interaction_model.json`. Click **Save Model**.
5. **Endpoint**:
   - Service Endpoint Type: **AWS Lambda ARN**
   - Default Region: paste the Lambda ARN from step 1.
   - Save.
6. **Build Model** (top of the page). Wait for the green "Full Build
   Successful" toast.
7. Copy the Skill ID (top-left of the console, under the skill name).
   Go back to the Lambda console and paste it into the Alexa Skills Kit
   trigger you added in step 2.
8. **Test** tab (top nav): switch the dropdown from "Off" to **Development**.
9. In the test simulator, type or speak: `open command center`. You should
   hear "Home Hub is ready..."
10. Try `tell command center to set relax mode`. Lights should flip on the
    Latitude dashboard within 2 seconds.

---

## Live testing on your Echo

Any Echo signed into the same Amazon account that owns the developer
console gets the skill automatically (in Development mode). Just speak
to it:

- "Alexa, open command center" → enters skill session
- "Alexa, tell command center to set gaming mode"
- "Alexa, ask command center to pause the music"
- "Alexa, tell command center to make it brighter"
- "Alexa, tell command center to run the party scene"
- "Alexa, ask command center to enable do not disturb"

If the skill doesn't respond, the most likely culprit is the Lambda env
vars — check **CloudWatch Logs** (Lambda → Monitor → View CloudWatch logs)
for the error.

---

## Updating the Skill or Lambda

- **Lambda code change** → paste the new `lambda_function.py` contents into
  the Lambda editor, click **Deploy**. Effective immediately.
- **Interaction model change** (new intents, new utterances, new slot
  values) → paste the new `interaction_model.json` into the JSON Editor,
  click **Save Model**, then click **Build Model**. Wait for the build.
- **Environment variable rotation** (e.g., new `HOME_HUB_SKILL_TOKEN`) →
  update the Lambda env var, save. Effective on the next invocation
  (no redeploy needed).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Home Hub didn't respond" | Lambda can't reach the tunnel | curl https://home-hub.gatte-home.com/health from outside LAN; check cloudflared status on the Latitude |
| "Home Hub rejected the request" | Skill token mismatch | Verify Lambda env var matches the Latitude .env |
| "I don't have a handler for X" | New utterance routed to wrong intent | Re-check sample utterances, rebuild model |
| Alexa stays silent / "There was a problem" | Lambda crash | CloudWatch Logs (filter by error level) |
| Slot value not resolving | User said something not in the synonym list | Add the synonym to interaction_model.json, rebuild |
| "I don't have a {scene/effect} called X" when X is on the safelist | Lambda is reading the slot's `name.value` instead of its `id` | Use `_resolved_slot()` (returns id) when the slot type's id ≠ value. Currently HOMEHUB_SCENE — spoken "party" → id "house_party" |
| "Turn on {Mode}" misroutes and Alexa asks "Which effect?" | Two custom intents share a verb pattern but only one had it | Mirror the verb shape on every colliding intent so NLU disambiguates by slot-type validity. Each "turn on {X}" / "start {X}" lives on both SetModeIntent and SetEffectIntent for this reason |
| "Louder" / "make it louder" changes the Echo's own volume, not Sonos | Reserved Alexa volume tokens hijack at the wake-word router before the skill is invoked. Even "make the music louder" hijacks — any utterance containing "louder"/"quieter" routes to device volume | Use "up"/"down" only ("turn the music up", "music down"). Don't put "louder"/"quieter" in synonyms or samples — they're poison anywhere in the utterance |

---

## Post-ship audit notes (2026-05-06)

Findings from the regression sweep after Phase 3.5 shipped — recorded here so they don't get rediscovered later.

### `AdjustBrightnessIntent` doesn't show up in `light_adjustments`

`POST /api/lights/brightness/{up,down}` — the route Alexa hits for "make it brighter / dimmer" — bumps every on-light through a multi-light bulk path that bypasses `_log_light_change()`. End-to-end the lights respond correctly, but the change is invisible in the `light_adjustments` event table. Direct per-light writes (`PUT /api/lights/{id}`) and `automation`-driven changes are still logged.

Impact: when behavioral mining starts pulling from `light_adjustments`, Alexa-initiated brightness bumps will be silent. Guest brightness bumps share the same path and have the same gap.

Not a Phase 3.5 regression — neither pathway has ever logged. Worth a one-line `_log_light_change(trigger="rest")` call in the bulk handler if/when it matters.

### `/health` reports `fauxmo: false`

The Phase-1/2 voice-control story (CLAUDE.md, `docs/PROJECT_SPEC.md` §"Voice Control") describes Fauxmo + Custom Skill running side by side — 7 virtual WeMos for simple on/off intents plus the skill for everything else. Audit shows Fauxmo isn't running on the Latitude.

Either Fauxmo was intentionally retired now that the Custom Skill covers all 15 intents, or it's stalled and nobody noticed. Skill alone is sufficient for current voice surface, so this isn't a functional gap. Decision pending: either revive Fauxmo (`FAUXMO_ENABLED=true` + restart) or strike Fauxmo from the spec.

### `ml_metrics` still emits retired-lane rows

`compute_per_source_metrics` walks 14 days of `ml_decisions`, so `accuracy_behavioral` and `accuracy_presence` rows continue to appear in `ml_metrics` even though both lanes were retired in the 2026-04-27 fusion refactor / Path-A predictor strip. Self-purges by 2026-05-11 (the 14-day window). Cosmetic, no action needed.
