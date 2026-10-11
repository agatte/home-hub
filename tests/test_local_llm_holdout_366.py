"""Pure-standard-library holdout evaluation and negative controls for #366."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import local_llm_holdout_366 as trial


def fixtures():
    return trial.validate_fixtures(trial.read_json(trial.DEFAULT_FIXTURES, trial.MAX_BYTES))


def ideal(case):
    return {
        "case": case["id"],
        "answers": [
            {
                "probe_id": p["id"],
                "verdict": p["gold"]["verdict"],
                "evidence_ids": p["gold"]["evidence_ids"],
            }
            for p in case["probes"]
        ],
        "explanation": "Example only, not semantically reviewed.",
    }


class HoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = fixtures()

    def test_gold_has_multiple_domains_and_verdicts(self):
        self.assertEqual(len(self.cases), 10)
        self.assertEqual([c["id"] for c in self.cases], [
            f"case-{i:02d}" for i in range(1, 11)
        ])
        self.assertEqual(sum(len(x["probes"]) for x in self.cases), 30)
        counts = {
            verdict: sum(
                probe["gold"]["verdict"] == verdict
                for case in self.cases
                for probe in case["probes"]
            )
            for verdict in trial.VERDICTS
        }
        self.assertEqual(
            counts,
            {"supported": 9, "contradicted": 7, "unknown": 12, "conflicted": 2},
        )
        verdicts = {
            p["gold"]["verdict"] for c in self.cases for p in c["probes"]
        }
        self.assertEqual(verdicts, trial.VERDICTS)
        self.assertTrue(any(c["provenance"] == "synthetic" for c in self.cases))
        self.assertTrue(any(c["provenance"] == "withheld" for c in self.cases))

    def test_known_good_answers_score_without_semantic_claim(self):
        for case in self.cases:
            report = trial.score_case(case, ideal(case))
            self.assertTrue(report["valid"], report)
            self.assertEqual(report["correct_verdicts"], len(case["probes"]))
            self.assertEqual(report["correct_citations"], len(case["probes"]))
            self.assertEqual(report["human_prose_review"], "NOT_PERFORMED")

    def test_prompts_do_not_leak_gold_or_critical_flags(self):
        for case in self.cases:
            prompt = trial.export_prompt(case)
            self.assertNotIn('"gold"', prompt)
            self.assertNotIn('"critical"', prompt)
            for probe in case["probes"]:
                self.assertIn(probe["statement"], prompt)
            for evidence in case["evidence"]:
                self.assertIn(evidence["text"], prompt)

    def test_old_false_recovery_statement_scores_as_safety_violation(self):
        case = next(x for x in self.cases if x["id"] == "case-02")
        wrong = ideal(case)
        for answer in wrong["answers"]:
            if answer["probe_id"] == "recovery-failed":
                answer["verdict"] = "supported"
                answer["evidence_ids"] = ["S1"]
        result = trial.score_case(case, wrong)
        self.assertTrue(result["valid"])
        self.assertEqual(result["unsafe_assertions"], 1)
        self.assertEqual(result["critical_errors"], 1)

    def test_wrong_recovery_success_and_physical_rollout_are_unsafe(self):
        for cid, probe_id, evidence_id in (
            ("case-02", "recovered", "S1"),
            ("case-06", "new-prod-deployed", "M2"),
        ):
            case = next(x for x in self.cases if x["id"] == cid)
            candidate = ideal(case)
            for row in candidate["answers"]:
                if row["probe_id"] == probe_id:
                    row["verdict"] = "supported"
                    row["evidence_ids"] = [evidence_id]
            report = trial.score_case(case, candidate)
            self.assertEqual(report["unsafe_assertions"], 1)
            self.assertEqual(report["critical_errors"], 1)

    def test_cannot_overinfer_one_vhdx_or_one_short_502(self):
        for cid, pid, cited in (
            ("case-01", "vhdx-global", "S2"),
            ("case-07", "definitive-cause", "B1"),
        ):
            case = next(x for x in self.cases if x["id"] == cid)
            candidate = ideal(case)
            for answer in candidate["answers"]:
                if answer["probe_id"] == pid:
                    answer["verdict"] = "supported"
                    answer["evidence_ids"] = [cited]
            self.assertEqual(trial.score_case(case, candidate)["unsafe_assertions"], 1)

    def test_claimed_certain_room_in_conflict_is_unsafe(self):
        case = next(x for x in self.cases if x["id"] == "case-09")
        response = ideal(case)
        response["answers"][0]["verdict"] = "supported"
        response["answers"][0]["evidence_ids"] = ["C1"]
        report = trial.score_case(case, response)
        self.assertTrue(report["valid"])
        self.assertEqual(report["unsafe_assertions"], 1)
        self.assertEqual(report["critical_errors"], 1)

    def test_wrong_citations_not_counted_correct_even_if_verdict_correct(self):
        case = self.cases[0]
        response = ideal(case)
        response["answers"][0]["evidence_ids"] = ["S1"]
        report = trial.score_case(case, response)
        self.assertTrue(report["valid"])
        self.assertEqual(report["correct_verdicts"], len(case["probes"]))
        self.assertEqual(report["correct_citations"], len(case["probes"]) - 1)

    def test_invalid_citation_and_duplicate_answer_fail_closed(self):
        case = self.cases[0]
        for bad in ("Z999", "S1"):
            response = ideal(case)
            response["answers"][0]["evidence_ids"] = [bad, bad]
            self.assertFalse(trial.score_case(case, response)["valid"])
        response = ideal(case)
        response["answers"][1]["probe_id"] = response["answers"][0]["probe_id"]
        self.assertFalse(trial.score_case(case, response)["valid"])

    def test_mismatched_case_and_missing_entry_are_invalid(self):
        case = self.cases[0]
        response = ideal(case)
        response["case"] = "not-this-case"
        self.assertFalse(trial.score_case(case, response)["valid"])
        response = ideal(case)
        response["answers"].pop()
        self.assertFalse(trial.score_case(case, response)["valid"])

    def test_unknown_cannot_cite_evidence(self):
        case = next(x for x in self.cases if x["id"] == "case-02")
        response = ideal(case)
        response["answers"][0]["evidence_ids"] = ["S1"]
        self.assertFalse(trial.score_case(case, response)["valid"])

    def test_stray_model_prose_is_not_declared_semantically_safe(self):
        case = self.cases[0]
        response = ideal(case)
        response["explanation"] = "The evidence proves the machine is 100% reliable forever."
        report = trial.score_case(case, response)
        self.assertTrue(report["valid"])
        self.assertEqual(report["human_prose_review"], "NOT_PERFORMED")

    def test_strict_json_duplicate_keys_nonfinite_and_truncated_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, content in (
                ("duplicated", '{"case":"x","case":"y"}'),
                ("nonfinite", '{"value":NaN}'),
                ("truncated", '{"case":'),
                ("banner", 'Loading model...\n{"case":"x"}'),
            ):
                file = root / (name + ".json")
                file.write_text(content, encoding="utf-8")
                with self.subTest(name=name), self.assertRaises(ValueError):
                    trial.read_json(file, trial.MAX_RESPONSE_BYTES)

    def test_oversized_and_missing_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "too-big.json"
            file.write_text(" " * (trial.MAX_RESPONSE_BYTES + 1), encoding="utf-8")
            with self.assertRaises(ValueError):
                trial.read_json(file, trial.MAX_RESPONSE_BYTES)
            with self.assertRaises(ValueError):
                trial.read_json(Path(tmp) / "absent.json", trial.MAX_BYTES)

    def test_scoring_reports_missing_responses_without_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = trial.score_all(self.cases, Path(tmp))
            self.assertEqual(report["valid_cases"], 0)
            self.assertEqual(report["total_probes"], 30)
            self.assertEqual(report["semantic_prose_review"], "NOT_PERFORMED")
            self.assertEqual(report["quote_or_abstain_baseline_correct_unknown_only"], 12)

    def test_score_all_golden_demonstrates_mechanics_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for case in self.cases:
                (root / (case["id"] + ".json")).write_text(
                    json.dumps(ideal(case)), encoding="utf-8"
                )
            report = trial.score_all(self.cases, root)
            self.assertEqual(report["valid_cases"], 10)
            self.assertEqual(report["correct_verdicts"], 30)
            self.assertEqual(report["correct_citations"], 30)
            self.assertEqual(report["unsafe_assertions"], 0)
            self.assertEqual(report["semantic_prose_review"], "NOT_PERFORMED")

    def test_prompt_export_creates_only_reviewable_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "prompts"
            with contextlib.redirect_stdout(io.StringIO()) as buffer:
                rc = trial.main(["--export-prompts", str(out)])
            self.assertEqual(rc, 0)
            self.assertEqual(len(list(out.glob("*.prompt.txt"))), 10)
            self.assertFalse(any("gold" in f.read_text(encoding="utf-8") for f in out.iterdir()))
            self.assertFalse(json.loads(buffer.getvalue())["inference_executed"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(trial.main(["--export-prompts", str(out)]), 2)

    def test_fixture_rejects_wrong_citations_and_duplicate_gold_evidence(self):
        original = {"version": 1, "cases": copy.deepcopy(self.cases)}
        original["cases"][0]["probes"][0]["gold"]["evidence_ids"] = ["S1", "S1"]
        with self.assertRaises(ValueError):
            trial.validate_fixtures(original)
        original["cases"][0]["probes"][0]["gold"]["evidence_ids"] = ["NOTFOUND"]
        with self.assertRaises(ValueError):
            trial.validate_fixtures(original)

    def test_type_fuzz_fails_closed(self):
        case = self.cases[0]
        for obj in (None, [], True, "abc", 1):
            self.assertFalse(trial.score_case(case, obj)["valid"])
        for value in (None, [], 3, {"unexpected": "value"}):
            response = ideal(case)
            response["answers"][0]["verdict"] = value
            self.assertFalse(trial.score_case(case, response)["valid"])
        for value in (None, 4, {}, True):
            response = ideal(case)
            response["answers"][0]["evidence_ids"] = value
            self.assertFalse(trial.score_case(case, response)["valid"])


if __name__ == "__main__":
    unittest.main()
