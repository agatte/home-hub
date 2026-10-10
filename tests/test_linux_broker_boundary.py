"""Test-only Linux isolation contract. Privilege changes occur ONLY in children."""
from contextlib import closing
import os
import signal
import socket
import stat
import struct
import sys
import time

import pytest

from tests.support.linux_broker_boundary import (
    Boundary, Node, Peer, peer_credentials, private_store, socket_custody, trusted_chain,
)

B = Boundary()
linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux kernel proof required")


@pytest.mark.parametrize("operation", ["bootstrap", "enroll", "revoke", "restore",
    "restore_intent_invalidate", "SQL", "shell", "verify ", "unknown"])
def test_backend_verify_only(operation):
    peer = Peer(12, B.backend_uid, B.backend_uid)
    assert not B.permits(peer, "verify", {"operation": operation})
    assert not B.permits(peer, "admin", {"operation": operation}, fresh_interactive=True)


def test_fail_closed_identity_and_approval():
    backend = Peer(12, B.backend_uid, B.backend_uid)
    assert B.permits(backend, "verify", {"operation": "verify"})
    for peer in (None, {"uid": B.backend_uid}, Peer(0, B.backend_uid, 0),
                 Peer(12, 99999, 0), Peer(12, 0, 0)):
        assert not B.permits(peer, "verify", {"operation": "verify"})
    for field in ("uid", "profile", "source", "localhost", "approved"):
        assert not B.permits(backend, "verify", {"operation": "verify", field: "root"})
    for uid in (0, B.admin_uid):
        admin = Peer(12, uid, uid)
        assert B.permits(admin, "admin", {"operation": "enroll"}, fresh_interactive=True)
        for approval in (False, None, 1, "fresh"):
            assert not B.permits(admin, "admin", {"operation": "enroll"}, fresh_interactive=approval)
        for operation in ("shell", "SQL", "verify", "restore", "unknown"):
            assert not B.permits(admin, "admin", {"operation": operation}, fresh_interactive=True)
        assert not B.permits(admin, "admin", {"operation": "enroll", "profile": "root"}, fresh_interactive=True)
    assert not B.admit(None, "verify", {"operation": "verify"})
    assert not B.permits(backend, "unknown", {"operation": "verify"})
    with pytest.raises(ValueError):
        Boundary(broker_uid=B.backend_uid)


@pytest.mark.parametrize("payload", [None, {}, {"operation": None}, {"operation": []},
                                     {"operation": "VERIFY"}])
def test_missing_or_invalid_operation(payload):
    assert not B.permits(Peer(12, B.backend_uid, B.backend_uid), "verify", payload)


def tree():
    return {"/": Node(0, 0, stat.S_IFDIR | 0o755),
            "/opt": Node(0, 0, stat.S_IFDIR | 0o755),
            "/opt/broker": Node(0, 0, stat.S_IFDIR | 0o755),
            "/opt/broker/python": Node(0, 0, stat.S_IFREG | 0o755)}


@pytest.mark.parametrize("nlink", [0, 2, 3, True, "1", None])
def test_protected_regular_file_rejects_invalid_link_count(nlink):
    metadata = tree()
    metadata["/opt/broker/python"] = Node(0, 0, stat.S_IFREG | 0o755, nlink=nlink)
    assert not trusted_chain("/opt/broker/python", metadata)


def test_directory_link_counts_do_not_reject_trusted_chain():
    metadata = tree()
    for member in ("/", "/opt", "/opt/broker"):
        metadata[member] = Node(0, 0, stat.S_IFDIR | 0o755, nlink=3)
    assert trusted_chain("/opt/broker/python", metadata)


@pytest.mark.parametrize("member", ["/", "/opt", "/opt/broker", "/opt/broker/python"])
@pytest.mark.parametrize("damage", ["backend", "group_write", "world_write", "symlink", "missing"])
def test_code_interpreter_dependency_config_chain(member, damage):
    metadata = tree()
    assert trusted_chain("/opt/broker/python", metadata)
    original = metadata[member]
    if damage == "missing":
        del metadata[member]
    else:
        metadata[member] = Node(B.backend_uid if damage == "backend" else 0, 0,
            stat.S_IFLNK | 0o777 if damage == "symlink" else original.mode |
            (0o020 if damage == "group_write" else 0o002 if damage == "world_write" else 0))
    assert not trusted_chain("/opt/broker/python", metadata)


def test_private_store_and_socket_safeguards():
    metadata = tree()
    path = "/opt/state"
    metadata[path] = Node(B.broker_uid, B.broker_uid, stat.S_IFDIR | 0o700)
    assert private_store(path, metadata, B)
    for node in (Node(B.backend_uid, B.backend_uid, stat.S_IFDIR | 0o700),
                 Node(B.broker_uid, B.backend_uid, stat.S_IFDIR | 0o700),
                 Node(B.broker_uid, B.broker_uid, stat.S_IFDIR | 0o750),
                 Node(B.broker_uid, B.broker_uid, stat.S_IFLNK | 0o700)):
        metadata[path] = node
        assert not private_store(path, metadata, B)
    for path in ("relative", "/opt/../state", "/missing/state"):
        assert not private_store(path, metadata, B)
    admin_parent, admin_socket = Node(0, 0, stat.S_IFDIR | 0o700), Node(0, 0, stat.S_IFSOCK | 0o600)
    verify_parent = Node(0, 0, stat.S_IFDIR | 0o755)
    verify_socket = Node(B.broker_uid, B.backend_uid, stat.S_IFSOCK | 0o660)
    assert socket_custody(admin_parent, admin_socket, B, "admin")
    assert socket_custody(verify_parent, verify_socket, B, "verify")
    assert not socket_custody(verify_parent, admin_socket, B, "admin")
    assert not socket_custody(Node(B.backend_uid, 0, stat.S_IFDIR | 0o755), verify_socket, B, "verify")
    assert not socket_custody(verify_parent, Node(B.broker_uid, B.backend_uid, stat.S_IFSOCK | 0o666), B, "verify")


def child_trial(tmp_path, listener, *, uid=None, private=None, admin=None, close_in_child=(),
                connect_before_drop=False):
    """Bounded fork: relative paths keep all I/O under inherited per-test cwd.

    Child bypasses pytest ancestor traversal by chdir BEFORE dropping privilege;
    it still traverses the dedicated state/admin directories being measured.
    """
    pid = os.fork()
    if pid == 0:
        try:
            listener.close()
            for inherited in close_in_child:
                inherited.close()
            os.chdir(tmp_path)
            if uid is not None and not connect_before_drop:
                os.setgroups([])
                os.setgid(uid)
                os.setuid(uid)
            if private:
                try:
                    with open(private, "rb") as stream:
                        stream.read(1)
                except PermissionError:
                    pass
                else:
                    os._exit(2)
            if admin:
                with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as probe:
                    try:
                        probe.connect(admin)
                    except PermissionError:
                        pass
                    else:
                        os._exit(3)
            with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as client:
                client.settimeout(5)
                client.connect("verify.sock")
                if connect_before_drop:
                    os.setgroups([])
                    os.setgid(uid)
                    os.setuid(uid)
                    client.sendall(f"post_drop={os.getuid()},{os.getgid()},{os.getgroups()}".encode())
                else:
                    client.sendall(b"claimed_uid=0;claimed_profile=root")
                if client.recv(1) != b"x":
                    os._exit(4)
            os._exit(0)
        except BaseException:
            os._exit(5)
    try:
        with closing(listener.accept()[0]) as connection:
            connection.settimeout(5)
            peer = peer_credentials(connection)
            expected = (f"post_drop={uid},{uid},[]".encode() if connect_before_drop
                        else b"claimed_uid=0;claimed_profile=root")
            received = b""
            while len(received) < len(expected):
                chunk = connection.recv(len(expected) - len(received))
                assert chunk, "child closed before completing fixture payload"
                received += chunk
            assert received == expected
            connection.sendall(b"x")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            waited, status = os.waitpid(pid, os.WNOHANG)
            if waited:
                pid_to_check, pid = pid, None
                assert os.waitstatus_to_exitcode(status) == 0
                assert peer.pid == pid_to_check
                return peer
            time.sleep(0.01)
        pytest.fail("child did not finish")
    finally:
        if pid is not None:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)


def listen(path):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.settimeout(5)
        listener.bind(str(path))
        listener.listen(4)
        return listener
    except BaseException:
        listener.close()
        raise


@linux
def test_real_same_uid_peers(tmp_path):
    with closing(listen(tmp_path / "verify.sock")) as listener:
        peers = [child_trial(tmp_path, listener) for _ in range(2)]
    assert peers[0].pid != peers[1].pid
    assert all(p.uid == os.getuid() and p.gid == os.getgid() for p in peers)
    # UID-only policy cannot distinguish these independently forked clients.
    if os.getuid() != 0:
        local = Boundary(backend_uid=os.getuid(), admin_uid=os.getuid() + 1, broker_uid=os.getuid() + 2)
        assert all(local.permits(p, "verify", {"operation": "verify"}) for p in peers)


@linux
def test_missing_or_invalid_kernel_credentials():
    # Failure injection on a real connected socket; NOT measured kernel behavior.
    class DamagedSocket(socket.socket):
        def getsockopt(self, level, option, *args):
            if option == socket.SO_PEERCRED:
                assert level == socket.SOL_SOCKET and args == (struct.calcsize('iII'),)
                return self.damage
            return super().getsockopt(level, option, *args)

    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with closing(right), closing(DamagedSocket(fileno=left.detach())) as connection:
        for damage in (b"", struct.pack('iII', 0, B.backend_uid, 0),
                       struct.pack('iII', -1, B.backend_uid, 0),
                       struct.pack('iII', 12, 0xFFFFFFFF, 0),
                       struct.pack('iII', 12, B.backend_uid, 0xFFFFFFFF)):
            connection.damage = damage
            with pytest.raises(PermissionError, match="missing kernel peer identity"):
                peer_credentials(connection)
            assert not B.admit(connection, "verify", {"operation": "verify"})
        for uid, gid in ((0x80000000, 0x80000000), (0xFFFFFFFE, 0xFFFFFFFE)):
            connection.damage = struct.pack('iII', 12, uid, gid)
            assert peer_credentials(connection) == Peer(12, uid, gid)
            assert not B.admit(connection, "verify", {"operation": "verify"})
            assert not B.admit(connection, "admin", {"operation": "enroll"}, fresh_interactive=True)


@linux
def test_peer_credentials_remain_connect_time_identity_after_child_drop(tmp_path):
    if os.geteuid() != 0:
        pytest.skip("requires root in explicitly disposable Linux container")
    if os.environ.get("HOMEHUB_DISPOSABLE_LINUX_BOUNDARY") != "1":
        pytest.skip("explicit disposable-container opt-in required")
    original_uid, original_gid = os.getuid(), os.getgid()
    with closing(listen(tmp_path / "verify.sock")) as listener:
        peer = child_trial(tmp_path, listener, uid=B.backend_uid, connect_before_drop=True)
    assert peer.uid == original_uid == 0
    assert peer.gid == original_gid
    assert peer.uid != B.backend_uid
    assert not B.permits(peer, "verify", {"operation": "verify"})
    # No admin admission: cached identity cannot establish current-holder authority.


@linux
def test_reject_unsupported_and_unconnected_transports(tmp_path):
    for family, kind in ((socket.AF_INET, socket.SOCK_STREAM), (socket.AF_UNIX, socket.SOCK_DGRAM),
                         (socket.AF_UNIX, socket.SOCK_STREAM)):
        with closing(socket.socket(family, kind)) as connection:
            assert not B.admit(connection, "verify", {"operation": "verify"})
    with closing(listen(tmp_path / "listener.sock")) as listener:
        assert not B.admit(listener, "verify", {"operation": "verify"})


@linux
def test_privileged_multi_uid_isolation(tmp_path):
    if os.geteuid() != 0:
        pytest.skip("requires root in explicitly disposable Linux container")
    if os.environ.get("HOMEHUB_DISPOSABLE_LINUX_BOUNDARY") != "1":
        pytest.skip("explicit disposable-container opt-in required")
    os.chmod(tmp_path, 0o755)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    os.chown(state, B.broker_uid, B.broker_uid)
    for name in ("registry", "journal", "guard"):
        file = state / name
        file.write_bytes(b"synthetic non-secret fixture")
        os.chown(file, B.broker_uid, B.broker_uid)
        os.chmod(file, 0o600)
    admin = tmp_path / "admin"
    admin.mkdir(mode=0o700)
    with closing(listen(admin / "admin.sock")) as admin_listener, closing(listen(tmp_path / "verify.sock")) as listener:
        os.chmod(admin / "admin.sock", 0o600)
        os.chown(tmp_path / "verify.sock", B.broker_uid, B.backend_uid)
        os.chmod(tmp_path / "verify.sock", 0o660)
        for name in ("registry", "journal", "guard"):
            peer = child_trial(tmp_path, listener, uid=B.backend_uid, private="state/" + name,
                               admin="admin/admin.sock", close_in_child=(admin_listener,))
            assert peer.uid == peer.gid == B.backend_uid
            assert B.permits(peer, "verify", {"operation": "verify"})
            assert not B.permits(peer, "admin", {"operation": "enroll"}, fresh_interactive=True)
        # Widen only this disposable verify socket to measure policy rejection of
        # a third UID independently of transport permissions, then restore mode.
        os.chmod(tmp_path / "verify.sock", 0o666)
        try:
            peer = child_trial(tmp_path, listener, uid=41004, close_in_child=(admin_listener,))
            assert peer.uid == peer.gid == 41004
            assert not B.permits(peer, "verify", {"operation": "verify"})
            assert not B.permits(peer, "admin", {"operation": "enroll"}, fresh_interactive=True)
        finally:
            os.chmod(tmp_path / "verify.sock", 0o660)
