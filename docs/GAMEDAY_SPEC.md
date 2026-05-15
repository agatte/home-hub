# Game Day — Feature Spec (Phases A + B + C shipped)

> **Phase A complete 2026-05-06; Phase B Slices A/B/C/D shipped 2026-05-07** with full worktree-fleet experiment + a follow-up dynamic-volume refinement (§9). **Phase C shipped 2026-05-07** — `gameday` exposed in FloatingNav, MODE_CONFIG theme entry, Alexa `HOMEHUB_MODE` slot + lambda `VALID_MODES`. Voice-end-to-end verified.
>
> Live preseason validation: 2026-08-13. Remaining work: SEQUENCES palette/TTS iteration with lighting-curator review.

Game Day is a season-bounded mode that turns the apartment into a Colts viewing room. ESPN drives the play feed; the dashboard celebrates scoring plays with custom light + TTS choreography; a 3D Threlte football field on the SvelteKit page mirrors live game state. Synthetic test endpoint `POST /api/gameday/test/{event}` fires real celebrations end-to-end (verified live 2026-05-07).

---

## 1. Decision summary

| # | Decision | Choice |
|---|---|---|
| 1.1 | Celebration scope (v1) | TD + FG + kickoff + end-of-game (4 events). Pre-game ambient + commercial-break deferred to v2. |
| 1.2 | Mode trigger | Auto-flip 30 min pre-kickoff via ESPN schedule; auto-exit 30 min post-game; manual override (Alexa + dashboard) always available. |
| 1.3a | Choreography building blocks | Fully custom CelebrationOrchestrator sequences. No stock effect calls (`sparkle`/`prism`/etc.). |
| 1.3b | Color palette | Free choice per event — each event has its own per-light HSB sequence. |
| 1.4a | TTS line authoring | 3–5 hand-written variations per event, randomized; ESPN play data (player, kicker, yards) threaded in where available. |
| 1.4b | TTS volume behavior | Duck-and-resume (existing pattern from `winddown_routine.py`). |
| 1.4c | Win/loss split | Win-only TTS at end-of-game. Loss is silent — lights handle the wind-down. |
| 1.5 | GameDay page visual | 3D pixel-art Threlte field with team logos, ball position synced to play state, floating scoreboard. |
| 1.6 | Mode integration | First-class automation mode, priority `6` (top auto-detected slot). Sleeping override still wins (persistent). |
| 1.7 | Phase B fleet commitment | Commit to 4-worktree parallel fleet now. Phase A spec is written for parallelism. |
| 1.8 | TTS volume model | Dynamic, "reads the room." WPA-driven (ESPN winprobability) primary signal with margin+time fallback; apartment-context modifiers (sleeping/DND/late-night/camera-absent); silent on losing blowouts. See §9. |

---

## 2. User-facing behavior

### 2.1 Mode lifecycle

```
T-30 min     T+0 min        T+game time          T+30 min
   │           │                 │                    │
   ├──auto────►├────in-game─────►├─auto-exit─────────►├──post-game
   │           │                 │                    │
gameday      kickoff         play events          gameday off
mode on      celebration     (TD/FG)              (wind-down)
```

- **T-30 min**: GameDayService observes "Colts game starts in 30m" from the ESPN schedule cache. Calls `automation.set_manual_override("gameday", source="gameday:auto")`. Mode-change callbacks fire (MusicMapper picks Colts pre-game playlist if mapped; screen-sync paused; camera zone overlays still active).
- **T+0**: Kickoff event detected from ESPN play feed. CelebrationOrchestrator fires the kickoff sequence (see §3.2.3).
- **In-game**: ESPN play feed polled every ~10s. CelebrationOrchestrator fires TD / FG sequences as play events arrive. Manual mode override (Alexa / dashboard) wins over auto.
- **T+game time +30 min**: Auto-exit clears the gameday override. If user manually overrode mid-game, auto-exit is suppressed.

### 2.2 Per-event behavior

#### Touchdown

- **Trigger**: ESPN play event with `scoringPlay=true` AND `scoringType.abbreviation='TD'` for the Colts side.
- **Lights**: 5–8 second custom sequence. Specifics TBD; placeholder pattern: blue/white pulse rotation across L1→L2/L5→L3+L4 (350ms each, L5 mirrors L2 on the same beat as a Phase A placeholder), then 3s sustained sparkle-style multi-pulse across all five lights, then fade to gameday baseline. L5 (Bedroom Lamp Right, installed 2026-05-11) is currently mirrored — Phase C curator review will differentiate it from L2 once the clear-housing visual character is exercised. Free choice per event (Decision 1.3b) — final values land in `CelebrationOrchestrator.SEQUENCES["touchdown"]`.
- **TTS**: One randomized line from the TD pool (3–5 variations). ESPN play description parsed for player name where format permits ("Jonathan Taylor 5 yard run for a TOUCHDOWN" → line variant: `"{player} in for six!"`). Duck Sonos to ~10 vol, play TTS, restore to prior volume.
- **Cooldown**: 8 seconds between any two celebration sequences (prevents stomping).

#### Field goal

- **Trigger**: ESPN play event with `scoringPlay=true` AND `scoringType.abbreviation='FG'` for the Colts side.
- **Lights**: 2–3 second shorter custom sequence. Free choice; placeholder: single blue/white pulse + brief flash. Lands in `CelebrationOrchestrator.SEQUENCES["field_goal"]`.
- **TTS**: 3–5 variations. Kicker name + distance threaded if ESPN exposes them ("{kicker} from {yards}!").
- **Cooldown**: same 8s as TD.

#### Kickoff

- **Trigger**: First play of the game (ESPN play type `kickoff` OR game state transition from `pregame` → `in-progress`).
- **Lights**: One-shot transition. Activate "gameday baseline" curated scene (defined in `routes/scenes.py` SCENE_PRESETS as `gameday_baseline`). Color palette is free choice — likely a Colts-tinted warm baseline that doesn't fight the apartment palette (Rule 5 in `feedback_lighting_design_principles.md`).
- **TTS**: 3–5 variations. ESPN matchup data threaded ("Colts vs {opponent}, kickoff!").

#### End-of-game

- **Trigger**: Game state transition from `in-progress` → `final`.
- **Lights**: Custom wind-down sequence. On a win: bigger celebration (5–8s like TD). On a loss: gentle 5–10s fade from gameday baseline back to whatever auto mode would otherwise apply.
- **TTS**: **Win only.** 3–5 variations with final score ("Colts win, {colts_score}–{opp_score}!"). Loss is silent.
- **Mode exit**: 30 min after this event, auto-clear override (unless user manually overrode mid-game).

### 2.3 Manual control surfaces

- **Alexa**: "Alexa, command center, game day on" / "game day off". Wired through the existing custom skill at `alexa_skill/lambda_function.py`. Slot type `HOMEHUB_MODE` gains `gameday` value.
- **Dashboard**: gameday button in `FloatingNav` or quick actions. Same `set_mode` API call as other modes.
- **Override-aware**: manual override flips set `source="manual"` and bypass the 30-min auto-exit window.

---

## 3. Architecture

### 3.1 Module diagram

```
ESPN API ─────► GameDayService ────► WebSocketManager ────► Frontend
                    │                       │                  │
                    │                       └─► broadcasts:    ├─► gameday store
                    │                          gameday_state,  │   (SvelteKit)
                    │                          gameday_play     │
                    │                                            ├─► FootballField.svelte
                    │                                            │   (Threlte 3D)
                    │
                    ├─► register_on_play_event(callback) ──────┐
                    │                                          ▼
                    │                                CelebrationOrchestrator
                    │                                  ├─► HueService (light sequences)
                    │                                  └─► TTSService (duck + speak + resume)
                    │
                    └─► register_on_state_transition(callback)
                          └─► AutomationEngine.set_manual_override("gameday")
```

### 3.2 Data flow

1. **Schedule polling**: GameDayService polls ESPN schedule endpoint hourly (cached 15 min). Knows next Colts game date + opponent + kickoff time.
2. **Pre-game flip**: 30 min before kickoff, GameDayService calls `automation.set_manual_override("gameday", source="gameday:auto")`. AutomationEngine fires mode-change callbacks.
3. **In-game polling**: every 10s during `in-progress`, GameDayService polls ESPN play-by-play. Diffs against last known state; emits `play_event` for new plays.
4. **Celebration dispatch**: CelebrationOrchestrator subscribes to `play_event`. On TD/FG/kickoff, runs the sequence. Cooldown enforced inside the orchestrator.
5. **Frontend sync**: WebSocketManager broadcasts `gameday_state` (score, clock, possession) on every poll cycle and `gameday_play` (description, type) on each new play.
6. **Game end**: GameDayService observes `final` state; emits `state_transition` event; CelebrationOrchestrator runs end-of-game sequence; 30 min later, GameDayService clears the override (unless `source!="gameday:auto"` — i.e. user manually overrode).

---

## 4. Interface contracts

### 4.1 `GameDayService` (backend)

**File**: `backend/services/gameday_service.py` (new)

```python
class GameDayService:
    """Owns ESPN polling and game state. Other modules subscribe; they do not poll ESPN themselves."""

    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def poll_state_loop(self, ws_manager) -> None: ...

    # Snapshot API — single source of truth for current state
    def current_state(self) -> GameDayState | None:
        """Returns: GameDayState(status, opponent, score_colts, score_opp,
                                 quarter, clock, possession, last_play) or None
                    if no game today."""

    # Subscription API — both callbacks are async
    def register_on_play_event(self, cb: Callable[[PlayEvent], Awaitable[None]]) -> None: ...
    def register_on_state_transition(self, cb: Callable[[GameDayStateTransition], Awaitable[None]]) -> None: ...

    # Properties
    @property
    def connected(self) -> bool: ...
```

```python
@dataclass
class GameDayState:
    status: Literal["pregame", "in-progress", "final", "no-game"]
    opponent: str | None
    kickoff_utc: datetime | None
    score_colts: int
    score_opp: int
    quarter: int  # 1-4, 5=OT
    clock: str    # "MM:SS"
    possession: Literal["colts", "opp", None]
    last_play: PlayEvent | None

@dataclass
class PlayEvent:
    timestamp: datetime
    play_type: Literal["touchdown", "field_goal", "kickoff", "other"]
    description: str         # raw ESPN play text
    player: str | None       # parsed from description, best-effort
    kicker: str | None       # for FG events, best-effort
    yards: int | None        # for FG events
    scoring_team: Literal["colts", "opp"] | None

@dataclass
class GameDayStateTransition:
    from_status: str
    to_status: str
    timestamp: datetime
```

**Polling cadences**:
- Schedule: hourly, cached 15 min.
- Play-by-play: every 10s during `in-progress`. Backs off to 60s during `pregame`/`final`.
- Stops polling entirely when no game scheduled in next 24h.

### 4.2 `CelebrationOrchestrator` (backend)

**File**: `backend/services/celebration_orchestrator.py` (new)

```python
class CelebrationOrchestrator:
    """Owns light + TTS sequencing for gameday events. Subscribes to
    GameDayService.register_on_play_event."""

    SEQUENCES: dict[str, CelebrationSequence] = {
        "touchdown": CelebrationSequence(...),
        "field_goal": CelebrationSequence(...),
        "kickoff": CelebrationSequence(...),
        "end_of_game_win": CelebrationSequence(...),
        "end_of_game_loss": CelebrationSequence(...),
    }

    COOLDOWN_SECONDS: float = 8.0

    async def on_play_event(self, evt: PlayEvent) -> None: ...
    async def on_state_transition(self, transition: GameDayStateTransition) -> None: ...

    async def _run_sequence(self, key: str, context: dict) -> None: ...
```

```python
@dataclass
class CelebrationSequence:
    light_steps: list[LightStep]      # ordered (timestamp, light_id → state) tuples
    tts_lines: list[str]              # 3-5 templates with {player}, {kicker}, {yards}, {opponent}, {colts_score}, {opp_score}
    tts_voice: str = "en-US-GuyNeural" # default; .env override applies
    duck_volume: int = 10              # Sonos volume during TTS
    duration_seconds: float            # total sequence length

@dataclass
class LightStep:
    light_id: str         # "1"-"4"
    delay_ms: int         # delay from sequence start
    state: dict           # {bri, hue, sat, ct, on, transitiontime}
```

### 4.3 `/api/gameday/*` routes (backend)

**File**: `backend/api/routes/gameday.py` (new)

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/api/gameday/state` | `GameDayState` JSON or `{"status": "no-game"}` | Current snapshot |
| GET | `/api/gameday/schedule` | `[{date, opponent, kickoff_utc, location}]` | Next 5 games |
| POST | `/api/gameday/test/{event}` | `{"status": "ok"}` | Trigger a sequence locally for tuning. `event` ∈ `touchdown`, `field_goal`, `kickoff`, `end_of_game_win`, `end_of_game_loss`. Auth required. |

All routes registered **before** the `/{path:path}` catch-all in `main.py`.

### 4.4 WebSocket events

| Type | Trigger | Data |
|---|---|---|
| `gameday_state` | every poll cycle | `GameDayState` (full snapshot) |
| `gameday_play` | new play arrives | `PlayEvent` |
| `gameday_celebration` | CelebrationOrchestrator fires | `{sequence_key, started_at}` (for UI flair) |

### 4.5 SvelteKit `routes/gameday/+page.svelte` (frontend)

Subscribes via `$gamedayStore` (new store at `frontend-svelte/src/lib/stores/gameday.js`). Layout:

```
┌─────────────────────────────────────────────────────────────┐
│  COLTS  21  ─────  14  TEXANS         Q3  4:32              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│              ┌──────────────────────────┐                   │
│              │                          │                   │
│              │   Threlte 3D field      │                   │
│              │   (FootballField.svelte) │                   │
│              │                          │                   │
│              └──────────────────────────┘                   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  Last play:  Jonathan Taylor 5 yard run for a TOUCHDOWN    │
│  Possession: COLTS                                          │
└─────────────────────────────────────────────────────────────┘
```

Falls back to a `no-game` state when `GameDayState.status == "no-game"`: shows the next scheduled game (date + opponent) and a faded field render.

### 4.6 `FootballField.svelte` + `footballfield/` subcomponents (frontend)

**Top-level file:** `frontend-svelte/src/lib/components/FootballField.svelte` — thin wrapper that defensively derives `hasGame`, `opponentAbbr`, `targetBallX` from the `game` prop and mounts a Threlte `<Canvas>` with `autoRender={false}` + `toneMapping={NoToneMapping}` + `shadows={true}` so the post-processing pipeline (PostFX) can drive rendering. The HUD scoreboard is owned by the `+page.svelte` route, not by FootballField.

**Subcomponents:** `frontend-svelte/src/lib/components/footballfield/`. Each is a pure prop-driven Threlte component composed by `FieldScene.svelte` (the top-level scene composition).

| Component | Role |
|---|---|
| `FieldScene.svelte` | Composition root inside `<Canvas>`. Imports + renders all sub-pieces. `<PostFX />` placed last so its `useTask` fires after every other scene-state task. |
| `BroadcastCamera.svelte` | Static `T.PerspectiveCamera` at `[0, 30, 75]`, ~22° pitch, FOV 50°. Phase 3 will swap to `camera-controls` for cinematic dynamics on plays. |
| `SkyDome.svelte` | Loads Poly Haven `stadium_01_2k.hdr` via `RGBELoader`, sets `scene.environment` for IBL on PBR materials, and instantiates a three.js `GroundedSkybox` mesh that re-projects the HDR's lower hemisphere onto a flat ground disc at world y=0. (Why static-import: see "Field rendering subsystem" §11 for the @threlte/extras `GroundProjectedSkybox` dynamic-import bug we sidestep.) |
| `StadiumModel.svelte` | Loads `static/3d/stadium.glb` (Awbmegames CC-BY low-poly football stadium) via `<GLTF>` from `@threlte/extras`. Y-rotated 90°, scaled 0.81, position offset y=-2.5. Hides bowl meshes on load via name-substring filter (default: `['stadium', 'cube']`) — the `Object001-006` floodlight/press-box meshes stay visible as ambience. |
| `FieldSurface.svelte` | The painted markings only — Colts blue endzone, neutral white opp endzone, 19 yard-line decals (every 5yd, midfield thicker), 2 goal-line decals at ±40 X, perimeter outline (4 sidelines + end lines forming the 100×53 rectangle). No grass plane — the HDRI ground is the visible surface. |
| `BallMarker.svelte` | Brown football geometry + soft glow disc. Eases toward `targetBallX` along the field's long axis with a mild bob. Honors `prefers-reduced-motion` (snaps with no bob). |
| `LightTowers.svelte` | 4 corner stadium light rigs at `[±95, 0, ±75]` — pole (cylinder) + emissive lamp head (BoxGeometry, picked up by bloom) + `T.PointLight` at lamp height. Always-on for now; phase 2.5 will gate by `kickoff_utc` for evening/night-only games. |
| `PostFX.svelte` | EffectComposer with `RenderPass → EffectPass(BloomEffect + ToneMappingEffect ACES_FILMIC)`. Drives `composer.render(delta)` via `useTask`. The parent `<Canvas autoRender={false}>` makes this the sole render driver. |

**Static assets** (under `frontend-svelte/static/3d/`):
- `stadium.glb` — Awbmegames Low Poly Football Stadium (CC-BY-4.0, Sketchfab, ~1.65 MB)
- `env/stadium_01_2k.hdr` — Poly Haven Stadium 01 HDRI (CC0, ~6 MB)
- `textures/grass-{color,normal,roughness}.jpg` — Poly Haven `leafy_grass` PBR set (CC0, ~13 MB total). Currently unused after phase 1.6 dropped the PBR grass plane in favor of the HDRI ground projection. Kept on disk as a fallback.

**Props in (boundary contract):**
```typescript
export let game: GameDayState | null;
export let theme: { primary: string; secondary: string } = { primary: "#002C5F", secondary: "#FFFFFF" };
```
FootballField derives the rest defensively; never throws on bad input.

The current implementation is photoreal-broadcast-style (HDRI-driven environment, PBR materials, post-processing), not pixel-art. See §11 "Field rendering subsystem" for the full rationale and roadmap.

---

## 5. Implementation slices (Phase B) — shipped

Per `docs/AGENT_STRATEGY.md` Part 3 — 4 worktree-isolated agents (only 3 ran in parallel; Slice A was solo-serial because it was the unblocking interface). Spec §4 interfaces held — zero merge conflicts across all four slices. See `AGENT_STRATEGY.md` Part 4 for the experiment retrospective.

| Slice | Status | Owns |
|---|---|---|
| **A** | ✓ Shipped 2026-05-06 (solo-serial main session) | ESPN poller + game-state model + `/api/gameday/*` routes + `automation.override_source` property |
| **B** | ✓ Shipped 2026-05-07 (worktree fleet) | `CelebrationOrchestrator` — light + TTS sequences subscribed to play events |
| **C** | ✓ Shipped 2026-05-07 (worktree fleet) | SvelteKit page rewrite + Svelte store + WS subscription |
| **D** | ✓ Shipped 2026-05-07 (worktree fleet) | Pure Threlte 3D `FootballField` component (top-down field + endzone tints + ball marker + HTML scoreboard overlay) |
| **Integration** | ✓ Shipped 2026-05-07 (main session) | `bootstrap.py` wiring + `init.js` WS dispatch + `+page.svelte` `<FootballField>` import |
| **Dynamic volume (§9)** | ✓ Shipped 2026-05-07 (Slice B agent continuation via SendMessage) | `celebration_volume_policy.py` + WPA on PlayEvent + apartment-context suppressions |

**Shared touchpoints owned by main session, NOT by any slice agent** (the file-disjoint plan worked — zero merge conflicts):
- `backend/bootstrap.py` lifespan — instantiates GameDayService + CelebrationOrchestrator, registers callbacks. ✓ wired.
- `backend/services/automation_engine.py` — `gameday` already in `MODE_PRIORITY` (=6) and `ACTIVITY_LIGHT_STATES` from the e6766c3 seam pass. ✓.
- `frontend-svelte/src/lib/stores/init.js` — three WS message types dispatched into the gameday store. ✓ wired.
- `frontend-svelte/src/lib/components/FloatingNav.svelte` — gameday entry (Trophy icon) ✓ Phase C 2026-05-07.
- `frontend-svelte/src/lib/theme.js` — `gameday` MODE_CONFIG entry (Colts blue #003594, silver/gold accents, energetic generative params) ✓ Phase C 2026-05-07.
- `alexa_skill/lambda_function.py` + `interaction_model.json` — `gameday` added to `HOMEHUB_MODE` slot (synonyms: "game day", "colts", "colts game", "football", "football mode"), `VALID_MODES`, disambiguation prompt ✓ Phase C 2026-05-07. Lambda + interaction model rebuild in AWS/Alexa Developer Console required (see `alexa_skill/README.md`).

**Live verification** (2026-05-07): `POST /api/gameday/test/touchdown` from desktop → Latitude logged `play_event: touchdown team=colts player=Test Player`, fired `celebration: firing touchdown sequence`, hue.set_light commands hit lights 1-4 with curator-tuned `_COLTS_BLUE_SAT=215`, kitchen pair held across all timestamps, Sonos ducked + played the templated TTS line, automation reconciled the post-celebration baseline back to the user's prior mode within ~20s.

---

## 6. Refactor seam pass (pre-Phase-B)

Before spawning slice agents, main session refactors these to make seams clean. Tracks under `chore(gameday-prep): ...` commits.

1. **Mode priority list** in `automation_engine.py` — extract to a module constant or enum so adding `gameday` is mechanical.
2. **Mode-change callback registration order** — confirm GameDayService's pre-game callback fires before MusicMapper's mode-aware playlist auto-play, so the right music starts on flip.
3. **Light state tables** in `light_state_calculator.py` — add a `gameday` row in `ACTIVITY_LIGHT_STATES` with `day` / `evening` / `night` / `late_night` periods. Initial values placeholder; CelebrationOrchestrator's sequences override during plays.

---

## 7. Open questions / refinements

- **ESPN play description parser quality** — ✓ **answered 2026-05-07.** Slice A's real-fixture test against `tests/fixtures/espn_colts_2025_summary.json` (Colts vs Dolphins 2025-09-07) confirmed both ESPN response formats parse cleanly: canonical `scoringPlays[]` full names ("Daniel Jones 1 Yd Rush", "Michael Pittman Jr. 27 Yd pass from Daniel Jones") AND abbreviated `drives.previous[].plays[]` initials ("D.Jones", "S.Shrader"). The parser tries TD-pass → TD-rush → abbreviated regexes in order; FGs try full-name → abbreviated. Tests cover both paths.
- **Light sequence values** — ✓ initial values shipped + curator-reviewed. Slice B agent authored placeholder Colts-blue/white pulse sequences for TD/FG/kickoff/end-of-game; lighting-curator caught + we applied an over-saturation fix (`_COLTS_BLUE_SAT` 254 → 215) before merge. Iterative palette authoring with the curator during preseason is tracked in [#5](https://github.com/agatte/home-hub/issues/5).
- **Pre-game / commercial behavior in v2** — still deferred. Pre-game ambient mode (continuous Colts-tinted lighting before kickoff) and commercial-break behavior (lights restore to mode default + Sonos resume on commercials) are out of scope for v1. Revisit post-preseason.
- **Preseason 2026-08-13 first test** — pending. 2026 schedule typically publishes May–June; check ESPN once published. The synthetic `/api/gameday/test/{event}` endpoint exercises the full pipeline (play_event → orchestrator → lights + TTS + WS) so we have confidence in the wiring; the preseason game is for tuning palette/timings/TTS lines against reality.
- **Celebration EventLogger gap** — ✓ closed 2026-05-07 (commit `34fc550`). `CelebrationOrchestrator._run_light_steps` now mirrors every successful `set_light` to `log_light_adjustment` with `trigger=f"celebration:{sequence_key}"`. Query celebrations via `WHERE trigger LIKE 'celebration:%'`; journalctl is now corroboration, not primary.
- **Agent fleet wiring** — ✓ shipped 2026-05-07. `gameday-preflight` fires from runbook entry #12 (preseason T-7) and #13 (weekly Sunday Aug-Jan) with bye-week early-exit. `gameday-postmortem` auto-fires from the loop's pre-fire detector when a `gameday:auto` window closes (real games only; manual `set_mode` doesn't trip it). See `docs/AGENT_STRATEGY.md` Part 5 for the full T-7d → T+90 timeline.

---

## 8. Verification — shipped status

**Phase A** (2026-05-06):
1. ✓ Spec reads end-to-end with all 8 sub-decisions explicitly recorded (§1).
2. ✓ Interface contracts (§4) name services, methods, file paths, JSON shapes concretely.
3. ✓ Mockup page renders cleanly with hardcoded data and the field-bleed layout.
4. ✓ `docs/PROJECT_SPEC.md` Roadmap section updated.

**Phase B** (2026-05-07):
1. ✓ Slice A: 21 GameDayService tests pass including a real-ESPN-response parser test.
2. ✓ Slice B: 30 CelebrationOrchestrator tests pass with kitchen-pair invariant + cooldown enforcement.
3. ✓ Slice C: frontend builds clean; no-game and in-game branches both render.
4. ✓ Slice D: Threlte component builds clean; defensive null-prop handling.
5. ✓ Integration: `POST /api/gameday/test/touchdown` fired live on the Latitude — lights pulsed, TTS played, WS broadcasts emitted, automation reconciled cleanly.
6. ✓ Curator review on Slice B's SEQUENCES caught + fixed an over-saturation anti-pattern.
7. ✓ Phase B integration build (commit `d9c1fcd`) shipped via `/deploy-home`; deploy-verifier returned STATUS=ok across 6/6 checks.

**Dynamic volume policy** (§9, also 2026-05-07):
1. ✓ 32 unit tests on `compute_celebration_volume` covering WPA bands, fallback formula, hard suppressions, apartment modifiers, clamping.
2. ✓ Real-fixture WPA computation test — extracts win-probability deltas from the 2025-09-07 Colts game.
3. ✓ Backend re-deployed (commit `ca712bd`); deploy-verifier ok.

**Phase C polish** (also 2026-05-07):
1. ✓ Celebration EventLogger wiring (β) — 33 celebration tests pass including 3 new `TestEventLoggerWiring` cases for the trigger format + backwards-compat + set_light failure handling. Shipped commit `34fc550`.
2. ✓ Agent fleet — `gameday-preflight` + `gameday-postmortem` registered as spawnable subagents; runbook entries #12 #13 + Pre-fire detector live. Smoke tests verified both via registered subagent types post-restart.

---

## 9. Dynamic celebration TTS volume — "read the room"

Shipped post-Phase-B (2026-05-07). Solves a real-world feedback loop: Slice B's hardcoded `duck_volume=10` was inaudible from the couch, but the right answer wasn't a louder constant — it was context-aware volume that scales with the moment.

**Module**: `backend/services/celebration_volume_policy.py` — pure function, no I/O, no service deps.

```python
def compute_celebration_volume(
    play: PlayEvent,
    game_state: GameDayState | None,
    *,
    base_volume: int = 30,
    sleeping_mode: bool = False,
    dnd_active: bool = False,
    camera_absent: bool = False,
    now: datetime | None = None,
) -> int | None:
    """Returns target Sonos volume (5-50) or None to suppress TTS.
    Lights fire regardless; this gates only the audio."""
```

**Hard suppressions** (return `None`, lights still fire):
- `sleeping_mode` — apartment is asleep
- `dnd_active` — Do Not Disturb override
- Losing blowout — `game_state.quarter >= 3 AND (score_colts - score_opp) <= -21`

**Primary signal: WPA** (when `play.wpa is not None`):
- `|WPA| >= 0.25` → +15 (huge swing — game-changing)
- `|WPA| >= 0.15` → +10 (big swing)
- `|WPA| >= 0.05` → 0 (standard)
- `|WPA| < 0.05` → -10 (decided game / polite)

**Fallback: margin + time** (when WPA not yet available — ESPN's WP model lags ~30-60s):
- Q4/OT, `|margin| <= 7`, `time_left < 120s` → +15 (clutch / 2-min drill)
- Q4/OT, `|margin| <= 7` → +10 (late close)
- `|margin| <= 3` → +5 (one-score game)
- Q4/OT, `margin >= 21` → -10 (winning blowout)

**Apartment-context modifiers**:
- Local hour ∈ [22, 06) → cap at 18 (late-night)
- `camera_absent` (no detection within 5 min) → vol − 10

Final clamp `[5, 50]`.

**Per-sequence base volumes**: TD 30, FG 28, kickoff 22, end_of_game_win 35, end_of_game_loss 0 (silent — `tts_lines=[]`).

**WPA plumbing**: GameDayService extracts per-play win probability from ESPN's `summary.winprobability[]` array and attaches Colts-perspective WPA to each emitted PlayEvent. Sign-flips when Colts are away. Returns `None` gracefully when ESPN's WP model hasn't yet indexed the play (10s polling cadence vs ESPN's WP-lag).

**Late-night gotcha**: at 22:00–05:59 Indy local, even big plays cap at vol 18. Synthetic test endpoint hits the all-fallback path (no WPA, no game state) so an after-hours smoke test will get vol 18 — that's the policy working correctly, not a bug. Volume constant calibration against real-game feedback is tracked in [#7](https://github.com/agatte/home-hub/issues/7).

---

## 10. Pre-game ambient mode (v2 design)

**Status:** spec only. Implementation tracked in [#9](https://github.com/agatte/home-hub/issues/9); target before preseason 2026-08-13.

The pre-game window is the hour leading up to kickoff. The current architecture has the apartment doing whatever it was doing (working, idle, etc) right up until the T-30 auto-flip lands the gameday baseline. v2 fills that hour with anticipation: lighting starts shifting earlier, and audio reads the season's stakes the same way `compute_celebration_volume` reads each play's stakes.

### 10.1 Decision summary

- **New mode `pregameday`**, priority 6 (matches `gameday`). gameday_service auto-flips the apartment to `pregameday` at T-60 and to `gameday` at T-30 (existing flip mechanic). `pregameday` clears at T-30 by way of being displaced; it doesn't have an independent clear path.
- **Lighting** is a "full pre-game palette" — all 4 lights take a Colts-tinted feel, distinct from the in-game gameday baseline. Kitchen pair held. Time-of-day variants (day / evening / night / late_night) parallel the existing gameday baseline structure in `light_state_calculator.py`.
- **Audio** is **playoff-stakes-aware** — same design philosophy as the WPA-driven celebration volume policy. Big-implication game → TTS announcement at T-30 + Sonos hype playlist auto-play. Out-of-playoff-running game → silent, lights only. Early-season fallback rules cover the period before playoff odds stabilize.
- **Verification** uses synthetic time injection on `gameday_service` (a `--mock-now` test hook) so the auto-flip can be exercised in dev without waiting for an actual kickoff window.

### 10.2 Lighting

**Trigger:** at T-60 ± 30s (poll cadence is 10s — actual flip lands within the next polling tick after the threshold crosses).

**Palette intent:** the "build" — Colts blue clearly present in the room, but with enough warm fill that the apartment doesn't feel like a sports bar yet. The in-game gameday baseline (already in `light_state_calculator.py:280-304`) is the destination; pre-game is a slightly less saturated, slightly cooler-temperature warmup. Kitchen pair invariant (L3 ≡ L4) held in every time-of-day variant.

**Schema parallel:** add a new top-level key `"pregameday"` to `ACTIVITY_LIGHT_STATES` with the same `day` / `evening` / `night` / `late_night` sub-structure already used by `gameday`. Each variant has 4 light entries. Placeholder structure matches gameday's saturation/brightness shape, dialed back ~15-20% on saturation and brightness. Lighting-curator iteration for real values before preseason is tracked in [#8](https://github.com/agatte/home-hub/issues/8).

**Curator iteration knob:** the saturation cap (currently `_COLTS_BLUE_SAT=215` for celebration pulses) provides a precedent. Pre-game L1 likely lands around `sat=170-185` (between mode-baseline warmth and gameday's full Colts-blue commit).

### 10.3 Audio — playoff-stakes-aware

Pure function in a new module `backend/services/pregame_audio_policy.py`, mirroring `celebration_volume_policy.py`'s shape:

```python
def compute_pregame_audio(
    *,
    season_week: int,        # NFL week 1-18 (preseason = week 0)
    is_preseason: bool,
    playoff_probability: float | None,  # ESPN's playoff odds, 0.0-1.0 or None
    is_eliminated: bool,     # mathematically out of contention
    division_gap_games: int | None,  # games behind division leader (None pre-week-3)
    record: tuple[int, int, int],    # (wins, losses, ties)
    sleeping_mode: bool = False,
    dnd_active: bool = False,
    now: datetime | None = None,
) -> PregameAudioDecision:
    """Returns {'tts_line': str | None, 'sonos_hype_play': bool}.
    Both None/False = silent pre-game (lights only).
    Hard suppressions (sleeping_mode, dnd_active) return both None/False
    regardless of stakes."""
```

**Decision shape** (`PregameAudioDecision`): `tts_line` is the line to speak (substituted with `{opponent}` etc), `sonos_hype_play` triggers `MusicMapper`-equivalent auto-play of a hype playlist. Both can fire (TTS first, Sonos starts after TTS finishes).

**Stakes tiers** (drive the decision):

| Tier | Condition | TTS | Sonos hype |
|---|---|---|---|
| **Eliminated** | `is_eliminated=True` | None | False |
| **Big stakes** | `playoff_probability ∈ [0.20, 0.80]` AND `season_week >= 8` | line from "big-stakes" pool | True |
| **Late-season clutch** | `season_week >= 14` AND `division_gap_games <= 1` | line from "clutch" pool | True |
| **Locked playoff seed** | `playoff_probability >= 0.95` AND `season_week >= 15` | line from "victory-lap" pool | True (mellow playlist) |
| **Standard / early season** | preseason OR `season_week <= 7` OR no special tier | line from "standard" pool | False (lights + TTS only) |

**TTS line pools** (authoring tracked in [#6](https://github.com/agatte/home-hub/issues/6); placeholder values below):
- "standard": `["Colts kick off in 30 minutes against the {opponent}.", "Game day. Colts and {opponent} in 30."]`
- "big-stakes": `["Colts and {opponent} in 30 minutes — big implications today.", ...]`
- "clutch": `["This is a must-win, Colts and {opponent} in half an hour.", ...]`
- "victory-lap": `["Playoffs locked, Colts and {opponent} in 30. Resting starters?", ...]`
- (Preseason override: `["Preseason kickoff in 30 minutes — Colts and {opponent}. Tuning the apparatus."]`)

**Sonos hype playlist** wired via the existing `mode_playlists` table — add a `pregameday` row with the user's pre-game playlist favorite_title. MusicMapper's existing on_mode_change callback handles the dispatch when the mode flips.

**Apartment-context modifiers (mirror celebration volume policy):**
- `sleeping_mode` or `dnd_active` → both `tts_line=None` AND `sonos_hype_play=False` (lights still flip).
- Local hour ∈ [22, 06) → if TTS would fire, gate volume to ≤18 (same late-night cap).

**Fire timing:**
- T-60: pre-game lighting palette activates (pregameday mode).
- T-60 → T-30: silent (lights-only build).
- T-30: gameday flip lands. Audio fires AFTER the flip via a new `on_mode_change` callback in MusicMapper-equivalent that handles `pregameday → gameday` specifically. TTS first (uses existing TTSService.speak), then Sonos auto-play begins ~2s later.

### 10.4 Architecture impact

**New module:** `backend/services/pregame_audio_policy.py` — pure function, no I/O, no service deps. Tests in `tests/test_pregame_audio_policy.py` cover all stakes-tier combinations + apartment-context modifiers + edge cases (week 0 preseason, mid-season bye, mathematical elimination boundary).

**Modified modules:**
- `backend/services/automation_engine.py` — add `"pregameday": 6` to `MODE_PRIORITIES`. Add `"pregameday"` block to `ACTIVITY_LIGHT_STATES` (in `light_state_calculator.py` actually, per current file split). Add `"pregameday"` to `MODE_TRANSITION_TIMES` (recommend 4s — slow build).
- `backend/services/light_state_calculator.py` — add `"pregameday"` block alongside `"gameday"` at line ~280. Day/evening/night/late_night variants. Effects: `pregameday` gets weather effects same as `gameday` (none by default).
- `backend/services/gameday_service.py` — extend `_check_pregame_window()` (currently fires at T-30) to also handle T-60. Add `_maybe_flip_pregame_ambient()` method that flips mode to `pregameday` at T-60 (idempotent, only if status=SCHEDULED). The existing `_maybe_flip_pregame()` becomes `_maybe_flip_gameday()` and continues to fire at T-30.
- `backend/services/music_mapper.py` (or a new sibling): on `on_mode_change(prev=pregameday, new=gameday)`, dispatch the playoff-stakes audio policy and fire TTS + (conditionally) Sonos hype.
- `backend/api/routes/gameday.py` — add `POST /api/gameday/test/pregame` for synthetic firing (mirrors existing test/{event} endpoints). Triggers a 30-second pregameday window then auto-clears.

**Constants** (in `gameday_service.py` near existing `PRE_KICKOFF_FLIP_MINUTES`):
```python
PRE_KICKOFF_FLIP_MINUTES = 30          # existing — gameday flip
PRE_GAME_AMBIENT_FLIP_MINUTES = 60     # new — pregameday flip
```

### 10.5 Playoff-odds sourcing

ESPN provides playoff probability via `summary.predictor.homeTeam.playoffProbability` and `awayTeam.playoffProbability` on game pages, but only after week 4-5. For weeks 1-3, the stakes function falls back to record + division-gap heuristics. For preseason (week 0 / `is_preseason=True`), the function returns the preseason-override TTS line and skips the playoff-tier branching.

**Sourcing implementation:**
- Cache playoff probability in `app_settings` under `gameday_playoff_state` after each game's poll. Refresh weekly on Tuesday after the Monday Night Football final (when ESPN's playoff model recomputes).
- Background `ScheduledTask` in scheduler.py: `playoff_state_refresh` at Tue 06:00 ET, fetches ESPN standings + playoff page for COLTS, extracts `playoffProbability`, writes to `app_settings`.
- gameday_service reads from `app_settings` at T-60 to feed the audio policy.

### 10.6 Verification

**Synthetic time injection:** add a `_now_override: datetime | None = None` class attribute to `GameDayService`. When set, `_check_pregame_window` and `_check_postgame_clear` use it instead of `datetime.now(timezone.utc)`. Cleared after each test run.

**Synthetic flow** (in dev or pre-preseason testing):
1. Stub a fake game in `gameday_service._schedule` with `kickoff_utc = real_now + 65 minutes`.
2. Set `_now_override = real_now`. Run `_check_pregame_window` once → mode flips to pregameday.
3. Advance `_now_override = real_now + 35 minutes` (T-30). Run again → mode flips to gameday, audio policy fires.
4. Advance `_now_override = real_now + 95 minutes` (T+30 of the fake game). Run `_check_postgame_clear` → mode clears.
5. Verify lights, TTS, and Sonos behave correctly at each step.

**Synthetic endpoint** for live exercising: `POST /api/gameday/test/pregame`. Body: `{"opponent": "Houston Texans", "stakes_tier": "big_stakes"}`. Triggers a real (non-mock-time) flip to pregameday for 30 seconds, fires the audio policy with the supplied stakes_tier, then auto-clears. Useful for "make the lights do the thing" without altering the real schedule.

**Pre-preseason validation** (during dev, before 2026-08-13):
- Unit test coverage on `pregame_audio_policy.compute_pregame_audio` (target: 25+ tests).
- Synthetic time injection test covering the T-60 → T-30 → T+30 lifecycle.
- One manual fire of `POST /api/gameday/test/pregame` from the Latitude — apartment lights flip to pregameday, TTS plays, Sonos hype starts. Visual + audible verification.
- Preseason 2026-08-13 is the first real-game validation. Note the postmortem digest entry should specifically note pre-game behavior (lighting palette feel + audio decision) for tuning.

### 10.7 Open questions / iteration

- **Early-season stakes computation** — week 1-3 has no ESPN playoff odds. Fallback to record-only is crude (1-0 vs 0-1 isn't meaningfully predictive). Acceptable for v1; revisit if real-game data shows the early-season tier mis-classifies often.
- **Playoff-odds refresh cadence** — Tuesday 06:00 may be too coarse if a game ends Monday night and the user has a Wednesday pre-game window. Consider per-game refresh on T-90 instead (out of scope for v1 ship).
- **Sonos hype playlist content** — user picks a Colts-themed playlist; mode_playlists row gets the favorite_title. Iteration knob for later.
- **TTS line authoring** — pools per stakes tier are placeholder values. Run through curator + user authoring before preseason.
- **Multi-game days** — Sunday with a 1pm and 4pm Colts game? Out of scope (Colts plays once a week).
- **Postseason** — playoff games shift the stakes math entirely. Out of scope for v1; revisit if Colts make the playoffs.

---

## 11. Field rendering subsystem (frontend 3D)

The `/gameday` 3D field went through four iteration cycles in a single session (2026-05-07). Initial Slice D shipped a pixel-art-style top-down field with an HTML scoreboard overlay; the photoreal broadcast rebuild followed when the user judged that result "very plain, boring, and other than the field, the entire screen is just black." This section captures the current architecture, the design decisions behind it, and the gotchas that survived.

### 11.1 Phase ledger

| Phase | Shipped | Outcome |
|---|---|---|
| **1a — Foundation** | HDRI sky + IBL, PBR `leafy_grass` plane, broadcast camera at `[0, 35, 70]`, sun + ambient lights | Black void around the field replaced by HDRI horizon. Field still bare. |
| **1b — Stadium model** | Awbmegames stadium GLB wired in, bowl-hide via mesh-name substring (`['stadium']`), camera repositioned to `[0, 110, 110]` (above bowl) — the bowl shell was occluding inside-bowl camera positions | Stadium chrome visible (floodlights, press boxes), but field tiny in frame. |
| **1.5 — Visual cleanup** | Hide list extended to `['stadium', 'cube']` killing soccer goals + bench prop cubes; PBR grass plane extended to 250×150 yd to blend out to HDRI horizon | Cohesive field with no model-vs-PBR seam. |
| **1.6 — HDRI ground** | PBR grass plane removed entirely; HDRI lower hemisphere re-projected as 3D ground via `GroundedSkybox`; out-of-bounds perimeter lines added (4 sidelines + end lines at 100×53). Camera dropped back to a sideline broadcast angle. | The HDRI's broadcast-style mowed-stripe grass is the visible ground everywhere. |
| **2 — Post-processing + light towers** | Added `postprocessing@6.35.4`. EffectComposer + Bloom + ACES tone mapping. 4 corner light towers (pole + emissive lamp head + PointLight). Canvas → `autoRender={false}` + `toneMapping={NoToneMapping}` so PostFX is the sole render driver. | Bloom-ready emissives in place; tone mapping moved into the post chain. |

### 11.2 HDRI ground projection (the key visual technique)

The HDRI is a real captured panorama of a stadium grass field at sunrise. Naively setting it as `scene.background` paints it as an infinitely-distant sky cube — visible at the horizon, but the camera looks at "nothing" beneath the field markings.

`three/examples/jsm/objects/GroundedSkybox.js` (renamed from `GroundProjectedSkybox.js` at three r161+) takes the equirect map and constructs a sphere with the lower hemisphere flattened into a flat disc. The HDRI's ground content (lower half of the equirect) projects onto the disc; the upper half stays as a regular sky dome. From inside the sphere the camera sees real 3D ground continuous with the painted markings on top.

Parameters in `SkyDome.svelte`:
- `HEIGHT = 50` — vertical distance from sphere equator to the flat disc. Setting `position.y = HEIGHT` lands the disc at world y=0 (matches our field).
- `RADIUS = 200` — sphere extent. Comfortably outside the 100×53 field and the model floodlights at ~104 yd.

**Critical gotcha:** `@threlte/extras` exports a `GroundProjectedSkybox` wrapper, and its `<Environment groundProjection={{...}}>` prop nests the wrapper automatically — but that wrapper uses a `/* @vite-ignore */` runtime dynamic import for the underlying class, which fails in the browser ("Failed to resolve module specifier"). We bypass it by importing `RGBELoader` and `GroundedSkybox` directly via static imports in `SkyDome.svelte`. Vite bundles those normally.

### 11.3 Post-processing pipeline

`PostFX.svelte` builds an `EffectComposer` with `RenderPass(scene, camera) → EffectPass(camera, BloomEffect, ToneMappingEffect)`. `composer.render(delta)` is called from `useTask`.

**Why autoRender=false on the parent Canvas:** Threlte's default render task and our `composer.render` would both target the canvas, double-rendering or fighting for the framebuffer. Disabling autoRender makes PostFX the sole driver.

**Why `toneMapping={NoToneMapping}` on the renderer:** ACES Filmic is applied as a `ToneMappingEffect` at the end of the post chain. If the renderer also applies tone mapping, it stacks twice and crushes highlights.

**Component ordering:** `<PostFX />` is placed last in `FieldScene.svelte`'s composition. Threlte's `useTask` queue runs in component-mount order; placing PostFX last means every other scene-state task (ball ease, etc.) updates the scene BEFORE the composer renders.

**Bloom config:** `luminanceThreshold: 0.8` so only bright pixels (emissive lamp heads, sun glints on grass, future TD-celebration light flashes) bloom. Kernel `LARGE` for soft falloff.

### 11.4 Stadium model integration

The Awbmegames CC-BY GLB (`static/3d/stadium.glb`) is a soccer/international stadium — its native long axis is Z (~123 units), our football long axis is X (100 yd). The integration in `FieldScene.svelte`:
```svelte
<StadiumModel rotation={[0, Math.PI / 2, 0]} scale={0.81} position={[0, -2.5, 0]} />
```
Rotation aligns long axes. Scale 0.81 makes the model's painted field span match our 100-yd X. Y-offset of -2.5 sits the model's painted field surface just under our perimeter outline.

**Mesh-name quirk:** Sketchfab's GLB exporter strips spaces from mesh names. Runtime names are `Football_Stadium_Color_0`, `Cube004_Color_0`, etc. — NOT "Football Stadium". The `hideMeshes` substring filter in `StadiumModel.svelte` accounts for this. Default catches `Football_Stadium*` (the bowl shell + secondary stadium piece) and `Cube*` (soccer goals + 2 bench-prop boxes). The `Object001-006` meshes — likely floodlights / press-box towers — stay visible as ambient stadium chrome.

**onLoad event signature:** `<GLTF on:load={...}>` uses Threlte's `createRawEventDispatcher`, which passes the gltf object directly to the handler — NOT wrapped in `CustomEvent.detail`. Use `function onLoad(gltf) { gltf.scene.traverse(...) }`, not `event.detail.scene`.

### 11.5 Roadmap (deferred)

Aesthetic tuning and rendering enhancements tracked in [#10](https://github.com/agatte/home-hub/issues/10).

- **Phase 2.5:** GodRaysEffect from one anchor light tower; weather-reactive HDRI swap (clear / overcast / rain / snow); procedural drifting clouds (`@takram/three-clouds` or sprite-based); sun-arc time-of-day shadow direction; conditional `kickoff_utc` gating so light towers only fire on evening/night games.
- **Phase 3:** `yomotsu/camera-controls` for cinematic dynamics — slow orbit during pregame and between plays, snap-to-broadcast on `gameday_play` arrival, dolly-in to scoring endzone on `gameday_celebration` (sequence_key keyed on `play.scoring_team`). Reduced-motion fallback skips dynamics.
- **Phase 4:** painted yard numbers (5/10/15/.../50/.../15/10/5) via `<Text>` from `@threlte/extras`; hash marks; midfield Colts logo as a texture decal; confetti/firework instanced particles for celebrations (color-tinted, gravity-driven, wired to `lastCelebration.sequence_key`); drive-direction arrow on `state.possession` change; HTML down/distance HUD overlay extension on `+page.svelte`.

### 11.6 Dependencies + version pins

- `@threlte/core@^7.3.0`, `@threlte/extras@^8.11.0`, `three@^0.163.0` — installed from prior phases.
- `postprocessing@^6.35.4` — pinned to this minor because the latest (`6.39.x`) requires `three >= 0.168.0`. Upgrading three is a separate scope decision.
