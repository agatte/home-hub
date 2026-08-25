"""Focused tests for the first #129/#130 living-room atmosphere slice."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import SceneActivation
from backend.services.automation_engine import AutomationEngine
from backend.services.light_applicator import LightApplyResult
from backend.services.light_state_calculator import ACTIVITY_LIGHT_STATES
from backend.services.living_room_atmosphere import (
    ATMOSPHERES,
    LIVING_ROOM_ATMOSPHERE_LIGHT_IDS,
    LivingRoomAtmosphereCurator,
    bound_living_room_atmosphere_brightness,
    merge_living_room_atmosphere,
    preserve_atmosphere_effect_scope,
)


START = datetime(2026, 8, 12, 19, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


class FakeGate:
    def __init__(self, envelope: dict) -> None:
        self.envelope = envelope

    async def evaluate(self, *, trigger: str = "normal") -> None:
        del trigger

    def current_envelope(self) -> dict:
        return self.envelope


def _envelope(
    *,
    eligible: bool = True,
    weather: str | None = "Clear",
    weather_freshness: str = "fresh",
    music: str = "stopped",
    music_freshness: str = "fresh",
    sonos_health: str = "healthy",
    reasons: tuple[str, ...] = (),
) -> dict:
    return {
        "shadow_only": True,
        "snapshot": {
            "effective_mode": "relax",
            "weather": {
                "state": weather,
                "freshness": weather_freshness,
                "stale_fallback": weather_freshness != "fresh",
            },
            "music_sonos_health": {"status": sonos_health},
            "music_state": {
                "state": music,
                "freshness": music_freshness,
            },
        },
        "decision": {
            "eligible_for_scene_curator": eligible,
            "reason_codes": list(reasons),
        },
    }


def _pin_evening_outside_winddown_ramp(engine: AutomationEngine) -> None:
    """Keep evening-state tests independent of the wall-clock ramp window."""
    engine._schedule_config.weekday.winddown_start_hour = 0
    engine._schedule_config.weekend.winddown_start_hour = 0

def _decide(
    curator: LivingRoomAtmosphereCurator,
    envelope: dict,
    *,
    period: str = "evening",
    provenance: str = "physical_context_relax",
    started_at: datetime = START,
    scene_override: bool = False,
):
    return curator.decide(
        envelope,
        period=period,
        provenance=provenance,
        session_started_at=started_at,
        scene_override_active=scene_override,
    )


def test_quiet_couch_selects_moss_ember_deterministically() -> None:
    first = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    second = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    assert _decide(first, _envelope()).atmosphere_id == "moss_ember"
    assert _decide(second, _envelope()).atmosphere_id == "moss_ember"
    assert first.current_status()["candidates"] == second.current_status()["candidates"]


def test_fresh_sonos_playing_selects_listening_glow() -> None:
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    plan = _decide(curator, _envelope(music="playing"))
    assert plan.atmosphere_id == "listening_glow"
    assert curator.current_status()["context"]["music"] == "playing"


@pytest.mark.parametrize(
    ("music_freshness", "sonos_health"),
    [("stale", "healthy"), ("missing", "unavailable")],
)
def test_missing_or_stale_sonos_stays_unknown_but_curates_quiet_couch(
    music_freshness: str,
    sonos_health: str,
) -> None:
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    plan = _decide(curator, _envelope(
        music="playing",
        music_freshness=music_freshness,
        sonos_health=sonos_health,
    ))
    assert plan.atmosphere_id == "moss_ember"
    assert curator.current_status()["context"]["music"] == "unknown"


@pytest.mark.parametrize("weather", ["Rain", "Thunderstorms", "Overcast clouds"])
def test_rain_storm_and_heavy_cloud_favor_rainy_forest(weather: str) -> None:
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    assert _decide(curator, _envelope(weather=weather)).atmosphere_id == "rainy_forest"


def test_missing_weather_is_safe_and_recent_history_breaks_only_a_tie() -> None:
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    curator._recent_history = ["moss_ember"]
    missing = _envelope(weather=None, weather_freshness="missing")
    assert _decide(curator, missing).atmosphere_id == "rainy_forest"

    rainy = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    rainy._recent_history = ["rainy_forest"]
    assert _decide(rainy, _envelope(weather="Heavy rain")).atmosphere_id == "rainy_forest"


def test_merge_owns_l1_l3_l4_l6_with_matched_kitchen_and_one_colorspace() -> None:
    ordinary = ACTIVITY_LIGHT_STATES["relax"]["evening"]
    for definition in ATMOSPHERES.values():
        merged = merge_living_room_atmosphere(
            ordinary,
            definition.palettes["evening"],
        )
        assert merged["2"] == ordinary["2"]
        assert merged["5"] == ordinary["5"]
        assert merged["6"] == definition.palettes["evening"]["6"]
        assert merged["3"] == merged["4"]
        for state in merged.values():
            assert not ("ct" in state and ({"hue", "sat"} & state.keys()))


def test_moss_raw_calibration_changes_only_day_evening_brightness() -> None:
    moss = ATMOSPHERES["moss_ember"].palettes
    assert moss["day"] == {
        "1": {"on": True, "bri": 110, "hue": 7500, "sat": 200},
        "3": {"on": True, "bri": 40, "hue": 20000, "sat": 100},
        "4": {"on": True, "bri": 40, "hue": 20000, "sat": 100},
        "6": {"on": True, "bri": 185, "hue": 44000, "sat": 165},
    }
    assert moss["evening"] == {
        "1": {"on": True, "bri": 90, "hue": 6000, "sat": 230},
        "3": {"on": True, "bri": 30, "hue": 20000, "sat": 100},
        "4": {"on": True, "bri": 30, "hue": 20000, "sat": 100},
        "6": {"on": True, "bri": 165, "hue": 64000, "sat": 185},
    }
    assert moss["night"] == {
        "1": {"on": True, "bri": 38, "hue": 5000, "sat": 254},
        "3": {"on": True, "bri": 8, "hue": 20000, "sat": 100},
        "4": {"on": True, "bri": 8, "hue": 20000, "sat": 100},
        "6": {"on": True, "bri": 110, "hue": 65000, "sat": 200},
    }
    assert moss["late_night"] == {
        "1": {"on": True, "bri": 34, "hue": 3000, "sat": 240},
        "3": {"on": True, "bri": 5, "hue": 20000, "sat": 100},
        "4": {"on": True, "bri": 5, "hue": 20000, "sat": 100},
        "6": {"on": True, "bri": 75, "hue": 65000, "sat": 190},
    }


def test_rainy_forest_and_listening_glow_raw_palettes_are_unchanged() -> None:
    expected = {
        "rainy_forest": {
            "day": ((90, 7000, 180), (35, 39500, 120), (180, 42000, 150)),
            "evening": ((65, 5500, 210), (20, 39500, 130), (170, 44000, 160)),
            "night": ((42, 5000, 220), (12, 39500, 130), (130, 46000, 155)),
            "late_night": ((36, 4000, 220), (8, 39500, 120), (90, 64000, 175)),
        },
        "listening_glow": {
            "day": ((115, 48000, 140), (40, 6500, 170), (190, 44000, 160)),
            "evening": ((85, 48000, 150), (28, 6000, 185), (185, 46000, 165)),
            "night": ((55, 47000, 150), (18, 5500, 190), (130, 64000, 185)),
            "late_night": ((45, 46000, 130), (12, 5000, 175), (85, 65000, 180)),
        },
    }
    for atmosphere_id, periods in expected.items():
        for period, (living, kitchen, plant_wash) in periods.items():
            palette = ATMOSPHERES[atmosphere_id].palettes[period]
            assert palette["1"] == {
                "on": True,
                "bri": living[0],
                "hue": living[1],
                "sat": living[2],
            }
            assert palette["3"] == palette["4"] == {
                "on": True,
                "bri": kitchen[0],
                "hue": kitchen[1],
                "sat": kitchen[2],
            }
            assert palette["6"] == {
                "on": True,
                "bri": plant_wash[0],
                "hue": plant_wash[1],
                "sat": plant_wash[2],
            }


@pytest.mark.parametrize(
    ("period", "processed_bri", "expected_bri"),
    [
        ("day", 40, 100),
        ("evening", 89, 100),
        ("night", 200, 110),
        ("late_night", 200, 100),
    ],
)
def test_bounded_brightness_enforces_period_limits_without_touching_color(
    period: str,
    processed_bri: int,
    expected_bri: int,
) -> None:
    basis = {
        light_id: {"on": True, "bri": 100, "hue": 7000, "sat": 180}
        for light_id in LIVING_ROOM_ATMOSPHERE_LIGHT_IDS
    }
    state = {
        **{
            light_id: {
                "on": True,
                "bri": processed_bri,
                "hue": 7000,
                "sat": 180,
            }
            for light_id in LIVING_ROOM_ATMOSPHERE_LIGHT_IDS
        },
        "2": {"on": True, "bri": 37, "hue": 6500, "sat": 220},
        "5": {"on": True, "bri": 41, "hue": 6000, "sat": 210},
    }
    original = {light_id: light_state.copy() for light_id, light_state in state.items()}

    bounded = bound_living_room_atmosphere_brightness(state, basis, period)

    assert state == original
    assert bounded["1"]["bri"] == expected_bri
    assert bounded["3"]["bri"] == bounded["4"]["bri"] == expected_bri
    assert {
        light_id: (bounded[light_id]["hue"], bounded[light_id]["sat"])
        for light_id in LIVING_ROOM_ATMOSPHERE_LIGHT_IDS
    } == {
        light_id: (7000, 180)
        for light_id in LIVING_ROOM_ATMOSPHERE_LIGHT_IDS
    }
    assert bounded["2"] == state["2"]
    assert bounded["5"] == state["5"]


@pytest.mark.parametrize("atmosphere_id", ["rainy_forest", "listening_glow"])
@pytest.mark.parametrize(
    ("period", "environment_ratio", "bound_ratio"),
    [
        ("day", 0.90, 1.00),
        ("evening", 0.90, 1.00),
        ("night", 1.30, 1.10),
        ("late_night", 1.30, 1.00),
    ],
)
def test_other_atmospheres_get_bounds_without_palette_retuning(
    atmosphere_id: str,
    period: str,
    environment_ratio: float,
    bound_ratio: float,
) -> None:
    basis = ATMOSPHERES[atmosphere_id].palettes[period]
    processed = {
        light_id: {
            **light_state,
            "bri": int(light_state["bri"] * environment_ratio),
        }
        for light_id, light_state in basis.items()
    }

    bounded = bound_living_room_atmosphere_brightness(
        processed,
        basis,
        period,
    )

    for light_id in LIVING_ROOM_ATMOSPHERE_LIGHT_IDS:
        assert bounded[light_id]["bri"] == int(
            basis[light_id]["bri"] * bound_ratio
        )
        assert bounded[light_id]["hue"] == basis[light_id]["hue"]
        assert bounded[light_id]["sat"] == basis[light_id]["sat"]
    assert bounded["3"] == bounded["4"]

def test_relax_effects_stay_on_ordinary_l2_l5_not_atmosphere_lights() -> None:
    assert preserve_atmosphere_effect_scope("sparkle") == {
        "effect": "sparkle",
        "lights": ["2", "5"],
    }
    assert preserve_atmosphere_effect_scope({
        "effect": "fire",
        "lights": ["1", "2", "5"],
    }) == {"effect": "fire", "lights": ["2", "5"]}
    assert preserve_atmosphere_effect_scope({
        "effect": "opal",
        "lights": None,
    }) == {"effect": "opal", "lights": ["2", "5"]}


def test_scene_override_and_actual_manual_relax_veto_curator() -> None:
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    scene_plan = _decide(curator, _envelope(), scene_override=True)
    assert scene_plan.should_apply is False
    assert scene_plan.reason_codes == ("scene_override_configured",)

    manual_plan = _decide(
        curator,
        _envelope(eligible=False, reasons=("manual_mode_override_active",)),
        provenance="api:dashboard",
    )
    assert manual_plan.should_apply is False
    assert manual_plan.reason_codes == ("not_physical_context_relax",)


@pytest.mark.parametrize(
    "reason",
    ["dnd_active", "sleeping_active", "apartment_away"],
)
def test_authority_loss_falls_back_and_resets_session(reason: str) -> None:
    clock = Clock()
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=clock)
    _decide(curator, _envelope())
    clock.now += timedelta(minutes=10)
    plan = _decide(
        curator,
        _envelope(eligible=False, reasons=(reason,)),
    )
    assert plan.should_apply is False
    assert curator.current_status()["session"]["started_at"] is None
    assert curator.current_status()["application"]["state"] == "fallback"

    recovered = _decide(curator, _envelope())
    assert recovered.action == "apply_initial"
    assert curator.current_status()["session"]["started_at"] == clock.now.isoformat()


def test_brief_couch_loss_fallback_retains_existing_session() -> None:
    clock = Clock()
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=clock)
    _decide(curator, _envelope())
    started_at = curator.current_status()["session"]["started_at"]
    clock.now += timedelta(seconds=10)
    plan = _decide(
        curator,
        _envelope(
            eligible=False,
            reasons=("authoritative_living_room_absent",),
        ),
    )
    assert plan.should_apply is False
    assert curator.current_status()["session"]["started_at"] == started_at


def test_session_settles_then_evolves_once_without_early_or_repeat_change() -> None:
    clock = Clock()
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=clock)
    unknown_weather = _envelope(weather=None, weather_freshness="missing")
    initial = _decide(curator, unknown_weather)
    assert initial.atmosphere_id == "moss_ember"

    clock.now = START + timedelta(minutes=15)
    before = _decide(curator, unknown_weather)
    assert before.atmosphere_id == "moss_ember"
    assert before.action == "hold"
    assert curator.current_status()["session"]["settled"] is True

    clock.now = START + timedelta(minutes=30)
    evolved = _decide(curator, unknown_weather)
    assert evolved.atmosphere_id == "rainy_forest"
    assert evolved.action == "evolve"
    assert curator.current_status()["session"]["evolved"] is True

    clock.now = START + timedelta(minutes=60)
    held = _decide(curator, unknown_weather)
    assert held.atmosphere_id == "rainy_forest"
    assert held.action == "hold"
    assert held.reason_codes == ("session_already_evolved",)


def test_period_reconciliation_keeps_candidate_and_does_not_count_as_evolution() -> None:
    clock = Clock()
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=clock)
    initial = _decide(curator, _envelope(), period="evening")
    clock.now += timedelta(minutes=20)
    reconciled = _decide(curator, _envelope(), period="night")
    assert reconciled.atmosphere_id == initial.atmosphere_id
    assert reconciled.action == "reconcile_period"
    assert curator.current_status()["session"]["evolved"] is False


@pytest.mark.asyncio
async def test_history_advances_only_after_genuine_successful_application() -> None:
    log_activation = AsyncMock()
    curator = LivingRoomAtmosphereCurator(
        enabled=True,
        log_activation=log_activation,
        now_provider=Clock(),
    )
    plan = _decide(curator, _envelope())

    await curator.observe_application(
        plan,
        LightApplyResult(failed={"1"}, successful={"3", "4", "6"}),
    )
    log_activation.assert_not_awaited()
    assert curator._recent_history == []

    retry_plan = _decide(curator, _envelope())
    assert retry_plan.record_history is True
    await curator.observe_application(
        retry_plan,
        LightApplyResult(successful={"1", "3", "4", "6"}),
    )
    log_activation.assert_awaited_once_with(
        "living_room_atmosphere:moss_ember",
        "Moss & Ember",
        "atmosphere",
        "relax",
    )
    assert curator._recent_history == ["moss_ember"]


@pytest.mark.asyncio
async def test_protected_target_does_not_block_successful_history() -> None:
    log_activation = AsyncMock()
    curator = LivingRoomAtmosphereCurator(
        enabled=True,
        log_activation=log_activation,
        now_provider=Clock(),
    )
    plan = _decide(curator, _envelope())

    await curator.observe_application(
        plan,
        LightApplyResult(successful={"1", "4", "6"}, skipped={"3"}),
    )

    log_activation.assert_awaited_once_with(
        "living_room_atmosphere:moss_ember",
        "Moss & Ember",
        "atmosphere",
        "relax",
    )
    assert curator.current_status()["application"]["state"] == "applied"
    assert curator._recent_history == ["moss_ember"]


@pytest.mark.asyncio
async def test_all_protected_targets_do_not_persist_history() -> None:
    log_activation = AsyncMock()
    curator = LivingRoomAtmosphereCurator(
        enabled=True,
        log_activation=log_activation,
        now_provider=Clock(),
    )
    plan = _decide(curator, _envelope())

    await curator.observe_application(
        plan,
        LightApplyResult(skipped={"1", "3", "4", "6"}),
    )

    log_activation.assert_not_awaited()
    assert curator._recent_history == []


@pytest.mark.asyncio
async def test_successful_application_persists_in_existing_scene_history(
    db_engine,
) -> None:
    session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def log_activation(scene_id, scene_name, source, mode_at_time):
        async with session_factory() as session:
            session.add(SceneActivation(
                scene_id=scene_id,
                scene_name=scene_name,
                source=source,
                mode_at_time=mode_at_time,
            ))
            await session.commit()

    curator = LivingRoomAtmosphereCurator(
        enabled=True,
        session_factory=session_factory,
        log_activation=log_activation,
        now_provider=Clock(),
    )
    plan = _decide(curator, _envelope())
    await curator.observe_application(
        plan,
        LightApplyResult(successful={"1", "3", "4", "6"}),
    )

    history = await curator.history(10)
    assert history[0]["atmosphere_id"] == "moss_ember"
    assert history[0]["source"] == "atmosphere"
    assert history[0]["mode_at_time"] == "relax"


@pytest.mark.asyncio
async def test_history_failure_does_not_escape_application_path() -> None:
    curator = LivingRoomAtmosphereCurator(
        enabled=True,
        log_activation=AsyncMock(side_effect=RuntimeError("db unavailable")),
        now_provider=Clock(),
    )
    plan = _decide(curator, _envelope())
    await curator.observe_application(
        plan,
        LightApplyResult(successful={"1", "3", "4", "6"}),
    )
    assert curator.current_status()["application"]["state"] == "applied"
    assert curator._recent_history == []
    assert curator._pending_history is not None


def test_disabled_switch_keeps_would_be_selection_observable_but_not_applied() -> None:
    curator = LivingRoomAtmosphereCurator(enabled=False, now_provider=Clock())
    plan = _decide(curator, _envelope(music="playing"))
    status = curator.current_status()
    assert plan.atmosphere_id == "listening_glow"
    assert plan.should_apply is False
    assert status["enabled"] is False
    assert status["application"]["reason"] == "feature_disabled"


@pytest.mark.asyncio
async def test_engine_uses_existing_dedup_and_preserves_l2_l5(
    mock_hue, mock_hue_v2, mock_ws,
) -> None:
    clock = Clock()
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=clock)
    engine = AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
    )
    engine.set_living_room_decision_gate(FakeGate(_envelope()))
    engine.set_living_room_atmosphere_curator(curator)
    engine._manual_override = True
    engine._override_mode = "relax"
    engine._override_source = "physical_context_relax"
    engine._override_time = START
    _pin_evening_outside_winddown_ramp(engine)
    engine._get_time_period = lambda now=None: "evening"
    engine._effect_manager.needs_reconcile = lambda _desired: False
    calls: list[str] = []
    original = mock_hue.set_light

    async def counting(light_id: str, state: dict) -> bool:
        calls.append(light_id)
        return await original(light_id, state)

    mock_hue.set_light = counting
    await engine._apply_mode("relax")
    assert mock_hue._lights["2"]["bri"] == ACTIVITY_LIGHT_STATES["relax"]["evening"]["2"]["bri"]
    assert mock_hue._lights["5"]["bri"] == ACTIVITY_LIGHT_STATES["relax"]["evening"]["5"]["bri"]
    assert mock_hue._lights["3"]["bri"] == mock_hue._lights["4"]["bri"]
    first_count = len(calls)

    await engine._apply_mode("relax")
    assert len(calls) == first_count
    assert curator.current_status()["application"]["state"] == "held"


@pytest.mark.asyncio
async def test_manual_plant_wash_target_is_not_overwritten_by_curator(
    mock_hue, mock_hue_v2, mock_ws,
) -> None:
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    engine = AutomationEngine(hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws)
    engine.set_living_room_decision_gate(FakeGate(_envelope()))
    engine.set_living_room_atmosphere_curator(curator)
    engine._manual_override = True
    engine._override_mode = "relax"
    engine._override_source = "physical_context_relax"
    engine._override_time = START
    _pin_evening_outside_winddown_ramp(engine)
    engine._get_time_period = lambda now=None: "evening"
    engine._effect_manager.needs_reconcile = lambda _desired: False
    manual = {"on": True, "bri": 42, "hue": 12000, "sat": 90}
    mock_hue._lights["6"].update(manual)
    engine.mark_light_manual("6", manual)

    await engine._apply_mode("relax", force_resend=True)

    assert {
        key: mock_hue._lights["6"][key] for key in manual
    } == manual


@pytest.mark.asyncio
async def test_engine_live_evening_lux_case_floors_only_atmosphere_lights(
    mock_hue, mock_hue_v2, mock_ws,
) -> None:
    class FreshLuxCamera:
        enabled = True
        _paused = False
        ema_lux = 150.0
        baseline_lux = 90.0
        last_lux_update = datetime.now(timezone.utc)

    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    engine = AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
    )
    engine.set_camera_service(FreshLuxCamera())
    engine.set_living_room_decision_gate(FakeGate(_envelope()))
    engine.set_living_room_atmosphere_curator(curator)
    engine._manual_override = True
    engine._override_mode = "relax"
    engine._override_source = "physical_context_relax"
    engine._override_time = START
    _pin_evening_outside_winddown_ramp(engine)
    engine._get_time_period = lambda now=None: "evening"
    engine._effect_manager.needs_reconcile = lambda _desired: False

    await engine._apply_mode("relax", force_resend=True)

    assert engine.last_lux_multiplier == pytest.approx(0.90)
    assert mock_hue._lights["1"]["bri"] == 90
    assert mock_hue._lights["3"]["bri"] == 30
    assert mock_hue._lights["4"]["bri"] == 30
    assert mock_hue._lights["2"]["bri"] == int(
        ACTIVITY_LIGHT_STATES["relax"]["evening"]["2"]["bri"] * 0.90
    )
    assert mock_hue._lights["5"]["bri"] == int(
        ACTIVITY_LIGHT_STATES["relax"]["evening"]["5"]["bri"] * 0.90
    )
    for light_id in LIVING_ROOM_ATMOSPHERE_LIGHT_IDS:
        expected = ATMOSPHERES["moss_ember"].palettes["evening"][light_id]
        assert mock_hue._lights[light_id]["hue"] == expected["hue"]
        assert mock_hue._lights[light_id]["sat"] == expected["sat"]


@pytest.mark.asyncio
async def test_learner_cannot_replace_atmosphere_owned_lights(
    mock_hue, mock_hue_v2, mock_ws,
) -> None:
    ordinary = ACTIVITY_LIGHT_STATES["relax"]["evening"]

    class OrdinaryRelaxLearner:
        def get_overlay(self, *_args, **_kwargs):
            return {
                "1": ordinary["1"],
                "2": {"bri": 100},
                "3": ordinary["3"],
                "4": ordinary["4"],
            }

    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    engine = AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
        lighting_learner=OrdinaryRelaxLearner(),
    )
    engine.set_living_room_decision_gate(FakeGate(_envelope()))
    engine.set_living_room_atmosphere_curator(curator)
    engine._manual_override = True
    engine._override_mode = "relax"
    engine._override_source = "physical_context_relax"
    engine._override_time = START
    _pin_evening_outside_winddown_ramp(engine)
    engine._get_time_period = lambda now=None: "evening"
    engine._mode_brightness["relax"] = 0.80
    engine._effect_manager.needs_reconcile = lambda _desired: False

    await engine._apply_mode("relax", force_resend=True)

    assert mock_hue._lights["1"]["bri"] == 72
    assert mock_hue._lights["3"]["bri"] == 24
    assert mock_hue._lights["4"]["bri"] == 24
    assert mock_hue._lights["2"]["bri"] == 80
    assert mock_hue._lights["5"]["bri"] == 60
    for light_id in LIVING_ROOM_ATMOSPHERE_LIGHT_IDS:
        expected = ATMOSPHERES["moss_ember"].palettes["evening"][light_id]
        assert mock_hue._lights[light_id]["hue"] == expected["hue"]
        assert mock_hue._lights[light_id]["sat"] == expected["sat"]

@pytest.mark.asyncio
async def test_configured_scene_override_wins_before_curator_palette(
    mock_hue, mock_hue_v2, mock_ws,
) -> None:
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    engine = AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
    )
    engine.set_living_room_decision_gate(FakeGate(_envelope()))
    engine.set_living_room_atmosphere_curator(curator)
    engine._manual_override = True
    engine._override_mode = "relax"
    engine._override_source = "physical_context_relax"
    engine._override_time = START
    _pin_evening_outside_winddown_ramp(engine)
    engine._get_time_period = lambda now=None: "evening"
    engine._scene_overrides = {"relax": {"evening": "bridge-scene"}}
    engine._effect_manager.replace_with_action = AsyncMock(return_value=True)
    mock_hue.set_light = AsyncMock(return_value=True)

    await engine._apply_mode("relax", force_resend=True)

    engine._effect_manager.replace_with_action.assert_awaited_once()
    mock_hue.set_light.assert_not_awaited()
    status = curator.current_status()
    assert status["application"]["reason"] == "scene_override_configured"


@pytest.mark.asyncio
async def test_selector_failure_falls_back_to_ordinary_relax(
    mock_hue, mock_hue_v2, mock_ws,
) -> None:
    curator = LivingRoomAtmosphereCurator(enabled=True, now_provider=Clock())
    curator.decide = MagicMock(side_effect=RuntimeError("selector boom"))
    engine = AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
    )
    engine.set_living_room_decision_gate(FakeGate(_envelope()))
    engine.set_living_room_atmosphere_curator(curator)
    engine._manual_override = True
    engine._override_mode = "relax"
    engine._override_source = "physical_context_relax"
    engine._override_time = START
    _pin_evening_outside_winddown_ramp(engine)
    engine._get_time_period = lambda now=None: "evening"
    engine._effect_manager.needs_reconcile = lambda _desired: False

    await engine._apply_mode("relax", force_resend=True)
    ordinary = ACTIVITY_LIGHT_STATES["relax"]["evening"]
    assert mock_hue._lights["1"]["bri"] == ordinary["1"]["bri"]
    assert mock_hue._lights["3"]["hue"] == ordinary["3"]["hue"]
    assert curator.current_status()["application"]["reason"] == "selector_failure"


@pytest.mark.asyncio
async def test_disabled_switch_applies_ordinary_relax_in_engine(
    mock_hue, mock_hue_v2, mock_ws,
) -> None:
    curator = LivingRoomAtmosphereCurator(enabled=False, now_provider=Clock())
    engine = AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
    )
    engine.set_living_room_decision_gate(FakeGate(_envelope(music="playing")))
    engine.set_living_room_atmosphere_curator(curator)
    engine._manual_override = True
    engine._override_mode = "relax"
    engine._override_source = "physical_context_relax"
    engine._override_time = START
    _pin_evening_outside_winddown_ramp(engine)
    engine._get_time_period = lambda now=None: "evening"
    engine._effect_manager.needs_reconcile = lambda _desired: False

    await engine._apply_mode("relax", force_resend=True)
    ordinary = ACTIVITY_LIGHT_STATES["relax"]["evening"]
    assert mock_hue._lights["1"]["bri"] == ordinary["1"]["bri"]
    assert mock_hue._lights["3"]["hue"] == ordinary["3"]["hue"]
    status = curator.current_status()
    assert status["selected_atmosphere"] == "listening_glow"
    assert status["application"]["reason"] == "feature_disabled"


def test_every_palette_is_bounded_to_living_room_lights() -> None:
    for definition in ATMOSPHERES.values():
        for palette in definition.palettes.values():
            assert set(palette) == set(LIVING_ROOM_ATMOSPHERE_LIGHT_IDS)
