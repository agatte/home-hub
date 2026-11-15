"""Offline source-contract checks; no systemd, root operations or activation."""
from dataclasses import FrozenInstanceError
import io
from pathlib import Path
from types import SimpleNamespace
import stat

import pytest

from security.homehub_identity_broker import unit_contract as c
from security.homehub_identity_broker.linux_protected_verify import RootCustodyProof
from security.homehub_identity_broker.runtime import Denied


DIRECTIVES = [
    (name, section, key, value)
    for name, sections in c.SCHEMA
    for section, pairs in sections
    for key, value in pairs
]


def test_supplied_sources_are_exact_and_never_runtime_authority():
    assert c.validate_supplied_files().source_consistent
    sources = c.proposed_sources()
    report = c.validate_sources(sources)
    assert report.source_consistent and report.runtime_authorized is False
    with pytest.raises((FrozenInstanceError, AttributeError)):
        report.runtime_authorized = True
    with pytest.raises(Denied):
        RootCustodyProof().check(role="service", policy=sources, broker=report)
    sources.clear()
    assert len(c.proposed_sources()) == 2
    assert c.validate_sources({}).runtime_authorized is False


@pytest.mark.parametrize("name,section,key,value", DIRECTIVES)
@pytest.mark.parametrize("operation", ["remove", "change", "duplicate"])
def test_every_directive_is_required_exactly_once(name, section, key, value, operation):
    sources = c.proposed_sources()
    line = key + "=" + value + "\n"
    replacement = {"remove": "", "change": key + "=untrusted\n",
                   "duplicate": line + line}[operation]
    sources[name] = sources[name].replace(line, replacement)
    report = c.validate_sources(sources)
    assert not report.source_consistent
    assert report.runtime_authorized is False


@pytest.mark.parametrize("name,sections", c.SCHEMA)
def test_duplicate_sections_and_stray_assignments(name, sections):
    for section, _ in sections:
        sources = c.proposed_sources()
        sources[name] += "\n[" + section + "]\n"
        assert not c.validate_sources(sources).source_consistent
    sources = c.proposed_sources()
    sources[name] = "User=root\n" + sources[name]
    assert not c.validate_sources(sources).source_consistent


@pytest.mark.parametrize("addition", [
    "ExecStart=/bin/sh", "ExecStartPre=/bin/true", "ExecStop=/bin/sh",
    "ExecReload=/bin/sh", "Environment=AUTHORIZED=1", "EnvironmentFile=/etc/secret",
    "PassEnvironment=HOME", "LoadCredential=key:/etc/secret", "ImportCredential=*",
    "SetCredential=key:value", "DynamicUser=yes", "User=root", "Group=root",
    "SupplementaryGroups=root homehub-backend", "AmbientCapabilities=CAP_SYS_ADMIN",
    "ListenStream=/tmp/admin.sock", "SocketGroup=root", "SocketMode=0666",
    "Service=other.service", "Sockets=other.socket", "FileDescriptorName=admin",
    "Accept=yes", "OnFailure=external.service", "BindPaths=/tmp:/opt/homehub-identity",
    "RootDirectory=/tmp", "ReadWritePaths=/", "PrivateNetwork=yes",
    "[Install]\nWantedBy=sockets.target", "[Unknown]\nExecStart=/bin/sh",
    "[Socket]\nListenStream=", "# extra comment", "\\", "\x00",
])
@pytest.mark.parametrize("name", [c.SOCKET_NAME, c.SERVICE_NAME])
def test_unreviewed_overrides_and_install_exec_environment_are_rejected(name, addition):
    sources = c.proposed_sources()
    sources[name] += addition + "\n"
    assert not c.validate_sources(sources).source_consistent


@pytest.mark.parametrize("bad_name", [
    "homehub-identity.service", "homehub-identity.socket", "other.socket.in",
    "/etc/systemd/system/homehub-identity.socket", "../homehub-identity.socket.in",
    "systemd/homehub-identity.socket.in", "homehub-identity.socket.in.d/override.conf",
])
def test_own_fragment_filename_is_fixed(bad_name):
    sources = c.proposed_sources()
    sources[bad_name] = sources.pop(c.SOCKET_NAME)
    assert not c.validate_sources(sources).source_consistent


@pytest.mark.parametrize("value", [None, True, {}, [], b"[Service]"])
def test_wrong_input_types(value):
    assert not c.validate_sources(value).source_consistent
    sources = c.proposed_sources()
    sources[c.SERVICE_NAME] = value
    assert not c.validate_sources(sources).source_consistent


def test_line_endings_only_are_normalized():
    sources = {k: v.replace("\n", "\r\n") for k, v in c.proposed_sources().items()}
    assert c.validate_sources(sources).source_consistent
    sources[c.SERVICE_NAME] += "\r"
    assert not c.validate_sources(sources).source_consistent


@pytest.mark.parametrize("field,value", [
    ("st_mode", stat.S_IFLNK | 0o777), ("st_nlink", 2),
    ("st_file_attributes", 0x400), ("st_mode", stat.S_IFDIR | 0o755),
])
def test_supplied_fragment_symlinks_reparse_hardlinks_and_nonfiles_denied(
        monkeypatch, field, value):
    original = Path.lstat

    def fake(path, *args, **kwargs):
        if path.name == c.SOCKET_NAME:
            fields = dict(st_mode=stat.S_IFREG | 0o644, st_nlink=1, st_file_attributes=0)
            fields[field] = value
            return SimpleNamespace(**fields)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", fake)
    assert c.validate_supplied_files().issues == ("source-path",)


def test_symlink_ancestor_denied(monkeypatch):
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p.name == "systemd" or original(p))
    assert c.validate_supplied_files().issues == ("source-path",)


def test_extra_fragment_or_dropin_denied(monkeypatch):
    monkeypatch.setattr(Path, "iterdir", lambda p: iter([
        p / c.SOCKET_NAME, p / c.SERVICE_NAME, p / "override.conf",
    ]))
    assert c.validate_supplied_files().issues == ("source-inventory",)


def test_read_failure_denied(monkeypatch):
    def fail(path, *args, **kwargs):
        raise OSError("synthetic")
    monkeypatch.setattr(Path, "open", fail)
    assert c.validate_supplied_files().issues == ("source-read",)


def test_oversized_lstat_rejected_without_opening(monkeypatch):
    original = Path.lstat

    def fake(path, *args, **kwargs):
        if path.name == c.SOCKET_NAME:
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_nlink=1,
                                   st_file_attributes=0, st_size=c.MAX_SOURCE_BYTES + 1)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", fake)
    assert c.validate_supplied_files().issues == ("source-size",)


def test_fragment_growth_after_lstat_is_bounded(monkeypatch):
    original = Path.open

    def fake(path, *args, **kwargs):
        if path.name == c.SOCKET_NAME:
            return io.BytesIO(b"x" * (c.MAX_SOURCE_BYTES + 1))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fake)
    assert c.validate_supplied_files().issues == ("source-size",)


def test_only_inert_sources_and_no_install_or_execution_commands():
    directory = Path(c.__file__).parent / "systemd"
    assert {p.name for p in directory.iterdir()} == {c.SOCKET_NAME, c.SERVICE_NAME}
    for path in directory.iterdir():
        assert path.suffix == ".in"
        text = path.read_text(encoding="ascii")
        assert text.startswith(c.HEADER)
        assert "[Install]" not in text and "Exec" not in text
        assert "systemctl" not in text and "sudo" not in text
    # The validator has no process/install API. No artifact is emitted to an
    # actual .socket/.service path; test reads only repository-owned sources.
    source = Path(c.__file__).read_text(encoding="ascii")
    assert "subprocess" not in source.replace("No subprocess", "")
    assert "write_text(" not in source and "write_bytes(" not in source
