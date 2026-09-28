"""Closed offline composition root for the bounded navigation-v1 replay."""

from __future__ import annotations

import copy
import math
from dataclasses import fields
from datetime import datetime
from typing import Any

from backend.services.automation_constants import (
    FIXTURE_COMFORT_DESK_STICKY_SECONDS,
    TZ,
    DaySchedule,
    ScheduleConfig,
)
from backend.services.engine_state import EngineState
from backend.services.light_applicator import LightApplicator
from backend.services.light_override_manager import LightOverrideManager
from backend.services.light_state_calculator import (
    LUX_STALE_SECONDS,
    MODE_TRANSITION_TIME,
    get_time_period,
)
from backend.services.lighting_transition_boundary import LightingTransitionBoundary
from backend.services.navigation_activity_policy import (
    evaluate_override_expiry,
    is_recent_desktop_interaction,
    project_activity,
    project_current_mode,
    project_effective_mode,
    project_house_state,
)
from backend.services.presence_fusion import PresenceFusion, PresenceReading
from backend.services.transit_lighting_service import TransitLightingService
from backend.services.working_light_composition import compose_working_lights

from .checkpoints import PendingEvaluationV1, ReplayCheckpointV1
from .clock import ReplayTimeError, parse_utc
from .scheduler import ReplayScheduler, schedule_recorded_inputs
from .schema import InputEnvelopeV1, KnownValue
from .sinks import RecordingEventSink, RecordingLightSink, ReplaySinkError
from .validate import IncidentBundleV1


class UnsupportedNavigationReplay(ValueError):
    """The validated bundle cannot be executed by the bounded v1 root."""


_PRESENCE_FIELDS = frozenset(
    {
        "source",
        "captured_at",
        "face_present",
        "face_confidence",
        "detection_source",
        "zone",
        "posture",
        "posture_confidence",
        "pose_visible_landmarks",
    }
)


_CAMERA_STATUS_FIELDS = frozenset(
    {
        "enabled",
        "last_detection",
        "detection_source",
        "confidence",
        "zone",
        "posture",
        "presence_authority_ready",
    }
)
_CAMERA_LUX_FIELDS = frozenset({"enabled", "paused", "ema_lux", "last_lux_update", "baseline_lux"})
_SCHEDULE_DAYS = frozenset({"weekday", "weekend"})
_DAY_SCHEDULE_FIELDS = frozenset(field.name for field in fields(DaySchedule))
_SUPPORTED_INPUT_KINDS = frozenset(
    {
        "fusion_ingest",
        "fusion_invalidation",
        "camera_status_change",
        "camera_lux_change",
        "engine_tick",
        "transit_tick",
        "deadline_tick",
        "restoration_tick",
    }
)


def _known_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, KnownValue) or not isinstance(value.value, dict):
        raise UnsupportedNavigationReplay(f"INCOMPLETE_INITIAL_STATE: {label}")
    return copy.deepcopy(value.value)


def _date(value: Any, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise UnsupportedNavigationReplay(f"INCOMPLETE_INITIAL_STATE: {label}")
    try:
        return parse_utc(value, label)
    except ReplayTimeError as exc:
        raise UnsupportedNavigationReplay(str(exc)) from exc


def _stamps(value: Any, label: str) -> dict[str, datetime]:
    if not isinstance(value, dict):
        raise UnsupportedNavigationReplay(f"INCOMPLETE_INITIAL_STATE: {label}")
    result: dict[str, datetime] = {}
    for key, stamp in value.items():
        if not isinstance(key, str) or not key:
            raise UnsupportedNavigationReplay(f"INCOMPLETE_INITIAL_STATE: {label}")
        parsed = _date(stamp, f"{label}.{key}")
        if parsed is None:
            raise UnsupportedNavigationReplay(f"INCOMPLETE_INITIAL_STATE: {label}.{key}")
        result[key] = parsed
    return result


_LIGHT_STATE_KEYS = frozenset({"on", "bri", "hue", "sat", "ct"})


def _light_state_map(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise UnsupportedNavigationReplay(f"INCOMPLETE_INITIAL_STATE: {label}")
    result: dict[str, dict[str, Any]] = {}
    for raw_light_id, raw_state in value.items():
        if not isinstance(raw_light_id, str) or not raw_light_id:
            raise UnsupportedNavigationReplay(f"INCOMPLETE_INITIAL_STATE: {label} light id")
        if not isinstance(raw_state, dict) or not set(raw_state) <= _LIGHT_STATE_KEYS:
            raise UnsupportedNavigationReplay(f"INCOMPLETE_INITIAL_STATE: {label}.{raw_light_id}")
        result[raw_light_id] = copy.deepcopy(raw_state)
    return result


def _optional_number(value: Any, label: str, *, unit_interval: bool = False) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise UnsupportedNavigationReplay(f"INCOMPLETE_INPUT: {label}")
    number = float(value)
    if unit_interval and not 0.0 <= number <= 1.0:
        raise UnsupportedNavigationReplay(f"INCOMPLETE_INPUT: {label}")
    return number


def _reading(value: Any, *, label: str = "presence") -> PresenceReading:
    if not isinstance(value, dict) or set(value) != _PRESENCE_FIELDS:
        raise UnsupportedNavigationReplay(
            f"INCOMPLETE_INPUT: {label} must capture every PresenceReading field"
        )
    source = value["source"]
    if not isinstance(source, str) or not source:
        raise UnsupportedNavigationReplay(f"INCOMPLETE_INPUT: {label}.source")
    face_present = value["face_present"]
    if face_present is not None and type(face_present) is not bool:
        raise UnsupportedNavigationReplay(f"INCOMPLETE_INPUT: {label}.face_present")
    for key in ("detection_source", "zone", "posture"):
        if value[key] is not None and not isinstance(value[key], str):
            raise UnsupportedNavigationReplay(f"INCOMPLETE_INPUT: {label}.{key}")
    landmarks = value["pose_visible_landmarks"]
    if landmarks is not None and (type(landmarks) is not int or landmarks < 0):
        raise UnsupportedNavigationReplay(f"INCOMPLETE_INPUT: {label}.pose_visible_landmarks")
    captured_at = _date(value["captured_at"], f"{label}.captured_at")
    assert captured_at is not None
    return PresenceReading(
        source=source,
        captured_at=captured_at,
        face_present=face_present,
        face_confidence=_optional_number(
            value["face_confidence"], f"{label}.face_confidence", unit_interval=True
        ),
        detection_source=value["detection_source"],
        zone=value["zone"],
        posture=value["posture"],
        posture_confidence=_optional_number(
            value["posture_confidence"],
            f"{label}.posture_confidence",
            unit_interval=True,
        ),
        pose_visible_landmarks=landmarks,
    )


def _validate_camera_status(value: Any, *, partial: bool = False) -> None:
    if not isinstance(value, dict):
        raise UnsupportedNavigationReplay("INCOMPLETE_INPUT: camera status")
    keys = set(value)
    if partial:
        if not keys or not keys <= _CAMERA_STATUS_FIELDS:
            raise UnsupportedNavigationReplay("INCOMPLETE_INPUT: camera status shape")
    elif keys != _CAMERA_STATUS_FIELDS:
        raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: camera status shape")
    if "enabled" in value and type(value["enabled"]) is not bool:
        raise UnsupportedNavigationReplay("INCOMPLETE_INPUT: camera status enabled")
    if "last_detection" in value and value["last_detection"] not in {
        "present",
        "absent",
        "unknown",
    }:
        raise UnsupportedNavigationReplay("INCOMPLETE_INPUT: camera last_detection")
    for key in ("detection_source", "zone", "posture"):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            raise UnsupportedNavigationReplay(f"INCOMPLETE_INPUT: camera status {key}")
    if "confidence" in value:
        _optional_number(value["confidence"], "camera confidence", unit_interval=True)
    if "presence_authority_ready" in value and type(value["presence_authority_ready"]) is not bool:
        raise UnsupportedNavigationReplay("INCOMPLETE_INPUT: camera presence_authority_ready")


def _validate_camera_lux(value: Any, *, partial: bool = False) -> None:
    if not isinstance(value, dict):
        raise UnsupportedNavigationReplay("INCOMPLETE_INPUT: camera lux")
    keys = set(value)
    if partial:
        if not keys or not keys <= _CAMERA_LUX_FIELDS:
            raise UnsupportedNavigationReplay("INCOMPLETE_INPUT: camera lux shape")
    elif keys != _CAMERA_LUX_FIELDS:
        raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: camera lux shape")
    for key in ("enabled", "paused"):
        if key in value and type(value[key]) is not bool:
            raise UnsupportedNavigationReplay(f"INCOMPLETE_INPUT: camera lux {key}")
    for key in ("ema_lux", "baseline_lux"):
        if key in value:
            _optional_number(value[key], f"camera lux {key}")
    if "last_lux_update" in value and value["last_lux_update"] is not None:
        _date(value["last_lux_update"], "camera.last_lux_update")


def _schedule(value: Any) -> ScheduleConfig:
    if not isinstance(value, dict) or set(value) != _SCHEDULE_DAYS:
        raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: Working schedule_config")
    parsed: dict[str, DaySchedule] = {}
    for day_name in ("weekday", "weekend"):
        raw = value[day_name]
        if not isinstance(raw, dict) or set(raw) != _DAY_SCHEDULE_FIELDS:
            raise UnsupportedNavigationReplay(
                f"INCOMPLETE_INITIAL_STATE: schedule_config.{day_name}"
            )
        if any(type(raw[name]) is not int for name in _DAY_SCHEDULE_FIELDS):
            raise UnsupportedNavigationReplay(
                f"INCOMPLETE_INITIAL_STATE: schedule_config.{day_name} values"
            )
        try:
            parsed[day_name] = DaySchedule(**raw)
        except TypeError as exc:
            raise UnsupportedNavigationReplay(
                f"INCOMPLETE_INITIAL_STATE: schedule_config.{day_name}"
            ) from exc
    return ScheduleConfig(weekday=parsed["weekday"], weekend=parsed["weekend"])


class _CameraView:
    def __init__(self, status: dict[str, Any], lux: dict[str, Any]) -> None:
        _validate_camera_status(status)
        _validate_camera_lux(lux)
        if status["enabled"] != lux["enabled"]:
            raise UnsupportedNavigationReplay(
                "INCOMPLETE_INITIAL_STATE: conflicting camera enabled state"
            )
        self.status = copy.deepcopy(status)
        self.lux = copy.deepcopy(lux)

    def get_status(self) -> dict[str, Any]:
        return copy.deepcopy(self.status)

    def update_status(self, value: dict[str, Any]) -> None:
        _validate_camera_status(value, partial=True)
        self.status.update(copy.deepcopy(value))
        if "enabled" in value:
            self.lux["enabled"] = value["enabled"]

    def update_lux(self, value: dict[str, Any]) -> None:
        _validate_camera_lux(value, partial=True)
        self.lux.update(copy.deepcopy(value))
        if "enabled" in value:
            self.status["enabled"] = value["enabled"]


class _NavigationAuthority:
    """Only the AutomationEngine surface Transit/reapply consumes in v1."""

    def __init__(
        self,
        root: "NavigationV1Replay",
        engine: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        self.root = root
        self.engine = engine
        self.context = context

    @property
    def current_mode(self) -> str:
        return project_current_mode(
            bool(self.engine["manual_override"]),
            self.engine["override_mode"],
            self.engine["current_mode"],
        )

    def _project_authority(self) -> tuple[str, str | None, str]:
        house = project_house_state(
            bool(self.engine["away_hold"]),
            self.current_mode,
        )
        activity = project_activity(house, self.current_mode)
        effective = project_effective_mode(house, activity, self.current_mode)
        return house, activity, effective

    def is_recent_desktop_interaction(
        self,
        *,
        max_idle_seconds: float,
        max_report_age_seconds: float,
    ) -> bool:
        return is_recent_desktop_interaction(
            None,
            self.root.clock.utc_now(),
            max_idle_seconds=max_idle_seconds,
            max_report_age_seconds=max_report_age_seconds,
        )

    def _read_fresh_camera_lux(self) -> tuple[float | None, float | None]:
        status = self.root.camera.status
        lux = self.root.camera.lux
        if not status["enabled"] or not lux["enabled"] or lux["paused"]:
            return None, None
        ema = lux["ema_lux"]
        if ema is None or lux["last_lux_update"] is None:
            return None, None
        last_update = _date(lux["last_lux_update"], "camera.last_lux_update")
        assert last_update is not None
        age = (self.root.clock.utc_now() - last_update).total_seconds()
        if age > LUX_STALE_SECONDS:
            return None, None
        baseline = lux["baseline_lux"]
        return float(ema), (float(baseline) if baseline is not None else None)

    async def evaluate_expiry(self) -> None:
        report_times = _stamps(
            self.engine["last_mode_source_report_at"],
            "engine.last_mode_source_report_at",
        )
        decision = evaluate_override_expiry(
            manual_override=bool(self.engine["manual_override"]),
            override_time=_date(self.engine["override_time"], "engine.override_time"),
            override_mode=self.engine["override_mode"],
            override_source=self.engine["override_source"],
            override_timeout_hours=float(self.engine["override_timeout_hours"]),
            current_mode=self.engine["current_mode"],
            mode_source=self.engine["mode_source"],
            mode_source_key=self.engine["mode_source_key"],
            report_times=report_times,
            now=self.root.clock.utc_now(),
            expiry_deferred=bool(self.engine["override_expiry_deferred"]),
        )
        if decision.suspend_idle_dwell:
            self.engine["idle_entered_at"] = None
        if decision.action == "defer":
            self.engine["override_expiry_deferred"] = True
        elif decision.action in {"release_autonomous", "release_fresh_replacement"}:
            self.engine["manual_override"] = False
            self.engine["override_mode"] = None
            self.engine["override_source"] = None
            self.engine["override_time"] = None
            self.engine["override_expiry_deferred"] = False
            self.root.overrides.invalidate_dedup_cache()
            await self.reapply_mode(self.engine["current_mode"])
        house, activity, effective = self._project_authority()
        if house != "home" or activity != "working" or effective != "working":
            raise UnsupportedNavigationReplay(
                "UNSUPPORTED_PROFILE: Working authority left navigation-v1"
            )

    async def apply_transit_override(self, states: dict[str, dict], **kwargs: Any) -> None:
        await self.root.overrides.apply_transit_override(states, **kwargs)

    async def clear_transit_override(self, **kwargs: Any) -> None:
        await self.root.overrides.clear_transit_override(**kwargs)

    def _comfort_zone(self) -> str | None:
        zone = self.root.fusion.latest_zone()
        if zone is not None:
            return zone
        seconds_since = self.root.fusion.seconds_since_at_desk()
        if (
            seconds_since is not None
            and -2.0 <= seconds_since <= FIXTURE_COMFORT_DESK_STICKY_SECONDS
        ):
            return "desk"
        return None

    async def reapply_mode(self, mode: str) -> None:
        if mode != "working":
            raise UnsupportedNavigationReplay(f"UNSUPPORTED_PROFILE: restoration mode {mode}")
        period = self.root.require_day_period()
        lux_ema, lux_baseline = self._read_fresh_camera_lux()
        gaming_lux_ema, gaming_lux_baseline = self._read_fresh_camera_lux()
        zone = self.root.fusion.latest_zone()
        posture = self.root.fusion.latest_posture()
        composition = compose_working_lights(
            period=period,
            current_game=self.context["current_game"],
            learner_overlay=self.context["learner_overlay_result"],
            mode_brightness=float(self.context["mode_brightness_working"]),
            lux_ema=lux_ema,
            lux_baseline=lux_baseline,
            last_lux_multiplier=float(self.context["last_lux_multiplier"]),
            last_weather_class=self.context["last_weather_class"],
            lux_weather_class=self.context["weather_condition"],
            functional_weather_condition=self.context["weather_condition"],
            learned_weather_light_ids=set(self.context["learner_weather_pref_lights"]),
            gaming_lux_ema=gaming_lux_ema,
            gaming_lux_baseline=gaming_lux_baseline,
            gaming_weather_condition=self.context["weather_condition"],
            zone=zone,
            posture=posture,
            apply_weather_adjustment=False,
            weather_adjust_condition=None,
            comfort_zone=self._comfort_zone(),
        )
        self.context["last_lux_multiplier"] = composition.last_lux_multiplier
        self.context["last_weather_class"] = composition.last_weather_class
        self.root.events.record_learner_deltas(
            period=period,
            deltas=composition.learner_deltas,
        )
        await self.root.applicator.apply_state(
            composition.state,
            MODE_TRANSITION_TIME["working"],
        )


class NavigationV1Replay:
    """Closed navigation-v1 object graph; operational runner remains fail-closed."""

    def __init__(self, bundle: IncidentBundleV1) -> None:
        if not isinstance(bundle, IncidentBundleV1):
            raise TypeError("NavigationV1Replay requires a validated IncidentBundleV1")
        self.bundle = bundle
        self.checkpoint = ReplayCheckpointV1.from_models(
            bundle.manifest,
            bundle.initial,
        )
        self.clock = self.checkpoint.create_clock()
        self.scheduler = ReplayScheduler(self.clock)

        self.engine = _known_mapping(bundle.initial.engine, "engine")
        self.context = _known_mapping(bundle.initial.working_context, "working_context")
        self.camera_state = _known_mapping(bundle.initial.camera, "camera")
        self.transit_state = _known_mapping(bundle.initial.transit, "transit")
        self.adapter_state = _known_mapping(bundle.initial.adapter, "adapter")

        self._validate_profile()
        self.schedule = _schedule(self.context["schedule_config"])
        sunset = self.context["sunset_ts"]
        if sunset is not None:
            sunset = _optional_number(sunset, "Working sunset_ts")
        self.sunset_ts = sunset
        self.require_day_period()

        self.fusion = PresenceFusion(clock=self.clock)
        self._restore_fusion(_known_mapping(bundle.initial.fusion, "fusion"))
        self._validate_working_context_alignment()
        self.camera = _CameraView(
            self.camera_state["status"],
            self.camera_state["lux"],
        )
        self.state = self._restore_engine_state(
            _known_mapping(bundle.initial.engine_state, "engine_state")
        )
        self.sink = RecordingLightSink(
            connected=self.adapter_state["connected"],
            available=self.adapter_state["available"],
            result_policy=self.adapter_state["result_policy"],
        )
        self.events = RecordingEventSink()
        self.boundary = LightingTransitionBoundary(self.sink)
        self.authority = _NavigationAuthority(self, self.engine, self.context)

        self.overrides = LightOverrideManager(
            state=self.state,
            hue_getter=lambda: self.sink,
            event_logger_getter=lambda: self.events,
            current_mode_getter=lambda: self.authority.current_mode,
            reapply_mode=self.authority.reapply_mode,
            suppressed_getter=self._suppressed,
            transition_boundary=self.boundary,
            clock=self.clock,
        )

        async def dispatch_per_light(states: dict, transitiontime: int | None):
            return await self.applicator.apply_per_light(states, transitiontime)

        async def dispatch_uniform(state: dict, transitiontime: int | None):
            return await self.applicator.apply_uniform(state, transitiontime)

        self.applicator = LightApplicator(
            state=self.state,
            overrides=self.overrides,
            hue_getter=lambda: self.sink,
            event_logger_getter=lambda: self.events,
            current_mode_getter=lambda: self.authority.current_mode,
            screen_sync_getter=lambda: None,
            external_owners_getter=lambda: [],
            suppressed_getter=self._suppressed,
            dispatch_per_light=dispatch_per_light,
            dispatch_uniform=dispatch_uniform,
            transition_boundary=self.boundary,
        )
        self.transit = TransitLightingService(
            self.authority,
            self.camera,
            self.fusion,
            clock=self.clock,
        )
        self._restore_transit()

        for event in bundle.inputs:
            self._validate_event_identity(event)

        self.input_handles = schedule_recorded_inputs(
            self.scheduler,
            bundle.inputs,
            self._dispatch_input,
            backend_boot_id=self.checkpoint.backend_boot_id,
            backend_session_id=self.checkpoint.backend_session_id,
            clock_domain=self.checkpoint.clock_domain,
        )
        self.pending_handles = self.checkpoint.seed_pending(
            self.scheduler,
            self._resolve_pending,
        )

    @classmethod
    def from_bundle(cls, bundle: IncidentBundleV1) -> "NavigationV1Replay":
        return cls(bundle)

    def _suppressed(self) -> bool:
        return bool(
            self.engine["away_hold"]
            or self.engine["external_off_detected"]
            or not self.engine["enabled"]
        )

    def _validate_profile(self) -> None:
        bool_keys = (
            "manual_override",
            "override_expiry_deferred",
            "away_hold",
            "host_return_hold",
            "external_off_detected",
            "home_awake_confirmed",
            "enabled",
        )
        if any(type(self.engine[key]) is not bool for key in bool_keys):
            raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: engine boolean state")
        for key in (
            "last_process_observation_by_device",
            "last_process_semantic_by_device",
        ):
            if not isinstance(self.engine[key], dict):
                raise UnsupportedNavigationReplay(f"INCOMPLETE_INITIAL_STATE: engine.{key}")
        if self.engine["desktop_sensing_state"] != "unavailable":
            raise UnsupportedNavigationReplay(
                "UNSUPPORTED_PROFILE: desktop sensing must be unavailable"
            )
        if (
            self.engine["last_process_observation_by_device"]
            or self.engine["last_process_semantic_by_device"]
        ):
            raise UnsupportedNavigationReplay(
                "UNSUPPORTED_PROFILE: desktop process evidence is present"
            )
        _stamps(
            self.engine["last_mode_source_report_at"],
            "engine.last_mode_source_report_at",
        )
        _date(self.engine["override_time"], "engine.override_time")
        _date(self.engine["idle_entered_at"], "engine.idle_entered_at")
        timeout = _optional_number(
            self.engine["override_timeout_hours"],
            "engine.override_timeout_hours",
        )
        if timeout is None or timeout <= 0:
            raise UnsupportedNavigationReplay(
                "INCOMPLETE_INITIAL_STATE: engine.override_timeout_hours"
            )

        pref_lights = self.context.get("learner_weather_pref_lights")
        if not isinstance(pref_lights, list) or any(
            not isinstance(light_id, str) or not light_id for light_id in pref_lights
        ):
            raise UnsupportedNavigationReplay(
                "INCOMPLETE_INITIAL_STATE: learner_weather_pref_lights"
            )
        if self.context.get("learner_overlay_result") is not None and not isinstance(
            self.context["learner_overlay_result"], dict
        ):
            raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: learner_overlay_result")
        for key in ("weather_condition", "last_weather_class"):
            if self.context.get(key) is not None and not isinstance(self.context[key], str):
                raise UnsupportedNavigationReplay(
                    f"INCOMPLETE_INITIAL_STATE: working_context.{key}"
                )
        for key in ("mode_brightness_working", "last_lux_multiplier"):
            if _optional_number(self.context.get(key), f"working_context.{key}") is None:
                raise UnsupportedNavigationReplay(
                    f"INCOMPLETE_INITIAL_STATE: working_context.{key}"
                )
        zone_posture = self.context.get("zone_posture")
        if not isinstance(zone_posture, dict) or set(zone_posture) != {
            "zone",
            "posture",
        }:
            raise UnsupportedNavigationReplay(
                "INCOMPLETE_INITIAL_STATE: working_context.zone_posture"
            )
        if any(
            zone_posture[key] is not None and not isinstance(zone_posture[key], str)
            for key in ("zone", "posture")
        ):
            raise UnsupportedNavigationReplay(
                "INCOMPLETE_INITIAL_STATE: working_context.zone_posture"
            )
        if "sunset_ts" not in self.context:
            raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: Working sunset_ts")
        result_policy = self.adapter_state.get("result_policy")
        if not isinstance(result_policy, dict) or "default" not in result_policy:
            raise UnsupportedNavigationReplay(
                "INCOMPLETE_INITIAL_STATE: adapter result_policy requires "
                "an explicit default outcome"
            )

        unsupported = [
            event.kind for event in self.bundle.inputs if event.kind not in _SUPPORTED_INPUT_KINDS
        ]
        if unsupported:
            raise UnsupportedNavigationReplay(
                "UNSUPPORTED_PROFILE: unmapped recorded input kinds "
                + ", ".join(sorted(set(unsupported)))
            )

    def _validate_working_context_alignment(self) -> None:
        captured = self.context["zone_posture"]
        resolved = {
            "zone": self.fusion.latest_zone(),
            "posture": self.fusion.latest_posture(),
        }
        if captured != resolved:
            raise UnsupportedNavigationReplay(
                "INCOMPLETE_INITIAL_STATE: working_context.zone_posture "
                "does not match restored PresenceFusion"
            )

    def require_day_period(self) -> str:
        period = get_time_period(
            self.schedule,
            self.clock.utc_now().astimezone(TZ),
            sunset_ts=self.sunset_ts,
        )
        if period != "day":
            raise UnsupportedNavigationReplay(
                f"UNSUPPORTED_PROFILE: navigation-v1 period became {period}"
            )
        return period

    def _restore_fusion(self, value: dict[str, Any]) -> None:
        readings = value["readings"]
        order = value["reading_order"]
        if not isinstance(readings, dict) or not isinstance(order, list):
            raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: fusion readings")
        restored: dict[str, PresenceReading] = {}
        for source in order:
            if source not in readings:
                raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: fusion reading order")
            reading = _reading(readings[source], label=f"fusion.readings.{source}")
            if reading.source != source:
                raise UnsupportedNavigationReplay(
                    "INCOMPLETE_INITIAL_STATE: fusion source identity"
                )
            restored[source] = reading
        if set(restored) != set(readings):
            raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: fusion reading order")
        self.fusion._readings = restored
        for attr, key in (
            ("_last_at_desk_at", "last_at_desk_at"),
            ("_last_global_absence_observed_at", "last_global_absence_observed_at"),
            ("_last_strong_reacquisition_at", "last_strong_reacquisition_at"),
        ):
            setattr(self.fusion, attr, _date(value[key], f"fusion.{key}"))
        self.fusion._last_at_desk_source = value["last_at_desk_source"]
        self.fusion._last_strong_reacquisition_source = value["last_strong_reacquisition_source"]

    def _restore_engine_state(self, value: dict[str, Any]) -> EngineState:
        manual = _stamps(
            value["manual_light_overrides"],
            "engine_state.manual_light_overrides",
        )
        transit = _stamps(
            value["transit_light_overrides"],
            "engine_state.transit_light_overrides",
        )
        manual_targets = _light_state_map(
            value["manual_light_targets"],
            "engine_state.manual_light_targets",
        )
        transit_targets = _light_state_map(
            value["transit_light_targets"],
            "engine_state.transit_light_targets",
        )
        last_applied = _light_state_map(
            value["last_applied_per_light"],
            "engine_state.last_applied_per_light",
        )
        return EngineState(
            last_applied_per_light=last_applied,
            manual_light_overrides={key: stamp.astimezone(TZ) for key, stamp in manual.items()},
            transit_light_overrides={key: stamp.astimezone(TZ) for key, stamp in transit.items()},
            manual_light_targets=manual_targets,
            transit_light_targets=transit_targets,
        )

    def _restore_transit(self) -> None:
        for key in ("enabled", "active", "presence_armed"):
            if type(self.transit_state[key]) is not bool:
                raise UnsupportedNavigationReplay(f"INCOMPLETE_INITIAL_STATE: transit.{key}")
        streak = self.transit_state["strong_absent_streak"]
        if type(streak) is not int or streak < 0:
            raise UnsupportedNavigationReplay(
                "INCOMPLETE_INITIAL_STATE: transit.strong_absent_streak"
            )
        last_block = self.transit_state["last_block_reason"]
        if last_block is not None and not isinstance(last_block, str):
            raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: transit.last_block_reason")
        mapping = {
            "_enabled": "enabled",
            "_active": "active",
            "_presence_armed": "presence_armed",
            "_strong_absent_streak": "strong_absent_streak",
            "_last_block_reason": "last_block_reason",
        }
        for attr, key in mapping.items():
            setattr(self.transit, attr, copy.deepcopy(self.transit_state[key]))
        for attr, key in (
            ("_camera_absent_since", "camera_absent_since"),
            ("_presence_during_absent_since", "presence_during_absent_since"),
            ("_camera_present_since", "camera_present_since"),
            ("_transit_start", "transit_start"),
            ("_last_deactivated_at", "last_deactivated_at"),
        ):
            stamp = _date(self.transit_state[key], f"transit.{key}")
            setattr(self.transit, attr, stamp.astimezone(TZ) if stamp else None)
        owned = self.transit_state["owned_lights"]
        if not isinstance(owned, list) or any(not isinstance(item, str) for item in owned):
            raise UnsupportedNavigationReplay("INCOMPLETE_INITIAL_STATE: transit.owned_lights")
        self.transit._owned_lights = set(owned)
        self.transit._heartbeat = None

    def _validate_event_identity(self, event: InputEnvelopeV1) -> None:
        if event.received_mono_ns < self.checkpoint.checkpoint_mono_ns:
            raise UnsupportedNavigationReplay(
                f"INCOMPLETE_INPUT: {event.event_id} precedes checkpoint"
            )
        event_clock = self.checkpoint.create_clock()
        try:
            event_clock.advance_to(event.received_mono_ns)
        except ReplayTimeError as exc:
            raise UnsupportedNavigationReplay(str(exc)) from exc
        received = _date(event.received_at_utc, f"{event.event_id}.received_at_utc")
        assert received is not None
        if event_clock.utc_now() != received:
            raise UnsupportedNavigationReplay(
                f"INCOMPLETE_INPUT: {event.event_id} wall/monotonic mismatch"
            )
        normalized = _date(
            event.captured_at_normalized,
            f"{event.event_id}.captured_at_normalized",
        )
        assert normalized is not None

        if event.source_id == "backend":
            if event.source_session_id != self.checkpoint.backend_session_id:
                raise UnsupportedNavigationReplay(
                    f"INCOMPLETE_INPUT: {event.event_id} backend source session"
                )
        else:
            expected = self.bundle.manifest.sessions.source_sessions.get(event.source_id)
            if expected is None or expected != event.source_session_id:
                raise UnsupportedNavigationReplay(
                    f"INCOMPLETE_INPUT: {event.event_id} source session"
                )

        if event.kind == "fusion_ingest":
            if not isinstance(event.payload, KnownValue):
                raise UnsupportedNavigationReplay(
                    f"INCOMPLETE_INPUT: {event.event_id} fusion payload"
                )
            reading = _reading(event.payload.value, label=event.event_id)
            if reading.source != event.source_id or reading.captured_at != normalized:
                raise UnsupportedNavigationReplay(
                    f"INCOMPLETE_INPUT: {event.event_id} fusion envelope identity"
                )
        elif event.kind == "fusion_invalidation":
            if not isinstance(event.payload, KnownValue) or event.payload.value != {
                "source": event.source_id
            }:
                raise UnsupportedNavigationReplay(
                    f"INCOMPLETE_INPUT: {event.event_id} invalidation identity"
                )
        elif event.kind in {"camera_status_change", "camera_lux_change"}:
            if event.source_id != "latitude" or not isinstance(event.payload, KnownValue):
                raise UnsupportedNavigationReplay(
                    f"INCOMPLETE_INPUT: {event.event_id} camera source"
                )
            if event.kind == "camera_status_change":
                _validate_camera_status(event.payload.value, partial=True)
            else:
                _validate_camera_lux(event.payload.value, partial=True)
        else:
            if event.source_id != "backend" or normalized != received:
                raise UnsupportedNavigationReplay(
                    f"INCOMPLETE_INPUT: {event.event_id} backend evaluation identity"
                )

    async def _dispatch_input(self, event: InputEnvelopeV1) -> None:
        self.require_day_period()
        if event.kind == "fusion_ingest":
            assert isinstance(event.payload, KnownValue)
            self.fusion.on_observation(_reading(event.payload.value, label=event.event_id))
            return
        if event.kind == "fusion_invalidation":
            self.fusion.invalidate_source(event.source_id)
            return
        if event.kind == "camera_status_change":
            assert isinstance(event.payload, KnownValue)
            self.camera.update_status(event.payload.value)
            return
        if event.kind == "camera_lux_change":
            assert isinstance(event.payload, KnownValue)
            self.camera.update_lux(event.payload.value)
            return
        await self._evaluate(event.kind)

    def _resolve_pending(self, pending: PendingEvaluationV1):
        async def continuation() -> None:
            self.require_day_period()
            await self._evaluate(pending.kind)

        return continuation

    async def _evaluate(self, kind: str) -> None:
        if kind == "engine_tick":
            await self.authority.evaluate_expiry()
            self.overrides.expire_manual_stamps(
                self.clock.utc_now().astimezone(TZ),
                float(self.engine["override_timeout_hours"]),
            )
            return
        if kind == "transit_tick":
            await self.transit._check()
            return
        if kind == "deadline_tick":
            self.overrides.prune_expired_transit()
            return
        if kind == "restoration_tick":
            await self.authority.reapply_mode(self.authority.current_mode)
            return
        raise UnsupportedNavigationReplay(f"UNSUPPORTED_PROFILE: evaluation kind {kind}")

    async def run_until(self, end_mono_ns: int) -> None:
        await self.scheduler.run_until(end_mono_ns)
