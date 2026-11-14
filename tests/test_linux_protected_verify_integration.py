"""Exact transport integration; synthetic custody is NOT privileged acceptance.

No sudo/accounts/systemd. The injected proof and temporary path checks model
root custody ONLY. Actual AF_UNIX, peer credentials, framing, flock and Broker
state machinery execute on Linux. Windows runs source/default-denial checks.
"""
import ast
import asyncio
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import multiprocessing
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import threading
import time

import pytest

from backend.services import linux_identity_broker_io as io
from backend.services.identity_broker_verify_client import (
    ProtocolDenied, VerifyClient, encode_frame,
)
from security.homehub_identity_broker import linux_protected_verify as s
from security.homehub_identity_broker import runtime as r
from security.homehub_identity_broker.linux_verify_server import ListenerSnapshot
from security.homehub_identity_broker.offline_fixture import offline_fixture_bootstrap

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="requires actual Linux AF_UNIX/flock/SO_PEERCRED")
TOKEN = "a" * 32 + "." + "B" * 43
GEN = "c" * 32
OP = "GET /api/automation/status"
DENY_CHECK = s.RootCustodyProof.check


def request(**changes):
    return encode_frame({"version": 1, "method": "verify", "nonce": "f" * 32,
        "generation": GEN, "revision": 1, "token": TOKEN, "operation": OP,
        "lane": "notifier", **changes})


def test_unimplemented_proof_denies_every_caller_claim():
    for role in ("service", "backend", "root", True):
        with pytest.raises(r.Denied):
            s.RootCustodyProof().check(role=role, policy={"root": True, "backend_uid": 0})


@pytest.mark.parametrize("proof", [None, True, {}, object()])
def test_no_caller_flag_or_snapshot_is_proof(proof):
    with pytest.raises(ProtocolDenied):
        io.LinuxProtectedVerifyIO(None, proof=proof)
    with pytest.raises(r.Denied):
        s.LinuxVerifyService(None, None, None, proof=proof)


def test_source_has_no_activation_or_admin_escape():
    for module in (s, io):
        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        compile(tree, module.__file__, "exec")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"bind", "listen", "unlink", "getenv", "system", "_mutate"}
        assert "os.environ" not in source
        assert '__name__ == "__main__"' not in source
    assert "FixtureVerifyServer" not in Path(s.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize("changes", [
    {"service_uid": 0}, {"backend_uid": 100}, {"service_gid": True},
    {"backend_gid": -1}, {"backend_uid": 2**32 - 1},
    {"listener": ListenerSnapshot("/tmp/verify", (1, 1), (1, 2), 0, 200, 0o660)},
])
def test_policy_has_no_arbitrary_identity_or_endpoint_fallback(changes):
    policy = s.LaunchPolicy(100, 100, 200, 200,
        ListenerSnapshot(s.VERIFY_PATH, (1, 1), (1, 2), 0, 200, 0o660), (1, 3), (1, 0, 0))
    with pytest.raises(r.Denied):
        s.validate_policy(replace(policy, **changes))


def test_root_policy_values_are_necessary_but_not_proof():
    policy = s.LaunchPolicy(100, 100, 200, 200,
        ListenerSnapshot(s.VERIFY_PATH, (1, 1), (1, 2), 0, 200, 0o660), (1, 3), (1, 0, 0))
    s.validate_policy(policy)
    with pytest.raises(r.Denied):
        s.validate_policy(replace(policy, backend_gid=100))
    with pytest.raises(r.Denied):
        s.RootCustodyProof().check(role="service", policy=policy)


@pytest.mark.parametrize("path", ["relative", "/run/../run/x", "/run//x", "/run/x/"])
def test_path_spelling_rejected(path):
    with pytest.raises(r.Denied):
        s.protected_path(path, uid=0, gid=1, mode=0o660, kind=stat.S_ISSOCK)


def test_caller_subclass_cannot_turn_intent_into_root_proof():
    class Forged(s.RootCustodyProof):
        def check(self, **kwargs):
            return
    with pytest.raises(ProtocolDenied):
        io.LinuxProtectedVerifyIO(None, proof=Forged())
    with pytest.raises(r.Denied):
        s.LinuxVerifyService(None, None, None, proof=Forged())


@pytest.fixture
def rig(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("requires actual Linux AF_UNIX/flock/SO_PEERCRED")
    path, lock = str(tmp_path / "v"), str(tmp_path / "l")
    monkeypatch.setattr(s, "VERIFY_PATH", path)
    monkeypatch.setattr(s, "LOCK_PATH", lock)
    monkeypatch.setattr(io, "VERIFY_PATH", path)
    # Nonroot disposable process cannot become two dedicated principals or own
    # root-controlled ancestors. Model ONLY that external gate explicitly.
    monkeypatch.setattr(s, "validate_policy", lambda policy: None)
    monkeypatch.setattr(io, "validate_policy", lambda policy: None)
    monkeypatch.setattr(s.os, "getgroups", lambda: [os.getgid()])

    def temporary_custody(path, *, uid, gid, mode, kind, identity=None):
        node = os.lstat(path)
        assert kind(node.st_mode) and not stat.S_ISLNK(node.st_mode)
        assert stat.S_IMODE(node.st_mode) == mode
        found = (node.st_dev, node.st_ino)
        if identity is not None and found != identity:
            raise r.Denied()
        return (found,)

    monkeypatch.setattr(s, "protected_path", temporary_custody)
    monkeypatch.setattr(io, "protected_path", temporary_custody)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    os.chmod(path, 0o660)
    listener.listen(16)
    node, descriptor = os.lstat(path), os.fstat(listener.fileno())
    lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o660)
    os.fchmod(lock_fd, 0o660)
    lock_node = os.fstat(lock_fd)
    os.close(lock_fd)
    snapshot = ListenerSnapshot(path, (descriptor.st_dev, descriptor.st_ino),
        (node.st_dev, node.st_ino), os.getuid(), os.getgid(), 0o660)
    policy = s.LaunchPolicy(os.getuid(), os.getgid(), os.getuid(), os.getgid(),
        snapshot, (lock_node.st_dev, lock_node.st_ino),
        (os.getpid(), os.getuid(), os.getgid()))
    private, anchor = tmp_path / "private", tmp_path / "anchor"
    private.mkdir()
    anchor.mkdir()
    broker = r.Broker(private / "registry", anchor / "journal", b"synthetic-only-key" * 2,
                      clock=lambda: 1000)
    p = r.PROFILES["desktop_notifier"]
    credential = {"principal_id": "d" * 32, "profile": "desktop_notifier",
        "source": p.source, "grants": [list(g) for g in sorted(p.grants)],
        "kind": "native_bearer", "expires_at": 2000, "revoked": False,
        "salt": "e" * 32, "iterations": r.ITERATIONS,
        "verifier": hashlib.pbkdf2_hmac("sha256", b"B" * 43,
            bytes.fromhex("e" * 32), r.ITERATIONS).hex()}
    state = {"version": 1, "minimum_code": 1, "generation": GEN, "revision": 1,
        "credentials": {"a" * 32: credential}, "rotations": [], "pending_delivery": []}
    offline_fixture_bootstrap(broker, state, trusted_fixture=True)
    proof = s.RootCustodyProof()
    proof.valid = True

    def synthetic_check(self, **kwargs):
        if not self.valid:
            raise r.Denied()

    monkeypatch.setattr(s.RootCustodyProof, "check", synthetic_check)
    try:
        yield broker, listener, policy, proof
    finally:
        listener.close()


@contextmanager
def running(rig, **options):
    broker, listener, policy, proof = rig
    service = s.LinuxVerifyService(broker, listener, policy, proof=proof,
                                  deadline=options.pop("deadline", 1.5), **options)
    errors = []

    def run():
        try:
            service.serve()
        except r.Denied:
            errors.append("quarantined")

    thread = threading.Thread(target=run)
    thread.start()
    try:
        yield service, errors
    finally:
        service.stop()
        thread.join(5)
        assert not thread.is_alive()


def connector(rig, **options):
    return io.LinuxProtectedVerifyIO(rig[2], proof=rig[3], timeout=1.8, **options)


def test_native_token_through_exact_pair_and_verify_client(rig, caplog):
    with running(rig):
        client = VerifyClient(connector(rig), generation=lambda: GEN, revision=lambda: 1,
                              timeout=2, clock=lambda: 1000)
        result = asyncio.run(client.authorize(TOKEN, OP, lane="notifier", stage="active"))
        assert result.profile == "desktop_notifier"
        assert TOKEN not in caplog.text + repr(client) + repr(connector(rig))


def test_revocation_rotation_and_journal_quarantine(rig):
    broker = rig[0]
    with running(rig) as (service, _):
        adapter = connector(rig)
        assert r.unframe(asyncio.run(adapter.exchange_verify(request())))["status"] == "verified"
        record = dict(broker._checked()["credentials"]["a" * 32])
        record["verifier"] = hashlib.pbkdf2_hmac("sha256", b"C" * 43,
            bytes.fromhex("e" * 32), r.ITERATIONS).hex()
        broker._rotate("a" * 32, "b" * 32, record)
        assert r.unframe(asyncio.run(adapter.exchange_verify(request(revision=2))))["status"] == "denied"
        replacement = "b" * 32 + "." + "C" * 43
        assert r.unframe(asyncio.run(adapter.exchange_verify(request(token=replacement, revision=2))))["status"] == "verified"
        broker._revoke("b" * 32)
        assert r.unframe(asyncio.run(adapter.exchange_verify(request(token=replacement, revision=3))))["status"] == "denied"
        broker._journal.write_bytes(b"synthetic corruption")
        with pytest.raises(ProtocolDenied):
            asyncio.run(adapter.exchange_verify(request(revision=3)))
        assert service._quarantined


@pytest.mark.parametrize("raw", [b"", b"\x00", struct.pack("!I", 2049),
    struct.pack("!I", 2) + b"{", request() + request(), request(method="revoke"),
    struct.pack("!I", 2) + b"[]", struct.pack("!I", 13) + b'{"a":1,"a":2}'])
def test_service_malformed_partial_surplus_no_admin(rig, raw):
    with running(rig):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(rig[2].listener.path)
            client.sendall(raw)
            client.shutdown(socket.SHUT_WR)
            assert client.recv(4096) == b""


def test_wrong_backend_peer_denied_before_body(rig, monkeypatch):
    policy = replace(rig[2], backend_uid=os.getuid() + 1)
    rig = (rig[0], rig[1], policy, rig[3])
    calls = []
    monkeypatch.setattr(rig[0], "process", lambda raw: calls.append(raw))
    with running(rig):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(policy.listener.path)
            assert client.recv(1) == b""
    assert not calls


def test_wrong_server_peer_denied_before_token(rig, monkeypatch):
    calls = []
    monkeypatch.setattr(rig[0], "process", lambda raw: calls.append(raw))
    with running(rig):
        adapter = io.LinuxProtectedVerifyIO(replace(rig[2], creator_peer=(os.getpid(), os.getuid() + 1, os.getgid())),
                                             proof=rig[3])
        with pytest.raises(ProtocolDenied):
            asyncio.run(adapter.exchange_verify(request()))
    assert not calls


def test_listener_fd_mismatch_fails_closed(rig):
    bad = replace(rig[2], listener=replace(rig[2].listener, descriptor_identity=(0, 0)))
    with pytest.raises(r.Denied):
        s.LinuxVerifyService(rig[0], rig[1], bad, proof=rig[3])


def test_default_proof_cannot_be_replaced_with_caller_policy(rig, monkeypatch):
    monkeypatch.setattr(s.RootCustodyProof, "check", DENY_CHECK)
    with pytest.raises(r.Denied):
        s.LinuxVerifyService(*rig[:3], proof=s.RootCustodyProof())


def _try_lock(path, output):
    import fcntl
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            output.send("locked")
        else:
            output.send("free")
    finally:
        os.close(fd)
        output.close()


def test_cross_process_singleton_and_release(rig):
    context = multiprocessing.get_context("spawn")
    with running(rig):
        parent, child = context.Pipe()
        process = context.Process(target=_try_lock, args=(s.LOCK_PATH, child))
        process.start()
        assert parent.poll(5) and parent.recv() == "locked"
        process.join(5)
        assert process.exitcode == 0
        parent.close()
        child.close()
    parent, child = context.Pipe()
    process = context.Process(target=_try_lock, args=(s.LOCK_PATH, child))
    process.start()
    assert parent.poll(5) and parent.recv() == "free"
    process.join(5)
    assert process.exitcode == 0
    parent.close()
    child.close()


def test_shutdown_retains_lock_while_worker_runs(rig, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = rig[0].process

    def blocked(raw):
        entered.set()
        assert release.wait(4)
        return original(raw)

    monkeypatch.setattr(rig[0], "process", blocked)
    with running(rig, deadline=0.08) as (service, _):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(1)
        client.connect(rig[2].listener.path)
        client.sendall(request())
        client.shutdown(socket.SHUT_WR)
        assert entered.wait(1)
        try:
            assert client.recv(1) == b""
            service.stop()
            time.sleep(0.05)
            assert service._lock_fd is not None
            import fcntl
            fd = os.open(s.LOCK_PATH, os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
        finally:
            release.set()
            client.close()


def test_custody_loss_quarantines_and_connector_sends_nothing(rig):
    with running(rig) as (service, _):
        adapter = connector(rig)
        rig[3].valid = False
        with pytest.raises(ProtocolDenied):
            asyncio.run(adapter.exchange_verify(request()))
        time.sleep(0.05)
        assert service._quarantined


@pytest.mark.parametrize("response", [
    b"", b"\x00", struct.pack("!I", 2049), struct.pack("!I", 10) + b"{}",
    r.frame({"ok": True}) + b"x", struct.pack("!I", 13) + b'{"a":1,"a":2}',
])
def test_connector_rejects_malformed_partial_surplus_response(rig, response):
    adapter = connector(rig)
    errors = []

    def server():
        connection, _ = rig[1].accept()
        with connection:
            connection.settimeout(2)
            try:
                while connection.recv(2048):
                    pass
                connection.sendall(response)
            except OSError:
                errors.append("closed")

    thread = threading.Thread(target=server)
    thread.start()
    try:
        with pytest.raises(ProtocolDenied) as caught:
            asyncio.run(adapter.exchange_verify(request()))
        assert caught.value.__context__ is None
        assert TOKEN not in str(caught.value)
    finally:
        thread.join(3)
        assert not thread.is_alive()


def test_connector_replacement_before_body_denied(rig, monkeypatch, tmp_path):
    adapter = connector(rig)
    original = adapter._check
    calls = 0
    replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def replace_before_body():
        nonlocal calls
        calls += 1
        if calls == 2:  # _exchange: before connect, then after SO_PEERCRED.
            os.rename(rig[2].listener.path, tmp_path / "old")
            replacement.bind(rig[2].listener.path)
            os.chmod(rig[2].listener.path, 0o660)
            replacement.listen(1)
        return original()

    monkeypatch.setattr(adapter, "_check", replace_before_body)
    try:
        with pytest.raises(ProtocolDenied):
            asyncio.run(adapter.exchange_verify(request()))
        accepted, _ = rig[1].accept()
        with accepted:
            accepted.settimeout(1)
            assert accepted.recv(1) == b""  # No token reached the old peer either.
    finally:
        replacement.close()


def test_connector_eof_timeout_capacity_and_cancellation(rig):
    adapter = io.LinuxProtectedVerifyIO(rig[2], proof=rig[3], timeout=0.08, capacity=1)
    accepted = threading.Event()
    release = threading.Event()

    def server():
        connection, _ = rig[1].accept()
        with connection:
            connection.settimeout(2)
            while connection.recv(2048):
                pass
            connection.sendall(r.frame({"synthetic": True}))
            accepted.set()
            release.wait(2)  # Withhold EOF even after a complete frame.

    thread = threading.Thread(target=server)
    thread.start()

    async def trial():
        first = asyncio.create_task(adapter.exchange_verify(request()))
        while not accepted.is_set():
            await asyncio.sleep(0.001)
        with pytest.raises(ProtocolDenied):
            await adapter.exchange_verify(request())
        with pytest.raises(ProtocolDenied):
            await first
        assert adapter._active == 0
        second = asyncio.create_task(adapter.exchange_verify(request()))
        await asyncio.sleep(0.01)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert adapter._active == 0

    try:
        asyncio.run(asyncio.wait_for(trial(), 3))
    finally:
        release.set()
        thread.join(3)
        assert not thread.is_alive()


def test_server_saturation_deadline_and_single_instance(rig):
    with running(rig, max_clients=1, deadline=0.1) as (service, _):
        first = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        second = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            first.settimeout(1)
            second.settimeout(1)
            first.connect(rig[2].listener.path)
            first.sendall(b"\x00")
            time.sleep(0.03)
            second.connect(rig[2].listener.path)
            assert second.recv(1) == b""
            assert first.recv(1) == b""
            duplicate = rig[1].dup()
            with pytest.raises(r.Denied):
                s.LinuxVerifyService(rig[0], duplicate, rig[2], proof=rig[3])
            assert not service._quarantined
        finally:
            first.close()
            second.close()


@LINUX
def test_real_path_checker_rejects_unprotected_tmp_and_symlink(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"synthetic")
    path.chmod(0o660)
    with pytest.raises(r.Denied):
        s.protected_path(str(path), uid=0, gid=os.getgid(), mode=0o660, kind=stat.S_ISREG)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(r.Denied):
        s.protected_path(str(link), uid=0, gid=os.getgid(), mode=0o660, kind=stat.S_ISREG)


@pytest.mark.parametrize("actual,allowed", [
    ((1, 0, 0), True),  # PID1/root-created listener, nonroot acceptor policy.
    ((99, 100, 100), False),  # Later service acceptor is not the creator.
    ((2, 0, 0), False),  # Root alone is insufficient.
    ((1, 0, 1), False),
])
def test_synthetic_creator_peer_checked_before_token(monkeypatch, actual, allowed):
    from types import SimpleNamespace
    adapter = object.__new__(io.LinuxProtectedVerifyIO)
    adapter._policy = SimpleNamespace(creator_peer=(1, 0, 0),
                                     service_uid=100, service_gid=100)
    checks, sent = [], []
    adapter._check = lambda: checks.append("custody")
    response = r.frame({"synthetic": True})
    chunks = [response[:4], response[4:], b""]

    class Connection:
        closed = False
        def setblocking(self, value):
            pass
        def getsockopt(self, *args):
            return struct.pack("iII", *actual)
        def shutdown(self, how):
            pass
        def close(self):
            self.closed = True

    connection = Connection()

    async def trial():
        loop = asyncio.get_running_loop()
        async def connect(*args):
            pass
        async def send(sock, raw):
            sent.append(raw)
        async def receive(sock, count):
            return chunks.pop(0)
        monkeypatch.setattr(loop, "sock_connect", connect)
        monkeypatch.setattr(loop, "sock_sendall", send)
        monkeypatch.setattr(loop, "sock_recv", receive)
        monkeypatch.setattr(io, "socket", SimpleNamespace(
            socket=lambda *args: connection, AF_UNIX=1, SOCK_STREAM=1,
            SOL_SOCKET=1, SO_PEERCRED=17, SHUT_WR=1))
        if allowed:
            assert await adapter._exchange(request()) == response
        else:
            with pytest.raises(ProtocolDenied):
                await adapter._exchange(request())
        # Restore socket factory before asyncio closes its own resources.
        monkeypatch.undo()

    asyncio.run(trial())
    assert sent == ([request()] if allowed else [])
    assert len(checks) == (3 if allowed else 1)
    assert connection.closed


def test_synthetic_preflight_denial_closes_owned_listener_and_lock(monkeypatch):
    from types import SimpleNamespace
    service = object.__new__(s.LinuxVerifyService)
    events = []
    service._used, service._quarantined, service._lock_fd = False, False, 123
    service._listener = SimpleNamespace(close=lambda: events.append("close"))
    service._transport = SimpleNamespace(_work=None,
        stop=lambda: events.append("stop"),
        serve=lambda: pytest.fail("transport must not run after custody denial"))
    def denied():
        raise r.Denied()
    service._check = denied
    monkeypatch.setattr(s.os, "close", lambda fd: events.append(("release", fd)))
    with pytest.raises(r.Denied):
        service.serve()
    assert events == ["stop", "close", ("release", 123)]
    assert service._quarantined and service._lock_fd is None


def test_preflight_custody_loss_closes_listener_releases_flock_preserves_path(rig):
    import fcntl
    service = s.LinuxVerifyService(*rig[:3], proof=rig[3])
    rig[3].valid = False
    with pytest.raises(r.Denied):
        service.serve()
    assert rig[1].fileno() == -1
    assert service._lock_fd is None and service._quarantined and rig[0]._poisoned
    assert os.path.exists(rig[2].listener.path)
    fd = os.open(s.LOCK_PATH, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)
