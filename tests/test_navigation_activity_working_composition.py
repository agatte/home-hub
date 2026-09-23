from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from backend.services.automation_constants import SOURCE_STALE_SECONDS
from backend.services.automation_engine import AutomationEngine
from backend.services.effect_manager import WEATHER_SKIP_MODES
from backend.services.light_state_calculator import resolve_activity_state
from backend.services.navigation_activity_policy import (
    evaluate_override_expiry,
    has_fresh_mode_replacement,
    is_recent_desktop_interaction,
    override_is_user_owned,
    project_activity,
    project_current_mode,
    project_effective_mode,
    project_house_state,
)
from backend.services.working_light_composition import compose_working_lights

NOW = datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)


def test_projection_helpers_preserve_engine_semantics() -> None:
    assert project_current_mode(False, "relax", "working") == "working"
    assert project_current_mode(True, None, "idle") == "idle"
    assert project_current_mode(True, "working", "idle") == "working"
    assert project_house_state(True, "working") == "away"
    assert project_house_state(False, "sleeping") == "sleeping"
    assert project_house_state(False, "idle") == "home"
    assert project_activity("home", "idle") == "general"
    assert project_activity("home", "working") == "working"
    assert project_activity("away", "working") is None
    assert project_effective_mode("away", None, "working") == "away"
    assert project_effective_mode("sleeping", None, "working") == "sleeping"
    assert project_effective_mode("home", "general", "idle") == "general"



def test_away_projection_preserves_current_mode_short_circuit(
    mock_hue,
    mock_hue_v2,
    mock_ws,
) -> None:
    engine = AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
    )
    engine._away_hold = True
    with patch.object(
        AutomationEngine,
        "current_mode",
        new_callable=PropertyMock,
    ) as current_mode:
        assert engine.house_state == "away"
        assert engine.activity is None
        assert engine.effective_mode == "away"
        current_mode.assert_not_called()

def test_fresh_replacement_source_fallback_and_strict_boundary() -> None:
    reports = {"process": NOW - timedelta(seconds=SOURCE_STALE_SECONDS)}
    assert not has_fresh_mode_replacement(
        "working", "process", "missing", reports, NOW,
    )
    reports["missing"] = (
        NOW - timedelta(seconds=SOURCE_STALE_SECONDS)
        + timedelta(microseconds=1)
    )
    assert has_fresh_mode_replacement(
        "working", "process", "missing", reports, NOW,
    )
    assert not has_fresh_mode_replacement(
        "idle", "process", "missing", reports, NOW,
    )


def test_override_ownership_and_expiry_exact_boundaries() -> None:
    assert override_is_user_owned(True, "api:test")
    assert not override_is_user_owned(True, "ambient_relax")
    assert not override_is_user_owned(False, "api:test")

    common = dict(
        manual_override=True,
        override_mode="working",
        override_source="api:test",
        override_timeout_hours=4,
        current_mode="working",
        mode_source="process",
        mode_source_key="desktop",
        report_times={},
        now=NOW,
        expiry_deferred=False,
    )
    exact = evaluate_override_expiry(
        **common,
        override_time=NOW - timedelta(hours=4),
    )
    assert exact.suspend_idle_dwell is True
    assert exact.action == "none"

    expired = dict(
        common,
        override_time=NOW - timedelta(hours=4, microseconds=1),
    )
    assert evaluate_override_expiry(**expired).action == "defer"

    expired["report_times"] = {"desktop": NOW}
    assert (
        evaluate_override_expiry(**expired).action
        == "release_fresh_replacement"
    )

    expired["override_source"] = "ambient_relax"
    expired["report_times"] = {}
    assert evaluate_override_expiry(**expired).action == "release_autonomous"

    sleeping = dict(expired, override_mode="sleeping")
    decision = evaluate_override_expiry(**sleeping)
    assert decision.suspend_idle_dwell is False
    assert decision.action == "none"

    physical = dict(
        expired,
        override_mode="working",
        override_source="physical_context_relax",
    )
    decision = evaluate_override_expiry(**physical)
    assert decision.suspend_idle_dwell is False
    assert decision.action == "none"

    already_deferred = dict(
        common,
        override_time=NOW - timedelta(hours=5),
        expiry_deferred=True,
    )
    assert evaluate_override_expiry(**already_deferred).action == "none"


def test_recent_desktop_interaction_boundaries() -> None:
    evidence = SimpleNamespace(
        received_at=NOW + timedelta(seconds=2),
        idle_seconds=0.0,
    )
    assert is_recent_desktop_interaction(
        evidence,
        NOW,
        max_idle_seconds=5,
        max_report_age_seconds=10,
    )

    evidence.received_at = NOW - timedelta(seconds=10)
    evidence.idle_seconds = 4.999
    assert is_recent_desktop_interaction(
        evidence,
        NOW,
        max_idle_seconds=5,
        max_report_age_seconds=10,
    )

    evidence.idle_seconds = 5
    assert not is_recent_desktop_interaction(
        evidence,
        NOW,
        max_idle_seconds=5,
        max_report_age_seconds=10,
    )

    evidence.idle_seconds = 0
    evidence.received_at = NOW + timedelta(seconds=2, microseconds=1)
    assert not is_recent_desktop_interaction(
        evidence,
        NOW,
        max_idle_seconds=5,
        max_report_age_seconds=10,
    )

    evidence.idle_seconds = None
    assert not is_recent_desktop_interaction(
        evidence,
        NOW,
        max_idle_seconds=5,
        max_report_age_seconds=10,
    )


def _compose(**overrides):
    args = dict(
        period="day",
        learner_overlay=None,
        mode_brightness=1.0,
        lux_ema=350.0,
        lux_baseline=100.0,
        last_lux_multiplier=0.8,
        last_weather_class="clear",
        lux_weather_class="rain",
        functional_weather_condition=None,
        learned_weather_light_ids=set(),
        gaming_lux_ema=20.0,
        gaming_lux_baseline=100.0,
        gaming_weather_condition="thunderstorm",
        zone=None,
        posture=None,
        bed_reclined_l1_night=50,
        apply_weather_adjustment=False,
        weather_adjust_condition=None,
        comfort_zone=None,
    )
    args.update(overrides)
    return compose_working_lights(**args)


def test_working_plain_day_and_lux_hysteresis_are_preserved() -> None:
    result = _compose()
    assert result.state == resolve_activity_state("working", "day", None)
    assert result.last_lux_multiplier == 0.8
    assert result.last_weather_class == "clear"


def test_working_learner_overlay_deltas_then_brightness() -> None:
    base = resolve_activity_state("working", "day", None)
    result = _compose(
        learner_overlay={"2": {"bri": 100, "ct": 300}},
        mode_brightness=1.2,
    )
    assert result.learner_deltas["2"]["bri"] == {
        "before": base["2"]["bri"],
        "after": 100,
    }
    assert result.state["2"]["bri"] == 120
    assert result.state["2"]["ct"] == 300


def test_working_functional_weather_and_learned_skip() -> None:
    boosted = _compose(
        functional_weather_condition="rain",
        mode_brightness=0.5,
    )
    skipped = _compose(
        functional_weather_condition="rain",
        learned_weather_light_ids={"2"},
        mode_brightness=0.5,
    )
    assert skipped.state["2"]["bri"] < boosted.state["2"]["bri"]


def test_working_fixture_comfort_applies_after_other_transforms() -> None:
    ordinary = _compose(
        mode_brightness=1.5,
        functional_weather_condition="rain",
    )
    comfortable = _compose(
        mode_brightness=1.5,
        functional_weather_condition="rain",
        comfort_zone="desk",
    )
    assert comfortable.state["5"]["bri"] <= ordinary.state["5"]["bri"]


def test_working_current_game_is_non_relevant() -> None:
    assert _compose(current_game=None).state == _compose(
        current_game="colts",
    ).state


@pytest.mark.asyncio
async def test_engine_working_day_matches_pure_composition_and_sync_order(
    mock_hue,
    mock_hue_v2,
    mock_ws,
) -> None:
    engine = AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
    )
    engine._get_time_period = lambda now=None: "day"
    engine._get_desired_effect = lambda mode, period: None
    engine._effect_manager.needs_reconcile = lambda desired: False
    engine._read_fresh_camera_lux = lambda: (None, None)
    engine._get_current_weather_condition = lambda: None
    engine._current_zone_posture = lambda: (None, None)
    engine._fixture_comfort_zone = lambda: None

    events: list[tuple[str, dict]] = []

    class Sync:
        target_lights: list[str] = []

        def clear_accepted_gaming_state(self) -> None:
            return None

        def prime_from_mode_state(self, mode, period, state) -> None:
            events.append(("prime", state.copy()))

        def fresh_owned_light_ids(self) -> set[str]:
            return set()

    engine._screen_sync = Sync()

    async def apply(state, transitiontime=None):
        events.append(("apply", state.copy()))
        return True

    engine._apply_state = AsyncMock(side_effect=apply)
    await engine._apply_mode("working")

    expected = compose_working_lights(
        period="day",
        current_game=engine._current_game,
        learner_overlay=None,
        mode_brightness=engine._mode_brightness["working"],
        lux_ema=None,
        lux_baseline=None,
        last_lux_multiplier=1.0,
        last_weather_class=None,
        lux_weather_class=None,
        functional_weather_condition=None,
        learned_weather_light_ids=set(),
        gaming_lux_ema=None,
        gaming_lux_baseline=None,
        gaming_weather_condition=None,
        zone=None,
        posture=None,
        bed_reclined_l1_night=50,
        weather_adjust_condition=None,
        comfort_zone=None,
    ).state

    assert events == [
        ("prime", expected),
        ("apply", expected),
    ]


@pytest.mark.asyncio
async def test_working_keeps_learner_await_before_later_reads(
    mock_hue,
    mock_hue_v2,
    mock_ws,
) -> None:
    engine = AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
    )
    engine._get_time_period = lambda now=None: "day"
    engine._get_desired_effect = lambda mode, period: None
    engine._effect_manager.needs_reconcile = lambda desired: False
    engine._mode_brightness["working"] = 0.5

    events: list[str] = []
    phase = {"after_log": False}

    class Learner:
        def get_overlay(self, mode, period, weather, zone=None):
            events.append("learner_overlay")
            return {"2": {"bri": 100}}

        def has_weather_pref(self, mode, period, condition):
            events.append(f"learner_weather:{condition}")
            return set()

    class Logger:
        async def log_decision(self, **kwargs):
            events.append("learner_log")
            phase["after_log"] = True

    engine._lighting_learner = Learner()
    engine._ml_logger = Logger()

    zone_calls = 0

    def current_zone_posture():
        nonlocal zone_calls
        zone_calls += 1
        label = "overlay" if zone_calls == 1 else "post_log"
        events.append(f"zone:{label}")
        return None, None

    def read_lux():
        label = "after" if phase["after_log"] else "before"
        events.append(f"lux:{label}")
        return (40.0, 100.0)

    def read_weather():
        label = "rain" if phase["after_log"] else "clear"
        events.append(f"weather:{label}")
        return label

    engine._current_zone_posture = current_zone_posture
    engine._read_fresh_camera_lux = read_lux
    engine._get_current_weather_condition = read_weather
    engine._fixture_comfort_zone = lambda: (
        events.append("comfort") or None
    )
    engine._apply_state = AsyncMock(return_value=True)

    await engine._apply_mode("working")

    assert events == [
        "zone:overlay",
        "learner_overlay",
        "learner_log",
        "lux:after",
        "weather:rain",
        "weather:rain",
        "learner_weather:rain",
        "lux:after",
        "weather:rain",
        "zone:post_log",
        "comfort",
    ]


def test_shared_modules_have_no_production_adapter_imports() -> None:
    forbidden = (
        "automation_engine",
        "backend.config",
        "camera_service",
        "sqlalchemy",
        "backend.api",
        "bootstrap",
        "screen_sync",
        "effect_manager",
    )
    for relative in (
        "backend/services/navigation_activity_policy.py",
        "backend/services/working_light_composition.py",
    ):
        path = Path(relative)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        imports.extend(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not [
            name
            for name in imports
            if any(term in name for term in forbidden)
        ]
