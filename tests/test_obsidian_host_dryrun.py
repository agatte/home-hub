"""No host-write path may emerge from a read-only dry-run."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from obsidian_host_dryrun import inspect_host_refresh_dryrun
from obsidian_host_identity import IdentityEvidence
from obsidian_process_probe import ProcessObservation

OLD = "d" * 40
NEW = "a" * 40


class HostDryRunTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hh399-host-dryrun-")
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name) / "Vault"
        self.vault.mkdir()

    def report(self, state="eligible_for_authorized_host_preflight", allowed=False):
        return (
            SimpleNamespace(state=state, refresh_authorized=allowed),
            SimpleNamespace(previously_sealed_commit=OLD, intended_commit=NEW,
                            refresh_authorized=False)
        )

    def run_case(self, identity=None, process=None, source=None):
        return inspect_host_refresh_dryrun(
            vault=self.vault, expected_vault=self.vault,
            expected_user_sid="S-1-5-21-10-20-30-1001",
            identity_probe=identity or (lambda: IdentityEvidence(
                "matched", "fixture", True, True, True, False)),
            process_probe=process or (lambda: ProcessObservation("closed", reason="fixture")),
            source_probe=source or (lambda: self.report()),
        )

    def test_candidate_is_review_only(self):
        r = self.run_case()
        self.assertEqual(r.status, "review_required")
        self.assertEqual(r.existing_commit, OLD)
        self.assertEqual(r.candidate_commit, NEW)
        self.assertFalse(r.host_automation_authorized)

    def test_same_head_is_no_change_and_never_write(self):
        r = self.run_case(source=lambda: self.report("no_change"))
        self.assertEqual(r.status, "no_change")
        self.assertFalse(r.host_automation_authorized)

    def test_foreign_sid_skips_network_and_process(self):
        def forbidden():
            self.fail("no more probes should run")
        r = self.run_case(
            identity=lambda: IdentityEvidence("refused", "owner_mismatch"),
            process=forbidden, source=forbidden,
        )
        self.assertEqual(r.status, "deferred")

    def test_unknown_identity_skips_network(self):
        r = self.run_case(identity=lambda: (_ for _ in ()).throw(PermissionError()))
        self.assertEqual(r.status, "unknown")

    def test_inconsistent_identity_details_refuses(self):
        r = self.run_case(identity=lambda: IdentityEvidence(
            "matched", "malformed", True, False, True, False))
        self.assertEqual(r.status, "deferred")

    def test_open_unknown_or_incomplete_process_skips_network(self):
        for state in ("open", "unknown", "invalid"):
            with self.subTest(state=state):
                r = self.run_case(
                    process=lambda: ProcessObservation(state, reason="fixture"),
                    source=lambda: self.fail("must not fetch"),
                )
                self.assertEqual(r.status, "deferred")

    def test_process_probe_exception_is_unknown(self):
        r = self.run_case(process=lambda: 1 / 0)
        self.assertEqual(r.status, "unknown")

    def test_unexpected_permission_refuses(self):
        r = self.run_case(source=lambda: self.report(allowed=True))
        self.assertEqual(r.status, "unknown")
        self.assertFalse(r.host_automation_authorized)

    def test_source_fetch_or_manifest_failure_is_unknown(self):
        r = self.run_case(source=lambda: 1 / 0)
        self.assertEqual(r.status, "unknown")

    def test_noneligible_source_defers(self):
        r = self.run_case(source=lambda: self.report("deferred"))
        self.assertEqual(r.status, "deferred")
        self.assertFalse(r.host_automation_authorized)


if __name__ == "__main__":
    unittest.main()
