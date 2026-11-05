"""#489 Windows Sandbox NTFS synthetic exclusive-stage rehearsal, never host."""
from __future__ import annotations

import base64
import copy
from hashlib import sha256
import os
from pathlib import Path
import sys
from uuid import uuid4
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import obsidian_relocation_stage_rehearsal as rehearsal
import prepare_obsidian_relocation as recipe


@unittest.skipUnless(
    os.name == "nt" and Path.home() == rehearsal.GUEST_TEMP.parents[2],
    "Native fixture runs only in the protected Windows Sandbox guest",
)
class StageRehearsalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_pins = (ROOT / "scripts" / "obsidian_launcher_pins.json").read_bytes()
        cls.old_modules = {
            name: (ROOT / "scripts" / name).read_bytes()
            for name in recipe.MODULE_FILES
        }
        cls.old_native = base64.b64decode(
            (ROOT / "tests" / "obsidian_hidden_launcher_baseline.b64").read_text(encoding="ascii"),
            validate=True,
        )

    def setUp(self):
        self.identity = dict(rehearsal.SYNTHETIC_IDENTITY)
        self.generated = recipe.bundle_recipe(
            self.old_modules, self.old_pins, self.old_native, self.identity
        )
        self.ticket = uuid4().hex
        self.dir = rehearsal.GUEST_TEMP / (rehearsal.FIXTURE_PREFIX + self.ticket)

    def stage(self, **kwargs):
        return rehearsal.rehearse_exclusive_sandbox_stage(
            self.old_modules, self.old_pins, self.old_native,
            self.identity, self.generated, token=self.ticket, **kwargs
        )

    def test_complete_synthetic_stage_exact_members_and_hashes(self):
        output = self.stage()
        self.assertEqual(output["status"], "SANDBOX_FIXTURE_ONLY")
        self.assertFalse(output["installable"])
        self.assertFalse(output["host_stage_authorized"])
        self.assertFalse(output["task_update_authorized"])
        self.assertFalse(output["vault_move_authorized"])
        self.assertEqual(output["files_written"], 10)
        self.assertEqual(
            {p.name for p in self.dir.iterdir()},
            frozenset(recipe.MODULE_FILES) | {"manifest.json"},
        )
        for name, data in {**self.generated["modules"],
                           "manifest.json": self.generated["manifest"]}.items():
            self.assertEqual(sha256((self.dir / name).read_bytes()).hexdigest(),
                             sha256(data).hexdigest())

    def test_existing_stage_collision_refused_and_original_bytes_preserved(self):
        self.stage()
        baseline = (self.dir / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.stage()
        self.assertEqual((self.dir / "manifest.json").read_bytes(), baseline)
        self.assertEqual(len(list(self.dir.iterdir())), 10)

    def test_preoccupied_file_target_refused_without_touching_marker(self):
        self.dir.write_text("protected existing marker", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.stage()
        self.assertEqual(self.dir.read_text(encoding="utf-8"), "protected existing marker")

    def test_injected_failure_preserves_partial_and_blocks_same_path_retry(self):
        with self.assertRaisesRegex(ValueError, "preserves_partial"):
            self.stage(fail_after=3)
        self.assertTrue(self.dir.is_dir())
        self.assertEqual(len(list(self.dir.iterdir())), 3)
        with self.assertRaises(FileExistsError):
            self.stage()

    def test_injected_failure_before_first_file_preserves_empty_directory(self):
        with self.assertRaisesRegex(ValueError, "preserves_partial"):
            self.stage(fail_after=0)
        self.assertTrue(self.dir.is_dir())
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_tampered_result_refused_before_directory_creation(self):
        self.generated = copy.deepcopy(self.generated)
        self.generated["modules"]["launch_obsidian_mirror.py"] += b"\n# tampered"
        with self.assertRaisesRegex(ValueError, "recipe_output_drift"):
            self.stage()
        self.assertFalse(self.dir.exists())

    def test_non_synthetic_identity_refused_before_creation(self):
        self.identity["python_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "synthetic_identity_only"):
            self.stage()
        self.assertFalse(self.dir.exists())

    def test_ticket_refusal_before_creation(self):
        for token in (self.ticket + "/../other", self.ticket.upper(), "0" * 31, ""):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, "ticket_invalid"):
                rehearsal.rehearse_exclusive_sandbox_stage(
                    self.old_modules, self.old_pins, self.old_native,
                    self.identity, self.generated, token=token
                )
        self.assertFalse(self.dir.exists())

    def test_invalid_failure_injection_refused_before_creation(self):
        for fail_after in (-1, 10, True, "1"):
            with self.subTest(fail_after=fail_after):
                with self.assertRaisesRegex(ValueError, "invalid_injected_failure"):
                    self.stage(fail_after=fail_after)
        self.assertFalse(self.dir.exists())

    def test_rebinding_fixture_root_toward_host_refuses_before_write(self):
        with mock.patch.object(
            rehearsal, "GUEST_TEMP",
            Path(r"C:\Users\Anthony\AppData\Local\Temp"),
        ):
            with self.assertRaisesRegex(ValueError, "sandbox_fixed_profile_and_temp_required"):
                self.stage()
        self.assertFalse(self.dir.exists())

    def test_no_cli_or_host_path_arguments(self):
        self.assertFalse(hasattr(rehearsal, "main"))
        self.assertEqual(rehearsal.GUEST_TEMP.name, "Temp")
        self.assertNotIn(r"C:\Users\Anthony", str(rehearsal.GUEST_TEMP))
        self.assertNotIn("HomeHub Vault Storage", str(rehearsal.GUEST_TEMP))


if __name__ == "__main__":
    unittest.main()
