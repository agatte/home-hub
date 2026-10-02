"""Slice 7 deterministic trace and synthetic navigation contract tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.replay import isolated_child
from tests.test_replay_bundle import _write_bundle
from tests.test_replay_navigation_root import (
    _backend_event,
    _make_absent_ready,
    _root,
)


def _records(root, *, kind=None, reason=None):
    records = root.trace.records
    if kind is not None:
        records = [record for record in records if record["kind"] == kind]
    if reason is not None:
        records = [record for record in records if reason in record["reason_codes"]]
    return records


@pytest.mark.asyncio
async def test_trace_jsonl_is_deterministic_and_synthetic_labeled(tmp_path):
    first = _root(tmp_path / "first", _make_absent_ready)
    second = _root(tmp_path / "second", _make_absent_ready)

    await first.run_until(1_000_000_000)
    await second.run_until(1_000_000_000)

    first_jsonl = first.trace.to_jsonl()
    assert first_jsonl == second.trace.to_jsonl()
    decoded = [json.loads(line) for line in first_jsonl.splitlines()]
    assert decoded
    assert decoded[0]["decision"]["input_kind"] == "initial_checkpoint"
    assert decoded[0]["cause_ids"] == ["checkpoint:initial"]
    assert {record["certainty"] for record in decoded} == {"synthetic_contract"}
    assert [record["record_id"] for record in decoded] == [
        f"r{index:06d}" for index in range(1, len(decoded) + 1)
    ]
    assert len({record["run_id"] for record in decoded}) == 1


def test_trace_jsonl_is_stable_across_hash_seeds():
    repo = Path(__file__).resolve().parents[1]
    script = """
import asyncio
import tempfile
from pathlib import Path
from tests.test_replay_navigation_root import _make_absent_ready, _root
root = _root(Path(tempfile.mkdtemp()) / "fixture", _make_absent_ready)
asyncio.run(root.run_until(1_000_000_000))
print(root.trace.to_jsonl(), end="")
"""
    outputs = []
    for seed in ("1", "987654"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]


@pytest.mark.asyncio
async def test_isolated_child_result_exports_deterministic_trace(tmp_path, monkeypatch):
    bundle_dir = _write_bundle(tmp_path)
    monkeypatch.setattr(
        isolated_child,
        "_run_isolation_self_test",
        lambda _bundle_dir: {"status": "passed", "checks": []},
    )

    payload = await isolated_child._run(bundle_dir)

    assert payload["status"] == "ok"
    trace_lines = payload["trace_jsonl"].splitlines()
    assert payload["trace_record_count"] == len(trace_lines)
    assert trace_lines
    decoded = [json.loads(line) for line in trace_lines]
    assert decoded[0]["decision"]["input_kind"] == "initial_checkpoint"
    assert {record["certainty"] for record in decoded} == {"synthetic_contract"}


@pytest.mark.asyncio
async def test_suppressed_transit_is_active_without_claiming_a_write(tmp_path):
    root = _root(tmp_path, _make_absent_ready)
    # The bundle validator intentionally rejects external-off as an initial
    # navigation-v1 profile. Toggle the in-memory test double only after the
    # valid synthetic contract is built, matching the existing manager unit seam.
    root.engine["external_off_detected"] = True
    await root.run_until(1_000_000_000)

    assert root.transit.active is True
    assert root.sink.requests == []
    proposal = _records(root, kind="PROPOSAL")
    assert len(proposal) == 1
    assert proposal[0]["light_ids"] == ["1", "3", "4"]
    assert proposal[0]["gates"]["physical_authority_gate"] == {
        "status": "not_evaluated",
        "reason_code": "navigation.physical_authority_gate_absent",
    }
    assert proposal[0]["gates"]["normal_applicator_guards"] == {
        "status": "not_evaluated",
        "reason_code": "lighting.direct_navigation_guard_set",
    }

    suppressed = _records(
        root,
        kind="SUPPRESSION",
        reason="lighting.external_off_suppressed",
    )
    assert len(suppressed) == 1
    assert suppressed[0]["light_ids"] == ["1", "3", "4"]
    assert suppressed[0]["gates"]["automation_write_authority"]["status"] == "blocked"
    delta = proposal[0]["relevant_state_delta"]
    assert delta["transit"]["active"] == {"before": False, "after": True}


@pytest.mark.asyncio
async def test_manual_kitchen_pair_suppression_preserves_original_proposal(tmp_path):
    def scenario(parts):
        _make_absent_ready(parts)
        state = parts["initial"]["engine_state"]["value"]
        state["manual_light_overrides"] = {"4": "2026-09-22T11:59:00Z"}
        state["manual_light_targets"] = {"4": {"on": True, "bri": 90}}

    root = _root(tmp_path, scenario)
    await root.run_until(1_000_000_000)

    assert [request.light_id for request in root.sink.requests] == ["1"]
    assert root.transit._owned_lights == {"1", "3", "4"}
    proposal = _records(root, kind="PROPOSAL")[0]
    assert proposal["light_ids"] == ["1", "3", "4"]
    suppression = _records(
        root,
        kind="SUPPRESSION",
        reason="lighting.manual_kitchen_pair",
    )[0]
    assert suppression["light_ids"] == ["3", "4"]


@pytest.mark.asyncio
async def test_simulated_failure_is_distinct_from_successful_cache_ownership(tmp_path):
    success = _root(tmp_path / "success", _make_absent_ready)

    def fail(parts):
        _make_absent_ready(parts, result_policy={"default": False})

    failed = _root(tmp_path / "failed", fail)
    await success.run_until(1_000_000_000)
    await failed.run_until(1_000_000_000)

    success_results = _records(
        success,
        kind="SIMULATED_RESULT",
        reason="lighting.adapter_acknowledged",
    )
    failed_results = _records(
        failed,
        kind="SIMULATED_RESULT",
        reason="lighting.adapter_rejected",
    )
    assert len(success_results) == len(failed_results) == 3
    assert all(record["result"]["acknowledged"] is True for record in success_results)
    assert all(record["result"]["acknowledged"] is False for record in failed_results)
    assert set(success.state.last_applied_per_light) == {"1", "3", "4"}
    assert failed.state.last_applied_per_light == {}
    assert failed.transit.active is True


@pytest.mark.asyncio
async def test_hard_timeout_trace_precedes_working_restoration_requests(tmp_path):
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

    timeout = _records(
        root,
        kind="DERIVED_DECISION",
        reason="navigation.hard_timeout",
    )
    assert len(timeout) == 1
    requests = _records(root, kind="REQUEST")
    assert requests
    assert all(record["owner"] == "working" for record in requests)
    assert timeout[0]["record_id"] < requests[0]["record_id"]


@pytest.mark.asyncio
async def test_expiry_defer_and_no_refire_have_stable_reason_codes(tmp_path):
    def stale_expiry(parts):
        engine = parts["initial"]["engine"]["value"]
        engine["override_time"] = "2026-09-22T07:00:00Z"
        engine["idle_entered_at"] = "2026-09-22T11:30:00Z"
        engine["last_mode_source_report_at"] = {"synthetic": "2026-09-22T07:00:00Z"}
        parts["inputs"] = [_backend_event(parts, "engine_tick", 1_000_000_000)]

    expiry = _root(tmp_path / "expiry", stale_expiry)
    await expiry.run_until(1_000_000_000)
    assert (
        len(
            _records(
                expiry,
                kind="DERIVED_DECISION",
                reason="activity.override_expiry_deferred",
            )
        )
        == 1
    )

    def no_refire(parts):
        _make_absent_ready(parts)
        transit = parts["initial"]["transit"]["value"]
        transit["presence_armed"] = False
        transit["camera_absent_since"] = None

    refire = _root(tmp_path / "no-refire", no_refire)
    await refire.run_until(1_000_000_000)
    assert refire.transit.active is False
    blocked = _records(
        refire,
        kind="SUPPRESSION",
        reason="navigation.awaiting_presence_edge",
    )
    assert len(blocked) == 1
    assert blocked[0]["gates"]["navigation_gate"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_absence_dwell_is_explicit_in_trace(tmp_path):
    def scenario(parts):
        _make_absent_ready(parts)
        parts["initial"]["transit"]["value"]["camera_absent_since"] = None

    root = _root(tmp_path, scenario)
    await root.run_until(1_000_000_000)

    assert root.transit.active is False
    dwell = _records(
        root,
        kind="DERIVED_DECISION",
        reason="navigation.absence_dwell_started",
    )
    assert len(dwell) == 1
    assert dwell[0]["decision"]["required_seconds"] == 10
    assert dwell[0]["gates"]["absence_dwell"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_camera_disabled_release_is_not_mislabeled_as_hard_timeout(tmp_path):
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
    root.camera.update_status({"enabled": False})
    await root.run_until(1_000_000_000)

    assert _records(root, reason="navigation.hard_timeout") == []
    disabled = _records(
        root,
        kind="SUPPRESSION",
        reason="navigation.camera_disabled",
    )
    assert len(disabled) == 1
