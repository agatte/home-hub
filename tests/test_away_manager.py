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
        engine.arm_away_suppression("geofence:test")  # idempotent
        assert engine._external_off_detected is True

        await engine.signal_presence("geofence:test")
        assert engine._external_off_detected is False

    async def test_reapply_current_mode_uses_effective_mode_and_forces(
        self, engine,
    ):
        engine._apply_mode = AsyncMock()
        await engine.set_manual_override("relax", source="api:test")
        engine._apply_mode.reset_mock()

        await engine.reapply_current_mode(force_resend=True)

        engine._apply_mode.assert_awaited_once_with("relax", force_resend=True)
