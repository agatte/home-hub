#!/usr/bin/python3 -I
"""One-time root installation; backups precede all system policy changes."""
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile

HELPER = Path("/usr/local/libexec/homehub-system-power")
SUDOERS = Path("/etc/sudoers.d/homehub-power-mode")
DROPIN = Path("/etc/systemd/logind.conf.d/99-homehub-power-mode.conf")
APT = Path("/etc/apt/apt.conf.d/99homehub-maintenance")
APT_POLICY = ('// HomeHub maintenance: daily checks, manual reboot\n'
              'APT::Periodic::Update-Package-Lists "1";\n'
              'APT::Periodic::Unattended-Upgrade "1";\n'
              'Unattended-Upgrade::Automatic-Reboot "false";\n')
BACKUP = Path("/var/lib/homehub-power-policy")
USER = "anthony"
TARGETS = ("sleep.target", "suspend.target")


def run(*args):
    subprocess.run(args, check=True, timeout=25)


def install_new(path, content, mode):
    """Publish complete root-owned files without replacing an existing path."""
    descriptor, temporary = tempfile.mkstemp(prefix=".homehub-install-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def overrides():
    state = {}
    for directory in ("/etc/systemd/system", "/run/systemd/system"):
        for unit in TARGETS:
            path = Path(directory) / unit
            if path.is_symlink() and os.readlink(path) == "/dev/null":
                state[str(path)] = "/dev/null"
            elif not path.is_symlink() and not path.exists():
                state[str(path)] = None
            else:
                raise RuntimeError(f"Unexpected unit override: {path}")
    return state


def install():
    account = pwd.getpwnam(USER)
    if account.pw_dir != "/home/anthony":
        raise RuntimeError("Unexpected Anthony home directory")
    for path in (HELPER, SUDOERS, DROPIN, APT, BACKUP):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"Already present; inspect before replacing: {path}")
    state = overrides()
    source = Path(__file__).resolve().with_name("homehub-system-power.py")
    desktop = source.with_name("homehub-desktop-power.py")
    if not source.is_file() or not desktop.is_file():
        raise RuntimeError("Run installer from reviewed HomeHub scripts directory")
    for directory in (HELPER.parent, SUDOERS.parent, DROPIN.parent, APT.parent):
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_uid != 0 or directory.stat().st_mode & 0o022:
            raise RuntimeError(f"Unsafe installation directory: {directory}")
    BACKUP.mkdir(mode=0o700)
    (BACKUP / "original-masks.json").write_text(json.dumps(state, indent=2))
    shutil.copy2("/etc/systemd/logind.conf", BACKUP / "logind.conf.before")
    helper_bytes = source.read_bytes()
    (BACKUP / "reviewed-helper.py").write_bytes(helper_bytes)
    rule = f"{USER} ALL=(root) NOPASSWD: {HELPER} home, {HELPER} travel\n"
    proposed = BACKUP / "sudoers.proposed"
    proposed.write_text(rule)
    run("/usr/sbin/visudo", "-cf", str(proposed))
    install_new(HELPER, helper_bytes, 0o755)
    install_new(SUDOERS, proposed.read_bytes(), 0o440)
    # Installation never releases the current HOME sleep blocks.
    run(str(HELPER), "home")
    # Existing APT files and allowed repositories are left intact. Removing
    # this new override restores their previous values.
    install_new(APT, APT_POLICY.encode(), 0o644)
    print(f"Installed HOME/TRAVEL power policy. Rollback evidence: {BACKUP}")


def restore():
    if BACKUP.is_symlink() or BACKUP.stat().st_uid != 0 or BACKUP.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe rollback directory")
    state = json.loads((BACKUP / "original-masks.json").read_text())
    allowed = {str(Path(d) / u) for d in ("/etc/systemd/system", "/run/systemd/system") for u in TARGETS}
    if set(state) != allowed or any(v not in (None, "/dev/null") for v in state.values()):
        raise RuntimeError("Invalid mask rollback evidence")
    for path in (HELPER, SUDOERS, DROPIN, APT):
        if path.is_symlink():
            raise RuntimeError(f"Refusing unexpected symlink: {path}")
    if HELPER.exists() and HELPER.read_bytes() != (BACKUP / "reviewed-helper.py").read_bytes():
        raise RuntimeError("Installed helper changed; inspect before restoring")
    if SUDOERS.exists() and SUDOERS.read_bytes() != (BACKUP / "sudoers.proposed").read_bytes():
        raise RuntimeError("Installed sudoers changed; inspect before restoring")
    configs = [("# Managed by HomeHub power policy\n[Login]\n"
                f"HandleLidSwitch={action}\nHandleLidSwitchExternalPower={action}\n"
                "HandleLidSwitchDocked=ignore\n") for action in ("ignore", "suspend")]
    if DROPIN.exists() and DROPIN.read_text() not in configs:
        raise RuntimeError("Drop-in changed; inspect before restoring")
    if APT.exists() and APT.read_text() != APT_POLICY:
        raise RuntimeError("APT policy changed; inspect before restoring")
    overrides()
    run("/usr/bin/systemctl", "unmask", *TARGETS)
    run("/usr/bin/systemctl", "unmask", "--runtime", *TARGETS)
    for name, value in state.items():
        if value == "/dev/null":
            Path(name).symlink_to(value)
    for path in (DROPIN, SUDOERS, HELPER, APT):
        if path.is_symlink():
            raise RuntimeError(f"Refusing unexpected symlink: {path}")
        if path.exists():
            path.unlink()
    run("/usr/bin/systemctl", "daemon-reload")
    run("/usr/bin/systemctl", "kill", "--kill-whom=main", "--signal=HUP", "systemd-logind.service")
    print("Original system power policy restored; rollback evidence retained.")


if __name__ == "__main__":
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in ("install", "restore"):
        sys.exit("Requires root: install-homehub-power-policy.py install|restore")
    try:
        install() if sys.argv[1] == "install" else restore()
    except Exception as error:
        sys.exit(str(error))
