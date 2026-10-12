"""Offline and fail-closed test of the #366 reviewer-declared citation policy."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import local_llm_adjudication_366 as audit


def fixture() -> dict:
    return {
        "version": 1,
        "cases": [{
            "id": "doc-05", "source": "GitHub dated merge note",
            "provenance": "synthetic",
            "evidence": [
                {"id": "E1", "text": "The pull request was merged."},
                {"id": "E2", "text": "The merge commit is on master."},
                {"id": "E3", "text": "PR merge confirmed; no service started during it."},
            ],
            "probes": [
                {"id": "merged", "statement": "The PR was merged.",
                 "critical": False,
                 "gold": {"verdict": "supported", "evidence_ids": ["E1"]}},
                {"id": "currently-live",
                 "statement": "A service is running now.",
                 "critical": True,
                 "gold": {"verdict": "unknown", "evidence_ids": []}},
            ],
        }],
    }


def manifest(digest: str, *, reviewed: bool = True) -> dict:
    return {
        "version": 1, "fixture_sha256": digest,
        "review": {
            "status": "reviewed" if reviewed else "draft",
            "reviewer_kind": "human" if reviewed else "unreviewed",
            "reviewer_reference": (
                "https://example.org/verified-review-record"
                if reviewed else ""
            ),
        },
        "cases": [{
            "id": "doc-05",
            "source_url": "https://github.com/agatte/home-hub/issues/366",
            "source_scope": "dated_document",
            "probes": [{
                "id": "merged", "verdict": "supported",
                "minimal_citation_sets": [["E1"], ["E2"]],
                "permitted_additional_ids": ["E2", "E3"],
                "rationale": "Either positive merge statement is sufficient.",
            }, {
                "id": "currently-live", "verdict": "unknown",
                "minimal_citation_sets": [],
                "permitted_additional_ids": [],
                "rationale": "The merger's silence cannot prove current state.",
            }],
        }],
    }


def answer(*, extra: list[str] | None = None, current: str = "unknown") -> dict:
    return {
        "case": "doc-05",
        "answers": [
            {"probe_id": "merged", "verdict": "supported",
             "evidence_ids": ["E1"] + (extra or [])},
            {"probe_id": "currently-live", "verdict": current,
             "evidence_ids": [] if current == "unknown" else ["E3"]},
        ],
        "explanation": "One bounded dated review.",
    }


class AdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture_file = self.root / "fixture.json"
        self.manifest_file = self.root / "review.json"
        self.responses = self.root / "responses"
        self.responses.mkdir()
        self.write_fixture(fixture())
        self.write_manifest(manifest(self.digest()))
        self.write_response(answer())

    def write_fixture(self, obj: dict):
        self.fixture_file.write_text(
            json.dumps(obj, sort_keys=True), encoding="utf-8"
        )

    def digest(self) -> str:
        return hashlib.sha256(self.fixture_file.read_bytes()).hexdigest()

    def write_manifest(self, obj: dict):
        self.manifest_file.write_text(
            json.dumps(obj, sort_keys=True), encoding="utf-8"
        )

    def write_response(self, obj: dict):
        (self.responses / "doc-05.json").write_text(
            json.dumps(obj, sort_keys=True), encoding="utf-8"
        )

    def test_minimum_citation_permits_declared_alternative_and_extra(self):
        for refs in ([], ["E2"], ["E3"], ["E2", "E3"]):
            self.write_response(answer(extra=refs))
            report = audit.evaluate(
                self.fixture_file, self.manifest_file, self.responses
            )
            self.assertEqual(report["correct_verdicts_vs_declared"], 2)
            self.assertEqual(report["citation_matches_vs_declared"], 2)
            self.assertEqual(report["invalid_cases"], 0)
            self.assertFalse(report["requires_review_or_reconciliation"])
            self.assertFalse(report["source_truth_verified_by_software"])
            self.assertFalse(report["review_attestation_authenticity_verified"])

    def test_exact_original_scorer_unchanged_and_separate(self):
        from scripts.local_llm_holdout_366 import score_case
        candidate = answer(extra=["E2"])
        old = score_case(fixture()["cases"][0], candidate)
        self.assertTrue(old["valid"])
        self.assertEqual(old["correct_verdicts"], 2)
        self.assertEqual(old["correct_citations"], 1)
        new = audit.evaluate(
            self.fixture_file, self.manifest_file, self.responses
        )
        self.assertTrue(new["historical_gold_scores_changed"] is False)
        self.assertEqual(new["citation_matches_vs_declared"], 2)

    def test_unapproved_extra_citation_is_scored_not_repaired(self):
        m = manifest(self.digest())
        m["cases"][0]["probes"][0]["permitted_additional_ids"] = ["E2"]
        self.write_manifest(m)
        self.write_response(answer(extra=["E3"]))
        r = audit.evaluate(self.fixture_file, self.manifest_file, self.responses)
        self.assertEqual(r["correct_verdicts_vs_declared"], 2)
        self.assertEqual(r["citation_matches_vs_declared"], 1)
        self.assertIn("citations not in approved", str(r["cases"]))
        self.assertTrue(r["requires_review_or_reconciliation"])

    def test_draft_does_not_gain_review_status(self):
        self.write_manifest(manifest(self.digest(), reviewed=False))
        r = audit.evaluate(self.fixture_file, self.manifest_file, self.responses)
        self.assertTrue(r["requires_review_or_reconciliation"])
        self.assertEqual(r["review_status"], "draft")

    def test_false_human_review_claims_fail(self):
        m = manifest(self.digest())
        m["review"]["reviewer_kind"] = "unreviewed"
        self.write_manifest(m)
        with self.assertRaisesRegex(ValueError, "human attestation"):
            audit.evaluate(self.fixture_file, self.manifest_file)

    def test_gold_label_disagreement_is_explicit_reconciliation_gate(self):
        m = manifest(self.digest())
        p = m["cases"][0]["probes"][1]
        p.update({"verdict": "contradicted", "minimal_citation_sets": [["E3"]]})
        self.write_manifest(m)
        r = audit.evaluate(self.fixture_file, self.manifest_file)
        self.assertEqual(r["gold_disagreements_requiring_separate_review"],
                         ["doc-05/currently-live"])
        self.assertTrue(r["requires_review_or_reconciliation"])

    def test_fixture_byte_change_refuses_old_manifest(self):
        f = fixture()
        f["cases"][0]["evidence"][0]["text"] += " extra"
        self.write_fixture(f)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            audit.evaluate(self.fixture_file, self.manifest_file)

    def test_unknown_citations_or_minimum_are_refused(self):
        for field, invalid in (
            ("permitted_additional_ids", ["E2"]),
            ("minimal_citation_sets", [["E3"]]),
        ):
            m = manifest(self.digest())
            m["cases"][0]["probes"][1][field] = invalid
            self.write_manifest(m)
            with self.assertRaisesRegex(ValueError, "unknown cannot cite"):
                audit.evaluate(self.fixture_file, self.manifest_file)

    def test_malformed_review_status_is_cleanly_rejected(self):
        m = manifest(self.digest())
        m["review"]["status"] = []
        self.write_manifest(m)
        with self.assertRaisesRegex(ValueError, "invalid review status"):
            audit.evaluate(self.fixture_file, self.manifest_file)

    def test_malformed_source_scope_is_cleanly_rejected(self):
        m = manifest(self.digest())
        m["cases"][0]["source_scope"] = []
        self.write_manifest(m)
        with self.assertRaisesRegex(ValueError, "invalid source scope"):
            audit.evaluate(self.fixture_file, self.manifest_file)

    def test_missing_or_invented_citation_rejected_in_manifest(self):
        m = manifest(self.digest())
        m["cases"][0]["probes"][0]["minimal_citation_sets"] = [["E99"]]
        self.write_manifest(m)
        with self.assertRaisesRegex(ValueError, "missing evidence ID"):
            audit.evaluate(self.fixture_file, self.manifest_file)

    def test_duplicate_citation_alternative_is_rejected(self):
        m = manifest(self.digest())
        m["cases"][0]["probes"][0]["minimal_citation_sets"].append(["E1"])
        self.write_manifest(m)
        with self.assertRaisesRegex(ValueError, "duplicated alternative"):
            audit.evaluate(self.fixture_file, self.manifest_file)

    def test_duplicate_json_key_rejected(self):
        self.manifest_file.write_text(
            '{"version":1,"version":1}', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            audit.evaluate(self.fixture_file, self.manifest_file)

    def test_response_schema_error_has_zero_scoring_and_holds_gate(self):
        bad = answer()
        bad["answers"][0]["invented"] = "bad"
        self.write_response(bad)
        r = audit.evaluate(self.fixture_file, self.manifest_file, self.responses)
        self.assertEqual(r["valid_cases"], 0)
        self.assertEqual(r["invalid_cases"], 1)
        self.assertEqual(r["correct_verdicts_vs_declared"], 0)
        self.assertTrue(r["requires_review_or_reconciliation"])

    def test_critical_missing_verdict_not_reclassified_as_hallucination(self):
        self.write_response(answer(current="contradicted"))
        r = audit.evaluate(self.fixture_file, self.manifest_file, self.responses)
        self.assertEqual(r["critical_verdict_misses_vs_declared"], 1)
        self.assertEqual(r["correct_verdicts_vs_declared"], 1)

    def test_symlink_response_refused(self):
        link = self.root / "linked"
        try:
            link.symlink_to(self.responses, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("filesystem disallows symlinks")
        with self.assertRaisesRegex(ValueError, "regular directory"):
            audit.evaluate(self.fixture_file, self.manifest_file, link)

    def test_documented_cli_runs_on_existing_fixture_without_writes(self):
        script = Path(audit.__file__).resolve()
        result = subprocess.run(
            [sys.executable, "-B", str(script), "--fixtures",
             str(self.fixture_file), "--manifest", str(self.manifest_file),
             "--responses", str(self.responses)],
            cwd=script.parents[1], capture_output=True, text=True,
            timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["correct_verdicts_vs_declared"], 2)
        self.assertEqual(
            sorted(x.name for x in self.root.iterdir()),
            ["fixture.json", "responses", "review.json"],
        )

    def test_reordered_probe_or_case_is_rejected(self):
        m = manifest(self.digest())
        m["cases"][0]["probes"].reverse()
        self.write_manifest(m)
        with self.assertRaisesRegex(ValueError, "probe order/id"):
            audit.evaluate(self.fixture_file, self.manifest_file)


if __name__ == "__main__":
    unittest.main()
