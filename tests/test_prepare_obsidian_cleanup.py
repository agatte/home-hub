"""Synthetic fixtures and dictionary-only removal simulation; no host executor."""

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import test_plan_obsidian_retention as fixtures
from prepare_obsidian_cleanup import prepare, revalidate
from plan_obsidian_retention import PREFIX


class CleanupPreparationTests(fixtures.RetentionTests):
    def setUp(self):
        # Keep all new fixtures within this task worktree. Cleanup uses only
        # individually enumerated fixture files and verified-empty directories.
        class Fixture:
            def __init__(self, **kwargs):
                self.name = tempfile.mkdtemp(prefix="hh399-retention-cleanup-",
                                             dir=Path(__file__).resolve().parents[1])

            def cleanup(self):
                root = Path(self.name)
                for parent, dirs, files in os.walk(root, topdown=False, followlinks=False):
                    for name in files:
                        (Path(parent) / name).unlink()
                    for name in dirs:
                        target = Path(parent) / name
                        if target.is_symlink():
                            target.unlink()
                        else:
                            target.rmdir()
                root.rmdir()

        with patch("test_plan_obsidian_retention.tempfile.TemporaryDirectory", Fixture):
            super().setUp()
        self.token = f"{0:032x}"

    def selection(self):
        return prepare(self.vault, expected_commit=self.oid(8), token=self.token)

    @staticmethod
    def ack(selection):
        return f"REVIEW ONE {selection['token']} {selection['digest']}"

    def test_exact_selection_and_read_only(self):
        before = self.inventory()
        with patch.object(Path, "unlink", side_effect=AssertionError("write")), \
                patch.object(Path, "rmdir", side_effect=AssertionError("write")), \
                patch.object(Path, "write_bytes", side_effect=AssertionError("write")):
            selected = self.selection()
            self.assertEqual(selected, self.selection())
            self.assertEqual(revalidate(selected, self.ack(selected)), selected)
            serialized = json.loads(json.dumps(selected))
            self.assertEqual(revalidate(serialized, self.ack(serialized)), selected)
        self.assertEqual(before, self.inventory())
        self.assertEqual(set(selected["selected_paths"].values()), set(map(str, self.parts[0])))
        ops = selected["operations"]
        self.assertEqual(len({op["evidence"]["path"] for op in ops}), len(ops))
        self.assertEqual(sum(op["evidence"]["size"] for op in ops
                             if op["operation"] == "unlink"), selected["estimated_bytes"])
        self.assertEqual(ops[-1]["evidence"]["path"], str(self.parts[0][2]))

    def inventory(self):
        # Synthetic fixture only; product code never enumerates personal notes.
        return {str(p): p.read_bytes() if p.is_file() else None
                for p in self.parent.rglob("*")}

    def test_explicit_identity_and_protected_tokens(self):
        for token in [None, "", "A" * 32, "../", f"{6:032x}", f"{10:032x}"]:
            with self.subTest(token=token), self.assertRaises(ValueError):
                prepare(self.vault, expected_commit=self.oid(8), token=token)
        with self.assertRaises(ValueError):
            prepare(self.vault, expected_commit=self.oid(7), token=self.token)

    def test_ack_and_tampered_manifest(self):
        selected = self.selection()
        for ack in [None, "", "yes", self.ack(selected) + " "]:
            with self.assertRaises(ValueError):
                revalidate(selected, ack)
        altered = copy.deepcopy(selected)
        altered["operations"].pop()
        with self.assertRaisesRegex(ValueError, "digest"):
            revalidate(altered, self.ack(selected))

    def test_same_target_mutation_refuses(self):
        selected = self.selection()
        (self.parts[0][0] / "AGENTS.md").write_text("external mutation")
        before = self.inventory()
        with self.assertRaises(ValueError):
            revalidate(selected, self.ack(selected))
        self.assertEqual(before, self.inventory())

    def test_hardlink_refused(self):
        from prepare_obsidian_cleanup import _record
        from types import SimpleNamespace
        target = self.parts[0][0] / "AGENTS.md"
        info = target.stat()
        linked = SimpleNamespace(st_mode=info.st_mode, st_nlink=2,
                                 st_file_attributes=0)
        # The mapped Sandbox filesystem may report nlink=1 even for os.link;
        # inject the OS metadata contract rather than claim native link coverage.
        with patch.object(Path, "stat", return_value=linked), \
                self.assertRaisesRegex(ValueError, "hardlinked"):
            _record(target)

    def test_receipt_timestamp_requires_new_digest(self):
        selected = self.selection()
        receipt = self.parts[0][2]
        os.utime(receipt, ns=(10**18 - 1000, 10**18 - 1000))
        replacement = self.selection()
        self.assertNotEqual(selected["digest"], replacement["digest"])
        with self.assertRaisesRegex(ValueError, "reapproval"):
            revalidate(selected, self.ack(selected))

    def test_active_evidence_after_approval(self):
        selected = self.selection()
        for suffix in ["refresh.lock", "simple.pending", "stage-" + "f" * 32, "unknown"]:
            marker = self.parent / (PREFIX + suffix)
            marker.write_text("synthetic")
            before = self.inventory()
            with self.assertRaises(ValueError):
                revalidate(selected, self.ack(selected))
            self.assertEqual(before, self.inventory())
            marker.unlink()

    def test_thread_change_between_observations(self):
        import prepare_obsidian_cleanup as module
        original = module._observe
        calls = []

        def observe(*args):
            result = original(*args)
            if not calls:
                calls.append(True)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit((self.parts[0][0] / "AGENTS.md").write_text,
                                "concurrent writer").result()
            return result

        with patch.object(module, "_observe", observe), self.assertRaises(ValueError):
            self.selection()

    def test_changed_current_and_preserved_snapshot_refuse(self):
        selected = self.selection()
        (self.vault / "HomeHub Source" / "AGENTS.md").write_text("changed source")
        with self.assertRaises(ValueError):
            revalidate(selected, self.ack(selected))

    def test_no_personal_or_standalone_content_inspection(self):
        original = Path.iterdir

        def guarded(path):
            if path == self.vault or path.name == ".obsidian" or path in [
                    self.parent / (PREFIX + "backup-" + f"{n:032x}") for n in range(10, 14)]:
                raise AssertionError("protected traversal")
            return original(path)

        with patch.object(Path, "iterdir", guarded):
            self.selection()

    def test_dictionary_simulation_success_and_partial_failure(self):
        selected = self.selection()
        before = self.inventory()

        def simulate(ack, fail_at=None):
            approved = revalidate(selected, ack)
            virtual = dict(before)
            completed = []
            for index, operation in enumerate(approved["operations"]):
                if index == fail_at:
                    break  # No retry, rollback or opportunistic cleanup.
                target = operation["evidence"]["path"]
                if operation["operation"] == "rmdir_empty":
                    self.assertFalse(any(Path(target) in Path(p).parents for p in virtual))
                del virtual[target]
                completed.append(target)
            return virtual, completed

        with self.assertRaises(ValueError):
            simulate("")
        partial, done = simulate(self.ack(selected), fail_at=1)
        self.assertEqual(len(done), 1)
        self.assertIn(str(self.parts[0][2]), partial)
        after, done = simulate(self.ack(selected))
        targets = {op["evidence"]["path"] for op in selected["operations"]}
        self.assertEqual(after, {p: value for p, value in before.items() if p not in targets})
        self.assertEqual(set(done), targets)
        self.assertEqual(before, self.inventory())  # Even simulation never deletes fixtures.

    def test_no_executor_or_delete_cli_exists(self):
        import prepare_obsidian_cleanup as module
        self.assertFalse(hasattr(module, "execute"))
        self.assertFalse(hasattr(module, "main"))
        # Real-like paths have no removal entrypoint, with or without flags.
        self.assertNotIn("unlink(", Path(module.__file__).read_text())
        self.assertNotIn("rmdir(", Path(module.__file__).read_text())
