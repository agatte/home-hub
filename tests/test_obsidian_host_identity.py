"""Host identity SID evidence is necessary, never refresh permission."""

from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from manage_obsidian_vault import MANAGED
from obsidian_host_identity import (
    IdentityEvidence, _windows_current_identity, _windows_path_owner,
    inspect_host_identity_readonly,
)

OWN = "S-1-5-21-100-200-300-1001"
OTHER = "S-1-5-21-100-200-300-1002"


class HostIdentityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hh399-identity-")
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name) / "Vault"
        (self.vault / MANAGED).mkdir(parents=True)
        self.owners = {self.vault: OWN, self.vault / MANAGED: OWN}

    def inspect(self, sid=OWN, elevated=False, **kwargs):
        args = {
            "vault": self.vault, "expected_vault": self.vault,
            "expected_user_sid": OWN,
            "current_identity": lambda: (sid, elevated),
            "path_owner": self.owners.__getitem__,
        }
        args.update(kwargs)
        return inspect_host_identity_readonly(**args)

    def test_matching_token_and_both_owners_still_do_not_authorize(self):
        result = self.inspect()
        if os.name != "nt":
            self.assertEqual(result.state, "unknown")
        else:
            self.assertEqual(result.state, "matched")
            self.assertEqual(result.reason, "owner_and_token_match_acl_not_evaluated")
        self.assertFalse(result.dacl_evaluated)
        self.assertFalse(result.process_launch_coordinated)
        self.assertFalse(result.authorizes_host_refresh)

    def test_foreign_user_refused(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        result = self.inspect(sid=OTHER)
        self.assertEqual(result.state, "refused")
        self.assertFalse(result.process_sid_matches)

    def test_elevated_token_refused(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        result = self.inspect(elevated=True)
        self.assertEqual(result.state, "refused")
        self.assertTrue(result.process_elevated)

    def test_mismatched_managed_owner_refused(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        self.owners[self.vault / MANAGED] = OTHER
        result = self.inspect()
        self.assertEqual(result.state, "refused")
        self.assertFalse(result.managed_owner_matches)

    def test_mismatched_vault_owner_refused(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        self.owners[self.vault] = OTHER
        self.assertEqual(self.inspect().state, "refused")

    def test_missing_or_invalid_exact_vault_refused(self):
        for change in (
            {"expected_vault": self.vault.parent / "Another"},
            {"expected_user_sid": ""},
            {"expected_user_sid": "localuser"},
            {"vault": self.vault.parent / "Missing"},
        ):
            with self.subTest(change=change):
                self.assertEqual(self.inspect(**change).state, "refused")

    def test_missing_vault_with_matching_expected_path_abstains(self):
        """The exact target is absent, not merely a mismatched path label."""
        missing = self.vault.parent / "Missing"
        result = self.inspect(vault=missing, expected_vault=missing)
        # Windows can directly reject an absent target. Linux cannot inspect
        # the Windows token/owner and returns unknown; neither grants writes.
        self.assertEqual(result.state, "refused" if os.name == "nt" else "unknown")
        self.assertFalse(result.authorizes_host_refresh)

    def test_security_read_denied_abstains(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        def denied(_):
            raise PermissionError("owner ACL unknown")
        self.assertEqual(self.inspect(path_owner=denied).state, "unknown")

    def test_symlinked_vault_refused(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        link = self.vault.parent / "Link"
        try:
            link.symlink_to(self.vault, target_is_directory=True)
        except OSError:
            self.skipTest("symlink privilege absent")
        self.assertEqual(self.inspect(vault=link, expected_vault=link).state, "unknown")

    def test_actual_win32_identity_and_fixture_owner_readonly(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        sid, elevated = _windows_current_identity()
        self.assertTrue(sid.startswith("S-1-"))
        self.assertIsInstance(elevated, bool)
        self.assertTrue(_windows_path_owner(self.vault).startswith("S-1-"))
        self.assertTrue(_windows_path_owner(self.vault / MANAGED).startswith("S-1-"))
        actual = inspect_host_identity_readonly(
            vault=self.vault, expected_vault=self.vault,
            expected_user_sid=sid,
        )
        self.assertIn(actual.state, ("matched", "refused", "unknown"))
        self.assertFalse(actual.authorizes_host_refresh)


if __name__ == "__main__":
    unittest.main()
