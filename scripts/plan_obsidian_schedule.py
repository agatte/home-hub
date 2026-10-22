"""Pure #399 schedule proposal. Prints JSON only; cannot install or run a task."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import json
from pathlib import PureWindowsPath
import re


def exact_path(raw: str) -> PureWindowsPath:
    """Lexical validation only: never inspect a real host path."""
    if not isinstance(raw, str):
        raise ValueError("invalid_path")
    path = PureWindowsPath(raw)
    devices = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    devices.update(f"{prefix}{n}" for prefix in ("COM", "LPT") for n in "123456789¹²³")
    if (not path.is_absolute() or not re.fullmatch(r"[A-Z]:\\", path.anchor)
            or str(path) != raw or len(path.parts) < 2):
        raise ValueError("invalid_path")
    for part in path.parts[1:]:
        if (part in {".", ".."} or part.endswith((".", " "))
                or any(c in part for c in '<>:"|?*%~$`')
                or any(ord(c) < 32 for c in part)
                or part.split(".", 1)[0].upper() in devices):
            raise ValueError("ambiguous_path")
    return path


def build_plan(*, user_root: str, bundle: str, python: str, vault: str,
               expected_vault: str, user_sid: str, source_commit: str,
               manifest_sha256: str) -> dict:
    """Return an unverified, disabled design, never an activation artifact.

    Caller-supplied identities and hashes are labels, not proof of review. No
    filesystem, process, environment, registry, scheduler or network access.
    """
    root, package, interpreter, target, expected = map(
        exact_path, (user_root, bundle, python, vault, expected_vault))
    if (len(root.parts) != 3 or root.parts[1] != "Users"
            or root.name.casefold() in {"public", "default", "all users"}
            or not re.fullmatch(r"[0-9a-f]{40}", source_commit)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256)
            or not re.fullmatch(r"S-1-5-21-(?:[1-9][0-9]{0,9}-){3}[1-9][0-9]{0,9}", user_sid)):
        raise ValueError("invalid_identity_or_pin")
    stable = root / "AppData" / "Local" / "HomeHub" / "ObsidianMirror" / source_commit
    if package != stable or str(package) != str(stable):
        raise ValueError("stable_versioned_user_bundle_required")
    if (interpreter.name != "python.exe" or not interpreter.is_relative_to(root)
            or any(p.casefold() in {"worktrees", ".git"} for p in interpreter.parts)):
        raise ValueError("reviewed_user_local_python_required")
    if (str(target) != str(expected) or not target.is_relative_to(root)
            or target == root or target.is_relative_to(package)
            or package.is_relative_to(target)):
        raise ValueError("unexpected_vault")
    return {
        "schema": "homehub.obsidian.schedule-plan.v1",
        "status": "plan_only_unverified",
        "enabled": False,
        "task_name": "HomeHub Obsidian Mirror Refresh",
        "principal": {"UserId": user_sid, "LogonType": "InteractiveToken",
                      "RunLevel": "LeastPrivilege", "ordinary_user_required": True},
        "triggers": [
            {"type": "LogonTrigger", "UserId": user_sid},
            {"type": "CalendarTrigger", "schedule": "daily", "local_time": "00:00:00",
             "repetition": {"Interval": "PT1H", "Duration": "P1D",
                            "StopAtDurationEnd": False}},
        ],
        "settings": {"MultipleInstancesPolicy": "IgnoreNew", "StartWhenAvailable": False,
                     "WakeToRun": False, "RestartCount": 0,
                     "RunOnlyIfNetworkAvailable": False, "ExecutionTimeLimit": "PT0S",
                     "AllowHardTerminate": False, "DisallowStartIfOnBatteries": False,
                     "StopIfGoingOnBatteries": False},
        "logged_off_policy": "skip_without_write_no_catchup",
        "offline_policy": "existing_one_shot_fails_closed_no_retry_or_fallback",
        "future_action_record": {
            "implemented": False, "executable": str(interpreter),
            "argv": ["-I", "-B", str(package / "launch_obsidian_mirror.py")],
            "launcher_contract": "verify_pins_before_import_then_call_existing_cli_once",
            "fixed_cli_argv": ["--apply", "--approve-local-evaluation", "--vault",
                               str(target), "--expected-vault", str(expected)],
            "source_commit": source_commit, "manifest_sha256": manifest_sha256,
        },
        "activation_gates": ["independent_security_review", "transitive_integrity_launcher",
                             "verify_ordinary_user_and_exact_paths_on_host",
                             "runtime_timeout_and_interruption_review",
                             "separate_physical_install_and_activation_authorization"],
    }


def main(argv=None, *, output=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("user-root", "bundle", "python", "vault", "expected-vault",
                 "user-sid", "source-commit", "manifest-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        plan = build_plan(**vars(args))
    except ValueError:
        print('{"status":"invalid_plan_parameters"}', file=output or sys.stdout)
        return 2
    print(json.dumps(plan, sort_keys=True, separators=(",", ":")), file=output or sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
