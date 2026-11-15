"""Read-only Linux metadata blocker probe. No CLI, installer or custody proof.

The sole public probe takes no arguments. O_PATH descriptors never read key,
registry or other file contents, and cannot block opening a FIFO/device. Private
dirfd primitives are for disposable kernel tests, never privileged entrypoints.
Even clean metadata is only a namespace-local snapshot, not OS authorization.
"""
from dataclasses import dataclass
import os
import stat
import sys

from .custody_plan import ARTIFACTS


# These two directories are intentionally broker-owned 0700 rather than
# root-owned. Without independently bound numeric service credentials, walking
# their children cannot establish custody; mark descendants uninspected.
PRIVATE_BOUNDARIES = ("/var/lib/homehub-identity/", "/var/lib/homehub-identity-anchor/")


def _private_descendant(path):
    return any(path.startswith(prefix) for prefix in PRIVATE_BOUNDARIES)


MISSING = (
    "root-controlled-probe-and-loaded-interpreter-dependency-closure",
    "dedicated-account-uid-gid-and-supplementary-group-binding",
    "pid1-system-manager-and-exact-descriptor-creator-provenance",
    "posix-acl-and-mac-enforcement",
    "mount-alias-and-namespace-custody",
    "continuous-custody-reboot-replacement-and-aba-exclusion",
    "backup-exemptions-and-crash-durability",
    "independent-external-backend-startup-deploy-rollback-floor",
)


@dataclass(frozen=True)
class Observation:
    """Only fixed artifact ordinal and bounded status; never exception text."""

    artifact: int
    status: str


@dataclass(frozen=True)
class PreflightReport:
    observations: tuple[Observation, ...]
    missing: tuple[str, ...] = MISSING

    @property
    def runtime_authorized(self):
        return False


def _stamp(node):
    return (node.st_dev, node.st_ino, node.st_mode, node.st_uid, node.st_gid,
            node.st_nlink, node.st_ctime_ns)


def _metadata(node, kind, uid, gid, mode):
    """None identities mean unavailable, never a wildcard approval."""
    types = {"directory": stat.S_ISDIR, "file": stat.S_ISREG, "socket": stat.S_ISSOCK}
    if (not types[kind](node.st_mode) or stat.S_IMODE(node.st_mode) != mode
            or (kind != "directory" and node.st_nlink != 1)):
        return "metadata-mismatch"
    if ((uid is not None and node.st_uid != uid)
            or (gid is not None and node.st_gid != gid)):
        return "metadata-mismatch"
    if uid is None or gid is None:
        return "identity-unverified"
    return "metadata-observed"


def _recheck(edges):
    # Held parents prevent a redirected lookup. Recheck *every* edge, including
    # ancestors, to detect persistent rename/replacement. ABA is still unproved.
    return all(_stamp(os.fstat(fd)) == stamp
               and _stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)) == stamp
               for parent, name, fd, stamp in edges)


def _walk(rootfd, components, kind, uid, gid, mode):
    """Internal metadata-only primitive; callers own rootfd, all child FDs close."""
    descriptors, edges = [], []
    try:
        if not components:
            return "invalid-component"
        parent = rootfd
        root = os.fstat(rootfd)
        if (not stat.S_ISDIR(root.st_mode) or root.st_uid != 0 or root.st_gid != 0
                or stat.S_IMODE(root.st_mode) & 0o7022):
            return "unsafe-ancestor"
        for index, name in enumerate(components):
            if not name or name in {".", ".."} or "/" in name:
                return "invalid-component"
            flags = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
            if index < len(components) - 1:
                flags |= os.O_DIRECTORY
            fd = os.open(name, flags, dir_fd=parent)
            descriptors.append(fd)
            node = os.fstat(fd)
            edges.append((parent, name, fd, _stamp(node)))
            if stat.S_ISLNK(node.st_mode):
                return "symlink"
            if index < len(components) - 1:
                if (node.st_uid != 0 or node.st_gid != 0
                        or stat.S_IMODE(node.st_mode) & 0o7022):
                    return "unsafe-ancestor"
            parent = fd
        result = _metadata(node, kind, uid, gid, mode)
        if not _recheck(edges) or _stamp(os.fstat(rootfd)) != _stamp(root):
            return "changed"
        return result
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unobservable"
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def probe():
    """Observe ONLY the fixed proposed layout in this process's Linux namespace.

    No NSS lookup (which could invoke network helpers), environment, subprocess,
    systemd query, content read, socket connection or caller path. Dedicated
    identities therefore remain unverified; root ownership is checked directly.
    A floor file's metadata never proves independent enforcement.
    """
    if sys.platform != "linux":
        return PreflightReport((Observation(-1, "linux-required"),))
    observations = []
    try:
        # Actual kernel process credentials, not supplied identity claims. Only
        # the bounded classification is returned; no group/name inventory leaks.
        credentials = (*os.getresuid(), *os.getresgid(), *os.getgroups())
        observations.append(Observation(-1, "root-process-observed" if
            all(value == 0 for value in credentials) else "nonroot-process-observed"))
        rootfd = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except (OSError, AttributeError):
        return PreflightReport((Observation(-1, "kernel-credentials-or-root-unobservable"),))
    try:
        for index, (path, kind, owner, group, mode) in enumerate(ARTIFACTS):
            if _private_descendant(path):
                # Broker-owned 0700 parent may be perfectly correct but its UID
                # cannot be authenticated by this probe. Do not call it unsafe,
                # inspect children as if trusted, or claim .next/WAL absence.
                observations.append(Observation(index, "private-ancestor-identity-unverified"))
                continue
            status = _walk(rootfd, path.split("/")[1:],
                           "file" if kind in {"optional", "absent"} else kind,
                           0 if owner == "root" else None,
                           0 if group == "root" else None, mode)
            if kind == "absent" or path.endswith(("-wal", "-shm")):
                status = "absence-observed" if status == "absent" else "unexpected-or-uncertain"
            elif kind == "optional" and status == "absent":
                status = "absence-observed"
            observations.append(Observation(index, status))
    finally:
        os.close(rootfd)
    return PreflightReport(tuple(observations))
