"""
Tests for CelebrationOrchestrator — light + TTS choreography for gameday.

Mocks HueService, TTSService, WebSocketManager, and GameDayService.
Validates per-event dispatch, cooldown, win/loss split, TTS template
substitution, and synthetic-test-event passthrough. Spec: docs/GAMEDAY_SPEC.md.

The autouse ``_freeze_to_afternoon`` fixture pins
``datetime.now(timezone.utc)`` inside the orchestrator module to a
mid-afternoon Indy local time, so the volume policy's late-night cap
(10pm-6am Indy local) doesn't fire and surprise volume assertions when
the test suite runs at night.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services import celebration_orchestrator as _orch_module
from backend.services.celebration_orchestrator import (
    CelebrationOrchestrator,
    CelebrationSequence,
    LightStep,
)
from backend.services.lighting_transition_boundary import LightingTransitionBoundary
from backend.services.gameday_viewer_sync import ViewerReleaseResult, ViewerSyncDecision
from backend.services.gameday_service import (
    GameDayState,
    GameDayStateTransition,
    PlayEvent,
)


@pytest.fixture(autouse=True)
def _freeze_to_afternoon(monkeypatch):
    """Pin the orchestrator's `datetime.now(timezone.utc)` to 18:00 UTC
    on a Tuesday — Indy local 14:00, comfortably outside the late-night
    cap window. Prevents test flakes when the suite runs after 10pm
    local time."""
    fixed_utc = datetime(2026, 9, 15, 18, 0, 0, tzinfo=timezone.utc)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return fixed_utc.replace(tzinfo=None)
            return fixed_utc.astimezone(tz)

    monkeypatch.setattr(_orch_module, "datetime", _FrozenDatetime)
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator(
    *,
    score_colts: int = 21,
    score_opp: int = 14,
    opponent: str = "Houston Texans",
    quarter: int = 2,
    clock: str = "5:32",
    automation_mode: str = "gameday",
    house_state: str | None = None,
    dnd_active: bool = False,
    camera_present: bool = True,
    with_apartment_context: bool = True,
    viewer_sync=None,
) -> tuple[CelebrationOrchestrator, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build an orchestrator with all-mock collaborators; return the tuple
    (orch, hue, tts, ws, gameday) so tests can assert on each.

    ``with_apartment_context=False`` reproduces the original 4-arg
    signature (no automation_engine, no camera_service) — used by the
    backwards-compat tests."""
    hue = MagicMock()
    hue.set_light = AsyncMock(return_value=True)

    tts = MagicMock()
    tts.speak = AsyncMock(return_value=True)

    ws = MagicMock()
    ws.broadcast = AsyncMock()

    gameday = MagicMock()
    gameday.current_state = MagicMock(
        return_value=GameDayState(
            status="in-progress",
            opponent=opponent,
            kickoff_utc=datetime.now(timezone.utc),
            score_colts=score_colts,
            score_opp=score_opp,
            quarter=quarter,
            clock=clock,
            possession="colts",
            last_play=None,
        )
    )

    if with_apartment_context:
        automation = MagicMock()
        automation.current_mode = automation_mode
        automation.house_state = house_state
        automation.is_dnd_active = MagicMock(return_value=dnd_active)
        automation.transient_light_write_block_reason = MagicMock(return_value=None)
        automation.supersede_screen_sync_lights = MagicMock()
        automation.reapply_current_mode = AsyncMock()

        camera = MagicMock()
        camera.is_present_within_seconds = MagicMock(return_value=camera_present)

        orch = CelebrationOrchestrator(
            hue_service=hue,
            tts_service=tts,
            ws_manager=ws,
            gameday_service=gameday,
            automation_engine=automation,
            camera_service=camera,
            viewer_sync=viewer_sync,
        )
    else:
        # Backwards-compat: original 4-arg signature.
        orch = CelebrationOrchestrator(
            hue_service=hue,
            tts_service=tts,
            ws_manager=ws,
            gameday_service=gameday,
            viewer_sync=viewer_sync,
        )
    return orch, hue, tts, ws, gameday


def _td_event(
    player: str = "Jonathan Taylor",
    wpa: float | None = None,
) -> PlayEvent:
    return PlayEvent(
        timestamp=datetime.now(timezone.utc),
        play_type="touchdown",
        description=f"{player} 5 Yd Rush (Spencer Shrader Kick)",
        player=player,
        kicker=None,
        yards=None,
        scoring_team="colts",
        wpa=wpa,
        synthetic=True,
    )


def test_touchdown_picker_receives_yardage(monkeypatch):
    orch, *_ = _make_orchestrator()
    captured = {}

    def fake_pick_td_tts(*, wpa=None, yards=None, rng=None):
        captured.update(wpa=wpa, yards=yards)
        return "Touchdown Colts! {player} in for six!"

    monkeypatch.setattr("backend.services.td_tts_picker.pick_td_tts", fake_pick_td_tts)
    line = orch._pick_touchdown_template({"wpa": "0.15", "yards": "3"})

    assert line == "Touchdown Colts! {player} in for six!"
    assert captured == {"wpa": 0.15, "yards": 3}


def _fg_event(
    kicker: str = "Spencer Shrader",
    yards: int = 42,
    wpa: float | None = None,
) -> PlayEvent:
    return PlayEvent(
        timestamp=datetime.now(timezone.utc),
        play_type="field_goal",
        description=f"{kicker} {yards} Yd Field Goal",
        player=None,
        kicker=kicker,
        yards=yards,
        scoring_team="colts",
        wpa=wpa,
        synthetic=True,
    )


def _kickoff_event() -> PlayEvent:
    return PlayEvent(
        timestamp=datetime.now(timezone.utc),
        play_type="kickoff",
        description="Kickoff",
        player=None,
        kicker=None,
        yards=None,
        scoring_team=None,
        synthetic=True,
    )


def _other_event() -> PlayEvent:
    return PlayEvent(
        timestamp=datetime.now(timezone.utc),
        play_type="other",
        description="3rd down conversion",
        player=None,
        kicker=None,
        yards=None,
        scoring_team="colts",
        synthetic=True,
    )


def _final_transition() -> GameDayStateTransition:
    return GameDayStateTransition(
        from_status="in-progress",
        to_status="final",
        timestamp=datetime.now(timezone.utc),
        synthetic=True,
    )


@pytest.mark.asyncio
async def test_provider_play_is_rejected_before_sequence_when_authority_is_gone():
    orch, hue, tts, ws, gameday = _make_orchestrator()
    gameday.celebration_eligibility = MagicMock(
        return_value=(False, "automation mode=watching")
    )
    evt = _td_event()
    evt.game_id = "game-1"
    evt.event_id = "play-1"
    evt.synthetic = False

    await orch.on_play_event(evt)

    gameday.celebration_eligibility.assert_called_once_with(
        game_id="game-1", allow_final=False,
    )
    hue.set_light.assert_not_awaited()
    tts.speak.assert_not_awaited()
    ws.broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_unscoped_non_synthetic_provider_event_fails_closed():
    orch, hue, tts, ws, _ = _make_orchestrator()
    evt = _td_event()
    evt.synthetic = False

    await orch.on_play_event(evt)

    hue.set_light.assert_not_awaited()
    tts.speak.assert_not_awaited()
    ws.broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_light_steps_abort_when_authority_changes():
    orch, hue, _, _, gameday = _make_orchestrator()
    gameday.celebration_eligibility = MagicMock(
        side_effect=[
            (True, "current Game Day authority"),
            (False, "automation mode=watching"),
        ]
    )
    evt = _td_event()
    evt.game_id = "game-1"
    evt.event_id = "play-1"
    evt.synthetic = False
    steps = [
        LightStep(light_id="1", delay_ms=0, state={"on": True}),
        LightStep(light_id="2", delay_ms=0, state={"on": True}),
    ]

    written = await orch._run_light_steps(
        steps, "touchdown", play=evt,
    )

    assert written == {"1"}
    hue.set_light.assert_awaited_once_with("1", {"on": True})
    assert gameday.celebration_eligibility.call_count == 2


@pytest.mark.asyncio
async def test_tts_rechecks_authority_immediately_before_speak():
    orch, _, tts, _, gameday = _make_orchestrator()
    gameday.celebration_eligibility = MagicMock(
        return_value=(False, "automation mode=watching")
    )
    evt = _td_event()
    evt.game_id = "game-1"
    evt.event_id = "play-1"
    evt.synthetic = False
    sequence = CelebrationSequence(
        light_steps=[],
        tts_lines=["Touchdown Colts!"],
        duration_seconds=1.0,
        base_volume=30,
    )

    await orch._run_tts(
        sequence, {}, 30, "touchdown", play=evt,
    )

    tts.speak.assert_not_awaited()
    gameday.celebration_eligibility.assert_called_once_with(
        game_id="game-1", allow_final=False,
    )


@pytest.mark.asyncio
async def test_real_final_transition_uses_transition_authority_even_with_context_play():
    orch, _, _, _, gameday = _make_orchestrator()
    gameday.celebration_eligibility = MagicMock(
        return_value=(False, "automation mode=watching")
    )
    context_play = PlayEvent(
        timestamp=datetime.now(timezone.utc),
        play_type="other",
        description="end_of_game",
        player=None, kicker=None, yards=None,
        scoring_team="colts",
    )
    transition = _final_transition()
    transition.game_id = "game-1"
    transition.synthetic = False

    allowed, reason = orch._authority_allows(
        play=context_play, transition=transition,
    )

    assert allowed is False
    assert reason == "automation mode=watching"
    gameday.celebration_eligibility.assert_called_once_with(
        game_id="game-1", allow_final=True,
    )


@pytest.mark.asyncio
async def test_real_final_transition_is_suppressed_after_manual_exit():
    orch, hue, tts, ws, gameday = _make_orchestrator(
        score_colts=24, score_opp=21,
    )
    gameday.celebration_eligibility = MagicMock(
        return_value=(False, "automation mode=watching")
    )
    transition = _final_transition()
    transition.game_id = "game-1"
    transition.synthetic = False

    await orch.on_state_transition(transition)

    hue.set_light.assert_not_awaited()
    tts.speak.assert_not_awaited()
    ws.broadcast.assert_not_awaited()
    gameday.celebration_eligibility.assert_called_once_with(
        game_id="game-1", allow_final=True,
    )



@pytest.mark.asyncio
async def test_transient_sequence_defers_then_reconciles_authoritative_mode(monkeypatch):
    orch, _, _, _, _ = _make_orchestrator()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocking_lights(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return {"1"}

    monkeypatch.setattr(orch, "_run_light_steps", blocking_lights)
    task = asyncio.create_task(orch._run_sequence("big_play", {}, play=None))
    await entered.wait()

    assert orch.is_active() is True
    release.set()
    await task

    assert orch.is_active() is False
    orch._automation.reapply_current_mode.assert_awaited_once_with(
        force_resend=True,
    )


@pytest.mark.asyncio
async def test_transient_sequence_preserves_newer_screen_sync_owner_on_reconcile():
    orch, _, _, _, _ = _make_orchestrator()
    await orch._run_sequence("big_play", {}, play=None)

    # Reconciliation must never clear ScreenSync ownership. A fresh frame can
    # acquire the lamp after the celebration releases the shared boundary but
    # before TTS finishes; central reapply will preserve that newer owner.
    orch._automation.supersede_screen_sync_lights.assert_not_called()
    orch._automation.reapply_current_mode.assert_awaited_once_with(
        force_resend=True,
    )



@pytest.mark.asyncio
async def test_transient_sequence_holds_shared_lighting_boundary(monkeypatch):
    orch, hue, _, _, _ = _make_orchestrator()
    boundary = LightingTransitionBoundary(hue)
    orch._transition_boundary = boundary
    entered = asyncio.Event()
    release = asyncio.Event()
    contender_entered = asyncio.Event()

    async def blocking_lights(*_args, **_kwargs):
        assert boundary.held_by_current_task is True
        entered.set()
        await release.wait()

    async def competing_writer():
        async with boundary.serialized():
            contender_entered.set()

    monkeypatch.setattr(orch, "_run_light_steps", blocking_lights)
    celebration = asyncio.create_task(
        orch._run_sequence("big_play", {}, play=None)
    )
    await entered.wait()
    contender = asyncio.create_task(competing_writer())
    await asyncio.sleep(0)
    assert contender_entered.is_set() is False

    release.set()
    await celebration
    await contender
    assert contender_entered.is_set() is True


# ---------------------------------------------------------------------------
# Touchdown
# ---------------------------------------------------------------------------

class TestTouchdown:

    async def test_td_fires_lights_tts_and_broadcast(self):
        orch, hue, tts, ws, _ = _make_orchestrator()
        await orch.on_play_event(_td_event(player="Jonathan Taylor"))

        # WS broadcast first.
        ws.broadcast.assert_awaited_once()
        msg_type, payload = ws.broadcast.await_args.args
        assert msg_type == "gameday_celebration"
        assert payload["sequence_key"] == "touchdown"
        assert "started_at" in payload

        # Lights: every TD step should have produced a set_light call.
        td_steps = CelebrationOrchestrator.SEQUENCES["touchdown"].light_steps
        assert hue.set_light.await_count == len(td_steps)

        # TTS: exactly one call, text substituted with the player name.
        tts.speak.assert_awaited_once()
        text = tts.speak.await_args.args[0]
        assert "Jonathan Taylor" in text
        # Volume comes from the volume policy. With base_volume=30, no WPA
        # (None → fallback path with mid-game state, no special bands fire),
        # camera present, no DND, no sleeping → unchanged base 30.
        assert tts.speak.await_args.kwargs.get("volume") == 30

    async def test_td_synthetic_test_event_fires(self):
        """The /api/gameday/test/touchdown route emits a synthetic PlayEvent
        whose description starts with `[TEST]`. The orchestrator must run
        it normally — this is the path Anthony uses to tune sequences."""
        orch, hue, tts, ws, _ = _make_orchestrator()
        synthetic = PlayEvent(
            timestamp=datetime.now(timezone.utc),
            play_type="touchdown",
            description="[TEST] Synthetic touchdown",
            player="Test Player",
            kicker=None,
            yards=None,
            scoring_team="colts",
            synthetic=True,
        )
        await orch.on_play_event(synthetic)

        # Sequence runs end-to-end.
        ws.broadcast.assert_awaited_once()
        assert hue.set_light.await_count > 0
        tts.speak.assert_awaited_once()
        assert "Test Player" in tts.speak.await_args.args[0]

    async def test_other_play_type_is_noop(self):
        orch, hue, tts, ws, _ = _make_orchestrator()
        await orch.on_play_event(_other_event())
        ws.broadcast.assert_not_awaited()
        hue.set_light.assert_not_awaited()
        tts.speak.assert_not_awaited()


# ---------------------------------------------------------------------------
# Field goal
# ---------------------------------------------------------------------------

class TestFieldGoal:

    async def test_fg_substitutes_kicker_and_yards(self):
        orch, hue, tts, ws, _ = _make_orchestrator()
        await orch.on_play_event(_fg_event(kicker="Spencer Shrader", yards=47))

        ws.broadcast.assert_awaited_once()
        assert ws.broadcast.await_args.args[1]["sequence_key"] == "field_goal"

        fg_steps = CelebrationOrchestrator.SEQUENCES["field_goal"].light_steps
        assert hue.set_light.await_count == len(fg_steps)

        tts.speak.assert_awaited_once()
        text = tts.speak.await_args.args[0]
        assert "Spencer Shrader" in text
        assert "47" in text


# ---------------------------------------------------------------------------
# Kickoff
# ---------------------------------------------------------------------------

class TestKickoff:

    async def test_kickoff_substitutes_opponent(self):
        orch, hue, tts, ws, _ = _make_orchestrator(opponent="Houston Texans")
        await orch.on_play_event(_kickoff_event())

        ws.broadcast.assert_awaited_once()
        assert ws.broadcast.await_args.args[1]["sequence_key"] == "kickoff"

        tts.speak.assert_awaited_once()
        assert "Houston Texans" in tts.speak.await_args.args[0]


# ---------------------------------------------------------------------------
# Slice C+ score subtypes (2026-05-15)
# ---------------------------------------------------------------------------

def _event_with_type(play_type: str, scoring_team: str | None = "colts") -> PlayEvent:
    return PlayEvent(
        timestamp=datetime.now(timezone.utc),
        play_type=play_type,  # type: ignore[arg-type]
        description=f"Synthetic {play_type}",
        player=None,
        kicker=None,
        yards=None,
        scoring_team=scoring_team,  # type: ignore[arg-type]
        synthetic=True,
    )


class TestSafety:

    async def test_safety_fires_lights_and_tts(self):
        orch, hue, tts, ws, _ = _make_orchestrator()
        await orch.on_play_event(_event_with_type("safety"))

        ws.broadcast.assert_awaited_once()
        assert ws.broadcast.await_args.args[1]["sequence_key"] == "safety"
        safety_steps = CelebrationOrchestrator.SEQUENCES["safety"].light_steps
        assert hue.set_light.await_count == len(safety_steps)
        tts.speak.assert_awaited_once()


class TestExtraPointGood:

    async def test_pat_fires_lights_no_tts(self):
        """Extra point is silent by design — fires after every offensive TD."""
        orch, hue, tts, ws, _ = _make_orchestrator()
        await orch.on_play_event(_event_with_type("extra_point_good"))

        ws.broadcast.assert_awaited_once()
        assert ws.broadcast.await_args.args[1]["sequence_key"] == "extra_point_good"
        pat_steps = CelebrationOrchestrator.SEQUENCES["extra_point_good"].light_steps
        assert hue.set_light.await_count == len(pat_steps)
        # No TTS — empty tts_lines list.
        tts.speak.assert_not_awaited()


class TestTwoPointConversion:

    async def test_2pt_fires_lights_and_tts(self):
        orch, hue, tts, ws, _ = _make_orchestrator()
        await orch.on_play_event(_event_with_type("two_point_conv"))

        ws.broadcast.assert_awaited_once()
        assert ws.broadcast.await_args.args[1]["sequence_key"] == "two_point_conv"
        tts.speak.assert_awaited_once()


class TestDefensiveTd:

    async def test_pick_six_fires_defensive_td_sequence(self):
        orch, hue, tts, ws, _ = _make_orchestrator()
        await orch.on_play_event(_event_with_type("defensive_td"))

        ws.broadcast.assert_awaited_once()
        assert ws.broadcast.await_args.args[1]["sequence_key"] == "defensive_td"
        def_td_steps = CelebrationOrchestrator.SEQUENCES["defensive_td"].light_steps
        assert hue.set_light.await_count == len(def_td_steps)
        tts.speak.assert_awaited_once()

    async def test_defensive_td_volume_above_offensive_td(self):
        """defensive_td has base_volume=32 vs touchdown's 30. Pick-six is
        the bigger emotional moment so it lands a touch louder."""
        def_seq = CelebrationOrchestrator.SEQUENCES["defensive_td"]
        td_seq = CelebrationOrchestrator.SEQUENCES["touchdown"]
        assert def_seq.base_volume > td_seq.base_volume


class TestOpponentSuppression:

    async def test_opponent_touchdown_does_not_fire(self):
        """Opponent scores must stay silent (spec §2.2)."""
        orch, hue, tts, ws, _ = _make_orchestrator()
        await orch.on_play_event(_event_with_type("touchdown", scoring_team="opp"))
        ws.broadcast.assert_not_awaited()
        hue.set_light.assert_not_awaited()
        tts.speak.assert_not_awaited()

    async def test_opponent_defensive_td_does_not_fire(self):
        orch, hue, tts, ws, _ = _make_orchestrator()
        await orch.on_play_event(_event_with_type("defensive_td", scoring_team="opp"))
        ws.broadcast.assert_not_awaited()
        hue.set_light.assert_not_awaited()


# ---------------------------------------------------------------------------
# Phase 2 — WPA momentum dispatch
# ---------------------------------------------------------------------------

class TestMomentumDispatch:

    async def test_momentum_fires_big_play_sequence_lights_only(self):
        """Phase 2: momentum PlayType dispatches the big_play SEQUENCE.
        Lights-only by design — no TTS even with apartment context healthy."""
        orch, hue, tts, ws, _ = _make_orchestrator()
        # Momentum events have scoring_team=None (it's a non-scoring play).
        evt = _event_with_type("momentum", scoring_team=None)
        evt = PlayEvent(
            timestamp=evt.timestamp,
            play_type="momentum",
            description="Pick! D.Buckner intercepts.",
            player=None, kicker=None, yards=None,
            scoring_team=None,
            wpa=0.22,  # comfortably above threshold
            synthetic=True,
        )
        await orch.on_play_event(evt)

        ws.broadcast.assert_awaited_once()
        assert ws.broadcast.await_args.args[1]["sequence_key"] == "big_play"
        # Lights fire — every step in _BIG_PLAY_STEPS executed.
        big_play_steps = CelebrationOrchestrator.SEQUENCES["big_play"].light_steps
        assert hue.set_light.await_count == len(big_play_steps)
        # No TTS — empty tts_lines list.
        tts.speak.assert_not_awaited()

    async def test_momentum_explicitly_owned_by_opponent_is_silent(self):
        """Opponent-owned momentum must never trigger Colts celebration lights."""
        orch, hue, tts, ws, _ = _make_orchestrator()
        evt = _event_with_type("momentum", scoring_team="opp")
        await orch.on_play_event(evt)
        ws.broadcast.assert_not_awaited()
        hue.set_light.assert_not_awaited()

    async def test_negative_colts_wpa_momentum_is_silent(self):
        """Defense in depth: a negative Colts WPA event cannot light the room."""
        orch, hue, tts, ws, _ = _make_orchestrator()
        base = _event_with_type("momentum", scoring_team=None)
        evt = PlayEvent(
            timestamp=base.timestamp,
            play_type="momentum",
            description="Opponent big play",
            player=None,
            kicker=None,
            yards=None,
            scoring_team=None,
            wpa=-0.39,
            synthetic=True,
        )
        await orch.on_play_event(evt)
        ws.broadcast.assert_not_awaited()
        hue.set_light.assert_not_awaited()


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

class TestCooldown:

    async def test_two_tds_within_cooldown_only_one_runs(self):
        orch, hue, tts, ws, _ = _make_orchestrator()

        # Stamp manually instead of waiting through a real sequence; the
        # cooldown logic checks `_last_celebration_at` and the value is
        # written at sequence START.
        await orch.on_play_event(_td_event())
        first_count = ws.broadcast.await_count
        first_lights = hue.set_light.await_count
        first_tts = tts.speak.await_count

        # Second TD immediately after — cooldown should reject it.
        await orch.on_play_event(_td_event(player="Anthony Richardson"))
        assert ws.broadcast.await_count == first_count
        assert hue.set_light.await_count == first_lights
        assert tts.speak.await_count == first_tts

    async def test_two_tds_past_cooldown_both_run(self):
        orch, hue, tts, ws, _ = _make_orchestrator()
        await orch.on_play_event(_td_event())
        baseline_broadcasts = ws.broadcast.await_count

        # Backdate the stamp past the cooldown window.
        orch._last_celebration_at = (
            time.time() - CelebrationOrchestrator.COOLDOWN_SECONDS - 0.1
        )

        await orch.on_play_event(_td_event(player="Anthony Richardson"))
        assert ws.broadcast.await_count == baseline_broadcasts + 1
        assert tts.speak.await_count == 2


# ---------------------------------------------------------------------------
# State transitions (end of game)
# ---------------------------------------------------------------------------

class TestEndOfGame:

    async def test_win_runs_celebration_with_tts(self):
        orch, hue, tts, ws, _ = _make_orchestrator(
            score_colts=27, score_opp=20, opponent="Houston Texans",
        )
        await orch.on_state_transition(_final_transition())

        ws.broadcast.assert_awaited_once()
        assert ws.broadcast.await_args.args[1]["sequence_key"] == "end_of_game_win"

        tts.speak.assert_awaited_once()
        text = tts.speak.await_args.args[0]
        assert "27" in text
        assert "20" in text

    async def test_loss_runs_lights_but_no_tts(self):
        orch, hue, tts, ws, _ = _make_orchestrator(
            score_colts=14, score_opp=24,
        )
        await orch.on_state_transition(_final_transition())

        ws.broadcast.assert_awaited_once()
        assert ws.broadcast.await_args.args[1]["sequence_key"] == "end_of_game_loss"

        # Loss is silent — spec §2.2 explicit.
        tts.speak.assert_not_awaited()

        # Lights still fire.
        loss_steps = CelebrationOrchestrator.SEQUENCES["end_of_game_loss"].light_steps
        assert hue.set_light.await_count == len(loss_steps)

    async def test_non_final_transition_is_noop(self):
        orch, hue, tts, ws, _ = _make_orchestrator()
        transition = GameDayStateTransition(
            from_status="pregame",
            to_status="in-progress",
            timestamp=datetime.now(timezone.utc),
        )
        await orch.on_state_transition(transition)
        ws.broadcast.assert_not_awaited()
        hue.set_light.assert_not_awaited()
        tts.speak.assert_not_awaited()


# ---------------------------------------------------------------------------
# Template substitution + structural invariants
# ---------------------------------------------------------------------------

class TestTemplateSubstitution:

    async def test_all_variables_substituted_in_td_template(self):
        """Pick a TD template that exercises {player}, run with player set,
        confirm format_map left no {placeholders} behind."""
        orch, _, tts, _, _ = _make_orchestrator()
        await orch.on_play_event(_td_event(player="Jonathan Taylor"))
        text = tts.speak.await_args.args[0]
        # No leftover braces from unsubstituted placeholders.
        assert "{" not in text and "}" not in text

    async def test_missing_player_falls_back_safely(self):
        """ESPN parser sometimes can't extract a player name. The line
        should still render — {player} is replaced by 'Indy' fallback
        (changed from 'Colts' 2026-05-07 to avoid double-Colts redundancy
        in templates that already include 'Colts' or 'for the Colts')."""
        orch, _, tts, _, _ = _make_orchestrator()
        evt = PlayEvent(
            timestamp=datetime.now(timezone.utc),
            play_type="touchdown",
            description="generic TD",
            player=None,
            kicker=None,
            yards=None,
            scoring_team="colts",
            synthetic=True,
        )
        await orch.on_play_event(evt)
        text = tts.speak.await_args.args[0]
        assert "{" not in text
        # Falls back to 'Indy' per _build_context — every TD pool line
        # still references either "Indy" (via fallback) or "Colts" (via
        # template's literal Colts mention).
        assert "Indy" in text or "Colts" in text


# ---------------------------------------------------------------------------
# Volume policy integration
# ---------------------------------------------------------------------------

class TestVolumePolicy:
    """The orchestrator delegates volume selection to
    celebration_volume_policy.compute_celebration_volume. These tests
    verify that apartment-context signals reach the policy and are
    honored — the policy itself is unit-tested separately."""

    async def test_huge_wpa_bumps_volume_to_45(self):
        """TD with |WPA| >= 0.25 → +15 from base 30 = 45."""
        orch, _, tts, _, _ = _make_orchestrator()
        await orch.on_play_event(_td_event(wpa=0.30))
        tts.speak.assert_awaited_once()
        assert tts.speak.await_args.kwargs.get("volume") == 45

    async def test_sleeping_mode_suppresses_tts(self):
        """current_mode == sleeping → TTS skipped, lights still fire."""
        orch, hue, tts, ws, _ = _make_orchestrator(automation_mode="sleeping")
        await orch.on_play_event(_td_event(wpa=0.30))

        # Lights + WS still fire.
        ws.broadcast.assert_awaited_once()
        assert hue.set_light.await_count > 0
        # TTS suppressed.
        tts.speak.assert_not_awaited()

    async def test_dnd_active_suppresses_tts(self):
        orch, hue, tts, ws, _ = _make_orchestrator(dnd_active=True)
        await orch.on_play_event(_td_event(wpa=0.30))
        ws.broadcast.assert_awaited_once()
        assert hue.set_light.await_count > 0
        tts.speak.assert_not_awaited()

    async def test_losing_blowout_suppresses_tts(self):
        """Q4, Colts down 28 — silent celebration even on a Colts FG."""
        orch, hue, tts, ws, _ = _make_orchestrator(
            score_colts=7, score_opp=35, quarter=4, clock="5:00",
        )
        await orch.on_play_event(_fg_event(wpa=0.05))
        ws.broadcast.assert_awaited_once()
        assert hue.set_light.await_count > 0
        tts.speak.assert_not_awaited()

    async def test_camera_absent_dials_volume_down(self):
        """Empty apartment → -10 from camera-absent modifier."""
        orch, _, tts, _, _ = _make_orchestrator(camera_present=False)
        await orch.on_play_event(_td_event(wpa=0.08))  # standard play
        tts.speak.assert_awaited_once()
        # base 30 + 0 from WPA - 10 from camera_absent = 20
        assert tts.speak.await_args.kwargs.get("volume") == 20

    async def test_home_state_ignores_camera_false_negative(self):
        """Confirmed Home is stronger than a weak camera absence signal."""
        orch, _, tts, _, _ = _make_orchestrator(
            house_state="home", camera_present=False,
        )
        await orch.on_play_event(_fg_event(wpa=0.02))
        tts.speak.assert_awaited_once()
        assert tts.speak.await_args.kwargs.get("volume") == 28

    async def test_loss_state_transition_no_tts(self):
        """Loss is silent regardless of policy — empty tts_lines pool."""
        orch, _, tts, _, _ = _make_orchestrator(
            score_colts=14, score_opp=24,
        )
        await orch.on_state_transition(GameDayStateTransition(
            from_status="in-progress",
            to_status="final",
            timestamp=datetime.now(timezone.utc),
        ))
        tts.speak.assert_not_awaited()

    async def test_win_state_transition_uses_eog_base_35(self):
        """end_of_game_win has base_volume=35, no WPA → 35."""
        orch, _, tts, _, _ = _make_orchestrator(
            score_colts=27, score_opp=20,
        )
        await orch.on_state_transition(GameDayStateTransition(
            from_status="in-progress",
            to_status="final",
            timestamp=datetime.now(timezone.utc),
            synthetic=True,
        ))
        tts.speak.assert_awaited_once()
        assert tts.speak.await_args.kwargs.get("volume") == 35


# ---------------------------------------------------------------------------
# Backwards compatibility: original 4-arg constructor
# ---------------------------------------------------------------------------

class TestBackwardsCompatibility:
    """The 4-arg constructor (no automation_engine, no camera_service)
    must keep working — defaults to None and the policy treats absent
    apartment context as "no suppression, no apartment modifier"."""

    async def test_4arg_constructor_still_fires(self):
        orch, hue, tts, ws, _ = _make_orchestrator(with_apartment_context=False)
        await orch.on_play_event(_td_event())
        ws.broadcast.assert_awaited_once()
        assert hue.set_light.await_count > 0
        tts.speak.assert_awaited_once()
        # No apartment context → falls through to base_volume = 30.
        assert tts.speak.await_args.kwargs.get("volume") == 30


# ---------------------------------------------------------------------------
# Sequence schema: per-event base_volume tuned post-d9c1fcd
# ---------------------------------------------------------------------------

class TestPerEventBaseVolume:
    """Per-event base_volume values codify the d9c1fcd live-test
    finding. Touchdown should be louder than kickoff; kickoff lower
    than the rest."""

    @pytest.mark.parametrize("key,expected_base", [
        ("touchdown", 30),
        ("field_goal", 28),
        ("kickoff", 22),
        ("end_of_game_win", 35),
        ("end_of_game_loss", 0),
    ])
    def test_base_volume_per_event(self, key, expected_base):
        seq = CelebrationOrchestrator.SEQUENCES[key]
        assert seq.base_volume == expected_base


# ---------------------------------------------------------------------------
# Lighting design rule: kitchen pair (L3 + L4)
# ---------------------------------------------------------------------------

class TestEventLoggerWiring:
    """The orchestrator must mirror every successful set_light into the
    EventLogger so celebrations show up in `light_adjustments`. Without
    this, gameday choreography is invisible to get_state_history, the
    nightly journal, and DB analytics.

    Memory: ~/.claude/projects/.../project_celebration_no_event_log.md.
    """

    async def test_celebration_logs_to_event_logger(self):
        """Kickoff is the smallest sequence (4 baseline steps, all at
        delay_ms=0). Asserts every step produces a log_light_adjustment
        call tagged trigger='celebration:kickoff'."""
        hue = MagicMock()
        hue.set_light = AsyncMock(return_value=True)
        # Polled state cache — orchestrator reads `_last_states` for
        # before-vector. Populate so before/after differs and the logger
        # doesn't dedup.
        hue._last_states = {
            "1": {"name": "Lamp 1", "bri": 100, "hue": 8000, "sat": 100},
            "2": {"name": "Lamp 2", "bri": 100, "hue": 8000, "sat": 100},
            "3": {"name": "Kitchen 3", "bri": 100, "hue": 8000, "sat": 100},
            "4": {"name": "Kitchen 4", "bri": 100, "hue": 8000, "sat": 100},
        }

        tts = MagicMock()
        tts.speak = AsyncMock(return_value=True)

        ws = MagicMock()
        ws.broadcast = AsyncMock()

        gameday = MagicMock()
        gameday.current_state = MagicMock(
            return_value=GameDayState(
                status="in-progress",
                opponent="Houston Texans",
                kickoff_utc=datetime.now(timezone.utc),
                score_colts=0,
                score_opp=0,
                quarter=1,
                clock="15:00",
                possession="colts",
                last_play=None,
            )
        )

        automation = MagicMock()
        automation.current_mode = "gameday"
        automation.is_dnd_active = MagicMock(return_value=False)
        automation.transient_light_write_block_reason = MagicMock(return_value=None)
        automation.reapply_current_mode = AsyncMock()

        event_logger = MagicMock()
        event_logger.log_light_adjustment = AsyncMock(return_value=None)

        orch = CelebrationOrchestrator(
            hue_service=hue,
            tts_service=tts,
            ws_manager=ws,
            gameday_service=gameday,
            automation_engine=automation,
            camera_service=None,
            event_logger=event_logger,
        )

        await orch.on_play_event(_kickoff_event())

        kickoff_steps = CelebrationOrchestrator.SEQUENCES["kickoff"].light_steps
        # set_light fired once per step.
        assert hue.set_light.await_count == len(kickoff_steps)

        # And every successful set_light produced a log_light_adjustment.
        assert event_logger.log_light_adjustment.await_count == len(kickoff_steps)
        assert event_logger.log_light_adjustment.await_count >= 4

        # Every call must be tagged with the celebration trigger prefix.
        for call in event_logger.log_light_adjustment.await_args_list:
            kwargs = call.kwargs
            assert "trigger" in kwargs
            assert kwargs["trigger"].startswith("celebration:"), (
                f"trigger should start with 'celebration:', got {kwargs['trigger']!r}"
            )
            assert kwargs["trigger"] == "celebration:kickoff"
            # mode_at_time threaded through from the automation engine.
            assert kwargs.get("mode_at_time") == "gameday"

    async def test_celebration_works_without_event_logger(self):
        """event_logger=None (the backwards-compat default) must not break
        the sequence — set_light still fires, no log calls attempted."""
        orch, hue, tts, ws, _ = _make_orchestrator()
        # Default _make_orchestrator omits event_logger → None.
        assert orch._event_logger is None

        await orch.on_play_event(_kickoff_event())

        kickoff_steps = CelebrationOrchestrator.SEQUENCES["kickoff"].light_steps
        assert hue.set_light.await_count == len(kickoff_steps)
        # No exception raised, sequence ran end-to-end.
        ws.broadcast.assert_awaited_once()

    async def test_set_light_failure_skips_log(self):
        """If hue.set_light raises, the corresponding log_light_adjustment
        must NOT be called — we only mirror confirmed bridge writes."""
        # Derive step count from the live SEQUENCES so future iterations
        # don't drift this fixture out of sync with kickoff's shape.
        kickoff_steps = CelebrationOrchestrator.SEQUENCES["kickoff"].light_steps
        n_steps = len(kickoff_steps)

        hue = MagicMock()
        # First step raises, rest succeed.
        hue.set_light = AsyncMock(side_effect=[
            RuntimeError("bridge timeout"),
            *[True] * (n_steps - 1),
        ])
        hue._last_states = {
            "1": {"name": "Lamp 1", "bri": 100, "hue": 8000, "sat": 100},
            "2": {"name": "Lamp 2", "bri": 100, "hue": 8000, "sat": 100},
            "3": {"name": "Kitchen 3", "bri": 100, "hue": 8000, "sat": 100},
            "4": {"name": "Kitchen 4", "bri": 100, "hue": 8000, "sat": 100},
        }

        tts = MagicMock()
        tts.speak = AsyncMock(return_value=True)
        ws = MagicMock()
        ws.broadcast = AsyncMock()
        gameday = MagicMock()
        gameday.current_state = MagicMock(return_value=None)

        event_logger = MagicMock()
        event_logger.log_light_adjustment = AsyncMock(return_value=None)

        orch = CelebrationOrchestrator(
            hue_service=hue,
            tts_service=tts,
            ws_manager=ws,
            gameday_service=gameday,
            event_logger=event_logger,
        )

        await orch.on_play_event(_kickoff_event())

        # All steps attempted; one failed, so log calls = n_steps - 1.
        assert hue.set_light.await_count == n_steps
        assert event_logger.log_light_adjustment.await_count == n_steps - 1


class TestKickoffTeamFormReader:
    """The orchestrator's `_pick_kickoff_template` reads team form from
    `app_settings['gameday_team_form']` and passes it to the picker.
    Valid shape → dimes/jones swap kicks in. Absent / malformed →
    defaults to None (jones pool)."""

    async def _make_orch(self):
        orch, hue, tts, ws, gameday = _make_orchestrator()
        # Pin gameday state so kickoff_at lands on a Sunday afternoon.
        from datetime import datetime as _dt
        sunday_afternoon = _dt(2026, 9, 13, 13, 0, tzinfo=timezone.utc).astimezone(
            __import__("zoneinfo").ZoneInfo("America/Indiana/Indianapolis")
        )
        gameday.current_state = MagicMock(
            return_value=GameDayState(
                status="scheduled",
                opponent="Houston Texans",
                kickoff_utc=sunday_afternoon,
                score_colts=0,
                score_opp=0,
                quarter=0,
                clock="",
                possession=None,
                last_play=None,
            )
        )
        return orch

    async def test_no_app_setting_returns_jones_line(self, monkeypatch):
        orch = await self._make_orch()

        async def _stub_load_setting(key):
            return {}  # no row

        monkeypatch.setattr(
            "backend.api.routes.routines.load_setting", _stub_load_setting,
        )

        line = await orch._pick_kickoff_template()
        assert "Daniel Jones" in line
        assert "Danny Dimes" not in line

    async def test_winning_form_returns_dimes_line(self, monkeypatch):
        orch = await self._make_orch()

        async def _stub_load_setting(key):
            if key == "gameday_playoff_state":
                return {"record": [7, 3, 0], "season_year": 2026, "is_preseason": False}
            assert key == "gameday_team_form"
            return {
                "season_year": 2026,
                "last4_record": [3, 1],
                "win_streak": 2,
                "season_record": [7, 3, 0],
            }

        monkeypatch.setattr(
            "backend.api.routes.routines.load_setting", _stub_load_setting,
        )

        line = await orch._pick_kickoff_template()
        assert "Danny Dimes" in line
        assert "Daniel Jones" not in line

    async def test_stale_prior_season_form_falls_back_to_jones(self, monkeypatch):
        orch = await self._make_orch()

        async def _stub_load_setting(key):
            if key == "gameday_playoff_state":
                return {"record": [7, 3, 0], "season_year": 2026, "is_preseason": False}
            return {
                "season_year": 2025,
                "last4_record": [3, 1],
                "win_streak": 2,
                "season_record": [7, 3, 0],
            }

        monkeypatch.setattr(
            "backend.api.routes.routines.load_setting", _stub_load_setting,
        )

        line = await orch._pick_kickoff_template()
        assert "Daniel Jones" in line
        assert "Danny Dimes" not in line

    async def test_struggling_form_returns_jones_line(self, monkeypatch):
        orch = await self._make_orch()

        async def _stub_load_setting(key):
            if key == "gameday_playoff_state":
                return {"record": [2, 5, 0], "season_year": 2026, "is_preseason": False}
            return {
                "season_year": 2026,
                "last4_record": [1, 3],
                "win_streak": 0,
                "season_record": [2, 5, 0],
            }

        monkeypatch.setattr(
            "backend.api.routes.routines.load_setting", _stub_load_setting,
        )

        line = await orch._pick_kickoff_template()
        assert "Daniel Jones" in line
        assert "Danny Dimes" not in line

    async def test_malformed_app_setting_falls_back_to_jones(self, monkeypatch):
        """A bad shape in app_settings (e.g. wrong types or missing keys)
        must never block a kickoff — picker falls through to None form
        and picks from the jones pool."""
        orch = await self._make_orch()

        async def _stub_load_setting(key):
            return {"last4_record": "not-a-list", "win_streak": "also-bad"}

        monkeypatch.setattr(
            "backend.api.routes.routines.load_setting", _stub_load_setting,
        )

        line = await orch._pick_kickoff_template()
        # Doesn't raise; gets a real line; falls back to jones.
        assert isinstance(line, str)
        assert "Danny Dimes" not in line

    async def test_load_setting_raises_falls_back_to_jones(self, monkeypatch):
        """If `load_setting` itself raises (DB hiccup), the kickoff still
        fires with the measured pool."""
        orch = await self._make_orch()

        async def _stub_load_setting(key):
            raise RuntimeError("DB unreachable")

        monkeypatch.setattr(
            "backend.api.routes.routines.load_setting", _stub_load_setting,
        )

        line = await orch._pick_kickoff_template()
        assert isinstance(line, str)
        assert "Danny Dimes" not in line


class TestKitchenPairRule:
    """Gameday is a functional mode → kitchen pair (lights 3 + 4) MUST
    match in every authored sequence frame. We verify by walking each
    sequence and confirming that for every L3 frame at delay_ms = D, an
    L4 frame at the same delay_ms exists with the same {bri, hue, sat,
    ct, on}. Hard rule from feedback_lighting_design_principles.md."""

    @pytest.mark.parametrize(
        "key", ["touchdown", "field_goal", "kickoff",
                "end_of_game_win", "end_of_game_loss"],
    )
    def test_kitchen_pair_matches(self, key):
        seq = CelebrationOrchestrator.SEQUENCES[key]
        l3_frames = {s.delay_ms: s.state for s in seq.light_steps if s.light_id == "3"}
        l4_frames = {s.delay_ms: s.state for s in seq.light_steps if s.light_id == "4"}

        assert set(l3_frames.keys()) == set(l4_frames.keys()), (
            f"{key}: L3 + L4 must fire on the same delays"
        )
        for delay_ms, l3_state in l3_frames.items():
            l4_state = l4_frames[delay_ms]
            for k in ("on", "bri", "hue", "sat", "ct"):
                if k in l3_state or k in l4_state:
                    assert l3_state.get(k) == l4_state.get(k), (
                        f"{key} @ {delay_ms}ms: kitchen pair diverges on {k!r} "
                        f"(L3={l3_state.get(k)} L4={l4_state.get(k)})"
                    )


class TestPlantWashCelebrationRule:
    """L6 Plant Wash is a Colts-blue accent in full-room celebrations."""

    FULL_ROOM_KEYS = (
        "touchdown",
        "field_goal",
        "kickoff",
        "end_of_game_win",
        "end_of_game_loss",
        "safety",
        "two_point_conv",
        "defensive_td",
        "big_play",
    )

    @pytest.mark.parametrize("key", FULL_ROOM_KEYS)
    def test_full_room_sequences_include_plant_wash(self, key):
        seq = CelebrationOrchestrator.SEQUENCES[key]
        assert any(step.light_id == "6" for step in seq.light_steps), key

    @pytest.mark.parametrize("key", FULL_ROOM_KEYS)
    def test_plant_wash_remains_colts_blue_anchor(self, key):
        seq = CelebrationOrchestrator.SEQUENCES[key]
        plant_steps = [step for step in seq.light_steps if step.light_id == "6"]
        assert plant_steps
        assert all(step.state.get("hue") == 47000 for step in plant_steps)
        assert all(int(step.state.get("sat", 0)) > 0 for step in plant_steps)

    def test_touchdown_visibly_pulses_plant_wash(self):
        seq = CelebrationOrchestrator.SEQUENCES["touchdown"]
        plant_brightness = [
            int(step.state["bri"])
            for step in seq.light_steps
            if step.light_id == "6" and "bri" in step.state
        ]
        assert max(plant_brightness) >= 225
        assert len(set(plant_brightness)) >= 3

    def test_pat_remains_deliberately_l1_only(self):
        seq = CelebrationOrchestrator.SEQUENCES["extra_point_good"]
        assert {step.light_id for step in seq.light_steps} == {"1"}

    def test_end_game_loss_holds_muted_state_before_reconcile(self):
        seq = CelebrationOrchestrator.SEQUENCES["end_of_game_loss"]
        assert max(step.delay_ms for step in seq.light_steps) >= int(
            seq.duration_seconds * 1000
        )


# ---------------------------------------------------------------------------
# #253 — game-sensitive semantic momentum dispatch
# ---------------------------------------------------------------------------

class TestSemanticMomentumDispatch:
    @pytest.mark.parametrize("play_type", ["fourth_down_stop", "blocked_punt", "blocked_field_goal", "interception", "fumble_recovery"])
    async def test_semantic_events_use_lower_amp_lights_only_sequence(
        self, play_type
    ):
        orch, hue, tts, ws, _ = _make_orchestrator()
        evt = PlayEvent(
            timestamp=datetime.now(timezone.utc),
            play_type=play_type,
            description="Meaningful defensive/special-teams stop.",
            player=None,
            kicker=None,
            yards=None,
            scoring_team=None,
            wpa=0.027,
            synthetic=True,
        )

        await orch.on_play_event(evt)

        ws.broadcast.assert_awaited_once()
        assert ws.broadcast.await_args.args[1]["sequence_key"] == "semantic_momentum"
        semantic = CelebrationOrchestrator.SEQUENCES["semantic_momentum"]
        assert hue.set_light.await_count == len(semantic.light_steps)
        tts.speak.assert_not_awaited()

    def test_semantic_sequence_is_visibly_below_generic_big_play_amp(self):
        semantic = CelebrationOrchestrator.SEQUENCES["semantic_momentum"]
        big_play = CelebrationOrchestrator.SEQUENCES["big_play"]

        assert semantic.duration_seconds < big_play.duration_seconds
        assert len(semantic.light_steps) < len(big_play.light_steps)
        semantic_ids = {step.light_id for step in semantic.light_steps}
        assert semantic_ids == {"1", "2", "5", "6"}
        assert "3" not in semantic_ids and "4" not in semantic_ids

        semantic_peak = max(
            int(step.state.get("bri", 0)) for step in semantic.light_steps
        )
        big_play_peak = max(
            int(step.state.get("bri", 0)) for step in big_play.light_steps
        )
        assert semantic_peak == 215
        assert semantic_peak < big_play_peak
        assert semantic.tts_lines == []


@pytest.mark.asyncio
async def test_direct_celebration_skips_protected_light_before_hue_write():
    orch, hue, _, _, _ = _make_orchestrator()
    orch._automation.transient_light_write_block_reason.side_effect = (
        lambda light_id: "protected light 2" if light_id == "2" else None
    )
    steps = [
        LightStep(light_id="1", delay_ms=0, state={"on": True, "bri": 200}),
        LightStep(light_id="2", delay_ms=0, state={"on": True, "bri": 200}),
    ]

    written = await orch._run_light_steps(steps, "big_play", play=None)

    assert written == {"1"}
    hue.set_light.assert_awaited_once_with(
        "1", {"on": True, "bri": 200},
    )


@pytest.mark.asyncio
async def test_direct_celebration_ownership_check_failure_fails_closed():
    orch, hue, _, _, _ = _make_orchestrator()
    orch._automation.transient_light_write_block_reason.side_effect = RuntimeError(
        "ownership unavailable"
    )
    steps = [
        LightStep(light_id="1", delay_ms=0, state={"on": True, "bri": 200}),
    ]

    written = await orch._run_light_steps(steps, "big_play", play=None)

    assert written == set()
    hue.set_light.assert_not_awaited()


@pytest.mark.asyncio
async def test_fully_blocked_sequence_does_not_reconcile_or_touch_hue():
    orch, hue, _, _, _ = _make_orchestrator()
    orch._automation.transient_light_write_block_reason = MagicMock(
        return_value="protected by newer owner"
    )

    await orch._run_sequence("semantic_momentum", {}, play=None)

    hue.set_light.assert_not_awaited()
    orch._automation.reapply_current_mode.assert_not_awaited()


# ---------------------------------------------------------------------------
# #253 kickoff + provider score subtype hardening
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_pregame_to_in_progress_transition_fires_kickoff_with_live_authority():
    orch, _, _, _, gameday = _make_orchestrator()
    gameday.celebration_eligibility = MagicMock(
        return_value=(True, "current Game Day authority")
    )
    orch._run_sequence = AsyncMock()
    transition = GameDayStateTransition(
        from_status="pregame", to_status="in-progress",
        timestamp=datetime.now(timezone.utc), game_id="kickoff-game",
        synthetic=False,
    )

    await orch.on_state_transition(transition)

    gameday.celebration_eligibility.assert_called_once_with(
        game_id="kickoff-game", allow_final=False,
    )
    assert orch._run_sequence.await_args.args[0] == "kickoff"
    assert orch._run_sequence.await_args.kwargs["transition"] is transition


@pytest.mark.asyncio
async def test_kickoff_transition_fails_closed_when_live_authority_is_gone():
    orch, hue, tts, ws, gameday = _make_orchestrator()
    gameday.celebration_eligibility = MagicMock(
        return_value=(False, "automation mode=watching")
    )
    transition = GameDayStateTransition(
        from_status="pregame", to_status="in-progress",
        timestamp=datetime.now(timezone.utc), game_id="kickoff-game",
        synthetic=False,
    )
    await orch.on_state_transition(transition)
    hue.set_light.assert_not_awaited()
    tts.speak.assert_not_awaited()
    ws.broadcast.assert_not_awaited()

@pytest.mark.asyncio
async def test_return_touchdown_uses_special_teams_sequence_not_defense_wording():
    orch, _, _, _, _ = _make_orchestrator()
    orch._run_sequence = AsyncMock()
    evt = PlayEvent(
        timestamp=datetime.now(timezone.utc), play_type="return_td",
        description="Antonio Gibson 90 Yd Kickoff Return",
        player=None, kicker=None, yards=None, scoring_team="colts",
        synthetic=True,
    )
    await orch.on_play_event(evt)
    assert orch._run_sequence.await_args.args[0] == "return_td"
    lines = CelebrationOrchestrator.SEQUENCES["return_td"].tts_lines
    assert lines
    assert all("defense" not in line.lower() for line in lines)


@pytest.mark.asyncio
async def test_derived_conversion_followup_bypasses_global_play_cooldown():
    orch, _, _, _, _ = _make_orchestrator()
    orch._run_sequence = AsyncMock()
    evt = PlayEvent(
        timestamp=datetime.now(timezone.utc), play_type="extra_point_good",
        description="Jonathan Taylor 3 Yd Rush (Spencer Shrader Kick)",
        player=None, kicker=None, yards=None, scoring_team="colts",
        event_id="td-1:extra_point_good", synthetic=True,
    )
    await orch.on_play_event(evt)
    assert orch._run_sequence.await_args.args[0] == "extra_point_good"
    assert orch._run_sequence.await_args.kwargs["bypass_cooldown"] is True


@pytest.mark.asyncio
async def test_standalone_two_point_score_bypasses_parent_score_cooldown():
    orch, _, _, _, _ = _make_orchestrator()
    orch._run_sequence = AsyncMock()
    evt = PlayEvent(
        timestamp=datetime.now(timezone.utc), play_type="two_point_conv",
        description="Markquese Bell Defensive PAT Conversion",
        player=None, kicker=None, yards=None, scoring_team="colts",
        event_id="standalone-2pt", synthetic=True,
    )
    await orch.on_play_event(evt)
    assert orch._run_sequence.await_args.kwargs["bypass_cooldown"] is True


@pytest.mark.asyncio
async def test_real_embedded_conversion_without_independent_time_is_silent():
    orch, _, _, _, _ = _make_orchestrator()
    orch._run_sequence = AsyncMock()
    evt = PlayEvent(
        timestamp=datetime.now(timezone.utc),
        play_type="extra_point_good",
        description="Jonathan Taylor 3 Yd Rush (Spencer Shrader Kick)",
        player=None,
        kicker=None,
        yards=None,
        scoring_team="colts",
        event_id="td-1:extra_point_good",
        game_id="game-1",
        timestamp_trusted=False,
        synthetic=False,
    )

    await orch.on_play_event(evt)

    orch._run_sequence.assert_not_awaited()


@pytest.mark.asyncio
async def test_conversion_cooldown_bypass_does_not_extend_global_window(monkeypatch):
    orch, _, _, ws, _ = _make_orchestrator()
    tiny = CelebrationSequence(
        light_steps=[], tts_lines=[], duration_seconds=0.0, base_volume=0,
    )
    monkeypatch.setitem(orch.SEQUENCES, "conversion_probe", tiny)
    previous = time.time()
    orch._last_celebration_at = previous

    await orch._run_sequence(
        "conversion_probe", {}, play=_other_event(), bypass_cooldown=True,
    )

    ws.broadcast.assert_awaited_once()
    assert orch._last_celebration_at == previous


# ---------------------------------------------------------------------------
# Adaptive viewer synchronization (#253)
# ---------------------------------------------------------------------------

def _provider_td() -> PlayEvent:
    evt = _td_event()
    evt.synthetic = False
    evt.game_id = "game-1"
    evt.event_id = "play-1"
    return evt


def _viewer_sync(result: ViewerReleaseResult) -> MagicMock:
    viewer = MagicMock()
    viewer.release_decision = MagicMock(
        return_value=ViewerSyncDecision(True, "await viewer clock", 0),
    )
    viewer.wait_until_visible = AsyncMock(return_value=result)
    return viewer


@pytest.mark.asyncio
async def test_viewer_synced_play_defers_without_blocking_provider_callback():
    viewer = _viewer_sync(ViewerReleaseResult.VISIBLE)
    orch, _, _, _, gameday = _make_orchestrator(viewer_sync=viewer)
    gameday.celebration_eligibility = MagicMock(
        return_value=(True, "current Game Day authority"),
    )
    orch._run_sequence = AsyncMock()

    await orch.on_play_event(_provider_td())
    orch._run_sequence.assert_not_awaited()

    await asyncio.sleep(0)
    await asyncio.sleep(0)
    orch._run_sequence.assert_awaited_once()


@pytest.mark.asyncio
async def test_forward_seek_drops_deferred_celebration():
    viewer = _viewer_sync(ViewerReleaseResult.SKIPPED_BY_SEEK)
    orch, _, _, _, gameday = _make_orchestrator(viewer_sync=viewer)
    gameday.celebration_eligibility = MagicMock(
        return_value=(True, "current Game Day authority"),
    )
    orch._run_sequence = AsyncMock()

    await orch.on_play_event(_provider_td())
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    orch._run_sequence.assert_not_awaited()


@pytest.mark.asyncio
async def test_viewer_clock_loss_falls_back_to_normal_authority_path():
    viewer = _viewer_sync(ViewerReleaseResult.UNAVAILABLE)
    orch, _, _, _, gameday = _make_orchestrator(viewer_sync=viewer)
    gameday.celebration_eligibility = MagicMock(
        return_value=(True, "current Game Day authority"),
    )
    orch._run_sequence = AsyncMock()

    await orch.on_play_event(_provider_td())
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    orch._run_sequence.assert_awaited_once()
    assert gameday.celebration_eligibility.call_count >= 2


@pytest.mark.asyncio
async def test_close_cancels_still_waiting_viewer_synced_celebration():
    gate = asyncio.Event()

    async def wait_forever(*args, **kwargs):
        await gate.wait()
        return ViewerReleaseResult.VISIBLE

    viewer = MagicMock()
    viewer.release_decision = MagicMock(
        return_value=ViewerSyncDecision(True, "await viewer clock", 0),
    )
    viewer.wait_until_visible = AsyncMock(side_effect=wait_forever)
    orch, _, _, _, gameday = _make_orchestrator(viewer_sync=viewer)
    gameday.celebration_eligibility = MagicMock(
        return_value=(True, "current Game Day authority"),
    )
    orch._run_sequence = AsyncMock()

    await orch.on_play_event(_provider_td())
    await asyncio.sleep(0)
    assert len(orch._viewer_sync_wait_tasks) == 1

    await orch.close()
    assert not orch._viewer_sync_wait_tasks
    orch._run_sequence.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_already_skipped_by_seek_never_schedules_celebration():
    viewer = MagicMock()
    viewer.release_decision = MagicMock(
        return_value=ViewerSyncDecision(
            False, "skipped by forward seek", 3, drop=True,
        ),
    )
    viewer.wait_until_visible = AsyncMock()
    orch, _, _, _, gameday = _make_orchestrator(viewer_sync=viewer)
    gameday.celebration_eligibility = MagicMock(
        return_value=(True, "current Game Day authority"),
    )
    orch._run_sequence = AsyncMock()

    await orch.on_play_event(_provider_td())

    orch._run_sequence.assert_not_awaited()
    viewer.wait_until_visible.assert_not_awaited()
    assert not orch._viewer_sync_wait_tasks



@pytest.mark.asyncio
async def test_viewer_visible_play_uses_delayed_final_authority_recheck():
    viewer = _viewer_sync(ViewerReleaseResult.VISIBLE)
    orch, _, _, _, gameday = _make_orchestrator(viewer_sync=viewer)
    gameday.celebration_eligibility = MagicMock(
        return_value=(True, "current Game Day authority"),
    )
    orch._run_sequence = AsyncMock()

    await orch.on_play_event(_provider_td())
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert any(
        call.kwargs.get("allow_viewer_delayed_play") is True
        for call in gameday.celebration_eligibility.call_args_list
    )
    assert orch._run_sequence.await_args.kwargs["viewer_delayed"] is True


@pytest.mark.asyncio
async def test_batch_anchor_wait_still_drops_play_skipped_at_its_provider_timestamp():
    play = _provider_td()
    play.viewer_anchor = play.timestamp + timedelta(seconds=12)
    decisions = [
        ViewerSyncDecision(True, "await play", 0),
        ViewerSyncDecision(True, "await batch frame", 0),
        ViewerSyncDecision(False, "skipped by forward seek", 1, drop=True),
    ]
    viewer = MagicMock()
    viewer.release_decision = MagicMock(side_effect=decisions)
    viewer.wait_until_visible = AsyncMock(return_value=ViewerReleaseResult.VISIBLE)
    orch, _, _, _, gameday = _make_orchestrator(viewer_sync=viewer)
    gameday.celebration_eligibility = MagicMock(
        return_value=(True, "current Game Day authority"),
    )
    orch._run_sequence = AsyncMock()

    await orch.on_play_event(play)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    viewer.wait_until_visible.assert_awaited_once()
    assert viewer.wait_until_visible.await_args.args[0] == play.viewer_anchor
    orch._run_sequence.assert_not_awaited()
@pytest.mark.asyncio
async def test_final_transition_bypasses_hulu_provider_program_offset() -> None:
    viewer = _viewer_sync(ViewerReleaseResult.VISIBLE)
    orch, _, _, _, gameday = _make_orchestrator(viewer_sync=viewer)
    gameday.celebration_eligibility = MagicMock(
        return_value=(True, "current Game Day authority"),
    )
    gameday.current_state.return_value = GameDayState(
        status="final",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=30,
        score_opp=33,
        quarter=5,
        clock="0:00",
        possession=None,
        last_play=None,
    )
    orch._run_sequence = AsyncMock()
    transition = GameDayStateTransition(
        from_status="in-progress",
        to_status="final",
        timestamp=datetime.now(timezone.utc),
        game_id="game-1",
    )

    await orch.on_state_transition(transition)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert viewer.release_decision.call_args_list[0].kwargs[
        "apply_program_time_offset"
    ] is False
    assert viewer.wait_until_visible.await_args.kwargs[
        "apply_program_time_offset"
    ] is False
    orch._run_sequence.assert_awaited_once()
