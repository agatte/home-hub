"""Deterministic semantic trace primitives for navigation-v1 replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

TRACE_VERSION = 1
TraceKind = Literal[
    "FACT",
    "DERIVED_DECISION",
    "PROPOSAL",
    "SUPPRESSION",
    "REQUEST",
    "SIMULATED_RESULT",
]
_GATE_STATES = frozenset({"passed", "blocked", "not_evaluated", "unknown"})


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("trace datetimes must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonicalize(value: Any) -> Any:
    """Convert replay state to JSON-safe values with deterministic ordering."""

    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Enum):
        return canonicalize(value.value)
    if is_dataclass(value):
        return canonicalize(asdict(value))
    if isinstance(value, dict):
        return {
            str(key): canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        items = [canonicalize(item) for item in value]
        return sorted(items, key=_canonical_json)
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if value is None or type(value) in (bool, int, float, str):
        return value
    raise TypeError(f"unsupported trace value type: {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def state_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def state_delta(before: Any, after: Any) -> Any:
    """Return a deterministic structural delta without inventing missing state."""

    before = canonicalize(before)
    after = canonicalize(after)
    if before == after:
        return {}
    if isinstance(before, dict) and isinstance(after, dict):
        delta: dict[str, Any] = {}
        for key in sorted(set(before) | set(after)):
            if key not in before:
                delta[key] = {"before": {"status": "absent"}, "after": after[key]}
            elif key not in after:
                delta[key] = {"before": before[key], "after": {"status": "absent"}}
            else:
                nested = state_delta(before[key], after[key])
                if nested != {}:
                    delta[key] = nested
        return delta
    return {"before": before, "after": after}


@dataclass(frozen=True)
class TraceContext:
    dispatch_sequence: int | None
    cause_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class ReplayTrace:
    """Append-only deterministic semantic trace for one validated replay."""

    def __init__(
        self,
        *,
        bundle_id: str,
        profile_id: str,
        backend_commit: str,
        policy_digest: str,
        manifest_sha256: str,
        synthetic_contract: bool,
    ) -> None:
        identity = {
            "bundle_id": bundle_id,
            "profile_id": profile_id,
            "backend_commit": backend_commit,
            "policy_digest": policy_digest,
            "manifest_sha256": manifest_sha256,
        }
        self.run_id = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:24]
        self.certainty = (
            "synthetic_contract" if synthetic_contract else "current_code_interpretation"
        )
        self.records: list[dict[str, Any]] = []

    def record(
        self,
        *,
        virtual_utc: datetime,
        mono_ns: int,
        participant: str,
        kind: TraceKind,
        context: TraceContext,
        state_before: Any,
        state_after: Any,
        decision: Any = None,
        reason_codes: tuple[str, ...] | list[str] = (),
        gates: dict[str, Any] | None = None,
        request_id: str | None = None,
        owner: str | None = None,
        light_ids: tuple[str, ...] | list[str] = (),
        payload: Any = None,
        result: Any = None,
    ) -> dict[str, Any]:
        if gates is None:
            gates = {}
        for name, gate in gates.items():
            if not isinstance(gate, dict) or gate.get("status") not in _GATE_STATES:
                raise ValueError(f"trace gate {name!r} has invalid status")

        record = {
            "trace_version": TRACE_VERSION,
            "run_id": self.run_id,
            "record_id": f"r{len(self.records) + 1:06d}",
            "virtual_utc": _iso(virtual_utc),
            "mono_ns": mono_ns,
            "dispatch_sequence": context.dispatch_sequence,
            "participant": participant,
            "kind": kind,
            "cause_ids": list(context.cause_ids),
            "evidence_ids": list(context.evidence_ids),
            "state_before_digest": state_digest(state_before),
            "relevant_state_delta": state_delta(state_before, state_after),
            "decision": canonicalize(decision),
            "reason_codes": list(reason_codes),
            "gates": canonicalize(gates),
            "request_id": request_id,
            "owner": owner,
            "light_ids": sorted(str(light_id) for light_id in light_ids),
            "payload": canonicalize(payload),
            "result": canonicalize(result),
            "certainty": self.certainty,
        }
        self.records.append(record)
        return record

    def to_jsonl(self) -> str:
        if not self.records:
            return ""
        return "".join(_canonical_json(record) + "\n" for record in self.records)
