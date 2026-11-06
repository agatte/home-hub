"""Regression tests for the conservative GitHub PR CI fast path."""

import subprocess
import unittest
from unittest.mock import patch

from scripts import ci_change_scope as scope


class CiScopeTests(unittest.TestCase):
    def test_docs_only_skips_expensive_jobs(self):
        self.assertEqual(scope.classify_paths(["docs/README.md", "AGENTS.md"]),
                         (False, False, "docs-only"))

    def test_frontend_only_runs_frontend(self):
        self.assertEqual(scope.classify_paths(
            ["frontend-svelte/src/routes/+page.svelte",
             "frontend-svelte/package-lock.json"]),
            (False, True, "frontend-and-optional-docs-only"))

    def test_frontend_and_docs_runs_frontend(self):
        self.assertEqual(scope.classify_paths(
            ["docs/DASHBOARD_REDESIGN_VISION.md", "frontend-svelte/src/lib/ui.js"]),
            (False, True, "frontend-and-optional-docs-only"))

    def test_backend_change_runs_full_suite(self):
        self.assertEqual(scope.classify_paths(
            ["backend/services/automation_engine.py"]),
            (True, True, "shared-or-unknown-path"))

    def test_unknown_ci_or_dependency_changes_run_full(self):
        for path in (
            ".github/workflows/check.yml",
            "scripts/ci_change_scope.py",
            "requirements-test.txt",
            "tests/test_automation_engine.py",
            "docs/unsafe_script.py",
            "frontend-svelte-renamed/x.js",
        ):
            with self.subTest(path=path):
                self.assertEqual(scope.classify_paths([path])[:2], (True, True))

    def test_mixed_frontend_backend_runs_full(self):
        self.assertEqual(scope.classify_paths(
            ["frontend-svelte/src/app.css", "backend/config.py"])[:2],
            (True, True))

    def test_empty_or_unknown_diff_runs_full(self):
        self.assertEqual(scope.classify_paths(None)[:2], (True, True))
        self.assertEqual(scope.classify_paths([])[:2], (True, True))

    def test_invalid_or_ambiguous_paths_run_full(self):
        for name in ("", "../docs/readme.md", "/docs/readme.md",
                     "frontend-svelte\\src\\bad.svelte", "frontend-svelte/"):
            with self.subTest(name=name):
                self.assertEqual(scope.classify_paths([name])[:2], (True, True))

    def test_diff_returns_nul_delimited_paths(self):
        result = subprocess.CompletedProcess(
            [], 0, b"docs/README.md\0frontend-svelte/src/app.css\0", b"")
        with patch.object(scope.subprocess, "run", return_value=result) as run:
            paths = scope.changed_pr_paths("a" * 40)
        self.assertEqual(paths, ["docs/README.md", "frontend-svelte/src/app.css"])
        command = run.call_args.args[0]
        self.assertIn("--no-renames", command)
        self.assertIn("-z", command)
        self.assertEqual(command[-2:], ["HEAD", "--"])

    def test_missing_diff_ancestry_or_error_runs_full(self):
        self.assertIsNone(scope.changed_pr_paths(""))
        self.assertIsNone(scope.changed_pr_paths("not-a-hash"))
        with patch.object(scope.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 128, b"", b"missing base")):
            self.assertIsNone(scope.changed_pr_paths("a" * 40))
        with patch.object(scope.subprocess, "run", side_effect=OSError("git unavailable")):
            self.assertIsNone(scope.changed_pr_paths("a" * 40))

    def test_malformed_diff_output_runs_full(self):
        with patch.object(scope.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, b"docs/x.md", b"")):
            self.assertIsNone(scope.changed_pr_paths("a" * 40))
        with patch.object(scope.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, b"docs/\xff.md\0", b"")):
            self.assertIsNone(scope.changed_pr_paths("a" * 40))

    def test_renamed_cross_scope_paths_are_not_hidden(self):
        # --no-renames makes old and new paths visible to the conservative policy.
        self.assertEqual(scope.classify_paths(
            ["backend/important.py", "docs/important.md"])[:2], (True, True))

    def test_root_markdown_is_documentation_but_nested_unknown_is_not(self):
        self.assertEqual(scope.classify_paths(["README.md"])[:2], (False, False))
        self.assertEqual(scope.classify_paths(["random/README.md"])[:2], (True, True))


if __name__ == "__main__":
    unittest.main()
