"""Fictional packets only; portable unittest, no Windows runtime imports."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import review_obsidian_relocation_cutover_evidence as reviewer


def fixture():
    complete = "a" * 32
    standalone = "b" * 32
    types = {
        reviewer.PREFIX + "backup-" + complete: "complete_backup",
        reviewer.PREFIX + "backup-" + standalone: "standalone_backup",
        reviewer.PREFIX + "complete-" + complete + ".json": "complete_receipt",
        reviewer.PREFIX + "completed-stage-" + complete: "complete_stage",
    }
    names = sorted(types)
    paths = [reviewer.OLD] + [reviewer.PARENT + "\\" + n for n in names]

    def observation(index):
        return {"volume": "a" * 16, "file_id": f"{index:032x}", "filesystem": "NTFS",
                "reparse": False, "hard_links": 1, "acl_sha256": "b" * 64,
                "acl_reviewed": True, "recursive_plain_tree": True,
                "content_sha256": "c" * 64, "seal_sha256": "d" * 64}

    records = []
    for i, path in enumerate(paths, 1):
        records.append({"path": path, "classification": (
            "vault" if i == 1 else types[names[i - 2]]
        ), "preserve": True, "coverage": "all_bytes_names_settings_personal_and_managed",
            "before": observation(i), "after": observation(i)})
    bindings = {}
    for i, kind in enumerate(("current", "proposed"), 1):
        bundle = r"C:\Users\Anthony\AppData\Local\HomeHub\ObsidianMirror" + "\\" + str(i) * 40
        bindings[kind] = {
            "exe": bundle + r"\fictional.exe", "start_in": bundle, "arguments": "",
            "python": r"C:\Users\Anthony\AppData\Local\Programs\Python\Python313\python.exe",
            "source_commit": str(i) * 40,
            **dict.fromkeys(("exe_sha256", "python_sha256", "manifest_sha256",
                             "pins_sha256", "runtime_sha256", "task_xml_sha256"), "f" * 64),
        }
    packet = {
        "schema": 1, "old": reviewer.OLD, "new": reviewer.NEW, "captured_at": 1000,
        "physical_confirmation": True, "inventory_complete": True,
        "siblings": names, "records": records,
        "parents": {reviewer.PARENT: observation(10), reviewer.NEW_PARENT: observation(11)},
        "destination_absent": True, "collisions": [],
        "task": {"name": "HomeHub Obsidian Mirror Refresh", "state": "Disabled",
                 "enabled": False, "running_instances": 0, "pending_instances": 0},
        "quiescence": {"obsidian_closed": True, "workers_drained": True,
                       "locks": [], "pending": []}, "bindings": bindings,
        "backup": {"independent_snapshot_ids": ["1" * 64, "2" * 64],
                   "protected_paths": paths, "verified": True},
        "rollback": {"old_path": reviewer.OLD, "retain_original_bundle_task_and_snapshots": True,
                     "stop_on_crash_or_drift": True, "no_auto_delete": True,
                     "restore_requires_attended_review": True},
    }
    return packet, deepcopy(names), deepcopy(bindings)


class OfflineReviewTests(unittest.TestCase):
    def review(self, packet, names, bindings, now=1100):
        result = reviewer.review_cutover_evidence(
            packet, reviewed_siblings=names, reviewed_bindings=bindings, now=now)
        self.assertEqual(result["readiness"], "OFFLINE_REVIEW_ONLY")
        for key, value in result.items():
            if key.endswith(("_authorized", "_verified")):
                self.assertIs(value, False, key)
        return result

    def test_fictional_consistency_never_authorizes_or_mutates(self):
        packet, names, bindings = fixture()
        before = deepcopy((packet, names, bindings))
        result = self.review(packet, names, bindings)
        self.assertTrue(result["packet_consistent"])
        self.assertEqual(result["reasons"], [])
        self.assertEqual((packet, names, bindings), before)
        self.assertEqual(result, self.review(packet, names, bindings))

    def test_adversarial_fields(self):
        cases = [
            (("old",), reviewer.OLD.lower(), "vault_literals"),
            (("old",), reviewer.OLD + "\\.", "vault_literals"),
            (("new",), reviewer.NEW.replace("C:", "D:"), "vault_literals"),
            (("new",), reviewer.OLD, "vault_literals"),
            (("destination_absent",), False, "destination_collision"),
            (("collisions",), [reviewer.NEW], "destination_collision"),
            (("inventory_complete",), False, "inventory_incomplete"),
            (("physical_confirmation",), False, "physical_confirmation_missing"),
            (("captured_at",), 1, "supplied_time_window"),
            (("captured_at",), 1200, "supplied_time_window"),
            (("captured_at",), True, "supplied_time_window"),
            (("records", 0, "before", "file_id"), "bad", "file_identity"),
            (("records", 0, "before", "acl_reviewed"), False, "acl_observation"),
            (("records", 0, "before", "acl_sha256"), "BAD", "acl_observation"),
            (("records", 0, "before", "reparse"), True, "filesystem_links"),
            (("records", 0, "before", "hard_links"), 2, "filesystem_links"),
            (("records", 0, "before", "hard_links"), True, "filesystem_links"),
            (("records", 0, "before", "filesystem"), "FAT32", "filesystem_links"),
            (("records", 0, "before", "content_sha256"), "x", "hash_shape"),
            (("records", 0, "after", "seal_sha256"), "0" * 64, "observation_drift"),
            (("records", 2, "after", "content_sha256"), "0" * 64, "observation_drift"),
            (("records", 0, "coverage"), "managed_only", "protected_coverage"),
            (("records", 1, "preserve"), False, "protected_path"),
            (("records", 1, "classification"), "incomplete", "unknown_or_incomplete_artifact_requires_review"),
            (("records", 2, "classification"), "unknown", "unknown_or_incomplete_artifact_requires_review"),
            (("task", "state"), "Ready", "task_not_quiescent"),
            (("task", "enabled"), True, "task_not_quiescent"),
            (("task", "running_instances"), 1, "task_not_quiescent"),
            (("task", "pending_instances"), 1, "task_not_quiescent"),
            (("quiescence", "locks"), ["refresh.lock"], "active_or_pending"),
            (("quiescence", "pending"), ["simple.pending"], "active_or_pending"),
            (("quiescence", "obsidian_closed"), False, "active_or_pending"),
            (("bindings", "proposed", "exe_sha256"), "0" * 64, "binding_drift"),
            (("bindings", "current", "arguments"), "--run", "action_literal"),
            (("bindings", "current", "python"), "python.exe", "runtime_literal"),
            (("bindings", "current", "start_in"), "C:\\alias", "bundle_literal"),
            (("backup", "verified"), False, "independent_backups"),
            (("backup", "protected_paths"), [reviewer.OLD], "independent_backups"),
            (("rollback", "no_auto_delete"), False, "rollback_contract"),
        ]
        for path, value, reason in cases:
            with self.subTest(path=path, value=value):
                packet, names, bindings = fixture()
                target = packet
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                self.assertEqual(self.review(packet, names, bindings)["reasons"], [reason])

    def test_release_label_must_match_version_directory(self):
        for kind in ("current", "proposed"):
            with self.subTest(kind=kind):
                packet, names, bindings = fixture()
                packet["bindings"][kind]["source_commit"] = "e" * 40
                bindings[kind]["source_commit"] = "e" * 40
                self.assertEqual(
                    self.review(packet, names, bindings)["reasons"],
                    ["release_label_binding"],
                )

    def test_missing_extra_and_malformed(self):
        for key in fixture()[0]:
            with self.subTest(missing=key):
                packet, names, bindings = fixture()
                del packet[key]
                self.assertEqual(self.review(packet, names, bindings)["reasons"], ["packet_shape"])
        for value in (None, [], "packet", 1):
            self.assertFalse(self.review(value, [], {})["packet_consistent"])
        for path in ((), ("task",), ("records", 0), ("records", 0, "before"),
                     ("bindings", "proposed"), ("backup",), ("rollback",)):
            packet, names, bindings = fixture()
            target = packet
            for part in path:
                target = target[part]
            target["extra"] = True
            self.assertFalse(self.review(packet, names, bindings)["packet_consistent"])

    def test_membership_bounds_and_aliases(self):
        for change in (lambda n: n.pop(), lambda n: n.append(reviewer.PREFIX + "stage-extra"),
                       lambda n: n.append(n[0].upper()), lambda n: n.reverse(),
                       lambda n: n.append("../escape"), lambda n: n.append({}),
                       lambda n: n.extend([reviewer.PREFIX + "x"] * 2049)):
            packet, names, bindings = fixture()
            change(packet["siblings"])
            self.assertFalse(self.review(packet, names, bindings)["packet_consistent"])
        packet, names, bindings = fixture()
        packet["records"].pop()
        self.assertEqual(self.review(packet, names, bindings)["reasons"], ["record_membership"])

    def test_volume_identity_and_backup_alias(self):
        for field, value, reason in (("volume", "b" * 16, "volume_mismatch"),
                                     ("file_id", f"{1:032x}", "identity_alias")):
            packet, names, bindings = fixture()
            for phase in ("before", "after"):
                packet["records"][1][phase][field] = value
            self.assertEqual(self.review(packet, names, bindings)["reasons"], [reason])
        packet, names, bindings = fixture()
        packet["backup"]["independent_snapshot_ids"] = ["1" * 64] * 2
        self.assertEqual(self.review(packet, names, bindings)["reasons"], ["independent_backups"])

    def test_unknown_name_cannot_be_reclassified_as_complete(self):
        for suffix in ("mystery-record", "stage-incomplete"):
            packet, names, bindings = fixture()
            names[0] = reviewer.PREFIX + suffix
            names.sort()
            packet["siblings"] = deepcopy(names)
            for index, name in enumerate(names, 1):
                packet["records"][index]["path"] = reviewer.PARENT + "\\" + name
                packet["records"][index]["classification"] = "complete_backup"
            self.assertEqual(self.review(packet, names, bindings)["reasons"],
                             ["unknown_or_incomplete_artifact_requires_review"])

    def test_complete_history_requires_exact_matched_triples(self):
        token = "a" * 32
        for kind, name in (
            ("backup", reviewer.PREFIX + "backup-" + token),
            ("stage", reviewer.PREFIX + "completed-stage-" + token),
            ("receipt", reviewer.PREFIX + "complete-" + token + ".json"),
        ):
            with self.subTest(missing=kind):
                packet, names, bindings = fixture()
                index = names.index(name)
                names.pop(index)
                packet["siblings"].pop(index)
                packet["records"].pop(index + 1)
                self.assertEqual(
                    self.review(packet, names, bindings)["reasons"],
                    ["incomplete_artifact_triple"],
                )

        packet, names, bindings = fixture()
        index = names.index(reviewer.PREFIX + "backup-" + token)
        packet["records"][index + 1]["classification"] = "standalone_backup"
        self.assertEqual(
            self.review(packet, names, bindings)["reasons"],
            ["incomplete_artifact_triple"],
        )

        packet, names, bindings = fixture()
        index = names.index(reviewer.PREFIX + "complete-" + token + ".json")
        wrong_receipt = reviewer.PREFIX + "complete-" + token + ".txt"
        names[index] = wrong_receipt
        packet["siblings"][index] = wrong_receipt
        packet["records"][index + 1]["path"] = reviewer.PARENT + "\\" + wrong_receipt
        self.assertEqual(
            self.review(packet, names, bindings)["reasons"],
            ["unknown_or_incomplete_artifact_requires_review"],
        )

    def test_parent_observations_and_exact_boolean_rollback(self):
        for field, value, reason in (("volume", "b" * 16, "volume_mismatch"),
                                     ("file_id", f"{1:032x}", "identity_alias"),
                                     ("reparse", True, "filesystem_links")):
            packet, names, bindings = fixture()
            packet["parents"][reviewer.NEW_PARENT][field] = value
            self.assertEqual(self.review(packet, names, bindings)["reasons"], [reason])
        packet, names, bindings = fixture()
        packet["rollback"]["no_auto_delete"] = 1
        self.assertEqual(self.review(packet, names, bindings)["reasons"], ["rollback_contract"])

    def test_supplied_time_boundaries_and_multiple_failure_order(self):
        packet, names, bindings = fixture()
        for now in (1000, 1300):
            self.assertTrue(self.review(packet, names, bindings, now)["packet_consistent"])
        for now in (999, 1301, True, None, 1000.0):
            self.assertEqual(self.review(packet, names, bindings, now)["reasons"],
                             ["supplied_time_window"])
        packet["old"] = "alias"
        packet["physical_confirmation"] = False
        self.assertEqual(self.review(packet, names, bindings)["reasons"], ["vault_literals"])


if __name__ == "__main__":
    unittest.main()
