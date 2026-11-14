"""Synthetic offline evidence only; never inspect host paths or secret contents."""
from dataclasses import replace
from pathlib import PurePosixPath

import pytest

from security.homehub_identity_broker import custody_plan as c
from security.homehub_identity_broker.linux_protected_verify import RootCustodyProof
from security.homehub_identity_broker.runtime import Denied


def fixture():
    principals = {"root": (0, 0), "broker": (41003, 41003), "backend": (41001, 41001)}
    nodes = {}
    for path, kind, owner, group, mode in c.ARTIFACTS:
        for parent in PurePosixPath(path).parents:
            nodes.setdefault(str(parent), c.Node(
                "directory", 0, 0, 0o755, 1, len(nodes) + 1, 2, "none", "reviewed"))
        nodes[path] = None if kind in {"optional", "absent"} else c.Node(
            kind, principals[owner][0], principals[group][1], mode, 1,
            len(nodes) + 100, 2 if kind == "directory" else 1, "none", "reviewed",
            "a" * 64 if path in c.HASHED else None, 100 if path in c.HASHED else None)
    return dict(plan=c.manifest(), before=nodes, after=nodes.copy(), principals=principals,
                release_hashes=dict.fromkeys(c.HASHED, "a" * 64), now=100,
                attestations=dict.fromkeys(c.REQUIRED_ATTESTATIONS, "requires-root-attestor"))


def test_consistent_snapshot_is_advisory_and_never_authority():
    report = c.preflight(**fixture())
    assert report.snapshot_consistent
    assert report.advisory_only and report.runtime_authorized is False
    assert len(report.issues) == len(c.REQUIRED_ATTESTATIONS)
    with pytest.raises(Denied):
        RootCustodyProof().check(role="service", policy=c.manifest(), broker=report)


@pytest.mark.parametrize("key,value", [
    ("runtime_authorized", True), ("version", True), ("version", 2),
    ("status", "install"), ("unknown", False), ("artifacts", []),
    ("principals", {"root": "backend"}), ("admin", "same-uid"),
])
def test_manifest_overrides_denied(key, value):
    args = fixture()
    args["plan"][key] = value
    assert c.preflight(**args).issues == ("manifest",)


@pytest.mark.parametrize("field", [
    "artifacts", "backup_exclude", "unit_contract", "required_attestations",
])
def test_manifest_rejects_tuples_in_list_fields(field):
    plan = c.manifest()
    plan[field] = tuple(plan[field])
    assert not c.lint_manifest(plan)
    args = fixture()
    args["plan"] = plan
    assert c.preflight(**args).issues == ("manifest",)


@pytest.mark.parametrize("index", [0, 6])
def test_manifest_rejects_tuple_artifact_rows(index):
    plan = c.manifest()
    plan["artifacts"][index] = tuple(plan["artifacts"][index])
    assert not c.lint_manifest(plan)


@pytest.mark.parametrize("field,value", [
    ("kind", "symlink"), ("uid", 99999), ("gid", 99999), ("mode", 0o666),
    ("mode", True), ("links", 2), ("inode", 0), ("device", -1),
    ("acl", "unknown"), ("acl", "extended"), ("mount", "unknown"),
])
def test_each_artifact_rejects_bad_metadata(field, value):
    for path, kind, *_ in c.ARTIFACTS:
        if kind in {"directory", "optional", "absent"}:
            continue
        args = fixture()
        args["before"][path] = replace(args["before"][path], **{field: value})
        args["after"] = args["before"].copy()
        assert "metadata:" + path in c.preflight(**args).issues


@pytest.mark.parametrize("path", ["/", "/opt", "/opt/homehub-identity", "/run",
                                 "/etc/homehub-identity", "/var/lib"])
def test_writable_or_symlink_ancestor_denied(path):
    for changes in ({"mode": 0o777}, {"kind": "symlink"}, {"uid": 41001}):
        args = fixture()
        args["before"][path] = replace(args["before"][path], **changes)
        args["after"] = args["before"].copy()
        assert not c.preflight(**args).snapshot_consistent


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_present_sidecars_must_be_private(suffix):
    args = fixture()
    db = "/var/lib/homehub-identity/registry.sqlite"
    args["before"][db + suffix] = replace(args["before"][db], inode=900)
    args["after"] = args["before"].copy()
    assert c.preflight(**args).snapshot_consistent
    args["before"][db + suffix] = replace(args["before"][db + suffix], mode=0o644)
    args["after"] = args["before"].copy()
    assert not c.preflight(**args).snapshot_consistent


@pytest.mark.parametrize("change", ["missing", "extra", "changed", "pending"])
def test_inventory_and_toctou_mismatch(change):
    args = fixture()
    if change == "missing":
        del args["before"]["/run"]
    elif change == "extra":
        args["before"]["/opt/rogue"] = None
    elif change == "pending":
        path = "/var/lib/homehub-identity-anchor/state.json.next"
        args["before"][path] = args["before"]["/var/lib/homehub-identity-anchor/state.json"]
    else:
        args["after"]["/run"] = replace(args["before"]["/run"], inode=999)
    assert not c.preflight(**args).snapshot_consistent


@pytest.mark.parametrize("changes", [{"digest": "b" * 64}, {"hashed_at": 39},
                                    {"hashed_at": 101}, {"hashed_at": None}])
def test_every_release_artifact_requires_fresh_matching_hash(changes):
    for path in c.HASHED:
        args = fixture()
        args["before"][path] = replace(args["before"][path], **changes)
        args["after"] = args["before"].copy()
        assert "hash-or-freshness:" + path in c.preflight(**args).issues


@pytest.mark.parametrize("field,value", [
    ("principals", {"root": (0, 0), "broker": (1, 1), "backend": (1, 2)}),
    ("principals", {"root": (0, 0), "broker": (1, 1), "backend": (2, 1)}),
    ("principals", {"root": (False, 0), "broker": (1, 1), "backend": (2, 2)}),
    ("now", True), ("release_hashes", {}), ("attestations", {}),
])
def test_incomplete_or_ambiguous_evidence(field, value):
    args = fixture()
    args[field] = value
    assert not c.preflight(**args).snapshot_consistent


def test_asserted_root_approval_cannot_replace_attestor():
    args = fixture()
    args["attestations"] = dict.fromkeys(c.REQUIRED_ATTESTATIONS, "approved")
    report = c.preflight(**args)
    assert not report.snapshot_consistent and not report.runtime_authorized


def test_matching_snapshots_cannot_detect_aba_or_prove_dependency_closure():
    args = fixture()
    report = c.preflight(**args)
    assert report.snapshot_consistent  # attacker could have restored identical evidence
    assert "root-attestor-required:continuous_custody_and_freshness" in report.issues
    assert "root-attestor-required:runtime_dependency_closure" in report.issues
    assert not report.runtime_authorized


def test_manifest_returns_independent_copies():
    plan = c.manifest()
    plan["artifacts"][0][0] = "/tmp/backend"
    assert not c.lint_manifest(plan)
    assert c.lint_manifest(c.manifest())
