"""Native metadata syscalls on disposable paths; no sudo or installed layout."""
import ast
import os
from pathlib import Path
import stat
import sys

import pytest

from security.homehub_identity_broker import linux_os_preflight as p
from security.homehub_identity_broker.linux_protected_verify import RootCustodyProof
from security.homehub_identity_broker.runtime import Denied

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux O_PATH/dirfd required")


def test_public_probe_has_no_input_or_authority():
    import inspect
    assert not inspect.signature(p.probe).parameters
    assert p.PreflightReport(()).runtime_authorized is False
    assert "independent-external-backend-startup-deploy-rollback-floor" in p.MISSING
    with pytest.raises(Denied):
        RootCustodyProof().check(role="root", policy=p.PreflightReport(()))


def test_source_never_reads_contents_or_launches():
    tree = ast.parse(Path(p.__file__).read_text(encoding="utf-8"))
    forbidden = {"read", "read_bytes", "read_text", "getenv", "system", "connect",
                 "write", "unlink", "chmod", "chown", "Popen", "run", "getpwnam"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden
    assert not any(isinstance(n, ast.Name) and n.id == "__name__" for n in ast.walk(tree))


def test_platform_denial(monkeypatch):
    monkeypatch.setattr(p.sys, "platform", "win32")
    assert p.probe().observations == (p.Observation(-1, "linux-required"),)


@pytest.mark.parametrize("path,expected", [
    ("/var/lib/homehub-identity", False),
    ("/var/lib/homehub-identity/registry.sqlite", True),
    ("/var/lib/homehub-identity/registry.sqlite-wal", True),
    ("/var/lib/homehub-identity-anchor/state.deny", True),
    ("/var/lib/homehub-identity-anchor/state.deny.next", True),
    ("/var/lib/homehub-identity-rogue/fence", False),
    ("/run/homehub-identity/verify.sock", False),
])
def test_exact_private_boundary_does_not_claim_broker_identity(path, expected):
    assert p._private_descendant(path) is expected


@LINUX
def test_broker_children_are_explicitly_uninspected_on_linux():
    report = p.probe()
    indices = [i for i, (path, *_rest) in enumerate(p.ARTIFACTS)
               if p._private_descendant(path)]
    assert indices
    for index in indices:
        assert report.observations[index + 1] == p.Observation(
            index, "private-ancestor-identity-unverified")


@LINUX
def test_actual_probe_bounded_and_always_blocked():
    report = p.probe()
    assert report.missing == p.MISSING
    assert not report.runtime_authorized
    assert len(report.observations) <= len(p.ARTIFACTS) + 1
    assert all(type(o.artifact) is int and "/" not in o.status for o in report.observations)


@LINUX
def test_kernel_credential_failure_is_sanitized(monkeypatch):
    def fail():
        raise OSError("PRIVATE TOKEN PATH")
    monkeypatch.setattr(p.os, "getresuid", fail)
    report = p.probe()
    assert report.observations == (p.Observation(-1, "kernel-credentials-or-root-unobservable"),)
    assert "PRIVATE" not in repr(report)


@LINUX
@pytest.mark.parametrize("field", ["uid", "gid", "mode", "kind", "missing_uid", "missing_gid"])
def test_actual_file_metadata_rejects_wrong_or_unavailable_identity(tmp_path, field):
    path = tmp_path / "fixture"
    path.touch(mode=0o600)
    node = path.stat()
    args = dict(kind="file", uid=node.st_uid, gid=node.st_gid, mode=stat.S_IMODE(node.st_mode))
    assert p._metadata(node, **args) == "metadata-observed"
    if field.startswith("missing_"):
        args[field.removeprefix("missing_")] = None
    elif field == "kind":
        args[field] = "directory"
    else:
        args[field] += 1
    assert p._metadata(node, **args) != "metadata-observed"


@LINUX
@pytest.mark.parametrize("replacement", ["file", "symlink", "mode", "hardlink"])
def test_held_fd_detects_actual_replacement_and_metadata_change(tmp_path, replacement):
    path = tmp_path / "fixture"
    path.touch(mode=0o600)
    parent = os.open(tmp_path, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    fd = os.open("fixture", os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        edges = [(parent, "fixture", fd, p._stamp(os.fstat(fd)))]
        assert p._recheck(edges)
        if replacement == "mode":
            path.chmod(0o644)
        elif replacement == "hardlink":
            os.link(path, tmp_path / "alias")
        else:
            path.rename(tmp_path / "old")
            if replacement == "file":
                path.touch()
            else:
                path.symlink_to(tmp_path / "old")
        assert not p._recheck(edges)
    finally:
        os.close(fd)
        os.close(parent)


@LINUX
def test_no_follow_opath_pins_symlink_without_opening_target(tmp_path):
    path = tmp_path / "link"
    path.symlink_to("/nonexistent-private-target")
    fd = os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        assert stat.S_ISLNK(os.fstat(fd).st_mode)
        assert not os.get_inheritable(fd)
    finally:
        os.close(fd)


@LINUX
def test_walk_actual_unsafe_parent_fails_without_content_read(tmp_path):
    tmp_path.chmod(0o777)
    (tmp_path / "fixture").touch()
    fd = os.open(tmp_path, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        assert p._walk(fd, ["fixture"], "file", 0, 0, 0o600) == "unsafe-ancestor"
    finally:
        os.close(fd)


@LINUX
def test_walk_native_root_contract_and_fd_cleanup(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "fixture"
    path.touch(mode=0o600)
    fd = os.open(tmp_path, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        expected = "metadata-observed" if os.getuid() == os.getgid() == 0 else "unsafe-ancestor"
        assert p._walk(fd, ["fixture"], "file", 0, 0, 0o600) == expected
        assert os.fstat(fd)  # caller's descriptor remains owned by caller
        if expected == "metadata-observed":
            path.unlink()
            path.symlink_to("missing")
            assert p._walk(fd, ["fixture"], "file", 0, 0, 0o600) == "symlink"
    finally:
        os.close(fd)
