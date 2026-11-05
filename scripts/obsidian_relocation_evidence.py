"""#489 pure evidence validators. SANDBOX DRAFT; not a real-host preflight.

Memory-only checks on supplied synthetic bytes/digests; they do not read the
Windows Vault, authenticate a filesystem observation, prove quiescence, or
authorize any move, task operation, or installation.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import PurePosixPath
import re

HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PREFIX = ".HomeHub Knowledge Vault-homehub-"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_RECEIPT_BYTES = 4096
REQUIRED = frozenset({"00-START-HERE.md", "SNAPSHOT.md", "AGENTS.md", "docs/PROJECT_SPEC.md"})
RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})

def _distinct(items):
    out = {}
    for name, value in items:
        if name in out:
            raise ValueError("duplicate_json_field")
        out[name] = value
    return out

def _strict_json(raw: bytes, cap: int):
    if type(raw) is not bytes or not 1 <= len(raw) <= cap:
        raise ValueError("missing_or_oversized_json")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_distinct)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid_utf8_json") from error

def _safe_managed_name(name: str) -> bool:
    if type(name) is not str or not name or len(name) > 300 or "\\" in name:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        return False
    parts = name.split("/")
    if any(not part or part in {".", ".."} or part.endswith((".", " "))
           or "~" in part or any(c in part for c in '<>:"|?*')
           or part.split(".", 1)[0].upper() in RESERVED
           for part in parts):
        return False
    p = PurePosixPath(name)
    if p.is_absolute() or p.as_posix() != name or p.suffix.lower() != ".md":
        return False
    return name in {"00-START-HERE.md", "SNAPSHOT.md", "AGENTS.md"} or name.startswith("docs/")

def checked_receipt(raw: bytes, *, token: str, backup_name: str) -> dict[str, str]:
    """Validate a receipt's *supplied bytes*. This does not authenticate disk I/O."""
    if type(token) is not str or not HEX32.fullmatch(token):
        raise ValueError("token")
    if backup_name != PREFIX + "backup-" + token:
        raise ValueError("backup_binding")
    obj = _strict_json(raw, MAX_RECEIPT_BYTES)
    if (type(obj) is not dict or set(obj) != {"token", "from", "to", "backup"}
            or any(type(v) is not str for v in obj.values())
            or obj["token"] != token or obj["backup"] != backup_name
            or not HEX40.fullmatch(obj["from"])
            or not HEX40.fullmatch(obj["to"]) or obj["from"] == obj["to"]):
        raise ValueError("untrusted_receipt_binding")
    return obj

def checked_managed_manifest(raw: bytes, claimed_member_sha256: dict[str, str]) -> dict:
    """Check exact claim membership and SHA strings; caller must hash files independently."""
    obj = _strict_json(raw, MAX_MANIFEST_BYTES)
    if (type(obj) is not dict or set(obj) != {"schema", "source_commit", "sha256"}
            or type(obj["schema"]) is not int or obj["schema"] != 1
            or type(obj["source_commit"]) is not str or not HEX40.fullmatch(obj["source_commit"])
            or type(obj["sha256"]) is not dict or not 3 <= len(obj["sha256"]) <= 500
            or not REQUIRED.issubset(obj["sha256"])
            or type(claimed_member_sha256) is not dict or set(claimed_member_sha256) != set(obj["sha256"])):
        raise ValueError("managed_manifest_schema_or_membership")
    namespace: dict[str, tuple[str, str]] = {}
    for name, expected in obj["sha256"].items():
        observed = claimed_member_sha256[name]
        if (not _safe_managed_name(name) or type(expected) is not str
                or not HEX64.fullmatch(expected) or type(observed) is not str
                or not HEX64.fullmatch(observed) or observed != expected):
            raise ValueError("managed_member_pin_or_name")
        parts = name.split("/")
        for i in range(len(parts)):
            rel = "/".join(parts[: i+1])
            kind = "file" if i == len(parts) - 1 else "directory"
            prev = namespace.setdefault(rel.casefold(), (rel, kind))
            if prev != (rel, kind):
                raise ValueError("windows_managed_namespace_collision")
    return {"source_commit": obj["source_commit"], "member_count": len(obj["sha256"]),
            "manifest_sha256": sha256(raw).hexdigest(),
            "evidence": "caller_claims_only_not_filesystem_verified"}

def checked_triple(receipt: bytes, *, token: str, backup_name: str,
                   backup_manifest: bytes, backup_members: dict[str, str],
                   stage_manifest: bytes, stage_members: dict[str, str]) -> dict:
    r = checked_receipt(receipt, token=token, backup_name=backup_name)
    before = checked_managed_manifest(backup_manifest, backup_members)
    after = checked_managed_manifest(stage_manifest, stage_members)
    if before["source_commit"] != r["from"] or after["source_commit"] != r["to"]:
        raise ValueError("receipt_manifest_commit_mismatch")
    return {"token": token, "backup_commit": before["source_commit"],
            "completed_stage_commit": after["source_commit"],
            "evidence": "synthetic_bytes_and_claimed_member_hashes_only"}

def checked_snapshot_bytes(manifest: bytes, member_bytes: dict[str, bytes]) -> dict:
    """Hash actual supplied bytes; still does NOT authenticate host observations.

    Caller must independently prove these are the exact immutable filesystem
    bytes at an exact plain path, without links or concurrent writes.
    """
    metadata = _strict_json(manifest, MAX_MANIFEST_BYTES)
    if (type(metadata) is not dict or set(metadata) != {"schema", "source_commit", "sha256"}
            or type(metadata["sha256"]) is not dict
            or not 3 <= len(metadata["sha256"]) <= 500
            or type(member_bytes) is not dict
            or set(member_bytes) != set(metadata["sha256"])):
        raise ValueError("snapshot_member_set")
    total = 0
    measured = {}
    for name, raw in member_bytes.items():
        if type(raw) is not bytes or len(raw) > 3 * 1024 * 1024:
            raise ValueError("snapshot_member_bytes_or_size")
        total += len(raw)
        if total > 30 * 1024 * 1024:
            raise ValueError("snapshot_total_size")
        measured[name] = sha256(raw).hexdigest()
    result = checked_managed_manifest(manifest, measured)
    return {**result, "measured_bytes": total,
            "evidence": "caller_supplied_file_bytes_hashed_not_host_attested"}

def checked_triple_bytes(receipt: bytes, *, token: str, backup_name: str,
                         backup_manifest: bytes, backup_files: dict[str, bytes],
                         stage_manifest: bytes, stage_files: dict[str, bytes]) -> dict:
    """Bind receipt to two fully byte-checked snapshots, never touching disk."""
    r = checked_receipt(receipt, token=token, backup_name=backup_name)
    before = checked_snapshot_bytes(backup_manifest, backup_files)
    after = checked_snapshot_bytes(stage_manifest, stage_files)
    if before["source_commit"] != r["from"] or after["source_commit"] != r["to"]:
        raise ValueError("receipt_manifest_commit_mismatch")
    return {"token": token, "backup_commit": before["source_commit"],
            "stage_commit": after["source_commit"],
            "backup_bytes_hashed": before["measured_bytes"],
            "stage_bytes_hashed": after["measured_bytes"],
            "evidence": "caller_supplied_snapshot_bytes_only_not_host_attested"}

def check_task_observation(observation: dict, expected_sid: str) -> dict:
    """Consume independent synthetic Scheduler observations only, not real COM state."""
    old_exe = (r"C:\Users\Anthony\AppData\Local\HomeHub\ObsidianMirror"
               r"\HiddenLauncher\20261025\ObsidianMirrorHiddenLauncher.exe")
    old_bundle = (r"C:\Users\Anthony\AppData\Local\HomeHub\ObsidianMirror"
                  r"\5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5")
    if (type(expected_sid) is not str or not re.fullmatch(r"S-1-5-21-(?:[1-9][0-9]{0,9}-){3}[1-9][0-9]{0,9}", expected_sid)
            or any(int(part) > 4294967295 for part in expected_sid.split("-")[4:])):
        raise ValueError("expected_sid")
    if (type(observation) is not dict or set(observation) !=
            {"task_path", "name", "state", "principal_sid", "run_level",
             "action", "triggers", "settings_enabled"}
            or observation["task_path"] != "\\"
            or observation["name"] != "HomeHub Obsidian Mirror Refresh"
            or observation["state"] != "Ready"
            or observation["principal_sid"] != expected_sid
            or observation["run_level"] != "LeastPrivilege"
            or observation["settings_enabled"] is not True
            or observation["action"] != {"execute": old_exe, "arguments": "",
                                        "working_directory": old_bundle}):
        raise ValueError("task_identity_or_action")
    triggers = observation["triggers"]
    if (type(triggers) is not list or len(triggers) != 2
            or any(type(item) is not dict for item in triggers)):
        raise ValueError("task_triggers")
    expected_triggers = [
        {"kind": "logon", "enabled": True, "sid": expected_sid},
        {"kind": "calendar", "enabled": True, "interval": "PT1H",
         "duration": "P1D", "days_interval": 1}
    ]
    if triggers != expected_triggers and triggers != list(reversed(expected_triggers)):
        raise ValueError("task_triggers")
    return {"task_shape": "expected", "quiesced": False,
            "task_execution_authorized": False, "evidence": "caller_supplied_task_fields_only"}

def compare_acl_digests(before: dict[str, str], after: dict[str, str]) -> dict:
    """Compare independently captured *hashed* SDDL over exact paths; not ACL attestation."""
    if (type(before) is not dict or type(after) is not dict or not before
            or set(before) != set(after)):
        raise ValueError("acl_membership")
    if len({name.casefold() for name in before if type(name) is str}) != len(before):
        raise ValueError('windows_case_alias')
    for name, expected in before.items():
        observed = after[name]
        if (type(name) is not str or not name or "/" in name or "\\" in name
                or type(expected) is not str or type(observed) is not str
                or not HEX64.fullmatch(expected) or observed != expected):
            raise ValueError("acl_digest_changed")
    return {"same_acl_digest_count": len(before), "evidence": "claims_only_no_live_acl_attestation"}
