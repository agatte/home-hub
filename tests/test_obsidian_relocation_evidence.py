"""Sandbox-only synthetic tests for #489 pure evidence contract."""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "hh489_evidence", REPO_ROOT / "scripts" / "obsidian_relocation_evidence.py")
assert spec and spec.loader
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
def raw(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
def hash_of(text):
    return sha256(text.encode()).hexdigest()

class ReceiptAndSeals(unittest.TestCase):
    def setUp(self):
        self.token = "a" * 32
        self.backup = ev.PREFIX + "backup-" + self.token
        self.old = "b" * 40
        self.new = "c" * 40
        self.receipt = {"token": self.token, "from": self.old,
                        "to": self.new, "backup": self.backup}
        self.files = {"00-START-HERE.md": hash_of("landing"),
                      "SNAPSHOT.md": hash_of("origin"),
                      "AGENTS.md": hash_of("rules"),
                      "docs/PROJECT_SPEC.md": hash_of("product")}
        self.before = {"schema": 1, "source_commit": self.old, "sha256": self.files}
        self.after = {"schema": 1, "source_commit": self.new, "sha256": self.files}

    def triplet(self, receipt=None, before=None, after=None, members=None):
        return ev.checked_triple(
            raw(self.receipt if receipt is None else receipt),
            token=self.token, backup_name=self.backup,
            backup_manifest=raw(self.before if before is None else before),
            backup_members=self.files if members is None else members,
            stage_manifest=raw(self.after if after is None else after),
            stage_members=self.files)

    def test_good_complete_receipt_and_seals_claims_only(self):
        outcome=self.triplet()
        self.assertEqual(outcome["backup_commit"],self.old)
        self.assertEqual(outcome["completed_stage_commit"],self.new)
        self.assertIn("claimed_member_hashes",outcome["evidence"])

    def test_receipt_binding_and_types_refuse(self):
        for bad in (
            dict(self.receipt, token="d"*32),
            dict(self.receipt, backup="unexpected"),
            dict(self.receipt, to=self.old),
            dict(self.receipt, to="invalid"),
            dict(self.receipt, unknown="field"),
            dict(self.receipt, **{"from":4}),
        ):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                ev.checked_receipt(raw(bad),token=self.token,backup_name=self.backup)

    def test_duplicate_receipt_key_and_oversize_refuse(self):
        duplicate=(b'{"token":"' + self.token.encode()
                   + b'","token":"' + self.token.encode()
                   + b'","from":"' + self.old.encode()
                   + b'","to":"' + self.new.encode()
                   + b'","backup":"' + self.backup.encode() + b'"}')
        with self.assertRaisesRegex(ValueError,"duplicate_json_field"):
            ev.checked_receipt(duplicate,token=self.token,backup_name=self.backup)
        with self.assertRaisesRegex(ValueError,"oversized"):
            ev.checked_receipt(b"a"*4097,token=self.token,backup_name=self.backup)

    def test_manifest_missing_extra_case_alias_and_drift_refuse(self):
        tests = [
            dict(self.before,schema=True),
            dict(self.before,source_commit="z"*40),
            dict(self.before,sha256={**self.files,"docs/foo/../bad.md":hash_of("x")}),
            dict(self.before,sha256={**self.files,"docs/CON.md":hash_of("x")}),
            dict(self.before,sha256={**self.files,"docs/A.md":hash_of("x"),"docs/a.md":hash_of("x")}),
            dict(self.before,sha256={"AGENTS.md":hash_of("x")}),
        ]
        for candidate in tests:
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):
                ev.checked_managed_manifest(raw(candidate),candidate["sha256"])
        altered=dict(self.files,**{"AGENTS.md":"f"*64})
        with self.assertRaisesRegex(ValueError,"pin"):
            ev.checked_managed_manifest(raw(self.before),altered)

    def test_duplicate_manifest_json_keys_refuse(self):
        payload=(b'{"schema":1,"schema":1,"source_commit":"' + self.old.encode()
                 + b'","sha256":{}}')
        with self.assertRaisesRegex(ValueError,"duplicate"):
            ev.checked_managed_manifest(payload,self.files)

    def test_manifest_claim_must_equal_receipt(self):
        bad=dict(self.after,source_commit="f"*40)
        with self.assertRaisesRegex(ValueError,"commit_mismatch"):
            self.triplet(after=bad)

    def test_receipt_and_manifest_limits(self):
        with self.assertRaisesRegex(ValueError,"oversized"):
            ev.checked_managed_manifest(b"x"*(128*1024+1),self.files)
        with self.assertRaisesRegex(ValueError,"invalid_utf8_json"):
            ev.checked_managed_manifest(b"\xff\xfe",self.files)

class ByteBackedEvidence(unittest.TestCase):
    def setUp(self):
        self.token = "a" * 32
        self.files = {"00-START-HERE.md": b"landing",
                      "SNAPSHOT.md": b"origin",
                      "AGENTS.md": b"rules",
                      "docs/PROJECT_SPEC.md": b"product"}
        self.pins = {key: sha256(value).hexdigest() for key, value in self.files.items()}
        self.old = "b" * 40
        self.new = "c" * 40
        self.before = raw({"schema": 1, "source_commit": self.old, "sha256": self.pins})
        self.after = raw({"schema": 1, "source_commit": self.new, "sha256": self.pins})
        self.backup = ev.PREFIX + "backup-" + self.token
        self.receipt = raw({"token": self.token, "from": self.old,
                            "to": self.new, "backup": self.backup})

    def test_byte_backed_member_hashes_and_receipt(self):
        observed = ev.checked_snapshot_bytes(self.before, self.files)
        self.assertEqual(observed["measured_bytes"], sum(map(len, self.files.values())))
        self.assertIn("bytes_hashed", observed["evidence"])
        self.assertNotIn("landing", repr(observed))
        outcome = ev.checked_triple_bytes(
            self.receipt, token=self.token, backup_name=self.backup,
            backup_manifest=self.before, backup_files=self.files,
            stage_manifest=self.after, stage_files=self.files)
        self.assertEqual(outcome["stage_commit"], self.new)
        self.assertEqual(outcome["backup_commit"], self.old)
        self.assertIn("not_host_attested", outcome["evidence"])

    def test_tampered_bytes_refused_even_if_digest_claim_unchanged(self):
        changed = dict(self.files, **{"AGENTS.md": b"tampered"})
        with self.assertRaisesRegex(ValueError, "pin"):
            ev.checked_snapshot_bytes(self.before, changed)
        changed = dict(self.files, **{"AGENTS.md": self.files["AGENTS.md"] + b" "})
        with self.assertRaisesRegex(ValueError, "pin"):
            ev.checked_snapshot_bytes(self.before, changed)

    def test_missing_extra_and_invalid_types_refuse(self):
        samples = [
            {k: v for k, v in self.files.items() if k != "AGENTS.md"},
            dict(self.files, **{"docs/new.md": b"x"}),
            dict(self.files, **{"AGENTS.md": "not raw bytes"}),
            dict(self.files, **{"AGENTS.md": bytearray(b"rules")}),
        ]
        for sample in samples:
            with self.subTest(sample=list(sample)), self.assertRaises(ValueError):
                ev.checked_snapshot_bytes(self.before, sample)

    def test_individual_size_limit(self):
        changed = dict(self.files, **{"AGENTS.md": b"x" * (3 * 1024 * 1024 + 1)})
        with self.assertRaisesRegex(ValueError, "bytes_or_size"):
            ev.checked_snapshot_bytes(self.before, changed)

    def test_total_size_limit_and_manifest_member_limit(self):
        block = b"z" * (1024 * 1024)
        members = dict(self.files)
        for i in range(31):
            members[f"docs/extra_{i}.md"] = block
        pins = {name: sha256(value).hexdigest() for name, value in members.items()}
        manifest = raw({"schema": 1, "source_commit": self.old, "sha256": pins})
        with self.assertRaisesRegex(ValueError, "snapshot_total_size"):
            ev.checked_snapshot_bytes(manifest, members)
        too_many = {f"docs/member_{i}.md": hash_of("x") for i in range(501)}
        manifest = raw({"schema": 1, "source_commit": self.old, "sha256": too_many})
        with self.assertRaisesRegex(ValueError, "snapshot_member_set"):
            ev.checked_snapshot_bytes(manifest, {name: b"x" for name in too_many})

    def test_triple_receipt_cannot_rebind_bytes(self):
        bad_receipt = raw({"token": self.token, "from": self.new,
                           "to": self.old, "backup": self.backup})
        with self.assertRaisesRegex(ValueError, "commit_mismatch"):
            ev.checked_triple_bytes(
                bad_receipt, token=self.token, backup_name=self.backup,
                backup_manifest=self.before, backup_files=self.files,
                stage_manifest=self.after, stage_files=self.files)

class TaskAndAcl(unittest.TestCase):
    def setUp(self):
        self.sid="S-1-5-21-111-222-333-1001"
        self.task={
            "task_path":"\\","name":"HomeHub Obsidian Mirror Refresh",
            "state":"Ready","principal_sid":self.sid,"run_level":"LeastPrivilege",
            "settings_enabled":True,
            "action":{
                "execute":(r"C:\Users\Anthony\AppData\Local\HomeHub\ObsidianMirror"
                           r"\HiddenLauncher\20261025\ObsidianMirrorHiddenLauncher.exe"),
                "arguments":"",
                "working_directory":(r"C:\Users\Anthony\AppData\Local\HomeHub\ObsidianMirror"
                                     r"\5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5"),
            },
            "triggers":[
                {"kind":"logon","enabled":True,"sid":self.sid},
                {"kind":"calendar","enabled":True,"interval":"PT1H",
                 "duration":"P1D","days_interval":1},
            ],
        }
    def test_task_two_trigger_shape_only(self):
        checked=ev.check_task_observation(self.task,self.sid)
        self.assertFalse(checked["quiesced"])
        self.assertFalse(checked["task_execution_authorized"])

    def test_sid_out_of_32bit_range_refuses(self):
        out_of_range = "S-1-5-21-4294967296-222-333-1001"
        with self.assertRaisesRegex(ValueError, "expected_sid"):
            ev.check_task_observation(dict(self.task, principal_sid=out_of_range),
                                      out_of_range)

    def test_task_unexpected_evidence_refuses(self):
        modifications=[
            ("state","Running"),("principal_sid","S-1-5-21-111-222-333-1002"),
            ("run_level","Highest"),("settings_enabled",False),
            ("triggers",self.task["triggers"][:1]),
            ("triggers",self.task["triggers"]+[self.task["triggers"][0]]),
            ("triggers",[self.task["triggers"][0],dict(self.task["triggers"][1], interval="PT30M")]),
            ("action",dict(self.task["action"],arguments="--run")),
            ("action",dict(self.task["action"],working_directory=r"C:\temp")),
        ]
        for key,value in modifications:
            with self.subTest(field=key,value=value), self.assertRaises(ValueError):
                ev.check_task_observation(dict(self.task,**{key:value}),self.sid)
    def test_acl_digests_are_exact_claims_not_acl_proof(self):
        before={"vault":hash_of("O:Synthetic"),"backup-name":hash_of("O:AlsoSynthetic")}
        result=ev.compare_acl_digests(before,dict(before))
        self.assertEqual(result["same_acl_digest_count"],2)
        with self.assertRaises(ValueError):
            ev.compare_acl_digests(before,dict(before, extra=hash_of("x")))
        with self.assertRaisesRegex(ValueError,"acl_digest_changed"):
            ev.compare_acl_digests(before,dict(before, vault=hash_of("changed")))
        aliased = {"Vault":hash_of("same"), "vault":hash_of("same")}
        with self.assertRaisesRegex(ValueError,"windows_case_alias"):
            ev.compare_acl_digests(aliased,dict(aliased))

if __name__ == "__main__":
    unittest.main()
