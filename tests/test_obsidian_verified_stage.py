"""Disposable stage fixtures; no real Vault, Git checkout, network, or devices."""

import json
import importlib.util
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from obsidian_verified_stage import stage_only_verified_docs
from test_obsidian_refresh_policy import bundle, FILES


# Only needed while the offline candidate is outside the real repo. In the
# integrated HomeHub tree these imports refer to the production implementations.
fixture_manager = types.ModuleType("manage_obsidian_vault")

def reject_link(path):
    if path.is_symlink():
        raise ValueError("linked_path_refused")

def seal(stage, sha):
    files = {
        p.relative_to(stage).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in stage.rglob("*") if p.is_file()
    }
    (stage / ".homehub-snapshot-manifest.json").write_text(
        json.dumps({"schema": 1, "source_commit": sha, "sha256": files}), encoding="utf-8"
    )

def verify_sealed(stage):
    manifest = json.loads((stage / ".homehub-snapshot-manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest["sha256"].items():
        assert sha256((stage / name).read_bytes()).hexdigest() == digest
    return manifest

fixture_manager.reject_link = reject_link
fixture_manager.seal = seal
fixture_manager.verify_sealed = verify_sealed
fixture_pilot = types.ModuleType("create_obsidian_pilot")
fixture_pilot.LANDING = "# HomeHub Knowledge — preview\n"


class StagingOnlyTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(prefix="homehub-399-stage-")
        self.addCleanup(self.root.cleanup)
        self.parent = Path(self.root.name)
        self.vault = self.parent / "Permanent Vault"
        self.vault.mkdir()
        (self.vault / "HomeHub Source").mkdir()
        (self.vault / "HomeHub Source" / "old.md").write_bytes(b"OLD")
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "app.json").write_bytes(b"settings")
        (self.vault / "Private Idea.md").write_bytes(b"private notes")
        # In an actual HomeHub checkout, test against the real production
        # generator/manifest functions. Offline artifact-only review has no
        # repository checkout, so use explicit minimal stubs in that case.
        if importlib.util.find_spec("manage_obsidian_vault") is None:
            self.manager = patch.dict(sys.modules, {
                "manage_obsidian_vault": fixture_manager,
                "create_obsidian_pilot": fixture_pilot,
            })
            self.manager.start()
            self.addCleanup(self.manager.stop)

    def stage(self, **kwargs):
        args = {
            "vault": self.vault, "docs": bundle(),
            "stage_suffix": "1" * 32, "source_identity_verified": True,
        }
        args.update(kwargs)
        return stage_only_verified_docs(**args)

    def assert_old_untouched(self):
        self.assertEqual((self.vault / "Private Idea.md").read_bytes(), b"private notes")
        self.assertEqual((self.vault / ".obsidian" / "app.json").read_bytes(), b"settings")
        self.assertEqual((self.vault / "HomeHub Source" / "old.md").read_bytes(), b"OLD")

    def test_stage_sealed_without_swapping_or_touching_user_content(self):
        outcome = self.stage()
        self.assertFalse(outcome.refresh_authorized)
        self.assertEqual(outcome.document_count, 4)
        self.assertEqual(outcome.location.parent, self.parent)
        self.assertEqual((outcome.location / "docs" / "README.md").read_bytes(), FILES["docs/README.md"])
        import manage_obsidian_vault as real_or_stub_manager
        self.assertEqual(
            real_or_stub_manager.verify_sealed(outcome.location)["source_commit"],
            bundle().commit,
        )
        self.assert_old_untouched()

    def test_duplicate_stage_refused_no_overwrite(self):
        stage = self.stage().location
        (stage / "keep.txt").write_bytes(b"KEEP")
        with self.assertRaises(FileExistsError):
            self.stage()
        self.assertEqual((stage / "keep.txt").read_bytes(), b"KEEP")
        self.assert_old_untouched()

    def test_bad_source_identity_prevents_stage(self):
        with self.assertRaisesRegex(ValueError, "source_identity_unverified"):
            self.stage(source_identity_verified=False)
        self.assertEqual(list(self.parent.glob(".*-homehub-stage-*")), [])
        self.assert_old_untouched()

    def test_bad_stage_suffix_prevents_stage(self):
        with self.assertRaisesRegex(ValueError, "invalid_stage_suffix"):
            self.stage(stage_suffix="../anything")
        self.assertEqual(list(self.parent.glob(".*-homehub-stage-*")), [])
        self.assert_old_untouched()

    def test_untrusted_blob_prevents_stage(self):
        from dataclasses import replace
        bad = replace(bundle(), contents={**FILES, "AGENTS.md": b"tampered"})
        with self.assertRaisesRegex(ValueError, "git_blob"):
            self.stage(docs=bad)
        self.assertEqual(list(self.parent.glob(".*-homehub-stage-*")), [])
        self.assert_old_untouched()

    def test_linked_vault_refused(self):
        link = self.parent / "linked"
        try:
            link.symlink_to(self.vault, target_is_directory=True)
        except OSError:
            self.skipTest("no symlink privilege")
        with self.assertRaisesRegex(ValueError, "invalid_existing_vault_path|linked_path_refused|Refusing linked path"):
            self.stage(vault=link)
        self.assert_old_untouched()

    def test_stage_seal_failure_keeps_partial_stage_and_original(self):
        from unittest.mock import patch
        import manage_obsidian_vault

        with patch.object(
            manage_obsidian_vault, "seal", side_effect=OSError("synthetic sealing failure")
        ), self.assertRaisesRegex(OSError, "synthetic sealing failure"):
            self.stage(stage_suffix="2" * 32)
        stage = self.parent / f".{self.vault.name}-homehub-stage-{'2' * 32}"
        self.assertTrue(stage.is_dir())
        self.assertTrue((stage / "AGENTS.md").is_file())
        self.assert_old_untouched()


if __name__ == "__main__":
    unittest.main()
