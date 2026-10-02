"""Bounded navigation capture/export contract tests."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.replay.schema import (
    ConfigurationIdentityV1,
    ImplementationIdentityV1,
    InitialStateV1,
    SessionsV1,
    TimeIdentityV1,
)
from backend.replay.validate import (
    BundleErrorCode,
    BundleValidationError,
    load_fixture_bundle,
)
from backend.services.navigation_incident_capture import (
    NavigationCaptureError,
    NavigationCaptureIdentity,
    NavigationIncidentCapture,
    snapshot_navigation_initial_state,
)
from backend.services.automation_constants import ScheduleConfig
from backend.services.engine_state import EngineState
from backend.services.light_override_manager import LightOverrideManager
from backend.services.presence_fusion import PresenceFusion, PresenceReading


def _known(value):
    return {"status": "known", "value": value}
def _unknown(reason: str):
    return {"status": "unknown", "reason": reason}


def _schedule_config() -> dict:
    weekday = {
        "wake_hour": 5,
        "wake_brightness": 40,
        "ramp_start_hour": 6,
        "ramp_duration_minutes": 60,
        "evening_start_hour": 18,
        "winddown_start_hour": 21,
        "late_night_start_hour": 23,
    }
    weekend = {
        **weekday,
        "wake_hour": 8,
        "ramp_start_hour": 8,
        "ramp_duration_minutes": 120,
    }
    return {"weekday": weekday, "weekend": weekend}


def _initial() -> InitialStateV1:
    return InitialStateV1.model_validate(
        {
            "schema_id": "homehub.incident.navigation.initial.v1",
            "schema_version": 1,
            "profile_id": "navigation-v1",
            "profile_version": 1,
            "backend_boot_id": "capture-boot",
            "backend_session_id": "capture-session",
            "checkpoint_utc": "2026-09-22T12:00:00Z",
            "quiescent": True,
            "fusion": _known(
                {
                    "readings": {},
                    "reading_order": [],
                    "last_at_desk_at": None,
                    "last_at_desk_source": None,
                    "last_global_absence_observed_at": None,
                    "last_strong_reacquisition_at": None,
                    "last_strong_reacquisition_source": None,
                }
            ),
            "engine": _known(
                {
                    "current_mode": "working",
                    "house_state": "Home",
                    "activity": "Working",
                    "mode_source": "manual",
                    "mode_source_key": "capture",
                    "last_mode_source_report_at": {},
                    "last_process_observation_by_device": {},
                    "last_process_semantic_by_device": {},
                    "desktop_sensing_state": "unavailable",
                    "manual_override": True,
                    "override_mode": "working",
                    "override_source": "api:capture-test",
                    "override_time": "2026-09-22T11:00:00Z",
                    "override_expiry_deferred": False,
                    "override_timeout_hours": 4,
                    "idle_entered_at": None,
                    "away_hold": False,
                    "host_return_hold": False,
                    "external_off_detected": False,
                    "home_awake_confirmed": True,
                    "enabled": True,
                    "dnd": {
                        "active": False,
                        "active_until": None,
                        "source": None,
                    },
                }
            ),
            "transit": _known(
                {
                    "enabled": True,
                    "active": False,
                    "presence_armed": True,
                    "camera_absent_since": None,
                    "presence_during_absent_since": None,
                    "camera_present_since": None,
                    "strong_absent_streak": 0,
                    "last_block_reason": None,
                    "transit_start": None,
                    "last_deactivated_at": None,
                    "owned_lights": [],
                }
            ),
            "camera": _known(
                {
                    "status": {
                        "enabled": True,
                        "last_detection": "present",
                        "detection_source": "face",
                        "confidence": 0.9,
                        "zone": None,
                        "posture": None,
                        "presence_authority_ready": True,
                    },
                    "lux": {
                        "enabled": True,
                        "paused": False,
                        "ema_lux": 20.0,
                        "last_lux_update": "2026-09-22T11:59:58Z",
                        "baseline_lux": 30.0,
                    },
                }
            ),
            "engine_state": _known(
                {
                    "manual_light_overrides": {},
                    "manual_light_targets": {},
                    "transit_light_overrides": {},
                    "transit_light_targets": {},
                    "last_applied_per_light": {},
                }
            ),
            "working_context": _known(
                {
                    "schedule_config": _schedule_config(),
                    "sunset_ts": None,
                    "current_game": None,
                    "mode_brightness_working": 1.0,
                    "learner_overlay_result": {},
                    "weather_condition": "clear",
                    "learner_weather_pref_lights": [],
                    "last_lux_multiplier": 1.0,
                    "last_weather_class": "clear",
                    "zone_posture": {"zone": None, "posture": None},
                }
            ),
            "ownership": _known(
                {
                    "scene_override_working_day": None,
                    "active_scene_override_key": None,
                    "effect_desired": None,
                    "effect_active": False,
                    "external_light_owners": {},
                    "screensync_owned_light_ids": [],
                }
            ),
            "adapter": _known(
                {
                    "connected": True,
                    "available": True,
                    "result_policy": {"default": True},
                }
            ),
            "transition_boundary": _known(
                {
                    "owner": None,
                    "in_flight": False,
                    "pending_adapter_completions": [],
                }
            ),
            "pending_evaluations": _known([]),
        }
    )


def _identity() -> NavigationCaptureIdentity:
    return NavigationCaptureIdentity(
        implementation=ImplementationIdentityV1(
            backend_commit="8b5b9d4",
            backend_build="capture-test",
            backend_dirty=False,
            python_version="3.13-test",
            dependency_identity="capture-test-lock",
            tzdata_identity="capture-test-tzdata",
            source_agent_build=_unknown("not consumed"),
        ),
        configuration=ConfigurationIdentityV1(
            consumed_values={"profile": "navigation-v1"},
            value_sources={"profile": "capture_test"},
            policy_digest="a" * 64,
        ),
        sessions=SessionsV1(
            backend_boot_id="capture-boot",
            backend_session_id="capture-session",
            source_sessions={
                "latitude": "latitude-session",
                "desktop": "desktop-session",
            },
            device_ids={
                "latitude": "capture-latitude",
                "desktop": "capture-desktop",
            },
        ),
        time=TimeIdentityV1(
            backend_monotonic_origin_ns=0,
            wall_time_anchor_utc="2026-09-22T12:00:00Z",
            clock_domain="backend-boot:capture-boot",
            adjustments=[],
        ),
    )


class _Clock:
    def __init__(self) -> None:
        self.mono_ns = 0

    def utc_now(self) -> datetime:
        return datetime.fromtimestamp(
            1_790_078_400 + self.mono_ns / 1_000_000_000,
            tz=timezone.utc,
        )

    def monotonic_ns(self) -> int:
        return self.mono_ns

    def set_seconds(self, seconds: float) -> None:
        self.mono_ns = int(seconds * 1_000_000_000)


class _Camera:
    ema_lux = 20.0
    baseline_lux = 30.0
    last_lux_update = datetime(2026, 9, 22, 11, 59, 58, tzinfo=timezone.utc)

    def get_status(self) -> dict:
        return _camera_status()


class _BoundaryLock:
    def __init__(self, locked: bool = False) -> None:
        self.value = locked

    def locked(self) -> bool:
        return self.value


class _Boundary:
    def __init__(self, locked: bool = False) -> None:
        self._lock = _BoundaryLock(locked)
        self.held_by_current_task = False


class _TransitRuntime:
    def __init__(self) -> None:
        self._enabled = True
        self._active = False
        self._presence_armed = True
        self._camera_absent_since = None
        self._presence_during_absent_since = None
        self._camera_present_since = None
        self._strong_absent_streak = 0
        self._last_block_reason = None
        self._transit_start = None
        self._last_deactivated_at = None
        self._owned_lights: set[str] = set()
        self.capture = None

    def set_navigation_incident_capture(self, capture) -> None:
        self.capture = capture


def _automation_runtime() -> SimpleNamespace:
    runtime = SimpleNamespace()
    runtime.current_mode = "working"
    runtime.house_state = "home"
    runtime.activity = "working"
    runtime.current_weather_class = "clear"
    runtime.current_game = None
    runtime._mode_source = "manual"
    runtime._mode_source_key = "capture-test"
    runtime._last_mode_source_report_at = {}
    runtime._last_process_observation_by_device = {}
    runtime._last_process_semantic_by_device = {}
    runtime._manual_override = True
    runtime._override_mode = "working"
    runtime._override_source = "api:capture-test"
    runtime._override_time = datetime(2026, 9, 22, 11, tzinfo=timezone.utc)
    runtime._override_expiry_deferred = False
    runtime._override_timeout_hours = 4
    runtime._idle_entered_at = None
    runtime._away_hold = False
    runtime._host_return_hold = False
    runtime._external_off_detected = False
    runtime._home_awake_confirmed = True
    runtime._enabled = True
    runtime._dnd = SimpleNamespace(_expiry=None)
    runtime.is_dnd_active = lambda: False
    runtime._state = SimpleNamespace(
        manual_light_overrides={},
        manual_light_targets={},
        transit_light_overrides={},
        transit_light_targets={},
        last_applied_per_light={},
    )
    runtime._scene_overrides = {}
    runtime._active_scene_override_key = None
    runtime._get_desired_effect = lambda _mode, _period: None
    runtime._effect_manager = SimpleNamespace(active_name=None)
    runtime._active_external_light_owners = lambda: []
    runtime._screen_sync = None
    runtime._weather_service = None
    runtime._lighting_learner = None
    runtime._schedule_config = ScheduleConfig()
    runtime._mode_brightness = {"working": 1.0}
    runtime._last_lux_multiplier = 1.0
    runtime._last_weather_class = "clear"
    runtime._get_time_period = lambda _now=None: "day"
    runtime._transition_boundary = _Boundary()
    runtime._hue = SimpleNamespace(connected=True)
    return runtime


def _authority() -> dict:
    return {
        "current_mode": "working",
        "house_state": "Home",
        "activity": "Working",
        "manual_override": True,
        "away_hold": False,
        "host_return_hold": False,
        "external_off_detected": False,
        "enabled": True,
        "dnd": {"active": False},
    }


def _camera_status(**changes) -> dict:
    value = {
        "enabled": True,
        "paused": False,
        "last_detection": "present",
        "detection_source": "face",
        "confidence": 0.9,
        "zone": None,
        "posture": None,
        "presence_authority_ready": True,
        "ema_lux": 20.0,
        "baseline_lux": 30.0,
    }
    value.update(changes)
    return value


def _capture(clock: _Clock, **kwargs) -> NavigationIncidentCapture:
    return NavigationIncidentCapture(
        bundle_id="bounded-capture-test",
        initial=_initial(),
        identity=_identity(),
        clock=clock,
        **kwargs,
    )


def test_complete_capture_exports_valid_navigation_bundle(tmp_path) -> None:
    clock = _Clock()
    capture = _capture(clock)
    clock.set_seconds(1)
    reading = PresenceReading(
        source="latitude",
        captured_at=datetime(2026, 9, 22, 12, 0, 1, tzinfo=timezone.utc),
        face_present=False,
        face_confidence=0.0,
        detection_source="yolo",
        zone=None,
        posture=None,
    )
    assert capture.record_fusion_ingest(reading) == "capture-000001"

    clock.set_seconds(2)
    tick_id = capture.record_transit_evaluation(
        camera_status=_camera_status(),
        camera=_Camera(),
        authority=_authority(),
    )
    assert tick_id == "capture-000002"

    clock.set_seconds(2.1)
    capture.record_navigation_outcome(
        phase="transit_override",
        requested_states={"1": {"on": True, "bri": 60, "ct": 447}},
        acknowledged_light_ids={"1"},
        owned_light_ids={"1"},
        cache={"1": {"on": True, "bri": 60, "ct": 447}},
        owner="transit",
    )
    root = capture.export(tmp_path / "capture")
    bundle = load_fixture_bundle(root)

    assert bundle.manifest.capture_provenance["kind"] == "bounded_navigation_capture"
    assert bundle.manifest.capture_provenance["historical_claim"] is False
    assert [item.event_id for item in bundle.inputs] == [
        "capture-000001",
        "capture-000002",
    ]
    assert bundle.expected.assertions[0].evidence_refs == ["capture-000002"]
    assert bundle.initial.adapter.value["result_policy"] == {
        "by_request": {"1": True}
    }
    assert set(path.name for path in root.iterdir()) == {
        "manifest.json",
        "initial.json",
        "inputs.jsonl",
        "expected.json",
    }


def test_exact_duration_bound_is_dropped_and_exported_incomplete(tmp_path) -> None:
    clock = _Clock()
    capture = _capture(clock, max_duration_seconds=2)
    clock.set_seconds(2)
    assert (
        capture.record_transit_evaluation(
            camera_status=_camera_status(),
            camera=_Camera(),
            authority=_authority(),
        )
        is None
    )
    assert capture.dropped_records == 1
    assert capture.complete is False

    root = capture.export(tmp_path / "capture")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["completeness_status"] == "incomplete"
    assert manifest["gaps"][0]["completeness_consequence"] == "incomplete"
    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(root)
    assert error.value.code is BundleErrorCode.INCOMPLETE_BUNDLE
def test_byte_overflow_never_silently_overwrites(tmp_path) -> None:
    clock = _Clock()
    capture = _capture(clock)
    capture.max_bytes = capture._bytes_used + 1
    clock.set_seconds(1)
    reading = PresenceReading(
        source="latitude",
        captured_at=datetime(2026, 9, 22, 12, 0, 1, tzinfo=timezone.utc),
        face_present=False,
    )
    assert capture.record_fusion_ingest(reading) is None
    assert capture.record_count == 0
    assert capture.dropped_records == 1
    root = capture.export(tmp_path / "capture")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["capture_provenance"]["dropped_records"] == 1
    assert manifest["completeness_status"] == "incomplete"


def test_camera_capture_is_allowlisted_and_drops_raw_media(tmp_path) -> None:
    clock = _Clock()
    capture = _capture(clock)
    clock.set_seconds(1)
    capture.record_transit_evaluation(
        camera_status=_camera_status(
            zone="couch",
            frame_base64="must-not-export",
            window_title="must-not-export",
        ),
        camera=_Camera(),
        authority=_authority(),
    )
    root = capture.export(tmp_path / "capture")
    raw = (root / "inputs.jsonl").read_text(encoding="utf-8")
    assert "must-not-export" not in raw
    assert "frame_base64" not in raw
    assert "window_title" not in raw
    bundle = load_fixture_bundle(root)
    status_event = next(
        item for item in bundle.inputs if item.kind == "camera_status_change"
    )
    assert status_event.payload.value["zone"] == "couch"


def test_non_quiescent_checkpoint_fails_closed() -> None:
    initial = _initial().model_dump(mode="json")
    initial["transition_boundary"]["value"]["in_flight"] = True
    with pytest.raises(NavigationCaptureError, match="write in flight"):
        NavigationIncidentCapture(
            bundle_id="unsafe-cut",
            initial=initial,
            identity=_identity(),
            clock=_Clock(),
        )


def test_presence_capture_failure_cannot_change_fusion_behavior() -> None:
    class _FailingCapture:
        def record_fusion_ingest(self, _reading) -> None:
            raise RuntimeError("capture failed")

    fusion = PresenceFusion(incident_capture=_FailingCapture())
    reading = PresenceReading(
        source="desktop",
        captured_at=datetime.now(timezone.utc),
        face_present=True,
        face_confidence=0.99,
        detection_source="face",
        zone="desk",
    )
    fusion.on_observation(reading)
    assert fusion._readings["desktop"] is reading


def test_payload_hashes_match_exported_members(tmp_path) -> None:
    clock = _Clock()
    capture = _capture(clock)
    clock.set_seconds(1)
    capture.record_transit_evaluation(
        camera_status=_camera_status(),
        camera=_Camera(),
        authority=_authority(),
    )
    root = capture.export(tmp_path / "capture")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["member_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected


def test_runtime_snapshot_builds_coherent_navigation_checkpoint() -> None:
    initial = snapshot_navigation_initial_state(
        identity=_identity(),
        automation=_automation_runtime(),
        transit=_TransitRuntime(),
        presence=PresenceFusion(),
        camera=_Camera(),
        clock=_Clock(),
    )
    assert initial.checkpoint_utc == "2026-09-22T12:00:00Z"
    assert initial.quiescent is True
    assert initial.engine.value["house_state"] == "Home"
    assert initial.engine.value["activity"] == "Working"
    assert initial.adapter.value["result_policy"] == {}
    assert initial.transition_boundary.value["in_flight"] is False


def test_runtime_snapshot_rejects_in_flight_transition() -> None:
    automation = _automation_runtime()
    automation._transition_boundary = _Boundary(locked=True)
    with pytest.raises(NavigationCaptureError, match="write is in flight"):
        snapshot_navigation_initial_state(
            identity=_identity(),
            automation=automation,
            transit=_TransitRuntime(),
            presence=PresenceFusion(),
            camera=_Camera(),
            clock=_Clock(),
        )


def test_arm_runtime_attaches_and_stop_detaches() -> None:
    transit = _TransitRuntime()
    capture = NavigationIncidentCapture.arm_runtime(
        bundle_id="runtime-arm-test",
        identity=_identity(),
        automation=_automation_runtime(),
        transit=transit,
        presence=PresenceFusion(),
        camera=_Camera(),
        clock=_Clock(),
    )
    assert transit.capture is capture
    capture.stop()
    assert transit.capture is None


def test_runtime_snapshot_rejects_consumer_view_race() -> None:
    class _RacingCamera(_Camera):
        def __init__(self) -> None:
            self.calls = 0

        def get_status(self) -> dict:
            self.calls += 1
            return _camera_status(zone=None if self.calls == 1 else "couch")

    with pytest.raises(
        NavigationCaptureError,
        match="changed during checkpoint cut",
    ):
        snapshot_navigation_initial_state(
            identity=_identity(),
            automation=_automation_runtime(),
            transit=_TransitRuntime(),
            presence=PresenceFusion(),
            camera=_RacingCamera(),
            clock=_Clock(),
        )


@pytest.mark.asyncio
async def test_override_manager_capture_observes_exact_existing_writes() -> None:
    class Hue:
        connected = True

        def __init__(self) -> None:
            self.calls = []

        async def set_light(self, light_id, payload):
            self.calls.append((light_id, payload))
            return light_id == "1"

    class CaptureSpy:
        def __init__(self) -> None:
            self.outcomes = []

        def record_navigation_outcome(self, **kwargs) -> None:
            self.outcomes.append(kwargs)

    async def reapply_mode(_mode: str) -> None:
        return None

    hue = Hue()
    state = EngineState()
    manager = LightOverrideManager(
        state=state,
        hue_getter=lambda: hue,
        event_logger_getter=lambda: None,
        current_mode_getter=lambda: "working",
        reapply_mode=reapply_mode,
        transition_boundary=None,
        clock=_Clock(),
    )
    capture = CaptureSpy()
    manager.set_navigation_incident_capture(capture)
    states = {
        "1": {"on": True, "bri": 60, "ct": 447},
        "3": {"on": True, "bri": 60, "ct": 447},
    }

    await manager.apply_transit_override(states, transition_time=20)

    assert [light_id for light_id, _ in hue.calls] == ["1", "3"]
    assert len(capture.outcomes) == 1
    outcome = capture.outcomes[0]
    assert list(outcome["requested_states"]) == ["1", "3"]
    assert outcome["acknowledged_light_ids"] == ["1"]
    assert outcome["failed_light_ids"] == ["3"]
    assert set(state.last_applied_per_light) == {"1"}


def test_configuration_identity_rejects_unallowlisted_values() -> None:
    base = _identity()
    bad_configuration = ConfigurationIdentityV1(
        consumed_values={
            "profile": "navigation-v1",
            "unrestricted_setting": "must-not-export",
        },
        value_sources={
            "profile": "capture_test",
            "unrestricted_setting": "capture_test",
        },
        policy_digest="a" * 64,
    )
    identity = NavigationCaptureIdentity(
        implementation=base.implementation,
        configuration=bad_configuration,
        sessions=base.sessions,
        time=base.time,
    )
    with pytest.raises(NavigationCaptureError, match="allowlist"):
        NavigationIncidentCapture(
            bundle_id="bad-config",
            initial=_initial(),
            identity=identity,
            clock=_Clock(),
        )


def test_runtime_snapshot_reads_external_owner_state_without_callbacks() -> None:
    class _InactiveOwner:
        owner_name = "inactive-test-owner"

        def __init__(self) -> None:
            self._owned: set[str] = set()
            self._owned_targets: dict[str, dict] = {}

        def owned_light_targets(self):
            raise AssertionError("snapshot must not call owner methods")

    automation = _automation_runtime()
    automation._external_light_owners = [_InactiveOwner()]
    initial = snapshot_navigation_initial_state(
        identity=_identity(),
        automation=automation,
        transit=_TransitRuntime(),
        presence=PresenceFusion(),
        camera=_Camera(),
        clock=_Clock(),
    )
    assert initial.ownership.value["external_light_owners"] == []


def test_output_before_transit_tick_correlates_to_backend_evaluation(tmp_path) -> None:
    clock = _Clock()
    capture = _capture(clock)
    clock.set_seconds(1)
    assert capture.record_backend_evaluation("restoration_tick") == "capture-000001"
    capture.record_navigation_outcome(
        phase="applicator_per_light",
        requested_states={},
        acknowledged_light_ids=set(),
        cache={},
        owner="working",
    )
    root = capture.export(tmp_path / "capture")
    bundle = load_fixture_bundle(root)
    assert bundle.expected.assertions[0].evidence_refs == ["capture-000001"]
