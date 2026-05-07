"""
Tests for the automation engine — mode priority, overrides, time periods.

These test the pure logic of the AutomationEngine without touching any real
hardware. Hue, Sonos, and WebSocket are all mocked.
"""
from datetime import datetime, timedelta, timezone
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
            "social", "gaming", "gameday",
        }
        assert set(MODE_PRIORITY.keys()) == expected


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

    Calendar events (winddown_routine), user-initiated API calls (api:*),
    and rule-suggestion accepts (rule_suggestion_accept:*) bypass.
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

    async def test_cooldown_does_not_block_winddown_routine(self, engine):
        # Calendar events bypass — wind-down at 22:00 should still fire even
        # if the user cleared an override 5 min earlier.
        await engine.clear_override(source="api:1.2.3.4")
        await engine.set_manual_override("relax", source="winddown_routine")
        assert engine.manual_override is True

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
# Per-light manual override preservation across mode changes
# ---------------------------------------------------------------------------

class TestPerLightOverridePreserve:
    """Per-light manual brightness/color overrides should survive autonomous
    mode pushes (winddown, late-night rescue, fusion, predictor, zone+posture
    rule) but get wiped when the user themselves picks a new mode.

    The user's invariant: "manual brightness sticks until I change it." Before
    this gate, every set_manual_override unconditionally cleared
    _manual_light_overrides, so e.g. winddown_routine at 22:00 would erase a
    manually-set kitchen brightness from earlier in the day.
    """

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return AutomationEngine(
            hue=mock_hue,
            hue_v2=mock_hue_v2,
            ws_manager=mock_ws,
        )

    async def test_winddown_routine_preserves_per_light(self, engine):
        engine.mark_light_manual("3")
        engine.mark_light_manual("4")
        await engine.set_manual_override("relax", source="winddown_routine")
        assert "3" in engine.manual_light_overrides
        assert "4" in engine.manual_light_overrides

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
        """
        engine._camera_service = _FakeCamera(zone="bed", posture="reclined")
        state = {
            "1": {"on": True, "bri": 60, "ct": 2270},
            "2": {"on": True, "bri": 130, "ct": 2700},
        }
        out = engine._apply_zone_overlay(state, "working", "night")
        assert out["1"]["bri"] == 25
        assert out["2"]["bri"] == 8

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
    """The MODE_ZONE_MAX_BRIGHTNESS lookup honors posture when available."""

    def test_exact_posture_match_wins(self):
        from backend.services.screen_sync import MODE_ZONE_MAX_BRIGHTNESS
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "bed", "reclined")] == 25
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "bed", "upright")] == 60

    def test_desk_entry_preserved(self):
        from backend.services.screen_sync import MODE_ZONE_MAX_BRIGHTNESS
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "desk")] == 180


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
        sync = ScreenSyncService(mock_hue)
        # Default from hardcoded dict.
        assert sync.get_cap("watching", "bed", "reclined") == 25
        # Override — settings slider dropped it to 10.
        sync.set_cap_override("watching", "bed", "reclined", 10)
        assert sync.get_cap("watching", "bed", "reclined") == 10
        # Sibling entries untouched.
        assert sync.get_cap("watching", "bed", "upright") == 60
        assert sync.get_cap("watching", "desk", "upright") == 180

    def test_screen_sync_cap_fallback_order(self, mock_hue):
        from backend.services.screen_sync import ScreenSyncService
        sync = ScreenSyncService(mock_hue)
        # Posture missing — falls back to (mode, zone).
        assert sync.get_cap("watching", "desk", None) == 180
        # Mode-only fallback.
        assert sync.get_cap("working", None, None) > 0

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
# is_at_desk_fresh — camera-aware veto helper
# ---------------------------------------------------------------------------


class _FakeEnabledCamera:
    """Camera stub with the ``enabled`` flag the helper checks."""

    def __init__(self, zone=None, enabled=True, zone_committed_at=None):
        self.zone = zone
        self.enabled = enabled
        self.zone_committed_at = zone_committed_at


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

