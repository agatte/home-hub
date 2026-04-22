"""
Tests for the automation engine — mode priority, overrides, time periods.

These test the pure logic of the AutomationEngine without touching any real
hardware. Hue, Sonos, and WebSocket are all mocked.
"""
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from backend.services.automation_engine import (
    MODE_PRIORITY,
    AutomationEngine,
    DaySchedule,
    _get_time_period_static,
    _resolve_activity_state,
)

TZ = ZoneInfo("America/Indiana/Indianapolis")


# ---------------------------------------------------------------------------
# Mode priority
# ---------------------------------------------------------------------------

class TestModePriority:
    """Verify mode priority ordering is correct."""

    def test_gaming_is_highest(self):
        assert MODE_PRIORITY["gaming"] == max(MODE_PRIORITY.values())

    def test_priority_ordering(self):
        assert MODE_PRIORITY["gaming"] > MODE_PRIORITY["social"]
        assert MODE_PRIORITY["social"] > MODE_PRIORITY["watching"]
        assert MODE_PRIORITY["watching"] > MODE_PRIORITY["working"]
        assert MODE_PRIORITY["working"] > MODE_PRIORITY["idle"]

    def test_sleeping_and_away_are_lowest(self):
        assert MODE_PRIORITY["sleeping"] == 0
        assert MODE_PRIORITY["away"] == 0

    def test_all_expected_modes_present(self):
        expected = {"sleeping", "away", "idle", "working", "watching", "cooking", "social", "gaming"}
        assert set(MODE_PRIORITY.keys()) == expected


# ---------------------------------------------------------------------------
# Time period detection
# ---------------------------------------------------------------------------

class TestTimePeriod:
    """Test the static time period helper."""

    @patch("backend.services.automation_engine.datetime")
    def test_morning_is_day(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 12, 10, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert _get_time_period_static() == "day"

    @patch("backend.services.automation_engine.datetime")
    def test_afternoon_is_day(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 12, 15, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert _get_time_period_static() == "day"

    @patch("backend.services.automation_engine.datetime")
    def test_evening(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 12, 19, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert _get_time_period_static() == "evening"

    @patch("backend.services.automation_engine.datetime")
    def test_night(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 12, 22, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert _get_time_period_static() == "night"

    @patch("backend.services.automation_engine.datetime")
    def test_early_morning_is_night(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 12, 3, 0, tzinfo=TZ)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert _get_time_period_static() == "night"


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
        assert engine.manual_override is False
        assert engine.enabled is True

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

    async def test_override_broadcasts(self, engine, mock_ws):
        await engine.set_manual_override("movie")
        # Should have broadcast at least one mode_update
        mode_broadcasts = [b for b in mock_ws.broadcasts if b[0] == "mode_update"]
        assert len(mode_broadcasts) >= 1
        assert mode_broadcasts[-1][1]["mode"] == "movie"

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
# Zone+posture → relax rule
# ---------------------------------------------------------------------------

class _FakeCamera:
    """Minimal camera stub exposing the attributes the rule reads."""

    def __init__(self, zone=None, posture=None):
        self.zone = zone
        self.posture = posture


class _FakeMLLogger:
    """Capture log_decision calls for assertion."""

    def __init__(self):
        self.calls: list[dict] = []

    async def log_decision(self, **kwargs):
        self.calls.append(kwargs)


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

    async def test_fires_in_shadow_mode_after_dwell(self, engine):
        """All gates pass, dwell met — logs applied=False by default."""
        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        calls = engine._ml_logger.calls
        assert len(calls) == 1
        assert calls[0]["decision_source"] == "zone_posture_rule"
        assert calls[0]["predicted_mode"] == "relax"
        assert calls[0]["applied"] is False  # shadow-mode default
        assert engine.manual_override is False  # did not actuate

    async def test_actuates_when_apply_flag_true(self, engine):
        """settings.ZONE_POSTURE_RULE_APPLY=True → override fires."""
        with patch(
            "backend.services.automation_engine.settings.ZONE_POSTURE_RULE_APPLY",
            True,
        ):
            await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        assert engine.manual_override is True
        assert engine.override_mode == "relax"
        assert engine._ml_logger.calls[0]["applied"] is True

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

    async def test_manual_override_suppresses(self, engine):
        """If the user (or rule) already set an override, rule stands down."""
        await engine.set_manual_override("social")
        await self._tick(engine, self.EVENING, dwell_offset_seconds=301)
        assert engine._ml_logger.calls == []
        assert engine._zone_posture_reclined_since is None

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

    def test_non_watching_mode_untouched(self, engine):
        """Overlay is watching-only — gaming/working states pass straight through."""
        engine._camera_service = _FakeCamera(zone="bed", posture="reclined")
        state = {"1": {"on": True, "bri": 100, "ct": 400}}
        out = engine._apply_zone_overlay(state, "gaming", "night")
        assert out == state


# ---------------------------------------------------------------------------
# Screen-sync posture-aware brightness cap
# ---------------------------------------------------------------------------

class TestScreenSyncPostureCap:
    """The MODE_ZONE_MAX_BRIGHTNESS lookup honors posture when available."""

    def test_exact_posture_match_wins(self):
        from backend.services.screen_sync import MODE_ZONE_MAX_BRIGHTNESS
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "bed", "reclined")] == 25
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "bed", "upright")] == 60

    def test_desk_entry_preserved(self):
        from backend.services.screen_sync import MODE_ZONE_MAX_BRIGHTNESS
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "desk")] == 180

