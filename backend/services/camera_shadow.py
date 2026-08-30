"""Zero-authority, persistent-worker camera challenger harness.

``CameraService`` owns capture. This module receives an already-captured frame
and hands it to one spawned worker, which owns experimental adapters/models
while awake. A generation is captured with every frame; sleeping increments it
before worker termination, so resume cannot revive pre-sleep work.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import multiprocessing as mp
from queue import Empty
import threading
import time
from typing import Any, Literal, Protocol, Sequence
import uuid


ShadowStatus = Literal["ok", "abstain", "timeout", "error", "shadow_drop"]
MAX_FRAME_LIFETIME_S = 3.0


@dataclass(frozen=True, slots=True)
class NormalizedBox:
    """A box expressed only as normalized geometry, never pixels or crops."""

    center_x: float
    center_y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class KeypointSummary:
    """Named-keypoint aggregate; raw landmark coordinates are prohibited."""

    available_count: int
    mean_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ShadowPerson:
    bbox: NormalizedBox
    keypoints: KeypointSummary
    confidence: float | None = None
    torso_center: tuple[float, float] | None = None
    association_type: str = "single_frame"


@dataclass(frozen=True, slots=True)
class ShadowFrameMetadata:
    run_id: str
    frame_seq: int
    captured_at: datetime
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class ShadowAdapterOutput:
    """Strict, derived-only output adapters are allowed to produce."""

    model_id: str
    artifact_id: str
    artifact_checksum: str | None
    status: ShadowStatus
    person_detected: bool
    person_count: int
    max_person_confidence: float | None
    persons: tuple[ShadowPerson, ...] = ()
    preprocess_ms: float = 0.0
    inference_ms: float = 0.0
    postprocess_ms: float = 0.0
    tracking_summary: dict[str, int | float | str] | None = None


@dataclass(frozen=True, slots=True)
class ShadowResult:
    """Sink-safe record. It deliberately has no raw frame field."""

    metadata: ShadowFrameMetadata
    model_id: str
    artifact_id: str
    artifact_checksum: str | None
    status: ShadowStatus
    person_detected: bool
    person_count: int
    max_person_confidence: float | None
    persons: tuple[ShadowPerson, ...]
    preprocess_ms: float
    inference_ms: float
    postprocess_ms: float
    total_ms: float
    worker_init_ms: float = 0.0
    queue_handoff_ms: float = 0.0
    end_to_end_ms: float = 0.0
    tracking_summary: dict[str, int | float | str] | None = None
    detail: str | None = None


class ShadowModelAdapter(Protocol):
    """Spawn-safe challenger interface; adapters never receive a camera."""

    def infer(self, frame: Any, metadata: ShadowFrameMetadata) -> ShadowAdapterOutput:
        """Return only derived measurements."""


class ShadowResultSink(Protocol):
    """Derived-only boundary with no authority dependencies."""

    def accept(self, result: ShadowResult) -> None:
        """Accept one derived result."""


@dataclass
class InMemoryShadowResultSink:
    """Test/calibration sink. It never writes to disk or authority lanes."""

    results: list[ShadowResult] = field(default_factory=list)

    def accept(self, result: ShadowResult) -> None:
        self.results.append(result)


class FakeDeterministicAdapter:
    """Dependency-free fake proving construction happens once per worker."""

    model_id = "fake-deterministic"

    def __init__(self) -> None:
        self._worker_init_count = 0

    def initialize(self) -> None:
        self._worker_init_count += 1

    def infer(self, frame: Any, metadata: ShadowFrameMetadata) -> ShadowAdapterOutput:
        del frame, metadata
        return ShadowAdapterOutput(
            model_id=self.model_id, artifact_id="fake-v1", artifact_checksum="fake-sha256",
            status="ok", person_detected=True, person_count=1, max_person_confidence=0.9,
            persons=(ShadowPerson(
                bbox=NormalizedBox(0.5, 0.5, 0.2, 0.4),
                keypoints=KeypointSummary(available_count=5, mean_confidence=0.8),
                confidence=0.9,
                torso_center=(0.5, 0.55),
            ),),
            preprocess_ms=1.0, inference_ms=2.0, postprocess_ms=1.0,
            tracking_summary={"fake_worker_init_count": self._worker_init_count},
        )


class SlowFakeAdapter(FakeDeterministicAdapter):
    """Fake adapter that exercises timeout and sleep cancellation."""

    model_id = "fake-slow"

    def __init__(self, delay_s: float = 1.0) -> None:
        super().__init__()
        self.delay_s = delay_s

    def infer(self, frame: Any, metadata: ShadowFrameMetadata) -> ShadowAdapterOutput:
        time.sleep(self.delay_s)
        return super().infer(frame, metadata)


class FailingFakeAdapter:
    model_id = "fake-failing"

    def initialize(self) -> None:
        pass

    def infer(self, frame: Any, metadata: ShadowFrameMetadata) -> ShadowAdapterOutput:
        del frame, metadata
        raise RuntimeError("intentional fake adapter failure")


class MalformedFakeAdapter:
    """Fake contract violation used to prove output validation is isolated."""

    model_id = "fake-malformed"

    def initialize(self) -> None:
        pass

    def infer(self, frame: Any, metadata: ShadowFrameMetadata) -> ShadowAdapterOutput:
        del frame, metadata
        return "not a ShadowAdapterOutput"  # type: ignore[return-value]


def _worker_main(adapters: tuple[ShadowModelAdapter, ...], commands: Any, results: Any) -> None:
    """Own adapter/model state for one awake process lifetime."""
    started_at = time.monotonic()
    try:
        for adapter in adapters:
            initialize = getattr(adapter, "initialize", None)
            if callable(initialize):
                initialize()
    except BaseException as exc:
        results.put(("init_error", f"{type(exc).__name__}: {exc}"))
        return
    results.put(("ready", mp.current_process().pid, (time.monotonic() - started_at) * 1000.0))
    while True:
        command = commands.get()
        if command[0] == "stop":
            return
        _, job_id, adapter_index, frame, metadata, expires_at, dispatched_at = command
        if time.monotonic() >= expires_at:
            frame = None
            results.put(("expired", job_id, adapter_index))
            continue
        adapter = adapters[adapter_index]
        inference_started_at = time.monotonic()
        results.put(("started", job_id, adapter_index, inference_started_at, dispatched_at))
        try:
            results.put(("output", job_id, adapter_index, adapter.infer(frame, metadata)))
        except BaseException as exc:
            results.put(("error", job_id, adapter_index, f"{type(exc).__name__}: {exc}"))
        finally:
            frame = None


def _valid_output(output: Any) -> bool:
    if not isinstance(output, ShadowAdapterOutput):
        return False
    if output.status not in {"ok", "abstain", "timeout", "error", "shadow_drop"}:
        return False
    if output.person_count < 0 or output.person_count != len(output.persons):
        return False
    return all(
        0.0 <= value <= 1.0
        for person in output.persons
        for value in (person.bbox.center_x, person.bbox.center_y, person.bbox.width, person.bbox.height)
    )


class ShadowCoordinator:
    """Capacity-one, zero-authority parent of one persistent spawned worker."""

    def __init__(
        self, adapters: Sequence[ShadowModelAdapter], sink: ShadowResultSink, *,
        run_id: str | None = None, adapter_timeout_s: float = 1.0,
        max_frame_lifetime_s: float = MAX_FRAME_LIFETIME_S,
    ) -> None:
        if not 0 < adapter_timeout_s <= max_frame_lifetime_s <= MAX_FRAME_LIFETIME_S:
            raise ValueError("timeouts must be positive and at most three seconds")
        self._adapters = tuple(adapters)
        self._sink = sink
        self._mp_context = mp.get_context("spawn")  # never inherit camera FDs via fork
        self._run_id = run_id or f"camera-shadow-{uuid.uuid4().hex}"
        self._adapter_timeout_s = adapter_timeout_s
        self._max_frame_lifetime_s = max_frame_lifetime_s
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopped = False
        self._sleeping = False
        self._generation = 0
        self._pending: tuple[Any, ShadowFrameMetadata, int, float] | None = None
        self._drop_notices: deque[tuple[ShadowFrameMetadata, int]] = deque()
        self._frame_seq = 0
        self._thread: threading.Thread | None = None
        self._worker_process: Any = None
        self._commands: Any = None
        self._results: Any = None
        self._worker_init_ms = 0.0
        self._active_adapter: str | None = None
        self._job_seq = 0
        self.shadow_drops = 0
        self.shadow_timeouts = 0
        self.shadow_errors = 0

    @property
    def pending_frame(self) -> bool:
        with self._lock:
            return self._pending is not None

    @property
    def worker_alive(self) -> bool:
        with self._lock:
            return self._worker_process is not None and self._worker_process.is_alive()

    @property
    def worker_pid(self) -> int | None:
        with self._lock:
            return self._worker_process.pid if self._worker_process is not None else None

    @property
    def active_adapter(self) -> str | None:
        with self._lock:
            return self._active_adapter

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def submit(self, frame: Any, *, captured_at: datetime, width: int, height: int) -> bool:
        """Non-blocking latest-frame-wins offer from CameraService."""
        if not self._adapters or self._stopped or self._sleeping:
            return False
        if not self._lock.acquire(blocking=False):
            self.shadow_drops += 1
            return False
        try:
            if self._stopped or self._sleeping:
                return False
            self._frame_seq += 1
            metadata = ShadowFrameMetadata(self._run_id, self._frame_seq, captured_at, width, height)
            if self._pending is not None:
                self._drop_notices.append((self._pending[1], self._pending[2]))
                self._pending = None
                self.shadow_drops += 1
            self._pending = (frame, metadata, self._generation, time.monotonic())
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="camera-shadow", daemon=True)
                self._thread.start()
            self._wake.set()
            return True
        finally:
            self._lock.release()

    def on_sleeping(self) -> None:
        """Invalidate old work and destroy worker/model-local state."""
        with self._lock:
            self._generation += 1
            self._sleeping = True
            self._pending = None
            self._drop_notices.clear()
            self._active_adapter = None
            self._terminate_worker_locked()
        self._wake.set()

    def on_resume(self) -> None:
        """Permit only a newly submitted generation; startup remains lazy."""
        with self._lock:
            self._pending = None
            self._drop_notices.clear()
            self._sleeping = False
        self._wake.set()

    def stop(self, timeout_s: float = 1.0) -> None:
        """Boundedly terminate worker and erase every parent frame reference."""
        with self._lock:
            self._stopped = True
            self._generation += 1
            self._pending = None
            self._drop_notices.clear()
            self._active_adapter = None
            self._terminate_worker_locked()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout_s)

    def _terminate_worker_locked(self) -> None:
        process = self._worker_process
        commands, results = self._commands, self._results
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(0.5)
        # Each worker owns its own queue handles.  Do not retain Windows pipe
        # resources across sleep/timeout/crash restart cycles.
        for queue in (commands, results):
            if queue is not None:
                queue.cancel_join_thread()
                queue.close()
        self._worker_process = None
        self._commands = None
        self._results = None
        self._worker_init_ms = 0.0

    def _valid_generation(self, generation: int) -> bool:
        with self._lock:
            return not self._stopped and not self._sleeping and self._generation == generation

    def _run(self) -> None:
        while True:
            self._wake.wait(0.05)
            self._wake.clear()
            with self._lock:
                if self._stopped:
                    return
                drop_notices = tuple(self._drop_notices)
                self._drop_notices.clear()
                pending, self._pending = self._pending, None
            for drop_notice in drop_notices:
                self._emit(self._drop_result(drop_notice[0]), drop_notice[1])
            if pending is None:
                continue
            frame, metadata, generation, captured_monotonic = pending
            try:
                self._process_frame(frame, metadata, generation, captured_monotonic)
            finally:
                frame = None

    def _process_frame(self, frame: Any, metadata: ShadowFrameMetadata, generation: int, captured_monotonic: float) -> None:
        expires_at = captured_monotonic + self._max_frame_lifetime_s
        if not self._valid_generation(generation):
            return
        if time.monotonic() >= expires_at:
            self._expire_before_inference(self._adapters[0], metadata, generation, captured_monotonic)
            return
        if not self._ensure_worker(generation, expires_at):
            if self._valid_generation(generation):
                self._expire_before_inference(self._adapters[0], metadata, generation, captured_monotonic)
            return
        for adapter_index, adapter in enumerate(self._adapters):
            if not self._valid_generation(generation):
                return
            if time.monotonic() >= expires_at:
                self._expire_before_inference(adapter, metadata, generation, captured_monotonic)
                return
            if not self._invoke_adapter(adapter_index, adapter, frame, metadata, generation, captured_monotonic, expires_at):
                return  # timeout/crash: only a later frame may spawn a replacement worker

    def _ensure_worker(self, generation: int, expires_at: float) -> bool:
        with self._lock:
            if self._worker_process is not None and self._worker_process.is_alive():
                return True
            if self._stopped or self._sleeping or self._generation != generation:
                return False
            if self._worker_process is not None:
                # An idle worker may have died between frames. Close its queue
                # handles before replacing it for this later valid frame.
                self._terminate_worker_locked()
            commands = self._mp_context.Queue(maxsize=1)
            results = self._mp_context.Queue()
            process = self._mp_context.Process(target=_worker_main, args=(self._adapters, commands, results), daemon=True)
        # ``spawn`` can take long enough to matter to submit().  Do not hold
        # the capacity-one coordinator lock while it imports the child.
        process.start()
        with self._lock:
            if self._stopped or self._sleeping or self._generation != generation:
                process.terminate()
                process.join(0.5)
                return False
            self._commands, self._results, self._worker_process = commands, results, process
        while time.monotonic() < expires_at:
            if not self._valid_generation(generation):
                return False
            with self._lock:
                process, results = self._worker_process, self._results
            if process is None or results is None:
                return False
            if not process.is_alive():
                with self._lock:
                    if self._worker_process is process:
                        self._terminate_worker_locked()
                return False
            try:
                event = results.get(timeout=min(0.05, max(0.001, expires_at - time.monotonic())))
            except Empty:
                continue
            if event[0] == "ready":
                with self._lock:
                    if self._worker_process is process:
                        self._worker_init_ms = float(event[2])
                return self._valid_generation(generation)
            if event[0] == "init_error":
                self.shadow_errors += 1
                with self._lock:
                    if self._worker_process is process:
                        self._terminate_worker_locked()
                return False
        return False

    def _invoke_adapter(self, adapter_index: int, adapter: ShadowModelAdapter, frame: Any, metadata: ShadowFrameMetadata, generation: int, captured_monotonic: float, expires_at: float) -> bool:
        if not self._valid_generation(generation):
            return False
        with self._lock:
            process, commands, results = self._worker_process, self._commands, self._results
            self._job_seq += 1
            job_id = self._job_seq
        if process is None or commands is None or results is None or not process.is_alive():
            return False
        dispatched_at = time.monotonic()
        try:
            commands.put_nowait(("invoke", job_id, adapter_index, frame, metadata, expires_at, dispatched_at))
        except Exception:
            self.shadow_errors += 1
            self._emit(self._failure_result(adapter, metadata, "error", "worker handoff failed", captured_monotonic), generation)
            return False
        inference_deadline: float | None = None
        while True:
            if not self._valid_generation(generation):
                return False
            now = time.monotonic()
            deadline = expires_at if inference_deadline is None else min(expires_at, inference_deadline)
            if not process.is_alive():
                with self._lock:
                    if self._worker_process is process:
                        self._terminate_worker_locked()
                    self._active_adapter = None
                self.shadow_errors += 1
                self._emit(self._failure_result(adapter, metadata, "error", "worker crashed", captured_monotonic), generation)
                return False
            if now >= deadline:
                with self._lock:
                    if self._worker_process is process:
                        self._terminate_worker_locked()
                    self._active_adapter = None
                self.shadow_timeouts += 1
                detail = "frame lifetime expired" if deadline == expires_at else "adapter inference timed out"
                self._emit(self._failure_result(adapter, metadata, "timeout", detail, captured_monotonic), generation)
                return False
            try:
                event = results.get(timeout=min(0.05, deadline - now))
            except Empty:
                continue
            if len(event) < 3 or event[1] != job_id or event[2] != adapter_index:
                continue
            if event[0] == "expired":
                self.shadow_timeouts += 1
                self._emit(self._failure_result(adapter, metadata, "timeout", "frame lifetime expired before inference", captured_monotonic), generation)
                return False
            if event[0] == "started":
                inference_deadline = float(event[3]) + self._adapter_timeout_s
                with self._lock:
                    if self._generation == generation and not self._sleeping and not self._stopped:
                        self._active_adapter = getattr(adapter, "model_id", "unknown")
                continue
            with self._lock:
                self._active_adapter = None
            if event[0] == "error":
                self.shadow_errors += 1
                self._emit(self._failure_result(adapter, metadata, "error", str(event[3]), captured_monotonic), generation)
                return True
            if event[0] != "output" or not _valid_output(event[3]):
                self.shadow_errors += 1
                self._emit(self._failure_result(adapter, metadata, "error", "malformed adapter output", captured_monotonic), generation)
                return True
            self._emit(self._success_result(event[3], metadata, captured_monotonic, dispatched_at), generation)
            return True

    def _expire_before_inference(self, adapter: ShadowModelAdapter, metadata: ShadowFrameMetadata, generation: int, captured_monotonic: float) -> None:
        self.shadow_timeouts += 1
        self._emit(self._failure_result(adapter, metadata, "timeout", "frame lifetime expired before inference", captured_monotonic), generation)

    def _success_result(self, output: ShadowAdapterOutput, metadata: ShadowFrameMetadata, captured_monotonic: float, dispatched_at: float) -> ShadowResult:
        now = time.monotonic()
        return ShadowResult(
            metadata=metadata, model_id=output.model_id, artifact_id=output.artifact_id, artifact_checksum=output.artifact_checksum,
            status=output.status, person_detected=output.person_detected, person_count=output.person_count, max_person_confidence=output.max_person_confidence,
            persons=output.persons, preprocess_ms=output.preprocess_ms, inference_ms=output.inference_ms, postprocess_ms=output.postprocess_ms,
            total_ms=output.preprocess_ms + output.inference_ms + output.postprocess_ms, worker_init_ms=self._worker_init_ms,
            queue_handoff_ms=max(0.0, (now - dispatched_at) * 1000.0 - output.preprocess_ms - output.inference_ms - output.postprocess_ms),
            end_to_end_ms=max(0.0, (now - captured_monotonic) * 1000.0), tracking_summary=output.tracking_summary,
        )

    def _failure_result(self, adapter: ShadowModelAdapter, metadata: ShadowFrameMetadata, status: ShadowStatus, detail: str, captured_monotonic: float) -> ShadowResult:
        return ShadowResult(
            metadata=metadata, model_id=getattr(adapter, "model_id", "unknown"), artifact_id="unavailable", artifact_checksum=None,
            status=status, person_detected=False, person_count=0, max_person_confidence=None, persons=(), preprocess_ms=0.0,
            inference_ms=0.0, postprocess_ms=0.0, total_ms=0.0, worker_init_ms=self._worker_init_ms,
            end_to_end_ms=max(0.0, (time.monotonic() - captured_monotonic) * 1000.0), detail=detail,
        )

    @staticmethod
    def _drop_result(metadata: ShadowFrameMetadata) -> ShadowResult:
        return ShadowResult(
            metadata=metadata, model_id="coordinator", artifact_id="none", artifact_checksum=None, status="shadow_drop",
            person_detected=False, person_count=0, max_person_confidence=None, persons=(), preprocess_ms=0.0,
            inference_ms=0.0, postprocess_ms=0.0, total_ms=0.0, detail="replaced by newer pending frame",
        )

    def _emit(self, result: ShadowResult, generation: int) -> None:
        if not self._valid_generation(generation):
            return
        try:
            self._sink.accept(result)
        except Exception:
            self.shadow_errors += 1
