"""Offline replay time, ordering, and checkpoint continuation contracts."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.replay.checkpoints import ReplayCheckpointError, ReplayCheckpointV1
from backend.replay.clock import ReplayClock, ReplayTimeError
from backend.replay.scheduler import ReplayScheduler, schedule_recorded_inputs
from backend.replay.schema import InitialStateV1, InputEnvelopeV1, ManifestV1, TimeIdentityV1
from tests.test_replay_bundle import _base_parts


def _time(**changes) -> TimeIdentityV1:
    values = {
        "backend_monotonic_origin_ns": 0,
        "wall_time_anchor_utc": "2026-09-22T12:00:00Z",
        "clock_domain": "backend-boot:synthetic-boot",
        "adjustments": [],
    }
    values.update(changes)
    return TimeIdentityV1.model_validate(values)


def _clock() -> ReplayClock:
    return ReplayClock(_time(), "2026-09-22T12:00:00Z")


def _checkpoint(mutate=None) -> ReplayCheckpointV1:
    parts = _base_parts()
    if mutate is not None:
        mutate(parts)
    return ReplayCheckpointV1.from_models(
        ManifestV1.model_validate(parts["manifest"]),
        InitialStateV1.model_validate(parts["initial"]),
    )


def test_clock_maps_anchor_checkpoint_and_forward_nanoseconds():
    clock = ReplayClock(
        _time(backend_monotonic_origin_ns=10_000_000_000),
        "2026-09-22T12:00:05Z",
    )
    assert clock.monotonic_ns() == 15_000_000_000
    assert clock.utc_now() == datetime(2026, 9, 22, 12, 0, 5, tzinfo=timezone.utc)
    clock.advance_to(15_000_000_001)
    assert clock.utc_now() == datetime(2026, 9, 22, 12, 0, 5, tzinfo=timezone.utc)
    clock.advance_to(17_500_001_000)
    assert clock.utc_now() == datetime(2026, 9, 22, 12, 0, 7, 500001, tzinfo=timezone.utc)


def test_clock_rejects_backward_naive_and_ambiguous_adjustments():
    clock = _clock()
    clock.advance_to(1_000)
    with pytest.raises(ReplayTimeError, match="backward"):
        clock.advance_to(999)
    assert clock.monotonic_ns() == 1_000
    with pytest.raises(ReplayTimeError, match="aware UTC"):
        ReplayClock(_time(wall_time_anchor_utc="2026-09-22T12:00:00"), "2026-09-22T12:00:00Z")
    with pytest.raises(ReplayTimeError, match="adjustments"):
        ReplayClock(_time(adjustments=[{"at": "2026-09-22T12:01:00Z"}]), "2026-09-22T12:00:00Z")
    with pytest.raises(ReplayTimeError, match="microsecond precision"):
        ReplayClock(_time(), "2026-09-22T12:00:00.0000001Z")


@pytest.mark.asyncio
async def test_scheduler_deadline_order_same_time_append_and_silence():
    scheduler = ReplayScheduler(_clock())
    seen = []

    async def first():
        seen.append(("first", scheduler.clock.monotonic_ns()))

        async def appended():
            seen.append(("appended", scheduler.clock.monotonic_ns()))

        scheduler.schedule(2, "later", appended)

    async def second():
        seen.append(("second", scheduler.clock.monotonic_ns()))

    async def early():
        seen.append(("early", scheduler.clock.monotonic_ns()))

    scheduler.schedule(2, "first", first)
    scheduler.schedule(2, "second", second)
    scheduler.schedule(1, "early", early)
    await scheduler.run_until(3)
    assert seen == [("early", 1), ("first", 2), ("second", 2), ("appended", 2)]
    await scheduler.run_until(1_000_000_000)
    assert scheduler.clock.utc_now().second == 1
    assert len(seen) == 4  # silence did not synthesize an evaluation


@pytest.mark.asyncio
async def test_scheduler_cancellation_survivors_and_equal_now():
    scheduler = ReplayScheduler(_clock())
    seen = []

    async def record(label):
        seen.append(label)

    scheduler.schedule(1, "one", lambda: record("one"))
    cancelled = scheduler.schedule(1, "two", lambda: record("two"))
    scheduler.schedule(1, "three", lambda: record("three"))
    scheduler.cancel(cancelled)
    scheduler.cancel(cancelled)
    await scheduler.run_until(1)
    scheduler.schedule(1, "now", lambda: record("now"))
    await scheduler.run_until(1)
    assert seen == ["one", "three", "now"]
    with pytest.raises(ValueError, match="before current"):
        scheduler.schedule(0, "past", lambda: record("past"))


@pytest.mark.asyncio
async def test_scheduler_exception_consumes_failing_entry_at_its_deadline():
    scheduler = ReplayScheduler(_clock())
    seen = []

    async def fail():
        raise RuntimeError("participant failed")

    async def survive():
        seen.append(scheduler.clock.monotonic_ns())

    scheduler.schedule(2, "bad", fail)
    scheduler.schedule(2, "good", survive)
    with pytest.raises(RuntimeError, match="participant failed"):
        await scheduler.run_until(10)
    assert scheduler.clock.monotonic_ns() == 2
    await scheduler.run_until(10)
    assert seen == [2]
    assert scheduler.clock.monotonic_ns() == 10


@pytest.mark.asyncio
async def test_checkpoint_pending_continuation_retains_tie_order():
    def pending(parts):
        parts["initial"]["pending_evaluations"]["value"] = [
            {"kind": "engine_tick", "received_mono_ns": 2},
            {"kind": "transit_tick", "received_mono_ns": 2},
            {"kind": "deadline_tick", "received_mono_ns": 1},
        ]

    checkpoint = _checkpoint(pending)
    assert checkpoint.quiescent is True
    assert checkpoint.initial.engine.status == "known"
    assert [item.source_identity for item in checkpoint.pending_evaluations] == [
        "checkpoint:0",
        "checkpoint:1",
        "checkpoint:2",
    ]
    scheduler = ReplayScheduler(checkpoint.create_clock())
    seen = []

    def resolver(item):
        async def deliver():
            seen.append((item.kind, item.checkpoint_sequence))

        return deliver

    checkpoint.seed_pending(scheduler, resolver)
    await scheduler.run_until(2)
    assert seen == [("deadline_tick", 2), ("engine_tick", 0), ("transit_tick", 1)]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda p: p["initial"]["pending_evaluations"]["value"].append(
                {"kind": "mystery_tick", "received_mono_ns": 3}
            ),
            "unknown kind",
        ),
        (
            lambda p: p["initial"]["pending_evaluations"]["value"].append({"kind": "engine_tick"}),
            "unknown kind or timing",
        ),
        (
            lambda p: p["initial"]["pending_evaluations"]["value"].append(
                {"kind": "engine_tick", "received_mono_ns": 3, "cadence": 60}
            ),
            "unknown kind or timing",
        ),
        (
            lambda p: p["initial"]["pending_evaluations"]["value"].append(
                {"kind": "engine_tick", "received_mono_ns": -1}
            ),
            "unknown kind or timing",
        ),
        (lambda p: p["initial"].__setitem__("backend_boot_id", "other"), "boot differs"),
        (lambda p: p["initial"].__setitem__("backend_session_id", "other"), "session differs"),
        (
            lambda p: p["initial"].__setitem__("checkpoint_utc", "2026-09-22T12:00:01Z"),
            "checkpoint time differs",
        ),
    ],
)
def test_checkpoint_rejects_invalid_continuation_or_identity(mutate, message):
    with pytest.raises(ReplayCheckpointError, match=message):
        _checkpoint(mutate)


def test_checkpoint_rejects_pending_before_cut_and_clock_mismatch():
    def before_cut(parts):
        parts["initial"]["checkpoint_utc"] = "2026-09-22T12:00:01Z"
        parts["manifest"]["window"]["checkpoint_utc"] = "2026-09-22T12:00:01Z"
        parts["initial"]["pending_evaluations"]["value"] = [
            {"kind": "transit_tick", "received_mono_ns": 999_999_999}
        ]

    with pytest.raises(ReplayCheckpointError, match="precedes checkpoint"):
        _checkpoint(before_cut)

    checkpoint = _checkpoint()
    wrong_domain = ReplayScheduler(
        ReplayClock(_time(clock_domain="other-domain"), "2026-09-22T12:00:00Z")
    )
    with pytest.raises(ReplayCheckpointError, match="domain"):
        checkpoint.seed_pending(wrong_domain, lambda _: lambda: None)

    moved = ReplayScheduler(checkpoint.create_clock())
    moved.clock.advance_to(checkpoint.checkpoint_mono_ns + 1)
    with pytest.raises(ReplayCheckpointError, match="checkpoint cut"):
        checkpoint.seed_pending(moved, lambda _: lambda: None)


def test_empty_checkpoint_schedule_stays_empty():
    def no_pending(parts):
        parts["initial"]["pending_evaluations"]["value"] = []

    checkpoint = _checkpoint(no_pending)
    scheduler = ReplayScheduler(checkpoint.create_clock())
    handles = checkpoint.seed_pending(scheduler, lambda _: (_ for _ in ()).throw(AssertionError()))
    assert handles == ()


@pytest.mark.asyncio
async def test_recorded_late_duplicate_and_mixed_completion_inputs_keep_dispatch_order():
    parts = _base_parts()
    original = parts["inputs"][0]
    records = []
    for index, (kind, captured) in enumerate(
        [
            ("fusion_ingest", "2026-09-22T11:59:59Z"),
            ("fusion_ingest", "2026-09-22T11:59:59Z"),
            ("adapter_completion", "2026-09-22T12:00:01Z"),
            ("adapter_completion", "2026-09-22T12:00:01Z"),
        ]
    ):
        raw = dict(original)
        raw.update(
            event_id=f"event-{index}",
            kind=kind,
            captured_at_normalized=captured,
            received_mono_ns=1_000_000_000 if index < 3 else 2_000_000_000,
            backend_dispatch_sequence=index + 10,
            source_sequence={"status": "known", "value": index + 1},
            payload={
                "status": "known",
                "value": {"request_id": f"request-{index % 2}", "ack": index},
            },
        )
        records.append(InputEnvelopeV1.model_validate(raw))
    scheduler = ReplayScheduler(_clock())
    seen = []

    async def dispatch(record):
        seen.append(
            (record.event_id, record.payload.value["request_id"], scheduler.clock.monotonic_ns())
        )

    schedule_recorded_inputs(
        scheduler,
        records,
        dispatch,
        backend_boot_id="synthetic-boot",
        backend_session_id="synthetic-backend-session",
        clock_domain="backend-boot:synthetic-boot",
    )
    await scheduler.run_until(3_000_000_000)
    assert seen == [
        ("event-0", "request-0", 1_000_000_000),
        ("event-1", "request-1", 1_000_000_000),
        ("event-2", "request-0", 1_000_000_000),
        ("event-3", "request-1", 2_000_000_000),
    ]


def test_recorded_input_helper_rejects_clock_and_dispatch_mismatch():
    parts = _base_parts()
    event = InputEnvelopeV1.model_validate(parts["inputs"][0])

    async def dispatch(_):
        pass

    with pytest.raises(ValueError, match="identity"):
        schedule_recorded_inputs(
            ReplayScheduler(ReplayClock(_time(clock_domain="wrong"), "2026-09-22T12:00:00Z")),
            [event],
            dispatch,
            backend_boot_id="synthetic-boot",
            backend_session_id="synthetic-backend-session",
            clock_domain="wrong",
        )
    with pytest.raises(ValueError, match="scheduler clock domain"):
        schedule_recorded_inputs(
            ReplayScheduler(ReplayClock(_time(clock_domain="other"), "2026-09-22T12:00:00Z")),
            [event],
            dispatch,
            backend_boot_id="synthetic-boot",
            backend_session_id="synthetic-backend-session",
            clock_domain="backend-boot:synthetic-boot",
        )
    later = event.model_copy(update={"event_id": "later", "backend_dispatch_sequence": 9})
    with pytest.raises(ValueError, match="JSONL order"):
        schedule_recorded_inputs(
            ReplayScheduler(_clock()),
            [event, later],
            dispatch,
            backend_boot_id="synthetic-boot",
            backend_session_id="synthetic-backend-session",
            clock_domain="backend-boot:synthetic-boot",
        )


def test_replay_time_modules_have_no_live_imports_or_sleep():
    for name in ("clock.py", "scheduler.py", "checkpoints.py"):
        tree = ast.parse((Path("backend/replay") / name).read_text(encoding="utf-8"))
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(
            module.startswith(
                (
                    "backend.services",
                    "backend.config",
                    "backend.bootstrap",
                    "socket",
                    "sqlite3",
                    "requests",
                    "httpx",
                    "time",
                    "asyncio",
                )
            )
            for module in modules
        )
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "sleep"
            for node in ast.walk(tree)
        )
