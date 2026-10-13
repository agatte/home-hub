"""Read-only #399 preflight against real manager and disposable Vaults."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from manage_obsidian_vault import MANAGED, seal
from obsidian_refresh_preflight import _verified_manifest, inspect_refresh_readonly, PreflightRefused
from obsidian_github_docs_source import SourceUnavailable, REPO_PATH
from test_obsidian_github_docs_source import fake_payloads, COMMIT, FILES


class ReadOnlyPreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="homehub-399-preflight-")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.vault = self.folder / "Persistent Vault"
        self.managed = self.vault / MANAGED
        self.managed.mkdir(parents=True)
        for name, content in FILES.items():
            dest = self.managed.joinpath(*name.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        (self.managed / "00-START-HERE.md").write_text("# Landing\n", encoding="utf-8")
        (self.managed / "SNAPSHOT.md").write_text("# Provenance\n", encoding="utf-8")
        self.old_commit = "d" * 40
        seal(self.managed, self.old_commit)
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "app.json").write_bytes(b"personal settings")
        (self.vault / "Idea.md").write_bytes(b"private")

    def fetcher(self):
        api = fake_payloads()
        api[REPO_PATH + "/compare/" + self.old_commit + "..." + COMMIT] = {
            "status": "ahead", "base_commit": {"sha": self.old_commit},
            "merge_base_commit": {"sha": self.old_commit},
        }
        return api.__getitem__

    def snapshot(self):
        return (
            (self.vault / "Idea.md").read_bytes(),
            (self.vault / ".obsidian" / "app.json").read_bytes(),
            (self.managed / "AGENTS.md").read_bytes(),
            _verified_manifest(self.vault, self.vault),
        )

    def inspect(self, *, probe=lambda: "closed", **changes):
        arguments = {
            "vault": self.vault, "expected_vault": self.vault,
            "app_state_probe": probe, "fetch": self.fetcher(),
        }
        arguments.update(changes)
        return inspect_refresh_readonly(**arguments)

    def test_forward_closed_returns_advisory_no_permission(self):
        before = self.snapshot()
        assessment, prepared = self.inspect()
        self.assertEqual(assessment.state, "eligible_for_authorized_host_preflight")
        self.assertEqual(prepared.intended_commit, COMMIT)
        self.assertFalse(assessment.refresh_authorized)
        self.assertFalse(prepared.refresh_authorized)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(list(self.folder.glob(".*-homehub-stage-*")))

    def test_unknown_and_open_defer_without_writes(self):
        before = self.snapshot()
        probes = [
            lambda: "open", lambda: "unknown", lambda: None, lambda: "CLOSED",
            lambda: 42, lambda: (_ for _ in ()).throw(PermissionError("deny")),
        ]
        for probe in probes:
            with self.subTest(probe=str(probe)):
                assessment, _ = self.inspect(probe=probe)
                self.assertEqual(assessment.state, "deferred")
                self.assertEqual(assessment.reason, "obsidian_not_proven_closed")
        self.assertEqual(before, self.snapshot())

    def test_same_commit_noop(self):
        p = self.managed / ".homehub-snapshot-manifest.json"
        old = json.loads(p.read_text(encoding="utf-8"))
        old["source_commit"] = COMMIT
        p.write_text(json.dumps(old), encoding="utf-8")
        assessment, _ = self.inspect()
        self.assertEqual(assessment.state, "no_change")
        self.assertFalse(assessment.refresh_authorized)

    def test_tamper_refused_before_fetch(self):
        (self.managed / "AGENTS.md").write_bytes(b"TAMPERED")
        def no_fetch(_):
            self.fail("fetch must not happen")
        with self.assertRaisesRegex(ValueError, "Managed file changed"):
            self.inspect(fetch=no_fetch)

    def test_wrong_vault_refused(self):
        with self.assertRaisesRegex(PreflightRefused, "exact_vault_identity"):
            self.inspect(expected_vault=self.folder / "different")

    def test_linked_vault_refused(self):
        link = self.folder / "linked"
        try:
            link.symlink_to(self.vault, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks not permitted")
        with self.assertRaisesRegex(ValueError, "Refusing linked path"):
            self.inspect(vault=link, expected_vault=link)

    def test_master_changed_during_fetch_refused(self):
        api = fake_payloads()
        api[REPO_PATH + "/compare/" + self.old_commit + "..." + COMMIT] = {
            "status": "ahead", "base_commit": {"sha": self.old_commit},
            "merge_base_commit": {"sha": self.old_commit},
        }
        count = [0]
        def changing(path):
            if path == REPO_PATH + "/git/ref/heads/master":
                count[0] += 1
                if count[0] == 2:
                    return {"object": {"type": "commit", "sha": "f" * 40}}
            return api[path]
        before = self.snapshot()
        with self.assertRaisesRegex(SourceUnavailable, "github_master_changed"):
            self.inspect(fetch=changing)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(list(self.folder.glob(".*-homehub-stage-*")))


if __name__ == "__main__":
    unittest.main()
