"""Read-only #399 filewise plan and disposable Windows interruption fixtures."""

from dataclasses import replace
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from manage_obsidian_vault import MANAGED, MANIFEST, seal, verify_sealed
from obsidian_filewise_preview import preview_filewise_refresh
from obsidian_github_docs_source import PreparedDocs
from obsidian_verified_stage import expected_generated_pages
from test_obsidian_refresh_policy import FILES, bundle, OLD, NEW


class FilewisePlanTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hh399-filewise-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.vault = self.root / "Synthetic Vault"
        self.managed = self.vault / MANAGED
        self.managed.mkdir(parents=True)
        self.original = bundle({**FILES, "docs/LEGACY.md": b"old optional\n"}, commit=OLD)
        self.new_docs = bundle({
            **FILES,
            "docs/PROJECT_SPEC.md": b"revised product spec\n",
            "docs/ADDED.md": b"new optional\n",
        }, commit=NEW)
        self.prepared = PreparedDocs(
            previously_sealed_commit=OLD,
            intended_commit=NEW,
            ancestry="forward",
            docs=self.new_docs,
            source_ref_stable=True,
        )
        for name, content in {
            **self.original.contents,
            **expected_generated_pages(self.original),
        }.items():
            target = self.managed / Path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        seal(self.managed, OLD)
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "app.json").write_bytes(b"my settings")
        (self.vault / "My Notes.md").write_bytes(b"private unchanged")
        self.original_manifest = (self.managed / MANIFEST).read_bytes()

    def plan(self, prepared=None, **kwargs):
        return preview_filewise_refresh(
            vault=self.vault,
            expected_vault=self.vault,
            prepared=self.prepared if prepared is None else prepared,
            **kwargs,
        )

    def assert_private_unchanged(self):
        self.assertEqual((self.vault / "My Notes.md").read_bytes(), b"private unchanged")
        self.assertEqual((self.vault / ".obsidian" / "app.json").read_bytes(), b"my settings")

    def test_plan_exact_added_replaced_retired_unmodified(self):
        result = self.plan()
        self.assertEqual(result.state, "review_required")
        self.assertEqual(result.added, ("docs/ADDED.md",))
        self.assertEqual(result.retired, ("docs/LEGACY.md",))
        self.assertIn("docs/PROJECT_SPEC.md", result.modified)
        self.assertIn("SNAPSHOT.md", result.modified)
        self.assertIn("AGENTS.md", result.unchanged)
        self.assertTrue(result.managed_directory_remains_present)
        self.assertTrue(result.manifest_replacement_last)
        self.assertFalse(result.multi_file_atomic)
        self.assertFalse(result.host_refresh_authorized)
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.original_manifest)
        self.assertEqual(verify_sealed(self.managed)["source_commit"], OLD)
        self.assert_private_unchanged()

    def test_same_source_and_bytes_is_noop_even_if_obsidian_open(self):
        same = PreparedDocs(OLD, OLD, "identical", self.original, True)
        r = self.plan(prepared=same)
        self.assertEqual(r.state, "no_change")
        self.assertEqual(r.added + r.modified + r.retired, ())
        self.assertFalse(r.host_refresh_authorized)

    def test_diverged_source_refused_without_changes(self):
        with self.assertRaisesRegex(ValueError, "non_forward_or_unstable_source"):
            self.plan(prepared=replace(self.prepared, ancestry="diverged"))
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.original_manifest)

    def test_changed_github_ref_refused_without_changes(self):
        with self.assertRaisesRegex(ValueError, "non_forward_or_unstable_source"):
            self.plan(prepared=replace(self.prepared, source_ref_stable=False))
        self.assert_private_unchanged()

    def test_source_claims_host_write_permission_refused(self):
        with self.assertRaisesRegex(ValueError, "untrusted_or_write_authorized_prepared_source"):
            self.plan(prepared=replace(self.prepared, refresh_authorized=True))

    def test_invalid_same_commit_claim_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "source_ancestry_state_mismatch"):
            self.plan(prepared=replace(self.prepared, ancestry="identical"))

    def test_reused_commit_with_different_content_refused(self):
        conflict = replace(self.prepared, intended_commit=OLD,
                           docs=bundle(self.new_docs.contents, commit=OLD),
                           ancestry="identical")
        with self.assertRaisesRegex(ValueError, "same_commit_but_changed_content"):
            self.plan(prepared=conflict)

    def test_old_tamper_refused_without_modifying_note(self):
        (self.managed / "AGENTS.md").write_bytes(b"tamper")
        with self.assertRaisesRegex(ValueError, "Managed file changed"):
            self.plan()
        self.assert_private_unchanged()

    def test_existing_unexpected_managed_md_is_never_silently_retired(self):
        p = self.managed / "Personally Added.md"
        p.write_bytes(b"unreviewed")
        (self.managed / MANIFEST).unlink()
        seal(self.managed, OLD)
        with self.assertRaisesRegex(ValueError, "unexpected_old_managed_content"):
            self.plan()
        self.assertEqual(p.read_bytes(), b"unreviewed")
        self.assert_private_unchanged()

    def test_mismatched_exact_vault_refused(self):
        with self.assertRaisesRegex(ValueError, "exact_vault_identity"):
            preview_filewise_refresh(
                vault=self.vault, expected_vault=self.root / "Other",
                prepared=self.prepared,
            )

    def test_tampered_new_git_content_refused(self):
        bad_docs = replace(
            self.new_docs,
            contents={**self.new_docs.contents, "AGENTS.md": b"unexpected"},
        )
        with self.assertRaises(ValueError):
            self.plan(prepared=replace(self.prepared, docs=bad_docs))
        self.assert_private_unchanged()

    def test_windows_reserved_old_path_never_retired(self):
        weird = self.managed / "docs" / "CON.md"
        weird.write_bytes(b"reserved on Windows")
        (self.managed / MANIFEST).unlink()
        seal(self.managed, OLD)
        with self.assertRaisesRegex(ValueError, "unexpected_old_managed_content"):
            self.plan()
        self.assert_private_unchanged()

    def test_unsafe_git_document_path_is_refused_even_with_valid_blob_hash(self):
        bad = bundle({**self.new_docs.contents, "docs/CON.md": b"unsafe"}, commit=NEW)
        with self.assertRaisesRegex(ValueError, "unsafe_markdown_path"):
            self.plan(prepared=replace(self.prepared, docs=bad))
        self.assert_private_unchanged()

    def test_unsorted_git_files_refused_before_any_apply(self):
        from dataclasses import replace as change
        bad = change(self.new_docs, files=tuple(reversed(self.new_docs.files)))
        with self.assertRaisesRegex(ValueError, "source_membership_or_order_unverified"):
            self.plan(prepared=change(self.prepared, docs=bad))
        self.assert_private_unchanged()

    def test_simulated_crash_mid_file_replace_preserves_directory_but_not_consistency(self):
        """Only disposable files: this is intentionally NOT an updater helper.

        Filewise publishing cannot offer an all-file atomic snapshot. It may
        leave mixed old/new content and a failing old seal after a crash,
        although it avoids the entire managed directory going missing.
        """
        plan = self.plan()
        self.assertTrue(plan.modified)
        backup = self.root / "exact-disposable-old-copy"
        shutil.copytree(self.managed, backup)
        self.assertEqual(verify_sealed(backup)["source_commit"], OLD)
        staged = self.root / "exact-disposable-single-file"
        staged.write_bytes(self.new_docs.contents["docs/PROJECT_SPEC.md"])
        staged.replace(self.managed / "docs" / "PROJECT_SPEC.md")
        # Simulated process interruption at this point: no more writes.
        self.assertTrue(self.managed.is_dir())
        self.assertTrue((self.managed / "00-START-HERE.md").is_file())
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.original_manifest)
        with self.assertRaisesRegex(ValueError, "Managed file changed"):
            verify_sealed(self.managed)
        self.assertEqual(verify_sealed(backup)["source_commit"], OLD)
        self.assert_private_unchanged()


if __name__ == "__main__":
    unittest.main()
