"""Read-only Linux cutover inventory. Never admission, installation or attestation.

Fixed CLI scope; injection is for offline tests only. No backend imports, environment
reads, policy contents, credential reads, network clients or lifecycle commands.
Metadata snapshots do not prove ACL/mount/loader closure or exclude concurrent changes.
"""
import hashlib
import ipaddress
import json
import os
from pathlib import PurePosixPath
import stat
import subprocess
import sys


CHECKOUT = "/home/anthony/home-hub"
UNITS = (("system", "home-hub-http.socket"),
         ("system", "homehub-identity.socket"),
         ("system", "homehub-identity.service"),
         ("system", "homehub-backend.service"),
         ("user", "home-hub.service"))
PROPERTIES = ("LoadState", "ActiveState", "SubState", "UnitFileState", "Names",
              "FragmentPath", "DropInPaths", "User", "Group", "Listen", "ReusePort",
              "Accept", "Service", "Sockets", "NoNewPrivileges", "ProtectSystem",
              "ExecStart", "ExecStartPre")
PATHS = ("/etc/homehub-identity/backend-floor.json",
         "/opt/homehub-backend/package", "/opt/homehub-identity/runtime", CHECKOUT)
SEALED_MODES = dict(zip(PATHS[:3], ("0444", "0444", "0555")))
# Full normalized source fingerprints, not substring approval. Any change is UNKNOWN.
SOURCES = {
    "deployment/home-hub.service": (
        "6ab7c3ea420d5f529828819c8cf3eb5e8644d0d9690b48bdb0d136e57542144d",
        "mutable-user-exec-and-default-target"),
    "scripts/deploy.sh": (
        "2398347dc2cdf447fe9ff8fb0c5b8b1c660d07c532ddaa1c6bd8f5a11eb16d72",
        "checkout-reset-and-user-restart"),
    "scripts/homehub-hostctl.sh": (
        "dea4ea4f44cb0feb9c2ea2964a859e35db42068e2c479b9bdc215f61c2f8cd09",
        "return-home-user-enable-start"),
    "run.py": (
        "b38bd47078fea02a82fd5c1584e7b242e75b9703dc7d371fa2fec12a788ef8dd",
        "manual-ipv4-wildcard-8000"),
    "deployment/home-hub-tunnel.service": (
        "63a9d16decd51f0e87f386e9f66df72e7cc660e9737b827d3e900e21c71a5d9c",
        "user-loopback-proxy-8002-to-8000"),
    "deployment/home-hub-guest-gateway.service": (
        "d27ac440527708d1503befd01b337756b84be121d5d3b85f778a7d5c06b4aaed",
        "user-loopback-guest-gateway-8003"),
}
LIMIT = 262144
SS = ("/usr/bin/ss", "-H", "-ltn")


def unit_command(scope, name):
    return ("/usr/bin/systemctl", "--" + scope, "show", name, "--no-pager",
            "--property=" + ",".join(PROPERTIES))


COMMANDS = (SS,) + tuple(unit_command(*unit) for unit in UNITS)


class FileSystem:
    """Read only fixed public source files; no-follow directory traversal on Linux."""

    def lstat(self, path):
        return os.lstat(path)

    def read(self, path):
        allowed = {CHECKOUT + "/" + p for p in SOURCES} | {"/proc/1/comm"}
        if path not in allowed:
            raise OSError("not an inventory source")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            parts = PurePosixPath(path).parts[1:]
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=fd)
                os.close(fd)
                fd = child
            leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                           dir_fd=fd)
            try:
                before = os.fstat(leaf)
                if not stat.S_ISREG(before.st_mode):
                    raise OSError("not regular")
                data = bytearray()
                while len(data) <= LIMIT:
                    block = os.read(leaf, min(8192, LIMIT + 1 - len(data)))
                    if not block:
                        break
                    data.extend(block)
                after = os.fstat(leaf)
                # Reading can itself update atime; compare identity/content
                # metadata, not access time. This still cannot defeat ABA/root.
                fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
                          "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
                if len(data) > LIMIT or any(getattr(before, k) != getattr(after, k)
                                           for k in fields):
                    raise OSError("unstable or oversized")
                return bytes(data)
            finally:
                os.close(leaf)
        finally:
            os.close(fd)


def run_readonly(command):
    if command not in COMMANDS:
        raise ValueError("command outside inventory")
    # Do not inherit PATH, loader/Python variables or caller bus overrides.
    uid = os.getuid()
    environment = {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin",
                   "XDG_RUNTIME_DIR": f"/run/user/{uid}",
                   "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus"}
    result = subprocess.run(command, shell=False, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=10, check=False, env=environment)
    if result.returncode or len(result.stdout) > LIMIT:
        raise OSError("command unavailable or oversized")
    return result.stdout.decode("utf-8", errors="strict")


def metadata(fs, path, protected=True, expected_leaf_kind="file"):
    """Exact lstat for every ancestor; require the expected leaf kind."""
    records = []
    parts = PurePosixPath(path).parts
    for index in range(1, len(parts) + 1):
        current = str(PurePosixPath(*parts[:index]))
        try:
            value = fs.lstat(current)
        except OSError:
            return records, "UNKNOWN"
        mode = stat.S_IMODE(value.st_mode)
        kind = ("directory" if stat.S_ISDIR(value.st_mode) else
                "file" if stat.S_ISREG(value.st_mode) else
                "symlink" if stat.S_ISLNK(value.st_mode) else "other")
        records.append({"path": current, "uid": value.st_uid, "gid": value.st_gid,
                        "mode": f"{mode:04o}", "kind": kind})
        if (kind not in ("file", "directory") or
                (index < len(parts) and kind != "directory") or
                mode & 0o022 or (protected and (value.st_uid != 0 or value.st_gid != 0))):
            return records, "UNSAFE"
    if kind != expected_leaf_kind:
        return records, "UNSAFE"
    return records, "INSPECTED"


def listeners(text):
    """No raw address/process output; only relevant port, family and bind scope."""
    found = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0] != "LISTEN":
            raise ValueError("unknown ss layout")
        host, separator, port = fields[3].rpartition(":")
        if not separator or not port.isdecimal() or not 0 < int(port) < 65536:
            raise ValueError("unknown endpoint")
        host = host.removeprefix("[").removesuffix("]")
        if host == "*":
            family, scope = "unknown", "wildcard"
        else:
            address = ipaddress.ip_address(host)
            family = "ipv4" if address.version == 4 else "ipv6"
            scope = ("wildcard" if address.is_unspecified else
                     "loopback" if address.is_loopback else "nonloopback")
        if int(port) in (8000, 8002, 8003):
            found.append({"port": int(port), "family": family, "scope": scope,
                          "owner": "UNKNOWN"})
    return found


def inspect_unit(text):
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in PROPERTIES or key in values:
            raise ValueError("unexpected unit output")
        values[key] = value
    required = {"LoadState", "ActiveState", "SubState", "UnitFileState",
                "Names", "FragmentPath", "DropInPaths"}
    if not required <= values.keys():
        raise ValueError("incomplete unit output")
    return values


def audit(*, runner, fs):
    blockers = ["external-operational-proof-required",
                "all-client-topology-and-manual-alternate-launches-unverified"]
    report = {"version": 1, "read_only": True, "runtime_authorized": False,
              "status": "BLOCKED", "pid1": "UNKNOWN", "units": [],
              "paths": [], "sources": [], "listeners": {"status": "UNKNOWN"},
              "blockers": blockers,
              "next_gate": "Separate owner authorization for reviewed Latitude inventory; "
              "then independent installed launch-floor/socket/legacy-retirement proof "
              "across boot, restart, deploy, rollback and Return Home. "
              "No enrollment, deployment or #461 acceptance authorized."}
    try:
        if fs.read("/proc/1/comm") == b"systemd\n":
            report["pid1"] = "systemd-observed"
        else:
            blockers.append("pid1-not-systemd")
    except (OSError, ValueError):
        blockers.append("pid1-unknown")
    for path in PATHS:
        records, status = metadata(
            fs, path, path != CHECKOUT,
            expected_leaf_kind="directory" if path == CHECKOUT else "file")
        if status == "INSPECTED" and path in SEALED_MODES:
            if records[-1]["mode"] != SEALED_MODES[path]:
                status = "UNSAFE"
        report["paths"].append({"path": path, "status": status, "metadata": records})
        if status != "INSPECTED":
            blockers.append("path-custody:" + path)
    unit_roots = ("/etc/systemd/system/", "/run/systemd/system/",
                  "/usr/lib/systemd/system/", "/lib/systemd/system/",
                  "/etc/systemd/user/", "/usr/lib/systemd/user/",
                  "/home/anthony/.config/systemd/user/")
    for scope, name in UNITS:
        item = {"scope": scope, "unit": name, "status": "UNKNOWN"}
        report["units"].append(item)
        try:
            values = inspect_unit(runner(unit_command(scope, name)))
            # Never return arbitrary property values, command lines or aliases.
            for key, choices in {
                "LoadState": {"loaded", "not-found", "masked", "error", "bad-setting"},
                "ActiveState": {"active", "inactive", "failed", "activating", "deactivating"},
                "UnitFileState": {"enabled", "disabled", "static", "masked", "alias",
                                  "enabled-runtime", "linked", "linked-runtime", ""},
            }.items():
                if values[key] not in choices:
                    raise ValueError("unknown state")
                item[key] = values[key]
            item["alias_count"] = len(set(values["Names"].split()) - {name})
            paths = values["DropInPaths"].split()
            item["dropin_count"] = len(paths)
            if values["FragmentPath"]:
                paths.append(values["FragmentPath"])
            item["effective_path_metadata"] = []
            for path in paths:
                # Inspect only unit metadata inside known unit directories.
                if (not path.startswith(unit_roots) or
                        any(p in (".", "..") for p in path.split("/")) or
                        not path.endswith((".service", ".socket", ".conf"))):
                    raise ValueError("unknown unit path")
                records, status = metadata(fs, path, scope == "system")
                # Paths from manager output are not echoed. Fixed path inventory
                # above supplies public canonical names; these are ordinal metadata.
                item["effective_path_metadata"].append({"status": status,
                    "components": [{k: v for k, v in r.items() if k != "path"}
                                   for r in records]})
                if status != "INSPECTED":
                    blockers.append("effective-unit-path:" + scope + ":" + name)
            item["status"] = "INSPECTED"
            execution = values.get("ExecStart", "") + values.get("ExecStartPre", "")
            item["execution"] = ("CHECKOUT_REFERENCE_OBSERVED" if CHECKOUT + "/" in execution
                                 else "UNKNOWN")
            if item["execution"] == "CHECKOUT_REFERENCE_OBSERVED":
                blockers.append("mutable-execution-reference:" + scope + ":" + name)
            if values["LoadState"] != "loaded" or not paths:
                blockers.append("unit-not-installed:" + scope + ":" + name)
            if scope == "user":
                blockers.append("legacy-unit-retirement-unverified")
            if item["alias_count"] or item["dropin_count"]:
                blockers.append("unit-alias-dropin-review:" + scope + ":" + name)
            # Selected socket/hardening properties are observed only as exact
            # expected matches, not arbitrary strings or an approval decision.
            item["checks"] = {key: ("UNKNOWN" if key not in values else
                                    "MATCH" if values[key] == expected else "MISMATCH")
                              for key, expected in
                              (("ReusePort", "no"), ("Accept", "no"),
                               ("NoNewPrivileges", "yes"), ("ProtectSystem", "strict"))}
            blockers.append("effective-execution-and-socket-binding-unverified:" + name)
        except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
            blockers.append("unit-unknown:" + scope + ":" + name)
    try:
        report["listeners"] = {"status": "INSPECTED", "endpoints": listeners(runner(SS)),
                               "socket_owner": "UNKNOWN"}
        blockers.append("listener-creator-and-client-topology-unverified")
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        blockers.append("listeners-unknown")
    for relative, (fingerprint, bypass) in SOURCES.items():
        item = {"path": CHECKOUT + "/" + relative, "status": "UNKNOWN"}
        report["sources"].append(item)
        try:
            data = fs.read(item["path"])
            if hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() == fingerprint:
                item.update(status="KNOWN_BYPASS", finding=bypass)
        except OSError:
            pass
        blockers.append("source-" + item["status"].lower() + ":" + relative)
    return report


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments not in ([], ["--json"]):
        print('{"error":"only --json or no arguments supported"}')
        return 2
    if not sys.platform.startswith("linux"):
        print(json.dumps({"version": 1, "read_only": True, "runtime_authorized": False,
                          "status": "BLOCKED", "blockers": ["linux-required"]}))
        return 1
    print(json.dumps(audit(runner=run_readonly, fs=FileSystem()), sort_keys=True))
    return 1  # Inventory is always blocked; never a ready/admission exit code.


if __name__ == "__main__":
    raise SystemExit(main())
