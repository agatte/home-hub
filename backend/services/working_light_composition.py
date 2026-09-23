"""Pure Working-light composition stages shared by production and replay.

Production resolves service-backed inputs between these stages so current read
and await opportunities remain unchanged. Replay can call compose_working_lights
with captured resolved values and never import live services or AutomationEngine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from backend.services.light_state_calculator import (
    BED_RECLINED_L1_NIGHT_DEFAULT,
    apply_brightness_multiplier,
    apply_functional_weather_brightness,
    apply_gaming_day_surround_brightness,
    apply_lux_multiplier,
    apply_weather_adjust,
    apply_zone_overlay,
    enforce_fixture_comfort_invariants,
    enforce_post_sunset_ct_warmth,
    resolve_activity_state,
)


LightState = dict[str, dict[str, Any]]


@dataclass(frozen=True)
class WorkingLearnerStage:
    state: LightState
    learner_deltas: dict[str, dict[str, dict[str, Any]]]


@dataclass(frozen=True)
class WorkingLuxStage:
    state: LightState
    last_lux_multiplier: float
    last_weather_class: str | None


@dataclass(frozen=True)
class WorkingComposition:
    state: LightState
    last_lux_multiplier: float
    last_weather_class: str | None
    learner_deltas: dict[str, dict[str, dict[str, Any]]]


def apply_working_learner_overlay(
    state: LightState,
    learner_overlay: Mapping[str, Mapping[str, Any]] | None,
) -> WorkingLearnerStage:
    composed = {
        light_id: light.copy()
        for light_id, light in state.items()
    }
    deltas: dict[str, dict[str, dict[str, Any]]] = {}
    for light_id, prefs in (learner_overlay or {}).items():
        if light_id not in composed:
            continue
        before = composed[light_id]
        changes = {
            key: {"before": before.get(key), "after": value}
            for key, value in prefs.items()
            if before.get(key) != value
        }
        if changes:
            deltas[light_id] = changes
        composed[light_id] = {**before, **prefs}
    return WorkingLearnerStage(composed, deltas)


def apply_working_brightness(
    state: LightState,
    mode_brightness: float,
) -> LightState:
    return apply_brightness_multiplier(
        state,
        "working",
        {"working": float(mode_brightness)},
    )


def apply_working_lux(
    state: LightState,
    *,
    ema_lux: float | None,
    baseline_lux: float | None,
    last_lux_multiplier: float,
    last_weather_class: str | None,
    weather_class: str | None,
) -> WorkingLuxStage:
    new_state, new_multiplier, new_weather_class = apply_lux_multiplier(
        state,
        "working",
        ema_lux,
        last_lux_multiplier,
        baseline_lux,
        weather_class=weather_class,
        last_weather_class=last_weather_class,
    )
    return WorkingLuxStage(
        new_state,
        new_multiplier,
        new_weather_class,
    )


def apply_working_functional_weather(
    state: LightState,
    *,
    period: str,
    weather_condition: str | None,
    learned_weather_light_ids: set[str],
) -> LightState:
    return apply_functional_weather_brightness(
        state,
        "working",
        period,
        weather_condition,
        learner_has_learned=learned_weather_light_ids,
    )


def apply_working_gaming_surround_noop(
    state: LightState,
    *,
    period: str,
    weather_condition: str | None,
    ema_lux: float | None,
    baseline_lux: float | None,
    mode_brightness: float,
) -> LightState:
    return apply_gaming_day_surround_brightness(
        state,
        "working",
        period,
        weather_condition,
        lux_reading=ema_lux,
        baseline_lux=baseline_lux,
        brightness_multiplier=float(mode_brightness),
    )


def apply_working_zone_posture(
    state: LightState,
    *,
    period: str,
    zone: str | None,
    posture: str | None,
    bed_reclined_l1_night: int,
) -> LightState:
    return apply_zone_overlay(
        state,
        "working",
        period,
        zone,
        posture,
        bed_reclined_l1_night,
    )


def apply_working_weather_adjust(
    state: LightState,
    weather_condition: str | None,
) -> LightState:
    return apply_weather_adjust(state, weather_condition)


def apply_working_fixture_comfort(
    state: LightState,
    *,
    period: str,
    comfort_zone: str | None,
) -> LightState:
    return enforce_fixture_comfort_invariants(
        state,
        "working",
        period,
        comfort_zone,
    )


def apply_working_post_sunset_warmth(
    state: LightState,
    period: str,
) -> LightState:
    return enforce_post_sunset_ct_warmth(state, period)


def compose_working_lights(
    *,
    period: str,
    current_game: str | None = None,
    learner_overlay: Mapping[str, Mapping[str, Any]] | None = None,
    mode_brightness: float = 1.0,
    lux_ema: float | None = None,
    lux_baseline: float | None = None,
    last_lux_multiplier: float = 1.0,
    last_weather_class: str | None = None,
    lux_weather_class: str | None = None,
    functional_weather_condition: str | None = None,
    learned_weather_light_ids: set[str] | None = None,
    gaming_lux_ema: float | None = None,
    gaming_lux_baseline: float | None = None,
    gaming_weather_condition: str | None = None,
    zone: str | None = None,
    posture: str | None = None,
    bed_reclined_l1_night: int = BED_RECLINED_L1_NIGHT_DEFAULT,
    apply_weather_adjustment: bool = False,
    weather_adjust_condition: str | None = None,
    comfort_zone: str | None = None,
) -> WorkingComposition:
    state = resolve_activity_state("working", period, current_game)
    learner = apply_working_learner_overlay(state, learner_overlay)
    state = apply_working_brightness(learner.state, mode_brightness)
    lux = apply_working_lux(
        state,
        ema_lux=lux_ema,
        baseline_lux=lux_baseline,
        last_lux_multiplier=last_lux_multiplier,
        last_weather_class=last_weather_class,
        weather_class=lux_weather_class,
    )
    state = apply_working_functional_weather(
        lux.state,
        period=period,
        weather_condition=functional_weather_condition,
        learned_weather_light_ids=learned_weather_light_ids or set(),
    )
    state = apply_working_gaming_surround_noop(
        state,
        period=period,
        weather_condition=gaming_weather_condition,
        ema_lux=gaming_lux_ema,
        baseline_lux=gaming_lux_baseline,
        mode_brightness=mode_brightness,
    )
    state = apply_working_zone_posture(
        state,
        period=period,
        zone=zone,
        posture=posture,
        bed_reclined_l1_night=bed_reclined_l1_night,
    )
    if apply_weather_adjustment:
        state = apply_working_weather_adjust(
            state,
            weather_adjust_condition,
        )
    state = apply_working_fixture_comfort(
        state,
        period=period,
        comfort_zone=comfort_zone,
    )
    state = apply_working_post_sunset_warmth(state, period)
    return WorkingComposition(
        state=state,
        last_lux_multiplier=lux.last_lux_multiplier,
        last_weather_class=lux.last_weather_class,
        learner_deltas=learner.learner_deltas,
    )
