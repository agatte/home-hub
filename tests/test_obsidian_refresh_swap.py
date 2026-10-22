"""Disposable exact-target managed-swap regression tests."""
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import manage_obsidian_vault as manager
from obsidian_github_docs_source import PreparedDocs
from obsidian_refresh_swap import swap_only_after_rechecks
from obsidian_refresh_lock import exclusive_refresh_lock, RefreshBusy
from obsidian_verified_stage import stage_only_verified_docs
from test_obsidian_refresh_policy import bundle, FILES, NEW as COMMIT


class SwapFixtureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="homehub-399-swap-")
        self.addCleanup(temp.cleanup)
        self.parent = Path(temp.name)
        self.vault = self.parent / "My Vault"
        self.managed = self.vault / manager.MANAGED
        self.managed.mkdir(parents=True)
        for path, data in FILES.items():
            p = self.managed.joinpath(*path.split("/"))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (self.managed / "00-START-HERE.md").write_text("# Landing\n")
        (self.managed / "SNAPSHOT.md").write_text("# Provenance\n")
        self.old_sha = "d" * 40
        manager.seal(self.managed, self.old_sha)
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "app.json").write_bytes(b"settings")
        (self.vault / "Personal.md").write_bytes(b"private")
        self.suffix = "a" * 32
        self.prepared = PreparedDocs(self.old_sha, COMMIT, "forward", bundle(), True)
        self.staged = stage_only_verified_docs(
            vault=self.vault, docs=bundle(), stage_suffix=self.suffix,
            source_identity_verified=True,
        ).location

    def swap(self, **changes):
        args = dict(vault=self.vault, expected_vault=self.vault,
                    staged=self.staged, prepared=self.prepared, suffix=self.suffix,
                    app_probe=lambda: "closed", head_probe=lambda: COMMIT)
        args.update(changes)
        return swap_only_after_rechecks(**args)

    def assert_notes(self):
        self.assertEqual((self.vault / "Personal.md").read_bytes(), b"private")
        self.assertEqual((self.vault / ".obsidian" / "app.json").read_bytes(), b"settings")

    def test_success_retains_old_backup(self):
        result = self.swap()
        self.assertFalse(result.authorized_host_automation)
        self.assertEqual(manager.verify_sealed(result.backup)["source_commit"], self.old_sha)
        self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], COMMIT)
        self.assertFalse(self.staged.exists())
        self.assert_notes()

    def test_second_rename_failure_rolls_back(self):
        import obsidian_refresh_swap
        original = obsidian_refresh_swap.os.rename
        def fail_stage(source, dest):
            if Path(source) == self.staged:
                raise OSError("synthetic second rename failure")
            return original(source, dest)
        with patch.object(obsidian_refresh_swap.os, "rename", side_effect=fail_stage):
            with self.assertRaisesRegex(OSError, "synthetic second rename failure"):
                self.swap()
        self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], self.old_sha)
        self.assertTrue(self.staged.is_dir())
        self.assert_notes()

    def test_resealed_extra_git_markdown_is_refused(self):
        """Local re-sealing of injected docs is not remote Git provenance."""
        extra = self.staged / "docs" / "Injected.md"
        extra.write_bytes(b"unverified injected page")
        (self.staged / manager.MANIFEST).unlink()
        manager.seal(self.staged, COMMIT)
        with self.assertRaisesRegex(ValueError, "staged_unexpected_or_missing_paths"):
            self.swap()
        self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], self.old_sha)
        self.assertTrue(extra.is_file())
        self.assert_notes()

    def test_resealed_changed_generated_pages_are_refused(self):
        """Generated landing/provenance pages are part of exact membership."""
        for generated in ("00-START-HERE.md", "SNAPSHOT.md"):
            with self.subTest(generated=generated):
                target = self.staged / generated
                original = target.read_bytes()
                target.write_bytes(b"# Pretend to be trusted\n")
                (self.staged / manager.MANIFEST).unlink()
                manager.seal(self.staged, COMMIT)
                with self.assertRaisesRegex(ValueError, "staged_generated_page_changed"):
                    self.swap()
                self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], self.old_sha)
                self.assert_notes()
                # Restoring only the exact disposable generated page allows the
                # second subtest to re-seal the untouched baseline fixtures.
                target.write_bytes(original)
                (self.staged / manager.MANIFEST).unlink()
                manager.seal(self.staged, COMMIT)

    def test_stage_resealed_during_app_callback_is_refused(self):
        def app_probe():
            (self.staged / "docs" / "Injected.md").write_bytes(b"after-first-check")
            (self.staged / manager.MANIFEST).unlink()
            manager.seal(self.staged, COMMIT)
            return "closed"

        with self.assertRaisesRegex(ValueError, "staged_unexpected_or_missing_paths"):
            self.swap(app_probe=app_probe)
        self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], self.old_sha)
        self.assertFalse((self.parent / f".{self.vault.name}-homehub-backup-{self.suffix}").exists())
        self.assert_notes()

    def test_generated_page_resealed_during_head_callback_is_refused(self):
        def head_probe():
            (self.staged / "SNAPSHOT.md").write_bytes(b"# substituted page")
            (self.staged / manager.MANIFEST).unlink()
            manager.seal(self.staged, COMMIT)
            return COMMIT

        with self.assertRaisesRegex(ValueError, "staged_generated_page_changed"):
            self.swap(head_probe=head_probe)
        self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], self.old_sha)
        self.assertFalse((self.parent / f".{self.vault.name}-homehub-backup-{self.suffix}").exists())
        self.assert_notes()

    def test_unknown_app_refused(self):
        for state in ("unknown", "open", None, "CLOSED"):
            with self.subTest(state=state):
                with self.assertRaisesRegex(ValueError, "obsidian_not_proven_closed"):
                    self.swap(app_probe=lambda: state)
        self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], self.old_sha)

    def test_changed_github_head_refused(self):
        with self.assertRaisesRegex(ValueError, "github_master_changed"):
            self.swap(head_probe=lambda: "f" * 40)
        self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], self.old_sha)

    def test_tampered_staged_file_refused(self):
        target = self.staged / "AGENTS.md"
        target.chmod(stat.S_IREAD | stat.S_IWRITE)
        target.write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            self.swap()
        self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], self.old_sha)

    def test_occupied_backup_refused(self):
        backup = self.parent / f".{self.vault.name}-homehub-backup-{self.suffix}"
        backup.mkdir()
        (backup / "keep.txt").write_text("keep")
        with self.assertRaisesRegex(FileExistsError, "backup_target_occupied"):
            self.swap()
        self.assertEqual((backup / "keep.txt").read_text(), "keep")

    def test_concurrent_refusal(self):
        with exclusive_refresh_lock(self.vault, expected_vault=self.vault):
            with self.assertRaises(RefreshBusy):
                self.swap()
        self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], self.old_sha)

    def test_app_launch_after_closed_probe_exposes_coordination_gap(self):
        """This is a counterexample: no guarantee survives a process poll.

        The candidate is fixture-only and always reports host authorization
        false. This test must NEVER be misread as host lifecycle acceptance.
        """
        import obsidian_refresh_swap
        original = obsidian_refresh_swap.os.rename
        app_running = [False]
        observed_closed = [False]

        def app_probe():
            observed_closed[0] = True
            return "closed"

        def simulated_launch_between_probe_and_rename(source, dest):
            if Path(source) == self.managed:
                assert observed_closed[0]
                app_running[0] = True
            return original(source, dest)

        with patch.object(
            obsidian_refresh_swap.os, "rename",
            side_effect=simulated_launch_between_probe_and_rename
        ):
            result = self.swap(app_probe=app_probe)

        # The old fixture-only mechanism cannot detect/prevent this race.
        # Activation is therefore explicitly blocked until real coordination.
        self.assertTrue(app_running[0])
        self.assertFalse(result.authorized_host_automation)
        self.assertEqual(manager.verify_sealed(self.managed)["source_commit"], COMMIT)
        self.assert_notes()

    def test_wrong_exact_vault_refused(self):
        with self.assertRaisesRegex(ValueError, "mismatched_exact_vault"):
            self.swap(expected_vault=self.parent / "wrong")


if __name__ == "__main__":
    unittest.main()
