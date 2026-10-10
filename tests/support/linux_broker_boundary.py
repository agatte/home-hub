"""OFFLINE conformance only: no broker, credentials, runtime imports or installer."""
from dataclasses import dataclass
import os
from pathlib import PurePosixPath
import socket
import stat
import struct
import sys


@dataclass(frozen=True)
class Peer:
    pid: int
    uid: int
    gid: int


def peer_credentials(connection):
    """Read Linux connect-time identity, not necessarily the current FD holder."""
    if (os.name != "posix" or sys.platform != "linux"
            or not hasattr(socket, "SO_PEERCRED")
            or not isinstance(connection, socket.socket)
            or connection.family != socket.AF_UNIX
            or connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM):
        raise PermissionError("unsupported peer transport")
    try:
        connection.getpeername()  # Reject listeners and unconnected sockets.
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('iII'))
        peer = Peer(*struct.unpack('iII', raw))
        if peer.pid <= 0 or peer.uid == 0xFFFFFFFF or peer.gid == 0xFFFFFFFF:
            raise ValueError()
        return peer
    except (OSError, ValueError, struct.error):
        raise PermissionError("missing kernel peer identity") from None


@dataclass(frozen=True)
class Boundary:
    # Trusted fixture configuration, NEVER accepted from the socket request.
    backend_uid: int = 41001
    admin_uid: int = 41002
    broker_uid: int = 41003

    def __post_init__(self):
        values = (self.backend_uid, self.admin_uid, self.broker_uid)
        if any(type(v) is not int or v <= 0 for v in values) or len(set(values)) != 3:
            raise ValueError("distinct dedicated fixture identities required")

    def permits(self, peer, endpoint, request, *, fresh_interactive=False):
        """Policy MODEL; successful admission performs no identity operation."""
        if (type(peer) is not Peer or any(type(v) is not int for v in (peer.pid, peer.uid, peer.gid))
                or peer.pid <= 0 or peer.uid < 0 or peer.gid < 0
                or type(request) is not dict or set(request) != {"operation"}
                or type(request["operation"]) is not str):
            return False
        operation = request["operation"]
        if endpoint == "verify":
            return peer.uid == self.backend_uid and operation == "verify"
        return (endpoint == "admin" and peer.uid != self.backend_uid
                and peer.uid in (0, self.admin_uid) and fresh_interactive is True
                and operation in {"bootstrap", "enroll", "revoke", "restore_intent_invalidate"})

    def admit(self, connection, endpoint, request, *, fresh_interactive=False):
        try:
            peer = peer_credentials(connection)
        except (PermissionError, OSError):
            return False
        return self.permits(peer, endpoint, request, fresh_interactive=fresh_interactive)


@dataclass(frozen=True)
class Node:
    """Synthetic lstat metadata: modes include file type; no real host traversal."""
    uid: int
    gid: int
    mode: int
    nlink: int = 1


def trusted_chain(path, metadata):
    """Validate a complete fake absolute parent chain, including its virtual '/'.

    This snapshot model cannot prove ACL/MAC policy or eliminate filesystem races.
    """
    path = PurePosixPath(path)
    if not path.is_absolute() or path.anchor != "/" or ".." in path.parts:
        return False
    for member in (*reversed(path.parents), path):
        node = metadata.get(str(member))
        if (type(node) is not Node or node.uid != 0 or node.mode & 0o022
                or stat.S_ISLNK(node.mode)
                or (stat.S_ISREG(node.mode) and (type(node.nlink) is not int or node.nlink != 1))
                or (member != path and not stat.S_ISDIR(node.mode))
                or not (stat.S_ISDIR(node.mode) or stat.S_ISREG(node.mode))):
            return False
    return True


def private_store(path, metadata, boundary):
    path = PurePosixPath(path)
    if not path.is_absolute() or path.anchor != "/" or ".." in path.parts:
        return False
    node = metadata.get(str(path))
    return (trusted_chain(str(path.parent), metadata) and type(node) is Node
            and node.uid == node.gid == boundary.broker_uid
            and stat.S_ISDIR(node.mode) and stat.S_IMODE(node.mode) == 0o700)


def socket_custody(parent, node, boundary, endpoint):
    """Model separately protected admin parent and explicit verify socket group."""
    if type(parent) is not Node or type(node) is not Node or not stat.S_ISSOCK(node.mode):
        return False
    if not stat.S_ISDIR(parent.mode) or parent.uid != 0:
        return False
    if endpoint == "admin":
        return (parent.gid == 0 and stat.S_IMODE(parent.mode) == 0o700
                and node.uid == node.gid == 0 and stat.S_IMODE(node.mode) == 0o600)
    return (endpoint == "verify" and parent.gid == 0
            and stat.S_IMODE(parent.mode) == 0o755 and node.uid == boundary.broker_uid
            and node.gid == boundary.backend_uid and stat.S_IMODE(node.mode) == 0o660)
