"""
AwayManager (D2/D6, GH#107) — leave/arrive behaviors, idempotency,
persistence restore, TTS quiet-hours gating, and the new engine hooks
(arm_away_suppression / reapply_current_mode).
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.away_manager import (
    AWAY_STATE_KEY,
    LEAVE_FADE_TRANSITIONTIME,
    AwayManager,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeEngine:
    """Just the surface AwayManager touches."""

    def __init__(self, *, mode="working", dnd=False, period="evening"):
        self._external_off_detected = False
        self._mode = mode
        self._dnd = dnd
        self._period = period
        self.signal_presence = AsyncMock(side_effect=self._clear)
        self.reapply_current_mode = AsyncMock()
        self.armed_by: list[str] = []

    async def _clear(self, source):
        self._external_off_detected = False

    def arm_away_suppression(self, source: str) -> None:
        self._external_off_detected = True
        self.armed_by.append(source)

    @property
    def current_mode(self) -> str:
        return self._mode

    def is_dnd_active(self) -> bool:
        return self._dnd

    def _get_time_period(self) -> str:
        return self._period


class FakeSettings:
    """In-memory save_setting/load_setting pair."""

    def __init__(self, initial=None):
        self.store = dict(initial or {})

    async def save(self, key, value):
        self.store[key] = value

    async def load(self, key):
        return self.store.get(key)


def _make_manager(
    *,
    engine=None,
    settings=None,
    sonos_state="STOPPED",
    sonos_connected=True,
    hue_connected=True,
    vibe_router=None,
):
    engine = engine or FakeEngine()
    settings = settings or FakeSettings()

    hue = MagicMock()
    hue.connected = hue_connected
    hue.set_all_lights = AsyncMock(return_value=True)

    sonos = MagicMock()
    sonos.connected = sonos_connected
    sonos.get_status = AsyncMock(return_value={"state": sonos_state})
    sonos.pause = AsyncMock(return_value=True)

    tts = MagicMock()
    tts.speak = AsyncMock(return_value=True)

    notifier = MagicMock()
    notifier.emit_alert = AsyncMock(return_value=True)

    mgr = AwayManager(
        engine=engine,
        hue_getter=lambda: hue,
        sonos_getter=lambda: sonos,
        tts_getter=lambda: tts,
        notifier_getter=lambda: notifier,
        save_setting=settings.save,
        load_setting=settings.load,
        vibe_router_getter=lambda: vibe_router,
    )
    return mgr, engine, settings, hue, sonos, tts, notifier


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------

class TestLeave:
    async def test_leave_arms_suppression_before_lights_off(self):
        mgr, engine, settings, hue, sonos, tts, notifier = _make_manager()

        result = await mgr.handle_event("leave", "ios_shortcut")

        assert result == {"status": "ok", "away": True, "changed": True}
        assert mgr.away is True
        assert engine._external_off_detected is True
        assert engine.armed_by == ["geofence:ios_shortcut"]
        hue.set_all_lights.assert_awaited_once_with(
            {"on": False, "transitiontime": LEAVE_FADE_TRANSITIONTIME}
        )

    async def test_leave_pauses_sonos_only_when_playing(self):
        mgr, *_, sonos, _tts, _n = _make_manager(sonos_state="PLAYING")
        await mgr.handle_event("leave", "ios_shortcut")
        sonos.pause.assert_awaited_once()

        mgr2, *_, sonos2, _tts2, _n2 = _make_manager(sonos_state="PAUSED_PLAYBACK")
        await mgr2.handle_event("leave", "ios_shortcut")
        sonos2.pause.assert_not_awaited()

    async def test_leave_emits_exactly_one_notification(self):
        mgr, *_, notifier = _make_manager()
        await mgr.handle_event("leave", "ios_shortcut")
        notifier.emit_alert.assert_awaited_once()
        kwargs = notifier.emit_alert.await_args.kwargs
        assert kwargs["kind"] == "away"
        assert kwargs["force"] is False

    async def test_leave_persists_state(self):
        mgr, _engine, settings, *_ = _make_manager()
        await mgr.handle_event("leave", "ios_shortcut")
        saved = settings.store[AWAY_STATE_KEY]
        assert saved["away"] is True
        assert saved["since_utc"] is not None

    async def test_duplicate_leave_is_noop(self):
        mgr, _engine, _settings, hue, sonos, _tts, notifier = _make_manager()
        await mgr.handle_event("leave", "ios_shortcut")
        result = await mgr.handle_event("leave", "ios_shortcut")
        assert result["changed"] is False
        # Actuation happened exactly once.
        hue.set_all_lights.assert_awaited_once()
        notifier.emit_alert.assert_awaited_once()

    async def test_sonos_failure_does_not_abort_lights_off(self):
        mgr, _engine, _settings, hue, sonos, *_ = _make_manager(sonos_state="PLAYING")
        sonos.pause.side_effect = RuntimeError("boom")
        await mgr.handle_event("leave", "ios_shortcut")
        hue.set_all_lights.assert_awaited_once()
        assert mgr.away is True


# ---------------------------------------------------------------------------
# Arrive
# ---------------------------------------------------------------------------

class TestArrive:
    async def test_arrive_releases_suppression_and_reapplies(self):
        mgr, engine, *_ = _make_manager()
        await mgr.handle_event("leave", "ios_shortcut")
        assert engine._external_off_detected is True

        result = await mgr.handle_event("arrive", "ios_shortcut")

        assert result == {"status": "ok", "away": False, "changed": True}
        assert mgr.away is False
        assert engine._external_off_detected is False
        engine.signal_presence.assert_awaited_with("geofence:ios_shortcut")
        engine.reapply_current_mode.assert_awaited_once_with(force_resend=True)

    async def test_arrive_speaks_welcome_when_allowed(self):
        mgr, _engine, _settings, _hue, _sonos, tts, _n = _make_manager()
        await mgr.handle_event("leave", "ios_shortcut")
        await mgr.handle_event("arrive", "ios_shortcut")
        tts.speak.assert_awaited_once_with("Welcome home.")

    @pytest.mark.parametrize(
        "engine_kwargs",
        [
            {"dnd": True},
            {"mode": "sleeping"},
            {"period": "late_night"},
        ],
    )
    async def test_arrive_tts_suppressed(self, engine_kwargs):
        engine = FakeEngine(**engine_kwargs)
        mgr, _e, _settings, _hue, _sonos, tts, _n = _make_manager(engine=engine)
        await mgr.handle_event("leave", "ios_shortcut")
        await mgr.handle_event("arrive", "ios_shortcut")
        tts.speak.assert_not_awaited()

    async def test_arrive_applies_pending_vibe_once(self):
        vibe_router = MagicMock()
        vibe_router.apply_pending_arrival = AsyncMock(
            return_value={"status": "ok", "plan": {"mode": "social"}}
        )
        mgr, _engine, _settings, _hue, _sonos, _tts, notifier = _make_manager(
            vibe_router=vibe_router,
        )
        await mgr.handle_event("leave", "ios_shortcut")
        notifier.emit_alert.reset_mock()

        await mgr.handle_event("arrive", "ios_shortcut")

        vibe_router.apply_pending_arrival.assert_awaited_once_with(
            source="arrival:ios_shortcut",
        )
        body = notifier.emit_alert.await_args.kwargs["body"]
        assert "staged vibe applied" in body
    async def test_arrive_while_home_still_clears_suppression(self):
        """A lost-state arrive must never leave the apartment suppressed."""
        mgr, engine, *_ = _make_manager()
        engine._external_off_detected = True  # e.g. Hue app armed it

        result = await mgr.handle_event("arrive", "ios_shortcut")

        assert result["changed"] is False
        assert engine._external_off_detected is False
        engine.reapply_current_mode.assert_not_awaited()

    async def test_unknown_event_rejected(self):
        mgr, *_ = _make_manager()
        result = await mgr.handle_event("hover", "ios_shortcut")
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Persistence restore
# ---------------------------------------------------------------------------

class TestRestore:
    async def test_load_state_rearms_suppression_when_away(self):
        since = datetime.now(timezone.utc).isoformat()
        settings = FakeSettings({
            AWAY_STATE_KEY: {"away": True, "since_utc": since, "source": "x"},
        })
        mgr, engine, *_ = _make_manager(settings=settings)

        await mgr.load_state()

        assert mgr.away is True
        assert engine._external_off_detected is True
        assert engine.armed_by == ["away_manager:restore"]

    async def test_load_state_noop_when_home(self):
        mgr, engine, *_ = _make_manager()
        await mgr.load_state()
        assert mgr.away is False
        assert engine._external_off_detected is False


# ---------------------------------------------------------------------------
# Real engine hooks
# ---------------------------------------------------------------------------

class TestEngineHooks:
    @pytest.fixture
    def engine(self):
        from backend.services.automation_engine import AutomationEngine
        hue = MagicMock()
        hue.connected = True
        hue_v2 = MagicMock()
        ws = MagicMock()
        ws.broadcast = AsyncMock()
        return AutomationEngine(hue=hue, hue_v2=hue_v2, ws_manager=ws)

    async def test_arm_away_suppression_idempotent_and_cleared_by_presence(
        self, engine,
    ):
        assert engine._external_off_detected is False
        engine.arm_away_suppression("geofence:test")
        assert engine._external_off_detected is True
        assert engine._away_hold is True
        engine.arm_away_suppression("geofence:test")  # idempotent
        assert engine._external_off_detected is True

        await engine.signal_presence("geofence:test")
        assert engine._external_off_detected is False
        assert engine._away_hold is False

    async def test_hard_hold_survives_residual_process_reports(self, engine):
        """The leak found live 2026-06-10: post-departure `working`
        heartbeats (foreground process lingers ~10 min) must NOT clear a
        geofence-armed suppression, must NOT actuate lights, and must NOT
        fire mode-change callbacks (music auto-play to an empty apartment).
        """
        engine._apply_mode = AsyncMock()
        callback = AsyncMock()
        engine.register_on_mode_change(callback)

        engine.arm_away_suppression("geofence:test")
        await engine.report_activity("working", source="process")

        assert engine._external_off_detected is True
        assert engine._away_hold is True
        engine._apply_mode.assert_not_awaited()
        callback.assert_not_awaited()

        # The working→idle transition at ~10 min must not re-light either
        # (this is the path that bypassed dedup via force_resend).
        await engine.report_activity("idle", source="process")
        engine._apply_mode.assert_not_awaited()
        callback.assert_not_awaited()
        assert engine._external_off_detected is True

    async def test_soft_suppression_still_cleared_by_activity(self, engine):
        """Hue-app path (_check_external_off) keeps its original
        semantics: a non-idle report clears the flag and resumes
        actuation."""
        engine._apply_mode = AsyncMock()
        engine._external_off_detected = True  # soft — no hold

        await engine.report_activity("working", source="process")

        assert engine._external_off_detected is False
        engine._apply_mode.assert_awaited_once()

    async def test_arm_invalidates_dedup_cache(self, engine):
        """Camera-walk-in release (geofence missed) must not dedup-skip
        the re-light against pre-departure cached values."""
        engine._last_applied_per_light = {"1": {"on": True, "bri": 200}}
        engine.arm_away_suppression("geofence:test")
        assert engine._last_applied_per_light == {}

    async def test_apply_mode_chokepoint_blocks_all_actuation(self, engine):
        """The 2026-06-10 live leak #2: the transit clear-revert (and any
        other direct _apply_mode caller) re-lit a suppressed apartment.
        _apply_mode itself must no-op while suppressed."""
        engine._apply_state = AsyncMock()
        engine._effect_manager.reconcile = AsyncMock()

        engine.arm_away_suppression("geofence:test")
        await engine._apply_mode("working", force_resend=True)
        engine._apply_state.assert_not_awaited()

        await engine.signal_presence("camera")
        await engine._apply_mode("working", force_resend=True)
        engine._apply_state.assert_awaited()

    async def test_transit_apply_gated_while_suppressed(self, engine):
        """Transit/desk-exit triggers are absence-shaped and churn while
        away (observed live: transit cycling ~70s post-LEAVE). The apply
        verb must no-op while suppressed — no bridge writes, no stamps."""
        engine.arm_away_suppression("geofence:test")
        await engine.apply_transit_override(
            {"1": {"on": True, "bri": 55}}, trigger="transit",
        )
        assert engine._transit_light_overrides == {}

    async def test_timeout_clear_override_gated_while_suppressed(self, engine):
        """pr-review block finding 2026-06-10: clear_override's idle branch
        calls _apply_time_based → _apply_state DIRECTLY (not _apply_mode),
        and run_loop fires clear_override(source='timeout_4h') BEFORE the
        external-off continue — a manual override expiring 4h into an away
        window re-lit the empty apartment. _apply_state must be gated too."""
        engine._apply_per_light = AsyncMock()
        engine._apply_uniform = AsyncMock()
        engine._effect_manager.reconcile = AsyncMock()
        await engine.set_manual_override("relax", source="api:test")
        engine._apply_per_light.reset_mock()
        engine._apply_uniform.reset_mock()

        engine.arm_away_suppression("geofence:test")
        engine._current_mode = "idle"  # the normal away state (PC idled)
        await engine.clear_override(source="timeout_4h")

        engine._apply_per_light.assert_not_awaited()
        engine._apply_uniform.assert_not_awaited()
        assert engine._external_off_detected is True
        assert engine._away_hold is True

    async def test_user_override_releases_suppression(self, engine):
        """Explicit user mode pick while away = deliberate remote
        actuation (dog-sitter case) — releases the hold and renders."""
        engine._apply_mode = AsyncMock()
        engine.arm_away_suppression("geofence:test")

        await engine.set_manual_override("social", source="api:1.2.3.4")

        assert engine._external_off_detected is False
        assert engine._away_hold is False
        engine._apply_mode.assert_awaited_once_with("social", force_resend=True)

    async def test_autonomous_override_blocked_while_suppressed(self, engine):
        """Autonomous setters must not pierce the suppression via direct
        set_manual_override calls (run_loop is gated; this guards the
        rest)."""
        engine._apply_mode = AsyncMock()
        engine.arm_away_suppression("geofence:test")

        await engine.set_manual_override("relax", source="ambient_relax")

        assert engine._manual_override is False
        assert engine._external_off_detected is True
        assert engine._away_hold is True
        engine._apply_mode.assert_not_awaited()

    async def test_reapply_current_mode_uses_effective_mode_and_forces(
        self, engine,
    ):
        engine._apply_mode = AsyncMock()
        await engine.set_manual_override("relax", source="api:test")
        engine._apply_mode.reset_mock()

        await engine.reapply_current_mode(force_resend=True)

        engine._apply_mode.assert_awaited_once_with("relax", force_resend=True)
