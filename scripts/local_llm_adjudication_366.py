#!/usr/bin/env python3
"""HomeHub #366 offline *advisory* gold/citation adjudication guard.

This validates declarations and literal evidence IDs. It cannot infer truth,
authenticate reviewers, independently check linked sources, or authorize HomeHub
behavior. Frozen local_llm_holdout_366.py scores remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__:
    from scripts.local_llm_holdout_366 import (
        MAX_BYTES, MAX_RESPONSE_BYTES, VERDICTS, read_json,
        score_case, validate_fixtures,
    )
else:
    from local_llm_holdout_366 import (
        MAX_BYTES, MAX_RESPONSE_BYTES, VERDICTS, read_json,
        score_case, validate_fixtures,
    )

SCOPES = frozenset({"dated_document", "synthetic", "natural_capture"})
REQUIRED_MANIFEST = {"version", "fixture_sha256", "review", "cases"}
REVIEW_FIELDS = {"status", "reviewer_kind", "reviewer_reference"}
CASE_FIELDS = {"id", "source_url", "source_scope", "probes"}
PROBE_FIELDS = {
    "id", "verdict", "minimal_citation_sets", "permitted_additional_ids",
    "rationale",
}


def _exact(value: Any, expected: set[str], label: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(label + ": unexpected fields")


def _ids(value: Any, available: set[str], label: str) -> set[str]:
    if type(value) is not list or any(type(x) is not str for x in value):
        raise ValueError(label + ": expected evidence-ID list")
    if len(value) != len(set(value)) or not set(value) <= available:
        raise ValueError(label + ": repeated or missing evidence ID")
    return set(value)


def validate_manifest(manifest: Any, cases: list[dict[str, Any]],
                      source_sha256: str) -> dict[str, Any]:
    """Validate provenance declarations without blessing their semantics."""
    _exact(manifest, REQUIRED_MANIFEST, "manifest")
    if (type(manifest["version"]) is not int or manifest["version"] != 1
            or manifest["fixture_sha256"] != source_sha256):
        raise ValueError("manifest version or pinned fixture SHA-256 mismatch")
    review = manifest["review"]
    _exact(review, REVIEW_FIELDS, "review")
    if (type(review["status"]) is not str
            or review["status"] not in {"draft", "reviewed"}):
        raise ValueError("invalid review status")
    if (type(review["reviewer_kind"]) is not str
            or review["reviewer_kind"] not in {"unreviewed", "human"}):
        raise ValueError("invalid reviewer kind")
    reference = review["reviewer_reference"]
    if type(reference) is not str:
        raise ValueError("invalid reviewer reference")
    if review["status"] == "reviewed":
        if review["reviewer_kind"] != "human" or not reference.startswith("https://"):
            raise ValueError("reviewed requires a human attestation link")
    elif review["reviewer_kind"] != "unreviewed" or reference:
        raise ValueError("draft must not claim a reviewer")

    authored = manifest["cases"]
    if type(authored) is not list or len(authored) != len(cases):
        raise ValueError("manifest case count mismatch")
    indexed: dict[str, Any] = {}
    gold_mismatches: list[str] = []
    citation_alternatives = 0
    for case, document in zip(cases, authored):
        _exact(document, CASE_FIELDS, "manifest case")
        cid = case["id"]
        if document["id"] != cid:
            raise ValueError("manifest case order/id mismatch")
        url = document["source_url"]
        if type(url) is not str or not url.startswith("https://"):
            raise ValueError(cid + ": source link required")
        if (type(document["source_scope"]) is not str
                or document["source_scope"] not in SCOPES):
            raise ValueError(cid + ": invalid source scope")
        probes = document["probes"]
        if type(probes) is not list or len(probes) != len(case["probes"]):
            raise ValueError(cid + ": probe count mismatch")
        accepted: dict[str, Any] = {}
        available = {x["id"] for x in case["evidence"]}
        for authored_probe, declared in zip(case["probes"], probes):
            _exact(declared, PROBE_FIELDS, cid + " adjudication probe")
            pid = authored_probe["id"]
            if declared["id"] != pid:
                raise ValueError(cid + ": probe order/id mismatch")
            verdict = declared["verdict"]
            if type(verdict) is not str or verdict not in VERDICTS:
                raise ValueError(cid + "/" + pid + ": invalid verdict")
            reason = declared["rationale"]
            if type(reason) is not str or not reason.strip() or len(reason) > 1200:
                raise ValueError(cid + "/" + pid + ": bounded rationale required")
            minimum = declared["minimal_citation_sets"]
            if type(minimum) is not list:
                raise ValueError(cid + "/" + pid + ": minimum sets must be a list")
            extras = _ids(declared["permitted_additional_ids"], available,
                          cid + "/" + pid + " extras")
            groups: list[frozenset[str]] = []
            for items in minimum:
                refs = _ids(items, available, cid + "/" + pid + " minimum")
                if not refs:
                    raise ValueError(cid + "/" + pid + ": empty citation alternative")
                key = frozenset(refs)
                if key in groups:
                    raise ValueError(cid + "/" + pid + ": duplicated alternative")
                groups.append(key)
            if verdict == "unknown":
                if groups or extras:
                    raise ValueError(cid + "/" + pid + ": unknown cannot cite evidence")
            elif not groups:
                raise ValueError(cid + "/" + pid + ": cited verdict needs minimum")
            if len(groups) > 8:
                raise ValueError(cid + "/" + pid + ": too many alternatives")
            # Every supplemental ref must be explicitly named and source-reviewed.
            citation_alternatives += len(groups)
            accepted[pid] = {
                "verdict": verdict, "minimum": groups, "extras": extras,
            }
            if verdict != authored_probe["gold"]["verdict"]:
                gold_mismatches.append(cid + "/" + pid)
        indexed[cid] = accepted
    return {
        "cases": indexed, "review_status": review["status"],
        "gold_disagreements": gold_mismatches,
        "citation_alternatives": citation_alternatives,
    }


def citation_admissible(answer: dict[str, Any], entry: dict[str, Any]) -> bool:
    """Accept only a reviewed minimum plus explicitly permitted extras."""
    actual = set(answer["evidence_ids"])
    if entry["verdict"] == "unknown":
        return not actual
    return any(group <= actual and actual <= group | entry["extras"]
               for group in entry["minimum"])


def evaluate(fixture: Path, manifest_file: Path,
             responses: Path | None = None) -> dict[str, Any]:
    if fixture.is_symlink() or not fixture.is_file():
        raise ValueError("fixture must be an existing regular file")
    if fixture.stat().st_size > MAX_BYTES:
        raise ValueError("fixture exceeds size bound")
    sha = hashlib.sha256(fixture.read_bytes()).hexdigest()
    cases = validate_fixtures(read_json(fixture, MAX_BYTES))
    manifest = read_json(manifest_file, MAX_BYTES)
    policy = validate_manifest(manifest, cases, sha)
    details: list[dict[str, Any]] = []
    valid = correct = citations = critical_misses = 0
    malformed = 0
    if responses is not None:
        if responses.is_symlink() or not responses.is_dir():
            raise ValueError("response path must be a regular directory")
        for case in cases:
            cid = case["id"]
            try:
                response = read_json(responses / (cid + ".json"),
                                     MAX_RESPONSE_BYTES)
                structure = score_case(case, response)
                if not structure["valid"]:
                    details.append({
                        "case": cid, "valid": False, "errors": structure["errors"],
                    })
                    malformed += 1
                    continue
            except (ValueError, OSError) as exc:
                details.append({"case": cid, "valid": False, "errors": [str(exc)]})
                malformed += 1
                continue
            valid += 1
            errors: list[str] = []
            by_id = {a["probe_id"]: a for a in response["answers"]}
            for probe in case["probes"]:
                pid = probe["id"]
                answer = by_id[pid]
                entry = policy["cases"][cid][pid]
                if answer["verdict"] != entry["verdict"]:
                    errors.append(pid + ": verdict mismatch")
                    if probe["critical"]:
                        critical_misses += 1
                else:
                    correct += 1
                    if citation_admissible(answer, entry):
                        citations += 1
                    else:
                        errors.append(pid + ": citations not in approved alternatives")
            details.append({"case": cid, "valid": True, "errors": errors})
    total_probes = sum(len(case["probes"]) for case in cases)
    blocked = (
        policy["review_status"] != "reviewed"
        or bool(policy["gold_disagreements"])
        or malformed > 0
        or (responses is not None
            and (correct != total_probes or citations != total_probes))
    )
    return {
        "kind": "offline_advisory_adjudication_only",
        "fixture_sha256": sha,
        "review_status": policy["review_status"],
        "review_attestation_authenticity_verified": False,
        "source_truth_verified_by_software": False,
        "model_executed": False,
        "device_or_production_authority": False,
        "source_review_authentication_not_implemented": True,
        "historical_gold_scores_changed": False,
        "total_probes": total_probes,
        "gold_disagreements_requiring_separate_review": policy["gold_disagreements"],
        "citation_alternatives_declared": policy["citation_alternatives"],
        "requires_review_or_reconciliation": blocked,
        "responses_inspected": responses is not None,
        "valid_cases": valid, "invalid_cases": malformed,
        "correct_verdicts_vs_declared": correct,
        "citation_matches_vs_declared": citations,
        "critical_verdict_misses_vs_declared": critical_misses,
        "cases": details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--responses", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.fixtures, args.manifest, args.responses)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result["requires_review_or_reconciliation"] else 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
