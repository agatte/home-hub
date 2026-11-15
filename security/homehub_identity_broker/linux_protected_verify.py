"""Inactive Linux integration. No privileged proof provider ships in this tree.

RootCustodyProof is an explicit trusted-composition boundary, NOT a capability
that an application caller can obtain by setting a flag or constructing a policy.
An implementation must live in independently root-controlled launcher code. Its
absence deliberately prevents service construction. Python objects cannot prove
systemd provenance, namespace/mount custody, key custody or executable integrity.
"""
from dataclasses import dataclass
import os
from pathlib import PurePosixPath
import socket
import stat
import sys

from .linux_verify_server import ListenerSnapshot, _check_listener, _VerifyTransport
from .runtime import Broker, Denied, directory_sync, unframe

VERIFY_PATH = "/run/homehub-identity/verify.sock"
LOCK_PATH = "/run/homehub-identity-lock/verify.lock"


@dataclass(frozen=True)
class LaunchPolicy:
    """Values supplied ONLY by independently root-controlled composition."""

    service_uid: int
    service_gid: int
    backend_uid: int
    backend_gid: int
    listener: ListenerSnapshot
    lock_identity: tuple[int, int]
    # Exact listener creator, NOT the later service acceptor. Attestor-bound.
    creator_peer: tuple[int, int, int]


class RootCustodyProof:
    """Unimplemented root-only attestation interface; no permissive default.

    check must raise unless the service manager, inherited FD provenance, exact
    policy, dedicated identities, packaged Python/dependencies, protected key,
    registry/journal/fence, backup/downgrade floor, ancestors, ACL/MAC and mount
    namespace remain independently protected. It must bind these exact objects,
    not trust fields on them. In particular, authenticate creator_peer (PID/UID/GID)
    against root-controlled listener creation/provenance, never root UID alone.
    Called at boot and throughout serving; no cache.
    HTTP code must never supply a provider. Caller subclasses are refused.
    The exact shipped implementation always denies; replacing it requires a
    separately reviewed root-packaged attestor, not application configuration.
    """

    def check(self, *, role, policy, broker=None, listener=None):
        raise Denied()


def protected_path(path, *, uid, gid, mode, kind, identity=None):
    """No-follow dirfd walk; deny extended ACLs and replacement of any ancestor.

    Returns a full identity chain for comparison before/after connect or use.
    Root/mount namespace custody is an additional proof-provider obligation.
    No unsupported-xattr or filesystem fallback is permitted.
    """
    if sys.platform != "linux":
        raise Denied()
    parts = PurePosixPath(path).parts
    if (not parts or parts[0] != "/" or str(PurePosixPath(path)) != path
            or ".." in parts or len(parts) < 3):
        raise Denied()
    descriptors = []
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        descriptors.append(fd)
        chain = []
        for index, part in enumerate(parts):
            if index:
                parent = fd
                if index == len(parts) - 1:
                    node = os.stat(part, dir_fd=parent, follow_symlinks=False)
                    # xattr lookup via held parent; final symlink is rejected below.
                    attrs = os.listxattr(f"/proc/self/fd/{parent}/{part}", follow_symlinks=False)
                else:
                    fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                 | os.O_CLOEXEC, dir_fd=parent)
                    descriptors.append(fd)
                    node = os.fstat(fd)
                    attrs = os.listxattr(fd)
            else:
                node, attrs = os.fstat(fd), os.listxattr(fd)
            if any(a.startswith("system.posix_acl_") for a in attrs):
                raise Denied()
            final = index == len(parts) - 1
            if final:
                if (not kind(node.st_mode) or node.st_uid != uid or node.st_gid != gid
                        or stat.S_IMODE(node.st_mode) != mode or node.st_nlink != 1
                        or (identity is not None and (node.st_dev, node.st_ino) != identity)):
                    raise Denied()
            elif (not stat.S_ISDIR(node.st_mode) or node.st_uid != 0
                  or stat.S_IMODE(node.st_mode) & 0o022):
                raise Denied()
            chain.append((node.st_dev, node.st_ino, node.st_uid, node.st_gid,
                          stat.S_IMODE(node.st_mode)))
        # Rewalk from the namespace root on every invocation. Retained dirfds
        # alone would miss renamed/replaced ancestors on the next invocation.
        return tuple(chain)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def validate_policy(policy):
    if type(policy) is not LaunchPolicy:
        raise Denied()
    peer = policy.creator_peer
    if (type(peer) is not tuple or len(peer) != 3
            or any(type(v) is not int for v in peer)
            or not 0 < peer[0] < 2**31
            or any(not 0 <= v < 2**32 - 1 for v in peer[1:])):
        raise Denied()
    values = (policy.service_uid, policy.service_gid, policy.backend_uid, policy.backend_gid)
    if (any(type(v) is not int or not 0 < v < 2**32 - 1 for v in values)
            or policy.service_uid == policy.backend_uid
            or policy.service_gid == policy.backend_gid
            or type(policy.listener) is not ListenerSnapshot
            or policy.listener.path != VERIFY_PATH or policy.listener.owner_uid != 0
            or policy.listener.group_gid != policy.backend_gid or policy.listener.mode != 0o660):
        raise Denied()


class LinuxVerifyService:
    """Verify-only service adapter, inherited listener only; NOT deployment-ready.

    No socket creation, CLI, environment identity, admin or fixture enablement.
    The trusted launcher must install cancellation/SIGTERM handling via stop().
    Serve retains flock until the last storage worker exits, even after shutdown.
    An uninterruptible filesystem call requires supervisor process termination.
    """

    def __init__(self, broker, listener, policy, *, proof, deadline=0.5, max_clients=8):
        if (sys.platform != "linux" or type(proof) is not RootCustodyProof
                or type(broker) is not Broker or type(listener) is not socket.socket
                or broker._barrier is not directory_sync):
            raise Denied()
        validate_policy(policy)
        self._broker, self._listener, self._policy, self._proof = broker, listener, policy, proof
        self._quarantined, self._used = False, False
        self._lock_fd = None
        self._chain = None
        try:
            self._check()
            import fcntl
            before = protected_path(LOCK_PATH, uid=0, gid=policy.service_gid, mode=0o660,
                kind=stat.S_ISREG, identity=policy.lock_identity)
            self._lock_fd = os.open(LOCK_PATH, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            node = os.fstat(self._lock_fd)
            if ((node.st_dev, node.st_ino) != policy.lock_identity
                    or protected_path(LOCK_PATH, uid=0, gid=policy.service_gid, mode=0o660,
                        kind=stat.S_ISREG, identity=policy.lock_identity) != before):
                raise Denied()
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_chain = before
            with broker._lock:
                broker._checked()
                for parent in {broker._db.parent, broker._journal.parent}:
                    directory_sync(parent)
            self._transport = _VerifyTransport(broker, {"verify": listener},
                {"verify": policy.listener}, backend_uid=policy.backend_uid,
                backend_gid=policy.backend_gid, custody_check=self._check,
                response_check=self._response_check,
                deadline=deadline, max_clients=max_clients)
        except BaseException:
            self._quarantined = True
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
            # Passed descriptor transfers ownership; never unlink its pathname.
            listener.close()
            raise Denied() from None

    def _check(self):
        try:
            if self._quarantined:
                raise Denied()
            p = self._policy
            self._proof.check(role="service", policy=p, broker=self._broker, listener=self._listener)
            if (os.getresuid() != (p.service_uid,) * 3
                    or os.getresgid() != (p.service_gid,) * 3
                    or set(os.getgroups()) - {p.service_gid}
                    or os.get_inheritable(self._listener.fileno())):
                raise Denied()
            _check_listener(self._listener, p.listener)
            chain = protected_path(VERIFY_PATH, uid=0, gid=p.backend_gid, mode=0o660,
                kind=stat.S_ISSOCK, identity=p.listener.path_identity)
            if self._chain is not None and chain != self._chain:
                raise Denied()
            self._chain = chain
            if self._lock_fd is not None:
                node = os.fstat(self._lock_fd)
                if ((node.st_dev, node.st_ino) != p.lock_identity
                        or protected_path(LOCK_PATH, uid=0, gid=p.service_gid, mode=0o660,
                            kind=stat.S_ISREG, identity=p.lock_identity) != self._lock_chain):
                    raise Denied()
        except BaseException:
            self._quarantined = True
            self._broker._poisoned = True
            raise Denied() from None

    def stop(self):
        self._transport.stop()

    def _response_check(self, response):
        if unframe(response).get("status") == "quarantined":
            self._quarantined = True
            self._broker._poisoned = True
            raise Denied()

    def serve(self):
        if self._used:
            raise Denied()
        self._used = True
        try:
            self._check()
            self._transport.serve()
        finally:
            self._quarantined = True
            # Transport may never have entered serve (preflight custody denial).
            # Ownership transferred at construction; never unlink caller paths.
            try:
                self._transport.stop()
                self._listener.close()
                if self._transport._work is not None:
                    self._transport._work.join()
            finally:
                if self._lock_fd is not None:
                    os.close(self._lock_fd)
                    self._lock_fd = None
