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
