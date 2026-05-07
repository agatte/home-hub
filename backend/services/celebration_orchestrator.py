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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from backend.services.celebration_volume_policy import compute_celebration_volume
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
    """Hand-tuned light + TTS choreography for one event type.

    ``base_volume`` is the per-event starting volume the volume policy
    builds on top of. The d9c1fcd live test showed ``duck_volume=10``
    was inaudible from the couch — this is the floor that the policy
    then bumps up for big WPA swings or down for blowouts / late-night
    / no-one-home.
    """
    light_steps: list[LightStep]
    tts_lines: list[str]
    duration_seconds: float
    tts_voice: str = "en-US-GuyNeural"
    base_volume: int = 30


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

# Colts blue (hue 47000) and white (sat 0). Saturation calibrated by the
# lighting curator: 215 instead of 254 for the pulse helper, matching the
# gaming-retune precedent (sat=240 → 180-200) so the room's cream/wood
# textile palette doesn't read as a saturated cave when all 4 lights pulse
# at peak together. Single-light sustained accents (the L1 baseline) can
# absorb a stronger saturation, but the celebration pulse is the primary
# anti-pattern surface. Hue aligned with light_state_calculator gameday
# day variant (47000) so post-celebration fade-home matches the canonical
# baseline the automation engine reconciles toward.
_COLTS_BLUE_HUE = 47000
_COLTS_BLUE_SAT = 215
_WHITE_SAT = 0

# Gameday baseline that sequences fade back to. Aligned with the day variant
# of `ACTIVITY_LIGHT_STATES["gameday"]` in `light_state_calculator.py:282-285`
# so a celebration's fade-home lands at the same per-light state the
# automation engine reconciles to — eliminates the prior drift where post-
# celebration values differed from steady-state gameday lighting.
# Kitchen pair (L3 ≡ L4) preserved by both lights referencing
# `_BASELINE_KITCHEN` (bri/hue/sat all matched).
_BASELINE_L1 = {"on": True, "bri": 150, "hue": _COLTS_BLUE_HUE, "sat": 185}
_BASELINE_FILL = {"on": True, "bri": 200, "hue": 8000, "sat": 130}  # L2 warm amber
_BASELINE_KITCHEN = {"on": True, "bri": 140, "hue": 8000, "sat": 130}  # L3 + L4 kitchen pair


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

# ----- Kickoff: 3-beat wave across the apartment (~1.7s). L1 → L2 →
#       (L3+L4 kitchen pair beat) at 150ms each, then settle to gameday
#       baseline. Wave preserves the kitchen pair invariant by firing
#       L3 and L4 on the same beat — the visual reads as a wave from the
#       living room to the kitchen rather than four sequential beats.
_KICKOFF_STEPS: list[LightStep] = [
    # Wave: each pulse fades in over ~100ms (transition=1).
    _pulse("1", 0, blue=True),
    _pulse("2", 150, blue=True),
    _pulse("3", 300, blue=True),
    _pulse("4", 300, blue=True),  # kitchen pair beat
    # Settle to gameday baseline. transitiontime=10 (=1.0s).
    _baseline_step("1", 700, _BASELINE_L1, transition=10),
    _baseline_step("2", 700, _BASELINE_FILL, transition=10),
    _baseline_step("3", 700, _BASELINE_KITCHEN, transition=10),
    _baseline_step("4", 700, _BASELINE_KITCHEN, transition=10),
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
            base_volume=30,
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
            base_volume=28,
        ),
        "kickoff": CelebrationSequence(
            light_steps=_KICKOFF_STEPS,
            tts_lines=[
                "Colts vs {opponent} — kickoff!",
                "We're underway! Colts taking on the {opponent}.",
                "Here we go, Colts! Kickoff against the {opponent}.",
                "Game on. Colts and {opponent}.",
            ],
            duration_seconds=1.7,
            base_volume=22,
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
            base_volume=35,
        ),
        "end_of_game_loss": CelebrationSequence(
            light_steps=_EOG_LOSS_STEPS,
            tts_lines=[],  # silent on a loss (spec §2.2)
            duration_seconds=6.0,
            base_volume=0,  # tts_lines empty — base_volume unused
        ),
    }

    COOLDOWN_SECONDS: float = 8.0

    def __init__(
        self,
        hue_service: Any,
        tts_service: Any,
        ws_manager: Any,
        gameday_service: Any,
        automation_engine: Any = None,
        camera_service: Any = None,
        event_logger: Any = None,
    ) -> None:
        self._hue = hue_service
        self._tts = tts_service
        self._ws = ws_manager
        self._gameday = gameday_service
        # automation + camera are optional context for celebration_volume_policy:
        # • automation: current_mode (sleeping → suppress) + is_dnd_active()
        # • camera:    is_present_within_seconds(300) → -10 modifier
        # Either being None just means "no apartment context for the policy" —
        # falls back to base volume + WPA + game-state modifiers, no
        # suppression. This keeps the constructor backwards-compatible with
        # tests that haven't been updated.
        self._automation = automation_engine
        self._camera = camera_service
        # event_logger is optional for the same backwards-compat reason.
        # When wired, every successful set_light inside a sequence emits a
        # `light_adjustments` row tagged `trigger="celebration:<key>"` so
        # celebrations show up in get_state_history / nightly journal /
        # DB analytics. Bypass-fire-and-forget by contract: a logging
        # exception must never bubble into _run_light_steps.
        self._event_logger = event_logger
        self._last_celebration_at: float = 0.0

    def set_automation_engine(self, automation_engine: Any) -> None:
        """Late-bind the automation engine. Bootstrap may construct the
        orchestrator before automation is fully wired (or vice versa)."""
        self._automation = automation_engine

    def set_camera_service(self, camera_service: Any) -> None:
        """Late-bind the camera service. Camera is opt-in and may not be
        on app.state at orchestrator construction time."""
        self._camera = camera_service

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
        await self._run_sequence(key, context, play=evt)

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
            "opponent": opponent or "opponent",
            "player": "",
            "kicker": "",
            "yards": "",
        }
        # Synthetic PlayEvent so the volume policy can apply apartment-
        # context modifiers (sleeping/DND/late-night/camera). End-of-game
        # has no WPA — the policy will fall through to per-event base.
        synthetic = PlayEvent(
            timestamp=datetime.now(timezone.utc),
            play_type="other",  # not used by policy
            description=f"end_of_game:{key}",
            player=None,
            kicker=None,
            yards=None,
            scoring_team="colts" if won else "opp",
            wpa=None,
        )
        await self._run_sequence(key, context, play=synthetic)

    # ------------------------------------------------------------------ Core

    async def _run_sequence(
        self,
        key: str,
        context: dict,
        *,
        play: Optional[PlayEvent] = None,
    ) -> None:
        """Broadcast WS flair, then run light steps + TTS in parallel.

        Cooldown stamp lands at sequence START so back-to-back plays inside
        the 8s window all skip — only the first wins.

        ``play`` feeds celebration_volume_policy: WPA for play events,
        synthetic placeholder for end-of-game transitions, None for any
        future caller that doesn't have one.
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

        # Volume policy runs before TTS dispatch so we can log a clean
        # "suppressed: <reason>" line and skip the speak() call if it
        # returns None. Lights still fire either way.
        target_volume = self._compute_target_volume(sequence, play)

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
            self._run_light_steps(sequence.light_steps, key),
            self._run_tts(sequence, context, target_volume, key),
            return_exceptions=True,
        )

    async def _run_light_steps(
        self, steps: list[LightStep], sequence_key: str,
    ) -> None:
        """Walk an ordered list of LightSteps, sleeping cumulatively from
        the sequence start. Each step's `delay_ms` is anchored to t=0.

        Each successful set_light is mirrored into the EventLogger with
        `trigger=f"celebration:{sequence_key}"` so the write shows up in
        `light_adjustments` (queryable via `WHERE trigger LIKE 'celebration:%'`).
        Without this, every gameday celebration is invisible to
        get_state_history, the nightly journal, and DB analytics — the
        bridge writes go through hue.set_light directly, which doesn't
        sit behind EventLogger middleware.
        """
        if not steps:
            return
        # Sort defensively; authored sequences should already be in order
        # but this protects against future hand-edits.
        steps_sorted = sorted(steps, key=lambda s: s.delay_ms)
        start = time.time()
        # Snapshot of the bridge's polled state, used as the before-vector
        # for log_light_adjustment. Falls back to {} if the hue service has
        # no _last_states attribute (e.g. a future stub or a test mock).
        last_states = getattr(self._hue, "_last_states", None)
        for step in steps_sorted:
            target = start + (step.delay_ms / 1000.0)
            wait = target - time.time()
            if wait > 0:
                try:
                    await asyncio.sleep(wait)
                except asyncio.CancelledError:
                    raise

            # Snapshot prev BEFORE the write so log_light_adjustment gets
            # accurate before/after pairs. We re-read on each step rather
            # than caching across the loop because earlier steps may have
            # already moved the bulb (sequences pulse the same light
            # multiple times).
            prev: dict = {}
            if isinstance(last_states, dict):
                prev = last_states.get(step.light_id) or {}

            try:
                await self._hue.set_light(step.light_id, step.state)
            except Exception:
                logger.exception(
                    "celebration: set_light failed light=%s step_delay=%dms",
                    step.light_id, step.delay_ms,
                )
                # Skip the log call on failure — there's no confirmed
                # bridge write to mirror.
                continue

            # Emit the EventLogger row. Wrapped defensively even though
            # log_light_adjustment is fire-and-forget by contract; a
            # future bug must not break the celebration loop.
            if self._event_logger is not None:
                try:
                    mode_at_time = getattr(self._automation, "current_mode", None)
                    new = step.state
                    await self._event_logger.log_light_adjustment(
                        light_id=step.light_id,
                        light_name=prev.get("name"),
                        bri_before=prev.get("bri"), bri_after=new.get("bri"),
                        hue_before=prev.get("hue"), hue_after=new.get("hue"),
                        sat_before=prev.get("sat"), sat_after=new.get("sat"),
                        ct_before=prev.get("ct"), ct_after=new.get("ct"),
                        mode_at_time=mode_at_time,
                        trigger=f"celebration:{sequence_key}",
                    )
                except Exception:
                    logger.exception(
                        "celebration: event_logger.log_light_adjustment "
                        "failed light=%s sequence=%s",
                        step.light_id, sequence_key,
                    )

    async def _run_tts(
        self,
        sequence: CelebrationSequence,
        context: dict,
        target_volume: Optional[int],
        sequence_key: str,
    ) -> None:
        """Pick a random line from the sequence pool, substitute context
        variables, hand off to TTSService.speak (duck-and-resume on Sonos).

        Skipped when:
            • Pool is empty (loss is silent by spec).
            • ``target_volume`` is None — volume policy hard-suppressed
              (sleeping, DND, or losing blowout).

        Kickoff special-cases via `kickoff_tts_picker.pick_kickoff_tts`
        which selects a line based on day-of-week (Sunday afternoon /
        SNF / MNF / TNF / Saturday primetime) and team form (Danny Dimes
        when Colts have been winning, Daniel Jones otherwise). Other
        sequences continue to pick from the flat `sequence.tts_lines`.
        """
        if not sequence.tts_lines:
            return
        if target_volume is None:
            return

        if sequence_key == "kickoff":
            template = await self._pick_kickoff_template()
        elif sequence_key == "field_goal":
            template = self._pick_field_goal_template(context)
        else:
            template = random.choice(sequence.tts_lines)
        try:
            text = template.format_map(_SafeFormatDict(context))
        except Exception:
            # format_map should be safe via _SafeFormatDict, but if a future
            # template introduces a non-key placeholder, fall back to raw.
            logger.exception("celebration: tts template format failed")
            text = template

        try:
            await self._tts.speak(text, volume=target_volume)
        except Exception:
            logger.exception("celebration: tts.speak failed")

    def _compute_target_volume(
        self, sequence: CelebrationSequence, play: Optional[PlayEvent],
    ) -> Optional[int]:
        """Gather apartment context, call the volume policy, log the
        decision. Returns the int volume (5-50) or None to suppress.

        Defensive against missing automation/camera deps — both are
        optional kwargs to the constructor for backwards-compat with
        existing tests, and the policy treats their absence as "no
        suppression, no apartment-context modifier"."""
        if play is None:
            # No PlayEvent context — return base volume directly. Used
            # by future callers that bypass the WPA path.
            return sequence.base_volume

        sleeping = False
        dnd = False
        if self._automation is not None:
            try:
                sleeping = (getattr(self._automation, "current_mode", None) == "sleeping")
            except Exception:
                logger.debug("celebration volume: current_mode read failed", exc_info=True)
            try:
                if hasattr(self._automation, "is_dnd_active"):
                    dnd = bool(self._automation.is_dnd_active())
            except Exception:
                logger.debug("celebration volume: is_dnd_active read failed", exc_info=True)

        camera_absent = False
        if self._camera is not None:
            try:
                if hasattr(self._camera, "is_present_within_seconds"):
                    camera_absent = not bool(self._camera.is_present_within_seconds(300))
            except Exception:
                logger.debug("celebration volume: camera presence read failed", exc_info=True)

        state = self._safe_current_state()
        target = compute_celebration_volume(
            play=play,
            game_state=state,
            base_volume=sequence.base_volume,
            sleeping_mode=sleeping,
            dnd_active=dnd,
            camera_absent=camera_absent,
            now=datetime.now(timezone.utc),
        )

        if target is None:
            reason = self._volume_suppression_reason(sleeping, dnd, state)
            logger.info("celebration TTS suppressed: %s", reason)
        else:
            logger.info(
                "celebration TTS volume=%d (base=%d wpa=%s sleeping=%s dnd=%s camera_absent=%s)",
                target, sequence.base_volume, play.wpa, sleeping, dnd, camera_absent,
            )
        return target

    @staticmethod
    def _volume_suppression_reason(
        sleeping: bool, dnd: bool, state: Optional[GameDayState],
    ) -> str:
        """Compose a human-readable reason string for the suppression
        log line so journalctl tells us why TTS was silent."""
        if sleeping:
            return "sleeping mode"
        if dnd:
            return "DND active"
        if state is not None:
            deficit = state.score_opp - state.score_colts
            if state.quarter >= 3 and deficit >= 21:
                return f"losing blowout (Q{state.quarter}, down {deficit})"
        return "unknown"

    def _pick_field_goal_template(self, context: dict) -> str:
        """Dispatch to `fg_tts_picker.pick_fg_tts` with the kick distance
        extracted from `context['yards']`. Standard pool for sub-50yd
        kicks, "big_kick" energy pool for 50+yd. Synchronous (no I/O)
        unlike the kickoff picker — FG doesn't read team form."""
        from backend.services.fg_tts_picker import pick_fg_tts

        # context['yards'] may be int, str (from format_map), or "".
        # Coerce defensively.
        raw_yards = context.get("yards")
        yards: Optional[int]
        try:
            yards = int(raw_yards) if raw_yards not in (None, "") else None
        except (TypeError, ValueError):
            yards = None
        return pick_fg_tts(yards=yards)

    async def _pick_kickoff_template(self) -> str:
        """Dispatch to `kickoff_tts_picker.pick_kickoff_tts` with context
        gathered from gameday_service + `app_settings['gameday_team_form']`.

        team_form storage shape (JSON in app_settings):
          {
            "last4_record": [wins, losses],
            "win_streak": int,
            "season_record": [wins, losses, ties]
          }
        Absent / malformed → picker falls back to the "jones" (measured)
        pool. The ESPN-driven refresh task that populates this row is a
        separate follow-up; users can manually seed via SQL for testing
        the dimes/jones swap.
        """
        # Local imports keep the kickoff-specific deps out of the cold-
        # load path for non-kickoff sequences.
        from backend.api.routes.routines import load_setting
        from backend.services.kickoff_tts_picker import (
            TeamForm,
            pick_kickoff_tts,
        )

        state = self._safe_current_state()
        kickoff_at = (
            state.kickoff_utc if state and state.kickoff_utc is not None
            else datetime.now(timezone.utc)
        )

        team_form: Optional[TeamForm] = None
        try:
            raw = await load_setting("gameday_team_form")
            if raw:
                last4 = raw.get("last4_record")
                streak = raw.get("win_streak")
                season = raw.get("season_record")
                if (isinstance(last4, list) and len(last4) == 2
                        and isinstance(streak, int)
                        and isinstance(season, list) and len(season) == 3):
                    team_form = TeamForm(
                        last4_record=(int(last4[0]), int(last4[1])),
                        win_streak=int(streak),
                        season_record=(
                            int(season[0]), int(season[1]), int(season[2]),
                        ),
                    )
        except Exception:
            # Best-effort — bad app_settings shape must never block a
            # kickoff TTS line. Falls through to team_form=None.
            logger.debug(
                "celebration: team_form load failed, defaulting to None",
                exc_info=True,
            )

        return pick_kickoff_tts(kickoff_at=kickoff_at, team_form=team_form)

    # ------------------------------------------------------------------ Helpers

    def _build_context(self, evt: PlayEvent) -> dict:
        """Build the substitution context dict for a PlayEvent's TTS line.

        Pulls live score + opponent from gameday_service.current_state()
        when available — synthetic test events may carry no opponent at
        all, and the {opponent}/{colts_score}/{opp_score} placeholders
        still need *something* to format against.
        """
        state = self._safe_current_state()
        # Bare "opponent" fallback (no leading article). Templates that say
        # "vs the {opponent}" / "the {opponent}" carry their own article;
        # combining the article with a "the opponent" fallback produced
        # "vs the the opponent" in synthetic test fires (verified live
        # 2026-05-07 — kickoff fire said "vs the the opponent"). Real-game
        # opponents land as bare team names (e.g. "Houston Texans") which
        # read fine in both article-prefixed and bare-{opponent} templates.
        opponent = state.opponent if state and state.opponent else "opponent"
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
