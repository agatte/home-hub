"""Inert system-manager proposal lint. No installer, launcher or OS attestation.

Only the two named .in source fragments are accepted. Passing this lint never
authorizes runtime; even exact files require a separately reviewed root package.
"""
from dataclasses import dataclass
from pathlib import Path
import stat


HEADER = "# DO-NOT-INSTALL: source-only proposal; no runtime authorization.\n"
SOCKET_NAME = "homehub-identity.socket.in"
SERVICE_NAME = "homehub-identity.service.in"
MAX_SOURCE_BYTES = 8192  # Bound untrusted local fragment reads even under file growth.

# Immutable source schema. No setting, environment input or caller-provided
# manifest can expand the schema or turn this proposal into installation proof.
SCHEMA = (
    (SOCKET_NAME, (
        ("Unit", (("Description", "INACTIVE HomeHub verify socket proposal"),)),
        ("Socket", (
            ("ListenStream", "/run/homehub-identity/verify.sock"),
            ("Service", "homehub-identity.service"),
            ("FileDescriptorName", "verify"),
            ("SocketUser", "root"),
            ("SocketGroup", "homehub-backend"),
            ("SocketMode", "0660"),
            ("DirectoryMode", "0755"),
            ("Accept", "no"),
            ("RemoveOnStop", "no"),
        )),
    )),
    (SERVICE_NAME, (
        ("Unit", (("Description", "INACTIVE HomeHub verify service proposal"),)),
        ("Service", (
            ("Type", "simple"),
            ("User", "homehub-identity"),
            ("Group", "homehub-identity"),
            ("SupplementaryGroups", ""),
            ("Sockets", "homehub-identity.socket"),
            ("UMask", "0077"),
            ("NoNewPrivileges", "yes"),
            ("ProtectSystem", "strict"),
            ("ProtectHome", "yes"),
            ("PrivateTmp", "yes"),
            ("PrivateDevices", "yes"),
            ("PrivateMounts", "yes"),
            ("ProtectKernelTunables", "yes"),
            ("ProtectKernelModules", "yes"),
            ("ProtectKernelLogs", "yes"),
            ("ProtectControlGroups", "yes"),
            ("RestrictSUIDSGID", "yes"),
            ("RestrictNamespaces", "yes"),
            ("LockPersonality", "yes"),
            ("CapabilityBoundingSet", ""),
            ("AmbientCapabilities", ""),
            ("RestrictAddressFamilies", "AF_UNIX"),
            ("ReadWritePaths", "/var/lib/homehub-identity /var/lib/homehub-identity-anchor"
             " /run/homehub-identity-lock/verify.lock"),
            ("StandardInput", "null"),
            ("StandardOutput", "null"),
            ("StandardError", "null"),
            ("Restart", "no"),
        )),
    )),
)


def proposed_sources():
    """Fresh text mapping, not install files or a command generator."""
    return {
        name: HEADER + "\n" + "\n\n".join(
            "[" + section + "]\n" + "\n".join(key + "=" + value for key, value in pairs)
            for section, pairs in sections
        ) + "\n"
        for name, sections in SCHEMA
    }


def _parse(text):
    """Deliberately smaller than systemd syntax: no escapes, repeats or overrides."""
    sections = {}
    current = None
    for line in text.splitlines():
        if not line or line == HEADER.rstrip("\n"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            if current in sections:
                raise ValueError("duplicate section")
            sections[current] = {}
        else:
            key, separator, value = line.partition("=")
            if current is None or not separator or key in sections[current]:
                raise ValueError("stray or duplicate directive")
            sections[current][key] = value
    return sections


@dataclass(frozen=True)
class ContractReport:
    issues: tuple[str, ...]

    @property
    def source_consistent(self):
        return not self.issues

    @property
    def runtime_authorized(self):
        """Intentionally unconditional; source exactness is never custody proof."""
        return False


def validate_sources(sources):
    """Exact plain names, types, sections, keys, values AND canonical source text.

    LF and CRLF checkout line endings are equivalent; all other text is exact.
    Unknown filenames, paths, install sections, exec/env directives and even
    semantically equivalent overrides are refused. No subprocess or environment.
    """
    expected = proposed_sources()
    if type(sources) is not dict or set(sources) != set(expected):
        return ContractReport(("source-inventory",))
    issues = []
    for name, target in expected.items():
        value = sources[name]
        if type(value) is not str:
            issues.append(name)
            continue
        value = value.replace("\r\n", "\n")
        try:
            if _parse(value) != _parse(target) or value != target:
                issues.append(name)
        except ValueError:
            issues.append(name)
    return ContractReport(tuple(issues))


def validate_supplied_files():
    """Read ONLY this module's two fixed sibling sources, never an install path.

    Reject symlink/reparse ancestors and fragments, nonregular files, extra
    directory entries and hard links. This is offline lint, not a race-safe
    root attestor; concurrent writers and OS namespace custody remain unproved.
    """
    directory = Path(__file__).absolute().parent / "systemd"
    try:
        for path in (directory, *directory.parents):
            node = path.lstat()
            if (not stat.S_ISDIR(node.st_mode) or path.is_symlink()
                    or getattr(node, "st_file_attributes", 0) & 0x400):
                return ContractReport(("source-path",))
        if {p.name for p in directory.iterdir()} != {SOCKET_NAME, SERVICE_NAME}:
            return ContractReport(("source-inventory",))
        sources = {}
        for name in (SOCKET_NAME, SERVICE_NAME):
            path = directory / name
            node = path.lstat()
            if (not stat.S_ISREG(node.st_mode) or path.is_symlink() or node.st_nlink != 1
                    or getattr(node, "st_file_attributes", 0) & 0x400):
                return ContractReport(("source-path",))
            # Both fstat size and a bounded read are needed: size may change
            # after lstat, so never decode an unbounded attacker-written file.
            if node.st_size > MAX_SOURCE_BYTES:
                return ContractReport(("source-size",))
            with path.open("rb") as stream:
                payload = stream.read(MAX_SOURCE_BYTES + 1)
            if len(payload) > MAX_SOURCE_BYTES:
                return ContractReport(("source-size",))
            sources[name] = payload.decode("ascii")
        return validate_sources(sources)
    except (OSError, UnicodeError):
        return ContractReport(("source-read",))
