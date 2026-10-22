"""Offline lexical planner tests; no scheduler or real user paths accessed."""

from contextlib import ExitStack
import builtins
from io import StringIO
import json
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import plan_obsidian_schedule as planner


def parameters():
    root = r"C:\Users\Synthetic User"
    return dict(user_root=root,
                bundle=root + "\\AppData\\Local\\HomeHub\\ObsidianMirror\\" + "a" * 40,
                python=root + r"\Programs\Python\python.exe",
                vault=root + r"\Documents\Synthetic Vault",
                expected_vault=root + r"\Documents\Synthetic Vault",
                user_sid="S-1-5-21-111-222-333-1001", source_commit="a" * 40,
                manifest_sha256="b" * 64)


def arguments(params=None):
    return [item for key, value in (params or parameters()).items()
            for item in ("--" + key.replace("_", "-"), value)]


def test_deterministic_no_side_effects_and_logged_off_contract():
    with ExitStack() as stack:
        stack.enter_context(patch.object(builtins, "open", side_effect=AssertionError("open")))
        for obj, names in ((Path, ("open", "stat", "lstat", "mkdir", "write_bytes")),
                           (socket, ("socket", "create_connection")),
                           (subprocess, ("Popen", "run"))):
            for name in names:
                stack.enter_context(patch.object(obj, name, side_effect=AssertionError(name)))
        first, second = StringIO(), StringIO()
        assert planner.main(arguments(), output=first) == 0
        assert planner.main(arguments(), output=second) == 0
        assert first.getvalue() == second.getvalue()
    plan = json.loads(first.getvalue())
    assert plan["enabled"] is False
    assert plan["logged_off_policy"] == "skip_without_write_no_catchup"
    assert plan["principal"]["LogonType"] == "InteractiveToken"
    assert plan["principal"]["RunLevel"] == "LeastPrivilege"
    assert plan["triggers"][0]["type"] == "LogonTrigger"
    assert plan["triggers"][1]["repetition"] == {
        "Interval": "PT1H", "Duration": "P1D", "StopAtDurationEnd": False}
    settings = plan["settings"]
    assert settings["MultipleInstancesPolicy"] == "IgnoreNew"
    for key in ("StartWhenAvailable", "WakeToRun", "AllowHardTerminate"):
        assert settings[key] is False
    assert settings["RestartCount"] == 0
    action = plan["future_action_record"]
    assert action["implemented"] is False
    assert action["argv"][:2] == ["-I", "-B"]
    assert action["fixed_cli_argv"] == [
        "--apply", "--approve-local-evaluation", "--vault", parameters()["vault"],
        "--expected-vault", parameters()["vault"]]


@pytest.mark.parametrize("flag", ["--register", "--enable", "--apply", "--password",
                                  "--credentials", "--run-level", "--extra-args",
                                  "--approve-scheduled-apply", "--user-s"])
def test_no_activation_credentials_or_additional_arguments(flag):
    with pytest.raises(SystemExit) as error:
        planner.main(arguments() + [flag, "anything"], output=StringIO())
    assert error.value.code == 2


@pytest.mark.parametrize("raw", ["relative", "C:relative", "C:\\", r"c:\Users\User",
                                r"C:\Users\..\Other", r"C:\Users\NUL.txt",
                                r"C:\Users\Vault.", r"C:\Users\%USER%",
                                r"C:\Users\short~1", r"\\server\share\Vault",
                                'C:\\Users\\bad"name', "C:\\Users\\bad\nname"])
def test_invalid_paths(raw):
    with pytest.raises(ValueError):
        planner.exact_path(raw)


@pytest.mark.parametrize("key,value", [
    ("bundle", r"C:\Work\home-hub-project\worktrees\temporary"),
    ("python", r"C:\Users\Synthetic User\worktrees\python.exe"),
    ("python", r"C:\Tools\python.exe"), ("expected_vault", r"C:\Users\Other\Vault"),
    ("user_sid", "SYSTEM"), ("user_sid", "S-1-5-18"),
    ("source_commit", "master"), ("manifest_sha256", "unreviewed"),
])
def test_invalid_identity_or_source(key, value):
    params = parameters()
    params[key] = value
    output = StringIO()
    assert planner.main(arguments(params), output=output) == 2
    assert json.loads(output.getvalue()) == {"status": "invalid_plan_parameters"}


def test_missing_parameters_refuse():
    with pytest.raises(SystemExit) as error:
        planner.main([], output=StringIO())
    assert error.value.code == 2


def test_direct_execution_disables_cache_and_imports_no_writer(monkeypatch):
    path = Path(planner.__file__)
    source = path.read_text(encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(path), *arguments()])
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    imported = []
    import builtins
    real_import = builtins.__import__

    def checked_import(name, *args, **kwargs):
        imported.append(name)
        assert not name.startswith(("obsidian_", "run_obsidian_", "winreg"))
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", checked_import), \
            patch.object(sys, "stdout", StringIO()), \
            patch("importlib._bootstrap_external._write_atomic",
                  side_effect=AssertionError("cache write")):
        with pytest.raises(SystemExit) as error:
            exec(compile(source, str(path), "exec"), {"__name__": "__main__"})
    assert error.value.code == 0
    assert sys.dont_write_bytecode is True
    assert {"sys", "argparse", "json", "pathlib", "re"} <= set(imported)
