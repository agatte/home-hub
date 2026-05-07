"""
Celebration orchestrator — Game Day light + TTS choreography.

Subscribes to GameDayService.register_on_play_event /
register_on_state_transition. On scoring plays (TD, FG, kickoff) and on
end-of-game state transitions, runs a hand-tuned light sequence in
parallel with a randomized TTS line, broadcasting a `gameday_celebration`
WebSocket frame so the SvelteKit frontend can flair.

Spec: docs/GAMEDAY_SPEC.md §2.2, §3.2, §4.2, §4.4.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.services.gameday_service import (
    GameDayState,
    GameDayStateTransition,
    PlayEvent,
)

logger = logging.getLogger("home_hub.celebration")


# ---------------------------------------------------------------------------
# Dataclasses (spec §4.2)
# ---------------------------------------------------------------------------

@dataclass
class LightStep:
    """A single timed light command. `delay_ms` is measured from the
    sequence start, not from the previous step — sequences sleep
    cumulatively in `_run_sequence`."""
    light_id: str
    delay_ms: int
    state: dict


@dataclass
class CelebrationSequence:
    """Hand-tuned light + TTS choreography for one event type."""
    light_steps: list[LightStep]
    tts_lines: list[str]
    duration_seconds: float
    tts_voice: str = "en-US-GuyNeural"
    duck_volume: int = 10


# ---------------------------------------------------------------------------
# Sequence library
#
# Placeholder values — main session iterates with lighting-curator subagent.
# Spec §2.2 sketch:
#   touchdown      = blue/white pulse rotation L1→L2→L3→L4 (350ms each) +
#                    3s sustained multi-pulse, fade to baseline.
#   field_goal     = single blue/white pulse + brief flash (2-3s).
#   kickoff        = one-shot warm Colts-tinted baseline activation.
#   end_of_game_*  = win = 5-8s celebration; loss = silent gentle fade.
#
# Hard rules from feedback_lighting_design_principles.md:
#   • Kitchen pair (L3 + L4) MUST match in functional modes — gameday is
#     functional. Every step here that touches L3 also touches L4 with the
#     same {bri, hue, sat, ct, on}; the reverse holds. The light_steps
#     emit the L3 frame followed immediately by the same-state L4 frame
#     so the bridge writes both before the next pulse rotates.
#   • Gameday uses HSB (saturated Colts blue / white pulses), not CT.
# ---------------------------------------------------------------------------

# Colts blue (Hue HSB ~46920) and white (sat 0). Saturation calibrated by
# the lighting curator: 215 instead of 254 for the pulse helper, matching
# the gaming-retune precedent (sat=240 → 180-200) so the room's cream/wood
# textile palette doesn't read as a saturated cave when all 4 lights pulse
# at peak together. Single-light sustained accents (the L1 baseline) can
# absorb a stronger saturation, but the celebration pulse is the primary
# anti-pattern surface.
_COLTS_BLUE_HUE = 46920
_COLTS_BLUE_SAT = 215
_WHITE_SAT = 0

# Gameday baseline that sequences fade back to: Colts blue accent on L1,
# warm-amber fill on L2, and matched warm-amber on L3 + L4 (kitchen pair).
# _BASELINE_KITCHEN is aliased to _BASELINE_FILL so future tuning of the
# warm-amber post-celebration recovery state can't accidentally desync the
# kitchen pair (curator finding 3).
_BASELINE_L1 = {"on": True, "bri": 200, "hue": _COLTS_BLUE_HUE, "sat": _COLTS_BLUE_SAT}
_BASELINE_FILL = {"on": True, "bri": 180, "hue": 8000, "sat": 180}  # warm amber
_BASELINE_KITCHEN = dict(_BASELINE_FILL)  # kitchen pair alias — see curator note above


def _pulse(light_id: str, delay_ms: int, *, blue: bool = True, bri: int = 254,
           transition: int = 1) -> LightStep:
    """Helper: one frame of a Colts-blue or white pulse."""
    return LightStep(
        light_id=light_id,
        delay_ms=delay_ms,
        state={
            "on": True,
            "bri": bri,
            "hue": _COLTS_BLUE_HUE,
            "sat": _COLTS_BLUE_SAT if blue else _WHITE_SAT,
            "transitiontime": transition,
        },
    )


def _baseline_step(light_id: str, delay_ms: int, base: dict,
                   transition: int = 10) -> LightStep:
    state = dict(base)
    state["transitiontime"] = transition
    return LightStep(light_id=light_id, delay_ms=delay_ms, state=state)


# ----- Touchdown: ~6s. Rotation L1→L2→L3+L4 (kitchen pair fires together)
#       at 350ms each, then 3s sustained alternating blue/white, fade home.
_TD_STEPS: list[LightStep] = [
    # Rotation phase: 350ms beats. L3 + L4 fire on the same beat (kitchen pair).
    _pulse("1", 0, blue=True),
    _pulse("2", 350, blue=False),
    _pulse("3", 700, blue=True),
    _pulse("4", 700, blue=True),  # kitchen pair beat
    # Sustained multi-pulse: alternate blue ↔ white across all 4 every 400ms
    # for 2.4s.
    _pulse("1", 1200, blue=False),
    _pulse("2", 1200, blue=True),
    _pulse("3", 1200, blue=False),
    _pulse("4", 1200, blue=False),  # kitchen pair
    _pulse("1", 1600, blue=True),
    _pulse("2", 1600, blue=False),
    _pulse("3", 1600, blue=True),
    _pulse("4", 1600, blue=True),
    _pulse("1", 2000, blue=False),
    _pulse("2", 2000, blue=True),
    _pulse("3", 2000, blue=False),
    _pulse("4", 2000, blue=False),
    _pulse("1", 2400, blue=True),
    _pulse("2", 2400, blue=False),
    _pulse("3", 2400, blue=True),
    _pulse("4", 2400, blue=True),
    _pulse("1", 2800, blue=False),
    _pulse("2", 2800, blue=True),
    _pulse("3", 2800, blue=False),
    _pulse("4", 2800, blue=False),
    # Fade home to gameday baseline. transitiontime=20 (=2.0s).
    _baseline_step("1", 3500, _BASELINE_L1, transition=20),
    _baseline_step("2", 3500, _BASELINE_FILL, transition=20),
    _baseline_step("3", 3500, _BASELINE_KITCHEN, transition=20),
    _baseline_step("4", 3500, _BASELINE_KITCHEN, transition=20),
]

# ----- Field goal: ~2.5s. Single blue pulse → white flash → fade home.
_FG_STEPS: list[LightStep] = [
    _pulse("1", 0, blue=True),
    _pulse("2", 0, blue=True),
    _pulse("3", 0, blue=True),
    _pulse("4", 0, blue=True),
    _pulse("1", 500, blue=False),
    _pulse("2", 500, blue=False),
    _pulse("3", 500, blue=False),
    _pulse("4", 500, blue=False),
    _baseline_step("1", 1500, _BASELINE_L1, transition=10),
    _baseline_step("2", 1500, _BASELINE_FILL, transition=10),
    _baseline_step("3", 1500, _BASELINE_KITCHEN, transition=10),
    _baseline_step("4", 1500, _BASELINE_KITCHEN, transition=10),
]

# ----- Kickoff: one-shot baseline activation (~1s).
_KICKOFF_STEPS: list[LightStep] = [
    _baseline_step("1", 0, _BASELINE_L1, transition=10),
    _baseline_step("2", 0, _BASELINE_FILL, transition=10),
    _baseline_step("3", 0, _BASELINE_KITCHEN, transition=10),
    _baseline_step("4", 0, _BASELINE_KITCHEN, transition=10),
]

# ----- End of game (win): 6s — sustained blue/white celebration → baseline.
_EOG_WIN_STEPS: list[LightStep] = [
    _pulse("1", 0, blue=True, bri=254),
    _pulse("2", 0, blue=False, bri=254),
    _pulse("3", 0, blue=True, bri=254),
    _pulse("4", 0, blue=True, bri=254),
    _pulse("1", 600, blue=False, bri=254),
    _pulse("2", 600, blue=True, bri=254),
    _pulse("3", 600, blue=False, bri=254),
    _pulse("4", 600, blue=False, bri=254),
    _pulse("1", 1200, blue=True, bri=254),
    _pulse("2", 1200, blue=False, bri=254),
    _pulse("3", 1200, blue=True, bri=254),
    _pulse("4", 1200, blue=True, bri=254),
    _pulse("1", 1800, blue=False, bri=254),
    _pulse("2", 1800, blue=True, bri=254),
    _pulse("3", 1800, blue=False, bri=254),
    _pulse("4", 1800, blue=False, bri=254),
    _pulse("1", 2400, blue=True, bri=254),
    _pulse("2", 2400, blue=False, bri=254),
    _pulse("3", 2400, blue=True, bri=254),
    _pulse("4", 2400, blue=True, bri=254),
    _baseline_step("1", 4000, _BASELINE_L1, transition=30),
    _baseline_step("2", 4000, _BASELINE_FILL, transition=30),
    _baseline_step("3", 4000, _BASELINE_KITCHEN, transition=30),
    _baseline_step("4", 4000, _BASELINE_KITCHEN, transition=30),
]

# ----- End of game (loss): silent ~6s gentle fade from current state to a
#       muted, lower-saturation Colts-blue → eventually let auto mode
#       reapply via the post-game clear. tts_lines = [] (spec §2.2: silent).
_EOG_LOSS_STEPS: list[LightStep] = [
    LightStep(light_id="1", delay_ms=0,
              state={"on": True, "bri": 100, "hue": _COLTS_BLUE_HUE,
                     "sat": 180, "transitiontime": 30}),
    LightStep(light_id="2", delay_ms=0,
              state={"on": True, "bri": 80, "hue": 8000,
                     "sat": 120, "transitiontime": 30}),
    LightStep(light_id="3", delay_ms=0,
              state={"on": True, "bri": 80, "hue": 8000,
                     "sat": 120, "transitiontime": 30}),
    LightStep(light_id="4", delay_ms=0,
              state={"on": True, "bri": 80, "hue": 8000,
                     "sat": 120, "transitiontime": 30}),
]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class CelebrationOrchestrator:
    """Owns light + TTS sequencing for gameday events.

    Wiring (done by main session in bootstrap):
        orch = CelebrationOrchestrator(hue, tts, ws, gameday)
        gameday.register_on_play_event(orch.on_play_event)
        gameday.register_on_state_transition(orch.on_state_transition)
    """

    SEQUENCES: dict[str, CelebrationSequence] = {
        "touchdown": CelebrationSequence(
            light_steps=_TD_STEPS,
            tts_lines=[
                "Touchdown Colts! {player} in for six!",
                "{player}! He goes the distance for the Colts!",
                "And it's a Colts touchdown! {player} finds the end zone!",
                "Six points! {player} punches it in!",
                "Touchdown Indianapolis! Way to go, {player}!",
            ],
            duration_seconds=6.0,
        ),
        "field_goal": CelebrationSequence(
            light_steps=_FG_STEPS,
            tts_lines=[
                "Field goal is good! {kicker} from {yards}!",
                "{kicker} drills it from {yards} yards out!",
                "Three points Colts — {kicker} from {yards}!",
                "Good! {kicker} nails the {yards}-yarder!",
                "Colts on the board — {kicker} from {yards}.",
            ],
            duration_seconds=2.5,
        ),
        "kickoff": CelebrationSequence(
            light_steps=_KICKOFF_STEPS,
            tts_lines=[
                "Colts vs {opponent} — kickoff!",
                "We're underway! Colts taking on the {opponent}.",
                "Here we go, Colts! Kickoff against the {opponent}.",
                "Game on. Colts and {opponent}.",
            ],
            duration_seconds=1.5,
        ),
        "end_of_game_win": CelebrationSequence(
            light_steps=_EOG_WIN_STEPS,
            tts_lines=[
                "Colts win! Final score, {colts_score} to {opp_score}!",
                "That's a Colts victory — {colts_score} to {opp_score}!",
                "Colts take it, {colts_score} to {opp_score}! Way to go boys!",
                "Final: Colts {colts_score}, {opponent} {opp_score}. Indy on top!",
            ],
            duration_seconds=6.0,
        ),
        "end_of_game_loss": CelebrationSequence(
            light_steps=_EOG_LOSS_STEPS,
            tts_lines=[],  # silent on a loss (spec §2.2)
            duration_seconds=6.0,
        ),
    }

    COOLDOWN_SECONDS: float = 8.0

    def __init__(
        self,
        hue_service: Any,
        tts_service: Any,
        ws_manager: Any,
        gameday_service: Any,
    ) -> None:
        self._hue = hue_service
        self._tts = tts_service
        self._ws = ws_manager
        self._gameday = gameday_service
        self._last_celebration_at: float = 0.0

    # ------------------------------------------------------------------ Subscribers

    async def on_play_event(self, evt: PlayEvent) -> None:
        """Subscriber for GameDayService play events."""
        if evt.play_type == "touchdown":
            key = "touchdown"
        elif evt.play_type == "field_goal":
            key = "field_goal"
        elif evt.play_type == "kickoff":
            key = "kickoff"
        else:
            # `other` — not a celebratable event.
            return

        context = self._build_context(evt)
        await self._run_sequence(key, context)

    async def on_state_transition(self, transition: GameDayStateTransition) -> None:
        """Subscriber for GameDayService state transitions. We only celebrate
        the *→final transition; everything else is informational."""
        if transition.to_status != "final":
            return

        state = self._safe_current_state()
        score_colts = state.score_colts if state else 0
        score_opp = state.score_opp if state else 0
        opponent = state.opponent if state else None

        won = score_colts > score_opp
        key = "end_of_game_win" if won else "end_of_game_loss"
        context = {
            "colts_score": score_colts,
            "opp_score": score_opp,
            "opponent": opponent or "the opponent",
            "player": "",
            "kicker": "",
            "yards": "",
        }
        await self._run_sequence(key, context)

    # ------------------------------------------------------------------ Core

    async def _run_sequence(self, key: str, context: dict) -> None:
        """Broadcast WS flair, then run light steps + TTS in parallel.

        Cooldown stamp lands at sequence START so back-to-back plays inside
        the 8s window all skip — only the first wins.
        """
        sequence = self.SEQUENCES.get(key)
        if sequence is None:
            logger.warning("celebration: unknown sequence key=%s", key)
            return

        now = time.time()
        elapsed = now - self._last_celebration_at
        if elapsed < self.COOLDOWN_SECONDS:
            logger.info(
                "celebration: skipping %s — cooldown (%.1fs since last)",
                key, elapsed,
            )
            return

        # Stamp at start so simultaneous calls all see the same window.
        self._last_celebration_at = now

        logger.info("celebration: firing %s sequence", key)

        # 1. WS broadcast first so the frontend can flair before the bridge
        #    write storm starts. Failure is non-fatal.
        try:
            await self._ws.broadcast(
                "gameday_celebration",
                {"sequence_key": key, "started_at": now},
            )
        except Exception:
            logger.exception("celebration: ws broadcast failed for %s", key)

        # 2. Run lights + TTS in parallel. asyncio.gather catches per-task
        #    exceptions so a bridge hiccup doesn't kill the TTS line.
        await asyncio.gather(
            self._run_light_steps(sequence.light_steps),
            self._run_tts(sequence, context),
            return_exceptions=True,
        )

    async def _run_light_steps(self, steps: list[LightStep]) -> None:
        """Walk an ordered list of LightSteps, sleeping cumulatively from
        the sequence start. Each step's `delay_ms` is anchored to t=0."""
        if not steps:
            return
        # Sort defensively; authored sequences should already be in order
        # but this protects against future hand-edits.
        steps_sorted = sorted(steps, key=lambda s: s.delay_ms)
        start = time.time()
        for step in steps_sorted:
            target = start + (step.delay_ms / 1000.0)
            wait = target - time.time()
            if wait > 0:
                try:
                    await asyncio.sleep(wait)
                except asyncio.CancelledError:
                    raise
            try:
                await self._hue.set_light(step.light_id, step.state)
            except Exception:
                logger.exception(
                    "celebration: set_light failed light=%s step_delay=%dms",
                    step.light_id, step.delay_ms,
                )

    async def _run_tts(
        self, sequence: CelebrationSequence, context: dict,
    ) -> None:
        """Pick a random line from the sequence pool, substitute context
        variables, hand off to TTSService.speak (duck-and-resume on Sonos).
        Empty pool (loss) → silent."""
        if not sequence.tts_lines:
            return

        template = random.choice(sequence.tts_lines)
        try:
            text = template.format_map(_SafeFormatDict(context))
        except Exception:
            # format_map should be safe via _SafeFormatDict, but if a future
            # template introduces a non-key placeholder, fall back to raw.
            logger.exception("celebration: tts template format failed")
            text = template

        try:
            await self._tts.speak(text, volume=sequence.duck_volume)
        except Exception:
            logger.exception("celebration: tts.speak failed")

    # ------------------------------------------------------------------ Helpers

    def _build_context(self, evt: PlayEvent) -> dict:
        """Build the substitution context dict for a PlayEvent's TTS line.

        Pulls live score + opponent from gameday_service.current_state()
        when available — synthetic test events may carry no opponent at
        all, and the {opponent}/{colts_score}/{opp_score} placeholders
        still need *something* to format against.
        """
        state = self._safe_current_state()
        opponent = state.opponent if state and state.opponent else "the opponent"
        score_colts = state.score_colts if state else 0
        score_opp = state.score_opp if state else 0

        return {
            "player": evt.player or "Colts",
            "kicker": evt.kicker or "the kicker",
            "yards": evt.yards if evt.yards is not None else "",
            "opponent": opponent,
            "colts_score": score_colts,
            "opp_score": score_opp,
        }

    def _safe_current_state(self) -> Optional[GameDayState]:
        try:
            return self._gameday.current_state()
        except Exception:
            logger.exception("celebration: current_state() raised")
            return None


class _SafeFormatDict(dict):
    """dict subclass that returns the placeholder name on a missing key
    instead of raising KeyError. Used so a TTS template like
    `"{player} touchdown!"` doesn't blow up when ESPN didn't supply a
    player name (we still substitute "Colts" via _build_context, but this
    is a defense in depth)."""

    def __missing__(self, key: str) -> str:
        return ""
