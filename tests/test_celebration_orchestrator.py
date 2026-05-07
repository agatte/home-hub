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

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services import celebration_orchestrator as _orch_module
from backend.services.celebration_orchestrator import (
    CelebrationOrchestrator,
    CelebrationSequence,
    LightStep,
)
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
    dnd_active: bool = False,
    camera_present: bool = True,
    with_apartment_context: bool = True,
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
        automation.is_dnd_active = MagicMock(return_value=dnd_active)

        camera = MagicMock()
        camera.is_present_within_seconds = MagicMock(return_value=camera_present)

        orch = CelebrationOrchestrator(
            hue_service=hue,
            tts_service=tts,
            ws_manager=ws,
            gameday_service=gameday,
            automation_engine=automation,
            camera_service=camera,
        )
    else:
        # Backwards-compat: original 4-arg signature.
        orch = CelebrationOrchestrator(
            hue_service=hue,
            tts_service=tts,
            ws_manager=ws,
            gameday_service=gameday,
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
    )


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
    )


def _final_transition() -> GameDayStateTransition:
    return GameDayStateTransition(
        from_status="in-progress",
        to_status="final",
        timestamp=datetime.now(timezone.utc),
    )


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
        should still render — {player} is replaced by 'Colts' fallback."""
        orch, _, tts, _, _ = _make_orchestrator()
        evt = PlayEvent(
            timestamp=datetime.now(timezone.utc),
            play_type="touchdown",
            description="generic TD",
            player=None,
            kicker=None,
            yards=None,
            scoring_team="colts",
        )
        await orch.on_play_event(evt)
        text = tts.speak.await_args.args[0]
        assert "{" not in text
        # Falls back to 'Colts' per _build_context.
        assert "Colts" in text or "colts" in text.lower()


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
            assert key == "gameday_team_form"
            return {
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

    async def test_struggling_form_returns_jones_line(self, monkeypatch):
        orch = await self._make_orch()

        async def _stub_load_setting(key):
            return {
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
