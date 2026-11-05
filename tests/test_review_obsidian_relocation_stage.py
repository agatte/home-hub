"""Offline-only synthetic #489 staging-plan contract tests."""
from __future__ import annotations

import base64
import copy
import importlib.util
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Sandbox review can use the already-present source-only #491 worktree.
# When integrated in the repository, this defaults to the current checkout.
SOURCE = Path(os.environ.get("HH489_TEST_SOURCE_ROOT", str(ROOT)))
sys.path.insert(0, str(SOURCE / "scripts"))
sys.path.insert(0, str(ROOT / "scripts"))
import prepare_obsidian_relocation as prep

spec = importlib.util.spec_from_file_location(
    "hh489_stage_review", ROOT / "scripts" / "review_obsidian_relocation_stage.py")
assert spec is not None and spec.loader is not None
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class StagePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pins = (SOURCE / "scripts/obsidian_launcher_pins.json").read_bytes()
        cls.modules = {name: (SOURCE / "scripts" / name).read_bytes()
                       for name in prep.MODULE_FILES}
        cls.native = base64.b64decode(
            (SOURCE / "tests/obsidian_hidden_launcher_baseline.b64").read_text(encoding="ascii"),
            validate=True,
        )

    def setUp(self):
        self.identity = {"user_root": prep.USER, "python": prep.PYTHON,
                         "sid": "S-1-5-21-111-222-333-1001",
                         "python_sha256": "a" * 64}
        self.result = prep.bundle_recipe(self.modules, self.pins, self.native,
                                         self.identity)

    def preview(self, result=None, identity=None, pins=None):
        return review.review_offline_stage_plan(
            self.modules, self.pins if pins is None else pins,
            self.native, self.identity if identity is None else identity,
            self.result if result is None else result)

    def test_preview_exact_10_members_no_install_authority(self):
        plan = self.preview()
        self.assertEqual(plan["status"], "OFFLINE_REVIEW_ONLY")
        self.assertFalse(plan["installable"])
        self.assertFalse(plan["stage_authorized"])
        self.assertFalse(plan["task_update_authorized"])
        self.assertFalse(plan["vault_move_authorized"])
        self.assertEqual(len(plan["members"]), 10)
        self.assertEqual(plan["members"][-1]["name"], "manifest.json")
        self.assertEqual(plan["manifest_sha256"], prep.digest(self.result["manifest"]))
        self.assertEqual(plan["pins_sha256"], self.result["pins_sha256"])
        self.assertEqual(plan["launcher_source_sha256"], self.result["launcher_source_sha256"])

    def test_stable_repeat(self):
        self.assertEqual(self.preview(), self.preview())

    def test_mutation_of_generated_modules_refuses(self):
        tampered = copy.deepcopy(self.result)
        tampered["modules"]["launch_obsidian_mirror.py"] += b"\n# mutation"
        with self.assertRaisesRegex(ValueError, "recipe_output_drift"):
            self.preview(result=tampered)

    def test_mutated_pins_and_manifest_refuse(self):
        for field, bad in (
            ("pins", b"{}"),
            ("pins_sha256", "0" * 64),
            ("manifest", b"{}"),
            ("manifest_sha256", "0" * 64),
            ("launcher_source_sha256", "0" * 64),
            ("installable", True),
            ("status", "ready"),
        ):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.result)
                candidate[field] = bad
                with self.assertRaises(ValueError):
                    self.preview(result=candidate)

    def test_missing_or_extra_member_refuses(self):
        original = copy.deepcopy(self.result)
        key = next(iter(prep.MODULE_FILES))
        del original["modules"][key]
        with self.assertRaises(ValueError):
            self.preview(result=original)
        original = copy.deepcopy(self.result)
        original["modules"]["../escape"] = b"oops"
        with self.assertRaises(ValueError):
            self.preview(result=original)

    def test_wrong_old_pin_source_refuses(self):
        raw = self.pins + b"\n"
        with self.assertRaisesRegex(ValueError, "reviewed_old_pins"):
            self.preview(pins=raw)

    def test_untrusted_identity_change_refuses(self):
        for field, value in (
            ("user_root", r"C:\Users\Public"),
            ("python_sha256", "z" * 64),
            ("sid", "S-1-5-21-0-0-0-0"),
        ):
            with self.subTest(field=field):
                identity = dict(self.identity, **{field: value})
                with self.assertRaises(ValueError):
                    self.preview(identity=identity)

    def test_caller_cannot_add_approval_field(self):
        output = copy.deepcopy(self.result)
        output["approve_stage"] = True
        with self.assertRaisesRegex(ValueError, "unexpected_recipe_fields"):
            self.preview(result=output)


if __name__ == "__main__":
    unittest.main()
