"""Fixture-only loader and validator for navigation-v1 incident bundles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .schema import (
    ExpectedV1,
    InitialStateV1,
    InputEnvelopeV1,
    KnownValue,
    ManifestV1,
    PROFILE_ID,
    SCHEMA_ID,
)


class BundleErrorCode(StrEnum):
    BAD_MEMBER_SET = "BAD_MEMBER_SET"
    UNSAFE_PATH = "UNSAFE_PATH"
    BAD_JSON = "BAD_JSON"
    BAD_HASH = "BAD_HASH"
    BAD_MANIFEST_DIGEST = "BAD_MANIFEST_DIGEST"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    UNSUPPORTED_PROFILE = "UNSUPPORTED_PROFILE"
    INCOMPLETE_BUNDLE = "INCOMPLETE_BUNDLE"
    INCOMPLETE_INITIAL_STATE = "INCOMPLETE_INITIAL_STATE"
    INCOMPLETE_INPUT = "INCOMPLETE_INPUT"
    FORBIDDEN_RAW_MEDIA = "FORBIDDEN_RAW_MEDIA"
    INVALID_INPUT_ORDER = "INVALID_INPUT_ORDER"
    UNSUPPORTED_ACTIVE_OWNER = "UNSUPPORTED_ACTIVE_OWNER"
    UNSUPPORTED_BOOT_CROSSING = "UNSUPPORTED_BOOT_CROSSING"
    UNSUPPORTED_PROFILE_TRANSITION = "UNSUPPORTED_PROFILE_TRANSITION"


class BundleValidationError(ValueError):
    def __init__(self, code: BundleErrorCode, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


REQUIRED_MEMBERS = frozenset(
    {"manifest.json", "initial.json", "inputs.jsonl", "expected.json"}
)
PAYLOAD_MEMBERS = frozenset(REQUIRED_MEMBERS - {"manifest.json"})

_FUSION_KEYS = frozenset(
    {
        "readings",
        "reading_order",
        "last_at_desk_at",
        "last_at_desk_source",
        "last_global_absence_observed_at",
        "last_strong_reacquisition_at",
        "last_strong_reacquisition_source",
    }
)
_ENGINE_KEYS = frozenset(
    {
        "current_mode",
        "house_state",
        "activity",
        "mode_source",
        "mode_source_key",
        "last_mode_source_report_at",
        "last_process_observation_by_device",
        "last_process_semantic_by_device",
        "desktop_sensing_state",
        "manual_override",
        "override_mode",
        "override_source",
        "override_time",
        "override_expiry_deferred",
        "override_timeout_hours",
        "idle_entered_at",
        "away_hold",
        "host_return_hold",
        "external_off_detected",
        "home_awake_confirmed",
        "enabled",
        "dnd",
    }
)
_TRANSIT_KEYS = frozenset(
    {
        "enabled",
        "active",
        "presence_armed",
        "camera_absent_since",
        "presence_during_absent_since",
        "camera_present_since",
        "strong_absent_streak",
        "last_block_reason",
        "transit_start",
        "last_deactivated_at",
        "owned_lights",
    }
)
_CAMERA_KEYS = frozenset({"status", "lux"})
_CAMERA_STATUS_KEYS = frozenset(
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
_CAMERA_LUX_KEYS = frozenset(
    {"enabled", "paused", "ema_lux", "last_lux_update", "baseline_lux"}
)
_ENGINE_STATE_KEYS = frozenset(
    {
        "manual_light_overrides",
        "manual_light_targets",
        "transit_light_overrides",
        "transit_light_targets",
        "last_applied_per_light",
    }
)
_WORKING_CONTEXT_KEYS = frozenset(
    {
        "schedule_config",
        "current_game",
        "mode_brightness_working",
        "learner_overlay_result",
        "weather_condition",
        "learner_weather_pref_lights",
        "last_lux_multiplier",
        "last_weather_class",
        "zone_posture",
    }
)
_OWNERSHIP_KEYS = frozenset(
    {
        "scene_override_working_day",
        "active_scene_override_key",
        "effect_desired",
        "effect_active",
        "external_light_owners",
        "screensync_owned_light_ids",
    }
)
_ADAPTER_KEYS = frozenset({"connected", "available", "result_policy"})
_BOUNDARY_KEYS = frozenset({"owner", "in_flight", "pending_adapter_completions"})
_PRESENCE_READING_KEYS = frozenset(
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
_FORBIDDEN_RAW_MEDIA_KEYS = frozenset(
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
    }
)
_UNSUPPORTED_TRANSITIONS = frozenset(
    {
        "boot_transition",
        "activity_transition",
        "lifecycle_transition",
        "period_transition",
        "owner_transition",
    }
)


@dataclass(frozen=True)
class IncidentBundleV1:
    """Validated immutable fixture data; this object performs no replay."""

    root: Path
    manifest: ManifestV1
    initial: InitialStateV1
    inputs: tuple[InputEnvelopeV1, ...]
    expected: ExpectedV1


def _fail(code: BundleErrorCode, message: str) -> None:
    raise BundleValidationError(code, message)


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleValidationError(
            BundleErrorCode.BAD_JSON, f"invalid JSON in {path.name}"
        ) from exc


def _parse(model_type: type, value: object, label: str):
    try:
        return model_type.model_validate(value)
    except ValidationError as exc:
        code = BundleErrorCode.SCHEMA_ERROR
        if label == "initial" and any(error["type"] == "missing" for error in exc.errors()):
            code = BundleErrorCode.INCOMPLETE_INITIAL_STATE
        raise BundleValidationError(code, f"invalid {label}: {exc}") from exc


def _parse_aware(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BundleValidationError(
            BundleErrorCode.SCHEMA_ERROR, f"{label} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None:
        _fail(BundleErrorCode.SCHEMA_ERROR, f"{label} must include a timezone")
    return parsed


def _parse_utc(value: str, label: str) -> datetime:
    parsed = _parse_aware(value, label)
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        _fail(BundleErrorCode.SCHEMA_ERROR, f"{label} must be UTC")
    return parsed


def _canonical_manifest_digest(raw_manifest: dict[str, Any]) -> str:
    canonical = dict(raw_manifest)
    canonical.pop("manifest_sha256", None)
    payload = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _reject_raw_media(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_RAW_MEDIA_KEYS:
                _fail(
                    BundleErrorCode.FORBIDDEN_RAW_MEDIA,
                    f"{path}.{key}: raw image/audio/screen content is outside navigation-v1",
                )
            _reject_raw_media(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_raw_media(child, f"{path}[{index}]")


def _known_mapping(evidence, label: str, required_keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(evidence, KnownValue):
        _fail(
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
            f"{label} checkpoint is {evidence.status}, not known",
        )
    if not isinstance(evidence.value, dict):
        _fail(BundleErrorCode.SCHEMA_ERROR, f"{label} checkpoint must be an object")
    missing = sorted(required_keys - set(evidence.value))
    if missing:
        _fail(
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
            f"{label} checkpoint missing required state: {', '.join(missing)}",
        )
    return evidence.value


def _validate_manifest(raw_manifest: object, manifest: ManifestV1) -> None:
    if not isinstance(raw_manifest, dict):
        _fail(BundleErrorCode.SCHEMA_ERROR, "manifest must be an object")
    if set(manifest.member_sha256) != PAYLOAD_MEMBERS:
        _fail(
            BundleErrorCode.BAD_MEMBER_SET,
            "member_sha256 must cover exactly initial.json, inputs.jsonl, expected.json",
        )
    if manifest.completeness_status != "complete":
        _fail(BundleErrorCode.INCOMPLETE_BUNDLE, "manifest marks bundle incomplete")
    consequential_gaps = [
        gap.field_or_event_id
        for gap in manifest.gaps
        if gap.completeness_consequence != "none"
    ]
    if consequential_gaps:
        _fail(
            BundleErrorCode.INCOMPLETE_BUNDLE,
            f"bundle has consequential evidence gaps: {', '.join(consequential_gaps)}",
        )
    digest = _canonical_manifest_digest(raw_manifest)
    if digest != manifest.manifest_sha256:
        _fail(BundleErrorCode.BAD_MANIFEST_DIGEST, "manifest digest mismatch")

    start = _parse_utc(manifest.window.start_utc, "window.start_utc")
    end = _parse_utc(manifest.window.end_utc, "window.end_utc")
    checkpoint = _parse_utc(manifest.window.checkpoint_utc, "window.checkpoint_utc")
    anchor = _parse_utc(manifest.time.wall_time_anchor_utc, "time.wall_time_anchor_utc")
    if not start <= checkpoint < end:
        _fail(
            BundleErrorCode.SCHEMA_ERROR,
            "window checkpoint must satisfy start <= checkpoint < end",
        )
    if anchor < start or anchor > end:
        _fail(BundleErrorCode.SCHEMA_ERROR, "wall-time anchor falls outside bundle window")


def _validate_initial(initial: InitialStateV1, manifest: ManifestV1) -> None:
    if initial.backend_boot_id != manifest.sessions.backend_boot_id:
        _fail(BundleErrorCode.UNSUPPORTED_BOOT_CROSSING, "initial boot differs from manifest")
    if initial.backend_session_id != manifest.sessions.backend_session_id:
        _fail(
            BundleErrorCode.UNSUPPORTED_BOOT_CROSSING,
            "initial backend session differs from manifest",
        )
    if initial.checkpoint_utc != manifest.window.checkpoint_utc:
        _fail(
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
            "initial checkpoint time differs from manifest window checkpoint",
        )
    if not initial.quiescent:
        _fail(
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
            "checkpoint is not quiescent",
        )

    fusion = _known_mapping(initial.fusion, "fusion", _FUSION_KEYS)
    engine = _known_mapping(initial.engine, "engine", _ENGINE_KEYS)
    _known_mapping(initial.transit, "transit", _TRANSIT_KEYS)
    camera = _known_mapping(initial.camera, "camera", _CAMERA_KEYS)
    _known_mapping(initial.engine_state, "engine_state", _ENGINE_STATE_KEYS)
    _known_mapping(initial.working_context, "working_context", _WORKING_CONTEXT_KEYS)
    ownership = _known_mapping(initial.ownership, "ownership", _OWNERSHIP_KEYS)
    _known_mapping(initial.adapter, "adapter", _ADAPTER_KEYS)
    boundary = _known_mapping(
        initial.transition_boundary, "transition_boundary", _BOUNDARY_KEYS
    )
    if not isinstance(initial.pending_evaluations, KnownValue):
        _fail(
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
            "pending_evaluations checkpoint is not known",
        )
    if not isinstance(initial.pending_evaluations.value, list):
        _fail(
            BundleErrorCode.SCHEMA_ERROR,
            "pending_evaluations checkpoint must be a list",
        )

    status = camera["status"]
    lux = camera["lux"]
    if not isinstance(status, dict) or not _CAMERA_STATUS_KEYS.issubset(status):
        _fail(
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
            "camera.status is missing consumed Transit fields",
        )
    if not isinstance(lux, dict) or not _CAMERA_LUX_KEYS.issubset(lux):
        _fail(
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
            "camera.lux is missing consumed navigation fields",
        )

    readings = fusion["readings"]
    order = fusion["reading_order"]
    if not isinstance(readings, dict) or not isinstance(order, list):
        _fail(
            BundleErrorCode.SCHEMA_ERROR,
            "fusion readings and insertion order must be explicit",
        )
    if set(order) != set(readings) or len(order) != len(readings):
        _fail(
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
            "fusion reading_order must name every reading exactly once",
        )

    if engine["current_mode"] != "working":
        _fail(BundleErrorCode.UNSUPPORTED_PROFILE, "navigation-v1 requires retained Working")
    if engine["house_state"] != "Home" or engine["activity"] != "Working":
        _fail(
            BundleErrorCode.UNSUPPORTED_PROFILE,
            "navigation-v1 requires Home + Working authority",
        )
    if engine["desktop_sensing_state"] not in {"unavailable", "stale"}:
        _fail(
            BundleErrorCode.UNSUPPORTED_PROFILE,
            "navigation-v1 requires desktop sensing unavailable or stale",
        )
    dnd = engine["dnd"]
    if not isinstance(dnd, dict) or "active" not in dnd:
        _fail(BundleErrorCode.INCOMPLETE_INITIAL_STATE, "engine.dnd is incomplete")
    if dnd["active"] is not False:
        _fail(BundleErrorCode.UNSUPPORTED_PROFILE, "navigation-v1 requires DND inactive")
    if engine["away_hold"] is not False or engine["host_return_hold"] is not False:
        _fail(
            BundleErrorCode.UNSUPPORTED_PROFILE,
            "navigation-v1 does not support Away/Return holds",
        )
    if engine["external_off_detected"] is not False or engine["enabled"] is not True:
        _fail(
            BundleErrorCode.UNSUPPORTED_PROFILE,
            "navigation-v1 requires enabled automatic lighting without external-off hold",
        )

    unsupported_owner = (
        ownership["scene_override_working_day"] is not None
        or ownership["active_scene_override_key"] is not None
        or ownership["effect_desired"] is not None
        or ownership["effect_active"] not in {False, None}
        or ownership["external_light_owners"] not in ({}, [])
        or ownership["screensync_owned_light_ids"] not in ([], {})
    )
    if unsupported_owner:
        _fail(
            BundleErrorCode.UNSUPPORTED_ACTIVE_OWNER,
            "scene/effect/external/ScreenSync ownership is active",
        )

    if (
        boundary["owner"] is not None
        or boundary["in_flight"] not in (False, [], {})
        or boundary["pending_adapter_completions"] not in ([], {})
    ):
        _fail(
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
            "transition boundary is not quiescent",
        )


def _validate_presence_payload(event: InputEnvelopeV1) -> None:
    if event.kind != "fusion_ingest":
        return
    if not isinstance(event.payload, KnownValue) or not isinstance(event.payload.value, dict):
        _fail(
            BundleErrorCode.INCOMPLETE_INPUT,
            f"{event.event_id}: fusion ingest payload is not known",
        )
    missing = sorted(_PRESENCE_READING_KEYS - set(event.payload.value))
    if missing:
        _fail(
            BundleErrorCode.INCOMPLETE_INPUT,
            f"{event.event_id}: PresenceReading missing {', '.join(missing)}",
        )


def _load_inputs(
    path: Path, manifest: ManifestV1
) -> tuple[InputEnvelopeV1, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise BundleValidationError(
            BundleErrorCode.BAD_JSON, "invalid inputs.jsonl"
        ) from exc

    inputs: list[InputEnvelopeV1] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            _fail(BundleErrorCode.BAD_JSON, f"blank JSONL line {line_number}")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BundleValidationError(
                BundleErrorCode.BAD_JSON, f"invalid JSONL line {line_number}"
            ) from exc
        _reject_raw_media(raw, f"inputs[{line_number}]")
        inputs.append(_parse(InputEnvelopeV1, raw, f"inputs line {line_number}"))

    previous_dispatch = -1
    previous_mono = -1
    seen_events: set[str] = set()
    source_sequences: dict[tuple[str, str], int] = {}
    window_start = _parse_utc(manifest.window.start_utc, "window.start_utc")
    window_end = _parse_utc(manifest.window.end_utc, "window.end_utc")

    for event in inputs:
        if event.event_id in seen_events:
            _fail(BundleErrorCode.INVALID_INPUT_ORDER, f"duplicate event_id {event.event_id}")
        seen_events.add(event.event_id)

        if event.backend_dispatch_sequence <= previous_dispatch:
            _fail(
                BundleErrorCode.INVALID_INPUT_ORDER,
                "backend dispatch sequence must be strictly increasing in JSONL order",
            )
        if event.received_mono_ns < previous_mono:
            _fail(
                BundleErrorCode.INVALID_INPUT_ORDER,
                "backend monotonic receipt time must be nondecreasing",
            )
        previous_dispatch = event.backend_dispatch_sequence
        previous_mono = event.received_mono_ns

        if event.backend_boot_id != manifest.sessions.backend_boot_id:
            _fail(
                BundleErrorCode.UNSUPPORTED_BOOT_CROSSING,
                f"{event.event_id}: backend boot differs from checkpoint",
            )
        if event.backend_session_id != manifest.sessions.backend_session_id:
            _fail(
                BundleErrorCode.UNSUPPORTED_BOOT_CROSSING,
                f"{event.event_id}: backend session differs from checkpoint",
            )
        expected_source_session = manifest.sessions.source_sessions.get(event.source_id)
        if expected_source_session is not None and event.source_session_id != expected_source_session:
            _fail(
                BundleErrorCode.SCHEMA_ERROR,
                f"{event.event_id}: source session disagrees with manifest",
            )
        if event.clock_domain != manifest.time.clock_domain:
            _fail(
                BundleErrorCode.SCHEMA_ERROR,
                f"{event.event_id}: clock domain disagrees with manifest",
            )
        if event.received_mono_ns < manifest.time.backend_monotonic_origin_ns:
            _fail(
                BundleErrorCode.INVALID_INPUT_ORDER,
                f"{event.event_id}: monotonic receipt precedes bundle clock origin",
            )
        if event.kind in _UNSUPPORTED_TRANSITIONS:
            code = (
                BundleErrorCode.UNSUPPORTED_BOOT_CROSSING
                if event.kind == "boot_transition"
                else BundleErrorCode.UNSUPPORTED_PROFILE_TRANSITION
            )
            _fail(code, f"{event.event_id}: unsupported {event.kind}")

        received = _parse_utc(event.received_at_utc, f"{event.event_id}.received_at_utc")
        _parse_utc(
            event.captured_at_normalized,
            f"{event.event_id}.captured_at_normalized",
        )
        if not window_start <= received < window_end:
            _fail(
                BundleErrorCode.INVALID_INPUT_ORDER,
                f"{event.event_id}: received_at_utc falls outside bundle window",
            )

        if isinstance(event.source_sequence, KnownValue):
            value = event.source_sequence.value
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                _fail(
                    BundleErrorCode.SCHEMA_ERROR,
                    f"{event.event_id}: known source_sequence must be a nonnegative integer",
                )
            source_key = (event.source_id, event.source_session_id)
            previous = source_sequences.get(source_key)
            if previous is not None and value <= previous:
                _fail(
                    BundleErrorCode.INVALID_INPUT_ORDER,
                    f"{event.event_id}: source sequence did not increase",
                )
            source_sequences[source_key] = value

        if isinstance(event.captured_at_original, KnownValue):
            if not isinstance(event.captured_at_original.value, str):
                _fail(
                    BundleErrorCode.SCHEMA_ERROR,
                    f"{event.event_id}: captured_at_original must be a timestamp string",
                )
            _parse_aware(
                event.captured_at_original.value,
                f"{event.event_id}.captured_at_original",
            )

        _validate_presence_payload(event)

    return tuple(inputs)


def load_fixture_bundle(root: str | Path) -> IncidentBundleV1:
    """Read one local JSON/JSONL fixture directory without production collaborators."""

    root_path = Path(root)
    if root_path.is_symlink():
        _fail(BundleErrorCode.UNSAFE_PATH, "bundle root may not be a symlink")
    if not root_path.is_dir():
        _fail(BundleErrorCode.BAD_MEMBER_SET, "bundle root must be a local directory")

    members = list(root_path.iterdir())
    names = {member.name for member in members}
    if names != REQUIRED_MEMBERS:
        _fail(
            BundleErrorCode.BAD_MEMBER_SET,
            "bundle must contain exactly manifest.json, initial.json, inputs.jsonl, expected.json",
        )
    if any(member.is_symlink() or not member.is_file() for member in members):
        _fail(BundleErrorCode.UNSAFE_PATH, "bundle members must be regular local files")

    raw_manifest = _load_json(root_path / "manifest.json")
    _reject_raw_media(raw_manifest, "manifest")
    if isinstance(raw_manifest, dict):
        if raw_manifest.get("schema_id") not in {None, SCHEMA_ID}:
            _fail(BundleErrorCode.UNSUPPORTED_SCHEMA, "unsupported incident schema")
        if raw_manifest.get("profile_id") not in {None, PROFILE_ID}:
            _fail(BundleErrorCode.UNSUPPORTED_PROFILE, "unsupported incident profile")
    manifest = _parse(ManifestV1, raw_manifest, "manifest")
    _validate_manifest(raw_manifest, manifest)

    for name in PAYLOAD_MEMBERS:
        actual = hashlib.sha256((root_path / name).read_bytes()).hexdigest()
        if actual != manifest.member_sha256[name]:
            _fail(BundleErrorCode.BAD_HASH, f"SHA-256 mismatch for {name}")

    raw_initial = _load_json(root_path / "initial.json")
    raw_expected = _load_json(root_path / "expected.json")
    _reject_raw_media(raw_initial, "initial")
    _reject_raw_media(raw_expected, "expected")
    initial = _parse(InitialStateV1, raw_initial, "initial")
    expected = _parse(ExpectedV1, raw_expected, "expected")
    _validate_initial(initial, manifest)
    inputs = _load_inputs(root_path / "inputs.jsonl", manifest)

    return IncidentBundleV1(
        root=root_path.resolve(),
        manifest=manifest,
        initial=initial,
        inputs=inputs,
        expected=expected,
    )
