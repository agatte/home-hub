#!/usr/bin/python3 -I
"""Root-owned, fixed-scope HOME/TRAVEL sleep policy. No caller-supplied paths."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

TARGETS = ("sleep.target", "suspend.target")
DROPIN = Path("/etc/systemd/logind.conf.d/99-homehub-power-mode.conf")
SYSTEMCTL = "/usr/bin/systemctl"


def run(*args):
    subprocess.run(args, check=True, timeout=20)


def lid_config(mode):
    action = "ignore" if mode == "home" else "suspend"
    return ("# Managed by HomeHub power policy\n[Login]\n"
            f"HandleLidSwitch={action}\nHandleLidSwitchExternalPower={action}\n"
            "HandleLidSwitchDocked=ignore\n")


def validate_mask_paths():
    # Never let unmask remove a custom unit or an unexpected symlink.
    for directory in ("/etc/systemd/system", "/run/systemd/system"):
        for unit in TARGETS:
            path = Path(directory) / unit
            if path.is_symlink():
                if os.readlink(path) != "/dev/null":
                    raise RuntimeError(f"Unexpected target override: {path}")
            elif path.exists():
                raise RuntimeError(f"Custom target override: {path}")


def write_lid_config(mode):
    parent = DROPIN.parent
    parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if parent.is_symlink() or parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022:
        raise RuntimeError("Unsafe logind configuration directory")
    if DROPIN.is_symlink():
        raise RuntimeError("Refusing symlink at managed drop-in")
    if DROPIN.exists() and (DROPIN.stat().st_uid != 0 or DROPIN.stat().st_mode & 0o022):
        raise RuntimeError("Unsafe ownership or permissions on managed drop-in")
    if DROPIN.exists() and DROPIN.read_text() not in (lid_config("home"), lid_config("travel")):
        raise RuntimeError("Managed drop-in has unexpected content")
    fd, temporary = tempfile.mkstemp(prefix=".homehub-power-", dir=parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(lid_config(mode))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, DROPIN)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(mode):
    if mode not in ("home", "travel"):
        raise ValueError("Only home or travel is supported")
    validate_mask_paths()
    # Block sleep before changing HOME policy; release it last for TRAVEL.
    run(SYSTEMCTL, "mask", *TARGETS)
    try:
        write_lid_config(mode)
        run(SYSTEMCTL, "kill", "--kill-whom=main", "--signal=HUP", "systemd-logind.service")
        if mode == "travel":
            run(SYSTEMCTL, "unmask", *TARGETS)
            run(SYSTEMCTL, "unmask", "--runtime", *TARGETS)
            for unit in TARGETS:
                result = subprocess.run(
                    (SYSTEMCTL, "show", unit, "-p", "LoadState", "--value"),
                    check=True, capture_output=True, text=True, timeout=10)
                if result.stdout.strip() != "loaded":
                    raise RuntimeError(f"{unit} is not available after unmask")
    except Exception:
        # A partial transition must leave the laptop awake, not suspend it.
        run(SYSTEMCTL, "mask", *TARGETS)
        raise


if __name__ == "__main__":
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in ("home", "travel"):
        sys.exit("Requires root and exactly one action: home or travel")
    try:
        import fcntl
        flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
        descriptor = os.open("/run/lock/homehub-power-mode.lock", flags, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            if os.fstat(lock.fileno()).st_uid != 0:
                raise RuntimeError("Unsafe power policy lock")
            fcntl.flock(lock, fcntl.LOCK_EX)
            apply(sys.argv[1])
    except Exception as error:
        sys.exit(str(error))
