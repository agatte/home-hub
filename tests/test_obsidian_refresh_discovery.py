"""Read-only document discovery works independently of Obsidian process state."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_obsidian_refresh_preflight as fixtures
from obsidian_refresh_discovery import inspect_docs_discovery_readonly
from obsidian_github_docs_source import REPO_PATH

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ReadOnlyPreflightTests("test_forward_closed_returns_advisory_no_permission")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def inspect(self, **changed):
        args = dict(vault=self.f.vault, expected_vault=self.f.vault,
                    fetch=self.f.fetcher())
        args.update(changed)
        return inspect_docs_discovery_readonly(**args)

    def test_new_docs_verified_without_checking_obsidian(self):
        before = self.f.snapshot()
        r = self.inspect()
        self.assertEqual(r.status, "update_discovered")
        self.assertEqual(r.reason, "verified_forward_update_not_authorized")
        self.assertEqual(r.existing_commit, self.f.old_commit)
        self.assertTrue(r.documents_verified)
        self.assertFalse(r.host_automation_authorized)
        self.assertFalse(r.stage_authorized)
        self.assertEqual(before, self.f.snapshot())
        self.assertFalse(any(self.f.folder.glob(".*-homehub-stage-*")))

    def test_noop_is_read_only_even_if_app_open(self):
        p = self.f.managed / ".homehub-snapshot-manifest.json"
        from test_obsidian_github_docs_source import COMMIT
        current = json.loads(p.read_text(encoding="utf-8"))
        current["source_commit"] = COMMIT
        p.write_text(json.dumps(current), encoding="utf-8")
        r = self.inspect()
        self.assertEqual(r.status, "no_change")
        self.assertTrue(r.documents_verified)
        self.assertFalse(r.host_automation_authorized)

    def test_wrong_exact_vault_abstains_before_network(self):
        def no_network(_):
            self.fail("network must not be called on invalid vault")
        r = self.inspect(expected_vault=self.f.folder / "wrong",fetch=no_network)
        self.assertEqual(r.status, "unknown")
        self.assertEqual(r.reason, "existing_managed_source_unverified")

    def test_tamper_abstains_before_network(self):
        (self.f.managed / "AGENTS.md").write_bytes(b"tamper")
        def no_network(_):
            self.fail("network must not be called after tampering")
        r = self.inspect(fetch=no_network)
        self.assertEqual(r.status, "unknown")
        self.assertEqual(r.reason, "existing_managed_source_unverified")

    def test_offline_abstains_preserves_notes(self):
        before = self.f.snapshot()
        def offline(_):
            raise OSError("synthetic network down")
        r = self.inspect(fetch=offline)
        self.assertEqual(r.status, "unknown")
        self.assertFalse(r.documents_verified)
        self.assertFalse(r.stage_authorized)
        self.assertEqual(before, self.f.snapshot())

    def test_changed_master_abstains(self):
        from test_obsidian_github_docs_source import fake_payloads, COMMIT
        api = fake_payloads()
        api[REPO_PATH + "/compare/" + self.f.old_commit + "..." + COMMIT] = {
            "status": "ahead", "base_commit": {"sha": self.f.old_commit},
            "merge_base_commit": {"sha": self.f.old_commit},
        }
        seen=[0]
        def raced(path):
            if path == REPO_PATH + "/git/ref/heads/master":
                seen[0]+=1
                if seen[0] == 2:
                    return {"object":{"type":"commit","sha":"f"*40}}
            return api[path]
        r = self.inspect(fetch=raced)
        self.assertEqual(r.status, "unknown")
        self.assertFalse(r.host_automation_authorized)

    def test_no_app_probe_is_needed(self):
        # Contract: function only takes Vault identity + GitHub fetcher.
        from inspect import signature
        self.assertNotIn("app_state_probe", signature(inspect_docs_discovery_readonly).parameters)

if __name__ == "__main__":
    unittest.main()
