#!/usr/bin/env python3
"""Gold-blind, source-quoting reference for the HomeHub #366 offline benchmark.

This deliberately cannot infer entailment from arbitrary evidence prose. It
copies the supplied evidence verbatim and abstains on all semantic probes.
Only the separate benchmark scorer may access gold labels for assessment.
No model, network, backend, HomeHub, or device access is provided.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__:
    from scripts.local_llm_holdout_366 import (
        DEFAULT_FIXTURES,
        MAX_BYTES,
        read_json,
        score_all,
        validate_fixtures,
    )
else:
    from local_llm_holdout_366 import (
        DEFAULT_FIXTURES,
        MAX_BYTES,
        read_json,
        score_all,
        validate_fixtures,
    )

BASELINE_POLICY = "verbatim_evidence_and_explicit_abstention_v1"


def gold_blind_view(case: dict[str, Any]) -> dict[str, Any]:
    """Select only public input fields, not gold, critical flags, or outcomes."""
    return {
        "id": case["id"],
        "source": case["source"],
        "evidence": [
            {"id": evidence["id"], "text": evidence["text"]}
            for evidence in case["evidence"]
        ],
        "probes": [
            {"id": probe["id"], "statement": probe["statement"]}
            for probe in case["probes"]
        ],
    }


def build_answer(case: dict[str, Any]) -> dict[str, Any]:
    """Match model response shape while declining unproved semantic judgment."""
    return {
        "case": case["id"],
        "answers": [
            {"probe_id": p["id"], "verdict": "unknown", "evidence_ids": []}
            for p in case["probes"]
        ],
        "explanation": "",
    }


def build_evidence_cards(case: dict[str, Any]) -> dict[str, Any]:
    """A faithful transcript with named source provenance, not a verdict."""
    return {
        "case": case["id"],
        "source": case["source"],
        "kind": "verbatim_evidence_only",
        "asserts_no_inferred_state": True,
        "cards": [
            {"evidence_id": e["id"], "source": case["source"], "quote": e["text"]}
            for e in case["evidence"]
        ],
        "unassessed_probes": [
            {"probe_id": p["id"], "statement": p["statement"]}
            for p in case["probes"]
        ],
    }


def make_plain_report(cards: dict[str, Any]) -> str:
    """Explicitly distinguish copied source content from inferred conclusions."""
    lines = [
        "HomeHub #366 evidence card: " + cards["case"],
        "Source label: " + cards["source"],
        "SOURCE-QUOTED MATERIAL ONLY: not independently verified live evidence.",
        "No physical room, house state, cause, device action or deployment inferred.",
        "",
        "Supplied evidence (verbatim, ID-tagged):",
    ]
    for card in cards["cards"]:
        # Preserve verbatim quote in JSON cards; make text display one line per
        # item, without interpreting any text as a command or markup.
        text = card["quote"].replace("\r", "\\r").replace("\n", "\\n")
        lines.append("[" + card["evidence_id"] + "] " + text)
    lines += [
        "",
        "Questions left explicitly unanswered (these are not findings):",
    ]
    for probe in cards["unassessed_probes"]:
        text = probe["statement"].replace("\r", "\\r").replace("\n", "\\n")
        lines.append("[" + probe["probe_id"] + "] " + text)
    return "\n".join(lines) + "\n"


def run(fixtures_path: Path, output_dir: Path) -> dict[str, Any]:
    # Refuse an existing target before any writes. No broad deletion/overwrite.
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("target already exists; refusing overwrite")
    dataset = read_json(fixtures_path, MAX_BYTES)
    cases = validate_fixtures(dataset)
    filtered = [gold_blind_view(case) for case in cases]

    output_dir.mkdir(parents=False, exist_ok=False)
    answers_dir = output_dir / "answers"
    cards_dir = output_dir / "evidence"
    answers_dir.mkdir()
    cards_dir.mkdir()

    for case in filtered:
        name = case["id"]
        answer = build_answer(case)
        cards = build_evidence_cards(case)
        (answers_dir / (name + ".json")).write_text(
            json.dumps(answer, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        (cards_dir / (name + ".json")).write_text(
            json.dumps(cards, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        (cards_dir / (name + ".txt")).write_text(
            make_plain_report(cards), encoding="utf-8"
        )

    # Scoring is explicitly separated from generating baseline answers.
    grades = score_all(cases, answers_dir)
    return {
        "status": "offline_comparator_only",
        "policy": BASELINE_POLICY,
        "cases": len(filtered),
        "probes": grades["total_probes"],
        "verdicts_correct": grades["correct_verdicts"],
        "verdicts_and_citations_correct": grades["correct_citations"],
        "valid_cases": grades["valid_cases"],
        "unsupported_affirmative_claims": grades["unsafe_assertions"],
        "critical_misses": grades["critical_errors"],
        "source_quotes": sum(len(case["evidence"]) for case in filtered),
        "probes_abstained": sum(len(case["probes"]) for case in filtered),
        "human_prose_review": "NOT_APPLICABLE_VERBATIM_QUOTES_ONLY",
        "model_executed": False,
        "live_evidence_retrieved": False,
        "gold_used_in_prediction": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.fixtures, args.output)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
