"""Slice 6 closed navigation-v1 composition-root and containment proof."""

from __future__ import annotations

import ast
import builtins
import copy
import importlib
import os
import socket
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.replay.isolated_runner import (
    ReplayIsolationUnavailable,
    require_supported_isolation,
    run_navigation_v1_isolated,
)
from backend.replay.navigation_v1 import (
    NavigationV1Replay,
    UnsupportedNavigationReplay,
)
from backend.replay.sinks import RecordingLightSink, ReplaySinkError
from backend.replay.validate import BundleErrorCode, BundleValidationError, load_fixture_bundle
from tests.test_replay_bundle import _base_parts, _known, _write_bundle


BASE_UTC = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def _iso_at(mono_ns: int) -> str:
    value = BASE_UTC + timedelta(microseconds=mono_ns // 1_000)
    return value.isoformat().replace("+00:00", "Z")


def _backend_event(
    parts: dict,
    kind: str,
    mono_ns: int,
    *,
    sequence: int = 10,
    event_id: str | None = None,
) -> dict:
    raw = copy.deepcopy(_base_parts()["inputs"][1])
    stamp = _iso_at(mono_ns)
    raw.update(
        event_id=event_id or f"{kind}-{sequence}",
        kind=kind,
        source_id="backend",
        source_session_id="synthetic-backend-session",
        received_at_utc=stamp,
        captured_at_normalized=stamp,
        received_mono_ns=mono_ns,
        backend_dispatch_sequence=sequence,
        payload=_known({}),
    )
    return raw


def _root(tmp_path: Path, mutate=None) -> NavigationV1Replay:
    def combined(parts):
        parts["initial"]["pending_evaluations"]["value"] = []
        if mutate is not None:
            mutate(parts)

    bundle = load_fixture_bundle(_write_bundle(tmp_path, combined))
    return NavigationV1Replay.from_bundle(bundle)


def _make_absent_ready(parts: dict, *, result_policy=None) -> None:
    reading = parts["initial"]["fusion"]["value"]["readings"]["latitude"]
    reading.update(
        face_present=False,
        face_confidence=0.0,
        detection_source="face",
        zone=None,
        posture=None,
        posture_confidence=None,
        pose_visible_landmarks=None,
    )
    status = parts["initial"]["camera"]["value"]["status"]
    status.update(
        last_detection="absent",
        detection_source="face",
        confidence=0.0,
        zone=None,
        posture=None,
    )
    parts["initial"]["working_context"]["value"]["zone_posture"] = {
        "zone": None,
        "posture": None,
    }
    transit = parts["initial"]["transit"]["value"]
    transit["presence_armed"] = True
    transit["camera_absent_since"] = "2026-09-22T11:59:45Z"
    if result_policy is not None:
        parts["initial"]["adapter"]["value"]["result_policy"] = result_policy
    parts["inputs"] = [_backend_event(parts, "transit_tick", 1_000_000_000)]


@pytest.mark.asyncio
async def test_transit_success_and_failure_preserve_acknowledgement_semantics(tmp_path):
    success = _root(tmp_path / "success", _make_absent_ready)
    await success.run_until(1_000_000_000)
    assert success.transit.active is True
    assert [request.light_id for request in success.sink.requests] == ["1", "3", "4"]
    assert set(success.state.transit_light_overrides) == {"1", "3", "4"}
    assert set(success.state.last_applied_per_light) == {"1", "3", "4"}
    assert all(request.result is True for request in success.sink.requests)

    def fail(parts):
        _make_absent_ready(parts, result_policy={"default": False})

    failed = _root(tmp_path / "failed", fail)
    await failed.run_until(1_000_000_000)
    assert failed.transit.active is True
    assert failed.transit._owned_lights == {"1", "3", "4"}
    assert failed.state.transit_light_overrides == {}
    assert failed.state.last_applied_per_light == {}
    assert all(request.result is False for request in failed.sink.requests)


@pytest.mark.asyncio
async def test_suppression_terminates_before_recording_sink(tmp_path):
    root = _root(tmp_path, lambda parts: parts.__setitem__("inputs", []))
    root.engine["external_off_detected"] = True
    await root.overrides.apply_transit_override(
        {"1": {"on": True, "bri": 50, "ct": 360}},
        duration_seconds=600,
        transition_time=5,
    )
    assert root.sink.requests == []
    assert root.state.transit_light_overrides == {}


@pytest.mark.asyncio
async def test_working_restoration_uses_applicator_protection_and_dedup(tmp_path):
    def scenario(parts):
        parts["inputs"] = []
        state = parts["initial"]["engine_state"]["value"]
        state["manual_light_overrides"] = {"2": "2026-09-22T11:30:00Z"}
        state["manual_light_targets"] = {"2": {"on": True, "bri": 77}}

    root = _root(tmp_path, scenario)
    await root.authority.reapply_mode("working")
    written = [request.light_id for request in root.sink.requests]
    assert "2" not in written
    assert set(written) == {"1", "3", "4", "5", "6"}
    first_count = len(root.sink.requests)
    await root.authority.reapply_mode("working")
    assert len(root.sink.requests) == first_count
    assert root.sink.settle_attempts == []
    assert len(root.events.light_adjustments) == first_count


@pytest.mark.asyncio
async def test_transit_hard_timeout_releases_and_restores_working(tmp_path):
    def scenario(parts):
        _make_absent_ready(parts)
        transit = parts["initial"]["transit"]["value"]
        transit.update(
            active=True,
            transit_start="2026-09-22T11:49:00Z",
            owned_lights=["1"],
            camera_absent_since=None,
        )
        state = parts["initial"]["engine_state"]["value"]
        state["transit_light_overrides"] = {"1": "2026-09-22T12:10:00Z"}
        state["transit_light_targets"] = {"1": {"on": True, "bri": 120, "ct": 360}}
        state["last_applied_per_light"] = {"1": {"on": True, "bri": 120, "ct": 360}}

    root = _root(tmp_path, scenario)
    await root.run_until(1_000_000_000)
    assert root.transit.active is False
    assert "1" not in root.state.transit_light_overrides
    assert "1" not in root.state.transit_light_targets
    assert any(request.light_id == "1" for request in root.sink.requests)
    assert root.sink.settle_attempts == []


@pytest.mark.asyncio
async def test_engine_tick_expires_manual_pair_before_later_transit(tmp_path):
    def scenario(parts):
        _make_absent_ready(parts)
        state = parts["initial"]["engine_state"]["value"]
        state["manual_light_overrides"] = {"4": "2026-09-22T07:00:00Z"}
        state["manual_light_targets"] = {"4": {"on": True, "bri": 90}}
        parts["inputs"] = [
            _backend_event(parts, "engine_tick", 500_000_000, sequence=10),
            _backend_event(parts, "transit_tick", 1_000_000_000, sequence=11),
        ]

    root = _root(tmp_path, scenario)
    await root.run_until(1_000_000_000)
    assert "4" not in root.state.manual_light_overrides
    assert "4" not in root.state.manual_light_targets
    assert "4" in [request.light_id for request in root.sink.requests]


@pytest.mark.asyncio
async def test_engine_expiry_uses_mode_source_reports_and_mutates_checkpoint_state(tmp_path):
    def fresh(parts):
        engine = parts["initial"]["engine"]["value"]
        engine["override_time"] = "2026-09-22T07:00:00Z"
        engine["idle_entered_at"] = "2026-09-22T11:30:00Z"
        engine["last_mode_source_report_at"] = {"synthetic": "2026-09-22T11:59:59Z"}
        state = parts["initial"]["engine_state"]["value"]
        state["manual_light_overrides"] = {"2": "2026-09-22T07:00:00Z"}
        state["manual_light_targets"] = {"2": {"on": True, "bri": 70}}
        parts["inputs"] = [_backend_event(parts, "engine_tick", 1_000_000_000)]

    fresh_root = _root(tmp_path / "fresh", fresh)
    await fresh_root.run_until(1_000_000_000)
    assert fresh_root.engine["manual_override"] is False
    assert fresh_root.engine["idle_entered_at"] is None
    assert fresh_root.authority.current_mode == "working"
    assert "2" not in [request.light_id for request in fresh_root.sink.requests]
    assert "2" not in fresh_root.state.manual_light_overrides
    assert fresh_root.sink.requests  # release force-reapplied Working

    def stale(parts):
        engine = parts["initial"]["engine"]["value"]
        engine["override_time"] = "2026-09-22T07:00:00Z"
        engine["idle_entered_at"] = "2026-09-22T11:30:00Z"
        engine["last_mode_source_report_at"] = {"synthetic": "2026-09-22T07:00:00Z"}
        parts["inputs"] = [_backend_event(parts, "engine_tick", 1_000_000_000)]

    stale_root = _root(tmp_path / "stale", stale)
    await stale_root.run_until(1_000_000_000)
    assert stale_root.engine["manual_override"] is True
    assert stale_root.engine["override_expiry_deferred"] is True
    assert stale_root.engine["idle_entered_at"] is None


def test_rejects_unavailable_profile_ambiguity_and_adapter_completion(tmp_path):
    def stale_desktop(parts):
        parts["initial"]["engine"]["value"]["desktop_sensing_state"] = "stale"

    with pytest.raises(UnsupportedNavigationReplay, match="desktop sensing"):
        _root(tmp_path / "desktop", stale_desktop)

    def adapter_completion(parts):
        event = _backend_event(parts, "adapter_completion", 1_000_000_000)
        parts["inputs"] = [event]

    with pytest.raises(UnsupportedNavigationReplay, match="adapter_completion"):
        _root(tmp_path / "completion", adapter_completion)

    def no_default_result(parts):
        parts["initial"]["adapter"]["value"]["result_policy"] = {"by_light": {"1": True}}

    with pytest.raises(UnsupportedNavigationReplay, match="default outcome"):
        _root(tmp_path / "result-policy", no_default_result)


def test_rejects_envelope_time_source_and_camera_contradictions(tmp_path):
    def wrong_source(parts):
        parts["inputs"] = [copy.deepcopy(parts["inputs"][0])]
        parts["inputs"][0]["payload"]["value"]["source"] = "desktop"

    with pytest.raises(UnsupportedNavigationReplay, match="fusion envelope identity"):
        _root(tmp_path / "source", wrong_source)

    def wrong_wall(parts):
        parts["inputs"] = [copy.deepcopy(parts["inputs"][0])]
        parts["inputs"][0]["received_at_utc"] = "2026-09-22T12:00:01.500000Z"

    with pytest.raises(UnsupportedNavigationReplay, match="wall/monotonic mismatch"):
        _root(tmp_path / "wall", wrong_wall)

    def conflicting_camera(parts):
        parts["inputs"] = []
        parts["initial"]["camera"]["value"]["lux"]["enabled"] = False

    with pytest.raises(UnsupportedNavigationReplay, match="conflicting camera"):
        _root(tmp_path / "camera", conflicting_camera)

    def bad_camera_update(parts):
        event = copy.deepcopy(parts["inputs"][0])
        event.update(
            event_id="camera-bad",
            kind="camera_status_change",
            source_id="latitude",
            source_session_id="latitude-session",
            received_at_utc="2026-09-22T12:00:01Z",
            captured_at_normalized="2026-09-22T12:00:01Z",
            received_mono_ns=1_000_000_000,
            backend_dispatch_sequence=10,
            payload=_known({"confidence": "high"}),
        )
        parts["inputs"] = [event]

    with pytest.raises(UnsupportedNavigationReplay, match="camera confidence"):
        _root(tmp_path / "update", bad_camera_update)


@pytest.mark.asyncio
async def test_camera_enabled_update_mirrors_single_production_availability_bit(tmp_path):
    def scenario(parts):
        event = copy.deepcopy(parts["inputs"][0])
        event.update(
            event_id="camera-disabled",
            kind="camera_status_change",
            source_id="latitude",
            source_session_id="latitude-session",
            received_at_utc="2026-09-22T12:00:01Z",
            captured_at_normalized="2026-09-22T12:00:01Z",
            received_mono_ns=1_000_000_000,
            backend_dispatch_sequence=10,
            payload=_known({"enabled": False}),
        )
        parts["inputs"] = [event]

    root = _root(tmp_path, scenario)
    await root.run_until(1_000_000_000)
    assert root.camera.status["enabled"] is False
    assert root.camera.lux["enabled"] is False


def test_recording_sink_is_data_only_and_fails_closed():
    with pytest.raises(ReplaySinkError, match="adapter outcome"):
        RecordingLightSink(
            connected=True,
            available=True,
            result_policy={"default": {"status": "import", "message": "os"}},
        )
    sink = RecordingLightSink(
        connected=True,
        available=True,
        result_policy={"by_light": {"1": True}},
    )

    async def unmatched():
        await sink.set_light("2", {"on": True})

    with pytest.raises(ReplaySinkError, match="no deterministic adapter outcome"):
        import asyncio

        asyncio.run(unmatched())
    assert sink.requests[-1].result is None


def test_operational_runner_fails_closed_without_reviewed_os_isolation(monkeypatch):
    monkeypatch.setattr(
        "backend.replay.isolated_runner.supported_isolation_backend",
        lambda: None,
    )
    with pytest.raises(ReplayIsolationUnavailable, match="operational replay requires"):
        require_supported_isolation()
    with pytest.raises(ReplayIsolationUnavailable):
        run_navigation_v1_isolated(bundle_path="synthetic-only")


def test_validator_requires_exact_checkpoint_presence_and_sunset(tmp_path):
    def missing_presence(parts):
        del parts["initial"]["fusion"]["value"]["readings"]["latitude"]["posture"]

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path / "presence", missing_presence))
    assert error.value.code is BundleErrorCode.INCOMPLETE_INITIAL_STATE

    def missing_sunset(parts):
        del parts["initial"]["working_context"]["value"]["sunset_ts"]

    with pytest.raises(BundleValidationError) as error:
        load_fixture_bundle(_write_bundle(tmp_path / "sunset", missing_sunset))
    assert error.value.code is BundleErrorCode.INCOMPLETE_INITIAL_STATE


def _project_module_path(repo: Path, name: str):
    parts = name.split(".")
    file_path = repo.joinpath(*parts).with_suffix(".py")
    if file_path.exists():
        return file_path, False
    init_path = repo.joinpath(*parts, "__init__.py")
    if init_path.exists():
        return init_path, True
    return None, False


def _project_import_closure(repo: Path):
    queue = ["backend.replay.navigation_v1"]
    visited: set[str] = set()
    external: set[str] = set()
    trees: dict[str, ast.AST] = {}
    while queue:
        name = queue.pop()
        if name in visited:
            continue
        path, is_package = _project_module_path(repo, name)
        assert path is not None, name
        visited.add(name)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        trees[name] = tree

        parts = name.split(".")
        for index in range(1, len(parts)):
            parent = ".".join(parts[:index])
            parent_path, _ = _project_module_path(repo, parent)
            if parent_path is not None and parent not in visited:
                queue.append(parent)

        package = name if is_package else name.rpartition(".")[0]
        for node in ast.walk(tree):
            imports: list[str] = []
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package_parts = package.split(".") if package else []
                    keep = max(0, len(package_parts) - (node.level - 1))
                    prefix = package_parts[:keep]
                    base = ".".join(prefix + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                if base:
                    imports.append(base)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    candidate = f"{base}.{alias.name}" if base else alias.name
                    candidate_path, _ = _project_module_path(repo, candidate)
                    if candidate_path is not None:
                        imports.append(candidate)
            for imported in imports:
                imported_path, _ = _project_module_path(repo, imported)
                if imported_path is not None:
                    queue.append(imported)
                else:
                    external.add(imported.split(".")[0])
    return visited, external, trees


def test_closed_project_import_graph_has_no_live_io_modules():
    repo = Path(__file__).resolve().parents[1]
    visited, external, trees = _project_import_closure(repo)

    expected_project = {
        "backend",
        "backend.replay",
        "backend.replay.checkpoints",
        "backend.replay.clock",
        "backend.replay.navigation_v1",
        "backend.replay.scheduler",
        "backend.replay.schema",
        "backend.replay.sinks",
        "backend.replay.validate",
        "backend.services",
        "backend.services.automation_constants",
        "backend.services.camera_constants",
        "backend.services.decision_clock",
        "backend.services.engine_state",
        "backend.services.heartbeat",
        "backend.services.light_applicator",
        "backend.services.light_override_manager",
        "backend.services.light_state_calculator",
        "backend.services.lighting_transition_boundary",
        "backend.services.navigation_activity_policy",
        "backend.services.presence_fusion",
        "backend.services.transit_lighting_service",
        "backend.services.working_light_composition",
    }
    expected_external = {
        "__future__",
        "asyncio",
        "collections",
        "contextlib",
        "contextvars",
        "copy",
        "dataclasses",
        "datetime",
        "enum",
        "hashlib",
        "heapq",
        "json",
        "logging",
        "math",
        "pathlib",
        "pydantic",
        "re",
        "threading",
        "time",
        "typing",
        "zoneinfo",
    }
    assert visited == expected_project
    assert external == expected_external

    forbidden_calls = {"eval", "exec", "__import__"}
    forbidden_attrs = {
        "system",
        "popen",
        "Popen",
        "create_connection",
        "urlopen",
        "write_text",
        "write_bytes",
        "unlink",
        "remove",
        "rmtree",
    }
    for name, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, (
                    name,
                    node.lineno,
                    node.func.id,
                )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_attrs, (
                    name,
                    node.lineno,
                    node.func.attr,
                )


@pytest.mark.asyncio
async def test_runtime_tripwire_root_execution_does_not_touch_live_io(tmp_path, monkeypatch):
    root = _root(tmp_path, lambda parts: parts.__setitem__("inputs", []))

    def denied(*args, **kwargs):
        raise AssertionError("live I/O tripwire fired")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(subprocess, "call", denied)
    monkeypatch.setattr(subprocess, "check_call", denied)
    monkeypatch.setattr(subprocess, "check_output", denied)
    monkeypatch.setattr(sqlite3, "connect", denied)
    monkeypatch.setattr(os, "system", denied)
    monkeypatch.setattr(os, "popen", denied)
    monkeypatch.setattr(builtins, "open", denied)
    monkeypatch.setattr(importlib, "import_module", denied)

    await root.authority.reapply_mode("working")
    await root.run_until(root.clock.monotonic_ns())
    assert root.sink.requests

    with pytest.raises(AssertionError, match="tripwire"):
        socket.socket()
    with pytest.raises(AssertionError, match="tripwire"):
        subprocess.run(["forbidden"])
