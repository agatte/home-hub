"""Synthetic only. Linux transport tests MUST run on an actual Linux kernel."""
import ast
from contextlib import contextmanager
import hashlib
import multiprocessing
import os
from pathlib import Path
import socket
import signal
import struct
import sys
import threading
import time

import pytest

from security.homehub_identity_broker import linux_verify_server as s
from security.homehub_identity_broker import runtime as r
from security.homehub_identity_broker.offline_fixture import offline_fixture_bootstrap

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux SO_PEERCRED/AF_UNIX gate")
TOKEN = "a" * 32 + "." + "B" * 43


def request(**changes):
    return {"version": 1, "method": "verify", "nonce": "f" * 32, "token": TOKEN,
            "operation": "WS /ws:light_command", "lane": "browser",
            "generation": "c" * 32, "revision": 1, **changes}


def test_source_compiles_and_has_no_entrypoint_or_backend_import():
    path = Path(s.__file__)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    compile(tree, str(path), "exec")
    assert not s.PRODUCTION_SUPPORTED
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
            assert all(not name.startswith("backend") for name in names)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"bind", "listen", "unlink", "getuid", "geteuid"}
    assert '__name__ == "__main__"' not in source
    assert "os.environ" not in source.replace("No implicit os.environ read.", "")


@pytest.mark.parametrize("environment", [
    {}, {"LISTEN_PID": "3", "LISTEN_FDS": "1", "LISTEN_FDNAMES": "verify"},
    {"LISTEN_PID": "42", "LISTEN_FDS": "2", "LISTEN_FDNAMES": "verify:verify"},
    {"LISTEN_PID": "42", "LISTEN_FDS": "01", "LISTEN_FDNAMES": "verify"},
    {"LISTEN_PID": "42", "LISTEN_FDS": "1", "LISTEN_FDNAMES": "admin"},
    {"LISTEN_PID": "42", "LISTEN_FDS": "2", "LISTEN_FDNAMES": "verify:issuer"},
])
def test_activation_exact_fail_closed(environment):
    with pytest.raises(r.Denied, match="^Broker unavailable$"):
        s.activation_descriptors(environment, 42)


def test_activation_names_and_order():
    assert s.activation_descriptors({"LISTEN_PID": "42", "LISTEN_FDS": "2",
        "LISTEN_FDNAMES": "admin:verify"}, 42) == {"admin": 3, "verify": 4}


def test_no_production_construction_or_env_authority():
    with pytest.raises(r.Denied):
        s.inherited_fixture_listeners({}, {})
    with pytest.raises(r.Denied):
        s.FixtureVerifyServer(None, {}, {}, backend_uid=123)


@pytest.fixture
def rig(tmp_path):
    if sys.platform != "linux":
        pytest.skip("actual Linux SO_PEERCRED/AF_UNIX gate")
    private, anchor = tmp_path / "private", tmp_path / "anchor"
    private.mkdir(mode=0o700)
    anchor.mkdir(mode=0o700)
    broker = r.Broker(private / "registry", anchor / "journal", b"synthetic-key-only" * 2,
                      clock=lambda: 1000)
    profile = r.PROFILES["owner_browser"]
    state = {"version": 1, "minimum_code": 1, "generation": "c" * 32, "revision": 1,
        "rotations": [], "pending_delivery": [], "credentials": {"a" * 32: {
            "principal_id": "d" * 32, "profile": "owner_browser", "source": profile.source,
            "grants": [list(g) for g in sorted(profile.grants)], "kind": "browser_session",
            "expires_at": 2000, "revoked": False, "salt": "e" * 32,
            "iterations": r.ITERATIONS, "verifier": hashlib.pbkdf2_hmac(
                "sha256", b"B" * 43, bytes.fromhex("e" * 32), r.ITERATIONS).hex()}}}
    offline_fixture_bootstrap(broker, state, trusted_fixture=True)
    originals, snapshots = {}, {}
    try:
        for name in ("verify", "admin"):
            path = tmp_path / ("v" if name == "verify" else "a")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            originals[name] = listener
            listener.bind(str(path))
            os.chmod(path, 0o600)
            listener.listen(16)
            fd, node = os.fstat(listener.fileno()), path.lstat()
            snapshots[name] = s.ListenerSnapshot(str(path), (fd.st_dev, fd.st_ino),
                (node.st_dev, node.st_ino), os.getuid(), os.getgid(), 0o600)
        yield broker, originals, snapshots
    finally:
        for listener in originals.values():
            listener.close()


def inherited(rig, **overrides):
    _, originals, snapshots = rig
    environment = {"LISTEN_PID": str(os.getpid()), "LISTEN_FDS": "2",
                   "LISTEN_FDNAMES": "verify:admin", **overrides}
    return s.inherited_fixture_listeners(environment, snapshots, fixture_only=True,
        duplicate=lambda fd: os.dup(originals[("verify", "admin")[fd - 3]].fileno()))


@contextmanager
def running(rig, **options):
    broker, _, snapshots = rig
    server = s.FixtureVerifyServer(broker, inherited(rig), snapshots,
        backend_uid=options.pop("backend_uid", os.getuid()), fixture_only=True,
        deadline=options.pop("deadline", 1.5), **options)
    errors = []
    def run():
        try:
            server.serve()
        except BaseException as error:
            errors.append(type(error).__name__)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        yield server
    finally:
        server.stop()
        thread.join(1)
        assert not thread.is_alive()
        if server._work:
            server._work.join(3)
            assert not server._work.is_alive()
        assert errors == []


def connect(rig, endpoint="verify"):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(3)
    client.connect(rig[2][endpoint].path)
    return client


def exchange(rig, raw):
    with connect(rig) as client:
        client.sendall(raw)
        client.shutdown(socket.SHUT_WR)
        result = bytearray()
        try:
            while chunk := client.recv(2053):
                result.extend(chunk)
        except ConnectionResetError:
            pass
        return bytes(result)


@LINUX
def test_correct_fixture_nonce_peer_and_token(rig):
    with running(rig, backend_gid=os.getgid()):
        with connect(rig) as peer:
            pid, uid, gid = struct.unpack("iII", peer.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("iII")))
            assert (pid, uid, gid) == (os.getpid(), os.getuid(), os.getgid())
        response = exchange(rig, r.frame(request()))
        value = r.unframe(response)
        assert value["status"] == "verified"
        assert value["nonce"] == "f" * 32
        assert TOKEN.encode() not in response
        assert r.unframe(exchange(rig, r.frame(request(token="a" * 32 + "." + "X" * 43))))["status"] == "denied"


@LINUX
@pytest.mark.parametrize("options", [{"backend_uid": "wrong"}, {"backend_gid": "wrong"}])
def test_kernel_identity_denied_before_body(rig, options):
    options = {k: (os.getuid() if k == "backend_uid" else os.getgid()) + 1 for k in options}
    calls = []
    rig[0]._hook = lambda point: calls.append(point)
    with running(rig, **options):
        with connect(rig) as client:
            assert client.recv(1) == b""  # No request body has been sent.
    assert calls == []


@LINUX
@pytest.mark.parametrize("raw", [b"", b"\0", struct.pack("!I", 0),
    struct.pack("!I", 2049), struct.pack("!I", 2) + b"{",
    struct.pack("!I", 13) + b'{"x":1,"x":2}', r.frame(request()) + b"x",
    r.frame(request(nonce="bad")), r.frame(request(method="revoke")),
    r.frame(request(uid=0)), r.frame(request(profile="owner_browser"))])
def test_malformed_truncated_oversize_duplicate_and_admin_commands(rig, raw):
    with running(rig):
        assert exchange(rig, raw) == b""


@LINUX
@pytest.mark.parametrize("mode", ["revoked", "expired"])
def test_revoked_expired_state(rig, mode):
    if mode == "revoked":
        rig[0]._revoke("a" * 32)
    else:
        rig[0]._clock = lambda: 2000
    with running(rig):
        response = exchange(rig, r.frame(request(revision=2 if mode == "revoked" else 1)))
        assert r.unframe(response)["status"] == "denied"


@LINUX
def test_congestion_admin_denial_delayed_client_and_restart(rig):
    with running(rig, max_clients=1, deadline=0.15):
        with connect(rig) as slow:
            slow.sendall(b"\0")
            time.sleep(0.04)
            with connect(rig) as excess, connect(rig, "admin") as admin:
                assert excess.recv(1) == b""
                assert admin.recv(1) == b""
            assert slow.recv(1) == b""
    assert all(Path(snapshot.path).exists() for snapshot in rig[2].values())
    with running(rig):
        assert r.unframe(exchange(rig, r.frame(request())))["status"] == "verified"


@LINUX
def test_stop_closes_pending_without_unlink(rig):
    with running(rig) as server:
        with connect(rig) as client:
            client.sendall(b"\0")
            time.sleep(0.04)
            server.stop()
            try:
                assert client.recv(1) == b""
            except ConnectionResetError:
                pass
    assert all(Path(snapshot.path).exists() for snapshot in rig[2].values())


@LINUX
def test_worker_deadline_retains_capacity_discards_late_result(rig):
    entered, release = threading.Event(), threading.Event()
    def hook(point):
        if point == "verify_locked":
            entered.set()
            release.wait(2)
    rig[0]._hook = hook
    with running(rig, deadline=0.15) as server:
        try:
            with connect(rig) as client:
                client.sendall(r.frame(request()))
                client.shutdown(socket.SHUT_WR)
                assert entered.wait(1)
                assert client.recv(1) == b""
                assert exchange(rig, r.frame(request())) == b""
                with connect(rig, "admin") as admin:
                    assert admin.recv(1) == b""
                server.stop()
        finally:
            release.set()


@LINUX
def test_eof_required_and_delayed_surplus_rejected(rig):
    with running(rig, deadline=0.2):
        with connect(rig) as client:
            client.sendall(r.frame(request()))
            client.settimeout(0.05)
            with pytest.raises(socket.timeout):
                client.recv(1)
            client.sendall(b"extra")
            client.settimeout(1)
            try:
                assert client.recv(1) == b""
            except ConnectionResetError:
                pass


@LINUX
def test_stop_while_worker_active_blocks_second_server(rig):
    entered, release = threading.Event(), threading.Event()
    def hook(point):
        if point == "verify_locked":
            entered.set()
            release.wait(2)
    rig[0]._hook = hook
    with running(rig) as first:
        try:
            with connect(rig) as client:
                client.sendall(r.frame(request()))
                client.shutdown(socket.SHUT_WR)
                assert entered.wait(1)
                first.stop()
                assert client.recv(1) == b""
                # Wait for selector shutdown, while the broker worker remains busy.
                until = time.monotonic() + 1
                while first._serving.locked() and time.monotonic() < until:
                    time.sleep(0.01)
                assert not first._serving.locked()
                second = s.FixtureVerifyServer(rig[0], inherited(rig), rig[2],
                    backend_uid=os.getuid(), fixture_only=True)
                with pytest.raises(r.Denied):
                    second.serve()
                assert all(listener.fileno() == -1 for listener in second._listeners.values())
        finally:
            release.set()


def _signal_fixture_child(rig, ready):
    """Disposable test launcher only; never packaged as a production entrypoint."""
    server = s.FixtureVerifyServer(rig[0], inherited(rig), rig[2],
        backend_uid=os.getuid(), fixture_only=True)
    signal.signal(signal.SIGTERM, lambda *_: server.stop())
    ready.send(True)
    ready.close()
    server.serve()


@LINUX
def test_real_sigterm_fixture_launcher_and_restart(rig):
    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_signal_fixture_child, args=(rig, child))
    process.start()
    child.close()
    try:
        assert parent.poll(2) and parent.recv() is True
        with connect(rig) as pending:
            pending.sendall(b"\0")
            time.sleep(0.04)
            os.kill(process.pid, signal.SIGTERM)
            try:
                assert pending.recv(1) == b""
            except ConnectionResetError:
                pass
        process.join(2)
        assert process.exitcode == 0
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
            process.join(2)
        assert not process.is_alive()
        process.close()
    with running(rig):
        assert r.unframe(exchange(rig, r.frame(request())))["status"] == "verified"


@LINUX
@pytest.mark.parametrize("mismatch", ["pid", "name", "inode", "path", "duplicate", "stream"])
def test_listener_mismatch(rig, mismatch):
    from dataclasses import replace
    broker, originals, snapshots = rig
    if mismatch in {"pid", "name"}:
        with pytest.raises(r.Denied):
            inherited(rig, **({"LISTEN_PID": "0"} if mismatch == "pid" else {"LISTEN_FDNAMES": "verify:issuer"}))
        return
    altered = dict(snapshots)
    if mismatch == "inode":
        altered["verify"] = replace(altered["verify"], descriptor_identity=(0, 0))
    elif mismatch == "path":
        altered["verify"] = replace(altered["verify"], path=altered["admin"].path)
    elif mismatch == "duplicate":
        altered["admin"] = altered["verify"]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as wrong:
        mapping = dict(originals)
        if mismatch == "duplicate":
            mapping["admin"] = mapping["verify"]
        elif mismatch == "stream":
            mapping["verify"] = wrong
        with pytest.raises(r.Denied):
            s.inherited_fixture_listeners({"LISTEN_PID": str(os.getpid()),
                "LISTEN_FDS": "2", "LISTEN_FDNAMES": "verify:admin"}, altered,
                fixture_only=True, duplicate=lambda fd: os.dup(mapping[("verify", "admin")[fd - 3]].fileno()))
    assert all(listener.fileno() >= 0 for listener in originals.values())
    assert broker is rig[0]
