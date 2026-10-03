"""Deterministic semantic diff for navigation-v1 replay traces."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .trace import TRACE_VERSION, canonicalize

DIFF_SCHEMA_ID = "homehub.replay.navigation.diff.v1"
FIXED_EVIDENCE_MODE = "FIXED-EVIDENCE COUNTERFACTUAL"
_ALLOWED_CERTAINTY = frozenset({"synthetic_contract", "current_code_interpretation"})
_COMPARE_FIELDS = (
    "virtual_utc",
    "mono_ns",
    "cause_ids",
    "evidence_ids",
    "state_before_digest",
    "relevant_state_delta",
    "decision",
    "reason_codes",
    "gates",
    "owner",
    "light_ids",
    "payload",
    "result",
)


class ReplayTraceDiffError(ValueError):
    """A replay trace pair cannot support an honest fixed-evidence diff."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _parse_trace_jsonl(value: str, *, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        raise ReplayTraceDiffError(f"{label} trace must be JSONL text")

    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(value.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ReplayTraceDiffError(
                f"{label} trace line {line_number} is not valid JSON"
            ) from exc
        if not isinstance(record, dict):
            raise ReplayTraceDiffError(f"{label} trace line {line_number} must be a JSON object")
        required = {
            "trace_version",
            "run_id",
            "record_id",
            "virtual_utc",
            "mono_ns",
            "dispatch_sequence",
            "participant",
            "kind",
            "cause_ids",
            "evidence_ids",
            "state_before_digest",
            "relevant_state_delta",
            "decision",
            "reason_codes",
            "gates",
            "request_id",
            "owner",
            "light_ids",
            "payload",
            "result",
            "certainty",
        }
        missing = sorted(required - set(record))
        if missing:
            raise ReplayTraceDiffError(
                f"{label} trace line {line_number} missing fields: {', '.join(missing)}"
            )
        if record["trace_version"] != TRACE_VERSION:
            raise ReplayTraceDiffError(
                f"{label} trace line {line_number} has unsupported trace_version"
            )
        if not isinstance(record["record_id"], str) or not record["record_id"]:
            raise ReplayTraceDiffError(f"{label} trace line {line_number} has invalid record_id")
        if not isinstance(record["participant"], str) or not record["participant"]:
            raise ReplayTraceDiffError(f"{label} trace line {line_number} has invalid participant")
        if not isinstance(record["kind"], str) or not record["kind"]:
            raise ReplayTraceDiffError(f"{label} trace line {line_number} has invalid kind")
        if type(record["mono_ns"]) is not int:
            raise ReplayTraceDiffError(f"{label} trace line {line_number} has invalid mono_ns")
        if record["dispatch_sequence"] is not None and type(record["dispatch_sequence"]) is not int:
            raise ReplayTraceDiffError(
                f"{label} trace line {line_number} has invalid dispatch_sequence"
            )
        for field in ("cause_ids", "evidence_ids", "light_ids", "reason_codes"):
            if not isinstance(record[field], list):
                raise ReplayTraceDiffError(f"{label} trace line {line_number} has invalid {field}")
        records.append(record)
    if not records:
        raise ReplayTraceDiffError(f"{label} trace is empty")

    run_ids = {record["run_id"] for record in records}
    if len(run_ids) != 1:
        raise ReplayTraceDiffError(f"{label} trace contains multiple run_id values")
    certainties = {record["certainty"] for record in records}
    if len(certainties) != 1 or not certainties <= _ALLOWED_CERTAINTY:
        raise ReplayTraceDiffError(f"{label} trace has unsupported mixed certainty")
    record_ids = [record["record_id"] for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise ReplayTraceDiffError(f"{label} trace contains duplicate record_id values")
    return records


def _semantic_action(record: dict[str, Any]) -> dict[str, Any] | None:
    decision = record.get("decision")
    if not isinstance(decision, dict):
        return None
    for key in ("action", "input_kind", "transition", "event", "kind", "state"):
        if key in decision:
            return {key: canonicalize(decision[key])}
    return None


def _causal_anchor(record: dict[str, Any]) -> dict[str, Any]:
    dispatch_sequence = record.get("dispatch_sequence")
    if dispatch_sequence is not None:
        return {"dispatch_sequence": dispatch_sequence}
    cause_ids = record.get("cause_ids") or []
    if cause_ids:
        return {"cause_ids": canonicalize(cause_ids)}
    evidence_ids = record.get("evidence_ids") or []
    if evidence_ids:
        return {"evidence_ids": canonicalize(evidence_ids)}
    return {
        "virtual_utc": record.get("virtual_utc"),
        "mono_ns": record.get("mono_ns"),
    }


def _alignment_base(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "causal_anchor": _causal_anchor(record),
        "participant": record["participant"],
        "kind": record["kind"],
        "semantic_action": _semantic_action(record),
        "owner": record.get("owner"),
        "light_ids": sorted(str(item) for item in record.get("light_ids", [])),
    }


def _index_records(
    records: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    occurrences: dict[str, int] = defaultdict(int)
    indexed: dict[str, dict[str, Any]] = {}
    positions: dict[str, int] = {}
    for position, record in enumerate(records):
        base = _alignment_base(record)
        base_token = _canonical_json(base)
        occurrences[base_token] += 1
        alignment = dict(base)
        alignment["occurrence"] = occurrences[base_token]
        token = _canonical_json(alignment)
        indexed[token] = {"alignment": alignment, "record": record}
        positions[token] = position
    return indexed, positions


def _projection(record: dict[str, Any]) -> dict[str, Any]:
    return {field: canonicalize(record.get(field)) for field in _COMPARE_FIELDS}


def _field_differences(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    differences: dict[str, dict[str, Any]] = {}
    baseline_projection = _projection(baseline)
    candidate_projection = _projection(candidate)
    for field in _COMPARE_FIELDS:
        if baseline_projection[field] != candidate_projection[field]:
            differences[field] = {
                "baseline": baseline_projection[field],
                "candidate": candidate_projection[field],
            }
    return differences


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    summary = _projection(record)
    summary["record_id"] = record["record_id"]
    summary["request_id"] = record.get("request_id")
    return summary


def _certainty(records: list[dict[str, Any]]) -> str:
    return str(records[0]["certainty"])


def _fact_evidence_fingerprint(records: list[dict[str, Any]]) -> str:
    facts: list[dict[str, Any]] = []
    for record in records:
        if record["kind"] != "FACT":
            continue
        fact = {
            "causal_anchor": _causal_anchor(record),
            "participant": record["participant"],
            "virtual_utc": record["virtual_utc"],
            "mono_ns": record["mono_ns"],
            "dispatch_sequence": record["dispatch_sequence"],
            "cause_ids": canonicalize(record["cause_ids"]),
            "evidence_ids": canonicalize(record["evidence_ids"]),
            "decision": canonicalize(record["decision"]),
            "payload": canonicalize(record["payload"]),
        }
        if record["decision"] == {"input_kind": "initial_checkpoint"}:
            fact["initial_state"] = canonicalize(record["relevant_state_delta"])
        facts.append(fact)
    return _canonical_json(facts)


def compare_fixed_evidence_traces(
    baseline_trace_jsonl: str,
    candidate_trace_jsonl: str,
    *,
    evidence_identity: str,
    response_policy_identity: str,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
) -> dict[str, Any]:
    """Compare two traces under one explicitly shared immutable evidence contract."""

    for name, value in (
        ("evidence_identity", evidence_identity),
        ("response_policy_identity", response_policy_identity),
        ("baseline_label", baseline_label),
        ("candidate_label", candidate_label),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ReplayTraceDiffError(f"{name} must be a non-empty string")
    baseline_records = _parse_trace_jsonl(baseline_trace_jsonl, label=baseline_label)
    candidate_records = _parse_trace_jsonl(candidate_trace_jsonl, label=candidate_label)
    baseline_certainty = _certainty(baseline_records)
    candidate_certainty = _certainty(candidate_records)
    if baseline_certainty != candidate_certainty:
        raise ReplayTraceDiffError("fixed-evidence comparison cannot mix trace certainty classes")
    if _fact_evidence_fingerprint(baseline_records) != _fact_evidence_fingerprint(
        candidate_records
    ):
        raise ReplayTraceDiffError(
            "fixed-evidence comparison requires identical FACT evidence streams"
        )

    baseline_index, baseline_positions = _index_records(baseline_records)
    candidate_index, candidate_positions = _index_records(candidate_records)
    tokens = set(baseline_index) | set(candidate_index)

    def order_key(token: str) -> tuple[int, int, int, str]:
        baseline_item = baseline_index.get(token)
        candidate_item = candidate_index.get(token)
        records = [item["record"] for item in (baseline_item, candidate_item) if item is not None]
        mono_ns = min(int(record["mono_ns"]) for record in records)
        dispatch_values = [
            int(record["dispatch_sequence"])
            for record in records
            if record["dispatch_sequence"] is not None
        ]
        dispatch_sequence = min(dispatch_values) if dispatch_values else -1
        positions = [
            mapping[token]
            for mapping in (baseline_positions, candidate_positions)
            if token in mapping
        ]
        return (mono_ns, dispatch_sequence, min(positions), token)

    summary = {
        "aligned": 0,
        "unchanged": 0,
        "changed": 0,
        "inserted": 0,
        "deleted": 0,
    }
    changes: list[dict[str, Any]] = []

    for token in sorted(tokens, key=order_key):
        baseline_item = baseline_index.get(token)
        candidate_item = candidate_index.get(token)
        alignment = (
            baseline_item["alignment"] if baseline_item is not None else candidate_item["alignment"]
        )

        if baseline_item is None:
            summary["inserted"] += 1
            changes.append(
                {
                    "status": "inserted",
                    "alignment": alignment,
                    "candidate": _record_summary(candidate_item["record"]),
                }
            )
            continue
        if candidate_item is None:
            summary["deleted"] += 1
            changes.append(
                {
                    "status": "deleted",
                    "alignment": alignment,
                    "baseline": _record_summary(baseline_item["record"]),
                }
            )
            continue

        summary["aligned"] += 1
        differences = _field_differences(
            baseline_item["record"],
            candidate_item["record"],
        )
        if differences:
            summary["changed"] += 1
            changes.append(
                {
                    "status": "changed",
                    "alignment": alignment,
                    "baseline_record_id": baseline_item["record"]["record_id"],
                    "candidate_record_id": candidate_item["record"]["record_id"],
                    "field_differences": differences,
                }
            )
        else:
            summary["unchanged"] += 1

    return {
        "schema_id": DIFF_SCHEMA_ID,
        "mode": FIXED_EVIDENCE_MODE,
        "evidence_identity": evidence_identity,
        "response_policy_identity": response_policy_identity,
        "baseline": {
            "label": baseline_label,
            "certainty": baseline_certainty,
            "record_count": len(baseline_records),
        },
        "candidate": {
            "label": candidate_label,
            "certainty": candidate_certainty,
            "record_count": len(candidate_records),
        },
        "summary": summary,
        "changes": changes,
    }


def _inline_json(value: Any) -> str:
    return _canonical_json(value)


def render_trace_diff_markdown(diff_result: dict[str, Any]) -> str:
    """Render a concise deterministic Markdown explanation of a trace diff."""

    if diff_result.get("schema_id") != DIFF_SCHEMA_ID:
        raise ReplayTraceDiffError("unsupported replay diff schema")
    summary = diff_result.get("summary")
    changes = diff_result.get("changes")
    if not isinstance(summary, dict) or not isinstance(changes, list):
        raise ReplayTraceDiffError("malformed replay diff result")
    lines = [
        "# Fixed-evidence counterfactual diff",
        "",
        f"- Evidence: `{diff_result['evidence_identity']}`",
        f"- Response policy: `{diff_result['response_policy_identity']}`",
        (
            "- Summary: "
            f"{summary.get('changed', 0)} changed, "
            f"{summary.get('inserted', 0)} inserted, "
            f"{summary.get('deleted', 0)} deleted, "
            f"{summary.get('unchanged', 0)} unchanged"
        ),
    ]
    if not changes:
        lines.extend(["", "No semantic trace differences."])
        return "\n".join(lines) + "\n"

    lines.extend(["", "## Changes", ""])
    for change in changes:
        alignment = change["alignment"]
        anchor = _inline_json(alignment["causal_anchor"])
        light_ids = alignment.get("light_ids") or []
        light_text = f" lights={','.join(light_ids)}" if light_ids else ""
        lines.append(
            f"- **{change['status'].upper()}** "
            f"{alignment['participant']}/{alignment['kind']}"
            f"{light_text} anchor=`{anchor}` "
            f"occurrence={alignment['occurrence']}"
        )
        if change["status"] == "changed":
            for field, values in change["field_differences"].items():
                lines.append(
                    f"  - `{field}`: "
                    f"`{_inline_json(values['baseline'])}` -> "
                    f"`{_inline_json(values['candidate'])}`"
                )
        elif change["status"] == "inserted":
            lines.append(f"  - candidate: `{_inline_json(change['candidate'])}`")
        else:
            lines.append(f"  - baseline: `{_inline_json(change['baseline'])}`")
    return "\n".join(lines) + "\n"
