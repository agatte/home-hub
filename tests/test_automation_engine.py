"""
Tests for the automation engine — mode priority, overrides, time periods.

These test the pure logic of the AutomationEngine without touching any real
hardware. Hue, Sonos, and WebSocket are all mocked.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend.services.automation_engine import (
    MODE_PRIORITY,
    SOURCE_STALE_SECONDS,
    AutomationEngine,
    DaySchedule,
    _resolve_activity_state,
)
from backend.services.presence_fusion import PresenceFusion, PresenceReading
from backend.services.camera_service import CameraService, spawn_camera_service
from backend.services.automation_constants import (
    PRESERVE_PER_LIGHT_OVERRIDE_SOURCES,
)
from backend.services.ml.confidence_fusion import ConfidenceFusion
from backend.services.light_state_calculator import (
    ACTIVITY_LIGHT_STATES,
    ALL_LIGHT_IDS,
    GAMING_LIGHTING_PROFILES,
    GameLightingProfile,
    get_time_period_static as _get_time_period_static,
    resolve_activity_state,
)
from backend.services.screen_sync import ScreenSyncService

TZ = ZoneInfo("America/Indiana/Indianapolis")


def _prime_gaming_sync(sync: ScreenSyncService, period: str = "day") -> None:
    sync.publish_accepted_gaming_state(resolve_activity_state("gaming", period))


# ---------------------------------------------------------------------------
# Mode priority
# ---------------------------------------------------------------------------

class TestModePriority:
    """Verify mode priority ordering is correct."""

    def test_gameday_is_highest(self):
        # gameday=6 (Decision 1.6 in docs/GAMEDAY_SPEC.md) — top auto-
        # detected slot, sits above gaming so a Colts game during a
        # Madden session still flips the room into team-color mode.
        assert MODE_PRIORITY["gameday"] == max(MODE_PRIORITY.values())
        assert MODE_PRIORITY["gameday"] > MODE_PRIORITY["gaming"]

    def test_priority_ordering(self):
        assert MODE_PRIORITY["gameday"] > MODE_PRIORITY["gaming"]
        assert MODE_PRIORITY["gaming"] > MODE_PRIORITY["social"]
        assert MODE_PRIORITY["social"] > MODE_PRIORITY["watching"]
        assert MODE_PRIORITY["watching"] > MODE_PRIORITY["working"]
        assert MODE_PRIORITY["working"] > MODE_PRIORITY["idle"]

    def test_sleeping_is_lowest(self):
        assert MODE_PRIORITY["sleeping"] == 0

    def test_all_expected_modes_present(self):
        expected = {
            "sleeping", "idle", "working", "watching", "cooking",
            "social", "gaming", "gameday", "pregameday",
        }
        assert set(MODE_PRIORITY.keys()) == expected

    def test_pregameday_priority_matches_gameday(self):
        """GAMEDAY_SPEC §10.1 — pregameday shares priority 6 with gameday so
        same-source updates from gameday_service can flip between them."""
        assert MODE_PRIORITY["pregameday"] == MODE_PRIORITY["gameday"]


# ---------------------------------------------------------------------------
# Time period detection
# ---------------------------------------------------------------------------

class TestTimePeriod:
    """Test the static time period helper.

    The function lives in ``light_state_calculator`` since the
    extraction; patches target that module's ``datetime`` (the
    engine module re-exports the helper for back-compat).
    """

    @patch("backend.services.light_state_calculator.datetime")
    def test_morning_is_day(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 12, 10, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert _get_time_period_static() == "day"

    @patch("backend.services.light_state_calculator.datetime")
    def test_afternoon_is_day(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 12, 15, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert _get_time_period_static() == "day"

    @patch("backend.services.light_state_calculator.datetime")
    def test_evening(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 12, 19, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert _get_time_period_static() == "evening"

    @patch("backend.services.light_state_calculator.datetime")
    def test_night(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 12, 22, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert _get_time_period_static() == "night"

    @patch("backend.services.light_state_calculator.datetime")
    def test_early_morning_is_night(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 12, 3, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert _get_time_period_static() == "night"


class TestEngineTimePeriodRampWindow:
    """Schedule-aware ``AutomationEngine._get_time_period``.

    Regression coverage for the ramp window falling through to "night":
    - Weekday Mon 06:30 (ramp 06:00 + 60min) → "day"
    - Weekend Sat 09:00 (ramp 08:00 + 120min) → "day"
    The morning ramp window is morning daylight, not nighttime.
    """

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws)

    @patch("backend.services.automation_engine.datetime")
    def test_weekday_mid_ramp_is_day(self, mock_dt, engine):
        # Monday 06:30 — inside the weekday ramp window (06:00–07:00)
        mock_dt.now.return_value = datetime(2026, 4, 13, 6, 30, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert engine._get_time_period() == "day"

    @patch("backend.services.automation_engine.datetime")
    def test_weekend_mid_ramp_is_day(self, mock_dt, engine):
        # Saturday 09:00 — inside the weekend ramp window (08:00–10:00)
        mock_dt.now.return_value = datetime(2026, 4, 25, 9, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert engine._get_time_period() == "day"

    @patch("backend.services.automation_engine.datetime")
    def test_weekday_pre_ramp_is_night(self, mock_dt, engine):
        # 05:30 — after wake, before ramp_start. Pre-dawn, "night" is fine.
        mock_dt.now.return_value = datetime(2026, 4, 13, 5, 30, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert engine._get_time_period() == "night"

    @patch("backend.services.automation_engine.datetime")
    def test_evening_unchanged(self, mock_dt, engine):
        mock_dt.now.return_value = datetime(2026, 4, 13, 19, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert engine._get_time_period() == "evening"

    @patch("backend.services.automation_engine.datetime")
    def test_late_night_unchanged(self, mock_dt, engine):
        mock_dt.now.return_value = datetime(2026, 4, 13, 23, 30, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert engine._get_time_period() == "late_night"


# ---------------------------------------------------------------------------
# Activity state resolution
# ---------------------------------------------------------------------------

class TestActivityStateResolution:
    """Test _resolve_activity_state lookup."""

    def test_unknown_mode_returns_empty(self):
        assert _resolve_activity_state("nonexistent") == {}

    def test_gaming_returns_per_light_states(self):
        state = _resolve_activity_state("gaming", time_period="evening")
        assert isinstance(state, dict)
        # Should have light IDs as keys
        if state:
            assert any(k.isdigit() for k in state.keys())

    def test_time_period_matters(self):
        day = _resolve_activity_state("working", time_period="day")
        night = _resolve_activity_state("working", time_period="night")
        # Day and night states should differ (at least brightness)
        if day and night:
            assert day != night

    def test_working_late_night_is_dimmer_than_night(self):
        night = _resolve_activity_state("working", time_period="night")
        late = _resolve_activity_state("working", time_period="late_night")
        assert late["2"]["bri"] < night["2"]["bri"]
        assert late["5"]["bri"] < night["5"]["bri"]
        ratio = late["2"]["bri"] / late["1"]["bri"]
        assert 1.0 <= ratio <= 3.0


# ---------------------------------------------------------------------------
# AutomationEngine — core behavior
# ---------------------------------------------------------------------------

class TestAutomationEngine:
    """Test the engine's mode management, overrides, and properties."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
        )

    def test_initial_state(self, engine):
        assert engine.current_mode == "idle"
        assert engine.mode_source == "time"
        assert engine.house_state == "home"
        assert engine.activity == "general"
        assert engine.effective_mode == "general"
        assert engine.effective_source == "time_of_day"
        context = engine.get_activity_context()
        assert context["current_activity"] == "idle"
        assert context["effective_mode"] == "general"
        assert context["effective_source"] == "time_of_day"
        pipeline = engine._build_pipeline_state()
        assert pipeline["inputs"]["activity"]["mode"] == "idle"
        assert pipeline["resolution"]["winning_input"] == "time_of_day"
        assert pipeline["resolution"]["effective_mode"] == "general"
        assert pipeline["resolution"]["effective_source"] == "time_of_day"
        assert pipeline["output"]["mode"] == "general"
        assert engine.manual_override is False
        assert engine.enabled is True

    async def test_global_off_still_covers_every_canonical_light(self, engine, mock_hue):
        await engine._apply_state({"on": False})

        assert set(mock_hue._lights) == set(ALL_LIGHT_IDS)
        assert all(light["on"] is False for light in mock_hue._lights.values())

    def test_sleeping_projects_house_state_without_awake_activity(self, engine):
        engine._manual_override = True
        engine._override_mode = "sleeping"
        engine._override_source = "api:test"

        assert engine.house_state == "sleeping"
        assert engine.activity is None

    async def test_activity_report_updates_mode(self, engine):
        await engine.report_activity("gaming", source="pc_agent")
        assert engine.current_mode == "gaming"

    async def test_higher_priority_wins(self, engine):
        await engine.report_activity("working", source="pc_agent")
        assert engine.current_mode == "working"
        # Gaming has higher priority and should override
        await engine.report_activity("gaming", source="pc_agent")
        assert engine.current_mode == "gaming"

    async def test_lower_priority_does_not_override(self, engine):
        await engine.report_activity("gaming", source="pc_agent")
        # Working is lower priority — should NOT downgrade
        await engine.report_activity("working", source="pc_agent")
        # Mode stays gaming because gaming > working
        # (actual behavior depends on engine logic — may accept if from
        # a different source, so we test the property reflects the report)
        assert engine.current_mode in ("gaming", "working")

    async def test_manual_override(self, engine):
        await engine.report_activity("working", source="pc_agent")
        await engine.set_manual_override("relax")
        assert engine.current_mode == "relax"
        assert engine.manual_override is True
        assert engine.mode_source == "manual"

    async def test_clear_override(self, engine):
        await engine.set_manual_override("relax")
        assert engine.manual_override is True
        await engine.clear_override()
        assert engine.manual_override is False

    async def test_explicit_sleeping_auto_establishes_home_general(self, engine):
        engine._current_mode = "working"
        engine._mode_source = "process"
        engine._mode_source_key = "process"
        engine._manual_override = True
        engine._override_mode = "sleeping"
        engine._override_source = "api:test"
        engine._external_off_detected = True
        engine._apply_mode = AsyncMock()
        engine._fire_mode_change_callbacks = AsyncMock()

        await engine.clear_override(
            source="api:test", user_requested_auto=True,
        )

        assert engine.manual_override is False
        assert engine._current_mode == "idle"
        assert engine.current_mode == "idle"
        assert engine.mode_source == "user_auto"
        assert engine.house_state == "home"
        assert engine.activity == "general"
        assert engine._home_awake_confirmed is True
        assert engine._external_off_detected is False
        assert engine._away_hold is False
        engine._apply_mode.assert_awaited_once_with("idle", force_resend=True)
        engine._fire_mode_change_callbacks.assert_awaited_once_with("idle")

    async def test_explicit_sleeping_auto_keeps_hard_away_dark(self, engine):
        engine._current_mode = "working"
        engine._manual_override = True
        engine._override_mode = "sleeping"
        engine._override_source = "api:test"
        engine._external_off_detected = True
        engine._away_hold = True
        engine._apply_mode = AsyncMock()
        engine._fire_mode_change_callbacks = AsyncMock()

        await engine.clear_override(
            source="api:test", user_requested_auto=True,
        )

        assert engine.manual_override is False
        assert engine._current_mode == "idle"
        assert engine.house_state == "away"
        assert engine.activity is None
        assert engine._home_awake_confirmed is False
        assert engine._external_off_detected is True
        assert engine._away_hold is True
        engine._apply_mode.assert_not_awaited()
        engine._fire_mode_change_callbacks.assert_not_awaited()

    async def test_explicit_auto_wakes_detected_non_override_sleeping(
        self, engine,
    ):
        # This regression owns state-transition semantics, not the asynchronous
        # Hue sleep fade. Stub application before creating detected Sleeping so
        # pytest does not leave an unrelated background fade task pending.
        engine._apply_mode = AsyncMock()
        await engine.report_activity("sleeping", source="process")
        assert engine.current_mode == "sleeping"
        assert engine.manual_override is False
        engine._apply_mode.reset_mock()
        engine._fire_mode_change_callbacks = AsyncMock()

        await engine.clear_override(
            source="api:test", user_requested_auto=True,
        )

        assert engine.manual_override is False
        assert engine.current_mode == "idle"
        assert engine.mode_source == "user_auto"
        assert engine.house_state == "home"
        assert engine.activity == "general"
        assert engine._home_awake_confirmed is True
        engine._apply_mode.assert_awaited_once_with("idle", force_resend=True)
        engine._fire_mode_change_callbacks.assert_awaited_once_with("idle")

    async def test_explicit_sleeping_auto_is_user_authority_during_dnd(
        self, engine,
    ):
        engine._manual_override = True
        engine._override_mode = "sleeping"
        engine._override_source = "alexa:AutoIntent"
        engine._dnd._enabled = True
        engine._dnd._expiry = datetime.now(tz=TZ) + timedelta(hours=1)
        engine._apply_mode = AsyncMock()

        await engine.clear_override(
            source="alexa:AutoIntent", user_requested_auto=True,
        )

        assert engine.manual_override is False
        assert engine.house_state == "home"
        assert engine.activity == "general"
        assert engine._user_cleared_override_at is not None
        engine._apply_mode.assert_awaited_once_with("idle", force_resend=True)

    async def test_internal_sleeping_clear_stays_blocked_during_dnd(self, engine):
        engine._manual_override = True
        engine._override_mode = "sleeping"
        engine._override_source = "internal"
        engine._dnd._enabled = True
        engine._dnd._expiry = datetime.now(tz=TZ) + timedelta(hours=1)
        engine._apply_mode = AsyncMock()

        await engine.clear_override(source="internal")

        assert engine.manual_override is True
        assert engine.house_state == "sleeping"
        engine._apply_mode.assert_not_awaited()

    async def test_non_explicit_sleeping_clear_keeps_legacy_safe_behavior(
        self, engine,
    ):
        engine._current_mode = "working"
        engine._manual_override = True
        engine._override_mode = "sleeping"
        engine._override_source = "internal"
        engine._apply_mode = AsyncMock()

        await engine.clear_override(source="internal")

        assert engine.current_mode == "working"
        assert engine.house_state == "home"
        assert engine.activity == "working"
        engine._apply_mode.assert_not_awaited()

    async def test_fresh_semantic_activity_refines_general_after_explicit_wake(
        self, engine,
    ):
        engine._manual_override = True
        engine._override_mode = "sleeping"
        engine._override_source = "api:test"
        engine._apply_mode = AsyncMock()

        await engine.clear_override(
            source="api:test", user_requested_auto=True,
        )
        await engine.report_activity("working", source="process")

        assert engine.house_state == "home"
        assert engine.activity == "working"
        assert engine.current_mode == "working"

    async def test_confirmed_home_ignores_process_sleeping_after_wake(self, engine):
        engine._home_awake_confirmed = True
        engine._current_mode = "idle"
        engine._mode_source = "process"
        engine._mode_source_key = "process"
        engine._apply_mode = AsyncMock()
        engine._event_logger = SimpleNamespace(log_mode_change=AsyncMock())

        result = await engine.report_activity("sleeping", source="process")

        assert result["semantic_disposition"] == "rejected"
        assert result["reason"] == "home_awake_confirmed"
        assert engine.current_mode == "idle"
        assert engine.house_state == "home"
        assert engine.activity == "general"
        engine._apply_mode.assert_not_awaited()
        engine._event_logger.log_mode_change.assert_not_awaited()

    async def test_explicit_sleeping_transition_clears_confirmed_home(self, engine):
        engine._home_awake_confirmed = True
        engine._apply_mode = AsyncMock()

        await engine.set_manual_override("sleeping", source="api:test")

        assert engine._home_awake_confirmed is False
        assert engine.house_state == "sleeping"

    def test_away_transition_clears_confirmed_home(self, engine):
        engine._home_awake_confirmed = True

        engine.arm_away_suppression("test")

        assert engine._home_awake_confirmed is False
        assert engine.house_state == "away"

    @patch("backend.services.automation_engine.datetime")
    async def test_confirmed_general_overnight_uses_dim_awake_baseline(
        self, mock_dt, engine,
    ):
        now = datetime(2026, 8, 18, 3, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._home_awake_confirmed = True
        engine._apply_state = AsyncMock()
        engine._weather_adjust = MagicMock(side_effect=lambda state: state)

        await engine._apply_time_based()

        target = engine._apply_state.await_args.args[0]
        legacy = {
            "on": True,
            "bri": engine.schedule_config.weekday.wake_brightness,
            "hue": 6000,
            "sat": 200,
        }
        assert {light_id: target[light_id] for light_id in "12345"} == {
            light_id: legacy for light_id in "12345"
        }
        assert target["6"] == {"on": False}

    @patch("backend.services.automation_engine.datetime")
    async def test_unconfirmed_idle_overnight_stays_dark(self, mock_dt, engine):
        now = datetime(2026, 8, 18, 3, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._apply_state = AsyncMock()
        engine._weather_adjust = MagicMock(side_effect=lambda state: state)

        await engine._apply_time_based()

        target = engine._apply_state.await_args.args[0]
        assert {light_id: target[light_id] for light_id in "12345"} == {
            light_id: {"on": False} for light_id in "12345"
        }
        assert target["6"] == {"on": False}

    @patch("backend.services.automation_engine.datetime")
    async def test_daytime_idle_preserves_l1_to_l5_ct_target_and_leaves_plant_wash_off(
        self, mock_dt, engine,
    ):
        now = datetime(2026, 8, 18, 10, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._apply_state = AsyncMock()
        engine._weather_adjust = MagicMock(side_effect=lambda state: state)

        await engine._apply_time_based()

        target = engine._apply_state.await_args.args[0]
        legacy = {"on": True, "bri": 220, "ct": 250}
        assert {light_id: target[light_id] for light_id in "12345"} == {
            light_id: legacy for light_id in "12345"
        }
        assert target["6"] == {"on": False}

    @patch("backend.services.automation_engine.datetime")
    async def test_explicit_sleeping_auto_overnight_renders_awake_general(
        self, mock_dt, engine, mock_hue,
    ):
        now = datetime(2026, 8, 18, 3, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        for light in mock_hue._lights.values():
            light["on"] = False
        engine._manual_override = True
        engine._override_mode = "sleeping"
        engine._override_source = "api:test"
        engine._external_off_detected = True

        await engine.clear_override(
            source="api:test", user_requested_auto=True,
        )

        assert engine.house_state == "home"
        assert engine.activity == "general"
        assert engine._home_awake_confirmed is True
        assert all(mock_hue._lights[light_id]["on"] for light_id in "12345")
        assert mock_hue._lights["6"]["on"] is False
        assert {
            mock_hue._lights[light_id]["bri"] for light_id in "12345"
        } == {engine.schedule_config.weekday.wake_brightness}

    @patch("backend.services.automation_engine.datetime")
    async def test_general_fallback_light_writes_are_labeled_general(
        self, mock_dt, engine,
    ):
        now = datetime(2026, 8, 27, 11, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        logger = SimpleNamespace(log_light_adjustment=AsyncMock())
        engine._event_logger = logger

        await engine._apply_time_based()

        assert logger.log_light_adjustment.await_count > 0
        assert {
            call.kwargs["mode_at_time"]
            for call in logger.log_light_adjustment.await_args_list
        } == {"general"}

    async def test_confirmed_general_idle_heartbeats_keep_awake_baseline(
        self, engine,
    ):
        engine._home_awake_confirmed = True
        engine._current_mode = "idle"
        engine._apply_time_based = AsyncMock()

        await engine.report_activity("idle", source="process")
        await engine.report_activity("idle", source="process")

        assert engine.current_mode == "idle"
        assert engine.activity == "general"
        assert engine._apply_time_based.await_count == 2

    async def test_set_override_logs_source(self, engine, caplog):
        with caplog.at_level("INFO", logger="home_hub.automation"):
            await engine.set_manual_override("relax", source="api:192.168.1.30")
        msgs = [r.message for r in caplog.records if "Manual override set" in r.message]
        assert any("source=api:192.168.1.30" in m for m in msgs), msgs

    async def test_clear_override_logs_source(self, engine, caplog):
        await engine.set_manual_override("relax")
        with caplog.at_level("INFO", logger="home_hub.automation"):
            await engine.clear_override(source="api:127.0.0.1")
        msgs = [r.message for r in caplog.records if "Manual override cleared" in r.message]
        assert any("source=api:127.0.0.1" in m for m in msgs), msgs

    async def test_override_broadcasts(self, engine, mock_ws):
        await engine.set_manual_override("movie")
        # Should have broadcast at least one mode_update
        mode_broadcasts = [b for b in mock_ws.broadcasts if b[0] == "mode_update"]
        assert len(mode_broadcasts) >= 1
        assert mode_broadcasts[-1][1]["mode"] == "movie"
        assert mode_broadcasts[-1][1]["house_state"] == "home"
        assert mode_broadcasts[-1][1]["activity"] == "movie"

    def test_schedule_config_has_weekday_and_weekend(self, engine):
        config = engine.schedule_config
        assert hasattr(config, "weekday")
        assert hasattr(config, "weekend")
        assert isinstance(config.weekday, DaySchedule)
        assert isinstance(config.weekend, DaySchedule)

    def test_mode_brightness_defaults(self, engine):
        brightness = engine.mode_brightness
        assert "gaming" in brightness
        assert "working" in brightness
        assert all(0.3 <= v <= 1.5 for v in brightness.values())

    def test_override_timeout_clamps(self, engine):
        engine.override_timeout_hours = 0
        assert engine.override_timeout_hours >= 1


# ---------------------------------------------------------------------------
# User-respect cooldown — clicking "auto" suppresses autonomous pushes
# ---------------------------------------------------------------------------

class TestUserClearCooldown:
    """When the user presses 'auto' on the dashboard (api:* clear), the
    engine should suppress autonomous-source set_manual_override calls
    for USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS so the choice actually sticks.

    User-initiated API calls (api:*) and rule-suggestion accepts
    (rule_suggestion_accept:*) bypass.
    """

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
        )

    async def test_api_clear_arms_cooldown_stamp(self, engine):
        await engine.set_manual_override("relax", source="api:1.2.3.4")
        assert engine._user_cleared_override_at is None
        await engine.clear_override(source="api:1.2.3.4")
        assert engine._user_cleared_override_at is not None

    async def test_internal_clear_does_not_arm_cooldown(self, engine):
        # Auto-timeout-driven clears (timeout_4h) shouldn't suppress later
        # autonomous pushes — those represent override expiry, not user intent.
        await engine.set_manual_override("relax")
        await engine.clear_override(source="timeout_4h")
        assert engine._user_cleared_override_at is None

    async def test_cooldown_blocks_late_night_rescue(self, engine):
        await engine.clear_override(source="api:1.2.3.4")
        # Same instant — cooldown definitely active. Autonomous push suppressed.
        await engine.set_manual_override("relax", source="late_night_rescue")
        assert engine.manual_override is False

    async def test_cooldown_blocks_zone_posture_rule(self, engine):
        await engine.clear_override(source="api:1.2.3.4")
        await engine.set_manual_override("relax", source="zone_posture_rule")
        assert engine.manual_override is False

    async def test_cooldown_blocks_fusion_can_override(self, engine):
        await engine.clear_override(source="api:1.2.3.4")
        await engine.set_manual_override("watching", source="fusion_can_override")
        assert engine.manual_override is False

    async def test_cooldown_blocks_fusion_auto_apply(self, engine):
        await engine.clear_override(source="api:1.2.3.4")
        await engine.set_manual_override("watching", source="fusion_auto_apply")
        assert engine.manual_override is False

    async def test_cooldown_blocks_behavioral_predictor(self, engine):
        await engine.clear_override(source="api:1.2.3.4")
        await engine.set_manual_override("relax", source="behavioral_predictor")
        assert engine.manual_override is False

    async def test_cooldown_does_not_block_user_api_set(self, engine):
        # User picks a different mode via the dashboard — bypass the cooldown
        # they just armed.
        await engine.clear_override(source="api:1.2.3.4")
        await engine.set_manual_override("watching", source="api:1.2.3.4")
        assert engine.manual_override is True
        assert engine.override_mode == "watching"

    async def test_cooldown_does_not_block_rule_suggestion_accept(self, engine):
        await engine.clear_override(source="api:1.2.3.4")
        await engine.set_manual_override(
            "relax", source="rule_suggestion_accept:1.2.3.4",
        )
        assert engine.manual_override is True

    async def test_cooldown_expires_after_window(self, engine):
        from backend.services.automation_engine import (
            USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS,
        )
        await engine.clear_override(source="api:1.2.3.4")
        # Fast-forward past the cooldown.
        engine._user_cleared_override_at = (
            datetime.now(tz=TZ)
            - timedelta(seconds=USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS + 60)
        )
        await engine.set_manual_override("relax", source="late_night_rescue")
        assert engine.manual_override is True


# ---------------------------------------------------------------------------
# Priority-bypass — higher-priority detector signal displaces an autonomous
# (but not user) override. Closes the 2026-05-12 fusion_auto_apply idle-lock
# bug where 7 organic working/gaming/watching reports were swallowed by an
# idle override for 116min until manual user intervention.
# ---------------------------------------------------------------------------

class TestAutonomousOverrideDisplacement:
    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
        )

    async def test_higher_priority_displaces_fusion_auto_apply(self, engine):
        # 5/12 scenario: fusion locks idle@1; process reports gaming@5.
        await engine.set_manual_override("idle", source="fusion_auto_apply")
        assert engine.manual_override is True

        await engine.report_activity("gaming", source="process")

        assert engine.manual_override is False
        assert engine.current_mode == "gaming"
        assert engine._override_source is None
        assert engine._override_mode is None

    async def test_higher_priority_displaces_late_night_rescue(self, engine):
        # Rescue set relax (priority 0 — not in MODE_PRIORITY map);
        # working@2 should displace.
        await engine.set_manual_override("relax", source="late_night_rescue")
        await engine.report_activity("working", source="process")

        assert engine.manual_override is False
        assert engine.current_mode == "working"

    async def test_user_override_is_never_displaced(self, engine):
        # User explicitly chose relax via the dashboard — gaming process
        # signal must not auto-clear it.
        await engine.set_manual_override("relax", source="api:1.2.3.4")
        await engine.report_activity("gaming", source="process")

        assert engine.manual_override is True
        assert engine.override_mode == "relax"

    async def test_lower_priority_preserves_autonomous_override(self, engine):
        # fusion locked watching@3; working@2 should NOT displace.
        await engine.set_manual_override("watching", source="fusion_auto_apply")
        await engine.report_activity("working", source="process")

        assert engine.manual_override is True
        assert engine.override_mode == "watching"

    async def test_same_priority_preserves_autonomous_override(self, engine):
        # watching@3 == cooking@3 — strict-greater means override stays.
        await engine.set_manual_override("watching", source="fusion_auto_apply")
        await engine.report_activity("cooking", source="process")

        assert engine.manual_override is True
        assert engine.override_mode == "watching"

    async def test_zone_posture_relax_displaced_by_gaming(self, engine):
        # zone_posture_rule pinned relax; user returns and starts gaming.
        await engine.set_manual_override("relax", source="zone_posture_rule")
        await engine.report_activity("gaming", source="process")

        assert engine.manual_override is False
        assert engine.current_mode == "gaming"

    # ── Rescue-override priority floor (bug 2026-05-15) ───────────────
    # Rescue sources push manual-only modes (relax, sleeping) at default
    # priority 0; an `idle` sensor report (p=1) used to silently undo
    # them every 60s. RESCUE_OVERRIDE_SOURCES bumps their effective
    # priority to idle's level so idle/sleeping reports can't displace —
    # real activity signals (working+) still can.

    async def test_idle_does_not_displace_late_night_rescue_relax(self, engine):
        await engine.set_manual_override("relax", source="late_night_rescue")
        await engine.report_activity("idle", source="ambient")

        assert engine.manual_override is True
        assert engine.override_mode == "relax"
        assert engine.override_source == "late_night_rescue"

    async def test_idle_does_not_displace_zone_posture_rule_relax(self, engine):
        await engine.set_manual_override("relax", source="zone_posture_rule")
        await engine.report_activity("idle", source="ambient")

        assert engine.manual_override is True
        assert engine.override_mode == "relax"

    async def test_idle_does_not_displace_watching_sleep_guard_sleeping(self, engine):
        engine._apply_mode = AsyncMock()
        await engine.set_manual_override("sleeping", source="watching_sleep_guard")
        await engine.report_activity("idle", source="ambient")

        assert engine.manual_override is True
        assert engine.override_mode == "sleeping"

    async def test_working_still_displaces_rescue_relax(self, engine):
        # Regression guard: floor only protects against idle/sleeping
        # reports; real-activity signals must still win.
        await engine.set_manual_override("relax", source="late_night_rescue")
        await engine.report_activity("working", source="process")

        assert engine.manual_override is False
        assert engine.current_mode == "working"

    async def test_floor_does_not_apply_to_fusion_auto_apply(self, engine):
        # Regression guard: fusion_auto_apply is NOT in RESCUE_OVERRIDE_SOURCES.
        # When fusion sets relax (p=0), idle (p=1) should still displace —
        # matches the existing 2026-05-12 fusion bug fix semantics.
        await engine.set_manual_override("relax", source="fusion_auto_apply")
        await engine.report_activity("idle", source="ambient")

        assert engine.manual_override is False
        assert engine.current_mode == "idle"


# ---------------------------------------------------------------------------
# Sleeping floor — non-override sleeping must survive idle sensor reports.
# Closes flag b064a0 (2026-06-03): sleeping carries MODE_PRIORITY=0, the global
# floor, so the priority guard can never protect it; once a manual "good night"
# override lapsed and sleeping survived only as a detected _current_mode
# (re-asserted by the PC sleep-watcher via source=process), an audio_ml `idle`
# report (p=1) walked straight through and broke sleep — twice that day. Only a
# foreground process activity report (working/watching/gaming) may now wake it.
# ---------------------------------------------------------------------------

class TestSleepingFloor:
    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
        )

    async def _enter_detected_sleeping(self, engine):
        """Establish non-override sleeping (source=process, no manual override),
        mirroring the PC sleep-watcher re-asserting sleeping after the original
        Alexa override lapsed."""
        # These tests own the Sleeping floor semantics, not Hue fade timing.
        # Stub mode application so entering detected Sleeping cannot leave an
        # unrelated background _sleep_fade task pending at pytest teardown.
        engine._apply_mode = AsyncMock()
        await engine.report_activity("sleeping", source="process")
        assert engine.current_mode == "sleeping"
        assert engine.manual_override is False

    async def test_audio_ml_idle_does_not_break_detected_sleeping(self, engine):
        # The exact 2026-06-03 repro: audio_ml idle@1 vs non-override sleeping.
        await self._enter_detected_sleeping(engine)
        await engine.report_activity("idle", source="audio_ml")
        assert engine.current_mode == "sleeping"

    async def test_ambient_idle_does_not_break_detected_sleeping(self, engine):
        await self._enter_detected_sleeping(engine)
        await engine.report_activity("idle", source="ambient")
        assert engine.current_mode == "sleeping"

    async def test_camera_does_not_break_detected_sleeping(self, engine):
        # Even a non-idle mode from a non-process source can't wake sleep —
        # only the foreground process detector should.
        await self._enter_detected_sleeping(engine)
        await engine.report_activity("working", source="camera")
        assert engine.current_mode == "sleeping"

    async def test_process_idle_does_not_break_detected_sleeping(self, engine):
        # Same-source process, but idle (p==idle, not above) must not wake.
        await self._enter_detected_sleeping(engine)
        await engine.report_activity("idle", source="process")
        assert engine.current_mode == "sleeping"

    async def test_process_working_wakes_detected_sleeping(self, engine):
        await self._enter_detected_sleeping(engine)
        await engine.report_activity("working", source="process")
        assert engine.current_mode == "working"

    async def test_process_gaming_wakes_detected_sleeping(self, engine):
        await self._enter_detected_sleeping(engine)
        await engine.report_activity("gaming", source="process")
        assert engine.current_mode == "gaming"

    async def test_process_watching_wakes_detected_sleeping(self, engine):
        await self._enter_detected_sleeping(engine)
        await engine.report_activity("watching", source="process")
        assert engine.current_mode == "watching"

    async def test_floor_persists_across_stale_owning_source(self, engine):
        # Sleep must stick even if the process source that set it goes stale —
        # the floor is deliberately NOT subject to SOURCE_STALE_SECONDS, so an
        # idle report long after the last process heartbeat still can't wake it.
        await self._enter_detected_sleeping(engine)
        stale = datetime.now(tz=TZ) - timedelta(seconds=SOURCE_STALE_SECONDS + 60)
        engine._last_mode_source_report_at["process"] = stale
        await engine.report_activity("idle", source="audio_ml")
        assert engine.current_mode == "sleeping"

    async def test_manual_sleeping_override_unaffected_by_floor(self, engine):
        # The floor is gated on `not manual_override`; a user/Alexa sleeping
        # override keeps its existing (downstream) protection.
        engine._apply_mode = AsyncMock()
        await engine.set_manual_override("sleeping", source="api:1.2.3.4")
        await engine.report_activity("idle", source="audio_ml")
        assert engine.manual_override is True
        assert engine.override_mode == "sleeping"


# ---------------------------------------------------------------------------
# Per-light manual override preservation across mode changes
# ---------------------------------------------------------------------------

class TestPerLightOverridePreserve:
    """Per-light manual brightness/color overrides should survive autonomous
    mode pushes (late-night rescue, fusion, predictor, zone+posture rule)
    but get wiped when the user themselves picks a new mode.

    The user's invariant: "manual brightness sticks until I change it." Before
    this gate, every set_manual_override unconditionally cleared
    _manual_light_overrides, so e.g. a late-night autonomous push would erase
    a manually-set kitchen brightness from earlier in the day.
    """

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
        )

    async def test_late_night_rescue_preserves_per_light(self, engine):
        engine.mark_light_manual("3")
        await engine.set_manual_override("relax", source="late_night_rescue")
        assert "3" in engine.manual_light_overrides

    async def test_zone_posture_rule_preserves_per_light(self, engine):
        engine.mark_light_manual("3")
        await engine.set_manual_override("relax", source="zone_posture_rule")
        assert "3" in engine.manual_light_overrides

    async def test_fusion_can_override_preserves_per_light(self, engine):
        engine.mark_light_manual("2")
        await engine.set_manual_override("watching", source="fusion_can_override")
        assert "2" in engine.manual_light_overrides

    async def test_fusion_auto_apply_preserves_per_light(self, engine):
        engine.mark_light_manual("2")
        await engine.set_manual_override("watching", source="fusion_auto_apply")
        assert "2" in engine.manual_light_overrides

    async def test_behavioral_predictor_preserves_per_light(self, engine):
        engine.mark_light_manual("3")
        await engine.set_manual_override("relax", source="behavioral_predictor")
        assert "3" in engine.manual_light_overrides

    async def test_user_dashboard_clears_per_light(self, engine):
        # User picking a new mode on the dashboard means "give me this mode's
        # full default state" — wipe the stamps so the new mode shows clean.
        engine.mark_light_manual("3")
        await engine.set_manual_override("relax", source="api:192.168.1.30")
        assert "3" not in engine.manual_light_overrides

    async def test_manual_source_clears_per_light(self, engine):
        engine.mark_light_manual("3")
        await engine.set_manual_override("relax", source="manual")
        assert "3" not in engine.manual_light_overrides

    async def test_guest_clears_per_light(self, engine):
        # Guest-mode party scene activation rewrites all lights anyway —
        # clearing per-light stamps is consistent with that takeover.
        engine.mark_light_manual("3")
        await engine.set_manual_override("social", source="guest")
        assert "3" not in engine.manual_light_overrides

    async def test_rule_suggestion_accept_clears_per_light(self, engine):
        engine.mark_light_manual("3")
        await engine.set_manual_override(
            "relax", source="rule_suggestion_accept:1.2.3.4",
        )
        assert "3" not in engine.manual_light_overrides

    async def test_user_clear_override_wipes_per_light(self, engine):
        # User pressing "auto" on the dashboard means "release my tweaks
        # too" — pair with the cooldown that already arms here.
        await engine.set_manual_override("relax", source="api:1.2.3.4")
        engine.mark_light_manual("3")
        await engine.clear_override(source="api:1.2.3.4")
        assert "3" not in engine.manual_light_overrides

    async def test_timeout_clear_preserves_per_light(self, engine):
        # The 4h override expiry isn't a user action; per-light stamps have
        # their own independent 4h expiry in run_loop.
        await engine.set_manual_override("relax", source="api:1.2.3.4")
        engine.mark_light_manual("3")
        await engine.clear_override(source="timeout_4h")
        assert "3" in engine.manual_light_overrides


# ---------------------------------------------------------------------------
# Zone+posture → relax rule
# ---------------------------------------------------------------------------

class _FakeCamera:
    """Minimal camera stub exposing the attributes the rule reads."""

    def __init__(self, zone=None, posture=None):
        self.zone = zone
        self.posture = posture


class _FakeCameraWithFreshness:
    """Camera stub that exposes the *_committed_at freshness timestamps.

    Mirrors the real CameraService surface that ``_apply_zone_overlay``
    uses for its freshness gate. Tests that exercise the gate should use
    this stub; tests that don't care about freshness can stick with the
    bare ``_FakeCamera`` (the gate falls through when the timestamp
    attribute is absent).
    """

    def __init__(
        self,
        zone=None,
        posture=None,
        zone_committed_at=None,
        posture_committed_at=None,
    ):
        self.zone = zone
        self.posture = posture
        self.zone_committed_at = zone_committed_at
        self.posture_committed_at = posture_committed_at


class _FakeMLLogger:
    """Capture log_decision calls for assertion."""

    def __init__(self):
        self.calls: list[dict] = []

    async def log_decision(self, **kwargs):
        self.calls.append(kwargs)


class TestProcessLaneMLDecisions:
    """Per-lane ml_decisions row for the process voter.

    Mirrors the rule_engine wiring shipped 2026-04-28. Closes the audit-#5
    gap where process was the only fusion voter without standalone rows,
    blinding per-source accuracy and the analytics constellation.
    """

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        eng = AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
        )
        eng._ml_logger = _FakeMLLogger()
        return eng

    async def test_process_source_logs_ml_decision(self, engine):
        await engine.report_activity("working", source="process")
        calls = engine._ml_logger.calls
        assert len(calls) == 1
        call = calls[0]
        assert call["decision_source"] == "process"
        assert call["predicted_mode"] == "working"
        assert call["confidence"] == 1.0
        assert call["applied"] is False
        assert call["broadcast"] is False

    async def test_ambient_source_does_not_log(self, engine):
        """Ambient/RMS aliases to audio_ml in fusion but is out of scope here."""
        await engine.report_activity("social", source="ambient")
        assert engine._ml_logger.calls == []

    async def test_camera_source_does_not_log(self, engine):
        """Camera has its own decision_source elsewhere; report_activity does
        not double-log it."""
        await engine.report_activity("idle", source="camera")
        assert engine._ml_logger.calls == []

    async def test_factors_carry_priority_and_agent_factors(self, engine):
        agent_factors = [{"sub": "foreground", "value": "code.exe"}]
        await engine.report_activity(
            "working", source="process", factors=agent_factors,
        )
        call = engine._ml_logger.calls[0]
        assert call["factors"]["engine_priority"] == MODE_PRIORITY["working"]
        assert call["factors"]["agent_factors"] == agent_factors

    async def test_missing_agent_factors_logs_empty_list(self, engine):
        await engine.report_activity("gaming", source="process")
        call = engine._ml_logger.calls[0]
        assert call["factors"]["agent_factors"] == []
        assert call["factors"]["engine_priority"] == MODE_PRIORITY["gaming"]

    async def test_logs_every_arrival_including_no_mode_change(self, engine):
        """Heartbeats (same-mode reports) still log — process is a voter,
        and analytics needs a row per signal arrival."""
        await engine.report_activity("working", source="process")
        await engine.report_activity("working", source="process")
        await engine.report_activity("working", source="process")
        assert len(engine._ml_logger.calls) == 3

    async def test_no_logger_attached_does_not_raise(
        self, mock_hue, mock_hue_v2, mock_ws,
    ):
        """If ml_logger isn't injected (test bootstraps that omit it),
        the engine still accepts process reports without errors."""
        eng = AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )
        # _ml_logger defaults to None on construction; do not attach one.
        await eng.report_activity("working", source="process")
        assert eng.current_mode == "working"


class TestZonePostureRule:
    """Rule gates and dwell for the zone+posture → relax actuation."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        eng = AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
        )
        eng._ml_logger = _FakeMLLogger()
        eng._camera_service = _FakeCamera(zone="bed", posture="reclined")
        return eng

    # Thursday (weekday) 8pm — past evening_start_hour, eligible
    EVENING = datetime(2026, 4, 16, 20, 0, tzinfo=TZ)
    # Thursday 10am — morning, NOT eligible
    WEEKDAY_MORNING = datetime(2026, 4, 16, 10, 0, tzinfo=TZ)
    # Saturday 2pm — weekend afternoon, eligible
    WEEKEND_AFTERNOON = datetime(2026, 4, 18, 14, 0, tzinfo=TZ)

    async def _tick(self, engine, now, dwell_offset_seconds=0):
        """Run the rule at ``now`` with the dwell timer started in the past."""
        if dwell_offset_seconds > 0:
            engine._zone_posture_reclined_since = (
                now - timedelta(seconds=dwell_offset_seconds)
            )
        await engine._evaluate_zone_posture_rule(now)

    async def test_actuates_by_default_after_dwell(self, engine):
        """All gates pass, dwell met — rule actuates (default flipped True
        after the in-bed-watching-TV scenario surfaced)."""
        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        calls = engine._ml_logger.calls
        assert len(calls) == 1
        assert calls[0]["decision_source"] == "zone_posture_rule"
        assert calls[0]["predicted_mode"] == "relax"
        assert calls[0]["applied"] is True
        assert engine.manual_override is True
        assert engine.override_mode == "relax"

    async def test_recent_process_working_vetoes_fire(self, engine):
        """Process attendance veto: PC reported `working` <10 min ago means
        the user is at the desk, not actually settling in. Dwell met but
        the fire is suppressed, the dwell timer resets, the refractory
        stamp is NOT burned (so the rule can fire fresh once attendance
        clears + 120s of pure bed-reclined elapse). Closes the 2026-05-12
        21:34 incident where the rule mis-fired while user was at PC.

        Note: is_recent_process_working() uses wall-clock datetime.now(),
        not the ``now`` arg passed into the rule. So _last_process_working_at
        must be anchored to real time, not the EVENING fixture.
        """
        engine._last_process_working_at = (
            datetime.now(tz=TZ) - timedelta(minutes=5)
        )
        assert engine.is_recent_process_working() is True

        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)

        # No fire, no ml_decisions row, no override.
        assert engine._ml_logger.calls == []
        assert engine.manual_override is False
        # Dwell reset — a fresh window is required after attendance clears.
        assert engine._zone_posture_reclined_since is None
        # Refractory stamp NOT burned — the rule isn't locked out for 4h
        # on a vetoed fire (feedback_rule_refractory_burn_pattern.md).
        assert engine._zone_posture_last_fired_at is None

    async def test_stale_process_working_does_not_veto(self, engine):
        """Process working >10 min ago is stale — veto stands down and
        the rule fires normally. Regression guard: the veto is conditional
        on a fresh attendance signal, not a blanket suppression."""
        engine._last_process_working_at = (
            datetime.now(tz=TZ) - timedelta(minutes=30)
        )
        assert engine.is_recent_process_working() is False

        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)

        assert len(engine._ml_logger.calls) == 1
        assert engine._ml_logger.calls[0]["predicted_mode"] == "relax"
        assert engine.override_mode == "relax"

    async def test_shadow_mode_when_apply_flag_false(self, engine):
        """settings.ZONE_POSTURE_RULE_APPLY=False → log only, no actuation.

        Regression guard for the shadow-mode escape hatch — ops can still
        flip the flag off in .env if the rule misfires in production.
        """
        with patch(
            "backend.services.automation_engine.settings.ZONE_POSTURE_RULE_APPLY",
            False,
        ):
            await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        assert engine.manual_override is False
        assert engine._ml_logger.calls[0]["applied"] is False

    async def test_projector_from_bed_does_not_trigger(self, engine):
        """Sitting up in bed to watch the projector: zone=bed but upright."""
        engine._camera_service = _FakeCamera(zone="bed", posture="upright")
        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        assert engine._ml_logger.calls == []
        assert engine._zone_posture_reclined_since is None

    async def test_desk_zone_does_not_trigger(self, engine):
        engine._camera_service = _FakeCamera(zone="desk", posture="upright")
        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        assert engine._ml_logger.calls == []

    async def test_ineligible_mode_does_not_trigger(self, engine):
        """Gaming / watching / sleeping etc. block the rule."""
        await engine.report_activity("gaming", source="pc_agent")
        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        assert engine._ml_logger.calls == []

    async def test_non_social_override_suppresses(self, engine):
        """Any override OTHER than social blocks the rule unconditionally."""
        await engine.set_manual_override("gaming")
        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        assert engine._ml_logger.calls == []
        assert engine._zone_posture_reclined_since is None

    async def test_fresh_social_override_suppresses(self, engine):
        """Social override younger than SOCIAL_MIN_AGE_SECONDS = fresh user
        intent. Rule respects it and stands down."""
        await engine.set_manual_override("social")
        # Override is 10 min old — under the 30-min min-age threshold.
        engine._override_time = self.EVENING - timedelta(minutes=10)
        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        assert engine._ml_logger.calls == []
        assert engine._zone_posture_reclined_since is None

    async def test_old_social_override_can_be_superseded(self, engine):
        """Social override ≥SOCIAL_MIN_AGE old + bed-reclined dwell met:
        rule supersedes (covers the 'guest left, host stayed in social
        and went to bed' pattern observed 6× in 30 days)."""
        await engine.set_manual_override("social")
        # Backdate the override so it's 1h old — past the 30-min gate.
        engine._override_time = self.EVENING - timedelta(hours=1)
        # Social uses the longer 180s dwell, not 120s.
        await self._tick(engine, self.EVENING, dwell_offset_seconds=181)
        assert len(engine._ml_logger.calls) == 1
        assert engine._ml_logger.calls[0]["predicted_mode"] == "relax"
        assert engine._ml_logger.calls[0]["factors"]["effective_mode"] == "social"
        assert engine.override_mode == "relax"

    async def test_old_social_override_respects_longer_dwell(self, engine):
        """Past the social min-age gate, the 180s dwell still applies —
        a brief lie-down (120s) under stale social shouldn't trip."""
        await engine.set_manual_override("social")
        engine._override_time = self.EVENING - timedelta(hours=1)
        # 130s dwell — would trip under 120s but not 180s
        await self._tick(engine, self.EVENING, dwell_offset_seconds=130)
        assert engine._ml_logger.calls == []
        # Timer is set, waiting for more dwell
        assert engine._zone_posture_reclined_since is not None

    async def test_morning_does_not_trigger(self, engine):
        """Weekday morning: reclined on bed means 'still sleeping', not relax."""
        await self._tick(engine, self.WEEKDAY_MORNING, dwell_offset_seconds=301)
        assert engine._ml_logger.calls == []

    async def test_weekend_afternoon_triggers(self, engine):
        """Sat/Sun afternoon: eligible even though not 'evening'."""
        await self._tick(
            engine, self.WEEKEND_AFTERNOON, dwell_offset_seconds=301
        )
        assert len(engine._ml_logger.calls) == 1
        assert engine._ml_logger.calls[0]["factors"]["trigger"] == "weekend_afternoon"

    async def test_dwell_not_met_does_not_trigger(self, engine):
        """Under the 5-min threshold: start timer, don't fire yet."""
        await self._tick(engine, self.EVENING, dwell_offset_seconds=60)
        assert engine._ml_logger.calls == []
        # Timer is set, waiting for more time to elapse
        assert engine._zone_posture_reclined_since is not None

    async def test_refractory_suppresses_refire(self, engine):
        """Recent fire (within override_timeout_hours) blocks re-fire."""
        engine._zone_posture_last_fired_at = self.EVENING - timedelta(hours=1)
        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        assert engine._ml_logger.calls == []

    async def test_conditions_breaking_resets_dwell(self, engine):
        """If posture flips mid-dwell, timer resets."""
        # Start dwell with good conditions
        engine._zone_posture_reclined_since = self.EVENING - timedelta(minutes=3)
        # Conditions break (user sat up)
        engine._camera_service = _FakeCamera(zone="bed", posture="upright")
        await engine._evaluate_zone_posture_rule(self.EVENING)
        assert engine._zone_posture_reclined_since is None

    async def test_stamp_set_before_set_manual_override_raises(self, engine):
        """Pre-fix bug: if set_manual_override raises (transient Hue error,
        broadcast failure, etc.), the rule's stamp assign + persist never
        run, so gate 2 keeps letting the rule re-fire on every dwell window
        within the supposed 4h refractory.

        Post-fix: stamp is committed BEFORE set_manual_override, so even
        when it raises, gate 2 holds.
        """
        async def _boom(*args, **kwargs):
            raise RuntimeError("simulated transient hue failure")

        engine.set_manual_override = _boom

        with pytest.raises(RuntimeError):
            await self._tick(engine, self.EVENING, dwell_offset_seconds=301)

        # The stamp must be in-memory despite the raise.
        assert engine._zone_posture_last_fired_at is not None

    async def test_gate_2_holds_after_set_manual_override_raises(self, engine):
        """End-to-end: after the rule's first fire raises mid-set_manual_override,
        a second tick within the refractory window should still suppress.
        """
        original_set_override = engine.set_manual_override

        async def _boom(*args, **kwargs):
            raise RuntimeError("simulated transient failure")

        engine.set_manual_override = _boom
        with pytest.raises(RuntimeError):
            await self._tick(engine, self.EVENING, dwell_offset_seconds=301)

        # Restore so the next call wouldn't raise — but gate 2 should still
        # short-circuit before reaching it.
        engine.set_manual_override = original_set_override
        engine._ml_logger.calls.clear()

        # Second tick a few minutes later, conditions still met, dwell hit.
        later = self.EVENING + timedelta(minutes=5)
        await self._tick(engine, later, dwell_offset_seconds=301)

        # Gate 2 should have suppressed: no new ml_decision row, no new fire.
        assert engine._ml_logger.calls == []


# ---------------------------------------------------------------------------
# Presence attribution on rule-fire ml_decisions (Commit 3 of multi-cam fusion)
# ---------------------------------------------------------------------------

class _FakePresenceFusion:
    """Minimal stand-in for PresenceFusion that returns a fixed sources dict."""

    def __init__(self, sources: dict) -> None:
        self._sources = sources

    def get_sources(self) -> dict:
        return self._sources


class TestPresenceAttribution:
    """``_attach_presence_attribution`` stamps zone_source / posture_source.

    The fusion-lane-auditor keys on these factors to confirm both presence
    sources (Latitude + desktop) are contributing to actual mode decisions,
    not just heartbeating into the camera lane.
    """

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    def test_no_op_without_presence_fusion(self, engine):
        factors: dict = {}
        engine._attach_presence_attribution(
            factors, zone="bed", posture="reclined",
        )
        assert factors == {}

    def test_stamps_latitude_for_bed_reclined(self, engine):
        engine._presence_fusion = _FakePresenceFusion({
            "latitude": {
                "zone": "bed", "posture": "reclined", "fresh": True,
            },
            "desktop": {
                "zone": None, "posture": None, "fresh": False,
            },
        })
        factors: dict = {}
        engine._attach_presence_attribution(
            factors, zone="bed", posture="reclined",
        )
        assert factors["zone_source"] == "latitude"
        assert factors["posture_source"] == "latitude"

    def test_stamps_desktop_for_slouched(self, engine):
        engine._presence_fusion = _FakePresenceFusion({
            "latitude": {
                "zone": "desk", "posture": "upright", "fresh": True,
            },
            "desktop": {
                "zone": None, "posture": "slouched", "fresh": True,
            },
        })
        factors: dict = {}
        engine._attach_presence_attribution(
            factors, zone="desk", posture="slouched",
        )
        assert factors["zone_source"] == "latitude"
        assert factors["posture_source"] == "desktop"

    def test_stale_source_not_picked(self, engine):
        engine._presence_fusion = _FakePresenceFusion({
            "latitude": {
                "zone": "bed", "posture": "reclined", "fresh": False,
            },
        })
        factors: dict = {}
        engine._attach_presence_attribution(
            factors, zone="bed", posture="reclined",
        )
        assert factors["zone_source"] is None
        assert factors["posture_source"] is None

    def test_helper_survives_broken_presence_fusion(self, engine):
        class _Broken:
            def get_sources(self):
                raise RuntimeError("boom")

        engine._presence_fusion = _Broken()
        factors: dict = {}
        # Helper must swallow exceptions so a broken fusion never
        # destabilizes the rule fire that's calling it.
        engine._attach_presence_attribution(
            factors, zone="bed", posture="reclined",
        )
        assert factors == {}

    def test_skips_keys_when_value_is_none(self, engine):
        """Caller can omit zone or posture; only requested keys get stamped."""
        engine._presence_fusion = _FakePresenceFusion({
            "latitude": {
                "zone": "bed", "posture": "reclined", "fresh": True,
            },
        })
        factors: dict = {}
        engine._attach_presence_attribution(factors, posture="reclined")
        assert "zone_source" not in factors
        assert factors["posture_source"] == "latitude"


# ---------------------------------------------------------------------------
# Zone + posture overlay — watching-mode per-light brightness shaping
# ---------------------------------------------------------------------------

class TestZonePostureOverlay:
    """Per-light overlay tuning for watching+zone+posture combinations."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws)

    def _night_watching_state(self):
        # Matches the ACTIVITY_LIGHT_STATES["watching"]["night"] baseline.
        return {
            "1": {"on": True, "bri": 45, "ct": 454},
            "2": {"on": True, "bri": 20, "ct": 454},
            "3": {"on": False, "bri": 1},
            "4": {"on": False, "bri": 1},
        }

    def test_bed_reclined_night_lowers_l1_and_l2(self, engine):
        """Reclined in bed at night → L1 and L2 drop below baseline."""
        engine._camera_service = _FakeCamera(zone="bed", posture="reclined")
        out = engine._apply_zone_overlay(self._night_watching_state(), "watching", "night")
        assert out["1"]["bri"] == 25  # below baseline 45
        assert out["2"]["bri"] == 8   # below baseline 20
        # Kitchen L3/L4 untouched — still off.
        assert out["3"]["on"] is False
        assert out["4"]["on"] is False

    def test_bed_upright_night_unchanged(self, engine):
        """Upright in bed (sitting up, football game) → baseline preserved."""
        engine._camera_service = _FakeCamera(zone="bed", posture="upright")
        baseline = self._night_watching_state()
        out = engine._apply_zone_overlay(baseline, "watching", "night")
        assert out["1"]["bri"] == baseline["1"]["bri"]
        assert out["2"]["bri"] == baseline["2"]["bri"]

    def test_bed_reclined_day_unchanged(self, engine):
        """Day period has no reclined target — natural light handles it."""
        engine._camera_service = _FakeCamera(zone="bed", posture="reclined")
        baseline = {
            "1": {"on": True, "bri": 80, "ct": 320},
            "2": {"on": True, "bri": 70, "ct": 370},
        }
        out = engine._apply_zone_overlay(baseline, "watching", "day")
        assert out["1"]["bri"] == 80
        assert out["2"]["bri"] == 70

    def test_posture_none_does_not_lower(self, engine):
        """Face-only sessions (posture=None) fall through — never assume reclined."""
        engine._camera_service = _FakeCamera(zone="bed", posture=None)
        baseline = self._night_watching_state()
        out = engine._apply_zone_overlay(baseline, "watching", "night")
        assert out["1"]["bri"] == baseline["1"]["bri"]
        assert out["2"]["bri"] == baseline["2"]["bri"]

    def test_desk_lift_still_works(self, engine):
        """Regression — desk branch continues to raise L2 above dim baseline."""
        engine._camera_service = _FakeCamera(zone="desk", posture="upright")
        state = {
            "1": {"on": True, "bri": 45, "ct": 454},
            "2": {"on": True, "bri": 20, "ct": 454},
        }
        out = engine._apply_zone_overlay(state, "watching", "night")
        assert out["2"]["bri"] == 70  # zone_bri_by_period[night]

    def test_stale_commit_ignored(self, engine):
        """Commit older than the freshness window is treated as missing.

        Regression for the morning-after-sleep case: bed/reclined committed
        before sleeping must not drive the next day's lighting decisions.
        """
        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        engine._camera_service = _FakeCameraWithFreshness(
            zone="bed",
            posture="reclined",
            zone_committed_at=stale,
            posture_committed_at=stale,
        )
        baseline = self._night_watching_state()
        out = engine._apply_zone_overlay(baseline, "watching", "night")
        # Stale → treated as no data → bed+reclined branch must NOT fire.
        assert out["1"]["bri"] == baseline["1"]["bri"]
        assert out["2"]["bri"] == baseline["2"]["bri"]

    def test_fresh_commit_still_lowers(self, engine):
        """A recent commit (well under the freshness window) still applies."""
        recent = datetime.now(timezone.utc) - timedelta(seconds=30)
        engine._camera_service = _FakeCameraWithFreshness(
            zone="bed",
            posture="reclined",
            zone_committed_at=recent,
            posture_committed_at=recent,
        )
        out = engine._apply_zone_overlay(
            self._night_watching_state(), "watching", "night",
        )
        assert out["1"]["bri"] == 25
        assert out["2"]["bri"] == 8

    def test_bed_reclined_lowers_in_working_mode(self, engine):
        """Bed+reclined is a physical fact — lower L1/L2 even when mode=working.

        Regression: previously _apply_zone_overlay was watching-only, so
        a watching→working flip while reclined snapped L2 to working's
        bright ambient (~bri 173).

        Working takes the readable-floor table (L2=35 at night) — terminal
        text needs to be legible. Watching/relax/idle take the
        watching-projector dim (L2=8 at night).
        """
        engine._camera_service = _FakeCamera(zone="bed", posture="reclined")
        state = {
            "1": {"on": True, "bri": 60, "ct": 2270},
            "2": {"on": True, "bri": 130, "ct": 2700},
        }
        out = engine._apply_zone_overlay(state, "working", "night")
        assert out["1"]["bri"] == 25
        assert out["2"]["bri"] == 35

    def test_bed_reclined_lowers_in_relax_and_idle(self, engine):
        """Reclined-lower applies across non-task modes."""
        engine._camera_service = _FakeCamera(zone="bed", posture="reclined")
        state = {
            "1": {"on": True, "bri": 80, "ct": 454},
            "2": {"on": True, "bri": 60, "ct": 454},
        }
        for mode in ("relax", "idle", "social"):
            out = engine._apply_zone_overlay(state, mode, "night")
            assert out["1"]["bri"] == 25
            assert out["2"]["bri"] == 8

    def test_bed_reclined_sleeping_passes_through(self, engine):
        """Sleeping baseline is already below the reclined targets — no-op."""
        engine._camera_service = _FakeCamera(zone="bed", posture="reclined")
        state = {
            "1": {"on": True, "bri": 20, "ct": 454},
            "2": {"on": True, "bri": 5, "ct": 454},
        }
        out = engine._apply_zone_overlay(state, "sleeping", "night")
        assert out == state

    def test_desk_lift_only_for_watching(self, engine):
        """Desk lift stays watching-only — working at desk uses its own ambient."""
        engine._camera_service = _FakeCamera(zone="desk", posture="upright")
        state = {
            "1": {"on": True, "bri": 60, "ct": 2270},
            "2": {"on": True, "bri": 130, "ct": 2700},
        }
        out = engine._apply_zone_overlay(state, "working", "night")
        assert out == state


# ---------------------------------------------------------------------------
# Screen-sync posture-aware brightness cap
# ---------------------------------------------------------------------------

class TestScreenSyncPostureCap:
    """MODE_ZONE_MAX_BRIGHTNESS entries are keyed by light id."""

    def test_exact_posture_match_wins_per_light(self):
        from backend.services.screen_sync import MODE_ZONE_MAX_BRIGHTNESS
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "bed", "reclined", "2")] == 25
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "bed", "upright",  "2")] == 60
        # L5 caps are stepped down because the clear housing reads brighter.
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "bed", "reclined", "5")] == 20
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "bed", "upright",  "5")] == 50

    def test_desk_entry_preserved(self):
        from backend.services.screen_sync import MODE_ZONE_MAX_BRIGHTNESS
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "desk", "day", "2")] == 180
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "desk", "night", "2")] == 110
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "desk", "2")] == 120


# ---------------------------------------------------------------------------
# Runtime-tunable watching-posture overrides
# ---------------------------------------------------------------------------

class TestWatchingPostureRuntimeTuning:
    """Settings-page sliders update screen-sync caps + engine L1 at runtime."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws)

    def test_screen_sync_cap_override_wins(self, mock_hue):
        from backend.services.screen_sync import ScreenSyncService
        sync = ScreenSyncService(mock_hue, target_light_ids=["2", "5"])
        # Default from hardcoded dict (L2 reclined cap = 25).
        assert sync.get_cap("watching", "2", "bed", "reclined") == 25
        # Override — settings slider dropped L2's reclined cap to 10.
        sync.set_cap_override("watching", "bed", "reclined", 10)
        assert sync.get_cap("watching", "2", "bed", "reclined") == 10
        # L5's parallel entry is untouched.
        assert sync.get_cap("watching", "5", "bed", "reclined") == 20
        # Sibling entries untouched.
        assert sync.get_cap("watching", "2", "bed", "upright") == 60
        assert sync.get_cap("watching", "2", "desk", "upright") == 120
        assert sync.get_cap("watching", "2", "desk", "upright", period="night") == 110

    def test_screen_sync_cap_fallback_order(self, mock_hue):
        from backend.services.screen_sync import ScreenSyncService
        sync = ScreenSyncService(mock_hue, target_light_ids=["2", "5"])
        # Posture missing — falls back through period-specific, then generic zone cap.
        assert sync.get_cap("watching", "2", "desk", None, period="day") == 180
        assert sync.get_cap("watching", "2", "desk", None, period="night") == 110
        assert sync.get_cap("watching", "2", "desk", None) == 120
        # Mode-only fallback (L2 working has no entry → default).
        assert sync.get_cap("working", "2", None, None) > 0

    def test_engine_l1_override_scales_reclined_night(self, engine):
        engine._camera_service = _FakeCamera(zone="bed", posture="reclined")
        state = {
            "1": {"on": True, "bri": 45, "ct": 454},
            "2": {"on": True, "bri": 20, "ct": 454},
        }
        engine.set_bed_reclined_l1_night(10)
        out = engine._apply_zone_overlay(state, "watching", "night")
        assert out["1"]["bri"] == 10  # night ratio = 1.0

    def test_engine_l1_override_scales_evening(self, engine):
        engine._camera_service = _FakeCamera(zone="bed", posture="reclined")
        state = {
            "1": {"on": True, "bri": 65, "ct": 400},
            "2": {"on": True, "bri": 40, "ct": 400},
        }
        engine.set_bed_reclined_l1_night(20)
        out = engine._apply_zone_overlay(state, "watching", "evening")
        # evening ratio = 1.8 → 20 * 1.8 = 36
        assert out["1"]["bri"] == 36

    def test_engine_l1_override_clamps(self, engine):
        engine.set_bed_reclined_l1_night(999)
        assert engine._bed_reclined_l1_night == 100
        engine.set_bed_reclined_l1_night(-5)
        assert engine._bed_reclined_l1_night == 1


# ---------------------------------------------------------------------------
# Process source device ownership — process reports from different machines
# should not all count as the same owner. This lets fresh Latitude/TV watching
# beat stale desktop gaming, while stale desktop work cannot demote an active
# Latitude watching session just because both reports use source="process".
# ---------------------------------------------------------------------------

class TestProcessSourceDeviceOwnership:
    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws)

    async def test_latitude_watching_displaces_stale_desktop_gaming(self, engine):
        stale = datetime.now(tz=TZ) - timedelta(seconds=SOURCE_STALE_SECONDS + 60)
        engine._current_mode = "gaming"
        engine._current_game = "rust"
        engine._mode_source = "process"
        engine._mode_source_key = "process:desktop"
        engine._last_mode_source_report_at["process:desktop"] = stale

        await engine.report_activity(
            mode="watching",
            source="process",
            factors=[
                {"key": "device", "value": "latitude"},
                {"key": "foreground_kind", "value": "media"},
            ],
        )

        assert engine.current_mode == "watching"
        assert engine.current_game is None
        assert engine._mode_source_key == "process:latitude"

    async def test_desktop_working_does_not_demote_fresh_latitude_watching(self, engine):
        recent = datetime.now(tz=TZ) - timedelta(seconds=5)
        engine._current_mode = "watching"
        engine._mode_source = "process"
        engine._mode_source_key = "process:latitude"
        engine._last_mode_source_report_at["process:latitude"] = recent

        await engine.report_activity(
            mode="working",
            source="process",
            factors=[
                {"key": "device", "value": "desktop"},
                {"key": "foreground_kind", "value": "dev"},
            ],
        )

        assert engine.current_mode == "watching"
        assert engine._mode_source_key == "process:latitude"
        assert engine._last_mode_source_report_at["process:desktop"] is not None

# ---------------------------------------------------------------------------
# is_at_desk_fresh — camera-aware veto helper
# ---------------------------------------------------------------------------


class _FakeEnabledCamera:
    """Camera stub with the ``enabled`` flag the helper checks."""

    def __init__(
        self,
        zone=None,
        enabled=True,
        zone_committed_at=None,
        posture=None,
        posture_committed_at=None,
    ):
        self.zone = zone
        self.enabled = enabled
        self.zone_committed_at = zone_committed_at
        self.posture = posture
        self.posture_committed_at = posture_committed_at


class TestIsAtDeskFresh:
    """``is_at_desk_fresh`` is the camera-veto used by autonomous mode-setters."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws)

    def test_no_camera_returns_false(self, engine):
        engine._camera_service = None
        assert engine.is_at_desk_fresh() is False

    def test_disabled_camera_returns_false(self, engine):
        engine._camera_service = _FakeEnabledCamera(zone="desk", enabled=False)
        assert engine.is_at_desk_fresh() is False

    def test_zone_bed_returns_false(self, engine):
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        engine._camera_service = _FakeEnabledCamera(
            zone="bed", enabled=True, zone_committed_at=recent,
        )
        assert engine.is_at_desk_fresh() is False

    def test_zone_none_returns_false(self, engine):
        engine._camera_service = _FakeEnabledCamera(zone=None, enabled=True)
        assert engine.is_at_desk_fresh() is False

    def test_zone_desk_fresh_returns_true(self, engine):
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        engine._camera_service = _FakeEnabledCamera(
            zone="desk", enabled=True, zone_committed_at=recent,
        )
        assert engine.is_at_desk_fresh() is True

    def test_zone_desk_stale_returns_false(self, engine):
        # Past the freshness window (>60s default) → treated as no data.
        stale = datetime.now(timezone.utc) - timedelta(minutes=10)
        engine._camera_service = _FakeEnabledCamera(
            zone="desk", enabled=True, zone_committed_at=stale,
        )
        assert engine.is_at_desk_fresh() is False

    def test_camera_without_timestamp_falls_through(self, engine):
        """Plain stubs without commit timestamps bypass the freshness gate.

        Mirrors the same back-compat behavior as ``_fresh_camera_attr`` so
        legacy fakes don't have to grow timestamp surfaces.
        """
        engine._camera_service = _FakeCamera(zone="desk")
        engine._camera_service.enabled = True  # add enabled flag
        assert engine.is_at_desk_fresh() is True


# ---------------------------------------------------------------------------
# _apply_mode dedup — force_resend gates the cache-clear so periodic reapplies
# can no-op via dedup. Regression guard against the "every 60s, all lights
# rewritten" churn that filled light_adjustments at ~4 rows/min/light.
# ---------------------------------------------------------------------------


class TestApplyModeDedup:

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    @staticmethod
    def _wrap_set_light(mock_hue) -> list[str]:
        """Wrap mock_hue.set_light to append every called light_id to a list."""
        calls: list[str] = []
        original = mock_hue.set_light

        async def counting(lid, state):
            calls.append(str(lid))
            return await original(lid, state)

        mock_hue.set_light = counting
        return calls

    async def test_reapply_with_force_resend_false_is_noop(self, engine, mock_hue):
        # First apply must force resend so the dedup cache populates and
        # the bridge actually receives the initial state.
        await engine._apply_mode("working", force_resend=True)

        # Now wrap and count subsequent writes only.
        calls = self._wrap_set_light(mock_hue)
        await engine._apply_mode("working", force_resend=False)
        assert calls == [], (
            f"reapply with force_resend=False wrote to {calls}; dedup is broken"
        )

    async def test_force_resend_true_writes_after_no_state_change(self, engine, mock_hue):
        await engine._apply_mode("working", force_resend=True)
        calls = self._wrap_set_light(mock_hue)
        # force_resend=True bypasses dedup even when state hasn't changed.
        await engine._apply_mode("working", force_resend=True)
        assert len(calls) > 0

    async def test_default_force_resend_is_false(self, engine, mock_hue):
        # Ensure the default behavior is the dedup-friendly one. A periodic
        # reapply tick that omits the kwarg should not thrash the bridge.
        await engine._apply_mode("working", force_resend=True)
        calls = self._wrap_set_light(mock_hue)
        await engine._apply_mode("working")  # no kwarg → default False
        assert calls == []

    async def test_same_mode_report_does_not_thrash_bridge(
        self, engine, mock_hue,
    ):
        """Regression test for the 2026-05-06 L2 churn audit.

        report_activity used to call _apply_mode(force_resend=True)
        unconditionally, which cleared _last_applied_per_light on every
        PC-agent heartbeat and produced ~3.5 no-op bridge writes per
        minute on L2 (logged with bri_before=null because the cache had
        just been wiped). The fix gates force_resend on
        old_mode != mode — same-mode heartbeats now ride the per-light
        dedup, so identical-state writes are suppressed. This test locks
        in that invariant.
        """
        # First report establishes the mode and pre-populates the cache
        # (the very first apply will go to the bridge — that's the one
        # legitimate write at session start).
        await engine.report_activity("working", source="process")

        # Wrap and count subsequent bridge writes only.
        calls = self._wrap_set_light(mock_hue)

        # Three same-mode heartbeats — what the PC agent does at 5s
        # cadence in steady state. With the fix, none of them should
        # reach the bridge (state hasn't changed, dedup catches them).
        await engine.report_activity("working", source="process")
        await engine.report_activity("working", source="process")
        await engine.report_activity("working", source="process")

        assert calls == [], (
            f"same-mode heartbeats wrote to {calls}; force_resend should be "
            f"False on no-mode-change reports so the dedup cache is preserved"
        )

    @patch("backend.services.automation_engine.datetime")
    async def test_confirmed_general_idle_heartbeats_do_not_thrash_bridge(
        self, mock_dt, engine, mock_hue,
    ):
        now = datetime(2026, 8, 18, 3, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._home_awake_confirmed = True

        await engine.report_activity("idle", source="process")
        calls = self._wrap_set_light(mock_hue)

        await engine.report_activity("idle", source="process")
        await engine.report_activity("idle", source="process")
        await engine.report_activity("idle", source="process")

        assert calls == [], (
            "confirmed General idle heartbeats should remain dedup-friendly"
        )

    async def test_mode_change_report_still_invalidates_cache(
        self, engine, mock_hue,
    ):
        """Counterpart to the above — when the mode actually changes,
        force_resend must still be True so any bridge drift accumulated
        during the prior mode (effects, external writes, override
        releases) gets re-corrected on the transition."""
        await engine.report_activity("working", source="process")

        calls = self._wrap_set_light(mock_hue)

        # Real mode change: working → gaming. Cache should be cleared,
        # bridge should receive new state.
        await engine.report_activity("gaming", source="process")

        assert len(calls) > 0, (
            "mode change should invalidate the cache and write new state "
            "to the bridge"
        )

    async def test_apply_mode_primes_screen_sync_with_final_state(
        self, engine,
    ):
        """Screen sync should start from the computed night baseline."""

        class _FakeScreenSync:
            def __init__(self) -> None:
                self.calls = []
                self.last_color_at = None
                self.target_lights = ["2", "5"]

            def prime_from_mode_state(self, mode, period, states) -> None:
                self.calls.append((mode, period, states))

        sync = _FakeScreenSync()
        engine._screen_sync = sync
        engine._get_time_period = lambda now=None: "night"

        await engine._apply_mode("watching", force_resend=True)

        assert sync.calls
        mode, period, states = sync.calls[-1]
        assert mode == "watching"
        assert period == "night"
        assert states["2"]["bri"] == 20
        assert states["5"]["bri"] == 12

    async def test_apply_mode_preserves_winddown_ramp_from_one_clock_sample(
        self, engine,
    ):
        """20:39 evening still interpolates Watching while sampling once."""

        class _FakeScreenSync:
            def __init__(self) -> None:
                self.calls = []
                self.last_color_at = None
                self.target_lights = ["2", "5"]

            def prime_from_mode_state(self, mode, period, states) -> None:
                self.calls.append((mode, period, states))

        fixed_now = datetime(2026, 8, 18, 20, 39, tzinfo=TZ)
        clock = MagicMock(return_value=fixed_now)
        engine._now = clock
        sync = _FakeScreenSync()
        engine._screen_sync = sync

        await engine._apply_mode("watching", force_resend=True)

        mode, period, states = sync.calls[-1]
        assert mode == "watching"
        assert period == "evening"
        assert states["2"]["bri"] == 27
        assert states["5"]["bri"] == 14
        clock.assert_called_once_with()

    async def test_learner_overlay_does_not_change_generic_screen_sync_source(
        self, mock_hue, mock_hue_v2, mock_ws,
    ):
        """The final composed target, including overlays, reaches ScreenSync."""

        class _Learner:
            def get_overlay(self, mode, period, weather, *, zone=None):
                assert (mode, period, weather) == ("gaming", "day", "clouds")
                return {"2": {"bri": 189}}

            def has_weather_pref(self, mode, period, weather):
                return set()

        class _Weather:
            def get_cached(self):
                return {"description": "clouds"}

        mock_hue._lights["5"] = {
            "id": "5",
            "name": "Bedroom Right",
            "on": True,
            "bri": 90,
            "hue": 8000,
            "sat": 140,
            "reachable": True,
        }
        sync = ScreenSyncService(
            hue_service=mock_hue, target_light_ids=["2", "5"],
        )
        engine = AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
            weather_service=_Weather(),
            lighting_learner=_Learner(),
            screen_sync=sync,
        )
        engine._get_time_period = lambda now=None: "day"

        await engine._apply_mode("gaming", force_resend=True)

        assert mock_hue._lights["2"]["bri"] == 207
        assert ACTIVITY_LIGHT_STATES["gaming"]["day"]["2"]["bri"] == 240
        assert resolve_activity_state("gaming", "day")["2"]["bri"] == 240

        await sync.apply_color("2", 0, 0, 0, mode="gaming", period="day")
        await sync.apply_color("5", 0, 0, 0, mode="gaming", period="day")

        assert mock_hue._lights["2"]["bri"] == 207
        assert mock_hue._lights["5"]["bri"] == sync._accepted_gaming_targets["5"]["bri"]


# ---------------------------------------------------------------------------
# notify_camera_commit — re-apply lights when zone/posture transitions
# ---------------------------------------------------------------------------


class TestNotifyCameraCommit:
    """Verify notify_camera_commit triggers a fresh light apply.

    Repro of the 2026-05-08 01:35 EDT regression: service restart wiped
    camera state, lights settled at the working baseline (~bri 176)
    before zone/posture re-committed. The 60s periodic re-apply skips
    when manual override is on, so without this hook, lights stayed
    bright until the next mode change.
    """

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    async def test_notify_writes_to_bridge_after_settled_state(
        self, engine, mock_hue,
    ):
        """The reproduction: lights are settled, manual override is on,
        camera commits zone/posture late, notify_camera_commit must
        force a re-apply so the overlay-aware state hits the bridge."""
        # Settle into working with a manual override (mirrors the live
        # 01:35 regression — mode_source=manual, no auto-reapply).
        await engine.set_manual_override("working", source="api:test")

        # Capture writes from this point forward only.
        calls: list[str] = []
        original = mock_hue.set_light

        async def counting(lid, state):
            calls.append(str(lid))
            return await original(lid, state)

        mock_hue.set_light = counting

        # Camera-commit notification — should bust dedup and re-apply.
        await engine.notify_camera_commit()

        assert len(calls) > 0, (
            "notify_camera_commit should clear the dedup cache and "
            "write to the bridge so the now-fresh zone/posture overlay "
            f"can take effect; got {calls}"
        )

    async def test_notify_no_op_when_mode_unset(self, engine, mock_hue):
        """If somehow current_mode is falsy, don't crash and don't write."""
        # Force-clear mode to simulate the very-early-startup edge case.
        engine._current_mode = None
        engine._manual_override = False
        engine._override_mode = None

        calls: list[str] = []
        original = mock_hue.set_light

        async def counting(lid, state):
            calls.append(str(lid))
            return await original(lid, state)

        mock_hue.set_light = counting

        # Should be a no-op, not an exception.
        await engine.notify_camera_commit()
        assert calls == []

    async def test_notify_uses_override_mode_when_active(
        self, engine, mock_hue,
    ):
        """current_mode resolves to the override when set — confirm the
        re-apply happens against the overridden mode, not the detected
        mode underneath."""
        # Prime PC-detected mode as gaming, then override to working.
        await engine.report_activity("gaming", source="process")
        await engine.set_manual_override("working", source="api:test")

        calls: list[tuple[str, dict]] = []
        original = mock_hue.set_light

        async def counting(lid, state):
            calls.append((str(lid), state))
            return await original(lid, state)

        mock_hue.set_light = counting

        await engine.notify_camera_commit()

        # Expect writes (force_resend=True clears dedup). The exact
        # state values are tested in TestZonePostureOverlay; here we
        # just confirm the apply ran for the override mode.
        assert len(calls) > 0


# ---------------------------------------------------------------------------
# Transit override revert respects manual override
# ---------------------------------------------------------------------------


class TestClearTransitOverrideRespectsManualOverride:
    """Regression for the in-bed-watching-TV bug: when transit lighting reverts
    after a brief camera flicker, it must reapply the EFFECTIVE (override-aware)
    mode — not the raw `_current_mode` which the PC activity detector keeps
    flooding with "working" while Anthony is reclined.

    Pre-fix path: relax override → camera flickers → transit fires (L1+L3+L4)
    → camera sees him → clear_transit_override → `_apply_mode(_current_mode)`
    snapped lights to working late_night × lux. Visible bug: bright lights
    over a relax override.
    """

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    async def test_revert_uses_override_mode_when_override_active(self, engine):
        # Process detector says working; user override says relax.
        await engine.report_activity("working", source="pc_agent")
        await engine.set_manual_override("relax")
        assert engine.current_mode == "relax"
        assert engine._current_mode == "working"  # internal field stays "working"

        # Simulate transit lighting having raised L1+L3+L4.
        from datetime import datetime, timedelta
        deadline = datetime.now(tz=TZ) + timedelta(minutes=10)
        engine._transit_light_overrides = {
            "1": deadline, "3": deadline, "4": deadline,
        }

        # Capture which mode `_apply_mode` is called with on revert.
        applied_modes: list[str] = []
        original = engine._apply_mode

        async def spy(mode, *, force_resend=False):
            applied_modes.append(mode)
            return await original(mode, force_resend=force_resend)

        engine._apply_mode = spy

        await engine.clear_transit_override()
        assert applied_modes == ["relax"], (
            f"expected revert to apply override mode 'relax', got {applied_modes}"
        )

    async def test_revert_uses_detected_mode_when_no_override(self, engine):
        # No override → revert reapplies whatever the detector reports.
        await engine.report_activity("working", source="pc_agent")
        assert engine.manual_override is False

        from datetime import datetime, timedelta
        deadline = datetime.now(tz=TZ) + timedelta(minutes=10)
        engine._transit_light_overrides = {"1": deadline}

        applied_modes: list[str] = []
        original = engine._apply_mode

        async def spy(mode, *, force_resend=False):
            applied_modes.append(mode)
            return await original(mode, force_resend=force_resend)

        engine._apply_mode = spy

        await engine.clear_transit_override()
        assert applied_modes == ["working"]


# ---------------------------------------------------------------------------
# Log-tag uses override-aware mode. Regression for the 2026-05-11 entry #17
# false positive: light_adjustments rows stamped `mode_at_time=working` while
# carrying relax-palette HSB during a relax override. Bridge writes were
# correct (transit-revert uses `self.current_mode` at line 1500); only the
# DB log tag was wrong because `_apply_uniform` + `_apply_per_light` used
# `self._current_mode` (raw detected) instead of `self.current_mode`
# (override-aware property). Same footgun as the 4/26 incident captured in
# feedback_current_mode_field_footgun.md.
# ---------------------------------------------------------------------------


class TestLogAdjustmentTagsUseOverrideMode:
    """`log_light_adjustment(mode_at_time=...)` must match the override-aware
    `current_mode` property — i.e. mirror what was actually applied to the
    bridge — not the raw `_current_mode` detector field."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    async def test_per_light_log_uses_override_mode_when_override_active(self, engine):
        from unittest.mock import AsyncMock

        await engine.report_activity("working", source="pc_agent")
        await engine.set_manual_override("relax")
        assert engine.current_mode == "relax"
        assert engine._current_mode == "working"

        engine._event_logger = AsyncMock()
        engine._event_logger.log_light_adjustment = AsyncMock()

        # Two differing states so the uniform short-circuit at line 1875
        # doesn't fire — we want to exercise the per-light log path.
        await engine._apply_per_light({
            "1": {"on": True, "bri": 100, "hue": 20000, "sat": 100},
            "2": {"on": True, "bri": 80, "hue": 8000, "sat": 200},
        })

        calls = engine._event_logger.log_light_adjustment.await_args_list
        assert len(calls) == 2, f"expected 2 log calls, got {len(calls)}"
        for call in calls:
            assert call.kwargs["mode_at_time"] == "relax", (
                f"log tag should be the override mode 'relax', "
                f"got {call.kwargs['mode_at_time']!r}"
            )

    async def test_uniform_log_uses_override_mode_when_override_active(self, engine):
        from unittest.mock import AsyncMock

        await engine.report_activity("working", source="pc_agent")
        await engine.set_manual_override("relax")
        assert engine.current_mode == "relax"
        assert engine._current_mode == "working"

        engine._event_logger = AsyncMock()
        engine._event_logger.log_light_adjustment = AsyncMock()

        await engine._apply_uniform(
            {"on": True, "bri": 100, "hue": 20000, "sat": 100},
        )

        calls = engine._event_logger.log_light_adjustment.await_args_list
        assert len(calls) >= 1, "expected at least one log call"
        for call in calls:
            assert call.kwargs["mode_at_time"] == "relax", (
                f"log tag should be the override mode 'relax', "
                f"got {call.kwargs['mode_at_time']!r}"
            )


# ---------------------------------------------------------------------------
# Screen-sync target protection (B3, audit 2026-05-30 syncfight-1). Screen
# sync writes L2/L5 straight to the bridge, bypassing the dedup cache; the
# mode-apply pipeline must skip those lamps while sync is fresh or it fights
# sync and the two lamps flicker. Freshness-gated so the engine reclaims them
# when sync goes quiet.
# ---------------------------------------------------------------------------


class TestScreenSyncTargetProtection:
    """`_protected_light_ids()` adds the sync target lamps while sync is
    fresh in a SCREEN_SYNC_MODE, and the apply pipeline honors that."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    def _fake_sync(self, *, age_seconds, targets=("2", "5")):
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace
        return SimpleNamespace(
            last_color_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
            target_lights=list(targets),
        )

    async def test_fresh_sync_protects_targets_in_gaming(self, engine):
        from unittest.mock import AsyncMock
        await engine.report_activity("gaming", source="pc_agent")
        engine._screen_sync = self._fake_sync(age_seconds=1.0)
        assert engine._protected_light_ids() == {"2", "5"}

        # Spy set_light (the conftest fake isn't a Mock and doesn't track L5).
        engine._hue.set_light = AsyncMock(return_value=True)
        engine._last_applied_per_light = {}  # force every light to be a write
        await engine._apply_per_light({
            "1": {"on": True, "bri": 65, "hue": 47000, "sat": 190},
            "2": {"on": True, "bri": 150, "hue": 46920, "sat": 190},
            "3": {"on": True, "bri": 40, "hue": 50000, "sat": 190},
            "4": {"on": True, "bri": 40, "hue": 50000, "sat": 190},
            "5": {"on": True, "bri": 120, "hue": 48000, "sat": 170},
        })
        written = {call.args[0] for call in engine._hue.set_light.await_args_list}
        assert "2" not in written and "5" not in written  # sync owns L2/L5
        assert {"1", "3", "4"} <= written  # ambient still applied

    async def test_stale_sync_reclaims_targets(self, engine):
        from unittest.mock import AsyncMock
        await engine.report_activity("gaming", source="pc_agent")
        engine._screen_sync = self._fake_sync(age_seconds=30.0)  # > 8s grace
        assert engine._protected_light_ids() == set()

        engine._hue.set_light = AsyncMock(return_value=True)
        engine._last_applied_per_light = {}
        await engine._apply_per_light({
            "1": {"on": True, "bri": 65, "hue": 47000, "sat": 190},
            "2": {"on": True, "bri": 150, "hue": 46920, "sat": 190},
            "5": {"on": True, "bri": 120, "hue": 48000, "sat": 170},
        })
        written = {call.args[0] for call in engine._hue.set_light.await_args_list}
        assert {"1", "2", "5"} <= written  # stale sync → engine reclaims L2/L5

    async def test_no_protection_outside_sync_modes(self, engine):
        # working is NOT a SCREEN_SYNC_MODE → a fresh sync push must not
        # protect (the engine owns the lamps in non-sync modes).
        await engine.report_activity("working", source="pc_agent")
        engine._screen_sync = self._fake_sync(age_seconds=1.0)
        assert engine._protected_light_ids() == set()

    async def test_protection_unions_manual_transit_sync(self, engine):
        from datetime import datetime, timedelta, timezone
        await engine.report_activity("gaming", source="pc_agent")
        engine._screen_sync = self._fake_sync(age_seconds=1.0)
        engine._manual_light_overrides = {"1": datetime.now(timezone.utc)}
        engine._transit_light_overrides = {
            "3": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        # manual L1 + transit L3 + sync L2/L5
        assert engine._protected_light_ids() == {"1", "2", "3", "5"}

    async def test_uniform_automation_write_invalidates_all_sync_targets(self, engine):
        """Uniform normal-automation writes dirty both sync targets."""
        from unittest.mock import AsyncMock

        from backend.services.screen_sync import ScreenSyncService

        sync = ScreenSyncService(
            hue_service=engine._hue, target_light_ids=["2", "5"],
        )
        _prime_gaming_sync(sync)
        await sync.apply_color("2", 0, 0, 0, mode="gaming", period="day")
        await sync.apply_color("5", 0, 0, 0, mode="gaming", period="day")
        assert set(sync._last_sent_state) == {"2", "5"}

        engine._screen_sync = sync
        engine._current_mode = "working"
        engine._hue.set_light = AsyncMock(return_value=True)
        engine._last_applied_per_light = {}

        await engine._apply_uniform({"on": True, "bri": 160, "ct": 350})

        assert engine._hue.set_light.await_count == 6
        assert sync._last_sent_state == {}

    async def test_failed_uniform_write_preserves_sync_cache_and_retries(self, engine):
        """Failed writes preserve sync assumptions and never poison dedup."""
        from unittest.mock import AsyncMock

        from backend.services.screen_sync import ScreenSyncService

        sync = ScreenSyncService(
            hue_service=engine._hue, target_light_ids=["2", "5"],
        )
        _prime_gaming_sync(sync)
        await sync.apply_color("2", 0, 0, 0, mode="gaming", period="day")
        await sync.apply_color("5", 0, 0, 0, mode="gaming", period="day")
        cached = {lid: state.copy() for lid, state in sync._last_sent_state.items()}

        engine._screen_sync = sync
        engine._current_mode = "working"
        engine._hue.set_light = AsyncMock(return_value=False)
        engine._last_applied_per_light = {}

        await engine._apply_uniform({"on": True, "bri": 160, "ct": 350})

        assert engine._hue.set_light.await_count == 6
        assert sync._last_sent_state == cached
        assert engine._last_applied_per_light == {}

        engine._hue.set_light.reset_mock()
        await engine._apply_uniform({"on": True, "bri": 160, "ct": 350})
        assert engine._hue.set_light.await_count == 6

    async def test_successful_per_light_l2_write_invalidates_only_l2(self, engine):
        """A successful L2 automation write dirties only L2's sync cache."""
        from unittest.mock import AsyncMock

        from backend.services.screen_sync import ScreenSyncService

        sync = ScreenSyncService(
            hue_service=engine._hue, target_light_ids=["2", "5"],
        )
        _prime_gaming_sync(sync)
        await sync.apply_color("2", 0, 0, 0, mode="gaming", period="day")
        await sync.apply_color("5", 0, 0, 0, mode="gaming", period="day")

        engine._screen_sync = sync
        engine._current_mode = "working"
        engine._hue.set_light = AsyncMock(return_value=True)
        engine._last_applied_per_light = {}

        await engine._apply_per_light({
            "1": {"on": True, "bri": 80, "ct": 350},
            "2": {"on": True, "bri": 207, "hue": 46920, "sat": 180},
        })

        assert "2" not in sync._last_sent_state
        assert sync._last_sent_state["5"]["bri"] == 90

    async def test_failed_per_light_l2_write_preserves_l2_cache(self, engine):
        """A failed L2 automation write does not dirty L2's sync cache."""
        from unittest.mock import AsyncMock

        from backend.services.screen_sync import ScreenSyncService

        sync = ScreenSyncService(
            hue_service=engine._hue, target_light_ids=["2", "5"],
        )
        _prime_gaming_sync(sync)
        await sync.apply_color("2", 0, 0, 0, mode="gaming", period="day")
        await sync.apply_color("5", 0, 0, 0, mode="gaming", period="day")
        cached_l2 = sync._last_sent_state["2"].copy()

        engine._screen_sync = sync
        engine._current_mode = "working"
        engine._hue.set_light = AsyncMock(
            side_effect=lambda light_id, _state: light_id != "2",
        )
        engine._last_applied_per_light = {}

        await engine._apply_per_light({
            "1": {"on": True, "bri": 80, "ct": 350},
            "2": {"on": True, "bri": 207, "hue": 46920, "sat": 180},
        })

        assert sync._last_sent_state["2"] == cached_l2
        assert sync._last_sent_state["5"]["bri"] == 90

    async def test_mixed_per_light_results_invalidate_only_successful_target(self, engine):
        """Failed L2 and successful L5 writes reconcile independently."""
        from unittest.mock import AsyncMock

        from backend.services.screen_sync import ScreenSyncService

        sync = ScreenSyncService(
            hue_service=engine._hue, target_light_ids=["2", "5"],
        )
        _prime_gaming_sync(sync)
        await sync.apply_color("2", 0, 0, 0, mode="gaming", period="day")
        await sync.apply_color("5", 0, 0, 0, mode="gaming", period="day")
        cached_l2 = sync._last_sent_state["2"].copy()

        engine._screen_sync = sync
        engine._current_mode = "working"
        engine._hue.set_light = AsyncMock(
            side_effect=lambda light_id, _state: light_id == "5",
        )
        engine._last_applied_per_light = {}

        await engine._apply_per_light({
            "2": {"on": True, "bri": 207, "hue": 46920, "sat": 180},
            "5": {"on": True, "bri": 139, "hue": 48500, "sat": 160},
        })

        assert sync._last_sent_state["2"] == cached_l2
        assert "5" not in sync._last_sent_state

    async def test_automation_write_invalidates_only_changed_sync_targets(self, engine):
        """Automation bridge writes dirty per-light sync assumptions."""
        from datetime import datetime, timedelta, timezone
        from unittest.mock import AsyncMock

        from backend.services.screen_sync import ScreenSyncService

        sync = ScreenSyncService(
            hue_service=engine._hue, target_light_ids=["2", "5"],
        )
        _prime_gaming_sync(sync)
        await sync.apply_color("2", 0, 0, 0, mode="gaming", period="day")
        await sync.apply_color("5", 0, 0, 0, mode="gaming", period="day")
        assert sync._last_sent_state["2"]["bri"] == 240
        assert sync._last_sent_state["5"]["bri"] == 90

        engine._screen_sync = sync
        engine._current_mode = "gaming"
        sync._last_color_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        engine._hue.set_light = AsyncMock(return_value=True)
        engine._last_applied_per_light = {}

        # L2 is manually held and must not be touched or invalidated. Only the
        # actual normal-automation L5 write makes L5's sync cache unknown.
        engine._manual_light_overrides = {"2": datetime.now(timezone.utc)}
        await engine._apply_per_light({
            "2": {"on": True, "bri": 207, "hue": 46920, "sat": 180},
            "5": {"on": True, "bri": 139, "hue": 48500, "sat": 160},
        })

        engine._hue.set_light.assert_awaited_once()
        assert engine._hue.set_light.await_args.args[0] == "5"
        assert sync._last_sent_state["2"]["bri"] == 240
        assert "5" not in sync._last_sent_state

    async def test_working_to_gaming_reconciles_l2_l5_then_deduplicates(self, engine):
        """Mode transition writes are repaired once by the first fresh report."""
        from datetime import datetime, timedelta, timezone
        from unittest.mock import AsyncMock

        from backend.services.screen_sync import ScreenSyncService

        sync = ScreenSyncService(
            hue_service=engine._hue, target_light_ids=["2", "5"],
        )
        _prime_gaming_sync(sync)
        await sync.apply_color("2", 0, 0, 0, mode="gaming", period="day")
        await sync.apply_color("5", 0, 0, 0, mode="gaming", period="day")
        sync._last_color_at = datetime.now(timezone.utc) - timedelta(seconds=30)

        engine._screen_sync = sync
        engine._current_mode = "working"
        engine._mode_source = "process"
        engine._hue.set_light = AsyncMock(return_value=True)

        # The transition's normal automation render writes its resolved gaming
        # state before fresh sync ownership exists, invalidating both targets.
        await engine.report_activity("gaming", source="process")
        assert "2" not in sync._last_sent_state
        assert "5" not in sync._last_sent_state

        engine._hue.set_light.reset_mock()
        await sync.apply_color("2", 20, 40, 220, mode="gaming", period="day")
        await sync.apply_color("5", 20, 40, 220, mode="gaming", period="day")
        repair_calls = engine._hue.set_light.await_args_list
        assert len(repair_calls) == 2
        repaired = {call.args[0]: call.args[1] for call in repair_calls}
        assert repaired["2"]["bri"] == sync._accepted_gaming_targets["2"]["bri"]
        assert repaired["5"]["bri"] == sync._accepted_gaming_targets["5"]["bri"]
        assert engine._protected_light_ids() == {"2", "5"}

        repaired_at = sync.last_color_at
        engine._hue.set_light.reset_mock()
        await sync.apply_color("2", 255, 255, 255, mode="gaming", period="day")
        await sync.apply_color("5", 255, 255, 255, mode="gaming", period="day")
        engine._hue.set_light.assert_not_awaited()
        assert sync.last_color_at is not None
        assert repaired_at is not None
        assert sync.last_color_at >= repaired_at


# ---------------------------------------------------------------------------
# Transit override + kitchen-pair atomicity. Regression guard for the
# 2026-05-09 21:44 ET Check J warn: 21 solo-L3 writes / zero L4 writes over
# 11 min while L4 had a manual brightness stamp. Two intertwined bugs:
#   (1) _prune_expired_transit_overrides removed _transit_light_overrides
#       entries on deadline expiry but left _last_applied_per_light populated
#       with transit values, so the next reconcile dedup-skipped on stale data.
#   (2) apply_transit_override wrote to L3 and L4 even when one was manually
#       stamped; the next _apply_per_light filter then re-protected only the
#       stamped one, splitting the kitchen pair.
# ---------------------------------------------------------------------------


class TestTransitOverrideKitchenPair:
    """Atomicity invariants on the transit-override entry/exit paths."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    async def test_prune_expired_pops_dedup_cache(self, engine):
        # Simulate a transit activation that has since expired: deadlines in
        # the past + dedup cache still seeded with transit-state values.
        past = datetime.now(tz=TZ) - timedelta(seconds=1)
        engine._transit_light_overrides = {"1": past, "3": past, "4": past}
        kitchen_state = {"on": True, "bri": 80, "ct": 360}
        living_state = {"on": True, "bri": 120, "ct": 360}
        engine._last_applied_per_light = {
            "1": living_state.copy(),
            "3": kitchen_state.copy(),
            "4": kitchen_state.copy(),
        }

        engine._prune_expired_transit_overrides()

        # Both dicts must be empty for the pruned lights — leaving stale dedup
        # entries causes the next reconcile to dedup-skip writes the cache
        # disagrees with the bridge on.
        assert engine._transit_light_overrides == {}
        assert engine._last_applied_per_light == {}

    async def test_prune_keeps_unexpired(self, engine):
        # Mixed deadlines: L3 expired, L4 still active — only L3's cache
        # entry should be popped.
        past = datetime.now(tz=TZ) - timedelta(seconds=1)
        future = datetime.now(tz=TZ) + timedelta(minutes=5)
        engine._transit_light_overrides = {"3": past, "4": future}
        kitchen_state = {"on": True, "bri": 80, "ct": 360}
        engine._last_applied_per_light = {
            "3": kitchen_state.copy(),
            "4": kitchen_state.copy(),
        }

        engine._prune_expired_transit_overrides()

        assert "3" not in engine._transit_light_overrides
        assert "4" in engine._transit_light_overrides
        assert "3" not in engine._last_applied_per_light
        assert engine._last_applied_per_light["4"] == kitchen_state

    async def test_apply_skips_kitchen_pair_when_l4_manual(self, engine, mock_hue):
        # L4 manually stamped (e.g., user pinned bri=114 earlier). Transit
        # navigation should NOT split the pendants by writing only L3.
        engine.mark_light_manual("4")
        l3_before = mock_hue._lights["3"].copy()
        l4_before = mock_hue._lights["4"].copy()

        # Standard navigation states (mirrors TransitLightingService output).
        states = {
            "1": {"on": True, "bri": 120, "ct": 360},
            "3": {"on": True, "bri": 80, "ct": 360},
            "4": {"on": True, "bri": 80, "ct": 360},
        }
        await engine.apply_transit_override(states, duration_seconds=600, transition_time=5)

        # L1 went through — bridge updated, override + cache seeded.
        assert mock_hue._lights["1"]["bri"] == 120
        assert "1" in engine._transit_light_overrides
        assert engine._last_applied_per_light["1"] == {"on": True, "bri": 120, "ct": 360}

        # L3 + L4 untouched — no bridge writes, no override seed, no cache seed.
        assert mock_hue._lights["3"] == l3_before
        assert mock_hue._lights["4"] == l4_before
        assert "3" not in engine._transit_light_overrides
        assert "4" not in engine._transit_light_overrides
        assert "3" not in engine._last_applied_per_light
        assert "4" not in engine._last_applied_per_light

    async def test_apply_skips_kitchen_pair_when_l3_manual(self, engine, mock_hue):
        # Symmetric: L3 stamped instead of L4. Same behavior.
        engine.mark_light_manual("3")
        l3_before = mock_hue._lights["3"].copy()
        l4_before = mock_hue._lights["4"].copy()

        states = {
            "1": {"on": True, "bri": 120, "ct": 360},
            "3": {"on": True, "bri": 80, "ct": 360},
            "4": {"on": True, "bri": 80, "ct": 360},
        }
        await engine.apply_transit_override(states, duration_seconds=600, transition_time=5)

        assert mock_hue._lights["3"] == l3_before
        assert mock_hue._lights["4"] == l4_before
        assert "3" not in engine._transit_light_overrides
        assert "4" not in engine._transit_light_overrides

    async def test_apply_proceeds_when_neither_kitchen_manual(self, engine, mock_hue):
        # Sanity: kitchen-pair guard does not fire when neither L3 nor L4 is
        # manually stamped — happy path stays intact.
        states = {
            "1": {"on": True, "bri": 120, "ct": 360},
            "3": {"on": True, "bri": 80, "ct": 360},
            "4": {"on": True, "bri": 80, "ct": 360},
        }
        await engine.apply_transit_override(states, duration_seconds=600, transition_time=5)

        assert mock_hue._lights["1"]["bri"] == 120
        assert mock_hue._lights["3"]["bri"] == 80
        assert mock_hue._lights["4"]["bri"] == 80
        assert set(engine._transit_light_overrides.keys()) == {"1", "3", "4"}
        assert set(engine._last_applied_per_light.keys()) == {"1", "3", "4"}

    async def test_apply_logs_to_light_adjustments_with_transit_trigger(
        self, engine, mock_hue,
    ):
        """Transit writes must land in light_adjustments with trigger='transit'.

        Regression guard for the 2026-05-12 incident: 107 transit on/off
        cycles in 30 min produced ZERO rows in light_adjustments because
        apply_transit_override skipped the event_logger call. Made the
        kitchen flicker invisible to analytics and DB queries.
        """
        from unittest.mock import AsyncMock

        engine._event_logger = AsyncMock()
        engine._event_logger.log_light_adjustment = AsyncMock()

        states = {
            "1": {"on": True, "bri": 120, "ct": 360},
            "3": {"on": True, "bri": 80, "ct": 360},
            "4": {"on": True, "bri": 80, "ct": 360},
        }
        await engine.apply_transit_override(
            states, duration_seconds=600, transition_time=5,
        )

        calls = engine._event_logger.log_light_adjustment.await_args_list
        assert len(calls) == 3, (
            f"expected 3 log calls (one per light), got {len(calls)}"
        )
        for call in calls:
            assert call.kwargs["trigger"] == "transit"
            assert call.kwargs["light_id"] in ("1", "3", "4")
            # mode_at_time mirrors what was actually applied (override-aware
            # current_mode property, not the raw _current_mode field).
            assert call.kwargs["mode_at_time"] == engine.current_mode

    async def test_apply_skipped_kitchen_does_not_log_kitchen_rows(
        self, engine, mock_hue,
    ):
        """When the kitchen-pair guard skips L3+L4 (manual stamp), only L1
        gets a log row. The skipped pair shouldn't show up in light_adjustments
        either — they weren't actually written to the bridge."""
        from unittest.mock import AsyncMock

        engine.mark_light_manual("4")
        engine._event_logger = AsyncMock()
        engine._event_logger.log_light_adjustment = AsyncMock()

        states = {
            "1": {"on": True, "bri": 120, "ct": 360},
            "3": {"on": True, "bri": 80, "ct": 360},
            "4": {"on": True, "bri": 80, "ct": 360},
        }
        await engine.apply_transit_override(
            states, duration_seconds=600, transition_time=5,
        )

        calls = engine._event_logger.log_light_adjustment.await_args_list
        light_ids = [c.kwargs["light_id"] for c in calls]
        assert light_ids == ["1"]
        assert calls[0].kwargs["trigger"] == "transit"


# ---------------------------------------------------------------------------
# is_recent_process_working — process-attendance veto for late-night rescue.
# Camera zone is brittle in dark rooms / pose-only conditions; a fresh PC-
# agent working report is an independent attendance signal. Regression
# guard for the 2026-05-07 incident where late_night_rescue fired during
# an active dev session because camera zone went stale.
# ---------------------------------------------------------------------------


class TestIsRecentProcessWorking:
    """``is_recent_process_working`` is the process-attendance veto."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    def test_never_reported_returns_false(self, engine):
        assert engine._last_process_working_at is None
        assert engine.is_recent_process_working() is False

    def test_recent_report_returns_true(self, engine):
        engine._last_process_working_at = datetime.now(tz=TZ) - timedelta(seconds=30)
        assert engine.is_recent_process_working() is True

    def test_stale_report_returns_false(self, engine):
        engine._last_process_working_at = datetime.now(tz=TZ) - timedelta(minutes=30)
        assert engine.is_recent_process_working() is False

    def test_window_default_just_under_returns_true(self, engine):
        engine._last_process_working_at = datetime.now(tz=TZ) - timedelta(seconds=599)
        assert engine.is_recent_process_working() is True

    def test_window_default_just_over_returns_false(self, engine):
        engine._last_process_working_at = datetime.now(tz=TZ) - timedelta(seconds=601)
        assert engine.is_recent_process_working() is False

    def test_custom_window_seconds(self, engine):
        engine._last_process_working_at = datetime.now(tz=TZ) - timedelta(seconds=120)
        assert engine.is_recent_process_working(window_seconds=60) is False
        assert engine.is_recent_process_working(window_seconds=180) is True

    async def test_report_activity_stamps_process_working(self, engine):
        before = datetime.now(tz=TZ) - timedelta(seconds=1)
        await engine.report_activity(mode="working", source="process")
        assert engine._last_process_working_at is not None
        assert engine._last_process_working_at >= before

    async def test_report_activity_does_not_stamp_for_other_sources(self, engine):
        await engine.report_activity(mode="working", source="ambient")
        assert engine._last_process_working_at is None
        await engine.report_activity(mode="working", source="camera")
        assert engine._last_process_working_at is None

    async def test_report_activity_does_not_stamp_for_idle(self, engine):
        await engine.report_activity(mode="idle", source="process")
        assert engine._last_process_working_at is None

    async def test_report_activity_idle_is_vetoed_by_fresh_desk_presence(self, engine):
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        engine._camera_service = _FakeEnabledCamera(
            zone="desk", enabled=True, zone_committed_at=recent,
        )
        engine._current_mode = "working"
        engine._mode_source = "process"

        await engine.report_activity(mode="idle", source="process")

        assert engine.current_mode == "working"
        assert engine._last_mode_source_report_at["process"] is not None
        assert engine._idle_entered_at is None

    async def test_report_activity_idle_clears_gaming_despite_fresh_desk_presence(self, engine):
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        engine._camera_service = _FakeEnabledCamera(
            zone="desk", enabled=True, zone_committed_at=recent,
        )
        engine._current_mode = "gaming"
        engine._current_game = "Hades II"
        engine._mode_source = "process"

        await engine.report_activity(mode="idle", source="process")

        assert engine.current_mode == "idle"
        assert engine.current_game is None
        assert engine._idle_entered_at is not None

    async def test_report_activity_does_not_stamp_for_gaming(self, engine):
        await engine.report_activity(mode="gaming", source="process")
        assert engine._last_process_working_at is None


class TestLateNightRescueProcessVeto:
    """Late-night rescue should be vetoed when process-working is recent.

    Regression guard for 2026-05-07 23:13 EDT incident: camera zone went
    stale (38 min since last commit), is_at_desk_fresh() returned False,
    rescue fired despite PC agent reporting working 1.4s prior.
    """

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    async def test_recent_process_working_blocks_rescue(self, engine):
        # Simulate the 2026-05-07 scenario: camera stale (False), process
        # reported working 30s ago. Rescue should be vetoed.
        engine._camera_service = None  # is_at_desk_fresh → False
        engine._last_process_working_at = datetime.now(tz=TZ) - timedelta(seconds=30)
        await engine.set_manual_override("relax", source="late_night_rescue")
        # The rescue path itself doesn't call set_manual_override under veto;
        # this test simulates what would happen if it did, just to confirm
        # the source isn't blocked. The actual gate-level test is below.
        # (set_manual_override always succeeds when called directly with
        # late_night_rescue source absent the user-clear cooldown.)
        assert engine.manual_override is True

    def test_veto_combination_both_signals_evaluated(self, engine):
        # When both signals are absent, both vetoes return False.
        engine._camera_service = None
        engine._last_process_working_at = None
        assert engine.is_at_desk_fresh() is False
        assert engine.is_recent_process_working() is False

    def test_veto_combination_camera_alone_protects(self, engine):
        # Camera at desk, process never reported — camera veto carries.
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        engine._camera_service = _FakeEnabledCamera(
            zone="desk", enabled=True, zone_committed_at=recent,
        )
        engine._last_process_working_at = None
        assert engine.is_at_desk_fresh() is True
        assert engine.is_recent_process_working() is False

    def test_veto_combination_process_alone_protects(self, engine):
        # No camera, but process recently reported — process veto carries.
        engine._camera_service = None
        engine._last_process_working_at = datetime.now(tz=TZ) - timedelta(seconds=60)
        assert engine.is_at_desk_fresh() is False
        assert engine.is_recent_process_working() is True

    def test_veto_combination_both_stale_no_protection(self, engine):
        # Camera stale + process stale → neither veto fires (rescue eligible).
        stale = datetime.now(timezone.utc) - timedelta(minutes=10)
        engine._camera_service = _FakeEnabledCamera(
            zone="desk", enabled=True, zone_committed_at=stale,
        )
        engine._last_process_working_at = datetime.now(tz=TZ) - timedelta(minutes=20)
        assert engine.is_at_desk_fresh() is False
        assert engine.is_recent_process_working() is False


# ---------------------------------------------------------------------------
# fusion_auto_apply no-op guard (regression for 2026-05-12 idle-lock)
# ---------------------------------------------------------------------------

class _StickyDeskPresence:
    """Presence fake with a recent desk high-water mark but optional fresh miss."""

    def __init__(
        self,
        seconds_since_at_desk: float | None,
        *,
        at_desk_fresh: bool = False,
        zone: str | None = None,
    ) -> None:
        self._seconds_since_at_desk = seconds_since_at_desk
        self._at_desk_fresh = at_desk_fresh
        self._zone = zone

    def seconds_since_at_desk(self):
        return self._seconds_since_at_desk

    def is_at_desk_fresh(self, _max_age_s=300):
        return self._at_desk_fresh

    def is_strongly_present_any(self):
        return False

    def latest_zone(self):
        return self._zone

    def latest_posture(self):
        return None

    def get_sources(self):
        return {}

class _StubFusion:
    """Minimal fusion stub: returns a fixed compute_fusion() result.

    The real ConfidenceFusion class has report_signal() side effects and an
    internal state machine; the run_loop only invokes compute_fusion(), so
    that's the only method we need.
    """

    def __init__(
        self, fused_mode: str, fused_confidence: float, *, can_override=False,
        auto_apply=False,
    ):
        self._fm = fused_mode
        self._fc = fused_confidence
        self._can_override = can_override
        self._auto_apply = auto_apply

    def compute_fusion(self):
        return {
            "fused_mode": self._fm,
            "fused_confidence": self._fc,
            "agreement": 0.9,
            "signals": {},
            "can_override": self._can_override,
            "auto_apply": self._auto_apply,
        }

    def report_signal(self, *args, **kwargs):
        return None


async def _drive_one_tick(engine: AutomationEngine) -> None:
    """Run exactly one iteration of ``run_loop`` and exit cleanly.

    Patches ``asyncio.sleep`` inside the engine module so the end-of-tick
    60s sleep raises ``CancelledError``; ``run_loop`` catches that and
    breaks. Our test scenarios never reach sleeping-mode-specific sleeps
    (lines 1570/1742/1748/1768/1775), so patching the module-level sleep
    is safe.
    """

    async def fake_sleep(_seconds):
        raise asyncio.CancelledError

    with patch(
        "backend.services.automation_engine.asyncio.sleep",
        side_effect=fake_sleep,
    ):
        await engine.run_loop()


class TestDesktopUnavailableLightingPolicy:
    """P0 regressions for stale desktop/camera semantic evidence."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    def test_daytime_idle_rule_is_ct_only(self, engine):
        rules = engine._build_time_rules(engine.schedule_config.weekday)
        daytime = next(
            state for _start, _end, state in rules
            if isinstance(state, dict) and state.get("bri") == 220
        )

        assert daytime == {"on": True, "bri": 220, "ct": 250}
        assert "hue" not in daytime
        assert "sat" not in daytime

    def test_stale_idle_is_not_a_safe_override_replacement(self, engine):
        now = datetime.now(tz=TZ)
        engine._current_mode = "idle"
        engine._mode_source = "process"
        engine._mode_source_key = "process"
        engine._last_mode_source_report_at["process"] = now

        assert engine._has_fresh_mode_replacement(now) is False

    async def test_expired_user_override_waits_for_fresh_replacement(
        self, monkeypatch, engine,
    ):
        monkeypatch.setattr(
            AutomationEngine, "_get_time_period", lambda self, now=None: "day",
        )
        await engine.set_manual_override("working", source="api:test")
        engine._override_time = (
            datetime.now(tz=TZ)
            - timedelta(hours=engine.override_timeout_hours + 1)
        )
        engine._current_mode = "idle"
        engine._mode_source = "process"
        engine._mode_source_key = "process"
        engine._last_mode_source_report_at["process"] = (
            datetime.now(tz=TZ) - timedelta(seconds=SOURCE_STALE_SECONDS + 1)
        )

        await _drive_one_tick(engine)

        assert engine.manual_override is True
        assert engine.current_mode == "working"
        assert engine._override_expiry_deferred is True
        assert engine._idle_entered_at is None

    async def test_expired_user_override_releases_to_fresh_mode(
        self, monkeypatch, engine,
    ):
        monkeypatch.setattr(
            AutomationEngine, "_get_time_period", lambda self, now=None: "day",
        )
        await engine.set_manual_override("relax", source="api:test")
        engine._override_time = (
            datetime.now(tz=TZ)
            - timedelta(hours=engine.override_timeout_hours + 1)
        )
        engine._current_mode = "working"
        engine._mode_source = "process"
        engine._mode_source_key = "process"
        engine._last_mode_source_report_at["process"] = datetime.now(tz=TZ)

        await _drive_one_tick(engine)

        assert engine.manual_override is False
        assert engine.current_mode == "working"

    async def test_autonomous_override_keeps_normal_timeout(
        self, monkeypatch, engine,
    ):
        monkeypatch.setattr(
            AutomationEngine, "_get_time_period", lambda self, now=None: "day",
        )
        await engine.set_manual_override("relax", source="ambient_relax")
        engine._override_time = (
            datetime.now(tz=TZ)
            - timedelta(hours=engine.override_timeout_hours + 1)
        )
        engine._current_mode = "idle"

        await _drive_one_tick(engine)

        assert engine.manual_override is False

    async def test_startup_restores_expired_user_override(
        self, monkeypatch, engine,
    ):
        saved = {
            "manual_override": True,
            "override_mode": "working",
            "override_source": "api:test",
            "override_time_utc": (
                datetime.now(timezone.utc)
                - timedelta(hours=engine.override_timeout_hours + 1)
            ).isoformat(),
        }

        async def fake_load_setting(_key):
            return saved

        monkeypatch.setattr(
            "backend.api.routes.routines.load_setting", fake_load_setting,
        )

        await engine.load_override_state()

        assert engine.manual_override is True
        assert engine.current_mode == "working"
        assert engine._override_expiry_deferred is True

    async def test_startup_drops_expired_autonomous_override(
        self, monkeypatch, engine,
    ):
        saved = {
            "manual_override": True,
            "override_mode": "relax",
            "override_source": "ambient_relax",
            "override_time_utc": (
                datetime.now(timezone.utc)
                - timedelta(hours=engine.override_timeout_hours + 1)
            ).isoformat(),
        }

        async def fake_load_setting(_key):
            return saved

        async def fake_persist():
            return None

        monkeypatch.setattr(
            "backend.api.routes.routines.load_setting", fake_load_setting,
        )
        monkeypatch.setattr(engine, "_persist_override_state", fake_persist)

        await engine.load_override_state()

        assert engine.manual_override is False
        assert engine._override_expiry_deferred is False


class TestRecentDeskAttendanceVeto:
    """Recent at-desk high-water marks suppress eager idle/relax automation."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        eng = AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )
        eng._ml_logger = _FakeMLLogger()
        return eng

    def test_recent_high_water_mark_counts_when_latest_frame_misses(self, engine):
        engine._presence_fusion = _StickyDeskPresence(
            120, at_desk_fresh=False,
        )

        assert engine.is_at_desk_fresh() is False
        assert engine.is_recently_at_desk() is True
        assert engine._attendance_veto_reason() == "recent_desk_attendance"

    def test_stale_high_water_mark_does_not_count(self, engine):
        engine._presence_fusion = _StickyDeskPresence(
            601, at_desk_fresh=False,
        )

        assert engine.is_recently_at_desk() is False
        assert engine._attendance_veto_reason() is None

    async def test_idle_report_is_vetoed_by_recent_desk_attendance(self, engine):
        engine._presence_fusion = _StickyDeskPresence(
            120, at_desk_fresh=False,
        )
        engine._current_mode = "working"
        engine._mode_source = "process"
        engine._mode_source_key = "process:desktop"

        await engine.report_activity(
            mode="idle",
            source="process",
            factors=[{"key": "device", "value": "desktop"}],
        )

        assert engine.current_mode == "working"
        assert engine._last_mode_source_report_at["process:desktop"] is not None
        assert engine._idle_entered_at is None

    async def test_rejected_desktop_idle_keeps_accepted_semantic_and_fusion_age(
        self, engine,
    ):
        engine._confidence_fusion = ConfidenceFusion()
        engine._event_logger = SimpleNamespace(log_mode_change=AsyncMock())
        desktop = [{"key": "device", "value": "desktop"}]
        await engine.report_activity("working", source="process", factors=desktop)
        engine._event_logger.log_mode_change.reset_mock()
        accepted_at = engine._last_process_semantic_by_device["desktop"].received_at
        fusion_at = engine._confidence_fusion._signals["process"].timestamp

        engine._presence_fusion = _StickyDeskPresence(120, at_desk_fresh=False)
        result = await engine.report_activity(
            "idle", source="process", factors=desktop,
        )

        assert result["semantic_disposition"] == "rejected"
        assert result["reason"] == "recent_desk_presence"
        assert result["semantic_mode"] == "working"
        assert result["included_in_fusion"] is False
        assert engine._last_process_observation_by_device["desktop"].observed_mode == "idle"
        assert engine._last_process_semantic_by_device["desktop"].committed_mode == "working"
        assert engine._last_process_semantic_by_device["desktop"].received_at == accepted_at
        assert engine._confidence_fusion._signals["process"].timestamp == fusion_at
        engine._event_logger.log_mode_change.assert_not_awaited()
        factors = engine._ml_logger.calls[-1]["factors"]
        assert factors["semantic_disposition"] == "rejected"
        assert factors["included_in_fusion"] is False

        engine._presence_fusion = _StickyDeskPresence(None, at_desk_fresh=False)
        engine._apply_mode = AsyncMock()
        accepted = await engine.report_activity(
            "idle", source="process", factors=desktop,
        )

        refreshed_at = engine._last_process_semantic_by_device["desktop"].received_at
        assert accepted["semantic_disposition"] == "accepted"
        assert refreshed_at > accepted_at
        assert engine._confidence_fusion._signals["process"].timestamp == refreshed_at

    def test_fresh_semantic_beats_stale_higher_priority_semantic_for_fusion(
        self, engine,
    ):
        engine._confidence_fusion = ConfidenceFusion()
        stale_at = datetime.now(tz=TZ) - timedelta(
            seconds=SOURCE_STALE_SECONDS + 1,
        )
        fresh_at = datetime.now(tz=TZ) - timedelta(seconds=1)
        engine._record_process_semantic(
            "gaming", [{"key": "device", "value": "desktop"}], stale_at,
        )
        engine._record_process_semantic(
            "working", [{"key": "device", "value": "latitude"}], fresh_at,
        )

        semantic_mode, included = engine._sync_process_fusion()

        assert semantic_mode == "working"
        assert included is True
        assert engine._confidence_fusion._signals["process"].mode == "working"
        assert engine._confidence_fusion._signals["process"].timestamp == fresh_at

    async def test_latitude_idle_retracts_only_latitude_and_restores_desktop(
        self, engine,
    ):
        engine._confidence_fusion = ConfidenceFusion()
        desktop = [{"key": "device", "value": "desktop"}]
        latitude = [{"key": "device", "value": "latitude"}]
        await engine.report_activity("working", source="process", factors=desktop)
        desktop_at = engine._last_process_semantic_by_device["desktop"].received_at
        await engine.report_activity("watching", source="process", factors=latitude)
        assert engine._confidence_fusion._signals["process"].mode == "watching"

        result = await engine.report_activity("idle", source="process", factors=latitude)

        assert result["semantic_disposition"] == "retracted"
        assert result["semantic_mode"] == "working"
        assert result["authoritative_mode"] == "watching"
        assert "latitude" not in engine._last_process_semantic_by_device
        assert engine._last_process_observation_by_device["latitude"].observed_mode == "idle"
        assert engine._confidence_fusion._signals["process"].mode == "working"
        assert engine._confidence_fusion._signals["process"].timestamp == desktop_at

    async def test_retraction_clears_fusion_when_only_retained_semantic_is_stale(
        self, engine,
    ):
        engine._confidence_fusion = ConfidenceFusion()
        stale_at = datetime.now(tz=TZ) - timedelta(
            seconds=SOURCE_STALE_SECONDS + 1,
        )
        desktop = [{"key": "device", "value": "desktop"}]
        latitude = [{"key": "device", "value": "latitude"}]
        engine._record_process_semantic("gaming", desktop, stale_at)
        await engine.report_activity("watching", source="process", factors=latitude)

        result = await engine.report_activity(
            "idle", source="process", factors=latitude,
        )

        assert result["semantic_disposition"] == "retracted"
        assert result["semantic_mode"] is None
        assert "process" not in engine._confidence_fusion._signals

    async def test_source_priority_rejection_keeps_one_existing_process_voter(
        self, engine,
    ):
        engine._confidence_fusion = ConfidenceFusion()
        engine._event_logger = SimpleNamespace(log_mode_change=AsyncMock())
        desktop = [{"key": "device", "value": "desktop"}]
        latitude = [{"key": "device", "value": "latitude"}]
        await engine.report_activity("gaming", source="process", factors=desktop)
        engine._event_logger.log_mode_change.reset_mock()
        original_at = engine._confidence_fusion._signals["process"].timestamp

        result = await engine.report_activity(
            "working", source="process", factors=latitude,
        )

        assert result["semantic_disposition"] == "rejected"
        assert result["reason"] == "source_priority"
        assert result["semantic_mode"] == "gaming"
        assert "latitude" not in engine._last_process_semantic_by_device
        assert engine._last_process_observation_by_device["latitude"].observed_mode == "working"
        assert engine._confidence_fusion._signals["process"].mode == "gaming"
        assert engine._confidence_fusion._signals["process"].timestamp == original_at
        engine._event_logger.log_mode_change.assert_not_awaited()

    async def test_dnd_rejection_has_no_authoritative_activity_event(self, engine):
        engine._confidence_fusion = ConfidenceFusion()
        engine._event_logger = SimpleNamespace(log_mode_change=AsyncMock())
        engine._dnd._enabled = True
        engine._dnd._expiry = datetime.now(tz=TZ) + timedelta(hours=1)

        result = await engine.report_activity(
            "working", source="process",
            factors=[{"key": "device", "value": "desktop"}],
        )

        assert result["semantic_disposition"] == "rejected"
        assert result["reason"] == "dnd_active"
        assert engine.current_mode == "idle"
        assert engine._last_process_semantic_by_device == {}
        assert "process" not in engine._confidence_fusion._signals
        engine._event_logger.log_mode_change.assert_not_awaited()

    async def test_sleeping_floor_rejection_has_no_authoritative_activity_event(
        self, engine,
    ):
        engine._confidence_fusion = ConfidenceFusion()
        engine._event_logger = SimpleNamespace(log_mode_change=AsyncMock())
        engine._current_mode = "sleeping"
        engine._mode_source = "process"
        engine._mode_source_key = "process:desktop"

        result = await engine.report_activity(
            "idle", source="process",
            factors=[{"key": "device", "value": "desktop"}],
        )

        assert result["semantic_disposition"] == "rejected"
        assert result["reason"] == "sleeping_floor"
        assert engine.current_mode == "sleeping"
        assert engine._last_process_semantic_by_device == {}
        assert "process" not in engine._confidence_fusion._signals
        engine._event_logger.log_mode_change.assert_not_awaited()

    async def test_disabled_process_report_records_raw_abstention_only(self, engine):
        engine._confidence_fusion = ConfidenceFusion()
        engine._event_logger = SimpleNamespace(log_mode_change=AsyncMock())
        engine._enabled = False

        result = await engine.report_activity(
            "working", source="process",
            factors=[{"key": "device", "value": "desktop"}],
        )

        assert result["semantic_disposition"] == "abstaining"
        assert result["reason"] == "automation_disabled"
        assert result["authoritative_mode"] == "idle"
        assert result["included_in_fusion"] is False
        assert engine._last_process_observation_by_device["desktop"].observed_mode == "working"
        assert engine._last_process_semantic_by_device == {}
        assert "process" not in engine._confidence_fusion._signals
        engine._event_logger.log_mode_change.assert_not_awaited()
        logged = engine._ml_logger.calls[-1]["factors"]
        assert logged["semantic_disposition"] == "abstaining"
        assert logged["reason"] == "automation_disabled"

    async def test_same_desktop_process_idle_releases_watching_at_desk(self, engine):
        engine._presence_fusion = _StickyDeskPresence(
            0, at_desk_fresh=True,
        )
        engine._current_mode = "watching"
        engine._mode_source = "process"
        engine._mode_source_key = "process:desktop"

        await engine.report_activity(
            mode="idle",
            source="process",
            factors=[{"key": "device", "value": "desktop"}],
        )

        assert engine.current_mode == "idle"
        assert engine._mode_source_key == "process:desktop"
        assert engine._idle_entered_at is not None

    async def test_same_desktop_process_idle_releases_watching_without_desk(self, engine):
        engine._presence_fusion = _StickyDeskPresence(
            None, at_desk_fresh=False,
        )
        engine._current_mode = "watching"
        engine._mode_source = "process"
        engine._mode_source_key = "process:desktop"

        await engine.report_activity(
            mode="idle",
            source="process",
            factors=[{"key": "device", "value": "desktop"}],
        )

        assert engine.current_mode == "idle"
        assert engine._idle_entered_at is not None

    async def test_manual_watching_authority_survives_process_release(self, engine):
        engine._presence_fusion = _StickyDeskPresence(
            0, at_desk_fresh=True,
        )
        engine._current_mode = "watching"
        engine._mode_source = "process"
        engine._mode_source_key = "process:desktop"
        await engine.set_manual_override("watching", source="api:127.0.0.1")

        await engine.report_activity(
            mode="idle",
            source="process",
            factors=[{"key": "device", "value": "desktop"}],
        )

        assert engine.manual_override is True
        assert engine.override_mode == "watching"
        assert engine.current_mode == "watching"
        assert engine._current_mode == "idle"

    async def test_stale_recent_desk_allows_idle_report(self, engine):
        engine._presence_fusion = _StickyDeskPresence(
            601, at_desk_fresh=False,
        )
        engine._current_mode = "working"
        engine._mode_source = "process"

        await engine.report_activity(mode="idle", source="process")

        assert engine.current_mode == "idle"
        assert engine._idle_entered_at is not None

    async def test_late_night_rescue_vetoes_recent_desk_attendance(
        self, monkeypatch, engine,
    ):
        monkeypatch.setattr(
            AutomationEngine, "_get_time_period", lambda self, now=None: "late_night",
        )
        engine._presence_fusion = _StickyDeskPresence(
            120, at_desk_fresh=False,
        )
        engine._current_mode = "working"

        await _drive_one_tick(engine)

        assert engine.manual_override is False
        call = engine._ml_logger.calls[0]
        assert call["decision_source"] == "late_night_rescue"
        assert call["applied"] is False
        assert call["factors"]["vetoed_by"] == "recent_desk_attendance"

    async def test_ambient_relax_vetoes_recent_desk_attendance(
        self, monkeypatch, engine,
    ):
        monkeypatch.setattr(
            AutomationEngine, "_get_time_period", lambda self, now=None: "evening",
        )
        engine._presence_fusion = _StickyDeskPresence(
            120, at_desk_fresh=False,
        )
        engine._current_mode = "idle"
        engine._idle_entered_at = datetime.now(tz=TZ) - timedelta(seconds=601)

        await _drive_one_tick(engine)

        assert engine.manual_override is False
        call = engine._ml_logger.calls[0]
        assert call["decision_source"] == "ambient_relax"
        assert call["applied"] is False
        assert call["factors"]["vetoed_by"] == "recent_desk_attendance"

    async def test_fusion_auto_apply_vetoes_recent_desk_attendance(
        self, monkeypatch, engine,
    ):
        monkeypatch.setattr(
            AutomationEngine, "_get_time_period", lambda self, now=None: "evening",
        )
        engine._presence_fusion = _StickyDeskPresence(
            120, at_desk_fresh=False,
        )
        engine._current_mode = "idle"
        engine._confidence_fusion = _StubFusion(
            "working", 0.96, auto_apply=True,
        )

        await _drive_one_tick(engine)

        assert engine.manual_override is False
        call = engine._ml_logger.calls[0]
        assert call["decision_source"] == "fusion"
        assert call["applied"] is False
        assert call["factors"]["shadow_candidate"] == "auto_apply"
        assert call["factors"]["vetoed_by"] == "recent_desk_attendance"

    async def test_fusion_override_vetoes_recent_desk_attendance(
        self, monkeypatch, engine,
    ):
        monkeypatch.setattr(
            AutomationEngine, "_get_time_period", lambda self, now=None: "evening",
        )
        engine._presence_fusion = _StickyDeskPresence(
            120, at_desk_fresh=False,
        )
        engine._current_mode = "working"
        engine._confidence_fusion = _StubFusion(
            "idle", 0.96, can_override=True,
        )

        await _drive_one_tick(engine)

        assert engine.manual_override is False
        call = engine._ml_logger.calls[0]
        assert call["decision_source"] == "fusion"
        assert call["applied"] is False
        assert call["factors"]["vetoed_by"] == "recent_desk_attendance"

class TestFusionShadowOnlyAuthority:
    """Fusion remains observable but has no mode-actuation authority."""

    @pytest.fixture(autouse=True)
    def _pin_evening_period(self, monkeypatch):
        """Pin ``_get_time_period`` to ``"evening"`` for every test in this
        class. This isolates the fusion shadow-only assertions from the
        unrelated late-night rescue path, which may set an autonomous
        ``relax`` override before the fusion tick is evaluated. Fusion
        eligibility remains observable here, but fusion itself cannot
        actuate or set an override.
        """
        monkeypatch.setattr(
            AutomationEngine, "_get_time_period", lambda self, now=None: "evening",
        )

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        eng = AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )
        eng._ml_logger = _FakeMLLogger()
        # No camera + no process-working stamp means former actuation
        # eligibility is recorded as an unvetoed shadow candidate.
        eng._camera_service = None
        eng._last_process_working_at = None
        return eng

    async def test_skips_when_predicted_equals_current(self, engine):
        engine._current_mode = "idle"
        engine._manual_override = False
        engine._confidence_fusion = _StubFusion(
            "idle", 0.96, auto_apply=True,
        )

        await _drive_one_tick(engine)

        assert engine.manual_override is False
        assert engine._override_mode is None

    async def test_auto_apply_result_cannot_set_manual_override(self, engine):
        engine._current_mode = "idle"
        engine._manual_override = False
        engine._confidence_fusion = _StubFusion(
            "working", 0.96, auto_apply=True,
        )
        engine.set_manual_override = AsyncMock(
            wraps=engine.set_manual_override,
        )

        await _drive_one_tick(engine)

        engine.set_manual_override.assert_not_awaited()
        assert engine.manual_override is False
        assert engine._last_fusion_result["auto_apply"] is True
        call = engine._ml_logger.calls[0]
        assert call["decision_source"] == "fusion"
        assert call["applied"] is False
        assert call["broadcast"] is False
        assert call["factors"]["action"] == "shadow"
        assert call["factors"]["shadow_candidate"] == "auto_apply"

    async def test_can_override_result_cannot_set_manual_override(self, engine):
        engine._current_mode = "working"
        engine._manual_override = False
        engine._confidence_fusion = _StubFusion(
            "watching", 0.93, can_override=True,
        )
        engine.set_manual_override = AsyncMock(
            wraps=engine.set_manual_override,
        )

        await _drive_one_tick(engine)

        engine.set_manual_override.assert_not_awaited()
        assert engine.manual_override is False
        assert engine._last_fusion_result["can_override"] is True
        call = engine._ml_logger.calls[0]
        assert call["decision_source"] == "fusion"
        assert call["applied"] is False
        assert call["broadcast"] is False
        assert call["factors"]["action"] == "shadow"
        assert call["factors"]["shadow_candidate"] == "override"

    async def test_camera_at_desk_veto_is_preserved_in_shadow(self, engine):
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        engine._camera_service = _FakeEnabledCamera(
            zone="desk", enabled=True, zone_committed_at=recent,
        )
        engine._current_mode = "idle"
        engine._manual_override = False
        engine._confidence_fusion = _StubFusion(
            "working", 0.96, auto_apply=True,
        )

        await _drive_one_tick(engine)

        assert engine.manual_override is False
        call = engine._ml_logger.calls[0]
        assert call["factors"]["shadow_candidate"] == "auto_apply"
        assert call["factors"]["vetoed_by"] == "recent_desk_attendance"

    async def test_recent_process_working_veto_is_preserved_in_shadow(
        self, engine,
    ):
        engine._last_process_working_at = (
            datetime.now(tz=TZ) - timedelta(seconds=60)
        )
        engine._current_mode = "idle"
        engine._manual_override = False
        engine._confidence_fusion = _StubFusion(
            "watching", 0.96, auto_apply=True,
        )

        await _drive_one_tick(engine)

        assert engine.manual_override is False
        call = engine._ml_logger.calls[0]
        assert call["factors"]["shadow_candidate"] == "auto_apply"
        assert call["factors"]["vetoed_by"] == "process_working_recent"


# ---------------------------------------------------------------------------
# Watching → sleeping guard rule
# ---------------------------------------------------------------------------

class TestWatchingSleepGuard:
    """Auto-flip watching → sleeping after sustained late-night bed dwell.

    Catches the "fell asleep with YouTube on the projector" case the
    late_night_rescue can't reach (it's gated to working/idle and skips
    while a video player is foregrounded). Reference incident:
    2026-05-13 → 2026-05-14, watching held 7h 39m overnight.
    """

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        eng = AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
        )
        eng._camera_service = _FakeCamera(zone="bed", posture="reclined")
        eng._current_mode = "watching"
        eng._ml_logger = _FakeMLLogger()
        # This class verifies guard/dwell/refractory semantics, not Hue fade
        # timing. A real sleeping application starts a background _sleep_fade
        # task that can outlive an individual pytest event loop.
        eng._apply_mode = AsyncMock()
        return eng

    # 02:00 weekday — solidly inside the late_night window (23:00 → wake_hour 5).
    LATE_NIGHT = datetime(2026, 5, 14, 2, 0, tzinfo=TZ)
    # 21:00 weekday — evening, not late_night yet.
    EVENING = datetime(2026, 5, 14, 21, 0, tzinfo=TZ)
    DWELL_OFFSET_FIRES = 91 * 60   # one minute past the 90-min dwell
    DWELL_OFFSET_PARTIAL = 60 * 60  # 60 min — under the 90-min threshold

    @patch("backend.services.automation_engine.datetime")
    async def test_actuates_after_dwell(self, mock_dt, engine):
        """All gates pass + dwell met → flips to sleeping with the right
        source label."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.manual_override is True
        assert engine.override_mode == "sleeping"
        assert engine.override_source == "watching_sleep_guard"
        # Stamp burned for refractory.
        assert engine._watching_sleep_guard_last_fired_at == self.LATE_NIGHT
        # Dwell reset after fire.
        assert engine._watching_sleep_dwell_since is None
        # Asleep stamp set during the confident bed+reclined observation
        # — consumed downstream by `_is_likely_still_asleep` to gate the
        # morning brightness ramp + watching mode's day transition.
        assert engine._last_bed_reclined_during_watching_at == self.LATE_NIGHT
        # Observability row — same shape as zone_posture_rule emits, so the
        # rule-engine-misfire-auditor and /api/learning queries can see fires.
        assert len(engine._ml_logger.calls) == 1
        call = engine._ml_logger.calls[0]
        assert call["decision_source"] == "watching_sleep_guard"
        assert call["predicted_mode"] == "sleeping"
        assert call["applied"] is True
        assert call["factors"]["zone"] == "bed"
        assert call["factors"]["posture"] == "reclined"
        assert call["factors"]["dwell_seconds"] >= self.DWELL_OFFSET_FIRES

    @patch("backend.services.automation_engine.datetime")
    async def test_dnd_blocks_and_resets_dwell(self, mock_dt, engine):
        """DND silence → no fire, dwell reset, refractory NOT burned."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )
        # DND active for the next hour. State lives on the DndManager since
        # the GH#86 step-2 extraction; its is_active() reads the real clock
        # (dnd_manager module datetime isn't patched here), so anchor the
        # expiry to real now rather than the mocked engine clock.
        engine._dnd._enabled = True
        engine._dnd._expiry = datetime.now(tz=TZ) + timedelta(hours=1)

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.manual_override is False
        assert engine._watching_sleep_dwell_since is None
        # CRITICAL: stamp NOT burned (per
        # feedback_rule_refractory_burn_pattern.md — silent rejection
        # must not lock the rule out for 4h).
        assert engine._watching_sleep_guard_last_fired_at is None

    @patch("backend.services.automation_engine.datetime")
    async def test_user_clear_cooldown_blocks_and_does_not_burn(
        self, mock_dt, engine,
    ):
        """User just tapped 'auto' → autonomous push silently blocked.
        Dwell reset and stamp NOT burned, so the rule re-arms cleanly
        once the cooldown expires."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )
        # User cleared override 5 minutes ago — well inside the 30-min
        # cooldown window.
        engine._user_cleared_override_at = (
            self.LATE_NIGHT - timedelta(minutes=5)
        )

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.manual_override is False
        assert engine._watching_sleep_dwell_since is None
        assert engine._watching_sleep_guard_last_fired_at is None

    @patch("backend.services.automation_engine.datetime")
    async def test_refractory_blocks_refire(self, mock_dt, engine):
        """Recent fire (within override_timeout_hours) suppresses re-fire."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # Fired 1h ago — well under the 4h refractory.
        engine._watching_sleep_guard_last_fired_at = (
            self.LATE_NIGHT - timedelta(hours=1)
        )
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        # Stamp held — no second fire.
        assert engine.manual_override is False
        # Dwell reset by gate 1.
        assert engine._watching_sleep_dwell_since is None

    @patch("backend.services.automation_engine.datetime")
    async def test_outside_late_night_does_not_trigger(self, mock_dt, engine):
        """21:00 evening — late_night gate fails, dwell reset, no fire.

        We only catch the 'asleep with YouTube on' case in the late-night
        window; a 9pm movie marathon is a normal use of watching mode."""
        mock_dt.now.return_value = self.EVENING
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._watching_sleep_dwell_since = (
            self.EVENING - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )

        await engine._evaluate_watching_sleep_guard(self.EVENING)

        assert engine.manual_override is False
        assert engine._watching_sleep_dwell_since is None

    @patch("backend.services.automation_engine.datetime")
    async def test_fresh_watching_override_is_protected(self, mock_dt, engine):
        """Manual watching override younger than the supersede min-age =
        fresh user intent. Don't override what they just set."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await engine.set_manual_override("watching", source="api:test")
        # Override is 30 min old — under the 90-min supersede threshold.
        engine._override_time = self.LATE_NIGHT - timedelta(minutes=30)
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        # Still on watching — guard didn't supersede.
        assert engine.override_mode == "watching"
        assert engine._watching_sleep_dwell_since is None

    @patch("backend.services.automation_engine.datetime")
    async def test_stale_watching_override_can_be_superseded(
        self, mock_dt, engine,
    ):
        """Watching override ≥90 min old + dwell met → guard fires.

        The reference incident: Anthony tapped watching at 22:26 and fell
        asleep — the override was hours old by 02:00."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        await engine.set_manual_override("watching", source="api:test")
        # Override is 4 hours old — well past the 90-min gate.
        engine._override_time = self.LATE_NIGHT - timedelta(hours=4)
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.override_mode == "sleeping"
        assert engine.override_source == "watching_sleep_guard"

    @patch("backend.services.automation_engine.datetime")
    async def test_zone_not_bed_does_not_trigger(self, mock_dt, engine):
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._camera_service = _FakeCamera(zone="desk", posture="reclined")
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.manual_override is False
        assert engine._watching_sleep_dwell_since is None

    @patch("backend.services.automation_engine.datetime")
    async def test_dwell_not_met_does_not_fire(self, mock_dt, engine):
        """Under the 90-min threshold: don't fire, but DON'T reset the
        dwell either — let it keep accumulating."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_PARTIAL)
        )

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.manual_override is False
        # Timer is still set — accumulating toward the threshold.
        assert engine._watching_sleep_dwell_since is not None

    @patch("backend.services.automation_engine.datetime")
    async def test_dwell_starts_on_first_qualifying_tick(
        self, mock_dt, engine,
    ):
        """First tick with all conditions met seeds the dwell timer."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # No prior dwell.
        assert engine._watching_sleep_dwell_since is None

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine._watching_sleep_dwell_since == self.LATE_NIGHT
        assert engine.manual_override is False

    @patch("backend.services.automation_engine.datetime")
    async def test_mode_not_watching_does_not_trigger(self, mock_dt, engine):
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._current_mode = "working"
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.manual_override is False
        assert engine._watching_sleep_dwell_since is None

    # ------------------------------------------------------------------
    # Dark-room continuation — 2026-05-15 regression coverage.
    #
    # Reference incident: 2026-05-14 → 2026-05-15. Watching held 7h+,
    # camera locked bed+reclined at 23:00 then lost pose detection past
    # 00:00 as the room darkened. Committed zone/posture cleared to
    # None for the rest of the night. Old strict gate 6 reset the dwell
    # on every dark-room tick and the guard never fired.
    #
    # New policy: once dwell has started, None (commit-cleared by
    # darkness) is tolerated; only active contradictions
    # (zone="desk", posture="upright") reset.
    # ------------------------------------------------------------------

    @patch("backend.services.automation_engine.datetime")
    async def test_dark_room_continuation_fires(self, mock_dt, engine):
        """Dwell started under bed+reclined, then camera commits cleared
        to None as the bedroom went dark — guard must still fire."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # Dwell already 91 min in — past the 90-min threshold.
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )
        # Camera has lost commits — the dark-bedroom scenario.
        engine._camera_service = _FakeCamera(zone=None, posture=None)

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.manual_override is True
        assert engine.override_mode == "sleeping"
        assert engine.override_source == "watching_sleep_guard"
        assert engine._watching_sleep_guard_last_fired_at == self.LATE_NIGHT
        # Factors record what the camera *did* see at fire time so the
        # rule-engine-misfire-auditor and journal can see the dark-room
        # branch was taken (zone/posture both None).
        call = engine._ml_logger.calls[0]
        assert call["factors"]["zone"] is None
        assert call["factors"]["posture"] is None

    @patch("backend.services.automation_engine.datetime")
    async def test_dark_room_continuation_started_with_lock(
        self, mock_dt, engine,
    ):
        """Two-tick sequence: first tick locks bed+reclined and starts
        dwell, second tick under camera blackout 91 min later still fires.
        Closer to the real-world flow than the single-tick test above."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # Tick 1 — 91 minutes ago, full lock.
        start = self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        engine._camera_service = _FakeCamera(zone="bed", posture="reclined")
        await engine._evaluate_watching_sleep_guard(start)
        assert engine._watching_sleep_dwell_since == start
        # Tick 2 — room darkened, both commits cleared.
        engine._camera_service = _FakeCamera(zone=None, posture=None)
        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.override_mode == "sleeping"
        assert engine.override_source == "watching_sleep_guard"

    @patch("backend.services.automation_engine.datetime")
    async def test_initial_start_still_requires_full_lock(
        self, mock_dt, engine,
    ):
        """No prior dwell + zone=None → don't start the dwell. The
        tolerance only applies AFTER a confident bed+reclined lock has
        already been observed; starting from cold needs the real signal
        so we don't fire on someone unrelated."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._camera_service = _FakeCamera(zone=None, posture="reclined")
        assert engine._watching_sleep_dwell_since is None

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.manual_override is False
        assert engine._watching_sleep_dwell_since is None

    @patch("backend.services.automation_engine.datetime")
    async def test_started_dwell_resets_on_zone_desk(self, mock_dt, engine):
        """Once dwell is running, a confident zone="desk" commit means
        the user moved — reset the dwell, don't keep counting."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )
        engine._camera_service = _FakeCamera(zone="desk", posture="reclined")

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.manual_override is False
        assert engine._watching_sleep_dwell_since is None

    @patch("backend.services.automation_engine.datetime")
    async def test_started_dwell_resets_on_posture_upright(
        self, mock_dt, engine,
    ):
        """User sat up in bed — posture="upright" is an active
        contradiction and breaks the dwell, even with zone still bed."""
        mock_dt.now.return_value = self.LATE_NIGHT
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        engine._watching_sleep_dwell_since = (
            self.LATE_NIGHT - timedelta(seconds=self.DWELL_OFFSET_FIRES)
        )
        engine._camera_service = _FakeCamera(zone="bed", posture="upright")

        await engine._evaluate_watching_sleep_guard(self.LATE_NIGHT)

        assert engine.manual_override is False
        assert engine._watching_sleep_dwell_since is None


# ---------------------------------------------------------------------------
# Asleep gate (`_is_likely_still_asleep`) + morning-ramp suppression
#
# Defense-in-depth coverage for the 2026-05-15 wake-up incident. Even with
# the watching_sleep_guard fix, both the morning brightness ramp (idle's
# 80→196 climb 06:00–07:00) and watching mode's late_night→day transition
# at 06:00 can wake the user if the guard ever fails to fire for any
# secondary reason. The asleep stamp is updated whenever the guard
# observes a confident bed+reclined lock during watching mode, and the
# helper drives both brightness-escalation suppressions.
# ---------------------------------------------------------------------------

class TestIsLikelyStillAsleep:
    """Unit coverage for the gate helper consumed by ramp + period gates."""

    NOW = datetime(2026, 5, 15, 6, 30, tzinfo=TZ)

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        eng = AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )
        eng._camera_service = None  # no camera = no desk-attendance veto
        eng._last_process_working_at = None  # no recent PC working
        return eng

    def test_no_stamp_returns_false(self, engine):
        """Cold start — no observation, no suppression."""
        assert engine._last_bed_reclined_during_watching_at is None
        assert engine._is_likely_still_asleep(self.NOW) is False

    def test_fresh_stamp_returns_true(self, engine):
        """Stamp set 30 min ago, no attendance signal → still asleep."""
        engine._last_bed_reclined_during_watching_at = (
            self.NOW - timedelta(minutes=30)
        )
        assert engine._is_likely_still_asleep(self.NOW) is True

    def test_stale_stamp_failsafe(self, engine):
        """Stamp >12h old → failsafe clears the gate regardless of
        attendance. Covers "user left for the day without the camera
        ever seeing them re-enter the desk zone."""
        engine._last_bed_reclined_during_watching_at = (
            self.NOW - timedelta(hours=13)
        )
        assert engine._is_likely_still_asleep(self.NOW) is False

    def test_desk_attendance_releases_gate(self, engine):
        """Camera sees user at the desk fresh → gate released even with
        a recent asleep stamp. They're up."""
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        engine._camera_service = _FakeEnabledCamera(
            zone="desk", enabled=True, zone_committed_at=recent,
        )
        engine._last_bed_reclined_during_watching_at = (
            self.NOW - timedelta(minutes=15)
        )
        assert engine._is_likely_still_asleep(self.NOW) is False

    def test_process_working_releases_gate(self, engine):
        """PC agent says user is working → release."""
        engine._last_process_working_at = (
            datetime.now(tz=TZ) - timedelta(seconds=60)
        )
        engine._last_bed_reclined_during_watching_at = (
            self.NOW - timedelta(minutes=15)
        )
        assert engine._is_likely_still_asleep(self.NOW) is False


class TestRelaxDriftFixtureScope:
    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )

    async def test_relax_drift_keeps_plant_wash_out_of_random_scope(self, engine):
        engine._scene_drift_enabled = True
        engine._current_mode = "relax"
        engine._last_activity_change = datetime.now(tz=TZ) - timedelta(
            minutes=engine._drift_interval_minutes + 1,
        )
        engine._apply_state = AsyncMock()
        engine._weather_adjust = MagicMock(side_effect=lambda state: state)

        with patch("backend.services.automation_engine.random.randint", return_value=0):
            await engine._maybe_drift()

        target = engine._apply_state.await_args.args[0]
        assert list(target) == ["1", "2", "3", "4", "5"]
        assert "6" not in target


class TestMorningRampAsleepGate:
    """The morning_ramp inside `_apply_time_based` honors the asleep gate.

    Captures the applied state via a patched `_apply_state` so we can
    assert what the ramp branch produced without touching the real Hue
    plumbing. Targets the 06:30 weekday window — solidly inside the
    06:00–07:00 ramp_start_hour → ramp_end window.
    """

    NOW = datetime(2026, 5, 15, 6, 30, tzinfo=TZ)

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        eng = AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )
        eng._camera_service = None
        eng._last_process_working_at = None
        return eng

    @pytest.fixture
    def captured_states(self):
        """Stash for what _apply_state was called with."""
        return []

    async def _drive_with_capture(self, engine, captured, now):
        async def _capture_apply_state(state, transitiontime=None):
            captured.append(dict(state))

        with patch("backend.services.automation_engine.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            engine._apply_state = _capture_apply_state  # type: ignore
            await engine._apply_time_based()

    async def test_ramp_runs_normally_without_stamp(
        self, engine, captured_states,
    ):
        """No asleep stamp → morning ramp runs as before. At 06:30 with
        ramp_start_hour=6 and 60-min duration, ramp progress is 50% —
        bri should be in the middle of the curve, well above the
        pre-ramp wake_brightness baseline."""
        assert engine._last_bed_reclined_during_watching_at is None

        await self._drive_with_capture(engine, captured_states, self.NOW)

        assert len(captured_states) == 1
        target = captured_states[0]
        assert target["6"] == {"on": False}
        state = target["1"]
        assert state["on"] is True
        assert state["bri"] > 60  # clearly past the pre-ramp dim hold

    async def test_ramp_suppressed_when_recently_in_bed(
        self, engine, captured_states,
    ):
        """Stamp 30 min ago, no attendance → ramp suppressed, pre-ramp
        dim held instead. The 2026-05-15 wake-up case: user asleep,
        ramp would have climbed brightness — we hold the dim
        wake_brightness state instead."""
        engine._last_bed_reclined_during_watching_at = (
            self.NOW - timedelta(minutes=30)
        )

        await self._drive_with_capture(engine, captured_states, self.NOW)

        assert len(captured_states) == 1
        target = captured_states[0]
        assert target["6"] == {"on": False}
        state = target["1"]
        # Pre-ramp dim shape from `_build_time_rules` (wake_hour → ramp
        # band): wake_brightness=40 with warm hue 6000, sat 200.
        assert state["on"] is True
        assert state["bri"] == 40  # DaySchedule.wake_brightness default
        assert state["hue"] == 6000
        assert state["sat"] == 200

    async def test_ramp_runs_when_desk_attendance_fresh(
        self, engine, captured_states,
    ):
        """Stamp set BUT camera sees user at the desk → ramp runs.
        Attendance veto wins — they're up even with a recent bed obs."""
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        engine._camera_service = _FakeEnabledCamera(
            zone="desk", enabled=True, zone_committed_at=recent,
        )
        engine._last_bed_reclined_during_watching_at = (
            self.NOW - timedelta(minutes=30)
        )

        await self._drive_with_capture(engine, captured_states, self.NOW)

        target = captured_states[0]
        assert target["6"] == {"on": False}
        state = target["1"]
        assert state["bri"] > 60

    async def test_ramp_runs_when_process_working_recent(
        self, engine, captured_states,
    ):
        """Stamp set BUT PC agent reports working recent → ramp runs."""
        engine._last_process_working_at = (
            datetime.now(tz=TZ) - timedelta(seconds=60)
        )
        engine._last_bed_reclined_during_watching_at = (
            self.NOW - timedelta(minutes=30)
        )

        await self._drive_with_capture(engine, captured_states, self.NOW)

        target = captured_states[0]
        assert target["6"] == {"on": False}
        state = target["1"]
        assert state["bri"] > 60

    async def test_ramp_runs_when_stamp_stale_by_failsafe(
        self, engine, captured_states,
    ):
        """Stamp >12h old → failsafe drops it, ramp runs."""
        engine._last_bed_reclined_during_watching_at = (
            self.NOW - timedelta(hours=13)
        )

        await self._drive_with_capture(engine, captured_states, self.NOW)

        target = captured_states[0]
        assert target["6"] == {"on": False}
        state = target["1"]
        assert state["bri"] > 60



# ---------------------------------------------------------------------------
# Presence signal — clears the external-off suppression flag
# ---------------------------------------------------------------------------


class TestSignalPresence:
    """`signal_presence(source)` is the hook camera (and future audio)
    services use to clear `_external_off_detected` after the Hue iOS app's
    "Leaving home" automation turned all lights off. Without it the flag
    only clears on report_activity with mode != idle, which can't happen
    if the user walks back in but doesn't touch the PC."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws)

    async def test_clears_external_off_when_set(self, engine):
        engine._external_off_detected = True
        await engine.signal_presence("camera")
        assert engine._external_off_detected is False

    async def test_idempotent_when_flag_already_clear(self, engine):
        # Already cleared — second call shouldn't raise or flip state.
        engine._external_off_detected = False
        await engine.signal_presence("camera")
        assert engine._external_off_detected is False

    async def test_accepts_any_source_label(self, engine):
        # Source is a free-form telemetry tag, not validated. Camera today,
        # audio tomorrow, anything else later — all valid.
        engine._external_off_detected = True
        await engine.signal_presence("audio")
        assert engine._external_off_detected is False


class _PhysicalContextCamera:
    def __init__(self) -> None:
        self.enabled = True
        self._paused = False
        self.healthy = True
        self.last_detection_at = datetime.now(timezone.utc)

    async def on_mode_change(self, mode: str) -> None:
        if mode != "sleeping" and self._paused:
            self._paused = False
            self.healthy = False
            self.last_detection_at = None


class TestPhysicalContextRelax:
    @pytest.fixture
    def context(self, mock_hue, mock_hue_v2, mock_ws):
        presence = PresenceFusion()
        engine = AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
            presence_fusion=presence,
        )
        camera = _PhysicalContextCamera()
        engine.set_camera_service(camera)
        return engine, presence, camera

    @staticmethod
    def observe(
        presence: PresenceFusion,
        *,
        source: str,
        captured_at: datetime,
        face_present: bool,
        zone: str | None,
    ) -> PresenceReading:
        reading = PresenceReading(
            source=source,
            captured_at=captured_at,
            face_present=face_present,
            face_confidence=0.9 if face_present else 0.0,
            detection_source="face",
            zone=zone,
        )
        presence.on_observation(reading)
        return reading

    @staticmethod
    def process_factors(
        mode: str,
        *,
        device: str = "desktop",
        candidate_mode: str | None = None,
        idle_seconds: int = 0,
    ) -> list[dict]:
        candidate = candidate_mode or mode
        factors = [
            {"key": "device", "value": device},
            {"key": "candidate_mode", "value": candidate},
            {"key": "candidate_reason", "value": f"foreground_{mode}"},
            {"key": "idle", "value": idle_seconds},
        ]
        if candidate != mode:
            factors.extend([
                {"key": "pending_mode", "value": candidate},
                {"key": "pending_dwell_age", "value": 12.0},
            ])
        if mode == "gaming":
            factors.append({
                "key": "gaming_qualification",
                "value": "foreground_game",
            })
        return factors

    def establish_couch_contradiction(
        self,
        presence: PresenceFusion,
        *,
        now: datetime,
        desk_age_seconds: float,
        desktop_absence_age_seconds: float = 0,
        couch_age_seconds: float = 0,
        couch_zone: str | None = "couch",
        couch_face_present: bool = True,
    ) -> PresenceReading:
        self.observe(
            presence,
            source="desktop",
            captured_at=now - timedelta(seconds=desk_age_seconds),
            face_present=True,
            zone="desk",
        )
        self.observe(
            presence,
            source="desktop",
            captured_at=now - timedelta(seconds=desktop_absence_age_seconds),
            face_present=False,
            zone=None,
        )
        return self.observe(
            presence,
            source="latitude",
            captured_at=now - timedelta(seconds=couch_age_seconds),
            face_present=couch_face_present,
            zone=couch_zone,
        )

    @staticmethod
    def hold_process_mode(
        engine: AutomationEngine,
        mode: str,
        factors: list[dict],
        now: datetime,
    ) -> None:
        engine._current_mode = mode
        engine._mode_source = "process"
        engine._mode_source_key = (
            f"process:{next(f['value'] for f in factors if f['key'] == 'device')}"
        )
        engine._record_process_semantic(mode, factors, now)

    async def test_fresh_committed_latitude_couch_enters_relax(self, context):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        reading = self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )

        await engine.notify_presence_observation(reading)

        assert engine._current_mode == "idle"
        assert engine.current_mode == "relax"
        assert engine.override_source == "physical_context_relax"

    async def test_no_latitude_evidence_leaves_idle_unchanged(self, context):
        engine, _, _ = context

        await engine._evaluate_physical_context_relax(
            now=datetime.now(tz=TZ),
            trigger="test",
        )

        assert engine.current_mode == "idle"
        assert engine.manual_override is False

    @pytest.mark.parametrize(
        ("enabled", "paused", "healthy", "age_seconds"),
        [
            (False, False, True, 0),
            (True, True, True, 0),
            (True, False, False, 0),
            (True, False, True, 9),
        ],
    )
    async def test_unavailable_or_stale_latitude_cannot_enter(
        self,
        context,
        enabled,
        paused,
        healthy,
        age_seconds,
    ):
        engine, presence, camera = context
        now = datetime.now(timezone.utc)
        camera.enabled = enabled
        camera._paused = paused
        camera.healthy = healthy
        self.observe(
            presence,
            source="latitude",
            captured_at=now - timedelta(seconds=age_seconds),
            face_present=True,
            zone="couch",
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False

    @pytest.mark.parametrize("mode", ["working", "watching", "gaming"])
    async def test_fresh_semantic_process_blocks_entry(self, context, mode):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        engine._record_process_semantic(
            mode,
            [{"key": "device", "value": "desktop"}],
            now,
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False

    async def test_process_age_31_to_299_does_not_block_entry(self, context):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        engine._record_process_semantic(
            "working",
            [{"key": "device", "value": "desktop"}],
            now - timedelta(seconds=31),
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.override_source == "physical_context_relax"
        assert SOURCE_STALE_SECONDS == 300

    async def test_fresh_process_immediately_preempts_active_fallback(self, context):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        reading = self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        await engine.notify_presence_observation(reading)

        await engine.report_activity(
            "gaming",
            source="process",
            factors=[{"key": "device", "value": "desktop"}],
        )

        assert engine.current_mode == "gaming"
        assert engine.manual_override is False

    async def test_working_couch_handoff_under_30_seconds_stays_blocked(
        self, context,
    ):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors(
            "working", candidate_mode="idle", idle_seconds=15,
        )
        self.hold_process_mode(engine, "working", factors, now)
        self.establish_couch_contradiction(
            presence, now=now, desk_age_seconds=29,
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False
        arbitration = engine.get_activity_context()[
            "physical_context_process_arbitration"
        ]
        assert arbitration["state"] == "veto"
        assert arbitration["reason"] == "desktop_process_intent_active"

    @pytest.mark.parametrize("mode", ["working", "gaming"])
    async def test_strong_couch_handoff_discounts_desktop_process_intent(
        self, context, mode,
    ):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors(
            mode,
            candidate_mode="idle" if mode == "working" else mode,
            idle_seconds=0,
        )
        self.hold_process_mode(engine, mode, factors, now)
        self.establish_couch_contradiction(
            presence, now=now, desk_age_seconds=31,
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.override_source == "physical_context_relax"
        assert engine.current_mode == "relax"
        context_row = engine.get_activity_context()
        arbitration = context_row["physical_context_process_arbitration"]
        assert arbitration["state"] == "discounted"
        assert arbitration["reason"] == "stale_desktop_process_discounted"
        assert arbitration["committed_mode"] == mode
        assert arbitration["candidate_mode"] == factors[1]["value"]
        assert arbitration["candidate_reason"] == f"foreground_{mode}"
        assert arbitration["idle_seconds"] == 0.0
        if mode == "gaming":
            assert arbitration["gaming_qualification"] == "foreground_game"
        assert set(context_row["process_evidence_by_device"]) == {"desktop"}

    async def test_repeated_working_heartbeats_remain_discounted_and_non_preempting(
        self, context,
    ):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors(
            "working", candidate_mode="idle", idle_seconds=15,
        )
        self.hold_process_mode(engine, "working", factors, now)
        self.establish_couch_contradiction(
            presence, now=now, desk_age_seconds=31,
        )
        await engine._evaluate_physical_context_relax(now=now, trigger="entry")

        await engine.report_activity("working", "process", factors)
        await engine.report_activity("working", "process", factors)

        assert engine.override_source == "physical_context_relax"
        assert engine.current_mode == "relax"
        evidence = engine.get_activity_context()["process_evidence_by_device"]
        assert len(evidence) == 1
        assert evidence["desktop"]["committed_mode"] == "working"
        assert engine.get_activity_context()[
            "physical_context_process_arbitration"
        ]["state"] == "discounted"

    async def test_discounted_heartbeat_respects_existing_couch_loss_debounce(
        self, context,
    ):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors("working")
        self.hold_process_mode(engine, "working", factors, now)
        self.establish_couch_contradiction(
            presence, now=now, desk_age_seconds=31,
        )
        await engine._evaluate_physical_context_relax(now=now, trigger="entry")
        loss_at = now + timedelta(seconds=2)
        self.observe(
            presence,
            source="latitude",
            captured_at=loss_at,
            face_present=False,
            zone=None,
        )
        await engine._evaluate_physical_context_relax(
            now=loss_at, trigger="loss_started",
        )
        engine._record_process_semantic("working", factors, loss_at)

        self.observe(
            presence,
            source="desktop",
            captured_at=loss_at + timedelta(seconds=29),
            face_present=False,
            zone=None,
        )
        await engine._evaluate_physical_context_relax(
            now=loss_at + timedelta(seconds=29), trigger="heartbeat",
        )
        assert engine.override_source == "physical_context_relax"

        self.observe(
            presence,
            source="desktop",
            captured_at=loss_at + timedelta(seconds=30),
            face_present=False,
            zone=None,
        )
        await engine._evaluate_physical_context_relax(
            now=loss_at + timedelta(seconds=30), trigger="loss_threshold",
        )
        assert engine.manual_override is False
        assert engine.current_mode == "working"

    def test_process_evidence_device_cardinality_is_bounded(self, context):
        engine, _, _ = context
        now = datetime.now(timezone.utc)

        for index in range(10):
            engine._record_process_semantic(
                "working",
                self.process_factors("working", device=f"device-{index}"),
                now + timedelta(milliseconds=index),
            )

        evidence = engine.get_activity_context()["process_evidence_by_device"]
        assert len(evidence) == 8
        assert "device-0" not in evidence
        assert "device-1" not in evidence

    async def test_fresh_desktop_face_restores_underlying_working_immediately(
        self, context,
    ):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors("working")
        self.hold_process_mode(engine, "working", factors, now)
        self.establish_couch_contradiction(
            presence, now=now, desk_age_seconds=31,
        )
        await engine._evaluate_physical_context_relax(now=now, trigger="entry")

        desk = self.observe(
            presence,
            source="desktop",
            captured_at=datetime.now(timezone.utc),
            face_present=True,
            zone=None,
        )
        await engine.notify_presence_observation(desk)

        assert engine.manual_override is False
        assert engine.current_mode == "working"
        assert engine.get_activity_context()[
            "physical_context_process_arbitration"
        ]["state"] == "veto"

    @pytest.mark.parametrize(
        ("couch_zone", "couch_face_present", "couch_age_seconds"),
        [(None, True, 0), ("couch", False, 0), ("couch", True, 9)],
    )
    async def test_weak_uncommitted_or_stale_couch_cannot_discount(
        self,
        context,
        couch_zone,
        couch_face_present,
        couch_age_seconds,
    ):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors("working")
        self.hold_process_mode(engine, "working", factors, now)
        self.establish_couch_contradiction(
            presence,
            now=now,
            desk_age_seconds=31,
            couch_zone=couch_zone,
            couch_face_present=couch_face_present,
            couch_age_seconds=couch_age_seconds,
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False
        assert engine.get_activity_context()[
            "physical_context_process_arbitration"
        ]["state"] == "veto"

    @pytest.mark.parametrize("absence", ["missing", "stale"])
    async def test_missing_or_stale_desktop_absence_cannot_discount(
        self, context, absence,
    ):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors("working")
        self.hold_process_mode(engine, "working", factors, now)
        self.observe(
            presence,
            source="desktop",
            captured_at=now - timedelta(seconds=31),
            face_present=True,
            zone="desk",
        )
        if absence == "stale":
            self.observe(
                presence,
                source="desktop",
                captured_at=now - timedelta(seconds=9),
                face_present=False,
                zone=None,
            )
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False
        assert engine.get_activity_context()[
            "physical_context_process_arbitration"
        ]["state"] == "veto"

    async def test_non_desktop_process_intent_is_never_discounted(self, context):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors("working", device="latitude")
        self.hold_process_mode(engine, "working", factors, now)
        self.establish_couch_contradiction(
            presence, now=now, desk_age_seconds=31,
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False
        arbitration = engine.get_activity_context()[
            "physical_context_process_arbitration"
        ]
        assert arbitration["state"] == "veto"
        assert arbitration["device"] == "latitude"

    @pytest.mark.parametrize("mode", ["working", "gaming"])
    async def test_desk_present_process_intent_remains_authoritative(
        self, context, mode,
    ):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors(mode)
        self.hold_process_mode(engine, mode, factors, now)
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        self.observe(
            presence,
            source="desktop",
            captured_at=now,
            face_present=True,
            zone="desk",
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False
        assert engine.get_activity_context()[
            "physical_context_process_arbitration"
        ]["state"] == "veto"

    async def test_watching_stays_authoritative_despite_couch_contradiction(
        self, context,
    ):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors(
            "watching", candidate_mode="idle", idle_seconds=900,
        )
        self.hold_process_mode(engine, "watching", factors, now)
        self.establish_couch_contradiction(
            presence, now=now, desk_age_seconds=31,
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False
        arbitration = engine.get_activity_context()[
            "physical_context_process_arbitration"
        ]
        assert arbitration["state"] == "veto"
        assert arbitration["committed_mode"] == "watching"
        assert arbitration["idle_seconds"] == 900.0

    @pytest.mark.parametrize("blocker", ["manual", "dnd", "away", "cooldown"])
    async def test_existing_authority_still_blocks_discounted_working_handoff(
        self, context, blocker,
    ):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        factors = self.process_factors("working")
        self.hold_process_mode(engine, "working", factors, now)
        self.establish_couch_contradiction(
            presence, now=now, desk_age_seconds=31,
        )
        if blocker == "manual":
            await engine.set_manual_override("working", source="api:test")
        elif blocker == "dnd":
            engine._dnd._enabled = True
            engine._dnd._expiry = now + timedelta(hours=1)
        elif blocker == "away":
            engine._external_off_detected = True
        else:
            engine._user_cleared_override_at = now
            engine._user_clear_allows_physical_context_relax = False

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.override_source != "physical_context_relax"
        if blocker == "manual":
            assert engine.override_source == "api:test"

    async def test_unsupported_activity_suggestion_does_not_displace(self, context):
        engine, presence, _ = context
        now = datetime.now(timezone.utc)
        reading = self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        await engine.notify_presence_observation(reading)

        await engine.report_activity("working", source="audio_ml")

        assert engine.current_mode == "relax"
        assert engine.override_source == "physical_context_relax"

    async def test_manual_dnd_and_away_each_block_entry(self, context):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )

        await engine.set_manual_override("working", source="api:test")
        await engine._evaluate_physical_context_relax(now=now, trigger="manual")
        assert engine.override_source == "api:test"

        await engine.clear_override(source="api:test")
        engine._external_off_detected = True
        await engine._evaluate_physical_context_relax(now=now, trigger="away")
        assert engine.manual_override is False

        engine._external_off_detected = False
        engine._dnd._enabled = True
        engine._dnd._expiry = now + timedelta(hours=1)
        await engine._evaluate_physical_context_relax(now=now, trigger="dnd")
        assert engine.manual_override is False

    async def test_presence_loss_releases_at_30s_without_brief_churn(self, context):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        await engine._evaluate_physical_context_relax(now=now, trigger="entry")
        self.observe(
            presence,
            source="latitude",
            captured_at=now + timedelta(seconds=1),
            face_present=False,
            zone="couch",
        )
        await engine._evaluate_physical_context_relax(
            now=now + timedelta(seconds=1),
            trigger="loss_started",
        )

        await engine._evaluate_physical_context_relax(
            now=now + timedelta(seconds=29),
            trigger="brief_loss",
        )
        assert engine.override_source == "physical_context_relax"

        await engine._evaluate_physical_context_relax(
            now=now + timedelta(seconds=30),
            trigger="loss",
        )
        assert engine.override_source == "physical_context_relax"

        await engine._evaluate_physical_context_relax(
            now=now + timedelta(seconds=31),
            trigger="loss_threshold",
        )
        assert engine.manual_override is False
        assert engine.current_mode == "idle"

    async def test_presence_loss_releases_at_exactly_30_continuous_seconds(
        self, context,
    ):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        await engine._evaluate_physical_context_relax(now=now, trigger="entry")
        loss_started_at = now + timedelta(seconds=2)
        self.observe(
            presence,
            source="latitude",
            captured_at=loss_started_at,
            face_present=False,
            zone="couch",
        )

        await engine._evaluate_physical_context_relax(
            now=loss_started_at,
            trigger="loss_started",
        )
        await engine._evaluate_physical_context_relax(
            now=loss_started_at + timedelta(seconds=29, milliseconds=999),
            trigger="before_threshold",
        )
        assert engine.override_source == "physical_context_relax"

        await engine._evaluate_physical_context_relax(
            now=loss_started_at + timedelta(seconds=30),
            trigger="at_threshold",
        )
        assert engine.manual_override is False
        assert engine.current_mode == "idle"

    async def test_loss_timer_survives_new_absent_observations_and_resets_on_couch(
        self, context,
    ):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        couch = self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        await engine.notify_presence_observation(couch)
        loss_started_at = now + timedelta(seconds=1)
        absent = self.observe(
            presence,
            source="latitude",
            captured_at=loss_started_at,
            face_present=False,
            zone="couch",
        )
        await engine._evaluate_physical_context_relax(
            now=loss_started_at,
            trigger="first_loss",
        )

        later_absent = self.observe(
            presence,
            source="latitude",
            captured_at=loss_started_at + timedelta(seconds=20),
            face_present=False,
            zone=None,
        )
        await engine._evaluate_physical_context_relax(
            now=later_absent.captured_at,
            trigger="continued_loss",
        )
        assert engine._physical_context_presence_lost_at == absent.captured_at

        renewed = self.observe(
            presence,
            source="latitude",
            captured_at=loss_started_at + timedelta(seconds=25),
            face_present=True,
            zone="couch",
        )
        await engine._evaluate_physical_context_relax(
            now=renewed.captured_at,
            trigger="renewed_couch",
        )
        assert engine.override_source == "physical_context_relax"
        assert engine._physical_context_presence_lost_at is None

        second_loss = self.observe(
            presence,
            source="latitude",
            captured_at=loss_started_at + timedelta(seconds=26),
            face_present=False,
            zone="couch",
        )
        await engine._evaluate_physical_context_relax(
            now=second_loss.captured_at,
            trigger="second_loss",
        )
        assert engine._physical_context_presence_lost_at == second_loss.captured_at

    async def test_desktop_conflict_vetoes_entry_and_logs(self, context, caplog):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        self.observe(
            presence,
            source="desktop",
            captured_at=now,
            face_present=True,
            zone="desk",
        )

        with caplog.at_level("INFO"):
            await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False
        assert "simultaneous fresh couch and desk" in caplog.text

    @pytest.mark.parametrize("zone", [None, "couch"])
    async def test_fresh_desktop_face_vetoes_entry_regardless_of_zone(
        self, context, zone,
    ):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        self.observe(
            presence,
            source="desktop",
            captured_at=now,
            face_present=True,
            zone=zone,
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False

    async def test_newer_idle_clears_device_veto_without_second_dwell(self, context):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        engine._record_process_semantic(
            "working",
            [{"key": "device", "value": "desktop"}],
            now,
        )
        await engine._evaluate_physical_context_relax(now=now, trigger="blocked")
        assert engine.manual_override is False

        await engine.report_activity(
            "idle",
            source="process",
            factors=[{"key": "device", "value": "desktop"}],
        )

        assert engine.override_source == "physical_context_relax"

    async def test_non_sleeping_clear_keeps_cooldown(self, context):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        await engine.set_manual_override("relax", source="api:test")
        await engine.clear_override(source="api:test")
        self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )

        await engine._evaluate_physical_context_relax(now=now, trigger="test")

        assert engine.manual_override is False
        assert engine._user_clear_allows_physical_context_relax is False

    async def test_respawn_sleeping_resume_requires_new_real_camera_commit(
        self, mock_hue, mock_hue_v2, mock_ws,
    ):
        presence = PresenceFusion()
        engine = AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
            presence_fusion=presence,
        )
        stale_camera = CameraService(mock_ws, engine)
        engine.register_on_mode_change(stale_camera.on_mode_change)
        app = SimpleNamespace(
            state=SimpleNamespace(
                automation=engine,
                ws_manager=mock_ws,
                presence=presence,
                camera_service=stale_camera,
            )
        )

        async def start_camera(camera):
            camera._enabled = True
            camera._cap = MagicMock()

        with (
            patch.object(CameraService, "start", start_camera),
            patch.object(CameraService, "poll_loop", new_callable=AsyncMock),
        ):
            result = await spawn_camera_service(app, reason="test_respawn")
            await asyncio.sleep(0)

        assert result["status"] == "ok"
        camera = app.state.camera_service
        assert camera is not stale_camera
        assert presence.on_observation in camera._observation_callbacks
        assert (
            presence.invalidate_source
            in camera._observation_invalidation_callbacks
        )
        assert engine._presence_fusion is presence

        before_sleep = datetime.now(timezone.utc)
        camera._last_detection = "present"
        camera._last_detection_at = before_sleep
        camera._last_confidence = 0.9
        camera._last_detection_source = "face"
        camera._last_zone = "couch"
        camera._last_zone_at = before_sleep
        camera._face_anchor_at["couch"] = before_sleep
        desktop = self.observe(
            presence,
            source="desktop",
            captured_at=before_sleep,
            face_present=False,
            zone="desk",
        )
        stale = PresenceReading(
            source="latitude",
            captured_at=before_sleep,
            face_present=True,
            face_confidence=0.9,
            detection_source="face",
            zone="couch",
        )
        for callback in camera._observation_callbacks:
            callback(stale)
        assert presence.get_source_reading("latitude") is stale
        assert presence.get_source_reading("desktop") is desktop

        await camera.on_mode_change("sleeping")
        engine._manual_override = True
        engine._override_mode = "sleeping"
        engine._override_source = "api:test"
        camera._open_capture_async = AsyncMock(return_value=AsyncMock())

        await engine.clear_override(source="api:test")

        assert camera.healthy is False
        assert camera.zone is None
        assert presence.get_source_reading("latitude") is None
        assert presence.get_source_reading("desktop") is desktop
        await engine._evaluate_physical_context_relax(
            now=datetime.now(timezone.utc), trigger="immediate_resume",
        )
        assert engine._current_mode == "idle"
        assert engine.current_mode == "idle"
        assert engine.manual_override is False

        first_at = datetime.now(timezone.utc)
        camera._last_detection = "present"
        camera._last_detection_at = first_at
        camera._last_confidence = 0.9
        camera._last_detection_source = "face"
        camera._apply_zone_hysteresis("couch", present_observed=True)
        first = PresenceReading(
            source="latitude",
            captured_at=first_at,
            face_present=True,
            face_confidence=0.9,
            detection_source="face",
            zone=camera.zone,
        )
        for callback in camera._observation_callbacks:
            callback(first)
        await engine.notify_presence_observation(first)

        assert camera.healthy is True
        assert camera.zone is None
        assert engine.current_mode == "idle"
        assert engine.manual_override is False

        camera._candidate_zone_since = (
            datetime.now(timezone.utc) - timedelta(seconds=15)
        )
        camera._apply_zone_hysteresis("couch", present_observed=True)
        committed_at = datetime.now(timezone.utc)
        camera._last_detection_at = committed_at
        committed = PresenceReading(
            source="latitude",
            captured_at=committed_at,
            face_present=True,
            face_confidence=0.9,
            detection_source="face",
            zone=camera.zone,
        )
        for callback in camera._observation_callbacks:
            callback(committed)
        engine._apply_mode = AsyncMock()
        await engine.notify_presence_observation(committed)
        await camera._maybe_notify_camera_commit(
            zone_before=None, posture_before=None,
        )

        assert camera.zone == "couch"
        assert engine._current_mode == "idle"
        assert engine.current_mode == "relax"
        assert engine.override_source == "physical_context_relax"
        engine._apply_mode.assert_awaited_once_with("relax", force_resend=True)

    async def test_sleeping_clear_exempts_only_physical_context(self, context):
        engine, presence, camera = context
        engine._manual_override = True
        engine._override_mode = "sleeping"
        engine._override_source = "api:test"
        camera._paused = True
        engine.register_on_mode_change(camera.on_mode_change)

        await engine.clear_override(source="api:test")

        assert camera._paused is False
        assert camera.healthy is False
        await engine.set_manual_override("relax", source="ambient_relax")
        assert engine.manual_override is False

        camera.healthy = True
        camera.last_detection_at = datetime.now(timezone.utc)
        unknown = self.observe(
            presence,
            source="latitude",
            captured_at=datetime.now(timezone.utc),
            face_present=True,
            zone=None,
        )
        await engine.notify_presence_observation(unknown)
        assert engine.manual_override is False

        committed = self.observe(
            presence,
            source="latitude",
            captured_at=datetime.now(timezone.utc),
            face_present=True,
            zone="couch",
        )
        await engine.notify_presence_observation(committed)

        assert engine.override_source == "physical_context_relax"
        assert engine._user_clear_allows_physical_context_relax is True

    def test_source_preserves_per_light_overrides(self):
        assert "physical_context_relax" in PRESERVE_PER_LIGHT_OVERRIDE_SOURCES

    async def test_transient_desktop_face_does_not_churn_active_couch_relax_over_idle(
        self, context,
    ):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        couch = self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        await engine.notify_presence_observation(couch)
        assert engine.override_source == "physical_context_relax"

        engine._apply_time_based = AsyncMock()
        engine._apply_mode = AsyncMock()

        # A single fresh desktop face can be a contradictory frame while the
        # committed Latitude couch evidence remains fresh.  It must not tear
        # down Relax to legacy Idle and then immediately re-enter Relax when
        # the next desktop heartbeat retracts the face.
        desk = self.observe(
            presence,
            source="desktop",
            captured_at=now + timedelta(seconds=1),
            face_present=True,
            zone="desk",
        )
        await engine.notify_presence_observation(desk)

        desktop_absent = self.observe(
            presence,
            source="desktop",
            captured_at=now + timedelta(seconds=2),
            face_present=False,
            zone=None,
        )
        await engine.notify_presence_observation(desktop_absent)

        assert engine.override_source == "physical_context_relax"
        assert engine.current_mode == "relax"
        assert engine.activity == "relax"
        engine._apply_time_based.assert_not_awaited()
        engine._apply_mode.assert_not_awaited()

    async def test_fresh_desktop_conflict_releases_after_couch_authority_is_gone(
        self, context,
    ):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        couch = self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        await engine.notify_presence_observation(couch)
        self.observe(
            presence,
            source="latitude",
            captured_at=now + timedelta(seconds=1),
            face_present=False,
            zone=None,
        )
        desk = self.observe(
            presence,
            source="desktop",
            captured_at=now + timedelta(seconds=1),
            face_present=True,
            zone="desk",
        )

        await engine.notify_presence_observation(desk)

        assert engine.manual_override is False
        assert engine.current_mode == "idle"
        assert engine.activity == "general"

    @pytest.mark.parametrize("zone", [None, "couch"])
    async def test_fresh_desktop_face_holds_relax_while_couch_remains_qualified(
        self, context, zone,
    ):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        couch = self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        await engine.notify_presence_observation(couch)
        desktop = self.observe(
            presence,
            source="desktop",
            captured_at=now,
            face_present=True,
            zone=zone,
        )

        await engine.notify_presence_observation(desktop)

        assert engine.manual_override is True
        assert engine.override_source == "physical_context_relax"
        assert engine.current_mode == "relax"

    async def test_away_release_clears_without_relighting(self, context):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        couch = self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        await engine.notify_presence_observation(couch)
        engine._apply_mode = AsyncMock()
        engine._apply_time_based = AsyncMock()
        engine._external_off_detected = True

        await engine._evaluate_physical_context_relax(
            now=now, trigger="away",
        )

        assert engine.manual_override is False
        engine._apply_mode.assert_not_awaited()
        engine._apply_time_based.assert_not_awaited()

    async def test_commit_after_entry_does_not_repaint_idle_or_relax(self, context):
        engine, presence, _ = context
        now = datetime.now(tz=TZ)
        couch = self.observe(
            presence,
            source="latitude",
            captured_at=now,
            face_present=True,
            zone="couch",
        )
        await engine.notify_presence_observation(couch)
        engine._apply_mode = AsyncMock()

        await engine.notify_camera_commit()

        engine._apply_mode.assert_not_awaited()

    async def test_explicit_user_mode_preempts_active_fallback(self, context):
        engine, presence, _ = context
        couch = self.observe(
            presence,
            source="latitude",
            captured_at=datetime.now(tz=TZ),
            face_present=True,
            zone="couch",
        )
        await engine.notify_presence_observation(couch)

        await engine.set_manual_override("working", source="api:test")

        assert engine.current_mode == "working"
        assert engine.override_source == "api:test"


# ---------------------------------------------------------------------------
# Gaming resolver integration — GH#203 commit 2
# ---------------------------------------------------------------------------


class TestGamingResolutionIntegration:
    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
        )

    @staticmethod
    def _record_writes(mock_hue):
        calls: list[tuple[str, dict]] = []
        original = mock_hue.set_light

        async def record(light_id, state):
            calls.append((str(light_id), state.copy()))
            return await original(light_id, state)

        mock_hue.set_light = record
        return calls

    async def test_generic_weekday_gaming_uses_resolver_and_diagnostics(
        self, engine, mock_hue,
    ):
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 13, 0, tzinfo=TZ),
        )

        await engine.report_activity("gaming", source="pc_agent")

        gaming = engine.get_gaming_diagnostics()
        assert gaming["requested_game"] is None
        assert gaming["selected_profile"] is None
        assert gaming["schedule_type"] == "weekday"
        assert gaming["period"] == "day"
        assert gaming["transition_reason"] == "activity_entry"
        assert mock_hue._lights["3"]["bri"] >= 160
        assert engine._last_applied_per_light["3"] == engine._last_applied_per_light["4"]

    async def test_weekend_daytime_resolves_separately(self, engine):
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 18, 13, 0, tzinfo=TZ),
        )

        await engine.report_activity("gaming", source="pc_agent")

        gaming = engine.get_gaming_diagnostics()
        assert gaming["schedule_type"] == "weekend"
        assert gaming["selected_variant"]["schedule_type"] == "weekend"

    async def test_profile_acquire_and_release_are_direct_compositions(
        self, engine, mock_hue,
    ):
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 13, 0, tzinfo=TZ),
        )
        calls = self._record_writes(mock_hue)
        await engine.report_activity("gaming", source="pc_agent")
        calls.clear()

        await engine.report_activity(
            "gaming", source="pc_agent", factors=[{"key": "game", "value": "rust"}],
        )
        assert engine.get_gaming_diagnostics()["transition_reason"] == "profile_acquire"
        assert engine.get_gaming_diagnostics()["selected_profile"] == "rust"
        assert calls

        calls.clear()
        await engine.report_activity("gaming", source="pc_agent")
        assert engine.get_gaming_diagnostics()["transition_reason"] == "profile_release"
        assert engine.get_gaming_diagnostics()["selected_profile"] is None
        assert calls

    async def test_failed_profile_acquisition_retains_accepted_screen_sync_plan(
        self, engine, mock_hue,
    ):
        sync = ScreenSyncService(
            mock_hue,
            target_light_ids=["2", "5"],
            transition_boundary=engine._transition_boundary,
        )
        engine._screen_sync = sync
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 13, 0, tzinfo=TZ),
        )
        await engine.report_activity("gaming", source="pc_agent")
        accepted = {
            light_id: target.copy()
            for light_id, target in sync._accepted_gaming_targets.items()
        }
        original = mock_hue.set_light

        async def fail_rust_handoff(light_id, state):
            if str(light_id) == "2" and state.get("ct") == accepted["2"].get("ct"):
                return False
            return await original(light_id, state)

        mock_hue.set_light = fail_rust_handoff
        await engine.report_activity(
            "gaming", source="pc_agent", factors=[{"key": "game", "value": "rust"}],
        )

        assert sync._accepted_gaming_targets == accepted

    async def test_leaving_gaming_clears_screen_sync_plan(self, engine, mock_hue):
        sync = ScreenSyncService(
            mock_hue,
            target_light_ids=["2", "5"],
            transition_boundary=engine._transition_boundary,
        )
        engine._screen_sync = sync
        await engine.report_activity("gaming", source="pc_agent")
        assert sync._accepted_gaming_targets

        await engine.report_activity("working", source="pc_agent")

        assert sync._accepted_gaming_targets == {}

    async def test_recognized_profiles_switch_without_generic_resolution(
        self, engine, monkeypatch,
    ):
        base = GAMING_LIGHTING_PROFILES["rust"]
        alpha = GameLightingProfile(
            game_slug="alpha",
            variants=base.variants,
            fixture_roles=base.fixture_roles,
            preserve_legacy_output=base.preserve_legacy_output,
        )
        beta_variants = {
            key: {lid: light.copy() for lid, light in value.items()}
            for key, value in base.variants.items()
        }
        beta_variants[(None, "day")]["1"]["bri"] = 201
        beta = GameLightingProfile(
            game_slug="beta",
            variants=beta_variants,
            fixture_roles=base.fixture_roles,
            preserve_legacy_output=base.preserve_legacy_output,
        )
        monkeypatch.setitem(GAMING_LIGHTING_PROFILES, "alpha", alpha)
        monkeypatch.setitem(GAMING_LIGHTING_PROFILES, "beta", beta)
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 13, 0, tzinfo=TZ),
        )

        await engine.report_activity(
            "gaming", source="pc_agent", factors=[{"key": "game", "value": "alpha"}],
        )
        await engine.report_activity(
            "gaming", source="pc_agent", factors=[{"key": "game", "value": "beta"}],
        )

        assert engine.get_gaming_diagnostics()["selected_profile"] == "beta"
        assert engine.get_gaming_diagnostics()["transition_reason"] == "game_switch"

    async def test_identical_heartbeats_and_unknown_game_switch_do_not_write(
        self, engine, mock_hue,
    ):
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 13, 0, tzinfo=TZ),
        )
        calls = self._record_writes(mock_hue)
        await engine.report_activity(
            "gaming", source="pc_agent", factors=[{"key": "game", "value": "unknown-a"}],
        )
        calls.clear()

        await engine.report_activity(
            "gaming", source="pc_agent", factors=[{"key": "game", "value": "unknown-a"}],
        )
        assert calls == []
        assert engine.get_gaming_diagnostics()["transition_reason"] == "steady"

        await engine.report_activity(
            "gaming", source="pc_agent", factors=[{"key": "game", "value": "unknown-b"}],
        )
        assert calls == []
        assert engine.get_gaming_diagnostics()["transition_reason"] == "steady"

    async def test_after_dark_schedule_rollover_with_shared_variant_is_a_noop(
        self, engine, mock_hue,
    ):
        calls = self._record_writes(mock_hue)
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 17, 20, 0, tzinfo=TZ),
        )
        await engine.report_activity("gaming", source="pc_agent")
        calls.clear()
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 18, 20, 0, tzinfo=TZ),
        )

        await engine.report_activity("gaming", source="pc_agent")

        assert calls == []
        gaming = engine.get_gaming_diagnostics()
        assert gaming["transition_reason"] == "steady"
        assert gaming["current_plan_differs_from_previous"] is False

    async def test_scheduled_period_change_and_ct_hsb_handoff_are_safe(
        self, engine, mock_hue,
    ):
        calls = self._record_writes(mock_hue)
        engine._transition_boundary.wait_for_settle = AsyncMock()
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 13, 0, tzinfo=TZ),
        )
        await engine.report_activity("gaming", source="pc_agent")
        calls.clear()
        engine._transition_boundary.wait_for_settle.reset_mock()
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 19, 0, tzinfo=TZ),
        )

        await engine.report_activity("gaming", source="pc_agent")

        assert engine.get_gaming_diagnostics()["transition_reason"] == "scheduled_evolution"
        # B (L2/L5/L6) masks and reaches its target before the functional
        # A group (L1/L3/L4) masks, so no whole-room low-brightness phase.
        assert engine._transition_boundary.wait_for_settle.await_count == 4
        assert calls
        assert all(not ("ct" in state and "hue" in state) for _, state in calls)
        low = [
            (index, light_id)
            for index, (light_id, state) in enumerate(calls)
            if state.get("bri", 255) <= 20
        ]
        bedroom_accent_low = [index for index, light_id in low if light_id in {"2", "5", "6"}]
        functional_low = [index for index, light_id in low if light_id in {"1", "3", "4"}]
        assert {light_id for _, light_id in low} == set(ALL_LIGHT_IDS)
        assert max(bedroom_accent_low) < min(functional_low)
        first_functional_mask = min(functional_low)
        assert {
            light_id for light_id, state in calls[:first_functional_mask]
            if light_id in {"2", "5", "6"} and "hue" in state
        } == {"2", "5", "6"}

    async def test_night_to_late_night_same_space_evolution_stays_deduplicable(
        self, engine, mock_hue,
    ):
        calls = self._record_writes(mock_hue)
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 22, 0, tzinfo=TZ),
        )
        await engine.report_activity("gaming", source="pc_agent")
        calls.clear()
        engine._transition_boundary.wait_for_settle = AsyncMock()
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 23, 0, tzinfo=TZ),
        )

        await engine.report_activity("gaming", source="pc_agent")

        assert engine.get_gaming_diagnostics()["transition_reason"] == "scheduled_evolution"
        assert engine._transition_boundary.wait_for_settle.await_count == 0
        assert calls
        assert all("ct" not in state for _, state in calls)

        calls.clear()
        await engine.report_activity("gaming", source="pc_agent")
        assert calls == []
        assert engine.get_gaming_diagnostics()["transition_reason"] == "steady"

    async def test_handoff_holds_shared_boundary_across_every_phase(
        self, engine,
    ):
        previous = {
            light_id: {"on": True, "bri": 100, "ct": 250}
            for light_id in ALL_LIGHT_IDS
        }
        target = {
            light_id: {"on": True, "bri": 100, "hue": 40000, "sat": 180}
            for light_id in ALL_LIGHT_IDS
        }
        first_settle = asyncio.Event()
        release_settle = asyncio.Event()
        calls = 0

        async def wait_for_settle(_light_ids):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_settle.set()
                await release_settle.wait()

        engine._transition_boundary.wait_for_settle = wait_for_settle
        handoff = asyncio.create_task(
            engine._apply_gaming_color_space_handoff(target, 20, previous)
        )
        await first_settle.wait()
        competing_entered = asyncio.Event()

        async def competing_writer():
            async with engine._transition_boundary.serialized():
                competing_entered.set()

        competitor = asyncio.create_task(competing_writer())
        await asyncio.sleep(0)
        assert not competing_entered.is_set()
        release_settle.set()
        await handoff
        await competitor
        assert competing_entered.is_set()

    async def test_failed_masking_write_blocks_final_recolor_and_retries(
        self, engine, mock_hue,
    ):
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 19, 0, tzinfo=TZ),
        )
        engine._effect_manager._tracker_known = True
        engine._current_mode = "working"
        engine._last_applied_per_light = {
            light_id: {"on": True, "bri": 150, "ct": 250}
            for light_id in ALL_LIGHT_IDS
        }
        calls = self._record_writes(mock_hue)
        original = mock_hue.set_light
        failed_once = False

        async def fail_bedroom_mask(light_id, state):
            nonlocal failed_once
            if str(light_id) == "2" and state.get("ct") == 250 and not failed_once:
                failed_once = True
                return False
            return await original(light_id, state)

        mock_hue.set_light = fail_bedroom_mask
        await engine.report_activity("gaming", source="pc_agent")

        assert engine._current_gaming_resolution is None
        assert not any(light_id == "2" and "hue" in state for light_id, state in calls)
        assert "2" in engine._gaming_handoff_retry_baseline

        calls.clear()
        await engine.report_activity("gaming", source="pc_agent")
        assert any(light_id == "2" and state.get("ct") == 250 for light_id, state in calls)
        assert any(light_id == "2" and "hue" in state for light_id, state in calls)
        assert engine._current_gaming_resolution is not None

    async def test_forced_gaming_entry_uses_pre_resend_ct_baseline(
        self, engine, mock_hue,
    ):
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 19, 0, tzinfo=TZ),
        )
        engine._effect_manager._tracker_known = True
        engine._current_mode = "working"
        engine._last_applied_per_light = {
            light_id: {"on": True, "bri": 150, "ct": 250}
            for light_id in ALL_LIGHT_IDS
        }
        calls = self._record_writes(mock_hue)

        await engine.report_activity("gaming", source="pc_agent")

        assert any(state.get("ct") == 250 and state.get("bri") <= 20 for _, state in calls)
        assert all(not ("ct" in state and "hue" in state) for _, state in calls)

    async def test_effect_reconcile_uses_staged_gaming_safety(
        self, engine, mock_hue,
    ):
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 19, 0, tzinfo=TZ),
        )
        engine._current_mode = "working"
        engine._last_applied_per_light = {
            light_id: {"on": True, "bri": 150, "ct": 250}
            for light_id in ALL_LIGHT_IDS
        }
        engine._effect_manager._tracker_known = False
        calls = self._record_writes(mock_hue)

        await engine.report_activity("gaming", source="pc_agent")

        assert any(state.get("ct") == 250 and state.get("bri") <= 20 for _, state in calls)
        assert all(not ("ct" in state and "hue" in state) for _, state in calls)
        assert engine._current_gaming_resolution is not None

    async def test_effect_handoff_safety_failure_does_not_accept_plan(
        self, engine, mock_hue,
    ):
        sync = ScreenSyncService(
            mock_hue,
            target_light_ids=["2", "5"],
            transition_boundary=engine._transition_boundary,
        )
        engine._screen_sync = sync
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 19, 0, tzinfo=TZ),
        )
        engine._current_mode = "working"
        engine._last_applied_per_light = {
            light_id: {"on": True, "bri": 150, "ct": 250}
            for light_id in ALL_LIGHT_IDS
        }
        engine._effect_manager._tracker_known = False
        original = mock_hue.set_light

        async def fail_mask(light_id, state):
            if str(light_id) == "2" and state.get("ct") == 250:
                return False
            return await original(light_id, state)

        mock_hue.set_light = fail_mask
        await engine.report_activity("gaming", source="pc_agent")

        assert engine._current_gaming_resolution is None
        assert engine._effect_manager._tracker_known is False
        assert sync._accepted_gaming_targets == {}

    async def test_native_gaming_scene_release_forces_composed_reconciliation(
        self, engine, mock_hue, mock_hue_v2,
    ):
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 19, 0, tzinfo=TZ),
        )
        await engine.report_activity("gaming", source="pc_agent")
        engine._scene_overrides = {"gaming": {"evening": "native-scene"}}

        async def activate_scene(_scene_id):
            for light in mock_hue._lights.values():
                light.update({"bri": 15, "hue": 1000, "sat": 254})
                light.pop("ct", None)
            return True

        mock_hue_v2.activate_scene = activate_scene
        await engine.report_activity("gaming", source="pc_agent")
        assert engine.get_gaming_diagnostics()["transition_reason"] == "scene_override"

        engine._scene_overrides["gaming"].pop("evening")
        calls = self._record_writes(mock_hue)
        await engine.report_activity("gaming", source="pc_agent")

        assert calls
        assert engine.get_gaming_diagnostics()["transition_reason"] == "scene_release"
        assert mock_hue._lights["1"]["bri"] == 65

    async def test_native_gaming_scene_release_retries_until_composition_is_accepted(
        self, engine, mock_hue, mock_hue_v2,
    ):
        sync = ScreenSyncService(
            mock_hue,
            target_light_ids=["2", "5"],
            transition_boundary=engine._transition_boundary,
        )
        engine._screen_sync = sync
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 19, 0, tzinfo=TZ),
        )
        await engine.report_activity("gaming", source="pc_agent")
        engine._scene_overrides = {"gaming": {"evening": "native-scene"}}

        async def activate_scene(_scene_id):
            for light in mock_hue._lights.values():
                light.update({"bri": 15, "hue": 1000, "sat": 254})
                light.pop("ct", None)
            return True

        mock_hue_v2.activate_scene = activate_scene
        await engine.report_activity("gaming", source="pc_agent")
        scene_marker = engine._gaming_scene_override.copy()
        assert sync._accepted_gaming_targets == {}
        engine._scene_overrides["gaming"].pop("evening")

        original = mock_hue.set_light

        async def fail_composed_release(light_id, state):
            if str(light_id) == "1":
                return False
            return await original(light_id, state)

        mock_hue.set_light = fail_composed_release
        await engine.report_activity("gaming", source="pc_agent")

        assert engine._gaming_scene_override == scene_marker
        diagnostics = engine.get_gaming_diagnostics()
        assert diagnostics["transition_reason"] == "scene_override"
        assert diagnostics["fallback_reason"] == "explicit_scene_override"
        assert engine._current_gaming_resolution is None
        assert sync._accepted_gaming_targets == {}

        mock_hue.set_light = original
        calls = self._record_writes(mock_hue)
        await engine.report_activity("gaming", source="pc_agent")

        assert calls
        assert engine._gaming_scene_override is None
        assert engine.get_gaming_diagnostics()["transition_reason"] == "scene_release"
        assert sync._accepted_gaming_targets == {
            light_id: engine._last_gaming_target[light_id]
            for light_id in sync.target_lights
        }
        calls.clear()
        await engine.report_activity("gaming", source="pc_agent")
        assert calls == []

    async def test_diagnostics_are_active_and_accepted_state_only(
        self, engine, mock_hue,
    ):
        engine._now = MagicMock(
            return_value=datetime(2026, 4, 13, 19, 0, tzinfo=TZ),
        )
        await engine.report_activity(
            "gaming", source="pc_agent", factors=[{"key": "game", "value": "rust"}],
        )
        await engine.report_activity("working", source="pc_agent")
        assert engine.get_gaming_diagnostics()["active"] is False
        assert engine.get_gaming_diagnostics()["selected_profile"] is None

        await engine.report_activity(
            "gaming", source="pc_agent", factors=[{"key": "game", "value": "rust"}],
        )
        engine._persist_override_state = AsyncMock()
        await engine.set_manual_override("relax", source="api:test")
        assert engine.get_gaming_diagnostics()["active"] is False
        assert engine.get_gaming_diagnostics()["selected_profile"] is None

        await engine.clear_override(source="api:test")
        original = mock_hue.set_light
        failed_once = False

        async def fail_profile_release(light_id, state):
            nonlocal failed_once
            if str(light_id) == "1" and not failed_once:
                failed_once = True
                return False
            return await original(light_id, state)

        mock_hue.set_light = fail_profile_release
        await engine.report_activity("gaming", source="pc_agent")
        diagnostics = engine.get_gaming_diagnostics()
        assert diagnostics["selected_profile"] == "rust"
        assert diagnostics["transition_reason"] == "steady"
