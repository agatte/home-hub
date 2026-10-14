"""End-to-end disposable filewise backup, interruption, and restore tests."""

from dataclasses import replace
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from manage_obsidian_vault import MANAGED, MANIFEST, seal, verify_sealed
from obsidian_filewise_fixture_transaction import (
    FixtureInterrupted, _paths, inspect_fixture_recovery,
    publish_disposable_fixture, restore_disposable_fixture_backup,
)
from obsidian_github_docs_source import PreparedDocs
from obsidian_verified_stage import expected_generated_pages
from test_obsidian_refresh_policy import FILES, bundle, OLD, NEW

SUFFIX = "b" * 32


class FilewiseTransactionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hh399-filewise-txn-")
        self.addCleanup(tmp.cleanup)
        self.parent = Path(tmp.name)
        self.vault = self.parent / "Synthetic Vault"
        self.managed = self.vault / MANAGED
        self.managed.mkdir(parents=True)
        self.old_bundle = bundle({**FILES, "docs/OLD.md": b"old"}, OLD)
        self.new_bundle = bundle({**FILES, "docs/NEW.md": b"new",
                                  "docs/PROJECT_SPEC.md": b"new spec"}, NEW)
        self.prepared = PreparedDocs(OLD, NEW, "forward", self.new_bundle, True)
        for rel, data in {**self.old_bundle.contents,
                          **expected_generated_pages(self.old_bundle)}.items():
            p = self.managed.joinpath(*rel.split("/"))
            p.parent.mkdir(exist_ok=True, parents=True)
            p.write_bytes(data)
        seal(self.managed, OLD)
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "app.json").write_bytes(b"settings")
        (self.vault / "Personal.md").write_bytes(b"never modify")
        self.original_manifest = (self.managed / MANIFEST).read_bytes()

    def run_publish(self, prepared=None, **kw):
        return publish_disposable_fixture(
            vault=self.vault, expected_vault=self.vault,
            prepared=self.prepared if prepared is None else prepared,
            suffix=SUFFIX, **kw
        )

    def inspect(self):
        return inspect_fixture_recovery(
            vault=self.vault, expected_vault=self.vault,
            suffix=SUFFIX, old_commit=OLD, new_commit=NEW
        )

    def restore(self, **kw):
        return restore_disposable_fixture_backup(
            vault=self.vault, expected_vault=self.vault,
            suffix=SUFFIX, old_commit=OLD, new_commit=NEW, **kw
        )

    def check_private(self):
        self.assertEqual((self.vault / "Personal.md").read_bytes(), b"never modify")
        self.assertEqual((self.vault / ".obsidian" / "app.json").read_bytes(), b"settings")

    def test_success_new_manifest_last_backup_retained(self):
        r = self.run_publish()
        self.assertEqual(r.state, "published")
        self.assertTrue(r.backup_verified)
        self.assertFalse(r.authorizes_host_refresh)
        self.assertEqual(verify_sealed(self.managed)["source_commit"], NEW)
        backup, stage, journal, pending = _paths(self.vault, SUFFIX)
        self.assertEqual(verify_sealed(backup)["source_commit"], OLD)
        self.assertEqual(verify_sealed(stage)["source_commit"], NEW)
        self.assertEqual(json.loads(journal.read_bytes())["phase"], "published")
        self.assertFalse(pending.exists())
        self.assertTrue(self.managed.is_dir())
        self.assertFalse((self.managed / "docs/OLD.md").exists())
        self.assertTrue((self.managed / "docs/NEW.md").exists())
        self.check_private()

    def test_interrupted_after_one_replace_is_detected_and_restorable(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        r = self.inspect()
        self.assertEqual(r.state, "interrupted_mixed")
        self.assertTrue(r.backup_verified)
        self.assertTrue(r.requires_operator_review)
        self.assertTrue(self.managed.is_dir())
        backup, _, journal, _ = _paths(self.vault, SUFFIX)
        self.assertEqual(verify_sealed(backup)["source_commit"], OLD)
        self.assertEqual(json.loads(journal.read_bytes())["phase"], "applying")
        with self.assertRaisesRegex(ValueError, "operator_fixture_confirmation_required"):
            self.restore()
        outcome = self.restore(operator_confirmed=True)
        self.assertEqual(outcome.state, "old_intact")
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.original_manifest)
        self.assertTrue(backup.exists())
        self.check_private()

    def test_child_process_crash_after_write_preserves_backup_and_lock(self):
        # Child runs only against an explicitly named disposable temp fixture.
        source = (
            "import sys,os\n"
            "from pathlib import Path\n"
            "from obsidian_filewise_fixture_transaction import publish_disposable_fixture\n"
            "from obsidian_github_docs_source import PreparedDocs\n"
            "from test_obsidian_refresh_policy import bundle,FILES,OLD,NEW\n"
            "vault=Path(sys.argv[1]); root=Path(sys.argv[2])\n"
            "docs=bundle({**FILES,'docs/NEW.md':b'new','docs/PROJECT_SPEC.md':b'new spec'},NEW)\n"
            "prepared=PreparedDocs(OLD,NEW,'forward',docs,True)\n"
            "def crash(index,name):os._exit(73)\n"
            "publish_disposable_fixture(vault=vault,expected_vault=vault,prepared=prepared,suffix='b'*32,after_write=crash)\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "scripts") + os.pathsep + str(Path(__file__).parent)
        result = subprocess.run(
            [sys.executable, "-c", source, str(self.vault), str(self.parent)],
            env=env, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 73, result.stderr.decode(errors="replace"))
        report = self.inspect()
        self.assertEqual(report.state, "interrupted_mixed")
        self.assertTrue(report.backup_verified)
        lock = self.parent / ".Synthetic Vault-homehub-refresh.lock"
        self.assertTrue(lock.is_file())
        with self.assertRaisesRegex(ValueError, "stale_lock_requires_external_review"):
            self.restore(operator_confirmed=True)
        # Exact disposable fixture-only lock release, AFTER subprocess exit was
        # observed by parent. This is not a generic production stale-lock API.
        lock.unlink()
        outcome = self.restore(operator_confirmed=True)
        self.assertEqual(outcome.state, "old_intact")
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()

    def test_tampered_backup_refuses_recovery_without_changes(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        backup, _, _, _ = _paths(self.vault, SUFFIX)
        (backup / "AGENTS.md").write_bytes(b"tampered backup")
        report = self.inspect()
        self.assertEqual(report.state, "unknown")
        self.assertFalse(report.backup_verified)
        with self.assertRaisesRegex(ValueError, "not_verified_interrupted_fixture"):
            self.restore(operator_confirmed=True)
        self.check_private()

    def test_incomplete_journal_temp_abstains(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        _, _, _, pending = _paths(self.vault, SUFFIX)
        pending.write_bytes(b"incomplete")
        r = self.inspect()
        self.assertEqual(r.state, "unknown")
        self.assertEqual(r.reason, "unfinished_journal_write")
        self.check_private()

    def test_unknown_new_managed_file_preserved_and_recovery_refused(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        additional = self.managed / "docs" / "personal addition.md"
        additional.write_bytes(b"someone's work")
        with self.assertRaisesRegex(ValueError, "unknown_managed_file_refuse_restore"):
            self.restore(operator_confirmed=True)
        self.assertEqual(additional.read_bytes(), b"someone's work")
        self.check_private()

    def test_forged_journal_drive_path_never_reaches_restore(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        _, _, journal, _ = _paths(self.vault, SUFFIX)
        record = json.loads(journal.read_bytes())
        record["new_paths"] = sorted(set(record["new_paths"]) | {"D:outside.md"})
        journal.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self.inspect().state, "unknown")
        with self.assertRaisesRegex(ValueError, "not_verified_interrupted_fixture"):
            self.restore(operator_confirmed=True)
        self.check_private()

    def test_forged_journal_safe_extra_path_rejected_against_sealed_stage(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        _, _, journal, _ = _paths(self.vault, SUFFIX)
        record = json.loads(journal.read_bytes())
        record["new_paths"] = sorted(set(record["new_paths"]) | {"docs/FORGED.md"})
        journal.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self.inspect().state, "unknown")
        self.check_private()

    def test_cross_generation_case_only_rename_refused_before_backup(self):
        bad = bundle({
            **FILES,
            "docs/old.md": b"case changed",
            "docs/PROJECT_SPEC.md": b"new spec",
        }, NEW)
        with self.assertRaisesRegex(ValueError, "cross_generation_windows_namespace_transition"):
            self.run_publish(prepared=PreparedDocs(OLD,NEW,"forward",bad,True))
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()

    def test_exact_interrupted_file_copy_artifact_preserved_and_restored(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        target = self.managed / "docs" / "PROJECT_SPEC.md"
        artifact = target.parent / f".{target.name}.filewise-{SUFFIX}.tmp"
        artifact.write_bytes(b"incomplete transfer bytes")
        self.assertEqual(self.inspect().state, "interrupted_mixed")
        restored = self.restore(operator_confirmed=True)
        self.assertEqual(restored.state, "old_intact")
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.assertFalse(artifact.exists())
        evidence = self.parent / f".{self.vault.name}-homehub-filewise-artifacts-{SUFFIX}"
        self.assertEqual(len(list(evidence.iterdir())), 1)
        self.assertEqual(next(evidence.iterdir()).read_bytes(), b"incomplete transfer bytes")
        self.check_private()

    def test_manifest_temp_artifact_preserved_outside_vault(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        temp_manifest = self.managed / f".{MANIFEST}.filewise-{SUFFIX}.tmp"
        temp_manifest.write_bytes(b"incomplete manifest bytes")
        restored = self.restore(operator_confirmed=True)
        self.assertEqual(restored.state, "old_intact")
        self.assertFalse(temp_manifest.exists())
        evidence = self.parent / f".{self.vault.name}-homehub-filewise-artifacts-{SUFFIX}"
        self.assertEqual(next(evidence.iterdir()).read_bytes(), b"incomplete manifest bytes")
        self.check_private()

    def test_similar_unknown_temp_artifact_still_refuses(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        unknown = self.managed / "docs" / f".UNRELATED.md.filewise-{SUFFIX}.tmp"
        unknown.write_bytes(b"not our transaction")
        with self.assertRaisesRegex(ValueError, "unknown_managed_file_refuse_restore"):
            self.restore(operator_confirmed=True)
        self.assertEqual(unknown.read_bytes(), b"not our transaction")
        self.check_private()

    def test_evidence_collision_refuses_without_overwriting(self):
        import hashlib
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        target = self.managed / "docs" / "PROJECT_SPEC.md"
        artifact = target.parent / f".{target.name}.filewise-{SUFFIX}.tmp"
        artifact.write_bytes(b"incomplete")
        evidence = self.parent / f".{self.vault.name}-homehub-filewise-artifacts-{SUFFIX}"
        evidence.mkdir()
        name = hashlib.sha256(b"docs/PROJECT_SPEC.md").hexdigest() + ".preserved"
        collision = evidence / name
        collision.write_bytes(b"preexisting evidence must survive")
        with self.assertRaisesRegex(ValueError, "not_verified_interrupted_fixture"):
            self.restore(operator_confirmed=True)
        self.assertEqual(collision.read_bytes(), b"preexisting evidence must survive")
        self.assertEqual(artifact.read_bytes(), b"incomplete")
        self.check_private()

    def test_existing_valid_evidence_allows_idempotent_restore(self):
        import hashlib
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        evidence = self.parent / f".{self.vault.name}-homehub-filewise-artifacts-{SUFFIX}"
        evidence.mkdir()
        name = hashlib.sha256(b"docs/PROJECT_SPEC.md").hexdigest() + "-attempt-1.preserved"
        (evidence / name).write_bytes(b"already preserved after previous crash")
        _, _, journal, _ = _paths(self.vault, SUFFIX)
        record = json.loads(journal.read_bytes())
        record["restore_attempts"] = 1
        record["phase"] = "restoring"
        journal.write_text(json.dumps(record), encoding="utf-8")
        r = self.restore(operator_confirmed=True)
        self.assertEqual(r.state, "old_intact")
        self.assertTrue(r.requires_operator_review)
        self.assertEqual((evidence / name).read_bytes(), b"already preserved after previous crash")
        self.check_private()

    def test_known_old_managed_file_user_edit_refuses_without_loss(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        changed = self.managed / "docs" / "PROJECT_SPEC.md"
        changed.write_bytes(b"human edited this Markdown")
        with self.assertRaisesRegex(ValueError, "unexpected_known_managed_file_bytes"):
            self.restore(operator_confirmed=True)
        self.assertEqual(changed.read_bytes(), b"human edited this Markdown")
        self.check_private()

    def test_known_new_only_file_unexpected_edit_refuses_without_loss(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        changed = self.managed / "docs" / "NEW.md"
        changed.write_bytes(b"human wrote something different")
        with self.assertRaisesRegex(ValueError, "unexpected_known_managed_file_bytes"):
            self.restore(operator_confirmed=True)
        self.assertEqual(changed.read_bytes(), b"human wrote something different")
        self.check_private()

    def test_second_restore_attempt_uses_distinct_evidence_slot(self):
        import hashlib
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        _, _, journal, _ = _paths(self.vault, SUFFIX)
        record = json.loads(journal.read_bytes())
        record["phase"] = "restoring"
        record["restore_attempts"] = 1
        journal.write_text(json.dumps(record), encoding="utf-8")
        evidence = self.parent / f".{self.vault.name}-homehub-filewise-artifacts-{SUFFIX}"
        evidence.mkdir()
        digest = hashlib.sha256(b"docs/PROJECT_SPEC.md").hexdigest()
        first = evidence / (digest + "-attempt-1.preserved")
        first.write_bytes(b"first interrupted attempt")
        target = self.managed / "docs" / "PROJECT_SPEC.md"
        pending = target.parent / f".{target.name}.filewise-{SUFFIX}.tmp"
        pending.write_bytes(b"second interruption temp")
        r = self.restore(operator_confirmed=True)
        self.assertEqual(r.state, "old_intact")
        self.assertEqual(first.read_bytes(), b"first interrupted attempt")
        second = evidence / (digest + "-attempt-2.preserved")
        self.assertEqual(second.read_bytes(), b"second interruption temp")
        self.check_private()

    def test_finished_content_with_stale_lock_still_needs_review(self):
        r = self.run_publish()
        self.assertEqual(r.state, "published")
        lock = self.parent / ".Synthetic Vault-homehub-refresh.lock"
        lock.write_bytes(b"stale lock from unrelated process")
        inspection = self.inspect()
        self.assertEqual(inspection.state, "published")
        self.assertTrue(inspection.requires_operator_review)
        self.assertTrue(lock.exists())
        self.check_private()

    def test_finished_content_with_unknown_evidence_is_unknown(self):
        self.run_publish()
        evidence = self.parent / f".{self.vault.name}-homehub-filewise-artifacts-{SUFFIX}"
        evidence.mkdir()
        (evidence / "mystery.preserved").write_bytes(b"unrecognized evidence")
        inspection = self.inspect()
        self.assertEqual(inspection.state, "unknown")
        self.assertTrue(inspection.requires_operator_review)
        self.check_private()

    def test_restore_attempt_limit_invalid_journal_abstains(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        _, _, journal, _ = _paths(self.vault, SUFFIX)
        baseline = json.loads(journal.read_bytes())
        for count in (True, -1, 11, 1.5, "2"):
            with self.subTest(restore_attempts=count):
                journal.write_text(
                    json.dumps({**baseline, "restore_attempts": count}),
                    encoding="utf-8"
                )
                r = self.inspect()
                self.assertEqual(r.state, "unknown")
                self.assertFalse(r.authorizes_host_refresh)
                with self.assertRaisesRegex(ValueError, "not_verified_interrupted_fixture"):
                    self.restore(operator_confirmed=True)
        journal.write_text(json.dumps(baseline), encoding="utf-8")
        self.assertEqual(self.inspect().state, "interrupted_mixed")
        self.check_private()

    def test_future_attempt_artifact_refuses_even_with_intact_backup(self):
        import hashlib
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        evidence = self.parent / f".{self.vault.name}-homehub-filewise-artifacts-{SUFFIX}"
        evidence.mkdir()
        digest = hashlib.sha256(b"docs/PROJECT_SPEC.md").hexdigest()
        unbound = evidence / (digest + "-attempt-2.preserved")
        unbound.write_bytes(b"unbound future evidence")
        result = self.inspect()
        self.assertEqual(result.state, "unknown")
        self.assertFalse(result.authorizes_host_refresh)
        with self.assertRaisesRegex(ValueError, "not_verified_interrupted_fixture"):
            self.restore(operator_confirmed=True)
        self.assertEqual(unbound.read_bytes(), b"unbound future evidence")
        self.check_private()

    def test_published_seal_with_unfinished_journal_needs_review(self):
        self.run_publish()
        _, _, journal, _ = _paths(self.vault, SUFFIX)
        record = json.loads(journal.read_bytes())
        record["phase"] = "applying"
        journal.write_text(json.dumps(record), encoding="utf-8")
        status = self.inspect()
        self.assertEqual(status.state, "published")
        self.assertTrue(status.backup_verified)
        self.assertTrue(status.requires_operator_review)
        self.assertFalse(status.authorizes_host_refresh)
        self.check_private()

    def test_restored_old_seal_with_unfinished_journal_needs_review(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        status = self.restore(operator_confirmed=True)
        self.assertEqual(status.state, "old_intact")
        _, _, journal, _ = _paths(self.vault, SUFFIX)
        record = json.loads(journal.read_bytes())
        record["phase"] = "restoring"
        journal.write_text(json.dumps(record), encoding="utf-8")
        status = self.inspect()
        self.assertEqual(status.state, "old_intact")
        self.assertTrue(status.requires_operator_review)
        self.assertFalse(status.authorizes_host_refresh)
        self.check_private()

    def test_real_child_exit_mid_restore_then_second_attempt_recovers(self):
        """A terminated fixture restore leaves a valid backup and journal."""
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        script = (
            "import os,sys\\n"
            "from pathlib import Path\\n"
            "import obsidian_filewise_fixture_transaction as tx\\n"
            "from test_obsidian_refresh_policy import OLD,NEW\\n"
            "vault=Path(sys.argv[1])\\n"
            "orig=tx._put_exact_file\\n"
            "def stop(src,root,rel,suffix):\\n"
            "    orig(src,root,rel,suffix)\\n"
            "    os._exit(74)\\n"
            "tx._put_exact_file=stop\\n"
            "tx.restore_disposable_fixture_backup(vault=vault,expected_vault=vault,suffix='b'*32,old_commit=OLD,new_commit=NEW,operator_confirmed=True)\\n"
        ).replace(chr(92) + "n", chr(10))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "scripts") + os.pathsep + str(Path(__file__).parent)
        result = subprocess.run([sys.executable, "-c", script, str(self.vault)],
                                env=env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 74, result.stderr.decode(errors="replace"))
        backup, stage, journal, pending = _paths(self.vault, SUFFIX)
        self.assertEqual(verify_sealed(backup)["source_commit"], OLD)
        self.assertEqual(verify_sealed(stage)["source_commit"], NEW)
        self.assertFalse(pending.exists())
        record = json.loads(journal.read_bytes())
        self.assertEqual(record["phase"], "restoring")
        self.assertEqual(record["restore_attempts"], 1)
        self.assertEqual(self.inspect().state, "interrupted_mixed")
        lock = self.parent / ".Synthetic Vault-homehub-refresh.lock"
        self.assertTrue(lock.is_file())
        with self.assertRaisesRegex(ValueError, "stale_lock_requires_external_review"):
            self.restore(operator_confirmed=True)
        # Exact disposable-child lock only, after subprocess exit was observed.
        lock.unlink()
        report = self.restore(operator_confirmed=True)
        self.assertEqual(report.state, "old_intact")
        self.assertTrue(report.backup_verified)
        self.assertEqual(json.loads(journal.read_bytes())["restore_attempts"], 2)
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.original_manifest)
        self.check_private()

    def test_real_child_exit_after_exact_artifact_preservation_recovers(self):
        """Preserved attempt-1 evidence survives a subsequent restore."""
        import hashlib as digestlib
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        source = self.managed / "docs" / f".PROJECT_SPEC.md.filewise-{SUFFIX}.tmp"
        source.write_bytes(b"partial publisher bytes")
        script = (
            "import os,sys\\n"
            "from pathlib import Path\\n"
            "import obsidian_filewise_fixture_transaction as tx\\n"
            "from test_obsidian_refresh_policy import OLD,NEW\\n"
            "vault=Path(sys.argv[1])\\n"
            "orig=tx.os.rename\\n"
            "def stop(src,dst):\\n"
            "    orig(src,dst)\\n"
            "    os._exit(75)\\n"
            "tx.os.rename=stop\\n"
            "tx.restore_disposable_fixture_backup(vault=vault,expected_vault=vault,suffix='b'*32,old_commit=OLD,new_commit=NEW,operator_confirmed=True)\\n"
        ).replace(chr(92) + "n", chr(10))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "scripts") + os.pathsep + str(Path(__file__).parent)
        result = subprocess.run([sys.executable, "-c", script, str(self.vault)],
                                env=env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 75, result.stderr.decode(errors="replace"))
        backup, _, journal, pending = _paths(self.vault, SUFFIX)
        self.assertEqual(verify_sealed(backup)["source_commit"], OLD)
        self.assertFalse(pending.exists())
        record = json.loads(journal.read_bytes())
        self.assertEqual(record["restore_attempts"], 1)
        evidence = self.parent / f".{self.vault.name}-homehub-filewise-artifacts-{SUFFIX}"
        evidence_name = digestlib.sha256(b"docs/PROJECT_SPEC.md").hexdigest() + "-attempt-1.preserved"
        preserved = evidence / evidence_name
        self.assertEqual(preserved.read_bytes(), b"partial publisher bytes")
        self.assertFalse(source.exists())
        lock = self.parent / ".Synthetic Vault-homehub-refresh.lock"
        self.assertTrue(lock.is_file())
        lock.unlink()  # Exact fixture lock, child definitively exited.
        outcome = self.restore(operator_confirmed=True)
        self.assertEqual(outcome.state, "old_intact")
        self.assertTrue(outcome.requires_operator_review)
        self.assertEqual(preserved.read_bytes(), b"partial publisher bytes")
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.assertEqual(json.loads(journal.read_bytes())["restore_attempts"], 2)
        self.check_private()

    def test_second_transaction_same_suffix_refused(self):
        self.run_publish()
        with self.assertRaisesRegex(ValueError, "old_managed_commit_changed"):
            self.run_publish()
        self.check_private()

    def test_host_named_vault_always_refused_before_write(self):
        host_name = self.parent / "HomeHub Knowledge Vault"
        host_name.mkdir()
        with self.assertRaisesRegex(ValueError, "fixture_only_exact_target"):
            publish_disposable_fixture(vault=host_name, expected_vault=host_name,
                                       prepared=self.prepared, suffix=SUFFIX)
        self.assertEqual(list(host_name.iterdir()), [])
        self.check_private()

    def test_simulator_never_grants_host_authority(self):
        r = self.run_publish()
        self.assertFalse(r.authorizes_host_refresh)
        self.assertIsNone(getattr(r, "permission_token", None))
        self.check_private()

    def test_refuse_diverged_source_before_backup(self):
        with self.assertRaises(ValueError):
            publish_disposable_fixture(
                vault=self.vault, expected_vault=self.vault,
                prepared=replace(self.prepared, ancestry="diverged"),
                suffix=SUFFIX,
            )
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.assertEqual(self.inspect().state, "unknown")
        self.check_private()


if __name__ == "__main__":
    unittest.main()
