#!/usr/bin/env python3
"""Offline, fixed-fixture local LLM grounding gate for HomeHub research #366.

This is NOT a natural-language entailment verifier. It rejects arbitrary prose
and only accepts allowlisted, evidence-bound fact IDs, then renders those facts
using deterministic benchmark-owned text. Never controls HomeHub or downloads
or invokes models. The synthetic cases are NOT live operational evidence.

Run: python scripts/eval_local_llm_grounding.py --case incident-withheld --response response.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Fact:
    evidence_ids: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Case:
    evidence: dict[str, str]
    facts: dict[str, Fact]
    unknowns: dict[str, str]


CASES = {
    "incident-complete": Case(
        evidence={
            "I1": "Windows Sandbox failed with error 0xC03A0014.",
            "I2": "A test VHDX mounted read-only and dismounted successfully.",
            "I3": "The operator approved a bounded shutdown and completed Sandbox app Repair.",
            "I4": "A later Sandbox launch succeeded; guest identity and worktrees were verified.",
            "I5": "The underlying failure cause was not established.",
        },
        facts={
            "initial_failure": Fact(("I1",), "Windows Sandbox failed with error 0xC03A0014."),
            "vhdx_test_passed": Fact(
                ("I2",), "A specific test VHDX mounted read-only and dismounted successfully."
            ),
            "repair_completed": Fact(
                ("I3",), "The approved bounded shutdown and Sandbox app Repair completed."
            ),
            "recovery_confirmed": Fact(
                ("I4",), "A subsequent Sandbox launch and its mapped worktrees were verified."
            ),
            "cause_not_established": Fact(
                ("I5",), "The underlying failure cause was not established."
            ),
        },
        unknowns={"root_cause": "The underlying failure cause remains unknown."},
    ),
    "incident-withheld": Case(
        evidence={
            "I1": "Windows Sandbox failed with error 0xC03A0014.",
            "I2": "An ordinary test VHDX mounted successfully.",
            "I3": "A possible repair was proposed; no outcome is included.",
        },
        facts={
            "initial_failure": Fact(("I1",), "Windows Sandbox failed with error 0xC03A0014."),
            "vhdx_test_passed": Fact(("I2",), "A specific test VHDX mounted successfully."),
            "repair_proposed": Fact(
                ("I3",), "A repair was proposed, but its outcome was not supplied."
            ),
        },
        unknowns={
            "recovery_outcome": "The evidence does not establish whether recovery succeeded.",
            "root_cause": "The evidence does not establish the underlying cause.",
        },
    ),
}

MAX_RESPONSE_BYTES = 16_384


def validate(case_name: str, candidate: Any) -> tuple[list[str], str | None]:
    """Fail closed against fixed, human-reviewed benchmark expectations.

    Exact required fact IDs, evidence IDs, and unknown IDs prevent the false
    recovery outcome seen in the first local trial. This does not generalize to
    unreviewed incidents; new facts require a separately reviewed fixture.
    """
    if case_name not in CASES:
        raise ValueError("Unknown benchmark case")
    case = CASES[case_name]
    if type(candidate) is not dict:
        return ["Response must be a JSON object"], None
    if set(candidate) != {"case", "facts", "unknowns"}:
        return ["Response keys must be exactly case, facts, unknowns"], None
    errors: list[str] = []
    if candidate["case"] != case_name or type(candidate["case"]) is not str:
        errors.append("Case ID does not match the selected fixture")
    facts = candidate["facts"]
    if type(facts) is not list or len(facts) > 12:
        errors.append("facts must be a bounded array")
    else:
        seen: set[str] = set()
        for index, fact in enumerate(facts):
            if type(fact) is not dict or set(fact) != {"id", "evidence_ids"}:
                errors.append(f"Fact {index}: require exact id and evidence_ids keys")
                continue
            fact_id = fact["id"]
            ids = fact["evidence_ids"]
            if type(fact_id) is not str or not fact_id:
                errors.append(f"Fact {index}: invalid fact ID")
                continue
            if fact_id in seen:
                errors.append(f"Duplicate fact ID: {fact_id}")
            seen.add(fact_id)
            if fact_id not in case.facts:
                errors.append(f"Unsupported fact ID: {fact_id}")
                continue
            if type(ids) is not list or any(type(x) is not str for x in ids):
                errors.append(f"Fact {fact_id}: evidence_ids must be strings")
                continue
            expected = case.facts[fact_id].evidence_ids
            if len(ids) != len(set(ids)) or set(ids) != set(expected):
                errors.append(f"Fact {fact_id}: missing, unrelated, or invented evidence")
        missing = set(case.facts) - seen
        if missing:
            errors.append("Missing required facts: " + ", ".join(sorted(missing)))
    unknowns = candidate["unknowns"]
    if type(unknowns) is not list or any(type(x) is not str for x in unknowns):
        errors.append("unknowns must be an array of strings")
    elif len(unknowns) != len(set(unknowns)) or set(unknowns) != set(case.unknowns):
        errors.append("Unknowns must exactly match the benchmark's unresolved questions")
    if errors:
        return errors, None
    # No model-authored prose is emitted; thus answer/claim contradictions are
    # impossible within the accepted rendering contract, not 'detected' by NLP.
    lines = [case.facts[claim_id].text for claim_id in case.facts]
    lines.extend(case.unknowns[unknown_id] for unknown_id in case.unknowns)
    return [], " ".join(lines)


def load_response(path: Path) -> Any:
    """Read only a bounded JSON file. Never evaluate model text or parse CLI logs."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("Response file is missing, linked, or not regular")
    if path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ValueError("Response exceeds bounded input size")
    try:
        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
            obj: dict[str, Any] = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError("Duplicate JSON object key")
                obj[key] = value
            return obj

        return json.loads(
            path.read_text(encoding="utf-8-sig"), object_pairs_hook=reject_duplicate_keys
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Response is not valid standalone JSON ({type(exc).__name__})") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=sorted(CASES), required=True)
    parser.add_argument("--response", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        errors, summary = validate(args.case, load_response(args.response))
    except (OSError, ValueError) as exc:
        errors, summary = [str(exc)], None
    print(json.dumps(
        {"case": args.case, "passed": not errors, "errors": errors, "rendered": summary},
        sort_keys=True,
    ))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
