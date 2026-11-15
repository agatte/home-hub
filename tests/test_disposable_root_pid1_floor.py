"""TEST-ONLY, DO-NOT-INSTALL: opt-in disposable Linux root experiments.

Never import from backend. No production authority, attestation or trusted runtime
closure is established. The root test runner is assumed trusted for this isolated
experiment. Only fixed test-created artifacts can be selected; no launcher CLI.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

import pytest


SURFACES = (
    "boot", "service-restart", "deploy-forward", "rollback",
    "failed-deploy-recovery", "return-home", "direct-user-restart",
    "linger-alternate-user-service", "restored-checkout", "manual-process",
)
OPT_IN = pytest.mark.skipif(
    os.environ.get("HOMEHUB_DISPOSABLE_ROOT_PID1_TESTS") != "1"
    or sys.platform != "linux" or not hasattr(os, "geteuid") or os.geteuid() != 0,
    reason="opt-in disposable Linux root only: HOMEHUB_DISPOSABLE_ROOT_PID1_TESTS=1",
)

# Root executes only this fixed test guard, never backend or candidate Python.
# Root path and selection are substituted by the test, not accepted from a CLI.
# Pinned fresh floor is a TEST oracle, not a durable anti-rollback trust source.
GUARD = r'''
import hashlib, json, os, stat, subprocess
from pathlib import Path
root = Path(ROOT_LITERAL)
selection = SELECTION_LITERAL
assert selection in ("approved", "old")
def directory(path, mode):
    info = path.lstat()
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == info.st_gid == 0
    assert stat.S_IMODE(info.st_mode) == mode
def stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_gid, info.st_nlink, info.st_ctime_ns)
def pin(parent, name, mode, is_dir):
    flags = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
    if is_dir:
        flags |= os.O_DIRECTORY
    fd = os.open(name, flags, dir_fd=parent)
    info = os.fstat(fd)
    predicate = stat.S_ISDIR if is_dir else stat.S_ISREG
    assert predicate(info.st_mode)
    assert info.st_uid == info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode
    assert is_dir or info.st_nlink == 1
    evidence = stamp(info)
    assert stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)) == evidence
    return fd, evidence
def recheck(parent, name, fd, evidence):
    assert stamp(os.fstat(fd)) == evidence
    assert stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)) == evidence
def read(path, mode):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        assert info.st_uid == info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode
        assert info.st_size <= 1024 * 1024
        data = b''
        while True:
            part = os.read(fd, 65536)
            if not part:
                return data
            data += part
            assert len(data) <= 1024 * 1024
    finally:
        os.close(fd)
def uint(value):
    return type(value) is int and 0 <= value < 2**64
try:
    # The fixed root-owned sticky /tmp prevents nonroot renaming this root-owned
    # child. Hold namespace-local directory and file identities through launch.
    assert root.parent == Path('/tmp')
    directory(Path('/'), 0o755)
    directory(Path('/tmp'), 0o1777)
    directory(root, 0o755)
    directory(root / 'policy', 0o700)
    directory(root / 'artifacts', 0o755)
    anchor = os.open('/', os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    tmp, tmp_meta = pin(anchor, 'tmp', 0o1777, True)
    work, work_meta = pin(tmp, root.name, 0o755, True)
    policy, policy_meta = pin(work, 'policy', 0o700, True)
    artifacts, artifacts_meta = pin(work, 'artifacts', 0o755, True)
    floor_fd, floor_meta = pin(policy, 'floor', 0o400, False)
    approval_fd, approval_meta = pin(policy, 'approval', 0o400, False)
    candidate_fd, candidate_meta = pin(policy, selection, 0o400, False)
    exe_fd, exe_meta = pin(artifacts, selection, 0o555, False)
    floor = json.loads(read(root / 'policy/floor', 0o400))
    approval = json.loads(read(root / 'policy/approval', 0o400))
    candidate = json.loads(read(root / ('policy/' + selection), 0o400))
    assert set(floor) == {'minimum_epoch', 'generation'}
    assert all(uint(v) for v in floor.values())
    assert floor == {'minimum_epoch': 7, 'generation': 2}
    for record in (approval, candidate):
        assert set(record) == {'epoch', 'generation', 'sha256'}
        assert uint(record['epoch']) and uint(record['generation'])
        digest = record['sha256']
        assert type(digest) is str and len(digest) == 64
        assert all(c in '0123456789abcdef' for c in digest)
    assert candidate == approval
    assert candidate['epoch'] >= floor['minimum_epoch']
    assert candidate['generation'] == floor['generation']
    artifact = root / ('artifacts/' + selection)
    assert hashlib.sha256(read(artifact, 0o555)).hexdigest() == approval['sha256']
    # Root-held directory and leaf bindings are rechecked before name-based
    # execution; reexec/mount alias/ABA and malicious root remain outside scope.
    for parent, name, fd, evidence in (
        (anchor, 'tmp', tmp, tmp_meta),
        (tmp, root.name, work, work_meta),
        (work, 'policy', policy, policy_meta),
        (work, 'artifacts', artifacts, artifacts_meta),
        (policy, 'floor', floor_fd, floor_meta),
        (policy, 'approval', approval_fd, approval_meta),
        (policy, selection, candidate_fd, candidate_meta),
        (artifacts, selection, exe_fd, exe_meta),
    ):
        recheck(parent, name, fd, evidence)
    assert selection == 'approved'
except (OSError, ValueError, AssertionError, TypeError, KeyError):
    print('DENIED', flush=True)
    raise SystemExit(23)
def drop():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
result = subprocess.run([str(artifact), '-u'], preexec_fn=drop,
                        env={'LC_ALL': 'C'}, cwd='/', close_fds=True,
                        capture_output=True, timeout=3)
assert result.returncode == 0 and result.stdout == b'65534\n', result
print('EXECUTED uid=65534', flush=True)
'''

NONROOT_WRITES = r'''
import os, sys
assert os.getuid() == os.getgid() == 65534 and os.getgroups() == []
for path in sys.argv[1:]:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_TRUNC)
    except PermissionError:
        continue
    else:
        os.close(fd)
        raise AssertionError('nonroot write succeeded')
print('permission denied for floor and artifact')
'''

# No /proc remount, systemctl or systemd. This is a real kernel PID namespace,
# with only UID 0 mapped; no supplementary-identity/system-manager claim follows.
PID1 = r'''
import errno, json, os, socket, subprocess, sys
assert os.getpid() == 1 and os.geteuid() == 0
legacy = """
import errno, socket, sys
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
    for option in sys.argv[3:]:
        candidate.setsockopt(socket.SOL_SOCKET, getattr(socket, option), 1)
    try:
        candidate.bind((sys.argv[1], int(sys.argv[2])))
    except OSError as error:
        assert error.errno == errno.EADDRINUSE, error
    else:
        raise AssertionError('legacy bind succeeded')
"""
child = """
import socket, sys
with socket.socket(fileno=int(sys.argv[1])) as listener:
    listener.settimeout(2)
    with listener.accept()[0] as client:
        client.sendall(b'ok')
"""
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as manager:
    assert manager.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
    assert manager.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT) == 0
    manager.bind(('127.0.0.1', 0))
    port = manager.getsockname()[1]
    assert port != 8000
    manager.listen(4)
    attempts = 0
    def competitors():
        global attempts
        for host in ('127.0.0.1', '0.0.0.0'):
            for options in ((), ('SO_REUSEADDR',), ('SO_REUSEPORT',),
                            ('SO_REUSEADDR', 'SO_REUSEPORT')):
                subprocess.run([sys.executable, '-I', '-S', '-B', '-c', legacy,
                                host, str(port), *options], check=True,
                               close_fds=True, timeout=3)
                attempts += 1
    competitors()
    for _ in range(2):
        proc = subprocess.Popen([sys.executable, '-I', '-S', '-B', '-c', child,
                                 str(manager.fileno())], close_fds=True,
                                pass_fds=(manager.fileno(),))
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=2) as client:
                client.settimeout(2)
                received = b''
                while len(received) < 2:
                    part = client.recv(2 - len(received))
                    assert part
                    received += part
                assert received == b'ok'
            assert proc.wait(timeout=3) == 0
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=3)
        competitors()
print(json.dumps({'pid': os.getpid(), 'euid': os.geteuid(),
                  'restarts': 2, 'denied_binds': attempts, 'systemd': False}))
'''


def _drop():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)


@pytest.fixture
def sealed():
    # Called only by opt-in tests. Direct tempfile parent avoids pytest's private
    # ancestor directories masking artifact permissions during nonroot execution.
    # Fixed /tmp is root-owned 01777; arbitrary TMPDIR/pytest temp is untrusted.
    for ancestor, expected in ((Path('/'), 0o755), (Path('/tmp'), 0o1777)):
        node = ancestor.lstat()
        assert stat.S_ISDIR(node.st_mode) and node.st_uid == node.st_gid == 0
        assert stat.S_IMODE(node.st_mode) == expected
    with tempfile.TemporaryDirectory(prefix="homehub-TEST-ONLY-floor-", dir="/tmp") as name:
        root = Path(name)
        root.chmod(0o755)
        (root / "policy").mkdir(mode=0o700)
        (root / "artifacts").mkdir(mode=0o755)
        for path, mode in ((root, 0o755), (root / "policy", 0o700),
                           (root / "artifacts", 0o755)):
            os.chown(path, 0, 0)
            path.chmod(mode)
        # Local inert executable, never downloaded/built or run as root. Dynamic
        # loader/libraries are NOT sealed or claimed as trusted dependency closure.
        binary = Path("/usr/bin/id")
        if not binary.is_file():
            pytest.fail("required local /usr/bin/id missing; do not install tools")
        for selection in ("approved", "old"):
            artifact = root / "artifacts" / selection
            artifact.write_bytes(binary.read_bytes() + (b"old" if selection == "old" else b""))
            os.chown(artifact, 0, 0)
            artifact.chmod(0o555)
            record = {"epoch": 7 if selection == "approved" else 6, "generation": 2,
                      "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
            _write(root / "policy" / selection, record)
        _write(root / "policy/approval", json.loads((root / "policy/approved").read_text()))
        _write(root / "policy/floor", {"minimum_epoch": 7, "generation": 2})
        yield root


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    os.chown(path, 0, 0)
    path.chmod(0o400)


def _guard(root, selection):
    source = GUARD.replace("ROOT_LITERAL", repr(str(root))).replace(
        "SELECTION_LITERAL", repr(selection))
    return _session([sys.executable, "-I", "-S", "-B", "-c", source], 6)


def _session(argv, timeout):
    """Bound and reap a test-controlled Linux process session, including children."""
    proc = subprocess.Popen(argv, start_new_session=True, close_fds=True,
                            env={"LC_ALL": "C"}, cwd="/",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        output, errors = proc.communicate(timeout=timeout)
    except BaseException:
        # Before reaping the session leader, kill its group on timeout/interruption.
        # A successful namespace PID1 exit already kills namespace descendants.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate(timeout=5)
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, output, errors)


def test_inert_source_and_child_compilation():
    for source in (GUARD, NONROOT_WRITES, PID1):
        tree = ast.parse(source)
        compile(tree, "<test-only-child>", "exec")
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if any(isinstance(t, ast.Name) and t.id in {"legacy", "child"}
                       for t in node.targets):
                    compile(node.value.value, "<nested-test-child>", "exec")
    production = Path(__file__).resolve().parents[1] / "backend"
    assert not any("test_disposable_root_pid1_floor" in path.read_text(encoding="utf-8")
                   for path in production.rglob("*.py"))
    assert "HOMEHUB_DISPOSABLE_ROOT_PID1_TESTS" not in GUARD
    assert "shell=True" not in GUARD + PID1
    assert "systemctl" not in GUARD + PID1


@OPT_IN
def test_nonroot_cannot_modify_floor_or_sealed_executable(sealed):
    paths = [sealed / "policy/floor", sealed / "artifacts/approved"]
    before = [p.read_bytes() for p in paths]
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", NONROOT_WRITES,
                             *map(str, paths)], preexec_fn=_drop, env={"LC_ALL": "C"},
                            cwd="/", close_fds=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert [p.read_bytes() for p in paths] == before


CASES = (
    "approved", "old", "old-epoch", "spoofed-sha", "stale-floor", "stale-generation",
    "missing-floor", "writable-floor", "writable-artifact", "untrusted-artifact",
    "tamper", "symlink", "hardlink", "boolean-epoch", "missing-approval",
    "approved-below-floor", "approved-stale-generation", "approved-boolean-epoch",
)


@OPT_IN
@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("case", CASES)
def test_synthetic_guarded_surfaces(sealed, surface, case):
    # Labels assert one shared synthetic choke point; NOT installed integrations.
    assert surface in SURFACES
    floor = sealed / "policy/floor"
    candidate = sealed / "policy/approved"
    artifact = sealed / "artifacts/approved"
    if case in {"approved-below-floor", "approved-stale-generation", "approved-boolean-epoch"}:
        record = json.loads(candidate.read_text())
        key, value = {"approved-below-floor": ("epoch", 6),
                      "approved-stale-generation": ("generation", 1),
                      "approved-boolean-epoch": ("epoch", True)}[case]
        record[key] = value
        _write(candidate, record)
        _write(sealed / "policy/approval", record)
    elif case in {"old-epoch", "spoofed-sha", "stale-generation", "boolean-epoch"}:
        record = json.loads(candidate.read_text())
        key, value = {"old-epoch": ("epoch", 6), "spoofed-sha": ("sha256", "0" * 64),
                      "stale-generation": ("generation", 1),
                      "boolean-epoch": ("epoch", True)}[case]
        record[key] = value
        _write(candidate, record)
    elif case == "stale-floor":
        _write(floor, {"minimum_epoch": 6, "generation": 1})
    elif case == "missing-floor":
        floor.unlink()
    elif case == "missing-approval":
        (sealed / "policy/approval").unlink()
    elif case == "writable-floor":
        floor.chmod(0o600)
    elif case == "writable-artifact":
        artifact.chmod(0o755)
    elif case == "untrusted-artifact":
        os.chown(artifact, 65534, 65534)
    elif case == "tamper":
        artifact.write_bytes(artifact.read_bytes() + b"tampered")
    elif case == "symlink":
        artifact.unlink()
        artifact.symlink_to(sealed / "artifacts/old")
    elif case == "hardlink":
        os.link(artifact, sealed / "artifacts/extra-link")
    result = _guard(sealed, "old" if case == "old" else "approved")
    if case == "approved":
        assert result.returncode == 0 and result.stdout == "EXECUTED uid=65534\n", result
    else:
        assert result.returncode == 23 and result.stdout == "DENIED\n", result


@OPT_IN
def test_user_namespace_pid1_holds_socket_across_restarts():
    unshare = shutil.which("unshare")
    if not unshare:
        pytest.skip("user/PID namespace unavailable: local unshare missing; no PID1 acceptance")
    # Separate preflight: only namespace availability may skip. Mechanism errors
    # after a successful probe must fail, never become optimistic acceptance.
    probe = _session([unshare, "-Urmpf", sys.executable, "-I", "-S", "-B", "-c",
                      "import os; assert os.getpid()==1 and os.geteuid()==0"], 5)
    if probe.returncode:
        diagnostics = probe.stderr.strip()
        known = {
            'unshare: unshare failed: Operation not permitted',
            'unshare: unshare failed: Invalid argument',
            'unshare: unshare failed: Permission denied',
        }
        if probe.returncode == 1 and diagnostics in known:
            pytest.skip('user/PID namespace unavailable: ' + diagnostics)
        pytest.fail(f'PID1 probe failed unexpectedly: exit={probe.returncode}, '
                    f'stderr={diagnostics[:250]!r}')
    result = _session([unshare, "-Urmpf", sys.executable, "-I", "-S", "-B", "-c", PID1], 45)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"pid": 1, "euid": 0, "restarts": 2,
                                        "denied_binds": 24, "systemd": False}
