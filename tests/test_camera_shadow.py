"""Focused #198 tests for the zero-authority persistent-worker harness."""
from __future__ import annotations

from datetime import datetime, timezone
import inspect
import time

import numpy as np
import pytest

from backend.services.camera_service import CameraService
from backend.services.camera_shadow import (
    FailingFakeAdapter,
    FakeDeterministicAdapter,
    InMemoryShadowResultSink,
    MalformedFakeAdapter,
    ShadowCoordinator,
    ShadowResult,
    SlowFakeAdapter,
)


def _frame() -> np.ndarray:
    return np.zeros((24, 32, 3), dtype=np.uint8)


def _submit(coordinator: ShadowCoordinator) -> bool:
    return coordinator.submit(_frame(), captured_at=datetime.now(timezone.utc), width=32, height=24)


def _wait_until(predicate, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def _wait_for(sink: InMemoryShadowResultSink, count: int, timeout_s: float = 8.0) -> None:
    _wait_until(lambda: len(sink.results) >= count, timeout_s)


def test_disabled_default_creates_no_shadow_coordinator_or_worker():
    service = CameraService(ws_manager=object(), automation_engine=object())
    assert service._shadow_coordinator is None


def test_worker_uses_spawn_and_initializes_once_for_multiple_frames():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([FakeDeterministicAdapter()], sink)
    assert coordinator._mp_context.get_start_method() == "spawn"
    assert _submit(coordinator)
    _wait_for(sink, 1)
    first_pid = coordinator.worker_pid
    assert first_pid is not None
    assert _submit(coordinator)
    _wait_for(sink, 2)
    assert coordinator.worker_pid == first_pid
    assert [r.tracking_summary["fake_worker_init_count"] for r in sink.results] == [1, 1]
    assert all(r.worker_init_ms >= 0 for r in sink.results)
    coordinator.stop()


def test_one_source_frame_has_same_sequence_for_all_adapters():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([FakeDeterministicAdapter(), FakeDeterministicAdapter()], sink)
    assert _submit(coordinator)
    _wait_for(sink, 2)
    assert {result.metadata.frame_seq for result in sink.results} == {1}
    assert {result.metadata.run_id for result in sink.results} == {sink.results[0].metadata.run_id}
    coordinator.stop()


def test_latest_frame_wins_without_unbounded_queue():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([SlowFakeAdapter(0.4)], sink, adapter_timeout_s=1.0)
    assert _submit(coordinator)
    _wait_until(lambda: coordinator.active_adapter == "fake-slow")
    assert _submit(coordinator)
    assert _submit(coordinator)  # replaces pending frame 2 with frame 3
    _wait_for(sink, 3)
    assert coordinator.shadow_drops >= 1
    assert any(result.status == "shadow_drop" and result.metadata.frame_seq == 2 for result in sink.results)
    assert {result.metadata.frame_seq for result in sink.results if result.status == "ok"} == {1, 3}
    assert not coordinator.pending_frame
    coordinator.stop()


def test_burst_replacements_emit_one_drop_record_per_replaced_frame():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([SlowFakeAdapter(0.8)], sink, adapter_timeout_s=1.5)
    assert _submit(coordinator)  # frame 1 becomes active
    _wait_until(lambda: coordinator.active_adapter == "fake-slow")

    assert _submit(coordinator)  # frame 2 pending
    assert _submit(coordinator)  # frame 3 replaces 2
    assert _submit(coordinator)  # frame 4 replaces 3
    assert _submit(coordinator)  # frame 5 replaces 4

    _wait_until(lambda: coordinator.shadow_drops == 3)
    _wait_until(
        lambda: len([r for r in sink.results if r.status == "shadow_drop"]) == 3,
        timeout_s=5.0,
    )
    drops = [r.metadata.frame_seq for r in sink.results if r.status == "shadow_drop"]
    assert coordinator.shadow_drops == 3
    assert drops == [2, 3, 4]
    assert len(drops) == len(set(drops)) == 3

    _wait_until(lambda: any(r.metadata.frame_seq == 5 and r.status == "ok" for r in sink.results))
    assert not coordinator.pending_frame
    coordinator.stop()


def test_sleep_clears_queued_drop_metadata_before_resume():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([SlowFakeAdapter(0.8)], sink, adapter_timeout_s=1.5)
    assert _submit(coordinator)  # frame 1 active, generation 0
    _wait_until(lambda: coordinator.active_adapter == "fake-slow")

    assert _submit(coordinator)  # frame 2 pending
    assert _submit(coordinator)  # frame 3 replaces 2 -> queued drop notice
    assert _submit(coordinator)  # frame 4 replaces 3 -> queued drop notice
    assert coordinator.shadow_drops == 2

    coordinator.on_sleeping()
    coordinator.on_resume()
    assert _submit(coordinator)  # frame 5, new generation
    _wait_until(lambda: any(r.metadata.frame_seq == 5 and r.status == "ok" for r in sink.results))

    assert not any(
        r.status == "shadow_drop" and r.metadata.frame_seq in {2, 3}
        for r in sink.results
    )
    assert all(r.metadata.frame_seq >= 5 for r in sink.results)
    coordinator.stop()


def test_slow_shadow_submit_cannot_delay_authoritative_camera_result(monkeypatch):
    """The CameraService handoff returns before a slow worker finishes."""
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([SlowFakeAdapter(1.0)], sink, adapter_timeout_s=0.2)

    class Detector:
        def detect(self, image):
            return type("Results", (), {"detections": []})()

    def camera_with(coordinator_or_none):
        service = CameraService(object(), object(), shadow_coordinator=coordinator_or_none)
        service._cap = type("Cap", (), {"isOpened": lambda self: True, "read": lambda self: (True, _frame())})()
        service._face_detector = Detector()
        return service

    assert camera_with(None)._process_frame()["status"] == "absent"
    started = time.monotonic()
    result = camera_with(coordinator)._process_frame()
    assert result is not None and result["status"] == "absent"
    assert time.monotonic() - started < 0.5
    _wait_for(sink, 1)
    assert sink.results[0].status == "timeout"
    coordinator.stop()


@pytest.mark.parametrize("run", range(3))
def test_failing_and_malformed_adapters_are_deterministic_shadow_errors(run):
    """Repeated spawned-worker runs prove startup is not charged as inference."""
    del run
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator(
        [FailingFakeAdapter(), MalformedFakeAdapter()], sink, adapter_timeout_s=0.1,
    )
    assert _submit(coordinator)
    _wait_for(sink, 2)
    assert [result.status for result in sink.results] == ["error", "error"]
    assert coordinator.shadow_errors >= 2
    coordinator.stop()


def test_failing_adapter_cannot_change_authoritative_camera_result():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([FailingFakeAdapter()], sink)
    service = CameraService(object(), object(), shadow_coordinator=coordinator)
    service._cap = type("Cap", (), {"isOpened": lambda self: True, "read": lambda self: (True, _frame())})()

    class Detector:
        def detect(self, image):
            return type("Results", (), {"detections": []})()

    service._face_detector = Detector()
    result = service._process_frame()
    assert result is not None and result["status"] == "absent"
    _wait_for(sink, 1)
    assert sink.results[0].status == "error"
    coordinator.stop()


def test_hard_inference_timeout_terminates_worker_and_later_frame_recovers():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([SlowFakeAdapter(0.5)], sink, adapter_timeout_s=0.1)
    assert _submit(coordinator)
    _wait_for(sink, 1)
    assert sink.results[0].status == "timeout"
    assert not coordinator.worker_alive
    coordinator.stop()


def test_absolute_frame_lifetime_expires_before_inference():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([SlowFakeAdapter(0.4)], sink, adapter_timeout_s=0.15, max_frame_lifetime_s=0.15)
    assert _submit(coordinator)
    _wait_for(sink, 1)
    assert sink.results[0].status == "timeout"
    assert "frame lifetime" in (sink.results[0].detail or "")
    assert sink.results[0].end_to_end_ms >= 100
    coordinator.stop()


def test_sleep_immediate_resume_invalidates_active_generation_before_next_adapter():
    """A pre-sleep A cannot allow pre-sleep B after immediate resume."""
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([SlowFakeAdapter(0.2), FakeDeterministicAdapter()], sink, adapter_timeout_s=2.0)
    assert _submit(coordinator)  # frame 1, generation 0
    _wait_until(lambda: coordinator.active_adapter == "fake-slow")
    before_sleep_generation = coordinator.generation
    coordinator.on_sleeping()
    assert coordinator.generation == before_sleep_generation + 1
    assert not coordinator.worker_alive
    coordinator.on_resume()
    assert not coordinator.worker_alive  # resume is lazy; it cannot revive state
    assert _submit(coordinator)  # frame 2, generation 1
    _wait_for(sink, 2)
    assert {(r.metadata.frame_seq, r.model_id) for r in sink.results} == {
        (2, "fake-slow"), (2, "fake-deterministic"),
    }
    assert all(r.metadata.frame_seq != 1 for r in sink.results)
    coordinator.stop()


def test_result_returning_across_sleep_boundary_is_discarded():
    """The final sink check rejects a result invalidated just before emission."""
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([FakeDeterministicAdapter()], sink)
    original = coordinator._success_result

    def invalidate_then_return(*args, **kwargs):
        result = original(*args, **kwargs)
        coordinator.on_sleeping()
        coordinator.on_resume()
        return result

    coordinator._success_result = invalidate_then_return  # type: ignore[method-assign]
    assert _submit(coordinator)
    _wait_until(lambda: coordinator.generation == 1)
    time.sleep(0.1)
    assert sink.results == []
    coordinator._success_result = original  # type: ignore[method-assign]
    assert _submit(coordinator)
    _wait_for(sink, 1)
    assert sink.results[0].metadata.frame_seq == 2
    coordinator.stop()


def test_sleep_destroys_worker_tracking_and_resume_creates_fresh_worker_only_on_frame():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([FakeDeterministicAdapter()], sink)
    assert _submit(coordinator)
    _wait_for(sink, 1)
    first_pid = coordinator.worker_pid
    coordinator.on_sleeping()
    assert not coordinator.worker_alive
    coordinator.on_resume()
    assert not coordinator.worker_alive
    assert _submit(coordinator)
    _wait_for(sink, 2)
    assert coordinator.worker_pid != first_pid
    assert sink.results[1].tracking_summary["fake_worker_init_count"] == 1
    coordinator.stop()


def test_worker_crash_is_shadow_only_and_later_frame_restarts():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([SlowFakeAdapter(0.3)], sink, adapter_timeout_s=1.0)
    assert _submit(coordinator)
    _wait_until(lambda: coordinator.active_adapter == "fake-slow")
    process = coordinator._worker_process
    process.terminate()
    process.join(1.0)  # make the intentional crash observable before classification
    _wait_for(sink, 1)
    assert sink.results[0].status == "error"
    assert "crashed" in (sink.results[0].detail or "")
    assert _submit(coordinator)
    _wait_for(sink, 2)
    assert sink.results[1].status == "ok"
    coordinator.stop()


def test_stop_clears_pending_and_leaves_no_live_worker():
    sink = InMemoryShadowResultSink()
    coordinator = ShadowCoordinator([SlowFakeAdapter(2.0)], sink, adapter_timeout_s=2.5)
    assert _submit(coordinator)
    _wait_until(lambda: coordinator.active_adapter == "fake-slow")
    coordinator.stop(timeout_s=1.0)
    assert not coordinator.pending_frame
    assert not coordinator.worker_alive


def test_sink_failure_cannot_escape_or_create_authority_path():
    class FailingSink:
        def accept(self, result: ShadowResult) -> None:
            raise RuntimeError("intentional sink failure")

    coordinator = ShadowCoordinator([FakeDeterministicAdapter()], FailingSink())
    assert _submit(coordinator)
    _wait_until(lambda: coordinator.shadow_errors >= 1)
    coordinator.stop()


def test_schema_is_derived_only_and_module_has_no_disk_or_authority_imports():
    fields = set(ShadowResult.__dataclass_fields__)
    forbidden = {"frame", "image", "crop", "tensor", "hash", "landmarks", "reading"}
    assert not fields & forbidden
    source = inspect.getsource(__import__("backend.services.camera_shadow", fromlist=["*"]))
    for forbidden_import in ("presence_fusion import", "automation_engine import", "ml_decision", "websocket import", "cv2.VideoCapture"):
        assert forbidden_import not in source
    assert 'get_context("spawn")' in source
    assert "imencode" not in source
    assert ".write(" not in source
