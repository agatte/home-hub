"""DO NOT INSTALL: Linux VERIFY transport experiment, with no production launcher.

Fixture intent and injected snapshots are NOT root provisioner attestations.
Production construction is deliberately refused. No environment value, UID,
Python object or successful snapshot establishes continuous OS custody.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import selectors
import socket
import stat
import struct
import sys
import threading
import time

from .runtime import Broker, Denied, MAX_FRAME, unframe

PRODUCTION_SUPPORTED = False
_OWNER_LOCK = threading.Lock()


@dataclass(frozen=True)
class ListenerSnapshot:
    """Launcher-injected fixture expectations; never derive from request/env."""

    path: str
    descriptor_identity: tuple[int, int]
    path_identity: tuple[int, int]
    owner_uid: int
    group_gid: int
    mode: int


def activation_descriptors(environment, pid):
    """Parse only the systemd ABI, not authority. No implicit os.environ read."""
    names = environment.get("LISTEN_FDNAMES", "").split(":")
    if (environment.get("LISTEN_PID") != str(pid)
            or names not in (["verify"], ["verify", "admin"], ["admin", "verify"])
            or environment.get("LISTEN_FDS") != str(len(names))):
        raise Denied()
    return dict(zip(names, range(3, 3 + len(names))))


def _identity(node):
    return node.st_dev, node.st_ino


def _check_listener(listener, expected):
    try:
        _listener_snapshot_matches(listener, expected)
        return
    except Exception:
        pass
    raise Denied()


def _listener_snapshot_matches(listener, expected):
    path = Path(expected.path)
    node = os.fstat(listener.fileno())
    path_node = path.lstat()
    if (not path.is_absolute() or ".." in path.parts
            or listener.family != socket.AF_UNIX
            or listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
            or listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 1
            or listener.getsockname() != expected.path
            or not stat.S_ISSOCK(node.st_mode) or not stat.S_ISSOCK(path_node.st_mode)
            or _identity(node) != expected.descriptor_identity
            or _identity(path_node) != expected.path_identity
            or node.st_uid != expected.owner_uid
            or path_node.st_uid != expected.owner_uid
            or path_node.st_gid != expected.group_gid
            or stat.S_IMODE(path_node.st_mode) != expected.mode):
        raise Denied()


def inherited_fixture_listeners(environment, expected, *, fixture_only=False,
                               duplicate=os.dup):
    """Duplicate injected inherited FDs; never bind/unlink or claim OS authority.

    `duplicate` maps systemd's fd numbers to disposable test descriptors. A real
    trusted launcher/root provisioner and race-safe path custody are absent.
    Originals stay owned by caller. Duplicates are owned by returned transport.
    """
    if sys.platform != "linux" or fixture_only is not True:
        raise Denied()
    listeners = {}
    try:
        descriptors = activation_descriptors(environment, os.getpid())
        if set(descriptors) != set(expected):
            raise Denied()
        identities = set()
        for name, fd in descriptors.items():
            copied = duplicate(fd)
            try:
                listener = socket.socket(fileno=copied)
            except BaseException:
                os.close(copied)
                raise
            listeners[name] = listener
            os.set_inheritable(copied, False)
            _check_listener(listener, expected[name])
            identity = _identity(os.fstat(copied))
            if identity in identities:
                raise Denied()
            identities.add(identity)
            listener.setblocking(False)
        return listeners
    except Exception:
        for listener in listeners.values():
            listener.close()
    raise Denied()


class _VerifyTransport:
    """Guarded injection-only harness; not a production daemon or admin API.

    One daemon worker, zero queued broker operations. A timed-out operation keeps
    the worker occupied until it actually completes; its result is discarded.
    Stop closes all clients immediately, without waiting for storage/PBKDF2.
    Python cannot interrupt a blocked filesystem call: restart on the same Broker
    must wait for worker completion. No second worker is created by serve().
    """

    def __init__(self, broker, listeners, snapshots, *, backend_uid, backend_gid=None,
                 max_clients=8, deadline=0.5, custody_check=lambda: None,
                 response_check=lambda response: None):
        if (sys.platform != "linux"
                or type(broker) is not Broker
                or type(backend_uid) is not int or not 0 <= backend_uid < 2**32 - 1
                or (backend_gid is not None and (type(backend_gid) is not int
                    or not 0 <= backend_gid < 2**32 - 1))
                or type(max_clients) is not int or not 1 <= max_clients <= 32
                or type(deadline) not in (int, float) or not 0 < deadline <= 2
                or set(listeners) not in ({"verify"}, {"verify", "admin"})
                or set(listeners) != set(snapshots)):
            raise Denied()
        identities = set()
        for name, listener in listeners.items():
            _check_listener(listener, snapshots[name])
            identity = _identity(os.fstat(listener.fileno()))
            if identity in identities:
                raise Denied()
            identities.add(identity)
        self._broker = broker
        self._listeners, self._snapshots = dict(listeners), dict(snapshots)
        self._uid, self._gid = backend_uid, backend_gid
        self._limit, self._deadline = max_clients, deadline
        self._stop = threading.Event()
        self._serving = threading.Lock()
        self._work = None
        self._used = False
        self._custody_check = custody_check
        self._response_check = response_check

    def stop(self):
        """Cancellation seam; a future launcher must bind SIGTERM to this."""
        self._stop.set()

    def _peer_allowed(self, connection):
        pid, uid, gid = struct.unpack("iII", connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("iII")))
        return pid > 0 and uid == self._uid and (self._gid is None or gid == self._gid)

    def serve(self):
        try:
            self._serve()
            return
        except Exception:
            pass
        raise Denied()

    def _serve(self):
        if not self._serving.acquire(blocking=False):
            raise Denied()
        with _OWNER_LOCK:
            previous = getattr(self._broker, "_fixture_transport_owner", None)
            if (self._used or (previous is not None and (
                    previous._serving.locked()
                    or (previous._work is not None and previous._work.is_alive())))):
                self._serving.release()
                for listener in self._listeners.values():
                    listener.close()
                raise Denied()
            self._broker._fixture_transport_owner = self
        self._used = True
        pending = {}
        result = queue.Queue(maxsize=1)
        busy = None

        def compute(raw, marker):
            response = None
            try:
                self._custody_check()
                response = self._broker.process(raw)
                unframe(response)  # Fixed Broker only; no arbitrary response provider.
                self._response_check(response)
                self._custody_check()
            except BaseException:
                response = None
            result.put((marker, response))

        try:
            with selectors.DefaultSelector() as selector:
                def close(connection):
                    try:
                        selector.unregister(connection)
                    except KeyError:
                        pass
                    pending.pop(connection)
                    connection.close()

                try:
                    for name, listener in self._listeners.items():
                        listener.setblocking(False)
                        selector.register(listener, selectors.EVENT_READ, name)
                    while not self._stop.is_set():
                        self._custody_check()
                        now = time.monotonic()
                        for connection, state in list(pending.items()):
                            if now >= state["end"]:
                                close(connection)
                        if busy is not None and not result.empty():
                            marker, response = result.get_nowait()
                            busy = None
                            for connection, state in list(pending.items()):
                                if state is marker:
                                    if response is None or time.monotonic() >= state["end"]:
                                        close(connection)
                                    else:
                                        state["output"] = response
                                        selector.register(connection, selectors.EVENT_WRITE, state)
                        events = selector.select(0.01)
                        # One accept per endpoint per tick; admin denies without a
                        # body or active slot, so verify congestion cannot starve it.
                        events.sort(key=lambda event: 0 if event[0].data == "admin" else 1)
                        for key, _ in events:
                            if self._stop.is_set():
                                break
                            if isinstance(key.data, str):
                                try:
                                    connection, _ = key.fileobj.accept()
                                except BlockingIOError:
                                    continue
                                connection.setblocking(False)
                                try:
                                    self._custody_check()
                                    allowed = self._peer_allowed(connection)
                                    _check_listener(key.fileobj, self._snapshots[key.data])
                                except Exception:
                                    allowed = False
                                if key.data == "admin" or not allowed or len(pending) >= self._limit:
                                    connection.close()  # No recv, including on admin.
                                    continue
                                state = {"raw": bytearray(), "end": time.monotonic() + self._deadline,
                                         "output": None}
                                pending[connection] = state
                                selector.register(connection, selectors.EVENT_READ, state)
                                continue
                            connection, state = key.fileobj, key.data
                            if connection not in pending:
                                continue
                            if time.monotonic() >= state["end"]:
                                close(connection)
                                continue
                            try:
                                if state["output"] is not None:
                                    sent = connection.send(state["output"])
                                    if sent == 0:
                                        close(connection)
                                    else:
                                        state["output"] = state["output"][sent:]
                                        if not state["output"]:
                                            close(connection)
                                    continue
                                chunk = connection.recv(MAX_FRAME + 5 - len(state["raw"]))
                                state["raw"].extend(chunk)
                                raw = state["raw"]
                                if len(raw) >= 4:
                                    size = struct.unpack("!I", raw[:4])[0]
                                    if not 1 <= size <= MAX_FRAME or len(raw) > size + 4:
                                        close(connection)
                                        continue
                                # Require write-half EOF to reject surplus/delayed
                                # second frames, under the original whole deadline.
                                if not chunk:
                                    unframe(bytes(raw))
                                    self._custody_check()
                                    if busy is not None:
                                        close(connection)  # Zero broker work queue.
                                        continue
                                    selector.unregister(connection)
                                    # Retain deadline ownership while worker runs.
                                    busy = state
                                    self._work = threading.Thread(target=compute,
                                        args=(bytes(raw), state), daemon=True)
                                    self._work.start()
                            except (OSError, ValueError, Denied):
                                close(connection)
                finally:
                    for connection in list(pending):
                        close(connection)
        finally:
            self._stop.set()
            for listener in self._listeners.values():
                listener.close()  # Never unlink externally owned pathnames.
            self._serving.release()


class FixtureVerifyServer(_VerifyTransport):
    """Disposable harness only; never a production launch mechanism."""

    def __init__(self, broker, listeners, snapshots, *, backend_uid, backend_gid=None,
                 fixture_only=False, max_clients=8, deadline=0.5):
        if fixture_only is not True:
            raise Denied()
        super().__init__(broker, listeners, snapshots, backend_uid=backend_uid,
            backend_gid=backend_gid, max_clients=max_clients, deadline=deadline)
