"""Offline inventory tests: injected reads only, no real subprocess/filesystem probes."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest


SOURCE = Path(__file__).parents[1] / "scripts/homehub_backend_cutover_audit.py"
SPEC = importlib.util.spec_from_file_location("cutover_audit", SOURCE)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class FakeFS:
    def __init__(self):
        self.reads = []
        self.stats = []
        self.bad = {}
        self.data = {"/proc/1/comm": b"systemd\n"}

    def read(self, path):
        self.reads.append(path)
        return self.data.get(path, b"unrecognized source with SECRET")

    def lstat(self, path):
        self.stats.append(path)
        if path in self.bad:
            value = self.bad[path]
            if isinstance(value, Exception):
                raise value
            return value
        leaf = path in audit.PATHS[:3] or path.endswith((".service", ".socket", ".conf"))
        mode = 0o555 if path == "/opt/homehub-identity/runtime" else 0o444
        return SimpleNamespace(st_mode=(stat.S_IFREG | mode) if leaf else
                               (stat.S_IFDIR | 0o755), st_uid=0, st_gid=0)


def unit_text(name):
    return "\n".join(("LoadState=loaded", "ActiveState=active", "SubState=running",
                      "UnitFileState=enabled", "Names=" + name,
                      "FragmentPath=/etc/systemd/system/" + name, "DropInPaths=",
                      "ReusePort=no", "Accept=no", "NoNewPrivileges=yes",
                      "ProtectSystem=strict"))


class Runner:
    def __init__(self):
        self.calls = []
        self.overrides = {}

    def __call__(self, command):
        assert command in audit.COMMANDS
        self.calls.append(command)
        value = self.overrides.get(command, "" if command == audit.SS else unit_text(command[3]))
        if isinstance(value, Exception):
            raise value
        return value


def test_synthetic_good_inventory_still_denied():
    fs, runner = FakeFS(), Runner()
    result = audit.audit(runner=runner, fs=fs)
    assert result["status"] == "BLOCKED"
    assert result["read_only"] and result["runtime_authorized"] is False
    assert result["pid1"] == "systemd-observed"
    assert all(u["status"] == "INSPECTED" for u in result["units"])
    assert set(runner.calls) == set(audit.COMMANDS)
    assert set(fs.reads) == {"/proc/1/comm"} | {
        audit.CHECKOUT + "/" + p for p in audit.SOURCES}
    assert "SECRET" not in json.dumps(result)
    assert "external-operational-proof-required" in result["blockers"]


@pytest.mark.parametrize("scope,name", audit.UNITS)
@pytest.mark.parametrize("failure", [OSError("SECRET user bus"), "", "ExecStart=SECRET",
                                     "LoadState=loaded\nLoadState=loaded"])
def test_unit_failures_are_unknown_sanitized(scope, name, failure):
    runner = Runner()
    runner.overrides[audit.unit_command(scope, name)] = failure
    result = audit.audit(runner=runner, fs=FakeFS())
    unit = next(u for u in result["units"] if u["scope"] == scope and u["unit"] == name)
    assert unit["status"] == "UNKNOWN"
    assert f"unit-unknown:{scope}:{name}" in result["blockers"]
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("endpoint,family,scope", [
    ("127.0.0.1:8000", "ipv4", "loopback"), ("0.0.0.0:8000", "ipv4", "wildcard"),
    ("[::1]:8002", "ipv6", "loopback"), ("[::]:8000", "ipv6", "wildcard"),
    ("192.168.1.2:8000", "ipv4", "nonloopback"), ("*:8000", "unknown", "wildcard"),
    ("127.0.0.1:8003", "ipv4", "loopback"),
])
def test_listener_parser(endpoint, family, scope):
    assert audit.listeners(f"LISTEN 0 128 {endpoint} *:*\n") == [
        {"port": int(endpoint.rsplit(":", 1)[1]), "family": family,
         "scope": scope, "owner": "UNKNOWN"}]


@pytest.mark.parametrize("text", ["garbage SECRET", "LISTEN 0 10 localhost:8000 *:*",
                                  "LISTEN 0 10 127.0.0.1:8000 *:* users:SECRET"])
def test_listener_unknown(text):
    runner = Runner()
    runner.overrides[audit.SS] = text
    result = audit.audit(runner=runner, fs=FakeFS())
    assert result["listeners"] == {"status": "UNKNOWN"}
    assert "SECRET" not in json.dumps(result)


def test_unrelated_listeners_do_not_leak_addresses():
    assert audit.listeners("LISTEN 0 10 10.20.30.40:22 *:*") == []


@pytest.mark.parametrize("bad", [OSError("SECRET"),
    SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0, st_gid=0),
    SimpleNamespace(st_mode=stat.S_IFDIR | 0o777, st_uid=0, st_gid=0),
    SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=1000, st_gid=1000)])
def test_missing_unsafe_ancestor_stops_traversal(bad):
    fs = FakeFS()
    fs.bad["/opt"] = bad
    records, state = audit.metadata(fs, "/opt/homehub-backend/package")
    assert state in ("UNKNOWN", "UNSAFE")
    assert "/opt/homehub-backend" not in fs.stats
    assert "SECRET" not in json.dumps(records)


def test_checkout_must_be_directory_even_with_safe_mode():
    fs = FakeFS()
    fs.bad[audit.CHECKOUT] = SimpleNamespace(
        st_mode=stat.S_IFREG | 0o755, st_uid=0, st_gid=0)
    result = audit.audit(runner=Runner(), fs=fs)
    checkout = next(p for p in result["paths"] if p["path"] == audit.CHECKOUT)
    assert checkout["status"] == "UNSAFE"
    assert "path-custody:" + audit.CHECKOUT in result["blockers"]
    assert result["status"] == "BLOCKED"


def test_writable_or_nonexecutable_sealed_artifact_is_unsafe():
    fs = FakeFS()
    fs.bad["/opt/homehub-identity/runtime"] = SimpleNamespace(
        st_mode=stat.S_IFREG | 0o644, st_uid=0, st_gid=0)
    report = audit.audit(runner=Runner(), fs=fs)
    assert next(p for p in report["paths"] if p["path"] ==
                "/opt/homehub-identity/runtime")["status"] == "UNSAFE"


def test_source_fingerprint_exact_and_changed(monkeypatch):
    # Fixture fingerprints are injected in memory; CLI cannot select expectations.
    fs = FakeFS()
    relative = "scripts/deploy.sh"
    data = b"known unsafe source\n"
    monkeypatch.setattr(audit, "SOURCES", {relative: (
        hashlib.sha256(data).hexdigest(), "checkout-reset-and-user-restart")})
    fs.data[audit.CHECKOUT + "/" + relative] = data.replace(b"\n", b"\r\n")
    result = audit.audit(runner=Runner(), fs=fs)
    assert result["sources"][0]["status"] == "KNOWN_BYPASS"
    fs.data[audit.CHECKOUT + "/" + relative] += b"# changed"
    result = audit.audit(runner=Runner(), fs=fs)
    assert result["sources"][0]["status"] == "UNKNOWN"


def test_alias_dropin_metadata_and_path_rejection():
    runner = Runner()
    command = audit.unit_command("user", "home-hub.service")
    runner.overrides[command] = unit_text("home-hub.service other.service").replace(
        "DropInPaths=", "DropInPaths=/home/anthony/.config/systemd/user/home-hub.service.d/a.conf")
    result = audit.audit(runner=runner, fs=FakeFS())
    assert result["units"][-1]["alias_count"] == 1
    assert result["units"][-1]["dropin_count"] == 1
    runner.overrides[command] = unit_text("home-hub.service").replace(
        "DropInPaths=", "DropInPaths=/SECRET/token.conf")
    fs = FakeFS()
    result = audit.audit(runner=runner, fs=fs)
    assert result["units"][-1]["status"] == "UNKNOWN"
    assert "/SECRET/token.conf" not in fs.stats
    assert "SECRET" not in json.dumps(result)


def test_effective_execution_is_classified_without_echo():
    runner = Runner()
    command = audit.unit_command("user", "home-hub.service")
    runner.overrides[command] = unit_text("home-hub.service") + (
        "\nExecStart={ path=/home/anthony/home-hub/venv/bin/python ; argv[]=SECRET ; }\n")
    result = audit.audit(runner=runner, fs=FakeFS())
    assert result["units"][-1]["execution"] == "CHECKOUT_REFERENCE_OBSERVED"
    assert "SECRET" not in json.dumps(result)


def test_cli_rejects_paths_without_io(monkeypatch, capsys):
    monkeypatch.setattr(audit, "run_readonly", lambda _: pytest.fail("real command"))
    assert audit.main(["--root", "/SECRET"]) == 2
    assert "SECRET" not in capsys.readouterr().out


@pytest.mark.parametrize("arguments", [[], ["--json"]])
def test_cli_cannot_admit_with_successful_fakes(monkeypatch, capsys, arguments):
    monkeypatch.setattr(audit.sys, "platform", "linux")
    monkeypatch.setattr(audit, "run_readonly", Runner())
    monkeypatch.setattr(audit, "FileSystem", FakeFS)
    assert audit.main(arguments) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["runtime_authorized"] is False and result["status"] == "BLOCKED"


def test_real_adapter_read_contract_with_fake_os(monkeypatch):
    calls = []
    for name, value in (("O_DIRECTORY", 65536), ("O_NOFOLLOW", 131072),
                        ("O_NONBLOCK", 2048)):
        monkeypatch.setattr(audit.os, name, value, raising=False)

    def fake_open(path, flags, **kwargs):
        calls.append((path, flags, kwargs))
        assert not flags & (audit.os.O_WRONLY | audit.os.O_RDWR | audit.os.O_CREAT)
        return len(calls)

    chunks = iter((b"systemd\n", b""))
    info = SimpleNamespace(st_mode=stat.S_IFREG | 0o444, st_dev=1, st_ino=2,
                           st_uid=0, st_gid=0, st_nlink=1, st_size=8,
                           st_mtime_ns=1, st_ctime_ns=1)
    monkeypatch.setattr(audit.os, "open", fake_open)
    monkeypatch.setattr(audit.os, "close", lambda _: None)
    monkeypatch.setattr(audit.os, "fstat", lambda _: info)
    monkeypatch.setattr(audit.os, "read", lambda *_: next(chunks))
    assert audit.FileSystem().read("/proc/1/comm") == b"systemd\n"
    assert all(flags & audit.os.O_NOFOLLOW for _, flags, _ in calls[1:])
    with pytest.raises(OSError):
        audit.FileSystem().read("/etc/SECRET")
    assert len(calls) == 4


def test_static_no_writes_shell_backend_or_subprocess_in_tests():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"write", "write_text", "write_bytes", "mkdir",
                                              "unlink", "system", "getenv"}
            if isinstance(node.func, ast.Name):
                assert node.func.id != "open"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert "backend" not in ast.unparse(node)
    assert all(c[0] in ("/usr/bin/systemctl", "/usr/bin/ss") for c in audit.COMMANDS)
    assert all("show" in c if c[0].endswith("systemctl") else c == audit.SS
               for c in audit.COMMANDS)
