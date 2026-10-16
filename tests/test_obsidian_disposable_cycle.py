"""#399 offline integration tests; synthetic Vault and source fixtures only."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

# In a reviewed Git checkout, derive the source root from this test's path.
# For the isolated guest-TEMP prototype, the runner must EXPLICITLY identify
# the read-only source checkout; never silently test a hardcoded worktree.
REFERENCE = Path(
    os.environ.get("HH399_TEST_SOURCE_ROOT", str(Path(__file__).resolve().parents[1]))
).resolve(strict=True)
if not (REFERENCE / "scripts" / "obsidian_filewise_fixture_transaction.py").is_file():
    raise RuntimeError("explicit_homehub_source_checkout_required")
sys.path.insert(0, str(REFERENCE / "scripts"))
sys.path.insert(0, str(REFERENCE / "tests"))

from manage_obsidian_vault import MANIFEST, verify_sealed
from obsidian_github_docs_source import PreparedDocs
from obsidian_filewise_fixture_transaction import FixtureInterrupted, _paths
from obsidian_disposable_cycle import (
    CycleStatus, PriorTransaction, run_fixture_cycle,
)
from obsidian_cycle_lease import exclusive_cycle_lease, lease_path
from test_obsidian_filewise_fixture_transaction import FilewiseTransactionTests
from test_obsidian_refresh_policy import FILES, OLD, NEW, bundle

FIRST = "b" * 32
NEXT = "c" * 32


class DisposableCycleIntegrationTests(unittest.TestCase):
    setUp = FilewiseTransactionTests.setUp
    check_private = FilewiseTransactionTests.check_private
    run_publish = FilewiseTransactionTests.run_publish

    def execute(self, prepared=None, suffix=FIRST, prior=None, history=None):
        return run_fixture_cycle(
            vault=self.vault, expected_vault=self.vault,
            prepared=self.prepared if prepared is None else prepared,
            suffix=suffix, prior=prior, history=history,
        )

    def test_verified_update_then_subsequent_identical_no_change(self):
        result = self.execute()
        self.assertEqual(result.outcome, "published")
        self.assertEqual(result.target_commit, NEW)
        self.assertFalse(result.host_refresh_authorized)
        self.assertFalse(result.requires_review)
        backup, stage, journal, pending = _paths(self.vault, FIRST)
        self.assertEqual(verify_sealed(backup)["source_commit"], OLD)
        self.assertEqual(verify_sealed(stage)["source_commit"], NEW)
        self.assertEqual(json.loads(journal.read_bytes())["phase"], "published")
        self.assertFalse(pending.exists())
        self.assertEqual(verify_sealed(self.managed)["source_commit"], NEW)
        self.check_private()

        identical = PreparedDocs(NEW, NEW, "identical", self.new_bundle, True)
        status = self.execute(
            prepared=identical, suffix=NEXT,
            prior=PriorTransaction(FIRST, OLD, NEW),
        )
        self.assertEqual(status.outcome, "up_to_date")
        self.assertEqual(status.old_commit, NEW)
        self.assertEqual(status.target_commit, NEW)
        self.assertFalse(status.host_refresh_authorized)
        self.assertFalse(_paths(self.vault, NEXT)[0].exists())
        self.assertEqual(verify_sealed(self.managed)["source_commit"], NEW)
        self.check_private()

    def test_original_already_current_no_mutation(self):
        identical = PreparedDocs(OLD, OLD, "identical", self.old_bundle, True)
        result = self.execute(prepared=identical)
        self.assertEqual(result.outcome, "up_to_date")
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.original_manifest)
        self.assertFalse(_paths(self.vault, FIRST)[0].exists())
        self.check_private()

    def test_previous_interruption_must_be_inspected_before_next_cycle(self):
        with self.assertRaises(FixtureInterrupted):
            self.run_publish(interrupt_after=1)
        state = self.execute(
            suffix=NEXT, prior=PriorTransaction(FIRST, OLD, NEW)
        )
        self.assertEqual(state.outcome, "recovery_required")
        self.assertTrue(state.requires_review)
        self.assertFalse(state.host_refresh_authorized)
        backup, stage, journal, pending = _paths(self.vault, FIRST)
        self.assertEqual(verify_sealed(backup)["source_commit"], OLD)
        self.assertEqual(verify_sealed(stage)["source_commit"], NEW)
        self.assertEqual(json.loads(journal.read_bytes())["phase"], "applying")
        self.assertFalse(pending.exists())
        self.assertFalse(_paths(self.vault, NEXT)[0].exists())
        self.check_private()

    def test_used_suffix_never_republished_or_cleaned(self):
        first = self.execute()
        self.assertEqual(first.outcome, "published")
        _, _, journal, _ = _paths(self.vault, FIRST)
        original = journal.read_bytes()
        blocked = self.execute()
        self.assertEqual(blocked.outcome, "recovery_required")
        self.assertEqual(blocked.reason, "target_transaction_evidence_present")
        self.assertEqual(journal.read_bytes(), original)
        self.check_private()

    def test_unstable_source_blocks_without_backup(self):
        bad = replace(self.prepared, source_ref_stable=False)
        outcome = self.execute(prepared=bad)
        self.assertEqual(outcome.outcome, "blocked")
        self.assertFalse(outcome.host_refresh_authorized)
        self.assertFalse(_paths(self.vault, FIRST)[0].exists())
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()

    def test_unknown_prior_suffix_blocks_even_if_old_managed_seal_intact(self):
        other_suffix = "d" * 32
        backup, stage, journal, pending = _paths(self.vault, other_suffix)
        pending.write_bytes(b'{"synthetic":"interrupted"}')
        original = pending.read_bytes()
        blocked = self.execute(suffix=NEXT)
        self.assertEqual(blocked.outcome, "recovery_required")
        self.assertEqual(blocked.reason, "unknown_transaction_artifacts")
        self.assertTrue(blocked.requires_review)
        self.assertFalse(blocked.host_refresh_authorized)
        self.assertEqual(pending.read_bytes(), original)
        self.assertFalse(_paths(self.vault, NEXT)[0].exists())
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()

    def test_completed_prior_without_explicit_identity_still_blocks(self):
        self.assertEqual(self.execute().outcome, "published")
        identical = PreparedDocs(NEW, NEW, "identical", self.new_bundle, True)
        blocked = self.execute(prepared=identical, suffix=NEXT)
        self.assertEqual(blocked.outcome, "recovery_required")
        self.assertEqual(blocked.reason, "unknown_transaction_artifacts")
        self.assertFalse(_paths(self.vault, NEXT)[0].exists())
        self.assertEqual(verify_sealed(self.managed)["source_commit"], NEW)
        self.check_private()

    def test_unrecognized_evidence_name_fails_closed_without_cleanup(self):
        artifact = self.parent / ".Synthetic Vault-homehub-unexpected-unknown"
        artifact.write_bytes(b"synthetic evidence")
        blocked = self.execute()
        self.assertEqual(blocked.outcome, "recovery_required")
        self.assertEqual(blocked.reason, "unknown_transaction_artifacts")
        self.assertEqual(artifact.read_bytes(), b"synthetic evidence")
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()

    def test_fixture_publication_error_reports_review_and_never_retries(self):
        with patch("obsidian_disposable_cycle.publish_disposable_fixture",
                   side_effect=OSError("synthetic_io_error")) as publisher:
            result = self.execute()
        self.assertEqual(publisher.call_count, 1)
        self.assertEqual(result.outcome, "recovery_required")
        self.assertTrue(result.requires_review)
        self.assertFalse(result.host_refresh_authorized)
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()

    def test_refuses_host_named_target_without_calling_publisher(self):
        wrong = self.parent / "HomeHub Knowledge Vault"
        wrong.mkdir()
        (wrong / "HomeHub Source").mkdir()
        with patch("obsidian_disposable_cycle.publish_disposable_fixture") as publisher:
            with self.assertRaisesRegex(ValueError, "fixture_only_exact_target"):
                run_fixture_cycle(vault=wrong, expected_vault=wrong,
                                  prepared=self.prepared, suffix=FIRST)
        publisher.assert_not_called()
        self.check_private()

    def test_external_lease_blocks_cycle_without_preview_or_publisher(self):
        with exclusive_cycle_lease(self.vault, expected_vault=self.vault):
            with patch("obsidian_disposable_cycle.preview_filewise_refresh") as preview:
                with patch("obsidian_disposable_cycle.publish_disposable_fixture") as publish:
                    outcome = self.execute()
            self.assertEqual(outcome.outcome, "recovery_required")
            self.assertEqual(outcome.reason, "cycle_lease_live_or_stale")
            self.assertTrue(outcome.requires_review)
            preview.assert_not_called()
            publish.assert_not_called()
            self.assertTrue(lease_path(self.vault).exists())
        self.assertFalse(lease_path(self.vault).exists())
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()

    def test_lease_is_held_during_identical_source_preview(self):
        identical = PreparedDocs(OLD, OLD, "identical", self.old_bundle, True)
        from obsidian_disposable_cycle import preview_filewise_refresh as real_preview
        def checked_preview(*args, **kwargs):
            self.assertTrue(lease_path(self.vault).is_file())
            return real_preview(*args, **kwargs)
        with patch("obsidian_disposable_cycle.preview_filewise_refresh",
                   side_effect=checked_preview) as preview:
            status = self.execute(prepared=identical)
        self.assertEqual(status.outcome, "up_to_date")
        self.assertEqual(preview.call_count, 1)
        self.assertFalse(lease_path(self.vault).exists())
        self.check_private()

    def test_lease_is_held_across_nested_publisher(self):
        from obsidian_disposable_cycle import publish_disposable_fixture as real_publish
        def checked_publish(*args, **kwargs):
            self.assertTrue(lease_path(self.vault).is_file())
            return real_publish(*args, **kwargs)
        with patch("obsidian_disposable_cycle.publish_disposable_fixture",
                   side_effect=checked_publish) as publisher:
            status = self.execute()
        self.assertEqual(status.outcome, "published")
        self.assertEqual(publisher.call_count, 1)
        self.assertFalse(lease_path(self.vault).exists())
        self.check_private()

    def test_competing_real_child_cycle_denied_while_parent_owns_lease(self):
        # Separate actual OS process, SAME Sandbox user/security principal.
        # This confirms cooperative cycle serialization, NOT Windows ACL isolation.
        code = (
            "from pathlib import Path\n"
            "from obsidian_disposable_cycle import run_fixture_cycle\n"
            "from obsidian_github_docs_source import PreparedDocs\n"
            "from test_obsidian_refresh_policy import FILES,bundle,OLD,NEW\n"
            "import sys\n"
            "v=Path(sys.argv[1])\n"
            "docs=bundle({**FILES,'docs/NEW.md':b'new',"
            "'docs/PROJECT_SPEC.md':b'new spec'},NEW)\n"
            "p=PreparedDocs(OLD,NEW,'forward',docs,True)\n"
            "r=run_fixture_cycle(vault=v,expected_vault=v,prepared=p,suffix='b'*32)\n"
            "print(r.outcome+'|'+r.reason)\n"
            "sys.exit(0 if r.outcome=='recovery_required' and "
            "r.reason=='cycle_lease_live_or_stale' else 9)\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join((
            str(Path(__file__).resolve().parent), str(REFERENCE / "scripts"),
            str(REFERENCE / "tests"),
        ))
        with exclusive_cycle_lease(self.vault, expected_vault=self.vault):
            child = subprocess.run(
                [sys.executable, "-c", code, str(self.vault)],
                env=env, capture_output=True, text=True, timeout=25,
            )
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(child.stdout.strip(),
                             "recovery_required|cycle_lease_live_or_stale")
            self.assertTrue(lease_path(self.vault).is_file())
        self.assertFalse(lease_path(self.vault).exists())
        self.assertFalse(_paths(self.vault, FIRST)[0].exists())
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()

    def test_child_abrupt_exit_leaves_stale_cycle_lock_and_blocks_cycle(self):
        # Terminate only a disposable child launched by this exact test.
        child_code = (
            "from pathlib import Path\n"
            "import os,sys\n"
            "from obsidian_cycle_lease import exclusive_cycle_lease\n"
            "v=Path(sys.argv[1])\n"
            "with exclusive_cycle_lease(v,expected_vault=v): os._exit(73)\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join((
            str(Path(__file__).resolve().parent), str(REFERENCE / "scripts"),
        ))
        child = subprocess.run(
            [sys.executable, "-c", child_code, str(self.vault)],
            env=env, capture_output=True, text=True, timeout=25,
        )
        self.assertEqual(child.returncode, 73, child.stderr)
        lock = lease_path(self.vault)
        self.assertTrue(lock.is_file())
        before = lock.read_bytes()
        state = self.execute()
        self.assertEqual(state.outcome, "recovery_required")
        self.assertEqual(state.reason, "cycle_lease_live_or_stale")
        self.assertEqual(lock.read_bytes(), before)
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()

    def test_altered_cycle_lease_never_signals_update_success(self):
        # Deliberately simulate an out-of-contract competing writer on the
        # disposable lease itself. The lease is retained for inspection.
        identical = PreparedDocs(OLD, OLD, "identical", self.old_bundle, True)
        from obsidian_disposable_cycle import preview_filewise_refresh as real_preview
        def corrupt_lease(*args, **kwargs):
            lease_path(self.vault).write_text('{"tampered":true}', encoding="utf-8")
            return real_preview(*args, **kwargs)
        with patch("obsidian_disposable_cycle.preview_filewise_refresh",
                   side_effect=corrupt_lease):
            state = self.execute(prepared=identical)
        self.assertEqual(state.outcome, "recovery_required")
        self.assertEqual(state.reason, "cycle_lease_integrity_failure")
        self.assertTrue(lease_path(self.vault).is_file())
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()

    def _publish_two_generations(self):
        self.assertEqual(self.execute().outcome, "published")
        a = PriorTransaction(FIRST, OLD, NEW)
        third_commit = "d" * 40
        docs = bundle(
            {**FILES, "docs/NEW.md": b"third",
             "docs/PROJECT_SPEC.md": b"third spec"},
            third_commit,
        )
        prepared = PreparedDocs(NEW, third_commit, "forward", docs, True)
        second = self.execute(prepared=prepared, suffix=NEXT, history=(a,))
        self.assertEqual(second.outcome, "published")
        b = PriorTransaction(NEXT, NEW, third_commit)
        return a, b

    def test_three_successive_publishes_retain_and_verify_all_history(self):
        a, b = self._publish_two_generations()
        last_commit = "e" * 40
        contents = {
            **FILES, "docs/NEW.md": b"fourth",
            "docs/PROJECT_SPEC.md": b"fourth spec",
        }
        prepared = PreparedDocs(
            b.new_commit, last_commit, "forward",
            bundle(contents, last_commit), True,
        )
        third_suffix = "d" * 32
        outcome = self.execute(
            prepared=prepared, suffix=third_suffix, history=(a, b),
        )
        self.assertEqual(outcome.outcome, "published")
        self.assertEqual(outcome.target_commit, last_commit)
        self.assertFalse(outcome.host_refresh_authorized)
        self.assertEqual(verify_sealed(self.managed)["source_commit"], last_commit)
        for txn in (a, b):
            backup, stage, journal, pending = _paths(self.vault, txn.suffix)
            self.assertEqual(
                verify_sealed(backup)["source_commit"], txn.old_commit
            )
            self.assertEqual(
                verify_sealed(stage)["source_commit"], txn.new_commit
            )
            self.assertEqual(json.loads(journal.read_bytes())["phase"], "published")
            self.assertFalse(pending.exists())
        self.check_private()

    def test_missing_older_history_blocks_third_publication(self):
        a, b = self._publish_two_generations()
        fourth_commit = "e" * 40
        prepared = PreparedDocs(
            b.new_commit, fourth_commit, "forward",
            bundle({**FILES, "docs/NEW.md": b"fourth"}, fourth_commit), True,
        )
        outcome = self.execute(
            prepared=prepared, suffix="d" * 32, history=(b,),
        )
        self.assertEqual(outcome.outcome, "recovery_required")
        self.assertEqual(outcome.reason, "unknown_transaction_artifacts")
        self.assertFalse(_paths(self.vault, "d" * 32)[0].exists())
        self.assertEqual(
            verify_sealed(self.managed)["source_commit"], b.new_commit
        )
        self.check_private()

    def test_tampered_older_backup_blocks_third_publication(self):
        a, b = self._publish_two_generations()
        old_backup, _, _, _ = _paths(self.vault, a.suffix)
        (old_backup / "AGENTS.md").write_bytes(b"changed historical backup")
        fourth_commit = "e" * 40
        prepared = PreparedDocs(
            b.new_commit, fourth_commit, "forward",
            bundle({**FILES, "docs/NEW.md": b"fourth"}, fourth_commit), True,
        )
        outcome = self.execute(
            prepared=prepared, suffix="d" * 32, history=(a, b),
        )
        self.assertEqual(outcome.outcome, "recovery_required")
        self.assertEqual(outcome.reason, "retained_history_unverified")
        self.assertFalse(_paths(self.vault, "d" * 32)[0].exists())
        self.assertEqual(
            verify_sealed(self.managed)["source_commit"], b.new_commit
        )
        self.check_private()

    def test_history_commit_chain_mismatch_refuses(self):
        a, b = self._publish_two_generations()
        bad = PriorTransaction(b.suffix, "f" * 40, b.new_commit)
        identical = PreparedDocs(
            b.new_commit, b.new_commit, "identical",
            bundle({**FILES, "docs/NEW.md": b"third",
                    "docs/PROJECT_SPEC.md": b"third spec"}, b.new_commit),
            True,
        )
        result = self.execute(
            prepared=identical, suffix="d" * 32, history=(a, bad),
        )
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.reason, "invalid_retained_history_chain")
        self.check_private()

    def test_lock_cleanup_failure_reports_published_commits(self):
        with patch(
            "obsidian_cycle_lease._verify_lease",
            side_effect=RuntimeError("cycle_lease_changed_preserved"),
        ):
            result = self.execute()
        self.assertEqual(result.outcome, "recovery_required")
        self.assertEqual(result.reason, "cycle_lease_integrity_failure")
        self.assertEqual(result.pre_cleanup_outcome, "published")
        self.assertEqual(result.old_commit, OLD)
        self.assertEqual(result.target_commit, NEW)
        self.assertTrue(lease_path(self.vault).is_file())
        self.assertEqual(verify_sealed(self.managed)["source_commit"], NEW)
        self.check_private()

    def test_failed_lease_fstat_closes_fd_and_preserves_evidence(self):
        from unittest.mock import patch
        with patch("obsidian_cycle_lease.os.close", wraps=os.close) as close:
            with patch(
                "obsidian_cycle_lease.os.fstat",
                side_effect=OSError("synthetic fstat failure"),
            ):
                result = self.execute()
        self.assertEqual(result.outcome, "recovery_required")
        self.assertEqual(result.reason, "cycle_lease_io_failure")
        self.assertTrue(lease_path(self.vault).exists())
        self.assertGreaterEqual(close.call_count, 1)
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.check_private()


if __name__ == "__main__":
    unittest.main(verbosity=2)
