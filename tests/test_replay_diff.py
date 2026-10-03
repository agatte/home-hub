"""Slice 9 deterministic fixed-evidence trace diff tests."""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from backend.replay.diff import (
    DIFF_SCHEMA_ID,
    FIXED_EVIDENCE_MODE,
    ReplayTraceDiffError,
    compare_fixed_evidence_traces,
    render_trace_diff_markdown,
)
from tests.test_replay_navigation_root import _make_absent_ready, _root


def _jsonl(records: list[dict]) -> str:
    return "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in records
    )


def _record(
    *,
    record_id: str,
    kind: str = "DERIVED_DECISION",
    participant: str = "transit",
    dispatch_sequence: int | None = 10,
    mono_ns: int = 1_000_000_000,
    cause_ids: list[str] | None = None,
    light_ids: list[str] | None = None,
    decision: dict | None = None,
    reason_codes: list[str] | None = None,
    payload=None,
    result=None,
    request_id: str | None = None,
    certainty: str = "synthetic_contract",
) -> dict:
    return {
        "trace_version": 1,
        "run_id": "run-a",
        "record_id": record_id,
        "virtual_utc": "2026-09-22T12:00:01Z",
        "mono_ns": mono_ns,
        "dispatch_sequence": dispatch_sequence,
        "participant": participant,
        "kind": kind,
        "cause_ids": cause_ids or ["transit-tick-10"],
        "evidence_ids": [],
        "state_before_digest": "a" * 64,
        "relevant_state_delta": {},
        "decision": decision or {"action": "evaluate_navigation"},
        "reason_codes": reason_codes or [],
        "gates": {},
        "request_id": request_id,
        "owner": "transit" if kind in {"REQUEST", "SIMULATED_RESULT"} else None,
        "light_ids": light_ids or [],
        "payload": payload,
        "result": result,
        "certainty": certainty,
    }


@pytest.mark.asyncio
async def test_identical_navigation_replays_have_empty_semantic_diff(tmp_path):
    first = _root(tmp_path / "first", _make_absent_ready)
    second = _root(tmp_path / "second", _make_absent_ready)
    await first.run_until(1_000_000_000)
    await second.run_until(1_000_000_000)

    result = compare_fixed_evidence_traces(
        first.trace.to_jsonl(),
        second.trace.to_jsonl(),
        evidence_identity="fixture:synthetic-absent-ready",
        response_policy_identity="policy:default-success",
    )

    assert result["schema_id"] == DIFF_SCHEMA_ID
    assert result["mode"] == FIXED_EVIDENCE_MODE
    assert result["changes"] == []
    assert result["summary"]["changed"] == 0
    assert result["summary"]["inserted"] == 0
    assert result["summary"]["deleted"] == 0
    assert result["summary"]["unchanged"] == len(first.trace.records)


def test_changed_request_aligns_by_causal_semantics_not_record_or_request_id():
    baseline = _record(
        record_id="r000004",
        kind="REQUEST",
        participant="lighting_adapter",
        light_ids=["1"],
        decision={"action": "set_light"},
        payload={"on": True, "bri": 100},
        request_id="light_request:1",
    )
    candidate = copy.deepcopy(baseline)
    candidate.update(
        record_id="r000099",
        request_id="light_request:42",
        payload={"on": True, "bri": 120},
    )

    result = compare_fixed_evidence_traces(
        _jsonl([baseline]),
        _jsonl([candidate]),
        evidence_identity="bundle-sha256:abc",
        response_policy_identity="adapter-policy-sha256:def",
    )

    assert result["summary"] == {
        "aligned": 1,
        "unchanged": 0,
        "changed": 1,
        "inserted": 0,
        "deleted": 0,
    }
    assert [change["status"] for change in result["changes"]] == ["changed"]
    assert set(result["changes"][0]["field_differences"]) == {"payload"}
    assert result["changes"][0]["alignment"]["light_ids"] == ["1"]


def test_inserted_and_deleted_semantic_transitions_are_explicit():
    retained = _record(record_id="r000001")
    deleted = _record(
        record_id="r000002",
        kind="SUPPRESSION",
        decision={"action": "suppress_navigation"},
        reason_codes=["navigation.awaiting_presence_edge"],
    )
    inserted = _record(
        record_id="r000009",
        kind="REQUEST",
        participant="lighting_adapter",
        light_ids=["4"],
        decision={"action": "set_light"},
        payload={"on": True, "bri": 80},
        request_id="light_request:1",
    )

    result = compare_fixed_evidence_traces(
        _jsonl([retained, deleted]),
        _jsonl([retained, inserted]),
        evidence_identity="fixture:one",
        response_policy_identity="policy:one",
    )

    statuses = [change["status"] for change in result["changes"]]
    assert statuses.count("inserted") == 1
    assert statuses.count("deleted") == 1
    assert result["summary"]["unchanged"] == 1


def test_causal_anchor_uses_cause_identity_when_dispatch_sequence_is_absent():
    baseline = _record(
        record_id="r000001",
        dispatch_sequence=None,
        cause_ids=["deadline:transit:timeout"],
        decision={"action": "timeout"},
    )
    candidate = copy.deepcopy(baseline)
    candidate["record_id"] = "r000777"
    candidate["reason_codes"] = ["navigation.hard_timeout"]

    result = compare_fixed_evidence_traces(
        _jsonl([baseline]),
        _jsonl([candidate]),
        evidence_identity="fixture:one",
        response_policy_identity="policy:one",
    )

    change = result["changes"][0]
    assert change["status"] == "changed"
    assert change["alignment"]["causal_anchor"] == {"cause_ids": ["deadline:transit:timeout"]}


def test_fixed_evidence_diff_rejects_mixed_certainty():
    baseline = _record(record_id="r000001", certainty="synthetic_contract")
    candidate = _record(record_id="r000001", certainty="current_code_interpretation")
    with pytest.raises(
        ReplayTraceDiffError,
        match="cannot mix trace certainty classes",
    ):
        compare_fixed_evidence_traces(
            _jsonl([baseline]),
            _jsonl([candidate]),
            evidence_identity="fixture:one",
            response_policy_identity="policy:one",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_identity", ""),
        ("response_policy_identity", ""),
    ],
)
def test_fixed_evidence_diff_requires_explicit_shared_identity(field, value):
    kwargs = {
        "evidence_identity": "fixture:one",
        "response_policy_identity": "policy:one",
    }
    kwargs[field] = value
    trace = _jsonl([_record(record_id="r000001")])
    with pytest.raises(ReplayTraceDiffError, match=field):
        compare_fixed_evidence_traces(trace, trace, **kwargs)


def test_markdown_render_is_deterministic_and_intelligible():
    baseline = _record(
        record_id="r000001",
        kind="REQUEST",
        participant="lighting_adapter",
        light_ids=["1"],
        decision={"action": "set_light"},
        payload={"on": True, "bri": 100},
        request_id="light_request:1",
    )
    candidate = copy.deepcopy(baseline)
    candidate["payload"] = {"on": True, "bri": 120}

    result = compare_fixed_evidence_traces(
        _jsonl([baseline]),
        _jsonl([candidate]),
        evidence_identity="bundle-sha256:abc",
        response_policy_identity="adapter-policy-sha256:def",
    )
    first = render_trace_diff_markdown(result)
    second = render_trace_diff_markdown(result)

    assert first == second
    assert "# Fixed-evidence counterfactual diff" in first
    assert "**CHANGED** lighting_adapter/REQUEST lights=1" in first
    assert "`payload`" in first
    assert '"bri":100' in first
    assert '"bri":120' in first


def test_fixed_evidence_diff_rejects_different_fact_streams():
    baseline = _record(
        record_id="r000001",
        kind="FACT",
        participant="presence_fusion",
        decision={"input_kind": "presence"},
        payload={"source": "latitude", "face_present": True},
    )
    candidate = copy.deepcopy(baseline)
    candidate["payload"] = {"source": "latitude", "face_present": False}

    with pytest.raises(
        ReplayTraceDiffError,
        match="requires identical FACT evidence streams",
    ):
        compare_fixed_evidence_traces(
            _jsonl([baseline]),
            _jsonl([candidate]),
            evidence_identity="fixture:one",
            response_policy_identity="policy:one",
        )


def test_trace_parser_rejects_unsupported_trace_version():
    bad = _record(record_id="r000001")
    bad["trace_version"] = 999

    with pytest.raises(ReplayTraceDiffError, match="unsupported trace_version"):
        compare_fixed_evidence_traces(
            _jsonl([bad]),
            _jsonl([bad]),
            evidence_identity="fixture:one",
            response_policy_identity="policy:one",
        )
