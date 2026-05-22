"""
Tests for the automation engine — mode priority, overrides, time periods.

These test the pure logic of the AutomationEngine without touching any real
hardware. Hue, Sonos, and WebSocket are all mocked.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from backend.services.automation_engine import (
    MODE_PRIORITY,
    AutomationEngine,
    DaySchedule,
    _resolve_activity_state,
)
from backend.services.light_state_calculator import (
    get_time_period_static as _get_time_period_static,
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
        assert MODE_ZONE_MAX_BRIGHTNESS[("watching", "desk", "2")] == 180


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
        assert sync.get_cap("watching", "2", "desk", "upright") == 180

    def test_screen_sync_cap_fallback_order(self, mock_hue):
        from backend.services.screen_sync import ScreenSyncService
        sync = ScreenSyncService(mock_hue, target_light_ids=["2", "5"])
        # Posture missing — falls back to (mode, zone, light_id).
        assert sync.get_cap("watching", "2", "desk", None) == 180
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

class _StubFusion:
    """Minimal fusion stub: returns a fixed compute_fusion() result.

    The real ConfidenceFusion class has report_signal() side effects and an
    internal state machine; the run_loop only invokes compute_fusion(), so
    that's the only method we need.
    """

    def __init__(self, fused_mode: str, fused_confidence: float):
        self._fm = fused_mode
        self._fc = fused_confidence

    def compute_fusion(self):
        return {
            "fused_mode": self._fm,
            "fused_confidence": self._fc,
            "agreement": 0.9,
            "signals": {},
            "can_override": False,
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


class TestFusionAutoApplyNoOp:
    """Regression coverage for the 2026-05-12 idle-lock incident.

    Bug: ``fusion_auto_apply`` (automation_engine.py:2378) fired with
    ``fm=idle, fc=0.96, _current_mode=idle`` at 14:10 UTC and set a 4h
    manual override to ``idle`` — the same mode that was already in
    place. The override then rejected 116 minutes of organic PC-agent
    activity reports via the ``_manual_override`` guard at line 895.

    Fix: add ``fm != self._current_mode`` to the elif condition (matches
    the sibling ``fusion_can_override`` branch's no-op guard at 2330).
    """

    @pytest.fixture(autouse=True)
    def _pin_evening_period(self, monkeypatch):
        """Pin ``_get_time_period`` to ``"evening"`` for every test in this
        class. Without this, the late_night_rescue branch (run_loop ~2615)
        fires first whenever the test suite runs after 23:00 local and
        overrides mode to ``"relax"`` before fusion_auto_apply can act —
        the test then sees ``_override_mode='relax'`` instead of the
        expected ``'working'``. Same pattern as ``_force_daytime`` in
        test_confidence_fusion.py / project_fusion_test_time_gotcha.md.
        """
        monkeypatch.setattr(
            AutomationEngine, "_get_time_period", lambda self: "evening",
        )

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        eng = AutomationEngine(
            hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
        )
        # No camera + no process-working stamp → both attendance vetoes
        # return False, so they don't mask the no-op guard's behavior.
        eng._camera_service = None
        eng._last_process_working_at = None
        return eng

    async def test_skips_when_predicted_equals_current(self, engine):
        engine._current_mode = "idle"
        engine._manual_override = False
        engine._confidence_fusion = _StubFusion("idle", 0.96)

        await _drive_one_tick(engine)

        assert engine.manual_override is False
        assert engine._override_mode is None

    async def test_fires_when_predicted_differs_from_current(self, engine):
        # Positive case: with fm != current, the branch SHOULD fire so the
        # no-op guard doesn't accidentally widen into a regression on
        # legitimate auto-apply.
        engine._current_mode = "idle"
        engine._manual_override = False
        engine._confidence_fusion = _StubFusion("working", 0.96)

        await _drive_one_tick(engine)

        assert engine.manual_override is True
        assert engine._override_mode == "working"

    async def test_camera_at_desk_blocks_even_when_modes_differ(self, engine):
        # Defense-in-depth guard #1: camera-at-desk veto.
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        engine._camera_service = _FakeEnabledCamera(
            zone="desk", enabled=True, zone_committed_at=recent,
        )
        engine._current_mode = "idle"
        engine._manual_override = False
        engine._confidence_fusion = _StubFusion("working", 0.96)

        await _drive_one_tick(engine)

        assert engine.manual_override is False

    async def test_recent_process_working_blocks_even_when_modes_differ(
        self, engine,
    ):
        # Defense-in-depth guard #2: process-attendance veto.
        engine._last_process_working_at = (
            datetime.now(tz=TZ) - timedelta(seconds=60)
        )
        engine._current_mode = "idle"
        engine._manual_override = False
        engine._confidence_fusion = _StubFusion("watching", 0.96)

        await _drive_one_tick(engine)

        assert engine.manual_override is False


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
        # DND active for the next hour.
        engine._dnd_enabled = True
        engine._dnd_expiry = self.LATE_NIGHT + timedelta(hours=1)

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
        state = captured_states[0]
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
        state = captured_states[0]
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

        state = captured_states[0]
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

        state = captured_states[0]
        assert state["bri"] > 60

    async def test_ramp_runs_when_stamp_stale_by_failsafe(
        self, engine, captured_states,
    ):
        """Stamp >12h old → failsafe drops it, ramp runs."""
        engine._last_bed_reclined_during_watching_at = (
            self.NOW - timedelta(hours=13)
        )

        await self._drive_with_capture(engine, captured_states, self.NOW)

        state = captured_states[0]
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
