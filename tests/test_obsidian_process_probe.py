"""Synthetic failures and live read-only Windows process observation."""

from pathlib import Path
import os
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from obsidian_process_probe import (
    ProcessObservation,
    classify_snapshot,
    observe_windows_obsidian,
    probe_windows_obsidian_state,
)


class SnapshotProbeTests(unittest.TestCase):
    def test_closed_requires_complete_valid_enumeration(self):
        result = observe_windows_obsidian(snapshot=lambda: [
            (24, "explorer.exe"), (32, "chrome.exe")
        ])
        self.assertEqual(result.state, "closed")
        self.assertFalse(result.authorizes_host_refresh)

    def test_windows_pid_zero_system_process_is_not_corruption(self):
        r = classify_snapshot([(0, "[System Process]"), (24, "explorer.exe")])
        self.assertEqual(r.state, "closed")
        self.assertFalse(r.authorizes_host_refresh)

    def test_any_session_observes_case_insensitive_exact_exe(self):
        result = observe_windows_obsidian(snapshot=lambda: [
            (44, "Obsidian.exe"), (24, "explorer.exe"), (15, "OBSIDIAN.EXE"),
        ])
        self.assertEqual(result.state, "open")
        self.assertEqual(result.matched_pids, (15, 44))
        self.assertFalse(result.authorizes_host_refresh)

    def test_different_process_name_is_not_open(self):
        result = classify_snapshot([(30, "obsidian-updater.exe"), (31, "not-obsidian.exe")])
        self.assertEqual(result.state, "closed")

    def test_invalid_entry_abstains(self):
        cases = [
            [(0, "obsidian.exe")],
            [(-1, "explorer.exe")],
            [(True, "explorer.exe")],
            [("12", "obsidian.exe")],
            [(25, None)],
            [(25, "")],
            [("invalid",)],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.assertEqual(classify_snapshot(rows).state, "unknown")

    def test_snapshot_failure_abstains(self):
        def fails():
            raise PermissionError("inaccessible-process-list")
        result = observe_windows_obsidian(snapshot=fails)
        self.assertEqual(result.state, "unknown")
        self.assertFalse(result.authorizes_host_refresh)

    def test_incomplete_iterator_abstains_even_after_obsidian_row(self):
        def partial():
            yield 123, "Obsidian.exe"
            raise OSError("incomplete-process-snapshot")
        result = classify_snapshot(partial())
        self.assertEqual(result.state, "unknown")

    def test_non_windows_default_abstains(self):
        if os.name == "nt":
            self.skipTest("real Windows path tested separately")
        self.assertEqual(observe_windows_obsidian().state, "unknown")

    def test_live_default_is_advisory_only(self):
        result = observe_windows_obsidian()
        self.assertIsInstance(result, ProcessObservation)
        self.assertIn(result.state, ("open", "closed", "unknown"))
        self.assertFalse(result.authorizes_host_refresh)
        self.assertIn(probe_windows_obsidian_state(), ("open", "closed", "unknown"))


if __name__ == "__main__":
    unittest.main()
