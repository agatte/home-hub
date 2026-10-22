"""Read-only crash inventory for synthetic Vaults; no automatic recovery."""

import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from manage_obsidian_vault import MANAGED, seal
from obsidian_refresh_recovery import inspect_exact_swap_recovery
from test_obsidian_refresh_policy import FILES

OLD = "d" * 40
NEW = "a" * 40
SUFFIX = "b" * 32


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hh399-crash-fixture-")
        self.addCleanup(tmp.cleanup)
        self.parent = Path(tmp.name)
        self.vault = self.parent / "Synthetic Vault"
        self.vault.mkdir()
        self.managed = self.vault / MANAGED
        self.staged = self.parent / f".{self.vault.name}-homehub-stage-{SUFFIX}"
        self.backup = self.parent / f".{self.vault.name}-homehub-backup-{SUFFIX}"
        self.lock = self.parent / f".{self.vault.name}-homehub-refresh.lock"
        self._create_sealed(self.managed, OLD)
        self._create_sealed(self.staged, NEW)
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "app.json").write_bytes(b"unchanged-config")
        (self.vault / "Personal.md").write_bytes(b"private-note")

    def _create_sealed(self, path, commit):
        path.mkdir()
        for name, content in FILES.items():
            file = path.joinpath(*name.split("/"))
            file.parent.mkdir(exist_ok=True, parents=True)
            file.write_bytes(content)
        (path / "00-START-HERE.md").write_text("# Landing\n", encoding="utf-8")
        (path / "SNAPSHOT.md").write_text("# Source\n", encoding="utf-8")
        seal(path, commit)

    def inspect(self, **overrides):
        kwargs = dict(
            vault=self.vault, expected_vault=self.vault, suffix=SUFFIX,
            previously_sealed_commit=OLD, intended_commit=NEW,
        )
        kwargs.update(overrides)
        return inspect_exact_swap_recovery(**kwargs)

    def _personal_untouched(self):
        self.assertEqual((self.vault / "Personal.md").read_bytes(), b"private-note")
        self.assertEqual((self.vault / ".obsidian" / "app.json").read_bytes(), b"unchanged-config")

    def test_prepare_only_is_not_permission(self):
        r = self.inspect()
        self.assertEqual(r.state, "prepared_only")
        self.assertEqual(r.managed_commit, OLD)
        self.assertEqual(r.stage_commit, NEW)
        self.assertIsNone(r.backup_commit)
        self.assertFalse(r.authorizes_repair_or_refresh)
        self._personal_untouched()

    def test_crash_after_first_rename_abstains_and_preserves_both(self):
        os.rename(self.managed, self.backup)
        r = self.inspect()
        self.assertEqual(r.reason, "interrupted_after_first_rename")
        self.assertTrue(r.manual_review_required)
        self.assertFalse(r.authorizes_repair_or_refresh)
        self.assertFalse(self.managed.exists())
        self.assertTrue(self.backup.is_dir())
        self.assertTrue(self.staged.is_dir())
        self._personal_untouched()

    def test_subprocess_crash_after_first_rename_never_auto_repairs(self):
        import subprocess
        import sys
        child = (
            "import os,sys\n"
            "os.rename(sys.argv[1],sys.argv[2])\n"
            "os._exit(73)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", child, str(self.managed), str(self.backup)],
            check=False, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 73, result.stderr)
        evidence = self.inspect()
        self.assertEqual(evidence.reason, "interrupted_after_first_rename")
        self.assertTrue(evidence.manual_review_required)
        self.assertFalse(evidence.authorizes_repair_or_refresh)
        self.assertTrue(self.staged.is_dir())
        self.assertTrue(self.backup.is_dir())
        self.assertFalse(self.managed.exists())
        self._personal_untouched()

    def test_completed_swap_preserves_backup(self):
        os.rename(self.managed, self.backup)
        os.rename(self.staged, self.managed)
        r = self.inspect()
        self.assertEqual(r.state, "completed_backup_preserved")
        self.assertFalse(r.manual_review_required)
        self.assertFalse(r.authorizes_repair_or_refresh)
        self.assertTrue(self.backup.is_dir())
        self._personal_untouched()

    def test_failed_rollback_without_managed_no_auto_repair(self):
        os.rename(self.managed, self.backup)
        os.rename(self.staged, self.parent / "separate-preserved-stage")
        r = self.inspect()
        self.assertEqual(r.state, "manual_review_required")
        self.assertEqual(r.reason, "ambiguous_transaction_state")
        self.assertTrue(self.backup.exists())
        self._personal_untouched()

    def test_old_intact_without_stage_or_backup(self):
        # Stage path was only an unused fixture. This is an exact-test cleanup.
        # Do not recursively delete: rename the stage outside the exact targets.
        os.rename(self.staged, self.parent / "not-transaction-stage")
        r = self.inspect()
        self.assertEqual(r.state, "old_snapshot_intact")
        self.assertFalse(r.manual_review_required)
        self.assertFalse(r.authorizes_repair_or_refresh)

    def test_unknown_lock_refuses_without_reading_or_removing(self):
        self.lock.write_bytes(b"stale or malicious: never unlock automatically")
        r = self.inspect()
        self.assertEqual(r.reason, "refresh_lock_present")
        self.assertTrue(self.lock.is_file())
        self.assertEqual(self.lock.read_bytes(), b"stale or malicious: never unlock automatically")
        self._personal_untouched()

    def test_tampered_managed_is_unknown(self):
        p = self.managed / "AGENTS.md"
        p.chmod(0o666)
        p.write_bytes(b"modified")
        r = self.inspect()
        self.assertEqual(r.state, "unknown")
        self.assertEqual(r.reason, "recovery_target_or_integrity_unverified")
        self._personal_untouched()

    def test_unexpected_old_sha_is_review(self):
        result = self.inspect(previously_sealed_commit="e" * 40)
        self.assertEqual(result.reason, "unexpected_managed_commit")

    def test_unexpected_stage_sha_is_review(self):
        result = self.inspect(intended_commit="f" * 40)
        self.assertEqual(result.reason, "unexpected_stage_commit")

    def test_invalid_exact_suffix_and_commit_refuse(self):
        for params in ({"suffix": "../x"}, {"suffix": "B" * 32},
                       {"intended_commit": OLD}, {"previously_sealed_commit": "x"}):
            with self.subTest(params=params):
                r = self.inspect(**params)
                self.assertEqual(r.state, "unknown")
                self.assertEqual(r.reason, "invalid_exact_transaction_identity")

    def test_wrong_exact_vault_refuses(self):
        r = self.inspect(expected_vault=self.parent / "Different")
        self.assertEqual(r.state, "unknown")

    def test_linked_backup_abstains(self):
        other = self.parent / "independent-dir"
        other.mkdir()
        try:
            self.backup.symlink_to(other, target_is_directory=True)
        except OSError:
            self.skipTest("symlink privilege unavailable")
        r = self.inspect()
        self.assertEqual(r.state, "unknown")
        self.assertTrue(other.is_dir())

    def test_stage_present_with_backup_and_old_is_ambiguous(self):
        self._create_sealed(self.backup, OLD)
        r = self.inspect()
        self.assertEqual(r.state, "manual_review_required")
        self.assertEqual(r.reason, "ambiguous_transaction_state")


if __name__ == "__main__":
    unittest.main()
