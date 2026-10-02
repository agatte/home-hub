"""Bounded, opt-in recorder/exporter for navigation-v1 replay evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.replay.schema import (
    ConfigurationIdentityV1,
    ExpectedAssertionV1,
    ExpectedV1,
    ImplementationIdentityV1,
    InitialStateV1,
    InputEnvelopeV1,
    KnownValue,
    ManifestV1,
    NotConsumedValue,
    PROFILE_ID,
    PROFILE_VERSION,
    SCHEMA_ID,
    SCHEMA_VERSION,
    SessionsV1,
    TimeIdentityV1,
    UnknownValue,
)
from backend.replay.validate import load_fixture_bundle
from backend.services.automation_constants import SCREEN_SYNC_FRESH_SECONDS
from backend.services.decision_clock import DecisionClock, SystemDecisionClock


DEFAULT_MAX_DURATION_SECONDS = 15 * 60
DEFAULT_MAX_BYTES = 16 * 1024 * 1024

_PRESENCE_FIELDS = (
    "source",
    "captured_at",
    "face_present",
    "face_confidence",
    "detection_source",
    "zone",
    "posture",
    "posture_confidence",
    "pose_visible_landmarks",
)
_CAMERA_STATUS_FIELDS = (
    "enabled",
    "last_detection",
    "detection_source",
    "confidence",
    "zone",
    "posture",
    "presence_authority_ready",
)
_CAMERA_LUX_FIELDS = (
    "enabled",
    "paused",
    "ema_lux",
    "last_lux_update",
    "baseline_lux",
)
_LIGHT_STATE_FIELDS = frozenset({"on", "bri", "hue", "sat", "ct", "transitiontime"})
_ALLOWED_CONFIGURATION_KEYS = frozenset({"profile"})
_FORBIDDEN_KEYS = frozenset(
    {
        "raw_image",
        "image_bytes",
        "image_base64",
        "raw_audio",
        "audio_bytes",
        "audio_base64",
        "screen_capture",
        "screenshot",
        "screen_frame",
        "frame_bytes",
        "frame_base64",
        "command_line",
        "window_title",
        "media_url",
        "password",
        "credential",
        "token",
        "secret",
    }
)
@dataclass(frozen=True)
class NavigationCaptureIdentity:
    implementation: ImplementationIdentityV1
    configuration: ConfigurationIdentityV1
    sessions: SessionsV1
    time: TimeIdentityV1


class NavigationCaptureError(ValueError):
    """Capture cannot satisfy the navigation-v1 contract."""


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise NavigationCaptureError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise NavigationCaptureError("capture timestamps must be UTC")
    return parsed


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso_utc(value)
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    return value
def _reject_private_payload(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in _FORBIDDEN_KEYS:
                raise NavigationCaptureError(f"forbidden capture field at {path}.{key}")
            _reject_private_payload(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_private_payload(child, f"{path}[{index}]")


def _known(value: Any) -> KnownValue:
    return KnownValue(status="known", value=_jsonable(value))


def _unknown(reason: str) -> UnknownValue:
    return UnknownValue(status="unknown", reason=reason)


def _not_consumed(reason: str) -> NotConsumedValue:
    return NotConsumedValue(status="not_consumed", reason=reason)


class NavigationIncidentCapture:
    """Record one bounded, single-boot navigation evidence window.

    The recorder is passive. Callers provide an already coherent InitialStateV1
    and identity facts, then selected participant hooks append normalized
    evidence. Export writes only the four navigation-v1 bundle members.
    """

    def __init__(
        self,
        *,
        bundle_id: str,
        initial: InitialStateV1 | dict[str, Any],
        identity: NavigationCaptureIdentity,
        clock: DecisionClock | None = None,
        max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        if not bundle_id:
            raise NavigationCaptureError("bundle_id is required")
        if max_duration_seconds <= 0 or max_bytes <= 0:
            raise NavigationCaptureError("capture bounds must be positive")
        self.bundle_id = bundle_id
        self.initial = (
            initial
            if isinstance(initial, InitialStateV1)
            else InitialStateV1.model_validate(initial)
        )
        self.identity = identity
        self._validate_identity()
        self.clock = clock or SystemDecisionClock()
        self.max_duration_seconds = int(max_duration_seconds)
        self.max_bytes = int(max_bytes)
        self._lock = threading.RLock()
        self._inputs: list[InputEnvelopeV1] = []
        self._assertions: list[ExpectedAssertionV1] = []
        self._gaps: list[dict[str, Any]] = []
        self._dispatch_sequence = 0
        self._output_sequence = 0
        self._last_evaluation_event_id: str | None = None
        self._adapter_outcomes: list[bool] = []
        self._dropped_records = 0
        self._stopped = False
        self._runtime_detacher = None

        self._checkpoint_utc = _parse_utc(self.initial.checkpoint_utc)
        self._checkpoint_mono_ns = self._mono_for_utc(self._checkpoint_utc)
        self._last_mono_ns = self._checkpoint_mono_ns
        self._validate_checkpoint()

        initial_payload = self.initial.model_dump(mode="json")
        initial_size = len(_canonical_bytes(initial_payload))
        if initial_size >= self.max_bytes:
            raise NavigationCaptureError("initial checkpoint exceeds capture byte bound")
        self._bytes_used = initial_size

        camera = self._known_mapping(self.initial.camera, "camera")
        self._last_camera_status = copy.deepcopy(camera["status"])
        self._last_camera_lux = copy.deepcopy(camera["lux"])
        engine = self._known_mapping(self.initial.engine, "engine")
        self._initial_authority = self._authority_subset(engine)

    @classmethod
    def arm_runtime(
        cls,
        *,
        bundle_id: str,
        identity: NavigationCaptureIdentity,
        automation: Any,
        transit: Any,
        presence: Any,
        camera: Any,
        clock: DecisionClock | None = None,
        max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> "NavigationIncidentCapture":
        """Take a coherent in-memory cut and attach passive runtime hooks."""
        runtime_clock = clock or SystemDecisionClock()
        initial = snapshot_navigation_initial_state(
            identity=identity,
            automation=automation,
            transit=transit,
            presence=presence,
            camera=camera,
            clock=runtime_clock,
        )
        capture = cls(
            bundle_id=bundle_id,
            initial=initial,
            identity=identity,
            clock=runtime_clock,
            max_duration_seconds=max_duration_seconds,
            max_bytes=max_bytes,
        )
        setter = getattr(transit, "set_navigation_incident_capture", None)
        if not callable(setter):
            raise NavigationCaptureError(
                "TransitLightingService capture setter is unavailable"
            )
        try:
            setter(capture)
            capture._runtime_detacher = lambda: setter(None)
            checkpoint_utc = _parse_utc(initial.checkpoint_utc)
            after_attach = _runtime_snapshot(
                automation=automation,
                transit=transit,
                presence=presence,
                camera=camera,
                checkpoint_utc=checkpoint_utc,
            )
            expected = {
                name: cls._known_value(getattr(initial, name), name)
                for name in (
                    "fusion",
                    "engine",
                    "transit",
                    "camera",
                    "engine_state",
                    "working_context",
                    "ownership",
                    "adapter",
                    "transition_boundary",
                    "pending_evaluations",
                )
            }
            if _canonical_bytes(after_attach) != _canonical_bytes(expected):
                raise NavigationCaptureError(
                    "runtime participant state changed before capture hooks were armed"
                )
        except Exception:
            try:
                setter(None)
            finally:
                capture._runtime_detacher = None
            raise
        return capture

    @staticmethod
    def _known_value(value: Any, label: str) -> Any:
        if not isinstance(value, KnownValue):
            raise NavigationCaptureError(f"{label} must be known at capture start")
        return value.value

    @classmethod
    def _known_mapping(cls, value: Any, label: str) -> dict[str, Any]:
        known = cls._known_value(value, label)
        if not isinstance(known, dict):
            raise NavigationCaptureError(f"{label} must be a known mapping")
        return known

    def _validate_identity(self) -> None:
        configuration = self.identity.configuration
        consumed_keys = set(configuration.consumed_values)
        source_keys = set(configuration.value_sources)
        if consumed_keys != source_keys:
            raise NavigationCaptureError(
                "configuration consumed_values/value_sources keys must match"
            )
        if not consumed_keys <= _ALLOWED_CONFIGURATION_KEYS:
            raise NavigationCaptureError(
                "configuration contains fields outside the navigation-v1 allowlist"
            )
        if configuration.consumed_values.get("profile") != PROFILE_ID:
            raise NavigationCaptureError(
                "configuration profile must be navigation-v1"
            )
        _reject_private_payload(configuration.consumed_values)

    def _validate_checkpoint(self) -> None:
        if not self.initial.quiescent:
            raise NavigationCaptureError("capture requires a quiescent checkpoint")
        boundary = self._known_mapping(
            self.initial.transition_boundary,
            "transition_boundary",
        )
        if boundary.get("in_flight") is not False:
            raise NavigationCaptureError("capture cannot start with a write in flight")
        if boundary.get("pending_adapter_completions") not in ([], {}):
            raise NavigationCaptureError(
                "capture cannot start with pending adapter completions"
            )
        if self.initial.backend_boot_id != self.identity.sessions.backend_boot_id:
            raise NavigationCaptureError("checkpoint boot identity mismatch")
        if self.initial.backend_session_id != self.identity.sessions.backend_session_id:
            raise NavigationCaptureError("checkpoint session identity mismatch")

    def _mono_for_utc(self, value: datetime) -> int:
        anchor = _parse_utc(self.identity.time.wall_time_anchor_utc)
        delta = value - anchor
        delta_ns = (
            (delta.days * 86_400 + delta.seconds) * 1_000_000_000
            + delta.microseconds * 1_000
        )
        return self.identity.time.backend_monotonic_origin_ns + delta_ns

    def _utc_for_mono(self, mono_ns: int) -> datetime:
        anchor = _parse_utc(self.identity.time.wall_time_anchor_utc)
        delta_ns = mono_ns - self.identity.time.backend_monotonic_origin_ns
        return anchor + timedelta(microseconds=delta_ns // 1_000)

    def _mark_gap(
        self,
        *,
        field_or_event_id: str,
        reason: str,
        affected_decisions: list[str] | None = None,
    ) -> None:
        key = (field_or_event_id, reason)
        if any(
            (gap["field_or_event_id"], gap["reason"]) == key
            for gap in self._gaps
        ):
            return
        self._gaps.append(
            {
                "field_or_event_id": field_or_event_id,
                "missing_interval": _unknown("bounded capture gap").model_dump(mode="json"),
                "reason": reason,
                "affected_decisions": affected_decisions or ["navigation-v1"],
                "completeness_consequence": "incomplete",
            }
        )
    def _reserve(self, payload: Any, *, label: str) -> bool:
        encoded_size = len(_canonical_bytes(payload)) + 1
        if self._bytes_used + encoded_size > self.max_bytes:
            self._dropped_records += 1
            self._stopped = True
            self._mark_gap(
                field_or_event_id="capture_byte_bound",
                reason=(
                    "capture byte bound exceeded; recorder stopped before "
                    f"{label}"
                ),
            )
            return False
        self._bytes_used += encoded_size
        return True

    def _next_timing(self, label: str) -> tuple[int, datetime] | None:
        if self._stopped:
            self._dropped_records += 1
            self._mark_gap(
                field_or_event_id=label,
                reason="record arrived after capture stop",
            )
            return None
        mono_ns = int(self.clock.monotonic_ns())
        if mono_ns < self._last_mono_ns:
            self._dropped_records += 1
            self._mark_gap(
                field_or_event_id=label,
                reason="monotonic clock moved backwards",
            )
            return None
        if mono_ns - self._checkpoint_mono_ns >= self.max_duration_seconds * 1_000_000_000:
            self._dropped_records += 1
            self._mark_gap(
                field_or_event_id=label,
                reason="capture duration bound exceeded; record dropped",
            )
            self._stopped = True
            return None
        self._last_mono_ns = mono_ns
        return mono_ns, self._utc_for_mono(mono_ns)

    def _source_session(self, source_id: str) -> str | None:
        if source_id == "backend":
            return self.identity.sessions.backend_session_id
        session = self.identity.sessions.source_sessions.get(source_id)
        if session is None:
            self._mark_gap(
                field_or_event_id=f"source_session:{source_id}",
                reason="source session identity was not captured",
            )
        return session

    def _append_input(
        self,
        *,
        kind: str,
        source_id: str,
        payload: Any,
        captured_at_normalized: datetime | None = None,
        captured_at_original: Any | None = None,
        source_sequence: Any | None = None,
        normalization_provenance: Any | None = None,
        evidence_refs: list[str] | None = None,
    ) -> str | None:
        with self._lock:
            session = self._source_session(source_id)
            timing = self._next_timing(kind)
            if session is None or timing is None:
                return None
            mono_ns, received_utc = timing
            self._dispatch_sequence += 1
            event_id = f"capture-{self._dispatch_sequence:06d}"
            normalized = captured_at_normalized or received_utc
            envelope = InputEnvelopeV1(
                schema_id="homehub.incident.navigation.input.v1",
                schema_version=1,
                event_id=event_id,
                kind=kind,
                source_id=source_id,
                source_session_id=session,
                source_sequence=(
                    _not_consumed("producer sequence not exposed at selected boundary")
                    if source_sequence is None
                    else _known(source_sequence)
                ),
                captured_at_original=(
                    _not_consumed("backend-local evaluation has no producer capture time")
                    if captured_at_original is None
                    else _known(captured_at_original)
                ),
                captured_at_normalized=_iso_utc(normalized),
                received_at_utc=_iso_utc(received_utc),
                received_mono_ns=mono_ns,
                backend_dispatch_sequence=self._dispatch_sequence,
                backend_boot_id=self.identity.sessions.backend_boot_id,
                backend_session_id=self.identity.sessions.backend_session_id,
                clock_domain=self.identity.time.clock_domain,
                normalization_provenance=(
                    _not_consumed("no ingress normalization at this boundary")
                    if normalization_provenance is None
                    else _known(normalization_provenance)
                ),
                payload=_known(payload),
                evidence_refs=evidence_refs or [],
            )
            raw = envelope.model_dump(mode="json")
            _reject_private_payload(raw)
            if not self._reserve(raw, label=event_id):
                return None
            self._inputs.append(envelope)
            return event_id

    @staticmethod
    def _presence_payload(reading: Any) -> dict[str, Any]:
        payload = {field: getattr(reading, field, None) for field in _PRESENCE_FIELDS}
        if payload["source"] is None or payload["captured_at"] is None:
            raise NavigationCaptureError("invalid PresenceReading at capture boundary")
        return _jsonable(payload)

    def record_fusion_ingest(self, reading: Any) -> str | None:
        payload = self._presence_payload(reading)
        captured_at = getattr(reading, "captured_at")
        return self._append_input(
            kind="fusion_ingest",
            source_id=str(payload["source"]),
            payload=payload,
            captured_at_normalized=captured_at,
            captured_at_original=captured_at,
            normalization_provenance={"boundary": "PresenceFusion.on_observation"},
        )
    def record_fusion_invalidation(self, source: str) -> str | None:
        return self._append_input(
            kind="fusion_invalidation",
            source_id=source,
            payload={"source": source},
            captured_at_normalized=self._utc_for_mono(int(self.clock.monotonic_ns())),
            normalization_provenance={"boundary": "PresenceFusion.invalidate_source"},
        )

    def record_backend_evaluation(self, kind: str) -> str | None:
        """Record a replay-mapped backend evaluation opportunity."""
        if kind not in {"engine_tick", "deadline_tick", "restoration_tick"}:
            raise NavigationCaptureError(f"unsupported backend evaluation kind: {kind}")
        event_id = self._append_input(
            kind=kind,
            source_id="backend",
            payload={},
        )
        self._last_evaluation_event_id = event_id
        return event_id

    @staticmethod
    def _camera_status_view(status: dict[str, Any]) -> dict[str, Any]:
        return _jsonable({field: status.get(field) for field in _CAMERA_STATUS_FIELDS})

    @staticmethod
    def _camera_lux_view(status: dict[str, Any], camera: Any) -> dict[str, Any]:
        return _jsonable(
            {
                "enabled": status.get("enabled"),
                "paused": status.get("paused"),
                "ema_lux": getattr(camera, "ema_lux", status.get("ema_lux")),
                "last_lux_update": getattr(
                    camera,
                    "last_lux_update",
                    status.get("last_lux_update"),
                ),
                "baseline_lux": getattr(
                    camera,
                    "baseline_lux",
                    status.get("baseline_lux"),
                ),
            }
        )

    @staticmethod
    def _authority_subset(engine: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "current_mode",
            "house_state",
            "activity",
            "manual_override",
            "away_hold",
            "host_return_hold",
            "external_off_detected",
            "enabled",
        )
        result = {key: copy.deepcopy(engine.get(key)) for key in keys}
        dnd = engine.get("dnd")
        result["dnd_active"] = dnd.get("active") if isinstance(dnd, dict) else None
        return result

    def record_transit_evaluation(
        self,
        *,
        camera_status: dict[str, Any],
        camera: Any,
        authority: dict[str, Any],
    ) -> str | None:
        with self._lock:
            current_authority = self._authority_subset(authority)
            if current_authority != self._initial_authority:
                self._mark_gap(
                    field_or_event_id="engine_authority",
                    reason="authority changed inside stable navigation-v1 capture profile",
                    affected_decisions=["transit_tick", "working_restoration"],
                )
            status_view = self._camera_status_view(camera_status)
            lux_view = self._camera_lux_view(camera_status, camera)
            if status_view != self._last_camera_status:
                self._append_input(
                    kind="camera_status_change",
                    source_id="latitude",
                    payload=status_view,
                    captured_at_normalized=self._utc_for_mono(int(self.clock.monotonic_ns())),
                    normalization_provenance={"boundary": "TransitLightingService._check"},
                )
                self._last_camera_status = copy.deepcopy(status_view)
            if lux_view != self._last_camera_lux:
                self._append_input(
                    kind="camera_lux_change",
                    source_id="latitude",
                    payload=lux_view,
                    captured_at_normalized=self._utc_for_mono(int(self.clock.monotonic_ns())),
                    normalization_provenance={"boundary": "TransitLightingService._check"},
                )
                self._last_camera_lux = copy.deepcopy(lux_view)
            tick_id = self._append_input(
                kind="transit_tick",
                source_id="backend",
                payload={},
            )
            self._last_evaluation_event_id = tick_id
            return tick_id

    @staticmethod
    def _light_states(value: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        clean: dict[str, dict[str, Any]] = {}
        for light_id, state in value.items():
            clean[str(light_id)] = {
                key: _jsonable(item)
                for key, item in state.items()
                if key in _LIGHT_STATE_FIELDS
            }
        return clean

    def record_navigation_outcome(
        self,
        *,
        phase: str,
        requested_states: dict[str, dict[str, Any]],
        acknowledged_light_ids: list[str] | set[str],
        failed_light_ids: list[str] | set[str] = (),
        skipped_light_ids: list[str] | set[str] = (),
        deduplicated_light_ids: list[str] | set[str] = (),
        owned_light_ids: list[str] | set[str] = (),
        cache: dict[str, dict[str, Any]],
        cause_event_id: str | None = None,
        reason: str | None = None,
        owner: str | None = None,
    ) -> None:
        with self._lock:
            timing = self._next_timing(f"output:{phase}")
            if timing is None:
                return
            mono_ns, observed_utc = timing
            acknowledged = {str(item) for item in acknowledged_light_ids}
            failed = {str(item) for item in failed_light_ids}
            attempted = {str(item) for item in requested_states}
            ambiguous = acknowledged & failed
            unresolved = attempted - acknowledged - failed
            if ambiguous or unresolved:
                self._mark_gap(
                    field_or_event_id=f"output:{phase}",
                    reason=(
                        "adapter outcome is ambiguous or missing for attempted lights: "
                        f"ambiguous={sorted(ambiguous)} unresolved={sorted(unresolved)}"
                    ),
                    affected_decisions=["adapter_result", "ownership_cache"],
                )
            for light_id in requested_states:
                light_id = str(light_id)
                if light_id in acknowledged and light_id not in failed:
                    self._adapter_outcomes.append(True)
                elif light_id in failed and light_id not in acknowledged:
                    self._adapter_outcomes.append(False)

            self._output_sequence += 1
            value = {
                "phase": phase,
                "observed_at_utc": _iso_utc(observed_utc),
                "observed_mono_ns": mono_ns,
                "requested_states": self._light_states(requested_states),
                "acknowledged_light_ids": sorted(acknowledged),
                "failed_light_ids": sorted(failed),
                "skipped_light_ids": sorted(str(item) for item in skipped_light_ids),
                "deduplicated_light_ids": sorted(
                    str(item) for item in deduplicated_light_ids
                ),
                "owned_light_ids": sorted(str(item) for item in owned_light_ids),
                "last_applied_per_light": self._light_states(cache),
                "reason": reason,
                "owner": owner,
            }
            _reject_private_payload(value)
            assertion = ExpectedAssertionV1(
                assertion_id=f"capture-output-{self._output_sequence:06d}",
                category="historical",
                claim=(
                    "Observed output from this bounded capture; "
                    "not a reproduction of the July 2026 incident"
                ),
                value=_known(value),
                evidence_refs=[
                    cause_event_id or self._last_evaluation_event_id
                ]
                if cause_event_id or self._last_evaluation_event_id
                else [],
            )
            raw = assertion.model_dump(mode="json")
            if self._reserve(raw, label=assertion.assertion_id):
                self._assertions.append(assertion)

    def mark_incomplete(self, reason: str, *, field_or_event_id: str = "capture") -> None:
        with self._lock:
            self._mark_gap(
                field_or_event_id=field_or_event_id,
                reason=reason,
            )

    @property
    def complete(self) -> bool:
        return not self._gaps

    @property
    def dropped_records(self) -> int:
        return self._dropped_records

    @property
    def record_count(self) -> int:
        return len(self._inputs)

    def _detach_runtime(self) -> None:
        detacher = self._runtime_detacher
        if detacher is None:
            return
        self._runtime_detacher = None
        try:
            detacher()
        except Exception as exc:
            raise NavigationCaptureError("failed to detach runtime capture hooks") from exc

    def stop(self) -> None:
        self._detach_runtime()
        with self._lock:
            self._stopped = True

    def _window_end(self) -> datetime:
        end = self._utc_for_mono(self._last_mono_ns)
        if end <= self._checkpoint_utc:
            end = self._checkpoint_utc + timedelta(microseconds=1)
        max_end = self._checkpoint_utc + timedelta(seconds=self.max_duration_seconds)
        return min(end + timedelta(microseconds=1), max_end)

    def export(self, root: Path) -> Path:
        self._detach_runtime()
        with self._lock:
            self._stopped = True
            if root.exists():
                raise NavigationCaptureError("export target already exists")
            expected = ExpectedV1(
                schema_id="homehub.incident.navigation.expected.v1",
                schema_version=1,
                profile_id=PROFILE_ID,
                profile_version=PROFILE_VERSION,
                assertions=copy.deepcopy(self._assertions),
            )
            export_initial = self.initial.model_dump(mode="json")
            adapter = export_initial.get("adapter", {})
            if adapter.get("status") == "known" and isinstance(adapter.get("value"), dict):
                adapter["value"]["result_policy"] = {
                    "by_request": {
                        str(index): outcome
                        for index, outcome in enumerate(self._adapter_outcomes, start=1)
                    }
                }
            encoded = {
                "initial.json": _canonical_bytes(export_initial),
                "inputs.jsonl": (
                    b"".join(
                        _canonical_bytes(item.model_dump(mode="json")) + b"\n"
                        for item in self._inputs
                    )
                ),
                "expected.json": _canonical_bytes(expected.model_dump(mode="json")),
            }
            member_sha256 = {
                name: hashlib.sha256(content).hexdigest()
                for name, content in encoded.items()
            }
            manifest = ManifestV1(
                schema_id=SCHEMA_ID,
                schema_version=SCHEMA_VERSION,
                profile_id=PROFILE_ID,
                profile_version=PROFILE_VERSION,
                bundle_id=self.bundle_id,
                capture_provenance={
                    "kind": "bounded_navigation_capture",
                    "historical_claim": False,
                    "max_duration_seconds": self.max_duration_seconds,
                    "max_bytes": self.max_bytes,
                    "dropped_records": self._dropped_records,
                },
                completeness_status="complete" if self.complete else "incomplete",
                member_sha256=member_sha256,
                manifest_sha256="0" * 64,
                implementation=self.identity.implementation,
                configuration=self.identity.configuration,
                window={
                    "start_utc": self.initial.checkpoint_utc,
                    "end_utc": _iso_utc(self._window_end()),
                    "checkpoint_utc": self.initial.checkpoint_utc,
                    "timezone": "America/Indiana/Indianapolis",
                    "boundary": "[start,end)",
                },
                sessions=self.identity.sessions,
                time=self.identity.time,
                gaps=copy.deepcopy(self._gaps),
            )
            manifest_raw = manifest.model_dump(mode="json")
            manifest_raw.pop("manifest_sha256", None)
            manifest.manifest_sha256 = hashlib.sha256(
                _canonical_bytes(manifest_raw)
            ).hexdigest()
            root.mkdir(parents=True, exist_ok=False)
            for name, content in encoded.items():
                (root / name).write_bytes(content)
            (root / "manifest.json").write_bytes(
                _canonical_bytes(manifest.model_dump(mode="json"))
            )
        if self.complete:
            load_fixture_bundle(root)
        return root


_CAPTURE_TZ = ZoneInfo("America/Indiana/Indianapolis")


def _runtime_fusion_snapshot(presence: Any) -> dict[str, Any]:
    readings = getattr(presence, "_readings", None)
    if not isinstance(readings, dict):
        raise NavigationCaptureError("PresenceFusion readings are unavailable")
    items = list(readings.items())
    payload: dict[str, dict[str, Any]] = {}
    for source, reading in items:
        value = {
            field: _jsonable(getattr(reading, field, None))
            for field in _PRESENCE_FIELDS
        }
        if value["source"] != source:
            raise NavigationCaptureError("PresenceFusion source identity mismatch")
        payload[str(source)] = value
    return {
        "readings": payload,
        "reading_order": [str(source) for source, _ in items],
        "last_at_desk_at": _jsonable(getattr(presence, "_last_at_desk_at", None)),
        "last_at_desk_source": getattr(presence, "_last_at_desk_source", None),
        "last_global_absence_observed_at": _jsonable(
            getattr(presence, "_last_global_absence_observed_at", None)
        ),
        "last_strong_reacquisition_at": _jsonable(
            getattr(presence, "_last_strong_reacquisition_at", None)
        ),
        "last_strong_reacquisition_source": getattr(
            presence,
            "_last_strong_reacquisition_source",
            None,
        ),
    }


def _runtime_engine_snapshot(automation: Any) -> dict[str, Any]:
    process_raw = getattr(automation, "_last_process_observation_by_device", {})
    semantic_raw = getattr(automation, "_last_process_semantic_by_device", {})
    if process_raw or semantic_raw:
        raise NavigationCaptureError(
            "navigation-v1 capture requires desktop process evidence unavailable"
        )
    dnd_check = getattr(automation, "is_dnd_active", None)
    dnd_active = bool(dnd_check()) if callable(dnd_check) else False
    dnd_manager = getattr(automation, "_dnd", None)
    dnd_expiry = getattr(dnd_manager, "_expiry", None)
    house_state = getattr(automation, "house_state", None)
    activity = getattr(automation, "activity", None)
    return {
        "current_mode": getattr(automation, "current_mode", None),
        "house_state": house_state.title() if isinstance(house_state, str) else house_state,
        "activity": activity.title() if isinstance(activity, str) else activity,
        "mode_source": getattr(automation, "_mode_source", None),
        "mode_source_key": getattr(automation, "_mode_source_key", None),
        "last_mode_source_report_at": _jsonable(
            getattr(automation, "_last_mode_source_report_at", {})
        ),
        "last_process_observation_by_device": {},
        "last_process_semantic_by_device": {},
        "desktop_sensing_state": "unavailable",
        "manual_override": bool(getattr(automation, "_manual_override", False)),
        "override_mode": getattr(automation, "_override_mode", None),
        "override_source": getattr(automation, "_override_source", None),
        "override_time": _jsonable(getattr(automation, "_override_time", None)),
        "override_expiry_deferred": bool(
            getattr(automation, "_override_expiry_deferred", False)
        ),
        "override_timeout_hours": getattr(
            automation,
            "_override_timeout_hours",
            None,
        ),
        "idle_entered_at": _jsonable(getattr(automation, "_idle_entered_at", None)),
        "away_hold": bool(getattr(automation, "_away_hold", False)),
        "host_return_hold": bool(getattr(automation, "_host_return_hold", False)),
        "external_off_detected": bool(
            getattr(automation, "_external_off_detected", False)
        ),
        "home_awake_confirmed": bool(
            getattr(automation, "_home_awake_confirmed", False)
        ),
        "enabled": bool(getattr(automation, "_enabled", False)),
        "dnd": {
            "active": dnd_active,
            "active_until": _jsonable(dnd_expiry),
            "source": None,
        },
    }


def _runtime_transit_snapshot(transit: Any) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(transit, "_enabled", False)),
        "active": bool(getattr(transit, "_active", False)),
        "presence_armed": bool(getattr(transit, "_presence_armed", False)),
        "camera_absent_since": _jsonable(
            getattr(transit, "_camera_absent_since", None)
        ),
        "presence_during_absent_since": _jsonable(
            getattr(transit, "_presence_during_absent_since", None)
        ),
        "camera_present_since": _jsonable(
            getattr(transit, "_camera_present_since", None)
        ),
        "strong_absent_streak": int(
            getattr(transit, "_strong_absent_streak", 0)
        ),
        "last_block_reason": getattr(transit, "_last_block_reason", None),
        "transit_start": _jsonable(getattr(transit, "_transit_start", None)),
        "last_deactivated_at": _jsonable(
            getattr(transit, "_last_deactivated_at", None)
        ),
        "owned_lights": sorted(
            str(light_id) for light_id in getattr(transit, "_owned_lights", set())
        ),
    }


def _runtime_engine_state_snapshot(automation: Any) -> dict[str, Any]:
    state = getattr(automation, "_state", None)
    if state is None:
        raise NavigationCaptureError("AutomationEngine state is unavailable")
    return {
        "manual_light_overrides": _jsonable(state.manual_light_overrides),
        "manual_light_targets": _jsonable(state.manual_light_targets),
        "transit_light_overrides": _jsonable(state.transit_light_overrides),
        "transit_light_targets": _jsonable(state.transit_light_targets),
        "last_applied_per_light": _jsonable(state.last_applied_per_light),
    }


def _runtime_camera_snapshot(camera: Any) -> dict[str, Any]:
    status = camera.get_status() if camera is not None else {}
    if not isinstance(status, dict):
        raise NavigationCaptureError("camera status consumer view is unavailable")
    return {
        "status": NavigationIncidentCapture._camera_status_view(status),
        "lux": NavigationIncidentCapture._camera_lux_view(status, camera),
    }


def _runtime_ownership_snapshot(
    automation: Any,
    checkpoint_utc: datetime,
) -> dict[str, Any]:
    scene_overrides = getattr(automation, "_scene_overrides", {})
    working_day_scene = (
        scene_overrides.get("working", {}).get("day")
        if isinstance(scene_overrides, dict)
        else None
    )
    active_scene = getattr(automation, "_active_scene_override_key", None)
    desired_getter = getattr(automation, "_get_desired_effect", None)
    effect_desired = (
        desired_getter("working", "day")
        if callable(desired_getter)
        else None
    )
    effect_manager = getattr(automation, "_effect_manager", None)
    effect_active = getattr(effect_manager, "active_name", None)

    suspended = set(getattr(automation, "_suspended_external_owner_ids", set()))
    external_payload: list[dict[str, Any]] = []
    for owner in getattr(automation, "_external_light_owners", []):
        if id(owner) in suspended:
            continue
        owned = getattr(owner, "_owned", None)
        targets = getattr(owner, "_owned_targets", None)
        if not isinstance(owned, set) or not isinstance(targets, dict):
            raise NavigationCaptureError(
                "external light owner lacks passive ownership state"
            )
        light_ids = sorted(str(light_id) for light_id in owned if light_id in targets)
        if light_ids:
            external_payload.append(
                {
                    "name": getattr(owner, "owner_name", type(owner).__name__),
                    "light_ids": light_ids,
                }
            )

    sync = getattr(automation, "_screen_sync", None)
    screensync_owned: set[str] = set()
    if sync is not None:
        sent = getattr(sync, "_last_sent_state", None)
        by_light = getattr(sync, "_last_color_at_by_light", None)
        holds = getattr(sync, "_hold_refreshed_at", None)
        last_global = getattr(sync, "_last_color_at", None)
        if not isinstance(sent, dict) or not isinstance(by_light, dict) or not isinstance(holds, dict):
            raise NavigationCaptureError(
                "ScreenSync lacks passive ownership state"
            )
        if isinstance(last_global, datetime):
            global_age = (checkpoint_utc - last_global).total_seconds()
            if -2.0 <= global_age < SCREEN_SYNC_FRESH_SECONDS:
                screensync_owned.update(
                    str(light_id)
                    for light_id, observed_at in by_light.items()
                    if isinstance(observed_at, datetime)
                    and -2.0
                    <= (checkpoint_utc - observed_at).total_seconds()
                    < SCREEN_SYNC_FRESH_SECONDS
                    and light_id in sent
                )
        for key, refreshed_at in holds.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or not isinstance(refreshed_at, datetime)
            ):
                raise NavigationCaptureError(
                    "ScreenSync hold state is malformed"
                )
            _source, light_id = key
            age = (checkpoint_utc - refreshed_at).total_seconds()
            if (
                -2.0 <= age < SCREEN_SYNC_FRESH_SECONDS
                and light_id in sent
            ):
                screensync_owned.add(str(light_id))
    return {
        "scene_override_working_day": _jsonable(working_day_scene),
        "active_scene_override_key": _jsonable(active_scene),
        "effect_desired": _jsonable(effect_desired),
        "effect_active": _jsonable(effect_active),
        "external_light_owners": external_payload,
        "screensync_owned_light_ids": sorted(screensync_owned),
    }


def _runtime_working_context(
    automation: Any,
    presence: Any,
    checkpoint_utc: datetime,
) -> dict[str, Any]:
    period_getter = getattr(automation, "_get_time_period", None)
    if not callable(period_getter):
        raise NavigationCaptureError("AutomationEngine period resolver is unavailable")
    period = period_getter(checkpoint_utc.astimezone(_CAPTURE_TZ))
    if period != "day":
        raise NavigationCaptureError(
            f"navigation-v1 bounded capture requires Working/day, got {period}"
        )

    weather_service = getattr(automation, "_weather_service", None)
    cached_weather = None
    if weather_service is not None:
        getter = getattr(weather_service, "get_cached", None)
        cached_weather = getter() if callable(getter) else None
    sunset_ts = (
        cached_weather.get("sunset")
        if isinstance(cached_weather, dict)
        else None
    )
    weather_condition = getattr(automation, "current_weather_class", None)
    zone_getter = getattr(presence, "latest_zone", None)
    posture_getter = getattr(presence, "latest_posture", None)
    zone = zone_getter() if callable(zone_getter) else None
    posture = posture_getter() if callable(posture_getter) else None

    learner = getattr(automation, "_lighting_learner", None)
    learner_overlay = None
    learned_weather_ids: list[str] = []
    if learner is not None:
        preferences = getattr(learner, "_preferences", None)
        if not isinstance(preferences, dict):
            raise NavigationCaptureError(
                "lighting learner lacks passive preference state"
            )
        weather_bucket = weather_condition or "any"
        keys = ["working:day:any"]
        if weather_bucket != "any":
            keys.append(f"working:day:{weather_bucket}")
        if zone:
            keys.append(f"working:day:any:{zone}")
            if weather_bucket != "any":
                keys.append(f"working:day:{weather_bucket}:{zone}")
        merged: dict[str, dict[str, Any]] = {}
        for key in keys:
            slot = preferences.get(key) or {}
            if not isinstance(slot, dict):
                raise NavigationCaptureError(
                    "lighting learner preference slot is malformed"
                )
            for light_id, pref in slot.items():
                if not isinstance(pref, dict):
                    raise NavigationCaptureError(
                        "lighting learner light preference is malformed"
                    )
                merged[str(light_id)] = copy.deepcopy(pref)
        learner_overlay = merged or None
        if weather_condition and weather_bucket != "any":
            slot = preferences.get(f"working:day:{weather_bucket}") or {}
            learned_weather_ids = sorted(
                str(light_id)
                for light_id, pref in slot.items()
                if isinstance(pref, dict) and "bri" in pref
            )

    schedule = getattr(automation, "_schedule_config", None)
    if schedule is None or not is_dataclass(schedule):
        raise NavigationCaptureError("Working schedule configuration is unavailable")
    return {
        "schedule_config": asdict(schedule),
        "sunset_ts": _jsonable(sunset_ts),
        "current_game": getattr(automation, "current_game", None),
        "mode_brightness_working": getattr(
            automation,
            "_mode_brightness",
            {},
        ).get("working", 1.0),
        "learner_overlay_result": _jsonable(learner_overlay),
        "weather_condition": weather_condition,
        "learner_weather_pref_lights": learned_weather_ids,
        "last_lux_multiplier": getattr(automation, "_last_lux_multiplier", 1.0),
        "last_weather_class": getattr(automation, "_last_weather_class", None),
        "zone_posture": {"zone": zone, "posture": posture},
    }


def _runtime_boundary_snapshot(automation: Any) -> dict[str, Any]:
    boundary = getattr(automation, "_transition_boundary", None)
    if boundary is None:
        raise NavigationCaptureError("lighting transition boundary is unavailable")
    lock = getattr(boundary, "_lock", None)
    in_flight = bool(lock.locked()) if lock is not None else True
    if in_flight or bool(getattr(boundary, "held_by_current_task", False)):
        raise NavigationCaptureError(
            "capture cannot take a checkpoint while a lighting write is in flight"
        )
    return {
        "owner": None,
        "in_flight": False,
        "pending_adapter_completions": [],
    }


def _runtime_adapter_snapshot(automation: Any) -> dict[str, Any]:
    hue = getattr(automation, "_hue", None)
    connected = bool(hue is not None and getattr(hue, "connected", False))
    return {
        "connected": connected,
        "available": connected,
        # Export replaces this with exact acknowledgement outcomes observed
        # during the bounded window. An empty map fails closed on any request.
        "result_policy": {},
    }


def _runtime_snapshot(
    *,
    automation: Any,
    transit: Any,
    presence: Any,
    camera: Any,
    checkpoint_utc: datetime,
) -> dict[str, Any]:
    return {
        "fusion": _runtime_fusion_snapshot(presence),
        "engine": _runtime_engine_snapshot(automation),
        "transit": _runtime_transit_snapshot(transit),
        "camera": _runtime_camera_snapshot(camera),
        "engine_state": _runtime_engine_state_snapshot(automation),
        "working_context": _runtime_working_context(
            automation,
            presence,
            checkpoint_utc,
        ),
        "ownership": _runtime_ownership_snapshot(
            automation,
            checkpoint_utc,
        ),
        "adapter": _runtime_adapter_snapshot(automation),
        "transition_boundary": _runtime_boundary_snapshot(automation),
        "pending_evaluations": [],
    }


def _require_supported_runtime_snapshot(snapshot: dict[str, Any]) -> None:
    engine = snapshot["engine"]
    if (
        engine["current_mode"] != "working"
        or engine["house_state"] != "Home"
        or engine["activity"] != "Working"
    ):
        raise NavigationCaptureError(
            "navigation-v1 bounded capture requires Home + Working authority"
        )
    if (
        engine["dnd"]["active"]
        or engine["away_hold"]
        or engine["host_return_hold"]
        or engine["external_off_detected"]
        or not engine["enabled"]
    ):
        raise NavigationCaptureError(
            "navigation-v1 bounded capture requires unsuppressed automatic lighting"
        )
    ownership = snapshot["ownership"]
    if (
        ownership["scene_override_working_day"] is not None
        or ownership["active_scene_override_key"] is not None
        or ownership["effect_desired"] is not None
        or ownership["effect_active"] not in (False, None)
        or ownership["external_light_owners"]
        or ownership["screensync_owned_light_ids"]
    ):
        raise NavigationCaptureError(
            "navigation-v1 bounded capture cannot start with an active light owner"
        )


def snapshot_navigation_initial_state(
    *,
    identity: NavigationCaptureIdentity,
    automation: Any,
    transit: Any,
    presence: Any,
    camera: Any,
    clock: DecisionClock,
) -> InitialStateV1:
    """Take a fail-closed, coherent checkpoint from the live participant graph."""
    mono_ns = int(clock.monotonic_ns())
    anchor = _parse_utc(identity.time.wall_time_anchor_utc)
    delta_ns = mono_ns - identity.time.backend_monotonic_origin_ns
    checkpoint_utc = anchor + timedelta(microseconds=delta_ns // 1_000)

    observed_utc = clock.utc_now()
    if observed_utc.tzinfo is None:
        raise NavigationCaptureError("runtime clock must be timezone-aware")
    skew = abs(
        (observed_utc.astimezone(timezone.utc) - checkpoint_utc).total_seconds()
    )
    if skew > 0.250:
        raise NavigationCaptureError(
            f"capture identity clock mapping differs from runtime by {skew:.3f}s"
        )

    first = _runtime_snapshot(
        automation=automation,
        transit=transit,
        presence=presence,
        camera=camera,
        checkpoint_utc=checkpoint_utc,
    )
    _require_supported_runtime_snapshot(first)
    second = _runtime_snapshot(
        automation=automation,
        transit=transit,
        presence=presence,
        camera=camera,
        checkpoint_utc=checkpoint_utc,
    )
    if _canonical_bytes(first) != _canonical_bytes(second):
        raise NavigationCaptureError(
            "runtime participant state changed during checkpoint cut"
        )

    return InitialStateV1(
        schema_id="homehub.incident.navigation.initial.v1",
        schema_version=1,
        profile_id=PROFILE_ID,
        profile_version=PROFILE_VERSION,
        backend_boot_id=identity.sessions.backend_boot_id,
        backend_session_id=identity.sessions.backend_session_id,
        checkpoint_utc=_iso_utc(checkpoint_utc),
        quiescent=True,
        fusion=_known(first["fusion"]),
        engine=_known(first["engine"]),
        transit=_known(first["transit"]),
        camera=_known(first["camera"]),
        engine_state=_known(first["engine_state"]),
        working_context=_known(first["working_context"]),
        ownership=_known(first["ownership"]),
        adapter=_known(first["adapter"]),
        transition_boundary=_known(first["transition_boundary"]),
        pending_evaluations=_known(first["pending_evaluations"]),
    )
