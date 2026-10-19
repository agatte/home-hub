"""Offline scheduled bundle tests; TEMP only, no Scheduler integration."""
from contextlib import ExitStack
from io import StringIO
import ast
import json
from pathlib import Path
import sys
import socket
import subprocess
from urllib import request
from unittest.mock import patch
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import launch_obsidian_mirror as launch
import package_obsidian_schedule as package
import test_obsidian_simple_mirror as fixtures
from test_obsidian_github_docs_source import FILES as SOURCE_FILES
from test_run_obsidian_simple_mirror import no_writes

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ROOT = r"C:\Users\Ordinary User"
BUNDLE = ROOT + r"\AppData\Local\HomeHub\ObsidianMirror" + "\\" + launch.SOURCE_COMMIT
SID = "S-1-5-21-123-456-789-1001"


def spec():
    return {"source_commit": launch.SOURCE_COMMIT, "user_root": ROOT, "sid": SID,
            "bundle": BUNDLE, "python": ROOT + r"\Python\python.exe",
            "python_sha256": "a" * 64, "vault": ROOT + r"\Documents\Knowledge Vault",
            "files": {name: launch.digest((SCRIPTS / name).read_bytes())
                      for name in launch.FILES}}


@pytest.mark.parametrize("tool", [launch, package])
def test_default_has_no_attempted_writes_or_operations(tool):
    out = StringIO()
    with ExitStack() as stack:
        no_writes(stack)
        for owner, name in ((subprocess, "run"), (subprocess, "Popen"),
                            (socket, "create_connection"), (request, "build_opener")):
            stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name)))
        stack.enter_context(patch.object(Path, "lstat", side_effect=AssertionError("probe")))
        stack.enter_context(patch.object(launch, "verified_bundle", side_effect=AssertionError("verify")))
        stack.enter_context(patch.object(package, "prepare", side_effect=AssertionError("stage")))
        assert tool.main([], output=out) == 0
    assert json.loads(out.getvalue())["status"] == "off"


@pytest.mark.parametrize("tool,args", [
    (launch, ["--run"]), (launch, ["--anchor", "a" * 64]),
    (package, ["--stage"]), (package, ["--approve-stage", BUNDLE]),
    (package, ["--spec-json", "{}"]), (package, ["--spec-json", "garbage", "--xml"]),
])
def test_single_keys_and_bad_json_never_act(tool, args):
    with patch.object(package, "prepare", side_effect=AssertionError("stage")), \
            patch.object(launch, "verified_bundle", side_effect=AssertionError("verify")):
        assert tool.main(args, output=StringIO()) == 2


@pytest.mark.parametrize("tool,args", [(launch, ["--ru"]), (launch, ["--vault", ROOT]),
                                     (package, ["--register"]), (package, ["--activate"]),
                                     (package, ["--password", "not-a-secret"])])
def test_no_abbreviations_registration_or_credentials(tool, args, capsys):
    out = StringIO()
    assert tool.main(args, output=out) == 2
    expected = "launcher" if tool is launch else "package"
    assert json.loads(out.getvalue()) == {"status": expected + "_refused_review_evidence"}
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("tool,flag", [(launch, "--anchor"), (package, "--spec-json")])
@pytest.mark.parametrize("kind", ["unknown", "missing", "mode"])
def test_hostile_arguments_are_bounded_and_never_act(tool, flag, kind, capsys):
    hostile = "--synthetic-secret-" + "x" * 1000
    args = {"unknown": [hostile], "missing": [flag, hostile],
            "mode": [flag, hostile, "--run" if tool is launch else "--stage"]}[kind]
    out = StringIO()
    with ExitStack() as stack:
        no_writes(stack)
        for owner, name in ((subprocess, "run"), (subprocess, "Popen"),
                            (socket, "create_connection"), (request, "build_opener"),
                            (Path, "lstat"), (launch, "verified_bundle"), (package, "prepare")):
            guard = stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name)))
            # Parse refusal must never reach an operation, even if exceptions are bounded.
            stack.callback(guard.assert_not_called)
        assert tool.main(args, output=out) == 2
    expected = "launcher" if tool is launch else "package"
    assert json.loads(out.getvalue()) == {"status": expected + "_refused_review_evidence"}
    assert len(out.getvalue()) < 100
    assert hostile not in out.getvalue()
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("tool", [launch, package])
def test_help_remains_explicit_success(tool, capsys):
    with pytest.raises(SystemExit) as exc:
        tool.main(["--help"], output=StringIO())
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("key,value", [
    ("bundle", r"C:\Work\checkout"), ("source_commit", "b" * 40),
    ("python", r"C:\Windows\python.exe"), ("sid", "S-1-5-18"),
    ("vault", ROOT + r"\..\Vault"), ("vault", ROOT + r"\%TEMP%\Vault"),
    ("vault", ROOT + r"\NUL"), ("vault", BUNDLE),
    ("python_sha256", "bad"), ("user_root", r"C:\Users\Public"),
])
def test_spec_misbindings(key, value):
    data = spec()
    data[key] = value
    with pytest.raises(ValueError):
        package.task_xml(data)


def test_xml_is_disabled_hourly_interactive_and_non_terminating():
    data = spec()
    with ExitStack() as stack:
        no_writes(stack)
        stack.enter_context(patch.object(Path, "lstat", side_effect=AssertionError("probe")))
        xml = package.task_xml(data)
        assert xml == package.task_xml(data)
    root = ET.fromstring(xml)
    ns = {"t": package.NS}
    def value(path):
        return root.find(path, ns).text
    assert value("t:Settings/t:Enabled") == "false"
    assert value("t:Principals/t:Principal/t:UserId") == SID
    assert value("t:Principals/t:Principal/t:LogonType") == "InteractiveToken"
    assert value("t:Principals/t:Principal/t:RunLevel") == "LeastPrivilege"
    assert value("t:Triggers/t:LogonTrigger/t:UserId") == SID
    assert value("t:Triggers/t:CalendarTrigger/t:Repetition/t:Interval") == "PT1H"
    assert value("t:Triggers/t:CalendarTrigger/t:Repetition/t:Duration") == "P1D"
    for field in ("AllowHardTerminate", "StartWhenAvailable", "WakeToRun"):
        assert value("t:Settings/t:" + field) == "false"
    assert value("t:Settings/t:ExecutionTimeLimit") == "PT0S"
    assert value("t:Settings/t:MultipleInstancesPolicy") == "IgnoreNew"
    assert root.find(".//t:RestartOnFailure", ns) is None
    assert value("t:Actions/t:Exec/t:Arguments") == (
        '-I -B "' + BUNDLE + '\\launch_obsidian_mirror.py" --run --anchor ' +
        launch.digest(package.manifest_bytes(data)))
    assert value("t:RegistrationInfo/t:URI") == "\\" + package.TASK_NAME


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """Native TEMP path substitutes only the separately tested Windows spelling gate."""
    folder = tmp_path / "bundle"
    folder.mkdir()
    data = spec()
    data["bundle"] = str(folder)
    python = tmp_path / "python.exe"
    python.write_bytes(b"synthetic interpreter")
    data["python"] = str(python)
    data["python_sha256"] = launch.digest(python.read_bytes())
    for name in launch.FILES:
        (folder / name).write_bytes((SCRIPTS / name).read_bytes())
    raw = json.dumps(data).encode()
    (folder / "manifest.json").write_bytes(raw)
    monkeypatch.setattr(launch, "validate_spec", lambda s: s)
    monkeypatch.setattr(launch, "__file__", str(folder / "launch_obsidian_mirror.py"))
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(launch, "windows_identity", lambda: (SID, ROOT, False, 1))
    return folder, data, launch.digest(raw)


def test_verified_bundle_reads_only_and_loads_exact_closure(bundle):
    folder, data, anchor = bundle
    with ExitStack() as stack:
        no_writes(stack)
        checked, blobs = launch.verified_bundle(folder, anchor)
    assert checked == data
    assert set(blobs) == set(launch.MODULES)


@pytest.mark.parametrize("change", ["anchor", "manifest", "added", "missing", "module",
                                    "launcher", "interpreter", "path", "elevated", "sid",
                                    "profile", "session", "reparse"])
def test_tamper_refuses_before_import(bundle, monkeypatch, change):
    folder, data, anchor = bundle
    if change == "anchor":
        anchor = "0" * 64
    elif change == "manifest":
        (folder / "manifest.json").write_bytes(b"{}")
    elif change == "added":
        (folder / "unknown.py").write_text("raise RuntimeError('must not execute')")
    elif change == "missing":
        (folder / "obsidian_verified_stage.py").unlink()
    elif change in {"module", "launcher"}:
        name = "launch_obsidian_mirror.py" if change == "launcher" else "obsidian_simple_mirror.py"
        (folder / name).write_bytes(b"raise RuntimeError('must not execute')")
    elif change == "interpreter":
        Path(data["python"]).write_bytes(b"tampered")
    elif change == "path":
        monkeypatch.setattr(launch, "__file__", str(folder / "wrong.py"))
    elif change == "reparse":
        real = Path.lstat
        def fake(path, *args, **kwargs):
            if path == folder:
                class Reparse:
                    st_mode = 0o040755
                    st_file_attributes = 0x400
                return Reparse()
            return real(path, *args, **kwargs)
        monkeypatch.setattr(Path, "lstat", fake)
    else:
        identity = [SID, ROOT, False, 1]
        index, value = {"sid": (0, "wrong"), "profile": (1, "wrong"),
                        "elevated": (2, True), "session": (3, 0)}[change]
        identity[index] = value
        monkeypatch.setattr(launch, "windows_identity", lambda: tuple(identity))
    with patch.object(launch.VerifiedModules, "exec_module", side_effect=AssertionError("import")):
        with pytest.raises((ValueError, OSError)):
            launch.verified_bundle(folder, anchor)


def test_static_pins_and_transitive_import_inventory():
    pins = json.loads((SCRIPTS / "obsidian_launcher_pins.json").read_bytes())
    assert pins == {"source_commit": launch.SOURCE_COMMIT, "files": spec()["files"]}
    local = {p.stem for p in SCRIPTS.glob("*.py")}
    seen, pending = set(), ["run_obsidian_simple_mirror"]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse((SCRIPTS / (name + ".py")).read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in local:
                pending.append(node.module)
            elif isinstance(node, ast.Import):
                pending.extend(a.name for a in node.names if a.name in local)
    assert seen == set(launch.MODULES)


@pytest.mark.parametrize("mode,expected", [("old", (0, "no_change")),
                                          ("new", (0, "updated")),
                                          ("offline", (3, "source_unavailable")),
                                          ("pending", (2, "refused_or_failed_review_evidence")),
                                          ("lock", (2, "refused_or_failed_review_evidence"))])
def test_real_writer_once_in_process_with_synthetic_vault(mode, expected, monkeypatch):
    fixture = fixtures.SimpleMirrorTests()
    fixture.setUp()
    saved = {name: sys.modules.pop(name) for name in launch.MODULES if name in sys.modules}
    calls = []
    try:
        if mode in {"pending", "lock"}:
            # Same pending evidence checked by the existing runner.
            (fixture.parent / ("." + fixture.vault.name + "-homehub-" +
                               ("simple.pending" if mode == "pending" else "refresh.lock"))).write_text("pending")
        commit = fixtures.OLD if mode == "old" else fixtures.NEW
        api = fixture.source_api(commit)
        original = launch.VerifiedModules.exec_module
        def execute(loader, module):
            original(loader, module)
            if module.__name__ == "run_obsidian_simple_mirror":
                def fetch(path):
                    if mode == "offline":
                        from obsidian_github_docs_source import SourceUnavailable
                        raise SourceUnavailable("hidden payload")
                    return api[path]
                module.github_json = fetch
                module.github_raw_blob = lambda sha, blob: SOURCE_FILES[blob.path]
                real = module.run_once
                def once(**kwargs):
                    calls.append(1)
                    return real(**kwargs)
                module.run_once = once
        monkeypatch.setattr(launch.VerifiedModules, "exec_module", execute)
        blobs = {name: (SCRIPTS / (name + ".py")).read_bytes() for name in launch.MODULES}
        before = fixture.snapshot(fixture.parent)
        code, report = launch.invoke_once({"vault": str(fixture.vault)}, blobs)
        assert (code, report["status"]) == expected
        assert len(calls) == (0 if mode in {"pending", "lock"} else 1)
        if mode in {"old", "offline", "pending", "lock"}:
            assert fixture.snapshot(fixture.parent) == before
    finally:
        sys.modules.update(saved)
        fixture.doCleanups()


@pytest.mark.parametrize("payload,code", [
    ('{"status":"no_change","commit":"bad"}', 0),
    ('{"status":"source_unavailable","secret":"payload"}', 3),
    ('{"status":"update_available"}', 1), ('x' * 513, 0),
])
def test_bad_output_refused_and_incidental_output_discarded(payload, code, capsys):
    saved = {name: sys.modules.pop(name) for name in launch.MODULES if name in sys.modules}
    blob = ("def main(argv, output):\n"
            "    print('untrusted incidental content')\n"
            f"    output.write({payload!r})\n    return {code}\n").encode()
    try:
        with pytest.raises(ValueError):
            launch.invoke_once({"vault": ROOT}, {"run_obsidian_simple_mirror": blob})
        assert capsys.readouterr().out == ""
    finally:
        sys.modules.update(saved)


def test_package_two_keys_and_staging(tmp_path, monkeypatch):
    data = spec()
    data["bundle"] = str(tmp_path / "new-bundle")
    python = tmp_path / "python.exe"
    python.write_bytes(b"fixture")
    data["python"] = str(python)
    data["python_sha256"] = launch.digest(b"fixture")
    monkeypatch.setattr(package, "validate_spec", lambda s: s)
    monkeypatch.setattr(launch, "validate_spec", lambda s: s)
    pin = launch.digest((SCRIPTS / "obsidian_launcher_pins.json").read_bytes())
    with pytest.raises(ValueError):
        package.prepare(data, SCRIPTS, "0" * 64)
    assert not Path(data["bundle"]).exists()
    anchor = package.prepare(data, SCRIPTS, pin)
    assert anchor == launch.digest((Path(data["bundle"]) / "manifest.json").read_bytes())
    assert {p.name for p in Path(data["bundle"]).iterdir()} == launch.FILES | {"manifest.json"}
    with pytest.raises(FileExistsError):
        package.prepare(data, SCRIPTS, pin)

@pytest.mark.parametrize("change", ["missing", "changed", "added", "pin", "extra_field"])
def test_module_manifest_validation_requires_exact_set(change):
    data = spec()
    if change == "missing":
        data["files"].pop("create_obsidian_pilot.py")
    elif change == "changed":
        data["files"]["create_obsidian_pilot.py"] = "not-a-digest"
    elif change == "added":
        data["files"]["evil.py"] = "0" * 64
    elif change == "pin":
        data["source_commit"] = "0" * 40
    else:
        data["activation"] = True
    with pytest.raises(ValueError):
        launch.validate_spec(data)


def test_explicit_staging_keys_bind_exact_destination(monkeypatch):
    data = spec()
    calls = []
    monkeypatch.setattr(package, "prepare", lambda *a: calls.append(a) or "a" * 64)
    args = ["--stage", "--spec-json", json.dumps(data), "--reviewed-pins-sha256", "b" * 64]
    assert package.main(args + ["--approve-stage", "wrong"], output=StringIO()) == 2
    assert not calls
    assert package.main(args + ["--approve-stage", BUNDLE], output=StringIO()) == 0
    assert len(calls) == 1


def test_preloaded_shadow_modules_refuse():
    with patch.dict(sys.modules, {"run_obsidian_simple_mirror": object()}):
        with pytest.raises(ValueError, match="preloaded"):
            launch.invoke_once({"vault": ROOT}, {})


def test_verified_loader_uses_verified_bytes_after_disk_change(bundle):
    folder, _, anchor = bundle
    _, blobs = launch.verified_bundle(folder, anchor)
    (folder / "create_obsidian_pilot.py").write_bytes(b"raise RuntimeError('changed after check')")
    loader = launch.VerifiedModules(blobs)
    module_spec = loader.find_spec("create_obsidian_pilot")
    import importlib.util
    module = importlib.util.module_from_spec(module_spec)
    loader.exec_module(module)
    assert module.MAX_FILE_BYTES == 3 * 1024 * 1024


def test_package_tampered_source_refuses_before_destination(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    data = spec()
    for name in launch.FILES | {"obsidian_launcher_pins.json"}:
        (source / name).write_bytes((SCRIPTS / name).read_bytes())
    (source / "obsidian_simple_mirror.py").write_bytes(b"tampered")
    data["bundle"] = str(tmp_path / "never-created")
    monkeypatch.setattr(package, "validate_spec", lambda s: s)
    pin = launch.digest((source / "obsidian_launcher_pins.json").read_bytes())
    with pytest.raises(ValueError, match="source_pin"):
        package.prepare(data, source, pin)
    assert not Path(data["bundle"]).exists()
