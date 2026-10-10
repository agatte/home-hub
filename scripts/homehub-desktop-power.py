#!/usr/bin/env python3
"""Save HOME desktop settings, apply TRAVEL, and restore on Return Home."""
import json
from pathlib import Path
import subprocess
import sys

ROOT_HELPER = "/usr/local/libexec/homehub-system-power"
POWER = "org.gnome.settings-daemon.plugins.power"
SESSION = "org.gnome.desktop.session"
LOCK = "org.gnome.desktop.screensaver"
TRAVEL = {
    (SESSION, "idle-delay"): "uint32 300",
    (POWER, "idle-dim"): "true",
    (POWER, "sleep-inactive-ac-type"): "'suspend'",
    (POWER, "sleep-inactive-ac-timeout"): "1800",
    (POWER, "sleep-inactive-battery-type"): "'suspend'",
    (POWER, "sleep-inactive-battery-timeout"): "900",
    (LOCK, "lock-enabled"): "true",
    (LOCK, "lock-delay"): "uint32 0",
}


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=25).stdout.strip()


def snapshot_path():
    return Path.home() / ".local/state/home-hub/power-home-settings.json"


def save_home():
    path = snapshot_path()
    if path.is_symlink():
        raise RuntimeError("Refusing symlink at desktop power snapshot")
    if path.exists():
        return
    settings = [{"schema": schema, "key": key,
                 "value": command("gsettings", "get", schema, key)} for schema, key in TRAVEL]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(settings, stream)
    path.chmod(0o600)


def restore_home():
    path = snapshot_path()
    if not path.exists():
        return
    if path.is_symlink():
        raise RuntimeError("Refusing symlink at desktop power snapshot")
    records = json.loads(path.read_text())
    if not isinstance(records, list) or len(records) != len(TRAVEL):
        raise RuntimeError("Invalid desktop power snapshot")
    restored = set()
    for item in records:
        pair = (item["schema"], item["key"])
        if pair not in TRAVEL or pair in restored or not isinstance(item["value"], str):
            raise RuntimeError("Invalid desktop power setting")
        restored.add(pair)
    for item in records:
        command("gsettings", "set", item["schema"], item["key"], item["value"])
    # Keep the baseline across failed return/retry; a new HOME baseline is
    # captured only after a completed transition explicitly calls finish-home.


def apply(mode):
    if mode == "travel":
        save_home()
        try:
            for pair, value in TRAVEL.items():
                command("gsettings", "set", *pair, value)
            command("sudo", "-n", ROOT_HELPER, "travel")
        except Exception:
            # Root helper remains masked on failure. Restore desktop policy too.
            restore_home()
            raise
    elif mode == "home":
        command("sudo", "-n", ROOT_HELPER, "home")
        restore_home()
    elif mode == "finish-home":
        path = snapshot_path()
        if path.is_symlink():
            raise RuntimeError("Refusing symlink at desktop power snapshot")
        if path.exists():
            path.unlink()
    else:
        raise ValueError("Invalid power mode")


def update_prompts(action):
    settings = {
        ("com.ubuntu.update-notifier", "no-show-notifications"): "true",
        ("com.ubuntu.update-notifier", "regular-auto-launch-interval"): "14",
    }
    # Some Ubuntu versions lack this preference. Inspect before setting it.
    try:
        keys = command("gsettings", "list-keys", "com.ubuntu.update-manager").splitlines()
        if "auto-launch" in keys:
            settings[("com.ubuntu.update-manager", "auto-launch")] = "false"
    except subprocess.CalledProcessError:
        pass
    path = snapshot_path().with_name("update-prompt-settings.json")
    if path.is_symlink():
        raise RuntimeError("Refusing symlink at update prompt snapshot")
    if action == "quiet-updates":
        if not path.exists():
            records = [{"schema": pair[0], "key": pair[1],
                        "value": command("gsettings", "get", *pair)} for pair in settings]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x") as stream:
                json.dump(records, stream)
            path.chmod(0o600)
        for pair, value in settings.items():
            command("gsettings", "set", *pair, value)
    elif path.exists():
        records = json.loads(path.read_text())
        # Restore only keys this tool owns, even if a schema later changes.
        allowed = set(settings) | {("com.ubuntu.update-manager", "auto-launch")}
        if not isinstance(records, list) or not records or any(
            (item["schema"], item["key"]) not in allowed or not isinstance(item["value"], str)
            for item in records):
            raise RuntimeError("Invalid update prompt snapshot")
        for item in records:
            command("gsettings", "set", item["schema"], item["key"], item["value"])
        path.unlink()


if __name__ == "__main__":
    actions = ("home", "travel", "finish-home", "quiet-updates", "restore-updates")
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        sys.exit("Usage: homehub-desktop-power.py " + "|".join(actions))
    try:
        if sys.argv[1] in ("quiet-updates", "restore-updates"):
            update_prompts(sys.argv[1])
        else:
            apply(sys.argv[1])
    except Exception as error:
        sys.exit(str(error))
