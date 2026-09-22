"""Synthetic navigation-v1 bundle contract tests; no historical incident is claimed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.replay.validate import (
    BundleErrorCode,
    BundleValidationError,
    load_fixture_bundle,
)


def _known(value):
    return {"status": "known", "value": value}


def _not_consumed(reason: str):
    return {"status": "not_consumed", "reason": reason}


def _unknown(reason: str):
    return {"status": "unknown", "reason": reason}


def _base_parts() -> dict:
    initial = {
        "schema_id": "homehub.incident.navigation.initial.v1",
        "schema_version": 1,
        "profile_id": "navigation-v1",
        "profile_version": 1,
        "backend_boot_id": "synthetic-boot",
        "backend_session_id": "synthetic-backend-session",
        "checkpoint_utc": "2026-09-22T12:00:00Z",
        "quiescent": True,
        "fusion": _known(
            {
                "readings": {
                    "latitude": {
                        "source": "latitude",
                        "captured_at": "2026-09-22T11:59:59Z",
                        "face_present": True,
                    }
                },
                "reading_order": ["latitude"],
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
                "mode_source_key": "synthetic",
                "last_mode_source_report_at": "2026-09-22T11:50:00Z",
                "last_process_observation_by_device": {},
                "last_process_semantic_by_device": {},
                "desktop_sensing_state": "unavailable",
                "manual_override": True,
                "override_mode": "working",
                "override_source": "api:test",
                "override_time": "2026-09-22T11:00:00Z",
                "override_expiry_deferred": False,
                "override_timeout_hours": 4,
                "idle_entered_at": None,
                "away_hold": False,
                "host_return_hold": False,
                "external_off_detected": False,
                "home_awake_confirmed": True,
                "enabled": True,
                "dnd": {"active": False, "active_until": None, "source": None},
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
                    "last_detection": "2026-09-22T11:59:59Z",
                    "detection_source": "yolo",
                    "confidence": 0.9,
                    "zone": "couch",
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
                "schedule_config": {},
                "current_game": None,
                "mode_brightness_working": 1.0,
                "learner_overlay_result": {},
                "weather_condition": "clear",
                "learner_weather_pref_lights": [],
                "last_lux_multiplier": 1.0,
                "last_weather_class": "clear",
                "zone_posture": {"zone": "couch", "posture": None},
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
            {"owner": None, "in_flight": False, "pending_adapter_completions": []}
        ),
        "pending_evaluations": _known(
            [{"kind": "transit_tick", "received_mono_ns": 2_000_000_000}]
        ),
    }
    inputs = [
        {
            "schema_id": "homehub.incident.navigation.input.v1",
            "schema_version": 1,
            "event_id": "obs-1",
            "kind": "fusion_ingest",
            "source_id": "latitude",
            "source_session_id": "latitude-session",
            "source_sequence": _known(1),
            "captured_at_original": _known("2026-09-22T12:00:01Z"),
            "captured_at_normalized": "2026-09-22T12:00:01Z",
            "received_at_utc": "2026-09-22T12:00:01Z",
            "received_mono_ns": 1_000_000_000,
            "backend_dispatch_sequence": 10,
            "backend_boot_id": "synthetic-boot",
            "backend_session_id": "synthetic-backend-session",
            "clock_domain": "backend-boot:synthetic-boot",
            "normalization_provenance": _known({"future_clamped": False}),
            "payload": _known(
                {
                    "source": "latitude",
                    "captured_at": "2026-09-22T12:00:01Z",
                    "face_present": None,
                    "face_confidence": 0.0,
                    "detection_source": "yolo",
                    "zone": None,
                    "posture": None,
                    "posture_confidence": None,
                    "pose_visible_landmarks": None,
                }
            ),
            "evidence_refs": ["synthetic:obs-1"],
        },
        {
            "schema_id": "homehub.incident.navigation.input.v1",
            "schema_version": 1,
            "event_id": "tick-1",
            "kind": "transit_tick",
            "source_id": "backend",
            "source_session_id": "synthetic-backend-session",
            "source_sequence": _not_consumed("backend scheduler has no producer sequence"),
            "captured_at_original": _not_consumed("scheduler tick is backend-local"),
            "captured_at_normalized": "2026-09-22T12:00:02Z",
            "received_at_utc": "2026-09-22T12:00:02Z",
            "received_mono_ns": 2_000_000_000,
            "backend_dispatch_sequence": 11,
            "backend_boot_id": "synthetic-boot",
            "backend_session_id": "synthetic-backend-session",
            "clock_domain": "backend-boot:synthetic-boot",
            "normalization_provenance": _not_consumed("scheduler tick has no ingress normalization"),
            "payload": _known({}),
            "evidence_refs": [],
        },
    ]
    expected = {
        "schema_id": "homehub.incident.navigation.expected.v1",
        "schema_version": 1,
        "profile_id": "navigation-v1",
        "profile_version": 1,
        "assertions": [
            {
                "assertion_id": "synthetic-shape",
                "category": "simulated",
                "claim": "fixture contract is readable",
                "value": _known(True),
                "evidence_refs": [],
            }
        ],
    }
    manifest = {
        "schema_id": "homehub.incident.navigation.v1",
        "schema_version": 1,
        "profile_id": "navigation-v1",
        "profile_version": 1,
        "bundle_id": "synthetic-test-only",
        "capture_provenance": {"kind": "synthetic_test", "historical_claim": False},
        "completeness_status": "complete",
        "member_sha256": {},
        "manifest_sha256": "0" * 64,
        "implementation": {
            "backend_commit": "7219103",
            "backend_build": "synthetic",
            "backend_dirty": False,
            "python_version": "3.12-test",
            "dependency_identity": "synthetic-lock",
            "tzdata_identity": "synthetic-tzdata",
            "source_agent_build": _unknown("desktop sensing unavailable in profile"),
        },
        "configuration": {
            "consumed_values": {"profile": "navigation-v1"},
            "value_sources": {"profile": "synthetic_test"},
            "policy_digest": "a" * 64,
        },
        "window": {
            "start_utc": "2026-09-22T12:00:00Z",
            "end_utc": "2026-09-22T12:10:00Z",
            "checkpoint_utc": "2026-09-22T12:00:00Z",
            "timezone": "America/Indiana/Indianapolis",
            "boundary": "[start,end)",
        },
        "sessions": {
            "backend_boot_id": "synthetic-boot",
            "backend_session_id": "synthetic-backend-session",
            "source_sessions": {"latitude": "latitude-session"},
            "device_ids": {"latitude": "synthetic-latitude"},
        },
        "time": {
            "backend_monotonic_origin_ns": 0,
            "wall_time_anchor_utc": "2026-09-22T12:00:00Z",
            "clock_domain": "backend-boot:synthetic-boot",
            "adjustments": [],
        },
        "gaps": [],
    }
    return {"initial": initial, "inputs": inputs, "expected": expected, "manifest": manifest}


def _write_bundle(tmp_path: Path, mutate=None) -> Path:
    root = tmp_path / "synthetic-navigation-v1"
    root.mkdir(parents=True)
    parts = _base_parts()
    if mutate is not None:
        mutate(parts)

    encoded = {
        "initial.json": json.dumps(
            parts["initial"], sort_keys=True, separators=(",", ":")
        ).encode(),
        "inputs.jsonl": (
            "\n".join(
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in parts["inputs"]
            )
            + "\n"
        ).encode(),
        "expected.json": json.dumps(
            parts["expected"], sort_keys=True, separators=(",", ":")
        ).encode(),
    }
    parts["manifest"]["member_sha256"] = {
        name: hashlib.sha256(content).hexdigest() for name, content in encoded.items()
    }
    manifest_for_digest = dict(parts["manifest"])
    manifest_for_digest.pop("manifest_sha256", None)
    parts["manifest"]["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            manifest_for_digest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()

    for name, content in encoded.items():
        (root / name).write_bytes(content)
    (root / "manifest.json").write_text(
        json.dumps(parts["manifest"], sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return root


def _assert_code(error, code: BundleErrorCode) -> None:
    assert error.value.code is code


def test_loads_complete_synthetic_fixture_and_preserves_unknown_vs_absent(tmp_path: Path):
    bundle = load_fixture_bundle(_write_bundle(tmp_path))
    assert bundle.manifest.profile_id == "navigation-v1"
    assert bundle.inputs[0].payload.value["face_present"] is None

    def absent(parts):
        parts["inputs"][0]["payload"]["value"]["face_present"] = False

    absent_bundle = load_fixture_bundle(_write_bundle(tmp_path / "absent", absent))
    assert absent_bundle.inputs[0].payload.value["face_present"] is False


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda parts: parts["initial"].__setitem__(
                "engine", _unknown("engine checkpoint not captured")
            ),
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
        ),
        (
            lambda parts: parts["initial"]["engine"]["value"].pop("mode_source"),
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
        ),
        (
            lambda parts: parts["initial"].pop("fusion"),
            BundleErrorCode.INCOMPLETE_INITIAL_STATE,
        ),
    ],
)
def test_rejects_missing_or_unknown_required_checkpoint_state(tmp_path, mutate, code):
    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path, mutate))
    _assert_code(error, code)


def test_rejects_invalid_backend_and_source_ordering(tmp_path: Path):
    def bad_dispatch(parts):
        parts["inputs"][1]["backend_dispatch_sequence"] = 9

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path, bad_dispatch))
    _assert_code(error, BundleErrorCode.INVALID_INPUT_ORDER)

    def bad_source_sequence(parts):
        duplicate = dict(parts["inputs"][0])
        duplicate["event_id"] = "obs-2"
        duplicate["backend_dispatch_sequence"] = 12
        duplicate["received_mono_ns"] = 3_000_000_000
        duplicate["received_at_utc"] = "2026-09-22T12:00:03Z"
        duplicate["captured_at_normalized"] = "2026-09-22T12:00:03Z"
        duplicate["source_sequence"] = _known(1)
        parts["inputs"].append(duplicate)

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path / "source", bad_source_sequence))
    _assert_code(error, BundleErrorCode.INVALID_INPUT_ORDER)


def test_rejects_bad_member_hash_and_member_set(tmp_path: Path):
    root = _write_bundle(tmp_path)
    (root / "expected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(root)
    _assert_code(error, BundleErrorCode.BAD_HASH)

    extra = _write_bundle(tmp_path / "extra")
    (extra / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(extra)
    _assert_code(error, BundleErrorCode.BAD_MEMBER_SET)


def test_rejects_bad_manifest_digest(tmp_path: Path):
    root = _write_bundle(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifest_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(root)
    _assert_code(error, BundleErrorCode.BAD_MANIFEST_DIGEST)


def test_rejects_incomplete_bundle_and_missing_build_identity(tmp_path: Path):
    def incomplete(parts):
        parts["manifest"]["completeness_status"] = "incomplete"

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path, incomplete))
    _assert_code(error, BundleErrorCode.INCOMPLETE_BUNDLE)

    def missing_build(parts):
        parts["manifest"]["implementation"].pop("backend_commit")

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path / "build", missing_build))
    _assert_code(error, BundleErrorCode.SCHEMA_ERROR)


def test_rejects_active_excluded_owner_and_boot_crossing(tmp_path: Path):
    def owner(parts):
        parts["initial"]["ownership"]["value"]["screensync_owned_light_ids"] = ["2"]

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path, owner))
    _assert_code(error, BundleErrorCode.UNSUPPORTED_ACTIVE_OWNER)

    def boot(parts):
        parts["inputs"][0]["backend_boot_id"] = "next-boot"

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path / "boot", boot))
    _assert_code(error, BundleErrorCode.UNSUPPORTED_BOOT_CROSSING)


def test_rejects_profile_transition_and_wrong_profile(tmp_path: Path):
    def transition(parts):
        parts["inputs"][1]["kind"] = "activity_transition"

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path, transition))
    _assert_code(error, BundleErrorCode.UNSUPPORTED_PROFILE_TRANSITION)

    def profile(parts):
        parts["manifest"]["profile_id"] = "whole-home-v1"

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path / "profile", profile))
    _assert_code(error, BundleErrorCode.UNSUPPORTED_PROFILE)


def test_rejects_incomplete_presence_reading(tmp_path: Path):
    def missing_face(parts):
        parts["inputs"][0]["payload"]["value"].pop("face_present")

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path, missing_face))
    _assert_code(error, BundleErrorCode.INCOMPLETE_INPUT)


def test_replay_package_has_no_production_service_imports():
    package = Path("backend/replay")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    assert "backend.services" not in combined
    assert "backend.bootstrap" not in combined
    assert "HueService" not in combined




def test_rejects_raw_media_payload_and_source_session_mismatch(tmp_path: Path):
    def raw_media(parts):
        parts["inputs"][0]["payload"]["value"]["image_bytes"] = "not-allowed"

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path, raw_media))
    _assert_code(error, BundleErrorCode.FORBIDDEN_RAW_MEDIA)

    def wrong_source_session(parts):
        parts["inputs"][0]["source_session_id"] = "different-session"

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path / "session", wrong_source_session))
    _assert_code(error, BundleErrorCode.SCHEMA_ERROR)


def test_rejects_clock_domain_mismatch(tmp_path: Path):
    def wrong_clock(parts):
        parts["inputs"][1]["clock_domain"] = "different-clock"

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path, wrong_clock))
    _assert_code(error, BundleErrorCode.SCHEMA_ERROR)
