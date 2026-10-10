"""OFFLINE / NOT PRODUCTION / DO NOT INSTALL. No credentials or storage.

Trusted configuration is injected by a local test launcher, never by clients.
This implements the sd_listen_fds environment ABI, not a systemd manager.
"""
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import struct
import sys
import time

MAX_PAYLOAD = 256
MAX_ACTIVE = 8
READ_TIMEOUT = 0.3
WRITE_TIMEOUT = 0.1
DENY = {"status": "DENY", "credentials_verified": False}
ADMIN_DENY = {"status": "UNIMPLEMENTED/DENY", "credentials_verified": False}


def activation_environment(env, pid):
    names = env.get("LISTEN_FDNAMES", "").split(":")
    if (env.get("LISTEN_PID") != str(pid) or env.get("LISTEN_FDS") != "2"
            or len(names) != 2 or set(names) != {"verify", "admin"}):
        raise ValueError("invalid activation")
    return dict(zip(names, (3, 4)))


def parse_request(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result
    if not raw or len(raw) > MAX_PAYLOAD:
        raise ValueError("invalid size")
    request = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    if (type(request) is not dict or set(request) != {"operation"}
            or type(request["operation"]) is not str):
        raise ValueError("invalid request")
    return request


def custody(path, endpoint, root, owner, group, *, provisioner_preflight=False):
    """Snapshot checks; no claim of ACL/MAC or race-free installer validation."""
    path = Path(path)
    root = Path(root)
    if (not root.is_absolute() or not path.is_absolute() or ".." in root.parts
            or ".." in path.parts or path != root / ("homehub-identity-prototype-" + endpoint) / (endpoint + ".sock")):
        raise ValueError("invalid socket location")
    # Injected test root is an explicit trust anchor. Never traverse beyond it.
    # A disposable launcher may enter the anchor before dropping UID; relative
    # snapshots then need no access through pytest's private ancestors. The
    # admin parent still enforces its unchanged 0700 traversal boundary.
    def snapshot(target):
        if root == Path.cwd():
            return Path(target.relative_to(root)).lstat()
        return target.lstat()

    for parent in (root, path.parent):
        node = snapshot(parent)
        expected_mode = (0o700 if endpoint == "admin" else 0o755) if parent == path.parent else None
        if (not stat.S_ISDIR(node.st_mode) or node.st_uid != owner
                or node.st_mode & 0o022
                or (endpoint == "admin" and parent == path.parent and node.st_gid != owner)
                or (expected_mode and stat.S_IMODE(node.st_mode) != expected_mode)):
            raise ValueError("invalid parent custody")
    try:
        node = snapshot(path)
    except PermissionError:
        # Root-only traversal is expected for the passed admin FD. Exact node
        # ownership/mode remains a trusted installer gate, not measured here.
        if (endpoint == "admin" and owner == 0 and os.geteuid() != 0
                and not provisioner_preflight):
            return "TRUSTED_OS_ATTESTATION_REQUIRED"
        raise
    mode = 0o600 if endpoint == "admin" else 0o660
    gid = owner if endpoint == "admin" else group
    if (not stat.S_ISSOCK(node.st_mode) or node.st_uid != owner
            or node.st_gid != gid or stat.S_IMODE(node.st_mode) != mode):
        raise ValueError("invalid socket custody")
    return "NODE_SNAPSHOT_CHECKED"


def inherited_listeners(env, root, owner, group):
    descriptors = activation_environment(env, os.getpid())
    listeners = []
    try:
        identities = set()
        for endpoint in ("verify", "admin"):
            fd = descriptors[endpoint]
            listener = socket.socket(fileno=fd)
            listeners.append(listener)
            os.set_inheritable(fd, False)
            fd_node = os.fstat(fd)
            identity = (fd_node.st_dev, fd_node.st_ino)
            if (identity in identities or not stat.S_ISSOCK(fd_node.st_mode)
                    or fd_node.st_uid != owner or listener.family != socket.AF_UNIX
                    or listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
                    or listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 1):
                raise ValueError("invalid listener")
            identities.add(identity)
            path = str(Path(root) / ("homehub-identity-prototype-" + endpoint) / (endpoint + ".sock"))
            if listener.getsockname() != path:
                raise ValueError("wrong listener path/name")
            custody(path, endpoint, root, owner, group)
            listener.setblocking(False)
        return listeners
    except BaseException:
        for listener in listeners:
            listener.close()
        raise
    finally:
        for key in ("LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES"):
            env.pop(key, None)


def serve(listeners, backend_uid, lifetime, active):
    """Bounded nonblocking transport; admin denial never waits for a body."""
    pending = {}
    end = time.monotonic() + lifetime
    with selectors.DefaultSelector() as selector:
        for listener, endpoint in zip(listeners, ("verify", "admin")):
            selector.register(listener, selectors.EVENT_READ, endpoint)

        def close(connection):
            selector.unregister(connection)
            pending.pop(connection)
            connection.close()

        def respond(connection, result):
            state = pending[connection]
            state["output"] = json.dumps(result, separators=(",", ":")).encode()
            state["deadline"] = time.monotonic() + WRITE_TIMEOUT
            selector.modify(connection, selectors.EVENT_WRITE, state)

        print("READY", flush=True)
        try:
            while active() and time.monotonic() < end:
                now = time.monotonic()
                for connection, state in list(pending.items()):
                    if now >= state["deadline"]:
                        if state["output"] is None:
                            respond(connection, DENY)
                        else:
                            close(connection)
                events = selector.select(0.01)
                # One accept per endpoint per cycle, admin first; no draining
                # a verify backlog or blocking on any client body/send.
                events.sort(key=lambda event: 0 if event[0].data == "admin" else 1)
                for key, _ in events:
                    if not active() or time.monotonic() >= end:
                        break
                    if isinstance(key.data, str):
                        try:
                            connection, _ = key.fileobj.accept()
                        except BlockingIOError:
                            continue
                        connection.setblocking(False)
                        endpoint = key.data
                        # Reserve one bounded slot for admin. Excess verify
                        # sockets close immediately, with no allocation/read.
                        limit = MAX_ACTIVE if endpoint == "admin" else MAX_ACTIVE - 1
                        if len(pending) >= limit:
                            connection.close()
                            continue
                        state = {"raw": bytearray(), "output": None,
                                 "deadline": time.monotonic() + READ_TIMEOUT}
                        pending[connection] = state
                        selector.register(connection, selectors.EVENT_READ, state)
                        try:
                            pid, uid, gid = struct.unpack("iII", connection.getsockopt(
                                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("iII")))
                            if pid <= 0 or uid == 0xFFFFFFFF or gid == 0xFFFFFFFF:
                                respond(connection, DENY)
                            elif endpoint == "admin":
                                respond(connection, ADMIN_DENY)
                            elif uid != backend_uid:
                                respond(connection, DENY)  # Before receiving body.
                        except (OSError, struct.error):
                            respond(connection, DENY)
                        continue
                    connection, state = key.fileobj, key.data
                    try:
                        if state["output"] is not None:
                            sent = connection.send(state["output"])
                            state["output"] = state["output"][sent:]
                            if not state["output"]:
                                close(connection)
                        else:
                            chunk = connection.recv(MAX_PAYLOAD + 1 - len(state["raw"]))
                            state["raw"].extend(chunk)
                            if len(state["raw"]) > MAX_PAYLOAD:
                                respond(connection, DENY)
                            elif not chunk:
                                result = DENY
                                try:
                                    if parse_request(bytes(state["raw"])) == {"operation": "verify"}:
                                        result = {"status": "TRANSPORT_ALLOWED_TRUE",
                                                  "credentials_verified": False,
                                                  "credential_status": "CREDENTIALS_VERIFIED_FALSE"}
                                except (ValueError, UnicodeError, RecursionError):
                                    pass
                                if not active():
                                    result = DENY
                                respond(connection, result)
                    except BlockingIOError:
                        pass
                    except OSError:
                        close(connection)
        finally:
            for connection in list(pending):
                close(connection)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trusted-root", required=True)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--backend-uid", type=int)
    identity.add_argument("--backend-user")
    parser.add_argument("--custody-uid", required=True, type=int)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--backend-gid", type=int)
    group.add_argument("--backend-group")
    parser.add_argument("--lifetime", type=float, default=5)
    args = parser.parse_args()
    if args.backend_group:
        import grp
        try:
            args.backend_gid = grp.getgrnam(args.backend_group).gr_gid
        except KeyError:
            return 2
    if args.backend_user:
        import pwd
        try:
            account = pwd.getpwnam(args.backend_user)
        except KeyError:
            return 2
        args.backend_uid = account.pw_uid
        if account.pw_gid != args.backend_gid:
            return 2
    if (sys.platform != "linux" or not 0 <= args.backend_uid < 0xFFFFFFFF
            or not 0 <= args.custody_uid < 0xFFFFFFFF
            or not 0 <= args.backend_gid < 0xFFFFFFFF
            or not 0 < args.lifetime <= 10):
        return 2
    listeners = []
    running = True
    def stop(signum, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        listeners = inherited_listeners(os.environ, args.trusted_root,
                                        args.custody_uid, args.backend_gid)
        serve(listeners, args.backend_uid, args.lifetime, lambda: running)
        return 0
    except (OSError, ValueError):
        return 2  # Never log paths, request contents or exception details.
    finally:
        for listener in listeners:
            listener.close()


if __name__ == "__main__":
    raise SystemExit(main())
