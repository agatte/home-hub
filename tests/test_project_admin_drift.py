"""Deterministic, network-free tests for the read-only Project Admin drift report."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts import check_project_admin_drift as drift


MAP = """# HomeHub Execution Map
> **Last reconciled:** 2026-10-08 (doc only)
## Current gate-aware routing (2026-10-08)
| Work / owner | Current gate | Next action |
|---|---|---|
| [#337](https://github.com/agatte/home-hub/issues/337) | Open implementation | Review |
| [#334](https://github.com/agatte/home-hub/issues/334) | Physical test | Wait |
## Implementation packet references
### #246 — persistence (closed implementation)
"""

HUB = """# Project Admin
> GitHub Projects board existence/configuration has **not** been verified
[#334](https://github.com/agatte/home-hub/issues/334)
"""

ISSUES = {
    337: {"number": 337, "state": "open", "title": "Assisted playback"},
    334: {
        "number": 334,
        "state": "open",
        "title": "Post-deploy physical acceptance: Blue Yeti recovery",
    },
    246: {"number": 246, "state": "closed", "title": "Manual light ownership"},
}


class ProjectAdminDriftTests(unittest.TestCase):
    def test_current_good_state_has_no_drift(self):
        errors, notices = drift.audit(HUB, MAP, ISSUES, date(2026, 10, 8))
        self.assertEqual(errors, [])
        self.assertEqual(len(notices), 1)
        self.assertIn("unverified", notices[0])

    def test_optional_current_gate_check_accepts_fully_specified_routes(self):
        self.assertEqual(drift.check_current_gate_rows(MAP, ISSUES), [])

    def test_optional_current_gate_check_reports_unlinked_owner_and_missing_fields(self):
        route = MAP.replace(
            "| [#337](https://github.com/agatte/home-hub/issues/337) | Open implementation | Review |",
            "| Unassigned | TBD | see issue |",
        )
        self.assertEqual(
            drift.check_current_gate_rows(route, ISSUES),
            [
                "Current routing row 1: missing owning issue link in Work / owner",
                "Current routing row 1: missing concrete current gate",
                "Current routing row 1: missing concrete next step",
            ],
        )

    def test_optional_current_gate_check_flags_only_explicit_current_closed_claim(self):
        route = MAP.replace("| Open implementation | Review |", "| **CLOSED** | Review |")
        self.assertEqual(
            drift.check_current_gate_rows(route, ISSUES),
            ["Current routing row 1: current gate claims closed, but owning issue #337 is open"],
        )
        route = MAP.replace(
            "| Open implementation | Review |",
            "| IMPLEMENTATION_COMPLETE | Review closed #334 evidence separately |",
        )
        self.assertEqual(drift.check_current_gate_rows(route, ISSUES), [])
        self.assertEqual(
            drift.check_current_gate_rows(
                route + "\n## Dated audit\n| past | CLOSED | TBD |", ISSUES
            ),
            [],
        )

    def test_optional_current_gate_check_handles_malformed_and_empty_rows(self):
        route = MAP.replace(
            "| [#337](https://github.com/agatte/home-hub/issues/337) | Open implementation | Review |",
            "| [#337](https://github.com/agatte/home-hub/issues/337) | Review |",
        )
        self.assertEqual(
            drift.check_current_gate_rows(route, ISSUES),
            ["Current routing row 1: expected three columns, found 2"],
        )
        empty = MAP.split("| [#337]", 1)[0] + "## Implementation packet references\n"
        self.assertEqual(
            drift.check_current_gate_rows(empty, ISSUES),
            ["Current routing table has no data rows"],
        )

    def test_current_gate_option_is_advisory_by_default_and_strict_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "EXECUTION_MAP.md").write_text(
                MAP.replace("| Open implementation | Review |", "| **CLOSED** | Review |"),
                encoding="utf-8",
            )
            (docs / "PROJECT_ADMIN_HUB.md").write_text(HUB, encoding="utf-8")
            snapshot = root / "issues.json"
            snapshot.write_text(json.dumps({"issues": list(ISSUES.values())}), encoding="utf-8")
            common = ["--snapshot", str(snapshot), "--root", str(root), "--as-of", "2026-10-08"]
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(drift.main(common), 0)
            self.assertNotIn("claims closed", output.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(drift.main(common + ["--check-current-gates"]), 0)
            self.assertIn("current gate claims closed", output.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(drift.main(common + ["--check-current-gates", "--strict"]), 1)
            self.assertIn("current gate claims closed", output.getvalue())

    def test_closed_current_owner_is_flagged_not_historical_packet(self):
        issues = {**ISSUES, 337: {**ISSUES[337], "state": "closed"}}
        errors, _ = drift.audit(HUB, MAP, issues, date(2026, 10, 8))
        self.assertEqual(errors, ["Current route #337: issue is closed, not open"])

    def test_open_historical_packet_is_flagged(self):
        issues = {**ISSUES, 246: {**ISSUES[246], "state": "open"}}
        errors, _ = drift.audit(HUB, MAP, issues, date(2026, 10, 8))
        self.assertEqual(errors, ["Closed implementation packet #246: issue is open"])

    def test_unrouted_physical_gate_flagged(self):
        hub = HUB.replace("[#334](https://github.com/agatte/home-hub/issues/334)", "")
        executive = MAP.replace(
            "[#334](https://github.com/agatte/home-hub/issues/334)",
            "Blue Yeti",
        )
        errors, _ = drift.audit(hub, executive, ISSUES, date(2026, 10, 8))
        self.assertEqual(errors, ["Open physical gate #334: missing current navigation link"])

    def test_missing_current_owner_and_stale_checkpoint(self):
        issues = {n: v for n, v in ISSUES.items() if n != 337}
        errors, notices = drift.audit(HUB, MAP, issues, date(2026, 12, 9))
        self.assertEqual(errors, ["Current route #337: no issue result"])
        self.assertTrue(any("62 days old" in n for n in notices))

    def test_future_checkpoint_flags_drift(self):
        errors, _ = drift.audit(HUB, MAP, ISSUES, date(2026, 10, 7))
        self.assertTrue(any("in the future" in e for e in errors))

    def test_malformed_or_incomplete_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            drift.actionable_issues("# Only a historical index")
        with self.assertRaises(ValueError):
            drift.normalize_issues({"issues": [{"number": 42, "state": "invented"}]})
        with self.assertRaises(ValueError):
            drift.normalize_issues(
                [
                    {"number": 42, "state": "open"},
                    {"number": 42, "state": "closed"},
                ]
            )
        with self.assertRaises(ValueError):
            drift.fetch_issues("not-a-valid-repo-name/with/three")

    def test_pr_records_are_ignored(self):
        result = drift.normalize_issues(
            [
                {"number": 337, "state": "open", "title": "Work"},
                {"number": 340, "state": "open", "pull_request": {"url": "pr"}},
            ]
        )
        self.assertEqual(set(result), {337})

    def test_bounded_knowledge_link_audit_is_read_only_and_reports_exact_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (root / "AGENTS.md").write_text(
                "[valid](docs/README.md) [external](https://example.org/docs) "
                "[section](#overview) ![image](missing-picture.png)",
                encoding="utf-8",
            )
            (docs / "README.md").write_text(
                "[local](PROJECT_ADMIN_HUB.md#heading) "
                "[escaped](../../unrelated.md) [missing](missing.md)",
                encoding="utf-8",
            )
            (docs / "PROJECT_ADMIN_HUB.md").write_text(
                "[percent-encoded](M%49SSING.md) [mail](mailto:help@example.org)",
                encoding="utf-8",
            )
            (docs / "EXECUTION_MAP.md").write_text("[fragment](#next-step)", encoding="utf-8")
            (docs / "KNOWLEDGE_WORKFLOW.md").write_text(
                "[angle destination](<README.md>)", encoding="utf-8"
            )

            findings = drift.check_knowledge_links(root)
            self.assertEqual(
                findings,
                [
                    "Knowledge link escapes repository: docs/README.md -> ../../unrelated.md",
                    "Knowledge link missing: docs/PROJECT_ADMIN_HUB.md -> M%49SSING.md",
                    "Knowledge link missing: docs/README.md -> missing.md",
                ],
            )
            self.assertEqual(findings, drift.check_knowledge_links(root))

    def test_missing_knowledge_entrypoint_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = drift.check_knowledge_links(Path(tmp), ("docs/KNOWLEDGE_WORKFLOW.md",))
            self.assertEqual(
                errors,
                ["Knowledge document missing or redirected: docs/KNOWLEDGE_WORKFLOW.md"],
            )

    def test_link_checks_are_opt_in_and_strict_only_changes_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "EXECUTION_MAP.md").write_text(MAP, encoding="utf-8")
            (docs / "PROJECT_ADMIN_HUB.md").write_text(
                HUB + "\n[broken](does-not-exist.md)", encoding="utf-8"
            )
            for name in ("AGENTS.md", "docs/README.md", "docs/KNOWLEDGE_WORKFLOW.md"):
                file = root / name
                file.write_text("# Stub for bounded fixture\n", encoding="utf-8")
            fixture = root / "issues.json"
            fixture.write_text(json.dumps({"issues": list(ISSUES.values())}), encoding="utf-8")
            args = ["--snapshot", str(fixture), "--root", str(root), "--as-of", "2026-10-08"]
            with contextlib.redirect_stdout(io.StringIO()) as plain:
                self.assertEqual(drift.main(args), 0)
            self.assertNotIn("Knowledge link", plain.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as report:
                self.assertEqual(drift.main([*args, "--check-doc-links"]), 0)
            self.assertIn(
                "DRIFT: Knowledge link missing: docs/PROJECT_ADMIN_HUB.md -> does-not-exist.md",
                report.getvalue(),
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(drift.main([*args, "--check-doc-links", "--strict"]), 1)

    def test_cli_is_report_only_unless_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "EXECUTION_MAP.md").write_text(MAP, encoding="utf-8")
            (root / "docs" / "PROJECT_ADMIN_HUB.md").write_text(HUB, encoding="utf-8")
            data = root / "issues.json"
            data.write_text(
                json.dumps(
                    {
                        "issues": [
                            *(
                                {**v, "state": "closed"} if n == 337 else v
                                for n, v in ISSUES.items()
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            args = ["--snapshot", str(data), "--root", str(root), "--as-of", "2026-10-08"]
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = drift.main(args)
            self.assertEqual(result, 0)
            self.assertIn("DRIFT: Current route #337", output.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                result = drift.main([*args, "--strict"])
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
