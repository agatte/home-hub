"""Finite offline fixtures only, beneath system TEMP / Synthetic Vault."""

from dataclasses import replace
from hashlib import sha1
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from manage_obsidian_vault import MANAGED, MANIFEST, seal, verify_sealed
from obsidian_github_docs_source import VerifiedDocs
from obsidian_simple_mirror import mirror_once, run_once
from obsidian_source_verifier import DocBlob
from obsidian_verified_stage import expected_generated_pages

OLD, NEW = "a" * 40, "b" * 40
FILES = {
    "AGENTS.md": b"guide\n", "docs/PROJECT_SPEC.md": b"spec\n",
    "docs/PROJECT_ADMIN_HUB.md": b"hub\n", "docs/README.md": b"readme\n",
}


def bundle(commit=NEW, contents=None):
    data = dict(FILES if contents is None else contents)
    blobs = tuple(
        DocBlob(n, sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest(),
                "100644", len(b))
        for n, b in sorted(data.items())
    )
    return VerifiedDocs(commit, "c" * 40, blobs, data)


class SimpleMirrorTests(unittest.TestCase):
    def setUp(self):
        # All filesystem writes, including fixtures and evidence, stay in TEMP.
        self.temp = tempfile.TemporaryDirectory(prefix="homehub-simple-")
        self.addCleanup(self.cleanup)
        self.parent = Path(self.temp.name)
        self.vault = self.parent / "Synthetic Vault"
        self.managed = self.vault / MANAGED
        self.managed.mkdir(parents=True)
        old = bundle(OLD)
        for name, raw in {**old.contents, **expected_generated_pages(old)}.items():
            dest = self.managed / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        seal(self.managed, OLD)
        self.before = self.snapshot(self.managed)
        (self.vault / "Personal.md").write_bytes(b"my note")
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "app.json").write_bytes(b"settings")
        self.historical = self.parent / ".Synthetic Vault-homehub-backup-historical"
        self.historical.mkdir()
        (self.historical / "keep").write_bytes(b"history")

    def cleanup(self):
        # Existing stage helper creates read-only files; only disposable TEMP.
        for parent, _, files in os.walk(self.parent):
            for name in files:
                (Path(parent) / name).chmod(stat.S_IREAD | stat.S_IWRITE)
        self.temp.cleanup()

    @staticmethod
    def snapshot(root):
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob("*") if p.is_file()}

    def run_mirror(self, **changes):
        args = dict(vault=self.vault, expected_vault=self.vault,
                    docs=bundle(contents={**FILES, "docs/README.md": b"updated\n"}),
                    authenticated_sha=NEW, source_identity_verified=True,
                    source_ref_stable=True, authenticated_forward_from=OLD,
                    local_evaluation_approved=True)
        args.update(changes)
        return mirror_once(**args)

    def assert_personal(self):
        self.assertEqual((self.vault / "Personal.md").read_bytes(), b"my note")
        self.assertEqual((self.vault / ".obsidian" / "app.json").read_bytes(), b"settings")
        self.assertEqual((self.historical / "keep").read_bytes(), b"history")

    def source_api(self, commit=NEW):
        from test_obsidian_github_docs_source import fake_payloads, REPO_PATH

        api = fake_payloads()
        metadata = api.pop(REPO_PATH + "/git/commits/" + OLD)
        api[REPO_PATH + "/git/commits/" + commit] = {**metadata, "sha": commit}
        api[REPO_PATH + "/git/ref/heads/master"]["object"]["sha"] = commit
        api[REPO_PATH + f"/compare/{OLD}...{commit}"] = {
            "status": "ahead", "base_commit": {"sha": OLD},
            "merge_base_commit": {"sha": OLD},
        }
        return api

    def run_adapter(self, fetch, **changes):
        args = dict(vault=self.vault, expected_vault=self.vault,
                    local_evaluation_approved=True, fetch=fetch)
        args.update(changes)
        return run_once(**args)

    def test_adapter_forward_pinned_update(self):
        from test_obsidian_github_docs_source import FILES as SOURCE_FILES

        api = self.source_api()
        touched = []

        def fetch(path):
            touched.append(path)
            return api[path]

        result = self.run_adapter(fetch)
        self.assertEqual((result.state, result.previous_commit, result.commit),
                         ("updated", OLD, NEW))
        self.assertEqual(result.mirror_result.commit, NEW)
        self.assertEqual(self.snapshot(result.mirror_result.backup), self.before)
        for name, raw in SOURCE_FILES.items():
            self.assertEqual((self.managed / name).read_bytes(), raw)
        self.assertIn(f"/repos/agatte/home-hub/git/commits/{NEW}", touched)
        self.assertNotIn(f"/repos/agatte/home-hub/git/commits/{OLD}", touched)
        self.assert_personal()

    def test_adapter_equal_no_staging_or_writes(self):
        before = self.snapshot(self.parent)
        with patch("obsidian_simple_mirror.mirror_once") as mirror:
            result = self.run_adapter(self.source_api(OLD).__getitem__)
        mirror.assert_not_called()
        self.assertEqual((result.state, result.previous_commit, result.commit),
                         ("no_change", OLD, OLD))
        self.assertIsNone(result.mirror_result)
        self.assertEqual(self.snapshot(self.parent), before)

    def test_adapter_active_evidence_refused_before_acquisition(self):
        for tail in ["simple.pending", "refresh.lock", "stage-" + "0" * 32]:
            with self.subTest(tail=tail):
                path = self.parent / (".Synthetic Vault-homehub-" + tail)
                path.write_bytes(b"interrupted evidence")
                before = self.snapshot(self.parent)
                fetch = unittest.mock.Mock(side_effect=AssertionError("unexpected fetch"))
                with self.assertRaisesRegex(ValueError, "evidence_requires_review"):
                    self.run_adapter(fetch)
                fetch.assert_not_called()
                self.assertEqual(self.snapshot(self.parent), before)
                self.assert_personal()
                path.unlink()

    def test_adapter_completed_records_allow_no_change(self):
        completed = self.parent / (".Synthetic Vault-homehub-completed-stage-" + "0" * 32)
        completed.mkdir()
        (completed / "record").write_bytes(b"completed stage")
        receipt = self.parent / (".Synthetic Vault-homehub-complete-" + "0" * 32 + ".json")
        receipt.write_bytes(b"completed receipt")
        before = self.snapshot(self.parent)
        result = self.run_adapter(self.source_api(OLD).__getitem__)
        self.assertEqual(result.state, "no_change")
        self.assertEqual(self.snapshot(self.parent), before)
        self.assert_personal()

    def test_adapter_published_manifest_interruption_refuses_no_change(self):
        real_replace = os.replace

        def interrupt_after_manifest(src, dest):
            real_replace(src, dest)
            if Path(dest) == self.managed / MANIFEST:
                raise OSError("synthetic after manifest publication")

        with patch("obsidian_simple_mirror.os.replace", side_effect=interrupt_after_manifest):
            with self.assertRaisesRegex(OSError, "after manifest publication"):
                self.run_mirror()
        self.assertEqual(verify_sealed(self.managed)["source_commit"], NEW)
        self.assertTrue((self.parent / ".Synthetic Vault-homehub-simple.pending").exists())
        api = self.source_api(NEW)
        fetch = unittest.mock.Mock(side_effect=api.__getitem__)
        before = self.snapshot(self.parent)
        with self.assertRaisesRegex(ValueError, "evidence_requires_review"):
            self.run_adapter(fetch)
        fetch.assert_not_called()
        self.assertEqual(self.snapshot(self.parent), before)
        self.assert_personal()

    def test_adapter_unavailable_and_divergence_zero_writes(self):
        from obsidian_github_docs_source import SourceUnavailable, REPO_PATH

        before = self.snapshot(self.parent)
        names = set(self.parent.rglob("*"))
        api = self.source_api()
        api[REPO_PATH + f"/compare/{OLD}...{NEW}"]["status"] = "diverged"
        for fetch in [unittest.mock.Mock(side_effect=SourceUnavailable("offline")),
                      api.__getitem__]:
            with self.subTest(fetch=fetch), self.assertRaises(SourceUnavailable):
                self.run_adapter(fetch)
            self.assertEqual(self.snapshot(self.parent), before)
            self.assertEqual(set(self.parent.rglob("*")), names)
        self.assert_personal()

    def test_adapter_changing_ref_zero_writes(self):
        from obsidian_github_docs_source import SourceUnavailable

        api = self.source_api()
        before = self.snapshot(self.parent)
        names = set(self.parent.rglob("*"))
        reads = 0

        def fetch(path):
            nonlocal reads
            if path.endswith("/git/ref/heads/master"):
                reads += 1
                if reads == 2:
                    return {"object": {"type": "commit", "sha": "f" * 40}}
            return api[path]

        with self.assertRaisesRegex(SourceUnavailable, "master_changed"):
            self.run_adapter(fetch)
        self.assertEqual(self.snapshot(self.parent), before)
        self.assertEqual(set(self.parent.rglob("*")), names)
        self.assert_personal()

    def test_adapter_spoofed_evidence_refused(self):
        from obsidian_github_docs_source import PreparedDocs

        prepared = PreparedDocs(OLD, NEW, "forward", bundle(), True)
        before = self.snapshot(self.parent)
        for changes in [dict(previously_sealed_commit=NEW), dict(docs=bundle(OLD)),
                        dict(ancestry="diverged"), dict(source_ref_stable=False),
                        dict(intended_commit=OLD, docs=bundle(OLD))]:
            with self.subTest(changes=changes), patch(
                "obsidian_simple_mirror.prepare_current_docs",
                return_value=replace(prepared, **changes),
            ), patch("obsidian_simple_mirror.mirror_once") as mirror:
                with self.assertRaises(ValueError):
                    self.run_adapter(self.source_api().__getitem__)
                mirror.assert_not_called()
            self.assertEqual(self.snapshot(self.parent), before)

    def test_adapter_guard_and_seal_precede_source(self):
        fetch = unittest.mock.Mock(side_effect=AssertionError("unexpected fetch"))
        for changes in [dict(local_evaluation_approved=False),
                        dict(expected_vault=self.parent / "Other")]:
            with self.assertRaises(ValueError):
                self.run_adapter(fetch, **changes)
        (self.managed / "AGENTS.md").write_bytes(b"edited")
        with self.assertRaises(ValueError):
            self.run_adapter(fetch)
        fetch.assert_not_called()

    def test_adapter_stage_and_mirror_errors_never_masked(self):
        from obsidian_github_docs_source import SourceUnavailable

        with patch("obsidian_simple_mirror.mirror_once",
                   side_effect=SourceUnavailable("synthetic mirror error")):
            with self.assertRaisesRegex(SourceUnavailable, "mirror error"):
                self.run_adapter(self.source_api().__getitem__)
        with patch("obsidian_simple_mirror.stage_only_verified_docs",
                   side_effect=OSError("synthetic stage error")):
            with self.assertRaisesRegex(OSError, "stage error"):
                self.run_adapter(self.source_api().__getitem__)
        self.assertTrue((self.parent / ".Synthetic Vault-homehub-refresh.lock").exists())
        self.assertEqual(self.snapshot(self.managed), self.before)
        self.assert_personal()

    def test_success_backup_before_write_and_preservation(self):
        real_replace = os.replace
        calls = []

        def checked_replace(src, dest):
            backups = [p for p in self.parent.glob(".*-homehub-backup-*")
                       if p != self.historical]
            self.assertEqual(len(backups), 1)
            self.assertEqual(self.snapshot(backups[0]), self.before)
            self.assertEqual(verify_sealed(backups[0])["source_commit"], OLD)
            self.assertTrue((self.parent / ".Synthetic Vault-homehub-simple.pending").exists())
            calls.append(Path(dest).name)
            real_replace(src, dest)

        (self.managed / "docs/README.md").chmod(stat.S_IREAD)
        with patch("obsidian_simple_mirror.os.replace", side_effect=checked_replace):
            result = self.run_mirror()
        self.assertEqual(calls[-1], MANIFEST)
        self.assertEqual(verify_sealed(self.managed)["source_commit"], NEW)
        self.assertEqual(self.snapshot(result.backup), self.before)
        self.assertTrue(result.receipt.is_file())
        self.assertFalse(list(self.parent.glob("*.lock")))
        self.assert_personal()
        # Successful evidence does not block a subsequent forward update.
        self.run_mirror(docs=bundle("d" * 40), authenticated_sha="d" * 40,
                        authenticated_forward_from=NEW)
        self.assertEqual(self.snapshot(result.backup), self.before)

    def test_no_op_refused_without_writes(self):
        names = set(self.parent.iterdir())
        with self.assertRaisesRegex(ValueError, "no_op"):
            self.run_mirror(docs=bundle(OLD), authenticated_sha=OLD)
        self.assertEqual(set(self.parent.iterdir()), names)

    def test_edited_file_and_rogue_file_or_directory_refused(self):
        for name, directory in [("rogue.md", False), ("empty", True)]:
            with self.subTest(name=name):
                path = self.managed / name
                path.mkdir() if directory else path.write_bytes(b"unknown")
                with self.assertRaises(ValueError):
                    self.run_mirror()
                path.rmdir() if directory else path.unlink()
        (self.managed / "AGENTS.md").write_bytes(b"edited")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.run_mirror()
        self.assertFalse(list(self.parent.glob("*.lock")))
        self.assert_personal()

    def test_reparse_directory_refused_without_traversal(self):
        # Model a Windows junction attribute without creating host junctions.
        real_lstat = Path.lstat
        target = self.managed / "docs"

        def reparse(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if path == target:
                from types import SimpleNamespace
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with patch.object(Path, "lstat", reparse):
            with self.assertRaisesRegex(ValueError, "reparse"):
                self.run_mirror()
        self.assertEqual(self.snapshot(self.managed), self.before)

    def test_interruption_preserves_evidence_and_refuses_retry(self):
        real_replace = os.replace
        count = 0

        def interrupt(src, dest):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("synthetic interruption")
            real_replace(src, dest)

        with patch("obsidian_simple_mirror.os.replace", side_effect=interrupt):
            with self.assertRaisesRegex(OSError, "synthetic"):
                self.run_mirror()
        evidence = set(self.parent.iterdir())
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.run_mirror()
        self.assertEqual(set(self.parent.iterdir()), evidence)
        self.assertTrue((self.parent / ".Synthetic Vault-homehub-simple.pending").exists())
        self.assert_personal()

    def test_bad_source_and_missing_trust_refused_before_writes(self):
        bad = replace(bundle(), contents={**FILES, "AGENTS.md": b"bad"})
        for changes in [dict(docs=bad), dict(source_ref_stable=False),
                        dict(local_evaluation_approved=False),
                        dict(source_identity_verified=False),
                        dict(authenticated_forward_from="e" * 40),
                        dict(authenticated_sha="e" * 40),
                        dict(expected_vault=self.parent / "Other")]:
            with self.subTest(changes=list(changes)):
                with self.assertRaises(ValueError):
                    self.run_mirror(**changes)
                self.assertEqual(self.snapshot(self.managed), self.before)
                self.assertFalse(list(self.parent.glob("*.lock")))

    def seed_former(self, name):
        target = self.managed / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"former")
        (self.managed / MANIFEST).unlink()
        seal(self.managed, OLD)
        self.before = self.snapshot(self.managed)

    def test_remove_document_keeps_docs_and_readonly_supported(self):
        self.seed_former("docs/obsolete.md")
        target = self.managed / "docs/obsolete.md"
        target.chmod(stat.S_IREAD)
        files = {k: v for k, v in FILES.items() if k != "docs/obsolete.md"}
        result = self.run_mirror(docs=bundle(contents=files))
        self.assertFalse(target.exists())
        self.assertTrue((self.managed / "docs").is_dir())
        self.assertEqual(self.snapshot(result.backup), self.before)
        verify_sealed(self.managed)
        self.assert_personal()

    def test_remove_last_nested_document_prunes_deepest_first(self):
        self.seed_former("docs/former/nested/page.md")
        real_rmdir = Path.rmdir
        removed = []

        def checked_rmdir(path):
            if path.is_relative_to(self.managed):
                self.assertEqual(list(path.iterdir()), [])
                removed.append(path.relative_to(self.managed).as_posix())
            return real_rmdir(path)

        with patch.object(Path, "rmdir", checked_rmdir):
            result = self.run_mirror()
        self.assertEqual(removed, ["docs/former/nested", "docs/former"])
        self.assertEqual(self.snapshot(result.backup), self.before)
        verify_sealed(self.managed)
        self.assert_personal()

    def test_mixed_add_modify_remove_and_new_directory(self):
        self.seed_former("docs/former/nested/page.md")
        files = {**FILES, "docs/README.md": b"modified", "docs/new/page.md": b"added"}
        result = self.run_mirror(docs=bundle(contents=files))
        self.assertFalse((self.managed / "docs/former").exists())
        self.assertEqual((self.managed / "docs/new/page.md").read_bytes(), b"added")
        self.assertEqual((self.managed / "docs/README.md").read_bytes(), b"modified")
        self.assertEqual(self.snapshot(result.backup), self.before)
        verify_sealed(self.managed)
        self.assert_personal()

    def test_edited_former_file_refused_before_modification(self):
        self.seed_former("docs/obsolete.md")
        (self.managed / "docs/obsolete.md").write_bytes(b"local edit")
        before = self.snapshot(self.parent)
        files = {k: v for k, v in FILES.items() if k != "docs/obsolete.md"}
        with self.assertRaises(ValueError):
            self.run_mirror(docs=bundle(contents=files))
        self.assertEqual(self.snapshot(self.parent), before)

    def test_retirement_interruption_preserves_backup_and_evidence(self):
        self.seed_former("docs/obsolete.md")
        real_unlink = Path.unlink
        files = {k: v for k, v in FILES.items() if k != "docs/obsolete.md"}

        def interrupted(path, *args, **kwargs):
            if path == self.managed / "docs/obsolete.md":
                self.assertTrue((self.parent / ".Synthetic Vault-homehub-simple.pending").exists())
                real_unlink(path, *args, **kwargs)
                raise PermissionError("synthetic retirement sharing failure")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", interrupted):
            with self.assertRaisesRegex(PermissionError, "retirement"):
                self.run_mirror(docs=bundle(contents=files))
        backups = [p for p in self.parent.glob(".*-homehub-backup-*")
                   if p != self.historical]
        self.assertEqual(self.snapshot(backups[0]), self.before)
        self.assertEqual(verify_sealed(backups[0])["source_commit"], OLD)
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.before[MANIFEST])
        evidence = self.snapshot(self.parent)
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.run_mirror(docs=bundle(contents=files))
        self.assertEqual(self.snapshot(self.parent), evidence)
        self.assert_personal()

    def test_former_file_edit_during_update_preserved(self):
        self.seed_former("docs/obsolete.md")
        real_replace = os.replace

        def edit_former(src, dest):
            real_replace(src, dest)
            if Path(dest) == self.managed / "docs/README.md":
                (self.managed / "docs/obsolete.md").write_bytes(b"late local edit")

        with patch("obsidian_simple_mirror.os.replace", side_effect=edit_former):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.run_mirror()
        self.assertEqual((self.managed / "docs/obsolete.md").read_bytes(), b"late local edit")
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.before[MANIFEST])
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.run_mirror()
        self.assert_personal()

    def test_retirement_rogue_residue_preserved(self):
        self.seed_former("docs/former/page.md")
        real_unlink = Path.unlink

        def rogue(path, *args, **kwargs):
            result = real_unlink(path, *args, **kwargs)
            if path == self.managed / "docs/former/page.md":
                (path.parent / "personal.txt").write_bytes(b"unknown")
            return result

        with patch.object(Path, "unlink", rogue):
            with self.assertRaisesRegex(ValueError, "not_empty"):
                self.run_mirror()
        self.assertEqual((self.managed / "docs/former/personal.txt").read_bytes(), b"unknown")
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.before[MANIFEST])
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.run_mirror()
        self.assert_personal()

    def test_retirement_alias_and_file_directory_collision_preflight(self):
        self.seed_former("docs/obsolete.md")
        for name in ["docs/OBSOLETE.md", "docs/obsolete.md/child.md"]:
            files = {k: v for k, v in FILES.items() if k != "docs/obsolete.md"}
            files[name] = b"replacement"
            before = self.snapshot(self.parent)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.run_mirror(docs=bundle(contents=files))
            self.assertEqual(self.snapshot(self.parent), before)

    def test_addition_existing_directory(self):
        self.check_addition("docs/extra.md")

    def test_addition_nested_directory(self):
        real_mkdir = Path.mkdir
        created = []

        def checked_mkdir(path, *args, **kwargs):
            if path.is_relative_to(self.managed):
                backups = [p for p in self.parent.glob(".*-homehub-backup-*")
                           if p != self.historical]
                self.assertEqual(len(backups), 1)
                self.assertEqual(self.snapshot(backups[0]), self.before)
                self.assertEqual(verify_sealed(backups[0])["source_commit"], OLD)
                self.assertTrue((self.parent / ".Synthetic Vault-homehub-simple.pending").exists())
                self.assertFalse(kwargs.get("parents", False))
                created.append(path.relative_to(self.managed).as_posix())
            return real_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", checked_mkdir):
            self.check_addition("docs/new/nested/extra.md")
        self.assertEqual(created, ["docs/new", "docs/new/nested"])

    def test_concurrent_addition_preserved(self):
        from obsidian_simple_mirror import _create

        name = "docs/extra.md"

        def create_concurrent(path, raw):
            identity = _create(path, raw)
            if path.parent == self.managed / "docs" and path.name.startswith("extra.md.simple-"):
                (self.managed / name).write_bytes(b"concurrent note")
            return identity

        with patch("obsidian_simple_mirror._create", side_effect=create_concurrent):
            with self.assertRaisesRegex(ValueError, "not_absent"):
                self.run_mirror(docs=bundle(contents={**FILES, name: b"new page"}))
        self.assertEqual((self.managed / name).read_bytes(), b"concurrent note")
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.before[MANIFEST])
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.run_mirror()


    def check_addition(self, name):
        files = {**FILES, name: b"new page"}
        result = self.run_mirror(docs=bundle(contents=files))
        self.assertEqual((self.managed / name).read_bytes(), b"new page")
        self.assertEqual(set(verify_sealed(self.managed)["sha256"]),
                         set(files) | set(expected_generated_pages(bundle(contents=files))))
        self.assertEqual(self.snapshot(result.backup), self.before)
        self.assert_personal()

    def test_addition_namespace_aliases_refused_before_writes(self):
        for name in ["docs/readme.md", "docs/DIR/a.md", "docs/README.md/child.md",
                     "docs/SHORT~1.md", "docs/COM?.md"]:
            files = {**FILES, "docs/dir/b.md": b"b", name: b"extra"}
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.run_mirror(docs=bundle(contents=files))
            self.assertEqual(self.snapshot(self.managed), self.before)
            self.assertFalse(list(self.parent.glob("*.lock")))

    def test_interrupt_after_add_preserves_evidence(self):
        real_replace = os.replace
        name = "docs/new/nested/extra.md"

        def interrupt(src, dest):
            real_replace(src, dest)
            if Path(dest) == self.managed / name:
                raise OSError("synthetic after addition")

        docs = bundle(contents={**FILES, name: b"new page"})
        with patch("obsidian_simple_mirror.os.replace", side_effect=interrupt):
            with self.assertRaisesRegex(OSError, "after addition"):
                self.run_mirror(docs=docs)
        self.assertEqual((self.managed / name).read_bytes(), b"new page")
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.before[MANIFEST])
        backups = [p for p in self.parent.glob(".*-homehub-backup-*")
                   if p != self.historical]
        self.assertEqual(self.snapshot(backups[0]), self.before)
        evidence = set(self.parent.iterdir())
        self.assertTrue((self.parent / ".Synthetic Vault-homehub-simple.pending").exists())
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.run_mirror(docs=docs)
        self.assertEqual(set(self.parent.iterdir()), evidence)
        self.assert_personal()

    def test_sealed_walk_enumeration_failure_propagates(self):
        from obsidian_simple_mirror import _sealed

        def unreadable(*args, **kwargs):
            kwargs["onerror"](PermissionError("synthetic unreadable subtree"))
            return iter(())

        with patch("obsidian_simple_mirror.os.walk", side_effect=unreadable):
            with self.assertRaisesRegex(PermissionError, "unreadable"):
                _sealed(self.managed)
        self.assertEqual(self.snapshot(self.managed), self.before)

    def test_existing_lock_stage_or_pending_refused(self):
        for tail in ["refresh.lock", "stage-" + "0" * 32,
                     "simple.pending", "simple.incomplete"]:
            path = self.parent / (".Synthetic Vault-homehub-" + tail)
            path.write_bytes(b"unknown evidence")
            with self.assertRaisesRegex(ValueError, "evidence"):
                self.run_mirror()
            self.assertEqual(path.read_bytes(), b"unknown evidence")
            path.unlink()
        self.assertEqual(self.snapshot(self.managed), self.before)

    def test_edit_immediately_before_replace_is_preserved(self):
        from obsidian_simple_mirror import _create

        def edit(path, raw):
            identity = _create(path, raw)
            if path.name.startswith("SNAPSHOT.md.simple-"):
                (self.managed / "SNAPSHOT.md").write_bytes(b"concurrent edit")
            return identity

        with patch("obsidian_simple_mirror._create", side_effect=edit):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.run_mirror()
        self.assertEqual((self.managed / "SNAPSHOT.md").read_bytes(), b"concurrent edit")
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.run_mirror()

    def test_backup_failure_never_changes_managed_bytes(self):
        from obsidian_simple_mirror import _create

        def fail_backup(path, raw):
            if "backup-" in path.parent.name:
                raise OSError("synthetic backup failure")
            return _create(path, raw)

        with patch("obsidian_simple_mirror._create", side_effect=fail_backup):
            with self.assertRaisesRegex(OSError, "backup failure"):
                self.run_mirror()
        self.assertEqual(self.snapshot(self.managed), self.before)
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.run_mirror()

    def test_all_new_bytes_checked_before_manifest_publication(self):
        real_replace = os.replace

        def edit_after_replace(src, dest):
            real_replace(src, dest)
            if Path(dest).name == "SNAPSHOT.md":
                (self.managed / "AGENTS.md").write_bytes(b"late edit")

        with patch("obsidian_simple_mirror.os.replace", side_effect=edit_after_replace):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.run_mirror()
        self.assertEqual((self.managed / MANIFEST).read_bytes(), self.before[MANIFEST])
        self.assert_personal()


if __name__ == "__main__":
    unittest.main()
