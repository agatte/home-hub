# Game Day — Feature Spec (Phase A)

> **Phase A complete: 2026-05-06.** Spec, interface contracts, and mockup placeholder. Phase B (parallel implementation across 4 worktree-isolated agents) is the next gate. See `docs/AGENT_STRATEGY.md` Part 3 for the multi-agent playbook.

Game Day is a season-bounded mode that turns the apartment into a Colts viewing room. ESPN drives the play feed; the dashboard celebrates scoring plays with custom light + TTS choreography; a 3D pixel-art football field on the SvelteKit page mirrors live game state. Roadmap window: **July–August 2026** (preseason starts 2026-08-15).

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
- **Lights**: 5–8 second custom sequence. Specifics TBD by user during Phase B authoring; placeholder pattern: blue/white pulse rotation across L1→L2→L3→L4 (350ms each), then 3s sustained sparkle-style multi-pulse on all 4 lights, then fade to gameday baseline. Free choice per event (Decision 1.3b) — final values land in `CelebrationOrchestrator.SEQUENCES["touchdown"]`.
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

### 4.6 `Threlte FootballField.svelte` (frontend)

**File**: `frontend-svelte/src/lib/components/FootballField.svelte` (new)

Pure Threlte component, prop-driven (no store imports — keeps it reusable).

```typescript
export let game: GameDayState;
export let lastPlay: PlayEvent | null;
export let theme: { primary: string; secondary: string } = { primary: "#002C5F", secondary: "#FFFFFF" };
```

Renders:
- Pixel-art football field (50×100 yard sprite-on-plane or low-poly mesh)
- Team logos at endzones (Colts horseshoe + opponent logo from ESPN team data)
- Ball marker positioned per `game.possession` + ESPN's `yardLine` field
- Floating scoreboard above the field with score, quarter, clock
- Optional: animated ball trajectory on each new `lastPlay`

---

## 5. Implementation slices (Phase B)

Per `docs/AGENT_STRATEGY.md` Part 3 — 4 worktree-isolated agents, staggered. Phase A spec defines interfaces with no cross-slice file overlap.

| Slice | Worktree | Owns | Files |
|---|---|---|---|
| **A** | `feature/gameday-service` | ESPN poller + game-state model + `/api/gameday/*` | `backend/services/gameday_service.py`, `backend/api/routes/gameday.py`, `tests/test_gameday_service.py` |
| **B** | `feature/celebration-orchestrator` | Light + TTS choreography subscribed to play events | `backend/services/celebration_orchestrator.py`, `tests/test_celebration_orchestrator.py` |
| **C** | `feature/gameday-frontend` | SvelteKit page + store + WS subscription | `frontend-svelte/src/routes/gameday/+page.svelte`, `frontend-svelte/src/lib/stores/gameday.js` |
| **D** | `feature/threlte-football-field` | Pure Threlte 3D component | `frontend-svelte/src/lib/components/FootballField.svelte` and supporting helpers |

**Shared touchpoints owned by main session, NOT by any slice agent**:
- `backend/main.py` lifespan — wire up GameDayService + register CelebrationOrchestrator's callbacks. Main session does the integration after slices land.
- `backend/services/automation_engine.py` — add `gameday` to mode priority list (=6) and to the per-mode state tables in `light_state_calculator.py`. Main session does this BEFORE Phase B starts so slice agents don't race on it.
- `frontend-svelte/src/routes/+layout.svelte` — add gameday entry to FloatingNav. Main session does this in Phase C integration.
- `alexa_skill/lambda_function.py` + interaction model — add `gameday` to `HOMEHUB_MODE` slot. Main session does this in Phase C.

**Stagger plan**:
- Spawn slice A first; once `register_on_play_event` interface is concrete (~24h in), spawn slice B.
- Spawn slices C and D in parallel against the SvelteKit/Threlte boundary defined in §4.5–4.6.
- Each slice opens a PR; main session reviews and cherry-picks. Run `/api-audit` after merges; `/deploy-home` when frontend + backend are both in.

---

## 6. Refactor seam pass (pre-Phase-B)

Before spawning slice agents, main session refactors these to make seams clean. Tracks under `chore(gameday-prep): ...` commits.

1. **Mode priority list** in `automation_engine.py` — extract to a module constant or enum so adding `gameday` is mechanical.
2. **Mode-change callback registration order** — confirm GameDayService's pre-game callback fires before MusicMapper's mode-aware playlist auto-play, so the right music starts on flip.
3. **Light state tables** in `light_state_calculator.py` — add a `gameday` row in `ACTIVITY_LIGHT_STATES` with `day` / `evening` / `night` / `late_night` periods. Initial values placeholder; CelebrationOrchestrator's sequences override during plays.

---

## 7. Open questions / Phase B refinements

These don't block Phase A approval but need answers during slice authoring:

- **ESPN play description parser quality**: confirm during slice A that `play.description` reliably contains `<player_name>` for TD runs and `<kicker_name>` + `<yards>` for FG. If parsing is flaky, fall back to generic TTS lines (no `{player}` substitution). Sample a 2025 Colts game's API response in slice A's first PR to verify.
- **Light sequence values**: §2.2 placeholders are starting points. User authors actual `LightStep` arrays during slice B in tight iteration with the lighting curator agent (review each diff against `feedback_lighting_design_principles.md`).
- **Pre-game / commercial behavior in v2**: deferred. Note for v2 spec: pre-game ambient mode (continuous Colts-tinted lighting) and commercial-break behavior (lights restore to mode default + Sonos resume).
- **Preseason 2026-08-15 first test**: target Indianapolis Colts preseason game 1 as the first live integration test. Confirm date once 2026 schedule publishes (typically May/June).

---

## 8. Verification

Phase A is verified by:
1. This document reads end-to-end with all 7 sub-decisions explicitly recorded (§1).
2. Interface contracts (§4) name services, methods, file paths, and JSON shapes concretely — slice agents can begin without ambiguity.
3. `frontend-svelte/src/routes/gameday/+page.svelte` mockup renders in dev with hardcoded data.
4. `docs/PROJECT_SPEC.md` Roadmap section reflects "Phase A complete, Phase B queued."

No tests, no deploy. Phase B owns those.
