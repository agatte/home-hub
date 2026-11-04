"""Synthetic TEMP fixtures only; no installed Vault access."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from manage_obsidian_vault import MANAGED, MANIFEST, seal
from plan_obsidian_retention import PREFIX, main, plan


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="homehub-retention-")
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name) / "Documents"
        self.vault = self.parent / "HomeHub Knowledge Vault"
        self.snapshot(self.vault / MANAGED, 8)
        self.parts = []
        for number in range(7):
            token = f"{number:032x}"
            backup = self.parent / (PREFIX + "backup-" + token)
            stage = self.parent / (PREFIX + "completed-stage-" + token)
            receipt = self.parent / (PREFIX + "complete-" + token + ".json")
            self.snapshot(backup, number + 1)
            self.snapshot(stage, number + 2)
            receipt.write_text(json.dumps(dict(token=token, backup=backup.name,
                                              **{"from": self.oid(number + 1),
                                                 "to": self.oid(number + 2)})))
            os.utime(receipt, ns=(10**18 + number, 10**18 + number))
            self.parts.append((backup, stage, receipt))
        for number in range(10, 14):
            (self.parent / (PREFIX + "backup-" + f"{number:032x}")).mkdir()
        (self.vault / "Personal.md").write_text("personal")
        (self.vault / ".obsidian").mkdir()

    @staticmethod
    def oid(number):
        return f"{number:040x}"

    def snapshot(self, root, number):
        root.mkdir(parents=True)
        for name in ["AGENTS.md", "docs/PROJECT_SPEC.md", "00-START-HERE.md", "SNAPSHOT.md"]:
            path = root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(str(number))
        seal(root, self.oid(number))

    def test_retention_and_no_mutation(self):
        def inventory():
            return {str(p): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                    for p in self.parent.rglob("*")}
        before = inventory()
        original_iterdir = Path.iterdir
        def guarded(path):
            if path == self.vault or path == self.vault / ".obsidian":
                raise AssertionError("personal traversal")
            return original_iterdir(path)
        with patch.object(Path, "iterdir", guarded), \
                patch.object(Path, "write_bytes", side_effect=AssertionError("write")), \
                patch.object(Path, "write_text", side_effect=AssertionError("write")), \
                patch.object(Path, "unlink", side_effect=AssertionError("remove")), \
                patch.object(Path, "rename", side_effect=AssertionError("rename")), \
                patch.object(Path, "rmdir", side_effect=AssertionError("remove")):
            result = plan(self.vault)
        self.assertEqual(inventory(), before)
        self.assertEqual(len(result["retained"]), 5)
        self.assertEqual(len(result["protected_standalone"]), 4)
        self.assertEqual([x["token"] for x in result["candidates"]], [f"{1:032x}", f"{0:032x}"])
        self.assertEqual(result["candidate_path_count"], 6)
        self.assertGreater(result["candidate_estimated_bytes"], 0)
        self.assertTrue(all(Path(p).is_absolute() for t in result["candidates"] for p in t["paths"].values()))

    def test_markers_unknown_and_case_alias(self):
        for name in ["active", "stage-" + "a" * 32, "pending.json", "refresh.lock",
                     "incomplete", "backup-bad", "BACKUP-" + "a" * 32]:
            with self.subTest(name=name):
                path = self.parent / (PREFIX + name)
                path.mkdir()
                with self.assertRaises(ValueError):
                    plan(self.vault)
                # Exact empty synthetic test-owned path only.
                path.rmdir()

    def test_corrupt_seal(self):
        (self.parts[0][0] / "AGENTS.md").write_text("corrupt")
        with self.assertRaises(ValueError):
            plan(self.vault)

    def test_unknown_snapshot_file(self):
        (self.parts[0][1] / "unknown.md").write_text("unknown")
        with self.assertRaises(ValueError):
            plan(self.vault)

    def test_receipt_mismatch(self):
        receipt = self.parts[0][2]
        data = json.loads(receipt.read_text())
        data["from"] = self.oid(99)
        receipt.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            plan(self.vault)

    def test_missing_pair(self):
        self.parts[0][1].rename(self.parent / "synthetic-displaced-stage")
        with self.assertRaises(ValueError):
            plan(self.vault)

    def test_current_mismatch(self):
        manifest = self.vault / MANAGED / MANIFEST
        data = json.loads(manifest.read_text())
        data["source_commit"] = self.oid(99)
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "does_not_match_current"):
            plan(self.vault)

    def test_invalid_root(self):
        for root in [Path("HomeHub Knowledge Vault"), self.vault / "wrong", self.parent]:
            with self.assertRaises(ValueError):
                plan(root)

    def test_link(self):
        target = self.parts[0][1] / "linked.md"
        try:
            target.symlink_to(self.parts[0][1] / "AGENTS.md")
        except OSError:
            self.skipTest("OS does not permit synthetic symlinks")
        with self.assertRaises(ValueError):
            plan(self.vault)

    def test_reparse_attribute(self):
        from obsidian_simple_mirror import _plain
        from types import SimpleNamespace
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=0o100644, st_file_attributes=0x400)):
            with self.assertRaises(ValueError):
                _plain(self.parts[0][2])

    def test_untrusted_receipts(self):
        receipt = self.parts[0][2]
        for raw in ['[]', '{"token":"a","token":"b"}', 'x' * 4097,
                    json.dumps({"token": "bad"}), '{bad']:
            receipt.write_text(raw)
            with self.assertRaises(ValueError):
                plan(self.vault)

    def test_cli_explicit_only(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for args in [[], ["plan"], ["delete", "--vault", str(self.vault)]]:
                with self.assertRaises(SystemExit):
                    main(args)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["plan", "--vault", str(self.vault)]), 0)
        self.assertEqual(json.loads(output.getvalue())["action"], "plan_only")


if __name__ == "__main__":
    unittest.main()
