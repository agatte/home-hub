"""Offline install-plan lint only. No filesystem, OS probe, installer or authority.

All evidence is untrusted injected data. Even a consistent report cannot satisfy
RootCustodyProof. In particular two matching snapshots do not exclude ABA races.
"""
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re


# Fixed proposed layout; changing any field requires a source review/version bump.
ARTIFACTS = (
    ("/opt/homehub-identity/package", "file", "root", "root", 0o444),
    ("/opt/homehub-identity/runtime", "file", "root", "root", 0o555),
    ("/etc/homehub-identity/policy.json", "file", "root", "root", 0o444),
    ("/etc/homehub-identity/state.key", "file", "root", "broker", 0o640),
    ("/var/lib/homehub-identity", "directory", "broker", "broker", 0o700),
    ("/var/lib/homehub-identity/registry.sqlite", "file", "broker", "broker", 0o600),
    ("/var/lib/homehub-identity/registry.sqlite-journal", "optional", "broker", "broker", 0o600),
    ("/var/lib/homehub-identity/registry.sqlite-wal", "optional", "broker", "broker", 0o600),
    ("/var/lib/homehub-identity/registry.sqlite-shm", "optional", "broker", "broker", 0o600),
    ("/var/lib/homehub-identity-anchor", "directory", "broker", "broker", 0o700),
    ("/var/lib/homehub-identity-anchor/state.json", "file", "broker", "broker", 0o600),
    ("/var/lib/homehub-identity-anchor/state.deny", "file", "broker", "broker", 0o600),
    ("/var/lib/homehub-identity-anchor/state.json.next", "absent", "broker", "broker", 0o600),
    ("/var/lib/homehub-identity-anchor/state.deny.next", "absent", "broker", "broker", 0o600),
    ("/run/homehub-identity/verify.sock", "socket", "root", "backend", 0o660),
    ("/run/homehub-identity-lock/verify.lock", "file", "root", "broker", 0o660),
    ("/etc/homehub-identity/backend-floor.json", "file", "root", "root", 0o444),
)
HASHED = tuple(p for p, *_ in ARTIFACTS if p in {
    "/opt/homehub-identity/package", "/opt/homehub-identity/runtime",
    "/etc/homehub-identity/policy.json", "/etc/homehub-identity/backend-floor.json",
})
REQUIRED_ATTESTATIONS = (
    "mounts_and_aliases", "acl_and_mac", "namespace_custody", "pid1_provisioner",
    "exact_socket_creator_and_fd_binding", "runtime_dependency_closure",
    "independent_backend_floor_enforcement", "backup_exclusions",
    "dedicated_accounts_and_groups", "continuous_custody_and_freshness",
)


def manifest():
    """Return a fresh fixed source contract, never a runtime configuration."""
    return {
        "format": "homehub-custody-install-plan", "version": 1,
        "status": "ADVISORY-NO-INSTALL", "runtime_authorized": False,
        "principals": {"root": "root", "broker": "homehub-identity",
                       "backend": "homehub-backend"},
        "artifacts": [list(a) for a in ARTIFACTS],
        "socket": "AF_UNIX/SOCK_STREAM; SO_PEERCRED; exact root/PID1 creator PID/UID/GID",
        "admin": "deny-all; no public pairing or same-UID authority",
        "closure": "sealed package AND runtime incl loader/libs/dependencies; no checkout/venv",
        "backup_exclude": ["/var/lib/homehub-identity", "/var/lib/homehub-identity-anchor",
                           "/etc/homehub-identity/state.key"],
        "floor": "root-controlled independent startup/deploy/rollback enforcement",
        "required_attestations": list(REQUIRED_ATTESTATIONS),
        "unit_contract": ["system manager only", "dedicated nonroot User/Group",
                          "inherited verify listener only", "no admin listener",
                          "UMask=0077", "NoNewPrivileges=yes", "ProtectSystem=strict",
                          "ProtectHome=yes", "RestrictAddressFamilies=AF_UNIX",
                          "empty capabilities", "no Install section or ExecStart supplied"],
    }


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _exact_types(value, expected):
    """Do not let JSON normalize tuples to lists or booleans to numbers."""
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return value.keys() == expected.keys() and all(
            _exact_types(value[key], expected[key]) for key in expected
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _exact_types(item, target) for item, target in zip(value, expected)
        )
    return value == expected


def lint_manifest(value):
    """Exact fields/types/values; unknown keys and caller overrides are refused."""
    try:
        expected = manifest()
        return _exact_types(value, expected) and _canonical(value) == _canonical(expected)
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class Node:
    """Fake lstat/hash evidence; never read a key or registry to construct this."""

    kind: str
    uid: int
    gid: int
    mode: int
    device: int
    inode: int
    links: int
    acl: str  # only explicit 'none'; unknown/unsupported is refused
    mount: str  # only explicit 'reviewed'; this assertion is NOT OS proof
    digest: str | None = None
    hashed_at: int | None = None


@dataclass(frozen=True)
class Report:
    issues: tuple[str, ...]
    runtime_authorized: bool = False
    advisory_only: bool = True

    @property
    def snapshot_consistent(self):
        return not any(not issue.startswith("root-attestor-required:") for issue in self.issues)


def preflight(plan, before, after, *, principals, release_hashes, now, attestations):
    """Lint two injected quiescent snapshots; no IO, dynamic import or execution.

    Missing evidence fails. 'reviewed' labels mean an external review is claimed,
    not authenticated. Expected hashes must come from an independent reviewed
    release inventory. No mutable state/key content hashes or secret inputs.
    """
    issues = []
    if not lint_manifest(plan):
        return Report(("manifest",))
    if (type(principals) is not dict or set(principals) != {"root", "broker", "backend"}
            or principals.get("root") != (0, 0)
            or any(type(v) is not tuple or len(v) != 2
                   or any(type(n) is not int or not 0 <= n < 2**32 - 1 for n in v)
                   for v in principals.values())
            or len({v[0] for v in principals.values()}) != 3
            or len({v[1] for v in principals.values()}) != 3):
        return Report(("principals",))
    if type(now) is not int or now <= 0:
        return Report(("clock",))
    if (type(attestations) is not dict or set(attestations) != set(REQUIRED_ATTESTATIONS)
            or any(v != "requires-root-attestor" for v in attestations.values())):
        issues.append("unresolved-or-ambiguous-external-evidence")
    # Deliberately unresolved: no injected assertion may stand in for a root attestor.
    issues.extend("root-attestor-required:" + name for name in REQUIRED_ATTESTATIONS)
    if (type(release_hashes) is not dict or set(release_hashes) != set(HASHED)
            or any(type(h) is not str or re.fullmatch(r"[0-9a-f]{64}", h) is None
                   for h in release_hashes.values())):
        return Report(tuple(issues + ["release-inventory"]))
    required = {p: (kind, owner, group, mode) for p, kind, owner, group, mode in ARTIFACTS}
    for path, *_ in ARTIFACTS:
        for parent in PurePosixPath(path).parents:
            required.setdefault(str(parent), ("directory", "root", "root", None))
    if (type(before) is not dict or type(after) is not dict
            or set(before) != set(required) or set(after) != set(required)):
        return Report(tuple(issues + ["snapshot-inventory"]))
    for path, (kind, owner, group, mode) in required.items():
        node = before[path]
        if node != after[path]:
            issues.append("changed:" + path)
        if node is None and kind in {"optional", "absent"}:
            continue  # explicit absence, never omitted inventory
        if kind == "absent" or type(node) is not Node:
            issues.append("missing-or-uncertain:" + path)
            continue
        integers = (node.uid, node.gid, node.mode, node.device, node.inode, node.links)
        valid = (
            all(type(n) is int and n >= 0 for n in integers)
            and node.inode > 0 and node.links > 0
            and node.kind == ("file" if kind == "optional" else kind)
            and node.uid == principals[owner][0] and node.gid == principals[group][1]
            and (node.mode == mode if mode is not None else
                 node.mode <= 0o777 and not node.mode & 0o022)
            and (node.kind == "directory" or node.links == 1)
            and node.acl == "none" and node.mount == "reviewed"
        )
        if not valid:
            issues.append("metadata:" + path)
        if path in HASHED and (
                node.digest != release_hashes[path] or type(node.hashed_at) is not int
                or not 0 <= now - node.hashed_at <= 60):
            issues.append("hash-or-freshness:" + path)
    return Report(tuple(issues))
