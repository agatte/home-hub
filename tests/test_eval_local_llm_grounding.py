"""Offline fail-closed golden-fixture checks for local LLM research #366."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import eval_local_llm_grounding as eval_llm


def accepted(case_name: str) -> dict:
    case = eval_llm.CASES[case_name]
    return {
        "case": case_name,
        "facts": [
            {"id": key, "evidence_ids": list(fact.evidence_ids)}
            for key, fact in case.facts.items()
        ],
        "unknowns": list(case.unknowns),
    }


class LocalLLMGroundingTests(unittest.TestCase):
    def test_complete_case_passes_with_deterministic_rendering(self):
        errors, rendered = eval_llm.validate("incident-complete", accepted("incident-complete"))
        self.assertEqual(errors, [])
        self.assertIn("subsequent Sandbox launch", rendered)
        self.assertIn("underlying failure cause", rendered)

    def test_withheld_case_passes_but_never_claims_failed_recovery(self):
        errors, rendered = eval_llm.validate("incident-withheld", accepted("incident-withheld"))
        self.assertEqual(errors, [])
        self.assertIn("does not establish whether recovery succeeded", rendered)
        self.assertNotIn("recovery was not successful", rendered)

    def test_false_failure_citing_initial_error_is_rejected(self):
        response = accepted("incident-withheld")
        response["facts"].append({"id": "recovery_failed", "evidence_ids": ["I1"]})
        errors, _ = eval_llm.validate("incident-withheld", response)
        self.assertTrue(any("Unsupported fact ID: recovery_failed" in x for x in errors))

    def test_false_recovery_success_when_outcome_withheld_rejected(self):
        response = accepted("incident-withheld")
        response["facts"].append({"id": "recovery_confirmed", "evidence_ids": ["I1"]})
        errors, _ = eval_llm.validate("incident-withheld", response)
        self.assertTrue(any("Unsupported fact ID" in x for x in errors))

    def test_vhdx_specific_diagnostic_cannot_prove_general_system_function(self):
        response = accepted("incident-withheld")
        response["facts"].append({"id": "all_virtual_disks_work", "evidence_ids": ["I2"]})
        errors, _ = eval_llm.validate("incident-withheld", response)
        self.assertTrue(any("Unsupported fact ID" in x for x in errors))

    def test_wrong_citation_even_if_known_id_is_rejected(self):
        response = accepted("incident-complete")
        response["facts"][-2]["evidence_ids"] = ["I1"]
        errors, _ = eval_llm.validate("incident-complete", response)
        self.assertTrue(any("missing, unrelated, or invented evidence" in x for x in errors))

    def test_fabricated_citation_is_rejected(self):
        response = accepted("incident-complete")
        response["facts"][0]["evidence_ids"] = ["I999"]
        self.assertTrue(eval_llm.validate("incident-complete", response)[0])

    def test_missing_required_claim_is_rejected_not_silently_accepted(self):
        response = accepted("incident-complete")
        response["facts"] = response["facts"][:3]
        errors, _ = eval_llm.validate("incident-complete", response)
        self.assertTrue(any("Missing required facts" in x for x in errors))

    def test_unknown_when_recovery_confirmed_is_rejected(self):
        response = accepted("incident-complete")
        response["unknowns"].append("recovery_outcome")
        self.assertTrue(eval_llm.validate("incident-complete", response)[0])

    def test_claimed_known_cause_rejected_without_source(self):
        response = accepted("incident-withheld")
        response["facts"].append({"id": "root_cause_known", "evidence_ids": ["I1"]})
        self.assertTrue(eval_llm.validate("incident-withheld", response)[0])

    def test_unknowns_missing_when_evidence_withheld_are_rejected(self):
        response = accepted("incident-withheld")
        response["unknowns"] = ["root_cause"]
        self.assertTrue(eval_llm.validate("incident-withheld", response)[0])

    def test_duplicate_fact_and_duplicate_evidence_rejected(self):
        response = accepted("incident-complete")
        response["facts"].append(copy.deepcopy(response["facts"][0]))
        self.assertTrue(eval_llm.validate("incident-complete", response)[0])
        response = accepted("incident-complete")
        response["facts"][0]["evidence_ids"] = ["I1", "I1"]
        self.assertTrue(eval_llm.validate("incident-complete", response)[0])

    def test_reject_free_prose_answer_claim_contradiction_instead_of_guessing(self):
        # Older 512-token run emitted these conflicting statements. Arbitrary
        # prose cannot be reliably entailed via citation-ID membership alone.
        old = {
            "answer": "Sandbox recovery status is unknown.",
            "claims": [
                {"text": "Sandbox recovery was not successful.", "evidence_ids": ["I1"]}
            ],
            "unknowns": ["Sandbox recovery outcome"],
        }
        errors, rendered = eval_llm.validate("incident-withheld", old)
        self.assertTrue(errors)
        self.assertIsNone(rendered)

    def test_wrong_case_and_extra_fields_rejected(self):
        response = accepted("incident-withheld")
        response["case"] = "incident-complete"
        self.assertTrue(eval_llm.validate("incident-withheld", response)[0])
        response = accepted("incident-withheld")
        response["answer"] = "Unexpected free text"
        self.assertTrue(eval_llm.validate("incident-withheld", response)[0])

    def test_invalid_types_and_excessive_facts_rejected(self):
        for bad in (None, [], 2, "hello"):
            self.assertTrue(eval_llm.validate("incident-complete", bad)[0])
        response = accepted("incident-complete")
        response["facts"] = [None] * 13
        self.assertTrue(eval_llm.validate("incident-complete", response)[0])

    def test_cli_good_case_is_read_only_and_returns_rendered_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            response = root / "good.json"
            response.write_text(json.dumps(accepted("incident-complete")), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                rc = eval_llm.main(
                    ["--case", "incident-complete", "--response", str(response)]
                )
            report = json.loads(stream.getvalue())
            self.assertEqual(rc, 0)
            self.assertTrue(report["passed"])
            self.assertEqual(report["errors"], [])
            self.assertIn("subsequent Sandbox launch", report["rendered"])
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["good.json"])

    def test_cli_bad_case_exits_nonzero_without_emitting_model_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = Path(tmp) / "bad.json"
            response.write_text(json.dumps({"answer": "recovered"}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                rc = eval_llm.main(["--case", "incident-withheld", "--response", str(response)])
            report = json.loads(stream.getvalue())
            self.assertEqual(rc, 1)
            self.assertFalse(report["passed"])
            self.assertIsNone(report["rendered"])

    def test_cli_does_not_parse_banner_or_truncated_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = Path(tmp) / "log.txt"
            response.write_text("Loading model...\n{ \"answer\": \"unfinished", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                rc = eval_llm.main(["--case", "incident-withheld", "--response", str(response)])
            self.assertEqual(rc, 1)
            self.assertIn("not valid standalone JSON", stream.getvalue())

    def test_oversized_input_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = Path(tmp) / "big.json"
            response.write_text(" " * (eval_llm.MAX_RESPONSE_BYTES + 1), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exceeds bounded"):
                eval_llm.load_response(response)

    def test_duplicate_json_object_keys_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = Path(tmp) / "ambiguous.json"
            response.write_text(
                '{"case":"incident-withheld","case":"incident-complete"}', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "Duplicate JSON object key"):
                eval_llm.load_response(response)

    def test_fixture_evidence_covers_every_approved_fact(self):
        for case in eval_llm.CASES.values():
            for fact in case.facts.values():
                self.assertTrue(set(fact.evidence_ids) <= set(case.evidence))
            self.assertEqual(len(case.evidence), len(set(case.evidence)))


if __name__ == "__main__":
    unittest.main()
