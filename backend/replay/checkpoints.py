"""Typed, quiescent continuation facts for one navigation-v1 replay boot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from .clock import ReplayClock, ReplayTimeError, parse_utc
from .scheduler import Continuation, ReplayScheduler, ScheduledHandle
from .schema import InitialStateV1, KnownValue, ManifestV1, StrictModel, TimeIdentityV1
from .validate import BundleValidationError, _validate_initial


class ReplayCheckpointError(ValueError):
    """The supplied checkpoint has no complete deterministic continuation."""


EvaluationKind = Literal["engine_tick", "transit_tick", "deadline_tick", "restoration_tick"]


class _PendingEvaluationRecord(StrictModel):
    kind: EvaluationKind
    received_mono_ns: Annotated[int, Field(ge=0)]


@dataclass(frozen=True)
class PendingEvaluationV1:
    kind: EvaluationKind
    deadline_mono_ns: int
    checkpoint_sequence: int

    @property
    def source_identity(self) -> str:
        return f"checkpoint:{self.checkpoint_sequence}"


@dataclass(frozen=True)
class ReplayCheckpointV1:
    """Retain the original participant state and type only continuation timing."""

    initial: InitialStateV1
    time: TimeIdentityV1
    backend_boot_id: str
    backend_session_id: str
    clock_domain: str
    checkpoint_utc: datetime
    checkpoint_mono_ns: int
    quiescent: bool
    pending_evaluations: tuple[PendingEvaluationV1, ...]

    @classmethod
    def from_models(cls, manifest: ManifestV1, initial: InitialStateV1) -> ReplayCheckpointV1:
        try:
            _validate_initial(initial, manifest)
        except BundleValidationError as exc:
            raise ReplayCheckpointError(str(exc)) from exc

        try:
            start = parse_utc(manifest.window.start_utc, "window.start_utc")
            end = parse_utc(manifest.window.end_utc, "window.end_utc")
            checkpoint_utc = parse_utc(manifest.window.checkpoint_utc, "window.checkpoint_utc")
            if not start <= checkpoint_utc < end:
                raise ReplayCheckpointError("checkpoint must satisfy start <= checkpoint < end")
            clock = ReplayClock(manifest.time, initial.checkpoint_utc)
        except ReplayTimeError as exc:
            raise ReplayCheckpointError(str(exc)) from exc

        if clock.utc_now() != checkpoint_utc:
            raise ReplayCheckpointError("initial checkpoint UTC differs from manifest window")
        if not isinstance(initial.pending_evaluations, KnownValue):
            raise ReplayCheckpointError("pending evaluations must be known")

        pending = []
        for index, raw in enumerate(initial.pending_evaluations.value):
            try:
                record = _PendingEvaluationRecord.model_validate(raw)
            except ValidationError as exc:
                raise ReplayCheckpointError(
                    f"pending_evaluations[{index}] has unknown kind or timing: {exc}"
                ) from exc
            if record.received_mono_ns < clock.monotonic_ns():
                raise ReplayCheckpointError(
                    f"pending_evaluations[{index}] precedes checkpoint monotonic cut"
                )
            pending.append(
                PendingEvaluationV1(
                    kind=record.kind,
                    deadline_mono_ns=record.received_mono_ns,
                    checkpoint_sequence=index,
                )
            )

        return cls(
            initial=initial,
            time=manifest.time,
            backend_boot_id=initial.backend_boot_id,
            backend_session_id=initial.backend_session_id,
            clock_domain=manifest.time.clock_domain,
            checkpoint_utc=checkpoint_utc,
            checkpoint_mono_ns=clock.monotonic_ns(),
            quiescent=initial.quiescent,
            pending_evaluations=tuple(pending),
        )

    def create_clock(self) -> ReplayClock:
        return ReplayClock(self.time, self.initial.checkpoint_utc)

    def seed_pending(
        self,
        scheduler: ReplayScheduler,
        resolver: Callable[[PendingEvaluationV1], Continuation],
    ) -> tuple[ScheduledHandle, ...]:
        """Enqueue known evaluations; caller owns participant dispatch."""

        clock = scheduler.clock
        if (
            clock.monotonic_ns() != self.checkpoint_mono_ns
            or clock.utc_now() != self.checkpoint_utc
            or clock.clock_domain != self.clock_domain
            or clock.backend_monotonic_origin_ns != self.time.backend_monotonic_origin_ns
            or clock.wall_time_anchor_utc
            != parse_utc(self.time.wall_time_anchor_utc, "wall_time_anchor_utc")
        ):
            raise ReplayCheckpointError("scheduler clock differs from checkpoint cut or domain")
        continuations = tuple(resolver(item) for item in self.pending_evaluations)
        if any(not callable(continuation) for continuation in continuations):
            raise ReplayCheckpointError("pending evaluation resolver must return async callables")
        return tuple(
            scheduler.schedule(item.deadline_mono_ns, item.kind, continuation)
            for item, continuation in zip(self.pending_evaluations, continuations, strict=True)
        )
