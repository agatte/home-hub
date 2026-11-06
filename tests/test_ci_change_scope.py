"""Regression tests for the conservative GitHub PR CI fast path."""

import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
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

    def test_stale_event_base_uses_verified_merge_first_parent(self):
        # A long-lived PR's event base may be missing from a shallow clone.
        # The checkout's first parent is the actual base tree for its merge.
        base, head, merge = "a" * 40, "b" * 40, "c" * 40
        ancestry = subprocess.CompletedProcess(
            [], 0, f"{merge} {base} {head}\n".encode(), b"")
        diff = subprocess.CompletedProcess(
            [], 0, b"docs/README.md\0frontend-svelte/src/app.css\0", b"")
        with patch.object(scope.subprocess, "run", side_effect=[ancestry, diff]) as run:
            paths = scope.changed_pr_paths(head, merge)
        self.assertEqual(paths, ["docs/README.md", "frontend-svelte/src/app.css"])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0],
                         ["git", "rev-list", "--parents", "-n", "1", "HEAD"])
        command = run.call_args_list[1].args[0]
        self.assertEqual(command[:2], ["git", "diff"])
        self.assertIn("--no-renames", command)
        self.assertIn("-z", command)
        self.assertEqual(command[-3:], [base, merge, "--"])

    def test_old_base_alone_is_not_enough_to_skip_checks(self):
        # With no event PR-head or synthetic-merge SHA, fail open to full CI.
        self.assertIsNone(scope.changed_pr_paths("a" * 40, ""))
        self.assertIsNone(scope.changed_pr_paths("", "c" * 40))
        self.assertIsNone(scope.changed_pr_paths("not-a-hash", "c" * 40))
        self.assertIsNone(scope.changed_pr_paths("b" * 40, "invalid"))
        self.assertEqual(scope.classify_paths(None)[:2], (True, True))

    def test_mismatched_or_ambiguous_merge_ancestry_is_rejected(self):
        base, head, merge = "a" * 40, "b" * 40, "c" * 40
        for parents in (
            f"{merge} {base} {'d' * 40}\n",  # unrelated PR head
            f"{'d' * 40} {base} {head}\n",   # checked-out merge mismatched
            f"{merge} {base}\n",              # single-parent commit
            f"{merge} {base} {head} {'d' * 40}\n",  # extra parent
            f"{merge}\n",                     # shallow or missing parents
            "corrupt metadata\n",
        ):
            with self.subTest(parents=parents):
                with patch.object(scope.subprocess, "run",
                                  return_value=subprocess.CompletedProcess(
                                      [], 0, parents.encode(), b"")) as run:
                    self.assertIsNone(scope.changed_pr_paths(head, merge))
                self.assertEqual(run.call_count, 1)  # never diff an untrusted merge

    def test_missing_git_or_ancestry_errors_run_full(self):
        head, merge = "b" * 40, "c" * 40
        with patch.object(scope.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 128, b"", b"missing parents")):
            self.assertIsNone(scope.changed_pr_paths(head, merge))
        for err in (OSError("git unavailable"),
                    subprocess.TimeoutExpired(cmd="git", timeout=30)):
            with self.subTest(err=type(err).__name__):
                with patch.object(scope.subprocess, "run", side_effect=err):
                    self.assertIsNone(scope.changed_pr_paths(head, merge))
        with patch.object(scope.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, b"\xff\n", b"")):
            self.assertIsNone(scope.changed_pr_paths(head, merge))

    def test_malformed_or_failed_diff_runs_full(self):
        base, head, merge = "a" * 40, "b" * 40, "c" * 40
        ancestry = subprocess.CompletedProcess(
            [], 0, f"{merge} {base} {head}\n".encode(), b"")
        for result in (
            subprocess.CompletedProcess([], 128, b"", b"diff failed"),
            subprocess.CompletedProcess([], 0, b"docs/x.md", b""),
            subprocess.CompletedProcess([], 0, b"docs/\xff.md\0", b""),
            subprocess.CompletedProcess([], 0, b"", b""),
        ):
            with self.subTest(output=result.stdout):
                with patch.object(scope.subprocess, "run",
                                  side_effect=[ancestry, result]):
                    self.assertIsNone(scope.changed_pr_paths(head, merge))

    def test_verified_ci_or_backend_change_remains_full(self):
        base, head, merge = "a" * 40, "b" * 40, "c" * 40
        ancestry = subprocess.CompletedProcess(
            [], 0, f"{merge} {base} {head}\n".encode(), b"")
        for name in (b"scripts/ci_change_scope.py\0",
                     b".github/workflows/check.yml\0",
                     b"backend/services/automation_engine.py\0"):
            with self.subTest(path=name):
                diff = subprocess.CompletedProcess([], 0, name, b"")
                with patch.object(scope.subprocess, "run",
                                  side_effect=[ancestry, diff]):
                    self.assertEqual(
                        scope.classify_paths(scope.changed_pr_paths(head, merge))[:2],
                        (True, True))

    def test_uppercase_event_shas_match_git_ancestry(self):
        base, head, merge = "a" * 40, "b" * 40, "c" * 40
        ancestry = subprocess.CompletedProcess(
            [], 0, f"{merge} {base} {head}\n".encode(), b"")
        diff = subprocess.CompletedProcess([], 0, b"docs/README.md\0", b"")
        with patch.object(scope.subprocess, "run", side_effect=[ancestry, diff]):
            self.assertEqual(scope.changed_pr_paths(head.upper(), merge.upper()),
                             ["docs/README.md"])

    def test_diff_subprocess_exceptions_also_fail_open(self):
        base, head, merge = "a" * 40, "b" * 40, "c" * 40
        ancestry = subprocess.CompletedProcess(
            [], 0, f"{merge} {base} {head}\n".encode(), b"")
        for err in (OSError("diff unavailable"),
                    subprocess.TimeoutExpired(cmd="git diff", timeout=30)):
            with self.subTest(err=type(err).__name__):
                with patch.object(scope.subprocess, "run",
                                  side_effect=[ancestry, err]):
                    self.assertIsNone(scope.changed_pr_paths(head, merge))

    def test_full_validation_events_bypass_git_and_write_scope_outputs(self):
        from unittest.mock import mock_open

        for event in ("push", "workflow_dispatch"):
            with self.subTest(event=event):
                stdout = StringIO()
                sink = mock_open()
                with (patch("sys.argv", ["ci_change_scope.py", "--event", event]),
                      patch.dict(scope.os.environ, {"GITHUB_OUTPUT": "scope-output"}),
                      patch.object(scope.Path, "open", sink),
                      patch.object(scope.subprocess, "run",
                                   side_effect=AssertionError("unexpected git call")),
                      redirect_stdout(stdout)):
                    scope.main()
                self.assertIn("full-validation-event; backend=true frontend=true",
                              stdout.getvalue())
                writes = [call.args[0] for call in sink().write.call_args_list]
                self.assertEqual(writes, ["backend=true\n", "frontend=true\n"])

    def test_pull_request_cli_passes_both_trusted_shas(self):
        head, merge = "b" * 40, "c" * 40
        stdout = StringIO()
        with (patch("sys.argv", ["ci_change_scope.py", "--event", "pull_request",
                                 "--pr-head", head, "--merge-sha", merge]),
              patch.dict(scope.os.environ, {"GITHUB_OUTPUT": ""}),
              patch.object(scope, "changed_pr_paths", return_value=["docs/README.md"]) as changed,
              redirect_stdout(stdout)):
            scope.main()
        changed.assert_called_once_with(head, merge)
        self.assertIn("docs-only; backend=false frontend=false", stdout.getvalue())

    def test_renamed_cross_scope_paths_are_not_hidden(self):
        # --no-renames makes old and new paths visible to the conservative policy.
        self.assertEqual(scope.classify_paths(
            ["backend/important.py", "docs/important.md"])[:2], (True, True))

    def test_root_markdown_is_documentation_but_nested_unknown_is_not(self):
        self.assertEqual(scope.classify_paths(["README.md"])[:2], (False, False))
        self.assertEqual(scope.classify_paths(["random/README.md"])[:2], (True, True))


if __name__ == "__main__":
    unittest.main()
