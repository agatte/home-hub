"""Offline ABI subprocess/kernel proof; units are static illustrations only."""
from contextlib import contextmanager
import configparser
import json
import os
from pathlib import Path
import select
import socket
import stat
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from tests.support.linux_broker_socket_prototype import activation_environment, parse_request, custody

HERE = Path(__file__).parent
BROKER = HERE / "support/linux_broker_socket_prototype.py"
UNITS = HERE / "fixtures/linux_identity_broker_systemd"
linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux kernel proof required")


@pytest.mark.parametrize("raw", [b"", b"x", b"[]", b"null", b"{}", b'{"operation":1}',
    b'{"operation":"verify","source":"root"}', b'{"operation":"verify","profile":"owner"}',
    b'{"operation":"verify","operation":"verify"}', b'{"operation":"verify"}{}', b"x" * 257])
def test_parser_denies(raw):
    with pytest.raises((ValueError, UnicodeError)):
        parse_request(raw)


@pytest.mark.parametrize("field,value", [("LISTEN_PID", "0"), ("LISTEN_FDS", "1"),
    ("LISTEN_FDS", "3"), ("LISTEN_FDNAMES", "verify:verify"), ("LISTEN_FDNAMES", "admin:admin"),
    ("LISTEN_FDNAMES", "verify:unknown"), ("LISTEN_FDNAMES", "verify:admin:verify"),
    ("LISTEN_FDNAMES", None), ("LISTEN_FDNAMES", "verify"),
    ("LISTEN_PID", "012"), ("LISTEN_FDS", None)])
def test_activation_parser(field, value):
    env = {"LISTEN_PID": "12", "LISTEN_FDS": "2", "LISTEN_FDNAMES": "verify:admin"}
    assert activation_environment(env, 12) == {"verify": 3, "admin": 4}
    if value is None:
        del env[field]
    else:
        env[field] = value
    with pytest.raises(ValueError):
        activation_environment(env, 12)


@pytest.mark.parametrize("names,expected", [("verify:admin", {"verify": 3, "admin": 4}),
    ("admin:verify", {"admin": 3, "verify": 4})])
def test_activation_permutations(names, expected):
    assert activation_environment({"LISTEN_PID": "12", "LISTEN_FDS": "2",
                                   "LISTEN_FDNAMES": names}, 12) == expected


@pytest.mark.parametrize("damage", ["inaccessible", "mode", "owner", "parent"])
def test_synthetic_admin_attestation(tmp_path, monkeypatch, damage):
    path = tmp_path / "homehub-identity-prototype-admin/admin.sock"

    def snapshot(target):
        if target == path:
            if damage == "inaccessible":
                raise PermissionError("fixture")
            return SimpleNamespace(st_mode=stat.S_IFSOCK | (0o666 if damage == "mode" else 0o600),
                                   st_uid=1 if damage == "owner" else 0, st_gid=0)
        mode = 0o700 if target == path.parent else 0o755
        if damage == "parent" and target == path.parent:
            mode = 0o755
        return SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=0, st_gid=0)

    monkeypatch.setattr(Path, "lstat", snapshot)
    monkeypatch.setattr(os, "geteuid", lambda: 41003, raising=False)
    if damage == "inaccessible":
        assert custody(path, "admin", tmp_path, 0, 41001) == "TRUSTED_OS_ATTESTATION_REQUIRED"
    with pytest.raises(PermissionError if damage == "inaccessible" else ValueError):
        custody(path, "admin", tmp_path, 0, 41001, provisioner_preflight=True)


def unit(name):
    path = UNITS / name
    assert "DO NOT INSTALL" in path.read_text()
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read(path)
    assert not parser.has_section("Install")
    return parser


def test_static_units():
    service = unit("homehub-identity-prototype.service")
    s = service["Service"]
    for key, value in {"User": "homehub-identity", "Group": "homehub-identity",
        "ProtectSystem": "strict", "ProtectHome": "true", "NoNewPrivileges": "yes",
        "RestrictAddressFamilies": "AF_UNIX",
        "RuntimeDirectoryMode": "0700", "KillMode": "control-group"}.items():
        assert s[key] == value
    assert s["ExecStart"].startswith("/opt/homehub-identity-prototype/bin/python -I -B ")
    assert "StateDirectory" not in s and "StateDirectoryMode" not in s
    assert "--backend-group homehub-backend" in s["ExecStart"]
    assert "ConditionPathExists" in service["Unit"]
    # ConfigParser checks illustrative text only, never systemd grammar.
    parents = []
    for endpoint, mode, directory, group in (("verify", "0660", "0755", "homehub-backend"),
                                             ("admin", "0600", "0700", "root")):
        name = "homehub-identity-" + endpoint + ".socket"
        u = unit(name)["Socket"]
        assert u["Service"] == "homehub-identity-prototype.service"
        assert u["FileDescriptorName"] == endpoint
        assert u["SocketMode"] == mode and u["DirectoryMode"] == directory
        assert u["SocketUser"] == "root" and u["SocketGroup"] == group
        assert u["Accept"] == "no"
        assert name in service["Unit"]["Requires"].split()
        parents.append(str(Path(u["ListenStream"]).parent))
    assert parents[0] != parents[1]


# Launch a fresh interpreter, then dup/exec there: no preexec_fn or os.fork in
# threaded pytest. pass_fds whitelists only listeners; exec closes old aliases.
LAUNCH = '''import os,sys,fcntl
fds=[int(x) for x in sys.argv[1].split(',')]
# Reserve aliases above sd_listen_fds slots 3 and 4. pytest may leave
# arbitrary gaps: os.dup() aliases can collide with dup2() targets.
copies=[fcntl.fcntl(fd,fcntl.F_DUPFD,10) for fd in fds]
for fd in set(fds): os.close(fd)
for target,fd in enumerate(copies,3): os.dup2(fd,target,inheritable=True)
for fd in copies:
 if fd not in (3,4): os.close(fd)
os.environ['LISTEN_PID']=str(os.getpid())
if os.environ.pop('BAD_PID','') == '1': os.environ['LISTEN_PID']='0'
drop=os.environ.pop('DROP_UID','')
if drop:
 os.chdir(sys.argv[sys.argv.index('--trusted-root')+1])
 os.setgroups([]); os.setgid(int(drop)); os.setuid(int(drop))
os.execv(sys.executable,[sys.executable,'-I','-B']+sys.argv[2:])
'''


@contextmanager
def launch(tmp_path, *, uid=None, damage=None, reordered=False, backend_gid=None, drop_uid=None):
    listeners = []
    process = None
    try:
        for endpoint in ("verify", "admin"):
            parent = tmp_path / ("homehub-identity-prototype-" + endpoint)
            parent.mkdir(mode=0o700 if endpoint == "admin" else 0o755, exist_ok=True)
            path = parent / ("rogue.sock" if damage == "roguepath" and endpoint == "admin"
                             else endpoint + ".sock")
            if path.exists():
                path.unlink()  # Only this fixture's stale socket on restart.
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listeners.append(listener)
            listener.bind(str(path))
            listener.listen(32)
            if endpoint == "verify" and backend_gid is not None:
                os.chown(path, os.getuid(), backend_gid)
            os.chmod(path, 0o600 if endpoint == "admin" else 0o660)
        fds = [s.fileno() for s in listeners]
        env = {"LISTEN_FDS": "2", "LISTEN_FDNAMES": "verify:admin"}
        if drop_uid is not None:
            env["DROP_UID"] = str(drop_uid)
        if reordered:
            fds.reverse()
            env["LISTEN_FDNAMES"] = "admin:verify"
        if damage == "order":
            fds.reverse()
        elif damage == "names":
            env["LISTEN_FDNAMES"] = "admin:verify"
        elif damage == "missing":
            env["LISTEN_FDS"] = "1"
        elif damage == "missingfd":
            fds = fds[:1]
        elif damage == "extra":
            env["LISTEN_FDS"] = "3"
        elif damage == "pid":
            env["BAD_PID"] = "1"
        elif damage == "nonsocket":
            fds[1] = os.open(os.devnull, os.O_RDONLY)
        elif damage == "rogue":
            env["LISTEN_FDNAMES"] = "verify:rogue"
        elif damage == "mode":
            os.chmod(tmp_path / "homehub-identity-prototype-verify/verify.sock", 0o666)
        elif damage == "symlink":
            parent = tmp_path / "homehub-identity-prototype-verify"
            moved = tmp_path / "moved"
            parent.rename(moved)
            parent.symlink_to(moved, target_is_directory=True)
        elif damage == "duplicate":
            fds[1] = fds[0]
        elif damage == "notlistening":
            listeners[1].close()
            listeners[1] = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            fds[1] = listeners[1].fileno()
        try:
            process = subprocess.Popen([sys.executable, "-I", "-B", "-c", LAUNCH,
                ",".join(map(str, fds)), str(BROKER), "--trusted-root", str(tmp_path),
                "--backend-uid", str(os.getuid() if uid is None else uid),
                "--custody-uid", str(os.getuid()), "--backend-gid", str(os.getgid() if backend_gid is None else backend_gid),
                "--lifetime", "3"], pass_fds=tuple(set(fds)), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        finally:
            if damage == "nonsocket":
                os.close(fds[1])
        for listener in listeners:
            listener.close()
        if damage is None:
            ready, _, _ = select.select([process.stdout], [], [], 2)
            assert ready and process.stdout.readline() == b"READY\n"
        yield process
    finally:
        for listener in listeners:
            listener.close()
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=2)


def request(tmp_path, endpoint, raw):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(tmp_path / ("homehub-identity-prototype-" + endpoint) / (endpoint + ".sock")))
        try:
            client.sendall(raw)
            client.shutdown(socket.SHUT_WR)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Early kernel UID/admin denial may close before body write.
        result = b""
        while True:
            chunk = client.recv(1024)
            if not chunk:
                return json.loads(result)
            result += chunk
            try:
                return json.loads(result)
            except ValueError:
                pass


@linux
@pytest.mark.parametrize("reordered", [False, True])
def test_kernel_e2e_restart(tmp_path, reordered):
    for _ in range(2):
        with launch(tmp_path, reordered=reordered) as process:
            result = request(tmp_path, "verify", b'{"operation":"verify"}')
            assert result["status"] == "TRANSPORT_ALLOWED_TRUE"
            assert result["credentials_verified"] is False
            assert result["credential_status"] == "CREDENTIALS_VERIFIED_FALSE"
            for operation in ("enroll", "revoke", "restore", "shell", "SQL", "verify"):
                result = request(tmp_path, "admin", json.dumps({"operation": operation}).encode())
                assert result["status"] == "UNIMPLEMENTED/DENY"
                assert result["credentials_verified"] is False
            for raw in (b'{}', b'{"operation":"shell"}', b'{"operation":"verify","uid":0}',
                        b'{"operation":"verify","source":"root"}',
                        b'{"operation":"verify","profile":"owner"}', b"x" * 257):
                assert request(tmp_path, "verify", raw)["status"] == "DENY"
            process.terminate()
            assert process.wait(timeout=2) == 0


@linux
def test_wrong_kernel_uid(tmp_path):
    with launch(tmp_path, uid=os.getuid() + 1):
        assert request(tmp_path, "verify", b'{"operation":"verify"}')["status"] == "DENY"


@linux
@pytest.mark.parametrize("damage", ["order", "names", "missing", "extra", "pid", "nonsocket",
                                         "rogue", "roguepath", "mode", "duplicate", "notlistening",
                                         "missingfd", "symlink"])
def test_startup_fail_closed(tmp_path, damage):
    with launch(tmp_path, damage=damage) as process:
        assert process.wait(timeout=2) != 0
        assert process.stdout.read() == b""


@linux
def test_stalled_connection_termination(tmp_path):
    with launch(tmp_path) as process:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(str(tmp_path / "homehub-identity-prototype-verify/verify.sock"))
            client.sendall(b'{')
            assert json.loads(client.recv(1024))["status"] == "DENY"
            assert client.recv(1) == b""
        process.terminate()
        assert process.wait(timeout=2) == 0


@linux
def test_disposable_root_group_and_admin_fd(tmp_path):
    if os.geteuid() != 0 or os.environ.get("HOMEHUB_DISPOSABLE_LINUX_BOUNDARY") != "1":
        pytest.skip("requires explicitly disposable root Linux environment")
    backend = 41001
    # Only pytest's unique disposable root: never chmod its ancestors.
    os.chmod(tmp_path, 0o755)
    with launch(tmp_path, uid=backend, backend_gid=backend, drop_uid=41003) as process:
        assert process.poll() is None
        # Full broker starts after provisioned group/mode and launcher UID drop.
        code = '''import os,socket,json,sys
os.chdir(sys.argv[1]); os.setgroups([]); os.setgid(41001); os.setuid(41001)
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
 s.settimeout(2)
 try: s.connect('homehub-identity-prototype-admin/admin.sock')
 except PermissionError: pass
 else: raise SystemExit(3)
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
 s.settimeout(2); s.connect('homehub-identity-prototype-verify/verify.sock')
 s.sendall(b'{"operation":"verify"}'); s.shutdown(socket.SHUT_WR)
 r=json.loads(s.recv(1024))
 assert r['status']=='TRANSPORT_ALLOWED_TRUE' and r['credentials_verified'] is False
'''
        subprocess.run([sys.executable, "-I", "-B", "-c", code, str(tmp_path)],
                       check=True, timeout=3, env={})
        result = request(tmp_path, "admin", b'{"operation":"enroll"}')
        assert result == {"status": "UNIMPLEMENTED/DENY", "credentials_verified": False}
        process.terminate()
        assert process.wait(timeout=1) == 0


@linux
def test_admin_provisioner_preflight(tmp_path):
    # Accessible synthetic fixture is sufficient for an OS provisioner snapshot;
    # ACL attestation and continuous custody are external gates, not this check.
    with launch(tmp_path):
        path = tmp_path / "homehub-identity-prototype-admin/admin.sock"
        assert custody(path, "admin", tmp_path, os.getuid(), os.getgid(),
                       provisioner_preflight=True) == "NODE_SNAPSHOT_CHECKED"
        os.chmod(path, 0o666)
        with pytest.raises(ValueError):
            custody(path, "admin", tmp_path, os.getuid(), os.getgid(),
                    provisioner_preflight=True)
        os.chmod(path, 0o600)
        path.parent.chmod(0o755)
        with pytest.raises(ValueError):
            custody(path, "admin", tmp_path, os.getuid(), os.getgid(),
                    provisioner_preflight=True)


@linux
def test_wrong_uid_denied_before_body(tmp_path):
    with launch(tmp_path, uid=os.getuid() + 1):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.2)
            client.connect(str(tmp_path / "homehub-identity-prototype-verify/verify.sock"))
            assert json.loads(client.recv(1024))["status"] == "DENY"


@linux
def test_saturation_admin_and_termination(tmp_path):
    with launch(tmp_path) as process:
        stalled = []
        try:
            baseline = len(list(Path(f"/proc/{process.pid}/fd").iterdir()))
            for _ in range(12):
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                stalled.append(client)
                client.settimeout(1)
                client.connect(str(tmp_path / "homehub-identity-prototype-verify/verify.sock"))
            start = time.monotonic()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as admin:
                admin.settimeout(0.25)
                admin.connect(str(tmp_path / "homehub-identity-prototype-admin/admin.sock"))
                # No body, so even admin stalls cannot monopolize service.
                assert json.loads(admin.recv(1024)) == {
                    "status": "UNIMPLEMENTED/DENY", "credentials_verified": False}
            assert time.monotonic() - start < 0.25
            time.sleep(0.5)
            assert len(list(Path(f"/proc/{process.pid}/fd").iterdir())) == baseline
            # Repeat saturation and terminate while requests are still pending.
            for client in stalled:
                client.close()
            stalled.clear()
            for _ in range(12):
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                stalled.append(client)
                client.settimeout(1)
                client.connect(str(tmp_path / "homehub-identity-prototype-verify/verify.sock"))
            start = time.monotonic()
            process.terminate()
            assert process.wait(timeout=0.5) == 0
            assert time.monotonic() - start < 0.5
        finally:
            for client in stalled:
                client.close()
